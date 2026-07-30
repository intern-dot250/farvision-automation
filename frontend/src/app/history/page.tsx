"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getRuns, type RunSummary } from "@/lib/api/history";

export default function HistoryPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getRuns()
      .then(setRuns)
      .catch(() => setError(true));
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
          History
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Past processing runs and their outcomes.
        </p>
      </div>

      <Card>
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Could not load run history.
          </p>
        )}
        {!error && !runs && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
        )}
        {!error && runs && runs.length === 0 && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            No runs yet.
          </p>
        )}
        {!error && runs && runs.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-zinc-500 dark:text-zinc-400">
                <tr>
                  <th className="px-3 py-2 font-medium">Started</th>
                  <th className="px-3 py-2 font-medium">Mode</th>
                  <th className="px-3 py-2 font-medium">Sheet</th>
                  <th className="px-3 py-2 font-medium">Receipt/Payment</th>
                  <th className="px-3 py-2 font-medium">Deposit/Withdrawal</th>
                  <th className="px-3 py-2 font-medium">Review</th>
                  <th className="px-3 py-2 font-medium">Duplicates</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {runs.map((run) => (
                  <tr key={run.run_id}>
                    <td className="px-3 py-2">
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString()
                        : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={run.dry_run ? "warning" : "success"}>
                        {run.dry_run ? "Dry run" : "Written"}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
                      {run.sheet_names && run.sheet_names.length > 0
                        ? run.sheet_names.join(", ")
                        : "—"}
                    </td>
                    <td className="px-3 py-2">
                      {run.routed_receipt_payment ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      {run.routed_deposit_withdrawal ?? "—"}
                    </td>
                    <td className="px-3 py-2">{run.needs_review ?? "—"}</td>
                    <td className="px-3 py-2">
                      {run.duplicates_skipped ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
