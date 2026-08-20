from collections import Counter
from dataclasses import dataclass
import re

from app.services import account_head_resolver, master_repository
from app.services.description_parser import IFSC_PATTERN, parse_description


@dataclass
class ClassificationResult:
    is_internal: bool
    head: str
    payee_name: str | None
    matched_master_row: dict | None
    needs_review: bool
    review_reason: str | None = None
    bank_name: str | None = None
    counterparty_account: str | None = None  # destination account number for TPT-shaped internal transfers
    account_head_ambiguous: bool = False  # this payee matched 2+ Master rows with no confident auto-pick - matched_master_row is a placeholder, needs an in-sheet dropdown
    account_head_candidates: list[dict] | None = None  # deduped candidate rows, only set when account_head_ambiguous - used to build the dropdown
    no_match_dropdown_options: list[str] | None = None  # trusted head has a known Parent Account Head mapping but no payee name could be extracted at all - offers every Master payee under that Parent Account Head as a dropdown instead of silently writing a placeholder
    no_match_parent_account_head: str | None = None  # the mapped Parent Account Head value to pre-fill when no_match_dropdown_options is set - every option in that dropdown shares this same value, so it's already correct regardless of which one gets picked


def _derive_head(master_row: dict) -> str:
    """Best-effort category label from a matched Master row.

    Confirmed: classification is by Master lookup on payee name. The exact
    column used to derive the display Head label (Contractor/Vendor/etc.)
    is not yet fully confirmed with Accounts — this falls back sensibly
    when Parent Account Head doesn't contain a recognizable category.
    """
    parent = str(master_row.get("Parent Account Head", "")).strip()
    if "CONTRACTOR" in parent.upper():
        return "Contractor"
    if parent:
        return parent
    return str(master_row.get("Account Head") or "Unclassified")


# Patterns that indicate a plain-name description (no NEFT/RTGS/TPT/UPI/
# IMPS prefix). A description that matches none of these will be treated
# as a raw payee name.
_STRUCTURED_PREFIX_RE = re.compile(
    r"^(YIB-|NEFT|RTGS|IMPS|UPI|TPT|ACH|CHQ)", re.IGNORECASE
)


def _extract_fallback_payee(description: str) -> str | None:
    """Best-effort payee name extraction when the description parser returns
    nothing useful. Handles two cases:

    1. Plain-name descriptions — the description IS the payee name (e.g.
       "DWARKADHIS PROJECTS PVT LTD", "VANDANA KHULLAR", "Avnish Singh").
    2. Dash-joined descriptions with no IFSC and no recognizable prefix
       (e.g. "NEFT Cr-IFSC-Payee-Ref") — return the last meaningful token
       which is typically the payee in credit-style formats.
    """
    desc = description.strip()
    if not desc:
        return None

    # Already looked at structured parsing first — if there's a known
    # channel/mode prefix we've already done our best.
    if _STRUCTURED_PREFIX_RE.match(desc):
        # For dash-joined credit formats like "NEFT Cr-IDFB0021001-Mrs. ANSHU
        # SHARMA-DWARKADHIS", the parser handled the IFSC-before-payee case
        # and may have returned an empty payee. Try the token between IFSC
        # and the end-of-description trailing token as a fallback.
        tokens = desc.split("-")
        # Look for IFSC anywhere — the last one is the real one.
        ifsc_positions = [
            i for i, t in enumerate(tokens) if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", t.strip())
        ]
        if ifsc_positions:
            last_ifsc = ifsc_positions[-1]
            # Everything after the IFSC: one token might be the payee.
            candidates = tokens[last_ifsc + 1:]
            candidates = [c.strip() for c in candidates if c.strip()]
            # Skip obvious non-name tokens (IFSC codes, head labels, etc.)
            for c in candidates:
                if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", c) and c.upper() not in (
                    "CONTRACTOR", "VENDOR", "BANK CHARGES", "INTERNAL", "RECEIPT",
                ):
                    return c
        return None

    # No structured prefix → likely a raw payee name in the description.
    # Clean it up: truncate at a long dash or bank-code suffix, strip
    # account-number fragments, and return what's left.
    clean = re.sub(r"\s*[-–]\s*\d{8,}", "", desc).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean or None


