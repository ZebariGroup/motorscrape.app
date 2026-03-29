"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { useAccessSummary } from "@/hooks/useAccessSummary";
import { resolveApiUrl } from "@/lib/apiBase";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { access } = useAccessSummary();

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [verifyEmailMessage, setVerifyEmailMessage] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setVerifyEmailMessage(null);
    setIsSubmitting(true);
    try {
      const r = await fetch(resolveApiUrl("/auth/signup"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setError(typeof j.detail === "string" ? j.detail : "Sign up failed.");
        setIsSubmitting(false);
        return;
      }
      const data = (await r.json().catch(() => ({}))) as { email_verification_required?: boolean; email?: string };
      if (data.email_verification_required) {
        setVerifyEmailMessage(
          `Check your email—we sent a confirmation link to ${data.email ?? email}. After you confirm, you can log in.`,
        );
        setIsSubmitting(false);
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setError("Network error. Please try again.");
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <SiteHeader access={access} />
      <main className="mx-auto max-w-md px-4 py-12 sm:px-6">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Create account</h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          After a few free searches without an account, you&apos;ll need a free login to continue.
        </p>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Already have one?{" "}
          <Link href="/login" className="font-medium text-emerald-700 dark:text-emerald-400">
            Log in
          </Link>
        </p>
        {verifyEmailMessage ? (
          <div className="mt-8 space-y-4">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100">
              <p>{verifyEmailMessage}</p>
              <p className="mt-3">
                <Link href="/login" className="font-medium text-emerald-800 underline dark:text-emerald-300">
                  Go to log in
                </Link>
              </p>
            </div>
            <button
              type="button"
              className="text-sm font-medium text-zinc-600 underline dark:text-zinc-400"
              onClick={() => {
                setVerifyEmailMessage(null);
                setPassword("");
              }}
            >
              Use a different email
            </button>
          </div>
        ) : (
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
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Password (min 8 characters)</span>
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              />
            </label>
            {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-lg bg-emerald-600 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? "Creating account..." : "Sign up"}
            </button>
          </form>
        )}
      </main>
    </>
  );
}
