"use client";

import { useEffect, useState } from "react";
import { resolveApiUrl } from "@/lib/apiBase";

type Props = {
  make?: string;
  state?: string;
  q?: string;
};

export function DealerExportButton({ make, state, q }: Props) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(resolveApiUrl("/auth/me"), { credentials: "include" })
      .then((r) => setIsLoggedIn(r.ok))
      .catch(() => setIsLoggedIn(false))
      .finally(() => setLoading(false));
  }, []);

  if (loading || !isLoggedIn) return null;

  const qs = new URLSearchParams();
  if (make) qs.set("make", make);
  if (state) qs.set("state", state);
  if (q) qs.set("q", q);
  const href = `/api/dealers/export${qs.toString() ? `?${qs}` : ""}`;

  return (
    <a
      href={href}
      download
      className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-4 py-2 text-sm font-medium text-zinc-700 shadow-sm hover:bg-zinc-50 hover:border-zinc-300 transition-colors dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
    >
      <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M8 2v8M5 7l3 3 3-3M3 12h10" />
      </svg>
      Export CSV
    </a>
  );
}
