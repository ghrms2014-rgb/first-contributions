"""서버를 띄우고 브라우저를 연다.

`python run.py` 또는 `캡컷 자동 편집기 실행.bat` 더블클릭으로 실행한다.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def find_free_port(host: str, start: int, tries: int = 20) -> int:
    """기본 포트가 이미 쓰이고 있으면 다음 빈 포트를 찾는다."""
    for offset in range(tries):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"{start}~{start + tries - 1} 사이에 빈 포트가 없습니다.")


def open_browser_later(url: str, delay: float = 1.2) -> None:
    def worker() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            print(f"브라우저를 열지 못했습니다. 직접 열어 주세요: {url}")

    threading.Thread(target=worker, daemon=True).start()


def check_dependencies() -> bool:
    missing = []
    for module, package in (("fastapi", "fastapi"), ("uvicorn", "uvicorn[standard]"),
                            ("pycapcut", "pycapcut")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print("필요한 패키지가 설치되어 있지 않습니다:")
        for m in missing:
            print(f"  - {m}")
        print("\n아래 명령으로 한 번에 설치할 수 있습니다:")
        print(f"  {sys.executable} -m pip install -r requirements.txt")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="캡컷 자동 편집기")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않는다")
    parser.add_argument("--reload", action="store_true", help="개발용 자동 재시작")
    args = parser.parse_args()

    if not check_dependencies():
        input("\n엔터를 누르면 종료합니다...")
        return 1

    import uvicorn

    port = args.port if args.reload else find_free_port(args.host, args.port)
    url = f"http://{args.host}:{port}"

    print("=" * 52)
    print("  캡컷 자동 편집기")
    print(f"  주소: {url}")
    print("  종료하려면 이 창에서 Ctrl+C 를 누르세요.")
    print("=" * 52)

    if not args.no_browser:
        open_browser_later(url)

    try:
        uvicorn.run("app.main:app", host=args.host, port=port,
                    reload=args.reload, log_level="info")
    except KeyboardInterrupt:
        print("\n종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
