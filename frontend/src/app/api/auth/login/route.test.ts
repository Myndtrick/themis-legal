import { describe, expect, test, beforeEach, vi } from "vitest";
import { GET } from "./route";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", "https://aicc.test");
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_CLIENT_ID", "themis-web");
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_REDIRECT", "https://themis.test/auth/callback");
  vi.stubEnv("AICC_PKCE_COOKIE_SECRET", "test-secret-at-least-32-bytes-long-aaaaa");
});

function makeReq(url: string): Request {
  return new Request(url);
}

describe("GET /api/auth/login", () => {
  test("redirects to AICC /auth/authorize with PKCE params and sets aicc_pkce cookie", async () => {
    const res = await GET(makeReq("https://themis.test/api/auth/login?callbackUrl=/laws"));
    expect(res.status).toBe(302);

    const location = res.headers.get("location")!;
    const u = new URL(location);
    expect(u.origin + u.pathname).toBe("https://aicc.test/auth/authorize");
    expect(u.searchParams.get("client_id")).toBe("themis-web");
    expect(u.searchParams.get("redirect_uri")).toBe("https://themis.test/auth/callback");
    expect(u.searchParams.get("code_challenge_method")).toBe("S256");
    expect(u.searchParams.get("state")).toBeTruthy();
    expect(u.searchParams.get("code_challenge")).toBeTruthy();

    const setCookie = res.headers.get("set-cookie")!;
    expect(setCookie).toContain("aicc_pkce=");
    expect(setCookie.toLowerCase()).toContain("httponly");
    expect(setCookie.toLowerCase()).toContain("samesite=lax");
    expect(setCookie.toLowerCase()).toContain("path=/");
  });

  test("defaults callbackUrl to / when missing", async () => {
    const res = await GET(makeReq("https://themis.test/api/auth/login"));
    expect(res.status).toBe(302);
    expect(res.headers.get("set-cookie")).toContain("aicc_pkce=");
  });
});
