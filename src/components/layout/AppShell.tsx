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
import { CodeVerifierPanel } from "../../features/verifier/CodeVerifierPanel";
import { DualCoderPanel } from "../../features/dual_coder/DualCoderPanel";
import { CoderAgentPanel } from "../../features/coder/CoderAgentPanel";
import { WorkspaceTrustDialog } from "../../components/workspace/WorkspaceTrustDialog";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { SettingsModal } from "../settings/SettingsModal";
import { OpenFolderModal } from "../workspace/OpenFolderModal";
import { WelcomeScreen } from "../workspace/WelcomeScreen";

// ── Activity Bar Button Sub-component ────────────────────────────────────────

function ActivityBarButton({
  iconName,
  label,
  active,
  onClick,
  id,
}: {
  iconName: string;
  label: string;
  active: boolean;
  onClick: () => void;
  id?: string;
}) {
  return (
    <button
      id={id}
      onClick={onClick}
      className={`w-full flex justify-center py-3 relative group transition-all duration-300 ease-in-out ${
        active
          ? "text-primary-container dark:text-primary-container border-l-2 border-primary-container bg-primary-container/10"
          : "text-on-surface-variant/60 dark:text-on-surface-variant/60 hover:text-primary dark:hover:text-primary-fixed-dim hover:bg-surface-variant/30"
      }`}
      title={label}
      aria-label={label}
    >
      <span 
        className="material-symbols-outlined text-[20px]" 
        style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
      >
        {iconName}
      </span>
      {/* Tooltip */}
      <div className="absolute left-16 top-1/2 -translate-y-1/2 bg-surface-container-highest border border-white/10 px-2.5 py-1 rounded-md shadow-2xl opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 font-label-caps text-label-caps text-on-surface font-semibold">
        {label}
      </div>
    </button>
  );
}

// ── Main AppShell ─────────────────────────────────────────────────────────────

