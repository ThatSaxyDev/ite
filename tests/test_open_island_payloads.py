from __future__ import annotations

import unittest
from pathlib import Path

from ite.integrations.open_island import payloads
from ite.integrations.open_island.terminal import (
    TerminalContext,
    detect_terminal,
    detect_terminal_app,
    detect_terminal_session_id,
    workspace_name,
)


class DetectTerminalAppTests(unittest.TestCase):
    def test_known_term_program_is_named(self) -> None:
        self.assertEqual(detect_terminal_app({"TERM_PROGRAM": "iTerm.app"}), "iTerm")
        self.assertEqual(
            detect_terminal_app({"TERM_PROGRAM": "Apple_Terminal"}), "Terminal"
        )
        self.assertEqual(
            detect_terminal_app({"TERM_PROGRAM": "WarpTerminal"}), "Warp"
        )

    def test_unknown_term_program_passes_through(self) -> None:
        self.assertEqual(detect_terminal_app({"TERM_PROGRAM": "SomeNewTerm"}), "SomeNewTerm")

    def test_missing_environment_yields_none(self) -> None:
        self.assertIsNone(detect_terminal_app({}))

    def test_ghostty_inferred_from_term(self) -> None:
        self.assertEqual(detect_terminal_app({"TERM": "xterm-ghostty"}), "Ghostty")


class DetectSessionIdTests(unittest.TestCase):
    def test_iterm_session_id_is_used(self) -> None:
        self.assertEqual(
            detect_terminal_session_id({"ITERM_SESSION_ID": "w0t0p0:ABC"}),
            "w0t0p0:ABC",
        )

    def test_missing_session_id_yields_none(self) -> None:
        self.assertIsNone(detect_terminal_session_id({}))


class TerminalContextTests(unittest.TestCase):
    def test_empty_fields_are_omitted(self) -> None:
        context = TerminalContext(app="iTerm", tty=None, session_id="", title=None)
        self.assertEqual(context.as_payload_fields(), {"terminal_app": "iTerm"})

    def test_all_fields_present(self) -> None:
        context = TerminalContext(
            app="Warp", tty="/dev/ttys003", session_id="abc", title="zsh"
        )
        self.assertEqual(
            context.as_payload_fields(),
            {
                "terminal_app": "Warp",
                "terminal_tty": "/dev/ttys003",
                "terminal_session_id": "abc",
                "terminal_title": "zsh",
            },
        )

    def test_detection_never_raises_on_broken_env(self) -> None:
        self.assertIsInstance(detect_terminal({"TERM_PROGRAM": ""}), TerminalContext)


class WorkspaceNameTests(unittest.TestCase):
    def test_uses_directory_name(self) -> None:
        self.assertEqual(workspace_name("/Users/someone/projects/my-app"), "my-app")

    def test_falls_back_to_full_path_for_root(self) -> None:
        self.assertEqual(workspace_name(Path("/")), "/")


class PayloadShapeTests(unittest.TestCase):
    def test_session_start_has_required_fields(self) -> None:
        payload = payloads.session_start("sid-1", "/tmp/proj")
        self.assertEqual(payload["hook_event_name"], "SessionStart")
        self.assertEqual(payload["session_id"], "sid-1")
        self.assertEqual(payload["cwd"], "/tmp/proj")
        self.assertEqual(payload["source"], "startup")
        self.assertEqual(payload["hook_source"], payloads.HOOK_SOURCE)

    def test_command_wraps_in_process_claude_hook(self) -> None:
        command = payloads.command(payloads.session_start("sid-1", "/tmp/proj"))
        self.assertEqual(command["type"], "processClaudeHook")
        self.assertEqual(command["claudeHook"]["hook_event_name"], "SessionStart")

    def test_terminal_fields_are_embedded(self) -> None:
        terminal = TerminalContext(app="iTerm", tty="/dev/ttys001")
        payload = payloads.session_start("sid-1", "/tmp/proj", terminal)
        self.assertEqual(payload["terminal_app"], "iTerm")
        self.assertEqual(payload["terminal_tty"], "/dev/ttys001")

    def test_tool_payloads_use_upstream_field_names(self) -> None:
        pre = payloads.pre_tool_use("sid", "/tmp/p", "read_file", {"path": "a.py"}, "call-1")
        self.assertEqual(pre["tool_name"], "read_file")
        self.assertEqual(pre["tool_use_id"], "call-1")
        # iTE calls it `path`; Open Island only renders `file_path`.
        self.assertEqual(pre["tool_input"], {"file_path": "a.py"})
        self.assertNotIn("toolUseID", pre)


