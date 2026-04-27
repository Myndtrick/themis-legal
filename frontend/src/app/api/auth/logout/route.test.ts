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
  return new Request("https://themis.test/api/auth/logout", { method: "POST", headers });
}

describe("POST /api/auth/logout", () => {
  test("calls AICC /auth/logout, clears cookies, redirects to /auth/signin", async () => {
    const aiccCalls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      aiccCalls.push(`${init?.method ?? "GET"} ${url}`);
      return new Response("{}", { status: 200 });
    }));

    const { POST } = await import("./route");
    const res = await POST(reqWithCookies({ aicc_access: "TOK" }));
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/auth/signin");
    expect(aiccCalls).toContain(`POST ${BASE}/auth/logout`);

    const setCookies = res.headers.getSetCookie().join("\n");
    expect(setCookies).toMatch(/aicc_access=;.*Max-Age=0/i);
    expect(setCookies).toMatch(/aicc_refresh=;.*Max-Age=0/i);
    expect(setCookies).toMatch(/aicc_access_exp=;.*Max-Age=0/i);
  });

  test("clears cookies even if AICC logout throws", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("boom"); }));
    const { POST } = await import("./route");
    const res = await POST(reqWithCookies({ aicc_access: "TOK" }));
    expect(res.status).toBe(302);
    expect(res.headers.getSetCookie().join("\n")).toMatch(/aicc_access=;/i);
  });
});
