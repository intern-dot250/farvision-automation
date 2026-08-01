import { API_BASE_URL, apiFetch, ApiError } from "@/lib/api-client";

export type TransactionSummary = {
  sl_no: string;
  date: string;
  reference: string;
  description: string;
  narration: string;
  head: string;
  destination: string;
  destination_sheet: string | null;
  source_sheet: string | null;
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
  skipped_internal_credit: number;
  transactions: TransactionSummary[];
};

export function runAutomation(dryRun: boolean): Promise<RunResponse> {
  return apiFetch<RunResponse>(`/automation/run?dry_run=${dryRun}`, {
    method: "POST",
  });
}

export type SheetNamesResponse = {
  sheets: string[];
  total_sheets: number;
  ignored_sheets: string[];
};

export async function getSheetNames(file: File): Promise<SheetNamesResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/automation/sheet-names`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      body?.detail ?? `Sheet lookup failed with status ${response.status}`,
    );
  }

  return response.json() as Promise<SheetNamesResponse>;
}

export async function runAutomationUpload(
  file: File,
  dryRun: boolean,
  sheetName?: string,
): Promise<RunResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (sheetName) {
    formData.append("sheet_name", sheetName);
  }

  const response = await fetch(
    `${API_BASE_URL}/automation/run-upload?dry_run=${dryRun}`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      body?.detail ?? `Upload failed with status ${response.status}`,
    );
  }

  return response.json() as Promise<RunResponse>;
}

export type UploadProgress = {
  stage: "classifying" | "writing";
  processed: number;
  total: number;
};

export async function runAutomationUploadStream(
  file: File,
  dryRun: boolean,
  sheetName: string | undefined,
  sheetNames: string[] | undefined,
  onProgress: (progress: UploadProgress) => void,
): Promise<RunResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (sheetNames && sheetNames.length > 0) {
    sheetNames.forEach((name) => formData.append("sheet_names", name));
  } else if (sheetName) {
    formData.append("sheet_name", sheetName);
  }

  const response = await fetch(
    `${API_BASE_URL}/automation/run-upload-stream?dry_run=${dryRun}`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      body?.detail ?? `Upload failed with status ${response.status}`,
    );
  }

  if (!response.body) {
    // Fallback for environments where streaming isn't available - the
    // whole response still arrives, just without incremental progress.
    return response.json() as Promise<RunResponse>;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: RunResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "progress") {
        onProgress({ stage: event.stage, processed: event.processed, total: event.total });
      } else if (event.type === "result") {
        finalResult = event as RunResponse;
      }
    }
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    if (event.type === "result") {
      finalResult = event as RunResponse;
    }
  }

  if (!finalResult) {
    throw new ApiError(500, "Upload stream ended without a result");
  }
  return finalResult;
}
