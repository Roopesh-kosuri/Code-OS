export type TerminalSession = {
  id: string;
  name: string;
  cwd: string;
};

export type CodeOSDesktopApi = {
  selectWorkspaceFolder: () => Promise<string | null>;
  revealInSystemExplorer: (path: string) => Promise<void>;
  copyText: (text: string) => Promise<void>;
  onMenuAction: (callback: (action: string) => void) => () => void;
  platform: NodeJS.Platform;

  // Terminal API
  terminalCreate: (cwd: string) => Promise<string>;
  terminalWrite: (sessionId: string, data: string) => void;
  terminalResize: (sessionId: string, cols: number, rows: number) => void;
  terminalKill: (sessionId: string) => void;
  terminalList: () => TerminalSession[];
  onTerminalOutput: (sessionId: string, callback: (data: string) => void) => () => void;
};

declare global {
  interface Window {
    codeOS?: CodeOSDesktopApi;
  }
}

export {};
