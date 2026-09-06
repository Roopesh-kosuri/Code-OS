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
  Eye,
  ChevronRight,
  ShieldCheck,
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
  VISION_MODELS,
  getUserCustomModels,
  saveUserCustomModel,
  deleteUserCustomModel,
  type CuratedModel,
} from "../../lib/models";
import { useAIStore } from "../../stores/aiStore";

// ── Public types ──────────────────────────────────────────────────────────────

export interface ProviderConfig {
  preset: string;
  model: string;
  base_url?: string;
  api_key_provider?: string;
  provider?: string;
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

export interface PresetTheme {
  icon: LucideIcon;
  accentColor: string;
  badgeBg: string;
  badgeBorder: string;
  badgeText: string;
  tag: string;
  desc: string;
}

export const PRESET_THEMES: Record<string, PresetTheme> = {
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
    desc: "GPT-4o, o3 & o-series reasoning",
  },
  anthropic: {
    icon: Bot,
    accentColor: "text-amber-400",
    badgeBg: "bg-amber-500/15",
    badgeBorder: "border-amber-500/30",
    badgeText: "text-amber-300",
    tag: "Claude",
    desc: "Claude 3.5 Sonnet, 3.7 & Opus",
  },
  gemini: {
    icon: Sparkles,
    accentColor: "text-sky-400",
    badgeBg: "bg-sky-500/15",
    badgeBorder: "border-sky-500/30",
    badgeText: "text-sky-300",
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
  moonshot: {
    icon: Compass,
    accentColor: "text-sky-400",
    badgeBg: "bg-sky-500/15",
    badgeBorder: "border-sky-500/30",
    badgeText: "text-sky-300",
    tag: "Kimi",
    desc: "Moonshot AI Kimi 128k long-context",
  },
  glm: {
    icon: Zap,
    accentColor: "text-blue-400",
    badgeBg: "bg-blue-500/15",
    badgeBorder: "border-blue-500/30",
    badgeText: "text-blue-300",
    tag: "GLM",
    desc: "Zhipu AI GLM-4 Plus & Long",
  },
  qwen: {
    icon: Compass,
    accentColor: "text-teal-400",
    badgeBg: "bg-teal-500/15",
    badgeBorder: "border-teal-500/30",
    badgeText: "text-teal-300",
    tag: "Qwen",
    desc: "Alibaba DashScope & Qwen Coder",
  },
  xai: {
    icon: Flame,
    accentColor: "text-rose-400",
    badgeBg: "bg-rose-500/15",
    badgeBorder: "border-rose-500/30",
    badgeText: "text-rose-300",
    tag: "xAI",
    desc: "Grok 3 & Grok 2 Reasoning",
  },
  cohere: {
    icon: Layers,
    accentColor: "text-amber-400",
    badgeBg: "bg-amber-500/15",
    badgeBorder: "border-amber-500/30",
    badgeText: "text-amber-300",
    tag: "Cohere",
    desc: "Command A & Command R+",
  },
  llama: {
    icon: Cpu,
    accentColor: "text-sky-400",
    badgeBg: "bg-sky-500/15",
    badgeBorder: "border-sky-500/30",
    badgeText: "text-sky-300",
    tag: "Llama",
    desc: "Meta Llama 3.3 & Llama 4 Scout",
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

export const DEFAULT_THEME: PresetTheme = {
  icon: Server,
  accentColor: "text-primary",
  badgeBg: "bg-primary/15",
  badgeBorder: "border-primary/30",
  badgeText: "text-primary",
  tag: "Provider",
  desc: "AI Provider",
};

export function getPresetTheme(presetId?: string): PresetTheme {
  if (!presetId) return DEFAULT_THEME;
  return PRESET_THEMES[presetId] || DEFAULT_THEME;
}

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
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold border transition-all ${
        isSet
          ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
          : "text-amber-400 bg-amber-500/10 border-amber-500/30"
      }`}
    >
      {isSet ? (
        <>
          <Check size={9} strokeWidth={2.5} /> Key ready
        </>
      ) : (
        <>
          <KeyRound size={9} /> Needs key
        </>
      )}
    </span>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

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
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isVisionDropdownOpen, setIsVisionDropdownOpen] = useState(false);

  const visionModel = useAIStore((s) => s.visionModel);
  const setVisionModel = useAIStore((s) => s.setVisionModel);

  const [nimSelfHosted, setNimSelfHosted] = useState(
    value.preset === "nvidia-nim" &&
      !!value.base_url &&
      value.base_url !== "https://integrate.api.nvidia.com/v1"
  );

  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const modelDropdownRef = useRef<HTMLDivElement | null>(null);
  const visionDropdownRef = useRef<HTMLDivElement | null>(null);

  const preset: ProviderPreset | undefined = getPreset(value.preset);
  const activeTheme = PRESET_THEMES[value.preset] || DEFAULT_THEME;
  const ActiveIcon = activeTheme.icon;

  useEffect(() => {
    setUserCustomList(getUserCustomModels(value.preset));
    setIsAddingCustomModel(false);
    setCustomModelInput("");
    setModelSearchQuery("");
  }, [value.preset]);

  // Clean outside-click listener without fullscreen black scrims
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
        setIsAddingCustomModel(false);
      }
      if (
        visionDropdownRef.current &&
        !visionDropdownRef.current.contains(e.target as Node)
      ) {
        setIsVisionDropdownOpen(false);
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
      ...value,
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
      theme.tag.toLowerCase().includes(q) ||
      theme.desc.toLowerCase().includes(q)
    );
  });

  const localPresets = filteredPresets.filter((p) => p.group === "local");
  const apiPresets = filteredPresets.filter((p) => p.group === "api");

  // ── Curated + Dynamic Backend + User Custom Models Aggregation ─────────────
  const curatedList: CuratedModel[] = PRESET_MODELS[value.preset] || [];
  const activeProviderName = preset?.provider ?? "ollama";
  const backendMatchingModels = models
    .filter(
      (m) => m.provider === activeProviderName || m.provider === value.preset
    )
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
  const activeModelName = activeModelObj?.name || value.model || "Select model...";

  return (
    <div
      className={`rounded-xl liquid-glass-card transition-all duration-200 relative overflow-visible ${
        compact ? "p-3 space-y-2.5" : "p-4 space-y-3"
      }`}
    >
      {/* ── Card Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-white/[0.06] pb-2.5">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-primary shadow-[0_0_8px_rgba(0,218,243,0.7)] animate-pulse" />
          <span className="text-xs font-bold text-white tracking-tight">
            {label || "AI Model & Engine"}
          </span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full font-mono font-medium bg-white/[0.06] border border-white/10 text-on-surface-variant">
            {preset?.group === "local" ? "Local" : "Cloud"}
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
              className="p-1 rounded-lg text-on-surface-variant hover:text-white hover:bg-white/[0.08] transition-colors cursor-pointer"
              title="Close engine settings"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* ── Provider Selector Section ────────────────────────────────────── */}
      <div className="relative" ref={dropdownRef}>
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant/80">
            Provider
          </span>
          <span className="text-[10px] text-on-surface-variant/60 font-mono">
            {preset?.label}
          </span>
        </div>

        {/* Trigger Button */}
        <button
          type="button"
          onClick={() => {
            const next = !isOpen;
            setIsOpen(next);
            if (next) {
              setIsModelDropdownOpen(false);
              setIsVisionDropdownOpen(false);
            }
          }}
          className={`w-full px-3 py-2 rounded-lg border text-left flex items-center justify-between transition-all duration-150 cursor-pointer shadow-sm group ${
            isOpen
              ? "bg-[#181b29] border-primary/60 ring-1 ring-primary/30 shadow-[0_0_16px_rgba(0,218,243,0.2)]"
              : "bg-[#131622]/90 hover:bg-[#191c2c] border-white/10 hover:border-white/25 hover:shadow-[0_2px_8px_rgba(0,0,0,0.4)]"
          }`}
        >
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <div
              className={`p-1.5 rounded-md shrink-0 border ${activeTheme.badgeBg} ${activeTheme.badgeBorder} ${activeTheme.accentColor}`}
            >
              <ActiveIcon size={14} />
            </div>
            <div className="flex flex-col min-w-0 flex-1">
              <span className="font-semibold text-xs text-white truncate">
                {preset?.label || "Select Provider"}
              </span>
              <span className="text-[10px] text-on-surface-variant/70 truncate">
                {activeTheme.desc}
              </span>
            </div>
            <span
              className={`text-[9px] px-2 py-0.5 rounded-full font-mono font-semibold shrink-0 border ${activeTheme.badgeBg} ${activeTheme.badgeBorder} ${activeTheme.badgeText}`}
            >
              {activeTheme.tag}
            </span>
          </div>

          <ChevronDown
            size={13}
            className={`text-on-surface-variant shrink-0 ml-2 transition-transform duration-200 ${
              isOpen ? "rotate-180 text-primary" : "group-hover:text-white"
            }`}
          />
        </button>

        {/* Floating Dropdown Popover */}
        {isOpen && (
          <div className="absolute left-0 right-0 top-full mt-1.5 rounded-xl liquid-glass-popover z-50 flex flex-col max-h-[300px] overflow-hidden animate-popover-in">
            {/* Search header */}
            <div className="p-2 border-b border-white/[0.08] bg-[#0d0f18]/90 shrink-0">
              <div className="relative">
                <Search
                  size={12}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant"
                />
                <input
                  type="text"
                  placeholder="Filter providers..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  autoFocus
                  className="w-full liquid-glass-search rounded-lg pl-7 pr-2 py-1.5 text-xs text-white placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary/60 font-sans"
                />
              </div>
            </div>

            {/* Scrollable Items List */}
            <div className="overflow-y-auto p-1.5 space-y-1 max-h-[240px]">
              {/* Local Section */}
              {localPresets.length > 0 && (
                <div className="space-y-0.5">
                  <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-on-surface-variant/60">
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
                        className={`w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between gap-2 liquid-glass-item cursor-pointer group ${
                          isSelected
                            ? "bg-primary/20 text-white font-bold border border-primary/40 shadow-[0_0_12px_rgba(0,218,243,0.15)]"
                            : "text-on-surface hover:text-white"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <div
                            className={`p-1 rounded-md shrink-0 border ${theme.badgeBg} ${theme.badgeBorder} ${theme.accentColor}`}
                          >
                            <Icon size={12} />
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="text-xs font-medium truncate text-white">
                              {p.label}
                            </span>
                            <span className="text-[10px] text-on-surface-variant/60 truncate">
                              {theme.desc}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <span
                            className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono border ${theme.badgeBg} ${theme.badgeBorder} ${theme.badgeText}`}
                          >
                            {theme.tag}
                          </span>
                          {isSelected && (
                            <Check
                              size={12}
                              className="text-primary animate-success-pop"
                              strokeWidth={3}
                            />
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Cloud & API Providers Section */}
              {apiPresets.length > 0 && (
                <div className="space-y-0.5 pt-1 border-t border-white/[0.05]">
                  <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-on-surface-variant/60">
                    Cloud & Frontier Providers
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
                        className={`w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between gap-2 liquid-glass-item cursor-pointer group ${
                          isSelected
                            ? "bg-primary/20 text-white font-bold border border-primary/40 shadow-[0_0_12px_rgba(0,218,243,0.15)]"
                            : "text-on-surface hover:text-white"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <div
                            className={`p-1 rounded-md shrink-0 border ${theme.badgeBg} ${theme.badgeBorder} ${theme.accentColor}`}
                          >
                            <Icon size={12} />
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="text-xs font-medium truncate text-white">
                              {p.label}
                            </span>
                            <span className="text-[10px] text-on-surface-variant/60 truncate">
                              {theme.desc}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {isKeyConfigured ? (
                            <span
                              className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]"
                              title="API Key active"
                            />
                          ) : (
                            <span
                              className="w-1.5 h-1.5 rounded-full bg-white/20"
                              title="No key saved"
                            />
                          )}
                          <span
                            className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono border ${theme.badgeBg} ${theme.badgeBorder} ${theme.badgeText}`}
                          >
                            {theme.tag}
                          </span>
                          {isSelected && (
                            <Check
                              size={12}
                              className="text-primary animate-success-pop"
                              strokeWidth={3}
                            />
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}

              {filteredPresets.length === 0 && (
                <div className="p-4 text-center text-xs text-on-surface-variant">
                  No matching providers found
                </div>
              )}
            </div>
          </div>
        )}

        {/* Caveat note */}
        {preset?.note && (
          <div className="mt-1 flex items-start gap-1.5 px-2 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-[10px] text-amber-200/90 leading-tight">
            <Info size={12} className="text-amber-400 mt-0.5 shrink-0" />
            <span className="truncate">{preset.note}</span>
          </div>
        )}
      </div>

      {/* ── Model Selector Section ───────────────────────────────────────── */}
      <div className="relative" ref={modelDropdownRef}>
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant/80">
            Model
          </span>
          {activeModelObj?.tag && (
            <span
              className={`text-[9px] px-2 py-0.5 rounded-full font-mono font-medium border ${getModelBadgeStyle(
                activeModelObj.tag
              )}`}
            >
              {activeModelObj.tag}
            </span>
          )}
        </div>

        {/* Trigger Button */}
        <button
          type="button"
          onClick={() => {
            const next = !isModelDropdownOpen;
            setIsModelDropdownOpen(next);
            if (next) {
              setIsOpen(false);
              setIsVisionDropdownOpen(false);
            }
          }}
          className={`w-full px-3 py-2 rounded-lg border text-left flex items-center justify-between transition-all duration-150 cursor-pointer shadow-sm group ${
            isModelDropdownOpen
              ? "bg-[#181b29] border-primary/60 ring-1 ring-primary/30 shadow-[0_0_16px_rgba(0,218,243,0.2)]"
              : "bg-[#131622]/90 hover:bg-[#191c2c] border-white/10 hover:border-white/25 hover:shadow-[0_2px_8px_rgba(0,0,0,0.4)]"
          }`}
        >
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <div className="p-1.5 rounded-md bg-primary/10 border border-primary/25 text-primary shrink-0">
              <Bot size={14} />
            </div>
            <div className="flex flex-col min-w-0 flex-1">
              <span className="font-semibold text-xs text-white truncate">
                {activeModelName}
              </span>
              <span className="text-[10px] text-on-surface-variant/70 font-mono truncate">
                {value.model || "Select coding model…"}
              </span>
            </div>
          </div>

          <ChevronDown
            size={13}
            className={`text-on-surface-variant shrink-0 ml-2 transition-transform duration-200 ${
              isModelDropdownOpen
                ? "rotate-180 text-primary"
                : "group-hover:text-white"
            }`}
          />
        </button>

        {/* Floating Model Dropdown Popover */}
        {isModelDropdownOpen && (
          <div className="absolute left-0 right-0 top-full mt-1.5 rounded-xl liquid-glass-popover z-50 flex flex-col max-h-[320px] overflow-hidden animate-popover-in">
            {/* Search Header */}
            <div className="p-2 border-b border-white/[0.08] bg-[#0d0f18]/90 shrink-0">
              <div className="relative">
                <Search
                  size={12}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant"
                />
                <input
                  type="text"
                  placeholder="Search coding models…"
                  value={modelSearchQuery}
                  onChange={(e) => setModelSearchQuery(e.target.value)}
                  autoFocus
                  className="w-full liquid-glass-search rounded-lg pl-7 pr-2 py-1.5 text-xs text-white placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary/60 font-sans"
                />
              </div>
            </div>

            {/* Scrollable Model List */}
            <div className="overflow-y-auto p-1.5 space-y-0.5 max-h-[210px]">
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
                    className={`w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between gap-2 liquid-glass-item cursor-pointer group ${
                      isSelected
                        ? "bg-primary/20 text-white font-bold border border-primary/40 shadow-[0_0_12px_rgba(0,218,243,0.15)]"
                        : "text-on-surface hover:text-white"
                    }`}
                  >
                    <div className="flex flex-col min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-semibold truncate text-white group-hover:text-primary transition-colors">
                          {m.name}
                        </span>
                        {m.tag && (
                          <span
                            className={`text-[9px] px-1.5 py-0.2 rounded-full font-mono font-medium shrink-0 border ${getModelBadgeStyle(
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

                    <div className="flex items-center gap-1.5 shrink-0">
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
                        <Check
                          size={13}
                          strokeWidth={2.5}
                          className="text-primary animate-success-pop"
                        />
                      )}
                    </div>
                  </button>
                );
              })}

              {filteredAvailableModels.length === 0 && (
                <div className="p-4 text-center text-xs text-on-surface-variant">
                  No matching models found
                </div>
              )}
            </div>

            {/* Add Custom Model Footer */}
            <div className="border-t border-white/[0.08] p-2 bg-[#0d0f18]/90 shrink-0">
              {!isAddingCustomModel ? (
                <button
                  type="button"
                  onClick={() => setIsAddingCustomModel(true)}
                  className="w-full px-2.5 py-1.5 rounded-lg text-left text-xs font-semibold text-primary hover:bg-primary/10 transition-colors cursor-pointer flex items-center gap-2"
                >
                  <Plus size={13} />
                  <span>Enter Custom Model Identifier…</span>
                </button>
              ) : (
                <form onSubmit={handleAddCustomModel} className="space-y-2">
                  <div className="text-[10px] font-bold text-on-surface-variant/80 uppercase tracking-wider">
                    Custom Model ID
                  </div>
                  <div className="flex items-center gap-1.5">
                    <input
                      type="text"
                      placeholder="e.g. qwen2.5-coder:32b, glm-5.2…"
                      value={customModelInput}
                      onChange={(e) => setCustomModelInput(e.target.value)}
                      autoFocus
                      className="flex-1 rounded-lg liquid-glass-search px-2.5 py-1 text-xs font-mono text-white placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/60"
                    />
                    <button
                      type="submit"
                      disabled={!customModelInput.trim()}
                      className="px-3 py-1 rounded-lg bg-primary text-[#001f24] font-bold text-xs hover:bg-primary/90 transition-all disabled:opacity-40 cursor-pointer shrink-0"
                    >
                      Use
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setIsAddingCustomModel(false);
                        setCustomModelInput("");
                      }}
                      className="p-1 rounded-lg text-on-surface-variant hover:text-white transition-colors cursor-pointer shrink-0"
                    >
                      <X size={14} />
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        )}

        {/* Reasoning Model indicator pill */}
        {modelIsReasoning && (
          <div className="mt-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 px-2.5 py-1 text-[10px] text-purple-200 flex items-center gap-1.5 shadow-sm">
            <Sparkles size={11} className="text-purple-400 shrink-0" />
            <span className="font-semibold">Reasoning Model active</span>
            <span className="text-purple-300/60 font-mono">
              (Chain-of-thought enabled)
            </span>
          </div>
        )}
      </div>

      {/* ── Collapsible Advanced & Vision Options ─────────────────────────── */}
      <div className="pt-0.5 border-t border-white/[0.06]">
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full flex items-center justify-between py-1 px-1 rounded-lg text-on-surface-variant hover:text-white transition-colors cursor-pointer group"
        >
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Sliders size={12} className="text-primary group-hover:rotate-45 transition-transform" />
            <span>Advanced & Vision Options</span>
          </div>
          <div className="flex items-center gap-1.5">
            {visionModel && (
              <span className="text-[9px] px-1.5 py-0.2 rounded-full font-mono bg-primary/10 text-primary border border-primary/20">
                VLM Active
              </span>
            )}
            <ChevronRight
              size={12}
              className={`transition-transform duration-200 ${
                showAdvanced ? "rotate-90 text-primary" : "text-on-surface-variant"
              }`}
            />
          </div>
        </button>

        {showAdvanced && (
          <div className="mt-2 space-y-2.5 pt-2 border-t border-white/[0.04] animate-fade-in">
            {/* Dedicated Vision QA Model (Sub-call) */}
            <div className="relative" ref={visionDropdownRef}>
              <div className="flex items-center justify-between mb-1 text-[10px]">
                <span className="font-bold text-on-surface-variant flex items-center gap-1">
                  <Eye size={11} className="text-primary" />
                  <span>Vision QA Model (Visual Inspector)</span>
                </span>
                <span className="text-[9px] text-primary/80 font-mono">
                  Multi-modal
                </span>
              </div>

              <button
                type="button"
                onClick={() => {
                  setIsVisionDropdownOpen(!isVisionDropdownOpen);
                  setIsOpen(false);
                  setIsModelDropdownOpen(false);
                }}
                className="w-full px-2.5 py-1.5 rounded-lg bg-[#131622]/90 hover:bg-[#191c2c] border border-white/10 hover:border-white/25 text-left flex items-center justify-between transition-all cursor-pointer text-xs text-white shadow-xs group"
              >
                <div className="flex items-center gap-2 truncate min-w-0 flex-1">
                  <Eye size={12} className="text-primary shrink-0" />
                  <span className="font-mono text-xs truncate">
                    {visionModel ||
                      (VISION_MODELS[value.preset] || VISION_MODELS.groq)[0]?.id ||
                      "Select vision model…"}
                  </span>
                </div>
                <ChevronDown
                  size={12}
                  className={`text-on-surface-variant shrink-0 ml-1 transition-transform duration-200 ${
                    isVisionDropdownOpen ? "rotate-180 text-primary" : "group-hover:text-white"
                  }`}
                />
              </button>

              {isVisionDropdownOpen && (
                <div className="absolute left-0 right-0 top-full mt-1 liquid-glass-popover rounded-xl overflow-hidden z-50 animate-popover-in max-h-[170px] overflow-y-auto p-1 space-y-0.5">
                  {(VISION_MODELS[value.preset] || VISION_MODELS.groq).map((vm) => {
                    const isSel =
                      (visionModel ||
                        (VISION_MODELS[value.preset] || VISION_MODELS.groq)[0]?.id) ===
                      vm.id;
                    return (
                      <button
                        key={vm.id}
                        type="button"
                        onClick={() => {
                          setVisionModel(vm.id);
                          setIsVisionDropdownOpen(false);
                        }}
                        className={`w-full px-2.5 py-1.5 rounded-lg text-left flex items-center justify-between gap-1.5 liquid-glass-item text-xs cursor-pointer ${
                          isSel
                            ? "bg-primary/20 text-primary font-bold border border-primary/40 shadow-[0_0_12px_rgba(0,218,243,0.15)]"
                            : "text-on-surface hover:text-white"
                        }`}
                      >
                        <div className="flex flex-col min-w-0 flex-1">
                          <span className="text-xs font-semibold text-white">
                            {vm.name}
                          </span>
                          <span className="text-[10px] font-mono text-on-surface-variant/70 truncate">
                            {vm.id}
                          </span>
                        </div>
                        {isSel && (
                          <Check
                            size={12}
                            className="text-primary shrink-0"
                            strokeWidth={2.5}
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Ollama Local URL */}
            {isOllama && (
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant mb-1 flex items-center gap-1">
                  <Server size={11} className="text-emerald-400" /> Host URL
                </label>
                <input
                  type="text"
                  placeholder="http://127.0.0.1:11434"
                  value={value.base_url ?? "http://127.0.0.1:11434"}
                  onChange={(e) =>
                    onChange({
                      ...value,
                      base_url: e.target.value || undefined,
                    })
                  }
                  className="w-full rounded-lg bg-[#141620] border border-white/10 px-2.5 py-1.5 text-xs font-mono text-white placeholder:text-on-surface-variant/40 focus:outline-none focus:border-emerald-500/50"
                />
              </div>
            )}

            {/* NVIDIA NIM Self-Hosted Toggle */}
            {isNim && (
              <div className="rounded-lg bg-[#141620] border border-white/10 p-2 space-y-1.5">
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={nimSelfHosted}
                    onChange={(e) => handleNimToggle(e.target.checked)}
                    className="rounded accent-primary text-xs"
                  />
                  <span className="text-xs font-medium text-white">
                    Self-hosted NIM container
                  </span>
                </label>
                {nimSelfHosted && (
                  <input
                    type="text"
                    placeholder="http://localhost:8000/v1"
                    value={value.base_url ?? "http://localhost:8000/v1"}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        base_url: e.target.value || undefined,
                      })
                    }
                    className="w-full rounded-lg bg-[#0f1117] border border-white/10 px-2.5 py-1 text-xs font-mono text-white focus:outline-none focus:border-primary/50"
                  />
                )}
              </div>
            )}

            {/* Custom Endpoint URLs */}
            {isCustom && (
              <div className="space-y-2">
                <div>
                  <label className="text-[10px] font-bold text-on-surface-variant mb-1 block">
                    Base URL
                  </label>
                  <input
                    type="text"
                    placeholder="https://your-endpoint.com/v1"
                    value={value.base_url ?? ""}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        base_url: e.target.value || undefined,
                      })
                    }
                    className="w-full rounded-lg bg-[#141620] border border-white/10 px-2.5 py-1.5 text-xs font-mono text-white placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-bold text-on-surface-variant mb-1 block">
                    Key Identifier
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
                    className="w-full rounded-lg bg-[#141620] border border-white/10 px-2.5 py-1.5 text-xs font-mono text-white placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50"
                  />
                </div>
              </div>
            )}

            {/* Quick link to API Keys settings */}
            {isApiPreset && !isCustom && !isNim && (
              <div className="flex items-center justify-between pt-1 border-t border-white/[0.04] text-[10px]">
                <span className="truncate text-on-surface-variant/60 font-mono">
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
                  className="flex items-center gap-1 text-primary hover:text-primary/80 font-semibold transition-colors shrink-0 ml-2 cursor-pointer"
                >
                  <ExternalLink size={10} /> API Keys Settings
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
