"""오디오 분석 · 전사 · 대본 정렬 · 컷 확정 · 드래프트 빌드."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import load_dictionary, load_settings
from ..services.audio_analysis import FFmpegMissing, Silence, detect_silence
from ..services.builder import BuildRequest, DraftBuilder
from ..services.capcut_draft import CalibrationProfile
from ..services.cut_edit import (CutCandidate, TimeMap, apply_manual_edits,
                                 build_candidates, summarize)
from ..services.jobs import JOBS, JobHandle
from ..services.logging_util import get_logger
from ..services.script_align import (Cue, apply_dictionary_to_utterances, cues_from_script,
                                     cues_from_transcript, load_cues, save_cues, shift_cues,
                                     write_srt)
from ..services.session import SESSIONS, Session
from ..services.sources import SourceTimeline
from ..services.transcribe import Transcriber, WhisperMissing, prepare_audio
from .common import get_session, ok, require_step

router = APIRouter(prefix="/api/editing", tags=["editing"])
log = get_logger("editing")


# ------------------------------------------------------------------ 파일 위치

def _timeline(session: Session) -> SourceTimeline:
    raw = (session.data.get("sources") or {}).get("timeline")
    if not raw:
        raise HTTPException(status_code=409, detail="먼저 원본 영상을 선택해 주세요.")
    return SourceTimeline.from_dict(raw)


def _f(session: Session, name: str) -> Path:
    return session.work_dir / name


def _load_candidates(session: Session) -> List[CutCandidate]:
    p = _f(session, "candidates.json")
    if not p.exists():
        raise HTTPException(status_code=409, detail="먼저 오디오 분석을 실행해 주세요.")
    return [CutCandidate.from_dict(r) for r in json.loads(p.read_text(encoding="utf-8"))]


def _save_candidates(session: Session, candidates: List[CutCandidate]) -> None:
    _f(session, "candidates.json").write_text(
        json.dumps([c.to_dict() for c in candidates], ensure_ascii=False, indent=2),
        encoding="utf-8")


def _profile(session: Session) -> Optional[CalibrationProfile]:
    raw = (session.data.get("calibration") or {}).get("profile")
    return CalibrationProfile.from_dict(raw) if raw else None


# -------------------------------------------------------------- 1) 오디오 분석

@router.post("/{session_id}/analyze")
def analyze(session_id: str) -> Dict[str, Any]:
    """오디오를 뽑아 무음을 찾고 컷 후보를 만든다. 오래 걸리므로 작업으로 돌린다."""
    session = get_session(session_id)
    require_step(session, "transcribe")   # 분석은 전사 단계 앞부분
    timeline = _timeline(session)
    settings = load_settings()

    def work(handle: JobHandle) -> Dict[str, Any]:
        handle.progress(0.05, "오디오 추출 중")
        audio = prepare_audio(timeline.paths, session.work_dir,
                              progress=lambda p, m: handle.progress(0.05 + p * 0.45, m))

        handle.progress(0.55, "무음 구간 찾는 중")
        silences = detect_silence(audio, threshold_db=settings.silence_db,
                                  min_silence=settings.min_silence_sec,
                                  total_duration=timeline.duration)

        handle.progress(0.85, "컷 후보 만드는 중")
        candidates = build_candidates(silences, timeline.duration,
                                      padding=settings.keep_padding_sec)

        _f(session, "silences.json").write_text(
            json.dumps([s.to_dict() for s in silences], ensure_ascii=False), encoding="utf-8")
        _save_candidates(session, candidates)

        stats = summarize(candidates, timeline.duration)
        session.data.setdefault("analyze", {}).update({"audio": str(audio), **stats})
        SESSIONS.save(session)
        handle.progress(1.0, f"컷 후보 {len(candidates)}개")
        return stats

    job = JOBS.submit(f"오디오 분석 ({session.name})", work)
    return ok(job=job.to_dict())


# ------------------------------------------------------------------ 2) 컷 후보

@router.get("/{session_id}/candidates")
def read_candidates(session_id: str) -> Dict[str, Any]:
    session = get_session(session_id)
    candidates = _load_candidates(session)
    timeline = _timeline(session)
    return {"candidates": [c.to_dict() for c in candidates],
            "summary": summarize(candidates, timeline.duration)}


class ToggleRequest(BaseModel):
    toggles: Dict[int, bool] = Field(default_factory=dict)


@router.post("/{session_id}/candidates")
def update_candidates(session_id: str, req: ToggleRequest) -> Dict[str, Any]:
    """UI에서 켜고 끈 구간을 반영한다."""
    session = get_session(session_id)
    candidates = apply_manual_edits(_load_candidates(session), req.toggles)
    _save_candidates(session, candidates)
    timeline = _timeline(session)
    return ok(summary=summarize(candidates, timeline.duration))


# -------------------------------------------------------------------- 3) 전사

class TranscribeRequest(BaseModel):
    force: bool = False           # 캐시된 청크를 버리고 처음부터


@router.post("/{session_id}/transcribe")
def transcribe(session_id: str, req: TranscribeRequest) -> Dict[str, Any]:
    session = get_session(session_id)
    require_step(session, "transcribe")
    timeline = _timeline(session)
    settings = load_settings()

    audio_path = (session.data.get("analyze") or {}).get("audio")
    if not audio_path or not Path(audio_path).exists():
        raise HTTPException(status_code=409, detail="먼저 오디오 분석을 실행해 주세요.")

    def work(handle: JobHandle) -> Dict[str, Any]:
        tr = Transcriber(session.work_dir, model_size=settings.whisper_model,
                         language=settings.whisper_language,
                         chunk_sec=settings.whisper_chunk_sec,
                         compute_type=settings.whisper_compute_type)
        if req.force:
            tr.reset()
        handle.progress(0.02, "모델 준비 중")
        utterances = tr.run(audio_path, total_duration=timeline.duration,
                            progress=lambda p, m: handle.progress(0.02 + p * 0.96, m),
                            force=req.force)
        tr.save(utterances)

        session.invalidate_from("transcribe")
        session.complete("transcribe", utterances=len(utterances))
        SESSIONS.save(session)
        return {"utterances": len(utterances)}

    job = JOBS.submit(f"음성 전사 ({session.name})", work)
    return ok(job=job.to_dict())


@router.get("/{session_id}/transcript")
def read_transcript(session_id: str) -> Dict[str, Any]:
    session = get_session(session_id)
    tr = Transcriber(session.work_dir)
    utterances = tr.load()
    return {"utterances": [u.to_dict() for u in utterances], "count": len(utterances)}


# --------------------------------------------------------- 4) 대본 정렬 · 자막

class AlignRequest(BaseModel):
    script: str = ""              # 비우면 전사 결과를 그대로 자막으로 쓴다
    use_dictionary: bool = True


@router.post("/{session_id}/align")
def align(session_id: str, req: AlignRequest) -> Dict[str, Any]:
    session = get_session(session_id)
    require_step(session, "align")
    settings = load_settings()

    tr = Transcriber(session.work_dir)
    utterances = tr.load()
    if not utterances:
        raise HTTPException(status_code=409, detail="전사 결과가 없습니다. 전사를 먼저 실행해 주세요.")

    if req.use_dictionary:
        utterances = apply_dictionary_to_utterances(utterances, load_dictionary())

    if req.script.strip():
        cues = cues_from_script(req.script, utterances,
                                max_chars=settings.subtitle_max_chars,
                                min_duration=settings.subtitle_min_dur_sec)
        source = "script"
    else:
        cues = cues_from_transcript(utterances,
                                    max_chars=settings.subtitle_max_chars,
                                    min_duration=settings.subtitle_min_dur_sec)
        source = "transcript"

    save_cues(cues, _f(session, "cues_source.json"))
    if req.script.strip():
        _f(session, "script.txt").write_text(req.script, encoding="utf-8")

    session.invalidate_from("align")
    session.complete("align", cues=len(cues), source=source)
    SESSIONS.save(session)
    return ok(cues=[c.to_dict() for c in cues], count=len(cues), source=source)


@router.get("/{session_id}/cues")
def read_cues(session_id: str, edited: bool = False) -> Dict[str, Any]:
    """edited=true 면 컷 적용 후 시간대로 옮긴 자막을 준다."""
    session = get_session(session_id)
    name = "cues_edited.json" if edited else "cues_source.json"
    cues = load_cues(_f(session, name))
    if not cues and edited:
        cues = load_cues(_f(session, "cues_source.json"))
    return {"cues": [c.to_dict() for c in cues], "count": len(cues)}


# ---------------------------------------------------------------- 5) 컷 확정

@router.post("/{session_id}/confirm")
def confirm_edit(session_id: str) -> Dict[str, Any]:
    """컷을 확정하고, 자막을 편집본 시간대로 옮긴다."""
    session = get_session(session_id)
    require_step(session, "edit")
    timeline = _timeline(session)
    candidates = _load_candidates(session)

    time_map = TimeMap.from_candidates(candidates)
    if not time_map.kept:
        raise HTTPException(status_code=400, detail="살릴 구간이 하나도 없습니다.")

    source_cues = load_cues(_f(session, "cues_source.json"))
    edited_cues = shift_cues(source_cues, time_map) if source_cues else []
    save_cues(edited_cues, _f(session, "cues_edited.json"))
    if edited_cues:
        write_srt(edited_cues, _f(session, "subtitle.srt"))

    stats = summarize(candidates, timeline.duration)
    session.invalidate_from("edit")
    session.complete("edit", **stats, edited_cues=len(edited_cues))
    SESSIONS.save(session)
    return ok(summary=stats, cues=len(edited_cues))


# ------------------------------------------------------------- 6) 드래프트 빌드

class BuildRequestBody(BaseModel):
    draft_name: str = ""
    bgm_path: Optional[str] = None
    bgm_volume: float = Field(default=0.12, ge=0.0, le=1.0)
    sfx: List[Dict[str, Any]] = Field(default_factory=list)   # [{path, at}]
    sfx_volume: float = Field(default=0.6, ge=0.0, le=1.0)
    allow_replace: bool = False


@router.post("/{session_id}/build")
def build(session_id: str, req: BuildRequestBody) -> Dict[str, Any]:
    session = get_session(session_id)
    require_step(session, "build")
    settings = load_settings()
    timeline = _timeline(session)
    candidates = _load_candidates(session)
    cues = load_cues(_f(session, "cues_edited.json"))

    name = req.draft_name.strip() or f"{settings.draft_name_prefix}{time.strftime('%m%d_%H%M')}"
    sfx = [(s["path"], float(s.get("at", 0.0))) for s in req.sfx if s.get("path")]

    def work(handle: JobHandle) -> Dict[str, Any]:
        handle.progress(0.05, "드래프트 준비 중")
        builder = DraftBuilder(settings)
        build_req = BuildRequest(
            draft_name=name, timeline=timeline, candidates=candidates, cues=cues,
            bgm_path=req.bgm_path, bgm_volume=req.bgm_volume,
            sfx=sfx, sfx_volume=req.sfx_volume,
            profile=_profile(session), allow_replace=req.allow_replace,
        )
        result = builder.build(build_req, progress=handle.progress)

        srt = _f(session, "subtitle.srt")
        payload = result.to_dict()
        payload["srt_path"] = str(srt) if srt.exists() else None

        session.invalidate_from("build")
        session.complete("build", **payload)
        SESSIONS.save(session)
        return payload

    job = JOBS.submit(f"드래프트 빌드 ({name})", work)
    return ok(job=job.to_dict(), draft_name=name)
