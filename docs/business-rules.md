# Phase 6 — Business Analysis

Derived from live inspection of the 3 real sheets (via `scripts/inspect_sheets.py`), not assumptions.

## 1. Sheet & Tab Inventory

| Sheet | Tabs |
|---|---|
| Statement/Master | `YES IDW 0490` (bank statement, 13 demo rows), `Master` (15,865 rows) |
| Deposit/Withdrawal | `DepositWithdrawal`, `DepositWithdrawalDetails`, `LedgerDetails`, `Info` |
| Receipt/Payment | `ReceiptPayment`, `ReceiptPaymentDetail`, `LedgerDetails`, `AdjustmentDetails`, `ImportTaxInfo`, `Info` |

**Key finding: each output "sheet" is not one flat table.** A single transaction becomes a linked set of rows across multiple tabs, joined by `Link Ref Code` (and `Detail Link Ref Code` for Receipt/Payment):

- Deposit/Withdrawal: 1 header row in `DepositWithdrawal` + 1 row in `DepositWithdrawalDetails` + 1+ rows in `LedgerDetails`, all sharing the same `Link Ref Code`.
- Receipt/Payment: 1 header row in `ReceiptPayment` + rows in `ReceiptPaymentDetail`, `LedgerDetails`, `AdjustmentDetails`, `ImportTaxInfo`, all sharing `Link Ref Code` + `Detail Link Ref Code`.

This means Phase 7's automation engine must write correlated rows across 3–5 tabs per transaction, not a single row in a single sheet.

## 2. Bank Statement tab (`YES IDW 0490`)

Columns: `SL#, QTR, MONTH, TXN DATE, VALUE DATE, TYPE, DESCRIPTION, REFERENCE, DEBITS, CREDITS, BALANCE, BUSINESS UNIT, HEAD, SUB HEAD, RECO, TYPE FOR RERA IDW, TCP Head, CONCERN, CUST ID, APT#, ACC REMARKS, CRM REMARKS, NARRATION`

**Important:** the `HEAD` column already exists and is already filled in on every row of this demo data — it is not blank/raw. Observed values: `Contractor`, `Vendor`, `Internal`. Every `Internal` row's `DESCRIPTION` is an inter-account transfer (`YIB-TPT-...`), every `Contractor`/`Vendor` row is a real NEFT payment to a third party. This matches the Internal → Deposit/Withdrawal, else → Receipt/Payment rule.

`DESCRIPTION` follows a consistent dash-delimited bank format, e.g.:
`YIB-NEFT-YESME62030018559-Rakiba BIBI-SBIN0007204-Contractor-STATE BANK OF INDIA`
→ `{channel}-{mode}-{UTR}-{payee name}-{IFSC}-{head}-{bank name}`

`NARRATION` is a synthesized pipe-delimited string: `Payment Disbursement (Purpose: ...) | To: ... | Ref: ... | BU: ... | Head: ...` — this looks like it's already been generated (by a human or a prior process), not raw bank data.

## 3. Master tab

Columns: `Company, Account Head, Parent Account Head, Document Type, Financial Year, Bank Name, Deduction Type, Description, EntryTypes, Debit/Credit, Payment Mode, Payee Name, Docno, Invoice No, Business Unit`

`Document Type` and `EntryTypes` contain values `RECEIPT / PAYMENT` or `Deposit / Withdrawal` directly — same wording as the two destination sheets. `Account Head`/`Payee Name` hold specific party names (e.g. `MUKESH KUMAR`).

**Unresolved:** in the 3 sample rows pulled, a Master row for `MUKESH KUMAR` shows `Document Type = Deposit / Withdrawal`, but the Bank Statement row for a NEFT payment to "Mukesh Kumar" has `HEAD = Contractor` (which per the confirmed rule should route to Receipt/Payment). This is either sample-data noise (15,865-row Master looks like placeholder/demo content — sequential dummy `Financial Year` values like `01-04-2026-31-03-2027`, `01-04-2027-31-03-2028`, `01-04-2029-31-03-2030` suggest generated, not real, data) or a sign that Master lookup isn't purely by name. Needs confirmation — see open questions.

## 4. Required Fields & Validation Rules (from the `Info` tabs — authoritative, not inferred)

