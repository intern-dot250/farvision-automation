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


def clear_cache() -> None:
    """Force the next lookup to re-fetch Master from Sheets (e.g. after edits)."""
    _load_master_df.cache_clear()
