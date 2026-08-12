#!/usr/bin/env python3
"""설정이 실제로 동작하는지 확인한다.

    python3 selfcheck.py

이 저장소를 만든 환경에서는 외부 네트워크가 막혀 있어 Open-Meteo 응답을
실제로 확인하지 못했다. 특히 조위 변수(sea_level_height_msl)가 이 좌표에서
제공되는지는 실행해봐야 안다. 처음 한 번은 이 스크립트로 확인하는 게 좋다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

import marine
from spots import DEFAULT_SPOT, TIMEZONE, get_spot

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kakao-notify"))

OK, FAIL, WARN = "  [OK]  ", "  [실패]", "  [경고]"


def check_domains() -> bool:
    """네트워크 정책이 필요한 도메인을 열어줬는지 본다."""
    print("\n1. 도메인 접근")
    domains = {
        "marine-api.open-meteo.com": "파고·너울·조위",
        "api.open-meteo.com": "바람",
        "kauth.kakao.com": "카카오 토큰 갱신",
        "kapi.kakao.com": "카카오 메시지 전송",
    }
    all_ok = True
    for host, purpose in domains.items():
        try:
            requests.get(f"https://{host}/", timeout=10)
            print(f"{OK} {host:32} {purpose}")
        except requests.RequestException as exc:
            print(f"{FAIL} {host:32} {purpose} — {type(exc).__name__}")
            all_ok = False
    return all_ok


def check_marine(spot_key: str) -> bool:
    """응답 형식과 조위 변수 제공 여부를 확인한다."""
    print("\n2. Open-Meteo 응답")
    spot = get_spot(spot_key)
    try:
        hourly = marine.fetch(spot.lat, spot.lon, TIMEZONE, days=3)
    except marine.MarineError as exc:
        print(f"{FAIL} {exc}")
        return False

    print(f"{OK} {spot.name} 시간축 {len(hourly['time'])}개 수신")

    ok = True
    for var in marine.MARINE_VARS + marine.WIND_VARS:
        values = hourly.get(var)
        if values and any(v is not None for v in values):
            sample = next(v for v in values if v is not None)
            print(f"{OK} {var:24} 예: {sample}")
        else:
            marker = FAIL if var == "sea_level_height_msl" else WARN
            print(f"{marker} {var:24} 값 없음")
            if var == "sea_level_height_msl":
                print("         → 조위를 못 받으면 물때가 빠집니다. marine.py의")
                print("           tide_extremes()가 빈 값을 처리하므로 죽지는 않지만,")
                print("           다른 조석 소스를 붙여야 합니다.")
                ok = False
    return ok


def check_brief(spot_key: str) -> bool:
    """실제 브리핑을 만들어 본다."""
    print("\n3. 브리핑 생성")
    import datetime as dt
    from zoneinfo import ZoneInfo

    import surf_brief

    spot = get_spot(spot_key)
    try:
        hourly = marine.fetch(spot.lat, spot.lon, TIMEZONE)
        day = dt.datetime.now(ZoneInfo(TIMEZONE)).date()
        result = surf_brief.build(spot, day, hourly)
    except marine.MarineError as exc:
        print(f"{FAIL} {exc}")
        return False

    compact = surf_brief.format_compact(spot, day, *result)
    print(f"{OK} 요약본 {len(compact)}자 (카카오 제한 200자)\n")
    print("\n".join("       " + line for line in compact.splitlines()))
    if len(compact) > 200:
        print(f"{WARN} 200자를 넘어 잘립니다. format_compact를 줄이세요.")
        return False
    return True


def check_kakao() -> bool:
    print("\n4. 카카오 인증")
    try:
        from kakao_notify import KakaoError, get_access_token
    except ImportError:
        print(f"{FAIL} kakao_notify를 찾을 수 없습니다 (tools/kakao-notify 확인)")
        return False

    try:
        get_access_token()
    except KakaoError as exc:
        print(f"{FAIL} {exc}")
        return False
    print(f"{OK} 액세스 토큰 정상")
    return True


def main() -> int:
    spot_key = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SPOT
    print(f"점검 대상 포인트: {spot_key}")

    results = [
        check_domains(),
        check_marine(spot_key),
        check_brief(spot_key),
        check_kakao(),
    ]

    print()
    if all(results):
        print("전부 통과. 이제 --send 로 실제 전송해보세요:")
        print(f"  python3 surf_brief.py --spot {spot_key} --send")
        return 0
    print("실패한 항목이 있습니다. 위 메시지와 README의 문제 해결 표를 확인하세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
