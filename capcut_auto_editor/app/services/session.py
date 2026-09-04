"""세션 상태와 단계 잠금."""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import PATHS

# 파이프라인 단계는 순서가 있고, 앞 단계를 끝내야 다음 단계가 열린다.
STEPS: List[str] = [
    "setup",         # 폴더/설정 확인
    "sources",       # 원본 영상 선택 + 소스 타임라인 구성
    "calibration",   # 드래프트 좌표계 캘리브레이션
    "transcribe",    # 음성 전사
    "align",         # 대본 정렬 + 자막 생성
    "edit",          # 컷 편집 확정
    "build",         # 캡컷 드래프트 생성
    "publish",       # 마케팅 문구 / 내보내기
]
STEP_INDEX = {name: i for i, name in enumerate(STEPS)}


class StepLocked(Exception):
    """앞 단계가 끝나지 않아 아직 실행할 수 없는 단계."""

    def __init__(self, step: str, missing: str) -> None:
        super().__init__(f"'{step}' 단계는 '{missing}' 단계를 끝낸 뒤에 실행할 수 있습니다.")
        self.step = step
        self.missing = missing


@dataclass
class Session:
    id: str
    name: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- 단계 잠금
    def is_done(self, step: str) -> bool:
        return step in self.completed

    def require(self, step: str) -> None:
        """`step`을 실행하기 전에 선행 단계가 모두 끝났는지 확인한다."""
        if step not in STEP_INDEX:
            raise ValueError(f"알 수 없는 단계: {step}")
        for prev in STEPS[: STEP_INDEX[step]]:
            if prev not in self.completed:
                raise StepLocked(step, prev)

    def complete(self, step: str, **payload: Any) -> None:
        if step not in STEP_INDEX:
            raise ValueError(f"알 수 없는 단계: {step}")
        if step not in self.completed:
            self.completed.append(step)
        if payload:
            self.data.setdefault(step, {}).update(payload)
        self.touch()

    def invalidate_from(self, step: str) -> None:
        """어떤 단계를 다시 하면 그 뒤 단계의 완료 표시를 모두 지운다."""
        idx = STEP_INDEX[step]
        self.completed = [s for s in self.completed if STEP_INDEX[s] < idx]
        self.touch()

    def touch(self) -> None:
        self.updated_at = time.time()

    # ------------------------------------------------------------ 직렬화 / 경로
    @property
    def dir(self) -> Path:
        return PATHS.sessions / self.id

    @property
    def work_dir(self) -> Path:
        """중간 산출물(추출 오디오, 전사 청크 등)을 두는 곳."""
        d = self.dir / "work"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "completed": self.completed, "data": self.data,
            "next_step": self.next_step(),
        }

    def next_step(self) -> Optional[str]:
        for s in STEPS:
            if s not in self.completed:
                return s
        return None


class SessionStore:
    """세션을 파일 하나당 하나씩 저장한다. 프로세스가 죽어도 이어서 할 수 있게."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, Session] = {}
        PATHS.ensure()

    def _file(self, session_id: str) -> Path:
        return PATHS.sessions / session_id / "session.json"

    def create(self, name: str = "") -> Session:
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        session = Session(id=sid, name=name or sid)
        session.dir.mkdir(parents=True, exist_ok=True)
        self.save(session)
        return session

    def save(self, session: Session) -> None:
        session.touch()
        with self._lock:
            self._cache[session.id] = session
            path = self._file(session.id)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(path)  # 저장 도중 죽어도 반쪽 파일이 남지 않게

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            if session_id in self._cache:
                return self._cache[session_id]
        path = self._file(session_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        session = Session(
            id=raw["id"], name=raw.get("name", ""),
            created_at=raw.get("created_at", time.time()),
            updated_at=raw.get("updated_at", time.time()),
            completed=raw.get("completed", []), data=raw.get("data", {}),
        )
        with self._lock:
            self._cache[session.id] = session
        return session

    def list(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for d in sorted(PATHS.sessions.glob("*/session.json"), reverse=True):
            s = self.get(d.parent.name)
            if s:
                out.append(s.to_dict())
        return out

    def delete(self, session_id: str) -> bool:
        import shutil
        d = PATHS.sessions / session_id
        if not d.is_dir():
            return False
        shutil.rmtree(d, ignore_errors=True)
        with self._lock:
            self._cache.pop(session_id, None)
        return True


SESSIONS = SessionStore()
