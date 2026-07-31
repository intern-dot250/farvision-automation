from dataclasses import dataclass
import re

from app.services import master_repository
from app.services.description_parser import parse_description


@dataclass
class ClassificationResult:
    is_internal: bool
    head: str
    payee_name: str | None
    matched_master_row: dict | None
    needs_review: bool
    review_reason: str | None = None
    bank_name: str | None = None


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


def classify_transaction(
    description: str, existing_head: str | None = None, is_credit: bool | None = None
) -> ClassificationResult:
    """Classify a transaction. If ``existing_head`` is provided (non-empty —
    e.g. already filled in on an uploaded statement), it's trusted for the
    Internal/Non-Internal decision and displayed head label instead of being
    re-derived, but a Master lookup still runs to populate Account
    Head/Parent Account Head/Payment Mode needed for the output rows.

    ``is_credit`` (money coming in vs. going out) disambiguates which side
    of a UPI narration's "From:"/"To:" pair is the actual counterparty -
    see description_parser._parse_upi().
    """
    parsed = parse_description(description, is_credit=is_credit)
    payee_name = parsed.payee_name or _extract_fallback_payee(description)
    trusted_head = existing_head.strip() if existing_head else ""

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
            internal_matched = master_repository.find_party(payee_name)
            return ClassificationResult(
                is_internal=True,
                head="Internal",
                payee_name=payee_name,
                matched_master_row=internal_matched,
                needs_review=False,
                bank_name=parsed.bank_name,
            )

        # A trusted, non-Internal head from the statement (Contractor/Vendor/
        # etc.) is enough on its own to route to Receipt/Payment - a Master
        # match is only used to fill in extra fields (Account Head, Bank
        # Name, ...) when available, not required for routing.
        matched = master_repository.find_party(payee_name)

        return ClassificationResult(
            is_internal=False,
            head=trusted_head,
            payee_name=payee_name,
            matched_master_row=matched,
            needs_review=False,
            bank_name=parsed.bank_name,
        )

    if parsed.is_internal_format:
        internal_matched = master_repository.find_party(payee_name)
        return ClassificationResult(
            is_internal=True,
            head="Internal",
            payee_name=payee_name,
            matched_master_row=internal_matched,
            needs_review=False,
            bank_name=parsed.bank_name,
        )

    matched = master_repository.find_party(payee_name)

    if matched is None:
        return ClassificationResult(
            is_internal=False,
            head="Unclassified",
            payee_name=payee_name,
            matched_master_row=None,
            needs_review=True,
            review_reason=f"No Master match for payee '{payee_name}'",
            bank_name=parsed.bank_name,
        )

    return ClassificationResult(
        is_internal=False,
        head=_derive_head(matched),
        payee_name=payee_name,
        matched_master_row=matched,
        needs_review=False,
        bank_name=parsed.bank_name,
    )
