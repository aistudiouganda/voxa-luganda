"""Application configuration with environment variable support."""
from pydantic_settings import BaseSettings
from typing import Optional, List
import secrets
import os


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Voxa Luganda API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = secrets.token_urlsafe(32)
    API_V1_PREFIX: str = "/api/v1"

    # CORS — allow localhost for local dev + production domains
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "https://voxaluganda.ai",
        "https://voxa-luganda.vercel.app",
    ]

    # Database — SQLite for local dev, PostgreSQL for production
    # To use PostgreSQL: set DATABASE_URL=postgresql+asyncpg://user:pass@host/db
    DATABASE_URL: str = "sqlite+aiosqlite:///./voxa_luganda.db"
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 5

    # Redis — optional, used by Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Storage — defaults to local filesystem
    STORAGE_BACKEND: str = "local"  # "local" | "s3" | "cloudinary"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = "voxa-luganda-audio"
    S3_CDN_URL: Optional[str] = None
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    LOCAL_STORAGE_PATH: str = "./voxa-audio-storage"

    # AI Models — use small/base models for local dev, large for production
    WHISPER_MODEL_SIZE: str = "base"   # "tiny" | "base" | "small" | "large-v3"
    WHISPER_DEVICE: str = "cpu"        # "cpu" | "cuda"
    WHISPER_COMPUTE_TYPE: str = "int8" # "int8" | "float16" | "float32"
    LUGANDA_MODEL_PATH: Optional[str] = None
    TRANSLATION_MODEL: str = "Helsinki-NLP/opus-mt-lug-en"  # Lighter than NLLB
    DIARIZATION_MODEL: str = "pyannote/speaker-diarization-3.1"
    NOISE_REDUCTION_MODEL: str = "noisereduce"

    # Hugging Face token (required for pyannote diarization)
    HF_TOKEN: Optional[str] = None

    # Processing limits
    MAX_AUDIO_DURATION_HOURS: float = 4.0
    MAX_FILE_SIZE_MB: int = 200  # 200MB for local dev
    CHUNK_DURATION_SECONDS: int = 30
    MAX_SPEAKERS: int = 8

    # Monitoring
    SENTRY_DSN: Optional[str] = None

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

# Create local storage directory
os.makedirs(settings.LOCAL_STORAGE_PATH, exist_ok=True)
