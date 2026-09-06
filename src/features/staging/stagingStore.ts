/**
 * stagingStore.ts — Zustand store for Smart Staging / PR Review.
 *
 * Manages:
 * - Staged files and line metrics
 * - Currently active Monaco diff
 * - Checkbox selections for bulk actions
 * - Approval and rejection at both file and chunk levels
 * - Disk application and completion events
 */

import { create } from "zustand";
import { api } from "../../lib/api";

export interface DiffChunk {
  index: number;
  type: "insert" | "delete" | "context";
  content: string;
  approved?: boolean | null;
  start_line?: number;
  end_line?: number;
  original_lines?: string[];
  new_lines?: string[];
}

export interface StagedFile {
  path: string;
  status: "added" | "modified" | "deleted";
  lines_added: number;
  lines_removed: number;
  approved: boolean;
  chunks: DiffChunk[];
}

export interface DiffLine {
  line_number: number;
  orig_line_number: number | null;
  new_line_number: number | null;
  type: "insert" | "delete" | "context";
  content: string;
  chunk_index: number;
}

export interface MonacoDiffData {
  job_id: string;
  path: string;
  file_path?: string;
  status: string;
  lines_added: number;
  lines_removed: number;
  approved: boolean;
  original_content: string;
  updated_content: string;
  diff_text: string;
  lines: DiffLine[];
  chunks: DiffChunk[];
}

export interface StagingSummaryResponse {
  job_id: string;
  files: StagedFile[];
  total_files: number;
  total_lines_added: number;
  total_lines_removed: number;
  approved_count: number;
  rejected_count: number;
  pending_count: number;
}

export interface StagingState {
  files: StagedFile[];
  selectedFile: string | null;
  activeDiff: MonacoDiffData | null;
  selectedFilePaths: string[];
  jobId: string | null;
  isOpen: boolean;
  isLoading: boolean;
  isApplying: boolean;
  error: string | null;

  // Getters
  approvedCount: () => number;
  rejectedCount: () => number;
  totalCount: () => number;
  pendingCount: () => number;
  totalLinesAdded: () => number;
  totalLinesRemoved: () => number;

