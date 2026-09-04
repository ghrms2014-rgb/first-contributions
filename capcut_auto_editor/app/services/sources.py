"""여러 영상을 이어붙인 소스 타임라인."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .audio_analysis import MediaInfo, probe
from .logging_util import get_logger

log = get_logger("sources")


@dataclass
class Clip:
    """소스 타임라인 위에 놓인 원본 영상 하나."""
    index: int
    path: str
    duration: float          # 초
    offset: float            # 소스 타임라인에서의 시작 위치(초)
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = True

    @property
    def end(self) -> float:
        return self.offset + self.duration

    def contains(self, t: float) -> bool:
        return self.offset - 1e-6 <= t < self.end - 1e-9

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["end"] = self.end
        d["name"] = Path(self.path).name
        return d


class SourceTimeline:
    """여러 파일을 순서대로 이어 하나의 연속된 시간축으로 본다.

    이후 모든 단계(무음 감지, 전사, 컷)는 이 '전역 시간'을 기준으로 움직이고,
    드래프트를 쓸 때만 다시 (파일, 파일 내 시간)으로 되돌린다.
    """

    def __init__(self, clips: Optional[List[Clip]] = None) -> None:
        self.clips: List[Clip] = clips or []

    # ------------------------------------------------------------------ 생성
    @classmethod
    def from_paths(cls, paths: Iterable[str | Path]) -> "SourceTimeline":
        clips: List[Clip] = []
        offset = 0.0
        for i, p in enumerate(paths):
            info: MediaInfo = probe(p)
            if info.duration <= 0:
                log.warning("길이를 읽을 수 없어 건너뜁니다: %s", p)
                continue
            clips.append(Clip(
                index=i, path=str(p), duration=info.duration, offset=offset,
                width=info.width, height=info.height, fps=info.fps,
                has_audio=info.has_audio,
            ))
            offset += info.duration
        tl = cls(clips)
        log.info("소스 타임라인 구성: %d개 클립, 총 %.1f초", len(tl.clips), tl.duration)
        return tl

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SourceTimeline":
        clips = [Clip(
            index=c["index"], path=c["path"], duration=c["duration"], offset=c["offset"],
            width=c.get("width", 0), height=c.get("height", 0), fps=c.get("fps", 0.0),
            has_audio=c.get("has_audio", True),
        ) for c in raw.get("clips", [])]
        return cls(clips)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clips": [c.to_dict() for c in self.clips],
            "duration": self.duration,
            "count": len(self.clips),
        }

    # ------------------------------------------------------------------ 조회
    @property
    def duration(self) -> float:
        return self.clips[-1].end if self.clips else 0.0

    @property
    def paths(self) -> List[str]:
        return [c.path for c in self.clips]

    def clip_at(self, t: float) -> Optional[Clip]:
        for c in self.clips:
            if c.contains(t):
                return c
        # 딱 끝 지점은 마지막 클립에 속하는 것으로 본다
        if self.clips and abs(t - self.duration) < 1e-6:
            return self.clips[-1]
        return None

    def to_local(self, t: float) -> Optional[Tuple[Clip, float]]:
        """전역 시간 → (클립, 클립 내 시간)."""
        c = self.clip_at(t)
        return (c, t - c.offset) if c else None

    def to_global(self, clip_index: int, local_t: float) -> float:
        """(클립 번호, 클립 내 시간) → 전역 시간."""
        return self.clips[clip_index].offset + local_t

    def split_span(self, start: float, end: float) -> List[Tuple[Clip, float, float]]:
        """전역 구간을 클립 경계에서 잘라 (클립, 시작, 끝) 목록으로 만든다.

        구간이 두 파일에 걸쳐 있으면 두 조각으로 나뉜다.
        """
        out: List[Tuple[Clip, float, float]] = []
        for c in self.clips:
            a, b = max(start, c.offset), min(end, c.end)
            if b - a > 1e-3:
                out.append((c, a - c.offset, b - c.offset))
        return out

    def reorder(self, order: List[int]) -> "SourceTimeline":
        """사용자가 UI에서 순서를 바꾼 뒤 offset 을 다시 계산한다."""
        by_index = {c.index: c for c in self.clips}
        clips: List[Clip] = []
        offset = 0.0
        for new_i, old_i in enumerate(order):
            src = by_index[old_i]
            clips.append(Clip(
                index=new_i, path=src.path, duration=src.duration, offset=offset,
                width=src.width, height=src.height, fps=src.fps, has_audio=src.has_audio,
            ))
            offset += src.duration
        return SourceTimeline(clips)
