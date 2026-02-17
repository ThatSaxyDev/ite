"""First-run setup wizard for ITE."""

from ite.config.loader import save_system_config
from ite.config.config import Config
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich import box


def _gradient_logo() -> Text:
    """Cyan-to-green gradient ITE logo."""
    logo_lines = [
        "    ██╗ ██████╗ ███████╗",
        "    ╚═╝ ╚═██╔═╝ ██╔═══╝",
        "    ██╗   ██║   ████╗  ",
        "    ██║   ██║   ██╔═╝  ",
        "    ██║   ██║   ███████╗",
        "    ╚═╝   ╚═╝   ╚══════╝",
    ]
    text = "\n".join(logo_lines)

    start_r, start_g, start_b = 0, 200, 255
    end_r, end_g, end_b = 30, 80, 48

    rich_text = Text()
    total = max(len(text) - 1, 1)

    for i, char in enumerate(text):
        t = i / total
        r = int(start_r + (end_r - start_r) * t)
        g = int(start_g + (end_g - start_g) * t)
        b = int(start_b + (end_b - start_b) * t)
        rich_text.append(char, style=f"bold #{r:02x}{g:02x}{b:02x}")

    return rich_text


def run_setup_wizard(console: Console, config: Config) -> Config:
    """Interactive setup wizard. Returns updated config with credentials."""

    content = Group(
        Text(),
        _gradient_logo(),
        Text(),
        Rule(style="grey35"),
        Text(),
        Text("  Interactive Terminal Environment", style="bold bright_white"),
        Text(),
        Text(
            "  Connect any OpenAI-compatible API to get started.",
            style="grey70",
        ),
        Text(),
    )

    console.print()
    console.print(
        Panel(
            content,
            border_style="grey35",
            box=box.HEAVY,
            padding=(0, 3),
        )
    )

    # ── Base URL ──
    console.print()
    console.print("  [grey70]Provider base URLs:[/grey70]")
    console.print(
        "    [grey50]OpenRouter[/grey50]  [grey70]→  https://openrouter.ai/api/v1[/grey70]"
    )
    console.print(
        "    [grey50]DeepSeek[/grey50]   [grey70]→  https://api.deepseek.com[/grey70]"
    )
    console.print(
        "    [grey50]OpenAI[/grey50]     [grey70]→  https://api.openai.com/v1[/grey70]"
    )
    console.print(
        "    [grey50]Ollama[/grey50]     [grey70]→  http://localhost:11434/v1[/grey70]"
    )
    console.print()

    base_url = console.input("  [bold cyan]❯[/bold cyan] Base URL: ").strip()

    if not base_url:
        base_url = "https://openrouter.ai/api/v1"
        console.print(f"    [grey70]→ {base_url}[/grey70]")

    # ── API Key ──
    console.print()
    api_key = console.input("  [bold cyan]❯[/bold cyan] API key: ").strip()

    if not api_key:
        console.print()
        console.print("  [bold red]✗[/bold red] API key is required.")
        raise SystemExit(1)

    # ── Model ──
    console.print()
    console.print("  [grey70]Model name as listed by your provider[/grey70]")
    model_name = console.input("  [bold cyan]❯[/bold cyan] Model: ").strip()

    if not model_name:
        model_name = config.model.name
        console.print(f"    [grey70]→ {model_name}[/grey70]")

    # ── Save ──
    config_path = save_system_config(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )

    console.print()
    console.print(
        f"  [bold green]✓[/bold green] Saved to [grey70]{config_path}[/grey70]"
    )
    console.print(
        "  [grey70]Override anytime with --model, --api-key, --base-url[/grey70]"
    )
    console.print()

    # Update the config object in-place
    config.api_key = api_key
    config.base_url = base_url
    config.model.name = model_name

    return config