class ToolInputNormalizationTests(unittest.TestCase):
    """Open Island renders a preview from a fixed set of key names.

    An unrecognised key makes it serialise the whole JSON object, which is the
    "tool calls look wrong" symptom. These tests pin the normalisation that
    fixes it.
    """

    def test_path_becomes_file_path(self) -> None:
        self.assertEqual(
            payloads.normalize_tool_input({"path": "src/app.py"}),
            {"file_path": "src/app.py"},
        )

    def test_cmd_becomes_command(self) -> None:
        self.assertEqual(
            payloads.normalize_tool_input({"cmd": "pytest -q"}),
            {"command": "pytest -q"},
        )

    def test_glob_becomes_pattern(self) -> None:
        self.assertEqual(
            payloads.normalize_tool_input({"glob": "**/*.py"}),
            {"pattern": "**/*.py"},
        )

    def test_recognised_key_is_left_untouched(self) -> None:
        """A payload that already renders well must not be rewritten."""
        arguments = {"file_path": "right"}
        self.assertEqual(payloads.normalize_tool_input(arguments), arguments)

    def test_grep_keeps_pattern_visible(self) -> None:
        """`path` must not be promoted: file_path outranks pattern upstream.

        Regression guard. Promoting `path` to `file_path` hid the search term
        behind the directory — strictly worse than not normalising at all.
        """
        normalized = payloads.normalize_tool_input(
            {"pattern": "def run", "path": "src/ite"}
        )
        self.assertEqual(
            payloads.summary_preview("grep", normalized), "Running grep: def run"
        )

    def test_glob_prefers_pattern_over_path(self) -> None:
        """Only one alias is promoted, most descriptive first."""
        normalized = payloads.normalize_tool_input({"glob": "**/*.py", "path": "src"})
        self.assertEqual(
            payloads.summary_preview("glob", normalized), "Running glob: **/*.py"
        )

    def test_unrelated_keys_are_preserved(self) -> None:
        normalized = payloads.normalize_tool_input(
            {"path": "a.py", "start_line": 10, "end_line": 20}
        )
        self.assertEqual(
            normalized,
            {"file_path": "a.py", "start_line": 10, "end_line": 20},
        )

    def test_none_is_passed_through(self) -> None:
        self.assertIsNone(payloads.normalize_tool_input(None))


