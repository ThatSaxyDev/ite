# PRD: One-Click OpenRouter Sign-In (PKCE OAuth)

## Summary

Replace the "paste your OpenRouter API key" step in iTE's setup flow with a one-click PKCE OAuth sign-in. The user clicks a button, iTE opens OpenRouter's auth page in their browser, OpenRouter redirects to a localhost callback, and iTE exchanges the authorization code for a user-controlled API key. The resulting key is treated identically to a manually pasted key throughout the rest of the runtime.

Net result: zero copy-paste for the largest single user segment (OpenRouter BYOK), no API key ever transits iTE's infrastructure, and the rest of the model pipeline is untouched.

This PRD covers both the TUI setup modal and the first-run CLI wizard.

## Problem

iTE's setup modal asks every user to manually paste an OpenRouter API key:

```text
API key
[ paste sk-or-v1-...           ] [ 👁 ]
```

A large share of new iTE users run OpenRouter because the free tier removes the local-Ollama bootstrap step. Asking them to:

1. Open OpenRouter in a browser.
2. Sign up or sign in.
3. Generate an API key.
4. Copy it.
5. Paste it into a TUI.

…before they see a single iTE response, is a known friction point. Every additional step is a drop-off.

OpenRouter ships a first-class PKCE OAuth endpoint (`/auth` + `/api/v1/auth/keys`) precisely to eliminate this friction. iTE should use it.

## Product Goal

A new user who chooses OpenRouter during setup should reach a working iTE chat with **one click** after picking the provider:

```text
Provider: OpenRouter
[ ✨  Sign in with OpenRouter ]
[ Or paste an OpenRouter API key above.  ]

(user clicks the button)
(iTE opens browser → user approves → modal fills in a verified key)
```

The manual paste path stays. Power users and CI/automation still need it.

## Non-Goals

- Do not remove the manual paste-key path.
- Do not change the iTE Cloud / bundled-OpenRouter flow (`ite/docs/design/openrouter-bundled-usage-phase1.md`). This PRD is **client-side BYOK only**.
- Do not implement token refresh. OpenRouter issues a long-lived user-controlled key, not an OAuth access token; there is nothing to refresh.
- Do not introduce a new dependency. `secrets`, `hashlib`, `httpx`, and `asyncio` already cover PKCE.
- Do not add a remote callback URL. Localhost-only (with a headless fallback that asks the user to paste a code). Public callback URLs and marketplace presence are deferred.
- Do not move OpenRouter keys into the OS keyring in this phase. Move them into the existing `secrets.toml` file. Keyring support is a follow-up.

## User Promise

```text
Pick "OpenRouter" → click "Sign in with OpenRouter" → chat.
```

Or, for the manual path that already exists:

```text
Pick "OpenRouter" → paste a key → click "Load" → chat.
```

## Guiding Principles

- **One path, one click.** The OAuth button is the recommended option and is shown first.
- **Both modes work.** Localhost callback when possible; headless code-paste when not. Never fail just because the user is on SSH.
- **Same downstream surface.** OAuth populates the same `#setup-api-key` field the paste path uses. No new persistence paths in the modal.
- **No new infra.** Pure client-side. No iTE Cloud endpoint involvement.
- **Fail loud, recover cleanly.** Surface OpenRouter error codes verbatim and let the user retry.
- **Default to discoverability.** Default `key_label` makes it obvious in the user's OpenRouter dashboard which device owns which key.

## OpenRouter OAuth Contract (from `ite/docs/openrouter-oauth.md`)

Three modes are supported. We use the first two:

| Mode                                             | When to use                                           | Mechanism                                                                     |
| ------------------------------------------------ | ----------------------------------------------------- | ----------------------------------------------------------------------------- |
| **Localhost callback** (any port)                | TUI, normal desktop, dev box                          | iTE binds `http://127.0.0.1:<port>/callback` and waits for the redirect       |
| **Headless (no callback, `key_label` required)** | SSH, container, CI without a reachable browser target | iTE opens the auth URL; OpenRouter displays the code; user pastes it into iTE |
| Public callback URL                              | Marketplace / attribution                             | **Deferred** — requires a registered public URL                               |

### Flow shape

1. Generate `code_verifier` (URL-safe random, ≥ 256 bits of entropy via `secrets.token_urlsafe(43)`).
2. Compute `code_challenge = base64url(sha256(verifier))`.
3. Open `https://openrouter.ai/auth?callback_url=<...>&code_challenge=<...>&code_challenge_method=S256&key_label=<...>`.
4. Capture `code` from the redirect (localhost) or user paste (headless).
5. `POST https://openrouter.ai/api/v1/auth/keys` with `{code, code_verifier, code_challenge_method: "S256"}` → response: `{key}`.

