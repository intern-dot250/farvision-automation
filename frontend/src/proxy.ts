import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, isValidSession } from "@/lib/auth";

const PUBLIC_PATHS = new Set(["/login", "/api/login"]);

export default function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  const isPublicPath = PUBLIC_PATHS.has(path);
  const authenticated = isValidSession(request.cookies.get(SESSION_COOKIE)?.value);

  if (!authenticated && !isPublicPath) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (authenticated && path === "/login") {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
