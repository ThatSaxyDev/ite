## Todo System Overhaul Plan (Scoped, Persistent, UI-Visible)

### Summary
Implement a scoped todo model that cleanly separates planner-internal tasks from user-facing execution tasks, persist todo state in session snapshots, and make execution progress visible consistently across `ite`, `ite --gui`, and `ite --reup`.

### Implementation Changes
- Introduce dual todo scopes: `planning` and `execution`.
- Update `todos` schema to include `scope` (defaulted by phase), and expand actions to `add`, `complete`, `list`, `remove`, `reopen`, `update`, `clear`.
- Keep task IDs stable UUID-short IDs per scope; prevent cross-scope mutation by requiring scope-aware lookup.
- Standardize output metadata for UI rendering: `scope`, `action`, `pending`, `completed`, `total`, `changed_ids`, `message`.
- Remove instruction conflict:
  - Tool description and system prompt both state: initialize execution todos for multi-step work, update as work evolves, complete immediately, remove invalidated tasks.
- Add deterministic agent behavior:
  - In planning phase, todo writes route to `planning`.
  - In execution phase, todo writes route to `execution`.
  - On plan approval, seed `execution` todos from final plan milestones, and keep `planning` todos frozen for traceability.
- Add policy guardrails:
  - Only `planning` scope allowed when `plan_phase != executing`.
  - `execution` scope blocked in planning phase unless explicit handoff event is active.
  - Preserve low-risk approval behavior for todos.
- Persist todos in session snapshot/checkpoints:
  - Add `todos_state` to snapshot payload with both scopes and item lifecycle fields.
  - Restore `todos_state` on session resume for all three surfaces.
- UI visibility updates:
  - Show `execution` todo updates by default in Rich TUI, GUI, and reup.
  - Hide `planning` todo updates by default.
  - Add lightweight “show planning internals” toggle/command per UI surface for debugging/trust transparency.
  - Render execution progress consistently as `X/Y completed` plus scoped list updates.

### Public Interfaces / Data Contract
- `todos` tool params:
  - `action: Literal["add","complete","list","remove","reopen","update","clear"]`
  - `scope: Literal["planning","execution"] | None`
  - `id: str | None`
  - `content: str | None`
  - `items: list[str] | None`
  - `new_content: str | None` (for `update`)
- `SessionSnapshot` additions:
  - `todos_state: {"planning": [...], "execution": [...], "version": 1}`
- UI event contract:
  - Todo tool metadata always includes scope and counts so renderers can apply visibility and progress UI without parsing free text.

### Test Plan
- Tool unit tests:
  - Scope isolation, cross-scope safety, all actions, invalid action/id handling, metadata completeness.
- Agent/policy tests:
  - Planning phase auto-routes to `planning`; execution phase routes to `execution`; blocked invalid scope use in planning.
- Persistence tests:
  - Save/load roundtrip of `todos_state` in sessions and checkpoints; resume restores exact state.
- UI tests:
  - `execution` todos visible by default in all 3 UIs.
  - `planning` todos hidden by default and visible only when toggled.
  - Progress/count rendering consistent with metadata.

### Assumptions and Defaults
- Chosen model: dual scopes (`planning` + `execution`).
- Chosen persistence: embed todo state in session snapshots/checkpoints.
- Chosen UI default: show execution, hide planning internals.
- Planner-to-execution handoff seeds execution todos from final approved plan rather than mutating planning todos in place.
