import difflib
import re
from functools import lru_cache

import pandas as pd

from app.core.config import get_settings
from app.core.logger import logger
from app.services import sheets_client

MASTER_WORKSHEET = "Master"
_LOOKUP_COLUMNS = ("Payee Name", "Account Head")

# Minimum difflib.SequenceMatcher ratio for find_party_fuzzy() to accept a
# match - roughly a 1-2 character difference on a normal-length name (e.g.
# "WALFARE" vs "WELFARE"). Tight enough that genuinely different names
# ("S N LTD" vs "R N LTD") don't collide.
_FUZZY_MIN_RATIO = 0.92

# How close two fuzzy candidates' ratios need to be before they're treated
# as an ambiguous near-tie instead of one decisively winning - e.g. 94% vs
# 93% (a 0.01 gap) is too close to trust as a confident automatic pick.
_FUZZY_AMBIGUITY_MARGIN = 0.03

# Master's Payee Name often has a short employee/vendor code or tag appended
# after the plain name used in bank descriptions - e.g. "Ravi Vats(555)",
# "Ram Kishan (C)", "Rahul Kumar - CR0198 (AR)". Strip only that kind of
# trailing code (parenthesized, or dash-prefixed, short alphanumeric) so
# "Arvind" doesn't wrongly match an unrelated "ARVIND KUMAR GARG - CR0446
# (AR)", while "Ravi Vats" still matches "RAVI VATS(555)".
_MASTER_SUFFIX_RE = re.compile(r"((\s*-\s*[A-Z0-9]{1,10})|(\s*\([A-Z0-9]{1,10}\)))+$")

# Company-suffix naming conventions vary between the bank description and
# Master ("Pvt Ltd" vs "Private Limited", "&" vs "and") for the exact same
# company. These are deterministic, well-known abbreviation equivalences -
# not fuzzy matching - so they can't make two genuinely different companies
# compare equal.
_LEGAL_SUFFIX_REPLACEMENTS = (
    (re.compile(r"\bPRIVATE LIMITED\b"), "PVT LTD"),
    (re.compile(r"\bPRIVATE\b"), "PVT"),
    (re.compile(r"\bLIMITED\b"), "LTD"),
)


def _normalize(name: str) -> str:
    name = name.strip().upper().replace(".", "").replace(",", "")
    name = name.replace("&", "AND")
    for pattern, replacement in _LEGAL_SUFFIX_REPLACEMENTS:
        name = pattern.sub(replacement, name)
    return " ".join(name.split())


def _strip_master_suffix(name: str) -> str:
    return _MASTER_SUFFIX_RE.sub("", name).strip()


_STANDALONE_PVT_RE = re.compile(r"\bPVT\b")

# Master frequently prefixes a vendor's Account Head with "M/S " (Hindi/
# Indian-English "Messrs" convention, e.g. "M/S A N FILLING STATION") while
# the bank narration for the same vendor never includes it (confirmed: 47
# such rows in Master as of 2026-08). Anchored to the start only - "M/S" is
# always a prefix in this data, never a mid-name token, so this can't
# collide with an unrelated name that happens to contain those letters.
_STANDALONE_MS_PREFIX_RE = re.compile(r"^M/S\s+")


def _collapse_doubled_name(name: str) -> str:
    """Bank narrations occasionally repeat a beneficiary's name twice back
    to back (e.g. "Shokeen Shokeen") where Master lists it once ("Shokeen").
    Deterministic, not fuzzy: only collapses when the second half of the
    (space-separated) name is a byte-for-byte repeat of the first half -
    never a partial or approximate repeat, so "RAM KISHAN RAM KUMAR" is
    left untouched."""
    words = name.split()
    half = len(words) // 2
    if half and len(words) % 2 == 0 and words[:half] == words[half:]:
        return " ".join(words[:half])
    return name


