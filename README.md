# iTE

iTE is a production-ready AI coding agent for serious terminal work: it understands your codebase, executes real changes, and keeps you in control. Learn more at [ite.kiishi.space](https://ite.kiishi.space).


![iTE Demo](https://ite.kiishi.space/demo.gif)

## Install

### macOS / Linux

```bash
curl -fsSL https://ite.kiishi.space/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://ite.kiishi.space/install.ps1 | iex
```

The installer detects your OS and architecture, downloads the latest standalone iTE binary, verifies its checksum, and adds `ite` to your PATH. No dependencies required.

Supported targets: `darwin-arm64`, `darwin-x64`, `linux-x64`, `win32-x64`.

## Verifying Integrity

The installer automatically verifies the SHA-256 checksum of every downloaded archive against the [release manifest](https://ite.kiishi.space/releases/manifest.json).

## From Source

If you prefer installing from source:

```bash
pipx install ite-agent          # isolated environment
uv tool install ite-agent        # via uv
pip install ite-agent            # global pip
```

## Documentation

- [iTE Docs](https://ite.kiishi.space/docs)
- [Learning mode (experimental)](docs/learning.md) — use `/learn on` to write the code yourself while iTE guides and reviews.
