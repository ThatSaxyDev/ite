const vscode = require("vscode");
const { execFile } = require("child_process");

let currentTerminal;
let statusBarItem;

function isCancellation(error) {
  return (
    error &&
    (error.name === "Canceled" ||
      error.message === "Canceled" ||
      String(error).includes("Canceled"))
  );
}

function handleCommandError(error) {
  if (isCancellation(error)) {
    return;
  }

  const message = error instanceof Error ? error.message : String(error);
  void vscode.window.showErrorMessage(`iTE failed to open: ${message}`);
}

function registerCommand(context, command, callback) {
  context.subscriptions.push(
    vscode.commands.registerCommand(command, async () => {
      try {
        await callback();
      } catch (error) {
        handleCommandError(error);
      }
    }),
  );
}

function getWorkspaceCwd() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length > 0 ? folders[0].uri.fsPath : undefined;
}

function getIteCommand() {
  const executable = getIteExecutable();
  const args = getIteArgs();

  return [executable, ...args].map(shellQuote).join(" ");
}

function getIteExecutable() {
  const configuredExecutable = vscode.workspace
    .getConfiguration("ite")
    .get("executable", "ite")
    .trim();

  return configuredExecutable || "ite";
}

function getIteArgs() {
  const configuredArgs = vscode.workspace.getConfiguration("ite").get("args", []);
  if (!Array.isArray(configuredArgs)) {
    return [];
  }

  return configuredArgs.filter((arg) => typeof arg === "string");
}

function getTerminalOptions() {
  return {
    name: "iTE",
    cwd: getWorkspaceCwd(),
  };
}

function shellQuote(value) {
  if (!/[\s"'\\$`!#&*();<>?[{|~]/.test(value)) {
    return value;
  }

  return `'${value.replace(/'/g, "'\\''")}'`;
}

function checkIteInstalled() {
  return new Promise((resolve) => {
    execFile(
      getIteExecutable(),
      ["--version"],
      { timeout: 5000 },
      (error, stdout, stderr) => {
        if (error) {
          resolve({
            installed: false,
            message: error.message,
          });
          return;
        }

        resolve({
          installed: true,
          message: String(stdout || stderr).trim(),
        });
      },
    );
  });
}

function createIteTerminal() {
  const terminal = vscode.window.createTerminal(getTerminalOptions());

  currentTerminal = terminal;
  terminal.show();
  terminal.sendText(getIteCommand());
}

function openTerminal() {
  if (currentTerminal) {
    currentTerminal.show();
    return;
  }

  createIteTerminal();
}

function openNewTerminal() {
  createIteTerminal();
}

async function checkInstallation() {
  const result = await checkIteInstalled();
  updateStatusBar(result.installed);

  if (result.installed) {
    await vscode.window.showInformationMessage(
      result.message ? `iTE is installed: ${result.message}` : "iTE is installed.",
    );
    return;
  }

  const action = await vscode.window.showWarningMessage(
    "VS Code could not find the iTE CLI. Install it with `pipx install ite-agent`, or set `ite.executable` to the full path.",
    "Open Install Docs",
  );

  if (action === "Open Install Docs") {
    await vscode.env.openExternal(vscode.Uri.parse("https://ite.kiishi.space/docs"));
  }
}

function registerTerminalProfile(context) {
  context.subscriptions.push(
    vscode.window.registerTerminalProfileProvider("ite.terminalProfile", {
      provideTerminalProfile() {
        return new vscode.TerminalProfile({
          ...getTerminalOptions(),
          shellPath: getIteExecutable(),
          shellArgs: getIteArgs(),
        });
      },
    }),
  );
}

function updateStatusBar(installed) {
  if (!statusBarItem) {
    return;
  }

  statusBarItem.text = installed ? "$(terminal) iTE" : "$(warning) iTE";
  statusBarItem.tooltip = installed
    ? "Open iTE in the integrated terminal"
    : "iTE CLI was not found. Click to open iTE anyway or configure ite.executable.";
}

function registerStatusBar(context) {
  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100,
  );
  statusBarItem.name = "iTE";
  statusBarItem.text = "$(terminal) iTE";
  statusBarItem.tooltip = "Open iTE in the integrated terminal";
  statusBarItem.command = "ite.openTerminal";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);
}

async function showWelcomeOnce(context) {
  const key = "ite.welcomeShown";
  if (context.globalState.get(key)) {
    return;
  }

  await context.globalState.update(key, true);
  const action = await vscode.window.showInformationMessage(
    "iTE is ready in VS Code.",
    "Open iTE",
  );

  if (action === "Open iTE") {
    openTerminal();
  }
}

async function refreshInstallState() {
  const result = await checkIteInstalled();
  updateStatusBar(result.installed);
}

function activate(context) {
  registerCommand(context, "ite.openTerminal", openTerminal);
  registerCommand(context, "ite.openNewTerminal", openNewTerminal);
  registerCommand(context, "ite.checkInstallation", checkInstallation);
  registerTerminalProfile(context);
  registerStatusBar(context);
  void refreshInstallState().catch(handleCommandError);
  void showWelcomeOnce(context).catch(handleCommandError);

  context.subscriptions.push(
    vscode.window.onDidCloseTerminal((terminal) => {
      if (terminal === currentTerminal) {
        currentTerminal = undefined;
      }
    }),
  );
}

function deactivate() {
  statusBarItem = undefined;
}

module.exports = {
  activate,
  deactivate,
};
