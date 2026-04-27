import { describe, expect, test, beforeEach, vi } from "vitest";

const BASE = "https://aicc.test";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", BASE);
  vi.unstubAllGlobals();
  vi.resetModules();
});

function reqWithCookies(cookies: Record<string, string>): Request {
  const headers = new Headers();
  headers.set("cookie", Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join("; "));
  return new Request("https://themis.test/api/token", { headers });
}

describe("GET /api/token", () => {
  test("returns the cookie's access token when fresh", async () => {
    const exp = Date.now() + 10 * 60 * 1000; // 10 min out
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({
      aicc_access: "FRESH",
      aicc_access_exp: String(exp),
      aicc_refresh: "REFRESH",
    }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.token).toBe("FRESH");
    expect(body.expiresAt).toBe(exp);
  });

  test("returns 401 when no aicc_access cookie", async () => {
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({}));
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.token).toBeNull();
  });

  test("refreshes token when within 60s of expiry, sets new cookies, returns new token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === `${BASE}/auth/token`) {
          return new Response(JSON.stringify({
            access_token: "NEW_ACCESS",
            refresh_token: "NEW_REFRESH",
            expires_in: 900,
            token_type: "Bearer",
          }), { status: 200 });
        }
        throw new Error("unexpected fetch");
      }),
    );
    const exp = Date.now() + 10 * 1000; // 10s — well within refresh window
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({
      aicc_access: "OLD",
      aicc_access_exp: String(exp),
      aicc_refresh: "OLD_REFRESH",
    }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.token).toBe("NEW_ACCESS");
    const setCookies = res.headers.getSetCookie().join("\n");
    expect(setCookies).toContain("aicc_access=NEW_ACCESS");
    expect(setCookies).toContain("aicc_refresh=NEW_REFRESH");
  });

  test("clears cookies and returns 401 when refresh fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: "invalid_grant" }), { status: 400 })),
    );
    const exp = Date.now() + 10 * 1000;
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({
      aicc_access: "OLD",
      aicc_access_exp: String(exp),
      aicc_refresh: "EXPIRED_REFRESH",
    }));
    expect(res.status).toBe(401);
    const setCookies = res.headers.getSetCookie().join("\n");
    expect(setCookies).toMatch(/aicc_access=;.*Max-Age=0/i);
    expect(setCookies).toMatch(/aicc_refresh=;.*Max-Age=0/i);
  });
});
