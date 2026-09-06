import { describe, it, expect, vi, beforeEach } from "vitest";
import { useGhostTextStore, type GhostChunk } from "../features/editor/ghostTextStore";
import {
  showGhostText,
  clearGhostText,
  acceptGhostText,
  rejectGhostText,
  installGhostTextKeybindings,
  attachGhostTextListener,
} from "../features/editor/ghostTextManager";
import { useEditorStore } from "../stores/editorStore";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ ok: true }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    put: vi.fn().mockResolvedValue({ ok: true }),
    delete: vi.fn().mockResolvedValue({ ok: true }),
    streamSSE: vi.fn(() => new AbortController()),
  },
}));

describe("Ghost Text & Inline Diffs Frontend Suite", () => {
  let mockModel: any;
  let mockEditor: any;
  let mockMonaco: any;

  beforeEach(() => {
    vi.clearAllMocks();
    useGhostTextStore.setState({
      activeEditors: {},
      fileToEditorId: {},
      ghostStreams: {},
      abortControllers: {},
    });

    mockModel = {
      getLineCount: vi.fn(() => 50),
      getValueInRange: vi.fn(() => "mock code"),
    };

    mockEditor = {
      getModel: vi.fn(() => mockModel),
      deltaDecorations: vi.fn((_old: string[], _new: any[]) => ["dec-1", "dec-2"]),
      setValue: vi.fn(),
      onKeyDown: vi.fn(),
    };

    mockMonaco = {
      Range: class Range {
        startLineNumber: number;
        startColumn: number;
        endLineNumber: number;
        endColumn: number;
        constructor(startLine: number, startCol: number, endLine: number, endCol: number) {
          this.startLineNumber = startLine;
          this.startColumn = startCol;
          this.endLineNumber = endLine;
          this.endColumn = endCol;
        }
      },
      KeyCode: {
        Tab: 2,
        Escape: 9,
      },
      editor: {
        OverviewRulerLane: {
          Right: 4,
        },
      },
    };
  });

  it("test_editor_registers_on_open: tracks editor tab and registers with backend", async () => {
    const ws = "/workspace/demo";
    const filePath = "src/index.ts";
    const editorId = "monaco_test_1";

    await useGhostTextStore.getState().registerEditor(ws, filePath, editorId);

    const state = useGhostTextStore.getState();
    expect(state.activeEditors[editorId]).toBeDefined();
    expect(state.activeEditors[editorId].filePath).toBe("src/index.ts");
    expect(state.fileToEditorId["src/index.ts"]).toBe(editorId);

    expect(api.post).toHaveBeenCalledWith("/api/ghost-text/register", {
      workspace: ws,
      file_path: "src/index.ts",
      editor_id: editorId,
    });
  });

  it("test_ghost_text_renders_in_editor: creates deltaDecorations with diff styling", () => {
    const chunks: GhostChunk[] = [
      {
        chunk_id: "chk-1",
        type: "insert",
        start_line: 10,
        end_line: 10,
        original_lines: [],
        new_lines: ["const x = 42;"],
        text: "const x = 42;",
      },
      {
        chunk_id: "chk-2",
        type: "replace",
        start_line: 20,
        end_line: 22,
        original_lines: ["oldFunction();"],
        new_lines: ["newFunction();"],
        text: "newFunction();",
      },
      {
        chunk_id: "chk-3",
        type: "delete",
        start_line: 30,
        end_line: 32,
        original_lines: ["deprecatedCode();"],
        new_lines: [],
        text: "",
      },
    ];

    const decorationIds = showGhostText(mockEditor, mockMonaco, chunks);

    expect(mockEditor.deltaDecorations).toHaveBeenCalledTimes(1);
    const calledDecorations = mockEditor.deltaDecorations.mock.calls[0][1];
    expect(calledDecorations).toHaveLength(3);

    // Insert decoration
    expect(calledDecorations[0].options.className).toBe("ghost-text-line-insert");
    expect(calledDecorations[0].options.after.inlineClassName).toBe("ghost-text-inline-insert");

    // Replace decoration
    expect(calledDecorations[1].options.className).toBe("ghost-text-line-replace");
    expect(calledDecorations[1].options.after.inlineClassName).toBe("ghost-text-inline-replace");

    // Delete decoration
    expect(calledDecorations[2].options.className).toBe("ghost-text-line-delete");
    expect(calledDecorations[2].options.after.inlineClassName).toBe("ghost-text-inline-delete");

    expect(decorationIds).toEqual(["dec-1", "dec-2"]);

    // Test clearGhostText cleans up decorations
    clearGhostText(mockEditor);
    expect(mockEditor.deltaDecorations).toHaveBeenCalledWith(["dec-1", "dec-2"], []);
  });

  it("test_tab_key_accepts_changes: calls backend accept and updates model text", async () => {
    const filePath = "src/app.tsx";
    const editorId = "monaco_tab_test";

    await useGhostTextStore.getState().registerEditor("/workspace/demo", filePath, editorId);

    // Setup ghost text with updatedContent
    useGhostTextStore.getState().setGhostChunks(
      filePath,
      [
        {
          chunk_id: "chk_tab",
          type: "insert",
          start_line: 5,
          end_line: 5,
          original_lines: [],
          new_lines: ["console.log('accepted');"],
          text: "console.log('accepted');",
        },
      ],
      "job_tab_1",
      "updated file content after accept"
    );

    expect(useGhostTextStore.getState().hasGhostText(filePath)).toBe(true);

    const success = await acceptGhostText(mockEditor, editorId, filePath);

    expect(success).toBe(true);
    expect(api.post).toHaveBeenCalledWith("/api/ghost-text/accept", {
      editor_id: editorId,
      file_path: filePath,
    });
    expect(mockEditor.setValue).toHaveBeenCalledWith("updated file content after accept");
    expect(useGhostTextStore.getState().hasGhostText(filePath)).toBe(false);
  });

  it("test_esc_key_rejects_changes: calls backend reject and discards ghost decorations", async () => {
    const filePath = "src/app.tsx";
    const editorId = "monaco_tab_test";

    await useGhostTextStore.getState().registerEditor("/workspace/demo", filePath, editorId);

    useGhostTextStore.getState().setGhostChunks(
      filePath,
      [
        {
          chunk_id: "chk_esc",
          type: "replace",
          start_line: 1,
          end_line: 2,
          original_lines: ["bad code"],
          new_lines: ["worse code"],
          text: "worse code",
        },
      ],
      "job_esc_1"
    );

    expect(useGhostTextStore.getState().hasGhostText(filePath)).toBe(true);

    const success = await rejectGhostText(mockEditor, editorId, filePath);

    expect(success).toBe(true);
    expect(api.post).toHaveBeenCalledWith("/api/ghost-text/reject", {
      editor_id: editorId,
      file_path: filePath,
    });
    expect(mockEditor.setValue).not.toHaveBeenCalled();
    expect(useGhostTextStore.getState().hasGhostText(filePath)).toBe(false);
  });

  it("test_editor_unregisters_on_close: cleans up state and aborts active streams", async () => {
    const ws = "/workspace/demo";
    const filePath = "src/utils.ts";
    const editorId = "monaco_closing_editor";

    await useGhostTextStore.getState().registerEditor(ws, filePath, editorId);
    expect(useGhostTextStore.getState().activeEditors[editorId]).toBeDefined();

    await useGhostTextStore.getState().unregisterEditor(editorId);

    const state = useGhostTextStore.getState();
    expect(state.activeEditors[editorId]).toBeUndefined();
    expect(state.fileToEditorId[filePath]).toBeUndefined();

    expect(api.post).toHaveBeenCalledWith("/api/ghost-text/unregister", {
      editor_id: editorId,
    });
  });

  it("test_keybinding_interception: intercepts Tab and Escape when ghost text is active", () => {
    const filePath = "src/main.ts";
    const editorId = "monaco_keybinding_test";

    let keyHandler: ((e: any) => void) | null = null;
    mockEditor.onKeyDown.mockImplementation((handler: any) => {
      keyHandler = handler;
      return { dispose: vi.fn() };
    });

    const cleanup = installGhostTextKeybindings(mockEditor, mockMonaco, filePath, editorId);
    expect(mockEditor.onKeyDown).toHaveBeenCalled();

    // With NO ghost text, key event should not be intercepted
    const mockTabEvent = {
      keyCode: 2, // Tab
      shiftKey: false,
      ctrlKey: false,
      altKey: false,
      metaKey: false,
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    };

    keyHandler!(mockTabEvent);
    expect(mockTabEvent.preventDefault).not.toHaveBeenCalled();

    // Now add ghost text
    useGhostTextStore.getState().setGhostChunks(filePath, [
      {
        chunk_id: "c1",
        type: "insert",
        start_line: 1,
        end_line: 1,
        original_lines: [],
        new_lines: ["test"],
        text: "test",
      },
    ]);

    // Press Tab
    keyHandler!(mockTabEvent);
    expect(mockTabEvent.preventDefault).toHaveBeenCalled();
    expect(mockTabEvent.stopPropagation).toHaveBeenCalled();

    // Press Escape
    const mockEscEvent = {
      keyCode: 9, // Escape
      shiftKey: false,
      ctrlKey: false,
      altKey: false,
      metaKey: false,
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    };
    keyHandler!(mockEscEvent);
    expect(mockEscEvent.preventDefault).toHaveBeenCalled();
    expect(mockEscEvent.stopPropagation).toHaveBeenCalled();

    cleanup();
  });

  it("test_attach_ghost_text_listener_syncs_decorations: updates decorations when store streams changes", () => {
    const filePath = "src/reactive.ts";
    const cleanup = attachGhostTextListener(mockEditor, mockMonaco, filePath);

    // Initial state: no chunks
    expect(mockEditor.deltaDecorations).not.toHaveBeenCalled();

    // Stream incoming chunks into store
    useGhostTextStore.getState().setGhostChunks(filePath, [
      {
        chunk_id: "chk-stream-1",
        type: "replace",
        start_line: 12,
        end_line: 14,
        original_lines: ["old"],
        new_lines: ["new"],
        text: "new",
      },
    ]);

    expect(mockEditor.deltaDecorations).toHaveBeenCalledTimes(1);

    // Clear ghost text in store
    useGhostTextStore.getState().clearGhost(filePath);
    expect(mockEditor.deltaDecorations).toHaveBeenCalledTimes(2);

    cleanup();
  });
});
