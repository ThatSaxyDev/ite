# GUI Refactor Mapping (Phase 1 + Phase 2)

This maps major responsibilities from the old monolithic `src/ite/ui/gui.py`
to the new feature-sliced package.

## Public API

- `ite.ui.gui.run_gui` -> `src/ite/ui/gui/app.py`
- `ite.ui.gui.create_gui_app` -> `src/ite/ui/gui/app.py`

## Composition Root

- `GUI` class -> `GUIApp` in `src/ite/ui/gui/app.py`

## Design Tokens

- UI constants/colors/radii/shadows -> `src/ite/ui/gui/tokens.py`

## Layout Builders

- shell/header/sidebar/composer/chat panel assembly ->
  `src/ite/ui/gui/builders/layout.py`

## Message Builders

- chat bubble rendering
- system cards
- tool call cards (start/complete)
- streaming assistant bubble
- expandable content blocks

All moved to `src/ite/ui/gui/builders/messages.py`.

## Controllers

- command execution + native GUI command handling ->
  `src/ite/ui/gui/controllers/commands.py`
- agent event dispatch/rendering ->
  `src/ite/ui/gui/controllers/agent_events.py`
- session autosave/load/resume/hydration/title generation ->
  `src/ite/ui/gui/controllers/sessions.py`
- workspace list/switch/thread refresh ->
  `src/ite/ui/gui/controllers/workspace.py`
- approval mode sync + inline approval cards/callback ->
  `src/ite/ui/gui/controllers/approval.py`
- auto-scroll policy + multi-pass bottom snapping ->
  `src/ite/ui/gui/controllers/scroll.py`

## Adapters

- command context construction helper ->
  `src/ite/ui/gui/adapters/registry.py`

