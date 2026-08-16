#!/usr/bin/env python3
"""최초 1회 실행 — 카카오 OAuth 인증을 받아 리프레시 토큰을 저장한다.

    python3 kakao_auth.py              브라우저 자동 (PC)
    python3 kakao_auth.py --manual     주소 직접 붙여넣기 (폰·원격 셸)
    python3 kakao_auth.py --show-env   등록할 환경변수 다시 보기

기본 모드는 localhost 콜백 서버를 띄우고 브라우저를 연다. 그게 불가능한
환경(폰, SSH, 컨테이너)에서는 --manual을 쓴다. 인가 코드를 손으로 옮기는
것만 다르고 결과는 같다.

이후로는 kakao_notify.py가 저장된 리프레시 토큰으로 알아서 갱신하므로 다시
실행할 일이 거의 없다(유효기간 2개월, 사용할 때마다 자동 연장).
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


def _authorize_url(rest_api_key: str, redirect_uri: str, state: str) -> str:
    return f"{AUTH_HOST}/oauth/authorize?" + urllib.parse.urlencode(
        {
            "client_id": rest_api_key,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
        }
    )


def _exchange(rest_api_key: str, redirect_uri: str, code: str) -> int:
    response = requests.post(
        f"{AUTH_HOST}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": rest_api_key,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=10,
    )
    if response.status_code != 200:
        print(f"[에러] 토큰 발급 실패 ({response.status_code}): {response.text}", file=sys.stderr)
        return 1
    save_tokens(response.json())
    return 0


def extract_code(pasted: str) -> str | None:
    """붙여넣은 값에서 인가 코드를 뽑는다.

    주소 전체를 붙여넣어도 되고 코드만 붙여넣어도 되게 한다. 폰에서 주소창을
    복사하면 보통 URL 전체가 딸려오기 때문이다.
    """
    pasted = pasted.strip()
    if not pasted:
        return None
    if "code=" in pasted:
        query = urllib.parse.urlparse(pasted).query or pasted.split("?", 1)[-1]
        values = urllib.parse.parse_qs(query).get("code")
        return values[0] if values else None
    # code= 없는 주소를 코드로 착각해 카카오에 보내면 엉뚱한 에러만 돌아온다.
    if pasted.startswith(("http://", "https://")):
        return None
    return pasted if " " not in pasted else None


def manual_flow() -> int:
    """콜백 서버 없이 인증한다 — 폰이나 원격 셸처럼 브라우저를 못 여는 환경용."""
    rest_api_key = get_rest_api_key()
    redirect_uri = get_redirect_uri()
    state = secrets.token_urlsafe(16)

    print("\n1) 아래 주소를 브라우저에서 여세요. 폰이면 길게 눌러 복사하세요.\n")
    print(f"{_authorize_url(rest_api_key, redirect_uri, state)}\n")
    print("2) 카카오 로그인 후 동의하면 접속 실패 화면이 뜹니다. 정상입니다.")
    print(f"   ({redirect_uri} 에는 아무것도 없으니 브라우저가 못 여는 게 맞습니다)")
    print("3) 그 화면의 주소창을 통째로 복사해 아래에 붙여넣으세요.")
    print("   code= 뒤의 값만 붙여넣으셔도 됩니다.\n")

    try:
        pasted = input("주소 또는 코드: ")
    except (EOFError, KeyboardInterrupt):
        print("\n중단했습니다.", file=sys.stderr)
        return 1

    if "error=" in pasted:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        print(f"[에러] 인증이 거부됐습니다: {params.get('error', ['?'])[0]}", file=sys.stderr)
        return 1

    code = extract_code(pasted)
    if not code:
        print("[에러] 코드를 찾지 못했습니다. 주소를 통째로 붙여넣어 보세요.", file=sys.stderr)
        return 1

    # state는 있으면 확인하고, 코드만 붙여넣은 경우엔 건너뛴다.
    if "state=" in pasted:
        got = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("state", [""])[0]
        if got != state:
            print("[에러] state 값이 일치하지 않습니다. 인증을 중단합니다.", file=sys.stderr)
            return 1

    if _exchange(rest_api_key, redirect_uri, code) != 0:
        return 1

    print("\n인증 완료.")
    print_env_block()
    return 0


def main() -> int:
    rest_api_key = get_rest_api_key()
    redirect_uri = get_redirect_uri()

    state = secrets.token_urlsafe(16)
    authorize_url = _authorize_url(rest_api_key, redirect_uri, state)

    try:
        server = _listen(redirect_uri)
    except OSError as exc:
        print(f"[에러] {redirect_uri} 포트를 열 수 없습니다: {exc}", file=sys.stderr)
        print("       포트를 쓰는 프로그램이 있는지 확인하거나 KAKAO_REDIRECT_URI를 바꾸세요.", file=sys.stderr)
        print("       콜백 서버 없이 하려면: python3 kakao_auth.py --manual", file=sys.stderr)
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

    if _exchange(rest_api_key, redirect_uri, _result["code"]) != 0:
        return 1

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
    if "--manual" in sys.argv:
        raise SystemExit(manual_flow())
    raise SystemExit(main())
