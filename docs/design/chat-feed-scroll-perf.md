# Chat Feed Scroll Performance — Investigation & Fix Plan

**Status:** Investigation complete, not yet implemented
**Scope:** `src/ite/ui/reup/` (Textual Reup runtime, `#conversation` VerticalScroll)
**Symptom:** Scrolling the TUI chat feed becomes progressively slower as the feed grows; degradation is most visible during streaming but persists after the turn completes.

---

## TL;DR

The `#conversation` `VerticalScroll` is a non-virtualized container whose child count grows monotonically with conversation length. Three O(n) operations are executed on every streaming token delta and tool-call tick:

1. **Whole-document markdown re-parse** — `Markdown.update(text)` re-parses the entire assistant turn from scratch on every delta.
2. **Activity indicator remove/remount** — `_pin_activity_indicator_to_end` removes and re-mounts the activity indicator widget on every tick whenever it isn't already the last child.
3. **Full-viewport scroll relayout** — `scroll_end(animate=False)` forces a re-layout of the entire scroll content because `VerticalScroll` lays out every child.

The cost per tick is O(n) in the number of mounted children. As the feed grows, every delta (and every scroll input event) does more work. That matches the reported symptom.

The biggest single win is #1 (stream into a cheap renderable, not `Markdown`, until finalize). #2 and #3 are secondary, cheaper fixes that compound.

---

## 1. Reproduction (expected)

- Open iTE in the TUI.
- Hold a long conversation (50+ turns, several with code blocks and streamed tool output).
- Scroll the feed with `j/k`, `PageUp/PageDown`, mouse wheel, or `End`.
- Observable: scroll input becomes laggy, repaints show visible delay, cursor position in the composer may stutter.

The slowdown is monotonic with feed length, not with the size of the current streaming turn. That points at per-tick work that touches the whole conversation tree, not at the streaming widget itself.

---

## 2. Hot path: what runs on every streaming delta

The agent emits one or more `TEXT_DELTA` events per token. Each delta traverses this path:

`agent turn loop` → `stream_assistant_delta(content)` (`_streaming.py:139`) → `_update_streaming_markdown(buffer)` (`_streaming.py:193`) → `Markdown.update(markdown_text)` → `_pin_activity_indicator_to_end()` (`_streaming.py:151`).

`stream_assistant_delta` (`src/ite/ui/reup/_streaming.py:139-151`):

```python
async def stream_assistant_delta(self, content: str) -> None:
    self._streaming_buffer += content
    conversation = self.query_one("#conversation", VerticalScroll)
    if self._streaming_widget is None:
        self._streaming_widget = Container(
            CopyableMarkdown(""),
            classes="block assistant",
        )
        await conversation.mount(self._streaming_widget)
        self._message_count += 1
        self._refresh_empty_state()
    await self._update_streaming_markdown(self._streaming_buffer)
    await self._pin_activity_indicator_to_end()
```

`_update_streaming_markdown` (`src/ite/ui/reup/_streaming.py:193-208`):

```python
async def _update_streaming_markdown(self, markdown_text: str) -> None:
    if self._streaming_widget is None:
        return
    try:
        markdown_widget = self._streaming_widget.query_one(CopyableMarkdown)
    except Exception:
        if hasattr(self._streaming_widget, "update"):
            code_theme = self._syntax_theme_name()
            self._streaming_widget.update(
                RichMarkdown(
                    markdown_text,
                    code_theme=code_theme,
                )
            )
        return
    await markdown_widget.update(markdown_text)
```

Same pattern is also used for `add_assistant_message` (`_streaming.py:353-356`) and `finalize_streaming_message` (`_streaming.py:154-180`).

---

## 3. The three compounding O(n) costs

### 3.1 Whole-document markdown re-parse per token

`Markdown.update(text)` is a full replace. It re-parses the source, rebuilds the block tree, and re-mounts child widgets (paragraphs, lists, code blocks). It is not an append.

For a single turn this is O(turn-size) per delta. That alone would slow streaming of one long turn. It does **not** by itself explain why scrolling after the turn remains slow — the streamed turn's `Markdown` widget size stabilizes when the turn ends. The remaining slowness is #3.2 and #3.3 below.

### 3.2 Activity indicator remove/remount on every tick

`_pin_activity_indicator_to_end` (`src/ite/ui/reup/app.py:1368-1383`):

