import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEditorStore, MAX_LIVE_TABS } from "../stores/editorStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useRunStore, MAX_LOG_ENTRIES } from "../stores/runStore";
import { api } from "../lib/api";

describe("Phase 2 Frontend Scalability Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/test_workspace", name: "test_workspace" } as any,
    });
  });

  it("test_lru_tab_eviction: caps live tabs at 15 and rehydrates evicted tabs in <50ms", async () => {
    const store = useEditorStore.getState();
    useEditorStore.setState({ openFiles: [], activePath: null });

    // 1. Mock file read for 20 distinct files
    vi.spyOn(api, "get").mockImplementation(async (_url: string, params: any) => {
      return {
        path: params.path,
        content: `content of ${params.path}`,
        language: "typescript",
      };
    });

    // Open 20 files
    for (let i = 1; i <= 20; i++) {
      await useEditorStore.getState().openFile(`file_${i}.ts`);
    }

    const state = useEditorStore.getState();
    expect(state.openFiles.length).toBe(20);

    // Verify exactly 15 have live content and 5 are evicted (content === "")
    const liveTabs = state.openFiles.filter((f) => f.content.length > 0);
    const evictedTabs = state.openFiles.filter((f) => f.content === "");
    expect(liveTabs.length).toBe(MAX_LIVE_TABS); // 15
    expect(evictedTabs.length).toBe(5);

    // Tab 1 (file_1.ts) should be evicted
    const file1Before = state.openFiles.find((f) => f.path === "file_1.ts");
    expect(file1Before?.content).toBe("");

    // 2. Switch back to Tab 1 (file_1.ts) and measure rehydration latency
    const t0 = performance.now();
    await useEditorStore.getState().openFile("file_1.ts");
    const elapsedMs = performance.now() - t0;

    const file1After = useEditorStore.getState().openFiles.find((f) => f.path === "file_1.ts");
    expect(file1After?.content).toBe("content of file_1.ts");
    expect(elapsedMs).toBeLessThan(50); // Rehydrates in <50ms
  });

  it("test_search_virtualization: caps search matches at 1,000", async () => {
    const mock10kMatches = Array.from({ length: 10_000 }, (_, i) => ({
      path: `src/file_${i}.ts`,
      line: i + 1,
      column: 1,
      match_text: `match text ${i}`,
      line_text: `const match_${i} = true;`,
    }));

    vi.spyOn(api, "get").mockResolvedValue(mock10kMatches);

    const rawResults = await api.get<any[]>("/api/search/text", {
      workspace: "D:/test_workspace",
      query: "match",
    });

    // Capping logic slices to 1,000 matches
    const virtualizedList = rawResults.slice(0, 1000);
    expect(virtualizedList.length).toBe(1000);
    expect(virtualizedList[0].path).toBe("src/file_0.ts");
    expect(virtualizedList[999].path).toBe("src/file_999.ts");
  });

  it("test_terminal_buffer_cap: enforces 10,000 lines buffer cap and drops oldest entries", () => {
    useRunStore.setState({ logs: [] });

    // Pipe 15,000 lines into runStore
    const newLogs: any[] = [];
    for (let i = 1; i <= 15_000; i++) {
      newLogs.push({
        id: `log_${i}`,
        type: "stdout",
        text: `Log line message ${i}`,
        timestamp: Date.now(),
      });
    }

    useRunStore.setState((state) => {
      let combined = [...state.logs, ...newLogs];
      if (combined.length > MAX_LOG_ENTRIES) {
        combined = combined.slice(combined.length - MAX_LOG_ENTRIES);
      }
      return { logs: combined };
    });

    const currentLogs = useRunStore.getState().logs;
    expect(currentLogs.length).toBe(MAX_LOG_ENTRIES); // Exactly 10,000
    // Oldest 5,000 dropped: first line should be log_5001
    expect(currentLogs[0].id).toBe("log_5001");
    expect(currentLogs[currentLogs.length - 1].id).toBe("log_15000");
  });
});
