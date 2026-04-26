"use client";

import { useEffect, useState } from "react";

interface Me {
  email: string;
  name: string | null;
  picture: string | null;
  role: "admin" | "user";
}

export function UserMenu() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (alive) setMe(data); })
      .catch(() => { if (alive) setMe(null); });
    return () => { alive = false; };
  }, []);

  if (!me) return null;

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-gray-600 hidden sm:block">
        {me.name || me.email}
      </span>
      {me.picture && (
        <img src={me.picture} alt="" className="w-8 h-8 rounded-full" />
      )}
      <form action="/api/auth/logout" method="POST">
        <button type="submit" className="text-sm text-gray-500 hover:text-gray-700">
          Sign out
        </button>
      </form>
    </div>
  );
}