def _canonical(name: str) -> str:
    """A stricter equality form, checked only after the exact-normalized
    comparison fails: drops the standalone "PVT" token, a leading "M/S "
    prefix, a doubled-name repeat, and all remaining whitespace.
    Deterministic, well-known equivalences - not fuzzy matching:

    - "SN LTD" == "S N LTD" (spacing on initials, e.g. "D K PLYWOOD PVT LTD")
    - "X LTD" == "X PVT LTD" ("Limited" only maps to "Ltd" by
      _LEGAL_SUFFIX_REPLACEMENTS, without inserting "Pvt", so a bank
      narration saying "Prayag Polymers Limited" wouldn't otherwise match
      Master's "PRAYAG POLYMERS PVT LTD")
    - "A N FILLING STATION" == "M/S A N FILLING STATION"
    - "SHOKEEN SHOKEEN" == "SHOKEEN"
    """
    name = _STANDALONE_PVT_RE.sub("", name)
    name = _STANDALONE_MS_PREFIX_RE.sub("", name)
    name = _collapse_doubled_name(name)
    return re.sub(r"\s+", "", name)


def _digits_only(value: str) -> str:
    """Strip every non-digit character from a string."""
    return re.sub(r"\D", "", value)


def _last_n_digits(value: str, n: int) -> str | None:
    """Return the last `n` digits in a string, or None if fewer than `n`
    digits are present. Non-digit characters are ignored."""
    digits = _digits_only(value)
    if len(digits) >= n:
        return digits[-n:]
    return None


# Known bank account suffixes (last 4 digits) mapped to which company's
# Master chart-of-accounts rows they belong to. Master mixes two companies'
# data (DPL and AMB) with many identically-named Account Head rows whose
# Parent Account Head genuinely differs between them - lookups must be
# scoped to the right company, not just "first match in sheet order wins".
# Extend this as more accounts (e.g. AMB's) are onboarded; unrecognized
# accounts default to "DPL", the only company currently processed.
_ACCOUNT_SUFFIX_COMPANY: dict[str, str] = {
    "2314": "DPL",
    "2457": "DPL",
    "2477": "DPL",
    "0490": "DPL",
    "0377": "DPL",
    "0264": "DPL",
}


def resolve_company(source_sheet: str | None, bank_name: str | None = None) -> str:
    """Which company's Master rows apply to a transaction, determined from
    its own bank account (short-form source tab name, e.g. "YES AH IDW
    2457", and/or narration-parsed bank name). Defaults to "DPL" when
    unrecognized - the only company currently processed."""
    if source_sheet:
        suffix = _last_n_digits(source_sheet, 4)
        if suffix and suffix in _ACCOUNT_SUFFIX_COMPANY:
            return _ACCOUNT_SUFFIX_COMPANY[suffix]
    text = f"{source_sheet or ''} {bank_name or ''}".upper()
    if "MAHARASHTRA" in text or "MAHARAS" in text:
        return "DPL"
    return "DPL"


@lru_cache
def _bank_name_suffix_index(n: int) -> dict[str, str]:
    """Precomputed {last-N-digit account suffix: full Bank Name}, built once
    per Master load (see _load_master_df) instead of re-scanning all of
    Master's Bank Name column on every find_bank_by_account_suffix() call -
    that per-call rescan (over 15k+ rows) was a major cost of a real-sized
    run. Keyed by n since a caller could in principle ask for a different
    suffix length, though both current callers always use 4."""
    df = _load_master_df()
    index: dict[str, str] = {}
    if "Bank Name" not in df.columns:
        return index
    for value in df["Bank Name"].astype(str):
        suffix = _last_n_digits(value, n)
        if suffix and suffix not in index:
            index[suffix] = value
    return index


def find_bank_by_account_suffix(suffix: str) -> str | None:
    """Find a Master row whose "Bank Name" contains an account number whose
    last N digits match `suffix`. Returns the full "Bank Name" value from
    Master, or None if no row matches.

    This resolves short-form source-tab names like "YES AH IDW 2457" to
    the full-form Master value "YES BANK AH IDW 045563400002457" by
    matching on the last-4-digit account-number suffix. Deterministic
    digit-only comparison — no fuzzy matching.
    """
    if not suffix or not suffix.isdigit() or len(suffix) < 4:
        return None

    return _bank_name_suffix_index(len(suffix)).get(suffix)


@lru_cache
def _load_master_df() -> pd.DataFrame:
    settings = get_settings()
    records = sheets_client.read_all_records(settings.STATEMENT_MASTER_SHEET_ID, MASTER_WORKSHEET)
    return pd.DataFrame.from_records(records)


@lru_cache
def _normalized_column(column: str) -> pd.Series | None:
    """Normalized version of a Master column, built once per Master load and
    reused across every lookup - see find_party/_category_rows, which used
    to rebuild this (a Python-level .apply() over 15k+ rows) on every call."""
    df = _load_master_df()
    if column not in df.columns:
        return None
    return df[column].astype(str).apply(_normalize)


