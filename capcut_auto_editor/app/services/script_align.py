"""대본 정렬, 용어 사전, 자막·SRT."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .line_break import one_line, normalize
from .logging_util import get_logger
from .transcribe import Utterance, Word

log = get_logger("align")

_STRIP = re.compile(r"[\s.,!?…·:;\"'“”‘’()\[\]{}~\-—]+")


# ------------------------------------------------------------------- 용어 사전

def apply_dictionary(text: str, mapping: Dict[str, str]) -> str:
    """오인식 교정. 긴 표기부터 바꿔 부분 치환이 먼저 일어나지 않게 한다."""
    if not mapping:
        return text
    for wrong in sorted(mapping, key=len, reverse=True):
        if wrong:
            text = text.replace(wrong, mapping[wrong])
    return text


def apply_dictionary_to_utterances(utterances: List[Utterance],
                                   mapping: Dict[str, str]) -> List[Utterance]:
    for u in utterances:
        u.text = apply_dictionary(u.text, mapping)
        for w in u.words:
            w.text = apply_dictionary(w.text, mapping)
    return utterances


# ------------------------------------------------------------------ 문자 시간축

@dataclass
class CharTime:
    """정규화된 글자 하나와 그 글자가 발화된 시각."""
    char: str
    start: float
    end: float


def build_char_timeline(utterances: List[Utterance]) -> List[CharTime]:
    """단어 타임스탬프를 글자 단위로 펼친다.

    단어 안에서는 글자가 고르게 발음된다고 본다. 자막 경계를 잡기엔 충분하다.
    """
    out: List[CharTime] = []
    for u in utterances:
        words = u.words or [Word(start=u.start, end=u.end, text=u.text)]
        for w in words:
            chars = _STRIP.sub("", w.text)
            if not chars:
                continue
            span = max(w.end - w.start, 1e-3)
            step = span / len(chars)
            for i, ch in enumerate(chars):
                out.append(CharTime(ch, w.start + i * step, w.start + (i + 1) * step))
    return out


def _normalize_with_index(text: str) -> Tuple[str, List[int]]:
    """정규화된 문자열과, 각 글자가 원문 어디서 왔는지의 인덱스."""
    chars: List[str] = []
    index: List[int] = []
    for i, ch in enumerate(text):
        if not _STRIP.match(ch):
            chars.append(ch)
            index.append(i)
    return "".join(chars), index


# ---------------------------------------------------------------------- 자막

@dataclass
class Cue:
    """자막 한 줄. 시간은 소스 타임라인 전역 기준(초)."""
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text,
                "duration": self.duration}

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Cue":
        return cls(start=raw["start"], end=raw["end"], text=raw["text"])


def align_script(script: str, utterances: List[Utterance]) -> List[Tuple[int, float, float]]:
    """대본 글자 하나하나에 시간을 붙인다.

    반환: (대본 원문 인덱스, 시작초, 끝초) 목록. 대본 표기를 그대로 쓰면서
    타이밍만 전사 결과에서 가져오려는 것.
    """
    timeline = build_char_timeline(utterances)
    if not timeline:
        return []

    hyp = "".join(c.char for c in timeline)
    ref, ref_index = _normalize_with_index(script)
    if not ref:
        return []

    times: List[Optional[Tuple[float, float]]] = [None] * len(ref)
    matcher = SequenceMatcher(None, ref, hyp, autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            ct = timeline[b + k]
            times[a + k] = (ct.start, ct.end)

    matched = sum(1 for t in times if t is not None)
    log.info("대본 정렬: %d/%d 글자 일치 (%.0f%%)",
             matched, len(ref), 100 * matched / len(ref) if ref else 0)

    # 못 맞춘 글자는 양옆에서 선형 보간한다
    _fill_gaps(times, timeline)

    return [(ref_index[i], t[0], t[1]) for i, t in enumerate(times) if t is not None]


def _fill_gaps(times: List[Optional[Tuple[float, float]]], timeline: List[CharTime]) -> None:
    """앞뒤로 맞은 글자가 있으면 그 사이를 고르게 나눠 채운다."""
    n = len(times)
    first = next((i for i, t in enumerate(times) if t), None)
    if first is None:
        return
    last = next(i for i in range(n - 1, -1, -1) if times[i])

    head, tail = times[first], times[last]
    for i in range(first):
        times[i] = (max(0.0, head[0]), head[0])
    for i in range(last + 1, n):
        times[i] = (tail[1], tail[1])

    i = first
    while i <= last:
        if times[i] is not None:
            i += 1
            continue
        gap_start = i
        while i <= last and times[i] is None:
            i += 1
        prev_end = times[gap_start - 1][1]
        next_start = times[i][0] if i <= last else prev_end
        span = max(next_start - prev_end, 0.0)
        count = i - gap_start
        step = span / count if count else 0.0
        for k in range(count):
            times[gap_start + k] = (prev_end + k * step, prev_end + (k + 1) * step)


def cues_from_script(script: str, utterances: List[Utterance], *,
                     max_chars: int = 18, min_duration: float = 0.7) -> List[Cue]:
    """대본 표기 + 전사 타이밍으로 자막을 만든다."""
    aligned = align_script(script, utterances)
    if not aligned:
        return cues_from_transcript(utterances, max_chars=max_chars,
                                    min_duration=min_duration)

    time_of = {idx: (s, e) for idx, s, e in aligned}
    cues: List[Cue] = []
    cursor = 0
    for line in one_line(script, max_chars):
        pos = script.find(line, cursor)
        if pos < 0:  # 줄 나누기에서 공백이 바뀐 경우 — 글자 단위로 다시 찾는다
            pos = _find_loose(script, line, cursor)
        if pos < 0:
            continue
        end_pos = pos + len(line)
        cursor = end_pos

        spans = [time_of[i] for i in range(pos, end_pos) if i in time_of]
        if not spans:
            continue
        cues.append(Cue(start=min(s for s, _ in spans), end=max(e for _, e in spans), text=line))

    return _tidy(cues, min_duration)


def _find_loose(haystack: str, needle: str, start: int) -> int:
    """공백 차이를 무시하고 위치를 찾는다."""
    compact = _STRIP.sub("", needle)
    if not compact:
        return -1
    j = 0
    first = -1
    for i in range(start, len(haystack)):
        if _STRIP.match(haystack[i]):
            continue
        if haystack[i] == compact[j]:
            if j == 0:
                first = i
            j += 1
            if j == len(compact):
                return first
        else:
            j = 0
            first = -1
    return -1


def cues_from_transcript(utterances: List[Utterance], *, max_chars: int = 18,
                         min_duration: float = 0.7) -> List[Cue]:
    """대본이 없을 때 전사 결과만으로 자막을 만든다."""
    cues: List[Cue] = []
    for u in utterances:
        lines = one_line(u.text, max_chars)
        if not lines:
            continue
        if len(lines) == 1:
            cues.append(Cue(u.start, u.end, lines[0]))
            continue
        # 글자수 비율대로 시간을 나눈다
        total = sum(len(l) for l in lines) or 1
        cursor = u.start
        span = max(u.end - u.start, 1e-3)
        for line in lines:
            width = span * len(line) / total
            cues.append(Cue(cursor, cursor + width, line))
            cursor += width
    return _tidy(cues, min_duration)


def _tidy(cues: List[Cue], min_duration: float) -> List[Cue]:
    """너무 짧은 자막을 늘리고, 겹치는 부분을 정리한다."""
    cues = [c for c in sorted(cues, key=lambda c: c.start) if c.text.strip()]
    for i, c in enumerate(cues):
        if c.duration < min_duration:
            limit = cues[i + 1].start if i + 1 < len(cues) else c.start + min_duration
            c.end = max(c.end, min(c.start + min_duration, limit))
        if i + 1 < len(cues) and c.end > cues[i + 1].start:
            c.end = cues[i + 1].start
    return [c for c in cues if c.duration > 1e-3]


def shift_cues(cues: List[Cue], time_map) -> List[Cue]:
    """원본 기준 자막을 편집본(컷 적용 후) 시간대로 옮긴다."""
    out: List[Cue] = []
    for c in cues:
        span = time_map.map_span(c.start, c.end)
        if span:
            out.append(Cue(span[0], span[1], c.text))
    log.info("자막 %d개 중 %d개가 편집본에 남았습니다", len(cues), len(out))
    return out


# ------------------------------------------------------------------------ SRT

def _srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: List[Cue]) -> str:
    blocks = []
    for i, c in enumerate(cues, start=1):
        blocks.append(f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text}\n")
    return "\n".join(blocks)


def write_srt(cues: List[Cue], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 캡컷은 BOM 없는 UTF-8 을 잘 읽는다
    p.write_text(to_srt(cues), encoding="utf-8")
    log.info("SRT 저장: %s (%d개)", p.name, len(cues))
    return p


def save_cues(cues: List[Cue], path: str | Path) -> Path:
    p = Path(path)
    p.write_text(json.dumps([c.to_dict() for c in cues], ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def load_cues(path: str | Path) -> List[Cue]:
    p = Path(path)
    if not p.exists():
        return []
    return [Cue.from_dict(r) for r in json.loads(p.read_text(encoding="utf-8"))]
