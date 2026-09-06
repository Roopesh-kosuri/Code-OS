/**
 * voiceStore.ts — Zustand store for Voice Mode (push-to-talk STT + TTS).
 * All processing done locally via backend Whisper + pyttsx3.
 * Browser MediaRecorder captures audio; backend handles transcription.
 */

import { create } from "zustand";
import { api } from "../../lib/api";

export interface VoiceInfo {
  id: string;
  name: string;
  language: string;
  gender: string;
}

export interface WhisperStatus {
  loaded: boolean;
  loading: boolean;
  model_size: string;
}

export interface VoiceStoreState {
  // Recording state
  isRecording: boolean;
  isTranscribing: boolean;
  isSpeaking: boolean;

  // Transcription
  transcription: string;
  partialTranscription: string;

  // Audio level visualizer (0.0–1.0)
  audioLevel: number;

  // Whisper status
  whisperStatus: WhisperStatus;

  // TTS
  ttsEnabled: boolean;
  selectedVoice: string;
  availableVoices: VoiceInfo[];

  // Modal
  isOpen: boolean;

  // Error
  error: string | null;

  // Internal: MediaRecorder + AudioContext refs (not serialized)
  _mediaRecorder: MediaRecorder | null;
  _audioChunks: Blob[];
  _audioContext: AudioContext | null;
  _analyser: AnalyserNode | null;
  _audioLevelInterval: ReturnType<typeof setInterval> | null;
  _currentAudio: HTMLAudioElement | null;

  // Actions
  openModal: () => void;
  closeModal: () => void;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
  transcribe: (audioBlob: Blob) => Promise<string>;
  speak: (text: string) => Promise<void>;
  stopSpeaking: () => void;
  setVoice: (voice: string) => void;
  setTtsEnabled: (enabled: boolean) => void;
  checkStatus: () => Promise<void>;
  fetchVoices: () => Promise<void>;
  initVoiceEngine: (modelSize?: string) => Promise<void>;
  setTranscription: (text: string) => void;
  clearTranscription: () => void;
  setError: (err: string | null) => void;
}

