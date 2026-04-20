"""Project initialization command: /init — analyzes project using tools and creates AGENTS.md."""

from pathlib import Path

from ite.commands import CommandContext
from ite.config.loader import AGENTS_MD_FILE

INIT_ANALYSIS_PROMPT = """You are analyzing a codebase to create an AGENTS.md file.

AGENTS.md is a project instructions file that tells AI agents how to work with this codebase. It should be concrete and grounded, not generic.

Use the tool results below to understand the project, then generate AGENTS.md content.

## TASK

Generate an AGENTS.md file based on the project analysis. Include:

1. **Project Overview**: What this project does (based on README, package.json, pyproject.toml, etc.)
2. **Architecture**: Directory structure, key modules/packages, tech stack
3. **Development Guidelines**:
   - Build/test commands (specific, not generic)
   - Code style/conventions visible in the existing code
   - Important patterns used
4. **Tool Preferences**:
   - Which tools to use for which file types
   - Any project-specific verification steps

## Rules:
- Be specific and grounded. Don't guess.
- If you don't know something, don't include it.
- Focus on patterns that differ from defaults.
- Include actual file names, commands, and patterns discovered.

## Output Format

Respond with ONLY the AGENTS.md content, starting with a level-1 heading (# Project Name). No explanation, no markdown wrapping, just the AGENTS.md content."""


async def _explore_project(ctx: CommandContext) -> dict:
    """Explore the project directory structure using direct filesystem calls."""
    import os
    cwd = ctx.config.cwd

    findings = {
        "root_files": [],
        "directories": [],
        "project_files_content": {},
        "sample_files": {},
    }

    # List root directory (fast sync operation)
    try:
        entries = os.listdir(cwd)
        findings["root_files"] = sorted(entries)
    except Exception as e:
        findings["root_files"] = [f"Error: {e}"]

    # Read key project files (fast sync operation)
    key_files = [
        "README.md", "pyproject.toml", "package.json", "pubspec.yaml",
        "Cargo.toml", "go.mod", "Gemfile", "composer.json", "CMakeLists.txt",
        "build.gradle", "pom.xml", "setup.py", "requirements.txt",
        "Makefile", "justfile", "tox.ini",
    ]

    for filename in key_files:
        filepath = cwd / filename
        try:
            if filepath.is_file():
                content = filepath.read_text(encoding="utf-8", errors="replace")
                findings["project_files_content"][filename] = content[:3000]
        except Exception:
            pass

    # Find directories (fast sync operation)
    try:
        dirs = [d for d in os.listdir(cwd) if (cwd / d).is_dir() and not d.startswith(".")]
        findings["directories"] = sorted(dirs)[:20]
    except Exception:
        pass

    # Sample source files from common directories (fast sync operation)
    source_dirs = ["src", "lib", "app", "cmd", "internal", "pkg"]
    for src_dir in source_dirs:
        src_path = cwd / src_dir
        if src_path.is_dir():
            try:
                for root, _dirs, files in os.walk(src_path):
                    for filename in files:
                        filepath = Path(root) / filename
                        if filepath.stat().st_size < 50000:
                            try:
                                content = filepath.read_text(encoding="utf-8", errors="replace")
                                rel_path = str(filepath.relative_to(cwd))
                                findings["sample_files"][rel_path] = content[:2000]
                                if len(findings["sample_files"]) >= 5:
                                    break
                            except Exception:
                                pass
                    if len(findings["sample_files"]) >= 5:
                        break
            except Exception:
                pass
            break

    return findings


async def _generate_agents_md(ctx: CommandContext, findings: dict) -> str:
    """Generate AGENTS.md content by querying the LLM with findings."""
    from ite.client.response import StreamEventType

    # Build the prompt with findings
    findings_text = []

    if findings["root_files"]:
        findings_text.append("## Root Directory Files\n```")
        findings_text.append("\n".join(findings["root_files"][::20]))
        findings_text.append("```")

    if findings["project_files_content"]:
        for filename, content in findings["project_files_content"].items():
            findings_text.append(f"\n## {filename}\n```")
            findings_text.append(content[:2000])
            findings_text.append("```")

    if findings["directories"]:
        findings_text.append("\n## Directory Structure")
        findings_text.append("\n".join(findings["directories"]))

    if findings["sample_files"]:
        for filepath, content in findings["sample_files"].items():
            findings_text.append(f"\n## {filepath}\n```")
            findings_text.append(content[:1500])
            findings_text.append("```")

    full_prompt = (
        f"{INIT_ANALYSIS_PROMPT}\n\n---\n\n## Project Analysis Results\n\n"
        + "\n".join(findings_text)
    )

    # Make the LLM call
    messages = [{"role": "user", "content": full_prompt}]

    response_parts = []
    async for event in ctx.agent.session.client.chat_completion(
        messages, tools=None, stream=True
    ):
        if event.type == StreamEventType.TEXT_DELTA and event.text_delta:
            if event.text_delta.content:
                # Stream the content directly to the card
                ctx.tui.stream_content(event.text_delta.content)
                response_parts.append(event.text_delta.content)

    return "".join(response_parts).strip()


async def cmd_init(ctx: CommandContext, args: list[str]) -> None:
    """
    Initialize a project with grounded AGENTS.md analysis.

    Usage: /init [--force]

    Analyzes the current workspace using tools, then uses the LLM to generate
    a grounded AGENTS.md file with:
    - Detected architecture and tech stack
    - Actual build/test commands
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

    ctx.tui.start_spinner("/init", "Analyzing project")

    try:
        # Phase 1: Explore using tools (fast synchronous fs operations)
        findings = await _explore_project(ctx)

        # Phase 2: Generate content via LLM (this streams content live)
        ctx.tui.change_spinner("Generating AGENTS.md")
        content = await _generate_agents_md(ctx, findings)

        # Phase 3: Write the file
        if not content:
            ctx.console.print("[error]Failed to generate AGENTS.md content.[/error]")
            return

        # Ensure proper markdown format
        if not content.startswith("#"):
            content = f"# {cwd.name}\n\n{content}"

        agents_md_path.write_text(content + "\n", encoding="utf-8")

        # Post completion card
        ctx.tui.post_success_card(
            "AGENTS.md Created",
            f"AGENTS.md has been created at {agents_md_path}",
            f"Analyzed {len(findings['root_files'])} root files, "
            f"{len(findings['project_files_content'])} configs, "
            f"{len(findings['sample_files'])} samples"
        )

    except Exception as e:
        ctx.console.print(f"[error]Error during initialization:[/error] {e}")
        raise
    finally:
        ctx.tui.stop_spinner()


def register(registry):
    from ite.commands import Command

    registry.register(
        Command(
            name="/init",
            description="Initialize project with AGENTS.md (analyzes codebase, generates grounded instructions)",
            handler=cmd_init,
        )
    )
