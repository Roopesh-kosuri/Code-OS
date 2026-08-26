import { describe, it, expect, vi, beforeEach } from "vitest";
import { cn } from "../lib/cn";
import { getPreset, PROVIDER_PRESETS } from "../lib/providerPresets";
import { isReasoningModel, getDefaultVisionModel, PRESET_MODELS } from "../lib/models";
import { api } from "../lib/api";

describe("Frontend Lib Utilities", () => {
  describe("cn (classnames merge)", () => {
    it("merges class names correctly", () => {
      expect(cn("px-2", "py-1")).toBe("px-2 py-1");
      expect(cn("px-2", false && "hidden", null, undefined, "bg-red-500")).toBe("px-2 bg-red-500");
    });

    it("resolves Tailwind conflicts in favor of the last class", () => {
      expect(cn("p-4", "p-2")).toBe("p-2");
      expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
    });
  });

  describe("providerPresets", () => {
    it("returns correct preset by id or undefined for unknown", () => {
      const ollama = getPreset("ollama");
      expect(ollama).toBeDefined();
      expect(ollama?.provider).toBe("ollama");
      expect(ollama?.api_key_provider).toBeNull();

      const groq = getPreset("groq");
      expect(groq).toBeDefined();
      expect(groq?.provider).toBe("openai-compatible");
      expect(groq?.base_url).toContain("groq.com");

      const unknown = getPreset("non-existent-preset");
      expect(unknown).toBeUndefined();
    });

    it("has valid schema for all supported presets", () => {
      expect(PROVIDER_PRESETS.length).toBeGreaterThan(3);
      for (const p of PROVIDER_PRESETS) {
        expect(p.id).toBeTruthy();
        expect(p.label).toBeTruthy();
        expect(["ollama", "openai-compatible"]).toContain(p.provider);
        expect(typeof p.base_url).toBe("string");
      }
    });
  });

  describe("models", () => {
    it("detects reasoning models by regex accurately", () => {
      expect(isReasoningModel("deepseek-ai/deepseek-r1")).toBe(true);
      expect(isReasoningModel("o1-mini")).toBe(true);
      expect(isReasoningModel("o3-mini")).toBe(true);
      expect(isReasoningModel("deepseek-reasoner")).toBe(true);
      expect(isReasoningModel("gpt-4o")).toBe(false);
      expect(isReasoningModel("llama-3.1-70b")).toBe(false);
      expect(isReasoningModel("qwen2.5-coder")).toBe(false);
    });

    it("resolves default vision models across presets", () => {
      expect(getDefaultVisionModel("nvidia-nim")).toContain("vision");
      expect(getDefaultVisionModel("openai")).toBe("gpt-4o-mini");
      expect(getDefaultVisionModel("anthropic")).toBe("claude-3-5-haiku-latest");
      expect(getDefaultVisionModel("ollama")).toBe("llama3.2-vision");
    });

    it("provides curated models for major presets", () => {
      expect(PRESET_MODELS["nvidia-nim"].length).toBeGreaterThan(0);
      expect(PRESET_MODELS["openai"].length).toBeGreaterThan(0);
      expect(PRESET_MODELS["anthropic"].length).toBeGreaterThan(0);
    });
  });

  describe("api client", () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    it("makes GET requests and parses JSON response", async () => {
      const mockData = { status: "ok", version: "2.4.0" };
      global.fetch = vi.fn().mockImplementation((url) => {
        if (typeof url === "string" && url.includes("/api/auth/token")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ token: "mock_token" }),
            text: async () => JSON.stringify({ token: "mock_token" }),
          });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockData,
          text: async () => JSON.stringify(mockData),
        });
      });

      const res = await api.get("/api/health");
      expect(res).toEqual(mockData);
    });

    it("makes POST requests with JSON payload", async () => {
      const mockResp = { success: true };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResp,
        text: async () => JSON.stringify(mockResp),
      });

      const res = await api.post("/api/workspaces/trust", { workspace: "D:/ws", trusted: true });
      expect(res).toEqual(mockResp);
    });

    it("throws detailed Error on non-200 HTTP responses", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        statusText: "Forbidden",
        text: async () => JSON.stringify({ detail: "Workspace is untrusted" }),
      });

      await expect(api.post("/api/terminal/sessions", { cwd: "D:/bad" })).rejects.toThrow();
    });
  });
});
