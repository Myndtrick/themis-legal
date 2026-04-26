import { exchangeCodeForTokens } from "@/lib/aicc-auth";
import { verifyPkceCookie } from "@/lib/cookies";

const REFRESH_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days

function isProdCookie(): boolean {
  return process.env.NODE_ENV === "production";
}

function buildSetCookie(opts: {
  name: string;
  value: string;
  maxAgeSeconds: number;
  httpOnly?: boolean;
}): string {
  const parts = [
    `${opts.name}=${opts.value}`,
    "Path=/",
    `Max-Age=${opts.maxAgeSeconds}`,
    "SameSite=Lax",
  ];
  if (opts.httpOnly !== false) parts.push("HttpOnly");
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function clearCookieHeader(name: string): string {
  const parts = [`${name}=`, "Path=/", "Max-Age=0", "SameSite=Lax", "HttpOnly"];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function readPkceCookie(req: Request): string | null {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(/;\s*/)) {
    if (part.startsWith("aicc_pkce=")) return part.slice("aicc_pkce=".length);
  }
  return null;
}

export async function GET(req: Request): Promise<Response> {
  const baseUrl = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;
  const cookieSecret = process.env.AICC_PKCE_COOKIE_SECRET!;

  const u = new URL(req.url);
  const code = u.searchParams.get("code");
  const state = u.searchParams.get("state");
  const cookieRaw = readPkceCookie(req);

  if (!code || !state || !cookieRaw) {
    console.error("[auth] missing PKCE cookie or query params on callback");
    return new Response("Sign-in session expired, please try again.", { status: 400 });
  }

  const cookie = await verifyPkceCookie(cookieRaw, cookieSecret);
  if (!cookie) {
    console.error("[auth] invalid PKCE cookie signature");
    return new Response("Sign-in session expired, please try again.", { status: 400 });
  }
  if (cookie.state !== state) {
    console.error("[auth] state mismatch: cookie=%s param=%s", cookie.state, state);
    return new Response("Sign-in session expired, please try again.", { status: 400 });
  }

  let tokens;
  try {
    tokens = await exchangeCodeForTokens({
      baseUrl,
      code,
      codeVerifier: cookie.verifier,
    });
  } catch (e) {
    console.error("[auth] /auth/token exchange failed:", e);
    return new Response("Auth provider error", { status: 502 });
  }

  const expEpochMs = Date.now() + tokens.expires_in * 1000;
  const dest = new URL(cookie.callbackUrl, u.origin).toString();

  const headers = new Headers();
  headers.set("Location", dest);
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access",
    value: tokens.access_token,
    maxAgeSeconds: tokens.expires_in,
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_refresh",
    value: tokens.refresh_token,
    maxAgeSeconds: REFRESH_COOKIE_MAX_AGE_SECONDS,
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access_exp",
    value: String(expEpochMs),
    maxAgeSeconds: tokens.expires_in,
    httpOnly: false, // JS reads this to know when to refresh
  }));
  headers.append("Set-Cookie", clearCookieHeader("aicc_pkce"));

  return new Response(null, { status: 302, headers });
}
