"""FastAPI 앱."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import PATHS, load_settings
from .routers import calibration, editing, files, publishing, sessions, setup
from .services.jobs import JOBS
from .services.logging_util import UI_PANEL, get_logger, setup_logging
from .services.session import StepLocked

APP_TITLE = "캡컷 자동 편집기"
VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    PATHS.ensure()
    log = setup_logging()
    settings = load_settings()
    log.info("%s v%s 시작", APP_TITLE, VERSION)
    log.info("드래프트 폴더: %s", settings.draft_folder or "(설정 안 됨)")
    yield
    log.info("%s 종료", APP_TITLE)


app = FastAPI(title=APP_TITLE, version=VERSION, lifespan=lifespan)
log = get_logger("main")

for router in (setup.router, files.router, sessions.router,
               calibration.router, editing.router, publishing.router):
    app.include_router(router)


# ------------------------------------------------------------------ 예외 처리

@app.exception_handler(StepLocked)
async def step_locked_handler(_request: Request, exc: StepLocked) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc), "missing": exc.missing})


@app.exception_handler(FileNotFoundError)
async def file_missing_handler(_request: Request, exc: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def runtime_handler(_request: Request, exc: RuntimeError) -> JSONResponse:
    log.error("처리 중 오류: %s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ------------------------------------------------------------------- 작업 / 로그

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "app": APP_TITLE, "version": VERSION}


@app.get("/api/jobs")
def list_jobs() -> Dict[str, Any]:
    return {"jobs": JOBS.list()}


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str) -> Dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Dict[str, Any]:
    if not JOBS.cancel(job_id):
        raise HTTPException(status_code=409, detail="이미 끝났거나 취소할 수 없는 작업입니다")
    return {"ok": True, "cancelled": job_id}


@app.get("/api/events")
def events() -> StreamingResponse:
    """작업 진행 상황을 흘려보내는 SSE 스트림."""
    q = JOBS.subscribe()

    def generate():
        try:
            yield from JOBS.stream(q)
        finally:
            JOBS.unsubscribe(q)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.get("/api/logs")
def logs(after: int = 0, limit: int = 200) -> Dict[str, Any]:
    """UI 로그 패널이 주기적으로 가져가는 최근 로그."""
    return {"logs": UI_PANEL.recent(after_seq=after, limit=limit)}


# -------------------------------------------------------------------- 정적 파일

app.mount("/", StaticFiles(directory=str(PATHS.static), html=True), name="static")
