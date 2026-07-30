import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Square, X, ShieldAlert, Terminal as TermIcon } from "lucide-react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

import { IconButton } from "../../components/ui/IconButton";
import { useWorkspaceStore } from "../../stores/workspaceStore";

type TermSession = {
  id: string;
  name: string;
  cwd: string;
  term: Terminal;
  fitAddon: FitAddon;
  container: HTMLDivElement | null;
  resizeObserver: ResizeObserver | null;
  removeListener: (() => void) | null;
  ws: WebSocket | null;
};

let sessionIdCounter = 0;
const sessions = new Map<string, TermSession>();
let activeSessionId: string | null = null;

function getTheme(themeName: string) {
  if (themeName === "light") {
    return {
      background: "#ffffff",
      foreground: "#1f2328",
      cursor: "#0969da",
      selectionBackground: "#ddf4ff",
      black: "#1f2328", red: "#cf222e", green: "#1a7f37", yellow: "#9a6700",
      blue: "#0969da", magenta: "#8250df", cyan: "#1b7c83",
      white: "#1f2328",
      brightBlack: "#57606a", brightRed: "#cf222e", brightGreen: "#1a7f37",
      brightYellow: "#9a6700", brightBlue: "#0969da", brightMagenta: "#8250df",
      brightCyan: "#1b7c83", brightWhite: "#1f2328",
    };
  }
  if (themeName === "void") {
    return {
      background: "#000000",
      foreground: "#f4f4f5",
      cursor: "#a1a1aa",
      selectionBackground: "#27272a",
      black: "#09090b", red: "#ef4444", green: "#22c55e", yellow: "#eab308",
      blue: "#a1a1aa", magenta: "#d4d4d8", cyan: "#e4e4e7",
      white: "#f4f4f5",
      brightBlack: "#52525b", brightRed: "#ef4444", brightGreen: "#22c55e",
      brightYellow: "#eab308", brightBlue: "#a1a1aa", brightMagenta: "#d4d4d8",
      brightCyan: "#e4e4e7", brightWhite: "#ffffff",
    };
  }
  if (themeName === "cyberpunk") {
    return {
      background: "#080b12",
      foreground: "#dcf1f5",
      cursor: "#00e5ff",
      selectionBackground: "rgba(0, 229, 255, 0.25)",
      black: "#05070d", red: "#ff2e88", green: "#00ffd8", yellow: "#ffdd00",
      blue: "#00e5ff", magenta: "#ff007f", cyan: "#00e5ff",
      white: "#dcf1f5",
      brightBlack: "#4b7e8a", brightRed: "#ff2e88", brightGreen: "#00ffd8",
      brightYellow: "#ffdd00", brightBlue: "#00e5ff", brightMagenta: "#ff79c6",
      brightCyan: "#00f0ff", brightWhite: "#ffffff",
    };
  }
  // Dark (default)
  return {
    background: "#131314",
    foreground: "#e5e2e3",
    cursor: "#00e5ff",
    selectionBackground: "#00626e66",
    black: "#1b2027", red: "#ffb4ab", green: "#64d99a", yellow: "#ffeac0",
    blue: "#00daf3", magenta: "#d1bcff", cyan: "#c3f5ff",
    white: "#e5e2e3",
    brightBlack: "#849396", brightRed: "#ffb4ab", brightGreen: "#64d99a",
    brightYellow: "#ffeac0", brightBlue: "#00daf3", brightMagenta: "#d1bcff",
    brightCyan: "#c3f5ff", brightWhite: "#ffffff",
  };
}

function safeGetTheme(themeName: string) {
  try {
    const t = getTheme(themeName);
    if (t && t.background && t.foreground) return t;
  } catch (e) {
    console.warn("xterm getTheme failed, falling back to dark default:", e);
  }
  return getTheme("dark");
}

function getActiveThemeName(): string {
  const root = document.documentElement;
  const dataTheme = root.getAttribute("data-theme");
  if (dataTheme && ["light", "void", "cyberpunk", "dark"].includes(dataTheme)) {
    return dataTheme;
  }
  if (root.classList.contains("light")) return "light";
  if (root.classList.contains("void")) return "void";
  if (root.classList.contains("cyberpunk")) return "cyberpunk";
  return "dark";
}

// ── Session management helpers ─────────────────────────────────────────

function detachSession(session: TermSession): void {
  try { session.term.element?.remove(); } catch { /* ignore */ }
  session.container = null;
  if (session.resizeObserver) {
    session.resizeObserver.disconnect();
    session.resizeObserver = null;
  }
}

