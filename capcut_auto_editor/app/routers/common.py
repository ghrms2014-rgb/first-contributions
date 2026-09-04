"""라우터가 함께 쓰는 도구."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from ..services.session import SESSIONS, Session, StepLocked


def get_session(session_id: str) -> Session:
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"세션을 찾을 수 없습니다: {session_id}")
    return session


def require_step(session: Session, step: str) -> None:
    try:
        session.require(step)
    except StepLocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def ok(**payload: Any) -> Dict[str, Any]:
    return {"ok": True, **payload}
