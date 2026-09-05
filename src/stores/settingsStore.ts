import { create } from "zustand";

import { api } from "../lib/api";
import type { SettingDto } from "../types/api";

export interface SettingsState {
  settings: Record<string, string>;
  moonshot_api_key?: string;
  zhipu_api_key?: string;
  qwen_api_key?: string;
  deepseek_api_key?: string;
  xai_api_key?: string;
  nvidia_api_key?: string;
  cohere_api_key?: string;
  load: () => Promise<void>;
  save: (key: string, value: string) => Promise<void>;
  saveApiKey: (providerId: string, apiKey: string) => Promise<void>;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  settings: {},
  moonshot_api_key: undefined,
  zhipu_api_key: undefined,
  qwen_api_key: undefined,
  deepseek_api_key: undefined,
  xai_api_key: undefined,
  nvidia_api_key: undefined,
  cohere_api_key: undefined,
  load: async () => {
    const response = await api.get<SettingDto[]>("/api/settings");
    const newSettings = Object.fromEntries(response.map((item) => [item.key, item.value]));
    if (newSettings.theme) localStorage.setItem("code-os:theme", newSettings.theme);
    set({
      settings: newSettings,
      moonshot_api_key: newSettings["api_key.moonshot"],
      zhipu_api_key: newSettings["api_key.glm"] || newSettings["api_key.zhipu"],
      qwen_api_key: newSettings["api_key.qwen"],
      deepseek_api_key: newSettings["api_key.deepseek"],
      xai_api_key: newSettings["api_key.xai"],
      nvidia_api_key: newSettings["api_key.nvidia-nim"] || newSettings["api_key.nvidia"],
      cohere_api_key: newSettings["api_key.cohere"],
    });
  },
  save: async (key, value) => {
    await api.post("/api/settings", { key, value });
    const current = get().settings;
    set({
      settings: { ...current, [key]: value },
    });
    if (key === "theme") localStorage.setItem("code-os:theme", value);
  },
  saveApiKey: async (providerId, apiKey) => {
    await api.post("/api/settings/api-keys", { provider_id: providerId, api_key: apiKey });
    const stateUpdate: Partial<SettingsState> = {};
    if (providerId === "moonshot") stateUpdate.moonshot_api_key = apiKey;
    if (providerId === "glm" || providerId === "zhipu") stateUpdate.zhipu_api_key = apiKey;
    if (providerId === "qwen") stateUpdate.qwen_api_key = apiKey;
    if (providerId === "deepseek") stateUpdate.deepseek_api_key = apiKey;
    if (providerId === "xai") stateUpdate.xai_api_key = apiKey;
    if (providerId === "nvidia-nim" || providerId === "nvidia") stateUpdate.nvidia_api_key = apiKey;
    if (providerId === "cohere") stateUpdate.cohere_api_key = apiKey;
    set(stateUpdate);
  },
}));
