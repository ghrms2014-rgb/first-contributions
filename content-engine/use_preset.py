#!/usr/bin/env python3
"""주제 프리셋을 config.json 에 적용한다.

    python3 content-engine/use_preset.py                    # 목록 보기
    python3 content-engine/use_preset.py ai-small-business  # 적용

브랜드 이름을 이미 직접 고쳤다면 그대로 두고 소스/키워드만 바꾸려면:

    python3 content-engine/use_preset.py ai-small-business --keep-brand
"""

import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
PRESETS_DIR = os.path.join(BASE, "presets")


def available():
    if not os.path.isdir(PRESETS_DIR):
        return []
    return sorted(
        name[:-5] for name in os.listdir(PRESETS_DIR) if name.endswith(".json")
    )


def show_list():
    names = available()
    if not names:
        print("presets/ 에 프리셋이 없습니다.")
        return 1
    print("사용 가능한 프리셋:\n")
    for name in names:
        with open(os.path.join(PRESETS_DIR, f"{name}.json"), encoding="utf-8") as fp:
            preset = json.load(fp)
        print(f"  {name}")
        print(f"      {preset.get('note', '')}")
        print(f"      제목: {preset['brand']['title']}")
        print()
    print("적용:  python3 content-engine/use_preset.py <이름>")
    return 0


def apply(name, keep_brand):
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    if not os.path.exists(path):
        print(f"'{name}' 프리셋이 없습니다. 사용 가능: {', '.join(available())}")
        return 1

    with open(path, encoding="utf-8") as fp:
        preset = json.load(fp)
    with open(CONFIG_PATH, encoding="utf-8") as fp:
        config = json.load(fp)

    # 되돌릴 수 있게 백업부터 남긴다.
    backup = CONFIG_PATH + ".backup"
    shutil.copyfile(CONFIG_PATH, backup)

    for key in ("sources", "keywords", "blocklist"):
        if key in preset:
            config[key] = preset[key]

    if not keep_brand:
        brand = dict(config.get("brand", {}))
        brand.update({k: v for k, v in preset["brand"].items() if v})
        config["brand"] = brand

    with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
        json.dump(config, fp, ensure_ascii=False, indent=2)

    print(f"'{name}' 적용 완료.")
    print(f"  제목:   {config['brand']['title']}")
    print(f"  소스:   {len(config['sources'])}개")
    print(f"  키워드: {len(config['keywords'])}개")
    print(f"  백업:   {os.path.relpath(backup, os.path.dirname(BASE))}")
    print("\n이어서 실행:  python3 content-engine/run.py")
    return 0


def main(argv):
    args = [item for item in argv if not item.startswith("-")]
    keep_brand = "--keep-brand" in argv
    if not args:
        return show_list()
    return apply(args[0], keep_brand)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
