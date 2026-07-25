"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getStats, type StatsSummary } from "@/lib/api/history";
import { runAutomation, type RunResponse } from "@/lib/api/automation";

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [dryRun, setDryRun] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const loadStats = () => {
    getStats()
      .then((data) => {
        setStats(data);
        setStatsError(false);
      })
      .catch(() => setStatsError(true));
  };

  useEffect(() => {
    loadStats();
  }, []);

  const handleRun = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const response = await runAutomation(dryRun);
      setResult(response);
      loadStats();
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "Run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Trigger a processing run and monitor its status.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Card title="Total Processed">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {statsError ? "—" : (stats?.total_processed ?? "…")}
          </p>
        </Card>
        <Card title="Receipt/Payment">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {statsError ? "—" : (stats?.total_receipt_payment ?? "…")}
          </p>
        </Card>
        <Card title="Deposit/Withdrawal">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {statsError ? "—" : (stats?.total_deposit_withdrawal ?? "…")}
          </p>
        </Card>
        <Card title="Total Runs">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {statsError ? "—" : (stats?.total_runs ?? "…")}
          </p>
        </Card>
      </div>

      <Card title="Run Processing">
        <div className="flex flex-col gap-4">
          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              disabled={running}
            />
            Dry run (preview only, no writes to Google Sheets)
          </label>

          <button
            onClick={handleRun}
            disabled={running}
            className="w-fit rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {running
              ? "Running..."
              : dryRun
                ? "Preview Run"
                : "Run & Write to Sheets"}
          </button>

          {runError && (
            <p className="text-sm text-red-600 dark:text-red-400">{runError}</p>
          )}

          {result && (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                <Badge tone={result.dry_run ? "warning" : "success"}>
                  {result.dry_run ? "Dry run" : "Written"}
                </Badge>
                <Badge tone="neutral">{result.total_transactions} total</Badge>
                <Badge tone="success">
                  {result.routed_receipt_payment} receipt/payment
                </Badge>
                <Badge tone="success">
                  {result.routed_deposit_withdrawal} deposit/withdrawal
                </Badge>
                <Badge tone="warning">{result.needs_review} needs review</Badge>
                <Badge tone="neutral">
                  {result.duplicates_skipped} duplicates skipped
                </Badge>
              </div>

              <div className="overflow-x-auto rounded-md border border-zinc-200 dark:border-zinc-800">
                <table className="w-full text-left text-sm">
                  <thead className="bg-zinc-50 text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
                    <tr>
                      <th className="px-3 py-2 font-medium">SL#</th>
                      <th className="px-3 py-2 font-medium">Payee</th>
                      <th className="px-3 py-2 font-medium">Head</th>
                      <th className="px-3 py-2 font-medium">Destination</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {result.transactions.map((txn) => (
                      <tr key={txn.sl_no}>
                        <td className="px-3 py-2">{txn.sl_no}</td>
                        <td className="px-3 py-2">{txn.payee_name ?? "—"}</td>
                        <td className="px-3 py-2">{txn.head || "—"}</td>
                        <td className="px-3 py-2">
                          <Badge
                            tone={
                              txn.destination === "review" ||
                              txn.destination === "error"
                                ? "warning"
                                : txn.destination === "duplicate"
                                  ? "neutral"
                                  : "success"
                            }
                          >
                            {txn.destination}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
