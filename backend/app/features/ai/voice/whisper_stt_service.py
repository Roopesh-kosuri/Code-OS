"""
whisper_stt_service.py — Local Whisper speech-to-text service using faster-whisper.
CPU-optimized. No external API calls. Model cached at ~/.cache/huggingface/hub/
"""

from __future__ import annotations

import io
import logging
import threading
import time
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional

logger = logging.getLogger(__name__)

# ── Module-level singleton ──────────────────────────────────────────────────
_model = None
_model_lock = threading.Lock()
_model_size: str = "base"
_model_loading: bool = False
_model_loaded: bool = False

SUPPORTED_FORMATS = {"wav", "mp3", "webm", "ogg", "flac", "m4a"}


def init_whisper(
    model_size: str = "base",
    progress_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Load the Whisper model on first use (thread-safe singleton).
    model_size: "tiny" | "base" | "small" | "medium" | "large"
    Returns True if model is loaded successfully.
    """
    global _model, _model_size, _model_loading, _model_loaded

    if _model_loaded and _model_size == model_size:
        return True

    with _model_lock:
        if _model_loaded and _model_size == model_size:
            return True

        _model_loading = True
        _model_size = model_size

        try:
            if progress_callback:
                progress_callback(f"Loading Whisper {model_size} model...")

            # Import here so module loads even if faster_whisper not installed
            from faster_whisper import WhisperModel

            logger.info(f"[voice.stt] Loading faster-whisper model: {model_size}")
            try:
                from app.core.config import get_settings
                models_dir = get_settings().data_dir / "models" / "whisper"
                models_dir.mkdir(parents=True, exist_ok=True)
                download_root_path = str(models_dir)
            except Exception:
                download_root_path = None

            _model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",  # CPU-optimized quantization
                download_root=download_root_path,
            )
            _model_loaded = True
            _model_loading = False

            if progress_callback:
                progress_callback(f"Whisper {model_size} model ready.")

            logger.info(f"[voice.stt] Whisper {model_size} loaded OK")
            return True

        except Exception as e:
            _model_loading = False
            _model_loaded = False
            logger.error(f"[voice.stt] Failed to load Whisper model: {e}")
            if progress_callback:
                progress_callback(f"Error loading model: {e}")
            return False


def get_status() -> dict:
    """Return current model loading status."""
    return {
        "loaded": _model_loaded,
        "loading": _model_loading,
        "model_size": _model_size,
    }


def transcribe_audio(
    audio_bytes: bytes,
    fmt: str = "wav",
    language: Optional[str] = None,
) -> dict:
    """
    Transcribe raw audio bytes (WAV/MP3/WebM/etc.) using the loaded Whisper model.

    Returns:
        {
            "text": str,
            "language": str,
            "duration_s": float,
            "confidence": float,   # avg. segment probability
            "segments": [{"start", "end", "text"}]
        }
    """
    global _model

    if not _model_loaded or _model is None:
        # Try to load on demand
        if not init_whisper(_model_size):
            return {
                "text": "",
                "language": "unknown",
                "duration_s": 0.0,
                "confidence": 0.0,
                "segments": [],
                "error": "Whisper model not loaded",
            }

    if fmt not in SUPPORTED_FORMATS:
        return {
            "text": "",
            "language": "unknown",
            "duration_s": 0.0,
            "confidence": 0.0,
            "segments": [],
            "error": f"Unsupported audio format: {fmt}",
        }

    try:
        import numpy as np
        import soundfile as sf

        # Decode audio bytes to numpy float32 array via soundfile
        buf = io.BytesIO(audio_bytes)
        audio_array, sample_rate = sf.read(buf, dtype="float32", always_2d=False)

        # If stereo, average channels to mono
        if audio_array.ndim == 2:
            audio_array = audio_array.mean(axis=1)

        # Resample to 16kHz if necessary (faster-whisper expects 16kHz)
        if sample_rate != 16000:
            import scipy.signal as signal
            num_samples = int(len(audio_array) * 16000 / sample_rate)
            audio_array = signal.resample(audio_array, num_samples)

        duration_s = len(audio_array) / 16000.0

        # Run transcription
        segments_gen, info = _model.transcribe(
            audio_array,
            language=language,
            beam_size=5,
            best_of=5,
            condition_on_previous_text=True,
        )

        segments = []
        full_text_parts = []
        total_prob = 0.0

        for seg in segments_gen:
            segments.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
            })
            full_text_parts.append(seg.text.strip())
            total_prob += getattr(seg, "avg_logprob", -0.5)

        text = " ".join(full_text_parts).strip()
        n_segs = len(segments) or 1
        # Convert avg logprob to 0-1 confidence estimate
        avg_logprob = total_prob / n_segs
        confidence = round(min(1.0, max(0.0, 1.0 + avg_logprob / 10.0)), 3)

        return {
            "text": text,
            "language": info.language if info else "en",
            "duration_s": round(duration_s, 2),
            "confidence": confidence,
            "segments": segments,
        }

    except Exception as e:
        logger.error(f"[voice.stt] transcription error: {e}")
        return {
            "text": "",
            "language": "unknown",
            "duration_s": 0.0,
            "confidence": 0.0,
            "segments": [],
            "error": str(e),
        }


async def stream_transcription(
    audio_bytes: bytes,
    fmt: str = "wav",
) -> AsyncGenerator[dict, None]:
    """
    Async generator yielding partial transcription chunks.
    Since faster-whisper produces segments, we yield each segment
    as it becomes available, simulating streaming.
    """
    global _model

    if not _model_loaded or _model is None:
        init_whisper(_model_size)

    if not _model_loaded or _model is None:
        yield {"partial": "", "done": True, "error": "Model not loaded"}
        return

    try:
        import numpy as np
        import soundfile as sf

        buf = io.BytesIO(audio_bytes)
        audio_array, sample_rate = sf.read(buf, dtype="float32", always_2d=False)
        if audio_array.ndim == 2:
            audio_array = audio_array.mean(axis=1)

        segments_gen, info = _model.transcribe(
            audio_array,
            language=None,
            beam_size=5,
        )

        accumulated = ""
        for seg in segments_gen:
            accumulated += " " + seg.text.strip()
            yield {
                "partial": accumulated.strip(),
                "done": False,
                "language": info.language if info else "en",
            }

        yield {
            "partial": accumulated.strip(),
            "done": True,
            "language": info.language if info else "en",
        }

    except Exception as e:
        logger.error(f"[voice.stt] stream error: {e}")
        yield {"partial": "", "done": True, "error": str(e)}
