# iTE VS Code Extension

This is a lightweight VS Code wrapper for iTE. It opens VS Code's integrated terminal and runs the existing `ite` command.

## What users see after install

- An `iTE` status-bar item.
- `iTE: Open iTE` in the Command Palette.
- `iTE` in the terminal profile selector.
- A first-run walkthrough on VS Code's Getting Started page.

## Try it locally

1. Open the `vscode-extension` folder in VS Code.
2. Open `extension.js`.
3. Press `F5` to launch an Extension Development Host.
4. In the new VS Code window, run `iTE: Open iTE` from the Command Palette.

## Commands

- `iTE: Open iTE` reopens the current iTE terminal if it exists, otherwise creates one and runs `ite`.
- `iTE: Open New iTE Terminal` always creates a fresh terminal and runs `ite`.
- `iTE: Check Installation` verifies that VS Code can find the iTE CLI.

## Settings

- `ite.executable`: executable used to launch iTE. Defaults to `ite`.
- `ite.args`: arguments passed to the iTE executable. Defaults to `[]`.

Use this if iTE is not on the VS Code PATH, for example:

```json
{
  "ite.executable": "/Users/you/.local/bin/ite"
}
```

## Package for local install

Install dependencies:

```bash
npm install
```

Build a `.vsix` package:

```bash
npm run package
```

Install the generated package:

```bash
code --install-extension ite-vscode-0.0.1.vsix
```

## Publish to the VS Code Marketplace

1. Create a Visual Studio Marketplace publisher.
2. Update `publisher` in `package.json` to match the publisher ID.
3. Create a Marketplace personal access token.
4. Login and publish:

```bash
npx vsce login <publisher-id>
npm run publish
```

Once published, users can install the extension from VS Code's Extensions view and immediately open iTE from the status bar, Command Palette, or terminal profile selector.
