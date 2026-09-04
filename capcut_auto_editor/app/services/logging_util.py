"""날짜별 로그 파일 + UI 패널용 링 버퍼."""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import date, datetime
from typing import Any, Deque, Dict, List, Optional

from ..config import PATHS

_LOGGER_NAME = "capcut"
_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%H:%M:%S"


class UIPanelHandler(logging.Handler):
    """최근 로그를 메모리에 들고 있다가 UI 패널에 그대로 넘긴다."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self._buf: Deque[Dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._seq += 1
            self._buf.append({
                "seq": self._seq,
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": record.getMessage(),
            })

    def recent(self, after_seq: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            rows = [r for r in self._buf if r["seq"] > after_seq]
        return rows[-limit:]


class _DailyFileHandler(logging.Handler):
    """자정을 넘기면 그날 날짜의 파일로 알아서 갈아탄다."""

    def __init__(self) -> None:
        super().__init__()
        self._day: Optional[date] = None
        self._stream = None
        self._lock_ = threading.Lock()

    def _stream_for_today(self):
        today = date.today()
        if self._day != today or self._stream is None:
            if self._stream is not None:
                self._stream.close()
            PATHS.logs.mkdir(parents=True, exist_ok=True)
            self._stream = open(PATHS.logs / f"{today.isoformat()}.log", "a", encoding="utf-8")
            self._day = today
        return self._stream

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock_:
                stream = self._stream_for_today()
                stream.write(self.format(record) + "\n")
                stream.flush()
        except Exception:  # 로깅 실패가 작업을 멈추게 하면 안 된다
            self.handleError(record)


UI_PANEL = UIPanelHandler()
_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler = _DailyFileHandler()
    file_handler.setFormatter(logging.Formatter(_FORMAT))

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    UI_PANEL.setFormatter(fmt)

    for h in (file_handler, console, UI_PANEL):
        logger.addHandler(h)

    _configured = True
    return logger


def get_logger(suffix: str = "") -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"{_LOGGER_NAME}.{suffix}" if suffix else _LOGGER_NAME)
