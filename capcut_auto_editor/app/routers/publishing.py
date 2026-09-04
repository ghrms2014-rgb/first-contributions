"""마케팅 문구, 산출물 내려받기, 백업 관리."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ..config import load_settings
from ..services.capcut_draft import list_backups, restore_backup
from ..services.logging_util import get_logger
from ..services.prompt_builder import PLATFORMS, TONES, PromptSpec, build_prompt, build_summary_prompt
from ..services.script_align import load_cues, to_srt
from ..services.session import SESSIONS
from .common import get_session, ok, require_step

router = APIRouter(prefix="/api/publishing", tags=["publishing"])
log = get_logger("publishing")


@router.get("/options")
def options() -> Dict[str, Any]:
    return {
        "platforms": [{"key": k, **v} for k, v in PLATFORMS.items()],
        "tones": [{"key": k, "label": v} for k, v in TONES.items()],
    }


class PromptRequest(BaseModel):
    platform: str = "youtube"
    tone: str = "friendly"
    keywords: List[str] = Field(default_factory=list)
    audience: str = ""
    cta: str = ""
    extra: str = ""
    video_title: str = ""


@router.post("/{session_id}/prompt")
def make_prompt(session_id: str, req: PromptRequest) -> Dict[str, Any]:
    """자막을 바탕으로 마케팅 문구 프롬프트를 만든다. LLM 에 그대로 붙여 넣으면 된다."""
    session = get_session(session_id)
    require_step(session, "publish")

    cues = load_cues(session.work_dir / "cues_edited.json") or \
        load_cues(session.work_dir / "cues_source.json")
    if not cues:
        raise HTTPException(status_code=409, detail="자막이 없습니다. 자막 생성 단계를 먼저 마쳐 주세요.")

    duration = float((session.data.get("build") or {}).get("duration")
                     or (session.data.get("edit") or {}).get("edited_duration") or 0.0)

    spec = PromptSpec(platform=req.platform, tone=req.tone, keywords=req.keywords,
                      audience=req.audience, cta=req.cta, extra=req.extra)
    prompt = build_prompt(cues, spec, video_title=req.video_title, duration_sec=duration)

    (session.work_dir / "marketing_prompt.txt").write_text(prompt, encoding="utf-8")
    session.complete("publish", platform=req.platform, tone=req.tone)
    SESSIONS.save(session)

    return ok(prompt=prompt, summary_prompt=build_summary_prompt(cues), chars=len(prompt))


@router.get("/{session_id}/srt", response_class=PlainTextResponse)
def download_srt(session_id: str, edited: bool = True) -> str:
    session = get_session(session_id)
    name = "cues_edited.json" if edited else "cues_source.json"
    cues = load_cues(session.work_dir / name)
    if not cues:
        raise HTTPException(status_code=404, detail="자막이 없습니다.")
    return to_srt(cues)


@router.get("/{session_id}/srt/file")
def download_srt_file(session_id: str):
    session = get_session(session_id)
    path = session.work_dir / "subtitle.srt"
    if not path.exists():
        raise HTTPException(status_code=404, detail="SRT 파일이 아직 없습니다.")
    return FileResponse(path, media_type="text/plain; charset=utf-8",
                        filename=f"{session.name}.srt")


# ------------------------------------------------------------------------ 백업

@router.get("/backups")
def backups(draft: Optional[str] = None) -> Dict[str, Any]:
    return {"backups": list_backups(draft)}


class RestoreRequest(BaseModel):
    backup: str


@router.post("/backups/restore")
def restore(req: RestoreRequest) -> Dict[str, Any]:
    settings = load_settings()
    if not settings.draft_folder:
        raise HTTPException(status_code=409, detail="캡컷 드래프트 폴더를 먼저 설정해 주세요.")
    try:
        path = restore_backup(settings.draft_folder, req.backup)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok(restored=str(path))
