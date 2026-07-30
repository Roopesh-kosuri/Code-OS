import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, shell } from "electron";
import path from "node:path";

const isDev = !app.isPackaged;
import { execFileSync } from "node:child_process";
import { BackendProcess } from "./services/backendProcess.js";
import * as pty from "node-pty";

const backend = new BackendProcess();
let mainWindow: BrowserWindow | null = null;

function resolveAssetPath(fileName: string): string {
  if (isDev) {
    return path.join(__dirname, "../public", fileName);
  }
  return path.join(__dirname, "../dist", fileName);
}

// ── Terminal PTY Sessions ──────────────────────────────────────────
interface TerminalPtySession {
  id: string;
  name: string;
  cwd: string;
  process: pty.IPty;
}

const terminalSessions = new Map<string, TerminalPtySession>();
let terminalIdCounter = 0;

function sendTerminalOutput(sessionId: string, data: string): void {
  mainWindow?.webContents.send("terminal:output", sessionId, data);
}

// ── Menu ───────────────────────────────────────────────────────────

function sendMenuAction(action: string): void {
  mainWindow?.webContents.send("menu:action", action);
}

function createMenu(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: "File",
      submenu: [
        { label: "Open Folder", accelerator: "CmdOrCtrl+O", click: () => sendMenuAction("file.openFolder") },
        { label: "Save", accelerator: "CmdOrCtrl+S", click: () => sendMenuAction("file.save") },
        { label: "Save All", accelerator: "CmdOrCtrl+Shift+S", click: () => sendMenuAction("file.saveAll") },
        { label: "Close Workspace", accelerator: "CmdOrCtrl+K", click: () => sendMenuAction("file.closeWorkspace") },
        { type: "separator" },
        { label: "Exit", role: "quit" }
      ]
    },
    {
      label: "Edit",
      submenu: [
        { label: "Undo", accelerator: "CmdOrCtrl+Z", role: "undo" },
        { label: "Redo", accelerator: "CmdOrCtrl+Y", role: "redo" },
        { type: "separator" },
        { label: "Copy", accelerator: "CmdOrCtrl+C", role: "copy" },
        { label: "Paste", accelerator: "CmdOrCtrl+V", role: "paste" },
        { type: "separator" },
        { label: "Find", accelerator: "CmdOrCtrl+F", click: () => sendMenuAction("edit.find") },
        { label: "Replace", accelerator: "CmdOrCtrl+H", click: () => sendMenuAction("edit.replace") }
      ]
    },
    {
      label: "View",
      submenu: [
        { label: "Toggle Explorer", accelerator: "CmdOrCtrl+B", click: () => sendMenuAction("view.toggleExplorer") },
        { label: "Toggle Terminal", accelerator: "Ctrl+`", click: () => sendMenuAction("view.toggleTerminal") },
        { label: "Toggle AI", accelerator: "CmdOrCtrl+Shift+A", click: () => sendMenuAction("view.toggleAI") },
        { type: "separator" },
        { role: "toggleDevTools" },
        { role: "reload" }
      ]
    },
    {
      label: "Help",
      submenu: [
        {
          label: "About CODE OS",
          click: () => {
            const options = {
              type: "info",
              title: "About CODE OS",
              message: "CODE OS",
              detail: "Local-first AI development workspace. Phase 1.5."
            } as const;
            if (mainWindow) {
              void dialog.showMessageBox(mainWindow, options);
            } else {
              void dialog.showMessageBox(options);
            }
          }
        }
      ]
    }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 950,
    minWidth: 1080,
    minHeight: 720,
    title: "CODE OS",
    icon: resolveAssetPath("codeos-app-icon.png"),
    backgroundColor: "#101215",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    const devUrl = process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5176";
    await mainWindow.loadURL(devUrl);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    await mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
}

ipcMain.handle("workspace:select-folder", async () => {
  console.log("[workspace.dialog] opening native folder dialog");
  const options = {
    title: "Open workspace",
    properties: ["openDirectory", "createDirectory"] as ("openDirectory" | "createDirectory")[]
  };
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, options)
    : await dialog.showOpenDialog(options);

  const selected = result.canceled ? null : result.filePaths[0] ?? null;
  console.log("[workspace.dialog] selected", selected);
  return selected;
});

ipcMain.handle("shell:reveal", (_event, targetPath: string) => {
  shell.showItemInFolder(targetPath);
});

ipcMain.handle("clipboard:copy", (_event, text: string) => {
  clipboard.writeText(text);
});

// ── Terminal Environment Allowlist ────────────────────────────────────────────
//
// SECURITY: We use an ALLOWLIST (not a blacklist) to control which host
// environment variables are forwarded to PTY terminal sessions.
//
// A blacklist is fundamentally broken: pattern-matching on substrings like
// "key", "secret", "auth" would kill legitimate shell variables:
//   - SSH_AUTH_SOCK  (matched "auth") — breaks SSH agent forwarding
//   - KEYBOARD_LAYOUT / KEYBINDING (matched "key") — breaks keyboard config
//   - GPG_KEY_ID (matched "key") — breaks gpg tooling
//
// The allowlist approach passes ONLY variables that are operationally necessary
// for a shell to function correctly.  Secrets (API keys, cloud credentials,
// database passwords, bearer tokens) are never forwarded even if present in
// the Electron main process environment (process.env).
//
// sandbox: false is required in BrowserWindow webPreferences because the
// preload script uses ipcRenderer, which needs Node.js APIs that are NOT
// available in the fully sandboxed renderer context.  contextIsolation: true
// and nodeIntegration: false are both set, so the renderer cannot access
// Node APIs directly — only the safe API surface exposed via contextBridge.

