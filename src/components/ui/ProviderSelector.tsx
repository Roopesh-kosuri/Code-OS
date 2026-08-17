import React, { useState, useRef, useEffect } from "react";
import {
  Sparkles,
  Cpu,
  Zap,
  Terminal,
  Bot,
  Compass,
  Flame,
  Globe,
  Sliders,
  Check,
  ChevronDown,
  Info,
  KeyRound,
  Server,
  ExternalLink,
  Search,
  Layers,
  X,
  Plus,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import {
  PROVIDER_PRESETS,
  getPreset,
  type ProviderPreset,
} from "../../lib/providerPresets";
import {
  isReasoningModel,
  PRESET_MODELS,
  getUserCustomModels,
  saveUserCustomModel,
  deleteUserCustomModel,
  type CuratedModel,
} from "../../lib/models";

// ── Public types ──────────────────────────────────────────────────────────────

export interface ProviderConfig {
  preset: string;
  model: string;
  base_url?: string;
  api_key_provider?: string;
}

interface ProviderSelectorProps {
  label?: string;
  value: ProviderConfig;
  onChange: (cfg: ProviderConfig) => void;
  configuredKeys?: string[];
  compact?: boolean;
  models?: { name: string; provider: string }[];
  onClose?: () => void;
}

// ── Visual Theme Mapping for Providers ─────────────────────────────────────────

interface PresetTheme {
  icon: LucideIcon;
  accentColor: string;
  badgeBg: string;
  badgeBorder: string;
  badgeText: string;
  tag: string;
  desc: string;
}

const PRESET_THEMES: Record<string, PresetTheme> = {
  auto: {
    icon: Sparkles,
    accentColor: "text-purple-400",
    badgeBg: "bg-purple-500/15",
    badgeBorder: "border-purple-500/30",
    badgeText: "text-purple-300",
    tag: "Auto",
    desc: "Auto-routes across local & cloud models",
  },
  ollama: {
    icon: Terminal,
    accentColor: "text-emerald-400",
    badgeBg: "bg-emerald-500/15",
    badgeBorder: "border-emerald-500/30",
    badgeText: "text-emerald-300",
    tag: "Local",
    desc: "Offline models via Ollama",
  },
  openai: {
    icon: Zap,
    accentColor: "text-emerald-400",
    badgeBg: "bg-emerald-500/15",
    badgeBorder: "border-emerald-500/30",
    badgeText: "text-emerald-300",
    tag: "OpenAI",
    desc: "GPT-4o & o-series reasoning",
  },
  anthropic: {
    icon: Bot,
    accentColor: "text-amber-400",
    badgeBg: "bg-amber-500/15",
    badgeBorder: "border-amber-500/30",
    badgeText: "text-amber-300",
    tag: "Claude",
    desc: "Claude 3.5 Sonnet & Opus",
  },
  gemini: {
    icon: Sparkles,
    accentColor: "text-blue-400",
    badgeBg: "bg-blue-500/15",
    badgeBorder: "border-blue-500/30",
    badgeText: "text-blue-300",
    tag: "Gemini",
    desc: "Gemini 2.5 Flash & Pro",
  },
  groq: {
    icon: Flame,
    accentColor: "text-orange-400",
    badgeBg: "bg-orange-500/15",
    badgeBorder: "border-orange-500/30",
    badgeText: "text-orange-300",
    tag: "Groq LPU",
    desc: "Ultra-fast inference (500+ tok/s)",
  },
  deepseek: {
    icon: Compass,
    accentColor: "text-cyan-400",
    badgeBg: "bg-cyan-500/15",
    badgeBorder: "border-cyan-500/30",
    badgeText: "text-cyan-300",
    tag: "DeepSeek",
    desc: "DeepSeek V3 & R1 reasoning",
  },
  mistral: {
    icon: Layers,
    accentColor: "text-amber-400",
    badgeBg: "bg-amber-500/15",
    badgeBorder: "border-amber-500/30",
    badgeText: "text-amber-300",
    tag: "Mistral",
    desc: "Codestral & Mistral Large",
  },
  openrouter: {
    icon: Globe,
    accentColor: "text-indigo-400",
    badgeBg: "bg-indigo-500/15",
    badgeBorder: "border-indigo-500/30",
    badgeText: "text-indigo-300",
    tag: "100+ Models",
    desc: "Unified meta-router",
  },
  "nvidia-nim": {
    icon: Cpu,
    accentColor: "text-lime-400",
    badgeBg: "bg-lime-500/15",
    badgeBorder: "border-lime-500/30",
    badgeText: "text-lime-300",
    tag: "NIM",
    desc: "GPU-accelerated open-weights",
  },
  custom: {
    icon: Sliders,
    accentColor: "text-slate-300",
    badgeBg: "bg-slate-500/15",
    badgeBorder: "border-slate-500/30",
    badgeText: "text-slate-300",
    tag: "Custom",
    desc: "Custom HTTP API endpoint",
  },
};

const DEFAULT_THEME: PresetTheme = {
  icon: Server,
  accentColor: "text-primary",
  badgeBg: "bg-primary/15",
  badgeBorder: "border-primary/30",
  badgeText: "text-primary",
  tag: "Provider",
  desc: "AI Provider",
};

function getModelBadgeStyle(tag?: string) {
  switch (tag) {
    case "Recommended":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
    case "Reasoning":
      return "bg-purple-500/15 text-purple-300 border-purple-500/30";
    case "Coding":
      return "bg-cyan-500/15 text-cyan-300 border-cyan-500/30";
    case "Flagship":
      return "bg-amber-500/15 text-amber-300 border-amber-500/30";
    case "Fast":
      return "bg-blue-500/15 text-blue-300 border-blue-500/30";
    case "Custom":
      return "bg-slate-500/15 text-slate-300 border-slate-500/30";
    default:
      return "bg-white/10 text-on-surface-variant border-white/10";
  }
}

// ── Key status badge ──────────────────────────────────────────────────────────

function KeyBadge({
  keyId,
  configuredKeys,
}: {
  keyId: string | null | undefined;
  configuredKeys?: string[];
}) {
  if (!keyId || !configuredKeys) return null;
  const isSet = configuredKeys.includes(keyId);
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-px text-[8.5px] font-semibold border transition-all ${
        isSet
          ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
          : "text-amber-400 bg-amber-500/10 border-amber-500/30"
      }`}
    >
      {isSet ? (
        <>
          <Check size={8} strokeWidth={2.5} /> Key set
        </>
      ) : (
        <>
          <KeyRound size={8} /> No key
        </>
      )}
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ProviderSelector({
  label,
  value,
  onChange,
  configuredKeys,
  compact = false,
  models = [],
  onClose,
}: ProviderSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false);
  const [modelSearchQuery, setModelSearchQuery] = useState("");
  const [isAddingCustomModel, setIsAddingCustomModel] = useState(false);
  const [customModelInput, setCustomModelInput] = useState("");
  const [userCustomList, setUserCustomList] = useState<string[]>(() =>
    getUserCustomModels(value.preset)
  );

  const [nimSelfHosted, setNimSelfHosted] = useState(
    value.preset === "nvidia-nim" &&
      !!value.base_url &&
      value.base_url !== "https://integrate.api.nvidia.com/v1"
  );

  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const modelDropdownRef = useRef<HTMLDivElement | null>(null);

  const preset: ProviderPreset | undefined = getPreset(value.preset);
  const activeTheme = PRESET_THEMES[value.preset] || DEFAULT_THEME;
  const ActiveIcon = activeTheme.icon;

  useEffect(() => {
    setUserCustomList(getUserCustomModels(value.preset));
    setIsAddingCustomModel(false);
    setCustomModelInput("");
    setModelSearchQuery("");
  }, [value.preset]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
      if (
        modelDropdownRef.current &&
        !modelDropdownRef.current.contains(e.target as Node)
      ) {
        setIsModelDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handlePresetChange = (newPresetId: string) => {
    const newPreset = getPreset(newPresetId);
    if (!newPreset) return;
    setNimSelfHosted(false);
    setIsOpen(false);
    setSearchQuery("");
    const autoModel =
      newPresetId === value.preset
        ? value.model
        : newPreset.model_example || "";
    onChange({
      preset: newPresetId,
      model: autoModel,
      base_url: newPreset.base_url || undefined,
      api_key_provider: newPreset.api_key_provider ?? undefined,
    });
  };

  const handleNimToggle = (selfHosted: boolean) => {
    setNimSelfHosted(selfHosted);
    onChange({
      ...value,
      base_url: selfHosted
        ? "http://localhost:8000/v1"
        : "https://integrate.api.nvidia.com/v1",
    });
  };

  const handleAddCustomModel = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanId = customModelInput.trim();
    if (!cleanId) return;
    saveUserCustomModel(value.preset, cleanId);
    setUserCustomList(getUserCustomModels(value.preset));
    onChange({ ...value, model: cleanId });
    setCustomModelInput("");
    setIsAddingCustomModel(false);
    setIsModelDropdownOpen(false);
  };

  const handleDeleteCustomModel = (modelId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    deleteUserCustomModel(value.preset, modelId);
    setUserCustomList(getUserCustomModels(value.preset));
  };

  const isOllama = value.preset === "ollama";
  const isCustom = value.preset === "custom";
  const isNim = value.preset === "nvidia-nim";
  const isApiPreset = !isOllama;
  const modelIsReasoning = isReasoningModel(value.model);

  // Filter presets by search
  const filteredPresets = PROVIDER_PRESETS.filter((p) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    const theme = PRESET_THEMES[p.id] || DEFAULT_THEME;
    return (
      p.label.toLowerCase().includes(q) ||
      p.id.toLowerCase().includes(q) ||
      theme.tag.toLowerCase().includes(q)
    );
  });

  const localPresets = filteredPresets.filter((p) => p.group === "local");
  const apiPresets = filteredPresets.filter((p) => p.group === "api");

  // ── Curated + Dynamic Backend + User Custom Models Aggregation ─────────────
  const curatedList: CuratedModel[] = PRESET_MODELS[value.preset] || [];
  const activeProviderName = preset?.provider ?? "ollama";
  const backendMatchingModels = models
    .filter((m) => m.provider === activeProviderName || m.provider === value.preset)
    .map((m) => ({ id: m.name, name: m.name, tag: undefined }));

  const combinedMap = new Map<string, CuratedModel>();
  for (const m of curatedList) {
    combinedMap.set(m.id, m);
  }
  for (const m of backendMatchingModels) {
    if (!combinedMap.has(m.id)) {
      combinedMap.set(m.id, m);
    }
  }
  for (const customId of userCustomList) {
    if (!combinedMap.has(customId)) {
      combinedMap.set(customId, {
        id: customId,
        name: customId,
        tag: "Custom",
        description: "User custom model",
      });
    }
  }
  if (value.model && !combinedMap.has(value.model)) {
    combinedMap.set(value.model, {
      id: value.model,
      name: value.model,
      tag: "Custom",
      description: "Active model",
    });
  }

  const allAvailableModels = Array.from(combinedMap.values());
  const filteredAvailableModels = allAvailableModels.filter((m) => {
    if (!modelSearchQuery.trim()) return true;
    const q = modelSearchQuery.toLowerCase();
    return (
      m.id.toLowerCase().includes(q) ||
      m.name.toLowerCase().includes(q) ||
      (m.tag && m.tag.toLowerCase().includes(q))
    );
  });

  const activeModelObj = combinedMap.get(value.model);

  return (
    <div
      className={`rounded-xl border border-white/10 bg-[#12141a]/95 backdrop-blur-xl shadow-lg transition-all duration-200 relative overflow-visible ${
        compact ? "p-2.5 space-y-2" : "p-3 space-y-2.5"
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between relative z-10">
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface">
            {label || "AI Model & Engine"}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {preset?.api_key_provider && (
            <KeyBadge
              keyId={preset.api_key_provider}
              configuredKeys={configuredKeys}
            />
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-0.5 rounded-md text-on-surface-variant hover:text-on-surface hover:bg-white/5 transition-colors cursor-pointer"
              title="Close engine settings"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* ── Custom Glassmorphic Provider Dropdown ─────────────────────────── */}
      <div className="relative z-30" ref={dropdownRef}>
        <div className="flex items-center justify-between mb-0.5 text-[9.5px]">
          <span className="font-semibold text-on-surface-variant">Provider</span>
          {preset?.group === "local" ? (
            <span className="text-emerald-400 font-mono text-[9px]">● Local</span>
          ) : (
            <span className="text-blue-400 font-mono text-[9px]">⚡ Cloud</span>
          )}
        </div>

        {/* Trigger Button (Single-line, compact) */}
        <button
          type="button"
          onClick={() => {
            const next = !isOpen;
            setIsOpen(next);
            if (next) setIsModelDropdownOpen(false);
          }}
          className={`w-full px-2.5 py-1.5 rounded-lg border text-left flex items-center justify-between transition-all duration-150 cursor-pointer shadow-sm group ${
            isOpen
              ? "bg-[#181a22] border-primary/50 ring-1 ring-primary/20"
              : "bg-[#16181f]/80 hover:bg-[#1c1e28] border-white/10 hover:border-white/20"
          }`}
        >
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <div
              className={`p-1 rounded-md shrink-0 ${activeTheme.badgeBg} ${activeTheme.badgeBorder} border ${activeTheme.accentColor}`}
            >
              <ActiveIcon size={13} />
            </div>
            <span className="font-semibold text-xs text-on-surface truncate">
              {preset?.label || "Select Provider"}
            </span>
            <span
              className={`text-[8.5px] px-1.5 py-0.2 rounded font-mono font-medium shrink-0 border ${activeTheme.badgeBg} ${activeTheme.badgeBorder} ${activeTheme.badgeText}`}
            >
              {activeTheme.tag}
            </span>
          </div>

          <ChevronDown
            size={13}
            className={`text-on-surface-variant shrink-0 ml-1.5 transition-transform duration-200 ${
              isOpen ? "rotate-180 text-primary" : "group-hover:text-on-surface"
            }`}
          />
        </button>

        {/* Backdrop Scrim with Subtle Blur */}
        {isOpen && (
          <div
            className="fixed inset-0 z-[90] bg-black/50 backdrop-blur-[3px] transition-all animate-in fade-in duration-150"
            onClick={() => setIsOpen(false)}
          />
        )}

        {/* Floating Dropdown Menu */}
        {isOpen && (
          <div className="absolute left-0 right-0 top-full mt-1.5 rounded-xl border border-white/20 bg-[#13151f] shadow-[0_25px_60px_rgba(0,0,0,0.95)] ring-1 ring-white/10 overflow-hidden z-[100] animate-popover-in flex flex-col max-h-[300px]">
            {/* Compact Search header */}
            <div className="p-1.5 border-b border-white/10 bg-[#0d0f15] shrink-0">
              <div className="relative">
                <Search
                  size={11}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant"
                />
                <input
                  type="text"
                  placeholder="Filter providers..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  autoFocus
                  className="w-full bg-[#181a24] rounded-lg pl-6 pr-2 py-1 text-[11px] text-on-surface placeholder:text-on-surface-variant/50 border border-white/10 focus:outline-none focus:border-primary/50 font-sans"
                />
              </div>
            </div>

            {/* Scrollable Items List */}
            <div className="overflow-y-auto p-1.5 space-y-1 divide-y divide-white/5 max-h-[240px]">
              {/* Local Section */}
              {localPresets.length > 0 && (
                <div className="space-y-0.5 pt-0.5 first:pt-0">
                  <div className="px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-on-surface-variant/70">
                    Local & Auto
                  </div>
                  {localPresets.map((p) => {
                    const theme = PRESET_THEMES[p.id] || DEFAULT_THEME;
                    const Icon = theme.icon;
                    const isSelected = p.id === value.preset;

                    return (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => handlePresetChange(p.id)}
                        className={`w-full min-h-[34px] px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between gap-2 transition-all duration-150 interactive-row cursor-pointer group ${
                          isSelected
                            ? "bg-primary/15 text-primary font-bold"
                            : "text-on-surface hover:bg-white/10"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <div
                            className={`p-1 rounded shrink-0 ${theme.badgeBg} ${theme.badgeBorder} border ${theme.accentColor}`}
                          >
                            <Icon size={12} />
                          </div>
                          <span className="text-xs font-medium truncate">
                            {p.label}
                          </span>
                          <span
                            className={`text-[8.5px] px-1 py-px rounded font-mono shrink-0 border ${theme.badgeBg} ${theme.badgeBorder} ${theme.badgeText}`}
                          >
                            {theme.tag}
                          </span>
                        </div>
                        {isSelected && (
                          <Check size={12} className="text-primary shrink-0 animate-success-pop" strokeWidth={3} />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* API Providers Section */}
              {apiPresets.length > 0 && (
                <div className="space-y-0.5 pt-1">
                  <div className="px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-on-surface-variant/70">
                    Cloud & API Providers
                  </div>
                  {apiPresets.map((p) => {
                    const theme = PRESET_THEMES[p.id] || DEFAULT_THEME;
                    const Icon = theme.icon;
                    const isSelected = p.id === value.preset;
                    const isKeyConfigured =
                      p.api_key_provider &&
                      configuredKeys?.includes(p.api_key_provider);

                    return (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => handlePresetChange(p.id)}
                        className={`w-full min-h-[34px] px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between gap-2 transition-all duration-150 interactive-row cursor-pointer group ${
                          isSelected
                            ? "bg-primary/15 text-primary font-bold"
                            : "text-on-surface hover:bg-white/10"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <div
                            className={`p-1 rounded shrink-0 ${theme.badgeBg} ${theme.badgeBorder} border ${theme.accentColor}`}
                          >
                            <Icon size={12} />
                          </div>
                          <span className="text-xs font-medium truncate">
                            {p.label}
                          </span>
                          <span
                            className={`text-[8.5px] px-1 py-px rounded font-mono shrink-0 border ${theme.badgeBg} ${theme.badgeBorder} ${theme.badgeText}`}
                          >
                            {theme.tag}
                          </span>
                          {isKeyConfigured && (
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" title="Key set" />
                          )}
                        </div>
                        {isSelected && (
                          <Check size={12} className="text-primary shrink-0 animate-success-pop" strokeWidth={3} />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}

              {filteredPresets.length === 0 && (
                <div className="p-3 text-center text-[10.5px] text-on-surface-variant">
                  No providers found
                </div>
              )}
            </div>
          </div>
        )}

        {/* Caveat note tooltip */}
        {preset?.note && (
          <div className="mt-1 flex items-start gap-1 p-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-[9.5px] text-amber-200/90 leading-tight">
            <Info size={11} className="text-amber-400 mt-0.5 shrink-0" />
            <span className="truncate">{preset.note}</span>
          </div>
        )}
      </div>

      {/* ── Rich Curated & Custom Model Selector ────────────────────────────── */}
      <div className="relative z-20" ref={modelDropdownRef}>
        <div className="flex items-center justify-between mb-0.5 text-[9.5px]">
          <span className="font-semibold text-on-surface-variant">Model</span>
          {preset?.model_example && (
            <span className="text-on-surface-variant/60 font-mono text-[9px] truncate max-w-[140px]">
              e.g. {preset.model_example}
            </span>
          )}
        </div>

        <div className="space-y-1.5">
          {/* Main Dropdown Button */}
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                const next = !isModelDropdownOpen;
                setIsModelDropdownOpen(next);
                if (next) setIsOpen(false);
              }}
              className="w-full px-2.5 py-1.5 rounded-lg bg-[#16181f]/80 hover:bg-[#1c1e28] border border-white/10 hover:border-white/20 text-left flex items-center justify-between transition-all cursor-pointer text-xs text-on-surface shadow-sm group"
            >
              <div className="flex items-center gap-1.5 truncate min-w-0 flex-1">
                <Bot size={13} className="text-primary shrink-0 group-hover:scale-105 transition-transform" />
                <span className="font-mono font-bold truncate text-[11px] text-on-surface">
                  {value.model || "Select coding model..."}
                </span>
                {activeModelObj?.tag && (
                  <span
                    className={`text-[8.5px] px-1.5 py-0.2 rounded font-mono font-medium shrink-0 border ${getModelBadgeStyle(
                      activeModelObj.tag
                    )}`}
                  >
                    {activeModelObj.tag}
                  </span>
                )}
              </div>
              <ChevronDown
                size={12}
                className={`text-on-surface-variant shrink-0 ml-1 transition-transform duration-200 ${
                  isModelDropdownOpen ? "rotate-180 text-primary" : "group-hover:text-on-surface"
                }`}
              />
            </button>

            {isModelDropdownOpen && (
              <div
                className="fixed inset-0 z-[90] bg-black/50 backdrop-blur-[3px] transition-all animate-in fade-in duration-150"
                onClick={() => {
                  setIsModelDropdownOpen(false);
                  setIsAddingCustomModel(false);
                }}
              />
            )}

            {/* Dropdown Menu */}
            {isModelDropdownOpen && (
              <div className="absolute left-0 right-0 top-full mt-1.5 rounded-xl border border-white/20 bg-[#13151f] shadow-[0_25px_60px_rgba(0,0,0,0.95)] ring-1 ring-white/10 overflow-hidden z-[100] flex flex-col max-h-[320px] animate-popover-in">
                {/* Search & Filter Header */}
                <div className="p-1.5 border-b border-white/10 bg-[#0d0f15] shrink-0">
                  <div className="relative">
                    <Search
                      size={11}
                      className="absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant"
                    />
                    <input
                      type="text"
                      placeholder="Search coding models…"
                      value={modelSearchQuery}
                      onChange={(e) => setModelSearchQuery(e.target.value)}
                      autoFocus
                      className="w-full bg-[#181a24] rounded-lg pl-6 pr-2 py-1 text-[11px] text-on-surface placeholder:text-on-surface-variant/50 border border-white/10 focus:outline-none focus:border-primary/50 font-sans"
                    />
                  </div>
                </div>

                {/* Models List */}
                <div className="overflow-y-auto p-1.5 space-y-0.5 max-h-[220px]">
                  {filteredAvailableModels.map((m) => {
                    const isSelected = value.model === m.id;
                    const isUserCustom = userCustomList.includes(m.id);

                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => {
                          onChange({ ...value, model: m.id });
                          setIsModelDropdownOpen(false);
                          setIsAddingCustomModel(false);
                        }}
                        className={`w-full min-h-[34px] px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between gap-2 transition-all duration-150 interactive-row cursor-pointer group ${
                          isSelected
                            ? "bg-primary/20 text-primary font-bold"
                            : "text-on-surface hover:bg-white/10"
                        }`}
                      >
                        <div className="flex flex-col min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[11.5px] font-semibold truncate text-on-surface group-hover:text-primary transition-colors">
                              {m.name}
                            </span>
                            {m.tag && (
                              <span
                                className={`text-[8px] px-1 py-px rounded font-mono font-medium shrink-0 border ${getModelBadgeStyle(
                                  m.tag
                                )}`}
                              >
                                {m.tag}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] font-mono text-on-surface-variant/70 truncate">
                            {m.id}
                          </span>
                        </div>

                        <div className="flex items-center gap-1 shrink-0">
                          {isUserCustom && (
                            <span
                              onClick={(e) => handleDeleteCustomModel(m.id, e)}
                              className="p-1 rounded text-on-surface-variant/50 hover:text-error hover:bg-error/10 transition-colors"
                              title="Delete custom model"
                            >
                              <Trash2 size={11} />
                            </span>
                          )}
                          {isSelected && (
                            <Check size={13} strokeWidth={2.5} className="text-primary animate-success-pop" />
                          )}
                        </div>
                      </button>
                    );
                  })}

                  {filteredAvailableModels.length === 0 && (
                    <div className="p-3 text-center text-[10.5px] text-on-surface-variant">
                      No models matching search
                    </div>
                  )}
                </div>

                {/* Add Custom Model Drawer / Footer */}
                <div className="border-t border-white/10 p-1.5 bg-[#0e1017] shrink-0 space-y-1.5">
                  {!isAddingCustomModel ? (
                    <button
                      type="button"
                      onClick={() => setIsAddingCustomModel(true)}
                      className="w-full px-2 py-1.5 rounded-lg text-left text-[11px] font-medium text-primary hover:bg-primary/10 transition-colors cursor-pointer flex items-center gap-1.5"
                    >
                      <Plus size={13} />
                      <span>Add Custom Model / Identifier…</span>
                    </button>
                  ) : (
                    <form onSubmit={handleAddCustomModel} className="space-y-1.5">
                      <div className="text-[9.5px] font-bold text-on-surface-variant/80 uppercase tracking-wider">
                        Add Custom Model
                      </div>
                      <div className="flex items-center gap-1.5">
                        <input
                          type="text"
                          placeholder="e.g. z-ai/glm-5.2, qwen2.5-coder…"
                          value={customModelInput}
                          onChange={(e) => setCustomModelInput(e.target.value)}
                          autoFocus
                          className="flex-1 rounded-lg bg-[#181a24] border border-white/15 px-2 py-1 text-xs font-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50"
                        />
                        <button
                          type="submit"
                          disabled={!customModelInput.trim()}
                          className="px-2.5 py-1 rounded-lg bg-primary text-[#001f24] font-bold text-[11px] hover:bg-primary/90 transition-all disabled:opacity-40 cursor-pointer shrink-0"
                        >
                          Add & Select
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setIsAddingCustomModel(false);
                            setCustomModelInput("");
                          }}
                          className="p-1 rounded text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer shrink-0"
                        >
                          <X size={13} />
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Direct Quick-Input Field */}
          <div className="relative">
            <input
              type="text"
              placeholder={
                preset?.model_placeholder ?? "Enter model identifier…"
              }
              value={value.model}
              onChange={(e) => onChange({ ...value, model: e.target.value })}
              className="w-full rounded-lg bg-[#0f1117] border border-white/10 px-2.5 py-1.5 text-xs font-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50 transition-all shadow-inner"
            />
          </div>
        </div>

        {modelIsReasoning && (
          <div className="mt-1.5 rounded-md border border-purple-500/30 bg-purple-500/10 px-2 py-1 text-[9.5px] leading-tight text-purple-200 flex items-center gap-1">
            <Sparkles size={11} className="text-purple-400 shrink-0" />
            <span>Reasoning Model active</span>
          </div>
        )}
      </div>

      {/* ── Ollama Local URL ──────────────────────────────────────────────── */}
      {isOllama && (
        <div className="pt-0.5">
          <label className="text-[9.5px] font-semibold text-on-surface-variant mb-0.5 flex items-center gap-1">
            <Server size={10} className="text-emerald-400" /> Host URL
          </label>
          <input
            type="text"
            placeholder="http://127.0.0.1:11434"
            value={value.base_url ?? "http://127.0.0.1:11434"}
            onChange={(e) =>
              onChange({ ...value, base_url: e.target.value || undefined })
            }
            className="w-full rounded-lg bg-[#0f1117] border border-white/10 px-2.5 py-1 text-xs font-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-emerald-500/50"
          />
        </div>
      )}

      {/* ── NVIDIA NIM Self-Hosted Toggle ─────────────────────────────────── */}
      {isNim && (
        <div className="rounded-lg bg-[#161820] border border-white/10 p-2 space-y-1.5">
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={nimSelfHosted}
              onChange={(e) => handleNimToggle(e.target.checked)}
              className="rounded accent-primary text-xs"
            />
            <span className="text-[10px] font-medium text-on-surface">
              Self-hosted NIM container
            </span>
          </label>
          {nimSelfHosted && (
            <input
              type="text"
              placeholder="http://localhost:8000/v1"
              value={value.base_url ?? "http://localhost:8000/v1"}
              onChange={(e) =>
                onChange({ ...value, base_url: e.target.value || undefined })
              }
              className="w-full rounded-md bg-[#0f1117] border border-white/10 px-2 py-1 text-xs font-mono text-on-surface focus:outline-none focus:border-primary/50"
            />
          )}
        </div>
      )}

      {/* ── Custom Endpoint URLs ─────────────────────────────────────────── */}
      {isCustom && (
        <div className="space-y-1.5 pt-0.5">
          <div>
            <label className="text-[9.5px] font-semibold text-on-surface-variant mb-0.5 block">
              Base URL
            </label>
            <input
              type="text"
              placeholder="https://your-endpoint.com/v1"
              value={value.base_url ?? ""}
              onChange={(e) =>
                onChange({ ...value, base_url: e.target.value || undefined })
              }
              className="w-full rounded-lg bg-[#0f1117] border border-white/10 px-2.5 py-1 text-xs font-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50"
            />
          </div>
          <div>
            <label className="text-[9.5px] font-semibold text-on-surface-variant mb-0.5 block">
              Key ID / Provider Identifier
            </label>
            <input
              type="text"
              placeholder="custom"
              value={value.api_key_provider ?? "custom"}
              onChange={(e) =>
                onChange({
                  ...value,
                  api_key_provider: e.target.value || "custom",
                })
              }
              className="w-full rounded-lg bg-[#0f1117] border border-white/10 px-2.5 py-1 text-xs font-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50"
            />
          </div>
        </div>
      )}

      {/* ── API Preset Footer ─────────────────────────────────────────────── */}
      {isApiPreset && !isCustom && !isNim && (
        <div className="flex items-center justify-between pt-0.5 border-t border-white/5 text-[9px]">
          <span className="truncate text-on-surface-variant/50 font-mono">
            {preset?.base_url ?? ""}
          </span>
          <button
            type="button"
            onClick={() =>
              window.dispatchEvent(
                new CustomEvent("code-os:switch-utility", {
                  detail: "settings",
                })
              )
            }
            className="flex items-center gap-0.5 text-primary hover:text-primary/80 font-medium transition-colors shrink-0 ml-1.5 cursor-pointer"
          >
            <ExternalLink size={9} /> Settings
          </button>
        </div>
      )}
    </div>
  );
}
