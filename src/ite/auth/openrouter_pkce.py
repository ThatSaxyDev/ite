"""PKCE OAuth helper for OpenRouter.

Implements the one-click sign-in flow documented at
``ite/docs/openrouter-oauth.md``. Two modes are supported:

- **Localhost callback** — iTE binds ``http://127.0.0.1:<port>/callback``,
  opens the auth URL in the user's browser, and waits for the redirect.
- **Headless** — iTE opens the auth URL, the user pastes the code shown on
  the OpenRouter result page, and iTE exchanges it for an API key.

Either way, the result is a user-controlled OpenRouter API key (a regular
``sk-or-v1-...`` string) that iTE stores alongside the rest of its
configuration.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import socket
import webbrowser
from dataclasses import dataclass

import httpx

OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"
OPENROUTER_HOST = "openrouter.ai"
DEFAULT_CALLBACK_HOST = "127.0.0.1"
DEFAULT_TIMEOUT_SEC = 300.0
PROBE_TIMEOUT_SEC = 0.5
CALLBACK_PATH = "/callback"

# Code length emitted by the headless flow. OpenRouter codes are short; we
# trim whitespace defensively.
_CODE_MIN_LEN = 8
_CODE_MAX_LEN = 512

SUCCESS_PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<title>iTE — OpenRouter sign-in complete</title>"
    "<style>body{font-family:system-ui,-apple-system,sans-serif;"
    "background:#0e1116;color:#e6edf3;display:grid;place-items:center;"
    "height:100vh;margin:0}main{max-width:30rem;padding:2rem;text-align:center}"
    "h1{font-size:1.25rem;margin:0 0 0.5rem}p{color:#8b949e;margin:0}</style></head>"
    "<body><main><h1>You can close this tab and return to iTE.</h1>"
    "<p>iTE has verified your OpenRouter sign-in.</p></main></body></html>"
).encode("utf-8")


class OpenRouterAuthError(RuntimeError):
    """Raised when OpenRouter rejects the authorization code."""


class OpenRouterTimeoutError(OpenRouterAuthError):
    """Raised when the callback server or headless prompt times out."""


class OpenRouterCancelledError(OpenRouterAuthError):
    """Raised when the user cancels the flow."""


@dataclass(frozen=True)
class PKCEPair:
    """A generated PKCE verifier and its S256 challenge."""

    code_verifier: str
    code_challenge: str


def generate_pkce_pair() -> PKCEPair:
    """Return a fresh PKCE verifier + S256 challenge.

    The verifier is a 256-bit URL-safe random string (43 chars from
    ``secrets.token_urlsafe(43)``). The challenge is the base64url-encoded
    SHA-256 digest of the verifier, with padding stripped per RFC 7636.
    """
    verifier = secrets.token_urlsafe(43)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PKCEPair(code_verifier=verifier, code_challenge=challenge)


def build_auth_url(
    *,
    code_challenge: str,
    key_label: str,
    callback_url: str | None = None,
) -> str:
    """Build the OpenRouter ``/auth`` URL with PKCE params.

    ``callback_url`` is the localhost URL iTE is listening on. When ``None``
    the URL is built in headless mode (no ``callback_url`` parameter) and
    the user pastes the code shown on the OpenRouter result page.
    """
    parts: list[str] = []
    if callback_url:
        parts.append(f"callback_url={_percent_encode(callback_url)}")
    parts.append(f"code_challenge={_percent_encode(code_challenge)}")
    parts.append("code_challenge_method=S256")
    label = str(key_label or "").strip()
    if label:
        parts.append(f"key_label={_percent_encode(label)}")
    return f"{OPENROUTER_AUTH_URL}?{'&'.join(parts)}"


def exchange_code(*, code: str, code_verifier: str) -> str:
    """Exchange an authorization code for an OpenRouter API key.

    Synchronous. Raises :class:`OpenRouterAuthError` on any non-2xx response
    or transport failure. The error message includes the verbatim error body
    from OpenRouter so the caller can surface it to the user.
    """
    payload = {
        "code": code,
        "code_verifier": code_verifier,
        "code_challenge_method": "S256",
    }
    try:
        response = httpx.post(OPENROUTER_KEYS_URL, json=payload, timeout=10.0)
    except httpx.HTTPError as exc:
        raise OpenRouterAuthError(
            f"Could not reach OpenRouter to exchange the code: {exc}"
        ) from exc

    if response.status_code >= 400:
        body = response.text.strip() or f"HTTP {response.status_code}"
        raise OpenRouterAuthError(f"OpenRouter rejected the code: {body}")

    try:
        data = response.json()
    except ValueError as exc:
        raise OpenRouterAuthError(
            "OpenRouter returned a non-JSON response while exchanging the code."
        ) from exc

    key = ""
    if isinstance(data, dict):
        candidate = data.get("key")
        if isinstance(candidate, str):
            key = candidate.strip()
    if not key:
        raise OpenRouterAuthError(
            "OpenRouter response did not include an API key."
        )
    return key


def openrouter_host_reachable(*, timeout_sec: float = PROBE_TIMEOUT_SEC) -> bool:
    """Best-effort check that the local network can reach OpenRouter.

    Used as a soft signal only — failures here never block the flow, they
    just influence the message we show the user. The localhost bind probe
    (see :func:`can_bind_localhost_callback`) is the authoritative signal
    for flow selection.
    """
    try:
        with socket.create_connection(
            (OPENROUTER_HOST, 443), timeout=timeout_sec
        ):
            return True
    except OSError:
        return False


def can_bind_localhost_callback(
    *, host: str = DEFAULT_CALLBACK_HOST, timeout_sec: float = PROBE_TIMEOUT_SEC
) -> bool:
    """Return ``True`` if iTE can bind a TCP port on ``host``.

    The probe is a no-op: it opens an ephemeral port, then closes it. We
    treat a successful bind as evidence that the localhost callback flow is
    viable. Failures mean we should fall back to the headless flow.
    """
    del timeout_sec  # kept for API stability; not used by the probe
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, 0))
    except OSError:
        return False
    finally:
        probe.close()
    return True


async def wait_for_localhost_callback_code(
    *,
    host: str = DEFAULT_CALLBACK_HOST,
    port: int | None = None,
    timeout_sec: float = 60.0
) -> str:
    """Run a single-shot HTTP server and return the captured auth code.

    Starts an ``asyncio.start_server`` on the given host and port, waits
    up to ``timeout_sec`` for the OpenRouter redirect, writes a small
    success page, and shuts the server down cleanly. Returns the
    authorization code captured from the ``?code=`` query string.

    ``port`` MUST be the same port baked into the ``callback_url`` used to
    build the OpenRouter auth URL. If it is ``None`` (backwards compatible
    for a standalone call) an ephemeral port is allocated, but callers who
    already resolved a port must pass it so the listener and the redirect
    target match — otherwise the callback is silently lost and the flow
    hangs.
    """
    if port is None:
        _, port = _alloc_localhost_callback(host=host)

    loop = asyncio.get_running_loop()
    code_future: asyncio.Future[str] = loop.create_future()

    async def _handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=5.0
            )
        except (asyncio.TimeoutError, ConnectionResetError):
            writer.close()
            return
        # Drain the rest of the request — headers + body — so the client
        # can finish writing. We don't care about the content.
        try:
            while True:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=5.0
                )
                if not line or line in (b"\r\n", b"\n"):
                    break
        except (asyncio.TimeoutError, ConnectionResetError):
            pass

        first = request_line.decode("latin-1", errors="replace").strip()
        path = first.split(" ", 2)[1] if first.startswith(("GET", "POST")) else ""
        code_value = ""
        if path.startswith(CALLBACK_PATH) and "code=" in path:
            query = path.split("?", 1)[1] if "?" in path else ""
            for pair in query.split("&"):
                if pair.startswith("code="):
                    code_value = _percent_decode(pair[len("code="):])
                    break
            body = SUCCESS_PAGE
            status = "200 OK"
        else:
            body = b"Not Found"
            status = "404 Not Found"
        try:
            writer.write(
                (
                    f"HTTP/1.1 {status}\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                ).encode("latin-1")
                + body
            )
            await writer.drain()
        finally:
            writer.close()

        if code_value and not code_future.done():
            code_future.set_result(code_value)

    server = await asyncio.start_server(_handle, host=host, port=port)
    try:
        try:
            return await asyncio.wait_for(code_future, timeout=timeout_sec)
        except asyncio.TimeoutError as exc:
            raise OpenRouterTimeoutError(
                "Timed out waiting for OpenRouter to redirect back to iTE."
            ) from exc
    finally:
        server.close()
        await server.wait_closed()


def open_browser(url: str) -> bool:
    """Open ``url`` in the user's default browser. Returns whether it worked."""
    try:
        return bool(webbrowser.open(url))
    except webbrowser.Error:
        return False


