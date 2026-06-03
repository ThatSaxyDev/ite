import asyncio
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ite.cloud.auth import CloudSession
from ite.cloud.services import _get_cloud_session_for_metadata, generate_cloud_session_title
from ite.config.config import Config


class CloudServicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            cwd=Path("/tmp"),
            api_key="test",
            cloud_auth_enabled=True,
            cloud_api_url="http://127.0.0.1:4000",
        )

    def test_metadata_session_refreshes_expired_access_token(self) -> None:
        expired = CloudSession(
            access_token="expired-access",
            refresh_token="refresh",
            access_expires_at=0,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )
        refreshed = CloudSession(
            access_token="fresh-access",
            refresh_token="refresh",
            access_expires_at=time.time() + 3600,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )

        with (
            patch("ite.cloud.services._load_cloud_session", return_value=expired),
            patch("ite.cloud.services._refresh_cloud_session", return_value=refreshed) as refresh,
        ):
            session = asyncio.run(_get_cloud_session_for_metadata(self.config))

        self.assertEqual(session, refreshed)
        refresh.assert_called_once_with(expired)

    def test_metadata_session_reuses_valid_access_token(self) -> None:
        valid = CloudSession(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=time.time() + 3600,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )

        with (
            patch("ite.cloud.services._load_cloud_session", return_value=valid),
            patch("ite.cloud.services._refresh_cloud_session") as refresh,
        ):
            session = asyncio.run(_get_cloud_session_for_metadata(self.config))

        self.assertEqual(session, valid)
        refresh.assert_not_called()

    def test_generate_cloud_session_title_posts_to_metadata_route(self) -> None:
        session = CloudSession(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=time.time() + 3600,
            api_url="http://127.0.0.1:4000",
            client_id="test-device",
        )
        captured: dict[str, object] = {}

        class Response:
            status_code = 200

            def json(self) -> dict[str, object]:
                return {"ok": True, "title": "Fix Session Naming"}

        class Client:
            def __init__(self, *args, **kwargs) -> None:
                captured["timeout"] = kwargs.get("timeout")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args) -> None:
                return None

            async def post(self, url, *, headers, json):
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                return Response()

        with (
            patch("ite.cloud.services._get_cloud_session_for_metadata", return_value=session),
            patch("ite.cloud.services.httpx.AsyncClient", Client),
        ):
            title = asyncio.run(
                generate_cloud_session_title(
                    self.config,
                    {
                        "first_user": "Help me fix session naming",
                        "first_assistant": "",
                        "latest_user": "Make the Reup title work",
                        "focus_hint": "session naming",
                        "first_turn": "User asked about session naming. Tool call grep found refresh logic.",
                        "turn_count": "1",
                    },
                )
            )

        self.assertEqual(title, "Fix Session Naming")
        self.assertEqual(captured["url"], "http://127.0.0.1:4000/metadata/session-title")
        self.assertEqual(captured["headers"]["authorization"], "Bearer access")
        self.assertEqual(captured["json"]["focusHint"], "session naming")
        self.assertIn("Tool call grep", captured["json"]["firstTurn"])
        self.assertEqual(captured["json"]["turnCount"], 1)
