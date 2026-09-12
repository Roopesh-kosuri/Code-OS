import React from "react";
import { Sparkles, Check, RotateCcw, Edit3, X, Loader2, AlertCircle } from "lucide-react";
import { useIntelligenceStore } from "../../stores/intelligenceStore";
import { useAIStore } from "../../stores/aiStore";

interface PromptEnhancerBarProps {
  currentPrompt: string;
  activeFile?: string | null;
  workspace?: string | null;
  onApplyEnhanced: (text: string) => void;
}

export const PromptEnhancerBar: React.FC<PromptEnhancerBarProps> = ({
  currentPrompt,
  activeFile,
  workspace,
  onApplyEnhanced,
}) => {
  const streaming = useAIStore((s) => s.streaming);
  const {
    quality,
    originalPrompt,
    enhancedPrompt,
    changes,
    modelUsed,
    showBar,
    showDiff,
    isEnhancing,
    enhancementError,
    enhance,
    accept,
    revert,
    editManually,
    dismiss,
  } = useIntelligenceStore();

  if (streaming) {
    return null;
  }

  if (!showDiff && !isEnhancing && !enhancementError && (!showBar || quality?.quality === "good")) {
    return null;
  }

  // State 3: Error state when enhancement fails, times out, or model is unreachable
  if (enhancementError) {
    return (
      <div
        data-testid="prompt-enhancer-error-card"
        className="mx-2 mb-1.5 px-3 py-2 bg-[#1a1b21]/95 border border-amber-500/40 rounded-lg flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs shadow-md animate-fade-in backdrop-blur-xs text-on-surface"
      >
        <div className="flex items-center gap-2 min-w-0">
          <AlertCircle size={14} className="text-amber-400 shrink-0" />
          <span className="text-on-surface text-xs font-medium truncate" title={enhancementError}>
            {enhancementError}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0 justify-end">
          <button
            type="button"
            data-testid="prompt-retry-button"
            onClick={() => void enhance(currentPrompt || originalPrompt, activeFile, workspace)}
            disabled={isEnhancing}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-surface-variant/80 hover:bg-surface-variant text-on-surface border border-white/10 text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
          >
            {isEnhancing ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                <span>Retrying…</span>
              </>
            ) : (
              <>
                <RotateCcw size={12} />
                <span>Retry</span>
              </>
            )}
          </button>

          <button
            type="button"
            data-testid="prompt-use-original-button"
            onClick={dismiss}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/30 text-xs font-medium transition-colors cursor-pointer"
          >
            <span>Use Original</span>
          </button>

          <button
            type="button"
            data-testid="prompt-dismiss-button"
            onClick={dismiss}
            className="p-1 text-on-surface-variant/70 hover:text-on-surface hover:bg-white/5 rounded transition-colors cursor-pointer"
            title="Dismiss error"
          >
            <X size={13} />
          </button>
        </div>
      </div>
    );
  }

  // State 1: Subtle inline suggestion hint
  if (showBar && !showDiff && quality?.quality !== "good") {
    return (
      <div
        data-testid="prompt-enhancer-hint-bar"
        className="mx-2 mb-1.5 px-3 py-1.5 bg-[#1a1b21]/95 border border-primary/25 rounded-lg flex items-center justify-between gap-2 text-xs shadow-md animate-fade-in backdrop-blur-xs"
      >
        <div className="flex items-center gap-2 text-on-surface truncate min-w-0">
          <Sparkles size={14} className="text-primary shrink-0 animate-pulse" />
          <span className="text-on-surface-variant truncate">
            ✨ This prompt could be clearer. Enhance it?
          </span>
          {quality?.issues && quality.issues.length > 0 && (
            <span className="hidden sm:inline text-[10px] text-on-surface-variant/70 border-l border-white/10 pl-2 truncate">
              {quality.issues[0]}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            data-testid="prompt-enhance-button"
            onClick={() => void enhance(currentPrompt || originalPrompt, activeFile, workspace)}
            disabled={isEnhancing}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-primary/20 hover:bg-primary/30 text-primary border border-primary/30 text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
          >
            {isEnhancing ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                <span>Enhancing…</span>
              </>
            ) : (
              <>
                <Sparkles size={12} />
                <span>Enhance</span>
              </>
            )}
          </button>

          <button
            type="button"
            data-testid="prompt-dismiss-button"
            onClick={dismiss}
            className="p-1 text-on-surface-variant/70 hover:text-on-surface hover:bg-white/5 rounded transition-colors cursor-pointer"
            title="Dismiss enhancement suggestion"
          >
            <X size={13} />
          </button>
        </div>
      </div>
    );
  }

  // State 2: Side-by-side Diff Card
  return (
    <div
      data-testid="prompt-enhancer-diff-card"
      className="mx-2 mb-2 p-3 bg-[#181920] border border-primary/30 rounded-xl shadow-lg animate-fade-in space-y-2.5 text-xs text-on-surface backdrop-blur-md"
    >
      <div className="flex items-center justify-between border-b border-white/10 pb-1.5">
        <div className="flex items-center gap-1.5 font-medium text-primary">
          <Sparkles size={14} />
          <span>Enhanced Prompt Preview</span>
          {modelUsed && (
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-surface-container text-on-surface-variant font-mono">
              {modelUsed}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
        {/* Original */}
        <div className="p-2.5 rounded-lg bg-[#121216] border border-white/10 flex flex-col justify-between">
          <div>
            <div className="font-caption text-[10px] uppercase text-outline-variant mb-1 font-mono tracking-wider">
              Original Prompt
            </div>
            <p className="text-on-surface-variant font-mono text-[11px] whitespace-pre-wrap line-clamp-3">
              {originalPrompt || currentPrompt}
            </p>
          </div>
        </div>

        {/* Enhanced */}
        <div className="p-2.5 rounded-lg bg-primary/5 border border-primary/30 flex flex-col justify-between shadow-xs">
          <div>
            <div className="font-caption text-[10px] uppercase text-primary mb-1 font-mono tracking-wider flex items-center justify-between">
              <span>Enhanced Actionable Prompt</span>
              <span className="text-[9px] text-primary/80 font-normal">Ready for Agent</span>
            </div>
            <p className="text-on-surface font-sans text-xs whitespace-pre-wrap leading-relaxed">
              {enhancedPrompt}
            </p>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          data-testid="prompt-keep-original-button"
          onClick={() => void revert()}
          className="flex items-center gap-1 px-2.5 py-1 rounded bg-surface-variant/60 hover:bg-surface-variant text-on-surface-variant hover:text-on-surface border border-white/10 transition-colors cursor-pointer text-xs"
        >
          <RotateCcw size={12} />
          <span>Keep Original</span>
        </button>

        <button
          type="button"
          data-testid="prompt-edit-button"
          onClick={() => {
            onApplyEnhanced(enhancedPrompt);
            editManually();
          }}
          className="flex items-center gap-1 px-2.5 py-1 rounded bg-surface-variant/60 hover:bg-surface-variant text-on-surface-variant hover:text-on-surface border border-white/10 transition-colors cursor-pointer text-xs"
        >
          <Edit3 size={12} />
          <span>Edit</span>
        </button>

        <button
          type="button"
          data-testid="prompt-use-enhanced-button"
          onClick={() => {
            onApplyEnhanced(enhancedPrompt);
            void accept();
          }}
          className="flex items-center gap-1.5 px-3 py-1 rounded bg-primary text-black hover:bg-primary-container font-semibold transition-colors cursor-pointer text-xs shadow-xs"
        >
          <Check size={13} />
          <span>Use Enhanced</span>
        </button>
      </div>
    </div>
  );
};
