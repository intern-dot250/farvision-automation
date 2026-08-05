from unittest.mock import patch

from app.services.classifier import classify_transaction


def test_internal_transfer_classified_as_internal():
    with patch("app.services.classifier.master_repository.find_party", return_value=None):
        result = classify_transaction(
            "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377"
        )

    assert result.is_internal is True
    assert result.head == "Internal"
    assert result.needs_review is False
    assert result.payee_name == "DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR"
    assert result.counterparty_account == "045563200000377"


def test_internal_transfer_still_looks_up_master_for_bank_name():
    # Internal transfers stay "Internal"/not-needing-review either way, but
    # Master is still consulted so a real Bank Name can be pulled for the
    # counterparty when Master happens to have an entry for them.
    with patch("app.services.classifier.master_repository.find_party") as mock_find:
        mock_find.return_value = {"Bank Name": "UBI ESCROW A/C CR- 497801010000168"}

        result = classify_transaction(
            "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377"
        )

    mock_find.assert_called_once_with("DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR", company="DPL")
    assert result.is_internal is True
    assert result.head == "Internal"
    assert result.needs_review is False
    assert result.matched_master_row == {"Bank Name": "UBI ESCROW A/C CR- 497801010000168"}


def test_matched_payee_classified_by_parent_account_head():
    with patch("app.services.classifier.master_repository.find_party") as mock_find:
        mock_find.return_value = {
            "Account Head": "MUKESH KUMAR",
            "Parent Account Head": "SUNDRY CREDITORS - CONTRACTORS",
        }

        result = classify_transaction(
            "YIB-NEFT-YESME62030018553-Mukesh Kumar-KVBL0004201-Contractor-KARUR VYSYA BANK"
        )

    assert result.is_internal is False
    assert result.head == "Contractor"
    assert result.needs_review is False
    assert result.matched_master_row is not None


def test_unmatched_external_payee_routes_to_unclassified():
    with patch("app.services.classifier.master_repository.find_party") as mock_find:
        mock_find.return_value = None

        result = classify_transaction(
            "YIB-NEFT-YESME99999999999-Unknown Payee-SBIN0007204-STATE BANK OF INDIA"
        )

    assert result.is_internal is False
    assert result.needs_review is False
    assert result.head == "Unclassified"
    assert result.payee_name == "Unknown Payee"


def test_existing_head_is_trusted_over_derived_label():
    with patch("app.services.classifier.master_repository.find_party") as mock_find:
        mock_find.return_value = {
            "Account Head": "MUKESH KUMAR",
            "Parent Account Head": "SUNDRY CREDITORS - PROFESSIONAL FEES",
        }

        result = classify_transaction(
            "YIB-NEFT-YESME62030018553-Mukesh Kumar-KVBL0004201-Contractor-KARUR VYSYA BANK",
            existing_head="Contractor",
        )

    assert result.is_internal is False
    assert result.head == "Contractor"
    assert result.needs_review is False
    assert result.matched_master_row is not None


def test_existing_head_internal_still_looks_up_master_for_bank_name():
    with patch("app.services.classifier.master_repository.find_party") as mock_find:
        mock_find.return_value = None

        result = classify_transaction(
            "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377",
            existing_head="Internal",
        )

    mock_find.assert_called_once()
    assert result.is_internal is True
    assert result.head == "Internal"
    assert result.payee_name == "DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR"


def test_trusted_non_internal_head_wins_even_with_no_ifsc_narration():
    # Regression: narrations with no IFSC ("POS GST", bank-charge style
    # entries) previously got silently forced to "Internal" even when the
    # file's own HEAD column explicitly said something else (e.g.
    # "Bank Charges") - a trusted head must always win over the
    # narration-shape heuristic, which is only for rows with no trusted
    # head at all.
    with patch("app.services.classifier.master_repository.find_party", return_value=None):
        result = classify_transaction("POS GST", existing_head="Bank Charges")

    assert result.is_internal is False
    assert result.head == "Bank Charges"
    assert result.needs_review is False


