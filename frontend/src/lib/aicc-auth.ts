/**
 * AICC auth client — pure HTTP helpers around AICC's PKCE endpoints.
 *
 * No cookie / session state lives here; route handlers drive that.
 */

export function base64UrlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function generatePkceVerifier(): string {
  const buf = new Uint8Array(32);
  crypto.getRandomValues(buf);
  return base64UrlEncode(buf);
}

export async function pkceChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(digest));
}

export interface AuthorizeUrlInput {
  baseUrl: string;
  clientId: string;
  redirectUri: string;
  state: string;
  codeChallenge: string;
  identityProvider?: string;
}

export function buildAuthorizeUrl(input: AuthorizeUrlInput): string {
  const url = new URL(`${input.baseUrl.replace(/\/$/, "")}/auth/authorize`);
  url.searchParams.set("client_id", input.clientId);
  url.searchParams.set("redirect_uri", input.redirectUri);
  url.searchParams.set("state", input.state);
  url.searchParams.set("code_challenge", input.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("identity_provider", input.identityProvider ?? "google");
  return url.toString();
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: "Bearer";
  user?: unknown;
}

export async function exchangeCodeForTokens(input: {
  baseUrl: string;
  code: string;
  codeVerifier: string;
}): Promise<TokenResponse> {
  const r = await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "authorization_code",
      code: input.code,
      code_verifier: input.codeVerifier,
    }),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`[aicc-auth] /auth/token exchange failed (${r.status}): ${body}`);
  }
  return r.json();
}

export async function refreshTokens(input: {
  baseUrl: string;
  refreshToken: string;
}): Promise<TokenResponse> {
  const r = await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "refresh_token",
      refresh_token: input.refreshToken,
    }),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`[aicc-auth] /auth/token refresh failed (${r.status}): ${body}`);
  }
  return r.json();
}

export async function revokeToken(input: {
  baseUrl: string;
  accessToken: string;
}): Promise<void> {
  await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${input.accessToken}` },
  }).catch((e) => {
    console.error("[aicc-auth] /auth/logout failed:", e);
  });
}

export interface AiccMe {
  id: string;
  email: string;
  name: string | null;
  avatarUrl: string | null;
  projectRole: string | null;
}

export async function fetchAiccMe(input: {
  baseUrl: string;
  accessToken: string;
}): Promise<AiccMe | null> {
  const r = await fetch(`${input.baseUrl.replace(/\/$/, "")}/auth/me`, {
    headers: { Authorization: `Bearer ${input.accessToken}` },
  });
  if (r.status === 401) return null;
  if (!r.ok) {
    throw new Error(`[aicc-auth] /auth/me failed (${r.status})`);
  }
  return r.json();
}
