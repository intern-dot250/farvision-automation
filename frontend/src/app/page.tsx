"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getStats, type StatsSummary } from "@/lib/api/history";
import {
  clearSheetData,
  getGoogleSheetTabs,
  getSheetNames,
  runAutomationGoogleSheetStream,
  runAutomationUploadStream,
  type ClearSheetApiResponse,
  type ClearSheetTarget,
  type RunResponse,
  type UploadProgress,
} from "@/lib/api/automation";
import { getSheetsStatus } from "@/lib/api/sheets";

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [sheetLinks, setSheetLinks] = useState<Record<string, string>>({});
  const [file, setFile] = useState<File | null>(null);
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

  const [sourceMode, setSourceMode] = useState<"file" | "google_sheet">("file");
  const [sheetUrl, setSheetUrl] = useState("");
  const [spreadsheetId, setSpreadsheetId] = useState<string | null>(null);
  const [sheetUrlError, setSheetUrlError] = useState<string | null>(null);

  const [showClearPanel, setShowClearPanel] = useState(false);
  const [clearTarget, setClearTarget] = useState<ClearSheetTarget>("receipt_payment");
  const [clearConfirmText, setClearConfirmText] = useState("");
  const [clearing, setClearing] = useState(false);
  const [clearResult, setClearResult] = useState<ClearSheetApiResponse | null>(null);
  const [clearError, setClearError] = useState<string | null>(null);

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

  // Refresh the stats cards periodically while a run is in progress, not
  // just once after the upload's promise resolves - so the numbers still
  // update even if that one request stalls or the connection has trouble,
  // instead of requiring a manual page reload to see them.
  useEffect(() => {
    if (!running) return;
    const interval = setInterval(loadStats, 5000);
    return () => clearInterval(interval);
  }, [running]);

  const resetSheetSelectionState = () => {
    setResult(null);
    setRunError(null);
    setSheetOptions([]);
    setSelectedSheetNames([]);
    setTotalSheets(0);
    setIgnoredSheets([]);
    setShowIgnored(false);
  };

  const handleSourceModeChange = (mode: "file" | "google_sheet") => {
    setSourceMode(mode);
    setFile(null);
    setSheetUrl("");
    setSpreadsheetId(null);
    setSheetUrlError(null);
    resetSheetSelectionState();
  };

  const handleFileChange = (selected: File | null) => {
    setFile(selected);
    resetSheetSelectionState();

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
          setSelectedSheetNames(data.sheets.slice(0, 1));
        } else {
          setSelectedSheetNames(data.sheets.slice(0, 1));
        }
      })
      .catch(() => setSheetOptions([]))
      .finally(() => setSheetOptionsLoading(false));
  };

  const handleLoadGoogleSheet = () => {
    setSheetUrlError(null);
    resetSheetSelectionState();
    setSpreadsheetId(null);

    if (!sheetUrl.trim()) {
      setSheetUrlError("Please enter a valid Google Sheets URL.");
      return;
    }

    setSheetOptionsLoading(true);
    getGoogleSheetTabs(sheetUrl.trim())
      .then((data) => {
        setSpreadsheetId(data.spreadsheet_id);
        setSheetOptions(data.sheets);
        setTotalSheets(data.total_sheets);
        setIgnoredSheets(data.ignored_sheets);
        setSelectedSheetNames(data.sheets.slice(0, 1));
      })
      .catch((err) => {
        setSheetUrlError(err instanceof Error ? err.message : "Please enter a valid Google Sheets URL.");
      })
      .finally(() => setSheetOptionsLoading(false));
  };

  const handleRun = async (dryRun: boolean) => {
    if (sourceMode === "file") {
      if (!file) return;
    } else {
      if (!spreadsheetId || selectedSheetNames.length === 0) return;
    }

    setRunning(true);
    setRunError(null);
    setProgress(null);
    try {
      const response =
        sourceMode === "file"
          ? await runAutomationUploadStream(
              file as File,
              dryRun,
              undefined,
              selectedSheetNames.length > 0 && selectedSheetNames.length < sheetOptions.length
                ? selectedSheetNames
                : undefined,
              setProgress,
            )
          : await runAutomationGoogleSheetStream(
              spreadsheetId as string,
              selectedSheetNames,
              dryRun,
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

  const handleClearSheets = async () => {
    if (clearConfirmText !== "DELETE") return;

    setClearing(true);
    setClearError(null);
    setClearResult(null);
    try {
      const response = await clearSheetData(clearTarget);
      setClearResult(response);
      setShowClearPanel(false);
      setClearConfirmText("");
      loadStats();
    } catch (err) {
      setClearError(err instanceof Error ? err.message : "Clear failed");
    } finally {
      setClearing(false);
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
          <div className="flex w-fit rounded-md border border-zinc-300 p-0.5 text-sm dark:border-zinc-700">
            <button
              type="button"
              onClick={() => handleSourceModeChange("file")}
              disabled={running}
              className={`rounded px-3 py-1.5 font-medium transition-colors ${
                sourceMode === "file"
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              }`}
            >
              Upload File
            </button>
            <button
              type="button"
              onClick={() => handleSourceModeChange("google_sheet")}
              disabled={running}
              className={`rounded px-3 py-1.5 font-medium transition-colors ${
                sourceMode === "google_sheet"
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              }`}
            >
              Google Sheet
            </button>
          </div>

          {sourceMode === "file" ? (
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
          ) : (
            <div className="flex flex-col gap-2">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">
                Google Sheet URL
              </span>
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={sheetUrl}
                  disabled={running}
                  onChange={(e) => setSheetUrl(e.target.value)}
                  placeholder="https://docs.google.com/spreadsheets/d/…/edit"
                  className="min-w-[280px] flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
                <button
                  type="button"
                  onClick={handleLoadGoogleSheet}
                  disabled={running || sheetOptionsLoading || !sheetUrl.trim()}
                  className="w-fit rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
                >
                  Load Sheet
                </button>
              </div>
              {sheetUrlError && (
                <p className="text-sm text-red-600 dark:text-red-400">{sheetUrlError}</p>
              )}
            </div>
          )}

          {sheetOptionsLoading && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {sourceMode === "file" ? "Reading sheet names…" : "Fetching spreadsheet…"}
            </p>
          )}

          {!sheetOptionsLoading && sheetOptions.length > 1 && (
            <label className="flex flex-col gap-2">
              <span className="text-sm text-zinc-600 dark:text-zinc-400">
                {selectedSheetNames.length === 0
                  ? sourceMode === "google_sheet"
                    ? "Please select at least one sheet to process."
                    : `${sheetOptions.length} sheets — processing all (nothing selected)`
                  : selectedSheetNames.length === sheetOptions.length && sourceMode === "file"
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
                {totalSheets} sheet{totalSheets === 1 ? "" : "s"} found{" "}
                {sourceMode === "file" ? "in file" : "in spreadsheet"}
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

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => handleRun(true)}
              disabled={
                running ||
                sheetOptionsLoading ||
                (sourceMode === "file" ? !file : !spreadsheetId || selectedSheetNames.length === 0)
              }
              className="w-fit rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
            >
              {running ? "Processing..." : sourceMode === "file" ? "Preview Upload" : "Preview Selected Sheets"}
            </button>
            <button
              onClick={() => handleRun(false)}
              disabled={
                running ||
                sheetOptionsLoading ||
                (sourceMode === "file" ? !file : !spreadsheetId || selectedSheetNames.length === 0)
              }
              className="w-fit rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50 dark:bg-emerald-500 dark:hover:bg-emerald-600"
            >
              {running ? "Processing..." : "Write to Google Sheets"}
            </button>
            <button
              onClick={() => {
                setShowClearPanel((v) => !v);
                setClearConfirmText("");
                setClearError(null);
              }}
              disabled={running || clearing}
              className="w-fit rounded-md border border-red-600 px-4 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-500 dark:text-red-500 dark:hover:bg-red-950/40"
            >
              Clear Sheet Data
            </button>
          </div>

          {showClearPanel && (
            <div className="flex flex-col gap-3 rounded-md border border-red-300 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/30">
              <p className="text-sm font-medium text-red-800 dark:text-red-300">
                This permanently erases every row (all tabs except Info) in
                the selected sheet. This cannot be undone from this app.
              </p>

              <label className="flex flex-col gap-1">
                <span className="text-sm text-zinc-700 dark:text-zinc-300">
                  Sheet to erase
                </span>
                <select
                  value={clearTarget}
                  onChange={(e) => setClearTarget(e.target.value as ClearSheetTarget)}
                  disabled={clearing}
                  className="w-fit rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                >
                  <option value="receipt_payment">Receipt / Payment</option>
                  <option value="deposit_withdrawal">Deposit / Withdrawal</option>
                  <option value="both">Both</option>
                </select>
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-sm text-zinc-700 dark:text-zinc-300">
                  Type <span className="font-mono font-semibold">DELETE</span> to confirm
                </span>
                <input
                  type="text"
                  value={clearConfirmText}
                  onChange={(e) => setClearConfirmText(e.target.value)}
                  disabled={clearing}
                  placeholder="DELETE"
                  className="w-48 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
              </label>

              <div className="flex gap-2">
                <button
                  onClick={handleClearSheets}
                  disabled={clearing || clearConfirmText !== "DELETE"}
                  className="w-fit rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
                >
                  {clearing ? "Erasing..." : "Confirm Erase"}
                </button>
                <button
                  onClick={() => {
                    setShowClearPanel(false);
                    setClearConfirmText("");
                  }}
                  disabled={clearing}
                  className="w-fit rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {clearError && (
            <p className="text-sm text-red-600 dark:text-red-400">{clearError}</p>
          )}

          {clearResult && (
            <div className="flex flex-col gap-1 rounded-md border border-zinc-200 p-3 text-sm dark:border-zinc-800">
              <span className="font-medium text-zinc-900 dark:text-zinc-100">
                Cleared successfully:
              </span>
              {clearResult.sheets_cleared.map((s) => (
                <span key={s.sheet} className="text-zinc-600 dark:text-zinc-400">
                  {s.sheet}: {s.tabs_cleared.join(", ")}
                </span>
              ))}
            </div>
          )}

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
                <Badge tone="neutral">
                  {result.skipped_internal_credit} internal-credit legs skipped
                </Badge>
                <Badge tone="neutral">
                  {result.skipped_collection} collection entries skipped
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
                      <th className="px-3 py-2 font-medium">Narration</th>
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
                                : txn.destination === "duplicate" ||
                                    txn.destination === "skipped_internal_credit" ||
                                    txn.destination === "skipped_collection"
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
                        <td className="max-w-xs whitespace-normal break-words px-3 py-2 text-zinc-600 dark:text-zinc-400">
                          {txn.description}
                        </td>
                        <td className="max-w-xs whitespace-normal break-words px-3 py-2 text-zinc-600 dark:text-zinc-400">
                          {txn.narration}
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
