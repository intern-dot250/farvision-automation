import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import get_settings
from app.core.logger import logger
from app.services import (
    classifier,
    ledger_repository,
    master_repository,
    override_rules,
    override_rules_repository,
    ref_code,
    sheets_client,
    validation,
)
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


_BUSINESS_UNIT_ALIASES = {
    "HO": "DWARKADHIS PROJECTS PVT. LTD-HO",
}


def _normalize_business_unit(value: str) -> str:
    """Expands known shorthand Business Unit values to the full form Master
    actually uses (e.g. "HO" -> "DWARKADHIS PROJECTS PVT. LTD-HO") - other
    values (Aravali Heights, Casa Romana, ...) already match Master as-is
    and pass through unchanged."""
    key = value.strip().upper()
    return _BUSINESS_UNIT_ALIASES.get(key, value)


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


def _resolve_counterparty_bank_name(
    counterparty_account: str | None,
    matched_master: dict,
    payee_name: str | None,
    raw_description: str | None = None,
) -> str:
    """Resolve the Account Head value for a Deposit/Withdrawal (internal
    transfer) row - the full account name/number of whichever side of the
    transfer is NOT our own account, mirroring _resolve_own_bank_name's
    suffix-matching pattern but applied to the counterparty side instead.

    counterparty_account comes from a TPT-shaped narration's embedded
    destination account number (description_parser.py). When it's absent
    (a minority of internal-transfer narration shapes have no embedded
    account number to extract - e.g. the counterparty's account number is
    prefixed with a bank code instead of being a bare digit string) or has
    no matching Master suffix, try the raw description's last 4 characters
    directly - the same extraction _compute_narration_from_formula() already
    uses for the Narration's "x{last4}" text, so Account Head can never
    disagree with what the Narration already (correctly) shows. Only after
    both attempts fail does this fall back to Master's Bank Name for the
    matched payee, then the payee name itself, then the literal
    "Internal Transfer" as the last resort - Account Head is never left
    blank."""
    if counterparty_account:
        suffix = master_repository._last_n_digits(counterparty_account, 4)
        if suffix:
            full = master_repository.find_bank_by_account_suffix(suffix)
            if full:
                return full
    if raw_description and len(raw_description) >= 4:
        full = master_repository.find_bank_by_account_suffix(raw_description[-4:])
        if full:
            return full
    return matched_master.get("Bank Name") or payee_name or "Internal Transfer"


def _compute_narration_from_formula(row: dict, own_bank_name: str) -> str:
    """Replicates the accounts team's NARRATION spreadsheet formula for the
    two branches verified against real data (Internal-head transfers, and
    Payment Disbursement for non-Internal debits) - used as a fallback when
    the uploaded file's own NARRATION cell is blank, see
    _process_rows_stream. own_bank_name is that tab's own label from the
    formula (e.g. "YES CR FREE 2477"), passed in as the uppercased source
    sheet name.

    The Receipt Credit (non-Internal, credit-side - e.g. Collection) branch
    is deliberately NOT implemented here: a real example on a different tab
    (YES Master 0264) showed a completely different narration format for
    that case ("Receipt: For (Apt#: ...) (Ref: ...) ...", not the
    pipe-separated "Receipt Credit from x..." shape given for YES CR Free
    2477), so it isn't safe to assume one formula covers it. Same for a row
    missing ACC REMARKS (the formula's own required field for every branch):
    rather than surface a hardcoded "Remarks Compulsory For Narration"
    placeholder on the dashboard, this returns "" for both cases so the
    caller falls back to the real raw description instead - never a
    fabricated message, same treatment as every other case where nothing
    computable is available.

    RIGHT(MID(description, position-of-3rd-dash + 1, LEN(description)), 4)
    in the original formula simplifies to just the last 4 characters of
    description (MID-to-end-of-string then RIGHT(4) collapses to that)."""
    description = str(row.get("DESCRIPTION", "")).strip()
    reference = str(row.get("REFERENCE", "")).strip()
    credits = _parse_amount(str(row.get("CREDITS", "")))
    business_unit = str(row.get("BUSINESS UNIT", "")).strip()
    head = str(row.get("HEAD", "")).strip()
    type_for_rera_idw = str(row.get("TYPE FOR RERA IDW", "")).strip()
    apt = str(row.get("APT#", "")).strip()
    acc_remarks = str(row.get("ACC REMARKS", "")).strip()

    ref = reference or "N/A"
    apt_suffix = f" | Apt: {apt}" if apt else ""

    if not acc_remarks:
        return ""

    is_credit = credits > 0
    last4 = description[-4:]

    if head == "Internal":
        # The formula gates this on DESCRIPTION having 3+ dashes, but a real
        # example (an IMPS/-delimited, zero-dash description) still produces
        # this full "From X to Y" form in the live sheet - so this is always
        # attempted for Internal-head rows, not gated on delimiter shape.
        if is_credit:
            transfer = f"Internal Fund Transfer (From x{last4} to {own_bank_name})"
        else:
            transfer = f"Internal Fund Transfer (From {own_bank_name} to x{last4})"
        text = f"{transfer} | Ref: {ref} | Type: {type_for_rera_idw} | BU: {business_unit} | Head: {head}"
    elif is_credit:
        # Not implemented - see docstring. Falls back to raw description.
        return ""
    else:
        purpose = "Salary" if "salary" in head.lower() else acc_remarks
        slash_parts = description.split("/")
        dash_parts = description.split("-")
        # Formula's IFERROR chain: 4th "/"-segment, else 4th "-"-segment,
        # else the raw description - only valid if enough delimiters exist
        # (mirrors FIND() erroring when a delimiter position doesn't exist).
        if len(slash_parts) >= 6:
            to = slash_parts[4]
        elif len(dash_parts) >= 5:
            to = dash_parts[3]
        else:
            to = description
        text = f"Payment Disbursement (Purpose: {purpose}) | To: {to} | Ref: {ref} | BU: {business_unit} | Head: {head}{apt_suffix}"

    return " ".join(text.split())  # TRIM() equivalent - collapses all whitespace runs


