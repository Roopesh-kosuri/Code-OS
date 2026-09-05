import { describe, it, expect, vi, beforeEach } from "vitest";
import { PROVIDER_PRESETS, getPreset } from "../lib/providerPresets";
import { PRESET_MODELS, VISION_MODELS, isReasoningModel } from "../lib/models";
import { useSettingsStore } from "../stores/settingsStore";

describe("Phase 4A & 4B: AI Providers and Models Suite", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }))));
  });

  it("includes all 14 major AI providers in PROVIDER_PRESETS including Moonshot", () => {
    const presetIds = PROVIDER_PRESETS.map((p) => p.id);
    expect(presetIds).toContain("moonshot");
    expect(presetIds).toContain("glm");
    expect(presetIds).toContain("qwen");
    expect(presetIds).toContain("deepseek");
    expect(presetIds).toContain("openai");
    expect(presetIds).toContain("anthropic");
    expect(presetIds).toContain("gemini");
    expect(presetIds).toContain("mistral");
    expect(presetIds).toContain("xai");
    expect(presetIds).toContain("llama");
    expect(presetIds).toContain("nvidia-nim");
    expect(presetIds).toContain("groq");
    expect(presetIds).toContain("cohere");
    expect(presetIds).toContain("openrouter");
  });

  it("configures correct base URLs and auth key providers for new presets", () => {
    const moonshot = getPreset("moonshot");
    expect(moonshot?.base_url).toBe("https://api.moonshot.ai/v1");
    expect(moonshot?.api_key_provider).toBe("moonshot");

    const glm = getPreset("glm");
    expect(glm?.base_url).toBe("https://open.bigmodel.cn/api/paas/v4");
    expect(glm?.api_key_provider).toBe("glm");

    const qwen = getPreset("qwen");
    expect(qwen?.base_url).toBe("https://dashscope.aliyuncs.com/compatible-mode/v1");
    expect(qwen?.api_key_provider).toBe("qwen");

    const xai = getPreset("xai");
    expect(xai?.base_url).toBe("https://api.x.ai/v1");
    expect(xai?.api_key_provider).toBe("xai");

    const cohere = getPreset("cohere");
    expect(cohere?.base_url).toBe("https://api.cohere.com/v1");
    expect(cohere?.api_key_provider).toBe("cohere");
  });

  it("contains curated model definitions for Moonshot, GLM, Qwen, DeepSeek, xAI, Cohere", () => {
    expect(PRESET_MODELS.moonshot?.length).toBeGreaterThanOrEqual(12);
    expect(PRESET_MODELS.moonshot.map((m) => m.id)).toContain("moonshot-v1-128k");
    expect(PRESET_MODELS.moonshot.map((m) => m.id)).toContain("kimi-k2-0711-preview");
    expect(PRESET_MODELS.moonshot.map((m) => m.id)).toContain("kimi-k2-thinking");

    expect(PRESET_MODELS.glm?.length).toBeGreaterThanOrEqual(6);
    expect(PRESET_MODELS.glm.map((m) => m.id)).toContain("glm-4-plus");

    expect(PRESET_MODELS.qwen?.length).toBeGreaterThanOrEqual(10);
    expect(PRESET_MODELS.qwen.map((m) => m.id)).toContain("qwen-max");
    expect(PRESET_MODELS.qwen.map((m) => m.id)).toContain("qwq-32b-preview");

    expect(PRESET_MODELS.deepseek?.length).toBeGreaterThanOrEqual(5);
    expect(PRESET_MODELS.deepseek.map((m) => m.id)).toContain("deepseek-chat");
    expect(PRESET_MODELS.deepseek.map((m) => m.id)).toContain("deepseek-reasoner");

    expect(PRESET_MODELS.xai?.length).toBeGreaterThanOrEqual(5);
    expect(PRESET_MODELS.xai.map((m) => m.id)).toContain("grok-3");

    expect(PRESET_MODELS.cohere?.length).toBeGreaterThanOrEqual(5);
    expect(PRESET_MODELS.cohere.map((m) => m.id)).toContain("command-a-03-2025");
  });

  it("contains updated OpenAI GPT-5, Anthropic Claude 3.7, and Gemini 3.x models", () => {
    const oaiIds = PRESET_MODELS.openai.map((m) => m.id);
    expect(oaiIds).toContain("o3");
    expect(oaiIds).toContain("o3-mini");
    expect(oaiIds).toContain("gpt-5");

    const claudeIds = PRESET_MODELS.anthropic.map((m) => m.id);
    expect(claudeIds).toContain("claude-3-7-sonnet");
    expect(claudeIds).toContain("claude-opus-5");

    const geminiIds = PRESET_MODELS.gemini.map((m) => m.id);
    expect(geminiIds).toContain("gemini-2.0-flash");
    expect(geminiIds).toContain("gemini-2.5-pro");
    expect(geminiIds).toContain("gemini-3.0-pro");
  });

  it("identifies reasoning models correctly with regex helper", () => {
    expect(isReasoningModel("deepseek-reasoner")).toBe(true);
    expect(isReasoningModel("deepseek-r1")).toBe(true);
    expect(isReasoningModel("kimi-k2-thinking")).toBe(true);
    expect(isReasoningModel("o3-mini")).toBe(true);
    expect(isReasoningModel("o4-mini")).toBe(true);
    expect(isReasoningModel("qwq-32b-preview")).toBe(true);
    expect(isReasoningModel("gemini-2.0-flash-thinking-exp")).toBe(true);
    expect(isReasoningModel("gpt-4o")).toBe(false);
  });

  it("contains vision models for all multimodal providers", () => {
    expect(VISION_MODELS.moonshot?.length).toBeGreaterThanOrEqual(2);
    expect(VISION_MODELS.glm?.length).toBeGreaterThanOrEqual(2);
    expect(VISION_MODELS.qwen?.length).toBeGreaterThanOrEqual(2);
    expect(VISION_MODELS.xai?.length).toBeGreaterThanOrEqual(2);
    expect(VISION_MODELS.deepseek?.length).toBeGreaterThanOrEqual(1);
    expect(VISION_MODELS.mistral?.length).toBeGreaterThanOrEqual(2);
  });

  it("updates settingsStore with specific API keys", async () => {
    const store = useSettingsStore.getState();
    await store.saveApiKey("moonshot", "sk-moonshot-secret-key-000");
    expect(useSettingsStore.getState().moonshot_api_key).toBe("sk-moonshot-secret-key-000");

    await store.saveApiKey("qwen", "qwen-secret-key-123");
    expect(useSettingsStore.getState().qwen_api_key).toBe("qwen-secret-key-123");

    await store.saveApiKey("xai", "xai-secret-key-456");
    expect(useSettingsStore.getState().xai_api_key).toBe("xai-secret-key-456");
  });
});
