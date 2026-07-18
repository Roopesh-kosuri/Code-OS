import { useEffect, useState } from "react";
import {
  Folder,
  Search as SearchIcon,
  GitBranch,
  Cpu,
  Zap,
  Gauge,
  Brain,
  Eye,
  FileDiff,
  Terminal as TermIcon,
  Bot,
  Settings as SettingsIcon,
} from "lucide-react";

import { AIChatPanel } from "../../features/ai/AIChatPanel";
import { EditorWorkspace } from "../../features/editor/EditorWorkspace";
import { FileExplorer } from "../../features/explorer/FileExplorer";
import { GitPanel } from "../../features/git/GitPanel";
import { SearchPanel } from "../../features/search/SearchPanel";
import { TerminalPanel } from "../../features/terminal/TerminalPanel";
import { TopBar } from "./TopBar";
import { RepoUnderstanding } from "../../features/explorer/RepoUnderstanding";
import { DiffViewer } from "../../features/ai/DiffViewer";
import { MemoryPanel } from "../../features/settings/MemoryPanel";
import { ContextPanel } from "../../features/ai/ContextPanel";
import { AgentConsole } from "../../features/ai/AgentConsole";
import { PerformanceDashboard } from "../../features/diagnostics/PerformanceDashboard";
import { DuoPanel } from "../../features/duo/DuoPanel";
import { WorkspaceTrustDialog } from "../../components/workspace/WorkspaceTrustDialog";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { SettingsModal } from "../settings/SettingsModal";
import { OpenFolderModal } from "../workspace/OpenFolderModal";

// ── Activity Bar Button Sub-component ────────────────────────────────────────

