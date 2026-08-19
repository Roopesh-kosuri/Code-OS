export type TerminalSession = {
  id: string;
  name: string;
  cwd: string;
};

export type CodeOSDesktopApi = {
  selectWorkspaceFolder: () => Promise<string | null>;
  revealInSystemExplorer: (path: string) => Promise<void>;
  copyText: (text: string) => Promise<void>;
  openExternal?: (url: string) => Promise<void>;
  onMenuAction: (callback: (action: string) => void) => () => void;
  platform: NodeJS.Platform;

  // Terminal API
  terminalCreate: (cwd: string) => Promise<string>;
  terminalWrite: (sessionId: string, data: string) => void;
  terminalResize: (sessionId: string, cols: number, rows: number) => void;
  terminalKill: (sessionId: string) => void;
  terminalList: () => TerminalSession[];
  onTerminalOutput: (sessionId: string, callback: (data: string) => void) => () => void;

  /**
   * Returns the backend session token so the API client can include it in
   * Authorization headers.  Call once at startup and keep in memory only.
   */
  getSessionToken: () => Promise<string | null>;
  getBackendStatus?: () => Promise<{ running: boolean; error: string | null; token: string | null }>;
  visionCapture?: (req: { mode?: "preview" | "app_window"; target?: string; workspace?: string; width?: number; height?: number }) => Promise<{ success: boolean; image_base64?: string; format?: string; error?: string }>;
  windowControls?: {
    minimize: () => Promise<void>;
    maximize: () => Promise<void>;
    close: () => Promise<void>;
    isMaximized: () => Promise<boolean>;
  };
};


declare global {
  interface Window {
    codeOS?: CodeOSDesktopApi;
  }
}

export {};
