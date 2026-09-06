import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Mic,
  MicOff,
  Volume2,
  Volume1,
  VolumeX,
  Radio,
  ChevronDown,
  Loader2,
  X,
  ArrowUpRight,
  Cpu,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Laptop,
  Check,
} from "lucide-react";
import { useVoiceStore } from "./voiceStore";
import { useRonyVoiceStore } from "../rony/ronyVoiceStore";

interface VoiceModePanelProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called when user clicks "Send to Agent" — injects transcription into chat */
  onSendToAgent?: (text: string) => void;
}

// ── Audio Level Visualizer ────────────────────────────────────────────────────
const AudioLevelMeter: React.FC<{ level: number; isActive: boolean }> = ({ level, isActive }) => {
  const bars = 12;
  return (
    <div
      data-testid="audio-level-meter"
      className="flex items-end justify-center gap-0.5 h-10"
      aria-label="Audio level meter"
    >
      {Array.from({ length: bars }, (_, i) => {
        const threshold = (i + 1) / bars;
        const active = isActive && level >= threshold;
        return (
          <div
            key={i}
            className={`w-1.5 rounded-full transition-all duration-75 ${
              active
                ? i < bars * 0.4
                  ? "bg-emerald-400"
                  : i < bars * 0.75
                  ? "bg-yellow-400"
                  : "bg-rose-400"
                : "bg-white/10"
            }`}
            style={{
              height: `${20 + (i % 4) * 10 + (active ? 5 : 0)}px`,
            }}
          />
        );
      })}
    </div>
  );
};

