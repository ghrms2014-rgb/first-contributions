#!/usr/bin/env python3
"""수집한 항목에 점수를 매겨 오늘 발행할 뉴스레터 '초안'을 만든다.

초안은 완성 원고가 아니다. 사람이 한 줄 코멘트를 채워 넣어야
읽을 가치가 생기고, 그래야 검색/구독자에게도 통한다.
"""

import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
ITEMS_PATH = os.path.join(BASE, "data", "items.json")
DRAFTS_DIR = os.path.join(BASE, "drafts")


def parse_when(value):
    from collect import parse_date

    return parse_date(value)


def load_items():
    if not os.path.exists(ITEMS_PATH):
        return []
    with open(ITEMS_PATH, encoding="utf-8") as fp:
        return json.load(fp)


def score_items(items, config, now=None):
    now = now or datetime.now(timezone.utc)
    keywords = config["keywords"]
    blocklist = [word.lower() for word in config.get("blocklist", [])]
    max_age_hours = config["draft"]["max_age_hours"]

    scored = []
    seen_titles = set()
    for item in items:
        haystack = f"{item['title']} {item.get('summary', '')}".lower()
        if any(word in haystack for word in blocklist):
            continue

        # 같은 사건을 여러 매체가 쓰면 제목이 거의 같다. 앞부분만 보고 하나만 남긴다.
        fingerprint = "".join(item["title"].lower().split())[:28]
        if fingerprint in seen_titles:
            continue
        seen_titles.add(fingerprint)

        moment = parse_when(item.get("published") or item.get("collected_at"))
        if moment is None:
            age_hours = max_age_hours
        else:
            age_hours = (now - moment).total_seconds() / 3600
        if age_hours > max_age_hours or age_hours < -6:
            continue

        score = 0.0
        hits = []
        title_lower = item["title"].lower()
        for keyword, weight in keywords.items():
            key = keyword.lower()
            if key in title_lower:
                score += weight * 3
                hits.append(keyword)
            elif key in haystack:
                score += weight
                hits.append(keyword)

        # 최신일수록 가산점 (48시간이면 0점).
        score += max(0.0, (max_age_hours - age_hours) / max_age_hours) * 4

        enriched = dict(item)
        enriched["score"] = round(score, 2)
        enriched["hits"] = sorted(set(hits))
        enriched["age_hours"] = round(age_hours, 1)
        scored.append(enriched)

    scored.sort(key=lambda entry: entry["score"], reverse=True)
    return scored


def shorten(text, limit=160):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def render_draft(scored, config, today):
    brand = config["brand"]
    picks = scored[: config["draft"]["picks"]]
    candidates = scored[: config["draft"]["headline_candidates"]]

    lines = []
    lines.append("---")
    lines.append(f'title: "{brand["title"]} — {today}"')
    lines.append(f"date: {today}")
    lines.append("status: draft")
    lines.append("---")
    lines.append("")
    lines.append(f"# {brand['title']} — {today}")
    lines.append("")
    lines.append(f"> {brand['tagline']}")
    lines.append("")

    lines.append("## 0. 제목 후보 (하나 고르고 나머지는 지우세요)")
    lines.append("")
    if candidates:
        for entry in candidates:
            lines.append(f"- {shorten(entry['title'], 70)}")
    else:
        lines.append("- (수집된 항목이 없습니다. config.json 의 소스를 확인하세요.)")
    lines.append("")

    lines.append("## 1. 오늘의 픽")
    lines.append("")
    if not picks:
        lines.append("_수집된 항목이 없습니다._")
        lines.append("")
    for index, entry in enumerate(picks, start=1):
        lines.append(f"### {index}. {entry['title']}")
        lines.append("")
        summary = shorten(entry.get("summary"), 220)
        if summary:
            lines.append(f"{summary}")
            lines.append("")
        lines.append(f"**왜 중요한가:** _여기에 본인 문장 1~2줄. 이 줄이 이 뉴스레터의 유일한 상품입니다._")
        lines.append("")
        lines.append(f"출처: [{entry['source']}]({entry['link']})")
        lines.append("")

    lines.append("## 2. 짧게 훑기")
    lines.append("")
    for entry in scored[config["draft"]["picks"] : config["draft"]["picks"] + 5]:
        lines.append(f"- [{shorten(entry['title'], 80)}]({entry['link']}) — {entry['source']}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("### 발행 전 체크리스트")
    lines.append("")
    lines.append("- [ ] '왜 중요한가' 문장을 전부 내 말로 채웠다 (빈칸이 남으면 발행하지 않는다)")
    lines.append("- [ ] 제목 후보 중 하나만 남기고 지웠다")
    lines.append("- [ ] 링크 5개를 실제로 눌러봤다 (죽은 링크/광고성 기사 제거)")
    lines.append("- [ ] 남의 문장을 그대로 옮긴 곳이 없다 (요약은 인용, 본문은 내 문장)")
    lines.append("- [ ] 제휴 링크를 넣었다면 '광고 포함'을 본문 맨 위에 표기했다")
    lines.append("")
    lines.append("완성했으면 이 파일을 `content-engine/posts/` 로 옮기고 `status: published` 로 바꾸세요.")
    lines.append("")

    return "\n".join(lines)


def main():
    from collect import load_config

    config = load_config()
    items = load_items()
    scored = score_items(items, config)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    path = os.path.join(DRAFTS_DIR, f"{today}.md")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(render_draft(scored, config, today))

    print(f"후보 {len(items)}건 -> 선별 {len(scored)}건 -> 초안 작성: {path}")
    for entry in scored[: config["draft"]["picks"]]:
        print(f"  {entry['score']:>6}  {shorten(entry['title'], 60)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
