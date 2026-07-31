import re
from functools import lru_cache

import pandas as pd

from app.core.config import get_settings
from app.services import sheets_client

MASTER_WORKSHEET = "Master"
_LOOKUP_COLUMNS = ("Payee Name", "Account Head")

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


def _canonical(name: str) -> str:
    """A stricter equality form, checked only after the exact-normalized
    comparison fails: drops the standalone "PVT" token and removes all
    whitespace. Deterministic, well-known equivalences - not fuzzy matching:

    - "SN LTD" == "S N LTD" (spacing on initials, e.g. "D K PLYWOOD PVT LTD")
    - "X LTD" == "X PVT LTD" ("Limited" only maps to "Ltd" by
      _LEGAL_SUFFIX_REPLACEMENTS, without inserting "Pvt", so a bank
      narration saying "Prayag Polymers Limited" wouldn't otherwise match
      Master's "PRAYAG POLYMERS PVT LTD")
    """
    return re.sub(r"\s+", "", _STANDALONE_PVT_RE.sub("", name))


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

    df = _load_master_df()
    if "Bank Name" not in df.columns:
        return None

    # Extract trailing N digits from each Bank Name value and compare as strings
    bank_series = df["Bank Name"].astype(str)
    extracted = bank_series.apply(lambda v: _last_n_digits(v, len(suffix)))
    matches = df[extracted == suffix]
    if matches.empty:
        return None
    return str(matches.iloc[0]["Bank Name"])


@lru_cache
def _load_master_df() -> pd.DataFrame:
    settings = get_settings()
    records = sheets_client.read_all_records(settings.STATEMENT_MASTER_SHEET_ID, MASTER_WORKSHEET)
    return pd.DataFrame.from_records(records)


def find_party(payee_name: str | None) -> dict | None:
    """Look up a party in Master by Payee Name or Account Head, case/whitespace-insensitive.

    Returns the first matching row as a dict, or None if no party in Master
    matches — which is how "Internal" transactions with no IFSC still get a
    definitive non-match check against known parties.
    """
    if not payee_name:
        return None

    df = _load_master_df()
    key = _normalize(payee_name)
    canonical_key = _canonical(key)

    for column in _LOOKUP_COLUMNS:
        if column not in df.columns:
            continue
        normalized = df[column].astype(str).apply(_normalize)
        stripped = normalized.apply(_strip_master_suffix)
        canonical_normalized = normalized.apply(_canonical)
        canonical_stripped = stripped.apply(_canonical)
        match = df[
            (normalized == key)
            | (stripped == key)
            | (canonical_normalized == canonical_key)
            | (canonical_stripped == canonical_key)
        ]
        if not match.empty:
            return match.iloc[0].to_dict()

    return None


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
        normalized_column = df[column].astype(str).apply(_normalize)
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


def clear_cache() -> None:
    """Force the next lookup to re-fetch Master from Sheets (e.g. after edits)."""
    _load_master_df.cache_clear()