def _financial_year(date: datetime) -> str:
    """Indian fiscal year: April 1 - March 31."""
    start_year = date.year if date.month >= 4 else date.year - 1
    return f"01-04-{start_year}-31-03-{start_year + 1}"


@dataclass
class TransactionRowSet:
    sl_no: str
    reference: str
    description: str  # raw bank DESCRIPTION - used for classification/payee parsing only, never written to the ERP output
    debit: float
    credit: float
    business_unit: str
    txn_date: datetime
    classification: ClassificationResult
    destination: str  # "deposit_withdrawal" | "receipt_payment" | "review" | "duplicate" | "error" | "skipped_internal_credit"
    destination_sheet: str | None = None  # human-readable sheet name for duplicates
    source_sheet: str | None = None  # original sheet/tab name from uploaded file
    review_reason: str | None = None
    rows: dict[str, list[dict]] = field(default_factory=dict)
    narration: str = ""  # display narration written to the ERP output - the source file's own NARRATION column when present, else falls back to description


@dataclass
class RunResult:
    run_id: str
    dry_run: bool
    total_transactions: int
    routed_deposit_withdrawal: int
    routed_receipt_payment: int
    needs_review: int
    duplicates_skipped: int
    skipped_internal_credit: int
    transactions: list[TransactionRowSet]


_CONTRACTOR_DEFAULT_DESCRIPTION = "TDS ON CONTRACTORS"


def _resolve_import_tax_description(matched: dict, deduction_type: str, default: str = "") -> str:
    """Description for one ImportTaxInfo row of a known Deduction Type
    (Contractor's TDS/GST rows, Vendor's GST row). Tries the payee's own
    Master Description first, then another Master row sharing the same
    Account Head/Parent Account Head AND the same Deduction Type
    (master_repository.find_description_for_head) - matching on Deduction
    Type too prevents a TDS-category Description ("TDS ON RENT PAID")
    ending up on a GST row just because they share an Account Head. Falls
    back to `default` only when neither source has anything."""
    description = matched.get("Description", "")
    if description:
        return description
    fallback = master_repository.find_description_for_head(
        matched.get("Account Head"), matched.get("Parent Account Head"), deduction_type
    )
    return fallback or default


