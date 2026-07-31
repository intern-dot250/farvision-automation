"""Matching logic for Override Rules - deterministic, not fuzzy, matching the
project's established convention (see master_repository.py). Isolated from
override_rules_repository.py (Supabase access) so it can be unit-tested with
plain dicts and has zero knowledge of Supabase.
"""
from typing import Any

RuleIndex = dict[tuple[str, str], list[dict[str, Any]]]


def _normalize(value: str | None) -> str:
    return (value or "").strip().upper()


def build_rule_index(rules: list[dict[str, Any]]) -> RuleIndex:
    """Groups rules by (normalized Head, normalized Sheet Name) so a lookup
    for a given transaction only ever scans the rules that share its exact
    Head+Sheet combination, not the full rule set. Within a bucket, rules
    are kept in ascending `id` order so matching is deterministic (first
    rule created wins on a tie)."""
    index: RuleIndex = {}
    for rule in sorted(rules, key=lambda r: r.get("id") or 0):
        key = (_normalize(rule.get("head")), _normalize(rule.get("sheet_name")))
        index.setdefault(key, []).append(rule)
    return index


def find_override(
    description: str, head: str, source_sheet: str | None, rule_index: RuleIndex
) -> str | None:
    """Returns the overriding Account Head for this transaction, or None if
    no active rule matches. A rule matches when its Head and Sheet Name both
    match exactly (case-insensitive, trimmed) AND its description_keyword is
    found anywhere in the transaction's narration (case-insensitive,
    trimmed, substring/"contains" match, per the business requirement)."""
    bucket = rule_index.get((_normalize(head), _normalize(source_sheet)))
    if not bucket:
        return None

    haystack = (description or "").strip().upper()
    for rule in bucket:
        keyword = _normalize(rule.get("description_keyword"))
        if keyword and keyword in haystack:
            return rule.get("account_head")

    return None
