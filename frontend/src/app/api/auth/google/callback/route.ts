import { OAuth2Client } from "google-auth-library";
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, getExpectedSessionValue } from "@/lib/auth";
import { INTENT_COOKIE, STATE_COOKIE } from "../route";

function loginRedirect(request: NextRequest, error: string) {
  return NextResponse.redirect(new URL(`/login?error=${error}`, request.url));
}

// Completes the Authorization Code flow: exchanges the code for tokens,
// verifies the ID token's signature server-side, and checks the verified
// email against a fixed allowlist - there are no per-user accounts in this
// app, just one shared dashboard session, so "linked to an existing user"
// means "is one of the addresses configured as authorized".
export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const expectedState = cookieStore.get(STATE_COOKIE)?.value;
  const intent = cookieStore.get(INTENT_COOKIE)?.value;
  cookieStore.delete(STATE_COOKIE);
  cookieStore.delete(INTENT_COOKIE);

  const searchParams = request.nextUrl.searchParams;
  const error = searchParams.get("error");
  const code = searchParams.get("code");
  const state = searchParams.get("state");

  if (error) {
    return loginRedirect(request, "google_cancelled");
  }

  if (!code || !state || !expectedState || state !== expectedState) {
    return loginRedirect(request, "google_failed");
  }

  try {
    const clientId = process.env.GOOGLE_CLIENT_ID ?? "";
    const clientSecret = process.env.GOOGLE_CLIENT_SECRET ?? "";
    const redirectUri = process.env.GOOGLE_OAUTH_REDIRECT_URI ?? "";

    const tokenResponse = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: clientId,
        client_secret: clientSecret,
        code,
        redirect_uri: redirectUri,
        grant_type: "authorization_code",
      }),
    });

    if (!tokenResponse.ok) {
      return loginRedirect(request, "google_failed");
    }

    const tokens = (await tokenResponse.json()) as { id_token?: string };
    if (!tokens.id_token) {
      return loginRedirect(request, "google_failed");
    }

    const oauthClient = new OAuth2Client(clientId);
    const ticket = await oauthClient.verifyIdToken({ idToken: tokens.id_token, audience: clientId });
    const payload = ticket.getPayload();

    if (!payload?.email || payload.email_verified !== true) {
      return loginRedirect(request, "google_failed");
    }

    const authorizedEmails = (process.env.AUTHORIZED_GOOGLE_EMAILS ?? "")
      .split(",")
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean);

    if (!authorizedEmails.includes(payload.email.toLowerCase())) {
      return loginRedirect(request, "google_unauthorized");
    }

    cookieStore.set(SESSION_COOKIE, getExpectedSessionValue(), {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 30,
    });

    return NextResponse.redirect(new URL(intent === "reset" ? "/settings" : "/", request.url));
  } catch {
    return loginRedirect(request, "google_failed");
  }
}
