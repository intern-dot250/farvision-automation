import { NextRequest, NextResponse } from "next/server";

// This route is intentionally the only one in the app that proxies to the
// backend server-side instead of letting the browser call it directly - the
// backend's /automation/clear-sheet endpoint (which permanently deletes
// data) requires a secret that must never reach the browser. This route
// already inherits the dashboard's session-cookie auth check for free, since
// proxy.ts's matcher covers every path except /login and /api/login.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

const VALID_TARGETS = new Set(["receipt_payment", "deposit_withdrawal", "both"]);

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const target = body?.target;

  if (typeof target !== "string" || !VALID_TARGETS.has(target)) {
    return NextResponse.json({ error: "Invalid target" }, { status: 400 });
  }

  const response = await fetch(
    `${API_BASE_URL}/automation/clear-sheet?target=${encodeURIComponent(target)}`,
    {
      method: "POST",
      headers: {
        "X-Internal-Secret": process.env.ACCESS_PASSWORD ?? "",
      },
    },
  );

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    return NextResponse.json(
      { error: data?.detail ?? `Clear failed with status ${response.status}` },
      { status: response.status },
    );
  }

  return NextResponse.json(data);
}
