import {
  buildAuthorizeUrl,
  generatePkceVerifier,
  pkceChallenge,
} from "@/lib/aicc-auth";
import { signPkceCookie } from "@/lib/cookies";

const PKCE_COOKIE_MAX_AGE_SECONDS = 5 * 60; // 5 minutes — only needs to survive the AICC roundtrip

function isProdCookie(): boolean {
  // Only production deploys serve over HTTPS. Avoid `Secure` in dev so cookies
  // work on http://localhost.
  return process.env.NODE_ENV === "production";
}

function setCookieHeader(name: string, value: string, maxAgeSeconds: number): string {
  const parts = [
    `${name}=${value}`,
    "Path=/",
    `Max-Age=${maxAgeSeconds}`,
    "HttpOnly",
    "SameSite=Lax",
  ];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

export async function GET(req: Request): Promise<Response> {
  const baseUrl = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;
  const clientId = process.env.NEXT_PUBLIC_AICC_AUTH_CLIENT_ID!;
  const redirectUri = process.env.NEXT_PUBLIC_AICC_AUTH_REDIRECT!;
  const cookieSecret = process.env.AICC_PKCE_COOKIE_SECRET!;

  const u = new URL(req.url);
  const callbackUrl = u.searchParams.get("callbackUrl") || "/";

  const verifier = generatePkceVerifier();
  const challenge = await pkceChallenge(verifier);
  const state = crypto.randomUUID();

  const cookieValue = await signPkceCookie(
    { verifier, state, callbackUrl },
    cookieSecret,
  );

  const authorizeUrl = buildAuthorizeUrl({
    baseUrl,
    clientId,
    redirectUri,
    state,
    codeChallenge: challenge,
  });

  const headers = new Headers();
  headers.set("Location", authorizeUrl);
  headers.append("Set-Cookie", setCookieHeader("aicc_pkce", cookieValue, PKCE_COOKIE_MAX_AGE_SECONDS));
  return new Response(null, { status: 302, headers });
}