def prompt_for_code(console_input) -> str:
    """Prompt the user to paste the authorization code from the headless flow.

    ``console_input`` is a callable matching ``rich.console.Console.input``'s
    signature. It is injected so tests can drive the prompt deterministically.
    """
    raw = console_input("Paste the authorization code from your browser: ")
    return str(raw or "").strip()


def run_localhost_pkce_flow(
    *,
    key_label: str,
    timeout_sec: float = 60.0,
    host: str = DEFAULT_CALLBACK_HOST,
    open_browser_fn=open_browser,
) -> str:
    """Sync entry point: runs the localhost PKCE flow on a fresh loop.

    Suitable for the CLI path where there is no event loop. The Textual
    modal calls :func:`run_localhost_pkce_flow_async` directly so the
    callback server can share the modal's loop.
    """
    return asyncio.run(
        _run_localhost_pkce_flow_async(
            key_label=key_label,
            timeout_sec=timeout_sec,
            host=host,
            open_browser_fn=open_browser_fn,
        )
    )


async def run_localhost_pkce_flow_async(
    *,
    key_label: str,
    timeout_sec: float = 60.0,
    host: str = DEFAULT_CALLBACK_HOST,
    open_browser_fn=open_browser,
) -> str:
    """Async entry point: run the localhost PKCE flow on the caller's loop.

    Used by the Textual modal so the callback server shares the modal's
    event loop. Allocates a port, starts the callback server, opens the
    browser, waits for the redirect, then exchanges the code. Raises
    :class:`OpenRouterAuthError` on any failure path.
    """
    return await _run_localhost_pkce_flow_async(
        key_label=key_label,
        timeout_sec=timeout_sec,
        host=host,
        open_browser_fn=open_browser_fn,
    )


