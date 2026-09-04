"""폴더 탐색과 파일 선택."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services import native_picker
from ..services.audio_analysis import FFmpegMissing, probe
from ..services.filesystem import collect_media, home_shortcuts, list_dir
from ..services.logging_util import get_logger
from .common import ok

router = APIRouter(prefix="/api/files", tags=["files"])
log = get_logger("files")


@router.get("/shortcuts")
def shortcuts() -> Dict[str, Any]:
    return {"shortcuts": home_shortcuts(), "picker": native_picker.available()}


@router.get("/list")
def browse(path: str = Query(...), kinds: Optional[str] = None,
           show_hidden: bool = False) -> Dict[str, Any]:
    wanted = [k.strip() for k in kinds.split(",")] if kinds else None
    try:
        return list_dir(path, kinds=wanted, show_hidden=show_hidden)
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"접근 권한이 없습니다: {path}") from exc


@router.get("/media")
def media(path: str = Query(...), recursive: bool = False,
          kinds: str = "video") -> Dict[str, Any]:
    wanted = [k.strip() for k in kinds.split(",")]
    try:
        files = collect_media(path, kinds=wanted, recursive=recursive)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": path, "files": files, "count": len(files)}


class PickRequest(BaseModel):
    mode: str = "files"           # folder | file | files
    title: str = ""
    initial: str = ""


@router.post("/pick")
def pick(req: PickRequest) -> Dict[str, Any]:
    """윈도우 기본 선택 창을 띄운다. 서버와 브라우저가 같은 PC 일 때만 의미가 있다."""
    if not native_picker.available():
        raise HTTPException(status_code=501,
                            detail="이 환경에서는 기본 선택 창을 쓸 수 없습니다. 경로를 직접 입력해 주세요.")
    if req.mode == "folder":
        picked = native_picker.pick_folder(req.title or "폴더 선택", req.initial)
        paths = [picked] if picked else []
    elif req.mode == "file":
        picked = native_picker.pick_file(req.title or "파일 선택", req.initial)
        paths = [picked] if picked else []
    else:
        paths = native_picker.pick_files(req.title or "영상 파일 선택", req.initial)
    return ok(paths=paths, cancelled=not paths)


class ProbeRequest(BaseModel):
    paths: List[str]


@router.post("/probe")
def probe_files(req: ProbeRequest) -> Dict[str, Any]:
    """선택한 파일들의 길이·해상도·오디오 유무를 미리 확인한다."""
    results: List[Dict[str, Any]] = []
    for p in req.paths:
        if not Path(p).exists():
            results.append({"path": p, "error": "파일이 없습니다"})
            continue
        try:
            results.append(probe(p).to_dict())
        except FFmpegMissing as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            results.append({"path": p, "error": str(exc)})

    total = sum(r.get("duration", 0.0) for r in results if "error" not in r)
    return {"files": results, "total_duration": total,
            "errors": [r for r in results if "error" in r]}
