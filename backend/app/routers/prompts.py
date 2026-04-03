from __future__ import annotations

import difflib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.records import Project, PromptVersion

router = APIRouter(prefix="/v1/prompts", tags=["prompts"])


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


@router.post("", response_model=PromptResponse, status_code=201)
async def create_prompt_version(body: PromptCreate, db: AsyncSession = Depends(get_db)):
    """Commit a new version of a prompt."""
    await _ensure_project(db, body.project)

    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.project == body.project, PromptVersion.prompt_name == body.prompt_name)
        .order_by(PromptVersion.version.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    next_version = (latest.version + 1) if latest else 1

    pv = PromptVersion(
        project=body.project,
        prompt_name=body.prompt_name,
        version=next_version,
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


@router.get("", response_model=list[PromptResponse])
async def list_prompt_versions(
    project: str = Query(...),
    prompt_name: str = Query(...),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
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
):
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

    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    return PromptDiffResponse(
        prompt_name=prompt_name,
        version_a=version_a,
        version_b=version_b,
        diff_lines=diff,
        additions=additions,
        deletions=deletions,
    )


@router.get("/{version_id}", response_model=PromptResponse)
async def get_prompt_version(version_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PromptVersion).where(PromptVersion.id == version_id))
    pv = result.scalar_one_or_none()
    if not pv:
        raise HTTPException(404, f"Prompt version {version_id} not found")
    return pv
