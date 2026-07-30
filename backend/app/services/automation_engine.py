import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import get_settings
from app.core.logger import logger
from app.services import classifier, ledger_repository, master_repository, ref_code, sheets_client, validation
from app.services.classifier import ClassificationResult

BANK_STATEMENT_WORKSHEET = "YES IDW 0490"


def _parse_amount(value: str) -> float:
    value = value.replace(",", "").strip()
    return float(value) if value else 0.0


# "%d-%b-%Y" matches the Google Sheet / CSV text format ("22-Jul-2026").
# "%Y-%m-%d %H:%M:%S" / "%Y-%m-%d" match native Excel date cells, which
# pandas stringifies this way even when read with dtype=str.
# "%d/%m/%Y" matches some rows stored as plain text in real statements
# ("28/03/2026") rather than native Excel date cells.
_TXN_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y")


def _parse_txn_date(value: str) -> datetime:
    value = value.strip()
    for fmt in _TXN_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"time data {value!r} does not match any known TXN DATE format")


def _format_amount(amount: float) -> int | str:
    """Whole-rupee integer for a real, sortable/summable Sheets number, or
    "" when there's nothing to show (Debit/Credit are mutually exclusive
    per row). Indian digit grouping ("1,50,000") isn't achievable on a
    genuine Sheets number - confirmed exhaustively (NUMBER/TEXT format
    types, custom patterns, locale tags, en_GB, even India's own hi_IN
    locale all only ever produce Western 3-digit grouping) - so display
    grouping is handled by the column's own number format
    (sheets_client._apply_amount_number_formats), not here.
    """
    return int(round(amount)) if amount else ""


def _resolve_own_bank_name(source_sheet, matched_master, narration_bank) -> str:
    """Resolve the BankName value for a Receipt/Payment or Deposit/
    Withdrawal row. When the transaction came from a multi-tab workbook
    upload, the source tab name encodes our own bank account in short
    form (e.g. "YES AH IDW 2457"). Master carries the full form (e.g.
    "YES BANK AH IDW 045563400002457") — match on the last 4 digits of
    the embedded account number and prefer the full form. Fall back to
    Master's Bank Name, then narration-parsed bank, then blank."""
    if source_sheet:
        suffix = master_repository._last_n_digits(source_sheet, 4)
        if suffix:
            full = master_repository.find_bank_by_account_suffix(suffix)
            if full:
                return full
        return source_sheet
    return matched_master.get("Bank Name") or narration_bank or ""


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
    destination_sheet: str | None = None  # human-readable sheet name for duplicates
    source_sheet: str | None = None  # original sheet/tab name from uploaded file
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


def _build_import_tax_info_rows(txn: TransactionRowSet, link_ref_code: int, matched: dict) -> list[dict]:
    """Contractor payments always need both a TDS row and a GST row on the
    same Link Ref Code; Vendor payments only need the GST row. Any other
    head keeps the original single Master-driven row."""
    description = matched.get("Description", "")
    base = {"Link Ref Code": link_ref_code, "Detail Link Ref Code": link_ref_code}

    if txn.classification.head == "Contractor":
        return [
            {**base, "Deduction Type": "Tax deducted at source", "Description": description},
            {**base, "Deduction Type": "Goods and Service Tax", "Description": description},
        ]
    if txn.classification.head == "Vendor":
        return [{**base, "Deduction Type": "Goods and Service Tax", "Description": description}]
    return [{**base, "Deduction Type": matched.get("Deduction Type", ""), "Description": description}]


