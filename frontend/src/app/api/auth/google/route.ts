import crypto from "crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const STATE_COOKIE = "google_oauth_state";

// Starts the Authorization Code flow - redirects the browser to Google's
// consent screen. The state value is round-tripped through Google and
// compared against this cookie in the callback to guard against CSRF.
export async function GET() {
  const state = crypto.randomBytes(32).toString("hex");

  const cookieStore = await cookies();
  cookieStore.set(STATE_COOKIE, state, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 5,
  });

  const params = new URLSearchParams({
    client_id: process.env.GOOGLE_CLIENT_ID ?? "",
    redirect_uri: process.env.GOOGLE_OAUTH_REDIRECT_URI ?? "",
    response_type: "code",
    scope: "openid email",
    state,
    prompt: "select_account",
  });

  return NextResponse.redirect(`https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`);
}
