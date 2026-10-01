from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from rich.console import Console

from ite.commands import CommandContext
from ite.commands import init as init_command
from ite.config.config import Config
from ite.config.loader import _merge_agents_md_instructions


def draft(cwd: Path, *, content: str = "", **fields: object) -> str:
    (cwd / "README.md").write_text("Project\nRun pytest to check it.\n")
    payload = {
        "markdown": content
        or "# AGENTS.md\n\n## Project Overview\nExample project.\n\n## Architecture\nRead README.md.\n\n## Development Guidelines\nRun `pytest`.\n",
        "inspected_files": ["README.md"],
        "referenced_paths": ["README.md"],
        "commands": [{"command": "pytest", "source": "README.md"}],
    }
    payload.update(fields)
    return json.dumps(payload)


def context(cwd: Path, monkeypatch: pytest.MonkeyPatch) -> CommandContext:
    monkeypatch.setattr(init_command, "_get_agents_md_files", lambda _: [])
    session = SimpleNamespace(
        context_manager=SimpleNamespace(add_system_message=Mock()),
        subagent_runtime=None,
    )
    return CommandContext(
        config=Config(cwd=cwd),
        agent=SimpleNamespace(session=session),
        tui=SimpleNamespace(
            begin_command_progress=AsyncMock(),
            update_command_progress=AsyncMock(),
            finish_command_progress=AsyncMock(),
        ),
        console=Console(file=StringIO()),
        evidence_files=["README.md"],
    )