export const useVoiceStore = create<VoiceStoreState>((set, get) => ({
  isRecording: false,
  isTranscribing: false,
  isSpeaking: false,
  transcription: "",
  partialTranscription: "",
  audioLevel: 0,
  whisperStatus: { loaded: false, loading: false, model_size: "base" },
  ttsEnabled: false,
  selectedVoice: "default",
  availableVoices: [],
  isOpen: false,
  error: null,
  _mediaRecorder: null,
  _audioChunks: [],
  _audioContext: null,
  _analyser: null,
  _audioLevelInterval: null,
  _currentAudio: null,

  openModal: () => set({ isOpen: true }),
  closeModal: () => {
    const { isRecording, _currentAudio } = get();
    if (isRecording) get().stopRecording();
    if (_currentAudio) {
      _currentAudio.pause();
      _currentAudio.src = "";
    }
    set({ isOpen: false, error: null });
  },

  setTranscription: (text) => set({ transcription: text }),
  clearTranscription: () => set({ transcription: "", partialTranscription: "" }),
  setError: (err) => set({ error: err }),
  setVoice: (voice) => set({ selectedVoice: voice }),
  setTtsEnabled: (enabled) => set({ ttsEnabled: enabled }),
  stopSpeaking: () => {
    const { _currentAudio } = get();
    if (_currentAudio) {
      _currentAudio.pause();
      _currentAudio.currentTime = 0;
    }
    set({ isSpeaking: false });
  },

  checkStatus: async () => {
    try {
      const res = await api.get<{
        whisper_loaded: boolean;
        whisper_loading: boolean;
        whisper_model_size: string;
        tts_ready: boolean;
      }>("/api/voice/status");
      set({
        whisperStatus: {
          loaded: res.whisper_loaded,
          loading: res.whisper_loading,
          model_size: res.whisper_model_size || "base",
        },
      });
    } catch {
      // backend may not be running yet — silently ignore
    }
  },

  fetchVoices: async () => {
    try {
      const res = await api.get<{ voices: VoiceInfo[] }>("/api/voice/voices");
      set({ availableVoices: res.voices || [] });
    } catch {
      /* graceful fallback */
    }
  },

  initVoiceEngine: async (modelSize = "base") => {
    try {
      await api.post("/api/voice/init", { model_size: modelSize });
      set({
        whisperStatus: { loaded: false, loading: true, model_size: modelSize },
      });
      // Poll until loaded
      const poll = setInterval(async () => {
        await get().checkStatus();
        if (get().whisperStatus.loaded) clearInterval(poll);
      }, 2000);
    } catch (e: any) {
      set({ error: e?.message || "Failed to initialize voice engine" });
    }
  },

  startRecording: async () => {
    if (get().isRecording) return;

    set({ error: null, transcription: "", partialTranscription: "" });

    try {
      // Request microphone permission
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Set up audio level analyser
      let audioContext: AudioContext | null = null;
      let analyser: AnalyserNode | null = null;
      let levelInterval: ReturnType<typeof setInterval> | null = null;

      try {
        audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        levelInterval = setInterval(() => {
          if (analyser) {
            analyser.getByteFrequencyData(dataArray);
            const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
            set({ audioLevel: Math.min(1.0, avg / 128) });
          }
        }, 50);
      } catch {
        // AudioContext not available — graceful skip
      }

      // Set up MediaRecorder
      const chunks: Blob[] = [];
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "audio/ogg";

      const recorder = new MediaRecorder(stream, { mimeType });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };

      recorder.start(100); // collect in 100ms chunks

      set({
        isRecording: true,
        _mediaRecorder: recorder,
        _audioChunks: chunks,
        _audioContext: audioContext,
        _analyser: analyser,
        _audioLevelInterval: levelInterval,
      });
    } catch (e: any) {
      set({
        error:
          e?.name === "NotAllowedError"
            ? "Microphone permission denied. Please allow microphone access."
            : `Could not start recording: ${e?.message || "Unknown error"}`,
      });
    }
  },

  stopRecording: async () => {
    const { _mediaRecorder, _audioChunks, _audioContext, _audioLevelInterval } = get();
    if (!_mediaRecorder || !get().isRecording) return;

    set({ isRecording: false, audioLevel: 0 });

    if (_audioLevelInterval) clearInterval(_audioLevelInterval);

    // Stop the recorder and await data
    await new Promise<void>((resolve) => {
      if (!_mediaRecorder) { resolve(); return; }
      _mediaRecorder.onstop = () => resolve();
      _mediaRecorder.stop();
      _mediaRecorder.stream.getTracks().forEach((t) => t.stop());
    });

    if (_audioContext) {
      try { await _audioContext.close(); } catch { /* ignore */ }
    }

    const audioBlob = new Blob(_audioChunks, { type: _mediaRecorder.mimeType });
    set({ _audioChunks: [], _mediaRecorder: null, _audioContext: null, _analyser: null, _audioLevelInterval: null });

    if (audioBlob.size > 1000) {
      const text = await get().transcribe(audioBlob);
      set({ transcription: text });
    }
  },

  transcribe: async (audioBlob: Blob): Promise<string> => {
    set({ isTranscribing: true, error: null });
    try {
      const formData = new FormData();
      // Determine extension from mime type
      const mimeType = audioBlob.type || "audio/webm";
      const ext = mimeType.includes("webm") ? "webm" : mimeType.includes("ogg") ? "ogg" : "wav";
      formData.append("audio", audioBlob, `recording.${ext}`);

      const data = await api.post<{ text?: string; error?: string }>("/api/voice/transcribe", formData);
      set({ isTranscribing: false, partialTranscription: "" });
      if (data?.error) {
        set({ error: data.error });
      }
      return data?.text || "";
    } catch (e: any) {
      set({ isTranscribing: false, error: e?.message || "Transcription failed" });
      return "";
    }
  },

  speak: async (text: string): Promise<void> => {
    if (!text.trim() || !get().ttsEnabled) return;

    // Stop any currently playing audio
    get().stopSpeaking();
    set({ isSpeaking: true, error: null });

    try {
      const audioBlob = await api.blob("/api/voice/speak", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text, voice: get().selectedVoice || undefined }),
      });

      if (audioBlob.size < 50) {
        set({ isSpeaking: false });
        return;
      }

      const url = URL.createObjectURL(audioBlob);
      const audio = new Audio(url);
      audio.onended = () => {
        set({ isSpeaking: false, _currentAudio: null });
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        set({ isSpeaking: false, _currentAudio: null });
        URL.revokeObjectURL(url);
      };

      set({ _currentAudio: audio });
      await audio.play();
    } catch (e: any) {
      set({ isSpeaking: false, error: e?.message || "TTS failed" });
    }
  },
}));
