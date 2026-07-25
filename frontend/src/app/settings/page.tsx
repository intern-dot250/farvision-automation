"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getSheetsStatus, type SheetConnectionStatus } from "@/lib/api/sheets";

export default function SettingsPage() {
  const [sheets, setSheets] = useState<SheetConnectionStatus[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getSheetsStatus()
      .then((data) => setSheets(data.sheets))
      .catch(() => setError(true));
  }, []);

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
    </div>
  );
}