class NonRenderableInputTests(unittest.TestCase):
    """Raw JSON must never reach the UI.

    `git_log` takes only `{limit, ref}`. Neither is a name Open Island renders,
    so it fell back to serialising the whole object and the notch showed the
    literal string `$ {limit: 10}` — an internal parameter leaked to the user.
    """

    def _status(self, tool_name: str, arguments: dict) -> str:
        payload = payloads.pre_tool_use("sid", "/tmp/p", tool_name, arguments, None)
        self.assertNotIn("tool_input", payload)
        return payloads.island_status_text(payload)

    def test_limit_only_args_are_dropped(self) -> None:
        self.assertIsNone(payloads.normalize_tool_input({"limit": 10}))

    def test_git_log_shows_only_its_name(self) -> None:
        self.assertEqual(self._status("git_log", {"limit": 10}), "Git Log")

    def test_empty_arguments_are_dropped(self) -> None:
        self.assertIsNone(payloads.normalize_tool_input({}))

    def test_non_string_recognised_key_is_dropped(self) -> None:
        """Upstream only renders `.string`; a number would still dump JSON."""
        self.assertIsNone(payloads.normalize_tool_input({"file_path": 12}))

    def test_boolean_of_a_recognised_key_is_dropped(self) -> None:
        self.assertIsNone(payloads.normalize_tool_input({"file_path": True}))

    def test_meaningful_arg_survives_alongside_noise(self) -> None:
        normalized = payloads.normalize_tool_input({"path": "a.py", "limit": 10})
        self.assertEqual(normalized["file_path"], "a.py")
        self.assertEqual(
            payloads.island_status_text(
                {"tool_name": "read_file", "tool_input": normalized}
            ),
            "Read File a.py",
        )

    def test_ref_only_args_are_dropped(self) -> None:
        self.assertIsNone(payloads.normalize_tool_input({"ref": "main"}))

    def test_offset_only_args_are_dropped(self) -> None:
        self.assertIsNone(payloads.normalize_tool_input({"offset": 200}))

    def test_no_payload_produces_a_json_blob(self) -> None:
        """End-to-end guard across every iTE tool argument shape we know of."""
        shapes = [
            ("git_log", {"limit": 10}),
            ("git_diff", {"staged_only": True}),
            ("read_file", {"limit": 50}),
            ("todos", {"action": "list", "scope": "execution"}),
            ("todos", {"action": "add", "items": ["a", "b"]}),
            ("memory", {"action": "list", "limit": 6}),
            ("list_dir", {}),
        ]
        for tool_name, arguments in shapes:
            with self.subTest(tool=tool_name, args=arguments):
                status = self._status(tool_name, arguments)
                self.assertNotIn("{", status)
                self.assertNotIn("}", status)
    def test_summary_preview_renders_path(self) -> None:
        preview = payloads.summary_preview(
            "read_file", payloads.normalize_tool_input({"path": "src/app.py"})
        )
        self.assertEqual(preview, "Running read_file: src/app.py")

    def test_summary_preview_renders_command(self) -> None:
        preview = payloads.summary_preview(
            "shell", payloads.normalize_tool_input({"cmd": "pytest -q"})
        )
        self.assertEqual(preview, "Running shell: pytest -q")

    def test_summary_preview_falls_back_to_whole_object(self) -> None:
        """Pins the upstream fallback that normalization exists to avoid."""
        preview = payloads.summary_preview("custom", {"anything": "value"})
        self.assertEqual(preview, 'Running custom: {"anything":"value"}')

    def test_unnormalized_path_produces_blob(self) -> None:
        """Regression guard: the pre-fix rendering was a raw JSON blob."""
        self.assertEqual(
            payloads.summary_preview("read_file", {"path": "src/app.py"}),
            'Running read_file: {"path":"src/app.py"}',
        )

    def test_normalized_path_produces_clean_summary(self) -> None:
        preview = payloads.summary_preview(
            "read_file", payloads.normalize_tool_input({"path": "src/app.py"})
        )
        self.assertEqual(preview, "Running read_file: src/app.py")

    def test_summary_preview_without_input_is_bare(self) -> None:
        self.assertEqual(payloads.summary_preview("read_file", None), "Running read_file")

    def test_correlation_key_is_stable_across_alias_forms(self) -> None:
        """PermissionRequest correlation depends on identical serialisation."""
        first = payloads.serialize_tool_input({"path": "a.py"})
        second = payloads.serialize_tool_input({"file_path": "a.py"})
        self.assertEqual(first, second)


