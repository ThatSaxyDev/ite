import unittest
from pathlib import Path

from ite.agent.session import Session
from ite.config.config import Config


class SessionNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = Session(Config(cwd=Path("/tmp"), api_key="test"))

    def test_manual_name_locks_session_title(self) -> None:
        self.session.turn_count = 2
        self.session.set_manual_name("Manual Title")

        self.assertEqual(self.session.name, "Manual Title")
        self.assertEqual(self.session.name_source, "manual")
        self.assertTrue(self.session.name_locked)

    def test_auto_name_can_refresh_once_after_turn_three(self) -> None:
        self.session.turn_count = 1
        self.session.set_auto_name("Initial Title")
        self.assertFalse(self.session.should_refresh_auto_name())

        self.session.turn_count = 3
        self.assertTrue(self.session.should_refresh_auto_name())

        self.session.set_auto_name("Better Title")
        self.assertFalse(self.session.should_refresh_auto_name())
        self.assertEqual(self.session.name, "Better Title")
