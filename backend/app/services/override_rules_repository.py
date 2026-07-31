from datetime import datetime, timezone
from typing import Any

from app.services import supabase_client

TABLE = "override_rules"


def list_all() -> list[dict[str, Any]]:
    response = (
        supabase_client.get_client()
        .table(TABLE)
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return response.data


def list_active() -> list[dict[str, Any]]:
    response = (
        supabase_client.get_client()
        .table(TABLE)
        .select("*")
        .eq("is_active", True)
        .execute()
    )
    return response.data


def create(data: dict[str, Any]) -> dict[str, Any]:
    response = supabase_client.get_client().table(TABLE).insert(data).execute()
    return response.data[0]


def update(rule_id: int, data: dict[str, Any]) -> dict[str, Any]:
    payload = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    response = (
        supabase_client.get_client()
        .table(TABLE)
        .update(payload)
        .eq("id", rule_id)
        .execute()
    )
    return response.data[0]


def toggle(rule_id: int, is_active: bool) -> dict[str, Any]:
    return update(rule_id, {"is_active": is_active})


def delete(rule_id: int) -> None:
    supabase_client.get_client().table(TABLE).delete().eq("id", rule_id).execute()
