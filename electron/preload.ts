import { contextBridge, ipcRenderer } from "electron";

type TerminalSessionInfo = {
  id: string;
  name: string;
  cwd: string;
};

const terminalOutputListeners = new Map<string, Set<(data: string) => void>>();

// Listen for terminal output from main process and route to the right session
ipcRenderer.on("terminal:output", (_event, sessionId: string, data: string) => {
  const listeners = terminalOutputListeners.get(sessionId);
  if (listeners) {
    listeners.forEach((cb) => cb(data));
  }
});

const api = {
  selectWorkspaceFolder: () => ipcRenderer.invoke("workspace:select-folder"),
  revealInSystemExplorer: (path: string) => ipcRenderer.invoke("shell:reveal", path),
  copyText: (text: string) => ipcRenderer.invoke("clipboard:copy", text),
  onMenuAction: (callback: (action: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, action: string) => callback(action);
    ipcRenderer.on("menu:action", listener);
    return () => ipcRenderer.removeListener("menu:action", listener);
  },
  platform: process.platform,

  // Terminal IPC
  terminalCreate: (cwd: string) => ipcRenderer.invoke("terminal:create", cwd),
  terminalWrite: (sessionId: string, data: string) => ipcRenderer.invoke("terminal:write", sessionId, data),
  terminalResize: (sessionId: string, cols: number, rows: number) => ipcRenderer.invoke("terminal:resize", sessionId, cols, rows),
  terminalKill: (sessionId: string) => ipcRenderer.invoke("terminal:kill", sessionId),
  terminalList: () => ipcRenderer.invoke("terminal:list") as unknown as TerminalSessionInfo[],
  onTerminalOutput: (sessionId: string, callback: (data: string) => void) => {
    if (!terminalOutputListeners.has(sessionId)) {
      terminalOutputListeners.set(sessionId, new Set());
    }
    terminalOutputListeners.get(sessionId)!.add(callback);
    return () => {
      const set = terminalOutputListeners.get(sessionId);
      if (set) {
        set.delete(callback);
        if (set.size === 0) terminalOutputListeners.delete(sessionId);
      }
    };
  }
};

contextBridge.exposeInMainWorld("codeOS", api);
