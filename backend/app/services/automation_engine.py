import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import get_settings
from app.core.logger import logger
from app.services import classifier, ledger_repository, ref_code, sheets_client, validation
from app.services.classifier import ClassificationResult

BANK_STATEMENT_WORKSHEET = "YES IDW 0490"
# Identifies the bank account this statement belongs to. Hardcoded for the
# single demo account; multi-account support would make this per-run config.
BANK_NAME_FOR_STATEMENT = "Yes Bank Idw A/c 045563200000490"


def _parse_amount(value: str) -> float:
    value = value.replace(",", "").strip()
    return float(value) if value else 0.0


# "%d-%b-%Y" matches the Google Sheet / CSV text format ("22-Jul-2026").
# "%Y-%m-%d %H:%M:%S" / "%Y-%m-%d" match native Excel date cells, which
# pandas stringifies this way even when read with dtype=str.
_TXN_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _parse_txn_date(value: str) -> datetime:
    value = value.strip()
    for fmt in _TXN_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"time data {value!r} does not match any known TXN DATE format")


def _format_amount(amount: float) -> str:
    return f"{amount:,.2f}" if amount else ""


def _financial_year(date: datetime) -> str:
    """Indian fiscal year: April 1 - March 31."""
    start_year = date.year if date.month >= 4 else date.year - 1
    return f"01-04-{start_year}-31-03-{start_year + 1}"


@dataclass
class TransactionRowSet:
    sl_no: str
    reference: str
    description: str
    debit: float
    credit: float
    business_unit: str
    txn_date: datetime
    classification: ClassificationResult
    destination: str  # "deposit_withdrawal" | "receipt_payment" | "review" | "duplicate" | "error"
    review_reason: str | None = None
    rows: dict[str, list[dict]] = field(default_factory=dict)


@dataclass
class RunResult:
    run_id: str
    dry_run: bool
    total_transactions: int
    routed_deposit_withdrawal: int
    routed_receipt_payment: int
    needs_review: int
    duplicates_skipped: int
    transactions: list[TransactionRowSet]


def _build_receipt_payment_rows(txn: TransactionRowSet, link_ref_code: int) -> dict[str, list[dict]]:
    matched = txn.classification.matched_master_row or {}
    debit_credit = "Debit" if txn.debit else "Credit"
    doc_date = txn.txn_date.strftime("%d/%m/%Y")
    financial_year = _financial_year(txn.txn_date)

    return {
        "ReceiptPayment": [
            {
                "Link Ref Code": link_ref_code,
                "Business Unit": txn.business_unit,
                "Financial Year": financial_year,
                "Document Type": "RECEIPT / PAYMENT",
                "Document Date": doc_date,
                "Document No": "",
                "Narration": txn.description,
                "BankName": BANK_NAME_FOR_STATEMENT,
                "EntryTypes": "RECEIPT / PAYMENT",
            }
        ],
        "ReceiptPaymentDetail": [
            {"Link Ref Code": link_ref_code, "Detail Link Ref Code": link_ref_code}
        ],
        "LedgerDetails": [
            {
                "Link Ref Code": link_ref_code,
                "Detail Link Ref Code": link_ref_code,
                "Business Unit": txn.business_unit,
                "Document Type": "RECEIPT / PAYMENT",
                "Debit/Credit": debit_credit,
                "Account Head": matched.get("Account Head") or txn.classification.payee_name,
                "Parent Account Head": matched.get("Parent Account Head", ""),
                "Debit Amount": _format_amount(txn.debit),
                "Credit Amount": _format_amount(txn.credit),
                "Payment Mode": matched.get("Payment Mode") or "Direct",
                "Payee Name": txn.classification.payee_name,
            }
        ],
        "AdjustmentDetails": [
            {
                "Link Ref Code": link_ref_code,
                "Detail Link Ref Code": link_ref_code,
                "Docno": matched.get("Docno") or "ON A/C",
                "Date": doc_date,
                "Invoice No": matched.get("Invoice No") or "Normal",
                "Invoice Date": doc_date,
                "Adjustment Amount": _format_amount(txn.debit or txn.credit),
            }
        ],
        "ImportTaxInfo": [
            {
                "Link Ref Code": link_ref_code,
                "Detail Link Ref Code": link_ref_code,
                "Deduction Type": matched.get("Deduction Type", ""),
                "Description": matched.get("Description", ""),
            }
        ],
    }


