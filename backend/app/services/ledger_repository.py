from app.services import supabase_client


from typing import Set

from app.services import supabase_client


def is_already_processed_batch(references: list[str]) -> Set[str]:
    """Batch duplicate-detection: returns the subset of references already processed.

    Does a single Supabase query instead of N individual calls. Blank
    references are excluded - transactions without a bank reference number
    (e.g. some internal transfers) can't be reliably deduplicated this way,
    so they're always treated as new.
    """
    references = [r for r in references if r]
    if not references:
        return set()

    response = (
        supabase_client.get_client()
        .table("processed_transactions")
        .select("reference")
        .in_("reference", references)
        .execute()
    )
    return {row["reference"] for row in (response.data or [])}


def mark_processed(
    reference: str,
    sl_no: str,
    description: str,
    head: str,
    destination: str,
    link_ref_code: int | None,
) -> None:
    # Store blank references as NULL rather than "": the reference column is
    # UNIQUE, and Postgres allows unlimited NULLs under a UNIQUE constraint
    # but only one "" - multiple transactions can legitimately have no
    # reference number.
    supabase_client.get_client().table("processed_transactions").insert(
        {
            "reference": reference or None,
            "sl_no": sl_no,
            "description": description,
            "head": head,
            "destination": destination,
            "link_ref_code": link_ref_code,
        }
    ).execute()


def log_audit(run_id: str, level: str, message: str, context: dict | None = None) -> None:
    supabase_client.get_client().table("audit_log").insert(
        {
            "run_id": run_id,
            "level": level,
            "message": message,
            "context": context,
        }
    ).execute()
