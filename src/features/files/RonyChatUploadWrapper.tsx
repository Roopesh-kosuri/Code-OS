import React, { useEffect, useState, useRef } from "react";
import ReactDOM from "react-dom";
import { FileText, FileCode, Image as ImageIcon, File as FileGeneric } from "lucide-react";
import { useFileUploadStore } from "./fileUploadStore";
import { FilePreviewModal } from "./FilePreviewModal";

interface RonyChatUploadWrapperProps {
  children: React.ReactNode;
}

export const RonyChatUploadWrapper: React.FC<RonyChatUploadWrapperProps> = ({ children }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  const { uploadedFiles, openPreview } = useFileUploadStore();

  useEffect(() => {
    // Look for textarea container inside AIChatPanel to mount above it and attach auto-resizing
    let textareaEl: HTMLTextAreaElement | null = null;
    let placeholderObserver: MutationObserver | null = null;

    const updatePlaceholder = () => {
      if (!textareaEl) return;
      if (textareaEl.placeholder !== "Enter your task or drop a file...") {
        textareaEl.placeholder = "Enter your task or drop a file...";
      }
    };

    const updateHeight = () => {
      if (!textareaEl) return;
      const val = textareaEl.value;
      if (!val || val.trim() === "") {
        textareaEl.style.height = "32px";
        textareaEl.style.overflowY = "hidden";
        return;
      }
      textareaEl.style.height = "auto";
      const scrollH = textareaEl.scrollHeight;
      const targetH = Math.min(Math.max(scrollH, 32), 200);
      textareaEl.style.height = `${targetH}px`;
      textareaEl.style.overflowY = scrollH > 200 ? "auto" : "hidden";
    };

    const findTarget = () => {
      if (!containerRef.current) return;
      const textarea = containerRef.current.querySelector("textarea");
      if (textarea && textarea.parentElement) {
        textareaEl = textarea;

        // Apply custom placeholder and initial compact height
        updatePlaceholder();
        updateHeight();

        // Attach listeners for dynamic expansion
        textarea.addEventListener("input", updateHeight);
        textarea.addEventListener("paste", () => setTimeout(updateHeight, 10));
        textarea.addEventListener("keydown", (e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            setTimeout(updateHeight, 50);
          }
        });

        // Observe placeholder changes to keep "Enter your task..." sticky
        if (!placeholderObserver) {
          placeholderObserver = new MutationObserver(updatePlaceholder);
          placeholderObserver.observe(textarea, { attributes: true, attributeFilter: ["placeholder"] });
        }

        let portalEl = textarea.parentElement.querySelector(".rony-upload-portal-mount") as HTMLElement;
        if (!portalEl) {
          portalEl = document.createElement("div");
          portalEl.className = "rony-upload-portal-mount w-full";
          textarea.parentElement.insertBefore(portalEl, textarea);
        }
        setPortalTarget(portalEl);
      }
    };

    findTarget();
    const timer = setTimeout(findTarget, 300);

    // Watch for React clearing the textarea value or resetting placeholder
    const pollInterval = setInterval(() => {
      if (textareaEl) {
        if (!textareaEl.value && textareaEl.style.height !== "32px") {
          updateHeight();
        }
        updatePlaceholder();
      } else {
        findTarget();
      }
    }, 250);

    return () => {
      clearTimeout(timer);
      clearInterval(pollInterval);
      if (placeholderObserver) {
        placeholderObserver.disconnect();
      }
      if (textareaEl) {
        textareaEl.removeEventListener("input", updateHeight);
      }
    };
  }, []);

  const getFileIcon = (mime?: string, name?: string) => {
    const safeName = (name || "").toLowerCase();
    const safeMime = (mime || "").toLowerCase();
    if (safeName.endsWith(".pdf") || safeMime === "application/pdf") {
      return <FileText size={11} className="text-red-400" />;
    }
    if (safeMime.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(safeName)) {
      return <ImageIcon size={11} className="text-blue-400" />;
    }
    if (/\.(py|js|ts|tsx|json|html|css|cpp|rs)$/i.test(safeName)) {
      return <FileCode size={11} className="text-emerald-400" />;
    }
    return <FileGeneric size={11} className="text-on-surface-variant" />;
  };

  const uploadControls = uploadedFiles.length > 0 ? (
    <div className="flex flex-col gap-1 px-3 py-1.5 bg-black/20 text-xs select-none border-b border-white/[0.06]">
      {/* Attached Files Badge Bar */}
      <div className="flex items-center justify-between gap-2 min-h-[22px]">
        <button
          type="button"
          data-testid="attached-files-badge"
          onClick={() => {
            if (uploadedFiles[0]) void openPreview(uploadedFiles[0]);
          }}
          className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-500/30 transition-all cursor-pointer text-[10.5px] font-medium group shadow-xs"
          title="Click to preview attached files"
        >
          <div className="flex items-center -space-x-1">
            {uploadedFiles.slice(0, 3).map((f) => (
              <span key={f.file_id} className="inline-block p-0.5 rounded-full bg-[#141620] border border-white/10">
                {getFileIcon(f.mime_type, f.filename)}
              </span>
            ))}
          </div>
          <span className="font-mono">
            {uploadedFiles.length} {uploadedFiles.length === 1 ? "file" : "files"} attached
          </span>
        </button>
      </div>
    </div>
  ) : null;

  return (
    <div
      ref={containerRef}
      className="rony-chat-wrapper relative w-full h-full flex flex-col min-h-0 overflow-hidden"
      data-testid="rony-chat-wrapper"
    >
      {/* Main Chat Panel Children — full height, no upload bar overhead */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden relative">
        {children}
      </div>

      {/* Upload Controls Portal or Fallback */}
      {uploadControls && (portalTarget ? ReactDOM.createPortal(uploadControls, portalTarget) : uploadControls)}

      {/* File Preview Modal */}
      <FilePreviewModal />
    </div>
  );
};
