import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  const { nextUrl } = req;
  const path = nextUrl.pathname;

  const isAuthPage = path.startsWith("/auth");
  const isApiAuth = path.startsWith("/api/auth");
  const isApiToken = path === "/api/token";
  const isApiMe = path === "/api/me";

  const hasAccess = req.cookies.has("aicc_access");

  // Auth-related routes (sign-in page, login/callback handlers, token endpoint)
  // are reachable without auth. Authenticated users visiting /auth/signin get
  // bounced to home.
  if (isAuthPage || isApiAuth || isApiToken || isApiMe) {
    if (hasAccess && isAuthPage) {
      return NextResponse.redirect(new URL("/", nextUrl));
    }
    return NextResponse.next();
  }

  if (!hasAccess) {
    const target = new URL("/api/auth/login", nextUrl);
    target.searchParams.set("callbackUrl", path);
    return NextResponse.redirect(target);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
