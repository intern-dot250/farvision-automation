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

    for column in _LOOKUP_COLUMNS:
        if column not in df.columns:
            continue
        normalized = df[column].astype(str).apply(_normalize)
        stripped = normalized.apply(_strip_master_suffix)
        match = df[(normalized == key) | (stripped == key)]
        if not match.empty:
            return match.iloc[0].to_dict()

    return None


def clear_cache() -> None:
    """Force the next lookup to re-fetch Master from Sheets (e.g. after edits)."""
    _load_master_df.cache_clear()
