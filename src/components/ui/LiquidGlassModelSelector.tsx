import React, { useState, useRef, useEffect, useMemo } from "react";
import {
  Bot,
  Search,
  ChevronDown,
  Sparkles,
  Check,
  Plus,
  Zap,
  Code2,
  Terminal,
  Cpu,
} from "lucide-react";
import {
  PRESET_MODELS,
  getUserCustomModels,
  saveUserCustomModel,
  type CuratedModel,
} from "../../lib/models";

export interface LiquidGlassModelSelectorProps {
  value: string;
  provider?: string;
  onChange: (model: string, provider?: string) => void;
  onProviderChange?: (provider: string) => void;
  disabled?: boolean;
  placeholder?: string;
  label?: string;
  testId?: string;
  inputTestId?: string;
  compact?: boolean;
  showProviderBadge?: boolean;
  className?: string;
}

export const LiquidGlassModelSelector: React.FC<LiquidGlassModelSelectorProps> = ({
  value,
  provider = "anthropic",
  onChange,
  onProviderChange,
  disabled = false,
  placeholder = "Select model...",
  label,
  testId,
  inputTestId,
  compact = false,
  showProviderBadge = true,
  className = "",
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [customInput, setCustomInput] = useState("");
  const [showCustomEntry, setShowCustomEntry] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Close on escape or outside click
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      document.addEventListener("mousedown", handleClickOutside);
      // Autofocus search input
      setTimeout(() => {
        searchInputRef.current?.focus();
      }, 50);
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  // Normalize provider key
  const normProvider = useMemo(() => {
    const p = (provider || "anthropic").toLowerCase();
    if (p === "nvidia" || p === "nvidia_nim") return "nvidia-nim";
    return p;
  }, [provider]);

  // Available models for current provider + custom models
  const availableModels = useMemo<CuratedModel[]>(() => {
    const userCustoms = getUserCustomModels(normProvider);
    const customList: CuratedModel[] = userCustoms.map((cm) => ({
      id: cm,
      name: cm,
      tag: "Custom",
      description: `Custom model (${normProvider})`,
    }));

    let providerModels: CuratedModel[] = [];
    if (normProvider === "auto") {
      // Aggregate top recommended models across providers
      const picks = [
        ...(PRESET_MODELS["anthropic"] || []).filter((m) => m.tag === "Recommended" || m.tag === "Flagship"),
        ...(PRESET_MODELS["openai"] || []).filter((m) => m.tag === "Recommended" || m.tag === "Reasoning"),
        ...(PRESET_MODELS["deepseek"] || []).filter((m) => m.tag === "Recommended" || m.tag === "Coding"),
        ...(PRESET_MODELS["gemini"] || []).filter((m) => m.tag === "Recommended"),
        ...(PRESET_MODELS["groq"] || []).filter((m) => m.tag === "Recommended"),
      ];
      providerModels = picks;
    } else if (PRESET_MODELS[normProvider]) {
      providerModels = PRESET_MODELS[normProvider].filter((m) => m.available !== false);
    } else {
      // Fallback for providers not explicitly in PRESET_MODELS (e.g. ollama or generic)
      providerModels = [
        { id: "qwen2.5-coder:7b", name: "Qwen 2.5 Coder 7B", tag: "Coding", description: "Local fast coding assistant" },
        { id: "llama3.3:70b", name: "Llama 3.3 70B", tag: "Flagship", description: "High-capability local model" },
        { id: "deepseek-r1:14b", name: "DeepSeek R1 14B", tag: "Reasoning", description: "Local chain-of-thought model" },
      ];
    }

    return [...customList, ...providerModels];
  }, [normProvider]);

  // Current active model object
  const activeModelObj = useMemo(() => {
    return availableModels.find((m) => m.id.toLowerCase() === (value || "").toLowerCase());
  }, [availableModels, value]);

  // Filtered models
  const filteredModels = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return availableModels;
    return availableModels.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        (m.tag && m.tag.toLowerCase().includes(q)) ||
        (m.description && m.description.toLowerCase().includes(q))
    );
  }, [availableModels, searchQuery]);

  const getTagBadgeStyle = (tag?: string) => {
    switch (tag) {
      case "Recommended":
        return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
      case "Coding":
        return "bg-cyan-500/15 text-cyan-300 border-cyan-500/30";
      case "Reasoning":
        return "bg-purple-500/15 text-purple-300 border-purple-500/30";
      case "Fast":
        return "bg-amber-500/15 text-amber-300 border-amber-500/30";
      case "Flagship":
        return "bg-indigo-500/15 text-indigo-300 border-indigo-500/30";
      case "Custom":
        return "bg-rose-500/15 text-rose-300 border-rose-500/30";
      default:
        return "bg-white/10 text-on-surface-variant border-white/10";
    }
  };

  const handleSelectModel = (modelId: string) => {
    onChange(modelId, provider);
    setIsOpen(false);
    setShowCustomEntry(false);
  };

  const handleApplyCustom = () => {
    const trimmed = customInput.trim();
    if (trimmed) {
      saveUserCustomModel(normProvider, trimmed);
      onChange(trimmed, provider);
      setCustomInput("");
      setShowCustomEntry(false);
      setIsOpen(false);
    }
  };

  return (
    <div className={`relative w-full ${className}`} ref={containerRef}>
      {/* Optional Hidden input for automated tests or forms */}
      {inputTestId && (
        <input
          type="hidden"
          data-testid={inputTestId}
          value={value}
          readOnly
        />
      )}

      {/* Trigger Button */}
      <button
        type="button"
        disabled={disabled}
        data-testid={testId || "liquid-glass-model-trigger"}
        onClick={() => setIsOpen((prev) => !prev)}
        className={`w-full text-left rounded-lg border transition-all duration-150 flex items-center justify-between gap-2.5 cursor-pointer shadow-sm group ${
          compact ? "px-2.5 py-1.5" : "px-3 py-2"
        } ${
          disabled
            ? "opacity-50 cursor-not-allowed bg-[#131622]/40 border-white/5"
            : isOpen
              ? "bg-[#181b29] border-primary/60 ring-1 ring-primary/30 shadow-[0_0_16px_rgba(0,218,243,0.2)]"
              : "bg-[#131622]/90 hover:bg-[#191c2c] border-white/10 hover:border-white/25 hover:shadow-[0_2px_8px_rgba(0,0,0,0.4)]"
        }`}
      >
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          <div className="p-1.5 rounded-md bg-primary/10 border border-primary/20 text-primary shrink-0">
            {normProvider === "ollama" ? (
              <Terminal size={14} />
            ) : normProvider === "groq" ? (
              <Zap size={14} />
            ) : normProvider === "deepseek" ? (
              <Code2 size={14} />
            ) : (
              <Bot size={14} />
            )}
          </div>
          <div className="flex flex-col min-w-0 flex-1">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="font-semibold text-xs text-white truncate group-hover:text-primary transition-colors">
                {activeModelObj?.name || value || placeholder}
              </span>
              {activeModelObj?.tag && (
                <span
                  className={`text-[9px] px-1.5 py-0.2 rounded-full font-mono font-medium border shrink-0 ${getTagBadgeStyle(
                    activeModelObj.tag
                  )}`}
                >
                  {activeModelObj.tag}
                </span>
              )}
            </div>
            <span className="text-[10px] text-on-surface-variant/70 font-mono truncate">
              {value ? value : "No model chosen"}
            </span>
          </div>
        </div>

        <ChevronDown
          size={13}
          className={`text-on-surface-variant shrink-0 ml-1 transition-transform duration-200 ${
            isOpen ? "rotate-180 text-primary" : "group-hover:text-white"
          }`}
        />
      </button>

      {/* Floating Dropdown Popover */}
      {isOpen && (
        <div className="absolute left-0 right-0 top-full mt-1.5 rounded-xl liquid-glass-popover z-50 flex flex-col max-h-[320px] overflow-hidden animate-popover-in shadow-2xl">
          {/* Search Header */}
          <div className="p-2 border-b border-white/[0.08] bg-[#0d0f18]/90 shrink-0">
            <div className="relative">
              <Search
                size={12}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant"
              />
              <input
                ref={searchInputRef}
                type="text"
                placeholder={`Search ${provider} models...`}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full liquid-glass-search rounded-lg pl-7 pr-2 py-1.5 text-xs text-white placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary/60 font-sans"
              />
            </div>
          </div>

          {/* Model Item List */}
          <div className="overflow-y-auto p-1.5 space-y-0.5 max-h-[220px]">
            {filteredModels.length > 0 ? (
              filteredModels.map((m) => {
                const isSelected = (value || "").toLowerCase() === m.id.toLowerCase();
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => handleSelectModel(m.id)}
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
                            className={`text-[9px] px-1.5 py-0.2 rounded-full font-mono font-medium border shrink-0 ${getTagBadgeStyle(
                              m.tag
                            )}`}
                          >
                            {m.tag}
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-on-surface-variant/70 font-mono truncate">
                        {m.id}
                      </span>
                      {m.description && (
                        <span className="text-[9px] text-on-surface-variant/60 truncate mt-0.5">
                          {m.description}
                        </span>
                      )}
                    </div>

                    {isSelected && (
                      <Check size={13} className="text-primary shrink-0 ml-1.5" />
                    )}
                  </button>
                );
              })
            ) : (
              <div className="p-3 text-center text-xs text-on-surface-variant">
                No matching models found.
              </div>
            )}
          </div>

          {/* Custom Model Entry Bar */}
          <div className="p-2 border-t border-white/[0.08] bg-[#0c0e17]/95 shrink-0">
            {showCustomEntry ? (
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  placeholder="Enter custom model ID (e.g. meta-llama/Llama-3-70b)"
                  value={customInput}
                  onChange={(e) => setCustomInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleApplyCustom();
                    }
                  }}
                  className="flex-1 bg-surface-container-lowest border border-white/10 rounded-lg px-2.5 py-1 text-xs text-white font-mono placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary"
                />
                <button
                  type="button"
                  onClick={handleApplyCustom}
                  className="px-2.5 py-1 rounded-lg bg-primary-container text-[#001f24] font-bold text-xs hover:opacity-90 transition-opacity cursor-pointer shrink-0"
                >
                  Apply
                </button>
                <button
                  type="button"
                  onClick={() => setShowCustomEntry(false)}
                  className="px-1.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-on-surface-variant text-xs cursor-pointer shrink-0"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowCustomEntry(true)}
                className="w-full flex items-center justify-center gap-1.5 py-1 px-2 rounded-lg text-xs font-mono text-primary hover:bg-primary/10 transition-colors cursor-pointer border border-primary/20 border-dashed"
              >
                <Plus size={12} />
                <span>Custom Model ID</span>
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
