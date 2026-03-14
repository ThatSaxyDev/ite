# Shell and Web Capabilities

This document is the canonical reference for iTE's execution and research primitives:

- `shell` for local command execution
- `web_search` for external discovery
- `web_fetch` for direct source retrieval

It exists so future work can build on explicit behavior instead of relying on prompt memory or UI conventions.

## Shell

### Supported behavior
- Executes commands through the platform shell (`/bin/bash -c` on Unix, `cmd.exe /c` on Windows).
- Accepts:
  - `command`
  - `timeout`
  - optional `cwd`
- Captures both stdout and stderr.
- Returns exit code for failed commands.
- Terminates long-running commands on timeout.
- Truncates very large output before returning it to the model/UI.
- Filters environment variables using configured exclusion patterns.

### Safety model
- Shell commands are classified into three buckets:
  - `safe`: read-only inspection commands
  - `caution`: unclear or potentially mutating commands
  - `dangerous`: explicitly blocked patterns
- Safe commands can run in planning contexts and may be auto-approved depending on approval mode.
- Caution commands require approval in stricter modes.
- Dangerous commands are rejected before execution.

### Sandbox behavior
- `cwd` must remain inside the filesystem sandbox.
- The command string is scanned for likely filesystem paths, including:
  - absolute paths
  - home-relative paths
  - relative traversals
  - quoted paths
  - redirect targets
- Referenced paths outside the sandbox are blocked before execution.

### Current limitations
- Shell path extraction is heuristic, not a full shell parser.
- Safety classification is regex-based, not semantic command understanding.
- Compound shell syntax is handled conservatively, but not exhaustively.

## Web Search

### Supported behavior
- Uses DuckDuckGo search through the `ddgs`/`duckduckgo_search` client.
- Accepts:
  - `query`
  - `max_results`
- Returns:
  - search query
  - result count
  - ranked result titles
  - URLs
  - snippets when available
- Annotates metadata with provider and top result URLs.

### Intended use
- Use for fresh or external information.
- Prefer before `web_fetch` when the agent needs to discover sources.
- Prefer local repo tools over web search for project/workspace truth.

### Current limitations
- No source ranking beyond provider ordering.
- No freshness guarantees beyond provider behavior.
- No citation policy enforcement at the tool layer.

## Web Fetch

### Supported behavior
- Fetches a specific `http://` or `https://` URL.
- Follows redirects.
- Handles:
  - HTML
  - JSON
  - plain text
- For HTML:
  - strips common noise tags
  - prefers `main`/`article`/`role=main` content when available
  - converts the result to readable markdown
- Returns metadata including:
  - source URL
  - status code
  - content type
  - content length
  - truncation flag

### Intended use
- Use when the URL is already known or selected from search results.
- Use to inspect the body of a source, not to discover sources.

### Current limitations
- Single-page retrieval only.
- No browsing session, source graph, or crawler behavior.
- No source-quality evaluation.

## UI Expectations

All three user surfaces should express the same conceptual model:

- `ite`: shell is local execution, web is external research.
- `ite --gui`: shell and web results should remain visible enough to explain what happened.
- `ite --reup`: shell and web should have compact but legible provenance, not disappear as invisible internal noise.

The UI may compress or summarize these tools, but should not hide approval-relevant shell behavior or source-relevant web behavior.
