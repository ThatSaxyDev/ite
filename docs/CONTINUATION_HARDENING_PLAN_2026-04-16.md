# Continuation Hardening Plan

Date: April 16, 2026

## Problem

iTE has two competing goals:

- do not stop mid-answer when the model clearly ended too early
- do not loop, restart, or visibly duplicate the same answer while trying to recover

The current bug came from the recovery side being too aggressive.

Observed user-facing symptom:

- the model gives a mostly complete answer
- the runtime decides the answer is incomplete
- the runtime asks the model to continue
- the model restarts from the top or partially repeats itself
- the UI ends up showing duplicated answer content or repeated answer blocks

This is especially visible in long structured replies with headings such as:

- `Current Setup`
- `What You Need to Do:`
- `Option 1:`

## What was changed already

Two improvements were applied on April 16, 2026.

### 1. Safer continuation merge

File:

- `src/ite/agent/agent.py`

Before:

- when the agent decided a response was incomplete, it stored the previous partial answer
- on the next turn it simply concatenated `previous_partial + new_response`
- if the model restarted from the top, duplicate text was guaranteed

Now:

- continuation merging is overlap-aware
- if the second response already includes the first, it keeps the fuller version
- if there is a suffix/prefix overlap, it merges only the non-overlapping tail
- only falls back to raw concatenation when there is no overlap at all

Why this is better:

- it preserves the original goal of continuing incomplete answers
- it removes the worst duplicate-content failure mode

### 2. Reup renders the final deduped text

File:

- `src/ite/ui/reup/app.py`

Before:

- the UI streamed raw text deltas
- when the turn ended, Reup finalized the visible message from the raw streaming buffer
- that meant the UI could still show duplicated retry text even if the agent had a cleaner final merged message

Now:

- Reup finalizes from the final `TEXT_COMPLETE` content when available
- this keeps the visible final answer aligned with the corrected final agent output

Why this is better:

- the UI now reflects the actual post-merge answer
- users no longer see the raw duplicated retry stream as the final card

### 3. Narrower incomplete-response trigger

File:

- `src/ite/agent/agent.py`

Before:

- any last line ending in `:` could trigger continuation

Now:

- the check is narrower and more heading-shaped
- long natural-language lines ending in `:` are less likely to trigger a continuation retry

Why this is better:

- fewer false positives
- still preserves recovery for obvious structural truncation

## Why this should be considered an upgrade

Yes, this should be treated as an upgrade, not just a behavior change.

Reason:

- it keeps the intended anti-truncation behavior
- it reduces false-positive continuation
- it removes a visible UX failure where the same content gets repeated
- it aligns the final rendered answer with the actual final agent state

What it does **not** do:

- it does not guarantee perfect continuation detection
- it does not eliminate every case where the model itself may restart or hedge
- it does not fully redesign the continuation policy yet

So the confidence level is:

- high confidence that this is better than the current broken repetition behavior
- medium confidence that it is the final long-term solution

## Remaining weakness

The continuation decision is still heuristic-driven.

Today the main decision still depends mostly on response shape, for example:

- dangling markdown fence
- heading-like last line ending in `:`

That is useful, but not sufficient.

The remaining failure modes are:

- a credible finished answer may still look structurally incomplete
- the model may restart from the top on continuation
- a continuation may be unnecessary even though the text shape suggests otherwise
- different model providers may behave differently on retry

## Recommended next upgrade

The next step should be to move from a shape-only heuristic to a scored continuation decision.

## Proposed design

Add a structured continuation decision function in `src/ite/agent/agent.py`, for example:

- `_should_retry_incomplete_response(...)`

Inputs should include:

- final visible response text
- tool call presence
- finish reason if available
- whether the response ended after execution progress
- whether the answer contains an obvious complete conclusion
- whether the previous retry already happened

### Signals that should increase continuation confidence

- unmatched code fence
- last line is a short heading-like label
- response ends directly after a numbered section opener
- provider stopped with a known truncation-ish finish reason
- answer is extremely short relative to the prompt and clearly unfinished

### Signals that should decrease continuation confidence

- answer already has a strong concluding paragraph
- answer includes a complete recommendation or summary
- answer is read-only and substantively responsive
- retry attempt already happened once
- continuation candidate substantially overlaps previous content
- model restarted with the same opening lines

## Recommended implementation order

### Phase 1. Add continuation scoring

Implement a helper that returns:

- `retry: bool`
- `reason: str`
- `score: int`

This should replace the current yes/no shape-only decision.

### Phase 2. Track retry overlap explicitly

Before accepting a continuation retry:

- compare new text against saved partial text
- if the new text substantially restarts from the beginning, treat that as evidence against further retries
- either merge once and stop, or stop retrying entirely after one restart

### Phase 3. Use finish-reason metadata when available

If the LLM client can expose finish reasons reliably across providers, fold that into the decision.

This is important because:

- `stop` should usually mean “trust the answer unless obviously incomplete”
- truncation-like reasons should favor retry

### Phase 4. Add UX-safe recovery cap

Keep the retry cap very low.

Recommended cap:

- one automatic continuation retry for incomplete-text recovery

Reason:

- if the first retry does not produce a clean completion, repeated retries usually make UX worse

### Phase 5. Add targeted tests

Add tests for:

- short obviously truncated heading
- open code fence
- fully complete answer ending with a colon in natural language
- restart-from-top continuation
- overlap merge with partial continuation
- one retry succeeds
- second retry is suppressed

## Acceptance criteria

This work is done only if all are true:

- incomplete answers still continue when clearly necessary
- complete answers are less likely to trigger continuation
- a restart-from-top retry does not produce duplicated final content
- Reup shows the deduped final answer
- automatic continuation happens at most once per answer

## Suggested files to touch later

- `src/ite/agent/agent.py`
- `src/ite/client/response.py`
- `src/ite/client/llm_client.py`
- `src/ite/ui/reup/app.py`
- `tests/test_agent_continuation.py`
- `tests/test_reup_command_palette.py`
- possibly `tests/test_llm_client.py` if finish reasons are expanded

## Practical recommendation

If credits run out and this work resumes later:

1. Start from this file.
2. Re-read the current continuation code in `src/ite/agent/agent.py`.
3. Keep the overlap-aware merge and the Reup final-text rendering change.
4. Replace the current incomplete-response decision with a scored policy instead of making the old heuristic broader again.

## Bottom line

The current patch is a real improvement.

It fixes the obvious repetition bug without removing the original “don’t stop mid-answer” behavior.

The next improvement should not be “retry more aggressively.”
It should be “decide continuation more intelligently, and retry at most once.”
