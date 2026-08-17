import { NextRequest, NextResponse } from "next/server";

// This route is intentionally the only one in the app that proxies to the
// backend server-side instead of letting the browser call it directly - the
// backend's /automation/clear-sheet endpoint (which permanently deletes
// data) requires a secret that must never reach the browser. This route
// already inherits the dashboard's session-cookie auth check for free, since
// proxy.ts's matcher covers every path except /login and /api/login.
//
// NEXT_PUBLIC_API_BASE_URL is written for BROWSER fetches, so it's allowed
// to be a relative path (e.g. "/api/v1") - the browser resolves that against
// the current page origin automatically. Node's server-side fetch() has no
// such implicit origin and throws "Failed to parse URL" on a relative
// string, so it must always be resolved against this request's own origin
// via `new URL(path, base)` (a no-op when the configured value is already
// absolute, since the base argument is ignored in that case).
const API_PATH = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

const VALID_TARGETS = new Set(["receipt_payment", "deposit_withdrawal", "both"]);

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const target = body?.target;

  if (typeof target !== "string" || !VALID_TARGETS.has(target)) {
    return NextResponse.json({ error: "Invalid target" }, { status: 400 });
  }

  const backendUrl = new URL(
    `${API_PATH}/automation/clear-sheet?target=${encodeURIComponent(target)}`,
    request.nextUrl.origin,
  );

  const response = await fetch(backendUrl, {
    method: "POST",
    headers: {
      "X-Internal-Secret": process.env.ACCESS_PASSWORD ?? "",
    },
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    return NextResponse.json(
      { error: data?.detail ?? `Clear failed with status ${response.status}` },
      { status: response.status },
    );
  }

  return NextResponse.json(data);
}
