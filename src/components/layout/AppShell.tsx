import { useEffect, useState } from "react";
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
      className={`w-full flex justify-center py-2.5 relative group transition-all duration-200 ease-in-out cursor-pointer ${
        active
          ? "text-primary border-l-2 border-primary bg-primary/10"
          : "text-on-surface-variant hover:bg-surface-variant/40 hover:text-on-surface"
      }`}
      title={label}
      aria-label={label}
    >
      <span
        className="material-symbols-outlined text-[20px] group-hover:scale-105 transition-transform"
        style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
      >
        {iconName}
      </span>
      {/* Tooltip */}
      <div className="absolute left-14 bg-surface-container-high border border-outline-variant/30 text-on-surface px-2.5 py-1 rounded-md font-caption text-caption opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 shadow-xl">
        {label}
      </div>
    </button>
  );
}

// ── Main AppShell ─────────────────────────────────────────────────────────────

export function AppShell({ backendDown = false }: { backendDown?: boolean }) {
  const [activeTopView, setActiveTopView] = useState<"main" | "agent" | "duo" | "verifier" | "diagnostics" | "proposals">("main");
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
    return Number(localStorage.getItem("code-os:layout-sidebar-width") ?? "220");
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
      if (action === "settings") {
        setShowSettings(true);
      }
    };

    window.addEventListener("code-os:switch-utility", listener);
    return () => window.removeEventListener("code-os:switch-utility", listener);
  }, []);

  const handleActivityClick = (sidebarId: string) => {
    if (activeSidebar === sidebarId && showSidebar) {
      setShowSidebar(false);
      localStorage.setItem("code-os:layout-show-sidebar", "false");
    } else {
      setActiveSidebar(sidebarId);
      setShowSidebar(true);
      localStorage.setItem("code-os:layout-show-sidebar", "true");
      localStorage.setItem("code-os:layout-active-sidebar", sidebarId);
    }
  };

  // Resizing handlers
  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (isResizing === "sidebar") {
        const newWidth = Math.max(160, Math.min(450, e.clientX - 64));
        setSidebarWidth(newWidth);
        localStorage.setItem("code-os:layout-sidebar-width", String(newWidth));
      } else if (isResizing === "ai") {
        const newWidth = Math.max(260, Math.min(600, window.innerWidth - e.clientX));
        setAiPanelWidth(newWidth);
        localStorage.setItem("code-os:layout-ai-width", String(newWidth));
      } else if (isResizing === "terminal") {
        const newHeight = Math.max(100, Math.min(600, window.innerHeight - e.clientY));
        setTerminalHeight(newHeight);
        localStorage.setItem("code-os:layout-terminal-height", String(newHeight));
      }
    };

    const handleMouseUp = () => {
      setIsResizing(null);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-background text-on-surface font-ui-label-reg text-ui-label-reg select-none antialiased">
      {/* ── Top Bar ────────────────────────────────────────────────────────── */}
      <TopBar
        onOpenSettings={() => setShowSettings(true)}
        activeView={activeTopView}
        onViewChange={(v) => setActiveTopView(v as any)}
      />

      {/* Resize Cover */}
      {isResizing && (
        <div
          className={`fixed inset-0 z-50 ${
            isResizing === "terminal" ? "cursor-row-resize" : "cursor-col-resize"
          }`}
        />
      )}

      {/* ── Main View Container ────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 w-full overflow-hidden">
        {/* Agent Console View */}
        <div className={activeTopView === "agent" ? "flex-1 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <AgentConsole />
        </div>

        {/* Duo Loop View */}
        <div className={activeTopView === "duo" ? "flex-1 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <DuoPanel />
        </div>

        {/* Code Verifier View */}
        <div className={activeTopView === "verifier" ? "flex-1 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <CodeVerifierPanel />
        </div>

        {/* Diagnostics View */}
        <div className={activeTopView === "diagnostics" ? "flex-1 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <PerformanceDashboard />
        </div>

        {/* Proposals View */}
        <div className={activeTopView === "proposals" ? "flex-1 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <DiffViewer />
        </div>

        {/* Main Editor View */}
        <div className={activeTopView === "main" ? "flex flex-1 min-h-0 w-full overflow-hidden h-full p-panel-gap gap-panel-gap" : "hidden"}>
          {!currentWorkspace ? (
            <WelcomeScreen backendDown={backendDown} />
          ) : (
            <>
              {/* 1. Side Navigation Rail (w-16) */}
              <aside className="bg-surface-container-low flex flex-col items-center py-4 space-y-6 h-full w-16 rounded-xl flex-shrink-0 border border-surface-container-high transition-all duration-200 ease-in-out">
                <div className="flex-1 flex flex-col items-center space-y-4 w-full mt-2">
                  <ActivityBarButton
                    id="activity-btn-explorer"
                    iconName="folder"
                    label="Explorer"
                    active={showSidebar && activeSidebar === "explorer"}
                    onClick={() => handleActivityClick("explorer")}
                  />
                  <ActivityBarButton
                    id="activity-btn-search"
                    iconName="search"
                    label="Search"
                    active={showSidebar && activeSidebar === "search"}
                    onClick={() => handleActivityClick("search")}
                  />
                  <ActivityBarButton
                    id="activity-btn-git"
                    iconName="account_tree"
                    label="Source Control"
                    active={showSidebar && activeSidebar === "git"}
                    onClick={() => handleActivityClick("git")}
                  />
                  <ActivityBarButton
                    id="activity-btn-run"
                    iconName="play_arrow"
                    label="Run & Debug"
                    active={showTerminal}
                    onClick={() => setShowTerminal((v) => {
                      localStorage.setItem("code-os:layout-show-terminal", String(!v));
                      return !v;
                    })}
                  />
                  <ActivityBarButton
                    id="activity-btn-agent"
                    iconName="smart_toy"
                    label="Agent Mode"
                    active={showSidebar && activeSidebar === "agent"}
                    onClick={() => handleActivityClick("agent")}
                  />
                  <ActivityBarButton
                    id="activity-btn-extensions"
                    iconName="extension"
                    label="Extensions"
                    active={showSidebar && activeSidebar === "diagnostics"}
                    onClick={() => handleActivityClick("diagnostics")}
                  />
                </div>

                <div className="flex flex-col items-center space-y-4 w-full pb-2 border-t border-surface-variant pt-4">
                  <ActivityBarButton
                    id="activity-btn-aichat"
                    iconName="auto_awesome"
                    label="Toggle Rony Agent Panel"
                    active={showAIChat}
                    onClick={() => setShowAIChat((v) => {
                      localStorage.setItem("code-os:layout-show-ai-chat", String(!v));
                      return !v;
                    })}
                  />
                  <ActivityBarButton
                    id="activity-btn-settings"
                    iconName="settings"
                    label="Settings"
                    active={showSettings}
                    onClick={() => setShowSettings(true)}
                  />
                </div>
              </aside>

              {/* 2. Collapsible Primary Sidebar (Explorer, Search, Git, etc.) */}
              {showSidebar && (
                <>
                  <aside
                    className="bg-surface-container-low rounded-xl flex flex-col overflow-hidden flex-shrink-0 border border-surface-container-high shadow-lg"
                    style={{ width: `${sidebarWidth}px` }}
                  >
                    <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                      {activeSidebar === "explorer" && <FileExplorer />}
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

                  {/* Resizer Sidebar */}
                  <div
                    onMouseDown={() => setIsResizing("sidebar")}
                    className="w-1 cursor-col-resize hover:bg-primary transition-colors flex-shrink-0"
                  />
                </>
              )}

              {/* 3. Center Column: Monaco Editor + Terminal */}
              <main className="flex-1 flex flex-col min-w-0 h-full overflow-hidden rounded-xl border border-surface-container-low shadow-[inset_0_0_40px_rgba(0,0,0,0.5)]">
                {/* Editor Workspace */}
                <div className="flex-1 min-h-0 overflow-hidden bg-[#0a0a0c]">
                  <EditorWorkspace />
                </div>

                {/* Resizer Terminal */}
                {showTerminal && (
                  <div
                    onMouseDown={() => setIsResizing("terminal")}
                    className="h-1 cursor-row-resize hover:bg-primary transition-colors flex-shrink-0"
                  />
                )}

                {/* Terminal Panel */}
                {showTerminal && (
                  <div
                    className="flex-shrink-0 overflow-hidden border-t border-surface-variant bg-[#0a0a0c]"
                    style={{ height: `${terminalHeight}px` }}
                  >
                    <TerminalPanel />
                  </div>
                )}
              </main>

              {/* 4. Resizer AI Chat */}
              {showAIChat && (
                <div
                  onMouseDown={() => setIsResizing("ai")}
                  className="w-1 cursor-col-resize hover:bg-primary transition-colors flex-shrink-0"
                />
              )}

              {/* 5. Right Column: Duo AI Assistant Chat Panel */}
              {showAIChat && (
                <aside
                  className="bg-surface-container-low rounded-xl flex flex-col overflow-hidden flex-shrink-0 border border-surface-container-high shadow-lg"
                  style={{ width: `${aiPanelWidth}px` }}
                >
                  <AIChatPanel />
                </aside>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Modals & Dialogs ────────────────────────────────────────────────── */}
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
      {isOpeningFolder && <OpenFolderModal onClose={() => setOpeningFolder(false)} />}
      {pendingWorkspacePath && (
        <WorkspaceTrustDialog
          workspacePath={pendingWorkspacePath}
          onCancel={() => useWorkspaceStore.setState({ pendingWorkspacePath: null })}
          onTrust={() => {
            void setWorkspaceTrust(pendingWorkspacePath, true);
            void completeWorkspaceOpen(pendingWorkspacePath);
          }}
          onRestricted={() => {
            void setRestrictedMode(true);
            void completeWorkspaceOpen(pendingWorkspacePath);
          }}
        />
      )}
    </div>
  );
}
