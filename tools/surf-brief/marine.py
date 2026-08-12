"""Open-Meteo에서 파고·너울·조위·바람을 받아오고, 갯바위 기준으로 해석한다.

Open-Meteo는 키가 필요 없고 비상업적 사용은 무료다. 조위는 marine API의
sea_level_height_msl(평균해수면 기준 조위) 시계열에서 극값을 찾아 만조/간조
시각을 역산한다. 시간당 값이라 그대로 쓰면 오차가 ±30분이므로, 극값 주변
세 점에 포물선을 맞춰 꼭짓점을 구해 분 단위로 보정한다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import requests

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

MARINE_VARS = [
    "wave_height",
    "wave_period",
    "wave_direction",
    "swell_wave_height",
    "swell_wave_period",
    "swell_wave_direction",
    "wind_wave_height",
    "sea_level_height_msl",
]
WIND_VARS = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]

# 레일리 분포에서 3시간(약 1000파) 중 최대파고 기대값 ≈ 1.86 × 유의파고.
# 갯바위에서 사람을 쓸어가는 건 평균이 아니라 이 세트파다.
MAX_SET_FACTOR = 1.86

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg: float | None) -> str:
    if deg is None:
        return "-"
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


@dataclass
class Extreme:
    """만조 또는 간조 한 건."""
    time: dt.datetime
    height_m: float
    kind: str  # "high" | "low"


@dataclass
class Conditions:
    """특정 시각의 해상 상태."""
    time: dt.datetime
    wave_height: float | None
    wave_period: float | None
    swell_height: float | None
    swell_period: float | None
    swell_direction: float | None
    wind_speed: float | None
    wind_direction: float | None
    wind_gust: float | None

    @property
    def max_set_m(self) -> float | None:
        """예상 최대 세트파 높이."""
        if self.wave_height is None:
            return None
        return round(self.wave_height * MAX_SET_FACTOR, 1)


class MarineError(RuntimeError):
    pass


def _get(url: str, params: dict) -> dict:
    try:
        response = requests.get(url, params=params, timeout=20)
    except requests.RequestException as exc:
        raise MarineError(
            f"{url} 요청 실패: {exc}\n"
            "네트워크 정책에서 이 도메인이 허용됐는지 확인하세요 (README 참고)."
        ) from exc
    if response.status_code != 200:
        raise MarineError(f"{url} 응답 오류 ({response.status_code}): {response.text[:300]}")
    return response.json()


def fetch(lat: float, lon: float, timezone: str, days: int = 7) -> dict:
    """marine + forecast 두 엔드포인트를 합쳐 시간별 시계열을 돌려준다.

    일출/일몰은 daily 응답에서 받아 _sunrise / _sunset 키로 함께 실어 보낸다.
    새벽에 들어가면 6시가 아직 어두운지가 실질적인 정보라 브리핑에 넣는다.
    """
    common = {"latitude": lat, "longitude": lon, "timezone": timezone, "forecast_days": days}

    marine = _get(MARINE_URL, {**common, "hourly": ",".join(MARINE_VARS)})
    wind = _get(FORECAST_URL, {
        **common,
        "hourly": ",".join(WIND_VARS),
        "daily": "sunrise,sunset",
    })

    hourly = dict(marine.get("hourly", {}))
    for key, values in wind.get("hourly", {}).items():
        if key != "time":
            hourly[key] = values

    if not hourly.get("time"):
        raise MarineError("응답에 시간축이 없습니다. Open-Meteo 응답 형식이 바뀌었을 수 있습니다.")

    daily = wind.get("daily") or {}
    hourly["_sunrise"] = daily.get("sunrise") or []
    hourly["_sunset"] = daily.get("sunset") or []

    return hourly


def sun_times(hourly: dict, day: dt.date) -> tuple[dt.datetime | None, dt.datetime | None]:
    """해당 날짜의 일출/일몰. 못 받았으면 (None, None)."""
    def pick(values: list[str]) -> dt.datetime | None:
        for raw in values:
            stamp = dt.datetime.fromisoformat(raw)
            if stamp.date() == day:
                return stamp
        return None

    return pick(hourly.get("_sunrise") or []), pick(hourly.get("_sunset") or [])


def _series(hourly: dict, key: str) -> list[float | None]:
    """없는 변수는 None으로 채워 길이를 맞춘다(API가 변수를 빼도 죽지 않게)."""
    values = hourly.get(key)
    if values is None:
        return [None] * len(hourly["time"])
    return values


def parse_times(hourly: dict) -> list[dt.datetime]:
    return [dt.datetime.fromisoformat(t) for t in hourly["time"]]


def conditions_at(hourly: dict, index: int) -> Conditions:
    def val(key: str):
        return _series(hourly, key)[index]

    return Conditions(
        time=parse_times(hourly)[index],
        wave_height=val("wave_height"),
        wave_period=val("wave_period"),
        swell_height=val("swell_wave_height"),
        swell_period=val("swell_wave_period"),
        swell_direction=val("swell_wave_direction"),
        wind_speed=val("wind_speed_10m"),
        wind_direction=val("wind_direction_10m"),
        wind_gust=val("wind_gusts_10m"),
    )


def all_extremes(hourly: dict) -> list[Extreme]:
    """조위 시계열 전체에서 만조/간조를 뽑는다.

    sea_level_height_msl이 응답에 없으면 빈 리스트를 돌려준다. 조위를 못 구했다고
    브리핑 전체를 실패시키지는 않되, 호출부가 그 사실을 표시하도록 한다.
    """
    levels = hourly.get("sea_level_height_msl")
    if not levels:
        return []

    times = parse_times(hourly)
    found: list[Extreme] = []

    for i in range(1, len(levels) - 1):
        prev, cur, nxt = levels[i - 1], levels[i], levels[i + 1]
        if prev is None or cur is None or nxt is None:
            continue

        is_high = cur > prev and cur >= nxt
        is_low = cur < prev and cur <= nxt
        if not (is_high or is_low):
            continue

        # 포물선 꼭짓점으로 시각을 분 단위까지 보정한다.
        denom = prev - 2 * cur + nxt
        offset = 0.0 if denom == 0 else 0.5 * (prev - nxt) / denom
        offset = max(-0.5, min(0.5, offset))

        peak_time = times[i] + dt.timedelta(hours=offset)
        peak_level = cur - 0.25 * (prev - nxt) * offset

        found.append(Extreme(peak_time, round(peak_level, 2), "high" if is_high else "low"))

    return sorted(found, key=lambda e: e.time)


def tide_extremes(hourly: dict, day: dt.date) -> list[Extreme]:
    """하루치 만조/간조."""
    return [e for e in all_extremes(hourly) if e.time.date() == day]


@dataclass
class TideState:
    """특정 시각의 물때 상황."""
    rising: bool
    next_extreme: Extreme

    @property
    def label(self) -> str:
        return "들물" if self.rising else "썰물"


def tide_state(hourly: dict, when: dt.datetime) -> TideState | None:
    """그 시각이 들물인지 썰물인지, 다음 정조가 언제인지.

    갯바위에서는 파고만큼 중요하다. 들물에 들어가면 나올 때 자리가 잠겨 퇴로가
    끊길 수 있고, 만조 전후로 갯바위를 넘는 물이 올라온다.
    """
    upcoming = [e for e in all_extremes(hourly) if e.time > when]
    if not upcoming:
        return None
    nxt = upcoming[0]
    return TideState(rising=(nxt.kind == "high"), next_extreme=nxt)


def risk(cond: Conditions, spot_exposed: tuple[int, int] | None) -> tuple[str, list[str]]:
    """갯바위 기준 위험도와 사유를 매긴다.

    공식 등급이 아니라 경험칙이다. 유의파고 자체보다 '긴 주기 너울'이 갯바위에서
    사고를 만들기 때문에 주기에 가중을 크게 뒀다. 최종 판단은 현장에서 직접.
    """
    height = cond.wave_height
    if height is None:
        return "판단불가", ["파고 데이터를 받지 못했습니다"]

    reasons: list[str] = []
    score = 0

    if height >= 2.5:
        score += 3
        reasons.append(f"유의파고 {height:.1f}m")
    elif height >= 1.5:
        score += 2
        reasons.append(f"유의파고 {height:.1f}m")
    elif height >= 1.0:
        score += 1

    period = cond.swell_period or cond.wave_period
    if period and period >= 12:
        score += 2
        reasons.append(f"장주기 너울 {period:.0f}초")
    elif period and period >= 10:
        score += 1
        reasons.append(f"너울 주기 {period:.0f}초")

    # 노출 방향 가점은 파고가 어느 정도 있을 때만 의미가 있다. 0.5m 잔물결은
    # 정면으로 들어와도 갯바위에서 문제가 되지 않는다.
    if spot_exposed and cond.swell_direction is not None and height >= 1.0:
        low, high = spot_exposed
        if low <= cond.swell_direction % 360 <= high:
            score += 1
            reasons.append(f"너울 방향 {compass(cond.swell_direction)}, 이 포인트 정면")

    if cond.wind_gust and cond.wind_gust >= 40:
        score += 1
        reasons.append(f"돌풍 {cond.wind_gust:.0f}km/h")

    if score >= 5:
        level = "매우위험"
    elif score >= 3:
        level = "위험"
    elif score >= 1:
        level = "주의"
    else:
        level = "양호"

    return level, reasons
