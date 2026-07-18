/**
 * ProviderSelector — shared component used in AIChatPanel, DuoPanel, and SettingsPanel.
 *
 * Handles preset selection, auto-fills base_url, shows model placeholder,
 * displays Anthropic caveat tooltip, and supports NVIDIA NIM self-hosted mode.
 *
 * API key management (save/delete) is done separately in SettingsPanel.
 * This component only shows a "✓ key configured" badge when configuredKeys is provided.
 */
import { useState } from "react";
import { Info, KeyRound, Check, ChevronDown, Server, ExternalLink } from "lucide-react";
import { PROVIDER_PRESETS, getPreset, type ProviderPreset } from "../../lib/providerPresets";
import { isReasoningModel } from "../../lib/models";

// ── Public types ──────────────────────────────────────────────────────────────

export interface ProviderConfig {
  /** Preset ID — one of PROVIDER_PRESETS[*].id */
  preset: string;
  /** Model name string */
  model: string;
  /** Effective base URL (may be overridden for custom / NIM self-hosted) */
  base_url?: string;
  /** api_keys.provider_id for key lookup — set by preset or manual for custom */
  api_key_provider?: string;
}

interface ProviderSelectorProps {
  /** Section label rendered above the controls */
  label?: string;
  value: ProviderConfig;
  onChange: (cfg: ProviderConfig) => void;
  /** List of provider_id strings that have a stored key (from /api/settings/api-keys) */
  configuredKeys?: string[];
  /** Show compact 2-col layout (for Duo panel) */
  compact?: boolean;
  /** Available models loaded from store */
  models?: { name: string; provider: string }[];
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

function InfoTooltip({ text }: { text: string }) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="relative inline-flex items-center">
      <button
        type="button"
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        className="ml-1 text-slate-500 hover:text-accent-400 transition-colors"
        aria-label="More information"
      >
        <Info size={12} />
      </button>
      {visible && (
        <div className="absolute left-5 top-0 z-50 w-72 rounded-lg border border-amber-500/40 bg-surface-800 p-2.5 text-[11px] text-slate-300 leading-relaxed shadow-xl">
          <div className="flex items-start gap-1.5">
            <Info size={11} className="text-amber-400 mt-0.5 shrink-0" />
            <span>{text}</span>
          </div>
        </div>
      )}
    </span>
  );
}

// ── Key status badge ──────────────────────────────────────────────────────────