async def _run_localhost_pkce_flow_async(
    *,
    key_label: str,
    timeout_sec: float,
    host: str,
    open_browser_fn,
) -> str:
    pkce = generate_pkce_pair()
    callback_url, port = _alloc_localhost_callback(host=host)
    auth_url = build_auth_url(
        code_challenge=pkce.code_challenge,
        key_label=key_label,
        callback_url=callback_url,
    )

    server_task = asyncio.create_task(
        wait_for_localhost_callback_code(
            host=host, port=port, timeout_sec=timeout_sec
        )
    )
    # Give the server a beat to start listening before opening the
    # browser, otherwise the browser can race the listener and see
    # "connection refused" on the redirect.
    for _ in range(40):
        if server_task.done() and server_task.exception() is not None:
            raise server_task.exception()  # type: ignore[misc]
        if _is_port_listening(host, port):
            break
        await asyncio.sleep(0.025)
    open_browser_fn(auth_url)

    code = await server_task
    return exchange_code(code=code, code_verifier=pkce.code_verifier)


def _alloc_localhost_callback(*, host: str) -> tuple[str, int]:
    """Reserve an ephemeral TCP port and return ``(callback_url, port)``.

    The returned port MUST be baked into both the callback URL (so
    OpenRouter redirects to it) and the localhost listener (so the
    redirect is actually served). Passing a different port to
    ``wait_for_localhost_callback_code`` than the one in the auth URL is a
    footgun that silently drops the callback and hangs the flow.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        port = int(listener.getsockname()[1])
    return f"http://{host}:{port}{CALLBACK_PATH}", port


def _is_port_listening(host: str, port: int) -> bool:
    """Return ``True`` if a TCP listener is already bound on ``host:port``."""
    try:
        with socket.create_connection((host, port), timeout=0.05):
            return True
    except OSError:
        return False



def run_headless_pkce_flow(
    *,
    key_label: str,
    console_input,
    open_browser_fn=open_browser,
) -> str:
    """Run the headless PKCE flow. Returns the API key.

    The caller passes a ``console_input`` callable for the code prompt so
    this function stays UI-tool-agnostic.
    """
    pkce = generate_pkce_pair()
    auth_url = build_auth_url(
        code_challenge=pkce.code_challenge,
        key_label=key_label,
        callback_url=None,
    )
    open_browser_fn(auth_url)
    raw_code = prompt_for_code(console_input)
    code = raw_code.strip()
    if not code:
        raise OpenRouterAuthError("No authorization code was provided.")
    if len(code) < _CODE_MIN_LEN or len(code) > _CODE_MAX_LEN:
        raise OpenRouterAuthError(
            "The authorization code looks malformed. Try the sign-in again."
        )
    return exchange_code(code=code, code_verifier=pkce.code_verifier)


def run_pkce_login(
    *,
    key_label: str,
    console_input,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    force_headless: bool = False,
    open_browser_fn=open_browser,
) -> str:
    """Top-level entry point. Returns the OpenRouter API key.

    Auto-detects which flow to run based on whether a localhost port can
    be bound. Pass ``force_headless=True`` to skip the probe and always
    use the paste-the-code flow (e.g. when the modal already detected
    SSH/headless).
    """
    label = str(key_label or "").strip() or "iTE CLI"
    if force_headless or not can_bind_localhost_callback():
        return run_headless_pkce_flow(
            key_label=label,
            console_input=console_input,
            open_browser_fn=open_browser_fn,
        )
    return run_localhost_pkce_flow(
        key_label=label,
        timeout_sec=timeout_sec,
        open_browser_fn=open_browser_fn,
    )


def _percent_encode(value: str) -> str:
    """URL-encode a value for use as a query parameter.

    Kept tiny on purpose — the only fields we encode are ASCII-only in
    normal use (host:port, code challenge, key label). Non-ASCII labels
    fall back to a safe encoding.
    """
    from urllib.parse import quote

    return quote(value, safe=".-_~")


def _percent_decode(value: str) -> str:
    from urllib.parse import unquote

    return unquote(value)