@lru_cache
def _stripped_column(column: str) -> pd.Series | None:
    normalized = _normalized_column(column)
    if normalized is None:
        return None
    return normalized.apply(_strip_master_suffix)


@lru_cache
def _canonical_column(column: str) -> pd.Series | None:
    normalized = _normalized_column(column)
    if normalized is None:
        return None
    return normalized.apply(_canonical)


@lru_cache
def _canonical_stripped_column(column: str) -> pd.Series | None:
    stripped = _stripped_column(column)
    if stripped is None:
        return None
    return stripped.apply(_canonical)


def find_party(payee_name: str | None, company: str | None = "DPL") -> dict | None:
    """Look up a party in Master by Payee Name or Account Head, case/whitespace-insensitive.

    Returns the first matching row as a dict, or None if no party in Master
    matches — which is how "Internal" transactions with no IFSC still get a
    definitive non-match check against known parties. Falls back to
    find_party_fuzzy() (a narrow typo-only match) only when this exact/
    canonical lookup finds nothing at all.

    `company` (see resolve_company()) restricts matches to that company's
    own rows when Master has a "Company" column - Master mixes two
    companies' charts of accounts, and many identically-named Account Head
    rows have genuinely different Parent Account Head values between them.
    Fixture DataFrames with no "Company" column (every existing test) are
    unaffected - filtering only activates against real Master data.
    """
    if not payee_name:
        return None

    df = _load_master_df()
    key = _normalize(payee_name)
    canonical_key = _canonical(key)

    company_mask = None
    if company and "Company" in df.columns:
        company_mask = df["Company"].astype(str).str.strip().str.upper() == company.strip().upper()

    for column in _LOOKUP_COLUMNS:
        normalized = _normalized_column(column)
        if normalized is None:
            continue
        stripped = _stripped_column(column)
        canonical_normalized = _canonical_column(column)
        canonical_stripped = _canonical_stripped_column(column)
        match_mask = (
            (normalized == key)
            | (stripped == key)
            | (canonical_normalized == canonical_key)
            | (canonical_stripped == canonical_key)
        )
        if company_mask is not None:
            match_mask = match_mask & company_mask
        match = df[match_mask]
        if not match.empty:
            return match.iloc[0].to_dict()

    return find_party_fuzzy(payee_name, company=company)


def find_party_fuzzy_candidates(payee_name: str | None, company: str | None = "DPL") -> list[dict]:
    """Fuzzy typo match for a payee name against a real Master entry - e.g.
    "Aravali Height Resident Walfare Association" vs Master's "...WELFARE...".
    Only ever consulted after exact/canonical matching has already found
    nothing.

    Deliberately narrow, not a general fuzzy search: requires both a high
    similarity ratio (difflib.SequenceMatcher, >= _FUZZY_MIN_RATIO) AND the
    same word count (blocks a high ratio that's really just one name being a
    truncated/extended version of a genuinely different one).

    Instead of only refusing on an exact tie, returns every row within
    _FUZZY_AMBIGUITY_MARGIN of the best ratio - so a genuinely close call
    (e.g. 94% vs 93%, not just an exact 94.0% vs 94.0% tie) is surfaced as
    multiple ambiguous candidates rather than either silently auto-picking
    the marginally-higher one or refusing with no candidates at all for the
    caller to build a dropdown from. Never guesses: a close call is always
    someone's decision, per the same "never guess silently" principle
    account_head_resolver already follows for ambiguous Account Heads.

    Returns []: below threshold, no payee_name, or no candidate at all.
    Returns a single-element list: one row decisively better than the rest
    (outside the margin) - the unambiguous match.
    Returns 2+ rows: near-tied candidates within the margin - genuinely
    ambiguous, the caller must not auto-pick between them.
    """
    if not payee_name:
        return []

    df = _load_master_df()
    key = _normalize(payee_name)
    key_word_count = len(key.split())
    if key_word_count == 0:
        return []

    company_mask = None
    if company and "Company" in df.columns:
        company_mask = df["Company"].astype(str).str.strip().str.upper() == company.strip().upper()

    for column in _LOOKUP_COLUMNS:
        normalized = _normalized_column(column)
        if normalized is None:
            continue

        scored: list[tuple[float, int]] = []
        for idx, value in normalized.items():
            if company_mask is not None and not company_mask.loc[idx]:
                continue
            if not value or len(value.split()) != key_word_count:
                continue
            ratio = difflib.SequenceMatcher(None, key, value).ratio()
            if ratio >= _FUZZY_MIN_RATIO:
                scored.append((ratio, idx))

        if not scored:
            continue

        best_ratio = max(ratio for ratio, _ in scored)
        near_best = [(ratio, idx) for ratio, idx in scored if best_ratio - ratio <= _FUZZY_AMBIGUITY_MARGIN]
        rows = [df.loc[idx].to_dict() for _, idx in near_best]

        if len(rows) == 1:
            logger.info(
                f"[master_repository] fuzzy_match payee={payee_name!r} "
                f"matched={rows[0].get(column)!r} ratio={best_ratio:.3f}"
            )
        else:
            logger.info(
                f"[master_repository] fuzzy_match payee={payee_name!r} column={column!r} "
                f"AMBIGUOUS {len(rows)} candidates within {_FUZZY_AMBIGUITY_MARGIN} of best "
                f"ratio {best_ratio:.3f} - never guessing"
            )
        return rows

    return []