export function AppShell() {
  const [activeTopView, setActiveTopView] = useState<"main" | "agent" | "coder" | "duo" | "dual-coder" | "verifier" | "diagnostics" | "proposals">("main");
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);

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
      if (action.startsWith("view.switchTopView:")) {
        const topView = action.substring("view.switchTopView:".length) as any;
        setActiveTopView(topView);
      }
    };
    window.addEventListener("code-os:menu", listener);
    return () => window.removeEventListener("code-os:menu", listener);
  }, []);

  // Listen for switch-top-view events (e.g. switching to proposals tab from Duo Loop)
  useEffect(() => {
    const handler = (e: Event) => {
      const view = (e as CustomEvent<string>).detail;
      if (["main", "agent", "duo", "diagnostics", "proposals"].includes(view)) {
        setActiveTopView(view as any);
      }
    };
    window.addEventListener("code-os:switch-top-view", handler);
    return () => window.removeEventListener("code-os:switch-top-view", handler);
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
      const newWidth = Math.max(260, Math.min(480, startWidth + deltaX));
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
    setActiveTopView("main");
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
    <div className="flex h-screen flex-col bg-background text-on-background selection:bg-primary-container/30 select-none">
      <TopBar 
        onOpenSettings={() => setShowSettings(true)}
        activeView={activeTopView}
        onViewChange={(v) => setActiveTopView(v as "main" | "agent" | "duo" | "diagnostics" | "proposals")}
      />

      {/* Resize Block Overlay */}
      {isResizing && (
        <div
          className={`fixed inset-0 z-50 ${
            isResizing === "terminal" ? "cursor-row-resize" : "cursor-col-resize"
          }`}
        />
      )}

      {/* Layout Container */}
      <div className="flex flex-1 min-h-0 w-full overflow-hidden">
        <div className={activeTopView === "agent" ? "flex-1 p-3 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <AgentConsole />
        </div>

        <div className={activeTopView === "coder" ? "flex-1 p-3 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <CoderAgentPanel />
        </div>

        <div className={activeTopView === "duo" ? "flex-1 p-3 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <DuoPanel />
        </div>

        <div className={activeTopView === "dual-coder" ? "flex-1 p-3 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <DualCoderPanel />
        </div>

        <div className={activeTopView === "verifier" ? "flex-1 p-3 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <CodeVerifierPanel />
        </div>

        <div className={activeTopView === "diagnostics" ? "flex-1 p-3 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <PerformanceDashboard />
        </div>

        <div className={activeTopView === "proposals" ? "flex-1 p-3 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <DiffViewer />
        </div>

        <div className={activeTopView === "main" ? "flex flex-1 min-h-0 w-full overflow-hidden h-full" : "hidden"}>
          {!currentWorkspace ? (
            <WelcomeScreen />
          ) : (
            <>
            {/* 1. Left Activity Bar (56px Rail) */}
            <aside className="glass-panel border-r border-outline-variant/20 flex flex-col justify-between items-center py-4 shrink-0 z-20 w-nav-rail-width">
              <div className="flex flex-col gap-1 w-full items-center">
                <ActivityBarButton
                  id="activity-btn-explorer"
                  iconName="folder_open"
                  label="File Explorer"
                  active={showSidebar && activeSidebar === "explorer"}
                  onClick={() => handleActivityClick("explorer")}
                />
                <ActivityBarButton
                  id="activity-btn-search"
                  iconName="search"
                  label="Global Search"
                  active={showSidebar && activeSidebar === "search"}
                  onClick={() => handleActivityClick("search")}
                />
                <ActivityBarButton
                  id="activity-btn-git"
                  iconName="conversion_path"
                  label="Source Control (Git)"
                  active={showSidebar && activeSidebar === "git"}
                  onClick={() => handleActivityClick("git")}
                />
                <ActivityBarButton
                  id="activity-btn-agent"
                  iconName="smart_toy"
                  label="Agent Console"
                  active={showSidebar && activeSidebar === "agent"}
                  onClick={() => handleActivityClick("agent")}
                />
                <ActivityBarButton
                  id="activity-btn-duo"
                  iconName="loop"
                  label="Duo Loop"
                  active={showSidebar && activeSidebar === "duo"}
                  onClick={() => handleActivityClick("duo")}
                />
                <ActivityBarButton
                  id="activity-btn-diagnostics"
                  iconName="monitoring"
                  label="Diagnostics"
                  active={showSidebar && activeSidebar === "diagnostics"}
                  onClick={() => handleActivityClick("diagnostics")}
                />
                <ActivityBarButton
                  id="activity-btn-diff"
                  iconName="extension"
                  label="AI Proposals"
                  active={showSidebar && activeSidebar === "diff"}
                  onClick={() => handleActivityClick("diff")}
                />
              </div>

              <div className="flex flex-col gap-1 w-full items-center mt-auto">
                <ActivityBarButton
                  id="activity-btn-terminal"
                  iconName="terminal"
                  label="Toggle Terminal Panel"
                  active={showTerminal}
                  onClick={() => setShowTerminal((v) => {
                    localStorage.setItem("code-os:layout-show-terminal", String(!v));
                    return !v;
                  })}
                />
                <ActivityBarButton
                  id="activity-btn-aichat"
                  iconName="auto_awesome"
                  label="Toggle AI Chat Panel"
                  active={showAIChat}
                  onClick={() => setShowAIChat((v) => {
                    localStorage.setItem("code-os:layout-show-ai-chat", String(!v));
                    return !v;
                  })}
                />
                <ActivityBarButton
                  id="activity-btn-settings"
                  iconName="settings"
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
                  className="glass-panel min-h-0 flex flex-col shrink-0 overflow-hidden border-r border-outline-variant/20 select-text"
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
                    {activeSidebar === "agent" && <AgentConsole compact />}
                    {activeSidebar === "diagnostics" && <PerformanceDashboard />}
                    {activeSidebar === "duo" && <DuoPanel compact />}
                  </div>
                </aside>
                {/* Draggable Resizer Handle */}
                <div
                  className="codeos-resizer w-[3px] hover:w-[5px] cursor-col-resize shrink-0 z-10 relative"
                  onMouseDown={handleSidebarMouseDown}
                >
                  <div className="absolute inset-y-0 -left-[5px] -right-[5px] cursor-col-resize" />
                </div>
              </>
            )}

            {/* 3. Central Editor and Terminal Area */}
            <main className="bg-surface flex flex-col flex-1 min-h-0 overflow-hidden">
              <div className="flex-1 min-h-0 relative select-text">
                <EditorWorkspace />
              </div>
              
              {showTerminal && (
                <>
                  {/* Bottom Resizer Handle */}
                  <div
                    className="codeos-resizer h-[3px] hover:h-[5px] cursor-row-resize shrink-0 z-10 relative"
                    onMouseDown={handleTerminalMouseDown}
                  >
                    <div className="absolute inset-x-0 -top-[5px] -bottom-[5px] cursor-row-resize" />
                  </div>
                  <div className="glass-panel shrink-0 overflow-hidden select-text" style={{ height: `${terminalHeight}px` }} id="terminal-panel">
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
                  className="codeos-resizer w-[3px] hover:w-[5px] cursor-col-resize shrink-0 z-10 relative"
                  onMouseDown={handleAIPanelMouseDown}
                >
                  <div className="absolute inset-y-0 -left-[5px] -right-[5px] cursor-col-resize" />
                </div>
                <aside
                  id="ai-chat-panel"
                  className="glass-panel min-h-0 flex flex-col justify-between shrink-0 overflow-hidden border-l border-outline-variant/20 select-text glass-edge z-30"
                  style={{ width: `${aiPanelWidth}px` }}
                >
                  <AIChatPanel />
                </aside>
              </>
            )}
          </>
        )}
      </div>
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
            useWorkspaceStore.setState({ pendingWorkspacePath: null, isOpeningFolder: false });
          }}

        />
      )}
    </div>
  );
}
