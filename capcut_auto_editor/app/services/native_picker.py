"""윈도우 기본 선택 창 (별도 프로세스에서 띄운다).

tkinter 대화상자를 서버 프로세스 안에서 직접 열면 이벤트 루프가 얽혀 창이 굳는다.
그래서 짧은 자식 프로세스를 띄우고 선택 결과만 표준출력으로 받아 온다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, List, Optional

from .logging_util import get_logger

log = get_logger("picker")

TIMEOUT = 300.0  # 사용자가 창을 열어 둔 채 고민할 시간

# 자식 프로세스에서 실행될 코드. 결과 한 줄만 JSON 으로 뱉는다.
_CHILD = r'''
import json, sys
mode, title, initial = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as exc:
    print(json.dumps({"ok": False, "error": "tkinter 없음: %s" % exc})); raise SystemExit

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
try:
    if mode == "folder":
        picked = filedialog.askdirectory(title=title, initialdir=initial or None)
        result = [picked] if picked else []
    elif mode == "save":
        picked = filedialog.asksaveasfilename(title=title, initialdir=initial or None)
        result = [picked] if picked else []
    else:
        types = [("영상 파일", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                 ("오디오 파일", "*.mp3 *.wav *.m4a *.aac *.flac"),
                 ("모든 파일", "*.*")]
        if mode == "file":
            picked = filedialog.askopenfilename(title=title, initialdir=initial or None,
                                                filetypes=types)
            result = [picked] if picked else []
        else:
            result = list(filedialog.askopenfilenames(title=title, initialdir=initial or None,
                                                      filetypes=types))
    print(json.dumps({"ok": True, "paths": [p for p in result if p]}))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
finally:
    root.destroy()
'''


def available() -> bool:
    """이 환경에서 기본 선택 창을 띄울 수 있는지."""
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    return True


def _pick(mode: str, title: str, initial: str = "") -> Dict[str, Any]:
    if not available():
        return {"ok": False, "error": "이 환경에서는 기본 선택 창을 쓸 수 없습니다. 경로를 직접 입력해 주세요."}

    kwargs: Dict[str, Any] = {}
    if sys.platform.startswith("win"):
        # 콘솔 창이 깜빡이지 않게
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD, mode, title, initial],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT, **kwargs,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "선택 창이 너무 오래 열려 있어 취소했습니다."}

    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return {"ok": False, "error": (proc.stderr or "선택 창을 열지 못했습니다.").strip()[-500:]}
    try:
        return json.loads(line[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": "선택 결과를 읽지 못했습니다."}


def pick_folder(title: str = "폴더 선택", initial: str = "") -> Optional[str]:
    res = _pick("folder", title, initial)
    paths = res.get("paths") or []
    if not res.get("ok"):
        log.warning("폴더 선택 실패: %s", res.get("error"))
    return paths[0] if paths else None


def pick_file(title: str = "파일 선택", initial: str = "") -> Optional[str]:
    res = _pick("file", title, initial)
    paths = res.get("paths") or []
    return paths[0] if paths else None


def pick_files(title: str = "파일 선택 (여러 개 가능)", initial: str = "") -> List[str]:
    res = _pick("files", title, initial)
    return res.get("paths") or []
