import { describe, expect, it, beforeEach } from "vitest";
import { useEditorStore } from "../stores/editorStore";

describe("Phase 6: Recent Files MRU Store & Cycling", () => {
  beforeEach(() => {
    localStorage.clear();
    useEditorStore.setState({
      recentFiles: [],
      openFiles: [],
      activePath: null,
    });
  });

  it("tracks MRU order properly when adding and reopening files", () => {
    const store = useEditorStore.getState();

    store.addToRecentFiles("/workspace/fileA.ts");
    store.addToRecentFiles("/workspace/fileB.ts");
    store.addToRecentFiles("/workspace/fileC.ts");

    expect(useEditorStore.getState().recentFiles).toEqual([
      "/workspace/fileC.ts",
      "/workspace/fileB.ts",
      "/workspace/fileA.ts",
    ]);

    // Reopen fileB -> moves to front
    store.addToRecentFiles("/workspace/fileB.ts");
    expect(useEditorStore.getState().recentFiles).toEqual([
      "/workspace/fileB.ts",
      "/workspace/fileC.ts",
      "/workspace/fileA.ts",
    ]);

    // Reopen fileA -> moves to front
    store.addToRecentFiles("/workspace/fileA.ts");
    expect(useEditorStore.getState().recentFiles).toEqual([
      "/workspace/fileA.ts",
      "/workspace/fileB.ts",
      "/workspace/fileC.ts",
    ]);
  });

  it("strictly caps recent files list at 20 entries", () => {
    const store = useEditorStore.getState();

    for (let i = 1; i <= 30; i++) {
      store.addToRecentFiles(`/workspace/file_${i}.ts`);
    }

    const recents = useEditorStore.getState().recentFiles;
    expect(recents).toHaveLength(20);
    // Most recent is file_30, oldest kept is file_11
    expect(recents[0]).toBe("/workspace/file_30.ts");
    expect(recents[19]).toBe("/workspace/file_11.ts");
    expect(recents).not.toContain("/workspace/file_1.ts");
  });

  it("persists recent files to localStorage", () => {
    const store = useEditorStore.getState();
    store.addToRecentFiles("/workspace/app.tsx");

    const saved = localStorage.getItem("code-os:recent-files");
    expect(saved).toBeTruthy();
    expect(JSON.parse(saved!)).toEqual(["/workspace/app.tsx"]);
  });
});
