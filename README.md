# iTE - Interactive Terminal Environment

An AI coding agent for your terminal. Connect your model service and start coding.

## Install

**With pipx (recommended):**
```bash
pipx install ite-agent
```

**With uv:**
```bash
uv tool install ite-agent
```

## Usage

Start a session:
```bash
ite
```

On first run, you'll be prompted to:
1. Sign in at `ite.kiishi.space`
2. Configure your model provider via `/setup`

Once configured, start prompting.

## VS Code

iTE also has a VS Code extension wrapper in `vscode-extension/`. It adds an `iTE` status-bar item, Command Palette commands, and an `iTE` terminal profile that launches the installed `ite` CLI in VS Code's integrated terminal.

## Documentation

Visit [ite.kiishi.space/docs](https://ite.kiishi.space/docs) for full documentation.

## License

MIT
