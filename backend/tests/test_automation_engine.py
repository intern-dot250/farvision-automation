from datetime import datetime
from unittest.mock import patch

from app.services.automation_engine import (
    TransactionRowSet,
    _build_deposit_withdrawal_rows,
    _process_rows,
)
from app.services.classifier import ClassificationResult


def _internal_txn(payee_name: str | None) -> TransactionRowSet:
    return TransactionRowSet(
        sl_no="1",
        reference="",
        description="YIB-TPT-Some Entity-045563200000377",
        debit=1000.0,
        credit=0.0,
        business_unit="Casa Romana",
        txn_date=datetime(2026, 7, 8),
        classification=ClassificationResult(
            is_internal=True,
            head="Internal",
            payee_name=payee_name,
            matched_master_row=None,
            needs_review=False,
        ),
        destination="deposit_withdrawal",
    )


def test_deposit_withdrawal_uses_extracted_entity_name_as_payee():
    rows = _build_deposit_withdrawal_rows(_internal_txn("DWARKADHIS PROJECTS PRIVATE LIMITED"), link_ref_code=1)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Payee Name"] == "DWARKADHIS PROJECTS PRIVATE LIMITED"
    # Head stays the category label regardless of the extracted name.
    assert ledger["Account Head"] == "Internal Transfer"
    assert ledger["Parent Account Head"] == "Internal Transfer"


def test_deposit_withdrawal_falls_back_to_generic_label_when_no_name_extracted():
    rows = _build_deposit_withdrawal_rows(_internal_txn(None), link_ref_code=1)

    ledger = rows["LedgerDetails"][0]
    assert ledger["Payee Name"] == "Internal Transfer"


def test_duplicate_transaction_shows_real_payee_not_head_category():
    # The ledger only stores head/destination for a duplicate match, not a
    # payee name - the real name should be re-derived from this row's own
    # description, not shown as the Head category (e.g. "Contractor").
    bank_rows = [
        {
            "SL#": "336",
            "REFERENCE": "YESME6203001855300",
            "DESCRIPTION": "YIB-NEFT-YESME6203001855300-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA",
            "TXN DATE": "22-Jul-2026",
            "DEBITS": "1000",
            "CREDITS": "",
            "BUSINESS UNIT": "Casa Romana",
        }
    ]

    with patch(
        "app.services.automation_engine.ledger_repository.is_already_processed_batch",
        return_value={"YESME6203001855300": {"head": "Contractor", "destination": "receipt_payment"}},
    ), patch("app.services.automation_engine.ledger_repository.log_audit"):
        transactions = _process_rows(bank_rows, run_id="test-run")

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn.destination == "duplicate"
    assert txn.classification.head == "Contractor"
    assert txn.classification.payee_name == "Rakiba BIBI"
