from app.services import supabase_client


def log_audit(run_id: str, level: str, message: str, context: dict | None = None) -> None:
    supabase_client.get_client().table("audit_log").insert(
        {
            "run_id": run_id,
            "level": level,
            "message": message,
            "context": context,
        }
    ).execute()
