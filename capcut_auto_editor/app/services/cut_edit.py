"""컷 후보 만들기, 원본 ↔ 편집본 타임코드 매핑."""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .audio_analysis import Silence, speech_spans
from .logging_util import get_logger

log = get_logger("cut")


@dataclass
class CutCandidate:
    """살릴 구간 하나. keep=False 로 두면 최종 편집본에서 빠진다."""
    index: int
    start: float           # 원본(소스 타임라인) 기준 초
    end: float
    keep: bool = True
    reason: str = "speech"  # speech | manual | filler

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["duration"] = self.duration
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "CutCandidate":
        return cls(index=raw["index"], start=raw["start"], end=raw["end"],
                   keep=raw.get("keep", True), reason=raw.get("reason", "speech"))


def build_candidates(silences: List[Silence], total_duration: float, *,
                     padding: float = 0.12,
                     min_keep: float = 0.25) -> List[CutCandidate]:
    """무음 사이의 말하는 구간을 '살릴 구간' 후보로 만든다."""
    spans = speech_spans(silences, total_duration, padding=padding)
    out: List[CutCandidate] = []
    for i, (a, b) in enumerate(spans):
        # 너무 짧은 조각은 기본적으로 빼 둔다. 사용자가 UI에서 되살릴 수 있다.
        keep = (b - a) >= min_keep
        out.append(CutCandidate(index=i, start=a, end=b, keep=keep))
    log.info("컷 후보 %d개 (살릴 구간 %d개)", len(out), sum(1 for c in out if c.keep))
    return out


class TimeMap:
    """원본 시간 ↔ 편집본 시간 양방향 변환.

    살릴 구간만 이어붙였을 때 원본의 어느 지점이 편집본의 어디로 가는지 계산한다.
    자막 타이밍을 편집본에 맞춰 옮길 때 쓴다.
    """

    def __init__(self, kept: List[Tuple[float, float]]) -> None:
        self.kept = sorted(kept)
        self._src_starts: List[float] = []
        self._dst_starts: List[float] = []
        cursor = 0.0
        for a, b in self.kept:
            self._src_starts.append(a)
            self._dst_starts.append(cursor)
            cursor += b - a
        self.duration = cursor

    @classmethod
    def from_candidates(cls, candidates: List[CutCandidate]) -> "TimeMap":
        return cls([(c.start, c.end) for c in candidates if c.keep])

    # ------------------------------------------------------------------ 변환
    def _segment_of(self, src_t: float) -> Optional[int]:
        i = bisect.bisect_right(self._src_starts, src_t) - 1
        if i < 0:
            return None
        a, b = self.kept[i]
        return i if src_t < b + 1e-9 else None

    def to_edited(self, src_t: float, *, snap: bool = True) -> Optional[float]:
        """원본 시간 → 편집본 시간. 잘려나간 구간이면 None(또는 가까운 경계)."""
        i = self._segment_of(src_t)
        if i is not None:
            return self._dst_starts[i] + (src_t - self.kept[i][0])
        if not snap or not self.kept:
            return None
        # 잘린 구간이면 다음 살아남은 구간의 시작으로 당긴다
        j = bisect.bisect_right(self._src_starts, src_t)
        if j >= len(self.kept):
            return self.duration
        return self._dst_starts[j]

    def to_source(self, dst_t: float) -> Optional[float]:
        """편집본 시간 → 원본 시간."""
        if not self.kept:
            return None
        i = bisect.bisect_right(self._dst_starts, dst_t) - 1
        if i < 0:
            return None
        offset = dst_t - self._dst_starts[i]
        a, b = self.kept[i]
        return min(a + offset, b)

    def map_span(self, start: float, end: float) -> Optional[Tuple[float, float]]:
        """구간 하나를 편집본 시간대로 옮긴다. 통째로 잘렸으면 None."""
        s = self.to_edited(start, snap=True)
        e = self.to_edited(end, snap=True)
        if s is None or e is None or e - s <= 1e-3:
            return None
        return (s, e)

    def to_dict(self) -> Dict[str, Any]:
        return {"kept": self.kept, "duration": self.duration}


def apply_manual_edits(candidates: List[CutCandidate],
                       toggles: Dict[int, bool]) -> List[CutCandidate]:
    """UI에서 켜고 끈 결과를 반영한다."""
    for c in candidates:
        if c.index in toggles:
            c.keep = bool(toggles[c.index])
            c.reason = "manual"
    return candidates


def summarize(candidates: List[CutCandidate], total_duration: float) -> Dict[str, Any]:
    kept = [c for c in candidates if c.keep]
    kept_dur = sum(c.duration for c in kept)
    return {
        "total_candidates": len(candidates),
        "kept": len(kept),
        "removed": len(candidates) - len(kept),
        "source_duration": total_duration,
        "edited_duration": kept_dur,
        "saved_seconds": max(0.0, total_duration - kept_dur),
        "saved_ratio": (1 - kept_dur / total_duration) if total_duration else 0.0,
    }
