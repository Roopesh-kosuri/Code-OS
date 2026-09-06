import React, { useEffect, useState, useRef } from "react";
import ReactDOM from "react-dom";
import { Paperclip, FileText, FileCode, Image as ImageIcon, File as FileGeneric, ChevronDown, ChevronUp } from "lucide-react";
import { useFileUploadStore } from "./fileUploadStore";
import { FileUploadZone } from "./FileUploadZone";
import { FilePreviewModal } from "./FilePreviewModal";

interface RonyChatUploadWrapperProps {
  children: React.ReactNode;
}

export const RonyChatUploadWrapper: React.FC<RonyChatUploadWrapperProps> = ({ children }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  const [isZoneOpen, setIsZoneOpen] = useState(false);
  const { uploadedFiles, openPreview } = useFileUploadStore();

  useEffect(() => {
    // Look for textarea container inside AIChatPanel to mount above it and attach auto-resizing
    let textareaEl: HTMLTextAreaElement | null = null;
    let placeholderObserver: MutationObserver | null = null;

    const updatePlaceholder = () => {
      if (!textareaEl) return;
      if (textareaEl.placeholder !== "Enter your task...") {
        textareaEl.placeholder = "Enter your task...";
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
          portalEl.className = "rony-upload-portal-mount w-full border-b border-white/[0.06]";
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

  const getFileIcon = (mime: string, name: string) => {
    if (name.toLowerCase().endsWith(".pdf") || mime === "application/pdf") {
      return <FileText size={11} className="text-red-400" />;
    }
    if (mime.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(name)) {
      return <ImageIcon size={11} className="text-blue-400" />;
    }
    if (/\.(py|js|ts|tsx|json|html|css|cpp|rs)$/i.test(name)) {
      return <FileCode size={11} className="text-emerald-400" />;
    }
    return <FileGeneric size={11} className="text-on-surface-variant" />;
  };

  const uploadControls = (
    <div className="flex flex-col gap-1 px-3 py-1.5 bg-black/20 text-xs select-none">
      {/* Attached Files Badge Bar / Toggle Drop Zone Header */}
      <div className="flex items-center justify-between gap-2 min-h-[22px]">
        {uploadedFiles.length > 0 ? (
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
        ) : (
          <div className="text-[10px] text-gray-400/80 font-mono flex items-center gap-1.5">
            <Paperclip size={10} className="text-gray-400/70" />
            <span>Drop spec or code to inject</span>
          </div>
        )}

        <button
          type="button"
          data-testid="toggle-upload-zone-btn"
          onClick={() => setIsZoneOpen(!isZoneOpen)}
          className="flex items-center gap-1 text-[10.5px] font-mono text-gray-400 hover:text-gray-200 transition-colors cursor-pointer px-2 py-0.5 rounded-md hover:bg-white/5 border border-transparent hover:border-white/5"
        >
          <span>{isZoneOpen ? "Hide Upload" : "+ Add Files"}</span>
          {isZoneOpen ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
        </button>
      </div>

      {/* Expandable Drag & Drop Zone */}
      {isZoneOpen && (
        <div className="pt-1.5 pb-1 animate-in fade-in slide-in-from-top-1">
          <FileUploadZone compact />
        </div>
      )}
    </div>
  );

  return (
    <div
      ref={containerRef}
      className="rony-chat-wrapper relative w-full h-full flex flex-col min-h-0 overflow-hidden"
      data-testid="rony-chat-wrapper"
    >
      {/* Main Chat Panel Children */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden relative">
        {children}
      </div>

      {/* Render Portal into AIChatPanel right above the textarea */}
      {portalTarget ? (
        ReactDOM.createPortal(uploadControls, portalTarget)
      ) : (
        <div className="border-t border-white/10 bg-surface-container-low shrink-0">
          {uploadControls}
        </div>
      )}

      {/* Global File Preview Modal */}
      <FilePreviewModal />
    </div>
  );
};
