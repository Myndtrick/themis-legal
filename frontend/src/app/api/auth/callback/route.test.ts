import { describe, expect, test, beforeEach, vi } from "vitest";
import { signPkceCookie } from "@/lib/cookies";

const SECRET = "test-secret-at-least-32-bytes-long-aaaaa";
const BASE = "https://aicc.test";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_BASE_URL", BASE);
  vi.stubEnv("NEXT_PUBLIC_AICC_AUTH_REDIRECT", "https://themis.test/api/auth/callback");
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

  test("redirects to /auth/signin?error=access_denied when AICC sends ?error=access_denied", async () => {
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "error=access_denied&state=anything",
    }));
    expect(res.status).toBe(302);
    const loc = res.headers.get("location")!;
    expect(loc).toContain("/auth/signin");
    expect(loc).toContain("error=access_denied");
  });

  test("redirects to /auth/signin?error=server_error for transient AICC failures", async () => {
    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "error=server_error&state=anything",
    }));
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toContain("error=server_error");
  });

  test("redirects to public origin even when req.url is the container's internal binding", async () => {
    // Simulates Railway: container binds 0.0.0.0:3000 but the public host
    // is themis.test (per NEXT_PUBLIC_AICC_AUTH_REDIRECT).
    const cookie = await signPkceCookie(
      { verifier: "v", state: "s", callbackUrl: "/laws" },
      SECRET,
    );
    mockTokenEndpoint({
      status: 200,
      body: { access_token: "A", refresh_token: "R", expires_in: 900, token_type: "Bearer" },
    });

    const headers = new Headers();
    headers.set("cookie", `aicc_pkce=${cookie}`);
    // Note the host: 0.0.0.0:3000 — what Railway's Node container would see.
    const req = new Request("http://0.0.0.0:3000/api/auth/callback?code=C&state=s", { headers });

    const { GET } = await import("./route");
    const res = await GET(req);
    expect(res.status).toBe(302);
    // Must redirect to the PUBLIC origin, not 0.0.0.0:3000.
    expect(res.headers.get("location")).toBe("https://themis.test/laws");
  });

  test("rejects cross-origin callbackUrl (open-redirect protection)", async () => {
    const cookie = await signPkceCookie(
      { verifier: "v", state: "s", callbackUrl: "https://evil.example/steal" },
      SECRET,
    );
    mockTokenEndpoint({
      status: 200,
      body: { access_token: "A", refresh_token: "R", expires_in: 900, token_type: "Bearer" },
    });

    const { GET } = await import("./route");
    const res = await GET(await makeReqWithCookie({
      query: "code=C&state=s",
      pkceCookie: cookie,
    }));
    expect(res.status).toBe(302);
    // Falls back to home of public origin, NOT the cross-origin URL.
    expect(res.headers.get("location")).toBe("https://themis.test/");
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
