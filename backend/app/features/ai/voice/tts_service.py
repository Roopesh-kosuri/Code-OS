"""
tts_service.py — Offline text-to-speech service using pyttsx3.
Generates WAV audio bytes from text. No external API calls.
"""

from __future__ import annotations

import io
import logging
import tempfile
import threading
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Singleton engine ─────────────────────────────────────────────────────────
_engine = None
_engine_lock = threading.Lock()
_tts_ready: bool = False
_selected_voice: Optional[str] = None
_speech_rate: int = 175
_speech_volume: float = 1.0


def init_tts(
    voice: str = "default",
    rate: int = 175,
    volume: float = 1.0,
) -> bool:
    """
    Initialize the pyttsx3 TTS engine (thread-safe singleton).
    Returns True if engine is ready.
    """
    global _engine, _tts_ready, _selected_voice, _speech_rate, _speech_volume

    if _tts_ready and _engine is not None:
        return True

    with _engine_lock:
        if _tts_ready and _engine is not None:
            return True

        try:
            import pyttsx3

            _engine = pyttsx3.init()
            _engine.setProperty("rate", rate)
            _engine.setProperty("volume", volume)
            _speech_rate = rate
            _speech_volume = volume

            # Set voice if specified
            if voice and voice != "default":
                voices = _engine.getProperty("voices")
                for v in (voices or []):
                    if voice.lower() in (v.name or "").lower() or voice == v.id:
                        _engine.setProperty("voice", v.id)
                        _selected_voice = v.id
                        break

            _tts_ready = True
            logger.info("[voice.tts] pyttsx3 engine initialized OK")
            return True

        except Exception as e:
            _tts_ready = False
            logger.error(f"[voice.tts] Failed to init pyttsx3: {e}")
            return False


def get_tts_status() -> dict:
    """Return current TTS engine status."""
    return {"ready": _tts_ready, "voice": _selected_voice, "rate": _speech_rate}


def list_voices() -> List[dict]:
    """
    List all available TTS voices on the system.
    Returns [{id, name, language, gender}]
    """
    global _engine

    if not _tts_ready:
        init_tts()

    if not _tts_ready or _engine is None:
        return []

    try:
        voices = _engine.getProperty("voices") or []
        result = []
        for v in voices:
            # pyttsx3 voice object attributes vary by platform
            result.append({
                "id": getattr(v, "id", ""),
                "name": getattr(v, "name", "Unknown"),
                "language": getattr(v, "languages", ["en"])[0] if getattr(v, "languages", None) else "en",
                "gender": getattr(v, "gender", "unknown"),
            })
        return result
    except Exception as e:
        logger.error(f"[voice.tts] list_voices error: {e}")
        return []


def set_voice(voice_name: str) -> bool:
    """
    Set the active TTS voice by name or ID.
    Returns True if voice was found and set.
    """
    global _engine, _selected_voice

    if not _tts_ready:
        init_tts()

    if not _tts_ready or _engine is None:
        return False

    try:
        voices = _engine.getProperty("voices") or []
        for v in voices:
            if voice_name.lower() in (v.name or "").lower() or voice_name == v.id:
                _engine.setProperty("voice", v.id)
                _selected_voice = v.id
                logger.info(f"[voice.tts] Set voice: {v.name}")
                return True
        logger.warning(f"[voice.tts] Voice not found: {voice_name}")
        return False
    except Exception as e:
        logger.error(f"[voice.tts] set_voice error: {e}")
        return False


def speak(text: str, voice: Optional[str] = None) -> bytes:
    """
    Generate WAV audio bytes from text using pyttsx3.
    Falls back to empty bytes if engine is unavailable (graceful degradation).
    
    Returns WAV bytes.
    """
    global _engine

    if not text or not text.strip():
        return b""

    # Auto-init if not done
    if not _tts_ready:
        if not init_tts():
            logger.warning("[voice.tts] Engine unavailable, returning silent fallback")
            return _make_silence_wav()

    if _engine is None:
        return _make_silence_wav()

    # Override voice for this call if specified
    if voice and voice != _selected_voice:
        set_voice(voice)

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        _engine.save_to_file(text.strip(), tmp_path)
        _engine.runAndWait()

        wav_bytes = Path(tmp_path).read_bytes()
        Path(tmp_path).unlink(missing_ok=True)

        logger.info(f"[voice.tts] Generated {len(wav_bytes)} bytes for text length {len(text)}")
        return wav_bytes

    except Exception as e:
        logger.error(f"[voice.tts] speak() error: {e}")
        return _make_silence_wav()


def _make_silence_wav(duration_ms: int = 500) -> bytes:
    """
    Generate a minimal silent WAV file as graceful fallback.
    44 bytes header + silence samples.
    """
    try:
        import struct
        import numpy as np
        import soundfile as sf

        buf = io.BytesIO()
        silence = np.zeros(int(16000 * duration_ms / 1000), dtype=np.float32)
        sf.write(buf, silence, 16000, format="WAV", subtype="PCM_16")
        return buf.getvalue()
    except Exception:
        # Minimal valid 44-byte WAV header for empty PCM
        return (
            b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00"
            b"\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00"
            b"data\x00\x00\x00\x00"
        )
