import { useState, useEffect, useRef } from "react";
import {
  RotateCw,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  Server,
  PowerOff,
  Globe,
  Settings2,
} from "lucide-react";

export function isValidPreviewUrl(url: string): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url.trim());
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    const host = parsed.hostname.toLowerCase();
    return host === "localhost" || host === "127.0.0.1";
  } catch {
    return false;
  }
}

interface LivePreviewPanelProps {
  initialUrl?: string;
  isServerRunning?: boolean;
  onRefresh?: () => void;
}

export function LivePreviewPanel({
  initialUrl = "http://127.0.0.1:5173",
  isServerRunning = true,
}: LivePreviewPanelProps) {
  const [urlInput, setUrlInput] = useState(initialUrl);
  const [currentSrc, setCurrentSrc] = useState(initialUrl);
  const [autoReload, setAutoReload] = useState(true);
  const [iframeKey, setIframeKey] = useState(0);
  const [urlError, setUrlError] = useState<string | null>(null);

  const isValid = isValidPreviewUrl(urlInput);

  const handleNavigate = () => {
    if (!isValidPreviewUrl(urlInput)) {
      setUrlError("Security Error: Only http://localhost or http://127.0.0.1 URLs are allowed.");
      return;
    }
    setUrlError(null);
    setCurrentSrc(urlInput.trim());
    setIframeKey((prev) => prev + 1);
  };

  const handleRefresh = () => {
    if (isValidPreviewUrl(currentSrc)) {
      setIframeKey((prev) => prev + 1);
    }
  };

  const handleOpenExternal = () => {
    if (!isValidPreviewUrl(currentSrc)) return;
    if ((window as any).codeOS?.openExternal) {
      void (window as any).codeOS.openExternal(currentSrc);
    } else {
      window.open(currentSrc, "_blank", "noopener,noreferrer");
    }
  };

  // Listen for file save events for auto-reload
  useEffect(() => {
    const handleFileSaved = () => {
      if (autoReload && isServerRunning && isValidPreviewUrl(currentSrc)) {
        setIframeKey((prev) => prev + 1);
      }
    };
    window.addEventListener("code-os:file-saved", handleFileSaved);
    return () => window.removeEventListener("code-os:file-saved", handleFileSaved);
  }, [autoReload, isServerRunning, currentSrc]);

  return (
    <section
      data-testid="live-preview-panel"
      className="flex h-full w-full flex-col bg-[#0f1015] text-on-surface font-ui-label-reg text-ui-label-reg select-none"
    >
      {/* Navigation & Controls Toolbar */}
      <div className="flex items-center justify-between gap-2 border-b border-surface-container-high/40 bg-surface-container/60 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className="flex items-center gap-1.5 text-xs text-primary font-semibold shrink-0">
            <Globe size={14} className="text-primary" />
            <span className="hidden sm:inline">Preview</span>
          </div>

          {/* URL Input Bar */}
          <div className="relative flex-1 min-w-0 flex items-center">
            <input
              data-testid="preview-url-input"
              type="text"
              className={`h-7 w-full rounded-md border px-2.5 text-xs font-mono bg-[#131317] focus:outline-none transition-colors ${
                isValid
                  ? "border-outline-variant/40 text-on-surface focus:border-primary/60"
                  : "border-error/60 text-error focus:border-error"
              }`}
              value={urlInput}
              onChange={(e) => {
                setUrlInput(e.target.value);
                if (isValidPreviewUrl(e.target.value)) setUrlError(null);
                else setUrlError("Security Error: Only http://localhost or http://127.0.0.1 allowed.");
              }}
              onKeyDown={(e) => e.key === "Enter" && handleNavigate()}
              placeholder="http://127.0.0.1:3000"
            />
            <button
              onClick={handleNavigate}
              className="absolute right-1 px-2 py-0.5 text-[10.5px] rounded bg-primary-container text-[#001f24] font-semibold hover:brightness-110 cursor-pointer"
            >
              Go
            </button>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-1.5 text-on-surface-variant shrink-0">
          <button
            data-testid="preview-refresh-btn"
            onClick={handleRefresh}
            className="p-1 rounded hover:bg-white/10 hover:text-on-surface transition-colors cursor-pointer"
            title="Refresh Preview"
          >
            <RotateCw size={13} />
          </button>
          <button
            data-testid="preview-external-btn"
            onClick={handleOpenExternal}
            className="p-1 rounded hover:bg-white/10 hover:text-on-surface transition-colors cursor-pointer"
            title="Open in System Browser"
          >
            <ExternalLink size={13} />
          </button>
          <label className="flex items-center gap-1 text-[10.5px] cursor-pointer ml-1 select-none hover:text-on-surface">
            <input
              type="checkbox"
              checked={autoReload}
              onChange={(e) => setAutoReload(e.target.checked)}
              className="rounded border-outline-variant/50 text-primary focus:ring-primary/40"
            />
            <span>Auto-reload</span>
          </label>
        </div>
      </div>

      {/* Error Security Banner */}
      {urlError && (
        <div
          data-testid="preview-security-error"
          className="mx-3 mt-2 p-2 rounded bg-error/15 border border-error/30 text-error text-xs flex items-center gap-2 shrink-0"
        >
          <ShieldAlert size={14} className="shrink-0 text-error" />
          <span>{urlError}</span>
        </div>
      )}

      {/* Frame Container / Server Stopped State */}
      <div className="relative flex-1 min-h-0 w-full overflow-hidden bg-background">
        {!isServerRunning ? (
          <div
            data-testid="preview-server-stopped"
            className="flex h-full flex-col items-center justify-center p-6 text-center space-y-3"
          >
            <div className="p-3 rounded-full bg-surface-container-high/40 text-on-surface-variant/60">
              <PowerOff size={28} />
            </div>
            <div className="space-y-1 max-w-sm">
              <h3 className="text-sm font-semibold text-on-surface">Server Stopped</h3>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                The background web server is not running. Start the server from the terminal or Run panel to view live output.
              </p>
            </div>
          </div>
        ) : isValid ? (
          <iframe
            key={iframeKey}
            data-testid="preview-iframe"
            src={currentSrc}
            sandbox="allow-scripts allow-forms allow-same-origin"
            className="h-full w-full border-0 bg-white"
            title="CODE OS Live Preview"
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center p-6 text-center space-y-2">
            <ShieldAlert size={28} className="text-error" />
            <span className="text-xs text-error font-medium">Blocked: Untrusted preview address</span>
            <span className="text-[11px] text-on-surface-variant">Only localhost and 127.0.0.1 can be embedded.</span>
          </div>
        )}
      </div>
    </section>
  );
}
