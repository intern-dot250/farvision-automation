from collections import Counter

from app.services import account_head_resolver


def _row(account_head: str, parent_account_head: str) -> dict:
    return {"Account Head": account_head, "Parent Account Head": parent_account_head}


# --- dedupe_candidates ---


def test_dedupe_candidates_collapses_identical_pairs():
    rows = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("rajesh kumar", "sundry creditors - other"),  # case-insensitive duplicate
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
    ]
    deduped = account_head_resolver.dedupe_candidates(rows)
    assert len(deduped) == 2


# --- dropdown_targets ---
# Account Head is the only field ever offered as a dropdown - Parent
# Account Head is never independently pickable, since the two are a fixed
# pair in Master and letting someone choose Parent Account Head on its own
# can produce a combination that doesn't correspond to any real Master row.


def test_dropdown_targets_synthesizes_combined_labels_when_account_head_text_is_identical():
    # Real-data shape: same Account Head text, different Parent Account Head
    # - each option must still uniquely identify the real underlying row.
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
    ]
    targets = account_head_resolver.dropdown_targets(candidates)
    assert set(targets.keys()) == {"Account Head"}
    assert set(targets["Account Head"]) == {
        "RAJESH KUMAR (SUNDRY CREDITORS - OTHER)",
        "RAJESH KUMAR (GENERAL CATEGORY-FLATS)",
    }


def test_dropdown_targets_uses_real_account_head_values_when_they_differ():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH K. SHARMA", "GENERAL CATEGORY-FLATS"),
    ]
    targets = account_head_resolver.dropdown_targets(candidates)
    assert set(targets.keys()) == {"Account Head"}
    assert set(targets["Account Head"]) == {"RAJESH KUMAR", "RAJESH K. SHARMA"}


def test_dropdown_targets_never_returns_parent_account_head():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
        _row("RAJESH K SHARMA", "ADVANCE FROM CUSTOMER (INVESTOR)"),
    ]
    targets = account_head_resolver.dropdown_targets(candidates)
    assert "Parent Account Head" not in targets


def test_dropdown_targets_empty_for_single_candidate():
    assert account_head_resolver.dropdown_targets([_row("MUKESH KUMAR", "SUNDRY CREDITORS - CONTRACTORS")]) == {}


def test_dropdown_targets_empty_when_nothing_distinguishes_candidates():
    # Both Account Head and Parent Account Head identical - dedupe_candidates
    # would already have collapsed this in practice, but dropdown_targets
    # itself must also degrade safely to "nothing to pick".
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
    ]
    assert account_head_resolver.dropdown_targets(candidates) == {}


def test_dropdown_targets_includes_a_candidate_with_blank_parent_account_head():
    # "Imprest"-style case: one of the duplicate Master rows has no Parent
    # Account Head at all - it must still be a selectable dropdown option,
    # not silently dropped.
    candidates = [
        _row("IMPREST", "SITE IMPREST"),
        _row("IMPREST", ""),
    ]
    targets = account_head_resolver.dropdown_targets(candidates)
    assert set(targets["Account Head"]) == {
        "IMPREST (SITE IMPREST)",
        f"IMPREST ({account_head_resolver.NO_PARENT_HEAD_LABEL})",
    }


# --- uses_synthesized_labels ---


def test_uses_synthesized_labels_true_when_account_head_text_is_identical():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
    ]
    assert account_head_resolver.uses_synthesized_labels(candidates) is True


def test_uses_synthesized_labels_false_when_account_head_text_differs():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH K. SHARMA", "GENERAL CATEGORY-FLATS"),
    ]
    assert account_head_resolver.uses_synthesized_labels(candidates) is False


def test_uses_synthesized_labels_false_for_single_candidate():
    assert account_head_resolver.uses_synthesized_labels([_row("MUKESH KUMAR", "SUNDRY CREDITORS")]) is False


# --- resolve(): the 7 required scenarios ---


def test_1_unique_match_is_unchanged():
    candidates = [_row("MUKESH KUMAR", "SUNDRY CREDITORS - CONTRACTORS")]
    result = account_head_resolver.resolve("MUKESH KUMAR", "DPL", candidates)
    assert result.ambiguous is False
    assert result.row == candidates[0]
    assert result.reason == "unique_match"


