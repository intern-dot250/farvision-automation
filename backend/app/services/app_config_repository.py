import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from app.services import supabase_client

APP_CONFIG_TABLE = "app_config"
RESET_TOKENS_TABLE = "password_reset_tokens"

# Single fixed row - there is exactly one dashboard password, not per-user
# credentials, so app_config never needs more than one row.
_PASSWORD_CONFIG_ID = 1

_PBKDF2_ITERATIONS = 260_000


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """PBKDF2-HMAC-SHA256, stored as "salt_hex$hash_hex". No new dependency
    (bcrypt/passlib aren't installed) - PBKDF2 via hashlib is stdlib and
    sufficiently strong for a single shared secret checked at a low request
    rate."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, _ = stored_hash.split("$", 1)
    except ValueError:
        return False
    candidate = _hash_password(password, bytes.fromhex(salt_hex))
    return secrets.compare_digest(candidate, stored_hash)


def get_password_hash() -> str | None:
    response = (
        supabase_client.get_client()
        .table(APP_CONFIG_TABLE)
        .select("password_hash")
        .eq("id", _PASSWORD_CONFIG_ID)
        .execute()
    )
    if not response.data:
        return None
    return response.data[0]["password_hash"]


def set_password(password: str) -> None:
    payload = {
        "id": _PASSWORD_CONFIG_ID,
        "password_hash": _hash_password(password),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase_client.get_client().table(APP_CONFIG_TABLE).upsert(payload).execute()


def seed_password_if_empty(password: str) -> None:
    """One-time migration helper - seeds app_config with a hash of the
    pre-existing static ACCESS_PASSWORD so today's password keeps working
    through the cutover to a DB-backed, resettable one. No-ops if a row
    already exists (never overwrites a password someone has already reset)."""
    if not password or get_password_hash() is not None:
        return
    set_password(password)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reset_token(ttl_minutes: int = 30) -> str:
    """Generates a random reset token, stores only its hash (the raw token
    is never persisted - only ever held by whoever clicked the emailed
    link), and returns the raw token for embedding in the email URL."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now.timestamp() + ttl_minutes * 60
    payload = {
        "token_hash": _hash_token(token),
        "created_at": now.isoformat(),
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        "used_at": None,
    }
    supabase_client.get_client().table(RESET_TOKENS_TABLE).insert(payload).execute()
    return token


def has_active_reset_token() -> bool:
    """Used to lightly rate-limit /auth/forgot-password - a non-expired,
    not-yet-used token already outstanding means a repeated click shouldn't
    trigger another email."""
    now_iso = datetime.now(timezone.utc).isoformat()
    response = (
        supabase_client.get_client()
        .table(RESET_TOKENS_TABLE)
        .select("id")
        .is_("used_at", "null")
        .gt("expires_at", now_iso)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def consume_reset_token(token: str) -> bool:
    """Validates the token is unexpired and unused, then atomically marks it
    used in the same request so it can never be replayed. Returns False for
    any invalid/expired/already-used token, without distinguishing which -
    the caller surfaces one generic "invalid or expired" message either
    way."""
    token_hash = _hash_token(token)
    now_iso = datetime.now(timezone.utc).isoformat()

    response = (
        supabase_client.get_client()
        .table(RESET_TOKENS_TABLE)
        .select("id")
        .eq("token_hash", token_hash)
        .is_("used_at", "null")
        .gt("expires_at", now_iso)
        .limit(1)
        .execute()
    )
    if not response.data:
        return False

    row_id = response.data[0]["id"]
    update_response = (
        supabase_client.get_client()
        .table(RESET_TOKENS_TABLE)
        .update({"used_at": now_iso})
        .eq("id", row_id)
        .is_("used_at", "null")
        .execute()
    )
    return bool(update_response.data)
