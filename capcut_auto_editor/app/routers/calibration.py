"""기준 드래프트에서 내 스타일을 읽어 오는 단계."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import load_settings
from ..services.capcut_draft import (DraftNotFound, calibrate, list_drafts, list_profiles,
                                     load_profile, save_profile)
from ..services.logging_util import get_logger
from ..services.session import SESSIONS
from .common import get_session, ok, require_step

router = APIRouter(prefix="/api/calibration", tags=["calibration"])
log = get_logger("calibration")


@router.get("/profiles")
def profiles() -> Dict[str, Any]:
    names = list_profiles()
    return {
        "profiles": names,
        "details": {n: (load_profile(n).to_dict() if load_profile(n) else None) for n in names},
    }


@router.get("/candidates")
def candidate_drafts() -> Dict[str, Any]:
    """캘리브레이션 기준으로 삼을 만한 기존 드래프트 목록."""
    settings = load_settings()
    if not settings.draft_folder:
        raise HTTPException(status_code=409, detail="캡컷 드래프트 폴더를 먼저 설정해 주세요.")
    return {"drafts": list_drafts(settings.draft_folder)}


class CalibrateRequest(BaseModel):
    draft_name: str
    profile_name: str = "default"


@router.post("/run")
def run_calibration(req: CalibrateRequest) -> Dict[str, Any]:
    """사용자가 캡컷에서 직접 꾸민 드래프트를 읽어 스타일 기준값을 뽑는다."""
    settings = load_settings()
    if not settings.draft_folder:
        raise HTTPException(status_code=409, detail="캡컷 드래프트 폴더를 먼저 설정해 주세요.")
    try:
        profile = calibrate(settings.draft_folder, req.draft_name)
    except DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"드래프트를 읽지 못했습니다: {exc}") from exc

    save_profile(profile, req.profile_name)
    warning = None
    if profile.sampled_texts == 0:
        warning = ("이 드래프트에 자막이 없어 캔버스 크기만 가져왔습니다. "
                   "자막 스타일까지 맞추려면 캡컷에서 자막을 하나 만든 뒤 다시 실행해 주세요.")
    return ok(profile=profile.to_dict(), warning=warning)


class ApplyRequest(BaseModel):
    profile_name: str = "default"


@router.post("/{session_id}/apply")
def apply_to_session(session_id: str, req: ApplyRequest) -> Dict[str, Any]:
    session = get_session(session_id)
    require_step(session, "calibration")

    profile = load_profile(req.profile_name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"프로파일이 없습니다: {req.profile_name}")

    session.invalidate_from("calibration")
    session.complete("calibration", profile_name=req.profile_name, profile=profile.to_dict())
    SESSIONS.save(session)
    return ok(profile=profile.to_dict())


@router.post("/{session_id}/skip")
def skip(session_id: str) -> Dict[str, Any]:
    """캘리브레이션 없이 기본 설정값으로 진행한다."""
    session = get_session(session_id)
    require_step(session, "calibration")
    session.invalidate_from("calibration")
    session.complete("calibration", profile_name=None, skipped=True)
    SESSIONS.save(session)
    return ok(skipped=True)
