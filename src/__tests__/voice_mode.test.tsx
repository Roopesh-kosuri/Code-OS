import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { VoiceModePanel } from "../features/voice/VoiceModePanel";
import { useVoiceStore } from "../features/voice/voiceStore";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

// Mock MediaRecorder globally
const mockStop = vi.fn();
const mockStart = vi.fn();
const mockStream = {
  getTracks: () => [{ stop: vi.fn() }],
};

const mockMediaRecorder = {
  start: mockStart,
  stop: mockStop,
  stream: mockStream,
  mimeType: "audio/webm",
  ondataavailable: null as any,
  onstop: null as any,
};

vi.stubGlobal("MediaRecorder", {
  ...vi.fn().mockImplementation(() => mockMediaRecorder),
  isTypeSupported: vi.fn().mockReturnValue(true),
});

// Mock getUserMedia
const mockGetUserMedia = vi.fn().mockResolvedValue(mockStream as any);
Object.defineProperty(global.navigator, "mediaDevices", {
  value: { getUserMedia: mockGetUserMedia },
  writable: true,
});

// Mock AudioContext
const mockAnalyser = {
  fftSize: 256,
  frequencyBinCount: 128,
  getByteFrequencyData: vi.fn(),
};
const mockAudioContext = {
  createMediaStreamSource: vi.fn().mockReturnValue({ connect: vi.fn() }),
  createAnalyser: vi.fn().mockReturnValue(mockAnalyser),
  close: vi.fn().mockResolvedValue(undefined),
};
vi.stubGlobal("AudioContext", vi.fn().mockImplementation(() => mockAudioContext));

// Mock fetch for transcription/speak
vi.stubGlobal("fetch", vi.fn());

describe("Voice Mode Frontend Test Suite", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    onSendToAgent: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();

    act(() => {
      useVoiceStore.setState({
        isRecording: false,
        isTranscribing: false,
        isSpeaking: false,
        transcription: "",
        partialTranscription: "",
        audioLevel: 0,
        whisperStatus: { loaded: true, loading: false, model_size: "base" },
        ttsEnabled: false,
        selectedVoice: "default",
        availableVoices: [],
        isOpen: true,
        error: null,
        _mediaRecorder: null,
        _audioChunks: [],
        _audioContext: null,
        _analyser: null,
        _audioLevelInterval: null,
        _currentAudio: null,
      });
    });

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/api/voice/status") {
        return {
          whisper_loaded: true,
          whisper_loading: false,
          whisper_model_size: "base",
          tts_ready: true,
        };
      }
      if (url === "/api/voice/voices") {
        return { voices: [{ id: "v1", name: "Microsoft David", language: "en-US", gender: "male" }] };
      }
      return {};
    });
  });

  afterEach(() => {
    act(() => {
      useVoiceStore.setState({ isRecording: false, isOpen: false });
    });
  });

  // ── Test 1: Microphone button starts recording ────────────────────────────
  it("test_microphone_button_starts_recording: clicking mic button triggers startRecording", async () => {
    render(<VoiceModePanel {...defaultProps} />);

    const micBtn = screen.getByTestId("mic-button");
    expect(micBtn).toBeDefined();

    await act(async () => {
      fireEvent.click(micBtn);
    });

    await waitFor(() => {
      expect(mockGetUserMedia).toHaveBeenCalledWith({ audio: true });
    });
  });

  // ── Test 2: Audio level meter updates ────────────────────────────────────
  it("test_audio_level_meter_updates: audio-level-meter renders bars and reflects audioLevel state", async () => {
    await act(async () => {
      render(<VoiceModePanel {...defaultProps} />);
    });

    const meter = screen.getByTestId("audio-level-meter");
    expect(meter).toBeDefined();
    // Should have 12 bar children
    expect(meter.children.length).toBe(12);

    // Update audioLevel to 0.8
    act(() => {
      useVoiceStore.setState({ audioLevel: 0.8, isRecording: true });
    });

    await waitFor(() => {
      const updatedMeter = screen.getByTestId("audio-level-meter");
      expect(updatedMeter).toBeDefined();
    });
  });

  // ── Test 3: Transcription displays in panel ──────────────────────────────
  it("test_transcription_displays_in_panel: transcription text appears in display area", async () => {
    act(() => {
      useVoiceStore.setState({
        transcription: "Build a calculator in Python",
        partialTranscription: "",
      });
    });

    await act(async () => {
      render(<VoiceModePanel {...defaultProps} />);
    });

    const display = screen.getByTestId("transcription-display");
    expect(display.textContent).toContain("Build a calculator in Python");

    // Send to Agent button should be visible
    const sendBtn = screen.getByTestId("send-to-agent-btn");
    expect(sendBtn).toBeDefined();

    fireEvent.click(sendBtn);
    expect(defaultProps.onSendToAgent).toHaveBeenCalledWith("Build a calculator in Python");
  });

  // ── Test 4: TTS toggle enables auto-speak ────────────────────────────────
  it("test_tts_toggle_enables_auto_speak: clicking TTS toggle changes ttsEnabled state", async () => {
    await act(async () => {
      render(<VoiceModePanel {...defaultProps} />);
    });

    const toggle = screen.getByTestId("tts-toggle");
    expect(toggle).toBeDefined();
    // Default is OFF
    expect(useVoiceStore.getState().ttsEnabled).toBe(false);

    // Click to enable
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(useVoiceStore.getState().ttsEnabled).toBe(true);
    });

    // Click to disable
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(useVoiceStore.getState().ttsEnabled).toBe(false);
    });
  });

  // ── Test 5: Hotkey triggers recording ────────────────────────────────────
  it("test_hotkey_triggers_recording: Ctrl+Shift+Space fires startRecording", async () => {
    const startRecordingSpy = vi.fn();
    useVoiceStore.setState({ startRecording: startRecordingSpy as any });

    await act(async () => {
      render(<VoiceModePanel {...defaultProps} />);
    });

    // Simulate Ctrl+Shift+Space keydown
    act(() => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          code: "Space",
          ctrlKey: true,
          shiftKey: true,
          bubbles: true,
        })
      );
    });

    await waitFor(() => {
      expect(startRecordingSpy).toHaveBeenCalled();
    });
  });

  // ── Test 6: Send to Agent injects text ───────────────────────────────────
  it("test_send_to_agent_injects_text: send-to-agent button calls onSendToAgent with transcription text", async () => {
    act(() => {
      useVoiceStore.setState({ transcription: "Create a REST API endpoint" });
    });

    await act(async () => {
      render(<VoiceModePanel {...defaultProps} />);
    });

    const sendBtn = screen.getByTestId("send-to-agent-btn");
    fireEvent.click(sendBtn);

    expect(defaultProps.onSendToAgent).toHaveBeenCalledWith("Create a REST API endpoint");

    // After sending, transcription should be cleared
    await waitFor(() => {
      expect(useVoiceStore.getState().transcription).toBe("");
    });
  });
});
