import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
  ],
  pages: {
    signIn: "/auth/signin",
    error: "/auth/signin",
  },
  callbacks: {
    async signIn({ user }) {
      // Verify with backend that this email is allowed
      try {
        const res = await fetch(`${API_BASE}/api/admin/verify-user`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-auth-secret": process.env.NEXTAUTH_SECRET!,
          },
          body: JSON.stringify({
            email: user.email,
            name: user.name,
            picture: user.image,
          }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        return data.allowed === true;
      } catch (e) {
        console.error("[auth] Failed to verify user:", e);
        return false;
      }
    },
    async jwt({ token, user, account }) {
      if (account && user) {
        // First sign-in: fetch role from backend
        try {
          const res = await fetch(`${API_BASE}/api/admin/verify-user`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "x-auth-secret": process.env.NEXTAUTH_SECRET!,
            },
            body: JSON.stringify({
              email: user.email,
              name: user.name,
              picture: user.image,
            }),
          });
          if (res.ok) {
            const data = await res.json();
            token.role = data.role;
          }
        } catch {
          // Role will be empty — non-critical
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as unknown as Record<string, unknown>).role = token.role;
      }
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET,
});
