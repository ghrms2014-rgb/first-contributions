#!/usr/bin/env python3
"""갯바위 낚시용 아침 브리핑 — 파고·너울·물때를 요약해 카카오톡으로 보낸다.

    python3 surf_brief.py                    # 오늘 브리핑을 화면에 출력
    python3 surf_brief.py --spot point_perp  # 포인트 지정
    python3 surf_brief.py --send             # 카카오톡으로 전송
    python3 surf_brief.py --date 2026-08-15  # 특정 날짜

새벽 6시 입수를 기준으로, 실제로 갯바위에 서 있는 시간대(04~11시)의 최악
조건으로 위험도를 매긴다. 토요일에 낚시를 나가므로 평일 브리핑에는 다가오는
토요일 전망이 한 줄 붙는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import marine
from marine import Conditions, Extreme, MarineError, TideState, compass
from spots import (
    DEFAULT_SPOT,
    SESSION_START_HOUR,
    SESSION_WINDOW,
    SPOTS,
    TIMEZONE,
    Spot,
    get_spot,
)

# 같은 저장소의 카카오 도구를 재사용한다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kakao-notify"))

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]
SATURDAY = 5

RISK_ORDER = {"판단불가": -1, "양호": 0, "주의": 1, "위험": 2, "매우위험": 3}


@dataclass
class Brief:
    spot: Spot
    day: dt.date
    start: Conditions          # 입수 시각(06시)의 조건
    worst: Conditions          # 세션 구간 중 최악 시점
    level: str
    reasons: list[str]
    extremes: list[Extreme]
    tide: TideState | None     # 입수 시각의 들물/썰물
    sunrise: dt.datetime | None
    saturday: tuple[dt.date, str, Conditions] | None


def _index_at(times: list[dt.datetime], day: dt.date, hour: int) -> int | None:
    for i, t in enumerate(times):
        if t.date() == day and t.hour == hour:
            return i
    return None


def worst_in_session(hourly: dict, day: dt.date, spot: Spot) -> tuple[Conditions, str, list[str]]:
    """세션 구간(04~11시) 중 가장 위험한 시점의 조건."""
    times = marine.parse_times(hourly)
    low, high = SESSION_WINDOW
    indices = [i for i, t in enumerate(times) if t.date() == day and low <= t.hour <= high]
    if not indices:
        raise MarineError(f"{day} 예보가 응답 범위 밖입니다. --date 를 확인하세요.")

    best_index, best = indices[0], None
    for i in indices:
        cond = marine.conditions_at(hourly, i)
        level, _ = marine.risk(cond, spot.exposed_from)
        key = (RISK_ORDER[level], cond.wave_height or 0)
        if best is None or key > best:
            best, best_index = key, i

    cond = marine.conditions_at(hourly, best_index)
    level, reasons = marine.risk(cond, spot.exposed_from)
    return cond, level, reasons


def next_saturday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=(SATURDAY - today.weekday()) % 7 or 7)


def build(spot: Spot, day: dt.date, hourly: dict, with_saturday: bool = True) -> Brief:
    times = marine.parse_times(hourly)
    start_index = _index_at(times, day, SESSION_START_HOUR)
    if start_index is None:
        raise MarineError(f"{day} 예보가 응답 범위 밖입니다. --date 를 확인하세요.")

    start = marine.conditions_at(hourly, start_index)
    worst, level, reasons = worst_in_session(hourly, day, spot)
    sunrise, _ = marine.sun_times(hourly, day)

    saturday = None
    if with_saturday and day.weekday() != SATURDAY:
        sat_day = next_saturday(day)
        try:
            sat_cond, sat_level, _ = worst_in_session(hourly, sat_day, spot)
            saturday = (sat_day, sat_level, sat_cond)
        except MarineError:
            pass  # 예보 범위를 벗어나면 토요일 줄만 생략한다.

    return Brief(
        spot=spot,
        day=day,
        start=start,
        worst=worst,
        level=level,
        reasons=reasons,
        extremes=marine.tide_extremes(hourly, day),
        tide=marine.tide_state(hourly, times[start_index]),
        sunrise=sunrise,
        saturday=saturday,
    )


def _tide_line(b: Brief) -> str:
    if not b.extremes:
        return "조위 데이터 없음"
    parts = [
        f"{'만조' if e.kind == 'high' else '간조'} {e.time:%H:%M}({e.height_m:+.1f}m)"
        for e in b.extremes
    ]
    return " ".join(parts)


def format_full(b: Brief) -> str:
    """화면/메일용 상세 브리핑."""
    day_label = f"{b.day:%-m월 %-d일}({WEEKDAY_KO[b.day.weekday()]})"
    lines = [
        f"■ {b.spot.name} — {day_label} 새벽 브리핑",
        "",
        f"  위험도   {b.level}" + (f"  ({', '.join(b.reasons)})" if b.reasons else ""),
    ]

    if b.start.wave_height is not None:
        lines.append(
            f"  파고     {SESSION_START_HOUR:02d}시 유의 {b.start.wave_height:.1f}m"
            f" / 예상 최대 세트 {b.start.max_set_m:.1f}m"
        )
        # 세션 중 눈에 띄게 더 나빠지는 시점이 있을 때만 덧붙인다.
        # 파고가 내내 평평하면 같은 값을 두 번 적을 뿐이다.
        if (
            b.worst.time.hour != SESSION_START_HOUR
            and b.worst.wave_height is not None
            and b.worst.wave_height >= b.start.wave_height + 0.1
        ):
            lines.append(
                f"           {b.worst.time:%H시} 최악 {b.worst.wave_height:.1f}m"
                f" (세트 {b.worst.max_set_m:.1f}m)"
            )
    if b.start.swell_height is not None:
        period = f" · {b.start.swell_period:.0f}초" if b.start.swell_period else ""
        lines.append(
            f"  너울     {b.start.swell_height:.1f}m{period} · {compass(b.start.swell_direction)}"
        )
    if b.start.wind_speed is not None:
        gust = f" (돌풍 {b.start.wind_gust:.0f})" if b.start.wind_gust else ""
        lines.append(
            f"  바람     {compass(b.start.wind_direction)} {b.start.wind_speed:.0f}km/h{gust}"
        )

    if b.tide:
        nxt = b.tide.next_extreme
        kind = "만조" if nxt.kind == "high" else "간조"
        lines.append(
            f"  물때     {SESSION_START_HOUR:02d}시 {b.tide.label} → {kind} {nxt.time:%H:%M}"
        )
    lines.append(f"           {_tide_line(b)}")

    if b.sunrise:
        dark = ""
        if b.sunrise.hour > SESSION_START_HOUR or (
            b.sunrise.hour == SESSION_START_HOUR and b.sunrise.minute > 0
        ):
            delta = int(
                (b.sunrise - b.sunrise.replace(hour=SESSION_START_HOUR, minute=0)).total_seconds()
                // 60
            )
            dark = f" (입수 후 {delta}분간 어두움)"
        lines.append(f"  일출     {b.sunrise:%H:%M}{dark}")

    if b.spot.note:
        lines.append(f"  참고     {b.spot.note}")
    if b.spot.access_check:
        lines.append(f"  출입     {b.spot.access_check}")

    if b.saturday:
        sat_day, sat_level, sat_cond = b.saturday
        wave = f"{sat_cond.wave_height:.1f}m" if sat_cond.wave_height is not None else "?"
        lines += ["", f"  토요일({sat_day:%-m/%-d}) 전망: {sat_level} · 파고 {wave}"]

    lines += [
        "",
        "  ※ 예보 기반 참고치입니다. 현장 도착 후 최소 15분간 세트 주기를 직접",
        "     확인하고, 구명조끼 착용 여부는 예보와 무관하게 판단하세요.",
    ]
    return "\n".join(lines)


def format_compact(b: Brief) -> str:
    """카카오톡용 요약. 텍스트 템플릿 200자 제한에 맞춘다."""
    short_name = b.spot.name.split(" (")[0]
    parts = [f"[{b.day:%-m/%-d}({WEEKDAY_KO[b.day.weekday()]})] {short_name}"]

    wave = f"{SESSION_START_HOUR:02d}시 파고 -"
    if b.start.wave_height is not None:
        wave = (f"{SESSION_START_HOUR:02d}시 파고 {b.start.wave_height:.1f}m"
                f"(세트 {b.start.max_set_m:.1f}m)")
    if b.start.swell_height is not None:
        period = f"/{b.start.swell_period:.0f}s" if b.start.swell_period else ""
        wave += f" 너울 {b.start.swell_height:.1f}m{period} {compass(b.start.swell_direction)}"
    parts.append(wave)

    if b.tide:
        nxt = b.tide.next_extreme
        parts.append(f"물때 {b.tide.label}, {'만조' if nxt.kind == 'high' else '간조'} {nxt.time:%H:%M}")

    extras = []
    if b.start.wind_speed is not None:
        extras.append(f"바람 {compass(b.start.wind_direction)} {b.start.wind_speed:.0f}km/h")
    if b.sunrise:
        extras.append(f"일출 {b.sunrise:%H:%M}")
    if extras:
        parts.append(" · ".join(extras))

    parts.append(b.level + (f" · {b.reasons[0]}" if b.reasons else ""))

    if b.saturday:
        sat_day, sat_level, sat_cond = b.saturday
        wave_txt = f"{sat_cond.wave_height:.1f}m" if sat_cond.wave_height is not None else "?"
        parts.append(f"토({sat_day:%-m/%-d}) {sat_level} {wave_txt}")

    if b.spot.access_check:
        parts.append(f"※{b.spot.access_check}")

    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="갯바위 낚시 새벽 브리핑")
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
        brief = build(spot, day, hourly)
    except MarineError as exc:
        print(f"[에러] {exc}", file=sys.stderr)
        return 1

    print(format_compact(brief) if args.compact else format_full(brief))

    if args.send:
        from spots import BEECROFT_URL
        try:
            from kakao_notify import KakaoError, send
            link = BEECROFT_URL if brief.spot.access_check else None
            send(format_compact(brief), link=link, button_title="사격장 개방 확인")
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
