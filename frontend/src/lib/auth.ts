import "server-only";
import crypto from "crypto";
import { API_BASE_URL } from "@/lib/api-client";

export const SESSION_COOKIE = "fv_session";

// Deterministic HMAC of a fixed label, keyed by a static session secret -
// only derivable server-side, so it can't be forged by a client just
// setting a guessable cookie value like "authenticated=true". Deliberately
// independent of the dashboard password (which now lives in Supabase and is
// resettable) so this middleware-facing check never needs a network/DB call.
export function getExpectedSessionValue(): string {
  const secret = process.env.SESSION_SECRET ?? "";
  return crypto.createHmac("sha256", secret).update("fv-session").digest("hex");
}

// Verified against the backend (Supabase-backed, resettable) rather than a
// static env var - see backend/app/api/v1/auth.py's /verify-password.
export async function checkPassword(candidate: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/auth/verify-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: candidate }),
    });
    if (!response.ok) return false;
    const data = await response.json();
    return data?.valid === true;
  } catch {
    return false;
  }
}

export function isValidSession(cookieValue: string | undefined): boolean {
  if (!cookieValue) return false;
  const expected = getExpectedSessionValue();
  const a = Buffer.from(cookieValue);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}
