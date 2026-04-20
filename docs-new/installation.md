# Installation

**Prerequisites:**

- Python 3.11+
- macOS, Linux, or Windows
- A terminal emulator

**Supported terminals:**

- **macOS:** Terminal.app, iTerm2, Ghostty, Kitty, Alacritty, WezTerm
- **Linux:** GNOME Terminal, Konsole, Ghostty, Kitty, Alacritty, WezTerm
- **Windows:** Windows Terminal, PowerShell, CMD

**Note:** Terminal.app, Windows Terminal, and other default terminals work perfectly fine. You don't need a specific terminal.

**API keys** for the LLM providers you want to use (unless using [iTE Cloud](/docs#bundled-models-&-pricing).

## Install with pipx (recommended)

[iTE](https://pypi.org/project/ite-agent/) is available on PyPI:

```bash
pipx install ite-agent
```

Verify the installation:

```bash
ite --version
```

## Other installation methods

### uv

```bash
uv tool install ite-agent
```

### Upgrade

```bash
pipx upgrade ite-agent
```

### Uninstall

```bash
pipx uninstall ite-agent
```

---

## Next Steps

[Configure your provider →](configuration.md)
