from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import generate_api_key
from ..db import get_db
from ..models.records import ApiKey, Project

router = APIRouter(prefix="/v1/keys", tags=["api keys"])


class ApiKeyCreate(BaseModel):
    project: str
    name: str = "default"


class ApiKeyResponse(BaseModel):
    id: str
    project: str
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyResponse):
    raw_key: str  # Only returned once at creation


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(body: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    """Create a new API key for a project. Raw key is returned only once."""
    result = await db.execute(select(Project).where(Project.name == body.project))
    project = result.scalar_one_or_none()
    if not project:
        project = Project(name=body.project)
        db.add(project)
        await db.flush()

    raw_key, hashed = generate_api_key()
    key = ApiKey(tier="free", project=body.project, key_hash=hashed, name=body.name)
    db.add(key)
    await db.flush()
    await db.refresh(key)

    return ApiKeyCreateResponse(
        id=key.id,
        project=key.project,
        name=key.name,
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        raw_key=raw_key,
    )


@router.get("/{project}", response_model=list[ApiKeyResponse])
async def list_api_keys(project: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiKey).where(ApiKey.project == project).order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(key_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, f"API key {key_id} not found")
    key.is_active = False
    await db.flush()