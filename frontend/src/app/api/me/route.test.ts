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
  return new Request("https://themis.test/api/me", { headers });
}

describe("GET /api/me", () => {
  test("returns user profile from AICC /auth/me when token is present", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === `${BASE}/auth/me`) {
        return new Response(JSON.stringify({
          id: "u1",
          email: "alice@x.com",
          name: "Alice",
          avatarUrl: "pic",
          projectRole: "admin",
        }), { status: 200 });
      }
      throw new Error("unexpected fetch");
    }));
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({ aicc_access: "TOK" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({
      email: "alice@x.com",
      name: "Alice",
      picture: "pic",
      role: "admin",
    });
  });

  test("returns 401 when no cookie", async () => {
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({}));
    expect(res.status).toBe(401);
  });

  test("maps non-admin projectRole to 'user'", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      id: "u1", email: "x@y.com", name: null, avatarUrl: null, projectRole: "viewer",
    }), { status: 200 })));
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({ aicc_access: "TOK" }));
    const body = await res.json();
    expect(body.role).toBe("user");
  });

  test("returns 401 when AICC token is rejected", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    const { GET } = await import("./route");
    const res = await GET(reqWithCookies({ aicc_access: "TOK" }));
    expect(res.status).toBe(401);
  });
});
