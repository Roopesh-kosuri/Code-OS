/**
 * Canonical list of supported AI provider presets.
 *
 * Every entry maps to a group of settings the user needs:
 *  - which HTTP endpoint to hit (base_url)
 *  - which api_keys row to use (api_key_provider)
 *  - what to show in the model name placeholder
 *
 * The wire protocol for all non-Ollama entries is "openai-compatible"
 * (OpenAI /chat/completions SSE streaming). The provider classes require
 * no changes — only the config layer was OpenAI-flavored before.
 */

export interface ProviderPreset {
  /** Unique preset ID used as the key in state and api_keys table */
  id: string;
  /** Display label shown in the dropdown */
  label: string;
  /** Wire-protocol provider name sent to backend ChatRequest.provider */
  provider: "ollama" | "openai-compatible";
  /** Default base URL for this provider */
  base_url: string;
  /** Key ID stored in api_keys table. null = no key needed (Ollama local). */
  api_key_provider: string | null;
  /** Placeholder text for the model name input */
  model_placeholder: string;
  /** Example model name shown as hint text */
  model_example: string;
  /** Optional key prefix hint (e.g. "nvapi-" for NVIDIA NIM) */
  api_key_prefix?: string;
  /**
   * Informational note shown as a tooltip (ⓘ) next to the preset label.
   * Use for important behavioural caveats (Anthropic system-msg limit, etc.)
   */
  note?: string;
  /**
   * Whether this preset supports a self-hosted variant where the user can
   * override base_url with their own container URL (NVIDIA NIM).
   */
  supports_self_hosted?: boolean;
  group: "local" | "api";
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  // ── Local ──────────────────────────────────────────────────────────────────
  {
    id: "auto",
    label: "Auto Routing (default)",
    provider: "ollama",
    base_url: "",
    api_key_provider: null,
    model_placeholder: "Automatic model routing...",
    model_example: "",
    group: "local",
  },
  {
    id: "ollama",
    label: "Ollama (local)",
    provider: "ollama",
    base_url: "http://127.0.0.1:11434",
    api_key_provider: null,
    model_placeholder: "llama3, codellama, mistral…",
    model_example: "llama3",
    group: "local",
  },

  // ── API providers ──────────────────────────────────────────────────────────
  {
    id: "openai",
    label: "OpenAI",
    provider: "openai-compatible",
    base_url: "https://api.openai.com/v1",
    api_key_provider: "openai",
    model_placeholder: "gpt-4o, gpt-4o-mini, o3-mini…",
    model_example: "gpt-4o",
    group: "api",
  },
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    provider: "openai-compatible",
    base_url: "https://api.anthropic.com/v1",
    api_key_provider: "anthropic",
    model_placeholder: "claude-sonnet-4-5, claude-opus-4…",
    model_example: "claude-sonnet-4-5",
    note:
      "Anthropic's OpenAI-compatible endpoint only supports a single system message — " +
      "multiple system messages are silently concatenated. This is a compatibility shim, not " +
      "Anthropic's primary API path. For production multi-agent workflows, prefer their native SDK.",
    group: "api",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    provider: "openai-compatible",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    api_key_provider: "gemini",
    model_placeholder: "gemini-2.5-flash, gemini-2.5-pro…",
    model_example: "gemini-2.5-flash",
    group: "api",
  },
  {
    id: "groq",
    label: "Groq",
    provider: "openai-compatible",
    base_url: "https://api.groq.com/openai/v1",
    api_key_provider: "groq",
    model_placeholder: "llama-3.3-70b-versatile, mixtral-8x7b-32768…",
    model_example: "llama-3.3-70b-versatile",
    group: "api",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    provider: "openai-compatible",
    base_url: "https://api.deepseek.com/v1",
    api_key_provider: "deepseek",
    model_placeholder: "deepseek-chat, deepseek-reasoner…",
    model_example: "deepseek-chat",
    group: "api",
  },
  {
    id: "mistral",
    label: "Mistral AI",
    provider: "openai-compatible",
    base_url: "https://api.mistral.ai/v1",
    api_key_provider: "mistral",
    model_placeholder: "mistral-large-latest, codestral-latest…",
    model_example: "mistral-large-latest",
    group: "api",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    provider: "openai-compatible",
    base_url: "https://openrouter.ai/api/v1",
    api_key_provider: "openrouter",
    model_placeholder: "openai/gpt-4o, anthropic/claude-3.5-sonnet…",
    model_example: "openai/gpt-4o",
    note:
      "OpenRouter is a meta-provider that routes to 100+ models from OpenAI, Anthropic, Google, " +
      "Meta, Mistral, and others — all through one API key. Model name format: 'provider/model-name'.",
    group: "api",
  },
  {
    id: "nvidia-nim",
    label: "NVIDIA NIM",
    provider: "openai-compatible",
    base_url: "https://integrate.api.nvidia.com/v1",
    api_key_provider: "nvidia-nim",
    model_placeholder: "meta/llama-3.3-70b-instruct, deepseek/deepseek-r1…",
    model_example: "meta/llama-3.3-70b-instruct",
    api_key_prefix: "nvapi-",
    note:
      "NVIDIA NIM hosts 100+ open-weight models (Llama, DeepSeek, Mistral, Nemotron, GLM…) on " +
      "NVIDIA GPU infrastructure with a free tier. API keys start with 'nvapi-'. " +
      "You can also self-host NIM containers on your own GPU and point to that URL instead.",
    supports_self_hosted: true,
    group: "api",
  },
  {
    id: "custom",
    label: "Custom endpoint",
    provider: "openai-compatible",
    base_url: "",
    api_key_provider: "custom",
    model_placeholder: "Enter model name…",
    model_example: "",
    group: "api",
  },
];

/** Quick lookup by preset id */
export function getPreset(id: string): ProviderPreset | undefined {
  return PROVIDER_PRESETS.find((p) => p.id === id);
}

/** All preset IDs that require an API key */
export const API_KEY_PRESET_IDS = PROVIDER_PRESETS.filter((p) => p.api_key_provider !== null && p.id !== "ollama" && p.id !== "custom")
  .map((p) => p.api_key_provider as string);