### Error codes (surfaced verbatim)

- `400 Invalid code_challenge_method`
- `403 Invalid code or code_verifier`
- `403 Authorization code expired` (codes expire after 10 min)
- `405 Method Not Allowed`

## Design Decisions (Locked)

| Decision                        | Choice                                                                          | Rationale                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `key_label` value               | `f"iTE CLI ({socket.gethostname()})"`                                           | Identifies the device in the OpenRouter dashboard; trivial for users to revoke per-machine |
| `key_label` mutability          | Editable in the modal before launch                                             | Edge case for users with non-default hostnames                                             |
| Storage location                | `~/.ite/secrets.toml` under new `[openrouter]` table                            | Matches the existing `_load_mcp_secrets` pattern; keeps `config.toml` free of credentials  |
| `config.toml`                   | Holds only `base_url` and `model.name` for OpenRouter                           | Credentials never in the config file                                                       |
| Storage of headless-flow extras | `created_at = ISO-8601` written alongside `api_key`                             | Lets the UI show "Connected 2 days ago" later                                              |
| Timeout                         | 5 minutes per phase (matches `oauth_timeout_sec=300` default)                   | Same as MCP OAuth                                                                          |
| Flow auto-detection             | Probe `127.0.0.1:0` bind at sign-in start                                       | Determines localhost vs. headless mode without user input                                  |
| Manual paste path               | Preserved verbatim                                                              | Power users, CI, future-key re-entry                                                       |
| Persistence write path          | New `save_openrouter_oauth_secret(key, key_label)` helper in `config/loader.py` | Mirrors `save_saved_custom_provider` shape                                                 |

## UI Changes (TUI)

### Current modal layout (provider = OpenRouter)

```
┌─ Setup iTE ──────────────────────────────────────────┐
│  Choose how iTE should reach your model.             │
│  Provider                                             │
│  [ OpenRouter                              ▾ ]       │
│  Use your own OpenRouter key with iTE.               │
│  API key                                              │
│  [ •••••••••••••••••••• ] [ 👁 ]                      │
│  Model                                                │
│  [ Select a model             ▾ ] [ Load ]            │
│  [ model_input                                       ] │
│  (status / error messages)                           │
│  [ Cancel ]                       [ Continue ]        │
└───────────────────────────────────────────────────────┘
```

### New modal layout (provider = OpenRouter)

```
┌─ Setup iTE ──────────────────────────────────────────┐
│  Choose how iTE should reach your model.             │
│  Provider                                             │
│  [ OpenRouter                              ▾ ]       │
│  Use your own OpenRouter key with iTE.               │
│  API key                                              │
│  [ •••••••••••••••••••• ] [ 👁 ]                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ ✨  Sign in with OpenRouter                    │  │  ← NEW
│  └────────────────────────────────────────────────┘  │
│  Or paste an OpenRouter API key above.               │  ← NEW
│  Model                                                │
│  [ Select a model             ▾ ] [ Load ]            │
│  [ model_input                                       ] │
│  (status / error messages)                           │
│  [ Cancel ]                       [ Continue ]        │
└───────────────────────────────────────────────────────┘
```

### Headless mode (no localhost bind available)

After clicking the button, if the bind probe fails, the button label updates to `"Sign in with OpenRouter"` and a new Input reveals (the help line above the Input changes to `"Paste the code shown in your browser after approving the connection."`):

```
  ┌──────────────────────────────────────────────────────────┐
  │ ✨  Sign in with OpenRouter                              │
  └──────────────────────────────────────────────────────────┘
  Or paste an OpenRouter API key above.
  Paste the code shown in your browser after approving the connection.
  ┌──────────────────────────────────────────────────────────┐
  │ Paste the authorization code…                            │  ← NEW Input
  └──────────────────────────────────────────────────────────┘
```

The Input is only visible in headless mode and is hidden when the user is back on a normal localhost flow.

### Status / error surface

Use the existing `#setup-status` and `#setup-error` `Static` widgets. No new widgets for messaging. Status messages during the OAuth flow:

1. `"Opening browser for OpenRouter sign-in…"`
2. `"Waiting for browser callback on http://127.0.0.1:<port>/callback…"`
3. `"Exchanging authorization code…"`
4. (success path) `"OpenRouter key verified. Loaded N models."`

### Visibility toggles (in `_apply_provider_visibility`)

