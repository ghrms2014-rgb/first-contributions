"""시드니~울릉공 구간 갯바위 포인트 좌표.

좌표는 각 곶(headland)의 갯바위 자리 기준이다. 파고 격자는 수 km 단위라
정확히 1m 단위로 맞출 필요는 없지만, 곶의 남쪽/북쪽은 너울 노출이 크게
다르므로 실제 들어가는 자리에 가깝게 잡는 편이 낫다.

새 포인트를 추가하려면 SPOTS에 한 줄 넣으면 된다. 위경도는 구글 지도에서
해당 갯바위를 우클릭하면 나온다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Spot:
    key: str
    name: str  # 한글 표기
    lat: float
    lon: float
    # 이 포인트가 특히 취약한 너울 방향(도). 해당 방향 너울이 들어오면 경고를 올린다.
    exposed_from: tuple[int, int] | None = None
    note: str = ""


SPOTS: dict[str, Spot] = {
    "kurnell": Spot(
        "kurnell", "커넬 (케이프 솔랜더)", -34.0136, 151.2233,
        exposed_from=(90, 200),
        note="동~남 너울에 그대로 열려 있음",
    ),
    "cronulla": Spot(
        "cronulla", "크로눌라 (베이스앤플린더스 포인트)", -34.0725, 151.1550,
        exposed_from=(90, 180),
    ),
    "wattamolla": Spot(
        "wattamolla", "와타몰라 (로열 국립공원)", -34.1367, 151.1147,
        exposed_from=(70, 190),
        note="접근로가 길어 철수 시간이 오래 걸림",
    ),
    "garie": Spot(
        "garie", "가리 비치", -34.1697, 151.0603,
        exposed_from=(70, 190),
    ),
    "stanwell": Spot(
        "stanwell", "스탠웰 파크", -34.2278, 150.9847,
        exposed_from=(60, 170),
    ),
    "coalcliff": Spot(
        "coalcliff", "콜클리프", -34.2400, 150.9750,
        exposed_from=(60, 170),
    ),
    "bellambi": Spot(
        "bellambi", "벨람비 포인트", -34.3697, 150.9200,
        exposed_from=(45, 160),
    ),
    "wollongong": Spot(
        "wollongong", "울릉공 (플래그스태프 포인트)", -34.4239, 150.9019,
        exposed_from=(45, 160),
    ),
    "hill60": Spot(
        "hill60", "포트켐블라 (힐 60)", -34.4728, 150.9089,
        exposed_from=(45, 170),
    ),
    "windang": Spot(
        "windang", "윈댕 아일랜드", -34.5333, 150.8722,
        exposed_from=(60, 180),
    ),
    "basspoint": Spot(
        "basspoint", "베이스 포인트 (셸하버)", -34.5936, 150.8961,
        exposed_from=(45, 180),
        note="구조 출동이 잦은 곳. 너울 예보를 특히 보수적으로 볼 것",
    ),
}

DEFAULT_SPOT = "wollongong"

# 브리핑 기준 시간대. 호주 NSW는 서머타임이 있어 UTC 고정 오프셋을 쓰면 안 된다.
TIMEZONE = "Australia/Sydney"


def get_spot(key: str) -> Spot:
    try:
        return SPOTS[key]
    except KeyError:
        raise SystemExit(
            f"'{key}'는 등록되지 않은 포인트입니다.\n"
            f"사용 가능: {', '.join(SPOTS)}\n"
            "새 포인트는 spots.py의 SPOTS에 추가하세요."
        ) from None