function attachSession(session: TermSession, container: HTMLDivElement): void {
  session.container = container;
  container.innerHTML = "";
  if (session.term.element) {
    container.appendChild(session.term.element);
  } else {
    session.term.open(container);
  }
  requestAnimationFrame(() => { try { session.fitAddon.fit(); } catch { /* ignore */ } });
  const ro = new ResizeObserver(() => {
    if (session.container) { try { session.fitAddon.fit(); } catch { /* ignore */ } }
  });
  ro.observe(container);
  session.resizeObserver = ro;
}

async function createElectronSession(workspacePath: string): Promise<TermSession | null> {
  const codeOS = window.codeOS!;
  const ptySessionId = await codeOS.terminalCreate(workspacePath);
  if (!ptySessionId) return null;
  const themeName = getActiveThemeName();
  const term = new Terminal({
    theme: safeGetTheme(themeName), cursorBlink: true, cursorStyle: "block",
    fontSize: 13, fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace",
    allowTransparency: false, cols: 80, rows: 24,
  });
  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  const removeListener = codeOS.onTerminalOutput(ptySessionId, (data: string) => {
    try { term.write(data); } catch { /* ignore if disposed */ }
  });
  term.onData((data) => {
    const restricted = useWorkspaceStore.getState().restrictedMode;
    if (restricted) return;
    codeOS.terminalWrite(ptySessionId, data);
  });
  term.onResize(({ cols, rows }) => { codeOS.terminalResize(ptySessionId, cols, rows); });
  // Use the same ID the main process assigned so IPC routing stays consistent.
  const session: TermSession = {
    id: ptySessionId, name: "Terminal", cwd: workspacePath,
    term, fitAddon, container: null, resizeObserver: null, removeListener, ws: null,
  };
  sessions.set(ptySessionId, session);
  return session;
}

function createWebSocketSession(workspacePath: string): TermSession {
  const themeName = getActiveThemeName();
  const term = new Terminal({
    theme: safeGetTheme(themeName), cursorBlink: true, cursorStyle: "block",
    fontSize: 13, fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace",
    allowTransparency: false, cols: 80, rows: 24,
  });
  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  const sessionId = `term-ws-${++sessionIdCounter}`;
  const ws = new WebSocket(`ws://127.0.0.1:8000/api/terminal/ws?cwd=${encodeURIComponent(workspacePath)}&session_id=${sessionId}`);
  ws.onopen = () => { ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows })); };
  ws.onmessage = (event) => { try { term.write(event.data); } catch { /* ignore */ } };
  ws.onerror = () => { term.write("\r\n\x1b[31m[WebSocket connection error]\x1b[0m\r\n"); };
  ws.onclose = () => { term.write("\r\n\x1b[33m[Connection closed]\x1b[0m\r\n"); };
  term.onData((data) => {
    const restricted = useWorkspaceStore.getState().restrictedMode;
    if (restricted) return;
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "input", data }));
  });
  term.onResize(({ cols, rows }) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", cols, rows })); });
  const session: TermSession = {
    id: sessionId, name: "Terminal", cwd: workspacePath,
    term, fitAddon, container: null, resizeObserver: null, removeListener: null, ws,
  };
  sessions.set(sessionId, session);
  return session;
}