| Widget                                   | Visible when                                                                        |
| ---------------------------------------- | ----------------------------------------------------------------------------------- |
| `#setup-openrouter-signin` (Button)      | `provider == SETUP_PROVIDER_OPENROUTER`                                             |
| `#setup-openrouter-signin-help` (Static) | `provider == SETUP_PROVIDER_OPENROUTER`                                             |
| `#openrouter-auth-code` (Input)          | `provider == SETUP_PROVIDER_OPENROUTER` AND bind probe failed AND not yet exchanged |
| `#openrouter-auth-code-label` (Static)   | Same as above                                                                       |

### Busy-state additions (in `_set_validating`)

The OAuth button and the headless code Input both flip to `disabled=True` while the PKCE exchange is in flight, alongside the existing widget disable list.

### Worker orchestration

A new `run_worker(_openrouter_pkce_signin(), exclusive=True)` is launched by an `@on(Button.Pressed, "#setup-openrouter-signin")` handler. The worker:

1. Probes `127.0.0.1:0` bind.
2. Routes to `_run_localhost_pkce_flow()` or `_run_headless_pkce_flow()`.
3. On success, sets `self.query_one("#setup-api-key", Input).value = key`.
4. Then calls the existing `self._load_openrouter_models_for_setup()` to verify and populate the model selector.

Cancellation: when the modal is dismissed, `on_unmount` cancels the worker. The PKCE helper's localhost server uses a `try/finally` to ensure socket cleanup regardless of cancellation.

## UI Changes (CLI First-Run Wizard)

`ite/src/ite/config/setup.py:run_setup_wizard` currently asks:

```text
❯ Base URL (http://localhost:11434/v1): https://openrouter.ai/api/v1
❯ API key (ollama): sk-or-v1-...
```

New shape (using `rich.prompt.Prompt.ask` with choices, or a numbered menu before the existing inputs):

```text
How would you like to connect?

❯ Sign in with OpenRouter
  Paste an OpenRouter API key
  Use Ollama
  Use another OpenAI-compatible provider
```

If **Sign in with OpenRouter** is chosen:

```text
Opening https://openrouter.ai/auth?... in your browser.
Approve the connection, then return here.
```

The CLI helper wraps the same `run_pkce_login()` entry point, using `console.status(...)` to show progress, and falls back to printing the URL + asking for a code if the headless probe succeeds without a callback. On success, it writes the key to the system secrets file via `save_openrouter_oauth_secret()` and continues with the model selection prompt.

If **Paste an OpenRouter API key** is chosen, behavior is unchanged from today.

## Data Model

### New secret-table schema (`~/.ite/secrets.toml`)

```toml
# OpenRouter OAuth-derived credentials (iTE-only; user-revocable from openrouter.ai/keys)
[openrouter]
api_key = "sk-or-v1-..."
key_label = "iTE CLI (my-macbook.local)"
created_at = "2026-09-07T14:32:11Z"
```

### New config-table schema (`~/.ite/config.toml`)

No change for existing fields. The `[model]` block continues to hold `name`, `context_window`, etc. The `api_key` field is **never** set to the OAuth-derived value; it remains unset or empty for OpenRouter users. The config loader merges the secrets table in via a new step (described below).

### Loader changes

A new merge step in `ite/src/ite/config/loader.py`:

```python
def _merge_openrouter_oauth_secret(config_dict: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
    if "openrouter" in config_dict and "openrouter" in secrets:
        # Base URL points at OpenRouter → inject the OAuth key
        if "openrouter.ai" in str(config_dict.get("openrouter", {}).get("base_url") or "").lower():
            api_key = str(secrets["openrouter"].get("api_key") or "").strip()
            if api_key:
                config_dict.setdefault("model", {})
                config_dict["api_key"] = api_key
    return config_dict
```

This mirrors the existing `_merge_mcp_secrets_into_config` and `_merge_mcp_client_credentials_secrets_into_config` patterns.

A new public helper:

```python
def save_openrouter_oauth_secret(
    *,
    api_key: str,
    key_label: str,
) -> Path:
    """Write the OAuth-derived OpenRouter key into secrets.toml with chmod 0o600."""
```

A new loader:

```python
def load_openrouter_oauth_secret() -> dict[str, Any] | None:
    """Return the [openrouter] table from system secrets.toml, or None."""
```

## New Module: `ite/src/ite/auth/openrouter_pkce.py`

