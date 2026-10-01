"""Evidence-based project initialization and live /init command progress."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import tempfile
from pathlib import Path

from ite.commands import Command, CommandContext, CommandRegistry
from ite.config.loader import (
    AGENTS_MD_FILE,
    AGENTS_OVERRIDE_FILE,
    _get_agents_md_files,
    _merge_agents_md_instructions,
)


async def _progress(ctx: CommandContext, message: str) -> None:
    update = getattr(ctx.tui, "update_command_progress", None)
    if update is not None:
        await update("/init", message)
    else:
        ctx.tui.change_spinner(message)


async def _run_init_investigator(
    ctx: CommandContext, *, deadline: float, feedback: str = ""
) -> str:
    """Use the exact specialist, real activity, and one deadline across attempts."""
    if ctx.agent is None or ctx.agent.session is None:
        raise RuntimeError("No active session.")
    runtime = ctx.agent.session.subagent_runtime
    if runtime is None:
        raise RuntimeError("Subagent runtime is unavailable.")
    goal = (
        f"Generate AGENTS.md for the workspace at {ctx.config.cwd}. "
        f"The combined instruction budget is {ctx.config.agents_max_bytes} bytes, "
        "including inherited/global instructions and framing. Read applicable guidance "
        "and leave room for it. Return the complete AGENTS.md Markdown document."
    )
    if feedback:
        goal = (
            f"INIT_DRAFT_REVISION\nDo not repeat investigation. Combined instruction "
            f"budget: {ctx.config.agents_max_bytes} bytes.\n"
            f"Previously read files: {', '.join(ctx.evidence_files)}\n{feedback}"
        )
        deadline = min(deadline, asyncio.get_running_loop().time() + 120)
    run = None
    reused = False
    finished = False
    try:
        async with asyncio.timeout_at(deadline):
            run, reused = await runtime.spawn(
                subagent="init_investigator",
                goal=goal,
                parent_tool_call_id=f"init_{id(asyncio.current_task())}",
            )
            last_activity = None
            while True:
                data = await runtime.wait(
                    run_ids=[run.run_id],
                    return_when="all_completed",
                    timeout_seconds=min(
                        1, max(0, deadline - asyncio.get_running_loop().time())
                    ),
                )
                current = next(
                    (
                        item
                        for item in data.get("runs", [])
                        if item.get("run_id") == run.run_id
                    ),
                    None,
                )
                if current is None:
                    raise RuntimeError("The investigator run could not be found.")
                for path in current.get("inspected_files", []):
                    if path not in ctx.evidence_files:
                        ctx.evidence_files.append(path)
                status = current.get("status")
                activity = str(
                    current.get("current_activity") or "Investigating repository"
                )
                if status in {"queued", "running"} and activity != last_activity:
                    await _progress(ctx, activity)
                    last_activity = activity
                if status in {"queued", "running"}:
                    continue
                finished = True
                if status == "timeout":
                    raise TimeoutError("The investigator reached its time limit.")
                if status != "completed":
                    raise RuntimeError(
                        str(current.get("error") or f"Investigator {status}.")
                    )
                summary = current.get("summary")
                if not isinstance(summary, str) or not summary.strip():
                    raise ValueError("The investigator returned no draft.")
                return summary.strip()
    finally:
        if run is not None and not reused and not finished:
            await runtime.cancel(run_ids=[run.run_id])


def _unwrap_fence(content: str) -> str:
    """Remove a single outer fence without cutting nested Markdown fences."""
    text = content.strip()
    lines = text.splitlines()
    if lines and re.fullmatch(r"(`{3,}|~{3,})(?:json|markdown|md)?\s*", lines[0]):
        fence = re.match(r"[`~]+", lines[0])
        assert fence is not None
        if len(lines) > 2 and lines[-1].strip() == fence.group():
            return "\n".join(lines[1:-1]).strip()
    return text


def _workspace_path(cwd: Path, value: object, *, file: bool = False) -> Path:
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        raise ValueError(f"Evidence path must be workspace-relative: {value!r}")
    path = (cwd / value).resolve()
    if not path.is_relative_to(cwd.resolve()) or not path.exists():
        raise ValueError(f"Evidence path does not exist in this workspace: {value}")
    if file and not path.is_file():
        raise ValueError(f"Evidence source must be a file: {value}")
    return path


def _command_supported(command: str, source: Path) -> bool:
    if source.stat().st_size > 1024 * 1024:
        return False
    text = source.read_text(encoding="utf-8")
    if " ".join(command.split()) in " ".join(text.split()):
        return True
    if source.name != "package.json":
        return False
    manifest = json.loads(text)
    if not isinstance(manifest, dict):
        return False
    words = shlex.split(command)
    if not words or words[0] not in {"npm", "pnpm", "yarn", "bun"}:
        return False
    name = (
        words[2]
        if len(words) == 3 and words[1] == "run"
        else (words[1] if len(words) == 2 else "")
    )
    scripts = manifest.get("scripts", {})
    return isinstance(scripts, dict) and name in scripts


def _markdown_draft(response: str, cwd: Path, observed: list[str]) -> dict:
    """Validate natural Markdown against evidence captured from successful reads."""
    text = _unwrap_fence(response)
    wrapper = re.search(r"(?m)^(`{3,}|~{3,})(?:markdown|md)\s*\n", text)
    if wrapper is not None:
        text = _unwrap_fence(text[wrapper.start() :])
    heading = re.search(r"(?m)^# AGENTS\.md\s*$", text)
    if heading is None:
        raise ValueError("The investigator did not return an AGENTS.md document.")
    text = text[heading.start() :].strip()
    if not observed:
        raise ValueError(
            "No successful repository file reads were recorded for this draft."
        )
    sources = [(name, _workspace_path(cwd, name, file=True)) for name in observed]
    references: list[str] = []
    commands: list[dict[str, str]] = []
    executables = {
        "python",
        "python3",
        "pytest",
        "ruff",
        "mypy",
        "uv",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "bun",
        "cargo",
        "go",
        "make",
        "cmake",
        "pip",
        "pipx",
        "docker",
        "git",
    }
    for match in re.finditer(r"(?<!`)`([^`\n]+)`(?!`)", text):
        value = match.group(1).strip().removeprefix("$ ")
        paragraph_start = text.rfind("\n\n", 0, match.start()) + 2
        paragraph_end = text.find("\n\n", match.end())
        paragraph = text[
            paragraph_start : paragraph_end if paragraph_end != -1 else len(text)
        ]
        hypothetical = bool(
            re.search(
                r"\b(?:if you|when adding|if new|if .*introduced|do not assume|without adding|rather than assuming)\b",
                paragraph,
                re.IGNORECASE,
            )
        )
        if hypothetical or any(character in value for character in "<>"):
            continue
        if value == AGENTS_MD_FILE:
            continue  # This is the output file, which may not exist yet.
        words = shlex.split(value)
        if words and words[0] in executables:
            source = next(
                (name for name, path in sources if _command_supported(value, path)),
                None,
            )
            if source is None:
                raise ValueError(
                    f"Command is not supported by inspected files: {value}"
                )
            commands.append({"command": value, "source": source})
        elif not any(character in value for character in " *<>~") and (
            value.startswith(("src/", "tests/", "docs/", "scripts/", ".github/"))
            or re.search(
                r"\.(?:py|json|toml|md|yaml|yml|js|ts|tsx|rs|go|sh)(?::\d+(?:-\d+)?)?$",
                value,
            )
        ):
            references.append(re.sub(r":\d+(?:-\d+)?$", "", value))
    return {
        "markdown": text,
        "inspected_files": observed,
        "referenced_paths": references,
        "commands": commands,
    }


def _validate_draft(
    response: str, cwd: Path, *, observed_files: list[str] | None = None
) -> tuple[str, int]:
    try:
        draft = json.loads(_unwrap_fence(response))
    except json.JSONDecodeError:
        draft = _markdown_draft(response, cwd, observed_files or [])
    if not isinstance(draft, dict) or not isinstance(draft.get("markdown"), str):
        raise TypeError("The draft has no markdown field.")
    content = _unwrap_fence(draft["markdown"])
    if not content.startswith("# AGENTS.md\n"):
        raise ValueError("The document must start with # AGENTS.md.")
    for section in ("Project Overview", "Architecture", "Development Guidelines"):
        if not re.search(rf"^## {section}\s*$", content, re.MULTILINE):
            raise ValueError(f"The draft is missing the {section} section.")
    if re.search(r"\[truncated|\.\.\. \[truncated", content, re.IGNORECASE):
        raise ValueError("The draft is truncated; revise complete sections instead.")
    # Track fence lengths so nested code samples are preserved and checked.
    open_fence = None
    for line in content.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            fence = match.group(1)
            if open_fence is None:
                open_fence = fence
            elif fence[0] == open_fence[0] and len(fence) >= len(open_fence):
                open_fence = None
    if open_fence:
        raise ValueError("The draft contains an unclosed code fence.")
    inspected = draft.get("inspected_files")
    references = draft.get("referenced_paths")
    commands = draft.get("commands")
    if not isinstance(inspected, list) or not inspected:
        raise ValueError("The draft must include inspected_files evidence.")
    for item in inspected:
        _workspace_path(cwd, item, file=True)
        if observed_files is not None and item not in observed_files:
            raise ValueError(
                f"No successful read was recorded for evidence file: {item}"
            )
    if not isinstance(references, list) or not isinstance(commands, list):
        raise TypeError("The draft must include referenced_paths and commands lists.")
    for item in references:
        _workspace_path(cwd, item)
    for item in commands:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("command"), str)
            or not item["command"].strip()
        ):
            raise ValueError("Each command needs a command string and source file.")
        source = _workspace_path(cwd, item.get("source"), file=True)
        if str(item["source"]) not in inspected:
            raise ValueError(
                f"Command source was not listed as inspected: {source.name}"
            )
        command = item["command"].strip()
        if not _command_supported(command, source):
            raise ValueError(f"Command is not defined in its cited source: {command}")
    return content.rstrip() + "\n", len(set(inspected))


def _write_agents_md(path: Path, content: str, original: bytes | None) -> None:
    """Publish a complete file; exclusive creation protects concurrent writers."""
    if path.is_symlink():
        raise ValueError("AGENTS.md is a symbolic link; edit its target explicitly.")
    if original is not None and (not path.exists() or path.read_bytes() != original):
        raise ValueError(
            "AGENTS.md changed during investigation. Run /init again to review the latest file."
        )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".agents-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if original is None:
            os.link(temporary, path)  # Fails if any file appeared during investigation.
        else:
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def cmd_init(ctx: CommandContext, args: list[str]) -> None:
    """Investigate, validate, safely save, and activate project instructions."""
    ctx.outcome = "failed"
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("No active session. Start iTE first.")
        return
    begin = getattr(ctx.tui, "begin_command_progress", None)
    if begin is not None:
        await begin("/init", "Inspecting project guidance")
    else:
        ctx.tui.start_spinner("/init", "Inspecting project guidance")
    message = ""
    saved = False
    response = ""
    recoverable_response = ""
    session = ctx.agent.session
    cwd = ctx.config.cwd
    path = cwd / AGENTS_MD_FILE
    try:
        if any(arg not in {"--force", "-f"} for arg in args):
            raise ValueError("Usage: /init [--force]")
        if path.exists() and not ({"--force", "-f"} & set(args)):
            ctx.outcome = "completed"
            message = "AGENTS.md already exists. Use /init --force to regenerate it."
            return
        if (cwd / AGENTS_OVERRIDE_FILE).exists():
            raise ValueError(
                "AGENTS.override.md is active here. Update that file or remove the override before generating AGENTS.md."
            )
        if path.is_symlink():
            raise ValueError(
                "AGENTS.md is a symbolic link; edit its target explicitly."
            )
        original = path.read_bytes() if path.exists() else None
        previous = _merge_agents_md_instructions(
            _get_agents_md_files(cwd), max_bytes=ctx.config.agents_max_bytes
        )
        deadline = asyncio.get_running_loop().time() + ctx.config.init_timeout_seconds
        feedback = ""
        for attempt in range(2):
            response = await _run_init_investigator(
                ctx, deadline=deadline, feedback=feedback
            )
            if "# AGENTS.md" in response:
                recoverable_response = response
            await _progress(ctx, "Checking draft and repository references")
            try:
                content, inspected_count = _validate_draft(
                    response, cwd, observed_files=ctx.evidence_files
                )
                files = [
                    (p, text) for p, text in _get_agents_md_files(cwd) if p != path
                ]
                files.append((path, content))
                merged = _merge_agents_md_instructions(
                    files, max_bytes=ctx.config.agents_max_bytes, strict=True
                )
                break
            except (ValueError, TypeError) as exc:
                if attempt:
                    raise
                feedback = f"{exc}\nPrevious response:\n{response}"
                await _progress(ctx, "Revising draft after validation")
        if ctx.agent.session is not session:
            raise RuntimeError(
                "The active session changed. Run /init in the current session."
            )
        manager = session.context_manager
        if manager is None:
            raise RuntimeError("The active session has no instruction context.")
        await _progress(ctx, "Saving AGENTS.md and refreshing instructions")
        _write_agents_md(path, content, original)
        saved = True
        manager.add_system_message(
            f"[AGENTS.md Instructions - Refreshed]\nThese instructions supersede earlier "
            f"AGENTS.md content for this workspace.\n\n{merged}"
        )
        # Preserve explicitly configured developer instructions alongside the refresh.
        if ctx.config.developer_instructions in (None, previous):
            ctx.config.developer_instructions = merged
        ctx.outcome = "completed"
        verb = "Updated" if original is not None else "Created"
        message = (
            f"{verb} AGENTS.md\n"
            f"{inspected_count} {'file' if inspected_count == 1 else 'files'} checked · "
            f"{len(content.encode('utf-8')) / 1024:.1f} KiB\n"
            f"Active in this chat\n{path}"
        )
    except asyncio.CancelledError:
        ctx.outcome = "cancelled"
        message = "Initialization cancelled. No generated draft was saved."
        raise
    except TimeoutError:
        message = "Initialization timed out. No generated draft was saved. Increase init_timeout_seconds in .ite/config.toml and retry."
    except (ValueError, TypeError, RuntimeError, OSError) as exc:
        message = (
            f"AGENTS.md was saved, but its instructions could not be refreshed: {exc}"
            if saved
            else f"Initialization failed: {exc}"
        )
    finally:
        if ctx.outcome != "completed" and not saved and recoverable_response:
            try:
                drafts = cwd / ".ite" / "init-drafts"
                drafts.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=drafts,
                    prefix="init-",
                    suffix=".txt",
                    delete=False,
                ) as handle:
                    handle.write(recoverable_response)
                    message += f"\nUnapplied draft saved for review: {handle.name}"
            except OSError:
                message += "\nThe unapplied draft could not be saved for review."
        ctx.result = message
        finish = getattr(ctx.tui, "finish_command_progress", None)
        if finish is not None:
            await finish("/init", message, status=ctx.outcome)
        else:
            ctx.tui.stop_spinner()
            ctx.console.print(message, markup=False)


def register(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="/init",
            description="Investigate the project and generate grounded AGENTS.md instructions",
            handler=cmd_init,
        )
    )