  // Actions
  setOpen: (open: boolean) => void;
  setJobId: (jobId: string | null) => void;
  openReview: (jobId: string) => Promise<void>;
  closeReview: () => void;
  setSelectedFile: (path: string | null) => void;
  toggleFileSelection: (path: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
  fetchSummary: (jobId: string) => Promise<void>;
  fetchDiff: (jobId: string, filePath: string) => Promise<MonacoDiffData | null>;
  approveFiles: (jobId: string, filePaths: string[]) => Promise<void>;
  rejectFiles: (jobId: string, filePaths: string[]) => Promise<void>;
  approveChunk: (jobId: string, filePath: string, chunkIndex: number) => Promise<void>;
  rejectChunk: (jobId: string, filePath: string, chunkIndex: number) => Promise<void>;
  applyChanges: (jobId: string) => Promise<{ success: boolean; applied_files?: string[]; rejected_files?: string[] }>;
  approveSelected: () => Promise<void>;
  rejectSelected: () => Promise<void>;
  approveAll: () => Promise<void>;
  rejectAll: () => Promise<void>;
}

export const useStagingStore = create<StagingState>((set, get) => ({
  files: [],
  selectedFile: null,
  activeDiff: null,
  selectedFilePaths: [],
  jobId: null,
  isOpen: false,
  isLoading: false,
  isApplying: false,
  error: null,

  approvedCount: () => {
    return get().files.filter((f) => f.approved).length;
  },

  rejectedCount: () => {
    return get().files.filter((f) => {
      const diffChunks = f.chunks.filter((c) => c.type === "insert" || c.type === "delete");
      return diffChunks.length > 0 && diffChunks.every((c) => c.approved === false) && !f.approved;
    }).length;
  },

  totalCount: () => {
    return get().files.length;
  },

  pendingCount: () => {
    const { files } = get();
    return files.filter((f) => {
      if (f.approved) return false;
      const diffChunks = f.chunks.filter((c) => c.type === "insert" || c.type === "delete");
      const isRejected = diffChunks.length > 0 && diffChunks.every((c) => c.approved === false);
      return !isRejected;
    }).length;
  },

  totalLinesAdded: () => {
    return get().files.reduce((acc, f) => acc + (f.lines_added || 0), 0);
  },

  totalLinesRemoved: () => {
    return get().files.reduce((acc, f) => acc + (f.lines_removed || 0), 0);
  },

  setOpen: (open: boolean) => set({ isOpen: open }),

  setJobId: (jobId: string | null) => set({ jobId }),

  openReview: async (jobId: string) => {
    set({ isOpen: true, jobId, isLoading: true, error: null });
    await get().fetchSummary(jobId);
    set({ isLoading: false });
  },

  closeReview: () => {
    set({ isOpen: false });
  },

  setSelectedFile: (path: string | null) => {
    set({ selectedFile: path });
    const { jobId } = get();
    if (path && jobId) {
      void get().fetchDiff(jobId, path);
    } else {
      set({ activeDiff: null });
    }
  },

  toggleFileSelection: (path: string) => {
    set((state) => {
      const exists = state.selectedFilePaths.includes(path);
      const next = exists
        ? state.selectedFilePaths.filter((p) => p !== path)
        : [...state.selectedFilePaths, path];
      return { selectedFilePaths: next };
    });
  },

  selectAll: () => {
    set((state) => ({
      selectedFilePaths: state.files.map((f) => f.path),
    }));
  },

  deselectAll: () => {
    set({ selectedFilePaths: [] });
  },

  fetchSummary: async (jobId: string) => {
    try {
      set({ isLoading: true, error: null });
      const summary = await api.get<StagingSummaryResponse>("/api/staging/summary", {
        job_id: jobId,
      });

      const currentSelected = get().selectedFile;
      const nextSelected =
        currentSelected && summary.files.some((f) => f.path === currentSelected)
          ? currentSelected
          : summary.files.length > 0
          ? summary.files[0].path
          : null;

      set({
        files: summary.files,
        jobId,
        selectedFile: nextSelected,
        selectedFilePaths: summary.files.map((f) => f.path),
        isLoading: false,
      });

      if (nextSelected) {
        void get().fetchDiff(jobId, nextSelected);
      }
    } catch (err: any) {
      console.error("[stagingStore] Failed to fetch summary:", err);
      set({ error: err.message || "Failed to load staging summary", isLoading: false });
    }
  },

  fetchDiff: async (jobId: string, filePath: string) => {
    try {
      const diffData = await api.get<MonacoDiffData>(
        `/api/staging/diff/${encodeURIComponent(jobId)}/${filePath}`
      );
      set({ activeDiff: diffData, selectedFile: filePath });
      return diffData;
    } catch (err: any) {
      console.error(`[stagingStore] Failed to fetch diff for ${filePath}:`, err);
      return null;
    }
  },

  approveFiles: async (jobId: string, filePaths: string[]) => {
    try {
      await api.post("/api/staging/approve-files", {
        job_id: jobId,
        file_paths: filePaths,
      });

      // Optimistically update files in state
      set((state) => ({
        files: state.files.map((f) => {
          if (filePaths.includes(f.path)) {
            return {
              ...f,
              approved: true,
              chunks: f.chunks.map((c) =>
                c.type === "insert" || c.type === "delete" ? { ...c, approved: true } : c
              ),
            };
          }
          return f;
        }),
      }));

      // Refresh diff if active file was approved
      const active = get().selectedFile;
      if (active && filePaths.includes(active)) {
        void get().fetchDiff(jobId, active);
      }
    } catch (err: any) {
      console.error("[stagingStore] Failed to approve files:", err);
    }
  },

  rejectFiles: async (jobId: string, filePaths: string[]) => {
    try {
      await api.post("/api/staging/reject-files", {
        job_id: jobId,
        file_paths: filePaths,
      });

      // Optimistically update files in state
      set((state) => ({
        files: state.files.map((f) => {
          if (filePaths.includes(f.path)) {
            return {
              ...f,
              approved: false,
              chunks: f.chunks.map((c) =>
                c.type === "insert" || c.type === "delete" ? { ...c, approved: false } : c
              ),
            };
          }
          return f;
        }),
      }));

      const active = get().selectedFile;
      if (active && filePaths.includes(active)) {
        void get().fetchDiff(jobId, active);
      }
    } catch (err: any) {
      console.error("[stagingStore] Failed to reject files:", err);
    }
  },

  approveChunk: async (jobId: string, filePath: string, chunkIndex: number) => {
    try {
      await api.post("/api/staging/approve-chunk", {
        job_id: jobId,
        file_path: filePath,
        chunk_index: chunkIndex,
      });

      // Optimistically update chunk in activeDiff and files
      set((state) => {
        const nextFiles = state.files.map((f) => {
          if (f.path === filePath) {
            const nextChunks = f.chunks.map((c) =>
              c.index === chunkIndex ? { ...c, approved: true } : c
            );
            const diffChunks = nextChunks.filter((c) => c.type === "insert" || c.type === "delete");
            const allApproved = diffChunks.length > 0 && diffChunks.every((c) => c.approved === true);
            return { ...f, chunks: nextChunks, approved: allApproved };
          }
          return f;
        });

        let nextDiff = state.activeDiff;
        if (nextDiff && (nextDiff.path === filePath || nextDiff.file_path === filePath)) {
          const nextChunks = nextDiff.chunks.map((c) =>
            c.index === chunkIndex ? { ...c, approved: true } : c
          );
          nextDiff = { ...nextDiff, chunks: nextChunks };
        }

        return { files: nextFiles, activeDiff: nextDiff };
      });
    } catch (err: any) {
      console.error("[stagingStore] Failed to approve chunk:", err);
    }
  },

  rejectChunk: async (jobId: string, filePath: string, chunkIndex: number) => {
    try {
      await api.post("/api/staging/reject-chunk", {
        job_id: jobId,
        file_path: filePath,
        chunk_index: chunkIndex,
      });

      // Optimistically update chunk in activeDiff and files
      set((state) => {
        const nextFiles = state.files.map((f) => {
          if (f.path === filePath) {
            const nextChunks = f.chunks.map((c) =>
              c.index === chunkIndex ? { ...c, approved: false } : c
            );
            return { ...f, chunks: nextChunks, approved: false };
          }
          return f;
        });

        let nextDiff = state.activeDiff;
        if (nextDiff && (nextDiff.path === filePath || nextDiff.file_path === filePath)) {
          const nextChunks = nextDiff.chunks.map((c) =>
            c.index === chunkIndex ? { ...c, approved: false } : c
          );
          nextDiff = { ...nextDiff, chunks: nextChunks, approved: false };
        }

        return { files: nextFiles, activeDiff: nextDiff };
      });
    } catch (err: any) {
      console.error("[stagingStore] Failed to reject chunk:", err);
    }
  },

  applyChanges: async (jobId: string) => {
    set({ isApplying: true, error: null });
    try {
      const res = await api.post<{ success: boolean; applied_files?: string[]; rejected_files?: string[] }>(
        "/api/staging/apply",
        { job_id: jobId }
      );

      // Emit event for editor, explorer, and agent console
      window.dispatchEvent(
        new CustomEvent("code-os:staging-applied", {
          detail: {
            jobId,
            appliedFiles: res.applied_files || [],
            rejectedFiles: res.rejected_files || [],
          },
        })
      );

      // Close review panel and reset
      set({ isOpen: false, isApplying: false });
      return res;
    } catch (err: any) {
      console.error("[stagingStore] Failed to apply changes:", err);
      set({ isApplying: false, error: err.message || "Failed to apply changes" });
      return { success: false };
    }
  },

  approveSelected: async () => {
    const { jobId, selectedFilePaths } = get();
    if (jobId && selectedFilePaths.length > 0) {
      await get().approveFiles(jobId, selectedFilePaths);
    }
  },

  rejectSelected: async () => {
    const { jobId, selectedFilePaths } = get();
    if (jobId && selectedFilePaths.length > 0) {
      await get().rejectFiles(jobId, selectedFilePaths);
    }
  },

  approveAll: async () => {
    const { jobId, files } = get();
    if (jobId && files.length > 0) {
      await get().approveFiles(jobId, files.map((f) => f.path));
    }
  },

  rejectAll: async () => {
    const { jobId, files } = get();
    if (jobId && files.length > 0) {
      await get().rejectFiles(jobId, files.map((f) => f.path));
    }
  },
}));
