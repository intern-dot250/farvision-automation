"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  getOrphanReport,
  getSheetsStatus,
  type DestinationOrphanReport,
  type SheetConnectionStatus,
} from "@/lib/api/sheets";

export default function SettingsPage() {
  const [sheets, setSheets] = useState<SheetConnectionStatus[] | null>(null);
  const [error, setError] = useState(false);
  const [orphanReports, setOrphanReports] = useState<DestinationOrphanReport[] | null>(null);
  const [orphanChecking, setOrphanChecking] = useState(false);
  const [orphanError, setOrphanError] = useState<string | null>(null);

  useEffect(() => {
    getSheetsStatus()
      .then((data) => setSheets(data.sheets))
      .catch(() => setError(true));
  }, []);

  const runOrphanCheck = async () => {
    setOrphanChecking(true);
    setOrphanError(null);
    try {
      const data = await getOrphanReport();
      setOrphanReports(data.reports);
    } catch (err) {
      setOrphanError(err instanceof Error ? err.message : "Orphan check failed");
    } finally {
      setOrphanChecking(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
          Settings
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Sheet connections and application configuration.
        </p>
      </div>

      <Card title="Google Sheets Connections">
        {error && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Could not load sheet status.
          </p>
        )}
        {!error && !sheets && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
        )}
        {!error && sheets && (
          <div className="flex flex-col gap-3">
            {sheets.map((sheet) => (
              <div
                key={sheet.sheet_id}
                className="flex flex-col gap-1 rounded-md border border-zinc-200 p-3 dark:border-zinc-800"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                    {sheet.name}
                  </span>
                  <Badge tone={sheet.connected ? "success" : "danger"}>
                    {sheet.connected ? "Connected" : "Error"}
                  </Badge>
                </div>
                {sheet.connected ? (
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    Tabs: {sheet.worksheets.join(", ")}
                  </span>
                ) : (
                  <span className="text-xs text-red-600 dark:text-red-400">
                    {sheet.error}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Linked-Tab Orphan Check">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Checks whether every Link Ref Code appears consistently across all
            of a destination&apos;s linked tabs - a mismatch usually means a
            row was manually deleted from only one tab. Read-only, changes
            nothing.
          </p>
          <button
            onClick={runOrphanCheck}
            disabled={orphanChecking}
            className="w-fit rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {orphanChecking ? "Checking…" : "Check for Orphaned Rows"}
          </button>

          {orphanError && (
            <p className="text-sm text-red-600 dark:text-red-400">{orphanError}</p>
          )}

          {orphanReports && (
            <div className="flex flex-col gap-4">
              {orphanReports.map((report) => (
                <div
                  key={report.destination}
                  className="flex flex-col gap-2 rounded-md border border-zinc-200 p-3 dark:border-zinc-800"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      {report.destination === "deposit_withdrawal" ? "Deposit/Withdrawal" : "Receipt/Payment"}
                    </span>
                    <Badge tone={report.orphans.length === 0 ? "success" : "warning"}>
                      {report.orphans.length === 0
                        ? "No orphans"
                        : `${report.orphans.length} mismatch${report.orphans.length === 1 ? "" : "es"}`}
                    </Badge>
                  </div>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    Tabs checked: {report.tabs_checked.join(", ")}
                  </span>
                  {report.orphans.length > 0 && (
                    <table className="mt-1 w-full text-left text-xs">
                      <thead className="text-zinc-500 dark:text-zinc-400">
                        <tr>
                          <th className="pr-3 py-1 font-medium">Link Ref Code</th>
                          <th className="pr-3 py-1 font-medium">Present in</th>
                          <th className="py-1 font-medium">Missing from</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                        {report.orphans.map((orphan) => (
                          <tr key={orphan.link_ref_code}>
                            <td className="pr-3 py-1">{orphan.link_ref_code}</td>
                            <td className="pr-3 py-1">{orphan.present_in.join(", ")}</td>
                            <td className="py-1 text-red-600 dark:text-red-400">
                              {orphan.missing_from.join(", ")}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
