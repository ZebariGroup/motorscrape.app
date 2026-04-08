"use client";

import { useEffect } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { useAccessSummary } from "@/hooks/useAccessSummary";

export function DirectoryHeader() {
  const { access, refresh } = useAccessSummary();

  useEffect(() => {
    refresh();
  }, [refresh]);

  return <SiteHeader access={access} />;
}
