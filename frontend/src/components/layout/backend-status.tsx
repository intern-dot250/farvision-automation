"use client";

import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "@/lib/api/health";

type Status = "checking" | "connected" | "error";

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    getHealth()
      .then((data) => {
        if (cancelled) return;
        setHealth(data);
        setStatus("connected");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const label =
    status === "connected"
      ? `Backend: ${health?.environment}`
      : status === "error"
        ? "Backend: unreachable"
        : "Backend: checking...";

  const colorClasses =
    status === "connected"
      ? "border-emerald-200 text-emerald-600 dark:border-emerald-900 dark:text-emerald-400"
      : status === "error"
        ? "border-red-200 text-red-600 dark:border-red-900 dark:text-red-400"
        : "border-zinc-200 text-zinc-500 dark:border-zinc-800 dark:text-zinc-400";

  return (
    <span
      className={`rounded-full border px-2.5 py-1 text-xs font-medium ${colorClasses}`}
    >
      {label}
    </span>
  );
}