export function TerminalPanel({ onClose }: { onClose?: () => void }) {
  const terminalContainerRef = useRef<HTMLDivElement>(null);
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const [, forceUpdate] = useState(0);

  // Observe theme changes on <html>
  useEffect(() => {
    const observer = new MutationObserver(() => {
      const themeName = getActiveThemeName();
      const target = activeSessionId ? sessions.get(activeSessionId) : undefined;
      if (target) target.term.options.theme = safeGetTheme(themeName);
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => observer.disconnect();
  }, []);

  // Activate a session (detach current, attach new)
  const activateSession = useCallback((session: TermSession) => {
    const container = terminalContainerRef.current;
    if (!container) return;
    const current = activeSessionId ? sessions.get(activeSessionId) : undefined;
    if (current && current !== session) detachSession(current);
    activeSessionId = session.id;
    attachSession(session, container);
    forceUpdate((n) => n + 1);
  }, []);

  // Create or re-attach terminal when workspace changes
  useEffect(() => {
    const container = terminalContainerRef.current;
    if (!container || !workspace) return;
    const normPath = workspace.path.toLowerCase().replace(/\\/g, "/");
    const existing = Array.from(sessions.values()).find(
      (s) => s.cwd.toLowerCase().replace(/\\/g, "/") === normPath
    );
    if (existing) { activateSession(existing); return; }

    const initSession = async () => {
      let session: TermSession | null = null;
      if (window.codeOS) {
        session = await createElectronSession(workspace.path);
      } else {
        session = createWebSocketSession(workspace.path);
      }
      if (session) { activateSession(session); }
      else { container.innerHTML = '<div class="p-3 text-sm text-slate-500">Failed to create terminal session.</div>'; }
    };
    void initSession();

    return () => {
      const cur = activeSessionId ? sessions.get(activeSessionId) : undefined;
      if (cur) detachSession(cur);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.path]);

  const handleSwitchTab = (session: TermSession) => {
    activateSession(session);
  };

  const handleKill = () => {
    if (!activeSessionId) return;
    const session = sessions.get(activeSessionId);
    if (!session) return;
    session.removeListener?.();
    session.ws?.close();
    session.term.dispose();
    if (session.resizeObserver) {
      session.resizeObserver.disconnect();
      session.resizeObserver = null;
    }
    if (window.codeOS && session.removeListener) {
      window.codeOS.terminalKill(activeSessionId);
    }
    sessions.delete(activeSessionId);
    activeSessionId = null;
    const container = terminalContainerRef.current;
    if (container) { container.innerHTML = ""; }
    forceUpdate((n) => n + 1);
  };

  const handleNew = () => {
    const container = terminalContainerRef.current;
    if (!container || !workspace) return;
    const current = activeSessionId ? sessions.get(activeSessionId) : undefined;
    if (current) detachSession(current);
    activeSessionId = null;
    container.innerHTML = "";

    const initSession = async () => {
      let session: TermSession | null = null;
      if (window.codeOS) {
        session = await createElectronSession(workspace.path);
      } else {
        session = createWebSocketSession(workspace.path);
      }
      if (session) activateSession(session);
    };
    void initSession();
  };

  const sessionList = Array.from(sessions.values());

  const restrictedMode = useWorkspaceStore((state) => state.restrictedMode);

  return (
    <section data-testid="terminal-panel" className="grid h-full min-h-0 grid-rows-[36px_minmax(0,1fr)] bg-surface-container/80 backdrop-blur-xl border-t border-outline-variant/30 glass-edge">

      <div className="flex justify-between items-center px-4 h-9 border-b border-outline-variant/20 bg-surface-container-low/50 shrink-0 select-none">
        <div className="flex items-center gap-4">
          <button className="font-label-caps text-label-caps text-on-surface-variant hover:text-on-surface transition-colors">PROBLEMS</button>
          <button className="font-label-caps text-label-caps text-on-surface-variant hover:text-on-surface transition-colors">OUTPUT</button>
          <button className="font-label-caps text-label-caps text-primary-fixed-dim border-b border-primary-fixed-dim pb-0.5">TERMINAL</button>
          
          <div className="flex items-center gap-1 ml-2">
            {sessionList.map((session, index) => (
              <button
                key={session.id}
                className={`shrink-0 rounded px-2 py-0.5 font-label-caps text-label-caps transition-colors ${
                  session.id === activeSessionId
                    ? "bg-surface-container-high text-primary-fixed-dim"
                    : "text-on-surface-variant/60 hover:bg-surface-bright/20 hover:text-on-surface"
                }`}
                onClick={() => handleSwitchTab(session)}
              >
                {session.name === "Terminal" ? `#${index + 1}` : session.name}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button className="text-on-surface-variant hover:text-on-surface" onClick={handleNew} title="New terminal">
            <span className="material-symbols-outlined text-[16px]">add</span>
          </button>
          <button className="text-on-surface-variant hover:text-on-surface" onClick={handleKill} title="Kill terminal">
            <span className="material-symbols-outlined text-[16px]">delete</span>
          </button>
          {onClose && (
            <button className="text-on-surface-variant hover:text-on-surface ml-2" onClick={onClose} title="Collapse terminal">
              <span className="material-symbols-outlined text-[16px]">keyboard_arrow_down</span>
            </button>
          )}
        </div>
      </div>
      <div className="relative min-h-0 overflow-hidden" style={{ height: "100%" }}>
        {restrictedMode && (
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm z-30 flex flex-col items-center justify-center p-4 text-center select-none">
            <ShieldAlert size={28} className="text-amber-500 mb-2 animate-bounce" />
            <div className="text-xs font-bold text-white mb-1 uppercase tracking-wider">Terminal Execution Suspended</div>
            <p className="text-[10px] text-slate-400 max-w-xs leading-relaxed">
              This workspace is running in Restricted Mode. Terminal command execution and interactive inputs are blocked. Click the Restricted badge in the top bar to Trust this workspace.
            </p>
          </div>
        )}
        {!workspace ? (
          <div className="flex h-full flex-col items-center justify-center p-4 text-center space-y-2 bg-surface-dim select-none">
            <TermIcon size={22} className="text-on-surface-variant/60 dark:text-on-surface-variant/60 mb-1 animate-pulse" />
            <span className="text-xs text-on-surface-variant/60 dark:text-on-surface-variant/60">Open a workspace to start terminal session.</span>
          </div>
        ) : (
          <div
            ref={terminalContainerRef}
            className="h-full w-full p-2 bg-surface-950"
          />
        )}
      </div>
    </section>
  );
}