```python
async def _pin_activity_indicator_to_end(self) -> None:
    # Skip during bulk hydration - we'll scroll once at the end
    if self._hydrating_from_snapshot:
        return
    conversation = self.query_one("#conversation", VerticalScroll)
    if self._activity_widget is None:
        conversation.scroll_end(animate=False)
        return
    children = list(conversation.children)        # O(n) snapshot
    if children and children[-1] is not self._activity_widget:
        try:
            await self._activity_widget.remove()  # unmount
            await conversation.mount(self._activity_widget)  # remount at end
        except Exception:
            pass
    conversation.scroll_end(animate=False)
```

`_pin_activity_indicator_to_end` is called from at least 16 sites in `_streaming.py` plus `_threads.py:729` and `_composer.py:1870, 2024`, and from `app.py:1366` and `:1486, 1496`. The activity indicator is rarely the last child (it's followed by the streaming widget, tool cards, etc.), so the `remove`/`mount` branch fires on essentially every tick.

The list snapshot is O(n). The remove+remount is a full DOM cycle for one widget plus a parent layout invalidation. The re-mount may also shift other children's positions, which forces a re-layout of the whole scroll content.

There is also a related O(n) pass in `_dedupe_activity_indicators` (`app.py:1385-1417`) that iterates `conversation.children` to find `activity-indicator` matches every time a new indicator is shown.

### 3.3 `VerticalScroll` is not virtualized

`#conversation` is a `VerticalScroll` (composed at `app.py:631`). It lays out **every** child and recomputes `virtual_size` and scrollbar geometry across the full content height on every relayout. `scroll_end()` triggers that relayout. There is no widget recycling.

This is the cost that keeps growing after the turn ends: every `scroll_end` during the turn laid out the whole tree, and subsequent scroll input events (key press, wheel) re-traverse the same layout.

---

## 4. Other observations (not root cause, but worth knowing)

- `_refresh_empty_state` (`_panels.py:869`) is cheap in the steady state (it short-circuits on `_message_count > 0` or `_is_turn_running`), but it is still called on every mount and a few other places. Negligible compared to the three above.
- The streaming path also calls `self._message_count += 1` and `_refresh_empty_state()` when the streaming widget is first created (`_streaming.py:148-149`). One-shot, not per-tick.
- The legacy backup files under `src/ite/ui/reup/legacy/` contain the same logic and would be updated alongside the active code only if a regression is being bisected. They are not the source of truth.
- `UserMessageRow.on_resize` (`widgets/message_row.py:39-40`) calls `refresh_bubble_width` on every resize event. Not in the per-delta hot path, but a long feed means a long resize cascade when the terminal is resized.

---

## 5. Fix plan

Implement in this order. Each step should be independently verifiable and shippable.

### Step 1 — Stop re-parsing markdown on every delta (biggest win)

**Goal:** Streaming should not invoke `Markdown.update` until the turn finalizes.

**Approach:** Stream into a cheap renderable and only swap to a `CopyableMarkdown` once at `finalize_streaming_message`.

- Replace the `CopyableMarkdown("")` initial content with a plain `Static` (or a `RichLog`-style appendable widget if available) that holds the buffered text as a `Text`/string and gets updated cheaply.
- On finalize, remove the `Static`-backed streaming container and mount a `CopyableMarkdown(final_text)` in its place. (Or replace the body widget inside the same container so existing positional state is preserved.)
- Keep the `try/except` fallback in `_update_streaming_markdown` for the case where the widget was created before this change.

**Files touched:**
- `src/ite/ui/reup/_streaming.py` — `stream_assistant_delta`, `finalize_streaming_message`, `_update_streaming_markdown`.

**Verification:**
- Stream a long assistant turn (e.g. 5k tokens). Confirm only one `Markdown.update` per turn (at finalize), not one per delta.
- Confirm `CopyableMarkdown` still renders the full turn with working code-block copy buttons after finalize.

### Step 2 — Stop thrashing the activity indicator

**Goal:** `_pin_activity_indicator_to_end` should be a no-op when the indicator is already at the end, and should not unmount/remount unless strictly necessary.

**Approach:**

- Track whether the activity indicator is the last child via a cached check, not by walking the child list every tick. Options:
  - Cache `_activity_widget_is_last` and invalidate it only on `mount`/`remove` of siblings.
  - Use a single `try: index = conversation.children.index(self._activity_widget); if index == len(conversation.children) - 1: return` early-out that does not allocate a full list when the answer is "yes, already last". (The `index()` call still walks, so this is only an improvement when the indicator is usually last — measure first.)
- Remove the `await self._activity_widget.remove() / await conversation.mount(...)` cycle. If the indicator needs to move, prefer `await conversation.move_child(self._activity_widget, after=...)` if Textual exposes it; otherwise skip the move and only call `scroll_end` (the visual effect of "indicator at the end of the viewport" is achieved by scrolling, not by DOM order, since the user is reading the bottom of the feed anyway).
- Coalesce `_pin_activity_indicator_to_end` calls within a refresh tick. Wrap the body in a `self.call_after_refresh` or a `setTimer(0, ...)` so multiple back-to-back deltas trigger at most one pin per frame.

**Files touched:**
- `src/ite/ui/reup/app.py` — `_pin_activity_indicator_to_end`, `_dedupe_activity_indicators`.

**Verification:**
- Instrument `list(conversation.children)` count or simply log inside `_pin_activity_indicator_to_end`; confirm the number of invocations during a long stream drops dramatically.
- Confirm the activity indicator still appears at the visual bottom during streaming and that the dedupe logic still works (only one indicator at a time).

### Step 3 — Throttle `scroll_end` during streaming

**Goal:** `scroll_end` should fire at most once per refresh tick, not once per delta.

**Approach:**

- Add a `_scroll_end_pending` flag. When set, the next `call_after_refresh` (or equivalent microtask) calls `scroll_end` once and clears the flag.
- Replace the direct `conversation.scroll_end(animate=False)` calls in `_pin_activity_indicator_to_end`, `stream_assistant_delta`, and the streaming-card paths with the coalesced version.
- For the non-streaming paths (turn finalization, snapshot hydration, `End` key) keep the immediate call.

**Files touched:**
- `src/ite/ui/reup/app.py` — new helper `_request_scroll_end`, used by `_pin_activity_indicator_to_end`.
- `src/ite/ui/reup/_streaming.py` — replace direct `scroll_end` in `_scroll_streaming_card_to_end` and finalize paths with the coalesced call.
- `src/ite/ui/reup/_turn.py:849` — keep the immediate call after hydration.

**Verification:**
- Stream a turn with N tokens. Count `scroll_end` calls — should be ≤ refresh rate, not N.
- Confirm auto-follow still tracks the stream tail.

### Step 4 (optional) — Cap mounted history

**Goal:** Bound `n` in the O(n) costs above.

**Approach:**

- Above a threshold (e.g. 200 messages), collapse older user/assistant messages into a single expandable "Earlier history" card. Tool cards and the current streaming widget are never collapsed.
- Re-expand on click.

**Files touched:**
- `src/ite/ui/reup/_streaming.py` — `add_user_message`, `add_assistant_message`, `add_assistant_card`.
- `src/ite/ui/reup/_turn.py` — snapshot hydration path.

**Verification:**
- Confirm scroll latency stabilizes regardless of conversation length.

---

## 6. What I did not investigate (yet)

- Whether Textual's `Markdown.update` has an incremental path we could opt into instead of replacing the streaming container. Worth a quick check of the installed `textual` version's source for any append-friendly API.
- The cost of `RichLog` or other append-only widgets as a streaming target versus a plain `Static` with a `Text` renderable. Pick the cheapest one that gives a visible cursor or end-of-stream marker.
- Whether the composer input widget has its own re-layout cost that contributes to perceived scroll lag. Out of scope for this issue, but flag if repro persists after Step 3.

---

## 7. How to resume in another session

If picking this up cold:

1. Read sections 1–4 for the problem statement.
2. Implement Steps 1, 2, 3 in order. Each is independently testable.
3. To verify, run iTE locally, hold a long conversation, and scroll. Per-delta profiling of `_update_streaming_markdown` and `_pin_activity_indicator_to_end` should show the call count drop and the per-call cost stabilize.
4. The legacy `src/ite/ui/reup/legacy/` files are pre-refactor snapshots. Do not edit them; they are not the source of truth.
5. The relevant files for the fix are:
   - `src/ite/ui/reup/_streaming.py`
   - `src/ite/ui/reup/app.py`
   - `src/ite/ui/reup/_turn.py`
   - `src/ite/ui/reup/_threads.py` (only the `_pin_activity_indicator_to_end` call at line 729)
   - `src/ite/ui/reup/_composer.py` (only the two `_pin_activity_indicator_to_end` calls)
6. The streaming widget is a `Container` with a `CopyableMarkdown` child; the activity indicator is a `Static` with class `activity-indicator`. Their `id`s are not stable — query by class.
