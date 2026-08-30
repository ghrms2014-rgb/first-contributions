#!/usr/bin/env python3
"""릴스 소재를 뽑는다. 뉴스 반응 + 상시 주제를 앵글과 조합한다.

    python3 content-engine/ideas.py                  # 오늘 소재 뽑기
    python3 content-engine/ideas.py --used <키>       # 촬영했다고 기록
    python3 content-engine/ideas.py --used <키> --score 4
    python3 content-engine/ideas.py --stats          # 어떤 앵글이 잘 됐나

소재 고갈은 주제가 아니라 각도가 떨어질 때 온다. 같은 주제도 앵글이
바뀌면 다른 영상이 된다. 그래서 (주제 x 앵글) 조합 단위로 관리한다.

--score 는 1~5. 실제 성과를 넣으면 잘 먹힌 앵글이 더 자주 나온다.
아무거나 올리던 걸 되풀이하지 않으려면 이 기록이 핵심이다.
"""

import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
IDEAS_DIR = os.path.join(BASE, "ideas")
BANK_PATH = os.path.join(BASE, "ideas", "bank.json")
ITEMS_PATH = os.path.join(BASE, "data", "items.json")

NEWS_COUNT = 3
EVERGREEN_COUNT = 4
NEWS_ANGLES = ["react", "compare", "newbie", "money", "myth"]


def load_json(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, OSError):
        return fallback


def load_bank():
    bank = load_json(BANK_PATH, {})
    bank.setdefault("used", {})
    return bank


def save_bank(bank):
    os.makedirs(os.path.dirname(BANK_PATH), exist_ok=True)
    with open(BANK_PATH, "w", encoding="utf-8") as fp:
        json.dump(bank, fp, ensure_ascii=False, indent=1)


def key_for(topic, angle_id):
    digest = hashlib.sha1(topic.encode("utf-8")).hexdigest()[:6]
    return f"{angle_id}-{digest}"


def angle_weights(bank, angles):
    """성과 기록이 있으면 잘 된 앵글에 가중치를 준다. 없으면 전부 동일."""
    totals = {}
    for entry in bank["used"].values():
        score = entry.get("score")
        if score:
            totals.setdefault(entry["angle"], []).append(score)
    weights = {}
    for angle in angles:
        scores = totals.get(angle["id"], [])
        # 기록이 없는 앵글도 계속 시도되도록 기본값을 3(보통)으로 둔다.
        weights[angle["id"]] = (sum(scores) / len(scores)) if scores else 3.0
    return weights


def pick_weighted(rng, candidates, weights):
    pool = [(item, weights.get(item[1]["id"], 3.0) ** 2) for item in candidates]
    total = sum(weight for _, weight in pool)
    mark = rng.uniform(0, total)
    running = 0.0
    for item, weight in pool:
        running += weight
        if running >= mark:
            return item
    return pool[-1][0]


def build_sheet(today, seed):
    angles = load_json(os.path.join(BASE, "angles.json"), {"angles": []})["angles"]
    evergreen = load_json(os.path.join(BASE, "evergreen.json"), {"topics": {}})["topics"]
    items = load_json(ITEMS_PATH, [])
    bank = load_bank()
    by_id = {angle["id"]: angle for angle in angles}
    weights = angle_weights(bank, angles)
    rng = random.Random(seed)

    chosen = []

    # 1) 뉴스 반응 — 유통기한이 짧으니 먼저 소진한다.
    news_angles = [by_id[aid] for aid in NEWS_ANGLES if aid in by_id]
    for item in items[: NEWS_COUNT * 4]:
        if len(chosen) >= NEWS_COUNT:
            break
        options = [(item["title"], angle) for angle in news_angles
                   if key_for(item["title"], angle["id"]) not in bank["used"]]
        if not options:
            continue
        topic, angle = pick_weighted(rng, options, weights)
        chosen.append({"kind": "뉴스", "topic": topic, "angle": angle,
                       "link": item.get("link", ""), "source": item.get("source", ""),
                       "key": key_for(topic, angle["id"])})

    # 2) 상시 주제 — 뉴스가 없는 주에도 소재가 끊기지 않게 한다.
    flat = [(group, topic) for group, block in evergreen.items() for topic in block["items"]]
    rng.shuffle(flat)
    total_combos = 0
    for group, block in evergreen.items():
        allowed = [a for a in block["angles"] if not by_id.get(a, {}).get("news_only")]
        total_combos += len(block["items"]) * len(allowed)

    for group, topic in flat:
        if len(chosen) >= NEWS_COUNT + EVERGREEN_COUNT:
            break
        # 분류마다 성립하는 앵글이 다르다. 뉴스 전용 앵글도 여기서 뺀다.
        allowed = [by_id[a] for a in evergreen[group]["angles"]
                   if a in by_id and not by_id[a].get("news_only")]
        options = [(topic, angle) for angle in allowed
                   if key_for(topic, angle["id"]) not in bank["used"]]
        if not options:
            continue
        picked_topic, angle = pick_weighted(rng, options, weights)
        chosen.append({"kind": group, "topic": picked_topic, "angle": angle,
                       "link": "", "source": "", "key": key_for(picked_topic, angle["id"])})

    return chosen, len(bank["used"]), total_combos