def _build_receipt_payment_rows(txn: TransactionRowSet, link_ref_code: int) -> dict[str, list[dict]]:
    matched = txn.classification.matched_master_row or {}
    debit_credit = "Debit" if txn.debit else "Credit"
    doc_date = txn.txn_date.strftime("%d/%m/%Y")
    financial_year = _financial_year(txn.txn_date)
    # The BankName column identifies our own bank account for the
    # transaction. When the upload came from a multi-tab workbook, the
    # source tab name (e.g. "YES AH IDW 2457") maps to a full-form Master
    # entry (e.g. "YES BANK AH IDW 045563400002457") via the last 4 digits
    # of the embedded account number. Otherwise fall back to Master's
    # Bank Name on the matched payee row, then the counterparty bank parsed
    # from the narration (used when running from the configured Google
    # Sheet, where there is no source tab).
    bank_name = _resolve_own_bank_name(
        txn.source_sheet, matched, txn.classification.bank_name
    )

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
                "BankName": bank_name,
                "EntryTypes": "RECEIPT / PAYMENT",
                "Reference": txn.reference,
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
                # Both fall back to the trusted head (Vendor/Contractor/Bank
                # Charges/...) as a last resort when Master has no entry for
                # this payee AND the narration has no extractable payee name
                # (e.g. "POS GST") - so a headed transaction never fails the
                # LedgerDetails required-field check and gets wrongly
                # rerouted to review just because neither source has a name.
                "Account Head": matched.get("Account Head") or txn.classification.payee_name or txn.classification.head,
                "Parent Account Head": matched.get("Parent Account Head") or txn.classification.head,
                "Debit Amount": _format_amount(txn.debit),
                "Credit Amount": _format_amount(txn.credit),
                "Payment Mode": "Net Banking",
                "Payee Name": txn.classification.payee_name or txn.classification.head,
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
        "ImportTaxInfo": _build_import_tax_info_rows(txn, link_ref_code, matched),
    }


def _build_deposit_withdrawal_rows(txn: TransactionRowSet, link_ref_code: int) -> dict[str, list[dict]]:
    matched = txn.classification.matched_master_row or {}
    debit_credit = "Debit" if txn.debit else "Credit"
    doc_date = txn.txn_date.strftime("%d/%m/%Y")
    financial_year = _financial_year(txn.txn_date)
    # The description usually names the counterparty entity even for
    # internal transfers - use it when available, otherwise fall back to
    # the generic label (e.g. non-TPT internal formats with no extractable
    # name).
    payee_display = txn.classification.payee_name or "Internal Transfer"
    # Same BankName resolution as Receipt/Payment — see _build_rp_rows.
    bank_name = _resolve_own_bank_name(
        txn.source_sheet, matched, txn.classification.bank_name
    )

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
                "BankName": bank_name,
                "EntryTypes": "Deposit / Withdrawal",
                "Reference": txn.reference,
            }
        ],
        "DepositWithdrawalDetails": [{"Link Ref Code": link_ref_code}],
        "LedgerDetails": [
            {
                "Link Ref Code": link_ref_code,
                "Debit/Credit": debit_credit,
                # Head stays the category label ("Internal Transfer") even
                # though Payee Name below may show the actual counterparty -
                # no Master match/category exists for internal transfers.
                "Account Head": "Internal Transfer",
                "Parent Account Head": "Internal Transfer",
                "Debit Amount": _format_amount(txn.debit),
                "Credit Amount": _format_amount(txn.credit),
                "Payment Mode": "Net Banking",
                "Payee Name": payee_display,
            }
        ],
    }


def _read_bank_rows_from_sheet() -> list[dict]:
    settings = get_settings()
    return sheets_client.read_all_records(settings.STATEMENT_MASTER_SHEET_ID, BANK_STATEMENT_WORKSHEET)


