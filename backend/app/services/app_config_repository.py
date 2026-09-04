import hashlib
import os
import secrets
from datetime import datetime, timezone

from app.services import supabase_client

APP_CONFIG_TABLE = "app_config"

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
