"""드래프트 읽기·쓰기·백업·캘리브레이션·레이어 교정."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import PATHS
from .logging_util import get_logger

log = get_logger("draft")

# 캡컷 버전마다 파일 이름이 조금씩 다르다. 있는 것부터 쓴다.
CONTENT_FILES = ("draft_content.json", "draft_info.json")

# 화면에 그려지는 트랙이 쌓이는 순서. 숫자가 클수록 위에 그려진다.
LAYER_ORDER = {"video": 0, "filter": 1, "adjust": 2, "effect": 3, "sticker": 4, "text": 5}
# 소리만 내는 트랙. 쌓이는 순서와 무관하므로 render_index 를 건드리지 않는다.
NON_VISUAL = {"audio"}


class DraftNotFound(FileNotFoundError):
    def __init__(self, name: str) -> None:
        super().__init__(f"드래프트를 찾을 수 없습니다: {name}")
        self.name = name


# ------------------------------------------------------------------ 읽기 / 쓰기

def draft_dir(root: str | Path, name: str) -> Path:
    d = Path(root) / name
    if not d.is_dir():
        raise DraftNotFound(name)
    return d


def content_path(draft: Path) -> Path:
    for fname in CONTENT_FILES:
        p = draft / fname
        if p.exists():
            return p
    raise DraftNotFound(f"{draft.name} (draft_content.json 없음)")


def list_drafts(root: str | Path) -> List[Dict[str, Any]]:
    """드래프트 폴더 목록. 최근 수정순."""
    r = Path(root)
    if not r.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for d in r.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        try:
            cp = content_path(d)
        except DraftNotFound:
            continue
        out.append({
            "name": d.name,
            "path": str(d),
            "mtime": cp.stat().st_mtime,
            "size": cp.stat().st_size,
        })
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def read_draft(root: str | Path, name: str) -> Dict[str, Any]:
    p = content_path(draft_dir(root, name))
    return json.loads(p.read_text(encoding="utf-8"))


def write_draft(root: str | Path, name: str, content: Dict[str, Any], *,
                backup: bool = True) -> Path:
    """드래프트를 덮어쓴다. 기본적으로 먼저 백업을 뜬다."""
    d = draft_dir(root, name)
    p = content_path(d)
    if backup:
        backup_draft(root, name)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)  # 쓰다 죽어도 원본이 반쪽 나지 않게
    log.info("드래프트 저장: %s", name)
    return p


# ---------------------------------------------------------------------- 백업

def backup_draft(root: str | Path, name: str) -> Optional[Path]:
    """드래프트 폴더를 backups/ 아래 타임스탬프 폴더로 복사한다."""
    try:
        d = draft_dir(root, name)
    except DraftNotFound:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = PATHS.backups / f"{name}__{stamp}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(d, dst, dirs_exist_ok=True)
    log.info("백업 생성: %s", dst.name)
    return dst


def list_backups(name: Optional[str] = None) -> List[Dict[str, Any]]:
    PATHS.backups.mkdir(parents=True, exist_ok=True)
    out: List[Dict[str, Any]] = []
    for d in PATHS.backups.iterdir():
        if not d.is_dir():
            continue
        draft_name = d.name.split("__", 1)[0]
        if name and draft_name != name:
            continue
        out.append({"backup": d.name, "draft": draft_name,
                    "path": str(d), "mtime": d.stat().st_mtime})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def restore_backup(root: str | Path, backup_name: str) -> Path:
    """백업을 원래 드래프트 자리로 되돌린다."""
    src = PATHS.backups / backup_name
    if not src.is_dir():
        raise FileNotFoundError(f"백업이 없습니다: {backup_name}")
    draft_name = backup_name.split("__", 1)[0]
    dst = Path(root) / draft_name
    if dst.exists():
        backup_draft(root, draft_name)  # 되돌리기 전 현재 상태도 남긴다
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    log.info("백업 복원: %s → %s", backup_name, draft_name)
    return dst


# ------------------------------------------------------------------ 캘리브레이션

@dataclass
class CalibrationProfile:
    """사용자가 손으로 만든 드래프트에서 뽑아낸 '내 스타일' 기준값."""
    source_draft: str = ""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    text_size: Optional[float] = None
    text_color: Optional[List[float]] = None
    text_transform_y: Optional[float] = None
    text_transform_x: Optional[float] = None
    font: Optional[str] = None
    track_order: List[str] = field(default_factory=list)
    sampled_texts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "CalibrationProfile":
        known = set(cls().to_dict())
        return cls(**{k: v for k, v in raw.items() if k in known})


def _iter_segments(content: Dict[str, Any], track_type: str):
    for track in content.get("tracks", []) or []:
        if track.get("type") != track_type:
            continue
        for seg in track.get("segments", []) or []:
            yield track, seg


def calibrate(root: str | Path, name: str) -> CalibrationProfile:
    """기준 드래프트에서 캔버스/자막 스타일/트랙 순서를 읽어 온다.

    사용자가 캡컷에서 자막 하나를 원하는 모양으로 만들어 두면,
    자동 생성 자막이 같은 크기·위치·색으로 나오게 하는 게 목적이다.
    """
    content = read_draft(root, name)
    canvas = content.get("canvas_config", {}) or {}

    profile = CalibrationProfile(
        source_draft=name,
        width=int(canvas.get("width") or 1080),
        height=int(canvas.get("height") or 1920),
        fps=int(content.get("fps") or 30),
        track_order=[t.get("type", "?") for t in content.get("tracks", []) or []],
    )

    materials = content.get("materials", {}) or {}
    texts = {m.get("id"): m for m in materials.get("texts", []) or []}

    sizes: List[float] = []
    colors: List[List[float]] = []
    xs: List[float] = []
    ys: List[float] = []
    fonts: List[str] = []

    for _track, seg in _iter_segments(content, "text"):
        clip = seg.get("clip", {}) or {}
        transform = clip.get("transform", {}) or {}
        if "x" in transform:
            xs.append(float(transform["x"]))
        if "y" in transform:
            ys.append(float(transform["y"]))

        mat = texts.get(seg.get("material_id"))
        if not mat:
            continue
        profile.sampled_texts += 1
        try:
            payload = json.loads(mat.get("content") or "{}")
        except json.JSONDecodeError:
            continue
        for style in payload.get("styles", []) or []:
            if "size" in style:
                sizes.append(float(style["size"]))
            fill = ((style.get("fill") or {}).get("content") or {}).get("solid") or {}
            if fill.get("color"):
                colors.append([float(v) for v in fill["color"][:3]])
            font = (style.get("font") or {}).get("id") or mat.get("font_name")
            if font:
                fonts.append(str(font))

    def _median(vals: List[float]) -> Optional[float]:
        if not vals:
            return None
        s = sorted(vals)
        return s[len(s) // 2]

    profile.text_size = _median(sizes)
    profile.text_transform_x = _median(xs)
    profile.text_transform_y = _median(ys)
    profile.text_color = colors[0] if colors else None
    profile.font = fonts[0] if fonts else None

    log.info("캘리브레이션 완료: %s (%dx%d, 자막 %d개 참조)",
             name, profile.width, profile.height, profile.sampled_texts)
    return profile


def save_profile(profile: CalibrationProfile, name: str = "default") -> Path:
    PATHS.profiles.mkdir(parents=True, exist_ok=True)
    p = PATHS.profiles / f"{name}.json"
    p.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_profile(name: str = "default") -> Optional[CalibrationProfile]:
    p = PATHS.profiles / f"{name}.json"
    if not p.exists():
        return None
    try:
        return CalibrationProfile.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def list_profiles() -> List[str]:
    PATHS.profiles.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in PATHS.profiles.glob("*.json"))


# ----------------------------------------------------------------- 레이어 교정

def fix_layers(content: Dict[str, Any]) -> Dict[str, Any]:
    """트랙이 뒤죽박죽 쌓여 자막이 영상 뒤로 가는 일을 막는다.

    같은 종류 안에서는 원래 순서를 지키고, 종류끼리만 정해진 순서로 다시 쌓는다.
    오디오처럼 화면에 안 나오는 트랙은 순서만 앞으로 모으고 render_index 는 손대지 않는다.
    """
    tracks = content.get("tracks", []) or []
    if not tracks:
        return content

    audio = [t for t in tracks if t.get("type") in NON_VISUAL]
    visual = [t for t in tracks if t.get("type") not in NON_VISUAL]
    visual.sort(key=lambda t: LAYER_ORDER.get(t.get("type", ""), 99))

    for index, track in enumerate(visual):
        track["render_index"] = index
        for seg in track.get("segments", []) or []:
            seg["render_index"] = index

    content["tracks"] = audio + visual
    log.info("레이어 교정: %s (오디오 %d개는 그대로)",
             " < ".join(t.get("type", "?") for t in visual), len(audio))
    return content


def apply_profile_to_text(content: Dict[str, Any], profile: CalibrationProfile) -> Dict[str, Any]:
    """생성된 드래프트의 자막을 캘리브레이션 값으로 맞춘다."""
    materials = content.get("materials", {}) or {}
    texts = {m.get("id"): m for m in materials.get("texts", []) or []}
    touched = 0

    for _track, seg in _iter_segments(content, "text"):
        clip = seg.setdefault("clip", {})
        transform = clip.setdefault("transform", {})
        if profile.text_transform_x is not None:
            transform["x"] = profile.text_transform_x
        if profile.text_transform_y is not None:
            transform["y"] = profile.text_transform_y

        mat = texts.get(seg.get("material_id"))
        if not mat:
            continue
        try:
            payload = json.loads(mat.get("content") or "{}")
        except json.JSONDecodeError:
            continue
        changed = False
        for style in payload.get("styles", []) or []:
            if profile.text_size is not None:
                style["size"] = profile.text_size
                changed = True
            if profile.text_color is not None:
                fill = style.setdefault("fill", {}).setdefault("content", {}).setdefault("solid", {})
                fill["color"] = list(profile.text_color)
                changed = True
        if changed:
            mat["content"] = json.dumps(payload, ensure_ascii=False)
            touched += 1

    log.info("캘리브레이션 적용: 자막 %d개", touched)
    return content
