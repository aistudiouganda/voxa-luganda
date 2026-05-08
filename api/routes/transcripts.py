"""Transcript CRUD and processing endpoints."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import Optional
import uuid
import os
import tempfile
import shutil

from core.database import get_db
from core.config import settings
from models.db_models import Transcript
from models.schemas import (
    TranscriptResponse, TranscriptListResponse,
    TranscriptUpdateRequest, ProcessingOptions
)
from services.storage import storage_service
from services.transcription_pipeline import submit_transcription_job
from api.middleware.auth import get_current_user
from models.db_models import User

router = APIRouter()

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/m4a",
    "audio/mp4", "audio/ogg", "audio/flac", "audio/webm", "audio/aac",
    "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo",
    "application/octet-stream",  # Some clients send this for any binary
}

MAX_FILE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024


@router.post("/", response_model=TranscriptResponse, status_code=201)
async def create_transcript(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    source_language: str = Form("lug"),
    noise_reduction: bool = Form(True),
    speaker_diarization: bool = Form(True),
    translate_to_english: bool = Form(True),
    num_speakers: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Read content
    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)")

    # Save to local temp storage
    transcript_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    storage_key = f"{current_user.id}/{transcript_id}/audio{ext}"
    audio_url = await storage_service.upload(content, storage_key, file.content_type or "audio/wav")

    # Save temp copy for immediate processing
    tmp_dir = os.path.join(settings.LOCAL_STORAGE_PATH, current_user.id, transcript_id)
    os.makedirs(tmp_dir, exist_ok=True)
    audio_path = os.path.join(tmp_dir, f"audio{ext}")
    with open(audio_path, "wb") as f:
        f.write(content)

    # Create DB record
    transcript = Transcript(
        id=transcript_id,
        user_id=current_user.id,
        title=title or (file.filename or "Untitled").rsplit(".", 1)[0],
        original_filename=file.filename,
        file_size_bytes=len(content),
        audio_url=audio_url,
        audio_format=file.content_type,
        source_language=source_language,
        status="queued",
        noise_reduction_applied=noise_reduction,
    )
    db.add(transcript)
    await db.flush()

    # Submit to pipeline
    options = ProcessingOptions(
        noise_reduction=noise_reduction,
        speaker_diarization=speaker_diarization,
        translate_to_english=translate_to_english,
        num_speakers=num_speakers,
        source_language=source_language,
    )
    task = await submit_transcription_job(transcript_id, audio_path, options)
    transcript.celery_task_id = task.id

    await db.commit()
    await db.refresh(transcript)
    return transcript


@router.get("/", response_model=TranscriptListResponse)
async def list_transcripts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Transcript).where(Transcript.user_id == current_user.id)
    if status:
        query = query.where(Transcript.status == status)
    if search:
        query = query.where(Transcript.title.ilike(f"%{search}%"))
    query = query.order_by(desc(Transcript.created_at))

    count_result = await db.execute(
        select(func.count()).select_from(
            select(Transcript).where(Transcript.user_id == current_user.id).subquery()
        )
    )
    total = count_result.scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(query.offset(offset).limit(per_page))
    transcripts = result.scalars().all()

    return {
        "items": transcripts,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/{transcript_id}", response_model=TranscriptResponse)
async def get_transcript(
    transcript_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Transcript).where(
            Transcript.id == transcript_id,
            Transcript.user_id == current_user.id,
        )
    )
    tr = result.scalar_one_or_none()
    if not tr:
        raise HTTPException(404, "Transcript not found")
    return tr


@router.get("/{transcript_id}/status")
async def get_status(
    transcript_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Transcript.status, Transcript.progress_pct, Transcript.error_message).where(
            Transcript.id == transcript_id,
            Transcript.user_id == current_user.id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Transcript not found")
    return {"status": row.status, "progress": row.progress_pct, "error": row.error_message}


@router.patch("/{transcript_id}", response_model=TranscriptResponse)
async def update_transcript(
    transcript_id: str,
    body: TranscriptUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Transcript).where(
            Transcript.id == transcript_id,
            Transcript.user_id == current_user.id,
        )
    )
    tr = result.scalar_one_or_none()
    if not tr:
        raise HTTPException(404, "Transcript not found")
    if body.title is not None:
        tr.title = body.title
    if body.segments_json is not None:
        tr.segments_json = body.segments_json
    await db.commit()
    await db.refresh(tr)
    return tr


@router.delete("/{transcript_id}", status_code=204)
async def delete_transcript(
    transcript_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Transcript).where(
            Transcript.id == transcript_id,
            Transcript.user_id == current_user.id,
        )
    )
    tr = result.scalar_one_or_none()
    if not tr:
        raise HTTPException(404, "Transcript not found")
    if tr.audio_url:
        await storage_service.delete(tr.audio_url)
    await db.delete(tr)
    await db.commit()