```python
# Public surface
def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge). S256 with secrets.token_urlsafe(43)."""

def build_auth_url(*, callback_url: str | None, code_challenge: str, key_label: str) -> str:
    """Build https://openrouter.ai/auth?... with the right params."""

def exchange_code(*, code: str, code_verifier: str) -> str:
    """POST /api/v1/auth/keys; return the user-controlled API key. Raises OpenRouterAuthError on failure."""

def run_pkce_login(
    *,
    key_label: str,
    timeout_sec: float = 300.0,
    allow_headless: bool = True,
) -> str:
    """Top-level entry. Probes 127.0.0.1:0, picks the right flow, returns the API key.

    Raises:
        OpenRouterAuthError on exchange failure
        OpenRouterTimeoutError on callback/paste timeout
        OpenRouterCancelledError if the user cancels
    """
```

### Implementation notes

- **PKCE:** `secrets.token_urlsafe(43)` → `code_verifier`; `code_challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()`.
- **Localhost server:** `asyncio.start_server` on an ephemeral port, parse one HTTP request, return a tiny HTML page ("You can close this tab and return to iTE."), extract `?code=...` from the request line, close the listener.
- **Headless:** open the URL via `webbrowser.open`, prompt via `console.input("Paste the authorization code: ")`.
- **Exchange:** `httpx.AsyncClient` with a 10s timeout, surface error codes verbatim.
- **Cancellation:** the worker must be able to cancel the await on the callback future. Use `asyncio.Future` + `future.set_result(...)` from the HTTP handler, and `await asyncio.wait_for(future, timeout=...)`.
- **Threading:** when called from the Textual worker, the helper itself runs in `asyncio.to_thread` because the callback future is bound to the worker's event loop, but the listener must be `loop.run_until_complete` to integrate with the existing asyncio loop. Use a small adapter.

## File-by-File Change List

### New files

| File                                  | Purpose                    |
| ------------------------------------- | -------------------------- |
| `ite/src/ite/auth/__init__.py`        | Package marker             |
| `ite/src/ite/auth/openrouter_pkce.py` | PKCE helper module (above) |
| `ite/tests/test_openrouter_pkce.py`   | Unit tests for the helper  |

### Modified files

| File                                                    | Change                                                                                                                                                                                                             |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ite/src/ite/ui/reup/modals.py`                         | +1 Button, +1 Static, +1 Input (headless only), `_apply_provider_visibility` update, `_set_validating` update, new `@on(Button.Pressed, "#setup-openrouter-signin")` handler, new worker `_openrouter_pkce_signin` |
| `ite/src/ite/config/loader.py`                          | New `save_openrouter_oauth_secret`, new `load_openrouter_oauth_secret`, new `_merge_openrouter_oauth_secret`, wired into `load_config` after MCP secret merges                                                     |
| `ite/src/ite/config/setup.py`                           | First-run wizard menu: add "Sign in with OpenRouter" choice, wrap `run_pkce_login` from console                                                                                                                    |
| `ite/tests/test_setup_modal.py`                         | Test the new button + headless code-paste path with a mocked browser-open and a mocked localhost callback                                                                                                          |
| `ite/tests/test_saved_custom_provider.py` (or new test) | Test `save_openrouter_oauth_secret` chmod 0o600, idempotent re-saves, and the loader merge step                                                                                                                    |
| `ite/docs/configuration.md`                             | Document the new `[openrouter]` secrets table and the OAuth flow                                                                                                                                                   |
| `ite/docs/openrouter.md` (new)                          | User-facing doc: "How to sign in with OpenRouter"                                                                                                                                                                  |

## Testing Strategy

### Unit tests (`ite/tests/test_openrouter_pkce.py`)

- `generate_pkce_pair` returns a verifier of length 43 (or more) and a challenge that round-trips via `base64.urlsafe_b64decode(challenge + "==")` to the SHA-256 of the verifier.
- `build_auth_url` includes `code_challenge_method=S256`, the verifier-derived challenge, and the right `callback_url` / `key_label` based on the mode.
- `exchange_code` posts `{code, code_verifier, code_challenge_method: "S256"}` to `https://openrouter.ai/api/v1/auth/keys`, returns the `key` field, and surfaces non-2xx responses as `OpenRouterAuthError` with the verbatim error body.
- `run_pkce_login` with a mocked `webbrowser.open` + a `loopback callback server` for the localhost path.
- `run_pkce_login` with a mocked `console.input` for the headless path.

### Integration / modal tests (`ite/tests/test_setup_modal.py`)

- `SetupModal` with `provider=OpenRouter` shows the new button when the user is on a normal desktop (bind probe succeeds).
- Clicking the button populates `#setup-api-key` with the returned key and triggers the model loader.
- Headless path: button click reveals the code Input; pasting a code and submitting populates the key.
- `_set_validating` disables the new button while a roundtrip is in flight.
- `on_unmount` cancels the in-flight worker without leaking the localhost server.

### Loader tests

