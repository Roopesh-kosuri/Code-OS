export function isReasoningModel(model: string): boolean {
  return /(^|[-_/:])(r1|o1|o3|reasoner|reasoning|thinking)([-_/:]|$)/i.test(model);
}

export interface CuratedModel {
  id: string;
  name: string;
  tag?: "Flagship" | "Coding" | "Reasoning" | "Fast" | "Vision" | "Recommended" | "Custom";
  description?: string;
}

export const PRESET_MODELS: Record<string, CuratedModel[]> = {
  "nvidia-nim": [
    { id: "meta/llama-3.3-70b-instruct", name: "Llama 3.3 70B Instruct", tag: "Recommended", description: "Top coding & agent performance" },
    { id: "z-ai/glm-5.2", name: "GLM 5.2", tag: "Flagship", description: "High-capability reasoning & code synthesis" },
    { id: "deepseek-ai/deepseek-r1", name: "DeepSeek R1", tag: "Reasoning", description: "Full chain-of-thought math & code reasoning" },
    { id: "deepseek-ai/deepseek-v3", name: "DeepSeek V3", tag: "Coding", description: "671B MoE architecture for software engineering" },
    { id: "nvidia/llama-3.1-nemotron-70b-instruct", name: "Llama 3.1 Nemotron 70B", tag: "Flagship", description: "NVIDIA-aligned high accuracy assistant" },
    { id: "mistralai/codestral-22b-instruct-v0.1", name: "Codestral 22B", tag: "Coding", description: "Specialized 80+ programming language model" },
    { id: "mistralai/mistral-large-2407", name: "Mistral Large 2407", tag: "Flagship", description: "128k context reasoning & multi-lingual code" },
    { id: "qwen/qwen2.5-coder-32b-instruct", name: "Qwen 2.5 Coder 32B", tag: "Coding", description: "State-of-the-art open code generation" },
    { id: "meta/llama-3.1-8b-instruct", name: "Llama 3.1 8B Instruct", tag: "Fast", description: "Fast lightweight assistance" },
    { id: "writer/palmyra-med-70b", name: "Palmyra Med 70B", tag: "Flagship" },
    { id: "zyphra/zamba2-7b-instruct", name: "Zamba2 7B Instruct", tag: "Fast" },
  ],
  openai: [
    { id: "gpt-4o", name: "GPT-4o", tag: "Flagship", description: "Omni-modal flagship model for complex coding" },
    { id: "gpt-4o-mini", name: "GPT-4o Mini", tag: "Fast", description: "Affordable, high-speed coding and chat" },
    { id: "o3-mini", name: "o3-mini", tag: "Reasoning", description: "High-intelligence STEM & code reasoning" },
    { id: "o1", name: "o1", tag: "Reasoning", description: "Advanced deep-thinking reasoning" },
    { id: "o1-mini", name: "o1-mini", tag: "Reasoning", description: "Fast specialized code & math reasoning" },
    { id: "gpt-4-turbo", name: "GPT-4 Turbo", tag: "Flagship", description: "128k context with vision support" },
  ],
  anthropic: [
    { id: "claude-3-7-sonnet", name: "Claude 3.7 Sonnet", tag: "Flagship", description: "Hybrid reasoning & coding flagship" },
    { id: "claude-3-5-sonnet-latest", name: "Claude 3.5 Sonnet", tag: "Recommended", description: "Industry benchmark for software engineering" },
    { id: "claude-3-5-haiku-latest", name: "Claude 3.5 Haiku", tag: "Fast", description: "Lightning-fast code generation" },
    { id: "claude-3-opus-latest", name: "Claude 3 Opus", tag: "Flagship", description: "Deep analysis and complex architecture" },
  ],
  gemini: [
    { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", tag: "Recommended", description: "1M token context, high-speed generation" },
    { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", tag: "Flagship", description: "2M token context, advanced coding & reasoning" },
    { id: "gemini-2.0-flash-thinking-exp", name: "Gemini 2.0 Flash Thinking", tag: "Reasoning", description: "Built-in reasoning trace for tricky logic" },
    { id: "gemini-1.5-pro", name: "Gemini 1.5 Pro", tag: "Flagship", description: "High-capacity analysis" },
  ],
  groq: [
    { id: "openai/gpt-oss-120b", name: "GPT-OSS 120B", tag: "Recommended", description: "High-parameter open coding powerhouse" },
    { id: "openai/gpt-oss-20b", name: "GPT-OSS 20B", tag: "Fast", description: "Ultra-fast low-latency code completion" },
    { id: "llama-3.3-70b-versatile", name: "Llama 3.3 70B", tag: "Flagship", description: "128k context versatile coding" },
    { id: "deepseek-r1-distill-llama-70b", name: "DeepSeek R1 Distill 70B", tag: "Reasoning", description: "Fast reasoning on Groq LPU" },
    { id: "llama-3.1-8b-instant", name: "Llama 3.1 8B Instant", tag: "Fast", description: "750+ tokens/second speed" },
    { id: "mixtral-8x7b-32768", name: "Mixtral 8x7B", tag: "Coding", description: "32k context MoE model" },
  ],
  deepseek: [
    { id: "deepseek-chat", name: "DeepSeek V3 (Chat)", tag: "Recommended", description: "671B MoE frontier coding & general agent" },
    { id: "deepseek-reasoner", name: "DeepSeek R1 (Reasoner)", tag: "Reasoning", description: "Deep thinking chain-of-thought model" },
  ],
  mistral: [
    { id: "codestral-latest", name: "Codestral", tag: "Recommended", description: "Specialized 80+ programming language model" },
    { id: "mistral-large-latest", name: "Mistral Large", tag: "Flagship", description: "Flagship 128k context reasoning model" },
    { id: "mistral-small-latest", name: "Mistral Small", tag: "Fast", description: "Efficient lightweight coding model" },
  ],
  openrouter: [
    { id: "anthropic/claude-3.5-sonnet", name: "Claude 3.5 Sonnet", tag: "Recommended" },
    { id: "openai/gpt-4o", name: "GPT-4o", tag: "Flagship" },
    { id: "deepseek/deepseek-r1", name: "DeepSeek R1", tag: "Reasoning" },
    { id: "deepseek/deepseek-chat", name: "DeepSeek V3", tag: "Coding" },
    { id: "google/gemini-2.5-flash", name: "Gemini 2.5 Flash", tag: "Fast" },
    { id: "meta-llama/llama-3.3-70b-instruct", name: "Llama 3.3 70B", tag: "Flagship" },
    { id: "qwen/qwen-2.5-coder-32b-instruct", name: "Qwen 2.5 Coder 32B", tag: "Coding" },
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