class ActivityStatusTests(unittest.TestCase):
    """The island's status line is derived only from `currentTool`.

    A reasoning turn has no tool, so without an explicit activity payload the
    island shows its generic "Thinking" while iTE's TUI shows a gerund.
    """

    def test_payload_carries_label_on_tool_name(self) -> None:
        payload = payloads.activity_status("sid", "/tmp/p", "Brewing")
        self.assertEqual(payload["hook_event_name"], "PreToolUse")
        self.assertEqual(payload["tool_name"], "Brewing")

    def test_no_tool_input_so_no_preview_is_appended(self) -> None:
        payload = payloads.activity_status("sid", "/tmp/p", "Brewing")
        self.assertNotIn("tool_input", payload)
        self.assertNotIn("tool_use_id", payload)

    def test_island_renders_the_label_verbatim(self) -> None:
        payload = payloads.activity_status("sid", "/tmp/p", "Brewing")
        self.assertEqual(payloads.island_status_text(payload), "Brewing")

    def test_terminal_fields_are_included(self) -> None:
        terminal = TerminalContext(app="iTerm", tty="/dev/ttys001")
        payload = payloads.activity_status("sid", "/tmp/p", "Brewing", terminal)
        self.assertEqual(payload["terminal_app"], "iTerm")

    def test_settable_as_a_bridge_command(self) -> None:
        command = payloads.command(
            payloads.activity_status("sid", "/tmp/p", "Brewing")
        )
        self.assertEqual(command["type"], "processClaudeHook")
        self.assertEqual(command["claudeHook"]["tool_name"], "Brewing")


class IslandStatusTextTests(unittest.TestCase):
    def test_tool_label_with_preview(self) -> None:
        payload = {
            "tool_name": "read_file",
            "tool_input": {"file_path": "config/loader.py"},
        }
        self.assertEqual(
            payloads.island_status_text(payload), "Read File config/loader.py"
        )

    def test_unknown_tool_name_is_humanised(self) -> None:
        self.assertEqual(
            payloads.humanized_tool_name("apply_patch"), "Apply Patch"
        )

    def test_acronyms_are_preserved(self) -> None:
        self.assertEqual(payloads.humanized_tool_name("read_url"), "Read URL")
        self.assertEqual(payloads.humanized_tool_name("get_api_key"), "Get API Key")

    def test_no_tool_name_falls_back_to_running(self) -> None:
        self.assertEqual(payloads.island_status_text({}), "Running")

    def test_failed_tool_uses_failure_event(self) -> None:
        post = payloads.post_tool_use(
            "sid", "/tmp/p", "shell", "call-1", output="boom", success=False
        )
        self.assertEqual(post["hook_event_name"], "PostToolUseFailure")
        self.assertIn("error", post)

    def test_successful_tool_uses_post_tool_use(self) -> None:
        post = payloads.post_tool_use(
            "sid", "/tmp/p", "shell", "call-1", output="ok", success=True
        )
        self.assertEqual(post["hook_event_name"], "PostToolUse")
        self.assertNotIn("error", post)

    def test_completion_carries_no_tool_input(self) -> None:
        """Omitting it is what clears the island's preview.

        Upstream clears `currentToolInputPreview` only when an update omits it.
        Sending it would let a finished tool's preview survive into the next
        reasoning label.
        """
        post = payloads.post_tool_use(
            "sid", "/tmp/p", "read_file", "call-1", output="ok", success=True
        )
        self.assertNotIn("tool_input", post)

    def test_large_output_is_truncated(self) -> None:
        huge = "x" * (payloads.MAX_FIELD_CHARS + 500)
        payload = payloads.post_tool_use(
            "sid", "/tmp/p", "shell", None, output=huge, success=True
        )
        self.assertLessEqual(
            len(payload["tool_response"]), payloads.MAX_FIELD_CHARS + 20
        )

    def test_session_end_marks_interrupt(self) -> None:
        payload = payloads.session_end("sid", "/tmp/p", is_interrupt=True)
        self.assertEqual(payload["hook_event_name"], "SessionEnd")
        self.assertTrue(payload["is_interrupt"])

    def test_serialize_tool_input_is_stable_ordering(self) -> None:
        first = payloads.serialize_tool_input({"b": 1, "a": 2})
        second = payloads.serialize_tool_input({"a": 2, "b": 1})
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
