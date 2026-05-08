"""SQLAlchemy ORM models."""
from sqlalchemy import String, Boolean, Float, Integer, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    organization: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    plan: Mapped[str] = mapped_column(String, default="free")
    usage_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    usage_limit_minutes: Mapped[float] = mapped_column(Float, default=60.0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transcripts: Mapped[list["Transcript"]] = relationship("Transcript", back_populates="user", lazy="noload")
    vocabulary: Mapped[list["CustomVocabularyEntry"]] = relationship("CustomVocabularyEntry", back_populates="user", lazy="noload")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_format: Mapped[str | None] = mapped_column(String, nullable=True)
    source_language: Mapped[str] = mapped_column(String, default="lug")
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    noise_reduction_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    segments_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="transcripts", lazy="noload")


class CustomVocabularyEntry(Base):
    __tablename__ = "vocabulary_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    phonetic: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String, default="lug")
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User | None"] = relationship("User", back_populates="vocabulary", lazy="noload")
