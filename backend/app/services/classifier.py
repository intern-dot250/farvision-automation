from dataclasses import dataclass

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


def classify_transaction(description: str, existing_head: str | None = None) -> ClassificationResult:
    """Classify a transaction. If ``existing_head`` is provided (non-empty —
    e.g. already filled in on an uploaded statement), it's trusted for the
    Internal/Non-Internal decision and displayed head label instead of being
    re-derived, but a Master lookup still runs to populate Account
    Head/Parent Account Head/Payment Mode needed for the output rows.
    """
    parsed = parse_description(description)
    trusted_head = existing_head.strip() if existing_head else ""

    if trusted_head:
        if trusted_head.upper() == "INTERNAL" or parsed.is_internal_format:
            # Internal transfers stay "Internal"/not-needing-review regardless
            # of whether Master has this counterparty - but still look it up,
            # so a real Bank Name (etc.) can be pulled from Master when it
            # does have an entry for them.
            internal_matched = master_repository.find_party(parsed.payee_name)
            return ClassificationResult(
                is_internal=True,
                head="Internal",
                payee_name=parsed.payee_name,
                matched_master_row=internal_matched,
                needs_review=False,
                bank_name=parsed.bank_name,
            )

        matched = master_repository.find_party(parsed.payee_name)

        return ClassificationResult(
            is_internal=False,
            head=trusted_head,
            payee_name=parsed.payee_name,
            matched_master_row=matched,
            needs_review=matched is None,
            review_reason=(
                None if matched else f"No Master match for payee '{parsed.payee_name}' (given head: {trusted_head})"
            ),
            bank_name=parsed.bank_name,
        )

    if parsed.is_internal_format:
        internal_matched = master_repository.find_party(parsed.payee_name)
        return ClassificationResult(
            is_internal=True,
            head="Internal",
            payee_name=parsed.payee_name,
            matched_master_row=internal_matched,
            needs_review=False,
            bank_name=parsed.bank_name,
        )

    matched = master_repository.find_party(parsed.payee_name)

    if matched is None:
        return ClassificationResult(
            is_internal=False,
            head="Unclassified",
            payee_name=parsed.payee_name,
            matched_master_row=None,
            needs_review=True,
            review_reason=f"No Master match for payee '{parsed.payee_name}'",
            bank_name=parsed.bank_name,
        )

    return ClassificationResult(
        is_internal=False,
        head=_derive_head(matched),
        payee_name=parsed.payee_name,
        matched_master_row=matched,
        needs_review=False,
        bank_name=parsed.bank_name,
    )
