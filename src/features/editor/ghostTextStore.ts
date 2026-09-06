/**
 * ghostTextStore.ts — Zustand store for Monaco Ghost Text & Inline Diffs
 *
 * Tracks open editor tabs, SSE streaming states, and pending ghost text chunks
 * across active Monaco editor sessions.
 */

import { create } from "zustand";
import { api } from "../../lib/api";

export interface GhostChunk {
  chunk_id: string;
  type: "insert" | "delete" | "replace";
  start_line: number;
  end_line: number;
  original_lines: string[];
  new_lines: string[];
  text: string;
}

export interface GhostStreamInfo {
  editorId: string;
  filePath: string;
  workspace: string;
  jobId: string;
  isStreaming: boolean;
  chunks: GhostChunk[];
  totalChunks: number;
  updatedContent?: string;
}

interface GhostTextState {
  activeEditors: Record<string, { editorId: string; filePath: string; workspace: string }>;
  fileToEditorId: Record<string, string>;
  ghostStreams: Record<string, GhostStreamInfo>;
  abortControllers: Record<string, AbortController>;

  registerEditor: (workspace: string, filePath: string, editorId: string) => Promise<void>;
  unregisterEditor: (editorId: string) => Promise<void>;
  startStream: (workspace: string, filePath: string, editorId: string) => Promise<void>;
  setGhostChunks: (filePath: string, chunks: GhostChunk[], jobId?: string, updatedContent?: string) => void;
  clearGhost: (filePath: string) => void;
  acceptGhost: (filePath: string) => Promise<boolean>;
  rejectGhost: (filePath: string) => Promise<boolean>;
  hasGhostText: (filePath: string) => boolean;
  isStreaming: (filePath: string) => boolean;
}

