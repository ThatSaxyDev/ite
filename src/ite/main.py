from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from ite import __version__
from ite.config.config import Config
from ite.config.loader import (
    ensure_workspace_layout,
    load_config,
    save_mcp_server_config,
)


console = Console()


class _HintingMixin:
    _hint_map = {
        "c": "Use `ite` to start.",
        "chat": "Use `ite` to start.",
    }

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except click.NoSuchOption as exc:
            option_name = str(exc.option_name or "").strip()
            hint = self._hint_map.get(option_name)
            if hint:
                rendered = (
                    f"-{option_name}" if len(option_name) == 1 else f"--{option_name}"
                )
                raise click.UsageError(f"No such option '{rendered}'. {hint}") from None
            raise


class IteGroup(_HintingMixin, click.Group):
    pass


def _load_runtime_config(
    *,
    workspace_dir: Path,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> Config:
    ensure_workspace_layout(workspace_dir)
    try:
        config = load_config(cwd=workspace_dir)
    except Exception as exc:
        console.print(f"[error]Configuration error: {exc}[/error]")
        raise click.Abort() from exc

    if api_key:
        config.api_key = api_key
    if base_url:
        config.base_url = base_url
    if model:
        config.model.name = model
    return config


def _run_upgrade() -> None:
    from ite.update_check import detect_install_method

    method = detect_install_method()

    if method == "uv":
        cmd = ["uv", "tool", "upgrade", "ite-agent"]
        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
        result = subprocess.run(cmd)
    elif method == "pipx":
        cmd = ["pipx", "upgrade", "ite-agent"]
        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
        result = subprocess.run(cmd)
    elif sys.platform == "win32":
        cmd = [
            "powershell",
            "-Command",
            "irm https://ite.kiishi.space/install.ps1 | iex",
        ]
        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
        result = subprocess.run(cmd)
    else:
        console.print(
            "[dim]Running: curl -fsSL https://ite.kiishi.space/install.sh | bash[/dim]"
        )
        curl_proc = subprocess.Popen(
            ["curl", "-fsSL", "https://ite.kiishi.space/install.sh"],
            stdout=subprocess.PIPE,
        )
        result = subprocess.run(["bash"], stdin=curl_proc.stdout)
        curl_proc.stdout.close()
        curl_proc.wait()

    if result.returncode != 0:
        raise click.ClickException(
            f"Upgrade exited with code {result.returncode}"
        )


def _run_main_app(
    *,
    workspace_dir: Path,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    resume_last: bool,
) -> None:
    config = _load_runtime_config(
        workspace_dir=workspace_dir,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    if resume_last:
        config.resume_last_session = True

    errors = config.validate()
    if errors:
        setup_missing_errors = {"missing_api_key", "missing_base_url", "missing_model"}
        real_errors = [error for error in errors if error not in setup_missing_errors]
        if real_errors:
            for error in real_errors:
                console.print(f"[error]{error}[/error]")
            raise click.Abort()

    from ite.ui.reup import run_reup

    run_reup(config)


@click.group(cls=IteGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="ite")
@click.option(
    "--cwd",
    "-w",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Current working directory",
)
@click.option("--model", "-m", help="Model name to use")
@click.option("--api-key", "-k", help="API key for the LLM provider")
@click.option("--base-url", "-u", help="Base URL for the OpenAI-compatible API")
@click.option(
    "--resume-last",
    is_flag=True,
    help="Resume the most recent saved session for this workspace on startup.",
)
@click.option("--upgrade", is_flag=True, help="Upgrade iTE to the latest version.")
@click.pass_context
def main(
    ctx: click.Context,
    cwd: Path | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    resume_last: bool,
    upgrade: bool,
) -> None:
    workspace_dir = cwd or Path.cwd()
    ctx.ensure_object(dict)
    ctx.obj["workspace_dir"] = workspace_dir
    ctx.obj["model"] = model
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url
    if ctx.invoked_subcommand is None:
        if upgrade:
            _run_upgrade()
            return
        _run_main_app(
            workspace_dir=workspace_dir,
            model=model,
            api_key=api_key,
            base_url=base_url,
            resume_last=resume_last,
        )


@main.group("mcp")
def mcp_group() -> None:
    """Manage persisted MCP server definitions."""


@mcp_group.command("add", context_settings={"ignore_unknown_options": True})
@click.argument("server")
@click.argument("target", required=False)
@click.argument("target_args", nargs=-1, type=str)
@click.option("--url", "url_value", help="Remote MCP server URL.")
@click.option(
    "--command", "command_value", help="stdio command to launch the MCP server."
)
@click.option("--transport", help="Explicit MCP transport override.")
@click.option("--arg", "command_args", multiple=True, help="Repeatable stdio argument.")
@click.option(
    "--scope",
    type=click.Choice(["global", "workspace", "user", "local", "project"]),
    default="global",
    show_default=True,
)
@click.pass_context
def mcp_add(
    ctx: click.Context,
    server: str,
    target: str | None,
    target_args: tuple[str, ...],
    url_value: str | None,
    command_value: str | None,
    transport: str | None,
    command_args: tuple[str, ...],
    scope: str,
) -> None:
    workspace_dir = Path(ctx.obj.get("workspace_dir") or Path.cwd())
    ensure_workspace_layout(workspace_dir)
    normalized_scope = _normalize_mcp_scope(scope)

    payload: dict[str, Any] = {}
    inferred_args = list(command_args or ())

    if url_value and command_value:
        raise click.ClickException("Use either --url or --command, not both.")

    if url_value:
        payload["url"] = url_value
    elif command_value:
        payload["command"] = command_value
    elif target:
        if target.startswith(("http://", "https://")):
            payload["url"] = target
        else:
            payload["command"] = target
            inferred_args.extend(target_args)
    else:
        raise click.ClickException(
            "Provide a URL or command. Example: `ite mcp add figma https://mcp.figma.com/mcp`"
        )

    if "url" in payload and target_args:
        raise click.ClickException("Unexpected extra arguments after URL target.")
    if "command" in payload and inferred_args:
        payload["args"] = inferred_args
    if transport:
        payload["transport"] = _normalize_mcp_transport(transport)

    try:
        path = save_mcp_server_config(
            cwd=workspace_dir,
            scope=normalized_scope,
            server=server,
            config=payload,
        )
    except Exception as exc:
        raise click.ClickException(
            f"Failed to save MCP server '{server}': {exc}"
        ) from exc
    console.print(
        f"[success]Saved MCP server[/success] [cyan]{server}[/cyan] "
        f"[dim]to {normalized_scope} config ({path})[/dim]"
    )


@main.group("remote")
def remote_group() -> None:
    """Manage the headless runtime daemon."""


@remote_group.command("serve")
@click.option(
    "--workspace",
    "-w",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Workspace directory the runtime serves.",
)
@click.option(
    "--approval-policy",
    type=click.Choice(["deny", "allow", "hold"]),
    default="deny",
    show_default=True,
    help="Policy applied when no interactive client can approve a tool call.",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    show_default=True,
)
@click.pass_context
def remote_serve(
    ctx: click.Context,
    workspace: Path | None,
    approval_policy: str,
    log_level: str,
) -> None:
    """Run the headless runtime and connect it to the cloud relay."""
    import logging

    from ite.runtime.client import ApprovalPolicy as RuntimeApprovalPolicy
    from ite.runtime.daemon import run_daemon

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    workspace_dir = Path(
        workspace or ctx.obj.get("workspace_dir") or Path.cwd()
    )
    config = _load_runtime_config(
        workspace_dir=workspace_dir,
        model=ctx.obj.get("model"),
        api_key=ctx.obj.get("api_key"),
        base_url=ctx.obj.get("base_url"),
    )
    errors = config.validate()
    if errors:
        for error in errors:
            console.print(f"[error]{error}[/error]")
        raise click.Abort()

    raise SystemExit(
        run_daemon(
            config,
            approval_policy=RuntimeApprovalPolicy(approval_policy),
        )
    )


def _normalize_mcp_transport(value: str) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "http": "streamable_http",
        "https": "streamable_http",
        "streamable-http": "streamable_http",
        "streamable_http": "streamable_http",
        "stdio": "stdio",
        "sse": "sse",
        "ws": "ws",
        "websocket": "ws",
    }
    return aliases.get(normalized, normalized)


def _normalize_mcp_scope(value: str) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "user": "global",
        "global": "global",
        "workspace": "workspace",
        "local": "workspace",
        "project": "workspace",
    }
    return aliases.get(normalized, normalized)


if __name__ == "__main__":
    main()
