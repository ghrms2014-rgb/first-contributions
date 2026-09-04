"""ffprobe, 오디오 추출, 무음 감지."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import detect_ffmpeg
from .logging_util import get_logger

log = get_logger("audio")


class FFmpegMissing(RuntimeError):
    def __init__(self, tool: str) -> None:
        super().__init__(
            f"{tool} 을(를) 찾을 수 없습니다. ffmpeg 을 설치하고 PATH 에 넣어 주세요. "
            "(윈도우: https://www.gyan.dev/ffmpeg/builds/ 에서 받아 bin 폴더를 PATH 에 추가)"
        )
        self.tool = tool


def _bin(tool: str) -> str:
    path = detect_ffmpeg().get(tool)
    if not path:
        raise FFmpegMissing(tool)
    return path


def _run(cmd: List[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    log.debug("실행: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


# ---------------------------------------------------------------------- ffprobe

@dataclass
class MediaInfo:
    path: str
    duration: float           # 초
    has_audio: bool
    has_video: bool
    width: int = 0
    height: int = 0
    fps: float = 0.0
    audio_rate: int = 0
    audio_channels: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def _parse_fps(text: str) -> float:
    if not text or text == "0/0":
        return 0.0
    if "/" in text:
        num, den = text.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> MediaInfo:
    """ffprobe 로 길이/해상도/오디오 유무를 읽는다."""
    p = str(path)
    proc = _run([_bin("ffprobe"), "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", p])
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {p}\n{proc.stderr.strip()}")

    raw = json.loads(proc.stdout or "{}")
    streams = raw.get("streams", [])
    fmt = raw.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(fmt.get("duration") or 0.0)
    if not duration:
        for s in streams:
            if s.get("duration"):
                duration = max(duration, float(s["duration"]))

    return MediaInfo(
        path=p, duration=duration,
        has_audio=audio is not None, has_video=video is not None,
        width=int(video.get("width", 0)) if video else 0,
        height=int(video.get("height", 0)) if video else 0,
        fps=_parse_fps(video.get("avg_frame_rate", "")) if video else 0.0,
        audio_rate=int(audio.get("sample_rate", 0)) if audio else 0,
        audio_channels=int(audio.get("channels", 0)) if audio else 0,
    )


# ------------------------------------------------------------------ 오디오 추출

def extract_audio(src: str | Path, dst: str | Path, *, sample_rate: int = 16000,
                  channels: int = 1, overwrite: bool = False) -> Path:
    """전사에 쓸 16kHz 모노 wav 로 뽑아낸다. 이미 있으면 건너뛴다."""
    out = Path(dst)
    if out.exists() and not overwrite and out.stat().st_size > 0:
        log.info("오디오 재사용: %s", out.name)
        return out
    out.parent.mkdir(parents=True, exist_ok=True)

    proc = _run([_bin("ffmpeg"), "-y", "-i", str(src), "-vn",
                 "-ac", str(channels), "-ar", str(sample_rate),
                 "-c:a", "pcm_s16le", str(out)])
    if proc.returncode != 0:
        raise RuntimeError(f"오디오 추출 실패: {src}\n{proc.stderr.strip()[-2000:]}")
    log.info("오디오 추출 완료: %s", out.name)
    return out


def slice_audio(src: str | Path, dst: str | Path, start: float, duration: float) -> Path:
    """전사 청크용으로 [start, start+duration) 구간만 잘라낸다."""
    out = Path(dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = _run([_bin("ffmpeg"), "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                 "-i", str(src), "-c", "copy", str(out)])
    if proc.returncode != 0:  # copy 가 안 되는 포맷이면 재인코딩
        proc = _run([_bin("ffmpeg"), "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                     "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)])
    if proc.returncode != 0:
        raise RuntimeError(f"오디오 분할 실패: {src}\n{proc.stderr.strip()[-2000:]}")
    return out


# ------------------------------------------------------------------- 무음 감지

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


@dataclass
class Silence:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> Dict[str, float]:
        return {"start": self.start, "end": self.end, "duration": self.duration}


def detect_silence(path: str | Path, *, threshold_db: float = -35.0,
                   min_silence: float = 0.45,
                   total_duration: Optional[float] = None) -> List[Silence]:
    """ffmpeg silencedetect 로 무음 구간을 찾는다."""
    proc = _run([_bin("ffmpeg"), "-i", str(path), "-af",
                 f"silencedetect=noise={threshold_db}dB:d={min_silence}",
                 "-f", "null", "-"])
    # silencedetect 는 결과를 stderr 로 뱉는다. 종료코드는 보지 않는다.
    text = proc.stderr or ""

    silences: List[Silence] = []
    pending: Optional[float] = None
    for line in text.splitlines():
        m = _SILENCE_START.search(line)
        if m:
            pending = max(0.0, float(m.group(1)))
            continue
        m = _SILENCE_END.search(line)
        if m and pending is not None:
            silences.append(Silence(pending, float(m.group(1))))
            pending = None

    if pending is not None:  # 파일 끝까지 무음으로 끝난 경우
        end = total_duration if total_duration is not None else probe(path).duration
        if end > pending:
            silences.append(Silence(pending, end))

    log.info("무음 %d개 감지 (%.1fdB, %.2fs 이상)", len(silences), threshold_db, min_silence)
    return silences


def speech_spans(silences: List[Silence], total_duration: float,
                 padding: float = 0.0) -> List[Tuple[float, float]]:
    """무음의 여집합 = 말하는 구간. padding 만큼 앞뒤로 늘려 준다."""
    spans: List[Tuple[float, float]] = []
    cursor = 0.0
    for s in sorted(silences, key=lambda x: x.start):
        if s.start > cursor:
            spans.append((cursor, min(s.start, total_duration)))
        cursor = max(cursor, s.end)
    if cursor < total_duration:
        spans.append((cursor, total_duration))

    if padding > 0:
        spans = [(max(0.0, a - padding), min(total_duration, b + padding)) for a, b in spans]
        merged: List[Tuple[float, float]] = []
        for span in spans:
            if merged and span[0] <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], span[1]))
            else:
                merged.append(span)
        spans = merged

    return [(a, b) for a, b in spans if b - a > 1e-3]
