"""API 동작 확인. 실제 영상 파일 없이 도는 것만 본다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app
from app.services.session import SESSIONS


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session_id(client):
    """설정 단계까지 끝난 세션. 캡컷 폴더는 이 환경에 없으므로 직접 통과시킨다."""
    sid = client.post("/api/sessions", json={"name": "pytest"}).json()["session"]["id"]
    session = SESSIONS.get(sid)
    if not session.is_done("setup"):
        session.complete("setup")
        SESSIONS.save(session)
    yield sid
    SESSIONS.delete(sid)


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_status_lists_every_check(client):
    body = client.get("/api/setup/status").json()
    keys = {c["key"] for c in body["checks"]}
    assert keys == {"draft_folder", "ffmpeg", "whisper", "assets"}


def test_settings_round_trip(client):
    client.post("/api/setup/settings", json={"subtitle_max_chars": 22})
    assert client.get("/api/setup/settings").json()["subtitle_max_chars"] == 22


def test_settings_reject_bad_value(client):
    assert client.post("/api/setup/settings", json={"fps": 0}).status_code == 422


def test_settings_reject_missing_folder(client):
    res = client.post("/api/setup/settings", json={"draft_folder": "/없는/폴더"})
    assert res.status_code == 400


def test_dictionary_round_trip(client):
    client.post("/api/setup/dictionary", json={"entries": {" 캡켓 ": " 캡컷 "}})
    assert client.get("/api/setup/dictionary").json() == {"캡켓": "캡컷"}


def test_unknown_session_is_404(client):
    assert client.get("/api/sessions/없는세션").status_code == 404


def test_sources_reject_missing_file(client, session_id):
    res = client.post(f"/api/sessions/{session_id}/sources",
                      json={"paths": ["/없는/영상.mp4"]})
    assert res.status_code == 400


def test_sources_reject_empty_list(client, session_id):
    res = client.post(f"/api/sessions/{session_id}/sources", json={"paths": []})
    assert res.status_code == 400


def test_locked_step_returns_409(client, session_id):
    # 원본도 안 고른 채 자막 정렬을 요청하면 막혀야 한다
    res = client.post(f"/api/editing/{session_id}/align", json={"script": ""})
    assert res.status_code == 409
    assert "단계" in res.json()["detail"]


def test_candidates_before_analysis_is_409(client, session_id):
    assert client.get(f"/api/editing/{session_id}/candidates").status_code == 409


def test_setup_step_gates_everything(client):
    """설정이 안 끝난 세션은 다음 단계로 못 넘어간다."""
    sid = client.post("/api/sessions", json={"name": "gate"}).json()["session"]["id"]
    try:
        session = SESSIONS.get(sid)
        if session.is_done("setup"):
            pytest.skip("이 환경에는 캡컷 폴더가 있어 setup 이 자동 통과됨")
        res = client.post(f"/api/sessions/{sid}/sources", json={"paths": []})
        assert res.status_code == 409
    finally:
        SESSIONS.delete(sid)


def test_publish_options(client):
    body = client.get("/api/publishing/options").json()
    assert {p["key"] for p in body["platforms"]} >= {"youtube", "shorts", "instagram"}


def test_jobs_and_logs_endpoints(client):
    assert "jobs" in client.get("/api/jobs").json()
    assert "logs" in client.get("/api/logs").json()


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/없는작업").status_code == 404


def test_static_index_served(client):
    res = client.get("/")
    assert res.status_code == 200 and "캡컷 자동 편집기" in res.text