# Maps a trusted "Head" label from the bank statement (normalized lowercase)
# to the real Master Parent Account Head value to offer as a category
# dropdown when that head has no extractable payee name at all (e.g. an IMPS
# narration truncated to just the counterparty bank name, "STATE BANK OF I").
# Deliberately starts with only the one confirmed case - other head labels
# (Vendor, Contractor, Imprest, ...) keep today's silent-placeholder
# behavior until a real unresolvable case for them is confirmed the same
# way this one was, rather than guessing a mapping upfront.
_HEAD_TO_PARENT_ACCOUNT_HEAD = {
    "salary site": "SALARY PAYABLE",
}


_GENERIC_PAYEE_LABELS = {
    "CONTRACTOR", "VENDOR", "BANK CHARGES", "INTERNAL", "RECEIPT", "COLLECTION", "IMPREST",
}


def _positional_fallback_payee(description: str) -> str | None:
    """Last-resort extraction reusing the exact heuristic already proven in
    automation_engine._compute_narration_from_formula (5th "/"-segment, else
    4th "-"-segment) - both functions run on the same raw DESCRIPTION for
    the same row (confirmed: automation_engine._process_rows_stream passes
    row["DESCRIPTION"] to both), and this positional split has recovered
    real payee names, confirmed against live production data, that the
    IFSC-anchored parsing above (parse_description/_extract_fallback_payee)
    missed entirely - e.g. falling back to the counterparty bank name or the
    generic Head label instead of the real beneficiary.

    Unlike the narration-formula version, never falls back to the whole raw
    description as a "candidate" (fine for cosmetic display text, not a
    safe Master-lookup key) and rejects a result that's just a generic
    label (e.g. "vendor") rather than a real name - those cases genuinely
    have no recoverable payee in the source data.
    """
    desc = description.strip()
    if not desc:
        return None
    slash_parts = desc.split("/")
    dash_parts = desc.split("-")
    if len(slash_parts) >= 6:
        candidate = slash_parts[4].strip()
    elif len(dash_parts) >= 5:
        candidate = dash_parts[3].strip()
    else:
        return None
    if not candidate or candidate.upper() in _GENERIC_PAYEE_LABELS:
        return None
    # Same reference/tracking-code exclusions description_parser.py's own
    # bank-name search already applies (RRN:/PC-prefixed tokens, IFSC codes,
    # bare digit strings) - without this, a slash-delimited narration whose
    # 5th segment happens to be a reference number (not the payee) would
    # return that code instead of correctly falling through to bank_name.
    if candidate.isdigit() or IFSC_PATTERN.match(candidate) or candidate.upper().startswith(("RRN", "PC")):
        return None
    return candidate


