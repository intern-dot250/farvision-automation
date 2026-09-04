import { NextRequest, NextResponse } from "next/server";

// Same-origin proxy so this can be called from the (unauthenticated) login
// page without exposing NEXT_PUBLIC_API_BASE_URL's backend directly for a
// pre-login action - mirrors clear-sheet/route.ts's proxy pattern, though
// unlike that route this one is intentionally public (see proxy.ts).
const API_PATH = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export async function POST(request: NextRequest) {
  const backendUrl = new URL(`${API_PATH}/auth/forgot-password`, request.nextUrl.origin);

  const response = await fetch(backendUrl, { method: "POST" });
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    return NextResponse.json(
      { error: data?.detail ?? `Request failed with status ${response.status}` },
      { status: response.status },
    );
  }

  return NextResponse.json(data);
}
