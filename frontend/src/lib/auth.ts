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
//
// `origin` is required because NEXT_PUBLIC_API_BASE_URL is often a relative
// path (e.g. "/api/v1" - see vercel.json's rewrite of /api/v1/* to the
// Python backend on this same domain). That's fine for browser fetches,
// which resolve relative URLs against the current page automatically, but
// Node's server-side fetch() has no implicit origin and throws on a
// relative string - silently swallowed by the catch below, which used to
// make every password look "incorrect" regardless of what was typed. Same
// fix as /api/clear-sheet/route.ts's backendUrl construction.
export async function checkPassword(candidate: string, origin: string): Promise<boolean> {
  try {
    const url = new URL(`${API_BASE_URL}/auth/verify-password`, origin);
    const response = await fetch(url, {
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
