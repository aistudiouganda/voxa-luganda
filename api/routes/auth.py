"""Authentication routes — register, login, token."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from core.database import get_db
from models.db_models import User
from models.schemas import UserCreate, TokenResponse
from api.middleware.auth import create_access_token, get_password_hash, verify_password

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        email=body.email,
        hashed_password=get_password_hash(body.password),
        full_name=body.full_name,
        organization=body.organization,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, token_type="bearer", user_id=user.id)


@router.post("/token", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": user.id, "email": user.email})
    return TokenResponse(access_token=token, token_type="bearer", user_id=user.id)


@router.get("/me")
async def me_info():
    """Public endpoint — confirm API is reachable."""
    return {"status": "API is running", "version": "1.0.0"}
