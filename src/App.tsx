import { useEffect, useState } from "react";

import { AppShell } from "./components/layout/AppShell";
import { OnboardingWizard } from "./components/workspace/OnboardingWizard";
import { useAIStore } from "./stores/aiStore";
import { useEditorStore } from "./stores/editorStore";
import { useIndexStore } from "./stores/indexStore";
import { useSettingsStore } from "./stores/settingsStore";
import { useWorkspaceStore } from "./stores/workspaceStore";

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
    // Clear all existing theme classes first
    root.classList.remove("light", "crimson", "navy", "void", "violet", "cyberpunk");
    
    let appliedTheme = theme;
    if (theme === "system") {
      const systemIsLight = typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: light)").matches;
      appliedTheme = systemIsLight ? "light" : "dark";
    }
    
    if (appliedTheme && appliedTheme !== "dark") {
      root.classList.add(appliedTheme);
    }
    root.setAttribute("data-theme", appliedTheme || "dark");
  }, [theme]);

  // Listen for system preference changes when theme is set to "system"
  useEffect(() => {
    if (theme !== "system") return;
    
    const mediaQuery = window.matchMedia("(prefers-color-scheme: light)");
    const handleChange = () => {
      const root = document.documentElement;
      root.classList.remove("light", "crimson", "navy", "void", "violet", "cyberpunk");
      const applied = mediaQuery.matches ? "light" : "dark";
      if (applied !== "dark") {
        root.classList.add(applied);
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
    const timer = window.setInterval(() => void refreshTree(), 2500);
    const indexTimer = window.setInterval(() => void useIndexStore.getState().refresh(), 2500);
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
      <AppShell />
      {!onboardingComplete && (
        <OnboardingWizard onClose={() => setOnboardingComplete(true)} />
      )}
    </>
  );
}
