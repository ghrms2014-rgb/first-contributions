"""faster-whisper 전사 (청크 단위 + 중단 후 재시작)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .audio_analysis import extract_audio, probe, slice_audio
from .logging_util import get_logger

log = get_logger("transcribe")

ProgressFn = Callable[[float, str], None]


class WhisperMissing(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "faster-whisper 가 설치되어 있지 않습니다. `pip install faster-whisper` 로 설치해 주세요."
        )


@dataclass
class Word:
    start: float
    end: float
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass
class Utterance:
    """전사 결과 한 덩어리. 시간은 소스 타임라인 전역 기준(초)."""
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text,
                "words": [w.to_dict() for w in self.words]}

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Utterance":
        return cls(start=raw["start"], end=raw["end"], text=raw["text"],
                   words=[Word(**w) for w in raw.get("words", [])])


def _load_model(model_size: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise WhisperMissing() from exc

    log.info("Whisper 모델 로드: %s (%s)", model_size, compute_type)
    try:
        return WhisperModel(model_size, device="auto", compute_type=compute_type)
    except Exception:
        # GPU 가 없거나 compute_type 이 안 맞으면 CPU/int8 로 물러난다
        log.warning("기본 설정 로드 실패 → CPU/int8 로 재시도")
        return WhisperModel(model_size, device="cpu", compute_type="int8")


class Transcriber:
    """긴 오디오를 청크로 잘라 전사하고, 청크마다 결과를 파일에 남긴다.

    중간에 끊겨도 이미 끝난 청크는 다시 돌리지 않는다.
    """

    def __init__(self, work_dir: str | Path, *, model_size: str = "medium",
                 language: str = "ko", chunk_sec: int = 600,
                 compute_type: str = "int8") -> None:
        self.work_dir = Path(work_dir)
        self.chunk_dir = self.work_dir / "transcribe_chunks"
        self.chunk_dir.mkdir(parents=True, exist_ok=True)
        self.model_size = model_size
        self.language = language
        self.chunk_sec = max(60, int(chunk_sec))
        self.compute_type = compute_type
        self._model = None

    # -------------------------------------------------------------- 내부 도구
    def _chunk_file(self, i: int) -> Path:
        return self.chunk_dir / f"chunk_{i:04d}.json"

    def _model_or_load(self):
        if self._model is None:
            self._model = _load_model(self.model_size, self.compute_type)
        return self._model

    def _transcribe_file(self, audio_path: Path, offset: float) -> List[Utterance]:
        model = self._model_or_load()
        segments, _info = model.transcribe(
            str(audio_path), language=self.language, word_timestamps=True,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
        )
        out: List[Utterance] = []
        for seg in segments:
            words = [Word(start=w.start + offset, end=w.end + offset, text=w.word.strip())
                     for w in (getattr(seg, "words", None) or []) if w.word.strip()]
            text = (seg.text or "").strip()
            if not text:
                continue
            out.append(Utterance(start=seg.start + offset, end=seg.end + offset,
                                 text=text, words=words))
        return out

    # ------------------------------------------------------------------ 본체
    def run(self, audio_path: str | Path, *, total_duration: Optional[float] = None,
            progress: Optional[ProgressFn] = None,
            force: bool = False) -> List[Utterance]:
        """전체 전사. 이미 끝난 청크는 건너뛴다."""
        audio_path = Path(audio_path)
        duration = total_duration if total_duration is not None else probe(audio_path).duration
        n_chunks = max(1, int(duration // self.chunk_sec) + (1 if duration % self.chunk_sec else 0))

        all_utts: List[Utterance] = []
        for i in range(n_chunks):
            start = i * self.chunk_sec
            length = min(self.chunk_sec, duration - start)
            if length <= 0.05:
                continue

            cache = self._chunk_file(i)
            if cache.exists() and not force:
                try:
                    cached = json.loads(cache.read_text(encoding="utf-8"))
                    all_utts.extend(Utterance.from_dict(u) for u in cached["utterances"])
                    log.info("청크 %d/%d 재사용", i + 1, n_chunks)
                    if progress:
                        progress((i + 1) / n_chunks, f"청크 {i + 1}/{n_chunks} (캐시)")
                    continue
                except (json.JSONDecodeError, KeyError, OSError):
                    log.warning("청크 %d 캐시가 깨져 다시 전사합니다", i)

            if progress:
                progress(i / n_chunks, f"청크 {i + 1}/{n_chunks} 전사 중")

            if n_chunks == 1:
                piece = audio_path
            else:
                piece = slice_audio(audio_path, self.chunk_dir / f"chunk_{i:04d}.wav",
                                    start, length)

            utts = self._transcribe_file(piece, offset=start)
            cache.write_text(json.dumps(
                {"index": i, "start": start, "duration": length,
                 "utterances": [u.to_dict() for u in utts]},
                ensure_ascii=False), encoding="utf-8")
            all_utts.extend(utts)

            if n_chunks > 1 and piece.exists():
                piece.unlink(missing_ok=True)  # 청크 wav 는 결과를 남겼으면 지운다
            if progress:
                progress((i + 1) / n_chunks, f"청크 {i + 1}/{n_chunks} 완료")

        all_utts.sort(key=lambda u: u.start)
        log.info("전사 완료: %d문장 / %.1f초", len(all_utts), duration)
        return all_utts

    # ------------------------------------------------------------------ 저장
    def save(self, utterances: List[Utterance], path: Optional[Path] = None) -> Path:
        path = path or (self.work_dir / "transcript.json")
        path.write_text(json.dumps([u.to_dict() for u in utterances],
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, path: Optional[Path] = None) -> List[Utterance]:
        path = path or (self.work_dir / "transcript.json")
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Utterance.from_dict(u) for u in raw]

    def reset(self) -> None:
        """캐시된 청크를 모두 지워 처음부터 다시 하게 한다."""
        for f in self.chunk_dir.glob("chunk_*"):
            f.unlink(missing_ok=True)


def prepare_audio(source_paths: List[str], work_dir: str | Path,
                  progress: Optional[ProgressFn] = None) -> Path:
    """여러 영상의 오디오를 하나의 wav 로 이어붙여 전사 입력으로 만든다."""
    from .audio_analysis import _bin, _run  # 내부 도구 재사용

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out = work / "source_audio.wav"

    if len(source_paths) == 1:
        return extract_audio(source_paths[0], out)

    parts: List[Path] = []
    for i, src in enumerate(source_paths):
        if progress:
            progress(i / len(source_paths), f"오디오 추출 {i + 1}/{len(source_paths)}")
        parts.append(extract_audio(src, work / f"part_{i:03d}.wav"))

    list_file = work / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")

    proc = _run([_bin("ffmpeg"), "-y", "-f", "concat", "-safe", "0",
                 "-i", str(list_file), "-ac", "1", "-ar", "16000",
                 "-c:a", "pcm_s16le", str(out)])
    if proc.returncode != 0:
        raise RuntimeError(f"오디오 병합 실패\n{proc.stderr.strip()[-2000:]}")

    for p in parts:
        p.unlink(missing_ok=True)
    return out
