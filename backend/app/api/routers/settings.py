from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import get_settings, reset_settings_overrides, update_settings
from app.models import User

router = APIRouter()


class SettingsPatch(BaseModel):
    class Config:
        extra = "allow"


@router.get("/settings")
async def read_settings():
    return get_settings().model_dump()


@router.patch("/settings")
async def patch_settings(patch: SettingsPatch, user: User = Depends(get_current_user)):
    try:
        updated = update_settings(patch.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return updated.model_dump()


@router.post("/settings/reset")
async def reset_settings(user: User = Depends(get_current_user)):
    return reset_settings_overrides().model_dump()
