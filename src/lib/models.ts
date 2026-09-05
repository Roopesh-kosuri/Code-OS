export function isReasoningModel(model: string): boolean {
  return /(^|[-_/:])(r1|o1|o3|o4|reasoner|reasoning|thinking|qwq|kimi)([-_/:]|$)/i.test(model);
}

export interface CuratedModel {
  id: string;
  name: string;
  tag?: "Flagship" | "Coding" | "Reasoning" | "Fast" | "Vision" | "Recommended" | "Custom";
  description?: string;
  available?: boolean;
}

export const PRESET_MODELS: Record<string, CuratedModel[]> = {
    moonshot: [
    { id: "moonshot-v1-8k", name: "Moonshot v1 8K", tag: "Fast", description: "8K context general model" },
    { id: "moonshot-v1-32k", name: "Moonshot v1 32K", tag: "Recommended", description: "32K context balanced model" },
    { id: "moonshot-v1-128k", name: "Moonshot v1 128K", tag: "Flagship", description: "128K long-context flagship" },
    { id: "moonshot-v1-8k-vision-preview", name: "Moonshot v1 8K Vision", tag: "Vision", description: "8K multimodal vision model" },
    { id: "moonshot-v1-32k-vision-preview", name: "Moonshot v1 32K Vision", tag: "Vision", description: "32K multimodal vision model" },
    { id: "moonshot-v1-128k-vision-preview", name: "Moonshot v1 128K Vision", tag: "Vision", description: "128K multimodal vision model" },
    { id: "kimi-k2-0711-preview", name: "Kimi K2 (0711)", tag: "Recommended", description: "1T MoE (32B active) high-speed reasoning" },
    { id: "kimi-k2-0905-preview", name: "Kimi K2 (0905)", tag: "Recommended", description: "Updated K2 MoE architecture" },
    { id: "kimi-k2-turbo-preview", name: "Kimi K2 Turbo", tag: "Fast", description: "High-throughput fast K2 model" },
    { id: "kimi-k2-thinking", name: "Kimi K2 Thinking", tag: "Reasoning", description: "Deep chain-of-thought reasoning model" },
    { id: "kimi-k2.5", name: "Kimi K2.5", tag: "Flagship", description: "256K unreleased next-gen model", available: false },
    { id: "kimi-latest", name: "Kimi Latest", tag: "Flagship", description: "Alias for latest flagship Kimi model" },
    { id: "moonshot-v1-auto", name: "Moonshot v1 Auto", tag: "Recommended", description: "Automatic context length selector" },
  ],
glm: [
    { id: "glm-4-plus", name: "GLM-4 Plus", tag: "Flagship", description: "128K context flagship general model" },
    { id: "glm-4-air", name: "GLM-4 Air", tag: "Recommended", description: "128K context high-speed model" },
    { id: "glm-4-flash", name: "GLM-4 Flash", tag: "Fast", description: "128K context ultra-fast free tier" },
    { id: "glm-4-long", name: "GLM-4 Long", tag: "Recommended", description: "1M token long-context model" },
    { id: "glm-4v-plus", name: "GLM-4V Plus", tag: "Vision", description: "8K context multimodal vision model" },
    { id: "glm-4v-flash", name: "GLM-4V Flash", tag: "Vision", description: "8K context fast vision model" },
    { id: "glm-5-1", name: "GLM 5.1", tag: "Flagship", description: "Next-gen unreleased model", available: false },
    { id: "glm-5-2", name: "GLM 5.2", tag: "Flagship", description: "Next-gen unreleased model", available: false },
    { id: "glm-5-3", name: "GLM 5.3", tag: "Flagship", description: "Next-gen unreleased model", available: false },
  ],
  qwen: [
    { id: "qwen-max", name: "Qwen Max", tag: "Flagship", description: "128K enterprise reasoning model" },
    { id: "qwen-max-latest", name: "Qwen Max Latest", tag: "Flagship", description: "1M token latest Qwen Max" },
    { id: "qwen-plus", name: "Qwen Plus", tag: "Recommended", description: "131K context balanced model" },
    { id: "qwen-plus-latest", name: "Qwen Plus Latest", tag: "Recommended", description: "1M context Qwen Plus" },
    { id: "qwen-turbo", name: "Qwen Turbo", tag: "Fast", description: "1M token ultra low-cost model" },
    { id: "qwen-turbo-latest", name: "Qwen Turbo Latest", tag: "Fast", description: "1M context low-latency model" },
    { id: "qwen-long", name: "Qwen Long", tag: "Recommended", description: "10M context document specialist" },
    { id: "qwen-coder-plus", name: "Qwen Coder Plus", tag: "Coding", description: "131K code generation & agent specialist" },
    { id: "qwen-coder-turbo", name: "Qwen Coder Turbo", tag: "Coding", description: "131K fast code assistant" },
    { id: "qwen2.5-coder-32b-instruct", name: "Qwen 2.5 Coder 32B", tag: "Coding", description: "131K open-weight code model" },
    { id: "qwen2.5-72b-instruct", name: "Qwen 2.5 72B Instruct", tag: "Flagship", description: "131K open-weight flagship" },
    { id: "qwen2.5-32b-instruct", name: "Qwen 2.5 32B Instruct", tag: "Recommended", description: "131K balanced open weights" },
    { id: "qwen2.5-14b-instruct", name: "Qwen 2.5 14B Instruct", tag: "Fast", description: "131K compact model" },
    { id: "qwen-vl-max", name: "Qwen VL Max", tag: "Vision", description: "32K vision model" },
    { id: "qwen-vl-plus", name: "Qwen VL Plus", tag: "Vision", description: "32K fast vision model" },
    { id: "qwen-math-plus", name: "Qwen Math Plus", tag: "Reasoning", description: "4K math solver" },
    { id: "qwen-math-turbo", name: "Qwen Math Turbo", tag: "Reasoning", description: "4K fast math assistant" },
    { id: "qwq-32b-preview", name: "QwQ 32B Preview", tag: "Reasoning", description: "32K chain-of-thought reasoning" },
    { id: "qwq-plus", name: "QwQ Plus", tag: "Reasoning", description: "Next-gen reasoning model", available: false },
  ],
  deepseek: [
    { id: "deepseek-chat", name: "DeepSeek V3", tag: "Recommended", description: "64K context 671B MoE coding & general model" },
    { id: "deepseek-reasoner", name: "DeepSeek R1", tag: "Reasoning", description: "64K full chain-of-thought reasoning model" },
    { id: "deepseek-coder", name: "DeepSeek Coder V2", tag: "Coding", description: "128K context code generation specialist" },
    { id: "deepseek-coder-v2-lite", name: "DeepSeek Coder V2 Lite", tag: "Coding", description: "128K context lightweight code model" },
    { id: "deepseek-vl", name: "DeepSeek VL", tag: "Vision", description: "4K visual language model" },
    { id: "deepseek-v2.5", name: "DeepSeek V2.5", tag: "Recommended", description: "128K context hybrid model" },
    { id: "deepseek-v3", name: "DeepSeek V3 (Direct)", tag: "Flagship", description: "64K direct V3 endpoint" },
  ],
  openai: [
    { id: "gpt-4o", name: "GPT-4o", tag: "Flagship", description: "128K flagship multimodal model" },
    { id: "gpt-4o-mini", name: "GPT-4o Mini", tag: "Fast", description: "128K lightweight multimodal model" },
    { id: "o3", name: "o3", tag: "Reasoning", description: "200K frontier reasoning model" },
    { id: "o3-mini", name: "o3-mini", tag: "Reasoning", description: "200K high-speed reasoning model" },
    { id: "o4-mini", name: "o4-mini", tag: "Reasoning", description: "200K next-gen reasoning model", available: false },
    { id: "gpt-5", name: "GPT-5", tag: "Flagship", description: "200K+ next-gen base model", available: false },
    { id: "gpt-5-turbo", name: "GPT-5 Turbo", tag: "Recommended", description: "200K+ fast next-gen model", available: false },
    { id: "gpt-5.5", name: "GPT-5.5", tag: "Flagship", description: "200K+ unreleased model", available: false },
    { id: "gpt-5.6-sol", name: "GPT-5.6 Sol", tag: "Flagship", description: "Specialized reasoning variant", available: false },
    { id: "gpt-5.6-terra", name: "GPT-5.6 Terra", tag: "Flagship", description: "Enterprise variant", available: false },
    { id: "gpt-5.6-luna", name: "GPT-5.6 Luna", tag: "Flagship", description: "Creative & coding variant", available: false },
    { id: "gpt-4.1", name: "GPT-4.1", tag: "Flagship", description: "1M context upgrade", available: false },
    { id: "gpt-4.1-mini", name: "GPT-4.1 Mini", tag: "Recommended", description: "1M context compact model", available: false },
    { id: "gpt-4.1-nano", name: "GPT-4.1 Nano", tag: "Fast", description: "1M context ultra-efficient model", available: false },
    { id: "gpt-4.5-preview", name: "GPT-4.5 Preview", tag: "Flagship", description: "128K high-capacity model" },
  ],
  anthropic: [
    { id: "claude-3-7-sonnet", name: "Claude 3.7 Sonnet", tag: "Flagship", description: "200K hybrid reasoning & coding model" },
    { id: "claude-3-7-sonnet-latest", name: "Claude 3.7 Sonnet Latest", tag: "Flagship", description: "Latest Claude 3.7 build" },
    { id: "claude-3-5-sonnet-latest", name: "Claude 3.5 Sonnet", tag: "Recommended", description: "200K benchmark coding assistant" },
    { id: "claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku", tag: "Fast", description: "200K fast responsive assistant" },
    { id: "claude-3-5-haiku-latest", name: "Claude 3.5 Haiku Latest", tag: "Fast", description: "Latest Claude 3.5 Haiku" },
    { id: "claude-3-opus-latest", name: "Claude 3 Opus", tag: "Flagship", description: "200K complex analysis model" },
    { id: "claude-opus-4-20250101", name: "Claude Opus 4 (2025)", tag: "Flagship", description: "Next-gen Opus preview", available: false },
    { id: "claude-opus-4-6", name: "Claude Opus 4.6", tag: "Flagship", description: "Unreleased Opus version", available: false },
    { id: "claude-opus-4-7", name: "Claude Opus 4.7", tag: "Flagship", description: "Unreleased Opus premium", available: false },
    { id: "claude-opus-4-8", name: "Claude Opus 4.8", tag: "Flagship", description: "Unreleased Opus premium", available: false },
    { id: "claude-opus-5", name: "Claude Opus 5", tag: "Flagship", description: "Next-gen flagship", available: false },
    { id: "claude-sonnet-4-7", name: "Claude Sonnet 4.7", tag: "Recommended", description: "Unreleased Sonnet", available: false },
    { id: "claude-sonnet-5", name: "Claude Sonnet 5", tag: "Recommended", description: "Next-gen Sonnet", available: false },
    { id: "claude-fable-5", name: "Claude Fable 5", tag: "Recommended", description: "Creative agent model", available: false },
  ],
  gemini: [
    { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash", tag: "Fast", description: "1M token context, high-speed multimodal" },
    { id: "gemini-2.0-pro", name: "Gemini 2.0 Pro", tag: "Flagship", description: "2M token context advanced reasoning" },
    { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", tag: "Flagship", description: "2M token context reasoning & coding specialist" },
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", tag: "Recommended", description: "1M token context thinking flash model" },
    { id: "gemini-3.0-pro", name: "Gemini 3.0 Pro", tag: "Flagship", description: "2M context next-gen Pro", available: false },
    { id: "gemini-3.0-flash", name: "Gemini 3.0 Flash", tag: "Fast", description: "1M context next-gen Flash", available: false },
    { id: "gemini-3.1-pro", name: "Gemini 3.1 Pro", tag: "Flagship", description: "2M context 3.1 upgrade", available: false },
    { id: "gemini-3.5-flash-low", name: "Gemini 3.5 Flash Low", tag: "Fast", description: "1M context low tier", available: false },
    { id: "gemini-3.5-flash-medium", name: "Gemini 3.5 Flash Medium", tag: "Recommended", description: "1M context medium tier", available: false },
    { id: "gemini-3.5-flash-high", name: "Gemini 3.5 Flash High", tag: "Flagship", description: "1M context high tier", available: false },
    { id: "gemini-3.6-pro", name: "Gemini 3.6 Pro", tag: "Flagship", description: "2M context 3.6 Pro", available: false },
    { id: "gemini-3.6-flash", name: "Gemini 3.6 Flash", tag: "Fast", description: "1M context 3.6 Flash", available: false },
    { id: "gemini-3.7-pro", name: "Gemini 3.7 Pro", tag: "Flagship", description: "2M context 3.7 Pro", available: false },
    { id: "gemini-3.7-flash", name: "Gemini 3.7 Flash", tag: "Fast", description: "1M context 3.7 Flash", available: false },
  ],
  mistral: [
    { id: "mistral-large-2", name: "Mistral Large 2", tag: "Flagship", description: "128K 123B flagship multilingual model" },
    { id: "mistral-large-latest", name: "Mistral Large Latest", tag: "Flagship", description: "128K flagship reasoning model" },
    { id: "mistral-small-latest", name: "Mistral Small Latest", tag: "Recommended", description: "128K efficient 24B model" },
    { id: "mistral-small-2501", name: "Mistral Small 2501", tag: "Recommended", description: "128K updated small model" },
    { id: "pixtral-large-latest", name: "Pixtral Large Latest", tag: "Vision", description: "128K multimodal vision flagship" },
    { id: "pixtral-12b-2409", name: "Pixtral 12B", tag: "Vision", description: "128K lightweight vision model" },
    { id: "codestral-latest", name: "Codestral Latest", tag: "Coding", description: "256K code generation model" },
    { id: "codestral-mamba-latest", name: "Codestral Mamba", tag: "Coding", description: "256K Mamba architecture for code" },
    { id: "open-mistral-nemo", name: "Mistral NeMo", tag: "Recommended", description: "128K 12B open research model" },
    { id: "ministral-8b-latest", name: "Ministral 8B", tag: "Fast", description: "128K edge & low latency model" },
    { id: "ministral-3b-latest", name: "Ministral 3B", tag: "Fast", description: "128K ultra compact edge model" },
  ],
  xai: [
    { id: "grok-3", name: "Grok 3", tag: "Flagship", description: "131K frontier reasoning model" },
    { id: "grok-3-mini", name: "Grok 3 Mini", tag: "Reasoning", description: "131K high-speed reasoning assistant" },
    { id: "grok-2", name: "Grok 2", tag: "Flagship", description: "131K reasoning and coding model" },
    { id: "grok-2-vision", name: "Grok 2 Vision", tag: "Vision", description: "8K multimodal vision model" },
    { id: "grok-beta", name: "Grok Beta", tag: "Recommended", description: "131K early access Grok model" },
    { id: "grok-vision-beta", name: "Grok Vision Beta", tag: "Vision", description: "8K early access vision model" },
  ],
  llama: [
    { id: "llama-4-scout", name: "Llama 4 Scout", tag: "Recommended", description: "10M long-context next-gen Llama", available: false },
    { id: "llama-4-maverick", name: "Llama 4 Maverick", tag: "Flagship", description: "1M context next-gen Llama", available: false },
    { id: "llama-4-behemoth", name: "Llama 4 Behemoth", tag: "Flagship", description: "2M dense frontier model", available: false },
    { id: "llama-3.3-70b-versatile", name: "Llama 3.3 70B", tag: "Recommended", description: "128K top 70B open weights model" },
    { id: "llama-3.3-8b-versatile", name: "Llama 3.3 8B", tag: "Fast", description: "128K fast lightweight model" },
    { id: "llama-3.2-90b-vision", name: "Llama 3.2 90B Vision", tag: "Vision", description: "128K large vision model" },
    { id: "llama-3.2-11b-vision", name: "Llama 3.2 11B Vision", tag: "Vision", description: "128K compact vision model" },
    { id: "llama-3.1-405b-instruct", name: "Llama 3.1 405B Instruct", tag: "Flagship", description: "128K massive 405B model" },
    { id: "llama-3.1-70b-instruct", name: "Llama 3.1 70B Instruct", tag: "Recommended", description: "128K standard 70B instruct" },
    { id: "llama-3.1-8b-instruct", name: "Llama 3.1 8B Instruct", tag: "Fast", description: "128K compact 8B instruct" },
  ],
  "nvidia-nim": [
    { id: "minimaxai/minimax-m3", name: "MiniMax-Text-01 (M3)", tag: "Recommended", description: "1M token context reasoning & coding specialist on NVIDIA NIM" },
    { id: "minimaxai/minimax-01", name: "MiniMax-01", tag: "Flagship", description: "1M context flagship multimodal model on NVIDIA NIM" },
    { id: "nvidia/llama-3.1-nemotron-70b-instruct", name: "Nemotron 70B", tag: "Flagship", description: "128K NVIDIA-aligned 70B reasoning" },
    { id: "nvidia/llama-3.1-nemotron-51b-instruct", name: "Nemotron 51B", tag: "Recommended", description: "128K 51B efficient model" },
    { id: "nvidia/llama-3.1-nemotron-ultra-253b-v1", name: "Nemotron Ultra 253B", tag: "Flagship", description: "128K massive model", available: false },
    { id: "nvidia/llama-3.3-nemotron-super-49b-v1", name: "Nemotron Super 49B", tag: "Recommended", description: "128K super-aligned 49B model" },
    { id: "nvidia/mistral-nemo-minitron-8b-8k-instruct", name: "Minitron 8B", tag: "Fast", description: "8K pruned high speed model" },
    { id: "nvidia/nemotron-4-340b-instruct", name: "Nemotron-4 340B", tag: "Flagship", description: "4K frontier synthetic & code" },
    { id: "nvidia/nemotron-mini-4b-instruct", name: "Nemotron Mini 4B", tag: "Fast", description: "4K lightweight edge model" },
  ],
  groq: [
    { id: "openai/gpt-oss-120b", name: "GPT-OSS 120B", tag: "Recommended", description: "128K frontier open weights model on Groq LPU" },
    { id: "openai/gpt-oss-20b", name: "GPT-OSS 20B", tag: "Fast", description: "128K high-speed open weights model on Groq LPU" },
    { id: "llama-4-scout-17b-16e-instruct", name: "Llama 4 Scout (Groq)", tag: "Recommended", description: "128K next-gen ultra fast Llama", available: false },
    { id: "llama-4-maverick-17b-128e-instruct", name: "Llama 4 Maverick (Groq)", tag: "Flagship", description: "128K fast Llama", available: false },
    { id: "llama-3.3-70b-versatile", name: "Llama 3.3 70B", tag: "Flagship", description: "128K high-throughput 70B on LPU" },
    { id: "llama-3.3-8b-versatile", name: "Llama 3.3 8B", tag: "Fast", description: "128K ultra-low latency 8B on LPU" },
    { id: "llama-3.1-8b-instant", name: "Llama 3.1 8B Instant", tag: "Fast", description: "128K instant response model" },
    { id: "llama-guard-4-12b", name: "Llama Guard 4 12B", tag: "Fast", description: "Safety moderation model", available: false },
    { id: "mixtral-8x7b-32768", name: "Mixtral 8x7B", tag: "Recommended", description: "32K MoE architecture on LPU" },
    { id: "gemma2-9b-it", name: "Gemma 2 9B", tag: "Fast", description: "8K Google open model on Groq" },
    { id: "deepseek-r1-distill-llama-70b", name: "DeepSeek R1 Distill 70B", tag: "Reasoning", description: "128K fast reasoning on Groq LPU" },
    { id: "qwen-2.5-32b", name: "Qwen 2.5 32B", tag: "Recommended", description: "128K Qwen open model on Groq" },
    { id: "qwen-2.5-coder-32b", name: "Qwen 2.5 Coder 32B", tag: "Coding", description: "128K code specialist on Groq" },
  ],
  cohere: [
    { id: "command-a-03-2025", name: "Command A", tag: "Flagship", description: "256K enterprise reasoning model" },
    { id: "command-r-plus-08-2024", name: "Command R+", tag: "Flagship", description: "128K enterprise RAG & agent flagship" },
    { id: "command-r-08-2024", name: "Command R", tag: "Recommended", description: "128K fast enterprise RAG model" },
    { id: "command-r7b-12-2024", name: "Command R7B", tag: "Fast", description: "128K lightweight enterprise model" },
    { id: "c4ai-aya-expanse-32b", name: "Aya Expanse 32B", tag: "Recommended", description: "128K multilingual model" },
    { id: "c4ai-aya-expanse-8b", name: "Aya Expanse 8B", tag: "Fast", description: "8K multilingual compact model" },
  ],
  openrouter: [
    { id: "anthropic/claude-opus-4-5", name: "Claude Opus 4.5", tag: "Flagship", available: false },
    { id: "anthropic/claude-sonnet-4-5", name: "Claude Sonnet 4.5", tag: "Recommended", available: false },
    { id: "openai/gpt-5", name: "GPT-5", tag: "Flagship", available: false },
    { id: "google/gemini-3.0-pro", name: "Gemini 3.0 Pro", tag: "Flagship", available: false },
    { id: "google/gemini-3.5-flash", name: "Gemini 3.5 Flash", tag: "Fast", available: false },
    { id: "deepseek/deepseek-r1", name: "DeepSeek R1", tag: "Reasoning" },
    { id: "deepseek/deepseek-chat", name: "DeepSeek V3", tag: "Coding" },
    { id: "qwen/qwen-max", name: "Qwen Max", tag: "Recommended" },
    { id: "qwen/qwen-2.5-72b-instruct", name: "Qwen 2.5 72B", tag: "Flagship" },
    { id: "meta-llama/llama-4-maverick", name: "Llama 4 Maverick", tag: "Flagship", available: false },
    { id: "meta-llama/llama-4-scout", name: "Llama 4 Scout", tag: "Recommended", available: false },
    { id: "x-ai/grok-3", name: "Grok 3", tag: "Flagship" },
    { id: "mistralai/mistral-large-2", name: "Mistral Large 2", tag: "Flagship" },
    { id: "cohere/command-a", name: "Command A", tag: "Flagship" },
  ],
  ollama: [
    { id: "qwen2.5-coder:7b", name: "Qwen 2.5 Coder 7B", tag: "Coding", description: "Top local code completion" },
    { id: "qwen2.5-coder:32b", name: "Qwen 2.5 Coder 32B", tag: "Flagship", description: "Powerful local code synthesis" },
    { id: "deepseek-r1:14b", name: "DeepSeek R1 14B", tag: "Reasoning", description: "Local reasoning & chain of thought" },
    { id: "llama3.3:70b", name: "Llama 3.3 70B", tag: "Flagship", description: "Comprehensive local reasoning" },
    { id: "llama3.1:8b", name: "Llama 3.1 8B", tag: "Fast", description: "Fast local assistant" },
    { id: "codellama:7b", name: "Code Llama 7B", tag: "Coding", description: "Meta coding model" },
    { id: "mistral:7b", name: "Mistral 7B", tag: "Fast", description: "General lightweight model" },
  ],
  auto: [
    { id: "auto", name: "Auto Routing", tag: "Recommended", description: "Intelligently routes to the best available model" },
  ],
  custom: [
    { id: "custom-model", name: "Custom Endpoint Model", tag: "Custom", description: "Model provided by your custom HTTP endpoint" },
  ],
};

const CUSTOM_MODELS_STORAGE_KEY = "code_os_user_custom_models";

export function getUserCustomModels(presetId: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(CUSTOM_MODELS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed[presetId]) ? parsed[presetId] : [];
  } catch {
    return [];
  }
}

export function saveUserCustomModel(presetId: string, modelId: string): void {
  if (typeof window === "undefined" || !modelId.trim()) return;
  try {
    const raw = localStorage.getItem(CUSTOM_MODELS_STORAGE_KEY);
    const parsed: Record<string, string[]> = raw ? JSON.parse(raw) : {};
    const list = Array.isArray(parsed[presetId]) ? parsed[presetId] : [];
    if (!list.includes(modelId.trim())) {
      parsed[presetId] = [modelId.trim(), ...list];
      localStorage.setItem(CUSTOM_MODELS_STORAGE_KEY, JSON.stringify(parsed));
    }
  } catch {
    // Ignore storage error
  }
}

export function deleteUserCustomModel(presetId: string, modelId: string): void {
  if (typeof window === "undefined") return;
  try {
    const raw = localStorage.getItem(CUSTOM_MODELS_STORAGE_KEY);
    if (!raw) return;
    const parsed: Record<string, string[]> = JSON.parse(raw);
    if (Array.isArray(parsed[presetId])) {
      parsed[presetId] = parsed[presetId].filter((m) => m !== modelId);
      localStorage.setItem(CUSTOM_MODELS_STORAGE_KEY, JSON.stringify(parsed));
    }
  } catch {
    // Ignore storage error
  }
}

export const VISION_MODELS: Record<string, CuratedModel[]> = {
  moonshot: [
    { id: "moonshot-v1-128k-vision-preview", name: "Moonshot v1 128K Vision", tag: "Flagship", description: "128K multimodal vision model" },
    { id: "moonshot-v1-32k-vision-preview", name: "Moonshot v1 32K Vision", tag: "Recommended", description: "32K multimodal vision model" },
    { id: "moonshot-v1-8k-vision-preview", name: "Moonshot v1 8K Vision", tag: "Fast", description: "8K multimodal vision model" },
  ],
  glm: [
    { id: "glm-4v-plus", name: "GLM-4V Plus", tag: "Recommended", description: "Advanced multimodal vision model" },
    { id: "glm-4v-flash", name: "GLM-4V Flash", tag: "Fast", description: "Fast free-tier vision model" },
  ],
  qwen: [
    { id: "qwen-vl-max", name: "Qwen VL Max", tag: "Flagship", description: "Top multimodal vision model" },
    { id: "qwen-vl-plus", name: "Qwen VL Plus", tag: "Recommended", description: "Fast multimodal vision model" },
  ],
  deepseek: [
    { id: "deepseek-vl", name: "DeepSeek VL", tag: "Recommended", description: "Visual language model" },
  ],
  xai: [
    { id: "grok-2-vision", name: "Grok 2 Vision", tag: "Flagship", description: "Multimodal vision assistant" },
    { id: "grok-vision-beta", name: "Grok Vision Beta", tag: "Vision", description: "Early access vision model" },
  ],
  mistral: [
    { id: "pixtral-large-latest", name: "Pixtral Large", tag: "Flagship", description: "Multimodal vision flagship" },
    { id: "pixtral-12b-2409", name: "Pixtral 12B", tag: "Vision", description: "Lightweight vision model" },
  ],
  llama: [
    { id: "llama-3.2-90b-vision", name: "Llama 3.2 90B Vision", tag: "Flagship", description: "Large multimodal vision model" },
    { id: "llama-3.2-11b-vision", name: "Llama 3.2 11B Vision", tag: "Fast", description: "Compact vision model" },
  ],
  groq: [
    { id: "llama-3.2-11b-vision-preview", name: "Llama 3.2 11B Vision", tag: "Recommended", description: "Fast & precise multimodal QA on Groq LPU" },
    { id: "llama-3.2-90b-vision-preview", name: "Llama 3.2 90B Vision", tag: "Flagship", description: "Deep reasoning multimodal model on Groq LPU" },
    { id: "meta-llama/llama-4-scout", name: "Llama 4 Scout", tag: "Fast", description: "Next-gen multimodal reasoning", available: false },
  ],
  openai: [
    { id: "gpt-4o-mini", name: "GPT-4o Mini", tag: "Recommended", description: "High-speed, low-cost visual inspection" },
    { id: "gpt-4o", name: "GPT-4o", tag: "Flagship", description: "Frontier vision & complex UI layout analysis" },
  ],
  anthropic: [
    { id: "claude-3-5-haiku-latest", name: "Claude 3.5 Haiku", tag: "Recommended", description: "Fast visual inspection & spatial analysis" },
    { id: "claude-3-7-sonnet", name: "Claude 3.7 Sonnet", tag: "Flagship", description: "Hybrid visual reasoning and coding" },
    { id: "claude-3-5-sonnet-latest", name: "Claude 3.5 Sonnet", tag: "Flagship", description: "Benchmark visual reasoning & design critique" },
  ],
  gemini: [
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", tag: "Recommended", description: "Ultra-fast multimodal UI inspection" },
    { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", tag: "Flagship", description: "High-intelligence visual layout analysis" },
  ],
  "nvidia-nim": [
    { id: "meta/llama-3.2-11b-vision-instruct", name: "Llama 3.2 11B Vision Instruct", tag: "Recommended", description: "NVIDIA-accelerated visual inspector" },
    { id: "meta/llama-3.2-90b-vision-instruct", name: "Llama 3.2 90B Vision Instruct", tag: "Flagship", description: "High-resolution multimodal visual QA" },
  ],
  ollama: [
    { id: "llama3.2-vision", name: "Llama 3.2 Vision", tag: "Recommended", description: "Local offline multimodal visual inspector" },
    { id: "llava", name: "LLaVA", tag: "Vision", description: "Open source visual assistant" },
    { id: "bakllava", name: "BakLLaVA", tag: "Fast", description: "Lightweight local visual QA" },
  ],
  openrouter: [
    { id: "openai/gpt-4o-mini", name: "GPT-4o Mini", tag: "Recommended" },
    { id: "meta-llama/llama-3.2-11b-vision-instruct", name: "Llama 3.2 11B Vision", tag: "Vision" },
    { id: "anthropic/claude-3.5-haiku", name: "Claude 3.5 Haiku", tag: "Fast" },
  ],
  auto: [
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", tag: "Recommended", description: "Auto-routes to fastest available vision model" },
  ],
  custom: [
    { id: "custom-vlm", name: "Custom Vision Model", tag: "Custom", description: "Model provided by your custom vision endpoint" },
  ],
};

export function getDefaultVisionModel(presetId: string): string {
  const models = VISION_MODELS[presetId] || VISION_MODELS.openai;
  return models[0]?.id || "gpt-4o-mini";
}
