import fs from "node:fs";
import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, shell } from "electron";
import path from "node:path";

const isDev = !app.isPackaged;
import { execFileSync } from "node:child_process";
import { BackendProcess } from "./services/backendProcess.js";
import { CaptureService } from "./services/captureService.js";
import * as pty from "node-pty";

const backend = new BackendProcess();
let mainWindow: BrowserWindow | null = null;
const captureService = new CaptureService(() => mainWindow, 5178);

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
  try {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.webContents.isDestroyed()) {
      mainWindow.webContents.send("terminal:output", sessionId, data);
    }
  } catch {
    // Window is closing/destroyed; ignore stream data during app shutdown
  }
}

// ── Menu ───────────────────────────────────────────────────────────

function sendMenuAction(action: string): void {
  try {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.webContents.isDestroyed()) {
      mainWindow.webContents.send("menu:action", action);
    }
  } catch {
    // Ignore if window destroyed
  }
}

function createMenu(): void {
  Menu.setApplicationMenu(null);
}

// ── Window Controls IPC ─────────────────────────────────────────────
ipcMain.handle("window:minimize", () => {
  mainWindow?.minimize();
});

ipcMain.handle("window:maximize", () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow.maximize();
    }
  }
});

ipcMain.handle("window:close", () => {
  mainWindow?.close();
});

ipcMain.handle("window:is-maximized", () => {
  return mainWindow?.isMaximized() ?? false;
});

async function createWindow(): Promise<void> {
  const iconPath = process.platform === "win32"
    ? path.join(__dirname, "../build/icon.ico")
    : path.join(__dirname, "../build/icon.png");

  mainWindow = new BrowserWindow({
    width: 1500,
    height: 950,
    minWidth: 1080,
    minHeight: 720,
    title: "CODE OS",
    frame: false,
    titleBarStyle: "hidden",
    autoHideMenuBar: true,
    icon: iconPath,
    backgroundColor: "#101215",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  });
  mainWindow.setMenuBarVisibility(false);


  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    const devUrl = process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5176";
    await mainWindow.loadURL(devUrl);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    if (process.env.CODEOS_DEBUG === "1") {
      mainWindow.webContents.openDevTools({ mode: "detach" });
    }
    const indexPath = path.join(__dirname, "../dist/index.html");
    try {
      await mainWindow.loadFile(indexPath);
    } catch (err: any) {
      console.error("[main] Could not load dist/index.html:", err);
      const fallbackHtml = `<!DOCTYPE html><html><body style="background:#101215;color:#f87171;font-family:sans-serif;padding:40px;line-height:1.6;">
        <h2>CODE OS - App Load Failure</h2>
        <p>Could not load packaged frontend bundle at: <code>${indexPath}</code></p>
        <p style="color:#a1a1aa">${err?.message || err}</p>
        <button onclick="location.reload()" style="background:#00e5ff;color:#000;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;font-weight:bold;margin-top:16px;">Retry</button>
      </body></html>`;
      await mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(fallbackHtml)}`);
    }
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

ipcMain.handle("shell:openExternal", (_event, url: string) => {
  void shell.openExternal(url);
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

  // Inject bundled standalone Node and Python runtimes to PATH in packaged app
  if (!isDev) {
    const platformFolder = process.platform === "win32" ? "win" : process.platform;
    const nodeDir = path.join(process.resourcesPath, "node-runtime", platformFolder, "node");
    const pythonDir = path.join(process.resourcesPath, "python-runtime", platformFolder, "python");
    const extraPaths: string[] = [];
    if (fs.existsSync(nodeDir)) {
      extraPaths.push(nodeDir);
      if (process.platform !== "win32") {
        extraPaths.push(path.join(nodeDir, "bin"));
      }
    }
    if (fs.existsSync(pythonDir)) {
      extraPaths.push(pythonDir);
      if (process.platform !== "win32") {
        extraPaths.push(path.join(pythonDir, "bin"));
      }
    }
    if (extraPaths.length > 0) {
      const currentPath = safe["PATH"] || process.env.PATH || "";
      safe["PATH"] = extraPaths.join(path.delimiter) + path.delimiter + currentPath;
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
    return await backend.waitForToken(4_000);
  } catch (err) {
    console.error("[session] Could not obtain session token:", err);
    return null;
  }
});

ipcMain.handle("backend:getStatus", () => {
  return {
    running: !!backend.sessionToken,
    error: backend.lastError,
    token: backend.sessionToken,
  };
});

ipcMain.handle("vision:capture", async (_event, req) => {
  return await captureService.handleCapture(req);
});

app.whenReady().then(async () => {
  createMenu();
  // Open window immediately so user sees instant startup UI
  await createWindow();

  // Start backend and capture service asynchronously
  void backend.start().catch((err) => {
    console.error("[app] backend start error:", err);
  });

  try {
    await captureService.start();
  } catch (err) {
    console.warn("[app] Capture service failed to start:", err);
  }
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
  captureService.stop();
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
