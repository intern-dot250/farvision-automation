"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Combobox } from "@/components/ui/combobox";
import {
  createOverrideRule,
  deleteOverrideRule,
  getAccountHeadOptions,
  getHeadOptions,
  getOverrideRules,
  toggleOverrideRule,
  updateOverrideRule,
  type OverrideRule,
  type OverrideRuleInput,
} from "@/lib/api/override-rules";

const EMPTY_FORM: OverrideRuleInput = {
  description_keyword: "",
  head: "",
  sheet_name: "",
  account_head: "",
  is_active: true,
};

export default function OverrideRulesPage() {
  const [rules, setRules] = useState<OverrideRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [headOptions, setHeadOptions] = useState<string[]>([]);
  const [accountHeadOptions, setAccountHeadOptions] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingRule, setEditingRule] = useState<OverrideRule | null>(null);
  const [form, setForm] = useState<OverrideRuleInput>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadRules = () => {
    getOverrideRules()
      .then((data) => {
        setRules(data);
        setError(null);
      })
      .catch(() => setError("Could not load override rules."));
  };

  useEffect(() => {
    loadRules();
    getHeadOptions()
      .then(setHeadOptions)
      .catch(() => setHeadOptions([]));
    getAccountHeadOptions()
      .then(setAccountHeadOptions)
      .catch(() => setAccountHeadOptions([]));
  }, []);

  const filteredRules = useMemo(() => {
    if (!rules) return null;
    const query = search.trim().toLowerCase();
    if (!query) return rules;
    return rules.filter((rule) =>
      [rule.description_keyword, rule.head, rule.sheet_name, rule.account_head]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [rules, search]);

  const openAddForm = () => {
    setEditingRule(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setShowForm(true);
  };

  const openEditForm = (rule: OverrideRule) => {
    setEditingRule(rule);
    setForm({
      description_keyword: rule.description_keyword,
      head: rule.head,
      sheet_name: rule.sheet_name,
      account_head: rule.account_head,
      is_active: rule.is_active,
    });
    setFormError(null);
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingRule(null);
    setFormError(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      if (editingRule) {
        await updateOverrideRule(editingRule.id, form);
      } else {
        await createOverrideRule(form);
      }
      closeForm();
      loadRules();
    } catch {
      setFormError("Could not save this rule. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (rule: OverrideRule) => {
    setBusyId(rule.id);
    try {
      const updated = await toggleOverrideRule(rule.id, !rule.is_active);
      setRules((prev) => prev?.map((r) => (r.id === rule.id ? updated : r)) ?? prev);
    } catch {
      setError("Could not update rule status.");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (rule: OverrideRule) => {
    if (!confirm(`Delete the override rule for "${rule.description_keyword}"?`)) return;
    setBusyId(rule.id);
    try {
      await deleteOverrideRule(rule.id);
      setRules((prev) => prev?.filter((r) => r.id !== rule.id) ?? prev);
    } catch {
      setError("Could not delete this rule.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
            Override Rules
          </h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Manually override the Account Head assigned to matching transactions.
          </p>
        </div>
        <button
          onClick={openAddForm}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          Add Rule
        </button>
      </div>

      {showForm && (
        <Card title={editingRule ? "Edit Rule" : "Add Rule"}>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Description Keyword
                </label>
                <input
                  required
                  value={form.description_keyword}
                  onChange={(e) => setForm({ ...form, description_keyword: e.target.value })}
                  placeholder="e.g. Ravi Vats"
                  className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Head
                </label>
                <Combobox
                  options={headOptions}
                  value={form.head}
                  onChange={(head) => setForm({ ...form, head })}
                  placeholder="Select a Head"
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Sheet Name
                </label>
                <input
                  required
                  value={form.sheet_name}
                  onChange={(e) => setForm({ ...form, sheet_name: e.target.value })}
                  placeholder="e.g. YES AH IDW 2457"
                  className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Account Head
                </label>
                <Combobox
                  options={accountHeadOptions}
                  value={form.account_head}
                  onChange={(account_head) => setForm({ ...form, account_head })}
                  placeholder="Select an Account Head"
                  required
                />
              </div>
            </div>

            <label className="flex w-fit items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              />
              Active
            </label>

            {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}

            <div className="flex gap-3">
              <button
                type="submit"
                disabled={saving}
                className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
              >
                {saving ? "Saving…" : editingRule ? "Save Changes" : "Add Rule"}
              </button>
              <button
                type="button"
                onClick={closeForm}
                className="rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
            </div>
          </form>
        </Card>
      )}

      <Card title="Rules">
        <div className="mb-4">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by keyword, head, sheet, or account head…"
            className="w-full max-w-sm rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
        </div>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {!error && !rules && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
        )}
        {!error && rules && filteredRules && filteredRules.length === 0 && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {rules.length === 0 ? "No override rules yet." : "No rules match your search."}
          </p>
        )}

        {!error && filteredRules && filteredRules.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-zinc-500 dark:text-zinc-400">
                <tr>
                  <th className="px-3 py-2 font-medium">Description Keyword</th>
                  <th className="px-3 py-2 font-medium">Head</th>
                  <th className="px-3 py-2 font-medium">Sheet Name</th>
                  <th className="px-3 py-2 font-medium">Account Head</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {filteredRules.map((rule) => (
                  <tr key={rule.id}>
                    <td className="px-3 py-2">{rule.description_keyword}</td>
                    <td className="px-3 py-2">{rule.head}</td>
                    <td className="px-3 py-2">{rule.sheet_name}</td>
                    <td className="px-3 py-2">{rule.account_head}</td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => handleToggle(rule)}
                        disabled={busyId === rule.id}
                        className="disabled:opacity-50"
                      >
                        <Badge tone={rule.is_active ? "success" : "neutral"}>
                          {rule.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-3">
                        <button
                          onClick={() => openEditForm(rule)}
                          className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleDelete(rule)}
                          disabled={busyId === rule.id}
                          className="text-sm font-medium text-red-600 hover:underline disabled:opacity-50 dark:text-red-400"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
