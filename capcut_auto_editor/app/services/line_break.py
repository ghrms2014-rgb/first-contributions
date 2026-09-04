"""문장부호 기준 한 줄 자막 만들기."""
from __future__ import annotations

import re
from typing import List

# 여기서 끊으면 가장 자연스럽다 (우선순위 높은 순)
_HARD_BREAK = re.compile(r"(?<=[.!?。！？\n])\s*")
_SOFT_BREAK = re.compile(r"(?<=[,、·…:;])\s*")
# 한국어 연결어미 뒤 — 마지막 수단으로 쓰는 끊기 지점
_CLAUSE_TAIL = re.compile(r"(?<=(?:는데|지만|면서|니까|어서|아서|고요|는요|구요))\s")

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """줄바꿈과 중복 공백을 한 칸으로 정리한다."""
    return _WS.sub(" ", text or "").strip()


def _split_keep(pattern: re.Pattern, text: str) -> List[str]:
    parts = [p.strip() for p in pattern.split(text)]
    return [p for p in parts if p]


def _split_by_length(chunk: str, max_chars: int) -> List[str]:
    """부호가 없어 길기만 한 덩어리를 공백 기준으로 자른다."""
    if len(chunk) <= max_chars:
        return [chunk]

    out: List[str] = []
    words = chunk.split(" ")
    line = ""
    for w in words:
        cand = f"{line} {w}".strip()
        if len(cand) <= max_chars or not line:
            line = cand
        else:
            out.append(line)
            line = w
    if line:
        out.append(line)

    # 공백조차 없는 아주 긴 단어는 글자수로 강제 분할
    final: List[str] = []
    for piece in out:
        while len(piece) > max_chars:
            final.append(piece[:max_chars])
            piece = piece[max_chars:]
        if piece:
            final.append(piece)
    return final


def split_lines(text: str, max_chars: int = 18) -> List[str]:
    """자막 한 줄에 들어갈 만큼씩 끊는다.

    문장부호 → 쉼표류 → 연결어미 → 공백 순으로 물러나며 자른다.
    """
    text = normalize(text)
    if not text:
        return []

    lines: List[str] = []
    for sentence in _split_keep(_HARD_BREAK, text) or [text]:
        if len(sentence) <= max_chars:
            lines.append(sentence)
            continue
        for clause in _split_keep(_SOFT_BREAK, sentence) or [sentence]:
            if len(clause) <= max_chars:
                lines.append(clause)
                continue
            for tail in _split_keep(_CLAUSE_TAIL, clause) or [clause]:
                lines.extend(_split_by_length(tail, max_chars))
    return [ln for ln in lines if ln]


def merge_short(lines: List[str], min_chars: int = 4, max_chars: int = 18) -> List[str]:
    """너무 짧은 조각은 앞줄에 붙인다. 한 글자 자막이 튀는 걸 막는다."""
    out: List[str] = []
    for line in lines:
        if out and len(line) < min_chars and len(out[-1]) + len(line) + 1 <= max_chars:
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def one_line(text: str, max_chars: int = 18) -> List[str]:
    """split_lines + merge_short. 자막 만들 때 쓰는 진입점."""
    return merge_short(split_lines(text, max_chars), max_chars=max_chars)
