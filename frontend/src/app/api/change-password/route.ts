import { NextRequest, NextResponse } from "next/server";

// Session-gated for free by proxy.ts (this path isn't in PUBLIC_PATHS) -
// only a logged-in dashboard user (via password or Google) can reach this.
// Proxies to the backend with the same internal secret /api/clear-sheet
// uses, since the backend has no other way to know this call came from an
// authenticated session.
const API_PATH = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const newPassword = typeof body?.new_password === "string" ? body.new_password : "";

  if (newPassword.length < 8) {
    return NextResponse.json({ error: "Password must be at least 8 characters" }, { status: 400 });
  }

  const backendUrl = new URL(`${API_PATH}/auth/set-password`, request.nextUrl.origin);

  const response = await fetch(backendUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Secret": process.env.INTERNAL_API_SECRET ?? "",
    },
    body: JSON.stringify({ new_password: newPassword }),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    return NextResponse.json(
      { error: data?.detail ?? `Failed to change password (status ${response.status})` },
      { status: response.status },
    );
  }

  return NextResponse.json(data);
}
