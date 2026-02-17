"""First-run setup wizard for ITE."""

from config.loader import save_system_config
from config.config import Config
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box


def run_setup_wizard(console: Console, config: Config) -> Config:
    """Interactive setup wizard. Returns updated config with credentials."""

    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold bright_white]Welcome to ITE![/bold bright_white]\n\n"
                "[dim]Let's get you connected to an LLM. ITE works with any\n"
                "OpenAI-compatible API — OpenRouter, DeepSeek, OpenAI,\n"
                "Anthropic (via proxy), local Ollama, and more.[/dim]"
            ),
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    console.print()

    # ── Base URL ──
    console.print(
        "[dim]  Paste the base URL of your provider's OpenAI-compatible endpoint.[/dim]"
    )
    console.print(
        "[dim]  Examples: https://openrouter.ai/api/v1 · https://api.deepseek.com · http://localhost:11434/v1[/dim]"
    )
    base_url = console.input("\n  [cyan bold]? Base URL:[/cyan bold] ").strip()

    if not base_url:
        base_url = "https://openrouter.ai/api/v1"
        console.print(f"  [dim]Using default: {base_url}[/dim]")

    # ── API Key ──
    console.print()
    console.print(
        "[dim]  Enter the API key for your provider.[/dim]"
    )
    api_key = console.input("  [cyan bold]? API key:[/cyan bold] ").strip()

    if not api_key:
        console.print("  [error]API key is required.[/error]")
        raise SystemExit(1)

    # ── Model ──
    console.print()
    console.print(
        "[dim]  Enter a model name supported by your provider.[/dim]"
    )
    console.print(
        "[dim]  Examples: deepseek/deepseek-chat · gpt-4o · claude-3.7-sonnet[/dim]"
    )
    model_name = console.input("\n  [cyan bold]? Model name:[/cyan bold] ").strip()

    if not model_name:
        model_name = config.model.name
        console.print(f"  [dim]Using default: {model_name}[/dim]")

    # ── Save ──
    config_path = save_system_config(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )

    console.print()
    console.print(f"  [success]✅ Config saved to[/success] [dim]{config_path}[/dim]")
    console.print(
        "  [dim]You can edit this file anytime, or override with CLI flags.[/dim]"
    )
    console.print()

    # Update the config object in-place
    config.api_key = api_key
    config.base_url = base_url
    config.model.name = model_name

    return config
