"""
test_voice_mode.py — Backend tests for Voice Mode (Whisper STT + pyttsx3 TTS).
All models run locally. External network calls are mocked/isolated.
"""

from __future__ import annotations

import io
import wave
import struct
import math
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


# ── Helper: build a valid minimal WAV file in memory ─────────────────────────
def make_test_wav(duration_s: float = 0.5, sample_rate: int = 16000, freq_hz: float = 440.0) -> bytes:
    """Generate a minimal sine-wave WAV file for testing."""
    num_samples = int(sample_rate * duration_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        samples = [
            int(32767 * math.sin(2 * math.pi * freq_hz * i / sample_rate))
            for i in range(num_samples)
        ]
        wf.writeframes(struct.pack(f"<{num_samples}h", *samples))
    return buf.getvalue()


# ── Test 1: Whisper transcribes audio ───────────────────────────────────────
def test_whisper_transcribes_audio():
    """
    Whisper STT service should accept a WAV buffer and return a
    transcription dict with the expected keys and sensible defaults.
    We mock the faster_whisper model so no GPU/CPU inference runs in CI.
    """
    mock_segment = MagicMock()
    mock_segment.text = " Hello world"
    mock_segment.start = 0.0
    mock_segment.end = 0.5
    mock_segment.avg_logprob = -0.3

    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([mock_segment]), mock_info)

    with patch("app.features.ai.voice.whisper_stt_service._model", mock_model), \
         patch("app.features.ai.voice.whisper_stt_service._model_loaded", True):

        from app.features.ai.voice.whisper_stt_service import transcribe_audio

        wav_bytes = make_test_wav()
        result = transcribe_audio(wav_bytes, fmt="wav")

    assert "text" in result
    assert "language" in result
    assert "duration_s" in result
    assert "confidence" in result
    assert "segments" in result
    assert result["language"] == "en"
    assert isinstance(result["duration_s"], float)
    assert result["duration_s"] > 0
    assert result["text"] == "Hello world"


# ── Test 2: TTS generates valid WAV audio ────────────────────────────────────
def test_tts_generates_audio():
    """
    TTS service should return WAV bytes with a valid RIFF header.
    We mock pyttsx3 to write a real WAV file using soundfile/numpy.
    """
    import numpy as np
    import soundfile as sf
    import tempfile
    from pathlib import Path

    def mock_save_to_file(text: str, path: str):
        """Write a real silent WAV file to simulate pyttsx3 output."""
        silence = np.zeros(8000, dtype=np.float32)
        sf.write(path, silence, 16000, format="WAV", subtype="PCM_16")

    mock_engine = MagicMock()
    mock_engine.save_to_file.side_effect = mock_save_to_file
    mock_engine.runAndWait.return_value = None

    with patch("app.features.ai.voice.tts_service._engine", mock_engine), \
         patch("app.features.ai.voice.tts_service._tts_ready", True):

        from app.features.ai.voice.tts_service import speak

        wav_bytes = speak("JARVIS online.")

    # Must be non-empty bytes starting with RIFF (WAV header)
    assert isinstance(wav_bytes, bytes)
    assert len(wav_bytes) > 44
    assert wav_bytes[:4] == b"RIFF", f"Expected WAV RIFF header, got: {wav_bytes[:4]!r}"
    assert wav_bytes[8:12] == b"WAVE", f"Expected WAVE marker, got: {wav_bytes[8:12]!r}"


# ── Test 3: Voice routes API ─────────────────────────────────────────────────
def test_voice_routes_api():
    """
    Test the full HTTP API surface for voice endpoints via FastAPI TestClient.
    Services are mocked so no real model inference occurs.
    """
    # We import the FastAPI app and use TestClient
    with patch("app.features.ai.voice.whisper_stt_service._model_loaded", True), \
         patch("app.features.ai.voice.whisper_stt_service._model_loading", False), \
         patch("app.features.ai.voice.whisper_stt_service._model_size", "base"), \
         patch("app.features.ai.voice.tts_service._tts_ready", True), \
         patch("app.features.ai.voice.tts_service._selected_voice", "Microsoft David"), \
         patch("app.features.ai.voice.tts_service._speech_rate", 175):

        from app.features.ai.voice.voice_routes import voice_router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(voice_router)
        client = TestClient(test_app)

        # GET /api/voice/status
        resp = client.get("/api/voice/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["whisper_loaded"] is True
        assert data["whisper_model_size"] == "base"
        assert data["tts_ready"] is True

        # GET /api/voice/voices (mocked engine with voices)
        mock_voice = MagicMock()
        mock_voice.id = "com.microsoft.David"
        mock_voice.name = "Microsoft David"
        mock_voice.languages = ["en-US"]
        mock_voice.gender = "male"

        mock_engine = MagicMock()
        mock_engine.getProperty.return_value = [mock_voice]

        with patch("app.features.ai.voice.tts_service._engine", mock_engine), \
             patch("app.features.ai.voice.tts_service._tts_ready", True):
            resp = client.get("/api/voice/voices")
        assert resp.status_code == 200
        voices_data = resp.json()
        assert "voices" in voices_data
        assert "count" in voices_data


# ── Test 4: Voice status returns correct loaded state ────────────────────────
def test_voice_status_returns_loaded_state():
    """
    get_status() should reflect real module-level state.
    When model is loaded, loaded=True; when not, loaded=False.
    """
    import app.features.ai.voice.whisper_stt_service as stt_mod
    import app.features.ai.voice.tts_service as tts_mod

    # Test: not loaded state
    orig_loaded = stt_mod._model_loaded
    orig_loading = stt_mod._model_loading
    orig_size = stt_mod._model_size

    try:
        stt_mod._model_loaded = False
        stt_mod._model_loading = False
        stt_mod._model_size = "base"

        from app.features.ai.voice.whisper_stt_service import get_status
        status = get_status()
        assert status["loaded"] is False
        assert status["loading"] is False
        assert status["model_size"] == "base"

        # Test: loaded state
        stt_mod._model_loaded = True
        stt_mod._model_loading = False
        stt_mod._model_size = "small"

        status = get_status()
        assert status["loaded"] is True
        assert status["model_size"] == "small"

    finally:
        stt_mod._model_loaded = orig_loaded
        stt_mod._model_loading = orig_loading
        stt_mod._model_size = orig_size

    # Test: TTS not ready
    orig_tts_ready = tts_mod._tts_ready
    try:
        tts_mod._tts_ready = False
        from app.features.ai.voice.tts_service import get_tts_status
        tts_status = get_tts_status()
        assert tts_status["ready"] is False

        tts_mod._tts_ready = True
        tts_status = get_tts_status()
        assert tts_status["ready"] is True
    finally:
        tts_mod._tts_ready = orig_tts_ready
