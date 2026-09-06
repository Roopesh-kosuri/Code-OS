/**
 * AgenticTerminalPanel.tsx — Live Agentic Terminal Emulator Component.
 *
 * Features:
 * - Real-time terminal streaming of agent commands and stdout/stderr
 * - Powered by @xterm/xterm + @xterm/addon-fit
 * - Cyan agent prompt: "agent@code-os:~$ <command>"
 * - White stdout, red stderr, green/red exit badges
 * - Controls: Session switcher, Kill Process (SIGINT), Clear, Close, New Session
 * - Auto-reconnection & auto-scroll
 */

import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  Terminal as TermIcon,
  Square,
  Trash2,
  X,
  Plus,
  Circle,
  Clock,
  Activity,
  ChevronDown,
} from "lucide-react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

import {
  useAgenticTerminalStore,
  TerminalEvent,
  AgenticTerminalSession,
} from "./agenticTerminalStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

interface AgenticTerminalPanelProps {
  compact?: boolean;
}

export const AgenticTerminalPanel: React.FC<AgenticTerminalPanelProps> = ({ compact = false }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);

  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const workspacePath = currentWorkspace?.path || ".";

  const {
    sessions,
    activeTerminalId,
    streamingOutputs,
    isProcessRunning,
    isLoading,
    createSession,
    setActiveTerminal,
    sendSignal,
    closeSession,
    clearTerminal,
    fetchActiveSessions,
    connectStream,
  } = useAgenticTerminalStore();

  const [isKilling, setIsKilling] = useState(false);

  // Active session object
  const activeSession: AgenticTerminalSession | null =
    activeTerminalId && sessions[activeTerminalId] ? sessions[activeTerminalId] : null;

  const isRunning = Boolean(activeTerminalId && isProcessRunning[activeTerminalId]);
  const activeEvents = activeTerminalId && streamingOutputs[activeTerminalId] ? streamingOutputs[activeTerminalId] : [];

  // Initialize terminal sessions on mount
  useEffect(() => {
    fetchActiveSessions();
  }, [fetchActiveSessions]);

  // Create default session if none exists
  useEffect(() => {
    const activeList = Object.values(sessions).filter((s) => s.status !== "closed");
    if (activeList.length === 0 && !activeTerminalId && !isLoading) {
      createSession("default_agent", workspacePath).catch(() => {});
    }
  }, [sessions, activeTerminalId, isLoading, createSession, workspacePath]);

  // Write an event to xterm
  const writeEventToTerminal = useCallback((term: Terminal, event: TerminalEvent) => {
    switch (event.type) {
      case "connected":
        term.write(`\r\n\x1b[90m[Connected to Agentic Terminal: ${event.terminal_id || ""}]\x1b[0m\r\n`);
        break;
      case "input":
        term.write(
          `\r\n\x1b[1;36magent@code-os\x1b[0m:\x1b[1;34m~$\x1b[0m \x1b[1;37m${event.command || ""}\x1b[0m\r\n`
        );
        break;
      case "output":
        if (event.stream === "stderr") {
          term.write(`\x1b[31m${event.line || ""}\x1b[0m\r\n`);
        } else {
          term.write(`${event.line || ""}\r\n`);
        }
        break;
      case "exit":
        if (event.code === 0) {
          term.write(
            `\x1b[32m✔ Process exited with code 0 (${event.duration_ms || 0}ms)\x1b[0m\r\n`
          );
        } else {
          term.write(
            `\x1b[31m✘ Process exited with code ${event.code} (${event.duration_ms || 0}ms)\x1b[0m\r\n`
          );
        }
        break;
      case "session_closed":
        term.write(`\r\n\x1b[33m[Session closed]\x1b[0m\r\n`);
        break;
      case "error":
        term.write(`\r\n\x1b[31m[Error: ${event.message || "Unknown error"}]\x1b[0m\r\n`);
        break;
      default:
        break;
    }
  }, []);

  // Initialize and mount xterm
  useEffect(() => {
    if (!containerRef.current) return;

    // Dispose prior instance
    if (terminalRef.current) {
      terminalRef.current.dispose();
      terminalRef.current = null;
    }

    const term = new Terminal({
      theme: {
        background: "#0a0a0c",
        foreground: "#e5e2e3",
        cursor: "#00e5ff",
        selectionBackground: "rgba(0, 229, 255, 0.25)",
        black: "#1b2027",
        red: "#ff5555",
        green: "#50fa7b",
        yellow: "#f1fa8c",
        blue: "#00daf3",
        magenta: "#ff79c6",
        cyan: "#8be9fd",
        white: "#f8f8f2",
        brightBlack: "#6272a4",
        brightRed: "#ff6e6e",
        brightGreen: "#69ff94",
        brightYellow: "#ffffa5",
        brightBlue: "#d6acff",
        brightMagenta: "#ff92df",
        brightCyan: "#a4ffff",
        brightWhite: "#ffffff",
      },
      cursorBlink: true,
      cursorStyle: "block",
      fontSize: 12,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace",
      allowTransparency: true,
      rows: 24,
      cols: 80,
      convertEol: true,
      scrollback: 5000,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);

    containerRef.current.innerHTML = "";
    term.open(containerRef.current);

    terminalRef.current = term;
    fitAddonRef.current = fitAddon;

    try {
      fitAddon.fit();
    } catch {
      // ignore
    }

    // Welcome message
    term.write("\x1b[1;36mCODE OS Agentic Terminal\x1b[0m — Real-time Agent Command Inspector\r\n");
    term.write("\x1b[90mListening for agent command executions and streaming stdout/stderr...\x1b[0m\r\n\r\n");

    // Replay existing events for the active session
    if (activeTerminalId && streamingOutputs[activeTerminalId]) {
      for (const ev of streamingOutputs[activeTerminalId]) {
        writeEventToTerminal(term, ev);
      }
    }

    // Resize handling
    const ro = new ResizeObserver(() => {
      try {
        fitAddon.fit();
      } catch {
        // ignore
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      term.dispose();
      terminalRef.current = null;
      fitAddonRef.current = null;
    };
  }, [activeTerminalId, writeEventToTerminal]);

  // Connect SSE stream when active terminal changes
  useEffect(() => {
    if (!activeTerminalId) return;

    const cleanup = connectStream(activeTerminalId, (event) => {
      if (terminalRef.current) {
        writeEventToTerminal(terminalRef.current, event);
      }
    });

    return () => {
      cleanup();
    };
  }, [activeTerminalId, connectStream, writeEventToTerminal]);

  // Handle Kill Process
  const handleKillProcess = async () => {
    if (!activeTerminalId || !isRunning) return;
    setIsKilling(true);
    try {
      await sendSignal(activeTerminalId, "SIGINT");
      if (terminalRef.current) {
        terminalRef.current.write("\r\n\x1b[33m[Sent SIGINT to process]\x1b[0m\r\n");
      }
    } finally {
      setIsKilling(false);
    }
  };

  // Handle Clear Terminal
  const handleClear = () => {
    if (activeTerminalId) {
      clearTerminal(activeTerminalId);
    }
    if (terminalRef.current) {
      terminalRef.current.clear();
      terminalRef.current.write("\x1b[90m[Terminal cleared]\x1b[0m\r\n");
    }
  };

  // Handle Close Session
  const handleClose = async () => {
    if (!activeTerminalId) return;
    await closeSession(activeTerminalId);
  };

  // Handle New Session
  const handleNewSession = async () => {
    await createSession(`agent_${Date.now()}`, workspacePath);
  };

  const activeSessionsList = Object.values(sessions).filter((s) => s.status !== "closed");

  return (
    <div
      data-testid="agentic-terminal-panel"
      className="flex flex-col h-full w-full bg-[#0a0a0c] text-on-surface border border-surface-container-high/40 rounded-lg overflow-hidden select-text"
    >
      {/* ── Top Controls Bar ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-2 bg-surface-container-low border-b border-surface-container-high/40 select-none">
        <div className="flex items-center space-x-2.5">
          {/* Terminal Icon & Title */}
          <div className="flex items-center space-x-1.5 text-primary">
            <TermIcon className="w-4 h-4 text-cyan-400" />
            <span className="font-semibold text-xs text-on-surface">Agent Terminal</span>
          </div>

          {/* Session Switcher Dropdown */}
          <div className="relative flex items-center">
            <select
              data-testid="terminal-session-selector"
              aria-label="Select Terminal Session"
              className="bg-surface-container border border-surface-container-high text-on-surface text-xs rounded px-2 py-1 focus:outline-none focus:border-primary cursor-pointer pr-6 appearance-none font-mono"
              value={activeTerminalId || ""}
              onChange={(e) => setActiveTerminal(e.target.value)}
            >
              {activeSessionsList.length === 0 ? (
                <option value="">No active sessions</option>
              ) : (
                activeSessionsList.map((sess) => (
                  <option key={sess.terminal_id} value={sess.terminal_id}>
                    {sess.terminal_id} ({sess.job_id})
                  </option>
                ))
              )}
            </select>
            <ChevronDown className="w-3 h-3 text-on-surface-variant absolute right-2 pointer-events-none" />
          </div>

          {/* Status Badge */}
          <div
            data-testid="terminal-status-badge"
            className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-medium ${
              isRunning
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30 animate-pulse"
                : activeSession?.status === "closed"
                ? "bg-red-500/10 text-red-400 border border-red-500/20"
                : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
            }`}
          >
            <Circle className={`w-1.5 h-1.5 fill-current ${isRunning ? "text-amber-400" : "text-emerald-400"}`} />
            <span>{isRunning ? "Running" : activeSession?.status === "closed" ? "Closed" : "Idle"}</span>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center space-x-1.5">
          {/* Kill Process Button */}
          <button
            data-testid="kill-process-btn"
            onClick={handleKillProcess}
            disabled={!isRunning || isKilling}
            title="Kill active process (SIGINT)"
            className={`inline-flex items-center space-x-1 px-2 py-1 rounded text-xs transition-colors ${
              isRunning
                ? "bg-red-500/20 text-red-300 hover:bg-red-500/30 border border-red-500/40 cursor-pointer"
                : "bg-surface-variant/20 text-on-surface-variant/40 border border-transparent cursor-not-allowed opacity-50"
            }`}
          >
            <Square className="w-3 h-3 fill-current" />
            <span className="hidden sm:inline">Kill Process</span>
          </button>

          {/* Clear Button */}
          <button
            data-testid="clear-terminal-btn"
            onClick={handleClear}
            title="Clear terminal buffer"
            className="p-1 rounded text-on-surface-variant hover:text-on-surface hover:bg-surface-variant/40 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>

          {/* New Session Button */}
          <button
            data-testid="new-terminal-btn"
            onClick={handleNewSession}
            title="Open new agent terminal"
            className="p-1 rounded text-on-surface-variant hover:text-cyan-400 hover:bg-cyan-500/10 transition-colors"
          >
            <Plus className="w-4 h-4" />
          </button>

          {/* Close Session Button */}
          <button
            data-testid="close-terminal-btn"
            onClick={handleClose}
            disabled={!activeTerminalId}
            title="Close this terminal session"
            className="p-1 rounded text-on-surface-variant hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-40"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── Terminal Emulator Container ─────────────────────────────────── */}
      <div className="flex-1 min-h-0 relative p-2 bg-[#0a0a0c]">
        <div
          data-testid="xterm-container"
          ref={containerRef}
          className="w-full h-full overflow-hidden font-mono"
        />

        {/* Hidden accessible DOM feed for unit test validation */}
        <div
          data-testid="terminal-output-feed"
          className="sr-only"
          aria-live="polite"
        >
          {activeEvents.map((ev, idx) => (
            <div key={idx} data-type={ev.type} data-stream={ev.stream}>
              {ev.type === "input" && `agent@code-os:~$ ${ev.command}`}
              {ev.type === "output" && ev.line}
              {ev.type === "exit" && `Process exited with code ${ev.code}`}
            </div>
          ))}
        </div>
      </div>

      {/* ── Bottom Status Bar ───────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1 bg-surface-container-lowest border-t border-surface-container-high/30 text-[10px] text-on-surface-variant font-mono">
        <div className="flex items-center space-x-3">
          <span>Session: {activeTerminalId || "none"}</span>
          <span>Workspace: {activeSession?.workspace || workspacePath}</span>
        </div>
        <div className="flex items-center space-x-3">
          <span>History: {activeSession?.history?.length || 0} commands</span>
          <span className="text-cyan-400 font-medium">SSE Stream Connected</span>
        </div>
      </div>
    </div>
  );
};