def find_party_fuzzy(payee_name: str | None, company: str | None = "DPL") -> dict | None:
    """Single-result fuzzy match, kept for callers (e.g. find_party()) that
    only ever want one row or nothing. Implemented on top of
    find_party_fuzzy_candidates() - returns that single row only when
    exactly one candidate exists (no genuinely close runner-up); returns
    None on a near-tie (including an exact tie, a margin of 0) or no match,
    the same "never guess" behavior this function always had.
    """
    candidates = find_party_fuzzy_candidates(payee_name, company=company)
    return candidates[0] if len(candidates) == 1 else None


def find_party_candidates(payee_name: str | None, company: str | None = "DPL") -> list[dict]:
    """Every Master row matching payee_name, instead of just the first -
    same Payee Name/Account Head column priority and company-scoping as
    find_party() (deliberately duplicated rather than shared, so find_party()
    itself stays byte-for-byte unchanged for its existing callers).

    Used to detect when a beneficiary name maps to more than one Master row
    with a genuinely different Account Head/Parent Account Head, so that
    ambiguity can be resolved (or flagged) instead of silently taking
    whichever row happens to come first in sheet order.
    """
    if not payee_name:
        return []

    df = _load_master_df()
    key = _normalize(payee_name)
    canonical_key = _canonical(key)

    company_mask = None
    if company and "Company" in df.columns:
        company_mask = df["Company"].astype(str).str.strip().str.upper() == company.strip().upper()

    for column in _LOOKUP_COLUMNS:
        normalized = _normalized_column(column)
        if normalized is None:
            continue
        stripped = _stripped_column(column)
        canonical_normalized = _canonical_column(column)
        canonical_stripped = _canonical_stripped_column(column)
        match_mask = (
            (normalized == key)
            | (stripped == key)
            | (canonical_normalized == canonical_key)
            | (canonical_stripped == canonical_key)
        )
        if company_mask is not None:
            match_mask = match_mask & company_mask
        match = df[match_mask]
        if not match.empty:
            return match.to_dict("records")

    # Uses the multi-candidate fuzzy fallback (not find_party_fuzzy()) so a
    # near-tied fuzzy match surfaces as a real ambiguous candidate list for
    # account_head_resolver to flag and dropdown, instead of silently
    # collapsing to "no match" the way a bare find_party_fuzzy() -> None
    # would.
    return find_party_fuzzy_candidates(payee_name, company=company)


def _category_rows(account_head: str | None, parent_account_head: str | None) -> pd.DataFrame:
    """Master rows sharing the given Account Head or Parent Account Head,
    restricted to rows that actually carry a Deduction Type + Description
    pair (the "category" rows). Deterministic exact-value lookup, not
    keyword/fuzzy matching. Tries Account Head first, then Parent Account
    Head; returns an empty frame if neither column exists or matches."""
    df = _load_master_df()
    if "Deduction Type" not in df.columns or "Description" not in df.columns:
        return df.iloc[0:0]

    has_data = (df["Deduction Type"].astype(str).str.strip() != "") & (
        df["Description"].astype(str).str.strip() != ""
    )

    for column, value in (("Account Head", account_head), ("Parent Account Head", parent_account_head)):
        if not value or column not in df.columns:
            continue
        key = _normalize(str(value))
        normalized_column = _normalized_column(column)
        if normalized_column is None:
            continue
        matches = df[has_data & (normalized_column == key)]
        if not matches.empty:
            return matches

    return df.iloc[0:0]


