import { useState, useEffect, useCallback } from "react";
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
} from "lucide-react";
import { Button } from "../ui/Button";
import { CodeOsLogo } from "../branding/CodeOsLogo";
import { useSettingsStore } from "../../stores/settingsStore";
import { useAIStore } from "../../stores/aiStore";
import { useEditorStore } from "../../stores/editorStore";
import { api } from "../../lib/api";
import { PROVIDER_PRESETS } from "../../lib/providerPresets";

// ── Types ────────────────────────────────────────────────────────────────────

interface SettingsModalProps {
  onClose: () => void;
}

type Category = "appearance" | "ai" | "editor" | "terminal" | "git" | "agents" | "security" | "about";

interface ThemeSwatch {
  id: string;
  name: string;
  bg: string;
  accent: string;
  text: string;
  isDark: boolean;
}

const THEME_SWATCHES: ThemeSwatch[] = [
  { id: "dark", name: "Default Dark", bg: "#101215", accent: "#45b3e7", text: "#f1f5f9", isDark: true },
  { id: "light", name: "Light", bg: "#ffffff", accent: "#208cc8", text: "#1f2328", isDark: false },
  { id: "crimson", name: "Crimson", bg: "#150808", accent: "#e0483e", text: "#f2e8e6", isDark: true },
  { id: "navy", name: "Navy", bg: "#0a0e1a", accent: "#3b82f6", text: "#e8ecf5", isDark: true },
  { id: "void", name: "Void (OLED)", bg: "#000000", accent: "#a1a1aa", text: "#e4e4e7", isDark: true },
  { id: "violet", name: "Violet", bg: "#120c1a", accent: "#a855f7", text: "#ede9f5", isDark: true },
  { id: "cyberpunk", name: "Cyberpunk", bg: "#080b12", accent: "#00e5ff", text: "#dcf1f5", isDark: true },
];

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [activeCategory, setActiveCategory] = useState<Category>("appearance");

  // Load Settings from stores
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

  // Key configurations list
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [keySaveStatus, setKeySaveStatus] = useState<Record<string, "idle" | "saving" | "saved">>({});

  // Monaco options local storage triggers
  const [editorWordWrap, setEditorWordWrap] = useState(
    () => localStorage.getItem("code-os:editor.wordWrap") !== "off"
  );
  const [editorMinimap, setEditorMinimap] = useState(
    () => localStorage.getItem("code-os:editor.minimap") !== "false"
  );
  const [editorFontFamily, setEditorFontFamily] = useState(
    () => localStorage.getItem("code-os:editor.fontFamily") || "JetBrains Mono, Cascadia Code, Consolas, monospace"
  );

  // Terminal options
  const [termShell, setTermShell] = useState(
    () => localStorage.getItem("code-os:terminal.shell") || "powershell.exe"
  );
  const [termFontFamily, setTermFontFamily] = useState(
    () => localStorage.getItem("code-os:terminal.fontFamily") || "JetBrains Mono, Consolas, monospace"
  );
  const [termFontSize, setTermFontSize] = useState(
    () => Number(localStorage.getItem("code-os:terminal.fontSize") ?? "12")
  );
  const [termCursorStyle, setTermCursorStyle] = useState(
    () => localStorage.getItem("code-os:terminal.cursorStyle") || "block"
  );

  // Git options
  const [gitAutoPoll, setGitAutoPoll] = useState(
    () => localStorage.getItem("code-os:git.autoPoll") !== "false"
  );
  const [gitSignCommits, setGitSignCommits] = useState(
    () => localStorage.getItem("code-os:git.signCommits") === "true"
  );

  // Agent/Duo options
  const [duoMaxRounds, setDuoMaxRounds] = useState(
    () => Number(localStorage.getItem("code-os:duo.maxRounds") ?? "5")
  );
  const [agentPlannerModel, setAgentPlannerModel] = useState(
    () => localStorage.getItem("code-os:agent.plannerModel") || "llama3"
  );
  const [agentDeveloperModel, setAgentDeveloperModel] = useState(
    () => localStorage.getItem("code-os:agent.developerModel") || "llama3"
  );

  // Save feedback state
  const [appearanceSaveFeedback, setAppearanceSaveFeedback] = useState(false);
  const [editorSaveFeedback, setEditorSaveFeedback] = useState(false);
  const [terminalSaveFeedback, setTerminalSaveFeedback] = useState(false);
  const [gitSaveFeedback, setGitSaveFeedback] = useState(false);
  const [agentsSaveFeedback, setAgentsSaveFeedback] = useState(false);

  // Load configured keys on mount
  const refreshKeys = useCallback(async () => {
    try {
      const keys = await api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys");
      setConfiguredKeys(keys.filter((k) => k.configured).map((k) => k.provider_id));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    void loadSettings();
    void refreshKeys();
  }, [loadSettings, refreshKeys]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Key storage logic
  const handleSaveKey = async (providerId: string) => {
    const value = keyInputs[providerId]?.trim();
    if (!value) return;

    setKeySaveStatus((s) => ({ ...s, [providerId]: "saving" }));
    try {
      await saveApiKey(providerId, value);
      setKeyInputs((i) => ({ ...i, [providerId]: "" }));
      setKeySaveStatus((s) => ({ ...s, [providerId]: "saved" }));
      void refreshKeys();
      setTimeout(() => {
        setKeySaveStatus((s) => ({ ...s, [providerId]: "idle" }));
      }, 2000);
    } catch {
      setKeySaveStatus((s) => ({ ...s, [providerId]: "idle" }));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      {/* Container */}
      <div className="relative w-full max-w-5xl h-[85vh] rounded-xl border border-surface-700 bg-surface-900 shadow-2xl flex overflow-hidden text-slate-100">
        
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 text-slate-400 hover:text-white transition-colors z-10 p-1 hover:bg-surface-800 rounded-md"
        >
          <X size={18} />
        </button>

        {/* Left Sidebar Navigation */}
        <aside className="w-64 border-r border-surface-700 bg-surface-950/40 shrink-0 flex flex-col p-4">
          <div className="flex items-center gap-2 mb-6 px-2">
            <Sliders className="text-accent-500" size={16} />
            <span className="font-bold text-sm tracking-wider uppercase">Settings</span>
          </div>

          <nav className="flex-1 space-y-1">
            <button
              onClick={() => setActiveCategory("appearance")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "appearance"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <Palette size={14} /> Swatch &amp; Appearance
            </button>
            <button
              onClick={() => setActiveCategory("ai")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "ai"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <Server size={14} /> AI Providers
            </button>
            <button
              onClick={() => setActiveCategory("editor")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "editor"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <Sliders size={14} /> Editor (Monaco)
            </button>
            <button
              onClick={() => setActiveCategory("terminal")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "terminal"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <TermIcon size={14} /> Terminal
            </button>
            <button
              onClick={() => setActiveCategory("git")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "git"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <GitBranch size={14} /> Git Configuration
            </button>
            <button
              onClick={() => setActiveCategory("agents")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "agents"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <Cpu size={14} /> Agents &amp; Duo
            </button>
            <button
              onClick={() => setActiveCategory("security")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "security"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <Lock size={14} /> Security &amp; Privacy
            </button>
            <button
              onClick={() => setActiveCategory("about")}
              className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-all ${
                activeCategory === "about"
                  ? "bg-accent-500 text-white shadow-md shadow-accent-500/10"
                  : "text-slate-400 hover:bg-surface-800 hover:text-white"
              }`}
            >
              <Info size={14} /> About
            </button>
          </nav>

          <div className="text-[10px] text-slate-600 px-2 mt-auto">
            Press <kbd className="bg-surface-800 px-1 py-0.5 rounded">ESC</kbd> to close
          </div>
        </aside>

        {/* Right Content Area */}
        <main className="flex-1 min-w-0 bg-surface-900 p-6 overflow-y-auto">
          {/* Header */}
          <div className="border-b border-surface-700 pb-3 mb-5 flex items-center justify-between">
            <h2 className="text-base font-bold text-white capitalize">{activeCategory} Settings</h2>
          </div>

          {/* ── Category: Appearance ───────────────────────────────────────── */}
          {activeCategory === "appearance" && (
            <div className="space-y-6">
              {/* Themes Swatch Grid */}
              <div>
                <label className="text-xs text-slate-400 font-semibold mb-2 block">Theme Palette Swatches</label>
                <div className="grid grid-cols-4 gap-3">
                  {THEME_SWATCHES.map((swatch) => {
                    const isActive = (settings.theme ?? "dark") === swatch.id;
                    return (
                      <button
                        key={swatch.id}
                        onClick={async () => {
                          await saveSetting("theme", swatch.id);
                          setAppearanceSaveFeedback(true);
                          setTimeout(() => setAppearanceSaveFeedback(false), 2000);
                        }}
                        className={`group relative flex flex-col justify-between p-3 rounded-lg border-2 text-left transition-all ${
                          isActive
                            ? "border-accent-500 bg-surface-800 scale-[1.02] shadow-lg shadow-accent-500/5"
                            : "border-surface-700 bg-surface-950/40 hover:border-surface-600 hover:bg-surface-850"
                        }`}
                        style={{ height: "72px" }}
                      >
                        <div className="text-xs font-bold text-slate-200 group-hover:text-white truncate">
                          {swatch.name}
                        </div>
                        
                        {/* Swatch indicators */}
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className="w-3 h-3 rounded-full border border-slate-700" style={{ backgroundColor: swatch.bg }} title="Background" />
                          <span className="w-3 h-3 rounded-full border border-slate-700" style={{ backgroundColor: swatch.accent }} title="Accent" />
                          <span className="w-3 h-3 rounded-full border border-slate-700" style={{ backgroundColor: swatch.text }} title="Text" />
                        </div>

                        {isActive && (
                          <span className="absolute top-2 right-2 text-accent-500">
                            <Check size={14} />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                {/* Editor Font Family */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Editor Font Family</label>
                  <input
                    type="text"
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500 font-mono"
                    value={editorFontFamily}
                    onChange={(e) => {
                      setEditorFontFamily(e.target.value);
                      localStorage.setItem("code-os:editor.fontFamily", e.target.value);
                      setAppearanceSaveFeedback(true);
                      setTimeout(() => setAppearanceSaveFeedback(false), 2000);
                    }}
                  />
                  <p className="text-[10px] text-slate-500 mt-1">Comma-separated list of fallback monospace fonts.</p>
                </div>

                {/* Status Indicator */}
                <div className="flex items-end justify-start pb-2">
                  {appearanceSaveFeedback && (
                    <span className="text-emerald-400 text-xs flex items-center gap-1">
                      <Check size={12} /> Theme variables applied
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── Category: AI Providers ─────────────────────────────────────── */}
          {activeCategory === "ai" && (
            <div className="space-y-6">
              {/* Ollama Defaults */}
              <div className="rounded-lg border border-surface-700 bg-surface-950/20 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  Local Inference (Ollama)
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-slate-500 block mb-1">Ollama Server Base URL</label>
                    <input
                      type="text"
                      className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                      value={aiBaseUrl}
                      onChange={async (e) => {
                        useAIStore.setState({ baseUrl: e.target.value });
                        await saveSetting("ollama.baseUrl", e.target.value);
                      }}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-500 block mb-1">Default Ollama Model</label>
                    <input
                      type="text"
                      className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                      value={aiModel}
                      onChange={async (e) => {
                        useAIStore.setState({ model: e.target.value });
                        await saveSetting("ollama.model", e.target.value);
                      }}
                    />
                    {/(^|[-_/:])(r1|o1|o3|reasoner|reasoning|thinking)([-_/:]|$)/i.test(aiModel) && (
                      <p className="mt-1 text-[10px] leading-relaxed text-amber-300">
                        Reasoning model detected: it may take longer before streaming a response.
                      </p>
                    )}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 border-t border-surface-800 pt-3">
                  <div>
                    <label className="text-xs text-slate-500 block mb-1">Local request timeout (seconds)</label>
                    <input
                      type="number"
                      min="5"
                      max="900"
                      className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                      value={settings["ai.provider.ollama.timeout_seconds"] ?? "300"}
                      onChange={async (e) => saveSetting("ai.provider.ollama.timeout_seconds", e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-500 block mb-1">API request timeout (seconds)</label>
                    <input
                      type="number"
                      min="5"
                      max="900"
                      className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                      value={settings["ai.provider.api.timeout_seconds"] ?? "60"}
                      onChange={async (e) => saveSetting("ai.provider.api.timeout_seconds", e.target.value)}
                    />
                  </div>
                  <p className="col-span-2 text-[10px] text-slate-600">Specific provider overrides use `ai.provider.&lt;provider-id&gt;.timeout_seconds` and `.retries`.</p>
                </div>
              </div>

              {/* API Keys Header */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                    Encrypted Provider Keys
                  </h3>
                  <span className="text-[10px] text-slate-500">
                    {configuredKeys.length} preset key(s) configured
                  </span>
                </div>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Keys are stored encrypted locally. Select providers will use their specific credentials instead of sharing a global key slot.
                </p>

                {/* Swatch-like expandable API key rows */}
                <div className="grid grid-cols-2 gap-3">
                  {PROVIDER_PRESETS.filter(
                    (p) => p.group === "api" && p.api_key_provider !== null
                  ).map((p) => {
                    const keyId = p.api_key_provider!;
                    const isSet = configuredKeys.includes(keyId);
                    const status = keySaveStatus[keyId] || "idle";

                    return (
                      <div
                        key={p.id}
                        className="rounded-lg border border-surface-700 bg-surface-950/20 p-3 space-y-2 flex flex-col justify-between"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-slate-300">{p.label}</span>
                          <span className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase border ${
                            isSet
                              ? "text-emerald-400 bg-emerald-400/5 border-emerald-500/20"
                              : "text-slate-500 bg-surface-800 border-surface-700"
                          }`}>
                            {isSet ? <><Check size={8} /> Saved</> : "Not configured"}
                          </span>
                        </div>

                        {p.note && (
                          <p className="text-[9px] text-slate-600 line-clamp-1 leading-normal" title={p.note}>
                            {p.note}
                          </p>
                        )}

                        <div className="flex gap-1.5 mt-1.5">
                          <input
                            type="password"
                            placeholder={isSet ? "••••••••••••••••" : p.api_key_prefix ? `${p.api_key_prefix}…` : "sk-…"}
                            value={keyInputs[keyId] || ""}
                            onChange={(e) => setKeyInputs((i) => ({ ...i, [keyId]: e.target.value }))}
                            className="h-7 flex-1 min-w-0 rounded border border-surface-650 bg-surface-850 px-2 text-[11px] text-slate-200 focus:outline-none focus:border-accent-500 font-mono"
                          />
                          <button
                            onClick={() => void handleSaveKey(keyId)}
                            disabled={!keyInputs[keyId]?.trim() || status === "saving"}
                            className="h-7 flex items-center gap-1 rounded bg-surface-800 border border-surface-650 px-2 text-[11px] text-slate-300 hover:bg-surface-700 disabled:opacity-40 transition-colors"
                          >
                            {status === "saving" ? "Saving…" : status === "saved" ? "Saved!" : <><KeyRound size={10} /> Store</>}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ── Category: Editor ───────────────────────────────────────────── */}
          {activeCategory === "editor" && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                {/* Font Size */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Editor Font Size (px)</label>
                  <input
                    type="number"
                    min={10}
                    max={32}
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                    value={editorFontSize}
                    onChange={(e) => {
                      setEditorSetting({ fontSize: Number(e.target.value) });
                      setEditorSaveFeedback(true);
                      setTimeout(() => setEditorSaveFeedback(false), 2000);
                    }}
                  />
                </div>

                {/* Tab Size */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Tab Indentation Size</label>
                  <input
                    type="number"
                    min={2}
                    max={8}
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                    value={editorTabSize}
                    onChange={(e) => {
                      setEditorSetting({ tabSize: Number(e.target.value) });
                      setEditorSaveFeedback(true);
                      setTimeout(() => setEditorSaveFeedback(false), 2000);
                    }}
                  />
                </div>
              </div>

              {/* Toggles */}
              <div className="rounded-lg border border-surface-700 bg-surface-950/20 p-4 space-y-3.5">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editorAutoSave}
                    onChange={(e) => setAutoSave(e.target.checked)}
                    className="rounded text-accent-500 focus:ring-accent-500"
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-200 block">Auto Save Changes</span>
                    <span className="text-[10px] text-slate-500">Automatically save modified code files on editor keystrokes.</span>
                  </div>
                </label>

                <label className="flex items-center gap-2 cursor-pointer border-t border-surface-800 pt-3">
                  <input
                    type="checkbox"
                    checked={editorWordWrap}
                    onChange={(e) => {
                      setEditorWordWrap(e.target.checked);
                      localStorage.setItem("code-os:editor.wordWrap", e.target.checked ? "on" : "off");
                      setEditorSaveFeedback(true);
                      setTimeout(() => setEditorSaveFeedback(false), 2000);
                    }}
                    className="rounded text-accent-500 focus:ring-accent-500"
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-200 block">Word Wrap</span>
                    <span className="text-[10px] text-slate-500">Wrap long lines to fit the current editor workspace width.</span>
                  </div>
                </label>

                <label className="flex items-center gap-2 cursor-pointer border-t border-surface-800 pt-3">
                  <input
                    type="checkbox"
                    checked={editorMinimap}
                    onChange={(e) => {
                      setEditorMinimap(e.target.checked);
                      localStorage.setItem("code-os:editor.minimap", String(e.target.checked));
                      setEditorSaveFeedback(true);
                      setTimeout(() => setEditorSaveFeedback(false), 2000);
                    }}
                    className="rounded text-accent-500 focus:ring-accent-500"
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-200 block">Code Minimap</span>
                    <span className="text-[10px] text-slate-500">Show vertical visual outline on the right hand side of the editor pane.</span>
                  </div>
                </label>
              </div>

              {/* Status Indicator */}
              {editorSaveFeedback && (
                <div className="text-emerald-400 text-xs flex items-center gap-1">
                  <Check size={12} /> Monaco configurations updated (takes effect next file open)
                </div>
              )}
            </div>
          )}

          {/* ── Category: Terminal ─────────────────────────────────────────── */}
          {activeCategory === "terminal" && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                {/* Shell Preference */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Shell Executable Path</label>
                  <input
                    type="text"
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500 font-mono"
                    value={termShell}
                    onChange={(e) => {
                      setTermShell(e.target.value);
                      localStorage.setItem("code-os:terminal.shell", e.target.value);
                      setTerminalSaveFeedback(true);
                      setTimeout(() => setTerminalSaveFeedback(false), 2000);
                    }}
                  />
                  <p className="text-[10px] text-slate-500 mt-1">e.g. powershell.exe, cmd.exe, bash.exe</p>
                </div>

                {/* Cursor Style */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Cursor Animation Style</label>
                  <select
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                    value={termCursorStyle}
                    onChange={(e) => {
                      setTermCursorStyle(e.target.value);
                      localStorage.setItem("code-os:terminal.cursorStyle", e.target.value);
                      setTerminalSaveFeedback(true);
                      setTimeout(() => setTerminalSaveFeedback(false), 2000);
                    }}
                  >
                    <option value="block">Block (█)</option>
                    <option value="underline">Underline (_)</option>
                    <option value="bar">Line (│)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                {/* Font Size */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Terminal Font Size (pt)</label>
                  <input
                    type="number"
                    min={9}
                    max={24}
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                    value={termFontSize}
                    onChange={(e) => {
                      const num = Number(e.target.value);
                      setTermFontSize(num);
                      localStorage.setItem("code-os:terminal.fontSize", String(num));
                      setTerminalSaveFeedback(true);
                      setTimeout(() => setTerminalSaveFeedback(false), 2000);
                    }}
                  />
                </div>

                {/* Font Family */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Terminal Font Family</label>
                  <input
                    type="text"
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500 font-mono"
                    value={termFontFamily}
                    onChange={(e) => {
                      setTermFontFamily(e.target.value);
                      localStorage.setItem("code-os:terminal.fontFamily", e.target.value);
                      setTerminalSaveFeedback(true);
                      setTimeout(() => setTerminalSaveFeedback(false), 2000);
                    }}
                  />
                </div>
              </div>

              {/* Status Indicator */}
              {terminalSaveFeedback && (
                <div className="text-emerald-400 text-xs flex items-center gap-1">
                  <Check size={12} /> Terminal styling persisted (restart terminal tab to apply)
                </div>
              )}
            </div>
          )}

          {/* ── Category: Git ─────────────────────────────────────────────── */}
          {activeCategory === "git" && (
            <div className="space-y-6">
              <div className="rounded-lg border border-surface-700 bg-surface-950/20 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Version Control Operations
                </h3>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={gitAutoPoll}
                    onChange={(e) => {
                      setGitAutoPoll(e.target.checked);
                      localStorage.setItem("code-os:git.autoPoll", String(e.target.checked));
                      setGitSaveFeedback(true);
                      setTimeout(() => setGitSaveFeedback(false), 2000);
                    }}
                    className="rounded text-accent-500 focus:ring-accent-500"
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-200 block">Automatic Status Polling</span>
                    <span className="text-[10px] text-slate-500">Poll git local repositories every 5 seconds to sync sidebars.</span>
                  </div>
                </label>

                <label className="flex items-center gap-2 cursor-pointer border-t border-surface-800 pt-3">
                  <input
                    type="checkbox"
                    checked={gitSignCommits}
                    onChange={(e) => {
                      setGitSignCommits(e.target.checked);
                      localStorage.setItem("code-os:git.signCommits", String(e.target.checked));
                      setGitSaveFeedback(true);
                      setTimeout(() => setGitSaveFeedback(false), 2000);
                    }}
                    className="rounded text-accent-500 focus:ring-accent-500"
                  />
                  <div>
                    <span className="text-xs font-semibold text-slate-200 block">GPG Commit Signoff</span>
                    <span className="text-[10px] text-slate-500">Append signoff metadata flag to commits executed via the Git console panel.</span>
                  </div>
                </label>
              </div>

              {/* Status Indicator */}
              {gitSaveFeedback && (
                <div className="text-emerald-400 text-xs flex items-center gap-1">
                  <Check size={12} /> Git configs saved
                </div>
              )}
            </div>
          )}

          {/* ── Category: Agents & Duo ─────────────────────────────────────── */}
          {activeCategory === "agents" && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                {/* Max rounds */}
                <div>
                  <label className="text-xs text-slate-400 block mb-1">Duo Loop Max Rounds</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                    value={duoMaxRounds}
                    onChange={(e) => {
                      const val = Math.max(1, Math.min(20, Number(e.target.value)));
                      setDuoMaxRounds(val);
                      localStorage.setItem("code-os:duo.maxRounds", String(val));
                      setAgentsSaveFeedback(true);
                      setTimeout(() => setAgentsSaveFeedback(false), 2000);
                    }}
                  />
                </div>
              </div>

              <div className="rounded-lg border border-surface-700 bg-surface-950/20 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Default Models for Autonomous Roles
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-slate-500 block mb-1">Planner Agent Default Model</label>
                    <input
                      type="text"
                      className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                      value={agentPlannerModel}
                      onChange={(e) => {
                        setAgentPlannerModel(e.target.value);
                        localStorage.setItem("code-os:agent.plannerModel", e.target.value);
                        setAgentsSaveFeedback(true);
                        setTimeout(() => setAgentsSaveFeedback(false), 2000);
                      }}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-500 block mb-1">Developer Agent Default Model</label>
                    <input
                      type="text"
                      className="w-full rounded bg-surface-800 border border-surface-650 px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                      value={agentDeveloperModel}
                      onChange={(e) => {
                        setAgentDeveloperModel(e.target.value);
                        localStorage.setItem("code-os:agent.developerModel", e.target.value);
                        setAgentsSaveFeedback(true);
                        setTimeout(() => setAgentsSaveFeedback(false), 2000);
                      }}
                    />
                  </div>
                </div>
              </div>

              {/* Status Indicator */}
              {agentsSaveFeedback && (
                <div className="text-emerald-400 text-xs flex items-center gap-1">
                  <Check size={12} /> Agent presets updated
                </div>
              )}
            </div>
          )}

          {/* ── Category: Security & Privacy ────────────────────────────────── */}
          {activeCategory === "security" && (
            <div className="space-y-6">
              <div className="rounded-lg border border-surface-700 bg-surface-950/20 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Data Reset Options
                </h3>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Reset local settings, encrypted API keys, or clear autonomous agent logs and execution history.
                </p>

                <div className="flex flex-col gap-3 max-w-sm pt-2">
                  <Button
                    variant="danger"
                    onClick={async () => {
                      if (confirm("Are you sure you want to clear all encrypted API keys? This action cannot be undone.")) {
                        await api.delete("/api/settings/api-keys");
                        alert("API keys cleared.");
                        void refreshKeys();
                      }
                    }}
                    className="w-full text-center"
                  >
                    Clear Configured API Keys
                  </Button>

                  <Button
                    variant="danger"
                    onClick={async () => {
                      if (confirm("Are you sure you want to clear all conversation threads, Duo loop session histories, and agent job queues?")) {
                        await api.delete("/api/settings/history");
                        alert("Chat, Duo, and Agent histories cleared.");
                      }
                    }}
                    className="w-full text-center"
                  >
                    Clear Chat &amp; Job History
                  </Button>

                  <Button
                    variant="danger"
                    onClick={async () => {
                      if (confirm("Are you sure you want to reset all workspace trust decisions? You will be prompted to trust workspaces when opening them again.")) {
                        await api.delete("/api/workspaces/trust");
                        const wsStore = (window as any).useWorkspaceStore;
                        if (wsStore) {
                          wsStore.getState().setRestrictedMode(true);
                        }
                        alert("Workspace trust decisions reset.");
                      }
                    }}
                    className="w-full text-center"
                  >
                    Reset Workspace Trust Decisions
                  </Button>
                </div>
              </div>

              <div className="rounded-lg border border-surface-700 bg-surface-950/20 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Walkthrough &amp; Onboarding
                </h3>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Restart the interactive walkthrough and tutorial spotlight. This will reload the workspace to launch the onboarding flow.
                </p>
                <Button
                  variant="primary"
                  id="btn-replay-tutorial"
                  onClick={() => {
                    if (confirm("Restart onboarding tutorial? The application will reload to initiate the walkthrough.")) {
                      localStorage.setItem("code-os:onboarding-complete", "false");
                      window.location.reload();
                    }
                  }}
                  className="animate-pulse"
                >
                  Replay Tutorial Walkthrough
                </Button>
              </div>
            </div>
          )}

          {/* ── Category: About ────────────────────────────────────────────── */}
          {activeCategory === "about" && (
            <div className="space-y-5 py-2">
              <div className="flex items-center gap-3">
                <div>
                  <CodeOsLogo className="px-2 py-1.5" imageClassName="h-8 w-[170px]" priority />
                  <p className="text-xs text-slate-400">Version 0.2.0 — Stable Channel</p>
                </div>
              </div>

              <div className="border-t border-surface-700 pt-4 space-y-2 text-xs text-slate-400 leading-relaxed max-w-xl">
                <p>
                  A production-ready agentic AI development environment, built for pair-programming and autonomous generator/critic validation loops.
                </p>
                <p>
                  Powered by a background DAG scheduling execution engine, integrated git change-logs, and direct hardware PTY WebSocket connection.
                </p>
              </div>

              <div className="flex gap-3 pt-2">
                <a
                  href="https://github.com/google-deepmind"
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs text-accent-400 hover:text-accent-300 font-semibold"
                >
                  DeepMind AI Group <ExternalLink size={12} />
                </a>
              </div>
            </div>
          )}

        </main>
      </div>
    </div>
  );
}
