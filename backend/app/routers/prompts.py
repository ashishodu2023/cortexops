from __future__ import annotations

import difflib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_key_info
from ..db import get_db, retry_on_integrity_error
from ..models.records import Project, PromptVersion
from ..tiers import TierInfo, require_scope

router = APIRouter(prefix="/v1/prompts", tags=["prompts"])

PROMPT_VERSION_ATTEMPTS = 5


class PromptCreate(BaseModel):
    project: str
    prompt_name: str
    content: str
    model: str = ""
    temperature: float = 0.7
    commit_message: str = ""
    author: str = ""


class PromptResponse(BaseModel):
    id: str
    project: str
    prompt_name: str
    version: int
    content: str
    model: str
    temperature: float
    parent_version_id: str | None
    commit_message: str
    author: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PromptDiffResponse(BaseModel):
    prompt_name: str
    version_a: int
    version_b: int
    diff_lines: list[str]
    additions: int
    deletions: int


async def _ensure_project(db: AsyncSession, name: str) -> Project:
    result = await db.execute(select(Project).where(Project.name == name))
    project = result.scalar_one_or_none()
    if not project:
        project = Project(name=name)
        db.add(project)
        await db.flush()
    return project


async def latest_prompt_version(db: AsyncSession, project: str, prompt_name: str) -> PromptVersion | None:
    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.project == project, PromptVersion.prompt_name == prompt_name)
        .order_by(PromptVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("", response_model=PromptResponse, status_code=201, responses={
    409: {"description": "Concurrent commits to the same prompt kept conflicting — retry"},
})
async def create_prompt_version(
    body: PromptCreate,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """Commit a new version of a prompt.

    Version numbers are allocated as latest + 1 and guarded by a unique index on
    (project, prompt_name, version); a concurrent commit that takes the number first makes
    this one retry with the next number.
    """
    require_scope(tier_info, "read_write")
    if tier_info.project != body.project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only commit prompts for your own project.")

    async def _attempt() -> PromptVersion:
        await _ensure_project(db, body.project)
        latest = await latest_prompt_version(db, body.project, body.prompt_name)
        pv = PromptVersion(
            project=body.project,
            prompt_name=body.prompt_name,
            version=(latest.version + 1) if latest else 1,
            content=body.content,
            model=body.model,
            temperature=body.temperature,
            parent_version_id=latest.id if latest else None,
            commit_message=body.commit_message,
            author=body.author,
        )
        db.add(pv)
        await db.flush()
        await db.refresh(pv)
        return pv

    try:
        return await retry_on_integrity_error(
            db, _attempt, attempts=PROMPT_VERSION_ATTEMPTS, what=f"prompt version {body.project}/{body.prompt_name}",
        )
    except IntegrityError:
        raise HTTPException(409, "Concurrent commits to this prompt kept conflicting — retry the request.") from None


@router.get("/catalog", response_model=list[PromptResponse])
async def list_project_prompts(
    project: str = Query(...),
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """Latest version of each prompt in a project."""
    if tier_info.project != project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only list prompts for your own project.")

    latest = (
        select(
            PromptVersion.prompt_name,
            func.max(PromptVersion.version).label("max_version"),
        )
        .where(PromptVersion.project == project)
        .group_by(PromptVersion.prompt_name)
        .subquery()
    )
    result = await db.execute(
        select(PromptVersion)
        .join(
            latest,
            (PromptVersion.prompt_name == latest.c.prompt_name)
            & (PromptVersion.version == latest.c.max_version)
            & (PromptVersion.project == project),
        )
        .order_by(PromptVersion.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("", response_model=list[PromptResponse])
async def list_prompt_versions(
    project: str = Query(...),
    prompt_name: str = Query(...),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    if tier_info.project != project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only list prompts for your own project.")
    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.project == project, PromptVersion.prompt_name == prompt_name)
        .order_by(PromptVersion.version.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/diff", response_model=PromptDiffResponse)
async def diff_prompt_versions(
    project: str = Query(...),
    prompt_name: str = Query(...),
    version_a: int = Query(...),
    version_b: int = Query(...),
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    if tier_info.project != project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only diff prompts in your own project.")
    async def _get(v: int) -> PromptVersion:
        r = await db.execute(
            select(PromptVersion).where(
                PromptVersion.project == project,
                PromptVersion.prompt_name == prompt_name,
                PromptVersion.version == v,
            )
        )
        record = r.scalar_one_or_none()
        if not record:
            raise HTTPException(404, f"Version {v} of {prompt_name} not found")
        return record

    pv_a = await _get(version_a)
    pv_b = await _get(version_b)

    lines_a = pv_a.content.splitlines(keepends=True)
    lines_b = pv_b.content.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=f"{prompt_name} v{version_a}",
        tofile=f"{prompt_name} v{version_b}",
        lineterm="",
    ))

    additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

    return PromptDiffResponse(
        prompt_name=prompt_name,
        version_a=version_a,
        version_b=version_b,
        diff_lines=diff,
        additions=additions,
        deletions=deletions,
    )


@router.get("/{version_id}", response_model=PromptResponse)
async def get_prompt_version(
    version_id: str,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    result = await db.execute(select(PromptVersion).where(PromptVersion.id == version_id))
    pv = result.scalar_one_or_none()
    if not pv:
        raise HTTPException(404, f"Prompt version {version_id} not found")
    if tier_info.project != pv.project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only view prompts in your own project.")
    return pv
