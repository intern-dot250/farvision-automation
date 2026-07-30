import { apiFetch } from "@/lib/api-client";

export type RunSummary = {
  run_id: string;
  started_at: string | null;
  completed_at: string | null;
  dry_run: boolean | null;
  sheet_names: string[] | null;
  routed_receipt_payment: number | null;
  routed_deposit_withdrawal: number | null;
  needs_review: number | null;
  duplicates_skipped: number | null;
};

export type LogEntry = {
  id: string;
  run_id: string;
  level: string;
  message: string;
  context: Record<string, unknown> | null;
  created_at: string;
};

export type StatsSummary = {
  total_processed: number;
  total_receipt_payment: number;
  total_deposit_withdrawal: number;
};

export function getRuns(limit = 20): Promise<RunSummary[]> {
  return apiFetch<RunSummary[]>(`/runs?limit=${limit}`);
}

export function getLogs(limit = 100): Promise<LogEntry[]> {
  return apiFetch<LogEntry[]>(`/logs?limit=${limit}`);
}

export function getStats(): Promise<StatsSummary> {
  return apiFetch<StatsSummary>("/stats");
}