def _build_deposit_withdrawal_rows(txn: TransactionRowSet, link_ref_code: int) -> dict[str, list[dict]]:
    debit_credit = "Debit" if txn.debit else "Credit"
    doc_date = txn.txn_date.strftime("%d/%m/%Y")
    financial_year = _financial_year(txn.txn_date)

    return {
        "DepositWithdrawal": [
            {
                "Link Ref Code": link_ref_code,
                "DepositWithdrawal Business Unit": txn.business_unit,
                "DepositWithdrawal Narration": txn.description,
                "Financial Year": financial_year,
                "Document Type": "Deposit / Withdrawal",
                "Document Date": doc_date,
                "Document No": "",
                "BankName": BANK_NAME_FOR_STATEMENT,
                "EntryTypes": "Deposit / Withdrawal",
            }
        ],
        "DepositWithdrawalDetails": [{"Link Ref Code": link_ref_code}],
        "LedgerDetails": [
            {
                "Link Ref Code": link_ref_code,
                "Debit/Credit": debit_credit,
                # Best-effort default: no Master match exists for internal
                # transfers, so there's no real party name to use here.
                "Account Head": "Internal Transfer",
                "Parent Account Head": "Internal Transfer",
                "Debit Amount": _format_amount(txn.debit),
                "Credit Amount": _format_amount(txn.credit),
                "Payment Mode": "Direct",
                "Payee Name": "Internal Transfer",
            }
        ],
    }


def _read_bank_rows_from_sheet() -> list[dict]:
    settings = get_settings()
    return sheets_client.read_all_records(settings.STATEMENT_MASTER_SHEET_ID, BANK_STATEMENT_WORKSHEET)


def _process_rows(bank_rows: list[dict], run_id: str) -> list[TransactionRowSet]:
    """Classify/route raw transaction rows, regardless of source (Google
    Sheet tab or an uploaded file) — same row shape, same pipeline.
    """
    # Batch duplicate check: single Supabase query instead of N per-row calls.
    raw_references = [str(row.get("REFERENCE", "")).strip() for row in bank_rows]
    existing_refs = ledger_repository.is_already_processed_batch(raw_references)

    transactions = []
    for row in bank_rows:
        sl_no = str(row.get("SL#", ""))
        reference = str(row.get("REFERENCE", "")).strip()

        try:
            if reference in existing_refs:
                logger.info(f"[{run_id}] Skipping duplicate SL#{sl_no} (reference={reference})")
                ledger_repository.log_audit(
                    run_id, "info", f"Skipped duplicate SL#{sl_no}", {"reference": reference}
                )
                transactions.append(
                    TransactionRowSet(
                        sl_no=sl_no,
                        reference=reference,
                        description=row.get("DESCRIPTION", ""),
                        debit=0,
                        credit=0,
                        business_unit=row.get("BUSINESS UNIT", ""),
                        txn_date=_parse_txn_date(str(row["TXN DATE"])),
                        classification=classifier.ClassificationResult(
                            is_internal=False, head="", payee_name=None, matched_master_row=None, needs_review=False
                        ),
                        destination="duplicate",
                    )
                )
                continue

            description = row.get("DESCRIPTION", "")
            debit = _parse_amount(str(row.get("DEBITS", "")))
            credit = _parse_amount(str(row.get("CREDITS", "")))
            txn_date = _parse_txn_date(str(row["TXN DATE"]))
            existing_head = str(row.get("HEAD", "")).strip()

            classification = classifier.classify_transaction(description, existing_head=existing_head)

            destination = (
                "review"
                if classification.needs_review
                else "deposit_withdrawal"
                if classification.is_internal
                else "receipt_payment"
            )

            if classification.needs_review:
                logger.warning(f"[{run_id}] SL#{sl_no} flagged for review: {classification.review_reason}")
                ledger_repository.log_audit(
                    run_id, "warning", f"SL#{sl_no} flagged for review",
                    {"reference": reference, "reason": classification.review_reason},
                )

            transactions.append(
                TransactionRowSet(
                    sl_no=sl_no,
                    reference=reference,
                    description=description,
                    debit=debit,
                    credit=credit,
                    business_unit=row.get("BUSINESS UNIT", ""),
                    txn_date=txn_date,
                    classification=classification,
                    destination=destination,
                )
            )
        except Exception as exc:
            logger.error(f"[{run_id}] Failed to process SL#{sl_no}: {exc}")
            ledger_repository.log_audit(
                run_id, "error", f"Failed to process SL#{sl_no}", {"reference": reference, "error": str(exc)}
            )
            transactions.append(
                TransactionRowSet(
                    sl_no=sl_no,
                    reference=reference,
                    description=row.get("DESCRIPTION", ""),
                    debit=0,
                    credit=0,
                    business_unit=row.get("BUSINESS UNIT", ""),
                    txn_date=datetime.now(),
                    classification=classifier.ClassificationResult(
                        is_internal=False, head="", payee_name=None, matched_master_row=None, needs_review=True,
                        review_reason=f"Processing error: {exc}",
                    ),
                    destination="error",
                    review_reason=str(exc),
                )
            )

    return transactions


