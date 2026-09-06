import React, { useState, useRef } from "react";
import {
  UploadCloud,
  FileText,
  FileCode,
  Image as ImageIcon,
  File as FileGeneric,
  X,
  AlertCircle,
  Eye,
  Loader2,
} from "lucide-react";
import { useFileUploadStore, type UploadedFile } from "./fileUploadStore";

interface FileUploadZoneProps {
  compact?: boolean;
  maxFiles?: number;
  workspace?: string;
  onFilesChanged?: (files: UploadedFile[]) => void;
}

const ACCEPT_STRING =
  ".pdf,.png,.jpg,.jpeg,.gif,.webp,.bmp,.py,.js,.ts,.tsx,.jsx,.java,.c,.cpp,.go,.rs,.rb,.php,.html,.css,.scss,.md,.json,.yaml,.yml,.xml,.csv,.tsv,.txt,.log";

export const FileUploadZone: React.FC<FileUploadZoneProps> = ({
  compact = false,
  maxFiles = 10,
  workspace,
  onFilesChanged,
}) => {
  const {
    uploadedFiles,
    isUploading,
    uploadProgress,
    uploadFile,
    removeFile,
    openPreview,
  } = useFileUploadStore();

  const [isDragging, setIsDragging] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = async (files: FileList | File[]) => {
    setErrorMsg(null);
    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;

    if (uploadedFiles.length + fileArray.length > maxFiles) {
      setErrorMsg(`Maximum of ${maxFiles} files per message reached.`);
      return;
    }

    for (const file of fileArray) {
      try {
        await uploadFile(file, workspace);
      } catch (err: any) {
        setErrorMsg(`Failed to upload ${file.name}: ${err?.message || "Error"}`);
      }
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      void handleFiles(e.dataTransfer.files);
    }
  };

  const formatSize = (bytes: number) => {
    if (!bytes) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getFileIcon = (file: UploadedFile) => {
    const isPdf =
      file.filename.toLowerCase().endsWith(".pdf") ||
      file.mime_type === "application/pdf";
    const isImage =
      file.mime_type.startsWith("image/") ||
      /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.filename);
    const isCode =
      /\.(py|js|ts|tsx|jsx|json|html|css|java|c|cpp|go|rs|rb|php|md|sh|sql)$/i.test(
        file.filename
      );

    if (isPdf) return <FileText size={14} className="text-red-400 shrink-0" />;
    if (isImage) return <ImageIcon size={14} className="text-blue-400 shrink-0" />;
    if (isCode) return <FileCode size={14} className="text-emerald-400 shrink-0" />;
    return <FileGeneric size={14} className="text-on-surface-variant shrink-0" />;
  };

  return (
    <div className="flex flex-col gap-2.5 w-full" data-testid="file-upload-zone">
      {/* Hidden native input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPT_STRING}
        onChange={(e) => {
          if (e.target.files) void handleFiles(e.target.files);
          e.target.value = "";
        }}
        className="hidden"
        data-testid="file-input-hidden"
      />

      {/* Drag & Drop Target Zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        data-testid="drag-drop-dropzone"
        className={`border-2 border-dashed rounded-xl transition-all duration-200 cursor-pointer flex items-center justify-center gap-3 select-none ${
          compact ? "p-2.5 text-xs" : "p-4 text-xs"
        } ${
          isDragging
            ? "border-primary bg-primary/10 scale-[1.01] shadow-lg shadow-primary/20"
            : "border-white/15 hover:border-primary/50 bg-surface-container-lowest/70 hover:bg-surface-container-lowest"
        }`}
      >
        <div className="w-7 h-7 rounded-lg bg-surface-container flex items-center justify-center shrink-0 text-primary-container">
          <UploadCloud size={16} />
        </div>
        <div className="flex flex-col min-w-0">
          <div className="flex items-center gap-1.5 font-medium text-on-surface">
            <span>Drop files here or click to browse</span>
            <span className="text-[10px] text-on-surface-variant/70 font-mono">
              (PDF, code, images, data — max {maxFiles})
            </span>
          </div>
        </div>
      </div>

      {/* Error notification */}
      {errorMsg && (
        <div className="flex items-center gap-2 p-2 rounded-lg bg-error/10 border border-error/30 text-error text-[11px]">
          <AlertCircle size={13} className="shrink-0" />
          <span className="flex-1 truncate">{errorMsg}</span>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            className="hover:opacity-75"
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* Uploading Progress Indicator */}
      {Object.entries(uploadProgress).map(([fname, pct]) => (
        <div
          key={fname}
          className="flex flex-col gap-1 p-2 rounded-lg bg-surface-container border border-white/5 text-[11px]"
        >
          <div className="flex items-center justify-between text-on-surface font-mono">
            <span className="truncate max-w-xs">{fname}</span>
            <span className="text-primary-container">{pct}%</span>
          </div>
          <div className="w-full h-1 bg-surface-container-high rounded-full overflow-hidden">
            <div
              className="h-full bg-primary-container transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      ))}

      {/* Uploaded Files Chips / Cards List */}
      {uploadedFiles.length > 0 && (
        <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto pr-1">
          {uploadedFiles.map((file) => (
            <div
              key={file.file_id}
              data-testid={`uploaded-file-item-${file.file_id}`}
              className="flex items-center justify-between gap-3 p-2 rounded-lg bg-surface-container-low border border-white/10 hover:border-primary/40 transition-colors group text-xs"
            >
              <div
                className="flex items-center gap-2 min-w-0 flex-1 cursor-pointer"
                onClick={() => void openPreview(file)}
                title="Click to preview file"
              >
                {getFileIcon(file)}
                <div className="flex flex-col min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-on-surface truncate text-[11.5px]">
                      {file.filename}
                    </span>
                    <span className="text-[10px] text-on-surface-variant font-mono">
                      ({formatSize(file.size)})
                    </span>
                  </div>
                  {file.content_preview && (
                    <span
                      data-testid={`file-preview-snippet-${file.file_id}`}
                      className="text-[10.5px] text-on-surface-variant/80 truncate font-mono"
                    >
                      {file.content_preview.slice(0, 100)}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  onClick={() => void openPreview(file)}
                  data-testid={`preview-btn-${file.file_id}`}
                  className="p-1 rounded hover:bg-surface-variant text-on-surface-variant hover:text-primary transition-colors cursor-pointer"
                  title="Preview"
                >
                  <Eye size={13} />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void removeFile(file.file_id, workspace);
                  }}
                  data-testid={`remove-file-btn-${file.file_id}`}
                  className="p-1 rounded hover:bg-error/20 text-on-surface-variant hover:text-error transition-colors cursor-pointer"
                  title="Remove file"
                >
                  <X size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
