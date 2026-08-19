import { useEffect, useState } from "react";

import { AppShell } from "./components/layout/AppShell";
import { useAIStore } from "./stores/aiStore";
import { useEditorStore } from "./stores/editorStore";
import { useIndexStore } from "./stores/indexStore";
import { useSettingsStore } from "./stores/settingsStore";
import { useWorkspaceStore } from "./stores/workspaceStore";

import { useBackendStore } from "./stores/backendStore";

function BackendStatusBanner() {
  const status = useBackendStore((s) => s.status);
  const nextRetryInSeconds = useBackendStore((s) => s.nextRetryInSeconds);
  const retryNow = useBackendStore((s) => s.retryNow);

  if (status === "connected") return null;

  return (
    <div className="bg-[#1c1014] border-b border-rose-500/40 text-rose-200 px-4 py-2 text-xs flex items-center justify-between z-[9999] relative shadow-md backdrop-blur-md">
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
        <span className="font-semibold text-rose-300">Backend not running:</span>
        <span className="text-on-surface-variant">
          Please start it with <code className="bg-black/60 px-1.5 py-0.5 rounded text-cyan-300 font-mono text-[11px]">npm run dev</code> or <code className="bg-black/60 px-1.5 py-0.5 rounded text-cyan-300 font-mono text-[11px]">python -m uvicorn app.main:app --port 8000</code>
        </span>
      </div>
      <div className="flex items-center gap-3">
        {nextRetryInSeconds > 0 && (
          <span className="text-[11px] text-rose-300/80 font-mono">
            Retrying in {nextRetryInSeconds}s...
          </span>
        )}
        <button
          type="button"
          onClick={() => void retryNow()}
          className="px-2.5 py-1 rounded-md bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/40 text-rose-200 text-xs font-medium cursor-pointer transition-all hover:scale-105 active:scale-95"
        >
          Retry now
        </button>
      </div>
    </div>
  );
}

function BackendFreshnessBanner() {
  const freshness = useBackendStore((s) => s.freshness);
  const status = useBackendStore((s) => s.status);
  const [dismissed, setDismissed] = useState(false);

  if (status !== "connected" || !freshness?.is_stale || dismissed) return null;

  return (
    <div className="bg-[#241705] border-b border-amber-500/50 text-amber-200 px-4 py-2 text-xs flex items-center justify-between z-[9998] relative shadow-md backdrop-blur-md">
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
        <span className="font-semibold text-amber-300">Backend is running old code — restart to apply fixes.</span>
        <span className="text-amber-200/80 font-mono text-[11px]">
          (Modified on disk: {freshness.changed_files.slice(0, 3).join(", ")}{freshness.changed_files.length > 3 ? ` +${freshness.changed_files.length - 3} more` : ""})
        </span>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="px-2.5 py-0.5 rounded-md bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-medium cursor-pointer transition-all"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function App() {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const restoreLastWorkspace = useWorkspaceStore((state) => state.restoreLastWorkspace);
  const refreshTree = useWorkspaceStore((state) => state.refreshTree);
  const theme = useSettingsStore((state) => state.settings.theme);

  const backendStatus = useBackendStore((s) => s.status);
  const backendDown = backendStatus === "disconnected";

  useEffect(() => {
    void restoreLastWorkspace();
  }, [restoreLastWorkspace]);

  useEffect(() => {
    void useSettingsStore.getState().load().then(() => {
      const settings = useSettingsStore.getState().settings;
      if (settings["ollama.baseUrl"]) useAIStore.setState({ baseUrl: settings["ollama.baseUrl"] });
    }).catch((err) => {
      console.error("Failed to load settings:", err);
    });
    // Load editor settings from backend
    void useEditorStore.getState().loadEditorSettings();
  }, []);

  useEffect(() => {
    void useBackendStore.getState().checkHealth();
    const interval = setInterval(() => {
      void useBackendStore.getState().checkFreshness();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    const themeClasses = ["light", "dark", "crimson", "navy", "void", "violet", "cyberpunk"];
    root.classList.remove(...themeClasses);

    let appliedTheme = theme || "dark";
    if (appliedTheme === "system") {
      const systemIsLight = typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: light)").matches;
      appliedTheme = systemIsLight ? "light" : "dark";
    }

    root.classList.add(appliedTheme);
    if (appliedTheme !== "light") {
      root.classList.add("dark");
    }
    root.setAttribute("data-theme", appliedTheme);
  }, [theme]);

  // Listen for system preference changes when theme is set to "system"
  useEffect(() => {
    if (theme !== "system") return;

    const mediaQuery = window.matchMedia("(prefers-color-scheme: light)");
    const handleChange = () => {
      const root = document.documentElement;
      const themeClasses = ["light", "dark", "crimson", "navy", "void", "violet", "cyberpunk"];
      root.classList.remove(...themeClasses);
      const applied = mediaQuery.matches ? "light" : "dark";
      root.classList.add(applied);
      if (applied !== "light") {
        root.classList.add("dark");
      }
      root.setAttribute("data-theme", applied);
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [theme]);

  useEffect(() => {
    if (!currentWorkspace) {
      return;
    }
    void useEditorStore.getState().restoreTabs();
    void useIndexStore.getState().refresh();
    const timer = window.setInterval(() => {
      if (useBackendStore.getState().status === "connected") {
        void refreshTree();
      }
    }, 10000);
    const indexTimer = window.setInterval(() => {
      if (useBackendStore.getState().status === "connected") {
        void useIndexStore.getState().refresh();
      }
    }, 10000);

    return () => {
      window.clearInterval(timer);
      window.clearInterval(indexTimer);
    };
  }, [currentWorkspace?.path, refreshTree]);

  useEffect(() => {
    return window.codeOS?.onMenuAction((action) => {
      const workspace = useWorkspaceStore.getState();
      const editor = useEditorStore.getState();
      if (action === "file.openFolder") void workspace.openWorkspace();
      if (action === "file.save" && editor.activePath) void editor.saveFile(editor.activePath);
      if (action === "file.saveAll") void editor.saveAll();
      if (action === "file.closeWorkspace") {
        editor.closeWorkspaceTabs();
        workspace.closeWorkspace();
      }
      if (action === "edit.find" || action === "edit.replace") {
        window.dispatchEvent(new CustomEvent("code-os:focus-search"));
      }
      if (action.startsWith("view.")) {
        window.dispatchEvent(new CustomEvent("code-os:menu", { detail: action }));
      }
    });
  }, []);

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const editor = useEditorStore.getState();
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (event.shiftKey) {
          void editor.saveAll();
        } else if (editor.activePath) {
          void editor.saveFile(editor.activePath);
        }
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  return (
    <>
      <BackendStatusBanner />
      <BackendFreshnessBanner />
      <AppShell backendDown={backendDown} />
    </>
  );
}