def test_success_activates_instructions_in_one_card(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    investigate = AsyncMock(return_value=draft(tmp_path))
    monkeypatch.setattr(init_command, "_run_init_investigator", investigate)
    asyncio.run(init_command.cmd_init(ctx, []))
    assert (tmp_path / "AGENTS.md").read_text().startswith("# AGENTS.md\n")
    assert ctx.outcome == "completed"
    assert "Active in this chat" in ctx.result
    assert "1 file checked" in ctx.result
    ctx.agent.session.context_manager.add_system_message.assert_called_once()
    assert "Development Guidelines" in ctx.config.developer_instructions
    ctx.tui.finish_command_progress.assert_awaited_once()
    assert not list(tmp_path.glob(".agents-*"))


@pytest.mark.parametrize(
    "response", ["No response", "# Analysis\nCould not investigate", "{}", "[]"]
)
def test_bad_output_is_never_written(tmp_path, monkeypatch, response):
    ctx = context(tmp_path, monkeypatch)
    monkeypatch.setattr(
        init_command, "_run_init_investigator", AsyncMock(return_value=response)
    )
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "failed"
    assert not (tmp_path / "AGENTS.md").exists()
    ctx.agent.session.context_manager.add_system_message.assert_not_called()


def test_validation_repair_uses_same_deadline(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    investigate = AsyncMock(side_effect=["No response", draft(tmp_path)])
    monkeypatch.setattr(init_command, "_run_init_investigator", investigate)
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "completed"
    first, second = investigate.await_args_list
    assert first.kwargs["deadline"] == second.kwargs["deadline"]
    assert "Previous response" in second.kwargs["feedback"]


def test_oversized_draft_does_not_cut_or_replace_existing_file(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    path = tmp_path / "AGENTS.md"
    path.write_text("Maintainer constraints\n")
    response = draft(tmp_path)
    data = json.loads(response)
    data["markdown"] += "\n" + "x" * 40000
    monkeypatch.setattr(
        init_command, "_run_init_investigator", AsyncMock(return_value=json.dumps(data))
    )
    asyncio.run(init_command.cmd_init(ctx, ["--force"]))
    assert ctx.outcome == "failed"
    assert path.read_text() == "Maintainer constraints\n"
    assert "combined budget" in ctx.result


@pytest.mark.parametrize("force", [False, True])
def test_concurrent_writer_is_protected(tmp_path, monkeypatch, force):
    ctx = context(tmp_path, monkeypatch)
    response = draft(tmp_path)
    path = tmp_path / "AGENTS.md"
    if force:
        path.write_text("original")

    async def investigate(*args, **kwargs):
        path.write_text("concurrent edit")
        return response

    monkeypatch.setattr(init_command, "_run_init_investigator", investigate)
    asyncio.run(init_command.cmd_init(ctx, ["--force"] if force else []))
    assert ctx.outcome == "failed"
    assert path.read_text() == "concurrent edit"
    assert not list(tmp_path.glob(".agents-*"))


def test_existing_file_requires_force(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    (tmp_path / "AGENTS.md").write_text("Existing")
    investigate = AsyncMock()
    monkeypatch.setattr(init_command, "_run_init_investigator", investigate)
    asyncio.run(init_command.cmd_init(ctx, []))
    investigate.assert_not_awaited()
    assert "/init --force" in ctx.result


def test_override_is_reported_without_generating_unused_file(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    (tmp_path / "AGENTS.override.md").write_text("Override")
    investigate = AsyncMock()
    monkeypatch.setattr(init_command, "_run_init_investigator", investigate)
    asyncio.run(init_command.cmd_init(ctx, []))
    investigate.assert_not_awaited()
    assert "override" in ctx.result
    assert ctx.outcome == "failed"


def test_fenced_json_and_nested_markdown_are_preserved(tmp_path):
    data = json.loads(draft(tmp_path))
    data["markdown"] = (
        "````markdown\n" + data["markdown"] + '\n```python\nprint("hello")\n```\n````'
    )
    content, _ = init_command._validate_draft(
        "```json\n" + json.dumps(data) + "\n```", tmp_path
    )
    assert '```python\nprint("hello")\n```' in content
    assert content.startswith("# AGENTS.md\n")


@pytest.mark.parametrize(
    "fields",
    [
        {"referenced_paths": ["missing.py"]},
        {"inspected_files": ["../outside"]},
        {"commands": [{"command": "made-up-build", "source": "README.md"}]},
    ],
)
def test_invalid_repository_evidence_is_rejected(tmp_path, fields):
    with pytest.raises(ValueError):
        init_command._validate_draft(draft(tmp_path, **fields), tmp_path)


def test_package_script_commands_are_grounded(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}')
    response = draft(
        tmp_path,
        inspected_files=["README.md", "package.json"],
        commands=[{"command": "npm run test", "source": "package.json"}],
    )
    init_command._validate_draft(response, tmp_path)


def test_unclosed_fence_is_rejected(tmp_path):
    data = json.loads(draft(tmp_path))
    data["markdown"] += "\n```python\nprint(1)"
    with pytest.raises(ValueError, match="unclosed"):
        init_command._validate_draft(json.dumps(data), tmp_path)


def test_combined_budget_preserves_inherited_constraints(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    inherited = tmp_path / "parent" / "AGENTS.md"
    monkeypatch.setattr(
        init_command,
        "_get_agents_md_files",
        lambda _: [(inherited, "constraint\n" * 5000)],
    )
    monkeypatch.setattr(
        init_command, "_run_init_investigator", AsyncMock(return_value=draft(tmp_path))
    )
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "failed"
    assert not (tmp_path / "AGENTS.md").exists()


def test_loader_reports_omissions_and_respects_configurable_budget(tmp_path):
    files = [(tmp_path / "AGENTS.md", "x" * 40000)]
    warning = _merge_agents_md_instructions(files)
    assert "NOT loaded" in warning
    with pytest.raises(ValueError, match="would be omitted"):
        _merge_agents_md_instructions(files, strict=True)
    merged = _merge_agents_md_instructions(files, max_bytes=65536, strict=True)
    assert "x" * 40000 in merged
    assert len(merged.encode()) <= 65536


@pytest.mark.parametrize("reason", ["timeout", "cancelled", "failed"])
def test_terminal_run_failure_is_not_a_success(tmp_path, monkeypatch, reason):
    ctx = context(tmp_path, monkeypatch)
    run = SimpleNamespace(run_id="init-run")
    runtime = SimpleNamespace(
        spawn=AsyncMock(return_value=(run, False)),
        wait=AsyncMock(
            return_value={
                "runs": [
                    {"run_id": run.run_id, "status": reason, "error": "provider failed"}
                ]
            }
        ),
        cancel=AsyncMock(),
    )
    ctx.agent.session.subagent_runtime = runtime
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "failed"
    assert not (tmp_path / "AGENTS.md").exists()
    runtime.cancel.assert_not_awaited()


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_user_cancellation_stop_owned_investigator(
    tmp_path, monkeypatch, cancel
):
    ctx = context(tmp_path, monkeypatch)
    run = SimpleNamespace(run_id="init-run")

    async def wait(**kwargs):
        if cancel:
            raise asyncio.CancelledError
        await asyncio.sleep(10)

    runtime = SimpleNamespace(
        spawn=AsyncMock(return_value=(run, False)), wait=wait, cancel=AsyncMock()
    )
    ctx.agent.session.subagent_runtime = runtime

    async def work():
        deadline = asyncio.get_running_loop().time() + 0.01
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await init_command._run_init_investigator(ctx, deadline=deadline)

    asyncio.run(work())
    runtime.cancel.assert_awaited_once_with(run_ids=["init-run"])


def test_progress_comes_from_runtime_activity(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    run = SimpleNamespace(run_id="init-run")
    response = draft(tmp_path)
    runtime = SimpleNamespace(
        spawn=AsyncMock(return_value=(run, False)),
        wait=AsyncMock(
            side_effect=[
                {
                    "runs": [
                        {
                            "run_id": run.run_id,
                            "status": "running",
                            "current_activity": "Reading README.md.",
                        }
                    ]
                },
                {
                    "runs": [
                        {
                            "run_id": run.run_id,
                            "status": "completed",
                            "summary": response,
                        }
                    ]
                },
            ]
        ),
        cancel=AsyncMock(),
    )
    ctx.agent.session.subagent_runtime = runtime
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "completed"
    assert any(
        call.args[1] == "Reading README.md."
        for call in ctx.tui.update_command_progress.await_args_list
    )
    assert runtime.spawn.await_args.kwargs["subagent"] == "init_investigator"


def test_configured_budget_is_used_during_loading(tmp_path, monkeypatch):
    from ite.config import loader

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "agents_max_bytes = 65536\ninit_max_turns = 60\ninit_timeout_seconds = 900\n"
    )
    monkeypatch.setattr(loader, "get_system_config_path", lambda: config_path)
    monkeypatch.setattr(
        loader,
        "_get_agents_md_files",
        lambda _: [(tmp_path / "AGENTS.md", "x" * 40000)],
    )
    config = loader.load_config(tmp_path)
    assert config.init_max_turns == 60
    assert config.init_timeout_seconds == 900
    assert "x" * 40000 in config.developer_instructions


def test_refresh_failure_reports_saved_file_honestly(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    monkeypatch.setattr(
        init_command, "_run_init_investigator", AsyncMock(return_value=draft(tmp_path))
    )
    ctx.agent.session.context_manager.add_system_message.side_effect = RuntimeError(
        "context unavailable"
    )
    asyncio.run(init_command.cmd_init(ctx, []))
    assert (tmp_path / "AGENTS.md").exists()
    assert ctx.outcome == "failed"
    assert "was saved" in ctx.result


def test_cancelled_command_finishes_card(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    monkeypatch.setattr(
        init_command,
        "_run_init_investigator",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "cancelled"
    assert not (tmp_path / "AGENTS.md").exists()
    ctx.tui.finish_command_progress.assert_awaited_once()
    assert ctx.tui.finish_command_progress.await_args.kwargs["status"] == "cancelled"


def test_omission_warning_also_fits_instruction_budget(tmp_path):
    files = [
        (tmp_path / "parent" / "AGENTS.md", "x" * 10000),
        (tmp_path / "AGENTS.md", "y" * 3500),
    ]
    merged = _merge_agents_md_instructions(files, max_bytes=4096)
    assert "NOT loaded" in merged
    assert len(merged.encode("utf-8")) <= 4096


@pytest.mark.parametrize("wrapper", ["plain", "fenced", "introduction"])
def test_markdown_is_accepted_using_runtime_read_evidence(tmp_path, wrapper):
    content = json.loads(draft(tmp_path))["markdown"]
    if wrapper == "fenced":
        content = "```markdown\n" + content + "```"
    elif wrapper == "introduction":
        content = "Here are the project instructions:\n\n" + content
    result, count = init_command._validate_draft(
        content, tmp_path, observed_files=["README.md"]
    )
    assert result.startswith("# AGENTS.md\n")
    assert "Run `pytest`." in result
    assert count == 1


def test_plain_markdown_without_actual_reads_is_rejected(tmp_path):
    content = json.loads(draft(tmp_path))["markdown"]
    with pytest.raises(ValueError, match="successful repository file reads"):
        init_command._validate_draft(content, tmp_path, observed_files=[])


def test_markdown_unknown_command_remains_rejected(tmp_path):
    content = json.loads(draft(tmp_path))["markdown"].replace(
        "`pytest`", "`make invented-target`"
    )
    with pytest.raises(ValueError, match="Command is not supported"):
        init_command._validate_draft(content, tmp_path, observed_files=["README.md"])


def test_markdown_missing_repository_path_remains_rejected(tmp_path):
    content = json.loads(draft(tmp_path))["markdown"] + "\nRead `src/missing.py`.\n"
    with pytest.raises(ValueError, match="does not exist"):
        init_command._validate_draft(content, tmp_path, observed_files=["README.md"])


def test_runtime_markdown_response_creates_instructions(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    ctx.evidence_files.clear()
    content = json.loads(draft(tmp_path))["markdown"]
    run = SimpleNamespace(run_id="init-run")
    runtime = SimpleNamespace(
        spawn=AsyncMock(return_value=(run, False)),
        wait=AsyncMock(
            return_value={
                "runs": [
                    {
                        "run_id": run.run_id,
                        "status": "completed",
                        "summary": content,
                        "inspected_files": ["README.md"],
                    }
                ]
            }
        ),
        cancel=AsyncMock(),
    )
    ctx.agent.session.subagent_runtime = runtime
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "completed"
    assert (tmp_path / "AGENTS.md").read_text() == content
    runtime.spawn.assert_awaited_once()


def test_failed_validation_preserves_unapplied_draft(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    content = "# AGENTS.md\nIncomplete draft worth recovering.\n"
    monkeypatch.setattr(
        init_command, "_run_init_investigator", AsyncMock(return_value=content)
    )
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "failed"
    assert not (tmp_path / "AGENTS.md").exists()
    paths = list((tmp_path / ".ite" / "init-drafts").glob("*.txt"))
    assert len(paths) == 1
    assert paths[0].read_text() == content
    assert "Unapplied draft saved" in ctx.result


def test_hypothetical_examples_are_not_project_command_claims(tmp_path):
    content = json.loads(draft(tmp_path))["markdown"]
    content += "\nDo not assume `pip install -e .` works without adding a build backend.\n\nIf you introduce a package, add `__main__.py` so `python -m <package>` works.\n"
    result, _ = init_command._validate_draft(
        content, tmp_path, observed_files=["README.md"]
    )
    assert "__main__.py" in result


def test_completed_draft_is_not_rendered_as_progress(tmp_path, monkeypatch):
    ctx = context(tmp_path, monkeypatch)
    content = json.loads(draft(tmp_path))["markdown"]
    run = SimpleNamespace(run_id="init-run")
    runtime = SimpleNamespace(
        spawn=AsyncMock(return_value=(run, False)),
        wait=AsyncMock(
            return_value={
                "runs": [
                    {
                        "run_id": run.run_id,
                        "status": "completed",
                        "summary": content,
                        "current_activity": content,
                        "inspected_files": ["README.md"],
                    }
                ]
            }
        ),
        cancel=AsyncMock(),
    )
    ctx.agent.session.subagent_runtime = runtime
    asyncio.run(init_command.cmd_init(ctx, []))
    assert ctx.outcome == "completed"
    assert all(
        "# AGENTS.md" not in call.args[1]
        for call in ctx.tui.update_command_progress.await_args_list
    )