def classify_transaction(
    description: str,
    existing_head: str | None = None,
    is_credit: bool | None = None,
    source_sheet: str | None = None,
    context_text: str | None = None,
    history: dict[str, Counter] | None = None,
) -> ClassificationResult:
    """Classify a transaction. If ``existing_head`` is provided (non-empty —
    e.g. already filled in on an uploaded statement), it's trusted for the
    Internal/Non-Internal decision and displayed head label instead of being
    re-derived, but a Master lookup still runs to populate Account
    Head/Parent Account Head/Payment Mode needed for the output rows.

    ``is_credit`` (money coming in vs. going out) disambiguates which side
    of a UPI narration's "From:"/"To:" pair is the actual counterparty -
    see description_parser._parse_upi().

    ``source_sheet`` resolves which company's Master rows apply (see
    master_repository.resolve_company()) - Master mixes two companies'
    charts of accounts.

    ``context_text`` (the transaction's display narration, including any
    "Purpose: ..." text) and ``history`` (a {normalized payee: Counter of
    previously-written (Account Head, Parent Account Head) pairs} index) are
    only used to disambiguate a beneficiary that matches more than one
    Master row - see account_head_resolver.resolve(). Both default to
    None/empty, which just means every such beneficiary is flagged ambiguous
    instead of auto-resolved.
    """
    parsed = parse_description(description, is_credit=is_credit)
    # parsed.bank_name is a weak last resort (see description_parser.py's
    # own docstring) - the positional fallback below has recovered a real
    # beneficiary name in live production cases where parsed.payee_name and
    # _extract_fallback_payee both found nothing and the code used to fall
    # straight to the bank name instead. Consulted only when both of those
    # already came up empty, so a row that already resolves correctly today
    # is completely unaffected.
    payee_name = (
        parsed.payee_name
        or _extract_fallback_payee(description)
        or _positional_fallback_payee(description)
        or parsed.bank_name
    )
    trusted_head = existing_head.strip() if existing_head else ""
    company = master_repository.resolve_company(source_sheet, parsed.bank_name)

    if trusted_head:
        if trusted_head.upper() == "INTERNAL":
            # Internal transfers stay "Internal"/not-needing-review regardless
            # of whether Master has this counterparty - but still look it up,
            # so a real Bank Name (etc.) can be pulled from Master when it
            # does have an entry for them.
            #
            # Deliberately NOT also checking parsed.is_internal_format here:
            # that's a narration-shape heuristic (no IFSC found) meant only
            # for rows with no trusted head at all. A trusted head that says
            # something other than "Internal" (e.g. "Bank Charges") must win
            # even if the narration has no IFSC ("POS GST" never will) -
            # otherwise every non-NEFT/RTGS narration gets silently
            # relabelled "Internal" regardless of what the file actually says.
            internal_matched = master_repository.find_party(payee_name, company=company)
            return ClassificationResult(
                is_internal=True,
                head="Internal",
                payee_name=payee_name,
                matched_master_row=internal_matched,
                needs_review=False,
                bank_name=parsed.bank_name,
                counterparty_account=parsed.counterparty_account,
            )

        # A trusted, non-Internal head from the statement (Contractor/Vendor/
        # etc.) is enough on its own to route to Receipt/Payment - a Master
        # match is only used to fill in extra fields (Account Head, Bank
        # Name, ...) when available, not required for routing.
        candidates = master_repository.find_party_candidates(payee_name, company=company)
        resolved = account_head_resolver.resolve(
            payee_name, company, candidates, context_text=context_text, history=history
        )

        no_match_dropdown_options = None
        no_match_parent_account_head = None
        if resolved.row is None and resolved.reason == "no_match":
            mapped_parent = _HEAD_TO_PARENT_ACCOUNT_HEAD.get(trusted_head.strip().lower())
            if mapped_parent:
                options = master_repository.list_payees_by_parent_account_head(mapped_parent, company=company)
                if options:
                    no_match_dropdown_options = options
                    no_match_parent_account_head = mapped_parent

        return ClassificationResult(
            is_internal=False,
            head=trusted_head,
            payee_name=payee_name,
            matched_master_row=resolved.row,
            needs_review=False,
            bank_name=parsed.bank_name,
            account_head_ambiguous=resolved.ambiguous,
            account_head_candidates=resolved.candidates if resolved.ambiguous else None,
            no_match_dropdown_options=no_match_dropdown_options,
            no_match_parent_account_head=no_match_parent_account_head,
        )

    if parsed.is_internal_format:
        internal_matched = master_repository.find_party(payee_name, company=company)
        return ClassificationResult(
            is_internal=True,
            head="Internal",
            payee_name=payee_name,
            matched_master_row=internal_matched,
            needs_review=False,
            bank_name=parsed.bank_name,
            counterparty_account=parsed.counterparty_account,
        )

    candidates = master_repository.find_party_candidates(payee_name, company=company)
    resolved = account_head_resolver.resolve(
        payee_name, company, candidates, context_text=context_text, history=history
    )
    matched = resolved.row

    if matched is None:
        # No Master match for the extracted payee name. Instead of blocking
        # the transaction in Review (which stalls the pipeline for IMPS
        # narrations where the bank's "NA" placeholder leaves the payee
        # unknown), route to receipt_payment with "Unclassified" head.
        # The Accounts team can correct the head manually in the ERP.
        return ClassificationResult(
            is_internal=False,
            head="Unclassified",
            payee_name=payee_name,
            matched_master_row=None,
            needs_review=False,
            bank_name=parsed.bank_name,
        )

    return ClassificationResult(
        is_internal=False,
        head=_derive_head(matched),
        payee_name=payee_name,
        matched_master_row=matched,
        needs_review=False,
        bank_name=parsed.bank_name,
        account_head_ambiguous=resolved.ambiguous,
        account_head_candidates=resolved.candidates if resolved.ambiguous else None,
    )
