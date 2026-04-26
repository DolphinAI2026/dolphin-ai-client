"""User-level 偏好设置 API (Phase F)"""
from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.preference import UserPreference

router = APIRouter(prefix="/me", tags=["preferences"])

VALID_MODES = {"simple", "pro"}


class UpdatePreferenceRequest(BaseModel):
    default_mode: str


def _to_dict(pref: UserPreference) -> dict:
    return {"user_id": pref.user_id, "default_mode": pref.default_mode}


@router.get("/preferences")
async def get_my_preferences(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user.id)
    )).scalar_one_or_none()
    if not pref:
        pref = UserPreference(user_id=ctx.user.id, default_mode="simple")
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return _to_dict(pref)


@router.put("/preferences")
async def put_my_preferences(
    req: UpdatePreferenceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if req.default_mode not in VALID_MODES:
        raise HTTPException(400, f"default_mode 仅支持 {sorted(VALID_MODES)}")
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user.id)
    )).scalar_one_or_none()
    if not pref:
        pref = UserPreference(user_id=ctx.user.id, default_mode=req.default_mode)
        db.add(pref)
    else:
        pref.default_mode = req.default_mode
    await db.commit()
    await db.refresh(pref)
    return _to_dict(pref)
