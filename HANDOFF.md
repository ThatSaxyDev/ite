# iTE Reup App Refactoring — Session Handoff

## What we did

Refactored `src/ite/ui/reup/app.py` from a single 14,493-line god class into a modular structure.

## Current file layout

```
src/ite/ui/reup/
├── app.py                    # 1,478 lines — ReupApp: lifecycle, compose, theme, shutdown, run_reup
├── _cloud.py                 # 1,608 — CloudMixin: auth, models, onboarding, updates
├── _panels.py                # 2,544 — PanelsMixin: commands, hooks, change review, aside, meta pickers
├── _composer.py              # 2,214 — ComposerMixin: prompt, palette, voice, plan cards, history
├── _threads.py               # 1,138 — ThreadsMixin: sessions, tabs, thread switcher, naming
├── _turn.py                  # 2,370 — TurnMixin: agent turn, commands, remote runtime, workboard
├── _streaming.py             # 3,002 — StreamingMixin: tool cards, shell cards, rendering, activity
├── _helpers.py               # 85    — Shared helpers (voice error detection, paste, redaction)
├── widgets/                  # 7 files — standalone widget classes extracted from app.py
│   ├── prompt_area.py        # ReupPromptTextArea (handles / key → palette, paste)
│   ├── message_row.py        # UserMessageRow
│   ├── state.py              # SessionRunState, ShellSessionCardState
│   ├── tool_cards.py         # ShellToolCard, CompactToolCard, ToolCardStack + pluralize helpers
│   ├── remote_bridge.py      # RemoteBridgeField, UpdateCommandBox, RemoteBridgeCard
│   ├── side_panels.py        # CommandsSidePanel, HooksSidePanel, ChangeReviewSidePanel
│   ├── thread_switcher.py    # ThreadSwitcherRow, ThreadSwitcherSidePanel
│   └── system_commands.py    # ReupSystemCommandsProvider
└── adapters/
    └── tui_adapter.py        # 166 — ReupTUIAdapter
```

## How it works

```python
class ReupApp(CloudMixin, PanelsMixin, ComposerMixin, ThreadsMixin, TurnMixin, StreamingMixin, App):
    ...
```

Each mixin's methods access `self` directly — zero call-site rewrites. MRO is deterministic: mixins first, then `App`.

## Critical: @on handler re-exports (lines ~342-376 in app.py)

**Textual's metaclass only looks at `cls.__dict__`, NOT the MRO.** All `@on` handlers defined in mixins (which inherit from `object`, not `App`) are invisible to Textual unless explicitly re-exported in the `ReupApp` class body.

35 re-exports at the top of `ReupApp`:
```python
on_prompt_changed = ComposerMixin.on_prompt_changed
on_composer_meta_line_click = ComposerMixin.on_composer_meta_line_click
...
```

If you add a new `@on` handler to ANY mixin, you MUST add a matching re-export line.

## Bugs already fixed from extraction

1. **Missing module-level constants** — `ONBOARDING_OTHER_VALUE`, `CLOUD_NETWORK_ONLINE_PROBE_INTERVAL_SEC`, `_VOICE_TRANSCRIPTION_MAX_RETRIES` moved to `_cloud.py` / `_composer.py` where used.

2. **Missing local imports** — `composer_views`, `change_tree.ChangedFilesTree`, `ChangeConflictError` added to appropriate mixins.

3. **Detached `@on` decorators** — Three decorators landed on wrong methods during extraction. Fixed in `_cloud.py` (`on_cloud_sign_in_pressed`, `on_onboarding_continue_pressed`) and `_threads.py` (`on_thread_switcher_row_selected`).

4. **Stale re-exports for tests** — `ReupPromptTextArea`, `UserMessageRow`, `pluralize_tool_title`, etc. now re-exported at bottom of `app.py`.

## Verification tools

| Check | Command |
|-------|---------|
| Import sanity | `source .venv/bin/activate && python -c "from ite.ui.reup.app import ReupApp, run_reup"` |
| Guard: undefined names in mixins | `python3 scripts/guard_mixin_imports.py` |
| Command palette works | `python direct_test.py` (if present) — should show "Registry seeded: 42 options, Palette visible: True" |
| Test suite | `python -m pytest tests/ -q --ignore=tests/test_setup_modal.py` |
| Lint | `ruff check src/ite/ui/reup/` |
| Type check | `mypy src/ite/ui/reup/app.py --no-error-summary` |

## Baseline metrics (unchanged since original)

- Tests: 58 failed, 724 passed (the 58 failures are pre-existing)
- `scripts/guard_mixin_imports.py`: exits 0 = clean

## Backups

- `app.py.backup` — untouched 14,493-line original
- `app.py.original` — same
- `app_refactored.py` — the refactored version before last swap

## Never do this

1. **Remove or rename a method from a mixin without verifying it's not used by another mixin** — they share `self`.
2. **Add an `@on` handler without a re-export in `app.py`** — it will silently not fire.
3. **Remove the re-exports block** (lines ~342-376 in `app.py`) — all event handling dies.
4. **Edit `app.py.backup`** — it's our safety net.
