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

export type OrphanEntry = {
  link_ref_code: string;
  present_in: string[];
  missing_from: string[];
};

export type DestinationOrphanReport = {
  destination: string;
  tabs_checked: string[];
  orphans: OrphanEntry[];
};

export type OrphanCheckResponse = {
  reports: DestinationOrphanReport[];
};

export function getOrphanReport(): Promise<OrphanCheckResponse> {
  return apiFetch<OrphanCheckResponse>("/sheets/orphans");
}
