# Account Head / Parent Account Head Resolution — Decision Rules

Reference for how `LedgerDetails`' `Account Head`/`Parent Account Head` cells get resolved,
auto-filled, or flagged for manual pick. Each rule is stated as **trigger → required
action**, with why it exists and which code implements it, so a future change can check
"does a rule already cover this case?" before adding a new mechanism.

**Keep this updated.** When a new case is discovered or a rule changes, add/edit an entry
here in the same session, not just in a commit message or code comment.

---

## 1. Exactly one plausible Master candidate → auto-resolve, no dropdown

If a payee/vendor name matches **exactly one** real Master row — via exact match, the
strict fuzzy tier (≥0.92 similarity, same word count), or the looser fuzzy tier (≥0.75
similarity, uniqueness-gated: only auto-accepts when it's the *one and only* candidate that
clears the floor) — write the match directly. No dropdown, no note.

**Why:** a single real candidate is unambiguous; showing a dropdown for a one-option choice
adds friction with no safety benefit.

**Code:** `master_repository.find_party`, `find_party_fuzzy_candidates`,
`find_party_loose_candidates`, `find_party_candidates`; `account_head_resolver.resolve()`'s
`unique_match` branch.

## 2. Two or more genuine candidates, no confident signal → never auto-pick

If a name matches 2+ real, distinct Master rows and neither narration context nor
historical write-majority decisively favors one, **never silently choose one** — attach a
dropdown restricted to just those real candidates, pre-filled with the best-evidenced guess
but requiring a human click to confirm.

**Why:** confirmed empirically this session — loosening any threshold to "just pick the
best match" produced 17–55% false-positive rates on real Master data (e.g. two different
real employees both named "Sanjay Kumar"). A human must always make the final call here.

**Code:** `account_head_resolver.resolve()`'s `no_confident_signal`/ambiguous branch;
`automation_engine._attach_ambiguous_dropdowns`.

## 3. Trusted head, known category, but no payee name at all → category dropdown

If the transaction's head is trusted (e.g. "Salary Site") and maps to a known Parent
Account Head, but no payee name could be extracted from the narration at all, offer a
dropdown of every real Master payee under that same Parent Account Head — narrowed by nothing
else, since there's no name to narrow by.

**Why:** better than a silent blank, and safer than guessing a name from nothing.

**Code:** `classifier._HEAD_TO_PARENT_ACCOUNT_HEAD`,
`master_repository.list_payees_by_parent_account_head`,
`automation_engine._attach_no_match_dropdowns`.

## 4. Genuinely nothing could be inferred → never leave blank

If there's no payee name, no Master candidates, and no category mapping (e.g. a
self-transfer narration like a GST pool account transfer), don't leave the cell blank with
nothing to click. Offer:
- `Account Head`: every distinct Master Account Head value (or a keyword-scoped subset, see
  rule 5), via a range-based dropdown.
- `Parent Account Head`: every real category (~44 values) plus an explicit blank option,
  independently pickable (a deliberate exception — see rule 2's dropdown, which never offers
  Parent Account Head independently, because there IS no real candidate pairing to protect
  when nothing matched at all).

**Code:** `automation_engine._attach_unresolved_full_dropdowns`,
`master_repository.list_all_account_heads`/`list_all_parent_account_heads`.

## 5. Narration/payee text is itself a GST/TDS/Credit-style label → scope the dropdown

If the extracted payee text or narration contains "GST", "TDS", or "Credit"
(case-insensitive substring), narrow the `Account Head` dropdown to only Master entries
that also contain that word — instead of the full list. Applies to:
- True dead-end rows (rule 4) whose narration hints at a category (e.g. a GST pool-account
  transfer).
- **Ambiguous** rows (rule 2) whose extracted payee text is itself category-shaped, not a
  real vendor/person — e.g. `"CREDITOR - AR"` fuzzy-matches 2 real Master rows, but neither
  is a confident "this is the payee" match; here the keyword-scoped list replaces the
  narrow 2-candidate list entirely.

Multiple matched keywords union their lists rather than picking one arbitrarily.

**Why:** a 7,800-entry Account Head dropdown is unusable when the narration already hints
at the right ~100-600-entry subset.

**Code:** `automation_engine._matched_account_head_keywords`,
`master_repository.list_account_heads_matching_keywords`.

## 6. Never override a confident unique match, even if it contains a keyword

