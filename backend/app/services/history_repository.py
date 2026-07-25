from collections import defaultdict
from typing import Any

from app.services import supabase_client


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Reconstruct run summaries from the 'started'/'completed' audit_log pair per run_id."""
    response = (
        supabase_client.get_client()
        .table("audit_log")
        .select("*")
        .in_("message", ["Automation run started", "Automation run completed"])
        .order("created_at", desc=False)
        .execute()
    )

    runs: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in response.data:
        run = runs[row["run_id"]]
        run["run_id"] = row["run_id"]
        context = row.get("context") or {}

        if row["message"] == "Automation run started":
            run["started_at"] = row["created_at"]
            run["dry_run"] = context.get("dry_run")
        else:
            run["completed_at"] = row["created_at"]
            run["routed_receipt_payment"] = context.get("routed_receipt_payment")
            run["routed_deposit_withdrawal"] = context.get("routed_deposit_withdrawal")
            run["needs_review"] = context.get("needs_review")
            run["duplicates_skipped"] = context.get("duplicates_skipped")

    ordered = sorted(runs.values(), key=lambda r: r.get("started_at") or "", reverse=True)
    return ordered[:limit]


def list_logs(limit: int = 100) -> list[dict[str, Any]]:
    response = (
        supabase_client.get_client()
        .table("audit_log")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data


def get_stats() -> dict[str, int]:
    client = supabase_client.get_client()

    def count(table: str, **filters: str) -> int:
        query = client.table(table).select("id", count="exact")
        for column, value in filters.items():
            query = query.eq(column, value)
        return query.execute().count or 0

    return {
        "total_processed": count("processed_transactions"),
        "total_receipt_payment": count("processed_transactions", destination="receipt_payment"),
        "total_deposit_withdrawal": count("processed_transactions", destination="deposit_withdrawal"),
        "total_runs": count("audit_log", message="Automation run started"),
    }