def find_description_for_head(
    account_head: str | None, parent_account_head: str | None, deduction_type: str
) -> str | None:
    """When a payee's own Master row has no Description for a specific
    Deduction Type (e.g. the "Goods and Service Tax" row of a Vendor
    payment), reuse the Description from another Master row that shares
    the same Account Head/Parent Account Head AND the same Deduction Type
    (e.g. many Vendor payees share Parent Account Head "SUNDRY CREDITORS -
    OTHER" and at least one already has a GST Description filled in).

    Matching on Deduction Type too prevents pulling in a Description meant
    for a different deduction (e.g. a TDS row's "TDS ON RENT PAID" text
    must never end up on a GST row just because they share an Account
    Head)."""
    matches = _category_rows(account_head, parent_account_head)
    if matches.empty:
        return None
    key = _normalize(deduction_type)
    same_type = matches[matches["Deduction Type"].astype(str).apply(_normalize) == key]
    if same_type.empty:
        return None
    return str(same_type.iloc[0]["Description"])


def find_deduction_for_head(
    account_head: str | None, parent_account_head: str | None
) -> tuple[str, str] | None:
    """Like find_description_for_head, but for heads with no predetermined
    Deduction Type (anything other than Contractor/Vendor): returns the
    (Deduction Type, Description) pair from another Master row sharing the
    same Account Head/Parent Account Head, so the two fields always come
    from the same row and stay consistent with each other."""
    matches = _category_rows(account_head, parent_account_head)
    if matches.empty:
        return None
    row = matches.iloc[0]
    return str(row["Deduction Type"]), str(row["Description"])


def list_tds_descriptions() -> list[str]:
    """Every distinct Description Master has on file for Deduction Type
    "Tax deducted at source" - the flat, always-current option list for the
    ImportTaxInfo Description dropdown (automation_engine.
    _attach_tax_info_description_dropdowns). Reads the same cached Master
    frame as every other lookup here, so a new TDS row in Master shows up
    next run with no code change. Not scoped to any Account Head/Parent
    Account Head - the dropdown offers every valid TDS description in
    Master, not just ones relevant to one payee."""
    df = _load_master_df()
    if "Deduction Type" not in df.columns or "Description" not in df.columns:
        return []
    key = _normalize("Tax deducted at source")
    matches = df[df["Deduction Type"].astype(str).apply(_normalize) == key]
    descriptions = {
        str(value).strip() for value in matches["Description"] if str(value).strip()
    }
    return sorted(descriptions)


def list_payees_by_parent_account_head(parent_account_head: str, company: str | None = "DPL") -> list[str]:
    """Every distinct Account Head value Master has on file for an exact
    Parent Account Head (e.g. every Salary payee, Parent Account Head ==
    "SALARY PAYABLE") - the option list for a category dropdown when a
    transaction's trusted head (e.g. "Salary Site") is known but no payee
    name could be extracted from the narration at all, so there's no name
    to look up candidates for in the first place. Company-scoped the same
    way as find_party/find_party_candidates - Master mixes two companies'
    charts of accounts under the same Parent Account Head values."""
    df = _load_master_df()
    if "Account Head" not in df.columns or "Parent Account Head" not in df.columns:
        return []

    company_mask = None
    if company and "Company" in df.columns:
        company_mask = df["Company"].astype(str).str.strip().str.upper() == company.strip().upper()

    key = _normalize(parent_account_head)
    normalized_parent = _normalized_column("Parent Account Head")
    if normalized_parent is None:
        return []
    match_mask = normalized_parent == key
    if company_mask is not None:
        match_mask = match_mask & company_mask

    matches = df[match_mask]
    payees = {str(value).strip() for value in matches["Account Head"] if str(value).strip()}
    return sorted(payees)


def clear_cache() -> None:
    """Force the next lookup to re-fetch Master from Sheets (e.g. after edits)."""
    _load_master_df.cache_clear()
    _normalized_column.cache_clear()
    _stripped_column.cache_clear()
    _canonical_column.cache_clear()
    _canonical_stripped_column.cache_clear()
    _bank_name_suffix_index.cache_clear()