function ActivityBarButton({
  icon,
  label,
  active,
  onClick,
  id,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  id?: string;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div className="relative w-full flex justify-center py-0.5 select-none">
      <button
        id={id}
        onClick={onClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        className={`relative flex h-9 w-9 items-center justify-center rounded-lg transition-all duration-150 ${
          active
            ? "text-white bg-surface-800 shadow-md shadow-accent-500/5 cyberpunk-glow"
            : "text-slate-400 hover:text-slate-200 hover:bg-surface-850"
        }`}
        title={label}
        aria-label={label}
      >
        {active && (
          <span className="absolute left-0 top-2 bottom-2 w-[3px] bg-accent-500 rounded-r" />
        )}
        {icon}
      </button>

      {hovered && (
        <div className="absolute left-12 top-1.5 z-45 rounded bg-surface-950 px-2 py-1 text-[10px] text-slate-200 border border-surface-700 whitespace-nowrap shadow-lg select-none pointer-events-none">
          {label}
        </div>
      )}
    </div>
  );
}

// ── Main AppShell ─────────────────────────────────────────────────────────────

export function AppShell() {
  const [activeSidebar, setActiveSidebar] = useState(() => {
    return localStorage.getItem("code-os:layout-active-sidebar") || "explorer";
  });
  const [showSidebar, setShowSidebar] = useState(() => {
    return localStorage.getItem("code-os:layout-show-sidebar") !== "false";
  });
  const [showAIChat, setShowAIChat] = useState(() => {
    return localStorage.getItem("code-os:layout-show-ai-chat") !== "false";
  });
  const [showTerminal, setShowTerminal] = useState(() => {
    return localStorage.getItem("code-os:layout-show-terminal") !== "false";
  });
  const [showSettings, setShowSettings] = useState(false);
  const isOpeningFolder = useWorkspaceStore((state) => state.isOpeningFolder);
  const setOpeningFolder = useWorkspaceStore((state) => state.setOpeningFolder);
  const pendingWorkspacePath = useWorkspaceStore((state) => state.pendingWorkspacePath);
  const setWorkspaceTrust = useWorkspaceStore((state) => state.setWorkspaceTrust);
  const setRestrictedMode = useWorkspaceStore((state) => state.setRestrictedMode);
  const completeWorkspaceOpen = useWorkspaceStore((state) => state.completeWorkspaceOpen);

  // Sizes from localStorage
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    return Number(localStorage.getItem("code-os:layout-sidebar-width") ?? "290");
  });
  const [aiPanelWidth, setAiPanelWidth] = useState(() => {
    return Number(localStorage.getItem("code-os:layout-ai-width") ?? "340");
  });
  const [terminalHeight, setTerminalHeight] = useState(() => {
    return Number(localStorage.getItem("code-os:layout-terminal-height") ?? "240");
  });

  const [isResizing, setIsResizing] = useState<"sidebar" | "ai" | "terminal" | null>(null);

  // Listen for programmatic switchUtility/toggle explorer menu actions
  useEffect(() => {
    const listener = (event: Event) => {
      const action = (event as CustomEvent<string>).detail;
      if (action === "view.toggleExplorer") {
        setShowSidebar((v) => {
          const next = !v;
          localStorage.setItem("code-os:layout-show-sidebar", String(next));
          return next;
        });
        setActiveSidebar("explorer");
      }
      if (action === "view.toggleTerminal") {
        setShowTerminal((v) => {
          const next = !v;
          localStorage.setItem("code-os:layout-show-terminal", String(next));
          return next;
        });
      }
      if (action === "view.toggleAI") {
        setShowAIChat((v) => {
          const next = !v;
          localStorage.setItem("code-os:layout-show-ai-chat", String(next));
          return next;
        });
      }
      if (action.startsWith("view.switchUtility:")) {
        const util = action.substring("view.switchUtility:".length);
        setActiveSidebar(util);
        setShowSidebar(true);
        localStorage.setItem("code-os:layout-show-sidebar", "true");
        localStorage.setItem("code-os:layout-active-sidebar", util);
      }
    };
    window.addEventListener("code-os:menu", listener);
    return () => window.removeEventListener("code-os:menu", listener);
  }, []);

  // Listen for switch-utility events (e.g. from round cards or proposals list)
  useEffect(() => {
    const handler = (e: Event) => {
      const utility = (e as CustomEvent<string>).detail;
      setActiveSidebar(utility);
      setShowSidebar(true);
      localStorage.setItem("code-os:layout-show-sidebar", "true");
      localStorage.setItem("code-os:layout-active-sidebar", utility);
    };
    window.addEventListener("code-os:switch-utility", handler);
    return () => window.removeEventListener("code-os:switch-utility", handler);
  }, []);

  // Keyboard shortcut Ctrl+` for Terminal
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "`") {
        event.preventDefault();
        setShowTerminal((v) => {
          const next = !v;
          localStorage.setItem("code-os:layout-show-terminal", String(next));
          return next;
        });
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Drag resizers
  const handleSidebarMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing("sidebar");
    const startX = e.clientX;
    const startWidth = sidebarWidth;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const deltaX = moveEvent.clientX - startX;
      const newWidth = Math.max(180, Math.min(480, startWidth + deltaX));
      setSidebarWidth(newWidth);
      localStorage.setItem("code-os:layout-sidebar-width", String(newWidth));
    };

    const handleMouseUp = () => {
      setIsResizing(null);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  };

  const handleAIPanelMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing("ai");
    const startX = e.clientX;
    const startWidth = aiPanelWidth;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const deltaX = startX - moveEvent.clientX;
      const newWidth = Math.max(200, Math.min(500, startWidth + deltaX));
      setAiPanelWidth(newWidth);
      localStorage.setItem("code-os:layout-ai-width", String(newWidth));
    };

    const handleMouseUp = () => {
      setIsResizing(null);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  };

  const handleTerminalMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing("terminal");
    const startY = e.clientY;
    const startHeight = terminalHeight;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const deltaY = startY - moveEvent.clientY;
      const newHeight = Math.max(120, Math.min(550, startHeight + deltaY));
      setTerminalHeight(newHeight);
      localStorage.setItem("code-os:layout-terminal-height", String(newHeight));
    };

    const handleMouseUp = () => {
      setIsResizing(null);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  };

  const handleActivityClick = (util: string) => {
    if (activeSidebar === util && showSidebar) {
      setShowSidebar(false);
      localStorage.setItem("code-os:layout-show-sidebar", "false");
    } else {
      setActiveSidebar(util);
      setShowSidebar(true);
      localStorage.setItem("code-os:layout-show-sidebar", "true");
      localStorage.setItem("code-os:layout-active-sidebar", util);
    }
  };

  const toggleTerminalOff = () => {
    setShowTerminal(false);
    localStorage.setItem("code-os:layout-show-terminal", "false");
  };

  return (
    <div className="flex h-screen flex-col bg-surface-950 text-slate-100 select-none">
      <TopBar onOpenSettings={() => setShowSettings(true)} />

      {/* Resize Block Overlay */}
      {isResizing && (
        <div
          className={`fixed inset-0 z-50 ${
            isResizing === "terminal" ? "cursor-row-resize" : "cursor-col-resize"
          }`}
        />
      )}

      {/* Layout Split Container */}
      <div className="flex flex-1 min-h-0 w-full overflow-hidden">
        
        {/* 1. Left Activity Bar (48px Rail) */}
        <aside className="w-12 bg-surface-900 border-r border-surface-700 flex flex-col justify-between items-center py-2 shrink-0 z-20">
          <div className="flex flex-col gap-2 w-full items-center">
            <ActivityBarButton
              id="activity-btn-explorer"
              icon={<Folder size={18} />}
              label="File Explorer"
              active={showSidebar && activeSidebar === "explorer"}
              onClick={() => handleActivityClick("explorer")}
            />
            <ActivityBarButton
              id="activity-btn-search"
              icon={<SearchIcon size={18} />}
              label="Global Search"
              active={showSidebar && activeSidebar === "search"}
              onClick={() => handleActivityClick("search")}
            />
            <ActivityBarButton
              id="activity-btn-git"
              icon={<GitBranch size={18} />}
              label="Source Control (Git)"
              active={showSidebar && activeSidebar === "git"}
              onClick={() => handleActivityClick("git")}
            />
            <ActivityBarButton
              id="activity-btn-agent"
              icon={<Cpu size={18} />}
              label="Agent Console"
              active={showSidebar && activeSidebar === "agent"}
              onClick={() => handleActivityClick("agent")}
            />
            <ActivityBarButton
              id="activity-btn-duo"
              icon={<Zap size={18} />}
              label="Duo Loop"
              active={showSidebar && activeSidebar === "duo"}
              onClick={() => handleActivityClick("duo")}
            />
            <ActivityBarButton
              id="activity-btn-diagnostics"
              icon={<Gauge size={18} />}
              label="Diagnostics"
              active={showSidebar && activeSidebar === "diagnostics"}
              onClick={() => handleActivityClick("diagnostics")}
            />
            <ActivityBarButton
              id="activity-btn-memory"
              icon={<Brain size={18} />}
              label="AI Memory"
              active={showSidebar && activeSidebar === "memory"}
              onClick={() => handleActivityClick("memory")}
            />
            <ActivityBarButton
              id="activity-btn-context"
              icon={<Eye size={18} />}
              label="AI Context"
              active={showSidebar && activeSidebar === "context"}
              onClick={() => handleActivityClick("context")}
            />
            <ActivityBarButton
              id="activity-btn-diff"
              icon={<FileDiff size={18} />}
              label="AI Proposals"
              active={showSidebar && activeSidebar === "diff"}
              onClick={() => handleActivityClick("diff")}
            />
          </div>

          <div className="flex flex-col gap-2 w-full items-center">
            <ActivityBarButton
              id="activity-btn-terminal"
              icon={<TermIcon size={18} />}
              label="Toggle Terminal Panel"
              active={showTerminal}
              onClick={() => setShowTerminal((v) => {
                localStorage.setItem("code-os:layout-show-terminal", String(!v));
                return !v;
              })}
            />
            <ActivityBarButton
              id="activity-btn-aichat"
              icon={<Bot size={18} />}
              label="Toggle AI Chat Panel"
              active={showAIChat}
              onClick={() => setShowAIChat((v) => {
                localStorage.setItem("code-os:layout-show-ai-chat", String(!v));
                return !v;
              })}
            />
            <ActivityBarButton
              id="activity-btn-settings"
              icon={<SettingsIcon size={18} />}
              label="Open Settings"
              active={showSettings}
              onClick={() => setShowSettings(true)}
            />
          </div>
        </aside>

        {/* 2. Left Primary Sidebar (Explorer / Search / Git / Console / etc.) */}
        {showSidebar && (
          <>
            <aside
              className="min-h-0 bg-surface-900 flex flex-col shrink-0 overflow-hidden border-r border-surface-700/80 select-text"
              style={{ width: `${sidebarWidth}px` }}
            >
              <div className="flex-1 min-h-0">
                {activeSidebar === "explorer" && (
                  <div className="flex flex-col h-full overflow-hidden">
                    <FileExplorer />
                  </div>
                )}
                {activeSidebar === "git" && <GitPanel />}
                {activeSidebar === "search" && <SearchPanel />}
                {activeSidebar === "repo" && <RepoUnderstanding />}
                {activeSidebar === "diff" && <DiffViewer />}
                {activeSidebar === "memory" && <MemoryPanel />}
                {activeSidebar === "context" && <ContextPanel />}
                {activeSidebar === "agent" && <AgentConsole />}
                {activeSidebar === "diagnostics" && <PerformanceDashboard />}
                {activeSidebar === "duo" && <DuoPanel />}
              </div>
            </aside>
            {/* Draggable Resizer Handle */}
            <div
              className="w-[3px] hover:w-[5px] bg-surface-700/80 hover:bg-accent-500 cursor-col-resize shrink-0 transition-all duration-100 z-10 relative"
              onMouseDown={handleSidebarMouseDown}
            >
              <div className="absolute inset-y-0 -left-[5px] -right-[5px] cursor-col-resize" />
            </div>
          </>
        )}

        {/* 3. Central Editor and Terminal Area */}
        <main className="flex flex-col flex-1 min-h-0 bg-surface-950 overflow-hidden">
          <div className="flex-1 min-h-0 relative select-text">
            <EditorWorkspace />
          </div>
          
          {showTerminal && (
            <>
              {/* Bottom Resizer Handle */}
              <div
                className="h-[3px] hover:h-[5px] bg-surface-700/80 hover:bg-accent-500 cursor-row-resize shrink-0 transition-all duration-100 z-10 relative"
                onMouseDown={handleTerminalMouseDown}
              >
                <div className="absolute inset-x-0 -top-[5px] -bottom-[5px] cursor-row-resize" />
              </div>
              <div className="shrink-0 overflow-hidden select-text" style={{ height: `${terminalHeight}px` }} id="terminal-panel">
                <TerminalPanel onClose={toggleTerminalOff} />
              </div>
            </>
          )}
        </main>

        {/* 4. Right Resizable Independent AI Chat Panel */}
        {showAIChat && (
          <>
            {/* Draggable Resizer Handle */}
            <div
              className="w-[3px] hover:w-[5px] bg-surface-700/80 hover:bg-accent-500 cursor-col-resize shrink-0 transition-all duration-100 z-10 relative"
              onMouseDown={handleAIPanelMouseDown}
            >
              <div className="absolute inset-y-0 -left-[5px] -right-[5px] cursor-col-resize" />
            </div>
            <aside
              id="ai-chat-panel"
              className="min-h-0 bg-surface-900 flex flex-col justify-between shrink-0 overflow-hidden border-l border-surface-700/80 select-text"
              style={{ width: `${aiPanelWidth}px` }}
            >
              <AIChatPanel />
            </aside>
          </>
        )}

      </div>

      {/* Settings Page Overlay Modal */}
      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} />
      )}

      {/* Open Folder Overlay Modal */}
      {isOpeningFolder && (
        <OpenFolderModal onClose={() => setOpeningFolder(false)} />
      )}

      {/* Workspace Trust Dialog */}
      {pendingWorkspacePath && (
        <WorkspaceTrustDialog
          workspacePath={pendingWorkspacePath}
          onTrust={async () => {
            await setWorkspaceTrust(pendingWorkspacePath, true);
            await completeWorkspaceOpen(pendingWorkspacePath);
          }}
          onRestricted={async () => {
            await setWorkspaceTrust(pendingWorkspacePath, false);
            setRestrictedMode(true);
            await completeWorkspaceOpen(pendingWorkspacePath);
          }}
          onCancel={() => {
            setOpeningFolder(false);
          }}
        />
      )}
    </div>
  );
}
