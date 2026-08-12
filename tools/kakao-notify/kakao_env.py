"""공통 설정 로더 — .env 파일과 토큰 저장소를 다룬다.

의존성을 requests 하나로 유지하기 위해 python-dotenv 대신 최소 구현을 쓴다.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
TOKEN_PATH = BASE_DIR / ".kakao_token.json"

AUTH_HOST = "https://kauth.kakao.com"
API_HOST = "https://kapi.kakao.com"

DEFAULT_REDIRECT_URI = "http://localhost:5000/oauth"

# 카카오 텍스트 템플릿의 본문 길이 제한
TEXT_LIMIT = 200


def load_env() -> None:
    """.env 파일을 os.environ에 채운다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_rest_api_key() -> str:
    load_env()
    key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "KAKAO_REST_API_KEY가 없습니다.\n"
            f"  {ENV_PATH} 파일을 만들고 아래 한 줄을 넣어주세요:\n"
            "  KAKAO_REST_API_KEY=발급받은_REST_API_키\n"
            "  (.env.example 참고)"
        )
    return key


def get_redirect_uri() -> str:
    load_env()
    return os.environ.get("KAKAO_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI


def save_tokens(payload: dict) -> None:
    """토큰 응답을 만료 시각과 함께 저장한다. 파일 권한은 소유자 전용(0600).

    파일에 쓸 수 없는 환경(읽기 전용 컨테이너 등)에서는 조용히 건너뛴다.
    리프레시 토큰만 있으면 매번 다시 발급받을 수 있으므로 동작에는 지장이 없다.
    """
    now = int(time.time())
    stored = read_tokens() or {}

    stored["access_token"] = payload["access_token"]
    stored["expires_at"] = now + int(payload.get("expires_in", 21599))

    # 갱신 응답에는 refresh_token이 없을 수 있다(만료 1개월 전에만 재발급됨).
    if payload.get("refresh_token"):
        stored["refresh_token"] = payload["refresh_token"]
        stored["refresh_token_expires_at"] = now + int(
            payload.get("refresh_token_expires_in", 5183999)
        )

    try:
        TOKEN_PATH.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        TOKEN_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def read_tokens() -> dict | None:
    """저장된 토큰을 읽는다.

    환경변수 KAKAO_REFRESH_TOKEN이 있으면 그쪽을 우선한다. 로컬에서 한 번
    인증한 뒤 토큰만 서버/클라우드에 넘겨 쓰는 용도다(파일을 옮길 필요 없음).
    """
    load_env()

    env_refresh = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if env_refresh:
        # 액세스 토큰 캐시가 남아 있으면 재활용하고, 없으면 갱신하도록 둔다.
        cached = _read_token_file() or {}
        if cached.get("refresh_token") != env_refresh:
            cached = {}
        cached["refresh_token"] = env_refresh
        return cached

    return _read_token_file()


def _read_token_file() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
