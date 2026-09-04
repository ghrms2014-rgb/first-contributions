"""세션 만들기, 원본 영상 고르기, 진행 상태 보기."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import load_settings
from ..services.audio_analysis import FFmpegMissing
from ..services.logging_util import get_logger
from ..services.session import SESSIONS, STEPS
from ..services.sources import SourceTimeline
from .common import get_session, ok, require_step

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
log = get_logger("sessions")


class CreateRequest(BaseModel):
    name: str = ""


@router.get("")
def list_sessions() -> Dict[str, Any]:
    return {"sessions": SESSIONS.list(), "steps": STEPS}


@router.post("")
def create_session(req: CreateRequest) -> Dict[str, Any]:
    session = SESSIONS.create(req.name)
    # 설정 단계는 앱 전역 설정이 끝나 있으면 통과로 본다
    settings = load_settings()
    if settings.draft_folder and Path(settings.draft_folder).is_dir():
        session.complete("setup", draft_folder=settings.draft_folder)
        SESSIONS.save(session)
    log.info("세션 생성: %s", session.id)
    return ok(session=session.to_dict())


@router.get("/{session_id}")
def read_session(session_id: str) -> Dict[str, Any]:
    return get_session(session_id).to_dict()


@router.delete("/{session_id}")
def delete_session(session_id: str) -> Dict[str, Any]:
    if not SESSIONS.delete(session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return ok(deleted=session_id)


class SourcesRequest(BaseModel):
    paths: List[str]


@router.post("/{session_id}/sources")
def set_sources(session_id: str, req: SourcesRequest) -> Dict[str, Any]:
    """원본 영상들을 순서대로 이어 소스 타임라인을 만든다."""
    session = get_session(session_id)
    require_step(session, "sources")

    missing = [p for p in req.paths if not Path(p).exists()]
    if missing:
        raise HTTPException(status_code=400, detail=f"파일이 없습니다: {', '.join(missing[:3])}")
    if not req.paths:
        raise HTTPException(status_code=400, detail="영상을 한 개 이상 선택해 주세요.")

    try:
        timeline = SourceTimeline.from_paths(req.paths)
    except FFmpegMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not timeline.clips:
        raise HTTPException(status_code=400, detail="읽을 수 있는 영상이 없습니다.")

    session.invalidate_from("sources")  # 원본이 바뀌면 뒤 단계는 모두 다시
    session.complete("sources", timeline=timeline.to_dict())
    SESSIONS.save(session)
    return ok(timeline=timeline.to_dict())


class ReorderRequest(BaseModel):
    order: List[int]


@router.post("/{session_id}/reorder")
def reorder_sources(session_id: str, req: ReorderRequest) -> Dict[str, Any]:
    session = get_session(session_id)
    raw = (session.data.get("sources") or {}).get("timeline")
    if not raw:
        raise HTTPException(status_code=409, detail="먼저 원본 영상을 선택해 주세요.")

    timeline = SourceTimeline.from_dict(raw)
    if sorted(req.order) != sorted(c.index for c in timeline.clips):
        raise HTTPException(status_code=400, detail="순서 목록이 현재 클립과 맞지 않습니다.")

    timeline = timeline.reorder(req.order)
    session.invalidate_from("sources")
    session.complete("sources", timeline=timeline.to_dict())
    SESSIONS.save(session)
    return ok(timeline=timeline.to_dict())


@router.get("/{session_id}/timeline")
def read_timeline(session_id: str) -> Dict[str, Any]:
    session = get_session(session_id)
    raw = (session.data.get("sources") or {}).get("timeline")
    if not raw:
        raise HTTPException(status_code=404, detail="아직 소스 타임라인이 없습니다.")
    return raw
