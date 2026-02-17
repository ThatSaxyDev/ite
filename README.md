# ITE - Interactive Terminal Environment

An AI coding agent for your terminal.

## Installation

### Option 1: Development Install (Local)

Clone the repository and install in editable mode:

```bash
git clone https://github.com/yourusername/ite.git
cd ite
pip install -e .
```

### Option 2: Install from Source (Global)

Install globally using `pipx` (recommended) or `pip`:

```bash
# Using pipx
pipx install ite-agent

# Using pip
pip install ite-agent
```

### Option 3: Install from Git

```bash
pipx install git+https://github.com/yourusername/ite.git
```

## Distribution

To distribute ITE, you can build a wheel file:

1. Install `build`:
   ```bash
   pip install build
   ```

2. Build the package:
   ```bash
   python -m build
   ```

This generates `dist/ite-0.0.1-py3-none-any.whl`, which can be shared and installed anywhere:

```bash
pipx install ite-0.0.1-py3-none-any.whl
```

## Usage

```bash
# Start interactive session
ite
```

## Configuration

Run `ite` for the first time to set up your API credentials interactively.
Or use the `/setup` command within the tool.