### Deposit/Withdrawal
| Tab | Column | Rule |
|---|---|---|
| DepositWithdrawal | Link Ref Code | Required |
| DepositWithdrawal | DepositWithdrawal Business Unit | Optional, 10–500 chars |
| DepositWithdrawal | DepositWithdrawal Narration | Optional, 10–500 chars |
| DepositWithdrawal | Financial Year | Required, 1–30 chars |
| DepositWithdrawal | Document Type | Required, 1–30 chars |
| DepositWithdrawal | Document Date | Required, 1–30 chars |
| DepositWithdrawal | Document No | Required, 1–30 chars |
| DepositWithdrawalDetails | Link Ref Code | Required |
| LedgerDetails | Link Ref Code, Debit/Credit, Account Head, Parent Account Head, Payment Mode, Payee Name | Required |
| LedgerDetails | Debit Amount, Credit Amount, Print Cheque | Optional |

### Receipt/Payment
| Tab | Column | Rule |
|---|---|---|
| ReceiptPayment | Link Ref Code | Required |
| ReceiptPayment | Business Unit | Optional, 10–500 chars |
| ReceiptPayment | Financial Year, Document Type, Document Date, Document No | Required |
| ReceiptPayment | Narration | Optional, 0–500 chars |
| ReceiptPaymentDetail | Link Ref Code, Detail Link Ref Code | Required |
| LedgerDetails | Link Ref Code, Detail Link Ref Code, Document Type, Debit/Credit, Account Head, Parent Account Head, Payment Mode, Payee Name | Required |
| LedgerDetails | Business Unit | Optional, 10–500 chars |
| LedgerDetails | Debit Amount, Credit Amount, Beneficiary, Sub Project, Budget, Zone, Department, Order, Milestone, Tower, Segment, Employee(+Name), Department Name, Cost Center, Purpose Of Payment | Optional |
| AdjustmentDetails | Link Ref Code, Detail Link Ref Code, Docno, Date, Adjustment Amount | Required |
| AdjustmentDetails | Invoice No, Invoice Date, Bill Amount, Balance Amount | Optional |
| ImportTaxInfo | Link Ref Code, Detail Link Ref Code, Deduction Type, Description | Required |

## 5. Confirmed Business Rules (2026-07-25)

1. **`HEAD` is NOT pre-filled in real bank statements.** Real statements arrive without a Head; the Accounts team currently determines it manually today. The demo data shows the *after* state — classification is a real problem Phase 7 must solve, not just routing an already-known Head.
2. **Classification lookup:** match the transaction's counterparty/payee name against Master's `Payee Name` / `Account Head` column. The matched Master row's category determines the HEAD (working detail — e.g. via `Parent Account Head` — still to be nailed down precisely once we build the matcher, but the lookup key is confirmed as payee name → Master).
3. **Internal detection:** a transaction is `Internal` when it does **not** match any party in Master, and the counterparty is recognized as one of the company's own bank accounts (not an explicit separate account allowlist — no-match-in-Master is the trigger, combined with recognizing it's an inter-account transfer).
4. **LedgerDetails cardinality:** always exactly **1** `LedgerDetails` row per Receipt/Payment transaction — no splitting for TDS/tax deductions in the current scope. Simplifies the write logic: 1 transaction → 1 row in each relevant tab.
5. **Link Ref Code numbering:** continue from the current max value already present in the destination sheet (`max(existing Link Ref Code) + 1` for each new transaction, sequentially).

## 6. Remaining Design Detail (not blocking, to refine during Phase 7 build)

- The exact Master column(s) used to turn a matched row into a specific HEAD label (`Contractor` vs `Vendor` vs others) — likely `Parent Account Head`, to be finalized against real data while building the classifier, since the demo Master data looks partly synthetic (sequential dummy `Financial Year` values) and shouldn't be over-trusted row-for-row.
- Exactly which Master column recognizes "one of our own bank accounts" for Internal detection (e.g. is there a dedicated indicator, or is it purely "no match found" + description keyword check like `internal`/`TPT`).

## 7. See also

The Master-matching rule in section 5 has since grown into a full multi-layer resolution
system (fuzzy-match tiers, ambiguous/no-match/dead-end dropdowns, keyword scoping) —
see [`docs/account-head-resolution-rules.md`](account-head-resolution-rules.md) for the
current decision rules governing it.
