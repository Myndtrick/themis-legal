/**
 * Cookie helpers for the AICC auth flow.
 *
 * The `aicc_pkce` cookie carries the PKCE verifier across the redirect to
 * AICC and back. Because it lives on the browser between requests, it must be
 * tamper-evident: we sign it with HMAC-SHA256 over the JSON payload.
 */
import { base64UrlEncode } from "./aicc-auth";

export interface PkceCookiePayload {
  verifier: string;
  state: string;
  callbackUrl: string;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function b64UrlDecode(s: string): Uint8Array {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function signPkceCookie(payload: PkceCookiePayload, secret: string): Promise<string> {
  const json = JSON.stringify(payload);
  const body = base64UrlEncode(new TextEncoder().encode(json));
  const key = await hmacKey(secret);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  return `${body}.${base64UrlEncode(sig)}`;
}

export async function verifyPkceCookie(
  cookie: string,
  secret: string,
): Promise<PkceCookiePayload | null> {
  const dot = cookie.indexOf(".");
  if (dot < 0) return null;
  const body = cookie.slice(0, dot);
  const sig = cookie.slice(dot + 1);
  const key = await hmacKey(secret);
  const expected = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
  let actual: Uint8Array;
  try {
    actual = b64UrlDecode(sig);
  } catch {
    return null;
  }
  if (!timingSafeEqual(expected, actual)) return null;
  try {
    const json = new TextDecoder().decode(b64UrlDecode(body));
    return JSON.parse(json) as PkceCookiePayload;
  } catch {
    return null;
  }
}
