"""Pydantic schemas for request/response validation."""
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Any
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    organization: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    organization: Optional[str] = None
    is_active: bool
    plan: str
    usage_minutes: float
    usage_limit_minutes: float

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str


class ProcessingOptions(BaseModel):
    noise_reduction: bool = True
    speaker_diarization: bool = True
    translate_to_english: bool = True
    num_speakers: Optional[int] = None
    source_language: str = "lug"


class TranscriptResponse(BaseModel):
    id: str
    user_id: str
    title: str
    original_filename: Optional[str] = None
    file_size_bytes: Optional[int] = None
    audio_url: Optional[str] = None
    audio_format: Optional[str] = None
    source_language: str
    status: str
    noise_reduction_applied: bool
    celery_task_id: Optional[str] = None
    segments_json: Optional[List[Any]] = None
    error_message: Optional[str] = None
    progress_pct: int
    duration_seconds: Optional[float] = None
    accuracy_score: Optional[float] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TranscriptListResponse(BaseModel):
    items: List[TranscriptResponse]
    total: int
    page: int
    per_page: int
    pages: int


class TranscriptUpdateRequest(BaseModel):
    title: Optional[str] = None
    segments_json: Optional[List[Any]] = None


class ExportRequest(BaseModel):
    format: str = "txt"
    include_translation: bool = True
    use_translation_as_primary: bool = False


class VocabularyEntryCreate(BaseModel):
    word: str
    phonetic: Optional[str] = None
    language: str = "lug"
    category: Optional[str] = None
