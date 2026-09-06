/**
 * ghostTextManager.ts — Monaco Ghost Text & Inline Diff Decorator
 *
 * Renders Cursor-style streaming diff decorations directly inside Monaco editor:
 * - Grey/cyan italic ghost text for incoming/suggested changes
 * - Line decorations for inserted, modified, or deleted chunks
 * - Intercepts Tab (accept) and Escape (reject) keys
 */

import { useGhostTextStore, type GhostChunk } from "./ghostTextStore";
import { useEditorStore } from "../../stores/editorStore";

// Store decoration IDs per editor instance
const editorDecorationMap = new WeakMap<any, string[]>();

function getEditorDecorations(editor: any): string[] {
  return editorDecorationMap.get(editor) || [];
}

function setEditorDecorations(editor: any, ids: string[]): void {
  editorDecorationMap.set(editor, ids);
}

/**
 * Creates Monaco deltaDecorations for diff chunks.
 */
export function showGhostText(
  editor: any,
  monaco: any,
  diffChunks: GhostChunk[]
): string[] {
  if (!editor || !monaco || !editor.getModel()) return [];

  const model = editor.getModel();
  const lineCount = model.getLineCount();

  const decorations: any[] = [];

  for (const chunk of diffChunks) {
    const startLine = Math.max(1, Math.min(chunk.start_line, lineCount));
    const endLine = Math.max(startLine, Math.min(chunk.end_line, lineCount));

    if (chunk.type === "insert") {
      // Inline ghost text preview for insertion
      const previewText = chunk.new_lines.length > 0
        ? chunk.new_lines.join(" ⏎ ")
        : chunk.text.trim();

      decorations.push({
        range: new monaco.Range(startLine, 1, startLine, 1000),
        options: {
          isWholeLine: true,
          className: "ghost-text-line-insert",
          after: {
            contentText: `   + [AI Suggestion]: ${previewText}`,
            inlineClassName: "ghost-text-inline-insert",
          },
          overviewRuler: {
            color: "#00daf388",
            position: monaco.editor?.OverviewRulerLane?.Right ?? 4,
          },
        },
      });
    } else if (chunk.type === "replace") {
      // Inline ghost text preview for replacement
      const previewText = chunk.new_lines.length > 0
        ? chunk.new_lines.join(" ⏎ ")
        : chunk.text.trim();

      decorations.push({
        range: new monaco.Range(startLine, 1, endLine, 1000),
        options: {
          isWholeLine: true,
          className: "ghost-text-line-replace",
          after: {
            contentText: `   ➔ [AI Modified]: ${previewText}`,
            inlineClassName: "ghost-text-inline-replace",
          },
          overviewRuler: {
            color: "#a855f788",
            position: monaco.editor?.OverviewRulerLane?.Right ?? 4,
          },
        },
      });
    } else if (chunk.type === "delete") {
      decorations.push({
        range: new monaco.Range(startLine, 1, endLine, 1000),
        options: {
          isWholeLine: true,
          className: "ghost-text-line-delete",
          after: {
            contentText: "   - [AI Deletion pending (Tab to accept, Esc to cancel)]",
            inlineClassName: "ghost-text-inline-delete",
          },
          overviewRuler: {
            color: "#ef444488",
            position: monaco.editor?.OverviewRulerLane?.Right ?? 4,
          },
        },
      });
    }
  }

  const oldDecorations = getEditorDecorations(editor);
  const newIds = editor.deltaDecorations(oldDecorations, decorations);
  setEditorDecorations(editor, newIds);
  return newIds;
}

/**
 * Removes all ghost text decorations from the editor.
 */
export function clearGhostText(editor: any): void {
  if (!editor) return;
  const oldDecorations = getEditorDecorations(editor);
  if (oldDecorations.length > 0) {
    editor.deltaDecorations(oldDecorations, []);
    setEditorDecorations(editor, []);
  }
}

/**
 * Accepts staged ghost text changes, updates editor model, and clears decorations.
 */
export async function acceptGhostText(
  editor: any,
  editorId: string,
  filePath: string
): Promise<boolean> {
  const store = useGhostTextStore.getState();
  const streamInfo = store.ghostStreams[filePath] || store.ghostStreams[normalizePath(filePath)];
  const updatedContent = streamInfo?.updatedContent;

  const ok = await store.acceptGhost(filePath);

  clearGhostText(editor);

  // If updated content was staged, update Monaco model directly
  if (editor && editor.getModel() && updatedContent !== undefined) {
    editor.setValue(updatedContent);
    useEditorStore.getState().updateContent(filePath, updatedContent);
  }

  return ok;
}

/**
 * Rejects staged ghost text changes and clears decorations.
 */
export async function rejectGhostText(
  editor: any,
  editorId: string,
  filePath: string
): Promise<boolean> {
  const store = useGhostTextStore.getState();
  const ok = await store.rejectGhost(filePath);
  clearGhostText(editor);
  return ok;
}

function normalizePath(p: string): string {
  if (!p) return "";
  return p.replace(/\\/g, "/").replace(/^\.\//, "");
}

/**
 * Attaches store subscription to sync ghost decorations with the active Monaco editor.
 */
export function attachGhostTextListener(
  editor: any,
  monaco: any,
  filePath: string
): () => void {
  const normPath = normalizePath(filePath);

  // Initial check
  const currentStream = useGhostTextStore.getState().ghostStreams[normPath];
  if (currentStream && currentStream.chunks && currentStream.chunks.length > 0) {
    showGhostText(editor, monaco, currentStream.chunks);
  }

  // Subscribe to changes in ghostStreams
  const unsubscribe = useGhostTextStore.subscribe((state) => {
    const stream = state.ghostStreams[normPath];
    if (stream && stream.chunks && stream.chunks.length > 0) {
      showGhostText(editor, monaco, stream.chunks);
    } else {
      clearGhostText(editor);
    }
  });

  return () => {
    unsubscribe();
    clearGhostText(editor);
  };
}

/**
 * Installs Tab / Esc keybindings on the Monaco editor instance for ghost text accept / reject.
 */
export function installGhostTextKeybindings(
  editor: any,
  monaco: any,
  filePath: string,
  editorId: string
): () => void {
  if (!editor || !monaco) return () => {};

  const normPath = normalizePath(filePath);

  const disposable = editor.onKeyDown((e: any) => {
    const hasGhost = useGhostTextStore.getState().hasGhostText(normPath);
    if (!hasGhost) return;

    // Monaco KeyCode: Tab is 2, Escape is 9
    const isTab = e.keyCode === monaco.KeyCode.Tab || e.browserEvent?.key === "Tab";
    const isEscape = e.keyCode === monaco.KeyCode.Escape || e.browserEvent?.key === "Escape";

    if (isTab && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      e.stopPropagation();
      void acceptGhostText(editor, editorId, normPath);
    } else if (isEscape && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      e.stopPropagation();
      void rejectGhostText(editor, editorId, normPath);
    }
  });

  return () => {
    disposable?.dispose?.();
  };
}
