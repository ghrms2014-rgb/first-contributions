"""폴더 탐색과 경로 판정."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
TEXT_EXT = {".txt", ".md", ".srt", ".vtt"}


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def is_video(path: os.PathLike | str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


def is_audio(path: os.PathLike | str) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXT


def describe(path: Path) -> Dict[str, Any]:
    try:
        stat = path.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        size, mtime = 0, 0.0
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "kind": "dir" if path.is_dir() else kind_of(path),
        "size": size,
        "mtime": mtime,
    }


def list_dir(path: str | Path, kinds: Optional[Iterable[str]] = None,
             show_hidden: bool = False) -> Dict[str, Any]:
    """한 폴더의 내용을 (폴더 먼저, 이름순) 나열한다."""
    p = Path(path).expanduser()
    if not p.is_dir():
        raise NotADirectoryError(f"폴더가 아닙니다: {p}")

    wanted = set(kinds) if kinds else None
    entries: List[Dict[str, Any]] = []
    with os.scandir(p) as it:
        for entry in it:
            if not show_hidden and entry.name.startswith("."):
                continue
            info = describe(Path(entry.path))
            if wanted and not info["is_dir"] and info["kind"] not in wanted:
                continue
            entries.append(info)

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p), "parent": parent, "entries": entries}


def collect_media(path: str | Path, kinds: Iterable[str] = ("video",),
                  recursive: bool = False) -> List[Dict[str, Any]]:
    """폴더에서 원하는 종류의 파일만 모아 이름순으로 돌려준다."""
    p = Path(path).expanduser()
    wanted = set(kinds)
    it = p.rglob("*") if recursive else p.glob("*")
    files = [describe(f) for f in it if f.is_file() and kind_of(f) in wanted]
    files.sort(key=lambda e: e["name"].lower())
    return files


def home_shortcuts() -> List[Dict[str, str]]:
    """UI 왼쪽에 띄울 기본 위치들."""
    home = Path.home()
    cands = [("홈", home), ("바탕화면", home / "Desktop"), ("문서", home / "Documents"),
             ("다운로드", home / "Downloads"), ("동영상", home / "Videos"),
             ("Movies", home / "Movies")]
    return [{"label": label, "path": str(p)} for label, p in cands if p.is_dir()]


def unique_path(path: Path) -> Path:
    """같은 이름이 있으면 ` (2)`, ` (3)` … 을 붙여 겹치지 않게."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    n = 2
    while True:
        cand = parent / f"{stem} ({n}){suffix}"
        if not cand.exists():
            return cand
        n += 1
