import re
from collections import Counter
from dataclasses import dataclass

from app.core.logger import logger
from app.services import master_repository

_STOPWORDS = {
    "the", "a", "an", "for", "to", "of", "and", "or", "in", "on", "at",
    "from", "by", "with", "payment", "purpose", "ref", "narration", "type",
    "bu", "head",
}

_WORD_RE = re.compile(r"[A-Za-z]{3,}")


@dataclass
class ResolveResult:
    row: dict | None
    ambiguous: bool
    reason: str
    confidence: float
    candidates: list[dict]


def _candidate_key(row: dict) -> tuple[str, str]:
    """The (Account Head, Parent Account Head) pair identifying a genuinely
    distinct option - shared by dedupe_candidates and resolve()'s historical
    lookup so both agree on what counts as "the same" head."""
    return (
        str(row.get("Account Head", "")).strip().upper(),
        str(row.get("Parent Account Head", "")).strip().upper(),
    )


def dedupe_candidates(rows: list[dict]) -> list[dict]:
    """Collapse Master rows sharing the same (Account Head, Parent Account
    Head) pair down to one representative row each, preserving first-seen
    order. Real Master data has near-duplicate rows for the same effective
    head (e.g. differing only in blank Deduction Type/Description) that
    aren't genuinely different options a person needs to choose between.
    """
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = _candidate_key(row)
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped


def dropdown_targets(candidates: list[dict]) -> dict[str, list[str]]:
    """"Account Head" is the only field ever offered as a dropdown for an
    ambiguous beneficiary - it's the true unique key in Master, and
    elsewhere in this codebase Parent Account Head is always *derived from*
    whichever Account Head matched (see
    automation_engine._build_receipt_payment_rows), never picked
    independently. An earlier version of this function also offered Parent
    Account Head as its own independent dropdown, which let someone pick a
    Parent Account Head value that didn't correspond to whatever Account
    Head text was still sitting in the cell - a combination that may not
    match any real Master row.

    Distinct real Account Head values become the options. When two or more
    candidates share literally the same Account Head text but differ in
    Parent Account Head (the common real-data shape - most of the 42
    duplicate-beneficiary cases found in Master), each option is
    disambiguated by appending that row's own Parent Account Head in
    parentheses, e.g. "Rajesh Kumar.. (SALARY PAYABLE)" - so every option
    still uniquely identifies one real Master row, and Parent Account Head
    is never exposed as an independently-pickable field.

    Returns {} if there's only one genuinely distinguishable option (nothing
    left to pick between).
    """
    if len(candidates) < 2:
        return {}

    account_heads = [str(c.get("Account Head", "")).strip() for c in candidates]
    if len(set(h for h in account_heads if h)) >= 2:
        values: list[str] = []
        seen: set[str] = set()
        for head in account_heads:
            if head and head not in seen:
                seen.add(head)
                values.append(head)
        return {"Account Head": values} if len(values) >= 2 else {}

    # Account Head text alone doesn't distinguish the candidates - fall back
    # to a synthesized "Account Head (Parent Account Head)" label per row, so
    # the dropdown still lets someone pick the correct real row without ever
    # exposing Parent Account Head as its own independent choice.
    values = []
    seen = set()
    for candidate in candidates:
        head = str(candidate.get("Account Head", "")).strip()
        parent = str(candidate.get("Parent Account Head", "")).strip()
        if not head or not parent:
            continue
        label = f"{head} ({parent})"
        if label not in seen:
            seen.add(label)
            values.append(label)
    return {"Account Head": values} if len(values) >= 2 else {}


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOPWORDS}


def _context_score(context_words: set[str], candidate: dict) -> int:
    candidate_text = f"{candidate.get('Parent Account Head', '')} {candidate.get('Account Head', '')}"
    return len(context_words & _keywords(candidate_text))


def resolve(
    payee_name: str | None,
    company: str | None,
    candidates: list[dict],
    context_text: str | None = None,
    history: dict[str, Counter] | None = None,
) -> ResolveResult:
    """Pick the right Account Head for a beneficiary that matched more than
    one Master row, without ever silently guessing.

    Priority order: unique match -> historical majority (from Account Heads
    already written for this payee) -> narration/context keyword overlap
    against each candidate's Parent Account Head -> otherwise flagged
    ambiguous (never a random/first-row pick) for the caller to write with a
    placeholder plus an in-sheet dropdown.
    """
    deduped = dedupe_candidates(candidates)

    if not deduped:
        return ResolveResult(row=None, ambiguous=False, reason="no_match", confidence=1.0, candidates=[])

    if len(deduped) == 1:
        selected = deduped[0]
        logger.info(
            f"[account_head_resolver] beneficiary={payee_name!r} candidates=1 "
            f"selected={selected.get('Account Head')!r} confidence=1.00 reason=unique_match"
        )
        return ResolveResult(row=selected, ambiguous=False, reason="unique_match", confidence=1.0, candidates=deduped)

    heads = [str(c.get("Account Head")) for c in deduped]

    # Level: historical majority - only decisive if one candidate strictly
    # dominates the payee's write history; a tie (or no history) falls
    # through rather than forcing a pick (see resolve()'s Test 7). Keyed on
    # the same (Account Head, Parent Account Head) pair as dedupe_candidates,
    # not Account Head alone - real duplicate-beneficiary rows usually share
    # a near-identical Account Head and differ only in Parent Account Head,
    # so Account Head alone can't tell them apart.
    normalized_payee = master_repository._normalize(payee_name) if payee_name else ""
    payee_history = (history or {}).get(normalized_payee)
    if payee_history:
        candidate_by_key = {_candidate_key(c): c for c in deduped}
        relevant = {
            key: count for key, count in payee_history.items()
            if key in candidate_by_key
        }
        if relevant:
            best_key, best_count = max(relevant.items(), key=lambda kv: kv[1])
            other_counts = [count for key, count in relevant.items() if key != best_key]
            if not other_counts or best_count > max(other_counts):
                selected = candidate_by_key[best_key]
                confidence = best_count / sum(relevant.values())
                logger.info(
                    f"[account_head_resolver] beneficiary={payee_name!r} candidates={heads} "
                    f"selected={selected.get('Account Head')!r} confidence={confidence:.2f} reason=historical_majority"
                )
                return ResolveResult(
                    row=selected, ambiguous=False, reason="historical_majority",
                    confidence=confidence, candidates=deduped,
                )

    # Level: narration/context keyword overlap against each candidate's
    # Parent Account Head - only decisive when exactly one candidate has a
    # strictly higher score than every other.
    context_words = _keywords(context_text or "")
    if context_words:
        scored = sorted(
            ((_context_score(context_words, c), c) for c in deduped),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_score, best_candidate = scored[0]
        runner_up_score = scored[1][0] if len(scored) > 1 else 0
        if best_score > 0 and best_score > runner_up_score:
            confidence = min(0.5 + 0.1 * best_score, 0.95)
            logger.info(
                f"[account_head_resolver] beneficiary={payee_name!r} candidates={heads} "
                f"selected={best_candidate.get('Account Head')!r} confidence={confidence:.2f} "
                f"reason=narration_context_match"
            )
            return ResolveResult(
                row=best_candidate, ambiguous=False, reason="narration_context_match",
                confidence=confidence, candidates=deduped,
            )

    logger.warning(
        f"[account_head_resolver] beneficiary={payee_name!r} candidates={heads} "
        f"REVIEW_REQUIRED reason=no_confident_signal - dropdown required"
    )
    return ResolveResult(
        row=deduped[0], ambiguous=True, reason="no_confident_signal",
        confidence=0.0, candidates=deduped,
    )
