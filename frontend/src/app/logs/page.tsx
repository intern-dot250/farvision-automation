"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getLogs, type LogEntry } from "@/lib/api/history";

const LEVEL_TONE: Record<string, "neutral" | "warning" | "danger"> = {
  info: "neutral",
  warning: "warning",
  error: "danger",
};

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getLogs()
      .then(setLogs)
      .catch(() => setError(true));
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
          Logs
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Application and processing logs.
        </p>
      </div>

      <Card>
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Could not load logs.
          </p>
        )}
        {!error && !logs && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
        )}
        {!error && logs && logs.length === 0 && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            No log entries yet.
          </p>
        )}
        {!error && logs && logs.length > 0 && (
          <ul className="flex flex-col divide-y divide-zinc-200 dark:divide-zinc-800">
            {logs.map((log) => (
              <li key={log.id} className="flex flex-col gap-1 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge tone={LEVEL_TONE[log.level] ?? "neutral"}>
                    {log.level}
                  </Badge>
                  <span className="text-zinc-500 dark:text-zinc-400">
                    {new Date(log.created_at).toLocaleString()}
                  </span>
                </div>
                <span className="text-zinc-900 dark:text-zinc-100">
                  {log.message}
                </span>
                {log.context && (
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {JSON.stringify(log.context)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
