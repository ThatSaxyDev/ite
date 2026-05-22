# ITE Installation Guide (macOS and Windows)

This guide installs `ite-agent` globally so the `ite` command works from any folder.

## macOS

### 1. Install Python 3.11++++
If neededd:

```bash
brew install python
```

### 2. Install pipx

```bash

pipx ensurepath
```

Close and reopen your terminal.

### 3. Install ITE globally

```bash
pipx install ite-agent
```

### 4. Verify

```bash
ite --version
which ite
```

## Windows (PowerShell)

### 1. Install Python 3.11+
Install from [python.org](https://www.python.org/downloads/windows/) and enable "Add Python to PATH" during setup.

### 2. Install pipx

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

Close and reopen PowerShell.

### 3. Install ITE globally

```powershell
pipx install --pip-args="--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple" ite-agent --force
```

If `pipx` is not recognized yet:

```powershell
py -m pipx install ite-agent
```

### 4. Verify

```powershell
ite --version
Get-Command ite
```

## Optional: Install from TestPyPI

Use this when validating a pre-release:

```bash
pipx install --pip-args="--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple" ite-agent --force
```

Windows PowerShell:

```powershell
pipx install --pip-args="--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple" ite-agent --force
```

## Upgrade

```bash
pipx upgrade ite-agent
```

## Uninstall

```bash
pipx uninstall ite-agent
```
