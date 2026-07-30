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
  { id: "dark", name: "Dark (Default)", bg: "#131314", accent: "#00daf3", text: "#e5e2e3", isDark: true },
  { id: "light", name: "Light (White)", bg: "#ffffff", accent: "#00838f", text: "#1f2328", isDark: false },
  { id: "void", name: "Void (OLED)", bg: "#000000", accent: "#a1a1aa", text: "#e4e4e7", isDark: true },
  { id: "cyberpunk", name: "Cyberpunk (Neon)", bg: "#080b12", accent: "#00e5ff", text: "#dcf1f5", isDark: true },
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

  const modalRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    modalRef.current?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4"
      role="dialog"
      aria-modal="true"
      data-testid="settings-modal"
      tabIndex={-1}
      ref={modalRef}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      {/* Full-page premium settings container */}
      <div className="relative w-full max-w-5xl h-[88vh] rounded-2xl overflow-hidden shadow-2xl shadow-black/50 flex border border-white/8"
        style={{ background: "linear-gradient(135deg, rgba(19,19,20,0.97) 0%, rgba(28,27,28,0.98) 100%)" }}>
        
        {/* Glow accent top edge */}
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/50 to-transparent pointer-events-none" />
        
        {/* Close Button */}
        <button
          onClick={onClose}
          aria-label="Close Settings"
          className="absolute top-4 right-4 z-20 w-8 h-8 flex items-center justify-center rounded-lg text-on-surface-variant/60 hover:text-on-surface hover:bg-white/5 transition-all active:scale-95"
          title="Close Settings (Esc)"
        >
          <X size={16} />
        </button>


        {/* Left Sidebar Navigation */}
        <aside className="w-56 border-r border-white/5 shrink-0 flex flex-col p-4 select-none">
          {/* Brand header */}
          <div className="flex items-center gap-2.5 mb-6 px-2 pb-4 border-b border-white/5">
            <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
              <Sliders size={14} className="text-primary" />
            </div>
            <span className="font-bold text-sm text-on-surface tracking-tight">Settings</span>
          </div>

          <nav className="flex-1 space-y-0.5">
            {([
              { key: "appearance", icon: <Palette size={14} />, label: "Appearance" },
              { key: "ai", icon: <Server size={14} />, label: "AI Providers" },
              { key: "editor", icon: <Sliders size={14} />, label: "Editor" },
              { key: "terminal", icon: <TermIcon size={14} />, label: "Terminal" },
              { key: "git", icon: <GitBranch size={14} />, label: "Git" },
              { key: "agents", icon: <Cpu size={14} />, label: "Agents & Duo" },
              { key: "security", icon: <Lock size={14} />, label: "Security" },
              { key: "about", icon: <Info size={14} />, label: "About" },
            ] as { key: Category; icon: React.ReactNode; label: string }[]).map(({ key, icon, label }) => (
              <button
                key={key}
                onClick={() => setActiveCategory(key)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-xs font-medium transition-all ${
                  activeCategory === key
                    ? "bg-primary/10 text-primary border border-primary/20 shadow-[0_0_10px_rgba(0,229,255,0.08)]"
                    : "text-on-surface-variant hover:bg-white/5 hover:text-on-surface border border-transparent"
                }`}
              >
                <span className={activeCategory === key ? "text-primary" : "text-on-surface-variant/60"}>{icon}</span>
                {label}
              </button>
            ))}
          </nav>

          <div className="text-[10px] text-on-surface-variant/30 px-2 mt-auto pt-4 border-t border-white/5">
            Press <kbd className="bg-white/5 px-1.5 py-0.5 rounded text-[9px] border border-white/10">ESC</kbd> to close
          </div>
        </aside>

        {/* Right Content Area */}
        <main className="flex-1 min-w-0 p-6 overflow-y-auto">
          {/* Section header */}
          <div className="flex items-center gap-3 border-b border-white/5 pb-4 mb-6">
            <h2 className="text-base font-bold text-on-surface capitalize tracking-tight">
              {activeCategory === "ai" ? "AI Providers" :
               activeCategory === "agents" ? "Agents & Duo" :
               activeCategory === "security" ? "Security & Privacy" :
               `${activeCategory.charAt(0).toUpperCase() + activeCategory.slice(1)} Settings`}
            </h2>
          </div>

          {/* ── Category: Appearance ───────────────────────────────────────── */}
          {activeCategory === "appearance" && (
            <div className="space-y-6">
              {/* Themes Swatch Grid */}
              <div>
                <label className="text-xs text-on-surface-variant font-semibold mb-3 block uppercase tracking-wider">Theme Palette</label>
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
                        className={`group relative flex flex-col justify-between p-3 rounded-xl border-2 text-left transition-all active:scale-95 ${
                          isActive
                            ? "border-primary bg-primary/5 shadow-[0_0_16px_rgba(0,229,255,0.15)] scale-[1.02]"
                            : "border-white/8 bg-white/3 hover:border-white/15 hover:bg-white/5"
                        }`}
                        style={{ height: "80px" }}
                      >
                        <div className={`text-xs font-bold truncate ${isActive ? "text-primary" : "text-on-surface-variant"}`}>
                          {swatch.name}
                        </div>
                        
                        {/* Swatch indicators */}
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className="w-4 h-4 rounded-full border border-white/10 shadow-sm" style={{ backgroundColor: swatch.bg }} title="Background" />
                          <span className="w-4 h-4 rounded-full border border-white/10 shadow-sm" style={{ backgroundColor: swatch.accent }} title="Accent" />
                          <span className="w-4 h-4 rounded-full border border-white/10 shadow-sm" style={{ backgroundColor: swatch.text }} title="Text" />
                        </div>

                        {isActive && (
                          <span className="absolute top-2 right-2 text-primary">
                            <Check size={13} />
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
                  <label className="text-xs text-on-surface-variant block mb-1.5">Editor Font Family</label>
                  <input
                    type="text"
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50 font-mono"
                    value={editorFontFamily}
                    onChange={(e) => {
                      setEditorFontFamily(e.target.value);
                      localStorage.setItem("code-os:editor.fontFamily", e.target.value);
                      setAppearanceSaveFeedback(true);
                      setTimeout(() => setAppearanceSaveFeedback(false), 2000);
                    }}
                  />
                  <p className="text-[10px] text-on-surface-variant/40 mt-1">Comma-separated fallback monospace fonts.</p>
                </div>

                {/* Status Indicator */}
                <div className="flex items-end justify-start pb-2">
                  {appearanceSaveFeedback && (
                    <span className="text-primary text-xs flex items-center gap-1">
                      <Check size={12} /> Applied
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
              <div className="rounded-xl border border-white/8 bg-white/3 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-primary flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[14px]">computer</span>
                  Local Inference (Ollama)
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-on-surface-variant block mb-1.5">Ollama Server Base URL</label>
                    <input
                      type="text"
                      className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                      value={aiBaseUrl}
                      onChange={async (e) => {
                        useAIStore.setState({ baseUrl: e.target.value });
                        await saveSetting("ollama.baseUrl", e.target.value);
                      }}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-on-surface-variant block mb-1.5">Default Ollama Model</label>
                    <input
                      type="text"
                      className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                      value={aiModel}
                      onChange={async (e) => {
                        useAIStore.setState({ model: e.target.value });
                        await saveSetting("ollama.model", e.target.value);
                      }}
                    />
                    {/(^|[-_/:])(r1|o1|o3|reasoner|reasoning|thinking)([-_/:]|$)/i.test(aiModel) && (
                      <p className="mt-1 text-[10px] leading-relaxed text-tertiary/80">
                        Reasoning model detected: may take longer before streaming.
                      </p>
                    )}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 border-t border-white/5 pt-3">
                  <div>
                    <label className="text-xs text-on-surface-variant block mb-1.5">Local request timeout (seconds)</label>
                    <input
                      type="number" min="5" max="900"
                      className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                      value={settings["ai.provider.ollama.timeout_seconds"] ?? "300"}
                      onChange={async (e) => saveSetting("ai.provider.ollama.timeout_seconds", e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-on-surface-variant block mb-1.5">API request timeout (seconds)</label>
                    <input
                      type="number" min="5" max="900"
                      className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                      value={settings["ai.provider.api.timeout_seconds"] ?? "60"}
                      onChange={async (e) => saveSetting("ai.provider.api.timeout_seconds", e.target.value)}
                    />
                  </div>
                </div>
              </div>

              {/* API Keys */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-secondary">
                    Encrypted Provider Keys
                  </h3>
                  <span className="text-[10px] text-on-surface-variant/50 bg-white/5 px-2 py-0.5 rounded">
                    {configuredKeys.length} configured
                  </span>
                </div>
                <p className="text-xs text-on-surface-variant/60 leading-relaxed">
                  Keys are stored encrypted locally. Each provider uses its own key slot.
                </p>
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
                        className="rounded-xl border border-white/8 bg-white/3 p-3 space-y-2 flex flex-col justify-between"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-on-surface">{p.label}</span>
                          <span className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase border ${
                            isSet
                              ? "text-primary bg-primary/5 border-primary/20"
                              : "text-on-surface-variant/50 bg-white/3 border-white/8"
                          }`}>
                            {isSet ? <><Check size={8} /> Saved</> : "Not set"}
                          </span>
                        </div>
                        {p.note && (
                          <p className="text-[9px] text-on-surface-variant/40 line-clamp-1" title={p.note}>{p.note}</p>
                        )}
                        <div className="flex gap-1.5 mt-1.5">
                          <input
                            type="password"
                            placeholder={isSet ? "••••••••••••••••" : p.api_key_prefix ? `${p.api_key_prefix}…` : "sk-…"}
                            value={keyInputs[keyId] || ""}
                            onChange={(e) => setKeyInputs((i) => ({ ...i, [keyId]: e.target.value }))}
                            className="h-7 flex-1 min-w-0 rounded-lg border border-white/10 bg-white/5 px-2 text-[11px] text-on-surface focus:outline-none focus:border-primary/50 font-mono"
                          />
                          <button
                            onClick={() => void handleSaveKey(keyId)}
                            disabled={!keyInputs[keyId]?.trim() || status === "saving"}
                            className="h-7 flex items-center gap-1 rounded-lg bg-primary/10 border border-primary/20 px-2 text-[11px] text-primary hover:bg-primary/20 disabled:opacity-40 transition-colors"
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
                <div>
                  <label className="text-xs text-on-surface-variant block mb-1.5">Editor Font Size (px)</label>
                  <input
                    type="number" min={10} max={32}
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                    value={editorFontSize}
                    onChange={(e) => {
                      setEditorSetting({ fontSize: Number(e.target.value) });
                      setEditorSaveFeedback(true);
                      setTimeout(() => setEditorSaveFeedback(false), 2000);
                    }}
                  />
                </div>
                <div>
                  <label className="text-xs text-on-surface-variant block mb-1.5">Tab Indentation Size</label>
                  <input
                    type="number" min={2} max={8}
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                    value={editorTabSize}
                    onChange={(e) => {
                      setEditorSetting({ tabSize: Number(e.target.value) });
                      setEditorSaveFeedback(true);
                      setTimeout(() => setEditorSaveFeedback(false), 2000);
                    }}
                  />
                </div>
              </div>

              <div className="rounded-xl border border-white/8 bg-white/3 p-4 space-y-4">
                {[
                  { checked: editorAutoSave, onChange: (c: boolean) => setAutoSave(c), label: "Auto Save Changes", desc: "Automatically save modified files on editor keystrokes.", border: false },
                  { checked: editorWordWrap, onChange: (c: boolean) => { setEditorWordWrap(c); localStorage.setItem("code-os:editor.wordWrap", c ? "on" : "off"); setEditorSaveFeedback(true); setTimeout(() => setEditorSaveFeedback(false), 2000); }, label: "Word Wrap", desc: "Wrap long lines to fit the current editor width.", border: true },
                  { checked: editorMinimap, onChange: (c: boolean) => { setEditorMinimap(c); localStorage.setItem("code-os:editor.minimap", String(c)); setEditorSaveFeedback(true); setTimeout(() => setEditorSaveFeedback(false), 2000); }, label: "Code Minimap", desc: "Show visual outline on the right side of the editor pane.", border: true },
                ].map(({ checked, onChange, label, desc, border }) => (
                  <label key={label} className={`flex items-center gap-3 cursor-pointer ${border ? "border-t border-white/5 pt-3" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => onChange(e.target.checked)}
                      className="rounded accent-primary w-3.5 h-3.5"
                    />
                    <div>
                      <span className="text-xs font-semibold text-on-surface block">{label}</span>
                      <span className="text-[10px] text-on-surface-variant/50">{desc}</span>
                    </div>
                  </label>
                ))}
              </div>

              {editorSaveFeedback && (
                <div className="text-primary text-xs flex items-center gap-1">
                  <Check size={12} /> Monaco configurations updated
                </div>
              )}
            </div>
          )}

          {/* ── Category: Terminal ─────────────────────────────────────────── */}
          {activeCategory === "terminal" && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-on-surface-variant block mb-1.5">Shell Executable Path</label>
                  <input
                    type="text"
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50 font-mono"
                    value={termShell}
                    onChange={(e) => {
                      setTermShell(e.target.value);
                      localStorage.setItem("code-os:terminal.shell", e.target.value);
                      setTerminalSaveFeedback(true);
                      setTimeout(() => setTerminalSaveFeedback(false), 2000);
                    }}
                  />
                  <p className="text-[10px] text-on-surface-variant/40 mt-1">e.g. powershell.exe, cmd.exe, bash.exe</p>
                </div>
                <div>
                  <label className="text-xs text-on-surface-variant block mb-1.5">Cursor Animation Style</label>
                  <select
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
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
                <div>
                  <label className="text-xs text-on-surface-variant block mb-1.5">Terminal Font Size (pt)</label>
                  <input
                    type="number" min={9} max={24}
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
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
                <div>
                  <label className="text-xs text-on-surface-variant block mb-1.5">Terminal Font Family</label>
                  <input
                    type="text"
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50 font-mono"
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
              {terminalSaveFeedback && (
                <div className="text-primary text-xs flex items-center gap-1">
                  <Check size={12} /> Terminal styling persisted
                </div>
              )}
            </div>
          )}

          {/* ── Category: Git ─────────────────────────────────────────────── */}
          {activeCategory === "git" && (
            <div className="space-y-6">
              <div className="rounded-xl border border-white/8 bg-white/3 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-secondary">Version Control</h3>
                {[
                  { checked: gitAutoPoll, onChange: (c: boolean) => { setGitAutoPoll(c); localStorage.setItem("code-os:git.autoPoll", String(c)); setGitSaveFeedback(true); setTimeout(() => setGitSaveFeedback(false), 2000); }, label: "Automatic Status Polling", desc: "Poll git repositories every 5s to sync sidebar.", border: false },
                  { checked: gitSignCommits, onChange: (c: boolean) => { setGitSignCommits(c); localStorage.setItem("code-os:git.signCommits", String(c)); setGitSaveFeedback(true); setTimeout(() => setGitSaveFeedback(false), 2000); }, label: "GPG Commit Signoff", desc: "Append signoff flag to commits via the Git console.", border: true },
                ].map(({ checked, onChange, label, desc, border }) => (
                  <label key={label} className={`flex items-center gap-3 cursor-pointer ${border ? "border-t border-white/5 pt-3" : ""}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => onChange(e.target.checked)}
                      className="rounded accent-primary w-3.5 h-3.5"
                    />
                    <div>
                      <span className="text-xs font-semibold text-on-surface block">{label}</span>
                      <span className="text-[10px] text-on-surface-variant/50">{desc}</span>
                    </div>
                  </label>
                ))}
              </div>
              {gitSaveFeedback && (
                <div className="text-primary text-xs flex items-center gap-1">
                  <Check size={12} /> Git configs saved
                </div>
              )}
            </div>
          )}

          {/* ── Category: Agents & Duo ─────────────────────────────────────── */}
          {activeCategory === "agents" && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-on-surface-variant block mb-1.5">Duo Loop Max Rounds</label>
                  <input
                    type="number" min={1} max={20}
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
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
              <div className="rounded-xl border border-white/8 bg-white/3 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-tertiary/80">Default Models for Autonomous Roles</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-on-surface-variant block mb-1.5">Planner Agent Model</label>
                    <input
                      type="text"
                      className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                      value={agentPlannerModel}
                      onChange={(e) => { setAgentPlannerModel(e.target.value); localStorage.setItem("code-os:agent.plannerModel", e.target.value); setAgentsSaveFeedback(true); setTimeout(() => setAgentsSaveFeedback(false), 2000); }}
                    />
                  </div>
                  <div>
                    <label className="text-xs text-on-surface-variant block mb-1.5">Developer Agent Model</label>
                    <input
                      type="text"
                      className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary/50"
                      value={agentDeveloperModel}
                      onChange={(e) => { setAgentDeveloperModel(e.target.value); localStorage.setItem("code-os:agent.developerModel", e.target.value); setAgentsSaveFeedback(true); setTimeout(() => setAgentsSaveFeedback(false), 2000); }}
                    />
                  </div>
                </div>
              </div>
              {agentsSaveFeedback && (
                <div className="text-primary text-xs flex items-center gap-1">
                  <Check size={12} /> Agent presets updated
                </div>
              )}
            </div>
          )}

          {/* ── Category: Security & Privacy ────────────────────────────────── */}
          {activeCategory === "security" && (
            <div className="space-y-6">
              <div className="rounded-xl border border-error/20 bg-error/3 p-4 space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-error/80">Data Reset Options</h3>
                <p className="text-[11px] text-on-surface-variant/60 leading-relaxed">
                  Reset local settings, encrypted API keys, or clear autonomous agent logs and execution history.
                </p>
                <div className="flex flex-col gap-3 max-w-sm pt-2">
                  {[
                    { label: "Clear API Keys", action: async () => { if (confirm("Clear all encrypted API keys? Cannot be undone.")) { await api.delete("/api/settings/api-keys"); void refreshKeys(); alert("API keys cleared."); } } },
                    { label: "Clear Chat & Job History", action: async () => { if (confirm("Clear all conversation threads, Duo sessions, and agent queues?")) { await api.delete("/api/settings/history"); alert("Histories cleared."); } } },
                    { label: "Reset Workspace Trust", action: async () => { if (confirm("Reset all workspace trust decisions?")) { await api.delete("/api/workspaces/trust"); alert("Trust decisions reset."); } } },
                  ].map(({ label, action }) => (
                    <Button key={label} variant="danger" onClick={action} className="w-full text-center text-xs">
                      {label}
                    </Button>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-white/8 bg-white/3 p-4 space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-on-surface-variant">Onboarding</h3>
                <p className="text-[11px] text-on-surface-variant/60">Restart the interactive walkthrough and tutorial spotlight.</p>
                <Button
                  variant="primary"
                  id="btn-replay-tutorial"
                  onClick={() => {
                    if (confirm("Restart onboarding tutorial? The application will reload.")) {
                      localStorage.setItem("code-os:onboarding-complete", "false");
                      window.location.reload();
                    }
                  }}
                >
                  Replay Tutorial Walkthrough
                </Button>
              </div>
            </div>
          )}

          {/* ── Category: About ────────────────────────────────────────────── */}
          {activeCategory === "about" && (
            <div className="space-y-5 py-2">
              <div className="flex items-center gap-4">
                <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center shadow-[0_0_24px_rgba(0,229,255,0.1)]">
                  <span className="material-symbols-outlined text-primary text-3xl" style={{ fontVariationSettings: "'FILL' 1" }}>code</span>
                </div>
                <div>
                  <div className="text-lg font-black text-primary tracking-tight">CODE OS</div>
                  <p className="text-xs text-on-surface-variant">Version 0.2.0 — Stable Channel</p>
                </div>
              </div>

              <div className="border-t border-white/5 pt-4 space-y-2 text-xs text-on-surface-variant/60 leading-relaxed max-w-xl">
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
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 font-semibold"
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
