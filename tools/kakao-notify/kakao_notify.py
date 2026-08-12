#!/usr/bin/env python3
"""카카오톡 '나에게 보내기' — 내 카카오톡으로 메시지를 보낸다.

    python3 kakao_notify.py "빌드 끝났습니다"
    python3 kakao_notify.py "PR 리뷰 도착" --link https://github.com/...
    echo "긴 로그 내용" | python3 kakao_notify.py

다른 파이썬 코드에서 쓸 때:

    from kakao_notify import send
    send("배포 완료")
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from kakao_env import (
    API_HOST,
    AUTH_HOST,
    TEXT_LIMIT,
    TOKEN_PATH,
    get_rest_api_key,
    read_tokens,
    save_tokens,
)

# 만료 직전 요청이 실패하지 않도록 여유를 둔다.
EXPIRY_MARGIN_SEC = 60


class KakaoError(RuntimeError):
    pass


def _refresh(refresh_token: str) -> str:
    response = requests.post(
        f"{AUTH_HOST}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": get_rest_api_key(),
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoError(
            f"액세스 토큰 갱신 실패 ({response.status_code}): {response.text}\n"
            "리프레시 토큰이 만료됐을 수 있습니다. python3 kakao_auth.py 를 다시 실행해주세요."
        )
    payload = response.json()
    save_tokens(payload)
    return payload["access_token"]


def get_access_token() -> str:
    """유효한 액세스 토큰을 돌려준다. 만료됐으면 자동으로 갱신한다."""
    tokens = read_tokens()
    if not tokens or "refresh_token" not in tokens:
        raise KakaoError(
            f"저장된 토큰이 없습니다 ({TOKEN_PATH}).\n"
            "먼저 python3 kakao_auth.py 를 실행해 인증해주세요."
        )

    if tokens.get("access_token") and time.time() < tokens.get("expires_at", 0) - EXPIRY_MARGIN_SEC:
        return tokens["access_token"]

    return _refresh(tokens["refresh_token"])


def send(text: str, link: str | None = None, button_title: str = "열기") -> None:
    """나에게 보내기. 실패하면 KakaoError를 던진다."""
    text = text.strip()
    if not text:
        raise KakaoError("보낼 내용이 비어 있습니다.")

    if len(text) > TEXT_LIMIT:
        print(
            f"[경고] 본문이 {len(text)}자라 카카오 제한({TEXT_LIMIT}자)에 맞춰 잘렸습니다.",
            file=sys.stderr,
        )
        text = text[: TEXT_LIMIT - 1] + "…"

    template: dict = {"object_type": "text", "text": text, "link": {}}
    if link:
        template["link"] = {"web_url": link, "mobile_web_url": link}
        template["button_title"] = button_title

    response = requests.post(
        f"{API_HOST}/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {get_access_token()}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoError(f"전송 실패 ({response.status_code}): {response.text}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="내 카카오톡으로 메시지를 보냅니다.",
        epilog='예: python3 kakao_notify.py "테스트" --link https://example.com',
    )
    parser.add_argument("text", nargs="?", help="보낼 내용. 생략하면 표준입력에서 읽습니다.")
    parser.add_argument("--link", help="메시지에 붙일 링크 (버튼으로 표시됨)")
    parser.add_argument("--button-title", default="열기", help="링크 버튼 문구 (기본: 열기)")
    args = parser.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()

    try:
        send(text, link=args.link, button_title=args.button_title)
    except KakaoError as exc:
        print(f"[에러] {exc}", file=sys.stderr)
        return 1

    print("보냈습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
