VS Code needs to find the `ite` executable on its PATH.

If this check fails, install the CLI with:

```bash
pipx install ite-agent
```

If iTE is already installed but VS Code cannot find it, set `ite.executable` to the full path returned by `which ite`.
