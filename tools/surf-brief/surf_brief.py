#!/usr/bin/env python3
"""갯바위 낚시용 아침 브리핑 — 파고·너울·물때를 요약해 카카오톡으로 보낸다.

    python3 surf_brief.py                    # 오늘 브리핑을 화면에 출력
    python3 surf_brief.py --spot basspoint   # 포인트 지정
    python3 surf_brief.py --send             # 카카오톡으로 전송
    python3 surf_brief.py --date 2026-08-15  # 특정 날짜

토요일에 낚시를 나가므로, 오늘이 토요일이 아니면 다가오는 토요일 전망을
한 줄 덧붙인다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import marine
from marine import Conditions, Extreme, MarineError, compass
from spots import DEFAULT_SPOT, SPOTS, TIMEZONE, Spot, get_spot

# 같은 저장소의 카카오 도구를 재사용한다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kakao-notify"))

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]
SATURDAY = 5

# 갯바위에 실제로 서 있을 만한 시간대. 이 구간의 최악 조건으로 위험도를 매긴다.
DAY_START, DAY_END = 5, 19


def _daylight_indices(times: list[dt.datetime], day: dt.date) -> list[int]:
    return [
        i for i, t in enumerate(times)
        if t.date() == day and DAY_START <= t.hour <= DAY_END
    ]


def worst_of_day(hourly: dict, day: dt.date, spot: Spot) -> tuple[Conditions, str, list[str]]:
    """그날 낮 시간대 중 가장 위험한 시점의 조건을 돌려준다."""
    times = marine.parse_times(hourly)
    indices = _daylight_indices(times, day)
    if not indices:
        raise MarineError(f"{day} 예보가 응답 범위 밖입니다. --date 를 확인하세요.")

    ranking = {"양호": 0, "주의": 1, "위험": 2, "매우위험": 3, "판단불가": -1}
    best_index, best = indices[0], None

    for i in indices:
        cond = marine.conditions_at(hourly, i)
        level, reasons = marine.risk(cond, spot.exposed_from)
        key = (ranking[level], cond.wave_height or 0)
        if best is None or key > best:
            best, best_index = key, i

    cond = marine.conditions_at(hourly, best_index)
    level, reasons = marine.risk(cond, spot.exposed_from)
    return cond, level, reasons


def next_saturday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=(SATURDAY - today.weekday()) % 7 or 7)


def _fmt_tides(extremes: list[Extreme]) -> str:
    if not extremes:
        return "물때: 조위 데이터 없음"
    parts = [
        f"{'만조' if e.kind == 'high' else '간조'} {e.time:%H:%M}({e.height_m:+.1f}m)"
        for e in sorted(extremes, key=lambda e: e.time)
    ]
    return " ".join(parts)


def format_full(spot: Spot, day: dt.date, cond: Conditions, level: str,
                reasons: list[str], extremes: list[Extreme],
                saturday: tuple[dt.date, str, Conditions] | None) -> str:
    """화면/메일용 상세 브리핑."""
    lines = [
        f"■ {spot.name} — {day:%-m월 %-d일}({WEEKDAY_KO[day.weekday()]}) 갯바위 브리핑",
        "",
        f"  위험도   {level}" + (f"  ({', '.join(reasons)})" if reasons else ""),
    ]

    if cond.wave_height is not None:
        lines.append(
            f"  파고     유의 {cond.wave_height:.1f}m / 예상 최대 세트 {cond.max_set_m:.1f}m"
        )
    if cond.swell_height is not None:
        period = f" · {cond.swell_period:.0f}초" if cond.swell_period else ""
        lines.append(
            f"  너울     {cond.swell_height:.1f}m{period} · {compass(cond.swell_direction)}"
        )
    if cond.wind_speed is not None:
        gust = f" (돌풍 {cond.wind_gust:.0f})" if cond.wind_gust else ""
        lines.append(
            f"  바람     {compass(cond.wind_direction)} {cond.wind_speed:.0f}km/h{gust}"
        )

    lines += [f"  물때     {_fmt_tides(extremes)}", f"  기준시각 {cond.time:%H:%M} (최악 조건 시점)"]

    if spot.note:
        lines.append(f"  참고     {spot.note}")

    if saturday:
        sat_day, sat_level, sat_cond = saturday
        wave = f"{sat_cond.wave_height:.1f}m" if sat_cond.wave_height is not None else "?"
        lines += ["", f"  토요일({sat_day:%-m/%-d}) 전망: {sat_level} · 파고 {wave}"]

    lines += [
        "",
        "  ※ 예보 기반 참고치입니다. 현장 도착 후 최소 15분간 세트 주기를 직접",
        "     확인하고, 구명조끼 착용 여부는 예보와 무관하게 판단하세요.",
    ]
    return "\n".join(lines)


def format_compact(spot: Spot, day: dt.date, cond: Conditions, level: str,
                   reasons: list[str], extremes: list[Extreme],
                   saturday: tuple[dt.date, str, Conditions] | None) -> str:
    """카카오톡용 요약. 텍스트 템플릿 200자 제한에 맞춘다."""
    head = f"[{day:%-m/%-d}({WEEKDAY_KO[day.weekday()]})] {spot.name.split(' (')[0]}"

    wave = "파고 -"
    if cond.wave_height is not None:
        wave = f"파고 {cond.wave_height:.1f}m(세트 {cond.max_set_m:.1f}m)"

    swell = ""
    if cond.swell_height is not None:
        period = f"/{cond.swell_period:.0f}s" if cond.swell_period else ""
        swell = f" 너울 {cond.swell_height:.1f}m{period} {compass(cond.swell_direction)}"

    tides = " ".join(
        f"{'만' if e.kind == 'high' else '간'}{e.time:%H:%M}"
        for e in sorted(extremes, key=lambda e: e.time)
    )

    parts = [head, wave + swell]
    if tides:
        parts.append(f"물때 {tides}")
    if cond.wind_speed is not None:
        parts.append(f"바람 {compass(cond.wind_direction)} {cond.wind_speed:.0f}km/h")

    verdict = level + (f" · {reasons[0]}" if reasons else "")
    parts.append(verdict)

    if saturday:
        sat_day, sat_level, sat_cond = saturday
        wave_txt = f"{sat_cond.wave_height:.1f}m" if sat_cond.wave_height is not None else "?"
        parts.append(f"토({sat_day:%-m/%-d}) {sat_level} {wave_txt}")

    return "\n".join(parts)


def build(spot: Spot, day: dt.date, hourly: dict, with_saturday: bool = True):
    cond, level, reasons = worst_of_day(hourly, day, spot)
    extremes = marine.tide_extremes(hourly, day)

    saturday = None
    if with_saturday and day.weekday() != SATURDAY:
        sat_day = next_saturday(day)
        try:
            sat_cond, sat_level, _ = worst_of_day(hourly, sat_day, spot)
            saturday = (sat_day, sat_level, sat_cond)
        except MarineError:
            pass  # 예보 범위를 벗어나면 토요일 줄만 생략한다.

    return cond, level, reasons, extremes, saturday


def main() -> int:
    parser = argparse.ArgumentParser(description="갯바위 낚시 아침 브리핑")
    parser.add_argument("--spot", default=DEFAULT_SPOT,
                        help=f"포인트 키 (기본: {DEFAULT_SPOT}). 목록: {', '.join(SPOTS)}")
    parser.add_argument("--date", help="YYYY-MM-DD (기본: 오늘)")
    parser.add_argument("--send", action="store_true", help="카카오톡으로 전송")
    parser.add_argument("--compact", action="store_true", help="요약본을 화면에 출력")
    args = parser.parse_args()

    spot = get_spot(args.spot)
    tz = ZoneInfo(TIMEZONE)
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(tz).date()

    try:
        hourly = marine.fetch(spot.lat, spot.lon, TIMEZONE)
        result = build(spot, day, hourly)
    except MarineError as exc:
        print(f"[에러] {exc}", file=sys.stderr)
        return 1

    compact = format_compact(spot, day, *result)
    full = format_full(spot, day, *result)

    print(compact if args.compact else full)

    if args.send:
        try:
            from kakao_notify import KakaoError, send
            send(compact)
        except ImportError:
            print("[에러] kakao_notify를 찾을 수 없습니다 (tools/kakao-notify 확인).",
                  file=sys.stderr)
            return 1
        except KakaoError as exc:
            print(f"[에러] 카카오톡 전송 실패: {exc}", file=sys.stderr)
            return 1
        print("\n카카오톡으로 보냈습니다.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
