import crypto from "crypto";
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

export const STATE_COOKIE = "google_oauth_state";
export const INTENT_COOKIE = "google_oauth_intent";

// Starts the Authorization Code flow - redirects the browser to Google's
// consent screen. The state value is round-tripped through Google and
// compared against this cookie in the callback to guard against CSRF.
//
// ?intent=reset is set by the login page's dedicated "Forgot password?"
// button (as opposed to its "Continue with Google" button, which omits it) -
// both trigger the exact same Google sign-in, but the callback reads this
// cookie afterward to decide whether to land on the dashboard or send the
// user straight to Settings' "Change Password" section.
export async function GET(request: NextRequest) {
  const state = crypto.randomBytes(32).toString("hex");
  const intent = request.nextUrl.searchParams.get("intent") === "reset" ? "reset" : "";

  const cookieStore = await cookies();
  cookieStore.set(STATE_COOKIE, state, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 5,
  });
  if (intent) {
    cookieStore.set(INTENT_COOKIE, intent, {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 5,
    });
  }

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
