import { refreshTokens } from "@/lib/aicc-auth";

const REFRESH_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days
const REFRESH_THRESHOLD_MS = 60 * 1000; // refresh when access expires within 60s

function isProdCookie(): boolean {
  return process.env.NODE_ENV === "production";
}

function buildSetCookie(opts: {
  name: string;
  value: string;
  maxAgeSeconds: number;
  httpOnly?: boolean;
}): string {
  const parts = [
    `${opts.name}=${opts.value}`,
    "Path=/",
    `Max-Age=${opts.maxAgeSeconds}`,
    "SameSite=Lax",
  ];
  if (opts.httpOnly !== false) parts.push("HttpOnly");
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function clearCookieHeader(name: string): string {
  const parts = [`${name}=`, "Path=/", "Max-Age=0", "SameSite=Lax", "HttpOnly"];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function readCookies(req: Request): Record<string, string> {
  const raw = req.headers.get("cookie") ?? "";
  const out: Record<string, string> = {};
  for (const part of raw.split(/;\s*/)) {
    const eq = part.indexOf("=");
    if (eq > 0) out[part.slice(0, eq)] = part.slice(eq + 1);
  }
  return out;
}

// Per-process mutex keyed by refresh_token so concurrent /api/token calls
// during the refresh window collapse into a single AICC roundtrip.
const inflight = new Map<string, Promise<{ access: string; expEpochMs: number; refresh: string }>>();

async function refreshOnce(refreshToken: string, baseUrl: string) {
  const existing = inflight.get(refreshToken);
  if (existing) return existing;
  const p = (async () => {
    const tokens = await refreshTokens({ baseUrl, refreshToken });
    return {
      access: tokens.access_token,
      expEpochMs: Date.now() + tokens.expires_in * 1000,
      refresh: tokens.refresh_token,
    };
  })();
  inflight.set(refreshToken, p);
  try {
    return await p;
  } finally {
    inflight.delete(refreshToken);
  }
}

export async function GET(req: Request): Promise<Response> {
  const baseUrl = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;

  const cookies = readCookies(req);
  const access = cookies["aicc_access"];
  const refresh = cookies["aicc_refresh"];
  const expRaw = cookies["aicc_access_exp"];

  if (!access || !refresh) {
    return Response.json({ token: null }, { status: 401 });
  }

  const expEpochMs = expRaw ? Number(expRaw) : 0;
  const needsRefresh = !expRaw || expEpochMs - Date.now() < REFRESH_THRESHOLD_MS;

  if (!needsRefresh) {
    return Response.json({ token: access, expiresAt: expEpochMs }, { status: 200 });
  }

  let refreshed;
  try {
    refreshed = await refreshOnce(refresh, baseUrl);
  } catch (e) {
    console.error("[auth] refresh failed:", e);
    const headers = new Headers();
    headers.append("Set-Cookie", clearCookieHeader("aicc_access"));
    headers.append("Set-Cookie", clearCookieHeader("aicc_refresh"));
    headers.append("Set-Cookie", clearCookieHeader("aicc_access_exp"));
    return new Response(JSON.stringify({ token: null }), { status: 401, headers });
  }

  const headers = new Headers();
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access",
    value: refreshed.access,
    maxAgeSeconds: Math.floor((refreshed.expEpochMs - Date.now()) / 1000),
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_refresh",
    value: refreshed.refresh,
    maxAgeSeconds: REFRESH_COOKIE_MAX_AGE_SECONDS,
  }));
  headers.append("Set-Cookie", buildSetCookie({
    name: "aicc_access_exp",
    value: String(refreshed.expEpochMs),
    maxAgeSeconds: Math.floor((refreshed.expEpochMs - Date.now()) / 1000),
    httpOnly: false,
  }));

  return new Response(
    JSON.stringify({ token: refreshed.access, expiresAt: refreshed.expEpochMs }),
    { status: 200, headers },
  );
}
