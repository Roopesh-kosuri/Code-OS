import { useEffect, useState } from "react";

import { AppShell } from "./components/layout/AppShell";
import { OnboardingWizard } from "./components/workspace/OnboardingWizard";
import { useAIStore } from "./stores/aiStore";
import { useEditorStore } from "./stores/editorStore";
import { useIndexStore } from "./stores/indexStore";
import { useSettingsStore } from "./stores/settingsStore";
import { useWorkspaceStore } from "./stores/workspaceStore";

function BackendStatusBanner() {
  const [status, setStatus] = useState<{ running: boolean; error: string | null } | null>(null);

  useEffect(() => {
    if (!window.codeOS?.getBackendStatus) return;
    const check = async () => {
      try {
        const s = await window.codeOS?.getBackendStatus?.();
        if (s) setStatus(s);
      } catch { /* ignore */ }
    };
    void check();
    const interval = setInterval(check, 3000);
    return () => clearInterval(interval);
  }, []);

  if (!status || (status.running && !status.error)) return null;

  return (
    <div className="bg-amber-950/80 border-b border-amber-500/30 text-amber-200 px-4 py-2 text-xs flex items-center justify-between z-[9999] relative">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-amber-400">⚠️ Backend Alert:</span>
        <span>{status.error || "Attempting to connect to Python backend process on 127.0.0.1:8000..."}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[11px] opacity-75">Python 3.11+ required</span>
      </div>
    </div>
  );
}

export function App() {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const restoreLastWorkspace = useWorkspaceStore((state) => state.restoreLastWorkspace);
  const refreshTree = useWorkspaceStore((state) => state.refreshTree);
  const theme = useSettingsStore((state) => state.settings.theme);

  const [onboardingComplete, setOnboardingComplete] = useState(() => {
    return localStorage.getItem("code-os:onboarding-complete") === "true";
  });

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
    const timer = window.setInterval(() => void refreshTree(), 10000);
    const indexTimer = window.setInterval(() => void useIndexStore.getState().refresh(), 10000);

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
      <AppShell />
      {!onboardingComplete && (
        <OnboardingWizard onClose={() => setOnboardingComplete(true)} />
      )}
    </>
  );
}
