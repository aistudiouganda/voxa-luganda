"""
AI Model Manager — lazy loads speech models on demand.
Works on CPU with small models for development.
Scales to GPU + large models in production.
"""
import logging
import asyncio
import numpy as np
from typing import Optional, Dict, Any

from core.config import settings

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self):
        self._whisper = None
        self._translator = None
        self._diarizer = None
        self._ready = False
        self._loading = False

    async def initialize(self):
        """Non-blocking startup — models load lazily on first use."""
        logger.info(f"Model manager ready (device={settings.WHISPER_DEVICE}, model={settings.WHISPER_MODEL_SIZE})")
        self._ready = True

    def _get_whisper(self):
        """Lazy-load Whisper on first transcription request."""
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
                logger.info(f"Loading Whisper {settings.WHISPER_MODEL_SIZE} on {settings.WHISPER_DEVICE}...")
                self._whisper = WhisperModel(
                    settings.WHISPER_MODEL_SIZE,
                    device=settings.WHISPER_DEVICE,
                    compute_type=settings.WHISPER_COMPUTE_TYPE,
                    download_root="./models/whisper",
                    cpu_threads=4,
                )
                logger.info("Whisper loaded successfully")
            except Exception as e:
                logger.error(f"Whisper failed to load: {e}")
                raise RuntimeError(f"Could not load Whisper model: {e}")
        return self._whisper

    def transcribe_file(
        self,
        audio_path: str,
        language: str = "lug",
        num_speakers: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Transcribe an audio file and return segments with timestamps."""
        whisper = self._get_whisper()

        # Whisper has no native Luganda support — use auto-detect (None)
        lang_code = None if language in ("lug", "luganda", "lg") else language

        segments_iter, info = whisper.transcribe(
            audio_path,
            language=lang_code,
            task="transcribe",
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        segments = list(segments_iter)

        return {
            "segments": [
                {
                    "id": f"seg_{i}",
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "text": seg.text.strip(),
                    "words": [
                        {"word": w.word, "start": round(w.start, 3),
                         "end": round(w.end, 3), "probability": round(w.probability, 3)}
                        for w in (seg.words or [])
                    ],
                    "confidence": round(float(np.mean(
                        [w.probability for w in (seg.words or [])] or [0.9]
                    )), 3),
                }
                for i, seg in enumerate(segments)
            ],
            "language": info.language,
            "duration": round(info.duration, 2),
            "text": " ".join(seg.text.strip() for seg in segments),
        }

    def transcribe_chunk(
        self,
        audio_bytes: bytes,
        language: str = "lug",
        sample_rate: int = 16000,
    ) -> Dict[str, Any]:
        """Transcribe a raw PCM chunk for live streaming."""
        whisper = self._get_whisper()
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        lang_code = None if language in ("lug", "luganda", "lg") else language

        segments_iter, info = whisper.transcribe(
            audio,
            language=lang_code,
            task="transcribe",
            beam_size=3,
            vad_filter=True,
        )
        segments = list(segments_iter)
        text = " ".join(s.text for s in segments).strip()
        return {"text": text, "language": info.language, "confidence": 0.9}

    def translate(self, text: str, src_lang: str = "lug_Latn", tgt_lang: str = "eng_Latn") -> str:
        """Translate Luganda text to English."""
        if not text.strip():
            return ""

        # Try Helsinki-NLP model (lighter weight than NLLB-200)
        try:
            if self._translator is None:
                from transformers import pipeline
                logger.info(f"Loading translation model {settings.TRANSLATION_MODEL}...")
                self._translator = pipeline(
                    "translation",
                    model=settings.TRANSLATION_MODEL,
                    device=-1,  # CPU
                )
                logger.info("Translation model loaded")
            result = self._translator(text, max_length=512)
            return result[0].get("translation_text", "")
        except Exception as e:
            logger.warning(f"Translation failed: {e} — returning empty")
            return ""

    def diarize(self, audio_path: str, num_speakers: Optional[int] = None) -> list:
        """Speaker diarization — uses pyannote if HF_TOKEN provided, else returns empty."""
        if not settings.HF_TOKEN:
            logger.info("No HF_TOKEN — skipping speaker diarization")
            return []
        try:
            if self._diarizer is None:
                from pyannote.audio import Pipeline
                self._diarizer = Pipeline.from_pretrained(
                    settings.DIARIZATION_MODEL,
                    use_auth_token=settings.HF_TOKEN,
                )
            params = {}
            if num_speakers:
                params["num_speakers"] = num_speakers
            diarization = self._diarizer(audio_path, **params)
            return [
                {"start": turn.start, "end": turn.end, "speaker": speaker}
                for turn, _, speaker in diarization.itertracks(yield_label=True)
            ]
        except Exception as e:
            logger.warning(f"Diarization failed: {e}")
            return []

    def apply_noise_reduction(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        """Apply noisereduce as lightweight noise filter."""
        try:
            import noisereduce as nr
            return nr.reduce_noise(y=audio, sr=sample_rate, stationary=False, prop_decrease=0.75)
        except Exception as e:
            logger.warning(f"Noise reduction failed: {e}")
            return audio

    def status(self) -> Dict[str, str]:
        return {
            "whisper": "loaded" if self._whisper else "not_loaded",
            "translator": "loaded" if self._translator else "not_loaded",
            "diarizer": "loaded" if self._diarizer else "not_loaded",
            "device": settings.WHISPER_DEVICE,
            "model_size": settings.WHISPER_MODEL_SIZE,
            "ready": str(self._ready),
        }

    async def cleanup(self):
        logger.info("Model manager cleanup complete")


model_manager = ModelManager()
