from app.services.override_rules import build_rule_index, find_override


def _rule(id, keyword, head, sheet, account_head, is_active=True):
    return {
        "id": id,
        "description_keyword": keyword,
        "head": head,
        "sheet_name": sheet,
        "account_head": account_head,
        "is_active": is_active,
    }


def test_find_override_matches_case_insensitive_contains():
    rules = [_rule(1, "Ravi Vats", "Imprest", "YES AH IDW 2457", "Ravi Vats(555)")]
    index = build_rule_index(rules)

    result = find_override(
        "YIB-NEFT-YESME61620064305-Ravi Vats-UBIN0567370-Imprest-UNION BANK OF INDIA",
        "Imprest",
        "YES AH IDW 2457",
        index,
    )

    assert result == "Ravi Vats(555)"


def test_find_override_is_case_insensitive_and_trims_whitespace():
    rules = [_rule(1, "  ravi vats  ", "  Imprest  ", "  YES AH IDW 2457  ", "Ravi Vats(555)")]
    index = build_rule_index(rules)

    result = find_override(
        "some narration mentioning RAVI VATS here",
        "imprest",
        "yes ah idw 2457",
        index,
    )

    assert result == "Ravi Vats(555)"


def test_find_override_returns_none_when_head_does_not_match():
    rules = [_rule(1, "Ravi Vats", "Imprest", "YES AH IDW 2457", "Ravi Vats(555)")]
    index = build_rule_index(rules)

    result = find_override(
        "narration with Ravi Vats",
        "Vendor",
        "YES AH IDW 2457",
        index,
    )

    assert result is None


def test_find_override_returns_none_when_sheet_does_not_match():
    rules = [_rule(1, "Ravi Vats", "Imprest", "YES AH IDW 2457", "Ravi Vats(555)")]
    index = build_rule_index(rules)

    result = find_override(
        "narration with Ravi Vats",
        "Imprest",
        "YES Rera 0377",
        index,
    )

    assert result is None


def test_find_override_returns_none_when_keyword_not_in_description():
    rules = [_rule(1, "Ravi Vats", "Imprest", "YES AH IDW 2457", "Ravi Vats(555)")]
    index = build_rule_index(rules)

    result = find_override(
        "narration about a totally different payee",
        "Imprest",
        "YES AH IDW 2457",
        index,
    )

    assert result is None


def test_find_override_ignores_inactive_rules():
    # Inactive rules must never even reach the index - list_active() (the
    # repository call feeding build_rule_index in production) already
    # filters them out, so an inactive rule here proves it was never passed in.
    rules = [_rule(1, "Ravi Vats", "Imprest", "YES AH IDW 2457", "Ravi Vats(555)", is_active=False)]
    index = build_rule_index([r for r in rules if r["is_active"]])

    result = find_override(
        "narration with Ravi Vats",
        "Imprest",
        "YES AH IDW 2457",
        index,
    )

    assert result is None


def test_find_override_first_match_wins_deterministically():
    rules = [
        _rule(2, "Vats", "Imprest", "YES AH IDW 2457", "Second Rule Account Head"),
        _rule(1, "Vats", "Imprest", "YES AH IDW 2457", "First Rule Account Head"),
    ]
    index = build_rule_index(rules)

    result = find_override(
        "narration with Ravi Vats",
        "Imprest",
        "YES AH IDW 2457",
        index,
    )

    assert result == "First Rule Account Head"


def test_find_override_returns_none_for_empty_rule_index():
    result = find_override("any narration", "Vendor", "YES AH IDW 2457", {})

    assert result is None


def test_find_override_handles_none_source_sheet():
    rules = [_rule(1, "Ravi Vats", "Imprest", "YES AH IDW 2457", "Ravi Vats(555)")]
    index = build_rule_index(rules)

    result = find_override("narration with Ravi Vats", "Imprest", None, index)

    assert result is None


def test_build_rule_index_separates_different_head_sheet_buckets():
    rules = [
        _rule(1, "Vats", "Imprest", "YES AH IDW 2457", "AccountHeadA"),
        _rule(2, "Vats", "Vendor", "YES AH IDW 2457", "AccountHeadB"),
        _rule(3, "Vats", "Imprest", "YES Rera 0377", "AccountHeadC"),
    ]
    index = build_rule_index(rules)

    assert len(index) == 3
    assert find_override("Vats", "Imprest", "YES AH IDW 2457", index) == "AccountHeadA"
    assert find_override("Vats", "Vendor", "YES AH IDW 2457", index) == "AccountHeadB"
    assert find_override("Vats", "Imprest", "YES Rera 0377", index) == "AccountHeadC"
