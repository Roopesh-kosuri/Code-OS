import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, shell } from "electron";
import isDev from "electron-is-dev";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { BackendProcess } from "./services/backendProcess.js";
import * as pty from "node-pty";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
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
    await mainWindow.loadURL("http://127.0.0.1:5173");
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
      env: { ...process.env, TERM: "xterm-256color" },
      useConpty,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[terminal] spawn failed for ${shellEnv}: ${msg}`);
    setTimeout(() => sendTerminalOutput(
      id,
      `
[31m[Failed to start shell "${shellEnv}": ${msg}][0m
`
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

app.whenReady().then(async () => {
  await backend.start();
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