function KeyBadge({ keyId, configuredKeys }: { keyId: string | null | undefined; configuredKeys?: string[] }) {
  if (!keyId || !configuredKeys) return null;
  const isSet = configuredKeys.includes(keyId);
  return (
    <span className={`inline-flex items-center gap-0.5 rounded px-1 py-px text-[9px] font-semibold border ${
      isSet
        ? "text-emerald-400 bg-emerald-400/10 border-emerald-500/30"
        : "text-slate-500 bg-surface-700 border-surface-600"
    }`}>
      {isSet ? <><Check size={8} /> Key set</> : <><KeyRound size={8} /> No key</>}
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ProviderSelector({ label, value, onChange, configuredKeys, compact = false, models = [] }: ProviderSelectorProps) {
  const [nimSelfHosted, setNimSelfHosted] = useState(
    value.preset === "nvidia-nim" &&
    !!value.base_url &&
    value.base_url !== "https://integrate.api.nvidia.com/v1"
  );

  const preset: ProviderPreset | undefined = getPreset(value.preset);

  const handlePresetChange = (newPresetId: string) => {
    const newPreset = getPreset(newPresetId);
    if (!newPreset) return;
    setNimSelfHosted(false);
    // Auto-fill model_example when switching presets so users don't need to type
    const autoModel = newPresetId === value.preset ? value.model : (newPreset.model_example || "");
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
      base_url: selfHosted ? "http://localhost:8000/v1" : "https://integrate.api.nvidia.com/v1",
    });
  };

  const isOllama = value.preset === "ollama";
  const isCustom = value.preset === "custom";
  const isNim = value.preset === "nvidia-nim";
  const isApiPreset = !isOllama;
  const modelIsReasoning = isReasoningModel(value.model);

  const inputCls = "w-full rounded bg-surface-800 border border-surface-600 px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-accent-500 transition-colors";
  const selectCls = `${inputCls} appearance-none`;

  return (
    <div className={`rounded-lg border border-surface-700 bg-surface-900 ${compact ? "p-2.5 space-y-2" : "p-3 space-y-2.5"}`}>
      {/* Header */}
      {label && (
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">{label}</span>
          {preset?.api_key_provider && (
            <KeyBadge keyId={preset.api_key_provider} configuredKeys={configuredKeys} />
          )}
        </div>
      )}

      {/* Preset dropdown */}
      <div>
        <label className="text-[10px] text-slate-500 mb-0.5 block">Provider</label>
        <div className="relative">
          <select
            value={value.preset}
            onChange={(e) => handlePresetChange(e.target.value)}
            className={`${selectCls} pr-6`}
          >
            <optgroup label="Local">
              {PROVIDER_PRESETS.filter((p) => p.group === "local").map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </optgroup>
            <optgroup label="API Providers">
              {PROVIDER_PRESETS.filter((p) => p.group === "api").map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </optgroup>
          </select>
          <ChevronDown size={11} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-500" />
        </div>
        {/* Caveat tooltip for presets with a note */}
        {preset?.note && (
          <div className="mt-1 flex items-start gap-1 text-[10px] text-slate-500">
            <InfoTooltip text={preset.note} />
            <span>{preset.id === "anthropic" ? "Single system-message limit — see ⓘ" :
                   preset.id === "openrouter" ? "Routes 100+ models — see ⓘ" :
                   preset.id === "nvidia-nim" ? "100+ open-weight models — see ⓘ" :
                   "See ⓘ for details"}</span>
          </div>
        )}
      </div>

      {/* Model selector */}
      <div>
        <label className="text-[10px] text-slate-500 mb-0.5 block">Model</label>
        {(() => {
          const activeProvider = preset?.provider ?? "ollama";
          const filteredModels = models.filter(m => m.provider === activeProvider);
          const hasModels = filteredModels.length > 0;
          const modelExists = filteredModels.some(m => m.name === value.model);

          if (hasModels) {
            return (
              <div className="space-y-1.5">
                <div className="relative">
                  <select
                    value={modelExists ? value.model : "custom"}
                    onChange={(e) => {
                      const val = e.target.value;
                      if (val === "custom") {
                        onChange({ ...value, model: "" });
                      } else {
                        onChange({ ...value, model: val });
                      }
                    }}
                    className={`${selectCls} pr-6`}
                  >
                    <option value="">Select a model...</option>
                    {filteredModels.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name}
                      </option>
                    ))}
                    <option value="custom">Custom (Type manual)...</option>
                  </select>
                  <ChevronDown size={11} className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-500" />
                </div>
                {(!modelExists || value.model === "") && (
                  <input
                    type="text"
                    placeholder={preset?.model_placeholder ?? "Enter model name…"}
                    value={value.model}
                    onChange={(e) => onChange({ ...value, model: e.target.value })}
                    className={inputCls}
                  />
                )}
              </div>
            );
          }

          return (
            <div className="space-y-1">
              <input
                type="text"
                placeholder={preset?.model_placeholder ?? "Enter model name…"}
                value={value.model}
                onChange={(e) => onChange({ ...value, model: e.target.value })}
                className={inputCls}
              />
              {preset?.model_example && (
                <p className="mt-0.5 text-[9px] text-slate-600">e.g. {preset.model_example}</p>
              )}
            </div>
          );
        })()}
        {modelIsReasoning && (
          <p className="mt-1.5 rounded border border-amber-500/25 bg-amber-500/5 px-2 py-1.5 text-[10px] leading-relaxed text-amber-200">
            This is a reasoning model. It may spend extra time thinking before streaming, especially when run locally.
          </p>
        )}
      </div>

      {/* Ollama base URL (always editable for local) */}
      {isOllama && (
        <div>
          <label className="text-[10px] text-slate-500 mb-0.5 block flex items-center gap-1">
            <Server size={9} /> Ollama URL
          </label>
          <input
            type="text"
            placeholder="http://127.0.0.1:11434"
            value={value.base_url ?? "http://127.0.0.1:11434"}
            onChange={(e) => onChange({ ...value, base_url: e.target.value || undefined })}
            className={inputCls}
          />
        </div>
      )}

      {/* NVIDIA NIM self-hosted toggle */}
      {isNim && (
        <div className="rounded bg-surface-800 border border-surface-600 p-2 space-y-1.5">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={nimSelfHosted}
              onChange={(e) => handleNimToggle(e.target.checked)}
              className="rounded"
            />
            <span className="text-[10px] text-slate-400">Self-hosted NIM container</span>
          </label>
          {nimSelfHosted && (
            <input
              type="text"
              placeholder="http://localhost:8000/v1"
              value={value.base_url ?? "http://localhost:8000/v1"}
              onChange={(e) => onChange({ ...value, base_url: e.target.value || undefined })}
              className={inputCls}
            />
          )}
          {!nimSelfHosted && (
            <p className="text-[9px] text-slate-600">Using NVIDIA hosted endpoint (requires nvapi- key)</p>
          )}
        </div>
      )}

      {/* Custom endpoint: editable base URL + key provider ID */}
      {isCustom && (
        <div className="space-y-1.5">
          <div>
            <label className="text-[10px] text-slate-500 mb-0.5 block">Base URL</label>
            <input
              type="text"
              placeholder="https://your-endpoint.com/v1"
              value={value.base_url ?? ""}
              onChange={(e) => onChange({ ...value, base_url: e.target.value || undefined })}
              className={inputCls}
            />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 mb-0.5 block">
              Key ID <span className="text-slate-600">(for stored API key lookup)</span>
            </label>
            <input
              type="text"
              placeholder="custom"
              value={value.api_key_provider ?? "custom"}
              onChange={(e) => onChange({ ...value, api_key_provider: e.target.value || "custom" })}
              className={inputCls}
            />
          </div>
        </div>
      )}

      {/* API preset: show non-editable base URL (dim) + link to settings for key */}
      {isApiPreset && !isCustom && !isNim && (
        <div className="flex items-center justify-between">
          <span className="truncate text-[9px] text-slate-600 font-mono">
            {preset?.base_url ?? ""}
          </span>
          {!configuredKeys && (
            <button
              type="button"
              onClick={() => window.dispatchEvent(new CustomEvent("code-os:switch-utility", { detail: "settings" }))}
              className="flex items-center gap-0.5 text-[9px] text-accent-400 hover:text-accent-300 transition-colors shrink-0 ml-2"
            >
              <ExternalLink size={9} /> Save key in Settings
            </button>
          )}
        </div>
      )}
    </div>
  );
}