const SAFE_ENV_VARS = new Set([
  // Shell / session identity
  "PATH", "HOME", "USER", "LOGNAME",
  "USERNAME", "USERPROFILE",          // Windows equivalents
  "SHELL", "LANG", "LC_ALL", "LC_MESSAGES", "LC_CTYPE", "LANGUAGE",
  "TERM", "TERM_PROGRAM", "COLORTERM", "COLUMNS", "LINES",

  // SSH agent socket (path only, not a secret)
  "SSH_AUTH_SOCK", "SSH_AGENT_PID",
  // GPG agent
  "GPG_AGENT_INFO",

  // Python / virtual env
  "PYTHONPATH", "PYTHONIOENCODING", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",

  // Node / npm toolchain
  "NVM_DIR", "NODE_PATH", "NPM_CONFIG_PREFIX",

  // Rust toolchain
  "CARGO_HOME", "RUSTUP_HOME",

  // Go toolchain
  "GOPATH", "GOROOT",

  // Java
  "JAVA_HOME",

  // macOS / Linux specifics
  "TMPDIR", "XDG_RUNTIME_DIR",
  "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "DBUS_SESSION_BUS_ADDRESS",

  // Windows specifics
  "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
  "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
  "PROGRAMFILES", "PROGRAMDATA", "COMPUTERNAME",
]);

function buildSafeEnv(): NodeJS.ProcessEnv {
  const safe: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (SAFE_ENV_VARS.has(key) && value !== undefined) {
      safe[key] = value;
    }
  }
  // Always inject a sane TERM value so TUI programs (vim, htop, etc.) work.
  safe["TERM"] = "xterm-256color";
  return safe;
}

// ── Terminal IPC Handlers ──────────────────────────────────────────

function resolveShell(): string {
  if (process.platform !== "win32") {
    return process.env.SHELL || "/bin/bash";
  }
  // On Windows, probe shells in order: PowerShell 7+, built-in PowerShell, then cmd.
  // `where.exe` is built-in on Windows and always available.
  for (const candidate of ["pwsh.exe", "powershell.exe", "cmd.exe"]) {
    try {
      execFileSync("where.exe", [candidate], { stdio: "ignore" });
      return candidate;
    } catch {
      // not found, try next
    }
  }
  return "cmd.exe"; // absolute last resort
}

ipcMain.handle("terminal:create", (_event, cwd: string) => {
  const id = `term-${++terminalIdCounter}`;
  const shellEnv = resolveShell();
  const useConpty = process.platform === "win32";
  const resolvedCwd = cwd || process.env.HOME || process.env.USERPROFILE || process.cwd();

  let ptyProcess;
  try {
    ptyProcess = pty.spawn(shellEnv, [], {
      name: "xterm-256color",
      cols: 80,
      rows: 24,
      cwd: resolvedCwd,
      env: buildSafeEnv(),
      useConpty,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[terminal] spawn failed for ${shellEnv}: ${msg}`);
    setTimeout(() => sendTerminalOutput(
      id,
      `\r\n\x1b[31m[Failed to start shell "${shellEnv}": ${msg}]\x1b[0m\r\n`
    ), 0);
    return id;
  }

  ptyProcess.onData((data: string) => {
    sendTerminalOutput(id, data);
  });

  ptyProcess.onExit(() => {
    terminalSessions.delete(id);
    sendTerminalOutput(id, `\r\n[Process exited]\r\n`);
  });

  const session: TerminalPtySession = {
    id,
    name: "Terminal",
    cwd: cwd || process.cwd(),
    process: ptyProcess,
  };
  terminalSessions.set(id, session);
  console.log(`[terminal] created session ${id} (cwd=${cwd}, shell=${shellEnv})`);
  return id;
});

ipcMain.handle("terminal:write", (_event, sessionId: string, data: string) => {
  const session = terminalSessions.get(sessionId);
  if (session) {
    session.process.write(data);
  }
});

ipcMain.handle("terminal:resize", (_event, sessionId: string, cols: number, rows: number) => {
  const session = terminalSessions.get(sessionId);
  if (session) {
    session.process.resize(cols, rows);
  }
});

ipcMain.handle("terminal:kill", (_event, sessionId: string) => {
  const session = terminalSessions.get(sessionId);
  if (session) {
    try {
      session.process.kill();
    } catch {
      // process may already be dead
    }
    terminalSessions.delete(sessionId);
    console.log(`[terminal] killed session ${sessionId}`);
  }
});

ipcMain.handle("terminal:list", () => {
  return Array.from(terminalSessions.values()).map((s) => ({
    id: s.id,
    name: s.name,
    cwd: s.cwd,
  }));
});

// ── Session Token IPC ──────────────────────────────────────────────────────
// The renderer needs the session token to include in every API request's
// Authorization header.  We expose it via a dedicated IPC handler so it is
// never injected into the renderer's global scope (which would be accessible
// to any content in the page).
//
// The renderer must call window.codeOS.getSessionToken() ONCE at startup and
// store the result in memory (not localStorage, not sessionStorage).

ipcMain.handle("session:getToken", async () => {
  try {
    return await backend.waitForToken(15_000);
  } catch (err) {
    console.error("[session] Could not obtain session token:", err);
    return null;
  }
});

app.whenReady().then(async () => {
  await backend.start();
  // Wait for the backend to emit its session token before opening the window.
  // This ensures the renderer can immediately call getSessionToken() without
  // a race condition.
  try {
    await backend.waitForToken(20_000);
    console.log("[app] session token ready");
  } catch {
    console.warn("[app] session token wait timed out; app will open anyway");
  }
  createMenu();
  await createWindow();
});


app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    void createWindow();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  backend.stop();
  // Kill all terminal sessions
  for (const session of terminalSessions.values()) {
    try {
      session.process.kill();
    } catch {
      // already dead
    }
  }
  terminalSessions.clear();
});
