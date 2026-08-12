#!/usr/bin/env python3
"""최초 1회 실행 — 카카오 OAuth 인증을 받아 리프레시 토큰을 저장한다.

    python3 kakao_auth.py

브라우저가 열리면 카카오 계정으로 로그인하고 동의하면 끝. 이후로는
kakao_notify.py가 저장된 리프레시 토큰으로 알아서 갱신하므로 다시 실행할
일이 거의 없다(리프레시 토큰 유효기간 2개월, 사용할 때마다 자동 연장).
"""

from __future__ import annotations

import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from kakao_env import (
    AUTH_HOST,
    get_redirect_uri,
    get_rest_api_key,
    read_tokens,
    save_tokens,
)

SCOPE = "talk_message"

_result: dict[str, str] = {}
_done = threading.Event()

_PAGE = """<!doctype html><meta charset="utf-8">
<title>{title}</title>
<body style="font-family:system-ui,sans-serif;text-align:center;padding:4rem">
<h2>{title}</h2><p>{body}</p><p>이 창은 닫으셔도 됩니다.</p>
"""


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server가 요구하는 이름)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params or "error" in params:
            _result.update({k: v[0] for k, v in params.items()})
            ok = "code" in params
            page = _PAGE.format(
                title="인증 완료" if ok else "인증 실패",
                body="터미널로 돌아가세요." if ok else _result.get("error_description", ""),
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            _done.set()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        """기본 요청 로그를 끈다."""


def _listen(redirect_uri: str) -> HTTPServer:
    parsed = urllib.parse.urlparse(redirect_uri)
    server = HTTPServer((parsed.hostname or "localhost", parsed.port or 80), _CallbackHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    rest_api_key = get_rest_api_key()
    redirect_uri = get_redirect_uri()

    state = secrets.token_urlsafe(16)
    authorize_url = f"{AUTH_HOST}/oauth/authorize?" + urllib.parse.urlencode(
        {
            "client_id": rest_api_key,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
        }
    )

    try:
        server = _listen(redirect_uri)
    except OSError as exc:
        print(f"[에러] {redirect_uri} 포트를 열 수 없습니다: {exc}", file=sys.stderr)
        print("       다른 프로그램이 쓰고 있는지 확인하거나 KAKAO_REDIRECT_URI를 바꿔주세요.", file=sys.stderr)
        return 1

    print("아래 주소를 브라우저에서 열어 로그인/동의해주세요:\n")
    print(f"  {authorize_url}\n")
    webbrowser.open(authorize_url)
    print("대기 중... (5분 안에 완료해주세요)")

    if not _done.wait(timeout=300):
        print("[에러] 시간이 초과됐습니다. 다시 실행해주세요.", file=sys.stderr)
        return 1
    server.shutdown()

    if "error" in _result:
        print(
            f"[에러] 인증 거부됨: {_result['error']} — {_result.get('error_description', '')}",
            file=sys.stderr,
        )
        return 1

    if _result.get("state") != state:
        print("[에러] state 값이 일치하지 않습니다. 인증을 중단합니다.", file=sys.stderr)
        return 1

    response = requests.post(
        f"{AUTH_HOST}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": rest_api_key,
            "redirect_uri": redirect_uri,
            "code": _result["code"],
        },
        timeout=10,
    )
    if response.status_code != 200:
        print(f"[에러] 토큰 발급 실패 ({response.status_code}): {response.text}", file=sys.stderr)
        return 1

    save_tokens(response.json())
    print("\n인증 완료. 바로 써보시려면:\n")
    print('  python3 kakao_notify.py "첫 메시지"')
    print_env_block()
    return 0


def print_env_block() -> int:
    """클라우드/서버에 등록할 환경변수를 그대로 출력한다.

    토큰 파일에서 값을 눈으로 찾아 복사하는 수고를 없애려는 것뿐이다.
    """
    tokens = read_tokens()
    if not tokens or not tokens.get("refresh_token"):
        print(
            "저장된 토큰이 없습니다. 먼저 python3 kakao_auth.py 를 실행하세요.",
            file=sys.stderr,
        )
        return 1

    print("\n" + "=" * 68)
    print("아래 두 줄을 환경변수로 등록하세요 (그대로 복사).")
    print("=" * 68)
    print(f"KAKAO_REST_API_KEY={get_rest_api_key()}")
    print(f"KAKAO_REFRESH_TOKEN={tokens['refresh_token']}")
    print("=" * 68)

    expires_at = tokens.get("refresh_token_expires_at")
    if expires_at:
        remaining = (expires_at - time.time()) / 86400
        print(f"리프레시 토큰 유효기간: 약 {remaining:.0f}일 (쓸 때마다 자동 연장)")
    print("이 값은 비밀번호와 같습니다. 채팅이나 저장소에 붙여넣지 마세요.")
    return 0


if __name__ == "__main__":
    if "--show-env" in sys.argv:
        raise SystemExit(print_env_block())
    raise SystemExit(main())