// ── Main Panel ────────────────────────────────────────────────────────────────
export const VoiceModePanel: React.FC<VoiceModePanelProps> = ({
  isOpen,
  onClose,
  onSendToAgent,
}) => {
  const {
    isRecording,
    isTranscribing,
    isSpeaking,
    transcription,
    partialTranscription,
    audioLevel,
    whisperStatus,
    ttsEnabled,
    selectedVoice,
    availableVoices,
    error,
    startRecording,
    stopRecording,
    setTtsEnabled,
    setVoice,
    speak,
    stopSpeaking,
    checkStatus,
    fetchVoices,
    initVoiceEngine,
    clearTranscription,
    setError,
  } = useVoiceStore();

  const { systemControlEnabled, toggleSystemControl, executeCommand } = useRonyVoiceStore();

  const [isVoiceDropdownOpen, setIsVoiceDropdownOpen] = useState(false);
  const [voiceSearchQuery, setVoiceSearchQuery] = useState("");
  const voiceDropdownRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (voiceDropdownRef.current && !voiceDropdownRef.current.contains(e.target as Node)) {
        setIsVoiceDropdownOpen(false);
      }
    };
    if (isVoiceDropdownOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isVoiceDropdownOpen]);

  const currentVoiceObj = availableVoices.find((v) => v.name === selectedVoice || v.id === selectedVoice);
  const currentVoiceLabel = currentVoiceObj
    ? currentVoiceObj.name
    : selectedVoice === "default"
    ? "System Default"
    : (selectedVoice || "System Default");

  const filteredVoices = availableVoices.filter((v) => {
    if (!voiceSearchQuery.trim()) return true;
    const q = voiceSearchQuery.toLowerCase();
    return v.name.toLowerCase().includes(q) || v.language.toLowerCase().includes(q);
  });

  const displayText = transcription || partialTranscription;

  // On mount, check status and fetch voices
  useEffect(() => {
    if (isOpen) {
      void checkStatus();
      void fetchVoices();
    }
  }, [isOpen, checkStatus, fetchVoices]);

  // Hotkey: Ctrl+Shift+Space → push-to-talk
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.code === "Space") {
        e.preventDefault();
        if (!isRecording) void startRecording();
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space" && e.ctrlKey && e.shiftKey) {
        e.preventDefault();
        if (isRecording) void stopRecording();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [isRecording, startRecording, stopRecording]);

  const handleMicToggle = () => {
    if (isRecording) {
      void stopRecording();
    } else {
      void startRecording();
    }
  };

  const handleSendToAgent = () => {
    if (transcription.trim()) {
      if (systemControlEnabled) {
        void executeCommand(transcription.trim());
      } else if (onSendToAgent) {
        onSendToAgent(transcription.trim());
      }
      clearTranscription();
    }
  };

  const handleSpeak = () => {
    if (displayText) void speak(displayText);
  };

  if (!isOpen) return null;

  return (
    <div
      data-testid="voice-mode-panel"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backdropFilter: "blur(8px)", background: "rgba(0,0,0,0.6)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="relative w-full max-w-lg rounded-2xl border border-white/10 shadow-2xl overflow-hidden"
        style={{
          background: "linear-gradient(135deg, #0e1119 0%, #13161f 60%, #0a0c14 100%)",
        }}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-primary/15 border border-primary/25 flex items-center justify-center">
              <Mic size={16} className="text-primary" />
            </div>
            <div>
              <h2 className="font-bold text-sm text-white tracking-wide">JARVIS Voice Mode</h2>
              <p className="text-[11px] text-on-surface-variant font-mono">Push-to-Talk · Local STT/TTS</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="system-control-toggle-voice-panel"
              onClick={() => toggleSystemControl()}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono border transition-all cursor-pointer ${
                systemControlEnabled
                  ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40 shadow-[0_0_8px_rgba(0,218,243,0.3)] font-bold"
                  : "bg-white/5 text-on-surface-variant border-white/10 hover:text-white"
              }`}
              title="Toggle Laptop Control Mode (JARVIS System Control)"
            >
              <Laptop size={12} className={systemControlEnabled ? "text-cyan-400" : "opacity-60"} />
              <span>{systemControlEnabled ? "Laptop Control ON" : "System Control OFF"}</span>
            </button>
            <button
              onClick={onClose}
              data-testid="voice-close-btn"
              className="w-7 h-7 rounded-lg bg-white/5 hover:bg-white/10 flex items-center justify-center text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* ── Whisper Status Bar ── */}
        <div className="px-5 py-2.5 bg-black/20 border-b border-white/5 flex items-center justify-between text-[11px] font-mono">
          <div className="flex items-center gap-2">
            <Cpu size={12} className="text-cyan-400 shrink-0" />
            {whisperStatus.loading ? (
              <span className="text-amber-400 flex items-center gap-1.5">
                <Loader2 size={10} className="animate-spin" />
                Loading Whisper {whisperStatus.model_size}...
              </span>
            ) : whisperStatus.loaded ? (
              <span className="text-emerald-400 flex items-center gap-1.5">
                <CheckCircle2 size={11} />
                Whisper {whisperStatus.model_size} · Ready
              </span>
            ) : (
              <button
                onClick={() => void initVoiceEngine("base")}
                data-testid="whisper-load-btn"
                className="text-primary hover:text-primary/80 underline cursor-pointer"
              >
                Load Whisper base model
              </button>
            )}
          </div>
          <span
            data-testid="whisper-status-badge"
            className={`px-2 py-0.5 rounded-full border text-[9px] font-bold uppercase ${
              whisperStatus.loaded
                ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                : whisperStatus.loading
                ? "bg-amber-500/15 text-amber-400 border-amber-500/30"
                : "bg-zinc-500/15 text-zinc-400 border-zinc-500/30"
            }`}
          >
            {whisperStatus.loaded ? "loaded" : whisperStatus.loading ? "loading" : "offline"}
          </span>
        </div>

        {/* ── Main Recording Area ── */}
        <div className="px-5 py-8 flex flex-col items-center gap-6">
          {/* Big Mic Button */}
          <div className="relative flex items-center justify-center">
            {isRecording && (
              <>
                <div className="absolute w-32 h-32 rounded-full border-2 border-rose-500/40 animate-ping" />
                <div className="absolute w-24 h-24 rounded-full border border-rose-500/30 animate-pulse" />
              </>
            )}
            <button
              onClick={handleMicToggle}
              data-testid="mic-button"
              disabled={isTranscribing}
              className={`relative w-20 h-20 rounded-full flex items-center justify-center transition-all duration-200 cursor-pointer disabled:opacity-50 shadow-lg ${
                isRecording
                  ? "bg-rose-500 hover:bg-rose-600 shadow-rose-500/30 scale-110"
                  : "bg-primary/20 hover:bg-primary/30 border border-primary/40 hover:border-primary/60"
              }`}
              title={isRecording ? "Stop recording (Ctrl+Shift+Space)" : "Start recording (Ctrl+Shift+Space)"}
            >
              {isTranscribing ? (
                <Loader2 size={28} className="text-white animate-spin" />
              ) : isRecording ? (
                <MicOff size={28} className="text-white" />
              ) : (
                <Mic size={28} className="text-primary" />
              )}
            </button>
          </div>

          {/* Status label */}
          <p className="text-xs text-on-surface-variant font-mono text-center">
            {isTranscribing
              ? "Transcribing with Whisper..."
              : isRecording
              ? "🔴 Recording… click to stop"
              : "Click mic or press Ctrl+Shift+Space"}
          </p>

          {/* Audio Level Meter */}
          <AudioLevelMeter level={audioLevel} isActive={isRecording} />
        </div>

        {/* ── Transcription Display ── */}
        <div className="px-5 pb-4">
          <div
            className="min-h-[80px] rounded-xl border border-white/8 bg-black/30 p-3 text-sm text-on-surface font-mono leading-relaxed"
            data-testid="transcription-display"
          >
            {displayText ? (
              <span className={partialTranscription && !transcription ? "text-on-surface-variant" : ""}>
                {displayText}
              </span>
            ) : (
              <span className="text-on-surface-variant/40 text-xs italic">
                Transcription will appear here…
              </span>
            )}
          </div>

          {/* Action buttons */}
          {transcription && (
            <div className="flex gap-2 mt-2">
              <button
                onClick={handleSendToAgent}
                data-testid="send-to-agent-btn"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/20 hover:bg-primary/30 border border-primary/40 text-primary text-xs font-semibold transition-colors cursor-pointer"
              >
                <ArrowUpRight size={13} />
                Send to Agent
              </button>
              <button
                onClick={clearTranscription}
                data-testid="clear-transcription-btn"
                className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-on-surface-variant text-xs transition-colors cursor-pointer"
              >
                Clear
              </button>
            </div>
          )}
        </div>

        {/* ── Error Banner ── */}
        {error && (
          <div className="mx-5 mb-3 px-3 py-2 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2">
            <AlertTriangle size={13} className="shrink-0" />
            <span data-testid="voice-error-banner">{error}</span>
            <button onClick={() => setError(null)} className="ml-auto cursor-pointer hover:text-rose-200">
              <X size={12} />
            </button>
          </div>
        )}

        {/* ── TTS + Voice Settings ── */}
        <div className="px-5 pb-5 flex flex-col gap-3 border-t border-white/5 pt-4">
          {/* TTS Toggle */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {ttsEnabled ? (
                <Volume2 size={14} className="text-primary" />
              ) : (
                <VolumeX size={14} className="text-on-surface-variant" />
              )}
              <span className="text-xs text-on-surface font-medium">Read replies aloud</span>
            </div>
            <button
              onClick={() => setTtsEnabled(!ttsEnabled)}
              data-testid="tts-toggle"
              className={`relative w-10 h-5 rounded-full transition-colors cursor-pointer ${
                ttsEnabled ? "bg-primary" : "bg-white/15"
              }`}
            >
              <div
                className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${
                  ttsEnabled ? "left-5" : "left-0.5"
                }`}
              />
            </button>
          </div>

          {/* Play last transcription via TTS */}
          {transcription && ttsEnabled && (
            <button
              onClick={isSpeaking ? stopSpeaking : handleSpeak}
              data-testid="tts-play-btn"
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-mono transition-colors cursor-pointer ${
                isSpeaking
                  ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                  : "bg-white/5 hover:bg-white/10 text-on-surface-variant border border-white/10"
              }`}
            >
              {isSpeaking ? (
                <>
                  <Activity size={12} className="animate-pulse" />
                  Speaking… (click to stop)
                </>
              ) : (
                <>
                  <Volume2 size={12} />
                  Play transcription aloud
                </>
              )}
            </button>
          )}

          {/* Voice selector (Liquid Glass Custom Dropdown) */}
          {availableVoices.length > 0 && (
            <div className="relative flex flex-col gap-1.5" ref={voiceDropdownRef}>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-on-surface-variant font-mono flex items-center gap-1.5">
                  <Volume2 size={12} className="text-cyan-400" />
                  <span>Speech Voice:</span>
                </span>
                <span className="text-[10px] text-gray-400 font-mono">
                  {availableVoices.length} available
                </span>
              </div>

              {/* Custom Dropdown Trigger */}
              <button
                type="button"
                data-testid="voice-selector-trigger"
                onClick={() => setIsVoiceDropdownOpen(!isVoiceDropdownOpen)}
                className={`w-full bg-[#131522]/90 hover:bg-[#1a1d2e] border rounded-xl px-3 py-2 flex items-center justify-between transition-all duration-200 cursor-pointer shadow-sm ${
                  isVoiceDropdownOpen
                    ? "border-cyan-500/50 shadow-[0_0_15px_rgba(0,218,243,0.15)] ring-1 ring-cyan-500/20"
                    : "border-white/10 hover:border-cyan-500/30"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-5 h-5 rounded-md bg-cyan-500/10 border border-cyan-500/25 flex items-center justify-center text-cyan-400 shrink-0">
                    <Volume1 size={12} />
                  </div>
                  <div className="flex flex-col items-start min-w-0">
                    <span className="text-xs font-semibold text-white truncate">
                      {currentVoiceLabel}
                    </span>
                    {currentVoiceObj && (
                      <span className="text-[10px] text-gray-400 font-mono truncate">
                        {currentVoiceObj.language} · {currentVoiceObj.gender || "Voice"}
                      </span>
                    )}
                  </div>
                </div>

                <ChevronDown
                  size={14}
                  className={`text-gray-400 transition-transform duration-200 shrink-0 ml-2 ${
                    isVoiceDropdownOpen ? "rotate-180 text-cyan-400" : ""
                  }`}
                />
              </button>

              {/* Popover Menu (Liquid Glass) */}
              {isVoiceDropdownOpen && (
                <div className="absolute left-0 right-0 bottom-full mb-2 bg-[#0d1017]/95 backdrop-blur-xl border border-cyan-500/25 rounded-xl shadow-[0_12px_40px_rgba(0,0,0,0.85),0_0_20px_rgba(0,218,243,0.1)] overflow-hidden z-50 animate-in fade-in zoom-in-95 duration-150 flex flex-col max-h-56">
                  {/* Search filter if > 4 voices */}
                  {availableVoices.length > 4 && (
                    <div className="p-2 border-b border-white/10 bg-black/20">
                      <input
                        type="text"
                        placeholder="Search voices..."
                        value={voiceSearchQuery}
                        onChange={(e) => setVoiceSearchQuery(e.target.value)}
                        className="w-full bg-[#161826] border border-white/10 rounded-lg px-2.5 py-1 text-xs text-white placeholder:text-gray-500 focus:outline-none focus:border-cyan-500/50 font-mono"
                        onClick={(e) => e.stopPropagation()}
                      />
                    </div>
                  )}

                  <div className="overflow-y-auto p-1.5 flex flex-col gap-1 no-scrollbar">
                    {/* System Default Option */}
                    <button
                      type="button"
                      onClick={() => {
                        setVoice("default");
                        setIsVoiceDropdownOpen(false);
                      }}
                      className={`w-full text-left px-2.5 py-2 rounded-lg flex items-center justify-between transition-all cursor-pointer text-xs ${
                        selectedVoice === "default"
                          ? "bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 font-semibold"
                          : "hover:bg-white/5 text-gray-300 hover:text-white border border-transparent"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                        <div>
                          <div className="font-medium">System Default</div>
                          <div className="text-[10px] text-gray-400 font-mono">Use operating system voice</div>
                        </div>
                      </div>
                      {selectedVoice === "default" && (
                        <Check size={13} className="text-cyan-400 shrink-0" />
                      )}
                    </button>

                    {/* Available Voices List */}
                    {filteredVoices.map((v) => {
                      const isSelected = selectedVoice === v.name || selectedVoice === v.id;
                      return (
                        <button
                          key={v.id}
                          type="button"
                          onClick={() => {
                            setVoice(v.name);
                            setIsVoiceDropdownOpen(false);
                          }}
                          className={`w-full text-left px-2.5 py-2 rounded-lg flex items-center justify-between transition-all cursor-pointer text-xs ${
                            isSelected
                              ? "bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 font-semibold"
                              : "hover:bg-white/5 text-gray-300 hover:text-white border border-transparent"
                          }`}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isSelected ? "bg-cyan-400" : "bg-gray-600"}`} />
                            <div className="truncate">
                              <div className="font-medium text-white truncate">{v.name}</div>
                              <div className="text-[10px] text-gray-400 font-mono truncate">
                                {v.language} {v.gender ? `· ${v.gender}` : ""}
                              </div>
                            </div>
                          </div>
                          {isSelected && (
                            <Check size={13} className="text-cyan-400 shrink-0 ml-2" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Hidden select for accessibility & automated tests */}
              <select
                data-testid="voice-selector"
                value={selectedVoice}
                onChange={(e) => setVoice(e.target.value)}
                className="sr-only"
                aria-hidden="true"
                tabIndex={-1}
              >
                <option value="default">System Default</option>
                {availableVoices.map((v) => (
                  <option key={v.id} value={v.name}>
                    {v.name} ({v.language})
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Hotkey hint */}
          <p className="text-[10px] text-on-surface-variant/40 font-mono text-center">
            Hotkey: <kbd className="px-1 py-0.5 rounded bg-white/5 border border-white/10 text-[9px]">Ctrl+Shift+Space</kbd> to push-to-talk
          </p>
        </div>
      </div>
    </div>
  );
};
