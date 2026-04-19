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
    """Explore the project directory structure using tools."""
    cwd = ctx.config.cwd
    registry = ctx.agent.session.tool_registry

    findings = {
        "root_files": [],
        "directories": [],
        "project_files_content": {},
        "sample_files": {},
    }

    # List root directory
    try:
        result = await registry.invoke("list_dir", {"path": str(cwd)}, {})
        if result.success:
            findings["root_files"] = result.output.split("\n") if result.output else []
    except Exception:
        pass

    # Read key project files if they exist
    key_files = [
        "README.md",
        "pyproject.toml",
        "package.json",
        "pubspec.yaml",
        "Cargo.toml",
        "go.mod",
        "Gemfile",
        "composer.json",
        "CMakeLists.txt",
        "build.gradle",
        "pom.xml",
        "setup.py",
        "requirements.txt",
        "Makefile",
        "justfile",
        "tox.ini",
    ]

    for filename in key_files:
        filepath = cwd / filename
        try:
            result = await registry.invoke(
                "read_file", {"path": str(filepath), "limit": 100}, {}
            )
            if result.success:
                findings["project_files_content"][filename] = result.output
        except Exception:
            pass

    # Explore directory structure (first few levels)
    try:
        result = await registry.invoke("glob", {"pattern": "*/", "path": str(cwd)}, {})
        if result.success:
            findings["directories"] = (
                result.output.split("\n")[:20] if result.output else []
            )
    except Exception:
        pass

    # Sample a few source files to understand code patterns
    source_dirs = ["src", "lib", "app", "cmd", "internal", "pkg"]
    for src_dir in source_dirs:
        src_path = cwd / src_dir
        if src_path.exists():
            try:
                # Find files in the source directory
                result = await registry.invoke(
                    "glob", {"pattern": f"{src_dir}/**/*", "path": str(cwd)}, {}
                )
                if result.success:
                    files = [
                        f
                        for f in result.output.split("\n")
                        if f and not f.endswith("/")
                    ][:5]
                    for filepath in files:
                        try:
                            content_result = await registry.invoke(
                                "read_file",
                                {"path": str(cwd / filepath), "limit": 50},
                                {},
                            )
                            if content_result.success:
                                findings["sample_files"][filepath] = (
                                    content_result.output
                                )
                        except Exception:
                            pass
            except Exception:
                pass
            break  # Only process first existing source dir

    return findings


async def _generate_agents_md(ctx: CommandContext, findings: dict) -> str:
    """Generate AGENTS.md content by querying the LLM with findings."""
    from ite.client.response import StreamEventType

    # Build the prompt with findings
    findings_text = []

    if findings["root_files"]:
        findings_text.append("## Root Directory Files")
        findings_text.append("\n".join(findings["root_files"]))

    if findings["project_files_content"]:
        findings_text.append("\n## Key Project Files")
        for filename, content in findings["project_files_content"].items():
            findings_text.append(f"\n### {filename}\n```\n{content[:3000]}\n```")

    if findings["directories"]:
        findings_text.append("\n## Directory Structure")
        findings_text.append("\n".join(findings["directories"]))

    if findings["sample_files"]:
        findings_text.append("\n## Sample Source Files")
        for filepath, content in findings["sample_files"].items():
            findings_text.append(f"\n### {filepath}\n```\n{content[:2000]}\n```")

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

    ctx.tui.start_spinner("Analyzing project")

    try:
        # Phase 1: Explore using tools
        findings = await _explore_project(ctx)

        # Phase 2: Generate content via LLM
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

        ctx.console.print(
            f"[success]Created AGENTS.md[/success] at {agents_md_path}\n"
            f"[dim]Analyzed {len(findings['root_files'])} root files, "
            f"{len(findings['project_files_content'])} project configs, "
            f"{len(findings['sample_files'])} sample files[/dim]"
        )

        ctx.console.print(
            "\n[grey42]Edit this file to refine instructions for the AI.[/grey42]"
        )

        # Show a preview of what was generated
        preview_lines = content.split("\n")[:20]
        ctx.console.print("\n[cyan]Preview:[/cyan]")
        ctx.console.print("[dim]" + "\n".join(preview_lines) + "[/dim]")
        if len(content.split("\n")) > 20:
            ctx.console.print("[dim]...[/dim]")

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