def _assign_rows(transactions: list[TransactionRowSet], settings, run_id: str) -> None:
    dw_next_ref = ref_code.get_next_ref_code(settings.DEPOSIT_WITHDRAWAL_SHEET_ID, "DepositWithdrawal")
    rp_next_ref = ref_code.get_next_ref_code(settings.RECEIPT_PAYMENT_SHEET_ID, "ReceiptPayment")

    for txn in transactions:
        if txn.destination not in ("receipt_payment", "deposit_withdrawal"):
            continue

        rows = (
            _build_receipt_payment_rows(txn, rp_next_ref)
            if txn.destination == "receipt_payment"
            else _build_deposit_withdrawal_rows(txn, dw_next_ref)
        )

        errors = validation.validate_rows(rows)
        if errors:
            logger.warning(f"[{run_id}] SL#{txn.sl_no} failed validation: {errors}")
            ledger_repository.log_audit(
                run_id, "error", f"SL#{txn.sl_no} failed validation",
                {"reference": txn.reference, "errors": errors},
            )
            txn.destination = "review"
            txn.review_reason = "; ".join(errors)
            continue

        txn.rows = rows
        if txn.destination == "receipt_payment":
            rp_next_ref += 1
        else:
            dw_next_ref += 1


def _write_transactions(transactions: list[TransactionRowSet], settings, run_id: str) -> None:
    dw_batches: dict[str, list[dict]] = {}
    rp_batches: dict[str, list[dict]] = {}

    for txn in transactions:
        target = (
            dw_batches
            if txn.destination == "deposit_withdrawal"
            else rp_batches
            if txn.destination == "receipt_payment"
            else None
        )
        if target is None:
            continue
        for tab, rows in txn.rows.items():
            target.setdefault(tab, []).extend(rows)

    try:
        for tab, rows in dw_batches.items():
            sheets_client.append_records(settings.DEPOSIT_WITHDRAWAL_SHEET_ID, tab, rows)
        for tab, rows in rp_batches.items():
            sheets_client.append_records(settings.RECEIPT_PAYMENT_SHEET_ID, tab, rows)
    except Exception as exc:
        logger.error(f"[{run_id}] Write to sheets failed: {exc}")
        ledger_repository.log_audit(run_id, "error", "Write to sheets failed", {"error": str(exc)})
        raise

    for txn in transactions:
        if txn.destination in ("receipt_payment", "deposit_withdrawal"):
            link_ref_code = txn.rows.get("ReceiptPayment") or txn.rows.get("DepositWithdrawal")
            ledger_repository.mark_processed(
                reference=txn.reference,
                sl_no=txn.sl_no,
                description=txn.description,
                head=txn.classification.head,
                destination=txn.destination,
                link_ref_code=link_ref_code[0]["Link Ref Code"] if link_ref_code else None,
            )


def run_automation(dry_run: bool = True, rows: list[dict] | None = None) -> RunResult:
    """Run the pipeline. If ``rows`` is given (e.g. parsed from an uploaded
    file), those are used directly; otherwise falls back to reading the
    configured Google Sheet bank statement tab.
    """
    run_id = str(uuid.uuid4())
    settings = get_settings()

    logger.info(f"[{run_id}] Automation run started (dry_run={dry_run}, source={'upload' if rows is not None else 'sheet'})")
    ledger_repository.log_audit(
        run_id, "info", "Automation run started",
        {"dry_run": dry_run, "source": "upload" if rows is not None else "sheet"},
    )

    bank_rows = rows if rows is not None else _read_bank_rows_from_sheet()
    transactions = _process_rows(bank_rows, run_id)
    _assign_rows(transactions, settings, run_id)

    if not dry_run:
        _write_transactions(transactions, settings, run_id)

    result = RunResult(
        run_id=run_id,
        dry_run=dry_run,
        total_transactions=len(transactions),
        routed_deposit_withdrawal=sum(1 for t in transactions if t.destination == "deposit_withdrawal"),
        routed_receipt_payment=sum(1 for t in transactions if t.destination == "receipt_payment"),
        needs_review=sum(1 for t in transactions if t.destination in ("review", "error")),
        duplicates_skipped=sum(1 for t in transactions if t.destination == "duplicate"),
        transactions=transactions,
    )

    logger.info(
        f"[{run_id}] Automation run completed: "
        f"{result.routed_receipt_payment} receipt/payment, "
        f"{result.routed_deposit_withdrawal} deposit/withdrawal, "
        f"{result.needs_review} needs review, "
        f"{result.duplicates_skipped} duplicates skipped"
    )
    ledger_repository.log_audit(
        run_id, "info", "Automation run completed",
        {
            "routed_receipt_payment": result.routed_receipt_payment,
            "routed_deposit_withdrawal": result.routed_deposit_withdrawal,
            "needs_review": result.needs_review,
            "duplicates_skipped": result.duplicates_skipped,
        },
    )

    return result
