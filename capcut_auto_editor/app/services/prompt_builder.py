"""마케팅 문구 프롬프트 만들기."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .line_break import normalize
from .script_align import Cue

PLATFORMS: Dict[str, Dict[str, Any]] = {
    "youtube": {"label": "유튜브", "title_limit": 100, "desc_limit": 5000, "tags": 15},
    "shorts": {"label": "유튜브 쇼츠", "title_limit": 60, "desc_limit": 1000, "tags": 10},
    "instagram": {"label": "인스타그램 릴스", "title_limit": 40, "desc_limit": 2200, "tags": 20},
    "tiktok": {"label": "틱톡", "title_limit": 40, "desc_limit": 2200, "tags": 10},
    "blog": {"label": "블로그", "title_limit": 60, "desc_limit": 8000, "tags": 10},
}

TONES = {
    "friendly": "편안하고 다정한 말투",
    "professional": "신뢰감 있는 전문가 말투",
    "punchy": "짧고 강한 후킹 위주 말투",
    "informative": "차분하게 정보를 전달하는 말투",
}


@dataclass
class PromptSpec:
    platform: str = "youtube"
    tone: str = "friendly"
    keywords: List[str] = field(default_factory=list)
    audience: str = ""
    cta: str = ""
    extra: str = ""
    transcript_chars: int = 3000

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def transcript_text(cues: List[Cue], limit: int = 3000) -> str:
    """자막을 이어 붙여 프롬프트에 넣을 본문을 만든다."""
    body = normalize(" ".join(c.text for c in cues))
    if len(body) <= limit:
        return body
    # 앞부분(후킹)과 뒷부분(마무리)을 남기는 편이 요약에 유리하다
    head = body[: int(limit * 0.7)]
    tail = body[-int(limit * 0.3):]
    return f"{head}\n…(중략)…\n{tail}"


def build_prompt(cues: List[Cue], spec: PromptSpec, *,
                 video_title: str = "", duration_sec: float = 0.0) -> str:
    """LLM 에 그대로 붙여 넣을 마케팅 문구 프롬프트."""
    meta = PLATFORMS.get(spec.platform, PLATFORMS["youtube"])
    tone = TONES.get(spec.tone, TONES["friendly"])
    body = transcript_text(cues, spec.transcript_chars)

    lines: List[str] = [
        f"너는 {meta['label']} 채널을 오래 운영해 온 한국어 콘텐츠 마케터야.",
        "아래 영상 내용을 읽고 실제로 클릭을 부르는 문구를 만들어 줘.",
        "",
        "## 영상 정보",
    ]
    if video_title:
        lines.append(f"- 가제: {video_title}")
    if duration_sec:
        lines.append(f"- 길이: 약 {int(duration_sec // 60)}분 {int(duration_sec % 60)}초")
    lines.append(f"- 플랫폼: {meta['label']}")
    lines.append(f"- 말투: {tone}")
    if spec.audience:
        lines.append(f"- 주 시청자: {spec.audience}")
    if spec.keywords:
        lines.append(f"- 꼭 넣을 키워드: {', '.join(spec.keywords)}")
    if spec.cta:
        lines.append(f"- 유도할 행동: {spec.cta}")

    lines += [
        "",
        "## 영상 내용 (자막 전문)",
        body or "(자막이 비어 있음)",
        "",
        "## 만들어 줄 것",
        f"1. 제목 후보 5개 — 각 {meta['title_limit']}자 이내, 서로 다른 각도로",
        f"2. 설명문 1개 — {meta['desc_limit']}자 이내, 첫 두 줄에 핵심이 오게",
        f"3. 해시태그 {meta['tags']}개 — 검색량 큰 것과 좁고 정확한 것을 섞어서",
        "4. 첫 3초 후킹 멘트 3개 — 영상 맨 앞에 넣을 한 문장",
        "5. 썸네일 문구 2개 — 8자 이내",
        "",
        "## 규칙",
        "- 영상에 없는 내용은 지어내지 말 것",
        "- 과장된 낚시 표현은 피하고, 내용과 맞는 범위에서 궁금하게 만들 것",
        "- 결과는 위 번호 순서대로, 군더더기 설명 없이",
    ]
    if spec.extra:
        lines += ["", "## 추가 요청", spec.extra]

    return "\n".join(lines)


def build_summary_prompt(cues: List[Cue], limit: int = 3000) -> str:
    """영상 요약용 짧은 프롬프트."""
    return (
        "아래는 한 영상의 자막 전문이야. 이 영상이 어떤 내용인지 "
        "3문장으로 요약하고, 핵심 키워드 5개를 뽑아 줘.\n\n"
        f"{transcript_text(cues, limit)}"
    )
