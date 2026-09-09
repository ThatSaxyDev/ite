"""Unit tests for the OpenRouter PKCE helper."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import unittest
from unittest.mock import patch

import httpx

from ite.auth import openrouter_pkce as pkce


class PKCEPairTests(unittest.TestCase):
    def test_pair_is_s256_and_round_trips(self) -> None:
        pair = pkce.generate_pkce_pair()
        # Per RFC 7636, an unencoded SHA-256 digest is 32 bytes; base64url
        # without padding is 43 chars.
        self.assertGreaterEqual(len(pair.code_verifier), 43)
        self.assertEqual(len(pair.code_challenge), 43)
        digest = hashlib.sha256(pair.code_verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        self.assertEqual(pair.code_challenge, expected)

    def test_pair_is_fresh_each_call(self) -> None:
        first = pkce.generate_pkce_pair()
        second = pkce.generate_pkce_pair()
        self.assertNotEqual(first.code_verifier, second.code_verifier)
        self.assertNotEqual(first.code_challenge, second.code_challenge)


class BuildAuthURLTests(unittest.TestCase):
    def test_localhost_url_includes_callback_and_s256(self) -> None:
        url = pkce.build_auth_url(
            code_challenge="abc123",
            key_label="iTE CLI (host)",
            callback_url="http://127.0.0.1:51423/callback",
        )
        self.assertTrue(url.startswith("https://openrouter.ai/auth?"))
        self.assertIn("callback_url=http%3A%2F%2F127.0.0.1%3A51423%2Fcallback", url)
        self.assertIn("code_challenge=abc123", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("key_label=iTE%20CLI%20%28host%29", url)

    def test_headless_url_omits_callback(self) -> None:
        url = pkce.build_auth_url(
            code_challenge="abc123",
            key_label="iTE CLI",
            callback_url=None,
        )
        self.assertNotIn("callback_url=", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("key_label=", url)

    def test_empty_label_is_dropped(self) -> None:
        url = pkce.build_auth_url(
            code_challenge="x", key_label="   ", callback_url=None
        )
        self.assertNotIn("key_label=", url)


class ExchangeCodeTests(unittest.TestCase):
    def _fake_response(self, status: int, body: bytes) -> httpx.Response:
        return httpx.Response(status, content=body)

    def test_exchange_returns_key_on_2xx(self) -> None:
        with patch.object(
            pkce.httpx,
            "post",
            return_value=self._fake_response(200, b'{"key": "sk-or-v1-abc"}'),
        ):
            key = pkce.exchange_code(code="abc", code_verifier="verifier")
        self.assertEqual(key, "sk-or-v1-abc")

    def test_exchange_surfaces_4xx_body(self) -> None:
        with patch.object(
            pkce.httpx,
            "post",
            return_value=self._fake_response(403, b"Authorization code expired"),
        ):
            with self.assertRaises(pkce.OpenRouterAuthError) as ctx:
                pkce.exchange_code(code="abc", code_verifier="verifier")
        self.assertIn("Authorization code expired", str(ctx.exception))

    def test_exchange_wraps_transport_error(self) -> None:
        with patch.object(
            pkce.httpx, "post", side_effect=httpx.ConnectError("nope")
        ):
            with self.assertRaises(pkce.OpenRouterAuthError) as ctx:
                pkce.exchange_code(code="abc", code_verifier="verifier")
        self.assertIn("Could not reach OpenRouter", str(ctx.exception))

    def test_exchange_rejects_missing_key(self) -> None:
        with patch.object(
            pkce.httpx,
            "post",
            return_value=self._fake_response(200, b'{"unexpected": true}'),
        ):
            with self.assertRaises(pkce.OpenRouterAuthError) as ctx:
                pkce.exchange_code(code="abc", code_verifier="verifier")
        self.assertIn("did not include an API key", str(ctx.exception))


class LocalhostProbeTests(unittest.TestCase):
    def test_can_bind_localhost_returns_true_on_normal_host(self) -> None:
        # The CI host must be able to bind a localhost port for this to
        # assert anything meaningful; on the dev box this is always true.
        self.assertTrue(pkce.can_bind_localhost_callback())


class LocalhostFlowTests(unittest.TestCase):
    """End-to-end localhost callback flow over a real loopback socket.

    Guarded regression: the callback listener must be bound to the SAME
    port that is baked into the OpenRouter auth URL, otherwise the
    redirect is silently dropped and the flow hangs until timeout.
    """

    def test_localhost_callback_flow_exchanges_key(self) -> None:
        import threading
        import urllib.request
        from urllib.parse import parse_qs, urlsplit

        def _simulate_browser(url: str) -> bool:
            # Fire a real HTTP GET at the exact callback target baked into
            # the auth URL, mirroring OpenRouter's redirect. The request is
            # made from a daemon thread so it does not block the event loop
            # that must serve the callback concurrently.
            query = urlsplit(url).query
            callback_url = parse_qs(query)["callback_url"][0]
            target = f"{callback_url}?code=test-code-123"

            def _fire() -> None:
                with urllib.request.urlopen(target, timeout=5) as resp:
                    resp.read()

            threading.Thread(target=_fire, daemon=True).start()
            return True

        with patch.object(
            pkce.httpx,
            "post",
            return_value=httpx.Response(200, content=b'{"key": "sk-or-v1-cbk"}'),
        ):
            key = asyncio.run(
                pkce.run_localhost_pkce_flow_async(
                    key_label="iTE CLI",
                    timeout_sec=10.0,
                    open_browser_fn=_simulate_browser,
                )
            )
        self.assertEqual(key, "sk-or-v1-cbk")


class HeadlessFlowTests(unittest.TestCase):
    def test_headless_prompts_and_exchanges(self) -> None:
        def _input(_prompt: str) -> str:
            return "  pasted-code-123  "

        with patch.object(
            pkce.httpx,
            "post",
            return_value=httpx.Response(200, content=b'{"key": "sk-or-v1-x"}'),
        ):
            key = pkce.run_headless_pkce_flow(
                key_label="iTE CLI",
                console_input=_input,
                open_browser_fn=lambda _url: True,
            )
        self.assertEqual(key, "sk-or-v1-x")

    def test_headless_rejects_empty_paste(self) -> None:
        with self.assertRaises(pkce.OpenRouterAuthError) as ctx:
            pkce.run_headless_pkce_flow(
                key_label="iTE CLI",
                console_input=lambda _prompt: "",
                open_browser_fn=lambda _url: True,
            )
        self.assertIn("No authorization code", str(ctx.exception))

    def test_headless_rejects_malformed_code(self) -> None:
        with self.assertRaises(pkce.OpenRouterAuthError) as ctx:
            pkce.run_headless_pkce_flow(
                key_label="iTE CLI",
                console_input=lambda _prompt: "x" * 4096,
                open_browser_fn=lambda _url: True,
            )
        self.assertIn("malformed", str(ctx.exception))


class KeyLinksTests(unittest.TestCase):
    def test_key_links_use_lowercase_sha256_hex_digest(self) -> None:
        settings_url, logs_url = pkce.openrouter_key_links(
            api_key="sk-or-v1-abc123"
        )
        digest = hashlib.sha256(b"sk-or-v1-abc123").hexdigest()
        self.assertEqual(settings_url, f"https://openrouter.ai/keys/{digest}")
        self.assertEqual(
            logs_url, f"https://openrouter.ai/logs?api_key_hash={digest}"
        )
        self.assertEqual(digest, digest.lower())

    def test_open_key_page_opens_settings_url(self) -> None:
        opened: list[str] = []

        def _open(url: str) -> bool:
            opened.append(url)
            return True

        ok = pkce.open_openrouter_key_page(
            api_key="sk-or-v1-abc", open_browser_fn=_open
        )
        self.assertTrue(ok)
        self.assertEqual(len(opened), 1)
        self.assertIn("https://openrouter.ai/keys/", opened[0])


class TopLevelEntryTests(unittest.TestCase):
    def test_force_headless_skips_probe(self) -> None:
        with patch.object(
            pkce.httpx,
            "post",
            return_value=httpx.Response(200, content=b'{"key": "sk-or-v1-y"}'),
        ):
            key = pkce.run_pkce_login(
                key_label="iTE CLI",
                console_input=lambda _prompt: "pasted-code-1234",
                force_headless=True,
            )
        self.assertEqual(key, "sk-or-v1-y")

    def test_default_label_when_blank(self) -> None:
        with patch.object(
            pkce.httpx,
            "post",
            return_value=httpx.Response(200, content=b'{"key": "sk-or-v1-z"}'),
        ):
            key = pkce.run_pkce_login(
                key_label="   ",
                console_input=lambda _prompt: "pasted-code-1234",
                force_headless=True,
            )
        self.assertEqual(key, "sk-or-v1-z")
