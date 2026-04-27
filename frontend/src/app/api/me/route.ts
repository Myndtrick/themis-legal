import { fetchAiccMe } from "@/lib/aicc-auth";

function readAccess(req: Request): string | null {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(/;\s*/)) {
    if (part.startsWith("aicc_access=")) return part.slice("aicc_access=".length);
  }
  return null;
}

function mapRole(projectRole: string | null): "admin" | "user" {
  return projectRole?.toLowerCase() === "admin" ? "admin" : "user";
}

export async function GET(req: Request): Promise<Response> {
  const baseUrl = process.env.NEXT_PUBLIC_AICC_AUTH_BASE_URL!;

  const access = readAccess(req);
  if (!access) return Response.json({ error: "unauthenticated" }, { status: 401 });

  let me;
  try {
    me = await fetchAiccMe({ baseUrl, accessToken: access });
  } catch (e) {
    console.error("[auth] /api/me lookup failed:", e);
    return Response.json({ error: "auth_provider_error" }, { status: 503 });
  }
  if (me === null) {
    return Response.json({ error: "unauthenticated" }, { status: 401 });
  }

  return Response.json({
    email: me.email,
    name: me.name,
    picture: me.avatarUrl,
    role: mapRole(me.projectRole),
  });
}