def _process_rows_stream(bank_rows: list[dict], run_id: str, settings):
    """Classify/route raw transaction rows, regardless of source (Google
    Sheet tab or an uploaded file) — same row shape, same pipeline.

    Yields a {"processed", "total"} dict after each row so callers (e.g. a
    streaming API response) can report live progress; returns the full
    transactions list as the generator's return value.
    """
    # Duplicate check reads the Reference column directly from both real
    # Sheets - the Sheet is the single source of truth. A separate ledger
    # (e.g. Supabase) can silently drift from what's actually in the Sheet
    # (deleted rows, failed partial writes); reading the Sheet itself can't.
    rp_refs = sheets_client.get_column_values(settings.RECEIPT_PAYMENT_SHEET_ID, "ReceiptPayment", "Reference")
    dw_refs = sheets_client.get_column_values(settings.DEPOSIT_WITHDRAWAL_SHEET_ID, "DepositWithdrawal", "Reference")

    total = len(bank_rows)
    transactions = []
    for index, row in enumerate(bank_rows):
        sl_no = str(row.get("SL#", ""))
        reference = str(row.get("REFERENCE", "")).strip()
        source_sheet = str(row.get("source_sheet", "")).strip() or None

        try:
            description = row.get("DESCRIPTION", "")
            debit = _parse_amount(str(row.get("DEBITS", "")))
            credit = _parse_amount(str(row.get("CREDITS", "")))
            txn_date = _parse_txn_date(str(row["TXN DATE"]))
            existing_head = str(row.get("HEAD", "")).strip()

            classification = classifier.classify_transaction(description, existing_head=existing_head)

            if reference and (reference in rp_refs or reference in dw_refs):
                logger.info(f"[{run_id}] Skipping duplicate SL#{sl_no} (reference={reference})")
                ledger_repository.log_audit(
                    run_id, "info", f"Skipped duplicate SL#{sl_no}", {"reference": reference}
                )
                original_dest = "receipt_payment" if reference in rp_refs else "deposit_withdrawal"
                transactions.append(
                    TransactionRowSet(
                        sl_no=sl_no,
                        reference=reference,
                        description=description,
                        debit=0,
                        credit=0,
                        business_unit=row.get("BUSINESS UNIT", ""),
                        txn_date=txn_date,
                        classification=classification,
                        destination="duplicate",
                        destination_sheet="receipt/payment" if original_dest == "receipt_payment" else "deposit/withdrawal",
                        source_sheet=source_sheet,
                    )
                )
            else:
                destination = (
                    "review"
                    if classification.needs_review
                    else "deposit_withdrawal"
                    if classification.is_internal or classification.head.strip().upper() == "COLLECTION"
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
                        source_sheet=source_sheet,
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
                    source_sheet=source_sheet,
                )
            )

        yield {"processed": index + 1, "total": total}

    return transactions


def _process_rows(bank_rows: list[dict], run_id: str, settings) -> list[TransactionRowSet]:
    """Non-streaming wrapper around _process_rows_stream for callers that
    don't need progress updates (e.g. the plain /run endpoint)."""
    gen = _process_rows_stream(bank_rows, run_id, settings)
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


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
    # The Sheet write above IS the record - duplicate-detection reads the
    # Reference column straight from the Sheet on the next run, so there's
    # no separate ledger to update here.


def run_automation_stream(dry_run: bool = True, rows: list[dict] | None = None):
    """Same pipeline as run_automation(), but yields live progress events so
    a caller (e.g. a streaming API response) can report real progress
    instead of just waiting for one final response.

    Yields dicts shaped either:
      {"type": "progress", "stage": "classifying"|"writing", "processed": int, "total": int}
      {"type": "result", "result": RunResult}
    The "result" event is always the last one yielded.
    """
    run_id = str(uuid.uuid4())
    settings = get_settings()

    logger.info(f"[{run_id}] Automation run started (dry_run={dry_run}, source={'upload' if rows is not None else 'sheet'})")
    ledger_repository.log_audit(
        run_id, "info", "Automation run started",
        {"dry_run": dry_run, "source": "upload" if rows is not None else "sheet"},
    )

    bank_rows = rows if rows is not None else _read_bank_rows_from_sheet()
    total = len(bank_rows)
    yield {"type": "progress", "stage": "classifying", "processed": 0, "total": total}

    gen = _process_rows_stream(bank_rows, run_id, settings)
    transactions: list[TransactionRowSet] = []
    while True:
        try:
            progress = next(gen)
            yield {"type": "progress", "stage": "classifying", **progress}
        except StopIteration as stop:
            transactions = stop.value
            break

    _assign_rows(transactions, settings, run_id)

    if not dry_run:
        yield {"type": "progress", "stage": "writing", "processed": total, "total": total}
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

    yield {"type": "result", "result": result}


def run_automation(dry_run: bool = True, rows: list[dict] | None = None) -> RunResult:
    """Run the pipeline and return only the final result - for callers that
    don't need progress updates. If ``rows`` is given (e.g. parsed from an
    uploaded file), those are used directly; otherwise falls back to reading
    the configured Google Sheet bank statement tab.
    """
    for event in run_automation_stream(dry_run=dry_run, rows=rows):
        if event["type"] == "result":
            return event["result"]
    raise RuntimeError("run_automation_stream ended without a result event")
