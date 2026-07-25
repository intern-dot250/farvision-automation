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


def classify_transaction(description: str) -> ClassificationResult:
    parsed = parse_description(description)

    if parsed.is_internal_format:
        return ClassificationResult(
            is_internal=True,
            head="Internal",
            payee_name=None,
            matched_master_row=None,
            needs_review=False,
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
        )

    return ClassificationResult(
        is_internal=False,
        head=_derive_head(matched),
        payee_name=parsed.payee_name,
        matched_master_row=matched,
        needs_review=False,
    )
