import { useEffect, useState } from "react";
import { AIChatPanel } from "../../features/ai/AIChatPanel";
import { RonyChatUploadWrapper } from "../../features/files/RonyChatUploadWrapper";
import { EditorWorkspace } from "../../features/editor/EditorWorkspace";
import { FileExplorer } from "../../features/explorer/FileExplorer";
import { GitPanel } from "../git/GitPanel";
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
import { RecentFilesModal } from "../../features/editor/RecentFilesModal";
import { OpenFolderModal } from "../workspace/OpenFolderModal";
import { WelcomeScreen } from "../workspace/WelcomeScreen";
import { SessionReplayPanel } from "../../features/ai/session/SessionReplayPanel";
import { StagingReviewPanel } from "../../features/staging/StagingReviewPanel";
import { AgenticTerminalPanel } from "../../features/terminal/AgenticTerminalPanel";
import { useAgenticTerminalStore } from "../../features/terminal/agenticTerminalStore";
import { GitAutopilotModal } from "../../features/git/GitAutopilotModal";
import { SemanticSearchPanel } from "../../features/rag/SemanticSearchPanel";
import { useRAGStore } from "../../features/rag/ragStore";
import { VoiceModePanel } from "../../features/voice/VoiceModePanel";
import { useVoiceStore } from "../../features/voice/voiceStore";
import { useGitAutopilotStore } from "../../features/git/gitAutopilotStore";
import { DiagramGeneratorPanel } from "../../features/diagrams/DiagramGeneratorPanel";
import { useDiagramStore } from "../../features/diagrams/diagramStore";
import { SecurityDashboardPanel } from "../../features/security/SecurityDashboardPanel";
import { useSecurityStore } from "../../features/security/securityStore";
import { StandupGeneratorPanel } from "../../features/standup/StandupGeneratorPanel";
import { PipelineGeneratorPanel } from "../../features/cicd/PipelineGeneratorPanel";
import { AgentMemoryPanel } from "../../features/memory/AgentMemoryPanel";
import { useMemoryStore } from "../../features/memory/memoryStore";
import { Shield, ClipboardList, GitBranch, Brain } from "lucide-react";

// ── Activity Bar Button Sub-component ────────────────────────────────────────

function ActivityBarButton({
  iconName,
  icon,
  label,
  active,
  onClick,
  id,
  badge,
  badgeClassName,
}: {
  iconName?: string;
  icon?: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  id?: string;
  badge?: number | string;
  badgeClassName?: string;
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
      {icon ? (
        <span className="flex items-center justify-center text-[22px] group-hover:scale-110 transition-transform">
          {icon}
        </span>
      ) : (
        <span
          className="material-symbols-outlined text-[22px] group-hover:scale-110 transition-transform"
          style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
        >
          {iconName}
        </span>
      )}
      {badge !== undefined && (
        <span
          data-testid={`${id}-badge`}
          className={`absolute top-1.5 right-2 ${badgeClassName || "bg-cyan-500 text-black"} text-[9px] font-bold px-1.5 py-0.2 rounded-full min-w-[14px] text-center leading-tight shadow-sm`}
        >
          {badge}
        </span>
      )}
      {/* Tooltip */}
      <div className="absolute left-[70px] bg-surface-container-high border border-outline-variant/30 text-on-surface px-2.5 py-1 rounded-md font-caption text-caption opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 shadow-xl">
        {label}
      </div>
    </button>
  );
}

// ── Main AppShell ─────────────────────────────────────────────────────────────

