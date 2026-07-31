import { apiFetch } from "@/lib/api-client";

export type OverrideRule = {
  id: number;
  description_keyword: string;
  head: string;
  sheet_name: string;
  account_head: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type OverrideRuleInput = {
  description_keyword: string;
  head: string;
  sheet_name: string;
  account_head: string;
  is_active: boolean;
};

export function getOverrideRules(): Promise<OverrideRule[]> {
  return apiFetch<OverrideRule[]>("/override-rules");
}

export function createOverrideRule(data: OverrideRuleInput): Promise<OverrideRule> {
  return apiFetch<OverrideRule>("/override-rules", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateOverrideRule(id: number, data: OverrideRuleInput): Promise<OverrideRule> {
  return apiFetch<OverrideRule>(`/override-rules/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function toggleOverrideRule(id: number, isActive: boolean): Promise<OverrideRule> {
  return apiFetch<OverrideRule>(`/override-rules/${id}/toggle`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
}

export function deleteOverrideRule(id: number): Promise<void> {
  return apiFetch<void>(`/override-rules/${id}`, { method: "DELETE" });
}

export function getHeadOptions(): Promise<string[]> {
  return apiFetch<{ heads: string[] }>("/master/heads").then((r) => r.heads);
}

export function getAccountHeadOptions(): Promise<string[]> {
  return apiFetch<{ account_heads: string[] }>("/master/account-heads").then(
    (r) => r.account_heads,
  );
}
