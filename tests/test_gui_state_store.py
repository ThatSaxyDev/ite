import unittest
from ite.ui.gui.state import GUIStateStore


class GUIStateStoreTests(unittest.TestCase):
    def test_session_selection_and_load_transaction(self):
        store = GUIStateStore(initial_workspace="/tmp/ws")
        store.select_session("abc")
        self.assertEqual(store.state.shell.loading_session_id, "abc")
        self.assertTrue(store.state.interaction.is_switching_session)
        self.assertFalse(store.state.interaction.can_send)

        store.session_loaded(
            session_id="abc",
            title="Loaded",
            workspace="/tmp/ws",
            visible_transcript_messages=[{"role": "user", "content": "hi"}],
            transcript_truncated=True,
            pending_transcript_load=True,
        )
        self.assertEqual(store.state.shell.active_session_id, "abc")
        self.assertIsNone(store.state.shell.loading_session_id)
        self.assertFalse(store.state.interaction.is_switching_session)
        self.assertEqual(store.state.session_view.current_session_title, "Loaded")
        self.assertTrue(store.state.session_view.transcript_truncated)

    def test_workboard_content_controls_visibility(self):
        store = GUIStateStore(initial_workspace="/tmp/ws")
        store.set_workboard_content(
            plan_text="plan",
            todos_state={"execution": [{"id": "1"}], "planning": [], "version": 1},
            show_planning_todos=False,
            has_content=True,
        )
        self.assertTrue(store.state.workboard.has_content)
        self.assertTrue(store.state.shell.workboard_visible)

        store.toggle_workboard()
        self.assertFalse(store.state.shell.workboard_visible)

        store.set_workboard_content(
            plan_text="",
            todos_state=None,
            show_planning_todos=False,
            has_content=False,
        )
        self.assertFalse(store.state.workboard.has_content)
        self.assertFalse(store.state.shell.workboard_visible)


if __name__ == "__main__":
    unittest.main()
