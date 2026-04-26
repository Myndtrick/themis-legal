import { describe, expect, test } from "vitest";
import {
  base64UrlEncode,
  buildAuthorizeUrl,
  generatePkceVerifier,
  pkceChallenge,
} from "./aicc-auth";

describe("base64UrlEncode + pkceChallenge", () => {
  test("encodes bytes per RFC 7636 (no padding, URL-safe alphabet)", async () => {
    // Known PKCE test vector from RFC 7636 Appendix B.
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    const challenge = await pkceChallenge(verifier);
    expect(challenge).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  test("base64UrlEncode produces no padding and URL-safe chars", () => {
    const enc = base64UrlEncode(new Uint8Array([0xff, 0xfb, 0xef]));
    expect(enc).not.toContain("=");
    expect(enc).not.toContain("+");
    expect(enc).not.toContain("/");
  });
});

describe("generatePkceVerifier", () => {
  test("produces a 43+ char base64url string with no padding", () => {
    const v = generatePkceVerifier();
    expect(v.length).toBeGreaterThanOrEqual(43);
    expect(v).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  test("produces unique values across calls", () => {
    const a = generatePkceVerifier();
    const b = generatePkceVerifier();
    expect(a).not.toBe(b);
  });
});

describe("buildAuthorizeUrl", () => {
  test("builds an /auth/authorize URL with all required PKCE query params", () => {
    const url = buildAuthorizeUrl({
      baseUrl: "https://aicc.example",
      clientId: "themis-web",
      redirectUri: "https://themis.example/auth/callback",
      state: "state-123",
      codeChallenge: "challenge-abc",
    });
    const parsed = new URL(url);
    expect(parsed.origin + parsed.pathname).toBe("https://aicc.example/auth/authorize");
    expect(parsed.searchParams.get("client_id")).toBe("themis-web");
    expect(parsed.searchParams.get("redirect_uri")).toBe("https://themis.example/auth/callback");
    expect(parsed.searchParams.get("state")).toBe("state-123");
    expect(parsed.searchParams.get("code_challenge")).toBe("challenge-abc");
    expect(parsed.searchParams.get("code_challenge_method")).toBe("S256");
    expect(parsed.searchParams.get("identity_provider")).toBe("google");
  });

  test("strips trailing slash from baseUrl", () => {
    const url = buildAuthorizeUrl({
      baseUrl: "https://aicc.example/",
      clientId: "x",
      redirectUri: "y",
      state: "s",
      codeChallenge: "c",
    });
    expect(url).toContain("https://aicc.example/auth/authorize?");
  });
});
