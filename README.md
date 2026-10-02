# iTE

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

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

Installer source: [macOS / Linux](scripts/install.sh) and
[Windows PowerShell](scripts/install.ps1).

## Verifying Integrity

The installer automatically verifies the SHA-256 checksum of every downloaded archive against the [release manifest](https://ite.kiishi.space/releases/manifest.json).

## Python Package

If you prefer installing the Python package:

```bash
pipx install ite-agent          # isolated environment
uv tool install ite-agent        # via uv
pip install ite-agent            # global pip
```

## Build From Source

Requires Python 3.11 or newer.

```bash
git clone https://github.com/ThatSaxyDev/ite.git
cd ite
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
ite
```

Model access requires a configured provider or iTE Cloud service; provider fees
and cloud subscriptions are separate from the runtime's license.

## License and Cloud Services

The iTE terminal runtime in this repository is open source under the
[MIT License](LICENSE). You may use, modify, and redistribute it, including
commercially, subject to the license's notice requirements.

iTE Cloud, including its hosted web application and backend API, is proprietary
and offered separately through paid subscriptions. The runtime's MIT license
does not grant access to those services or license their private source code.
Third-party dependencies and bundled third-party materials retain their own
licenses.

## Documentation

- [iTE Docs](https://ite.kiishi.space/docs)
- [Learning mode (experimental)](docs/learning.md) — use `/learn on` to write the code yourself while iTE guides and reviews.
