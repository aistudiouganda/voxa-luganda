"""Export endpoints — generate and download transcript files."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.db_models import Transcript
from models.schemas import ExportRequest
from services.export_service import (
    generate_txt, generate_srt, generate_vtt,
    generate_docx, generate_pdf, generate_json
)
from api.middleware.auth import get_current_user
from models.db_models import User

router = APIRouter()

CONTENT_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "srt": "text/plain; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "json": "application/json; charset=utf-8",
}


@router.post("/{transcript_id}")
async def export_transcript(
    transcript_id: str,
    request: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Transcript).where(
            Transcript.id == transcript_id,
            Transcript.user_id == current_user.id,
            Transcript.status == "completed",
        )
    )
    tr = result.scalar_one_or_none()
    if not tr:
        raise HTTPException(404, "Transcript not found or not yet complete")

    segments = tr.segments_json or []
    fmt = request.format

    generators = {
        "txt": lambda: generate_txt(segments, request.include_translation),
        "srt": lambda: generate_srt(segments, request.use_translation_as_primary),
        "vtt": lambda: generate_vtt(segments, request.use_translation_as_primary),
        "docx": lambda: generate_docx(segments, tr.title, request.include_translation),
        "pdf": lambda: generate_pdf(segments, tr.title),
        "json": lambda: generate_json(segments, {"title": tr.title, "id": transcript_id}),
    }

    content = generators[fmt]()
    filename = f"{(tr.title or 'transcript').replace(' ', '_')[:50]}.{fmt}"

    return Response(
        content=content,
        media_type=CONTENT_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
