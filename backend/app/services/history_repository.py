from collections import defaultdict
from typing import Any

from app.core.config import get_settings
from app.services import sheets_client, supabase_client


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
            run["sheet_names"] = context.get("sheet_names")
        else:
            run["completed_at"] = row["created_at"]
            run["routed_receipt_payment"] = context.get("routed_receipt_payment")
            run["routed_deposit_withdrawal"] = context.get("routed_deposit_withdrawal")
            run["needs_review"] = context.get("needs_review")
            run["duplicates_skipped"] = context.get("duplicates_skipped")
            run["skipped_internal_credit"] = context.get("skipped_internal_credit")

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
    """Stats reflect the real Google Sheets directly, not the Supabase
    duplicate-detection ledger - Accounts only ever looks at the Sheets and
    this dashboard, never Supabase, so the numbers shown here should match
    exactly what's actually in the Sheets (including if rows are ever
    manually deleted there).
    """
    settings = get_settings()
    total_receipt_payment = sheets_client.count_data_rows(settings.RECEIPT_PAYMENT_SHEET_ID, "ReceiptPayment")
    total_deposit_withdrawal = sheets_client.count_data_rows(settings.DEPOSIT_WITHDRAWAL_SHEET_ID, "DepositWithdrawal")

    return {
        "total_processed": total_receipt_payment + total_deposit_withdrawal,
        "total_receipt_payment": total_receipt_payment,
        "total_deposit_withdrawal": total_deposit_withdrawal,
    }
