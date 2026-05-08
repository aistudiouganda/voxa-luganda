"""User management endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.database import get_db
from models.db_models import User, Transcript
from models.schemas import UserResponse
from api.middleware.auth import get_current_user

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/me/stats")
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total = (await db.execute(
        select(func.count()).where(Transcript.user_id == current_user.id)
    )).scalar() or 0

    completed = (await db.execute(
        select(func.count()).where(
            Transcript.user_id == current_user.id,
            Transcript.status == "completed",
        )
    )).scalar() or 0

    total_secs = (await db.execute(
        select(func.sum(Transcript.duration_seconds)).where(
            Transcript.user_id == current_user.id,
            Transcript.status == "completed",
        )
    )).scalar() or 0

    avg_acc = (await db.execute(
        select(func.avg(Transcript.accuracy_score)).where(
            Transcript.user_id == current_user.id,
            Transcript.status == "completed",
        )
    )).scalar() or 0

    return {
        "total_transcripts": total,
        "completed_transcripts": completed,
        "total_duration_seconds": round(total_secs or 0, 1),
        "total_duration_hours": round((total_secs or 0) / 3600, 2),
        "avg_accuracy": round(avg_acc or 0, 2),
        "usage_minutes": current_user.usage_minutes,
        "usage_limit_minutes": current_user.usage_limit_minutes,
        "plan": current_user.plan,
    }
