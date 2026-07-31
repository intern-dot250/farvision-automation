import "server-only";
import crypto from "crypto";

export const SESSION_COOKIE = "fv_session";

// Deterministic HMAC of a fixed label, keyed by the shared password - only
// derivable server-side (requires ACCESS_PASSWORD), so it can't be forged
// by a client just setting a guessable cookie value like "authenticated=true".
export function getExpectedSessionValue(): string {
  const password = process.env.ACCESS_PASSWORD ?? "";
  return crypto.createHmac("sha256", password).update("fv-session").digest("hex");
}

export function checkPassword(candidate: string): boolean {
  const expected = process.env.ACCESS_PASSWORD ?? "";
  const a = Buffer.from(candidate);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

export function isValidSession(cookieValue: string | undefined): boolean {
  if (!cookieValue) return false;
  const expected = getExpectedSessionValue();
  const a = Buffer.from(cookieValue);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}
