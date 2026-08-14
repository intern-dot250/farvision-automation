from app.core.logger import logger
from app.services import supabase_client


def log_audit(run_id: str, level: str, message: str, context: dict | None = None) -> None:
    """Best-effort audit log write - Supabase being unreachable (paused
    project, rotated key, network issue, ...) must never take down the
    actual automation run. Failures here are logged locally and swallowed,
    same "degrade gracefully" convention as _load_override_rule_index in
    automation_engine.py."""
    try:
        supabase_client.get_client().table("audit_log").insert(
            {
                "run_id": run_id,
                "level": level,
                "message": message,
                "context": context,
            }
        ).execute()
    except Exception as exc:
        logger.warning(f"[{run_id}] Failed to write audit log ({message}): {exc}")
