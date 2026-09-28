"""Project initialization command: /init — analyzes project using init_investigator subagent and creates AGENTS.md."""

import asyncio
import json
from pathlib import Path

from ite.commands import CommandContext
from ite.config.loader import AGENTS_MD_FILE


async def _run_init_investigator(
    ctx: CommandContext,
) -> str:
    """Spawn init_investigator via subagent tools and return the AGENTS.md content."""
    from ite.tools.base import ToolInvocation
    from ite.tools.builtin.subagent_runtime_tools import (
        SpawnSubagentTool,
        WaitSubagentTool,
    )

    subagent_runtime = ctx.agent.session.subagent_runtime
    if subagent_runtime is None:
        raise RuntimeError("Subagent runtime not available")

    cwd = ctx.config.cwd
    goal = f"Write AGENTS.md for project at {cwd}"

    # Create tools (pass config required by Tool base class)
    spawn_tool = SpawnSubagentTool(ctx.config)
    spawn_tool.set_runtime(subagent_runtime)

    wait_tool = WaitSubagentTool(ctx.config)
    wait_tool.set_runtime(subagent_runtime)

    # Spawn the investigator
    spawn_invocation = ToolInvocation(
        params={"subagent": "init_investigator", "goal": goal},
        cwd=cwd,
        call_id=f"init_spawn_{id(asyncio.current_task())}",
    )

    ctx.tui.change_spinner("Scanning project structure...")
    spawn_result = await spawn_tool.execute(spawn_invocation)
    if not spawn_result.success:
        raise RuntimeError(f"Failed to spawn investigator: {spawn_result.message}")

    # Extract run_id from result
    try:
        spawn_data = json.loads(spawn_result.output or "{}")
        run = spawn_data.get("run", {})
        run_id = run.get("run_id")
        if not run_id:
            raise ValueError("No run_id in spawn result")
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise RuntimeError(f"Invalid spawn result: {e}")

    # Poll for completion with spinner updates
    start_time = asyncio.get_running_loop().time()
    timeout = 180  # 3 minutes

    while True:
        elapsed = asyncio.get_running_loop().time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Investigation timed out after {timeout}s")

        # Update spinner with progress
        if elapsed < 5:
            ctx.tui.change_spinner("Scanning project structure...")
        elif elapsed < 12:
            ctx.tui.change_spinner("Analyzing tech stack...")
        elif elapsed < 20:
            ctx.tui.change_spinner("Mapping entry points...")
        elif elapsed < 28:
            ctx.tui.change_spinner("Discovering code patterns...")
        elif elapsed < 36:
            ctx.tui.change_spinner("Extracting conventions...")
        elif elapsed < 44:
            ctx.tui.change_spinner("Resolving dependencies...")
        elif elapsed < 52:
            ctx.tui.change_spinner("Synthesizing context...")
        elif elapsed < 60:
            ctx.tui.change_spinner("Encoding guidelines...")
        else:
            ctx.tui.change_spinner("Generating AGENTS.md...")

        # Wait for completion (short poll)
        wait_invocation = ToolInvocation(
            params={
                "run_ids": [run_id],
                "return_when": "all_completed",
                "timeout_seconds": 2,
            },
            cwd=cwd,
            call_id=f"init_wait_{id(asyncio.current_task())}",
        )

        wait_result = await wait_tool.execute(wait_invocation)
        if not wait_result.success:
            # Wait operation itself failed
            raise RuntimeError(f"Wait failed: {wait_result.message}")

        # Parse wait result
        try:
            wait_data = json.loads(wait_result.output or "{}")
            completed_ids = wait_data.get("completed_run_ids", [])

            # If no runs completed yet, continue polling
            if not completed_ids:
                await asyncio.sleep(0.5)
                continue

            runs = wait_data.get("runs", [])
            # Find the completed run
            run_data = None
            for run in runs:
                if run.get("run_id") in completed_ids:
                    run_data = run
                    break

            if not run_data:
                raise ValueError("No matching completed run found")

            summary = run_data.get("summary", "")
            status = run_data.get("status", "unknown")

            if status == "timeout":
                raise TimeoutError("Subagent timed out")
            if status == "cancelled":
                raise RuntimeError("Subagent was cancelled")
            if status == "failed":
                error = run_data.get("error", "Unknown error")
                raise RuntimeError(f"Subagent failed: {error}")
            if status != "completed":
                # Shouldn't happen if in completed_run_ids, but handle anyway
                raise RuntimeError(f"Subagent ended with unexpected status: {status}")

            # The init_investigator returns AGENTS.md content directly
            if not summary:
                raise RuntimeError("Subagent returned empty response")

            return summary.strip()

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            raise RuntimeError(f"Invalid wait result: {e}")


