import { useState, useEffect, useRef } from "react";
import { FileText, Clock, X } from "lucide-react";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { FileIcon } from "../../components/ui/FileIcon";

export function RecentFilesModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const recentFiles = useEditorStore((state) => state.recentFiles);
  const openFile = useEditorStore((state) => state.openFile);
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);

  const selectedIndexRef = useRef(selectedIndex);
  selectedIndexRef.current = selectedIndex;

  const recentFilesRef = useRef(recentFiles);
  recentFilesRef.current = recentFiles;

  const isOpenRef = useRef(isOpen);
  isOpenRef.current = isOpen;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Tab / Cmd+Tab / Ctrl+Shift+Tab
      if ((e.ctrlKey || e.metaKey) && (e.key === "Tab" || e.code === "Tab")) {
        e.preventDefault();
        const files = recentFilesRef.current;
        if (files.length === 0) return;

        if (!isOpenRef.current) {
          setIsOpen(true);
          // If moving forward initially, highlight second item (most recent previous file)
          const nextIdx = e.shiftKey ? files.length - 1 : files.length > 1 ? 1 : 0;
          setSelectedIndex(nextIdx);
        } else {
          // Cycle forward or backward
          if (e.shiftKey) {
            setSelectedIndex((prev) => (prev - 1 + files.length) % files.length);
          } else {
            setSelectedIndex((prev) => (prev + 1) % files.length);
          }
        }
      } else if (e.key === "Escape" && isOpenRef.current) {
        e.preventDefault();
        setIsOpen(false);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      // When Ctrl or Cmd is released, jump to selected file!
      if ((e.key === "Control" || e.key === "Meta") && isOpenRef.current) {
        const files = recentFilesRef.current;
        const idx = selectedIndexRef.current;
        setIsOpen(false);
        if (files[idx]) {
          void openFile(files[idx]);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [openFile]);

  if (!isOpen || recentFiles.length === 0) return null;

  return (
    <div
      data-testid="recent-files-modal"
      className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/50 backdrop-blur-xs select-none animate-fade-in"
      onClick={() => setIsOpen(false)}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-outline-variant/30 bg-[#121318] shadow-2xl overflow-hidden animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/20 bg-surface-container/30">
          <div className="flex items-center gap-2 text-xs font-semibold text-on-surface uppercase tracking-wider">
            <Clock size={14} className="text-primary" />
            <span>Recent Files</span>
          </div>
          <span className="text-[10px] text-on-surface-variant/60 font-mono">
            Release Ctrl to Open • Tab to Cycle
          </span>
        </div>

        {/* List of Recent Files */}
        <div className="max-h-80 overflow-y-auto p-1.5 space-y-0.5">
          {recentFiles.map((filePath, idx) => {
            const isSelected = idx === selectedIndex;
            const fileName = filePath.split(/[\\/]/).pop() || filePath;
            const relPath = currentWorkspace
              ? filePath.replace(currentWorkspace.path, "").replace(/^[\\/]/, "")
              : filePath;

            return (
              <div
                key={filePath}
                data-testid={`recent-file-item-${idx}`}
                className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs cursor-pointer transition-colors ${
                  isSelected
                    ? "bg-primary-container text-[#001f24] font-semibold"
                    : "text-on-surface-variant hover:bg-surface-container-high/40 hover:text-on-surface"
                }`}
                onClick={() => {
                  setIsOpen(false);
                  void openFile(filePath);
                }}
                onMouseEnter={() => setSelectedIndex(idx)}
              >
                <div className="flex items-center gap-2.5 truncate flex-1 min-w-0">
                  <FileIcon filename={fileName} size={15} />
                  <span className={isSelected ? "text-[#001f24]" : "text-on-surface font-medium"}>
                    {fileName}
                  </span>
                  <span
                    className={`text-[11px] truncate max-w-[200px] ${
                      isSelected ? "text-[#001f24]/70" : "text-on-surface-variant/50 font-mono"
                    }`}
                  >
                    {relPath}
                  </span>
                </div>
                {idx === 0 && (
                  <span
                    className={`text-[9.5px] px-1.5 py-0.2 rounded font-mono shrink-0 ${
                      isSelected ? "bg-black/15 text-[#001f24]" : "bg-surface-container text-on-surface-variant/60"
                    }`}
                  >
                    Active
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
