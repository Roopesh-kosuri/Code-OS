import React, { useState, useEffect, useCallback } from "react";
import {
  X,
  Palette,
  Server,
  Sliders,
  Terminal as TermIcon,
  GitBranch,
  Cpu,
  Info,
  Check,
  KeyRound,
  ExternalLink,
  Lock,
  RotateCcw,
  Trash2,
  HelpCircle,
  ShieldAlert,
} from "lucide-react";
import { useSettingsStore } from "../../stores/settingsStore";
import { useAIStore } from "../../stores/aiStore";
import { useEditorStore } from "../../stores/editorStore";
import { api } from "../../lib/api";
import { PROVIDER_PRESETS } from "../../lib/providerPresets";

interface SettingsModalProps {
  onClose: () => void;
}

type Category = "general" | "providers" | "editor" | "terminal" | "git" | "agents" | "theme" | "security" | "about";

interface ThemeSwatch {
  id: string;
  name: string;
  bg: string;
  accent: string;
  text: string;
}

const THEME_SWATCHES: ThemeSwatch[] = [
  { id: "dark", name: "Dark (Default)", bg: "#131315", accent: "#00daf3", text: "#e5e1e4" },
  { id: "light", name: "Light (White)", bg: "#ffffff", accent: "#00838f", text: "#1f2328" },
  { id: "void", name: "Void (OLED)", bg: "#000000", accent: "#a1a1aa", text: "#e4e4e7" },
  { id: "cyberpunk", name: "Cyberpunk (Neon)", bg: "#080b12", accent: "#00e5ff", text: "#dcf1f5" },
];

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [activeCategory, setActiveCategory] = useState<Category>("general");

  const settings = useSettingsStore((s) => s.settings);
  const saveSetting = useSettingsStore((s) => s.save);
  const saveApiKey = useSettingsStore((s) => s.saveApiKey);
  const loadSettings = useSettingsStore((s) => s.load);

  const editorFontSize = useEditorStore((s) => s.fontSize);
  const editorTabSize = useEditorStore((s) => s.tabSize);
  const editorAutoSave = useEditorStore((s) => s.autoSave);
  const setEditorSetting = useEditorStore((s) => s.setEditorSetting);
  const setAutoSave = useEditorStore((s) => s.setAutoSave);

  const aiBaseUrl = useAIStore((s) => s.baseUrl);
  const aiModel = useAIStore((s) => s.model);

  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [keySaveStatus, setKeySaveStatus] = useState<Record<string, "idle" | "saving" | "saved">>({});

  // Monaco options (immediate auto-save)
  const [editorWordWrap, setEditorWordWrap] = useState(
    () => localStorage.getItem("code-os:editor.wordWrap") !== "off"
  );
  const [editorMinimap, setEditorMinimap] = useState(
    () => localStorage.getItem("code-os:editor.minimap") !== "false"
  );

  // Terminal options (immediate auto-save)
  const [termShell, setTermShell] = useState(
    () => localStorage.getItem("code-os:terminal.shell") || "powershell.exe"
  );
  const [termFontSize, setTermFontSize] = useState(
    () => Number(localStorage.getItem("code-os:terminal.fontSize") ?? "12")
  );

  // General & System Prompts (immediate auto-save)
  const [systemPrompt, setSystemPrompt] = useState(
    () => localStorage.getItem("code-os:general.systemPrompt") || "You are an expert AI development assistant in CODE OS. Prioritize clean, efficient, and well-documented code."
  );
  const [inlineSuggestions, setInlineSuggestions] = useState(
    () => localStorage.getItem("code-os:general.inlineSuggestions") !== "false"
  );

  // Agent/Duo options (immediate auto-save)
  const [duoMaxRounds, setDuoMaxRounds] = useState(
    () => Number(localStorage.getItem("code-os:duo.maxRounds") ?? "5")
  );
  const [agentPlannerModel, setAgentPlannerModel] = useState(
    () => localStorage.getItem("code-os:agent.plannerModel") || "gpt-4o"
  );
  const [agentDeveloperModel, setAgentDeveloperModel] = useState(
    () => localStorage.getItem("code-os:agent.developerModel") || "claude-3-5-sonnet-20241022"
  );

  // Git options (immediate auto-save)
  const [gitAutoFetch, setGitAutoFetch] = useState(
    () => localStorage.getItem("code-os:git.autoFetch") === "true"
  );
  const [gitConfirmSync, setGitConfirmSync] = useState(
    () => localStorage.getItem("code-os:git.confirmSync") !== "false"
  );
  const [gitDefaultBranch, setGitDefaultBranch] = useState(
    () => localStorage.getItem("code-os:git.defaultBranch") || "main"
  );

  const [feedback, setFeedback] = useState<string | null>(null);

  const showFeedback = (msg: string) => {
    setFeedback(msg);
    setTimeout(() => setFeedback(null), 2500);
  };

  const refreshKeys = useCallback(async () => {
    try {
      const keys = await api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys");
      setConfiguredKeys(keys.filter((k) => k.configured).map((k) => k.provider_id));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    void loadSettings();
    void refreshKeys();
  }, [loadSettings, refreshKeys]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const handleSaveKey = async (providerId: string) => {
    const value = keyInputs[providerId]?.trim();
    if (!value) return;

    setKeySaveStatus((s) => ({ ...s, [providerId]: "saving" }));
    try {
      await saveApiKey(providerId, value);
      setKeyInputs((i) => ({ ...i, [providerId]: "" }));
      setKeySaveStatus((s) => ({ ...s, [providerId]: "saved" }));
      void refreshKeys();
      showFeedback("API key encrypted and stored.");
      setTimeout(() => {
        setKeySaveStatus((s) => ({ ...s, [providerId]: "idle" }));
      }, 2000);
    } catch {
      setKeySaveStatus((s) => ({ ...s, [providerId]: "idle" }));
    }
  };

  const navCategories = [
    { id: "general", label: "General", icon: "tune" },
    { id: "providers", label: "Providers & Models", icon: "smart_toy" },
    { id: "editor", label: "Editor", icon: "edit_note" },
    { id: "terminal", label: "Terminal", icon: "terminal" },
    { id: "git", label: "Git & Source Control", icon: "account_tree" },
    { id: "agents", label: "Agents & Duo", icon: "psychology" },
    { id: "theme", label: "Theme & Palette", icon: "palette" },
    { id: "security", label: "Security & Privacy", icon: "security" },
    { id: "about", label: "About", icon: "info" },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-6"
      role="dialog"
      aria-modal="true"
    >
      {/* ── Settings Container ────────────────────────────────────────────── */}
      <div className="relative w-full max-w-5xl h-[88vh] bg-[#0a0a0c] rounded-2xl overflow-hidden shadow-2xl border border-surface-container-high/60 flex text-on-surface font-ui-label-reg text-ui-label-reg select-none antialiased">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-30 w-8 h-8 flex items-center justify-center rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-variant transition-all cursor-pointer"
          title="Close Settings (Esc)"
        >
          <X size={18} />
        </button>

        {/* ── Left Settings Sidebar ─────────────────────────────────────────── */}
        <aside className="w-64 bg-[#131418] rounded-l-2xl border-r border-surface-container-high/50 flex flex-col z-10 flex-shrink-0 p-4">
          <div className="p-4 pb-6 border-b border-surface-container-high/40 flex items-center gap-2.5">
            <span className="material-symbols-outlined text-primary text-2xl">settings</span>
            <h1 className="font-headline-md text-headline-md text-on-surface font-bold">Settings</h1>
          </div>

          <nav className="flex-1 overflow-y-auto py-4 space-y-1">
            {navCategories.map(({ id, label, icon }) => {
              const isActive = activeCategory === id;
              return (
                <button
                  key={id}
                  onClick={() => setActiveCategory(id as Category)}
                  className={`w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-left transition-all cursor-pointer ${
                    isActive
                      ? "bg-surface-variant/50 text-primary font-ui-label-bold shadow-sm"
                      : "text-on-surface-variant hover:bg-surface-variant/30 hover:text-on-surface"
                  }`}
                >
                  <span
                    className={`material-symbols-outlined text-[20px] ${isActive ? "text-primary" : "text-on-surface-variant"}`}
                    style={isActive ? { fontVariationSettings: "'FILL' 1" } : undefined}
                  >
                    {icon}
                  </span>
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
          </nav>

          <div className="text-[11px] text-on-surface-variant/40 px-3 pt-4 border-t border-surface-container-high/40">
            CODE OS v0.2.0 • Auto-saved
          </div>
        </aside>

        {/* ── Right Content Canvas ─────────────────────────────────────────── */}
        <section className="flex-1 bg-[#131418] rounded-r-2xl overflow-y-auto z-10 p-8 lg:p-12 flex flex-col justify-between">
          <div className="max-w-3xl space-y-8">
            {/* Feedback Alert */}
            {feedback && (
              <div className="rounded-xl border border-primary-container/40 bg-primary-container/10 p-3 text-xs text-primary flex items-center gap-2 animate-pulse">
                <Check size={14} />
                <span>{feedback}</span>
              </div>
            )}

            {/* ── Category: General ───────────────────────────────────────── */}
            {activeCategory === "general" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">General Configuration</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Manage core settings and AI assistance defaults (changes save automatically).</p>
                </div>

                {/* Workspace Group */}
                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-6 shadow-md">
                  <h3 className="font-ui-label-bold text-ui-label-bold text-primary flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm">workspaces</span> Workspace
                  </h3>

                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-ui-label-reg text-ui-label-reg text-on-surface">Auto-Save</div>
                      <div className="font-caption text-caption text-on-surface-variant mt-0.5">Automatically save modified files on keystroke delays.</div>
                    </div>
                    <label className="relative inline-block w-10 h-6 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={editorAutoSave}
                        onChange={(e) => {
                          setAutoSave(e.target.checked);
                          showFeedback(`Auto-save ${e.target.checked ? "enabled" : "disabled"}`);
                        }}
                        className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer z-10 opacity-0"
                      />
                      <div className="toggle-label block overflow-hidden h-6 rounded-full bg-surface-variant cursor-pointer" />
                    </label>
                  </div>
                </div>

                {/* AI Assistance Group */}
                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-6 shadow-md">
                  <h3 className="font-ui-label-bold text-ui-label-bold text-primary flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm">psychology</span> AI Assistance
                  </h3>

                  <div className="space-y-2">
                    <div className="font-ui-label-reg text-ui-label-reg text-on-surface">Default System Prompt</div>
                    <div className="font-caption text-caption text-on-surface-variant">Base instructions provided to the active agent context.</div>
                    <textarea
                      value={systemPrompt}
                      onChange={(e) => {
                        setSystemPrompt(e.target.value);
                        localStorage.setItem("code-os:general.systemPrompt", e.target.value);
                      }}
                      onBlur={() => showFeedback("System prompt saved")}
                      rows={3}
                      className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-3 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none input-glow resize-none"
                    />
                  </div>

                  <div className="flex items-center justify-between border-t border-surface-container-high/40 pt-4">
                    <div>
                      <div className="font-ui-label-reg text-ui-label-reg text-on-surface">Inline Suggestions (Ctrl+I)</div>
                      <div className="font-caption text-caption text-on-surface-variant mt-0.5">Show AI completions as you type in the editor.</div>
                    </div>
                    <label className="relative inline-block w-10 h-6 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={inlineSuggestions}
                        onChange={(e) => {
                          setInlineSuggestions(e.target.checked);
                          localStorage.setItem("code-os:general.inlineSuggestions", String(e.target.checked));
                          showFeedback(`Inline suggestions ${e.target.checked ? "enabled" : "disabled"}`);
                        }}
                        className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer z-10 opacity-0"
                      />
                      <div className="toggle-label block overflow-hidden h-6 rounded-full bg-surface-variant cursor-pointer" />
                    </label>
                  </div>
                </div>
              </div>
            )}

            {/* ── Category: Providers & Models ─────────────────────────────── */}
            {activeCategory === "providers" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">Providers &amp; API Keys</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Configure local Ollama inference and encrypted provider API keys.</p>
                </div>

                {/* Ollama Card */}
                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-4 shadow-md">
                  <h3 className="font-ui-label-bold text-ui-label-bold text-primary flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm">computer</span> Local Inference (Ollama)
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="font-caption text-caption text-on-surface-variant mb-1 block">Ollama Server Base URL</label>
                      <input
                        type="text"
                        value={aiBaseUrl}
                        onChange={async (e) => {
                          useAIStore.setState({ baseUrl: e.target.value });
                          await saveSetting("ollama.baseUrl", e.target.value);
                          showFeedback("Ollama URL saved");
                        }}
                        className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="font-caption text-caption text-on-surface-variant mb-1 block">Default Ollama Model</label>
                      <input
                        type="text"
                        value={aiModel}
                        onChange={async (e) => {
                          useAIStore.setState({ model: e.target.value });
                          await saveSetting("ollama.model", e.target.value);
                          showFeedback("Ollama Model saved");
                        }}
                        className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                      />
                    </div>
                  </div>
                </div>

                {/* API Keys */}
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <h3 className="font-ui-label-bold text-ui-label-bold text-secondary">Encrypted Provider Keys</h3>
                    <span className="text-[10px] text-on-surface-variant bg-surface-variant px-2.5 py-0.5 rounded-full font-mono font-bold">
                      {configuredKeys.length} configured
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {PROVIDER_PRESETS.filter((p) => p.group === "api" && p.api_key_provider !== null).map((p) => {
                      const keyId = p.api_key_provider!;
                      const isSet = configuredKeys.includes(keyId);
                      const status = keySaveStatus[keyId] || "idle";

                      return (
                        <div key={p.id} className="bg-[#1e1f24] rounded-xl border border-surface-container-high/40 p-4 space-y-3 shadow-md flex flex-col justify-between">
                          <div className="flex justify-between items-center">
                            <span className="font-ui-label-bold text-ui-label-bold text-on-surface">{p.label}</span>
                            <span className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase border ${
                              isSet
                                ? "text-primary bg-primary-container/10 border-primary-container/30"
                                : "text-on-surface-variant bg-white/5 border-white/10"
                            }`}>
                              {isSet ? "Saved" : "Not set"}
                            </span>
                          </div>
                          <div className="flex gap-2">
                            <input
                              type="password"
                              placeholder={isSet ? "••••••••••••••••" : p.api_key_prefix ? `${p.api_key_prefix}…` : "sk-…"}
                              value={keyInputs[keyId] || ""}
                              onChange={(e) => setKeyInputs((i) => ({ ...i, [keyId]: e.target.value }))}
                              className="h-8 flex-1 bg-[#131318] border border-surface-container-high rounded-lg px-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                            />
                            <button
                              onClick={() => void handleSaveKey(keyId)}
                              disabled={!keyInputs[keyId]?.trim() || status === "saving"}
                              className="h-8 px-3 rounded-lg bg-primary-container text-[#001f24] font-bold text-xs hover:bg-primary-fixed disabled:opacity-40 transition-colors cursor-pointer shrink-0"
                            >
                              {status === "saving" ? "Saving…" : "Store"}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* ── Category: Editor ─────────────────────────────────────────── */}
            {activeCategory === "editor" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">Editor Preferences</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Configure Monaco editor font, indentation, wrapping, and minimap.</p>
                </div>

                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-6 shadow-md">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="font-caption text-caption text-on-surface-variant mb-1 block">Editor Font Size (px)</label>
                      <input
                        type="number"
                        min={10}
                        max={32}
                        value={editorFontSize}
                        onChange={(e) => {
                          const val = Number(e.target.value);
                          setEditorSetting({ fontSize: val });
                          showFeedback(`Font size: ${val}px`);
                        }}
                        className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface focus:border-primary-container focus:outline-none font-mono"
                      />
                    </div>
                    <div>
                      <label className="font-caption text-caption text-on-surface-variant mb-1 block">Tab Size</label>
                      <input
                        type="number"
                        min={2}
                        max={8}
                        value={editorTabSize}
                        onChange={(e) => {
                          const val = Number(e.target.value);
                          setEditorSetting({ tabSize: val });
                          showFeedback(`Tab size: ${val}`);
                        }}
                        className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface focus:border-primary-container focus:outline-none font-mono"
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-t border-surface-container-high/40 pt-4">
                    <div>
                      <div className="font-ui-label-reg text-ui-label-reg text-on-surface">Word Wrap</div>
                      <div className="font-caption text-caption text-on-surface-variant mt-0.5">Wrap long lines to fit editor width.</div>
                    </div>
                    <label className="relative inline-block w-10 h-6 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={editorWordWrap}
                        onChange={(e) => {
                          setEditorWordWrap(e.target.checked);
                          localStorage.setItem("code-os:editor.wordWrap", e.target.checked ? "on" : "off");
                          showFeedback(`Word wrap ${e.target.checked ? "on" : "off"}`);
                        }}
                        className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer z-10 opacity-0"
                      />
                      <div className="toggle-label block overflow-hidden h-6 rounded-full bg-surface-variant cursor-pointer" />
                    </label>
                  </div>

                  <div className="flex items-center justify-between border-t border-surface-container-high/40 pt-4">
                    <div>
                      <div className="font-ui-label-reg text-ui-label-reg text-on-surface">Code Minimap</div>
                      <div className="font-caption text-caption text-on-surface-variant mt-0.5">Show overview minimap on the right of the editor.</div>
                    </div>
                    <label className="relative inline-block w-10 h-6 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={editorMinimap}
                        onChange={(e) => {
                          setEditorMinimap(e.target.checked);
                          localStorage.setItem("code-os:editor.minimap", String(e.target.checked));
                          showFeedback(`Minimap ${e.target.checked ? "visible" : "hidden"}`);
                        }}
                        className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer z-10 opacity-0"
                      />
                      <div className="toggle-label block overflow-hidden h-6 rounded-full bg-surface-variant cursor-pointer" />
                    </label>
                  </div>
                </div>
              </div>
            )}

            {/* ── Category: Terminal ───────────────────────────────────────── */}
            {activeCategory === "terminal" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">Terminal Shell &amp; PTY</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Configure integrated hardware terminal executable and font size.</p>
                </div>

                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-4 shadow-md">
                  <div>
                    <label className="font-caption text-caption text-on-surface-variant mb-1 block">Shell Executable Path</label>
                    <input
                      type="text"
                      value={termShell}
                      onChange={(e) => {
                        setTermShell(e.target.value);
                        localStorage.setItem("code-os:terminal.shell", e.target.value);
                      }}
                      onBlur={() => showFeedback("Terminal shell path saved")}
                      className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="font-caption text-caption text-on-surface-variant mb-1 block">Terminal Font Size (pt)</label>
                    <input
                      type="number"
                      min={9}
                      max={24}
                      value={termFontSize}
                      onChange={(e) => {
                        const val = Number(e.target.value);
                        setTermFontSize(val);
                        localStorage.setItem("code-os:terminal.fontSize", String(val));
                        showFeedback(`Terminal font: ${val}pt`);
                      }}
                      className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* ── Category: Git & Source Control (Restored) ────────────────── */}
            {activeCategory === "git" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">Git &amp; Version Control</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Configure automated background fetching and commit synchronization behaviors.</p>
                </div>

                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-6 shadow-md">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-ui-label-reg text-ui-label-reg text-on-surface">Auto-Fetch Remote Commits</div>
                      <div className="font-caption text-caption text-on-surface-variant mt-0.5">Periodically poll remote branch for changes in the background.</div>
                    </div>
                    <label className="relative inline-block w-10 h-6 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={gitAutoFetch}
                        onChange={(e) => {
                          setGitAutoFetch(e.target.checked);
                          localStorage.setItem("code-os:git.autoFetch", String(e.target.checked));
                          showFeedback(`Auto-fetch ${e.target.checked ? "enabled" : "disabled"}`);
                        }}
                        className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer z-10 opacity-0"
                      />
                      <div className="toggle-label block overflow-hidden h-6 rounded-full bg-surface-variant cursor-pointer" />
                    </label>
                  </div>

                  <div className="flex items-center justify-between border-t border-surface-container-high/40 pt-4">
                    <div>
                      <div className="font-ui-label-reg text-ui-label-reg text-on-surface">Confirm Before Sync / Push</div>
                      <div className="font-caption text-caption text-on-surface-variant mt-0.5">Prompt confirmation dialog before pushing commits to upstream.</div>
                    </div>
                    <label className="relative inline-block w-10 h-6 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={gitConfirmSync}
                        onChange={(e) => {
                          setGitConfirmSync(e.target.checked);
                          localStorage.setItem("code-os:git.confirmSync", String(e.target.checked));
                          showFeedback(`Confirm sync ${e.target.checked ? "enabled" : "disabled"}`);
                        }}
                        className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer z-10 opacity-0"
                      />
                      <div className="toggle-label block overflow-hidden h-6 rounded-full bg-surface-variant cursor-pointer" />
                    </label>
                  </div>

                  <div className="border-t border-surface-container-high/40 pt-4">
                    <label className="font-caption text-caption text-on-surface-variant mb-1 block">Default Initial Branch</label>
                    <input
                      type="text"
                      value={gitDefaultBranch}
                      onChange={(e) => {
                        setGitDefaultBranch(e.target.value);
                        localStorage.setItem("code-os:git.defaultBranch", e.target.value);
                      }}
                      onBlur={() => showFeedback("Default branch saved")}
                      className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* ── Category: Agents & Duo ─────────────────────────────────────── */}
            {activeCategory === "agents" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">Autonomous Agents &amp; Duo</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Default models and round limits for multi-agent DAG pipelines.</p>
                </div>

                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-6 shadow-md">
                  <div>
                    <label className="font-caption text-caption text-on-surface-variant mb-1 block">Duo Loop Maximum Rounds</label>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={duoMaxRounds}
                      onChange={(e) => {
                        const val = Math.max(1, Math.min(20, Number(e.target.value)));
                        setDuoMaxRounds(val);
                        localStorage.setItem("code-os:duo.maxRounds", String(val));
                        showFeedback(`Duo max rounds: ${val}`);
                      }}
                      className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4 border-t border-surface-container-high/40 pt-4">
                    <div>
                      <label className="font-caption text-caption text-on-surface-variant mb-1 block">Planner Agent Model</label>
                      <input
                        type="text"
                        value={agentPlannerModel}
                        onChange={(e) => {
                          setAgentPlannerModel(e.target.value);
                          localStorage.setItem("code-os:agent.plannerModel", e.target.value);
                        }}
                        onBlur={() => showFeedback("Planner model saved")}
                        className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="font-caption text-caption text-on-surface-variant mb-1 block">Developer Agent Model</label>
                      <input
                        type="text"
                        value={agentDeveloperModel}
                        onChange={(e) => {
                          setAgentDeveloperModel(e.target.value);
                          localStorage.setItem("code-os:agent.developerModel", e.target.value);
                        }}
                        onBlur={() => showFeedback("Developer model saved")}
                        className="w-full bg-[#131318] border border-surface-container-high rounded-lg p-2.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none"
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── Category: Theme ──────────────────────────────────────────── */}
            {activeCategory === "theme" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">Theme &amp; Palette</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Select color themes tailored for high-contrast coding.</p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  {THEME_SWATCHES.map((swatch) => {
                    const isActive = (settings.theme ?? "dark") === swatch.id;
                    return (
                      <button
                        key={swatch.id}
                        onClick={async () => {
                          await saveSetting("theme", swatch.id);
                          showFeedback(`Theme changed to ${swatch.name}`);
                        }}
                        className={`p-4 rounded-xl border text-left transition-all relative flex flex-col justify-between h-28 cursor-pointer ${
                          isActive
                            ? "border-primary-container bg-primary-container/5 shadow-[0_0_16px_rgba(0,218,243,0.15)] ring-1 ring-primary-container"
                            : "border-surface-container-high bg-[#1e1f24] hover:border-outline-variant"
                        }`}
                      >
                        <div className="flex justify-between items-center">
                          <span className="font-ui-label-bold text-ui-label-bold text-on-surface">{swatch.name}</span>
                          {isActive && <Check size={16} className="text-primary-container" />}
                        </div>

                        <div className="flex items-center gap-2">
                          <span className="w-5 h-5 rounded-full border border-white/10" style={{ backgroundColor: swatch.bg }} />
                          <span className="w-5 h-5 rounded-full border border-white/10" style={{ backgroundColor: swatch.accent }} />
                          <span className="w-5 h-5 rounded-full border border-white/10" style={{ backgroundColor: swatch.text }} />
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── Category: Security & Privacy (Restored Data Reset Actions) ── */}
            {activeCategory === "security" && (
              <div className="space-y-6">
                <div>
                  <h2 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">Security &amp; Data Reset</h2>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant">Manage encrypted key slots, workspace trust boundaries, and history caches.</p>
                </div>

                <div className="bg-[#1e1f24] rounded-xl border border-error/20 p-6 space-y-4 shadow-md">
                  <h3 className="font-ui-label-bold text-ui-label-bold text-error flex items-center gap-2">
                    <ShieldAlert size={16} />
                    <span>Data Reset Options</span>
                  </h3>
                  <p className="text-xs text-on-surface-variant leading-relaxed">
                    Clear stored credentials, reset workspace trust policies, or flush autonomous agent execution logs.
                  </p>

                  <div className="flex flex-col gap-3 max-w-sm pt-2">
                    <button
                      onClick={async () => {
                        if (confirm("Clear all encrypted API keys? This cannot be undone.")) {
                          await api.delete("/api/settings/api-keys");
                          void refreshKeys();
                          showFeedback("API keys cleared.");
                        }
                      }}
                      className="px-4 py-2.5 rounded-lg bg-error/10 hover:bg-error/20 border border-error/30 text-error font-ui-label-bold text-xs text-center transition-colors cursor-pointer"
                    >
                      Clear Encrypted API Keys
                    </button>

                    <button
                      onClick={async () => {
                        if (confirm("Clear all conversation threads, Duo sessions, and agent run histories?")) {
                          await api.delete("/api/settings/history");
                          showFeedback("Chat and execution histories cleared.");
                        }
                      }}
                      className="px-4 py-2.5 rounded-lg bg-error/10 hover:bg-error/20 border border-error/30 text-error font-ui-label-bold text-xs text-center transition-colors cursor-pointer"
                    >
                      Clear Chat &amp; Job History
                    </button>

                    <button
                      onClick={async () => {
                        if (confirm("Reset all workspace trust authorizations?")) {
                          await api.delete("/api/workspaces/trust");
                          showFeedback("Workspace trust authorizations reset.");
                        }
                      }}
                      className="px-4 py-2.5 rounded-lg bg-error/10 hover:bg-error/20 border border-error/30 text-error font-ui-label-bold text-xs text-center transition-colors cursor-pointer"
                    >
                      Reset Workspace Trust Decisions
                    </button>
                  </div>
                </div>

                {/* Onboarding Restart */}
                <div className="bg-[#1e1f24] rounded-xl border border-surface-container-high/30 p-6 space-y-3 shadow-md">
                  <h3 className="font-ui-label-bold text-ui-label-bold text-on-surface flex items-center gap-2">
                    <HelpCircle size={16} className="text-primary" />
                    <span>Onboarding Tutorial</span>
                  </h3>
                  <p className="text-xs text-on-surface-variant">Restart the interactive walkthrough and tutorial spotlight.</p>
                  <button
                    onClick={() => {
                      if (confirm("Restart onboarding tutorial? The application will reload.")) {
                        localStorage.setItem("code-os:onboarding-complete", "false");
                        window.location.reload();
                      }
                    }}
                    className="px-5 py-2 rounded-full bg-primary-container text-[#001f24] font-ui-label-bold text-xs hover:bg-primary-fixed transition-colors shadow-md cursor-pointer"
                  >
                    Replay Tutorial Walkthrough
                  </button>
                </div>
              </div>
            )}

            {/* ── Category: About ──────────────────────────────────────────── */}
            {activeCategory === "about" && (
              <div className="space-y-6">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-primary-container/10 border border-primary-container/30 flex items-center justify-center text-primary-container shadow-lg">
                    <span className="material-symbols-outlined text-3xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                      terminal
                    </span>
                  </div>
                  <div>
                    <h2 className="font-headline-md text-headline-md text-on-surface font-black">CODE OS</h2>
                    <p className="font-caption text-caption text-on-surface-variant">Version 0.2.0 • Google Stitch Design System</p>
                  </div>
                </div>

                <p className="text-xs text-on-surface-variant leading-relaxed bg-[#1e1f24] rounded-xl p-6 border border-surface-container-high/40">
                  CODE OS is a high-performance local AI development environment featuring autonomous DAG multi-agent pipelines, adversarial Duo feedback loops, multi-model SAST code verification, and hardware PTY integration.
                </p>
              </div>
            )}
          </div>

          {/* ── Bottom Action Bar ──────────────────────────────────────────── */}
          <div className="flex justify-between items-center pt-6 border-t border-surface-container-high/40 mt-8">
            <span className="text-[11px] text-on-surface-variant/60 font-mono">
              All preferences auto-save instantly.
            </span>
            <button
              onClick={onClose}
              className="px-6 py-2 rounded-full font-ui-label-bold text-ui-label-bold text-[#0a0a0c] bg-primary-container hover:bg-primary-fixed transition-all shadow-md cursor-pointer text-xs"
            >
              Done
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
