#!/usr/bin/env python3
"""수집 -> 초안 -> 사이트 빌드를 한 번에 실행한다.

    python3 content-engine/run.py
"""

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import build_site  # noqa: E402
import collect  # noqa: E402
import draft  # noqa: E402

steps = [("수집", collect.main), ("초안", draft.main), ("사이트 빌드", build_site.main)]

for number, (label, run) in enumerate(steps, start=1):
    print(f"\n[{number}/{len(steps)}] {label}")
    code = run()
    if code:
        print(f"'{label}' 단계 실패 (종료 코드 {code})")
        raise SystemExit(code)

print("\n완료. content-engine/drafts/ 에서 오늘 초안을 확인하세요.")
