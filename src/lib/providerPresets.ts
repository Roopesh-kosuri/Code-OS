/**
 * Canonical list of supported AI provider presets.
 *
 * Every entry maps to a group of settings the user needs:
 *  - which HTTP endpoint to hit (base_url)
 *  - which api_keys row to use (api_key_provider)
 *  - what to show in the model name placeholder
 *
 * The wire protocol for all non-Ollama entries is "openai-compatible"
 * (OpenAI /chat/completions SSE streaming).
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
   * Informational note shown as a tooltip next to the preset label.
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
  // -- Local ------------------------------------------------------------------
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
    model_placeholder: "llama3, codellama, mistral...",
    model_example: "llama3",
    group: "local",
  },

  // -- API providers ----------------------------------------------------------
  {
    id: "openai",
    label: "OpenAI",
    provider: "openai-compatible",
    base_url: "https://api.openai.com/v1",
    api_key_provider: "openai",
    model_placeholder: "gpt-4o, gpt-4o-mini, o3-mini, gpt-5...",
    model_example: "gpt-4o",
    api_key_prefix: "sk-",
    group: "api",
  },
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    provider: "openai-compatible",
    base_url: "https://api.anthropic.com/v1",
    api_key_provider: "anthropic",
    model_placeholder: "claude-3-7-sonnet, claude-3-5-sonnet-latest...",
    model_example: "claude-3-7-sonnet",
    api_key_prefix: "sk-ant-",
    note:
      "Anthropic's OpenAI-compatible endpoint supports reasoning and multi-turn chat.",
    group: "api",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    provider: "openai-compatible",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    api_key_provider: "gemini",
    model_placeholder: "gemini-2.5-flash, gemini-2.5-pro, gemini-3.0-pro...",
    model_example: "gemini-2.5-flash",
    api_key_prefix: "AIza",
    group: "api",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    provider: "openai-compatible",
    base_url: "https://api.deepseek.com/v1",
    api_key_provider: "deepseek",
    model_placeholder: "deepseek-chat, deepseek-reasoner, deepseek-coder...",
    model_example: "deepseek-chat",
    api_key_prefix: "sk-",
    group: "api",
  },
  {
    id: "moonshot",
    label: "Moonshot AI (Kimi)",
    provider: "openai-compatible",
    base_url: "https://api.moonshot.ai/v1",
    api_key_provider: "moonshot",
    model_placeholder: "moonshot-v1-128k, kimi-k2-0711-preview...",
    model_example: "moonshot-v1-128k",
    api_key_prefix: "sk-",
    group: "api",
  },
  {
    id: "glm",
    label: "GLM (Zhipu AI)",
    provider: "openai-compatible",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    api_key_provider: "glm",
    model_placeholder: "glm-4-plus, glm-4-air, glm-4-flash...",
    model_example: "glm-4-plus",
    group: "api",
  },
  {
    id: "qwen",
    label: "Qwen (Alibaba DashScope)",
    provider: "openai-compatible",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key_provider: "qwen",
    model_placeholder: "qwen-max, qwen-plus, qwen2.5-coder-32b-instruct...",
    model_example: "qwen-max",
    api_key_prefix: "sk-",
    group: "api",
  },
  {
    id: "xai",
    label: "xAI (Grok)",
    provider: "openai-compatible",
    base_url: "https://api.x.ai/v1",
    api_key_provider: "xai",
    model_placeholder: "grok-3, grok-3-mini, grok-2...",
    model_example: "grok-3",
    api_key_prefix: "xai-",
    group: "api",
  },
  {
    id: "mistral",
    label: "Mistral AI",
    provider: "openai-compatible",
    base_url: "https://api.mistral.ai/v1",
    api_key_provider: "mistral",
    model_placeholder: "mistral-large-latest, codestral-latest...",
    model_example: "mistral-large-latest",
    group: "api",
  },
  {
    id: "groq",
    label: "Groq",
    provider: "openai-compatible",
    base_url: "https://api.groq.com/openai/v1",
    api_key_provider: "groq",
    model_placeholder: "openai/gpt-oss-120b, openai/gpt-oss-20b...",
    model_example: "openai/gpt-oss-120b",
    api_key_prefix: "gsk_",
    group: "api",
  },
  {
    id: "nvidia-nim",
    label: "NVIDIA NIM",
    provider: "openai-compatible",
    base_url: "https://integrate.api.nvidia.com/v1",
    api_key_provider: "nvidia-nim",
    model_placeholder: "minimaxai/minimax-m3, meta/llama-3.1-70b-instruct...",
    model_example: "minimaxai/minimax-m3",
    api_key_prefix: "nvapi-",
    note:
      "NVIDIA NIM hosts accelerated open-weight models on NVIDIA GPU infrastructure.",
    supports_self_hosted: true,
    group: "api",
  },
  {
    id: "cohere",
    label: "Cohere",
    provider: "openai-compatible",
    base_url: "https://api.cohere.com/v1",
    api_key_provider: "cohere",
    model_placeholder: "command-a-03-2025, command-r-plus-08-2024...",
    model_example: "command-a-03-2025",
    group: "api",
  },
  {
    id: "llama",
    label: "Meta Llama",
    provider: "openai-compatible",
    base_url: "https://api.groq.com/openai/v1",
    api_key_provider: "groq",
    model_placeholder: "llama-3.3-70b-versatile, llama-3.1-8b-instruct...",
    model_example: "llama-3.3-70b-versatile",
    group: "api",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    provider: "openai-compatible",
    base_url: "https://openrouter.ai/api/v1",
    api_key_provider: "openrouter",
    model_placeholder: "openai/gpt-4o, anthropic/claude-3.7-sonnet...",
    model_example: "openai/gpt-4o",
    api_key_prefix: "sk-or-v1-",
    note:
      "OpenRouter routes to 100+ models from OpenAI, Anthropic, Google, Meta, Mistral through one key.",
    group: "api",
  },
  {
    id: "custom",
    label: "Custom endpoint",
    provider: "openai-compatible",
    base_url: "",
    api_key_provider: "custom",
    model_placeholder: "Enter model name...",
    model_example: "",
    group: "api",
  },
];

/** Quick lookup by preset id */
export function getPreset(id: string): ProviderPreset | undefined {
  return PROVIDER_PRESETS.find((p) => p.id === id);
}

/** All preset IDs that require an API key */
export const API_KEY_PRESET_IDS = PROVIDER_PRESETS.filter(
  (p) => p.api_key_provider !== null && p.id !== "ollama" && p.id !== "custom"
).map((p) => p.api_key_provider as string);
