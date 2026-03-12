# Reup In-Chat Reactive Cards Pattern

This note documents the pattern used in `--reup` to replace blocking modals with in-chat interactive cards.

## Why this pattern

Modal dialogs in Textual can block interaction flow if awaited from the wrong context or if focus gets stuck. In-chat cards keep context visible and feel more natural for long-form agent workflows (planning, approvals, follow-ups).

## Where this is implemented

- Core app: `/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/ui/reup/app.py`
- Styles: `/Users/kiishidavid/Documents/Dev/Projects/ite/src/ite/ui/reup/reup.tcss`

## Current usages

1. Plan-ready action card
- Method: `_present_plan_ready_action_card()`
- Resolver: `_resolve_plan_ready_choice(...)`
- Button handlers: `on_plan_ready_implement(...)`, `on_plan_ready_keep(...)`
- Keyboard fallback in `ReupApp.on_key(...)`

2. Plan-question in-chat card
- Method: `_present_plan_question_card(...)`
- Resolver: `_resolve_plan_question_choice(...)`
- Button handler: `on_plan_question_button_pressed(...)`
- Custom input submit handler: `on_plan_question_custom_submitted(...)`
- Invoked from `plan_question_callback(...)`

## State machine model

Use `Future` + widget refs on `ReupApp`:

- `self._X_future`: pending user choice/result
- `self._X_card`: mounted chat card container
- optional refs: buttons/input/status widgets

Flow:

1. Create future (`loop.create_future()`)
2. Build and mount card into `#conversation`
3. Focus sensible default control
4. Await future
5. Resolve from handlers/keys
6. Disable controls + show captured state
7. Set future result and clear active refs

## Keyboard strategy

Add explicit key routes in `ReupApp.on_key(...)` while a future is active.

Examples:
- Plan-ready: `1/2`, `Enter`, `Y/N`, `Esc`, `Ctrl+C`
- Plan-question: numeric keys for options, `Esc`/`Ctrl+C` for cancel

This makes interaction resilient even when terminal mouse behavior is inconsistent.

## Styling strategy

Use dedicated CSS classes instead of reusing generic system cards:

- `.block.plan` for planning narrative cards
- `.block.plan.plan-ready` for plan decision card
- `.block.plan.plan-question` for question card
- `#pq-*` ids for custom input controls

Guidelines:
- keep borders minimal/subtle
- markdown-first bodies
- concise title + body spacing (`card-title` + `card-body` margins)
- immediate visual state update after selection (disable buttons, show captured summary)

## Reuse recipe for new feature

To build another in-chat decision card:

1. Add state fields on `ReupApp` (`_feature_future`, `_feature_card`, control refs)
2. Add `async _present_feature_card(...)` that mounts and awaits future
3. Add `_resolve_feature_choice(...)` that updates UI and sets future result
4. Add `@on(Button.Pressed, "#..." )` and/or generic handler with id prefix
5. Add optional `Input.Submitted` handler
6. Add keyboard fallbacks in `on_key(...)`
7. Add feature-specific CSS block

## Gotchas

- Do not await modal-like user decisions directly in a UI event path that can starve message pumping.
  - Prefer worker flow (`run_worker`) or in-chat card futures.
- Avoid duplicate IDs across multiple historical cards. Keep active card IDs unique or only rely on refs for the active card.
- If a card remains in history, clear only active refs, not visual content.

## Why this is better for planning

- user can read long plan content while deciding
- avoids disruptive context switching
- allows reactive “captured answer” feedback inline
- better matches conversational UX expectations