def _extract_agents_md(content: str) -> str:
    """Extract AGENTS.md content from subagent response."""
    content = content.strip()

    # If it already starts with a header, use it as-is
    if content.startswith("# AGENTS.md") or content.startswith("# "):
        return content

    # Try to extract content from markdown code blocks
    if "```markdown" in content:
        parts = content.split("```markdown")
        if len(parts) > 1:
            content = parts[1].split("```")[0].strip()
    elif "```" in content:
        # Extract first code block if it looks like AGENTS.md
        blocks = content.split("```")
        for i in range(1, len(blocks), 2):
            block = blocks[i].strip()
            if block.startswith("# AGENTS.md") or block.startswith("# "):
                # Remove language identifier if present
                lines = block.splitlines()
                if lines and not lines[0].startswith("#"):
                    content = "\n".join(lines[1:]).strip()
                else:
                    content = block
                break

    return content


def _truncate_agents_md(content: str, max_bytes: int = 32 * 1024 - 500) -> str:
    """Truncate AGENTS.md to fit within size limit, preserving later sections."""
    content_bytes = content.encode("utf-8")
    if len(content_bytes) <= max_bytes:
        return content

    truncated = content_bytes[:max_bytes].decode("utf-8", errors="ignore")

    # Find last newline to avoid cutting mid-line
    if "\n" in truncated:
        truncated = truncated[: truncated.rfind("\n")]

    return f"{truncated}\n\n... [truncated for 32KB limit]"


async def cmd_init(ctx: CommandContext, args: list[str]) -> None:
    """
    Initialize a project with grounded AGENTS.md analysis using init_investigator.

    Usage: /init [--force]

    Spawns init_investigator to quickly scan the codebase (max 10 turns, 3 min),
    then generates a focused AGENTS.md with:
    - Detected architecture and tech stack
    - Actual build/test commands found
    - Code style patterns from existing code
    - Specific file/directory structure
    """
    if not ctx.agent or not ctx.agent.session:
        ctx.console.print("[error]No active session. Start iTE first.[/error]")
        return

    cwd = ctx.config.cwd
    force = "--force" in args or "-f" in args

    agents_md_path = cwd / AGENTS_MD_FILE

    # Check if AGENTS.md already exists
    if agents_md_path.exists() and not force:
        ctx.console.print(
            f"[warning]AGENTS.md already exists at {agents_md_path}[/warning]\n"
            f"[dim]Use [bold]/init --force[/bold] to overwrite.[/dim]"
        )
        return

    ctx.tui.start_spinner("/init", "Spawning codebase investigator")

    try:
        # Phase 1: Run init_investigator subagent to generate AGENTS.md content
        content = await _run_init_investigator(ctx)

        if not content:
            ctx.console.print("[error]Failed to generate AGENTS.md content.[/error]")
            return

        ctx.tui.change_spinner("Finalizing...")

        # Phase 2: Extract and clean content
        content = _extract_agents_md(content)

        # Phase 3: Ensure proper format
        if not content.startswith("#"):
            content = f"# {cwd.name}\n\n{content}"

        # Phase 4: Respect size limit
        content = _truncate_agents_md(content)

        # Phase 5: Write file
        agents_md_path.write_text(content + "\n", encoding="utf-8")

        ctx.tui.post_success_card(
            "AGENTS.md Created",
            f"AGENTS.md has been created at {agents_md_path}",
            f"Size: {len(content.encode('utf-8')) / 1024:.1f}KB",
        )

    except TimeoutError:
        ctx.console.print(
            "[error]Investigation timed out.[/error]\n"
            "[dim]The codebase may be too large or complex for fast-scanning.[/dim]\n"
            "[dim]Try running with a more specific subdirectory or create AGENTS.md manually.[/dim]"
        )
    except RuntimeError as e:
        ctx.console.print(f"[error]Subagent error:[/error] {e}")
        return
    except Exception as e:
        ctx.console.print(f"[error]Error during initialization:[/error] {e}")
        import traceback

        ctx.console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise
    finally:
        ctx.tui.stop_spinner()


def register(registry):
    from ite.commands import Command

    registry.register(
        Command(
            name="/init",
            description="Initialize project with AGENTS.md using fast codebase investigation",
            handler=cmd_init,
        )
    )
