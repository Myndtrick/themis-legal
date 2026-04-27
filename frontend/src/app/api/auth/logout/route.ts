import { revokeToken } from "@/lib/aicc-auth";

function isProdCookie(): boolean {
  return process.env.NODE_ENV === "production";
}

function clearCookieHeader(name: string): string {
  const parts = [`${name}=`, "Path=/", "Max-Age=0", "SameSite=Lax", "HttpOnly"];
  if (isProdCookie()) parts.push("Secure");
  return parts.join("; ");
}

function readAccess(req: Request): string | null {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(/;\s*/)) {
    if (part.startsWith("aicc_access=")) return part.slice("aicc_access=".length);
  }
  return null;
}

export async function POST(req: Request): Promise<Response> {
  const baseUrl = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;

  const access = readAccess(req);
  if (access) {
    await revokeToken({ baseUrl, accessToken: access }).catch((e) => {
      console.error("[auth] revoke failed:", e);
    });
  }
  const headers = new Headers();
  headers.set("Location", "/auth/signin");
  headers.append("Set-Cookie", clearCookieHeader("aicc_access"));
  headers.append("Set-Cookie", clearCookieHeader("aicc_refresh"));
  headers.append("Set-Cookie", clearCookieHeader("aicc_access_exp"));
  return new Response(null, { status: 302, headers });
}
