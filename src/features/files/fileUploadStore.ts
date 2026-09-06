import { create } from "zustand";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";

export interface UploadedFile {
  file_id: string;
  filename: string;
  mime_type: string;
  size: number;
  content_preview: string;
  content?: string;
  metadata?: {
    filename: string;
    size_bytes: number;
    mime_type: string;
    page_count?: number | null;
    word_count: number;
    extracted_at: string;
    stored_path?: string;
    relative_path?: string;
  };
  error?: string | null;
}

export interface FileUploadState {
  uploadedFiles: UploadedFile[];
  isUploading: boolean;
  uploadProgress: Record<string, number>;
  activePreviewFile: UploadedFile | null;
  isPreviewModalOpen: boolean;

  uploadFile: (file: File, workspace?: string) => Promise<UploadedFile>;
  removeFile: (file_id: string, workspace?: string) => Promise<void>;
  clearFiles: () => void;
  fetchFiles: (workspace: string) => Promise<void>;
  openPreview: (file: UploadedFile) => Promise<void>;
  closePreview: () => void;
}

export const useFileUploadStore = create<FileUploadState>((set, get) => ({
  uploadedFiles: [],
  isUploading: false,
  uploadProgress: {},
  activePreviewFile: null,
  isPreviewModalOpen: false,

  uploadFile: async (file: File, workspace?: string) => {
    const ws = workspace || useWorkspaceStore.getState().currentWorkspace?.path || "";
    set((state) => ({
      isUploading: true,
      uploadProgress: { ...state.uploadProgress, [file.name]: 20 },
    }));

    const formData = new FormData();
    formData.append("file", file);
    formData.append("workspace", ws);

    try {
      // Simulate progress progression for micro-animations
      set((state) => ({
        uploadProgress: { ...state.uploadProgress, [file.name]: 65 },
      }));

      const response = await api.post<{
        file_id: string;
        filename: string;
        content_preview: string;
        metadata: any;
        error?: string | null;
      }>("/api/files/upload", formData);

      const newUploaded: UploadedFile = {
        file_id: response.file_id,
        filename: response.filename,
        mime_type: response.metadata?.mime_type || file.type || "application/octet-stream",
        size: response.metadata?.size_bytes || file.size,
        content_preview: response.content_preview || "",
        metadata: response.metadata,
        error: response.error,
      };

      set((state) => ({
        uploadedFiles: [
          ...state.uploadedFiles.filter((f) => f.file_id !== newUploaded.file_id),
          newUploaded,
        ],
        uploadProgress: { ...state.uploadProgress, [file.name]: 100 },
      }));

      // Cleanup progress entry after brief completion
      setTimeout(() => {
        set((state) => {
          const { [file.name]: _, ...rest } = state.uploadProgress;
          return { uploadProgress: rest };
        });
      }, 500);

      return newUploaded;
    } catch (err: any) {
      console.error("Failed to upload file:", err);
      set((state) => {
        const { [file.name]: _, ...rest } = state.uploadProgress;
        return { uploadProgress: rest };
      });
      throw err;
    } finally {
      set({ isUploading: false });
    }
  },

  removeFile: async (file_id: string, workspace?: string) => {
    const ws = workspace || useWorkspaceStore.getState().currentWorkspace?.path || "";
    // Optimistically remove from state
    set((state) => ({
      uploadedFiles: state.uploadedFiles.filter((f) => f.file_id !== file_id),
      activePreviewFile:
        state.activePreviewFile?.file_id === file_id ? null : state.activePreviewFile,
      isPreviewModalOpen:
        state.activePreviewFile?.file_id === file_id ? false : state.isPreviewModalOpen,
    }));

    try {
      await api.delete(`/api/files/${file_id}`, { workspace: ws });
    } catch (err) {
      console.warn("Could not delete file on server:", err);
    }
  },

  clearFiles: () => {
    set({
      uploadedFiles: [],
      uploadProgress: {},
      activePreviewFile: null,
      isPreviewModalOpen: false,
    });
  },

  fetchFiles: async (workspace: string) => {
    if (!workspace) return;
    try {
      const list = await api.get<any[]>("/api/files/list", { workspace });
      if (Array.isArray(list)) {
        const mapped: UploadedFile[] = list.map((item) => ({
          file_id: item.file_id,
          filename: item.filename,
          mime_type: item.metadata?.mime_type || "text/plain",
          size: item.metadata?.size_bytes || 0,
          content_preview: item.content_preview || "",
          metadata: item.metadata,
          error: item.error,
        }));
        set({ uploadedFiles: mapped });
      }
    } catch (err) {
      console.debug("Failed to fetch uploaded files list:", err);
    }
  },

  openPreview: async (file: UploadedFile) => {
    // If full content is not yet loaded, fetch from GET /api/files/{file_id}
    let targetFile = file;
    if (!file.content) {
      try {
        const ws = useWorkspaceStore.getState().currentWorkspace?.path || "";
        const details = await api.get<{
          file_id: string;
          filename: string;
          content: string;
          metadata: any;
          error?: string | null;
        }>(`/api/files/${file.file_id}`, { workspace: ws });
        if (details) {
          targetFile = {
            ...file,
            content: details.content || file.content_preview,
            metadata: details.metadata || file.metadata,
          };
        }
      } catch (err) {
        console.warn("Failed to fetch file full content:", err);
      }
    }

    set({
      activePreviewFile: targetFile,
      isPreviewModalOpen: true,
    });
  },

  closePreview: () => {
    set({
      activePreviewFile: null,
      isPreviewModalOpen: false,
    });
  },
}));

if (typeof window !== "undefined") {
  (window as any).__fileUploadStore = useFileUploadStore;
}
