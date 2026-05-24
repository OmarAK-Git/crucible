import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app
from backend import db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_home_dir(monkeypatch, tmp_path):
    # Patch Path.home() so all user-relative paths point to tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path

def test_get_incoming_handoffs_empty():
    response = client.get("/api/handoffs/incoming")
    assert response.status_code == 200
    assert response.json() == []

def test_get_incoming_handoffs_with_files(tmp_path):
    incoming_dir = tmp_path / ".crucible" / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    
    # Create two synthetic handoffs
    h1 = {
        "tumbler_session_id": "session-1",
        "created_at": "2026-05-23T10:00:00Z",
        "corpus_bundle": "<evidence path=\"a.py\">\nprint(1)\n</evidence>",
        "source": "tumbler",
        "tumbler_verdict": "PASS"
    }
    h2 = {
        "tumbler_session_id": "session-2",
        "created_at": "2026-05-23T11:00:00Z",
        "corpus_bundle": "<evidence path=\"b.py\">\nprint(2)\n</evidence>",
        "source": "tumbler",
        "tumbler_verdict": "PASS"
    }
    
    with open(incoming_dir / "session-1.json", "w", encoding="utf-8") as f:
        json.dump(h1, f)
    with open(incoming_dir / "session-2.json", "w", encoding="utf-8") as f:
        json.dump(h2, f)
        
    response = client.get("/api/handoffs/incoming")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    
    # Should be sorted by created_at descending (session-2 first)
    assert data[0]["tumbler_session_id"] == "session-2"
    assert data[0]["filename"] == "session-2.json"
    assert data[1]["tumbler_session_id"] == "session-1"
    assert data[1]["filename"] == "session-1.json"

def test_post_session_from_tumbler_happy_path(tmp_path):
    incoming_dir = tmp_path / ".crucible" / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    
    h = {
        "tumbler_session_id": "session-pass",
        "created_at": "2026-05-23T12:00:00Z",
        "corpus_bundle": "<evidence path=\"main.py\">\nprint(3)\n</evidence>",
        "source": "tumbler",
        "tumbler_verdict": "PASS"
    }
    
    filename = "session-pass.json"
    with open(incoming_dir / filename, "w", encoding="utf-8") as f:
        json.dump(h, f)
        
    payload = {
        "handoff_filename": filename,
        "prompt": "Add database caching",
        "questions_mode": "off"
    }
    
    response = client.post("/api/sessions/from-tumbler", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    new_session_id = data["session_id"]
    
    # Verify session created in DB
    session = db.get_session(new_session_id)
    assert session is not None
    assert session["prompt"] == "Add database caching"
    assert session["corpus"] == h["corpus_bundle"]
    assert session["status"] == "running"
    assert session["questions_mode"] == "off"
    
    # Verify file moved to consumed with the new_session_id
    consumed_path = tmp_path / ".crucible" / "consumed" / f"{new_session_id}.json"
    assert consumed_path.exists()
    assert not (incoming_dir / filename).exists()
    
    with open(consumed_path, "r", encoding="utf-8") as f:
        consumed_data = json.load(f)
    assert consumed_data["tumbler_session_id"] == "session-pass"

def test_post_session_from_tumbler_empty_prompt(tmp_path):
    incoming_dir = tmp_path / ".crucible" / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    
    h = {
        "tumbler_session_id": "session-pass",
        "created_at": "2026-05-23T12:00:00Z",
        "corpus_bundle": "<evidence path=\"main.py\">\nprint(3)\n</evidence>",
        "source": "tumbler",
        "tumbler_verdict": "PASS"
    }
    filename = "session-pass.json"
    with open(incoming_dir / filename, "w", encoding="utf-8") as f:
        json.dump(h, f)
        
    # Empty prompt -> 400
    payload = {
        "handoff_filename": filename,
        "prompt": "   ",
        "questions_mode": "off"
    }
    response = client.post("/api/sessions/from-tumbler", json=payload)
    assert response.status_code == 400
    assert "prompt cannot be empty" in response.json()["detail"].lower()

def test_post_session_from_tumbler_malformed_json(tmp_path):
    incoming_dir = tmp_path / ".crucible" / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    
    filename = "malformed.json"
    with open(incoming_dir / filename, "w", encoding="utf-8") as f:
        f.write("{invalid json:}")
        
    payload = {
        "handoff_filename": filename,
        "prompt": "Add styling",
        "questions_mode": "off"
    }
    response = client.post("/api/sessions/from-tumbler", json=payload)
    assert response.status_code == 400
    assert "malformed json" in response.json()["detail"].lower()

def test_post_session_from_tumbler_missing_file():
    payload = {
        "handoff_filename": "nonexistent.json",
        "prompt": "Fix bug",
        "questions_mode": "off"
    }
    response = client.post("/api/sessions/from-tumbler", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_concurrency_conflict_sessions_stream():
    # 1. Create a running session directly in DB
    db.create_session("active-session-id", "Some prompt", "some corpus", status="running")
    
    # 2. Try starting a new session via stream without session_id
    response = client.post(
        "/api/sessions/stream",
        data={"prompt": "Another prompt"},
        files=[("files", ("main.py", b"print(1)"))]
    )
    assert response.status_code == 409
    data = response.json()
    assert "error" in data
    assert "already active" in data["error"] or "one running session" in data["error"]

