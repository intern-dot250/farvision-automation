from unittest.mock import patch

from app.services.classifier import classify_transaction


def test_internal_transfer_classified_as_internal():
    result = classify_transaction(
        "YIB-TPT-DWARKADHIS PROJECTS PRIVATE LIMITED IN CIRP CR-045563200000377"
    )

    assert result.is_internal is True
    assert result.head == "Internal"
    assert result.needs_review is False


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


def test_unmatched_external_payee_flagged_for_review():
    with patch("app.services.classifier.master_repository.find_party") as mock_find:
        mock_find.return_value = None

        result = classify_transaction(
            "YIB-NEFT-YESME99999999999-Unknown Payee-SBIN0007204-STATE BANK OF INDIA"
        )

    assert result.is_internal is False
    assert result.needs_review is True
    assert result.head == "Unclassified"
    assert "Unknown Payee" in result.review_reason