def test_existing_head_with_no_master_match_still_routes_without_review():
    # A trusted, non-Internal head from the statement (Contractor/Vendor/...)
    # is enough on its own to route to Receipt/Payment - it shouldn't need
    # review just because Master doesn't happen to have this payee.
    with patch("app.services.classifier.master_repository.find_party") as mock_find:
        mock_find.return_value = None

        result = classify_transaction(
            "YIB-NEFT-YESME99999999999-Unknown Payee-SBIN0007204-STATE BANK OF INDIA",
            existing_head="Vendor",
        )

    assert result.is_internal is False
    assert result.head == "Vendor"
    assert result.needs_review is False
    assert result.matched_master_row is None


# --- Fallback payee extraction (plain-name descriptions) ---


def test_plain_name_description_becomes_payee_name():
    # Descriptions with no NEFT/RTGS/TPT/UPI/IMPS prefix are treated as
    # raw payee names.
    result = classify_transaction("DWARKADHIS PROJECTS PVT LTD")

    assert result.payee_name == "DWARKADHIS PROJECTS PVT LTD"


def test_plain_name_description_cleans_up_account_number_trailer():
    # "VANDANA KHULLAR - A/C 12345678" → "VANDANA KHULLAR"
    result = classify_transaction("VANDANA KHULLAR - 1234567890")

    assert result.payee_name == "VANDANA KHULLAR"


def test_neft_credit_style_fallback_extracts_payee_after_ifsc():
    # "NEFT Cr-IDFB0021001-Mrs. ANSHU SHARMA-DWARKADHIS" — the parser
    # already handles IFSC-before-payee, but verify the fallback chain too.
    result = classify_transaction(
        "NEFT Cr-IDFB0021001-Mrs. ANSHU SHARMA-DWARKADHIS"
    )

    assert result.payee_name == "Mrs. ANSHU SHARMA"


def test_neft_style_fallback_extracts_payee_after_ifsc():
    # Standard NEFT dash-joined format: ifsc appears before payee, parser
    # handles it. Fallback test for edge case where IFSC is before payee.
    result = classify_transaction(
        "YIB-NEFT-IDFB0021001-Mrs. ANSHU SHARMA-DWARKADHIS"
    )

    assert result.payee_name == "Mrs. ANSHU SHARMA"


def test_imps_narration_extracts_payee_from_second_segment():
    # IMPS slash-delimited: IMPS/{payee}/{account}/RRN:.../...
    result = classify_transaction(
        "IMPS/Jayant Raitani/XXX8180/RRN:618614869331/PC123"
    )

    assert result.payee_name == "Jayant Raitani"


def test_imps_with_na_placeholder_returns_no_payee():
    # IMPS/NA/... means unknown payee — should not return "NA" as payee.
    result = classify_transaction(
        "IMPS/NA/XXXX0091/RRN:616698356024/PC38978"
    )

    assert result.payee_name is None


def test_imps_na_prefix_filters_unknown_payee():
    # IMPS/NAXXXQ675 (NA-prefixed tracking codes) filters the unknown payee
    # slot, then falls back to bank name for Master matching.
    result = classify_transaction(
        "IMPS/NAXXXQ675/XXXX0091/RRN:61874887784/PC04585698164489/BANK OF MAHARAS/D"
    )

    assert result.payee_name == "BANK OF MAHARAS"


def test_plain_name_description_with_no_master_match_routes_to_unclassified():
    # No Master match → route to receipt_payment with Unclassified head
    # (no longer blocked in Review). The Accounts team can correct the head
    # manually in the ERP if needed.
    with patch("app.services.classifier.master_repository.find_party", return_value=None):
        result = classify_transaction("VIJAY YADAV")

    assert result.is_internal is False
    assert result.payee_name == "VIJAY YADAV"
    assert result.needs_review is False
    assert result.head == "Unclassified"


# --- Company resolution (Master mixes DPL/AMB) ---


def test_source_sheet_resolves_company_and_threads_into_master_lookup():
    with patch("app.services.classifier.master_repository.find_party", return_value=None) as mock_find:
        classify_transaction("VIJAY YADAV", source_sheet="YES AH IDW 2457")

    mock_find.assert_called_once_with("VIJAY YADAV", company="DPL")


def test_no_source_sheet_still_defaults_to_dpl():
    # No source_sheet (e.g. running against the plain configured Sheet) -
    # resolve_company() still defaults to "DPL", the only company currently
    # processed, so this doesn't change existing behavior.
    with patch("app.services.classifier.master_repository.find_party", return_value=None) as mock_find:
        classify_transaction("VIJAY YADAV")

    mock_find.assert_called_once_with("VIJAY YADAV", company="DPL")
