"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getStats, type StatsSummary } from "@/lib/api/history";
import {
  getSheetNames,
  runAutomationUploadStream,
  type RunResponse,
  type UploadProgress,
} from "@/lib/api/automation";
import { getSheetsStatus } from "@/lib/api/sheets";

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [sheetLinks, setSheetLinks] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [sheetOptions, setSheetOptions] = useState<string[]>([]);
  const [selectedSheetNames, setSelectedSheetNames] = useState<string[]>([]);
  const [sheetOptionsLoading, setSheetOptionsLoading] = useState(false);
  const [totalSheets, setTotalSheets] = useState(0);
  const [ignoredSheets, setIgnoredSheets] = useState<string[]>([]);
  const [showIgnored, setShowIgnored] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);

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
    getSheetsStatus()
      .then((data) => {
        const links: Record<string, string> = {};
        for (const sheet of data.sheets) {
          links[sheet.name] = `https://docs.google.com/spreadsheets/d/${sheet.sheet_id}/edit`;
        }
        setSheetLinks(links);
      })
      .catch(() => {});
  }, []);

  const handleFileChange = (selected: File | null) => {
    setFile(selected);
    setResult(null);
    setRunError(null);
    setSheetOptions([]);
    setSelectedSheetNames([]);
    setTotalSheets(0);
    setIgnoredSheets([]);
    setShowIgnored(false);

    if (!selected || !/\.xlsx?$/i.test(selected.name)) {
      return;
    }

    setSheetOptionsLoading(true);
    getSheetNames(selected)
      .then((data) => {
        setSheetOptions(data.sheets);
        setTotalSheets(data.total_sheets);
        setIgnoredSheets(data.ignored_sheets);
        if (data.sheets.length === 1) {
          setSheetName(data.sheets[0]);
          setSelectedSheetNames(data.sheets.slice(0, 1));
        } else {
          setSelectedSheetNames(data.sheets.slice(0, 1));
        }
      })
      .catch(() => setSheetOptions([]))
      .finally(() => setSheetOptionsLoading(false));
  };

  const handleRun = async () => {
    if (!file) return;

    setRunning(true);
    setRunError(null);
    setProgress(null);
    try {
      const response = await runAutomationUploadStream(
        file,
        dryRun,
        undefined,
        selectedSheetNames.length > 0 && selectedSheetNames.length < sheetOptions.length
          ? selectedSheetNames
          : undefined,
        setProgress,
      );
      setResult(response);
      loadStats();
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "Run failed");
    } finally {
      setRunning(false);
      setProgress(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Upload today&apos;s bank statement to classify and route transactions.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card title="Total Processed">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {statsError ? "—" : (stats?.total_processed ?? "…")}
          </p>
        </Card>
        <Card title="Receipt/Payment">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {statsError ? "—" : (stats?.total_receipt_payment ?? "…")}
          </p>
          {sheetLinks["Receipt / Payment"] && (
            <a
              href={sheetLinks["Receipt / Payment"]}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-block text-xs text-blue-600 hover:underline dark:text-blue-400"
            >
              Open sheet ↗
            </a>
          )}
        </Card>
        <Card title="Deposit/Withdrawal">
          <p className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
            {statsError ? "—" : (stats?.total_deposit_withdrawal ?? "…")}
          </p>
          {sheetLinks["Deposit / Withdrawal"] && (
            <a
              href={sheetLinks["Deposit / Withdrawal"]}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-block text-xs text-blue-600 hover:underline dark:text-blue-400"
            >
              Open sheet ↗
            </a>
          )}
        </Card>
      </div>

      <Card title="Upload Bank Statement">
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-2">
            <span className="text-sm text-zinc-600 dark:text-zinc-400">
              Statement file (.xlsx or .csv)
            </span>
            <input
              type="file"
              accept=".xlsx,.xls,.csv"
              disabled={running}
              onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
              className="text-sm text-zinc-600 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-900 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-zinc-700 dark:text-zinc-400 dark:file:bg-zinc-100 dark:file:text-zinc-900 dark:hover:file:bg-zinc-300"
            />
          </label>

          {sheetOptionsLoading && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Reading sheet names…
            </p>
          )}

          {!sheetOptionsLoading && sheetOptions.length > 1 && (
            <label className="flex flex-col gap-2">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">
                {selectedSheetNames.length === 0
                  ? `${sheetOptions.length} sheets — processing all (nothing selected)`
                  : selectedSheetNames.length === sheetOptions.length
                    ? `${sheetOptions.length} sheets — processing all`
                    : `${selectedSheetNames.length} selected: ${selectedSheetNames.join(", ")}`}
              </span>
              <div className="max-h-60 overflow-y-auto rounded-md border border-zinc-300 p-2 dark:border-zinc-700 dark:bg-zinc-900">
                {sheetOptions.map((name) => {
                  const checked = selectedSheetNames.includes(name);
                  return (
                    <label
                      key={name}
                      className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          setSelectedSheetNames((prev) =>
                            e.target.checked
                              ? [...prev, name]
                              : prev.filter((n) => n !== name)
                          );
                        }}
                        disabled={running}
                        className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
                      />
                      <span className="text-sm text-zinc-700 dark:text-zinc-300">{name}</span>
                    </label>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={() => {
                  if (selectedSheetNames.length === sheetOptions.length) {
                    setSelectedSheetNames([]);
                  } else {
                    setSelectedSheetNames([...sheetOptions]);
                  }
                }}
                className="w-fit rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800"
              >
                {selectedSheetNames.length === sheetOptions.length ? "Deselect all" : "Select all"}
              </button>
            </label>
          )}

          {!sheetOptionsLoading && totalSheets > 0 && (
            <div className="flex flex-col gap-1 rounded-md border border-zinc-200 px-3 py-2 dark:border-zinc-800">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">
                {totalSheets} sheet{totalSheets === 1 ? "" : "s"} found in file
                {ignoredSheets.length > 0
                  ? ` — ${ignoredSheets.length} ignored (no transaction data detected)`
                  : " — all used"}
              </span>
              {ignoredSheets.length > 0 && (
                <div className="mt-1">
                  <button
                    type="button"
                    onClick={() => setShowIgnored(!showIgnored)}
                    className="rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-xs text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800"
                  >
                    {showIgnored ? "Hide" : `Show ${ignoredSheets.length} ignored sheets`}
                  </button>
                  {showIgnored && (
                    <ul className="mt-1.5 max-h-48 overflow-y-auto rounded-md border border-zinc-200 bg-white p-2 text-xs dark:border-zinc-700 dark:bg-zinc-900">
                      {ignoredSheets.map((name) => (
                        <li
                          key={name}
                          className="whitespace-nowrap px-2 py-0.5 text-zinc-600 dark:text-zinc-400"
                        >
                          {name}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}

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
            disabled={running || !file}
            className="w-fit rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {running
              ? "Processing..."
              : dryRun
                ? "Preview Upload"
                : "Upload & Write to Sheets"}
          </button>

          {running && (
            <div className="flex flex-col gap-1">
              <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                <div
                  className="h-full rounded-full bg-zinc-900 transition-all duration-200 dark:bg-zinc-100"
                  style={{
                    width: progress && progress.total > 0
                      ? `${Math.round((progress.processed / progress.total) * 100)}%`
                      : "5%",
                  }}
                />
              </div>
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                {progress && progress.total > 0
                  ? `${progress.stage === "writing" ? "Writing to sheets" : "Classifying"} — ${progress.processed}/${progress.total} (${Math.round((progress.processed / progress.total) * 100)}%)`
                  : "Starting…"}
              </span>
            </div>
          )}

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
                      <th className="px-3 py-2 font-medium">Date</th>
                      <th className="px-3 py-2 font-medium">Payee</th>
                      <th className="px-3 py-2 font-medium">Source Sheet</th>
                      <th className="px-3 py-2 font-medium">Head</th>
                      <th className="px-3 py-2 font-medium">Destination</th>
                      <th className="px-3 py-2 font-medium">Sheet</th>
                      <th className="px-3 py-2 font-medium">Description</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {result.transactions.map((txn) => (
                      <tr key={txn.sl_no}>
                        <td className="px-3 py-2">{txn.sl_no}</td>
                        <td className="px-3 py-2 whitespace-nowrap text-zinc-600 dark:text-zinc-400">
                          {txn.date}
                        </td>
                        <td className="px-3 py-2">{txn.payee_name ?? "—"}</td>
                        <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
                          {txn.source_sheet ?? "—"}
                        </td>
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
                        <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
                          {txn.destination === "duplicate"
                            ? (txn.destination_sheet ?? "—")
                            : txn.destination === "receipt_payment"
                              ? "Receipt / Payment"
                              : txn.destination === "deposit_withdrawal"
                                ? "Deposit / Withdrawal"
                                : "—"}
                        </td>
                        <td
                          className="max-w-xs truncate px-3 py-2 text-zinc-600 dark:text-zinc-400"
                          title={txn.description}
                        >
                          {txn.description}
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
