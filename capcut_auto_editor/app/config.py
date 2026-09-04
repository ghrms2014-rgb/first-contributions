"""경로 탐지, 설정, 사전."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "capcut_auto_editor"
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# ---------------------------------------------------------------- 프로젝트 경로

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    app: Path = ROOT / "app"
    static: Path = ROOT / "app" / "static"
    data: Path = ROOT / "data"
    sessions: Path = ROOT / "data" / "sessions"
    profiles: Path = ROOT / "data" / "profiles"
    backups: Path = ROOT / "backups"
    logs: Path = ROOT / "logs"
    docs: Path = ROOT / "docs"
    sfx: Path = ROOT / "assets" / "sfx"
    bg: Path = ROOT / "assets" / "bg"

    def ensure(self) -> None:
        for p in (self.data, self.sessions, self.profiles, self.backups,
                  self.logs, self.docs, self.sfx, self.bg):
            p.mkdir(parents=True, exist_ok=True)


PATHS = Paths()

SETTINGS_FILE = PATHS.data / "settings.json"
DICTIONARY_FILE = PATHS.data / "dictionary.json"

# ------------------------------------------------------- 캡컷 드래프트 폴더 탐지

def _candidate_draft_folders() -> List[Path]:
    """플랫폼별로 캡컷/剪映 드래프트 폴더 후보를 순서대로 돌려준다."""
    out: List[Path] = []
    if IS_WIN:
        local = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        for base in filter(None, [local, appdata]):
            for vendor in ("CapCut", "JianyingPro"):
                out.append(Path(base) / vendor / "User Data" / "Projects" / "com.lveditor.draft")
    elif IS_MAC:
        home = Path.home()
        for vendor in ("CapCut", "JianyingPro"):
            out.append(home / "Movies" / vendor / "User Data" / "Projects" / "com.lveditor.draft")
    else:
        # 리눅스에는 캡컷 정식 빌드가 없다. 개발/테스트용 경로만 본다.
        out.append(Path.home() / ".capcut" / "drafts")
    return out


def detect_draft_folder() -> Optional[Path]:
    """실제로 존재하는 첫 번째 드래프트 폴더. 없으면 None."""
    for cand in _candidate_draft_folders():
        if cand.is_dir():
            return cand
    return None


def detect_ffmpeg() -> Dict[str, Optional[str]]:
    """ffmpeg / ffprobe 실행 파일 경로. 없으면 None."""
    return {"ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe")}


# ------------------------------------------------------------------------ 설정

@dataclass
class Settings:
    draft_folder: Optional[str] = None          # 캡컷 드래프트 루트
    draft_name_prefix: str = "auto_"            # 생성할 드래프트 이름 접두어
    width: int = 1080
    height: int = 1920
    fps: int = 30

    # 무음 컷 편집
    silence_db: float = -35.0                   # 무음 판정 임계값(dBFS)
    min_silence_sec: float = 0.45               # 이보다 긴 무음만 컷 후보
    keep_padding_sec: float = 0.12              # 컷 앞뒤로 남길 여유

    # 자막
    subtitle_max_chars: int = 18                # 한 줄 최대 글자수
    subtitle_min_dur_sec: float = 0.7
    subtitle_font_size: float = 8.0

    # 전사
    whisper_model: str = "medium"
    whisper_language: str = "ko"
    whisper_chunk_sec: int = 600                # 청크 길이(재시작 단위)
    whisper_compute_type: str = "int8"

    # 캘리브레이션 결과(드래프트 좌표계 보정)
    calibration: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_settings() -> Settings:
    PATHS.ensure()
    data: Dict[str, Any] = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    known = {f for f in Settings().to_dict()}
    settings = Settings(**{k: v for k, v in data.items() if k in known})
    if not settings.draft_folder:
        found = detect_draft_folder()
        settings.draft_folder = str(found) if found else None
    return settings


def save_settings(settings: Settings) -> None:
    PATHS.ensure()
    SETTINGS_FILE.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ------------------------------------------------------------------- 용어 사전

DEFAULT_DICTIONARY: Dict[str, str] = {}


def load_dictionary() -> Dict[str, str]:
    """오인식 교정용 용어 사전 {잘못 들린 말: 올바른 표기}."""
    PATHS.ensure()
    if DICTIONARY_FILE.exists():
        try:
            raw = json.loads(DICTIONARY_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): str(v) for k, v in raw.items()}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_DICTIONARY)


def save_dictionary(mapping: Dict[str, str]) -> None:
    PATHS.ensure()
    DICTIONARY_FILE.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
