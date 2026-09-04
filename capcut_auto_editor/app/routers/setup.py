"""설치 상태 확인, 설정, 용어 사전."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import (PATHS, Settings, detect_draft_folder, detect_ffmpeg,
                      load_dictionary, load_settings, save_dictionary, save_settings)
from ..services.capcut_draft import list_drafts
from ..services.logging_util import get_logger
from .common import ok

router = APIRouter(prefix="/api/setup", tags=["setup"])
log = get_logger("setup")


def _whisper_ready() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


@router.get("/status")
def status() -> Dict[str, Any]:
    """첫 화면에서 '무엇이 준비됐고 무엇이 빠졌는지' 보여 준다."""
    settings = load_settings()
    ff = detect_ffmpeg()
    draft = settings.draft_folder or (str(detect_draft_folder() or "") or None)

    checks: List[Dict[str, Any]] = [
        {
            "key": "draft_folder", "label": "캡컷 드래프트 폴더",
            "ok": bool(draft and Path(draft).is_dir()),
            "value": draft or "찾지 못함",
            "hint": "캡컷을 한 번이라도 실행해 프로젝트를 만든 뒤 다시 확인하거나, 폴더를 직접 지정해 주세요.",
        },
        {
            "key": "ffmpeg", "label": "ffmpeg",
            "ok": bool(ff["ffmpeg"] and ff["ffprobe"]),
            "value": ff["ffmpeg"] or "찾지 못함",
            "hint": "ffmpeg 을 설치하고 PATH 에 추가해 주세요. 오디오 분석과 무음 감지에 필요합니다.",
        },
        {
            "key": "whisper", "label": "faster-whisper",
            "ok": _whisper_ready(),
            "value": "설치됨" if _whisper_ready() else "설치되지 않음",
            "hint": "pip install faster-whisper 로 설치하면 자동 자막을 쓸 수 있습니다.",
        },
        {
            "key": "assets", "label": "에셋 폴더",
            "ok": PATHS.sfx.is_dir() and PATHS.bg.is_dir(),
            "value": f"효과음 {len(list(PATHS.sfx.glob('*')))}개 · 배경음 {len(list(PATHS.bg.glob('*')))}개",
            "hint": "assets/sfx, assets/bg 폴더에 원하는 소리 파일을 넣어 두세요.",
        },
    ]

    return {
        "ready": all(c["ok"] for c in checks if c["key"] in ("draft_folder", "ffmpeg")),
        "checks": checks,
        "settings": settings.to_dict(),
        "paths": {k: str(v) for k, v in vars(PATHS).items()} or {},
    }


@router.get("/settings")
def get_settings() -> Dict[str, Any]:
    return load_settings().to_dict()


class SettingsPatch(BaseModel):
    model_config = {"extra": "ignore"}

    draft_folder: Optional[str] = None
    draft_name_prefix: Optional[str] = None
    width: Optional[int] = Field(default=None, ge=16, le=8192)
    height: Optional[int] = Field(default=None, ge=16, le=8192)
    fps: Optional[int] = Field(default=None, ge=1, le=240)
    silence_db: Optional[float] = Field(default=None, ge=-90, le=0)
    min_silence_sec: Optional[float] = Field(default=None, ge=0.05, le=10)
    keep_padding_sec: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    subtitle_max_chars: Optional[int] = Field(default=None, ge=4, le=60)
    subtitle_min_dur_sec: Optional[float] = Field(default=None, ge=0.1, le=10)
    subtitle_font_size: Optional[float] = Field(default=None, ge=1, le=50)
    whisper_model: Optional[str] = None
    whisper_language: Optional[str] = None
    whisper_chunk_sec: Optional[int] = Field(default=None, ge=60, le=3600)
    whisper_compute_type: Optional[str] = None


@router.post("/settings")
def patch_settings(patch: SettingsPatch) -> Dict[str, Any]:
    settings = load_settings()
    changes = patch.model_dump(exclude_none=True)

    folder = changes.get("draft_folder")
    if folder and not Path(folder).is_dir():
        raise HTTPException(status_code=400, detail=f"폴더가 없습니다: {folder}")

    for key, value in changes.items():
        setattr(settings, key, value)
    save_settings(settings)
    log.info("설정 변경: %s", ", ".join(changes) or "(없음)")
    return ok(settings=settings.to_dict())


@router.post("/detect-draft-folder")
def redetect() -> Dict[str, Any]:
    found = detect_draft_folder()
    if not found:
        raise HTTPException(status_code=404, detail="캡컷 드래프트 폴더를 찾지 못했습니다. 직접 지정해 주세요.")
    settings = load_settings()
    settings.draft_folder = str(found)
    save_settings(settings)
    return ok(draft_folder=str(found))


@router.get("/drafts")
def drafts() -> Dict[str, Any]:
    settings = load_settings()
    if not settings.draft_folder:
        return {"drafts": [], "root": None}
    return {"drafts": list_drafts(settings.draft_folder), "root": settings.draft_folder}


@router.get("/dictionary")
def get_dictionary() -> Dict[str, str]:
    return load_dictionary()


class DictionaryPayload(BaseModel):
    entries: Dict[str, str]


@router.post("/dictionary")
def put_dictionary(payload: DictionaryPayload) -> Dict[str, Any]:
    cleaned = {k.strip(): v.strip() for k, v in payload.entries.items() if k.strip()}
    save_dictionary(cleaned)
    log.info("용어 사전 저장: %d개", len(cleaned))
    return ok(count=len(cleaned))


@router.get("/assets")
def assets() -> Dict[str, Any]:
    def listing(folder: Path) -> List[Dict[str, str]]:
        if not folder.is_dir():
            return []
        return [{"name": f.name, "path": str(f)}
                for f in sorted(folder.iterdir()) if f.is_file()]

    return {"sfx": listing(PATHS.sfx), "bg": listing(PATHS.bg)}
