import { useCallback, useEffect, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import type { AccessSummary } from "@/types/access";

type AccessState = {
  access: AccessSummary | null;
  loading: boolean;
  refresh: () => Promise<void>;
};

export function useAccessSummary(): AccessState {
  const [access, setAccess] = useState<AccessSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(resolveApiUrl("/auth/access-summary"), { credentials: "include" });
      const data = await response.json();
      setAccess(data);
    } catch {
      setAccess(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { access, loading, refresh };
}

