"""백그라운드 작업 + SSE 이벤트 스트림."""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

from .logging_util import get_logger

log = get_logger("jobs")

PENDING, RUNNING, DONE, FAILED, CANCELLED = "pending", "running", "done", "failed", "cancelled"


class JobCancelled(Exception):
    """작업이 취소 요청을 받았을 때 워커가 던지는 예외."""


@dataclass
class Job:
    id: str
    name: str
    status: str = PENDING
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "progress": round(self.progress, 4), "message": self.message,
            "result": self.result, "error": self.error,
            "created_at": self.created_at, "finished_at": self.finished_at,
        }


class JobHandle:
    """워커 함수에 넘겨주는 진행률/취소 채널."""

    def __init__(self, manager: "JobManager", job: Job) -> None:
        self._manager = manager
        self._job = job

    @property
    def cancelled(self) -> bool:
        return self._job._cancel.is_set()

    def check_cancel(self) -> None:
        if self.cancelled:
            raise JobCancelled(self._job.name)

    def progress(self, value: float, message: str = "") -> None:
        self.check_cancel()
        self._job.progress = max(0.0, min(1.0, value))
        if message:
            self._job.message = message
        self._manager._publish({"type": "progress", "job": self._job.to_dict()})

    def log(self, message: str, level: str = "info") -> None:
        getattr(log, level, log.info)(f"[{self._job.name}] {message}")
        self._manager._publish({
            "type": "log", "job_id": self._job.id, "level": level.upper(), "message": message,
        })


class JobManager:
    """작업은 스레드에서 돌리고, 상태 변화는 구독자에게 SSE로 흘려보낸다."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()

    # ----------------------------------------------------------- 구독 / 발행
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _publish(self, event: Dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # 느린 구독자 때문에 작업이 밀리지 않게 버린다

    def stream(self, q: queue.Queue) -> Generator[str, None, None]:
        """text/event-stream 본문 생성기."""
        import json
        yield "retry: 3000\n\n"
        while True:
            try:
                event = q.get(timeout=15.0)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    # -------------------------------------------------------------- 작업 제어
    def submit(self, name: str, fn: Callable[[JobHandle], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], name=name)
        with self._lock:
            self._jobs[job.id] = job
        handle = JobHandle(self, job)

        def runner() -> None:
            job.status = RUNNING
            self._publish({"type": "started", "job": job.to_dict()})
            try:
                job.result = fn(handle)
                job.status = DONE
                job.progress = 1.0
            except JobCancelled:
                job.status = CANCELLED
                job.message = "사용자가 취소했습니다"
            except Exception as exc:
                job.status = FAILED
                job.error = f"{type(exc).__name__}: {exc}"
                log.error("작업 실패 [%s] %s\n%s", name, exc, traceback.format_exc())
            finally:
                job.finished_at = time.time()
                self._publish({"type": "finished", "job": job.to_dict()})

        threading.Thread(target=runner, name=f"job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in (PENDING, RUNNING):
            return False
        job._cancel.set()
        return True

    def list(self) -> List[Dict[str, Any]]:
        return [j.to_dict() for j in sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)]


JOBS = JobManager()
