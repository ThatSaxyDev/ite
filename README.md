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
### Method 1: The Best Experience (Recommended)
We recommend using **pipx** to install `ite`. This ensures the `ite` command is available globally without conflicting with other Python packages.

1. **Install pipx** (if you haven't already):
   ```bash
   brew install pipx
   pipx ensurepath
   ```
   *(Restart your terminal after this)*

2. **Install ite-agent**:
   ```bash
   pipx install ite-agent
   ```

3. **Run it**:
   ```bash
   ite
   ```

### Method 2: Standard Pip
If you prefer standard pip:
```bash
pip install ite-agent
```
*Note: You may need to add your Python binary location to your PATH to run the `ite` command directly.*
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

This generates `dist/ite-0.0.4-py3-none-any.whl`, which can be shared and installed anywhere:

```bash
pipx install ite-0.0.4-py3-none-any.whl
```

## Usage

```bash
# Start interactive session
ite
```

## Configuration

Run `ite` for the first time to set up your API credentials interactively.
Or use the `/setup` command within the tool.
