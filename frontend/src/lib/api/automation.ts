import { apiFetch } from "@/lib/api-client";

export type TransactionSummary = {
  sl_no: string;
  reference: string;
  description: string;
  head: string;
  destination: string;
  payee_name: string | null;
  needs_review: boolean;
  review_reason: string | null;
};

export type RunResponse = {
  run_id: string;
  dry_run: boolean;
  total_transactions: number;
  routed_deposit_withdrawal: number;
  routed_receipt_payment: number;
  needs_review: number;
  duplicates_skipped: number;
  transactions: TransactionSummary[];
};

export function runAutomation(dryRun: boolean): Promise<RunResponse> {
  return apiFetch<RunResponse>(`/automation/run?dry_run=${dryRun}`, {
    method: "POST",
  });
}
