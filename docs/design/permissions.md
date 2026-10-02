# Unified permissions

## Phase 1: complete user flow

`/permissions` opens a native picker over the current chat. The composer displays a clickable `permissions ask|auto|Full access|custom` control. Arrow keys choose a mode; Enter or Select applies it; Escape cancels. There is no Advanced control or command. Descriptions wrap, the content scrolls, and the action row stays visible at 80×24.

| Mode | Workspace file tools | Commands, internet, MCP, child agents | External files |
|---|---|---|---|
| Ask for approval | Reads run; edits ask | Ask | Ask |
| Automatic | Run | Ask | Ask |
| Full access | Run | Run without iTE approval | Run without iTE path restrictions |

Automatic is a conservative rules policy. It is not a separate AI reviewer. Commands always ask in restricted modes because process access is not isolated. Shells and integrations run with the user's operating-system permissions after approval. Existing tool-specific prohibitions can still apply under Full access.

Restricted modes suspend configured hooks, which otherwise execute arbitrary commands outside tool approval. Learning mode retains its execution restrictions under every permissions mode.

External-file approval grants exact resolved paths for one invocation using a ContextVar, propagated to that invocation's worker thread. Grants do not modify trusted directories, leak into simultaneous invocations, or survive cancellation. Child invocations begin with an empty grant context. Authorization runs after validation and tool-selection policy, before hooks and confirmation builders that might inspect file contents. Symlinks resolve before checking boundaries.

The selected preset is saved globally and applied to open idle sessions. Changes are blocked while turns, tools, hooks, or child agents are running. Automatic is the default for configurations without an explicit mode or custom legacy restrictions. Explicit saved modes and legacy custom restrictions are retained. `/approval` and `/sandbox` are removed from discovery and command execution. Trusted paths are configured in .ite/config.toml under [sandbox]. Trusted paths remain workspace configuration; selecting a preset does not erase them. Full → Ask/Automatic restores filesystem checks.

## Next phases

1. Implement actual process isolation per operating system, with explicit filesystem roots and network capability. Route shell, verification, hooks, and subprocess-backed integrations through the same executor. Only then can routine workspace commands run automatically with an enforceable boundary.
2. Add an independent approval reviewer using an isolated model request with a bounded action/transcript schema. It must have no execution tools; approval must match the exact proposed action. Rejection, timeout, malformed responses, or unavailable models fall back to a human decision. Only this mode should be named “Approve for me”.
3. Add a deterministic network policy that also covers subprocesses and integration servers. Keep the public permissions control limited to the three modes; cover migrations and escalation requests in the same TUI acceptance suite.

## Manual TUI acceptance

Restart the local editable app with `.venv/bin/ite` from a disposable project directory.

1. Run `/permissions`. The chat remains visible behind the picker. Cancel: nothing changes. Select Ask for approval; the composer updates to `permissions ask`.
2. Send “Use write_file to create permissions-demo.txt containing hello.” An approval appears. Decline: the file is absent. Ask again and approve: it is created.
3. Select Automatic via the composer control. Ask to create a second file with write_file: it runs without approval. Ask to run `pwd` using the shell: approval appears. Ask to fetch a webpage: approval appears even though the tool is read-only.
4. Create a harmless text file outside the project. Ask iTE to read its absolute path using read_file. Decline: no contents appear. Approve on a later attempt: it is read. Ask again: another approval is required.
5. Select Full access; repeat the harmless file read and `pwd`: no iTE permission prompt. Return to Ask; prompts return. Restart and check `/permissions status` retains Ask.
6. Enable `/learn on`, then select Full access. Ask the agent to write the exercise file: Learn still prevents execution and asks you to write it.
7. Open the picker at 80×24, scroll, and switch a light/dark theme. The descriptions wrap, the chat scrim remains visible, and Select/Cancel remain inside the popup.
8. Check `/help` and slash suggestions: `/approval` and `/sandbox` are absent. Typing either directly directs you to `/permissions` without changing settings. Context is absent from the composer control row.


## Settings and status

`/permissions status` renders a native themed card, using the same system-card border as Learning. Current access is emphasized; Full access uses the warning theme color. Scope is displayed as All workspaces. Settings exposes the same picker below Token activity, and its value refreshes immediately after a change. User-facing mode names always use Full access; `/permissions full access` is the suggested command, with the previous `full` spelling accepted as an input alias.

The global saved permissions mode overrides project configuration. With no global choice, Automatic is the global default; workspace-local permissions cannot replace it. Explicit legacy global restrictions remain Custom until a preset is selected.
