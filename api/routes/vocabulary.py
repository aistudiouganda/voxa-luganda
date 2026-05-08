"""Custom vocabulary management — Ugandan names, places, orgs."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from core.database import get_db
from models.db_models import CustomVocabularyEntry, User
from models.schemas import VocabularyEntryCreate
from api.middleware.auth import get_current_user

router = APIRouter()

UGANDAN_VOCABULARY = {
    "names": ["Museveni", "Ssebuliba", "Namukasa", "Kiwanuka", "Ssempebwa",
               "Nakiganda", "Mugisha", "Mbabazi", "Tumwesigye", "Asiimwe",
               "Nantume", "Kayiira", "Ssemwogerere", "Lukwago", "Besigye"],
    "places": ["Kampala", "Entebbe", "Jinja", "Gulu", "Mbarara", "Mbale",
                "Makerere", "Kololo", "Nakasero", "Kabalagala", "Kibuli",
                "Ntinda", "Kansanga", "Namirembe", "Nakulabye", "Bwaise",
                "Mukono", "Masaka", "Fort Portal", "Kasese", "Soroti", "Lira", "Arua"],
    "organizations": ["NRM", "NUP", "FDC", "UPDF", "URA", "KCCA", "NWSC", "UMEME",
                       "Bank of Uganda", "UBC", "NTV Uganda", "Bukedde",
                       "Daily Monitor", "New Vision"],
    "slang": ["ayi", "naye", "abakadde", "omwana", "omuntu",
               "wano", "nkwagala", "webale", "gyebale"],
}


@router.get("/")
async def list_vocabulary(
    category: str = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(CustomVocabularyEntry).where(
        (CustomVocabularyEntry.user_id == current_user.id) |
        (CustomVocabularyEntry.is_global == True)
    )
    if category:
        query = query.where(CustomVocabularyEntry.category == category)
    result = await db.execute(query)
    entries = result.scalars().all()
    return {
        "user_entries": [
            {"id": e.id, "word": e.word, "category": e.category, "language": e.language}
            for e in entries
        ],
        "global_vocabulary": UGANDAN_VOCABULARY,
    }


@router.post("/")
async def add_vocabulary(
    entry: VocabularyEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_entry = CustomVocabularyEntry(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        word=entry.word,
        phonetic=entry.phonetic,
        language=entry.language,
        category=entry.category,
    )
    db.add(new_entry)
    await db.commit()
    return {"id": new_entry.id, "word": new_entry.word, "status": "added"}