- `save_openrouter_oauth_secret` writes the file with `chmod 0o600` and preserves any other keys in `secrets.toml`.
- `load_openrouter_oauth_secret` returns the `[openrouter]` table.
- `load_config` correctly injects the OAuth key when `base_url` is `openrouter.ai` and the key exists.
- `load_config` does **not** inject the key when `base_url` points at a non-OpenRouter provider.

### Manual / e2e checklist (recorded in PR description)

- [ ] Normal desktop: button click → browser opens → iTE fills in the key → model list loads → Continue saves.
- [ ] SSH session (no localhost reachable): button click → message says "paste the code from your browser" → Input appears → paste → key fills in.
- [ ] Browser does not auto-open: URL printed to terminal, fallback instructions work.
- [ ] OpenRouter rejects the code (`403 Invalid code or code_verifier`): error surfaced verbatim, button still clickable to retry.
- [ ] Continue after OAuth: `~/.ite/secrets.toml` contains the new `[openrouter]` table; `~/.ite/config.toml` does **not** contain the key.
- [ ] Second sign-in: existing `[openrouter]` table is overwritten cleanly (no leftover stale data).

## Phased Rollout

### Phase 1 — TUI modal (smallest, ships fastest)

- New `ite/src/ite/auth/openrouter_pkce.py`
- New button + status flow in `SetupModal`
- Loader merge for `[openrouter]` secret
- Unit tests for the helper and the modal

**Acceptance:** clicking the button in `/setup` reaches a working chat without any copy-paste, on a normal desktop.

### Phase 2 — CLI first-run wizard

- New menu choice in `ite/src/ite/config/setup.py:run_setup_wizard`
- `console.status` progress display
- Reuse the same `run_pkce_login()` entry point

**Acceptance:** `ite` (no config) on a fresh machine offers the one-click path and completes setup without copy-paste.

### Phase 3 — Polish

- "View usage" deep-link button in the setup modal (uses the SHA-256 hex of the key per the OpenRouter doc).
- `/usage openrouter` slash command that prints the deep-link.
- User-facing `ite/docs/openrouter.md`.

### Phase 4 — Follow-ups (out of scope for this PRD)

- Move OAuth-derived keys to the OS keyring via the existing MCP secret backend.
- "Reconnect OpenRouter" action in the modal that re-runs the flow without losing the user's saved `base_url` and `model.name`.
- Multi-account support: store a list of `[openrouter.<account>]` tables.
- Per-machine `key_label` remembered in a workspace-level `.ite/secrets.toml`.

## Risks and Mitigations

| Risk                                                                                                    | Mitigation                                                                                                                           |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Browser doesn't auto-open (headless server, macOS sandbox)                                              | `webbrowser.open` returns `False` → print the URL explicitly; same pattern as `ite/src/ite/cloud/auth.py:1086`                       |
| User is on SSH / inside a container where `127.0.0.1:<port>` isn't reachable back to the user's machine | Ephemeral `bind(127.0.0.1, 0)` probe at the start of the worker; on failure, switch to headless mode automatically                   |
| OpenRouter revokes or rotates the key                                                                   | Out of scope; same risk profile as today. Phase 3 deep-link makes it visible                                                         |
| User has an existing manual key                                                                         | OAuth just overwrites the Input value; `save_system_config` is not called until Continue, so the existing key is preserved on Cancel |
| 10-min code expiry                                                                                      | Hard 5-min client timeout; "Try again" button regenerates `code_verifier`                                                            |
| `httpx` already verified for the existing `/key` and `/models` calls                                    | Reuse the same client shape and timeout constants                                                                                    |
| Secrets file gets corrupted by an external editor                                                       | Existing `ConfigError` handling in `_parse_toml` covers it; the merge step falls back to "no OAuth key" if the table is malformed    |
| Concurrent sign-in attempts (user double-clicks)                                                        | `_set_validating` disables the button while the worker runs                                                                          |
| Future PKCE helper versions need refresh support                                                        | Out of scope; OpenRouter does not return refresh tokens. Documented in Non-Goals                                                     |

## Open Questions

None at PRD level. The two key decisions (`key_label` format, storage location) are locked.

## Anti-Patterns to Avoid

- Don't add a remote callback URL. It would require registering a public URL and bring marketplace complexity.
- Don't introduce a new dependency. PKCE fits in stdlib.
- Don't store the `code_verifier` after the exchange. It's a single-use secret.
- Don't silently fall back to "paste your key" on OAuth failure without telling the user why.
- Don't log the API key anywhere, including in tracebacks. Wrap exchange errors with messages that reference the error code, not the key.
- Don't move the manual paste path. Some users (CI, automation, accounts with a pre-issued key) still need it.
