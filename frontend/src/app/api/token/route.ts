import { auth } from "@/lib/auth";
import { SignJWT } from "jose/jwt/sign";

export async function GET() {
  const session = await auth();
  if (!session?.user?.email) {
    return Response.json({ token: null }, { status: 401 });
  }

  const secret = new TextEncoder().encode(process.env.NEXTAUTH_SECRET!);
  const token = await new SignJWT({
    email: session.user.email,
    name: session.user.name,
    picture: session.user.image,
    role: (session.user as unknown as Record<string, unknown>).role,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("1h")
    .sign(secret);

  return Response.json({ token });
}
