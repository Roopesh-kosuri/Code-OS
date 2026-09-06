import React, { useState, useMemo } from "react";
import {
  X,
  Copy,
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  FileCode,
  Image as ImageIcon,
  File as FileGeneric,
  Layers,
  Sparkles,
} from "lucide-react";
import { useFileUploadStore, type UploadedFile } from "./fileUploadStore";

export const FilePreviewModal: React.FC = () => {
  const { activePreviewFile, isPreviewModalOpen, closePreview } = useFileUploadStore();
  const [copied, setCopied] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);

  const file = activePreviewFile;
  const isPdf = Boolean(
    file &&
      (file.filename.toLowerCase().endsWith(".pdf") ||
        file.mime_type === "application/pdf")
  );
  const isImage = Boolean(
    file &&
      (file.mime_type.startsWith("image/") ||
        /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(file.filename))
  );
  const isCode = Boolean(
    file &&
      /\.(py|js|ts|tsx|jsx|json|html|css|scss|java|c|cpp|go|rs|rb|php|md|sh|sql)$/i.test(
        file.filename
      )
  );

  // Extract pages if PDF has multi-page dividers
  const pdfPages = useMemo(() => {
    if (!file || !isPdf || !file.content) return [file?.content || ""];
    if (file.content.includes("--- Page ")) {
      const parts = file.content.split(/--- Page \d+ ---\n/);
      return parts.filter((p) => p.trim().length > 0);
    }
    return [file.content];
  }, [file, isPdf]);

  const totalPages = isPdf
    ? Math.max(file?.metadata?.page_count || 1, pdfPages.length)
    : 1;

  const currentContent = useMemo(() => {
    if (!file) return "";
    if (isPdf && pdfPages.length > 0) {
      const pageIndex = Math.min(Math.max(0, currentPage - 1), pdfPages.length - 1);
      return pdfPages[pageIndex] || "";
    }
    return file.content || file.content_preview || "No content extracted.";
  }, [file, isPdf, pdfPages, currentPage]);

  const formattedSize = useMemo(() => {
    const bytes = file?.size || 0;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }, [file?.size]);

  const handleCopy = () => {
    const textToCopy = isPdf
      ? pdfPages.join("\n\n")
      : file?.content || file?.content_preview || "";
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (!isPreviewModalOpen || !file) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 sm:p-6 animate-fade-in"
      data-testid="file-preview-modal"
      onClick={(e) => {
        if (e.target === e.currentTarget) closePreview();
      }}
    >
      <div className="bg-surface-container-low border border-white/15 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden animate-scale-in">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-surface-container-lowest/80">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-primary-container/20 border border-primary-container/30 flex items-center justify-center shrink-0 text-primary-container">
              {isPdf ? (
                <FileText size={18} />
              ) : isImage ? (
                <ImageIcon size={18} />
              ) : isCode ? (
                <FileCode size={18} />
              ) : (
                <FileGeneric size={18} />
              )}
            </div>
            <div className="flex flex-col min-w-0">
              <div className="flex items-center gap-2 truncate">
                <span className="font-bold text-sm text-on-surface truncate" title={file.filename}>
                  {file.filename}
                </span>
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-on-surface-variant">
                  {file.mime_type.split("/")[1] || "file"}
                </span>
              </div>
              <div className="flex items-center gap-3 text-xs text-on-surface-variant font-mono mt-0.5">
                <span>{formattedSize}</span>
                {file.metadata?.word_count ? (
                  <span>{file.metadata.word_count.toLocaleString()} words</span>
                ) : null}
                {isPdf && totalPages > 1 ? (
                  <span>{totalPages} pages</span>
                ) : null}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Copy Button */}
            <button
              onClick={handleCopy}
              data-testid="copy-content-btn"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-surface-container hover:bg-surface-variant text-on-surface border border-white/10 transition-colors cursor-pointer"
              title="Copy extracted content to clipboard"
            >
              {copied ? (
                <>
                  <Check size={13} className="text-emerald-400" />
                  <span className="text-emerald-400">Copied!</span>
                </>
              ) : (
                <>
                  <Copy size={13} />
                  <span>Copy</span>
                </>
              )}
            </button>

            {/* Close Button */}
            <button
              onClick={closePreview}
              data-testid="close-preview-btn"
              className="p-1.5 rounded-lg hover:bg-surface-variant text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
              title="Close Preview"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 font-mono text-xs text-on-surface bg-[#0f1117] min-h-[350px]">
          {isImage && (
            <div className="flex flex-col items-center justify-center p-4 gap-4">
              <div className="max-w-full max-h-[60vh] rounded-lg overflow-hidden border border-white/10 shadow-lg bg-surface-container-lowest p-2">
                <img
                  src={
                    file.metadata?.stored_path
                      ? `/api/files/download?path=${encodeURIComponent(file.metadata.stored_path)}`
                      : ""
                  }
                  alt={file.filename}
                  className="max-h-[50vh] object-contain rounded"
                  onError={(e) => {
                    // Fallback to placeholder if backend streaming not active
                    (e.target as HTMLElement).style.display = "none";
                  }}
                />
              </div>
              {file.content && (
                <div className="w-full bg-surface-container-low p-4 rounded-xl border border-white/10 flex flex-col gap-2">
                  <span className="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider">
                    OCR Extracted Text
                  </span>
                  <p className="text-on-surface whitespace-pre-wrap leading-relaxed">
                    {file.content}
                  </p>
                </div>
              )}
            </div>
          )}

          {!isImage && (
            <div className="flex flex-col gap-2">
              {isPdf && totalPages > 1 && (
                <div className="flex items-center justify-between pb-3 border-b border-white/10 text-xs text-on-surface-variant">
                  <div className="flex items-center gap-1.5">
                    <Layers size={13} className="text-primary-container" />
                    <span>
                      Page {currentPage} of {totalPages}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                      disabled={currentPage <= 1}
                      className="p-1 rounded bg-surface-container hover:bg-surface-variant disabled:opacity-30 cursor-pointer"
                      title="Previous Page"
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <button
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                      disabled={currentPage >= totalPages}
                      className="p-1 rounded bg-surface-container hover:bg-surface-variant disabled:opacity-30 cursor-pointer"
                      title="Next Page"
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              )}

              {/* Text / Code Render with line numbers */}
              <div className="flex gap-4">
                <div className="select-none text-right text-on-surface-variant/40 pr-2 border-r border-white/5 font-mono text-[11px] leading-6 shrink-0">
                  {currentContent.split("\n").map((_, i) => (
                    <div key={i}>{i + 1}</div>
                  ))}
                </div>
                <div className="flex-1 overflow-x-auto whitespace-pre-wrap leading-6 text-on-surface font-mono text-[11.5px]">
                  {currentContent}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
