"""pyCapCut 호출 + 후처리 주입."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pycapcut as capcut

from ..config import PATHS, Settings
from .capcut_draft import (CalibrationProfile, apply_profile_to_text, content_path,
                           draft_dir, fix_layers)
from .cut_edit import CutCandidate, TimeMap
from .logging_util import get_logger
from .script_align import Cue
from .sources import SourceTimeline

log = get_logger("builder")

SEC = capcut.SEC  # 1초 = 1_000_000 마이크로초

TRACK_MAIN = "메인"
TRACK_SUBTITLE = "자막"
TRACK_BGM = "배경음"
TRACK_SFX = "효과음"

ProgressFn = Callable[[float, str], None]


def us(seconds: float) -> int:
    """초 → 마이크로초. pycapcut.tim() 은 float 을 마이크로초로 보므로 직접 환산한다."""
    return int(round(seconds * SEC))


def trange(start: float, duration: float) -> capcut.Timerange:
    return capcut.Timerange(us(start), us(duration))


@dataclass
class BuildRequest:
    draft_name: str
    timeline: SourceTimeline
    candidates: List[CutCandidate]
    cues: List[Cue] = field(default_factory=list)
    bgm_path: Optional[str] = None
    bgm_volume: float = 0.12
    sfx: List[Tuple[str, float]] = field(default_factory=list)  # (파일, 편집본 시각)
    sfx_volume: float = 0.6
    profile: Optional[CalibrationProfile] = None
    allow_replace: bool = False


@dataclass
class BuildResult:
    draft_name: str
    draft_path: str
    duration: float
    video_segments: int
    subtitle_segments: int
    audio_segments: int
    srt_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class DraftBuilder:
    """컷 결과와 자막을 캡컷 드래프트로 굽는다.

    pyCapCut 이 만들어 주는 범위까지는 그대로 쓰고, 그 위에 우리가 필요한
    보정(레이어 순서, 캘리브레이션 스타일)을 JSON 단계에서 덧씌운다.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.draft_folder:
            raise RuntimeError("캡컷 드래프트 폴더가 설정되지 않았습니다. 설정 단계를 먼저 마쳐 주세요.")
        self.settings = settings
        self.root = Path(settings.draft_folder)
        if not self.root.is_dir():
            raise RuntimeError(f"드래프트 폴더가 없습니다: {self.root}")

    # ------------------------------------------------------------------ 본체
    def build(self, req: BuildRequest, progress: Optional[ProgressFn] = None) -> BuildResult:
        s = self.settings
        folder = capcut.DraftFolder(str(self.root))

        width = req.profile.width if req.profile else s.width
        height = req.profile.height if req.profile else s.height
        fps = req.profile.fps if req.profile else s.fps

        script = folder.create_draft(req.draft_name, width, height, fps,
                                     allow_replace=req.allow_replace)
        log.info("드래프트 생성: %s (%dx%d @%dfps)", req.draft_name, width, height, fps)

        time_map = TimeMap.from_candidates(req.candidates)
        if not time_map.kept:
            raise RuntimeError("살릴 구간이 하나도 없습니다. 컷 편집 단계를 확인해 주세요.")

        if progress:
            progress(0.15, "영상 트랙 구성 중")
        n_video = self._add_video(script, req.timeline, time_map)

        if progress:
            progress(0.5, "자막 트랙 구성 중")
        n_text = self._add_subtitles(script, req.cues, req.profile)

        if progress:
            progress(0.7, "오디오 트랙 구성 중")
        n_audio = self._add_audio(script, req, time_map.duration)

        if progress:
            progress(0.85, "드래프트 저장 중")
        script.save()

        # ---- 여기서부터가 후처리 주입 ----
        self._postprocess(req)

        if progress:
            progress(1.0, "완료")

        result = BuildResult(
            draft_name=req.draft_name,
            draft_path=str(self.root / req.draft_name),
            duration=time_map.duration,
            video_segments=n_video,
            subtitle_segments=n_text,
            audio_segments=n_audio,
        )
        log.info("빌드 완료: 영상 %d · 자막 %d · 오디오 %d · %.1f초",
                 n_video, n_text, n_audio, time_map.duration)
        return result

    # ------------------------------------------------------------- 영상 트랙
    def _add_video(self, script, timeline: SourceTimeline, time_map: TimeMap) -> int:
        script.add_track(capcut.TrackType.video, TRACK_MAIN)

        materials: Dict[str, capcut.VideoMaterial] = {}
        count = 0
        cursor = 0.0  # 편집본 위 커서

        for kept_start, kept_end in time_map.kept:
            # 살릴 구간이 파일 경계를 넘으면 파일별로 쪼갠다
            for clip, local_start, local_end in timeline.split_span(kept_start, kept_end):
                if clip.path not in materials:
                    materials[clip.path] = capcut.VideoMaterial(clip.path)
                duration = local_end - local_start
                segment = capcut.VideoSegment(
                    materials[clip.path],
                    target_timerange=trange(cursor, duration),
                    source_timerange=trange(local_start, duration),
                )
                script.add_segment(segment, TRACK_MAIN)
                cursor += duration
                count += 1
        return count

    # ------------------------------------------------------------- 자막 트랙
    def _add_subtitles(self, script, cues: List[Cue],
                       profile: Optional[CalibrationProfile]) -> int:
        if not cues:
            return 0
        script.add_track(capcut.TrackType.text, TRACK_SUBTITLE)

        size = (profile.text_size if profile and profile.text_size
                else self.settings.subtitle_font_size)
        color = tuple(profile.text_color) if profile and profile.text_color else (1.0, 1.0, 1.0)
        style = capcut.TextStyle(size=size, color=color, align=1, auto_wrapping=False)

        clip_settings = None
        if profile and (profile.text_transform_x is not None or profile.text_transform_y is not None):
            clip_settings = capcut.ClipSettings(
                transform_x=profile.text_transform_x or 0.0,
                transform_y=profile.text_transform_y or 0.0,
            )

        for cue in cues:
            script.add_segment(capcut.TextSegment(
                cue.text, trange(cue.start, cue.duration),
                style=style, clip_settings=clip_settings,
            ), TRACK_SUBTITLE)
        return len(cues)

    # ------------------------------------------------------------ 오디오 트랙
    def _add_audio(self, script, req: BuildRequest, total: float) -> int:
        count = 0

        if req.bgm_path and Path(req.bgm_path).exists():
            script.add_track(capcut.TrackType.audio, TRACK_BGM)
            material = capcut.AudioMaterial(req.bgm_path)
            bgm_len = getattr(material, "duration", 0) / SEC or total
            # 배경음이 짧으면 영상 길이만큼 반복해 깐다
            cursor = 0.0
            while cursor < total - 0.05:
                piece = min(bgm_len, total - cursor)
                script.add_segment(capcut.AudioSegment(
                    material, target_timerange=trange(cursor, piece),
                    source_timerange=trange(0.0, piece), volume=req.bgm_volume,
                ), TRACK_BGM)
                cursor += piece
                count += 1

        valid_sfx = [(p, t) for p, t in req.sfx if Path(p).exists() and 0 <= t < total]
        if valid_sfx:
            script.add_track(capcut.TrackType.audio, TRACK_SFX)
            for path, at in valid_sfx:
                material = capcut.AudioMaterial(path)
                length = getattr(material, "duration", 0) / SEC
                length = min(length or 1.0, max(total - at, 0.05))
                script.add_segment(capcut.AudioSegment(
                    material, target_timerange=trange(at, length), volume=req.sfx_volume,
                ), TRACK_SFX)
                count += 1

        return count

    # ------------------------------------------------------------- 후처리 주입
    def _postprocess(self, req: BuildRequest) -> None:
        """저장된 draft_content.json 을 열어 레이어와 자막 스타일을 손본다."""
        path = content_path(draft_dir(self.root, req.draft_name))
        content = json.loads(path.read_text(encoding="utf-8"))

        content = fix_layers(content)
        if req.profile:
            content = apply_profile_to_text(content, req.profile)

        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        log.info("후처리 주입 완료: %s", path.name)
