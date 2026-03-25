"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { resolveApiUrl } from "@/lib/apiBase";
import type { AccessSummary } from "@/types/access";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [access, setAccess] = useState<AccessSummary | null>(null);

  const loadAccess = () => {
    fetch(resolveApiUrl("/auth/access-summary"), { credentials: "include" })
      .then((r) => r.json())
      .then(setAccess)
      .catch(() => setAccess(null));
  };

  useEffect(() => {
    loadAccess();
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const r = await fetch(resolveApiUrl("/auth/login"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      setError(typeof j.detail === "string" ? j.detail : "Login failed.");
      return;
    }
    router.push("/");
    router.refresh();
  };

  return (
    <>
      <SiteHeader access={access} />
      <main className="mx-auto max-w-md px-4 py-12 sm:px-6">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Log in</h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          No account?{" "}
          <Link href="/signup" className="font-medium text-emerald-700 dark:text-emerald-400">
            Sign up
          </Link>
        </p>
        <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">Email</span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
          </label>
          {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
          <button
            type="submit"
            className="rounded-lg bg-emerald-600 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500"
          >
            Log in
          </button>
        </form>
      </main>
    </>
  );
}
