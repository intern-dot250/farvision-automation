import { apiFetch } from "@/lib/api-client";

export type SheetConnectionStatus = {
  name: string;
  sheet_id: string;
  connected: boolean;
  worksheets: string[];
  error: string | null;
};

export type SheetsStatusResponse = {
  sheets: SheetConnectionStatus[];
};

export function getSheetsStatus(): Promise<SheetsStatusResponse> {
  return apiFetch<SheetsStatusResponse>("/sheets/status");
}
