import { describe, expect, test, beforeEach, vi } from "vitest";
import { signPkceCookie } from "@/lib/cookies";

const SECRET = "test-secret-at-least-32-bytes-long-aaaaa";
const BASE = "https://aicc.test";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", BASE);
  vi.stubEnv("AICC_PKCE_COOKIE_SECRET", SECRET);
  vi.unstubAllGlobals();
});

async function makeReqWithCookie(opts: {
  query: string;
  pkceCookie?: string;
}): Promise<Request> {
  const headers = new Headers();
  if (opts.pkceCookie !== undefined) {
    headers.set("cookie", `aicc_pkce=${opts.pkceCookie}`);
  }
  return new Request(`https://themis.test/api/auth/callback?${opts.query}`, { headers });
}

function mockTokenEndpoint(response: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === `${BASE}/auth/token` && init?.method === "POST") {
        return new Response(JSON.stringify(response.body), { status: response.status });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );
}

describe("GET /api/auth/callback", () => {
  test("exchanges code, sets aicc_access + aicc_refresh + aicc_access_exp cookies, redirects to callbackUrl", async () => {
    const cookie = await signPkceCookie(
      { verifier: "verifier-abc", state: "state-xyz", callbackUrl: "/laws" },
      SECRET,
    );
    mockTokenEndpoint({
      status: 200,
      body: {
        access_token: "ACCESS",
        refresh_token: "REFRESH",
        expires_in: 900,
        token_type: "Bearer",
      },
    });

    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "code=CODE&state=state-xyz",
      pkceCookie: cookie,
    }));

    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("https://themis.test/laws");

    const setCookies = res.headers.getSetCookie();
    const joined = setCookies.join("\n");
    expect(joined).toContain("aicc_access=ACCESS");
    expect(joined).toContain("aicc_refresh=REFRESH");
    expect(joined).toContain("aicc_access_exp=");
    // PKCE cookie cleared
    expect(joined).toMatch(/aicc_pkce=;.*Max-Age=0/i);
  });

  test("returns 400 when state does not match", async () => {
    const cookie = await signPkceCookie(
      { verifier: "v", state: "expected", callbackUrl: "/" },
      SECRET,
    );
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "code=CODE&state=different",
      pkceCookie: cookie,
    }));
    expect(res.status).toBe(400);
  });

  test("returns 400 when aicc_pkce cookie is missing", async () => {
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({ query: "code=C&state=S" }));
    expect(res.status).toBe(400);
  });

  test("returns 502 when AICC /auth/token returns 5xx", async () => {
    const cookie = await signPkceCookie(
      { verifier: "v", state: "s", callbackUrl: "/" },
      SECRET,
    );
    mockTokenEndpoint({ status: 500, body: { error: "boom" } });
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "code=C&state=s",
      pkceCookie: cookie,
    }));
    expect(res.status).toBe(502);
  });
});