def test_2_two_candidates_no_signal_is_ambiguous_not_first_row():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
    ]
    result = account_head_resolver.resolve("RAJESH KUMAR", "DPL", candidates)
    assert result.ambiguous is True
    assert result.reason == "no_confident_signal"
    assert len(result.candidates) == 2
    targets = account_head_resolver.dropdown_targets(result.candidates)
    assert targets["Account Head"] == [
        "RAJESH KUMAR (SUNDRY CREDITORS - OTHER)", "RAJESH KUMAR (GENERAL CATEGORY-FLATS)",
    ]


def test_3_narration_context_clearly_favors_one_candidate():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "ADVANCE FROM CUSTOMER (INVESTOR)"),
    ]
    result = account_head_resolver.resolve(
        "RAJESH KUMAR", "DPL", candidates, context_text="Purpose: Investor advance refund"
    )
    assert result.ambiguous is False
    assert result.reason == "narration_context_match"
    assert result.row["Parent Account Head"] == "ADVANCE FROM CUSTOMER (INVESTOR)"


def test_4_no_clear_signal_is_flagged_not_random():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
        _row("RAJESH KUMAR", "ADVANCE FROM CUSTOMER (INVESTOR)"),
    ]
    result = account_head_resolver.resolve(
        "RAJESH KUMAR", "DPL", candidates, context_text="Payment for services rendered"
    )
    assert result.ambiguous is True
    assert result.confidence == 0.0


def test_5_and_6_dpl_amb_regression_not_affected_by_single_candidate():
    # Unique-match rows for either company must still auto-assign unchanged
    # - this module doesn't itself do company filtering (find_party_candidates
    # does), so a single passed-in candidate is always a unique match
    # regardless of which company it came from.
    dpl_candidates = [_row("SOME VENDOR", "SUNDRY CREDITORS - OTHER")]
    amb_candidates = [_row("SOME VENDOR", "SUNDRY CREDITORS - AMB SPECIFIC")]
    dpl_result = account_head_resolver.resolve("SOME VENDOR", "DPL", dpl_candidates)
    amb_result = account_head_resolver.resolve("SOME VENDOR", "AMB", amb_candidates)
    assert dpl_result.ambiguous is False
    assert amb_result.ambiguous is False
    assert dpl_result.row["Parent Account Head"] == "SUNDRY CREDITORS - OTHER"
    assert amb_result.row["Parent Account Head"] == "SUNDRY CREDITORS - AMB SPECIFIC"


def test_7_history_split_across_heads_falls_through_instead_of_forcing_one():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
    ]
    history = {
        "RAJESH KUMAR": Counter({
            ("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"): 4,
            ("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"): 4,
        })
    }
    result = account_head_resolver.resolve("RAJESH KUMAR", "DPL", candidates, history=history)
    assert result.ambiguous is True


def test_history_majority_wins_when_not_tied():
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"),
    ]
    history = {
        "RAJESH KUMAR": Counter({
            ("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"): 9,
            ("RAJESH KUMAR", "GENERAL CATEGORY-FLATS"): 1,
        })
    }
    result = account_head_resolver.resolve("RAJESH KUMAR", "DPL", candidates, history=history)
    assert result.ambiguous is False
    assert result.reason == "historical_majority"
    assert result.row["Parent Account Head"] == "SUNDRY CREDITORS - OTHER"


def test_no_candidates_returns_no_match_not_ambiguous():
    result = account_head_resolver.resolve("UNKNOWN PAYEE", "DPL", [])
    assert result.row is None
    assert result.ambiguous is False
    assert result.reason == "no_match"


def test_same_beneficiary_can_legitimately_resolve_to_different_heads_across_transactions():
    # Two different transactions for the same ambiguous beneficiary, with
    # different narration context, must be allowed to resolve differently -
    # a beneficiary is not forced to always map to one head.
    candidates = [
        _row("RAJESH KUMAR", "SUNDRY CREDITORS - OTHER"),
        _row("RAJESH KUMAR", "ADVANCE FROM CUSTOMER (INVESTOR)"),
    ]
    result_a = account_head_resolver.resolve(
        "RAJESH KUMAR", "DPL", candidates, context_text="Purpose: Investor advance refund"
    )
    result_b = account_head_resolver.resolve(
        "RAJESH KUMAR", "DPL", candidates, context_text="Purpose: Sundry creditor settlement"
    )
    assert result_a.row["Parent Account Head"] == "ADVANCE FROM CUSTOMER (INVESTOR)"
    assert result_b.row["Parent Account Head"] == "SUNDRY CREDITORS - OTHER"