def render(chosen, today, used_count, total_combos):
    out = [f"# 릴스 소재 — {today}", ""]
    if not chosen:
        out += ["소재를 뽑지 못했습니다. `evergreen.json` 이 비었거나 조합을 전부 소진했습니다.", ""]
    out += [f"조합 소진: {used_count} / {total_combos:,}", "",
            "촬영한 소재는 이렇게 기록하세요 (기록해야 다음에 안 나옵니다):", "",
            "```bash",
            "python3 content-engine/ideas.py --used <키> --score 4",
            "```", "", "---", ""]

    for index, idea in enumerate(chosen, start=1):
        angle = idea["angle"]
        out.append(f"## {index}. {idea['topic']}")
        out.append("")
        out.append(f"- **키**: `{idea['key']}`  ·  **분류**: {idea['kind']}  "
                   f"·  **앵글**: {angle['name']}  ·  **촬영 부담**: {angle['cost']}")
        out.append(f"- **어떻게 다룰까**: {angle['frame']}")
        out.append(f"- **첫 3초**: {angle['hook']}")
        out.append(f"- **왜 통하나**: {angle['why']}")
        if idea["link"]:
            out.append(f"- **출처**: [{idea['source']}]({idea['link']})")
        out.append("")
        out.append("훅 문장(직접 쓰세요): ")
        out.append("")

    out += ["---", "",
            "> 첫 3초가 전부입니다. 나머지는 이미 552개 찍으면서 아시는 대로 하시면 됩니다."]
    return "\n".join(out)


def mark_used(key, score):
    bank = load_bank()
    angle = key.split("-")[0]
    bank["used"][key] = {"angle": angle, "score": score,
                         "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    save_bank(bank)
    label = f"성과 {score}/5" if score else "성과 미기록"
    print(f"기록 완료: {key} ({angle}, {label})")
    if not score:
        print("  성과를 넣으면 잘 되는 앵글이 더 자주 나옵니다: --score 1~5")
    return 0


def show_stats():
    bank = load_bank()
    angles = load_json(os.path.join(BASE, "angles.json"), {"angles": []})["angles"]
    names = {angle["id"]: angle["name"] for angle in angles}
    rows = {}
    for entry in bank["used"].values():
        rows.setdefault(entry["angle"], []).append(entry.get("score"))

    if not rows:
        print("아직 기록이 없습니다. --used 로 촬영한 소재를 기록하세요.")
        return 0

    print(f"{'앵글':<12} {'사용':>4} {'평균성과':>8}")
    ranked = []
    for angle_id, scores in rows.items():
        rated = [s for s in scores if s]
        average = sum(rated) / len(rated) if rated else None
        ranked.append((average or 0, angle_id, len(scores), average))
    for _, angle_id, count, average in sorted(ranked, reverse=True):
        shown = f"{average:.1f}" if average else "-"
        print(f"{names.get(angle_id, angle_id):<12} {count:>4} {shown:>8}")
    print("\n평균이 높은 앵글이 다음 소재에 더 자주 나옵니다.")
    return 0


def main(argv):
    if "--stats" in argv:
        return show_stats()

    if "--used" in argv:
        position = argv.index("--used")
        if position + 1 >= len(argv):
            print("사용법: --used <키> [--score 1~5]")
            return 1
        score = None
        if "--score" in argv:
            try:
                score = int(argv[argv.index("--score") + 1])
            except (IndexError, ValueError):
                print("--score 는 1~5 사이 숫자여야 합니다.")
                return 1
            if not 1 <= score <= 5:
                print("--score 는 1~5 사이여야 합니다.")
                return 1
        return mark_used(argv[position + 1], score)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    chosen, used_count, total = build_sheet(today, seed=today)

    os.makedirs(IDEAS_DIR, exist_ok=True)
    path = os.path.join(IDEAS_DIR, f"{today}.md")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(render(chosen, today, used_count, total))

    news = sum(1 for idea in chosen if idea["kind"] == "뉴스")
    print(f"소재 {len(chosen)}개 (뉴스 {news} + 상시 {len(chosen) - news}) -> {path}")
    for idea in chosen:
        print(f"  [{idea['angle']['name']:<8}] {idea['topic'][:52]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
