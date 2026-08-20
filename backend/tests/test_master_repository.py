import pandas as pd

from app.services import master_repository
from app.services.master_repository import (
    _canonical,
    _digits_only,
    _last_n_digits,
    _normalize,
    _strip_master_suffix,
    find_bank_by_account_suffix,
)


def test_digits_only_strips_non_digits():
    assert _digits_only("YES BANK AH IDW 045563400002457") == "045563400002457"
    assert _digits_only("") == ""


def test_last_n_digits_returns_trailing_n():
    assert _last_n_digits("YES BANK AH IDW 045563400002457", 4) == "2457"
    assert _last_n_digits("045563400002457", 4) == "2457"
    assert _last_n_digits("2457", 4) == "2457"


def test_last_n_digits_returns_none_when_fewer_than_n_digits():
    assert _last_n_digits("", 4) is None
    assert _last_n_digits("abc", 4) is None
    assert _last_n_digits("123", 4) is None


def test_last_n_digits_ignores_non_digit_chars():
    assert _last_n_digits("IDW - 2457 (active)", 4) == "2457"


def test_find_bank_by_account_suffix_matches_last_4_digits(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "YES BANK AH IDW", "Account Head": "Contractor", "Bank Name": "YES BANK AH IDW 045563400002457"},
            {"Payee Name": "ICICI BANK LTD", "Account Head": "Vendor", "Bank Name": "ICICI BANK LTD 000123456789"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert find_bank_by_account_suffix("2457") == "YES BANK AH IDW 045563400002457"
    assert find_bank_by_account_suffix("6789") == "ICICI BANK LTD 000123456789"


def test_find_bank_by_account_suffix_no_match_returns_none(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "YES BANK AH IDW", "Account Head": "Contractor", "Bank Name": "YES BANK AH IDW 045563400002457"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert find_bank_by_account_suffix("9999") is None


def test_find_bank_by_account_suffix_handles_short_accounts(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "MINI", "Account Head": "Contractor", "Bank Name": "MINI 123"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    # "123" has fewer than 4 digits — skipped, no match
    assert find_bank_by_account_suffix("123") is None
    assert find_bank_by_account_suffix("") is None


def test_find_bank_by_account_suffix_empty_bank_name_column(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "YES BANK AH IDW", "Account Head": "Contractor"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert find_bank_by_account_suffix("2457") is None


def test_strips_paren_code_suffix():
    assert _strip_master_suffix("RAVI VATS(555)") == "RAVI VATS"


def test_strips_space_paren_letter_code():
    assert _strip_master_suffix("RAM KISHAN (C)") == "RAM KISHAN"


def test_strips_dash_and_paren_combo():
    assert _strip_master_suffix("RAHUL KUMAR - CR0198 (AR)") == "RAHUL KUMAR"


def test_no_suffix_is_unchanged():
    assert _strip_master_suffix("SAHIL YADAV") == "SAHIL YADAV"


def test_does_not_strip_real_name_words():
    # "Arvind" must not match this - stripping should leave the real name
    # words ("KUMAR GARG") intact, not just chop to the first word.
    assert _strip_master_suffix("ARVIND KUMAR GARG - CR0446 (AR)") == "ARVIND KUMAR GARG"


def test_normalize_equates_pvt_ltd_and_private_limited():
    assert _normalize("Awesome Paint Planners Pvt Ltd") == _normalize(
        "AWESOME PAINT PLANNERS PRIVATE LIMITED"
    )


def test_normalize_equates_ampersand_and_and():
    assert _normalize("Gupta Paint and Chemical") == _normalize("Gupta Paint & Chemical")


def test_normalize_strips_periods_in_pvt_ltd():
    assert _normalize("XYZ Pvt. Ltd.") == _normalize("XYZ PVT LTD")


def test_normalize_does_not_merge_unrelated_names():
    assert _normalize("Awesome Paint Planners Pvt Ltd") != _normalize(
        "Awesome Paint Traders Private Limited"
    )


def test_canonical_equates_spaced_and_unspaced_initials():
    assert _canonical(_normalize("SN LTD")) == _canonical(_normalize("S N LTD"))
    assert _canonical(_normalize("DK Plywood Pvt Ltd")) == _canonical(_normalize("D K PLYWOOD PVT LTD"))


def test_canonical_equates_ltd_and_pvt_ltd():
    assert _canonical(_normalize("Prayag Polymers Limited")) == _canonical(_normalize("PRAYAG POLYMERS PVT LTD"))


def test_canonical_does_not_merge_unrelated_names():
    assert _canonical(_normalize("SN LTD")) != _canonical(_normalize("RN LTD"))


def test_find_party_matches_via_canonical_form(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "S N LTD", "Account Head": "S N LTD"},
            {"Payee Name": "D K PLYWOOD PVT LTD", "Account Head": "D K PLYWOOD PVT LTD"},
            {"Payee Name": "PRAYAG POLYMERS PVT LTD", "Account Head": "PRAYAG POLYMERS PVT LTD"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party("SN Ltd")["Payee Name"] == "S N LTD"
    assert master_repository.find_party("DK Plywood Pvt Ltd")["Payee Name"] == "D K PLYWOOD PVT LTD"
    assert master_repository.find_party("Prayag Polymers Limited")["Payee Name"] == "PRAYAG POLYMERS PVT LTD"
    assert master_repository.find_party("Totally Unrelated Company") is None


def test_resolve_company_matches_known_dpl_account_suffixes():
    for suffix in ("2314", "2457", "2477", "0490", "0377", "0264"):
        assert master_repository.resolve_company(f"YES AH IDW {suffix}") == "DPL"


def test_resolve_company_matches_bank_of_maharashtra_by_name():
    assert master_repository.resolve_company("Some Tab", "BANK OF MAHARASHTRA") == "DPL"
    assert master_repository.resolve_company("BANK OF MAHARAS 1234") == "DPL"


def test_resolve_company_defaults_to_dpl_when_unrecognized():
    assert master_repository.resolve_company("Some Unknown Tab 9999") == "DPL"
    assert master_repository.resolve_company(None) == "DPL"


def test_find_party_scopes_by_company_when_master_has_conflicting_duplicates(monkeypatch):
    # Master mixes DPL and AMB rows - same Account Head name, genuinely
    # different Parent Account Head. Reproduces a real conflict found in
    # production Master data.
    df = pd.DataFrame.from_records(
        [
            {"Company": "DPL", "Payee Name": "ANITA DEVI", "Account Head": "ANITA DEVI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
            {"Company": "AMB", "Payee Name": "ANITA DEVI", "Account Head": "ANITA DEVI", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    dpl_match = master_repository.find_party("ANITA DEVI", company="DPL")
    amb_match = master_repository.find_party("ANITA DEVI", company="AMB")

    assert dpl_match["Parent Account Head"] == "SUNDRY CREDITORS - CONTRACTORS"
    assert amb_match["Parent Account Head"] == "SUNDRY CREDITORS - OTHER"


def test_find_party_company_filter_returns_none_when_only_other_company_matches(monkeypatch):
    df = pd.DataFrame.from_records(
        [{"Company": "AMB", "Payee Name": "SOME VENDOR", "Account Head": "SOME VENDOR", "Parent Account Head": "X"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party("SOME VENDOR", company="DPL") is None
    assert master_repository.find_party("SOME VENDOR", company="AMB") is not None


def test_find_party_ignores_company_filter_when_no_company_column(monkeypatch):
    # Existing fixtures (and older/simpler Master exports) with no
    # "Company" column at all must be unaffected by the default company="DPL".
    df = pd.DataFrame.from_records(
        [{"Payee Name": "SOME VENDOR", "Account Head": "SOME VENDOR", "Parent Account Head": "X"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party("SOME VENDOR")["Parent Account Head"] == "X"


def test_find_description_for_head_reuses_description_from_same_parent_account_head(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {
                "Payee Name": "MUKESH KUMAR",
                "Account Head": "MUKESH KUMAR",
                "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS",
                "Deduction Type": "Goods and Service Tax",
                "Description": "TDS ON CONTRACTORS",
            },
            {
                "Payee Name": "NAVEEN YADAV",
                "Account Head": "NAVEEN YADAV",
                "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS",
                "Deduction Type": "",
                "Description": "",
            },
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_description_for_head(
        "NAVEEN YADAV", "SUNDRY CREDITORS - CONTRACTORS", "Goods and Service Tax"
    )

    assert result == "TDS ON CONTRACTORS"


def test_find_description_for_head_falls_back_to_account_head_match(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {
                "Payee Name": "A",
                "Account Head": "RENT PAYABLE",
                "Parent Account Head": "",
                "Deduction Type": "Tax deducted at source",
                "Description": "TDS ON RENT PAID",
            },
            {
                "Payee Name": "B",
                "Account Head": "RENT PAYABLE",
                "Parent Account Head": "",
                "Deduction Type": "",
                "Description": "",
            },
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_description_for_head("RENT PAYABLE", "", "Tax deducted at source")

    assert result == "TDS ON RENT PAID"


def test_find_description_for_head_returns_none_when_no_category_match(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {
                "Payee Name": "A",
                "Account Head": "A",
                "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS",
                "Deduction Type": "Tax deducted at source",
                "Description": "TDS ON CONTRACTORS",
            },
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_description_for_head(
        "UNRELATED", "SUNDRY DEBTORS - OTHERS", "Tax deducted at source"
    )

    assert result is None


def test_find_description_for_head_does_not_mix_deduction_types(monkeypatch):
    # A category row that matches on Account Head but has a DIFFERENT
    # Deduction Type must not be used - "TDS ON RENT PAID" (a TDS row) must
    # never be returned for a GST lookup just because they share an
    # Account Head.
    df = pd.DataFrame.from_records(
        [
            {
                "Payee Name": "A",
                "Account Head": "RENT PAYABLE",
                "Parent Account Head": "",
                "Deduction Type": "Tax deducted at source",
                "Description": "TDS ON RENT PAID",
            },
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_description_for_head("RENT PAYABLE", "", "Goods and Service Tax")

    assert result is None


def test_find_deduction_for_head_returns_paired_deduction_type_and_description(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {
                "Payee Name": "A",
                "Account Head": "SALARY PAYABLE",
                "Parent Account Head": "",
                "Deduction Type": "Tax deducted at source",
                "Description": "TDS ON SALARY",
            },
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_deduction_for_head("SALARY PAYABLE", "")

    assert result == ("Tax deducted at source", "TDS ON SALARY")


def test_list_tds_descriptions_returns_sorted_deduped_descriptions(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Account Head": "A", "Deduction Type": "Tax deducted at source", "Description": "TDS ON CONTRACTORS"},
            {"Account Head": "B", "Deduction Type": "Tax deducted at source", "Description": "TDS ON RENT PAID"},
            {"Account Head": "C", "Deduction Type": "Tax deducted at source", "Description": "TDS ON CONTRACTORS"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.list_tds_descriptions()

    assert result == ["TDS ON CONTRACTORS", "TDS ON RENT PAID"]


def test_list_tds_descriptions_ignores_other_deduction_types_and_blank_descriptions(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Account Head": "A", "Deduction Type": "Tax deducted at source", "Description": "TDS ON SALARY"},
            {"Account Head": "B", "Deduction Type": "Goods and Service Tax", "Description": "GST ON VENDOR"},
            {"Account Head": "C", "Deduction Type": "Tax deducted at source", "Description": ""},
            {"Account Head": "D", "Deduction Type": "", "Description": ""},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.list_tds_descriptions()

    assert result == ["TDS ON SALARY"]


def test_list_tds_descriptions_is_case_insensitive_on_deduction_type(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Account Head": "A", "Deduction Type": "tax deducted at source", "Description": "TDS ON BROKERAGE COMMISSION"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.list_tds_descriptions()

    assert result == ["TDS ON BROKERAGE COMMISSION"]


def test_list_tds_descriptions_returns_empty_list_when_columns_missing(monkeypatch):
    df = pd.DataFrame.from_records([{"Account Head": "A"}])
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.list_tds_descriptions() == []


def test_list_payees_by_parent_account_head_returns_sorted_deduped_payees(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Company": "DPL", "Account Head": "Bharat Singh(406)", "Parent Account Head": "SALARY PAYABLE"},
            {"Company": "DPL", "Account Head": "Ashish Gaur(157)", "Parent Account Head": "SALARY PAYABLE"},
            {"Company": "DPL", "Account Head": "Bharat Singh(406)", "Parent Account Head": "SALARY PAYABLE"},
            {"Company": "DPL", "Account Head": "Some Vendor", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.list_payees_by_parent_account_head("SALARY PAYABLE", company="DPL")

    assert result == ["Ashish Gaur(157)", "Bharat Singh(406)"]


def test_list_payees_by_parent_account_head_scoped_by_company(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Company": "DPL", "Account Head": "DPL Employee", "Parent Account Head": "SALARY PAYABLE"},
            {"Company": "AMB", "Account Head": "AMB Employee", "Parent Account Head": "SALARY PAYABLE"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.list_payees_by_parent_account_head("SALARY PAYABLE", company="DPL")

    assert result == ["DPL Employee"]


def test_list_payees_by_parent_account_head_returns_empty_for_no_match(monkeypatch):
    df = pd.DataFrame.from_records(
        [{"Company": "DPL", "Account Head": "Some Vendor", "Parent Account Head": "SUNDRY CREDITORS - OTHER"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.list_payees_by_parent_account_head("SALARY PAYABLE", company="DPL") == []


def test_list_payees_by_parent_account_head_returns_empty_when_columns_missing(monkeypatch):
    df = pd.DataFrame.from_records([{"Company": "DPL"}])
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.list_payees_by_parent_account_head("SALARY PAYABLE", company="DPL") == []


def test_find_party_candidates_returns_all_matching_rows(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Company": "DPL", "Payee Name": "RAJESH KUMAR", "Account Head": "RAJESH KUMAR", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
            {"Company": "DPL", "Payee Name": "RAJESH KUMAR", "Account Head": "RAJESH KUMAR", "Parent Account Head": "GENERAL CATEGORY-FLATS"},
            {"Company": "DPL", "Payee Name": "RAJESH KUMAR", "Account Head": "RAJESH KUMAR", "Parent Account Head": "ADVANCE FROM CUSTOMER (INVESTOR)"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    candidates = master_repository.find_party_candidates("Rajesh Kumar", company="DPL")

    assert len(candidates) == 3
    assert {c["Parent Account Head"] for c in candidates} == {
        "SUNDRY CREDITORS - OTHER", "GENERAL CATEGORY-FLATS", "ADVANCE FROM CUSTOMER (INVESTOR)",
    }


def test_find_party_candidates_returns_single_row_for_unique_match(monkeypatch):
    df = pd.DataFrame.from_records(
        [{"Payee Name": "MUKESH KUMAR", "Account Head": "MUKESH KUMAR", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    candidates = master_repository.find_party_candidates("Mukesh Kumar")

    assert len(candidates) == 1


def test_find_party_candidates_returns_empty_list_for_no_match(monkeypatch):
    df = pd.DataFrame.from_records(
        [{"Payee Name": "MUKESH KUMAR", "Account Head": "MUKESH KUMAR"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party_candidates("Totally Unrelated") == []
    assert master_repository.find_party_candidates(None) == []


def test_find_party_candidates_scoped_by_company(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Company": "DPL", "Payee Name": "ANITA DEVI", "Account Head": "ANITA DEVI", "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS"},
            {"Company": "AMB", "Payee Name": "ANITA DEVI", "Account Head": "ANITA DEVI", "Parent Account Head": "SUNDRY CREDITORS - OTHER"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    dpl_candidates = master_repository.find_party_candidates("ANITA DEVI", company="DPL")

    assert len(dpl_candidates) == 1
    assert dpl_candidates[0]["Parent Account Head"] == "SUNDRY CREDITORS - CONTRACTORS"


# --- find_party_fuzzy: narrow, last-resort typo fallback ---


def test_find_party_fuzzy_matches_a_one_word_typo(monkeypatch):
    # Reproduces the real production case: "Walfare" (bank narration typo)
    # vs Master's correctly-spelled "Welfare".
    df = pd.DataFrame.from_records(
        [{
            "Payee Name": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Account Head": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Parent Account Head": "SUNDRY CREDITORS - EXPENSES",
        }]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_party_fuzzy("Aravali Height Resident Walfare Association")

    assert result is not None
    assert result["Parent Account Head"] == "SUNDRY CREDITORS - EXPENSES"


def test_find_party_fuzzy_refuses_when_two_candidates_tie(monkeypatch):
    # Two Master rows are both plausible typo candidates for the same
    # input, at the exact same similarity ratio - must never guess between
    # them, falls through to None.
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION", "Account Head": "X", "Parent Account Head": "A"},
            {"Payee Name": "ARAVALI HEIGHT RESIDENT WOLFARE ASSOCIATION", "Account Head": "Y", "Parent Account Head": "B"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party_fuzzy("ARAVALI HEIGHT RESIDENT WALFARE ASSOCIATION") is None


def test_find_party_fuzzy_refuses_when_word_count_differs(monkeypatch):
    # High raw similarity but a different word count (a name that's really
    # a truncated/extended version of another) must not match.
    df = pd.DataFrame.from_records(
        [{"Payee Name": "ARAVALI HEIGHTS", "Account Head": "ARAVALI HEIGHTS", "Parent Account Head": "X"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party_fuzzy("ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION") is None


def test_find_party_fuzzy_refuses_below_threshold(monkeypatch):
    df = pd.DataFrame.from_records(
        [{"Payee Name": "S N LTD", "Account Head": "S N LTD", "Parent Account Head": "X"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party_fuzzy("R N LTD") is None


def test_find_party_fuzzy_scoped_by_company(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Company": "AMB", "Payee Name": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION", "Account Head": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION", "Parent Account Head": "AMB VALUE"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party_fuzzy("Aravali Height Resident Walfare Association", company="DPL") is None
    result = master_repository.find_party_fuzzy("Aravali Height Resident Walfare Association", company="AMB")
    assert result["Parent Account Head"] == "AMB VALUE"


def test_find_party_prefers_exact_match_over_fuzzy(monkeypatch):
    # An exact match must always win - the fuzzy fallback is never even
    # consulted when an exact/canonical match already exists.
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "ARAVALI HEIGHT RESIDENT WALFARE ASSOCIATION", "Account Head": "X", "Parent Account Head": "EXACT MATCH"},
            {"Payee Name": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION", "Account Head": "Y", "Parent Account Head": "FUZZY MATCH"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_party("Aravali Height Resident Walfare Association")

    assert result["Parent Account Head"] == "EXACT MATCH"


def test_find_party_falls_back_to_fuzzy_when_no_exact_match(monkeypatch):
    df = pd.DataFrame.from_records(
        [{
            "Payee Name": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Account Head": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Parent Account Head": "SUNDRY CREDITORS - EXPENSES",
        }]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_party("Aravali Height Resident Walfare Association")

    assert result is not None
    assert result["Parent Account Head"] == "SUNDRY CREDITORS - EXPENSES"


def test_find_party_candidates_falls_back_to_fuzzy_as_single_element_list(monkeypatch):
    df = pd.DataFrame.from_records(
        [{
            "Payee Name": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Account Head": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Parent Account Head": "SUNDRY CREDITORS - EXPENSES",
        }]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    candidates = master_repository.find_party_candidates("Aravali Height Resident Walfare Association")

    assert len(candidates) == 1
    assert candidates[0]["Parent Account Head"] == "SUNDRY CREDITORS - EXPENSES"


def test_find_party_fuzzy_candidates_flags_near_miss_margin_as_ambiguous(monkeypatch):
    # Two candidates at ratios 0.986 and 0.973 (a 0.013 gap, both above the
    # 0.92 threshold) - too close to trust as a confident automatic pick -
    # must both come back as candidates instead of one being silently
    # auto-picked just for having the marginally higher ratio.
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "RAJESH KUMAR SHARMA VERMA CONTRACTOR", "Account Head": "X", "Parent Account Head": "A"},
            {"Payee Name": "RAJESH KUMAR SHARMO VERMA CONTRACTORS", "Account Head": "Y", "Parent Account Head": "B"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    candidates = master_repository.find_party_fuzzy_candidates("RAJESH KUMAR SHARMA VERMA CONTRACTORS")

    assert len(candidates) == 2
    assert {c["Parent Account Head"] for c in candidates} == {"A", "B"}
    # find_party_fuzzy() (single-result contract) must refuse the same way.
    assert master_repository.find_party_fuzzy("RAJESH KUMAR SHARMA VERMA CONTRACTORS") is None


def test_find_party_fuzzy_candidates_still_auto_picks_a_clear_winner(monkeypatch):
    # A candidate decisively better than the rest (margin exceeded) must
    # still come back as a single-element list, unchanged from before.
    df = pd.DataFrame.from_records(
        [{
            "Payee Name": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Account Head": "ARAVALI HEIGHT RESIDENT WELFARE ASSOCIATION",
            "Parent Account Head": "SUNDRY CREDITORS - EXPENSES",
        }]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    candidates = master_repository.find_party_fuzzy_candidates("Aravali Height Resident Walfare Association")

    assert len(candidates) == 1
    assert candidates[0]["Parent Account Head"] == "SUNDRY CREDITORS - EXPENSES"


def test_find_party_fuzzy_candidates_never_crosses_company_boundary_on_a_near_miss(monkeypatch):
    # A closer-ratio same-name row belonging to a different company must
    # never enter the candidate set, even under the new margin logic.
    df = pd.DataFrame.from_records(
        [
            {"Company": "DPL", "Payee Name": "RAJESH KUMAR SHARMA", "Account Head": "X", "Parent Account Head": "DPL VALUE"},
            {"Company": "AMB", "Payee Name": "RAJESH KUMAR SHRMA", "Account Head": "Y", "Parent Account Head": "AMB VALUE"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    candidates = master_repository.find_party_fuzzy_candidates("RAJESH KUMAR SHRMA", company="DPL")

    assert len(candidates) == 1
    assert candidates[0]["Parent Account Head"] == "DPL VALUE"


def test_find_party_fuzzy_no_match_for_unrelated_name(monkeypatch):
    df = pd.DataFrame.from_records(
        [{"Payee Name": "TOTALLY DIFFERENT COMPANY", "Account Head": "TOTALLY DIFFERENT COMPANY", "Parent Account Head": "X"}]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party_fuzzy("Aravali Height Resident Walfare Association") is None


def test_find_deduction_for_head_returns_none_when_no_category_match(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {
                "Payee Name": "A",
                "Account Head": "SALARY PAYABLE",
                "Parent Account Head": "",
                "Deduction Type": "Tax deducted at source",
                "Description": "TDS ON SALARY",
            },
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    result = master_repository.find_deduction_for_head("UNRELATED", "")

    assert result is None