Rule 5's keyword override only applies to ambiguous (rule 2) or dead-end (rule 4) rows —
never to a row that already auto-resolved to one confident, unique Master match (rule 1).
A real vendor uniquely matched as e.g. "ABC Creditors Pvt Ltd" keeps that value; it doesn't
get swapped for a generic Credit-scoped dropdown just because its name contains "credit".

**Why:** a confident unique match is already correct — silently second-guessing it on a
keyword coincidence would be a regression, not an improvement.

**Code:** the eligibility check in `automation_engine._attach_ambiguous_dropdowns` only
reaches the keyword branch for rows with `account_head_candidates` set (i.e. already
ambiguous) — it never touches a row with a single confident `matched_master_row`.

## 7. Any dropdown list that could reach ~500 items → must use the range-based mechanism

Google Sheets' inline (`ONE_OF_LIST`) dropdown validation has a **hard API cap of 500
values** — confirmed live via a real 400 error ("Use the 'List from a range' criteria
instead"), not a UX guess. Any option list that could approach or exceed that (the full
Account Head list at ~7,800/company, or even a single keyword like "TDS" alone at ~600)
must use a "List from a range" (`ONE_OF_RANGE`) dropdown sourced from the hidden `Lookup`
helper tab inside the same spreadsheet as the cell being validated — never an inline list.

**Why:** `ONE_OF_RANGE`'s source range must live in the same spreadsheet as the validated
cell; Master itself lives in a different spreadsheet, so the relevant list has to be
mirrored into a same-spreadsheet helper tab first.

**Code:** `sheets_client.get_or_create_worksheet`, `sync_lookup_column`,
`batch_apply_cell_flags`'s `dropdown_range` flag (vs. `dropdown_values` for genuinely small,
safe-inline lists like Parent Account Head's ~44 values).

## 8. Anything syncing into the `Lookup` tab in the same run must share one column cache

`_attach_ambiguous_dropdowns` (rule 5's ambiguous branch) and
`_attach_unresolved_full_dropdowns` (rule 4/5) can both run in the same automation cycle and
both sync into the same `Lookup` tab, assigning the next unused column in encounter order.
They must share **one** column-allocation cache for the run — never one independent cache
per function.

**Why:** two independent per-function counters could both start at column "A" for two
different (company, keyword) combos in the same run; the second sync would silently
overwrite the first's already-referenced source range out from under an already-attached
dropdown.

**Code:** `automation_engine._sync_account_head_lookup_range` (takes `cache` as an explicit
parameter); `run_automation_stream` creates one `account_head_lookup_cache` and passes it to
both attach functions.

## 9. Live/manual sheet fixes → always cross-reference Master first, never guess

Before writing any value directly into a live cell (outside the automated pipeline), check
what `master_repository.find_party`/`find_party_candidates` actually returns for that name:
- Exactly one real match → write that value directly (no dropdown needed).
- Zero matches → apply rule 4 (dropdown fallback), don't fabricate a value.
- 2+ matches → leave as rule 2's dropdown; don't guess which one is correct.

**Why:** confirmed necessary this session — a row that "looked" like a simple typo fix
(e.g. a blank `Parent Account Head`) turned out in one case to already have a confirmed
unique Master match (just not written correctly) and in another to be a genuine dead end —
the two needed completely different fixes, distinguishable only by actually checking Master.

## 10. Empirical validation before loosening any auto-resolve threshold

Before enabling any new or loosened auto-resolve mechanism (e.g. a looser fuzzy-match
floor), test it against real Master data and measure the false-positive rate first. Never
assume a threshold is safe because it "seems reasonable."

**Why:** this is exactly how the unsafe "auto-pick best fuzzy match" approach was caught and
rejected earlier this session (rule 2), and how the safer uniqueness-gated loose tier (rule
1) was validated before shipping.

## 11. Deploy discipline

1. Run the full backend test suite (`backend/.venv/Scripts/python.exe -m pytest`) — must be
   green, including new/updated tests for the change.
2. Push to `origin master`, then deploy via `vercel --prod --yes`.
3. Verify live against the real motivating example (not just unit tests) before considering
   the change done.

**Why:** this project has no staging environment — production is the only real environment,
and several rounds this session caught real issues (a hard 500-item API cap, a range-format
requirement, a column-collision bug) only by checking live behavior after deploying.

---

See also: [`docs/business-rules.md`](business-rules.md) for the original Master-matching /
Internal-detection business rules this system builds on.
