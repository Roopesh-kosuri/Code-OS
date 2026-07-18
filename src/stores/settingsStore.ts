import { create } from "zustand";

import { api } from "../lib/api";
import type { SettingDto } from "../types/api";

type SettingsState = {
  settings: Record<string, string>;
  load: () => Promise<void>;
  save: (key: string, value: string) => Promise<void>;
  saveApiKey: (providerId: string, apiKey: string) => Promise<void>;
};

export const useSettingsStore = create<SettingsState>((set, get) => ({
  settings: {},
  load: async () => {
    const response = await api.get<SettingDto[]>("/api/settings");
    const newSettings = Object.fromEntries(response.map((item) => [item.key, item.value]));
    if (newSettings.theme) localStorage.setItem("code-os:theme", newSettings.theme);
    set({ settings: newSettings });
  },
  save: async (key, value) => {
    await api.post("/api/settings", { key, value });
    set({ settings: { ...get().settings, [key]: value } });
    if (key === "theme") localStorage.setItem("code-os:theme", value);
  },
  saveApiKey: async (providerId, apiKey) => {
    await api.post("/api/settings/api-keys", { provider_id: providerId, api_key: apiKey });
  }
}));