def _build_import_tax_info_rows(txn: TransactionRowSet, link_ref_code: int, matched: dict) -> list[dict]:
    """Every Receipt/Payment transaction gets a matching ImportTaxInfo row on
    the same Link Ref Code, so the tab tracks 1:1 with ReceiptPayment.
    Contractor payments get both a TDS row and a GST row; Vendor payments
    get only the GST row; every other head keeps a single Master-driven row.

    Contractor/Vendor already know their Deduction Type, so only the
    Description needs resolving (own Master row, then same-category
    fallback, then a fixed default for Contractor since every Contractor
    payment is a TDS-on-contractor deduction by definition). Other heads
    don't have a predetermined Deduction Type, so Deduction Type and
    Description are resolved together as a pair from the same Master row
    (master_repository.find_deduction_for_head) to keep them consistent."""
    base = {"Link Ref Code": link_ref_code, "Detail Link Ref Code": link_ref_code}

    if txn.classification.head == "Contractor":
        tds_description = _resolve_import_tax_description(
            matched, "Tax deducted at source", default=_CONTRACTOR_DEFAULT_DESCRIPTION
        )
        gst_description = _resolve_import_tax_description(
            matched, "Goods and Service Tax", default=_CONTRACTOR_DEFAULT_DESCRIPTION
        )
        return [
            {**base, "Deduction Type": "Tax deducted at source", "Description": tds_description},
            {**base, "Deduction Type": "Goods and Service Tax", "Description": gst_description},
        ]
    if txn.classification.head == "Vendor":
        description = _resolve_import_tax_description(matched, "Goods and Service Tax")
        return [{**base, "Deduction Type": "Goods and Service Tax", "Description": description}]

    deduction_type = matched.get("Deduction Type", "")
    description = matched.get("Description", "")
    if not deduction_type or not description:
        fallback = master_repository.find_deduction_for_head(
            matched.get("Account Head"), matched.get("Parent Account Head")
        )
        if fallback:
            fallback_type, fallback_description = fallback
            deduction_type = deduction_type or fallback_type
            description = description or fallback_description
    return [{**base, "Deduction Type": deduction_type, "Description": description}]


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
                "Narration": txn.narration,
                "BankName": bank_name,
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
    counterparty_bank_name = _resolve_counterparty_bank_name(
        txn.classification.counterparty_account, matched, txn.classification.payee_name,
        raw_description=txn.description,
    )

    return {
        "DepositWithdrawal": [
            {
                "Link Ref Code": link_ref_code,
                "DepositWithdrawal Business Unit": txn.business_unit,
                "DepositWithdrawal Narration": txn.narration,
                "Financial Year": financial_year,
                "Document Type": "Deposit / Withdrawal",
                "Document Date": doc_date,
                "Document No": "",
                "BankName": bank_name,
                "EntryTypes": "Deposit / Withdrawal",
            }
        ],
        "DepositWithdrawalDetails": [{"Link Ref Code": link_ref_code}],
        "LedgerDetails": [
            {
                "Link Ref Code": link_ref_code,
                "Debit/Credit": debit_credit,
                # Account Head shows the counterparty's full account
                # name/number (the other side of the internal transfer, not
                # our own account) - see _resolve_counterparty_bank_name.
                # Parent Account Head has no equivalent concept for internal
                # transfers, so it's left blank rather than a placeholder.
                "Account Head": counterparty_bank_name,
                "Parent Account Head": "",
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
    # Duplicate check reads the Narration column directly from both real
    # Sheets - the Sheet is the single source of truth. A separate ledger
    # (e.g. Supabase) can silently drift from what's actually in the Sheet
    # (deleted rows, failed partial writes); reading the Sheet itself can't.
    # Matched by the transaction's own Reference/UTR digits appearing
    # anywhere inside an existing Narration value, rather than exact-string
    # equality - both the raw bank DESCRIPTION shape and the source file's
    # own pretty-formatted NARRATION column (see below) embed that same
    # reference number, just with different surrounding text, so this stays
    # correct whether an existing row was written before or after the
    # switch to writing the pretty NARRATION.
    rp_narrations = sheets_client.get_column_values(settings.RECEIPT_PAYMENT_SHEET_ID, "ReceiptPayment", "Narration")
    dw_narrations = sheets_client.get_column_values(
        settings.DEPOSIT_WITHDRAWAL_SHEET_ID, "DepositWithdrawal", "DepositWithdrawal Narration"
    )
    existing_narration_digits = {master_repository._digits_only(n) for n in rp_narrations | dw_narrations}

    total = len(bank_rows)
    transactions = []
    for index, row in enumerate(bank_rows):
        sl_no = str(row.get("SL#", ""))
        reference = str(row.get("REFERENCE", "")).strip()
        source_sheet = str(row.get("source_sheet", "")).strip() or None

        # Extracted before the try block (rather than as its first line) so
        # it's always available in the except branch below too, regardless
        # of which later field fails to parse - _normalize_business_unit()
        # itself can never raise.
        business_unit = _normalize_business_unit(row.get("BUSINESS UNIT", ""))

        try:
            description = row.get("DESCRIPTION", "")
            # The source file's own pretty-formatted NARRATION column
            # (computed by the user's bank-statement spreadsheet) is what
            # gets written to the ERP output - description stays the raw
            # DESCRIPTION value used only for classification/payee parsing
            # below, never written out. When the file's NARRATION cell is
            # blank (e.g. the accounts team's formula hadn't recalculated
            # yet at export time), compute it ourselves via the same
            # formula rather than falling straight to the raw description.
            narration = (
                str(row.get("NARRATION", "")).strip()
                or _compute_narration_from_formula(row, source_sheet.upper() if source_sheet else "")
                or description
            )
            debit = _parse_amount(str(row.get("DEBITS", "")))
            credit = _parse_amount(str(row.get("CREDITS", "")))
            txn_date = _parse_txn_date(str(row["TXN DATE"]))
            existing_head = str(row.get("HEAD", "")).strip()

            classification = classifier.classify_transaction(
                description, existing_head=existing_head, is_credit=credit > 0, source_sheet=source_sheet
            )

            reference_digits = master_repository._digits_only(reference)
            is_duplicate = len(reference_digits) >= 4 and any(
                reference_digits in existing for existing in existing_narration_digits
            )

            if is_duplicate:
                logger.info(f"[{run_id}] Skipping duplicate SL#{sl_no} (reference={reference})")
                ledger_repository.log_audit(
                    run_id, "info", f"Skipped duplicate SL#{sl_no}", {"reference": reference}
                )
                original_dest = (
                    "receipt_payment"
                    if any(reference_digits in master_repository._digits_only(n) for n in rp_narrations)
                    else "deposit_withdrawal"
                )
                transactions.append(
                    TransactionRowSet(
                        sl_no=sl_no,
                        reference=reference,
                        description=description,
                        debit=0,
                        credit=0,
                        business_unit=business_unit,
                        txn_date=txn_date,
                        classification=classification,
                        destination="duplicate",
                        destination_sheet="receipt/payment" if original_dest == "receipt_payment" else "deposit/withdrawal",
                        source_sheet=source_sheet,
                        narration=narration,
                    )
                )
            else:
                # Internal transfers appear twice across the combined bank
                # statements - once as a Debit on the sending account, once
                # as a Credit on the receiving account. Recording both would
                # double the transfer in the ERP, so only the Debit leg is
                # written to Deposit/Withdrawal; the Credit leg is skipped
                # entirely (not written to any of the three tabs).
                destination = (
                    "skipped_internal_credit"
                    if classification.is_internal and debit == 0 and credit > 0
                    else "review"
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
                        business_unit=business_unit,
                        txn_date=txn_date,
                        classification=classification,
                        destination=destination,
                        source_sheet=source_sheet,
                        narration=narration,
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
                    business_unit=business_unit,
                    txn_date=datetime.now(),
                    classification=classifier.ClassificationResult(
                        is_internal=False, head="", payee_name=None, matched_master_row=None, needs_review=True,
                        review_reason=f"Processing error: {exc}",
                    ),
                    destination="error",
                    review_reason=str(exc),
                    source_sheet=source_sheet,
                    narration=str(row.get("NARRATION", "")).strip() or str(row.get("DESCRIPTION", "")),
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


def _load_override_rule_index(run_id: str) -> override_rules.RuleIndex:
    """Loaded once per run (not per transaction) - see override_rules.py for
    the matching logic itself. Failing to load (Supabase unreachable, table
    not created yet, ...) degrades to "no overrides applied" rather than
    blocking the whole automation run."""
    try:
        active_rules = override_rules_repository.list_active()
        return override_rules.build_rule_index(active_rules)
    except Exception as exc:
        logger.warning(f"[{run_id}] Failed to load override rules, continuing without them: {exc}")
        ledger_repository.log_audit(
            run_id, "warning", "Failed to load override rules", {"error": str(exc)}
        )
        return {}


def _assign_rows(transactions: list[TransactionRowSet], settings, run_id: str) -> None:
    dw_next_ref = ref_code.get_next_ref_code(settings.DEPOSIT_WITHDRAWAL_SHEET_ID, "DepositWithdrawal")
    rp_next_ref = ref_code.get_next_ref_code(settings.RECEIPT_PAYMENT_SHEET_ID, "ReceiptPayment")
    rule_index = _load_override_rule_index(run_id)

    for txn in transactions:
        if txn.destination not in ("receipt_payment", "deposit_withdrawal"):
            continue

        try:
            rows = (
                _build_receipt_payment_rows(txn, rp_next_ref)
                if txn.destination == "receipt_payment"
                else _build_deposit_withdrawal_rows(txn, dw_next_ref)
            )

            # Override Rules run after classification/row-generation but before
            # validation - only ever replacing the LedgerDetails Account Head
            # already computed above (and, to keep the two consistent with each
            # other, Parent Account Head re-resolved from Master for that new
            # Account Head - see below). Narration parsing, payee extraction,
            # head classification, duplicate detection, and validation itself
            # are all untouched by this.
            override = override_rules.find_override(
                txn.description, txn.classification.head, txn.source_sheet, rule_index
            )
            if override:
                rows["LedgerDetails"][0]["Account Head"] = override
                # Without this, Parent Account Head would keep whatever the
                # *original* (pre-override) payee's Master row had - a
                # combination that may not exist in Master at all (e.g.
                # Account Head "IMPREST SITE IDW" paired with the old payee's
                # "SALARY PAYABLE"). Re-look-up the new Account Head itself so
                # the two fields always agree with Master - even when Master's
                # own value for it is blank.
                override_company = master_repository.resolve_company(txn.source_sheet)
                override_master_match = master_repository.find_party(override, company=override_company)
                if override_master_match is not None:
                    rows["LedgerDetails"][0]["Parent Account Head"] = override_master_match.get("Parent Account Head", "")

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

            # Routing to Review is driven only by real validation failures
            # (missing required fields, checked above) - not by a missing Master
            # Description. Business rule: Internal head -> Deposit/Withdrawal,
            # every other head (Contractor/Vendor/Imprest/Collection/...) ->
            # Receipt/Payment, regardless of whether Master has a Description
            # for the payee. When Description is missing, ImportTaxInfo simply
            # has no TDS/GST rows for that transaction (see
            # _build_import_tax_info_rows) rather than blocking the whole row.
            txn.rows = rows
            if txn.destination == "receipt_payment":
                rp_next_ref += 1
            else:
                dw_next_ref += 1
        except Exception as exc:
            # Row-building/Override Rules/Master lookups are otherwise
            # unguarded here - a single transaction hitting an unexpected
            # error (e.g. a transient Master/Sheets failure) must not take
            # down the whole run, same convention as _process_rows_stream's
            # per-row except block above.
            logger.error(f"[{run_id}] Failed to assign rows for SL#{txn.sl_no}: {exc}")
            ledger_repository.log_audit(
                run_id, "error", f"Failed to assign rows for SL#{txn.sl_no}", {"reference": txn.reference, "error": str(exc)}
            )
            txn.destination = "error"
            txn.review_reason = str(exc)


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


def _distinct_sheet_names(bank_rows: list[dict]) -> list[str]:
    """Source tab name(s) actually used by a run (an upload with no sheet
    chosen can span several) - empty for runs against the plain configured
    Google Sheet, which has no per-row "source_sheet" tag."""
    return sorted({row["source_sheet"] for row in bank_rows if row.get("source_sheet")})


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

    bank_rows = rows if rows is not None else _read_bank_rows_from_sheet()
    total = len(bank_rows)
    sheet_names = _distinct_sheet_names(bank_rows)

    logger.info(f"[{run_id}] Automation run started (dry_run={dry_run}, source={'upload' if rows is not None else 'sheet'})")
    ledger_repository.log_audit(
        run_id, "info", "Automation run started",
        {"dry_run": dry_run, "source": "upload" if rows is not None else "sheet", "sheet_names": sheet_names},
    )

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
        skipped_internal_credit=sum(1 for t in transactions if t.destination == "skipped_internal_credit"),
        transactions=transactions,
    )

    logger.info(
        f"[{run_id}] Automation run completed: "
        f"{result.routed_receipt_payment} receipt/payment, "
        f"{result.routed_deposit_withdrawal} deposit/withdrawal, "
        f"{result.needs_review} needs review, "
        f"{result.duplicates_skipped} duplicates skipped, "
        f"{result.skipped_internal_credit} internal-credit legs skipped"
    )
    ledger_repository.log_audit(
        run_id, "info", "Automation run completed",
        {
            "routed_receipt_payment": result.routed_receipt_payment,
            "routed_deposit_withdrawal": result.routed_deposit_withdrawal,
            "needs_review": result.needs_review,
            "duplicates_skipped": result.duplicates_skipped,
            "skipped_internal_credit": result.skipped_internal_credit,
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
