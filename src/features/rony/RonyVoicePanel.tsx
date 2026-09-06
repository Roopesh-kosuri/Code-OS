/**
 * RonyVoicePanel.tsx — Full system-wide JARVIS voice assistant panel with laptop control.
 */

import React, { useState, useEffect } from "react";
import {
  Mic,
  MicOff,
  AlertOctagon,
  ShieldAlert,
  Radio,
  Sparkles,
  Layers,
  Search,
  CheckCircle2,
  XCircle,
  Clock,
  Send,
  Sliders,
  X,
  Laptop,
} from "lucide-react";
import { useRonyVoiceStore } from "./ronyVoiceStore";

interface RonyVoicePanelProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export const RonyVoicePanel: React.FC<RonyVoicePanelProps> = ({
  isOpen = true,
  onClose,
}) => {
  const {
    isListening,
    isProcessing,
    isAutomating,
    systemControlEnabled,
    alwaysListening,
    wakeWord,
    wakeWordDetected,
    currentTranscript,
    activeAutomation,
    pendingApproval,
    commandHistory,
    startListening,
    stopListening,
    toggleSystemControl,
    toggleAlwaysListening,
    executeCommand,
    approveAction,
    rejectAction,
    emergencyStop,
  } = useRonyVoiceStore();

  const [inputCommand, setInputCommand] = useState("");
  const [showPrivacyNotice, setShowPrivacyNotice] = useState(false);

  // Global hotkeys: Ctrl+Shift+R (toggle mic), Ctrl+Shift+Q (emergency stop)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && (e.key === "R" || e.key === "r")) {
        e.preventDefault();
        if (isListening) stopListening();
        else startListening();
      }
      if (e.ctrlKey && e.shiftKey && (e.key === "Q" || e.key === "q")) {
        e.preventDefault();
        void emergencyStop();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isListening, startListening, stopListening, emergencyStop]);

  if (!isOpen) return null;

  const handleSubmitText = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputCommand.trim()) return;
    void executeCommand(inputCommand.trim());
    setInputCommand("");
  };

  return (
    <div
      data-testid="rony-voice-panel"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in select-none"
    >
      <div className="relative w-full max-w-2xl bg-[#0f1117] border border-cyan-500/20 rounded-2xl shadow-[0_0_50px_rgba(0,218,243,0.12)] flex flex-col overflow-hidden text-white font-sans max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#141724]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Sparkles size={16} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold tracking-wide text-white">RONY VOICE</h2>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                  JARVIS Laptop Control
                </span>
              </div>
              <p className="text-[11px] text-gray-400">System-wide voice intelligence & laptop automation</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Emergency Stop Button */}
            <button
              data-testid="emergency-stop-btn"
              onClick={() => void emergencyStop()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/40 text-rose-300 text-xs font-bold transition-all cursor-pointer shadow-[0_0_12px_rgba(244,63,94,0.2)]"
              title="Emergency Stop (Ctrl+Shift+Q)"
            >
              <AlertOctagon size={13} className="text-rose-400" />
              <span>Emergency Stop</span>
            </button>

            {onClose && (
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors cursor-pointer"
                title="Close"
              >
                <X size={16} />
              </button>
            )}
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col items-center gap-6">
          {/* Controls Bar: System Control Toggle & Always Listening */}
          <div className="w-full flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-[#141724]/60 border border-white/5 text-xs">
            {/* System Control Toggle */}
            <div className="flex items-center gap-2">
              <Laptop size={14} className={systemControlEnabled ? "text-cyan-400" : "text-gray-400"} />
              <span className="text-gray-300 font-medium">System Control:</span>
              <button
                data-testid="system-control-toggle"
                onClick={() => toggleSystemControl()}
                className={`px-2.5 py-1 rounded-md text-xs font-mono transition-all cursor-pointer border ${
                  systemControlEnabled
                    ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40 shadow-[0_0_8px_rgba(0,218,243,0.3)] font-bold"
                    : "bg-white/5 text-gray-400 border-white/10 hover:text-gray-200"
                }`}
              >
                {systemControlEnabled ? "LAPTOP CONTROL (ON)" : "CODE OS ONLY (OFF)"}
              </button>
            </div>

            {/* Always Listening Toggle */}
            <div className="flex items-center gap-2">
              <Radio size={14} className={alwaysListening ? "text-amber-400 animate-pulse" : "text-gray-400"} />
              <span className="text-gray-300 font-medium">Always Listening:</span>
              <button
                data-testid="always-listening-toggle"
                onClick={() => {
                  if (!alwaysListening) setShowPrivacyNotice(true);
                  toggleAlwaysListening();
                }}
                className={`px-2.5 py-1 rounded-md text-xs font-mono transition-all cursor-pointer border ${
                  alwaysListening
                    ? "bg-amber-500/20 text-amber-300 border-amber-500/40 font-bold"
                    : "bg-white/5 text-gray-400 border-white/10 hover:text-gray-200"
                }`}
              >
                {alwaysListening ? "ACTIVE (OPT-IN)" : "DISABLED"}
              </button>
            </div>
          </div>

          {/* Privacy Disclaimer Notice */}
          {showPrivacyNotice && alwaysListening && (
            <div className="w-full p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldAlert size={16} className="shrink-0 text-amber-400" />
                <span>
                  <strong>Privacy Notice:</strong> Always-listening mode processes microphone audio locally to detect &apos;{wakeWord}&apos;. No audio is transmitted externally.
                </span>
              </div>
              <button
                onClick={() => setShowPrivacyNotice(false)}
                className="text-amber-400 hover:text-amber-200 text-xs cursor-pointer ml-2"
              >
                Dismiss
              </button>
            </div>
          )}

          {/* Center Microphone Button Stage */}
          <div className="flex flex-col items-center justify-center gap-4 my-2">
            <div className="relative flex items-center justify-center">
              {/* Outer pulsing ring when listening */}
              {isListening && (
                <>
                  <div className="absolute w-32 h-32 rounded-full border border-cyan-400/30 animate-ping pointer-events-none" />
                  <div className="absolute w-28 h-28 rounded-full border border-cyan-400/50 animate-pulse pointer-events-none" />
                </>
              )}

              <button
                data-testid="microphone-toggle-btn"
                onClick={() => {
                  if (isListening) stopListening();
                  else startListening();
                }}
                className={`w-20 h-20 rounded-full flex items-center justify-center transition-all duration-300 cursor-pointer shadow-xl ${
                  isListening
                    ? "bg-gradient-to-tr from-cyan-500 to-blue-500 text-black shadow-[0_0_30px_rgba(0,218,243,0.5)] scale-105"
                    : "bg-[#181a25] hover:bg-[#202334] text-cyan-400 border border-cyan-500/30 hover:border-cyan-500/60"
                }`}
                title="Toggle Listening (Ctrl+Shift+R)"
              >
                {isListening ? <Mic size={32} className="animate-bounce" /> : <MicOff size={28} />}
              </button>
            </div>

            {/* Wake Word Indicator */}
            <div
              data-testid="wake-word-indicator"
              className="flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs font-mono"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  isListening ? "bg-emerald-400 animate-ping" : "bg-gray-500"
                }`}
              />
              <span className="text-gray-300">
                Listening for <strong className="text-cyan-400">&apos;{wakeWord}&apos;</strong>...
              </span>
            </div>
          </div>

          {/* Active Automation Progress Bar */}
          {activeAutomation && (
            <div
              data-testid="automation-status-bar"
              className="w-full p-4 rounded-xl bg-cyan-950/20 border border-cyan-500/30 flex flex-col gap-2 shadow-inner"
            >
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-cyan-300 flex items-center gap-1.5">
                  <span className="animate-spin text-sm">⚙️</span>
                  <span>{activeAutomation.description}</span>
                </span>
                <span className="font-mono text-cyan-400">
                  Step {activeAutomation.current_step}/{activeAutomation.total_steps} ({activeAutomation.progress}%)
                </span>
              </div>
              <div className="w-full h-1.5 bg-black/40 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-300 rounded-full"
                  style={{ width: `${activeAutomation.progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Destructive Action Approval Dialog Modal / Box */}
          {pendingApproval && (
            <div
              data-testid="approval-dialog"
              className="w-full p-4 rounded-xl bg-rose-950/30 border border-rose-500/50 flex flex-col gap-3 shadow-[0_0_20px_rgba(244,63,94,0.15)] animate-in zoom-in-95"
            >
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-rose-500/20 flex items-center justify-center text-rose-400 shrink-0">
                  <ShieldAlert size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="text-xs font-bold text-rose-300">{pendingApproval.title}</h4>
                  <p className="text-xs text-gray-200 mt-1">{pendingApproval.message}</p>
                  {pendingApproval.details && Object.keys(pendingApproval.details).length > 0 && (
                    <div className="mt-2 p-2 rounded bg-black/40 text-[11px] font-mono text-gray-300 border border-white/5">
                      {JSON.stringify(pendingApproval.details, null, 2)}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-rose-500/20">
                <button
                  data-testid="reject-action-btn"
                  onClick={() => rejectAction(pendingApproval.id)}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/10 hover:bg-white/15 text-gray-300 transition-colors cursor-pointer"
                >
                  Deny
                </button>
                <button
                  data-testid="approve-action-btn"
                  onClick={() => void approveAction(pendingApproval.id)}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white transition-all cursor-pointer shadow-md shadow-rose-600/30"
                >
                  Approve Execution
                </button>
              </div>
            </div>
          )}

          {/* Live Transcript / Input Row */}
          <form onSubmit={handleSubmitText} className="w-full flex items-center gap-2">
            <input
              type="text"
              data-testid="voice-transcript-input"
              value={inputCommand || currentTranscript}
              onChange={(e) => setInputCommand(e.target.value)}
              placeholder="Speak command or type (e.g. 'Hey Rony, search best Python IDEs')..."
              className="flex-1 bg-[#141724] border border-white/10 rounded-xl px-4 py-2.5 text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-cyan-500/50 font-mono"
            />
            <button
              type="submit"
              disabled={isProcessing || (!inputCommand.trim() && !currentTranscript.trim())}
              className="p-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-black font-bold transition-all disabled:opacity-40 cursor-pointer shrink-0"
              title="Execute Command"
            >
              <Send size={14} />
            </button>
          </form>

          {/* Command History */}
          <div className="w-full flex flex-col gap-2">
            <div className="flex items-center justify-between text-xs text-gray-400 px-1">
              <span className="font-semibold uppercase tracking-wider text-[10px]">Command History</span>
              <span className="font-mono text-[10px]">{commandHistory.length} total</span>
            </div>

            <div
              data-testid="command-history-list"
              className="flex flex-col gap-2 max-h-48 overflow-y-auto pr-1"
            >
              {commandHistory.length === 0 ? (
                <div className="text-center py-6 text-xs text-gray-500 italic">
                  No voice commands yet. Try saying &apos;Hey Rony, open Chrome&apos;.
                </div>
              ) : (
                commandHistory.map((item) => (
                  <div
                    key={item.id}
                    data-testid={`history-item-${item.id}`}
                    className="p-2.5 rounded-lg bg-[#141724]/80 border border-white/5 flex flex-col gap-1 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-white truncate">{item.command}</span>
                      <span
                        className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
                          item.status === "success"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : item.status === "approval_required"
                            ? "bg-amber-500/15 text-amber-300"
                            : item.status === "pending"
                            ? "bg-blue-500/15 text-blue-300"
                            : "bg-rose-500/15 text-rose-300"
                        }`}
                      >
                        {item.status}
                      </span>
                    </div>
                    {item.result && (
                      <p className="text-[11px] text-gray-400 line-clamp-2">{item.result}</p>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
