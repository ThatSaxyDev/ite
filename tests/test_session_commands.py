import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console

from ite.commands import CommandContext
from ite.commands.session import cmd_rename
from ite.config.config import Config


class SessionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_rename_updates_session_name(self) -> None:
        cwd = Path("/tmp/ite-test-session-rename")
        config = Config(cwd=cwd, api_key="test")
        output = io.StringIO()
        session = SimpleNamespace(
            session_id="session-123",
            name=None,
            name_source=None,
            name_locked=False,
            name_last_generated_turn=0,
            created_at=None,
            updated_at=None,
            turn_count=0,
            context_manager=SimpleNamespace(get_messages=lambda: [], total_usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0, cached_tokens=0)),
            plan_mode_enabled=False,
            plan_phase="idle",
            plan_questions_asked=0,
            plan_target_questions=3,
            pending_plan_text=None,
            active_plan_text=None,
            export_todos_state=lambda: {},
            show_planning_todos=False,
            export_change_history_state=lambda: {},
            set_manual_name=lambda name: setattr(session, "name", name),
            snapshot_kwargs=lambda workspace_path: {
                "session_id": "session-123",
                "name": session.name,
                "name_source": session.name_source,
                "name_locked": session.name_locked,
                "name_last_generated_turn": session.name_last_generated_turn,
                "workspace_path": workspace_path,
                "created_at": None,
                "updated_at": None,
                "turn_count": 0,
                "messages": [],
                "total_usage": SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0, cached_tokens=0),
                "plan_mode_enabled": False,
                "plan_phase": "idle",
                "plan_questions_asked": 0,
                "plan_target_questions": 3,
                "pending_plan_text": None,
                "active_plan_text": None,
                "todos_state": {},
                "show_planning_todos": False,
                "change_history_state": {},
            },
        )
        agent = SimpleNamespace(session=session)
        ctx = CommandContext(
            config=config,
            agent=agent,
            tui=None,
            console=Console(file=output, force_terminal=False, color_system=None),
        )

        fake_manager = SimpleNamespace(save_session=lambda snapshot: None)
        with patch("ite.commands.session.SessionManager", return_value=fake_manager):
            await cmd_rename(ctx, ["Release", "Bump", "Thread"])

        self.assertEqual(session.name, "Release Bump Thread")
        self.assertIn("Session renamed", output.getvalue())
