"""
Transcription pipeline — runs in-process for local dev, Celery for production.
"""
import asyncio
import logging
import os
import tempfile
import time
import uuid
import numpy as np
from typing import Optional, Dict, Any
from pathlib import Path

from core.config import settings
from models.schemas import ProcessingOptions

logger = logging.getLogger(__name__)


async def submit_transcription_job(
    transcript_id: str,
    audio_path: str,
    options: ProcessingOptions,
) -> object:
    """
    Submit a transcription job.
    - In development: runs directly in a background thread.
    - In production: delegates to Celery worker.
    """
    # Check if Redis/Celery is available
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        r.ping()
        celery_available = True
    except Exception:
        celery_available = False

    if celery_available:
        try:
            from celery import Celery
            celery_app = Celery(broker=settings.REDIS_URL, backend=settings.REDIS_URL)
            task = celery_app.send_task(
                "services.transcription_pipeline.transcribe_audio_task",
                kwargs={"transcript_id": transcript_id, "audio_path": audio_path, "options": options.model_dump()},
                queue="transcription",
            )

            class TaskRef:
                id = task.id
            return TaskRef()
        except Exception as e:
            logger.warning(f"Celery unavailable ({e}), running inline")

    # Run inline (development mode)
    asyncio.create_task(_run_pipeline_inline(transcript_id, audio_path, options))

    class FakeTask:
        id = f"local-{uuid.uuid4()}"
    return FakeTask()


async def _run_pipeline_inline(
    transcript_id: str,
    audio_path: str,
    options: ProcessingOptions,
):
    """Run the full transcription pipeline in an asyncio task (dev mode)."""
    from core.database import AsyncSessionLocal
    from models.db_models import Transcript

    async def update_status(status: str, progress: float, **kwargs):
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(Transcript).where(Transcript.id == transcript_id))
            tr = result.scalar_one_or_none()
            if tr:
                tr.status = status
                tr.progress_pct = progress
                for k, v in kwargs.items():
                    setattr(tr, k, v)
                await db.commit()

    try:
        from services.model_manager import model_manager
        import librosa
        import soundfile as sf

        start_time = time.time()

        # Step 1 — Load and preprocess audio
        await update_status("preprocessing", 10.0)
        logger.info(f"[{transcript_id}] Loading audio: {audio_path}")
        audio, sr = librosa.load(audio_path, sr=16000, mono=True)
        duration = len(audio) / sr
        logger.info(f"[{transcript_id}] Duration: {duration:.1f}s")

        # Noise reduction
        if options.noise_reduction:
            await update_status("preprocessing", 20.0)
            logger.info(f"[{transcript_id}] Applying noise reduction...")
            audio = await asyncio.get_event_loop().run_in_executor(
                None, model_manager.apply_noise_reduction, audio, sr
            )

        # Normalize
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio)) * 0.95

        # Write preprocessed file
        processed_path = audio_path + "_processed.wav"
        sf.write(processed_path, audio, sr)
        await update_status("preprocessing", 30.0)

        # Step 2 — Speaker diarization
        diarization = []
        if options.speaker_diarization:
            await update_status("transcribing", 35.0)
            logger.info(f"[{transcript_id}] Running speaker diarization...")
            diarization = await asyncio.get_event_loop().run_in_executor(
                None, model_manager.diarize, processed_path, options.num_speakers
            )

        # Step 3 — ASR transcription
        await update_status("transcribing", 40.0)
        logger.info(f"[{transcript_id}] Running Whisper ASR...")
        asr_result = await asyncio.get_event_loop().run_in_executor(
            None, model_manager.transcribe_file, processed_path, options.source_language
        )
        await update_status("transcribing", 70.0)

        # Step 4 — Assign speakers
        segments = _assign_speakers(asr_result["segments"], diarization)

        # Step 5 — Translation
        if options.translate_to_english:
            await update_status("translating", 75.0)
            logger.info(f"[{transcript_id}] Translating {len(segments)} segments...")
            for seg in segments:
                text = seg.get("text", "").strip()
                if text:
                    seg["translation"] = await asyncio.get_event_loop().run_in_executor(
                        None, model_manager.translate, text
                    )
                    seg["language"] = _detect_code_switch(text)

        await update_status("translating", 90.0)

        # Step 6 — Finalize
        full_luganda = " ".join(s["text"] for s in segments)
        full_english = " ".join(s.get("translation", "") for s in segments)
        num_speakers = len(set(s.get("speaker", 0) for s in segments))
        word_count = len(full_luganda.split())
        avg_confidence = float(np.mean([s.get("confidence", 0.9) for s in segments]))
        elapsed = time.time() - start_time

        await update_status(
            "completed", 100.0,
            segments_json=segments,
            full_text_luganda=full_luganda,
            full_text_english=full_english,
            num_speakers=num_speakers,
            word_count=word_count,
            accuracy_score=round(avg_confidence * 100, 2),
            duration_seconds=round(duration, 2),
            processing_time_seconds=round(elapsed, 2),
            model_versions={"whisper": settings.WHISPER_MODEL_SIZE},
        )
        logger.info(f"[{transcript_id}] Completed in {elapsed:.1f}s")

    except Exception as e:
        logger.error(f"[{transcript_id}] Pipeline failed: {e}", exc_info=True)
        await update_status("failed", 0.0, error_message=str(e))
    finally:
        # Cleanup temp files
        for path in [audio_path, audio_path + "_processed.wav"]:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass


def _assign_speakers(segments: list, diarization: list) -> list:
    speaker_map = {}
    counter = 0
    for seg in segments:
        if not diarization:
            seg["speaker"] = 0
            seg["speakerLabel"] = "Speaker 1"
            continue
        best_speaker, best_overlap = None, 0.0
        for turn in diarization:
            overlap = min(seg["end"], turn["end"]) - max(seg["start"], turn["start"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]
        if best_speaker and best_speaker not in speaker_map:
            speaker_map[best_speaker] = counter
            counter += 1
        idx = speaker_map.get(best_speaker, 0)
        seg["speaker"] = idx
        seg["speakerLabel"] = f"Speaker {idx + 1}"
    return segments


def _detect_code_switch(text: str) -> str:
    english_markers = {"the", "and", "is", "are", "was", "were", "has", "have", "that", "this", "it", "but", "so"}
    words = text.lower().split()
    if not words:
        return "luganda"
    english_count = sum(1 for w in words if w in english_markers)
    ratio = english_count / len(words)
    if ratio > 0.5:
        return "english"
    elif ratio > 0.05:
        return "mixed"
    return "luganda"
