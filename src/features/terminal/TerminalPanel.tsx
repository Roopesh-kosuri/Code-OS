import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Square, X, ShieldAlert, Terminal as TermIcon } from "lucide-react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

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

function getTheme(isLight: boolean) {
  return {
    background: isLight ? "#ffffff" : "#101215",
    foreground: isLight ? "#1f2328" : "#e2e8f0",
    cursor: isLight ? "#1f2328" : "#45b3e7",
    selectionBackground: isLight ? "#d0d7de" : "#303843",
    black: "#1b2027", red: "#e25c5c", green: "#42c77b", yellow: "#f3b44e",
    blue: "#45b3e7", magenta: "#c084fc", cyan: "#2dd4bf",
    white: isLight ? "#1f2328" : "#e2e8f0",
    brightBlack: "#64748b", brightRed: "#e25c5c", brightGreen: "#42c77b",
    brightYellow: "#f3b44e", brightBlue: "#45b3e7", brightMagenta: "#c084fc",
    brightCyan: "#2dd4bf", brightWhite: isLight ? "#1f2328" : "#f1f5f9",
  };
}

function getActiveTheme(): boolean {
  return document.documentElement.classList.contains("light");
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
  session.term.open(container);
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
  const isLight = getActiveTheme();
  const term = new Terminal({
    theme: getTheme(isLight), cursorBlink: true, cursorStyle: "block",
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
  const isLight = getActiveTheme();
  const term = new Terminal({
    theme: getTheme(isLight), cursorBlink: true, cursorStyle: "block",
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
      const isLight = getActiveTheme();
      const target = activeSessionId ? sessions.get(activeSessionId) : undefined;
      if (target) target.term.options.theme = getTheme(isLight);
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
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
    <section className="grid h-full min-h-0 grid-rows-[36px_minmax(0,1fr)] border-t border-surface-700 bg-surface-950">
      <div className="flex items-center justify-between border-b border-surface-800 px-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="shrink-0 text-xs font-semibold uppercase tracking-wider text-slate-400">Terminal</span>
          <div className="flex items-center gap-0.5 overflow-x-auto">
            {sessionList.map((session, index) => (
              <button
                key={session.id}
                className={`shrink-0 rounded px-2 py-1 text-xs transition-colors ${
                  session.id === activeSessionId
                    ? "bg-surface-700 text-white"
                    : "text-slate-400 hover:bg-surface-800 hover:text-slate-200"
                }`}
                onClick={() => handleSwitchTab(session)}
              >
                {session.name === "Terminal" ? `#${index + 1}` : session.name}
              </button>
            ))}
          </div>
          {activeSessionId ? (
            <span className="hidden lg:block max-w-[320px] truncate text-xs text-slate-500 ml-1">
              {sessions.get(activeSessionId)?.cwd ?? ""}
            </span>
          ) : null}
        </div>
        <div className="flex gap-1 shrink-0">
          <IconButton label="New terminal" icon={<Plus size={15} />} onClick={handleNew} disabled={!workspace} />
          <IconButton label="Kill terminal" icon={<Square size={15} />} onClick={handleKill} disabled={!activeSessionId} />
          {onClose && <IconButton label="Collapse terminal" icon={<X size={15} />} onClick={onClose} />}
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
          <div className="flex h-full flex-col items-center justify-center p-4 text-center space-y-2 bg-surface-950 select-none">
            <TermIcon size={22} className="text-slate-600 mb-1 animate-pulse" />
            <span className="text-xs text-slate-500">Open a workspace to start terminal session.</span>
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