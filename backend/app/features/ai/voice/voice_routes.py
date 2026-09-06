"""
voice_routes.py — FastAPI router for Voice Mode endpoints.
Handles Whisper STT transcription + pyttsx3 TTS speech synthesis.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .whisper_stt_service import (
    get_status as get_whisper_status,
    init_whisper,
    transcribe_audio,
)
from .tts_service import (
    get_tts_status,
    init_tts,
    list_voices,
    set_voice,
    speak,
)

logger = logging.getLogger(__name__)

voice_router = APIRouter(prefix="/api/voice", tags=["voice"])


# ── Request / Response models ────────────────────────────────────────────────

class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None


class VoiceStatusResponse(BaseModel):
    whisper_loaded: bool
    whisper_loading: bool
    whisper_model_size: str
    tts_ready: bool
    tts_voice: str | None


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str
    gender: str


class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration_s: float
    confidence: float
    segments: list
    error: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@voice_router.get("/status", response_model=VoiceStatusResponse)
async def voice_status():
    """
    Return current loading state of Whisper STT and pyttsx3 TTS engines.
    """
    whisper = get_whisper_status()
    tts = get_tts_status()
    return VoiceStatusResponse(
        whisper_loaded=whisper["loaded"],
        whisper_loading=whisper["loading"],
        whisper_model_size=whisper["model_size"],
        tts_ready=tts["ready"],
        tts_voice=tts.get("voice"),
    )


@voice_router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(
    audio: UploadFile = File(...),
    language: str | None = Form(None),
):
    """
    POST multipart/form-data with `audio` file.
    Transcribes the uploaded audio using Whisper STT running locally.
    Supported formats: wav, mp3, webm, ogg, flac, m4a.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # Detect format from content-type or filename
    content_type = audio.content_type or ""
    filename = audio.filename or ""
    fmt = "wav"

    if "webm" in content_type or filename.endswith(".webm"):
        fmt = "webm"
    elif "mpeg" in content_type or "mp3" in content_type or filename.endswith(".mp3"):
        fmt = "mp3"
    elif "ogg" in content_type or filename.endswith(".ogg"):
        fmt = "ogg"
    elif "flac" in content_type or filename.endswith(".flac"):
        fmt = "flac"
    elif "mp4" in content_type or "m4a" in content_type or filename.endswith(".m4a"):
        fmt = "m4a"

    logger.info(f"[voice.transcribe] Received {len(audio_bytes)} bytes, format={fmt}")

    result = transcribe_audio(audio_bytes, fmt=fmt, language=language or None)
    return TranscribeResponse(**result)


@voice_router.post("/speak")
async def speak_endpoint(body: SpeakRequest):
    """
    POST {text, voice?} → returns audio/wav bytes.
    Synthesizes speech offline using pyttsx3.
    """
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    wav_bytes = speak(body.text.strip(), voice=body.voice)

    if not wav_bytes:
        # Graceful: return empty 200 rather than 500
        return Response(content=b"", media_type="audio/wav")

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "Content-Length": str(len(wav_bytes)),
            "X-Voice-Text-Length": str(len(body.text)),
        },
    )


@voice_router.get("/voices")
async def list_voices_endpoint():
    """
    Return all available TTS voices on the current system.
    """
    if not get_tts_status()["ready"]:
        init_tts()
    voices = list_voices()
    return {"voices": voices, "count": len(voices)}


@voice_router.post("/voices/set")
async def set_voice_endpoint(body: dict):
    """
    POST {voice_name} → sets the active TTS voice.
    """
    voice_name = body.get("voice_name", "")
    if not voice_name:
        raise HTTPException(status_code=400, detail="voice_name is required")
    ok = set_voice(voice_name)
    return {"ok": ok, "voice_name": voice_name}


@voice_router.post("/init")
async def init_voice_endpoint(body: dict):
    """
    Trigger model initialization. model_size: tiny|base|small|medium|large.
    Returns immediately; model loads in background thread.
    """
    model_size = body.get("model_size", "base")
    import threading

    def _load():
        init_whisper(model_size)
        init_tts()

    t = threading.Thread(target=_load, daemon=True)
    t.start()

    return {"ok": True, "message": f"Loading Whisper {model_size} + TTS in background"}
