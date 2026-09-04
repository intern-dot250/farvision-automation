import { NextRequest, NextResponse } from "next/server";

const API_PATH = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const token = body?.token;
  const newPassword = body?.new_password;

  if (typeof token !== "string" || !token || typeof newPassword !== "string" || newPassword.length < 8) {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const backendUrl = new URL(`${API_PATH}/auth/reset-password`, request.nextUrl.origin);

  const response = await fetch(backendUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    return NextResponse.json(
      { error: data?.detail ?? `Reset failed with status ${response.status}` },
      { status: response.status },
    );
  }

  return NextResponse.json(data);
}