export function AppShell({ backendDown = false }: { backendDown?: boolean }) {
  const [activeTopView, setActiveTopView] = useState<"main" | "sessions" | "agent" | "duo" | "verifier" | "diagnostics" | "proposals">("main");
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const activeTerminalCount = useAgenticTerminalStore((state) => state.getActiveCount());
  const indexedFilesCount = useRAGStore((state) => state.indexStatus.indexed_files);
  const voiceIsOpen = useVoiceStore((state) => state.isOpen);
  const closeVoiceModal = useVoiceStore((state) => state.closeModal);
  const generatedDiagramsCount = Object.values(
    useDiagramStore((state) => state.diagrams)
  ).filter(Boolean).length;
  const securityCriticalCount = useSecurityStore(
    (state) => state.scanSummary.critical + state.scanSummary.high
  );
  const memoryCount = useMemoryStore((state) => state.memories.length);

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
    return Number(localStorage.getItem("code-os:layout-sidebar-width") ?? "260");
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
      if (action === "view.openTerminal") {
        setShowTerminal(true);
        localStorage.setItem("code-os:layout-show-terminal", "true");
      }
      if (action === "view.toggleAI") {
        setShowAIChat((v) => {
          const next = !v;
          localStorage.setItem("code-os:layout-show-ai-chat", String(next));
          return next;
        });
      }
      if (action.startsWith("view.switchTopView:")) {
        const topView = action.substring("view.switchTopView:".length);
        setActiveTopView(topView as any);
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
    window.addEventListener("code-os:menu-action", listener);
    window.addEventListener("code-os:menu", listener);
    return () => {
      window.removeEventListener("code-os:switch-utility", listener);
      window.removeEventListener("code-os:menu-action", listener);
      window.removeEventListener("code-os:menu", listener);
    };
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

  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Shift+H / Cmd+Shift+H -> Find & Replace Across Files
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "H" || e.key === "h")) {
        e.preventDefault();
        setActiveSidebar("search");
        setShowSidebar(true);
        localStorage.setItem("code-os:layout-show-sidebar", "true");
        localStorage.setItem("code-os:layout-active-sidebar", "search");
        window.dispatchEvent(new CustomEvent("code-os:focus-search-replace"));
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, []);

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
        {/* Session Replay View */}
        <div className={activeTopView === "sessions" ? "flex-1 min-h-0 overflow-hidden flex flex-col h-full" : "hidden"}>
          <SessionReplayPanel onBackToMain={() => setActiveTopView("main")} />
        </div>

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
              {/* 1. Side Navigation Rail (w-[68px]) */}
              <aside className="bg-surface-container-low flex flex-col items-center py-3.5 h-full max-h-full w-[68px] rounded-xl flex-shrink-0 border border-surface-container-high overflow-hidden transition-all duration-200 ease-in-out shadow-sm">
                <div className="flex-1 min-h-0 w-full overflow-y-auto overflow-x-hidden rail-scrollbar flex flex-col items-center space-y-2 py-0.5">
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
                    id="activity-btn-sessions"
                    iconName="history"
                    label="Session Replay"
                    active={showSidebar && activeSidebar === "sessions"}
                    onClick={() => handleActivityClick("sessions")}
                  />
                  <ActivityBarButton
                    id="activity-btn-agentic-terminal"
                    iconName="terminal"
                    label="Agent Terminal"
                    active={showSidebar && activeSidebar === "agentic-terminal"}
                    onClick={() => handleActivityClick("agentic-terminal")}
                    badge={activeTerminalCount > 0 ? activeTerminalCount : undefined}
                  />
                  <ActivityBarButton
                    id="activity-btn-rag"
                    iconName="database"
                    label="Knowledge Base"
                    active={showSidebar && activeSidebar === "rag"}
                    onClick={() => handleActivityClick("rag")}
                    badge={indexedFilesCount > 0 ? indexedFilesCount : undefined}
                  />
                  <ActivityBarButton
                    id="activity-btn-diagrams"
                    iconName="schema"
                    label="Architecture Diagrams"
                    active={showSidebar && activeSidebar === "diagrams"}
                    onClick={() => handleActivityClick("diagrams")}
                    badge={generatedDiagramsCount > 0 ? generatedDiagramsCount : undefined}
                  />
                  <ActivityBarButton
                    id="activity-btn-security"
                    icon={<Shield size={20} />}
                    label="Security"
                    active={showSidebar && activeSidebar === "security"}
                    onClick={() => handleActivityClick("security")}
                    badge={securityCriticalCount > 0 ? securityCriticalCount : undefined}
                    badgeClassName="bg-red-500 text-white"
                  />
                  <ActivityBarButton
                    id="activity-btn-standup"
                    icon={<ClipboardList size={20} />}
                    label="Standup"
                    active={showSidebar && activeSidebar === "standup"}
                    onClick={() => handleActivityClick("standup")}
                  />
                  <ActivityBarButton
                    id="activity-btn-cicd"
                    icon={<GitBranch size={20} />}
                    label="CI/CD"
                    active={showSidebar && activeSidebar === "cicd"}
                    onClick={() => handleActivityClick("cicd")}
                  />
                  <ActivityBarButton
                    id="activity-btn-memory"
                    icon={<Brain size={20} />}
                    label="Memory & Feedback"
                    active={showSidebar && (activeSidebar === "memory" || activeSidebar === "agent-memory")}
                    onClick={() => handleActivityClick("agent-memory")}
                    badge={memoryCount > 0 ? memoryCount : undefined}
                    badgeClassName="bg-cyan-500 text-black"
                  />
                  <ActivityBarButton
                    id="activity-btn-extensions"
                    iconName="extension"
                    label="Extensions"
                    active={showSidebar && activeSidebar === "diagnostics"}
                    onClick={() => handleActivityClick("diagnostics")}
                  />
                </div>

                <div className="mt-auto flex flex-col items-center space-y-2 w-full pb-1 border-t border-surface-variant/40 pt-2.5 shrink-0">
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

                  {/* Ship It — Git Autopilot */}
                  <button
                    id="ship-it-btn"
                    data-testid="ship-it-btn"
                    onClick={() => {
                      const store = useGitAutopilotStore.getState();
                      store.setOpen(true);
                      if (currentWorkspace?.path) {
                        void store.analyze(currentWorkspace.path);
                      }
                    }}
                    className="w-full flex justify-center py-2.5 relative group transition-all duration-200 ease-in-out cursor-pointer text-on-surface-variant hover:bg-surface-variant/40 hover:text-primary"
                    title="Ship It — Git Autopilot"
                    aria-label="Ship It"
                  >
                    <span
                      className="material-symbols-outlined text-[22px] group-hover:scale-110 transition-transform"
                    >
                      rocket_launch
                    </span>
                    {/* Tooltip */}
                    <div className="absolute left-[70px] bg-surface-container-high border border-outline-variant/30 text-on-surface px-2.5 py-1 rounded-md font-caption text-caption opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 shadow-xl">
                      Ship It
                    </div>
                  </button>

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
                      {activeSidebar === "git" ? <GitPanel />
                        : activeSidebar === "search" ? <SearchPanel />
                        : activeSidebar === "rag" ? <SemanticSearchPanel />
                        : activeSidebar === "repo" ? <RepoUnderstanding />
                        : activeSidebar === "diff" ? <DiffViewer />
                        : (activeSidebar === "memory" || activeSidebar === "agent-memory") ? <AgentMemoryPanel />
                        : activeSidebar === "context" ? <ContextPanel />
                        : activeSidebar === "agent" ? <AgentConsole compact />
                        : activeSidebar === "diagnostics" ? <PerformanceDashboard />
                        : activeSidebar === "duo" ? <DuoPanel compact />
                        : activeSidebar === "sessions" ? <SessionReplayPanel compact onOpenFullView={() => setActiveTopView("sessions")} />
                        : activeSidebar === "agentic-terminal" ? <AgenticTerminalPanel />
                        : activeSidebar === "diagrams" ? <DiagramGeneratorPanel />
                        : activeSidebar === "security" ? <SecurityDashboardPanel />
                        : activeSidebar === "standup" ? <StandupGeneratorPanel />
                        : activeSidebar === "cicd" ? <PipelineGeneratorPanel />
                        : <FileExplorer />}
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
                  <RonyChatUploadWrapper>
                    <AIChatPanel />
                  </RonyChatUploadWrapper>
                </aside>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Modals & Dialogs ────────────────────────────────────────────────── */}
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
      <RecentFilesModal />
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
      <StagingReviewPanel />
      <GitAutopilotModal />
      <VoiceModePanel
        isOpen={voiceIsOpen}
        onClose={closeVoiceModal}
        onSendToAgent={(text) => {
          // Dispatch custom event that AIChatPanel can listen to for injection
          window.dispatchEvent(new CustomEvent("code-os:voice-inject", { detail: { text } }));
          closeVoiceModal();
        }}
      />
    </div>
  );
}