function normalizePath(p: string): string {
  if (!p) return "";
  return p.replace(/\\/g, "/").replace(/^\.\//, "");
}

export const useGhostTextStore = create<GhostTextState>((set, get) => ({
  activeEditors: {},
  fileToEditorId: {},
  ghostStreams: {},
  abortControllers: {},

  registerEditor: async (workspace: string, filePath: string, editorId: string) => {
    const normPath = normalizePath(filePath);
    set((state) => ({
      activeEditors: {
        ...state.activeEditors,
        [editorId]: { editorId, filePath: normPath, workspace },
      },
      fileToEditorId: {
        ...state.fileToEditorId,
        [normPath]: editorId,
      },
    }));

    try {
      await api.post("/api/ghost-text/register", {
        workspace,
        file_path: normPath,
        editor_id: editorId,
      });
      // Start streaming listener for this editor
      void get().startStream(workspace, normPath, editorId);
    } catch (err) {
      console.warn("[GhostText] registerEditor failed:", err);
    }
  },

  unregisterEditor: async (editorId: string) => {
    const entry = get().activeEditors[editorId];
    const normPath = entry?.filePath;

    // Abort active stream
    if (normPath && get().abortControllers[normPath]) {
      get().abortControllers[normPath].abort();
    }

    set((state) => {
      const nextActive = { ...state.activeEditors };
      delete nextActive[editorId];

      const nextFileToEd = { ...state.fileToEditorId };
      if (normPath) delete nextFileToEd[normPath];

      const nextStreams = { ...state.ghostStreams };
      if (normPath) delete nextStreams[normPath];

      const nextAborts = { ...state.abortControllers };
      if (normPath) delete nextAborts[normPath];

      return {
        activeEditors: nextActive,
        fileToEditorId: nextFileToEd,
        ghostStreams: nextStreams,
        abortControllers: nextAborts,
      };
    });

    try {
      await api.post("/api/ghost-text/unregister", { editor_id: editorId });
    } catch (err) {
      console.warn("[GhostText] unregisterEditor failed:", err);
    }
  },

  startStream: async (workspace: string, filePath: string, editorId: string) => {
    const normPath = normalizePath(filePath);

    // Cancel prior stream if present
    if (get().abortControllers[normPath]) {
      get().abortControllers[normPath].abort();
    }

    const abortController = new AbortController();
    set((state) => ({
      abortControllers: {
        ...state.abortControllers,
        [normPath]: abortController,
      },
    }));

    // First check if pending ghost text already exists on server
    try {
      const pendingRes = await api.get<{ ok: boolean; pending?: any }>(
        `/api/ghost-text/pending?editor_id=${encodeURIComponent(editorId)}&file_path=${encodeURIComponent(normPath)}`
      );
      if (pendingRes?.pending?.chunks && pendingRes.pending.chunks.length > 0) {
        get().setGhostChunks(
          normPath,
          pendingRes.pending.chunks,
          pendingRes.pending.job_id,
          pendingRes.pending.updated
        );
      }
    } catch {
      // Ignore initial poll failure
    }

    // Connect SSE stream
    try {
      await api.streamSSE(
        "/api/ghost-text/stream",
        { job_id: "live", file_path: normPath, editor_id: editorId },
        (_eventType: string, data: any) => {
          if (!data || typeof data !== "object") return;

          if (data.type === "start") {
            set((state) => ({
              ghostStreams: {
                ...state.ghostStreams,
                [normPath]: {
                  editorId,
                  filePath: normPath,
                  workspace,
                  jobId: data.job_id || "",
                  isStreaming: true,
                  chunks: [],
                  totalChunks: data.total_chunks || 0,
                },
              },
            }));
          } else if (data.type === "chunk") {
            set((state) => {
              const current = state.ghostStreams[normPath] || {
                editorId,
                filePath: normPath,
                workspace,
                jobId: data.job_id || "",
                isStreaming: true,
                chunks: [],
                totalChunks: 1,
              };
              const exists = current.chunks.some((c) => c.chunk_id === data.chunk.chunk_id);
              const nextChunks = exists ? current.chunks : [...current.chunks, data.chunk];
              return {
                ghostStreams: {
                  ...state.ghostStreams,
                  [normPath]: {
                    ...current,
                    chunks: nextChunks,
                  },
                },
              };
            });
          } else if (data.type === "done") {
            set((state) => {
              const current = state.ghostStreams[normPath];
              if (!current) return state;
              return {
                ghostStreams: {
                  ...state.ghostStreams,
                  [normPath]: {
                    ...current,
                    isStreaming: false,
                  },
                },
              };
            });
          } else if (data.type === "accepted" || data.type === "rejected" || data.type === "closed") {
            get().clearGhost(normPath);
          }
        },
        abortController.signal
      );
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        console.debug("[GhostText] stream closed for:", normPath);
      }
    }
  },

  setGhostChunks: (filePath: string, chunks: GhostChunk[], jobId = "", updatedContent?: string) => {
    const normPath = normalizePath(filePath);
    const editorId = get().fileToEditorId[normPath] || `editor_${normPath}`;
    const workspace = get().activeEditors[editorId]?.workspace || "";

    set((state) => ({
      ghostStreams: {
        ...state.ghostStreams,
        [normPath]: {
          editorId,
          filePath: normPath,
          workspace,
          jobId,
          isStreaming: false,
          chunks,
          totalChunks: chunks.length,
          updatedContent,
        },
      },
    }));
  },

  clearGhost: (filePath: string) => {
    const normPath = normalizePath(filePath);
    set((state) => {
      const next = { ...state.ghostStreams };
      delete next[normPath];
      return { ghostStreams: next };
    });
  },

  acceptGhost: async (filePath: string) => {
    const normPath = normalizePath(filePath);
    const stream = get().ghostStreams[normPath];
    const editorId = stream?.editorId || get().fileToEditorId[normPath] || "";

    try {
      const res = await api.post<{ ok: boolean; result?: any }>("/api/ghost-text/accept", {
        editor_id: editorId,
        file_path: normPath,
      });
      get().clearGhost(normPath);
      return Boolean(res?.ok);
    } catch (err) {
      console.warn("[GhostText] acceptGhost failed:", err);
      get().clearGhost(normPath);
      return false;
    }
  },

  rejectGhost: async (filePath: string) => {
    const normPath = normalizePath(filePath);
    const stream = get().ghostStreams[normPath];
    const editorId = stream?.editorId || get().fileToEditorId[normPath] || "";

    try {
      const res = await api.post<{ ok: boolean; result?: any }>("/api/ghost-text/reject", {
        editor_id: editorId,
        file_path: normPath,
      });
      get().clearGhost(normPath);
      return Boolean(res?.ok);
    } catch (err) {
      console.warn("[GhostText] rejectGhost failed:", err);
      get().clearGhost(normPath);
      return false;
    }
  },

  hasGhostText: (filePath: string) => {
    const normPath = normalizePath(filePath);
    const stream = get().ghostStreams[normPath];
    return Boolean(stream && stream.chunks && stream.chunks.length > 0);
  },

  isStreaming: (filePath: string) => {
    const normPath = normalizePath(filePath);
    return Boolean(get().ghostStreams[normPath]?.isStreaming);
  },
}));
