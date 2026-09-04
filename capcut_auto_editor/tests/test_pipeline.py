"""파이프라인 핵심 로직 테스트. 외부 프로그램(ffmpeg, whisper) 없이 돈다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.audio_analysis import Silence, speech_spans
from app.services.capcut_draft import fix_layers
from app.services.cut_edit import TimeMap, build_candidates, summarize
from app.services.line_break import one_line, split_lines
from app.services.script_align import (Cue, apply_dictionary, cues_from_script,
                                       cues_from_transcript, shift_cues, to_srt)
from app.services.session import SESSIONS, StepLocked
from app.services.sources import Clip, SourceTimeline
from app.services.transcribe import Utterance, Word


# ------------------------------------------------------------------ 줄 나누기

def test_split_respects_max_chars():
    text = "안녕하세요, 오늘은 캡컷 자동 편집기를 소개합니다. 무음을 잘라내고 자막까지 붙여 줍니다!"
    for line in one_line(text, 18):
        assert len(line) <= 18


def test_split_breaks_at_sentence_end():
    lines = split_lines("첫 문장이다. 둘째 문장이다.", 40)
    assert lines == ["첫 문장이다.", "둘째 문장이다."]


def test_empty_text_yields_nothing():
    assert one_line("   ") == []


# -------------------------------------------------------------- 무음 → 컷 후보

def test_speech_spans_are_silence_complement():
    spans = speech_spans([Silence(2.0, 3.0), Silence(6.0, 8.0)], 12.0)
    assert spans == [(0.0, 2.0), (3.0, 6.0), (8.0, 12.0)]


def test_padding_merges_adjacent_spans():
    spans = speech_spans([Silence(2.0, 2.2)], 5.0, padding=0.5)
    assert spans == [(0.0, 5.0)]  # 여유를 주면 붙어 버린다


def test_short_candidates_dropped_by_default():
    candidates = build_candidates([Silence(1.0, 5.0), Silence(5.1, 9.0)], 10.0,
                                  padding=0.0, min_keep=0.25)
    short = [c for c in candidates if c.duration < 0.25]
    assert short and all(not c.keep for c in short)


# ----------------------------------------------------------------- 시간 매핑

def _sample_map() -> TimeMap:
    return TimeMap([(0.0, 2.0), (3.0, 6.0), (8.0, 12.0)])


def test_time_map_shifts_by_removed_amount():
    tm = _sample_map()
    assert tm.duration == pytest.approx(9.0)
    assert tm.to_edited(1.0) == pytest.approx(1.0)
    assert tm.to_edited(4.0) == pytest.approx(3.0)   # 1초가 잘려 나감
    assert tm.to_edited(9.0) == pytest.approx(6.0)   # 3초가 잘려 나감


def test_time_map_round_trip():
    tm = _sample_map()
    for src in (0.5, 3.5, 11.0):
        assert tm.to_source(tm.to_edited(src)) == pytest.approx(src)


def test_cut_region_snaps_forward():
    tm = _sample_map()
    assert tm.to_edited(2.5) == pytest.approx(2.0)   # 잘린 구간 → 다음 시작점


def test_summary_counts_saved_time():
    stats = summarize(build_candidates([Silence(2.0, 3.0)], 10.0, padding=0.0), 10.0)
    assert stats["saved_seconds"] == pytest.approx(1.0)


# ------------------------------------------------------------------ 소스 타임라인

def _timeline() -> SourceTimeline:
    return SourceTimeline([
        Clip(index=0, path="a.mp4", duration=10.0, offset=0.0),
        Clip(index=1, path="b.mp4", duration=5.0, offset=10.0),
    ])


def test_global_to_local_conversion():
    tl = _timeline()
    clip, local = tl.to_local(12.0)
    assert clip.path == "b.mp4" and local == pytest.approx(2.0)


def test_span_split_across_files():
    parts = _timeline().split_span(8.0, 13.0)
    assert [(c.path, round(a, 1), round(b, 1)) for c, a, b in parts] == [
        ("a.mp4", 8.0, 10.0), ("b.mp4", 0.0, 3.0)]


def test_reorder_recomputes_offsets():
    tl = _timeline().reorder([1, 0])
    assert [c.path for c in tl.clips] == ["b.mp4", "a.mp4"]
    assert [c.offset for c in tl.clips] == [0.0, 5.0]


# --------------------------------------------------------------- 대본 정렬

def _utterances() -> list:
    words = [("안녕하세요", 0.0, 0.8), ("오늘은", 0.9, 1.4), ("캡켓", 1.5, 2.0),
             ("소개합니다", 2.1, 3.0)]
    return [Utterance(0.0, 3.0, " ".join(w[0] for w in words),
                      [Word(s, e, t) for t, s, e in words])]


def test_script_wording_wins_over_transcript():
    cues = cues_from_script("안녕하세요, 오늘은 캡컷 소개합니다.", _utterances(), max_chars=30)
    joined = " ".join(c.text for c in cues)
    assert "캡컷" in joined and "캡켓" not in joined


def test_script_alignment_keeps_transcript_timing():
    cues = cues_from_script("안녕하세요, 오늘은 캡컷 소개합니다.", _utterances(), max_chars=30)
    assert cues[0].start == pytest.approx(0.0, abs=0.2)
    assert cues[-1].end == pytest.approx(3.0, abs=0.3)


def test_transcript_only_fallback():
    cues = cues_from_transcript(_utterances(), max_chars=10)
    assert cues and all(len(c.text) <= 10 for c in cues)


def test_dictionary_prefers_longer_keys():
    assert apply_dictionary("캡켓프로", {"캡켓": "캡컷", "캡켓프로": "캡컷 프로"}) == "캡컷 프로"


def test_cues_shift_and_drop_with_cuts():
    cues = [Cue(0.5, 1.5, "남는다"), Cue(2.2, 2.8, "잘린다"), Cue(4.0, 5.0, "옮겨진다")]
    shifted = shift_cues(cues, TimeMap([(0.0, 2.0), (3.0, 6.0)]))
    assert [c.text for c in shifted] == ["남는다", "옮겨진다"]
    assert shifted[-1].start == pytest.approx(3.0)


def test_srt_format():
    srt = to_srt([Cue(1.5, 2.25, "한 줄")])
    assert "00:00:01,500 --> 00:00:02,250" in srt


# ------------------------------------------------------------------ 단계 잠금

def test_steps_lock_until_previous_done():
    session = SESSIONS.create("테스트")
    try:
        with pytest.raises(StepLocked):
            session.require("build")
        for step in ("setup", "sources", "calibration", "transcribe", "align", "edit"):
            session.complete(step)
        session.require("build")  # 이제 열린다
    finally:
        SESSIONS.delete(session.id)


def test_redoing_a_step_invalidates_later_ones():
    session = SESSIONS.create("테스트")
    try:
        for step in ("setup", "sources", "calibration"):
            session.complete(step)
        session.invalidate_from("sources")
        assert session.completed == ["setup"]
    finally:
        SESSIONS.delete(session.id)


# ---------------------------------------------------------------- 레이어 교정

def test_text_renders_above_video():
    content = fix_layers({"tracks": [
        {"type": "text", "segments": [{}]},
        {"type": "video", "segments": [{}]},
    ]})
    order = {t["type"]: t["render_index"] for t in content["tracks"]}
    assert order["text"] > order["video"]


def test_audio_track_keeps_no_render_index():
    content = fix_layers({"tracks": [
        {"type": "audio", "segments": [{}]},
        {"type": "video", "segments": [{}]},
    ]})
    audio = next(t for t in content["tracks"] if t["type"] == "audio")
    assert "render_index" not in audio
