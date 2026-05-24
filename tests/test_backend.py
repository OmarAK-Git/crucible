import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient
from fastapi import UploadFile

from backend.main import app
from backend.corpus import extract_and_read, build_evidence_bundle, UploadTooLargeError
from backend import db

client = TestClient(app)

@pytest.fixture
def mock_run_debate():
    with patch("backend.main.run_debate", new_callable=AsyncMock) as mock:
        async def mock_debate_impl(prompt, corpus, session_id, event_queue, questions_mode="off"):
            # Save a complete mock session to DB so get_session endpoint works
            db.update_session(
                session_id,
                status="completed",
                winner="defender",
                termination_reason="Finished",
                final_prompt="Hardened output prompt"
            )
            # Create a mock round
            db.save_round(session_id, 1, "Working prompt after R1")
            
            await event_queue.put(("session_started", {"session_id": session_id, "prompt": prompt}))
            await event_queue.put(("synthesis_completed", {"final_prompt": "Hardened output prompt"}))
            
            class FakeResult:
                rounds = []
                final_prompt = "Hardened output prompt"
                winner = "defender"
                termination_reason = "Done"
                defender_score = 0.0
                challenger_score = 0.0
            return FakeResult()
            
        mock.side_effect = mock_debate_impl
        yield mock

def test_happy_path_streaming(mock_run_debate):
    file1 = ("files", ("folder/file1.txt", b"Hello from file 1"))
    file2 = ("files", ("folder/file2.py", b"print('Hello')"))
    
    response = client.post(
        "/api/sessions/stream",
        data={"prompt": "Optimize this code"},
        files=[file1, file2]
    )
    
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    
    lines = list(response.iter_lines())
    decoded_lines = [l for l in lines if l]
    
    # We should have received session_started event which is followed by the data line
    started_event_index = [i for i, l in enumerate(decoded_lines) if "session_started" in l][0]
    data_line = decoded_lines[started_event_index + 1]
    import json
    data_str = data_line.split("data: ")[1].strip()
    data_json = json.loads(data_str)
    session_id = data_json["session_id"]
    
    # Test GET completed session by ID
    get_response = client.get(f"/api/sessions/{session_id}")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["session_id"] == session_id
    assert get_data["status"] == "completed"
    assert get_data["final_prompt"] == "Hardened output prompt"

def test_empty_prompt():
    file1 = ("files", ("folder/file1.txt", b"content"))
    
    response = client.post(
        "/api/sessions/stream",
        data={"prompt": "  "},
        files=[file1]
    )
    
    assert response.status_code == 400
    assert response.json() == {"error": "The prompt cannot be empty"}

def test_no_files():
    response = client.post(
        "/api/sessions/stream",
        data={"prompt": "Optimize code"},
        files=[]
    )
    
    assert response.status_code == 400
    assert response.json() == {"error": "No files uploaded"}

def test_get_not_found():
    response = client.get("/api/sessions/nonexistent_id")
    assert response.status_code == 404
    assert response.json() == {"error": "Session not found"}

@pytest.mark.asyncio
async def test_corpus_smoke_test():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        mock_files = [
            MagicMock(spec=UploadFile, filename="main.py", read=AsyncMock(side_effect=[b"print('hello')", b""])),
            MagicMock(spec=UploadFile, filename="logo.png", read=AsyncMock(side_effect=[b"\x89PNG\r\n\x1a\n", b""])),
            MagicMock(spec=UploadFile, filename="node_modules/index.js", read=AsyncMock(side_effect=[b"console.log()", b""]))
        ]

        scanned = await extract_and_read(temp_path, mock_files)
        scanned_by_path = {s["path"]: s for s in scanned}
        
        assert "main.py" in scanned_by_path
        assert scanned_by_path["main.py"]["skipped"] is False
        assert scanned_by_path["main.py"]["content"] == "print('hello')"
        
        assert "logo.png" in scanned_by_path
        assert scanned_by_path["logo.png"]["skipped"] is True
        
        assert "node_modules/index.js" not in scanned_by_path
        
        bundle = build_evidence_bundle(scanned)
        assert '<evidence path="main.py"' in bundle
        assert "print('hello')" in bundle

@pytest.mark.asyncio
async def test_corpus_size_limit():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        large_file = MagicMock(spec=UploadFile, filename="huge.txt")
        large_file.read = AsyncMock(side_effect=[b"a" * 8192] * 7000 + [b""])
        
        with pytest.raises(UploadTooLargeError):
            await extract_and_read(temp_path, [large_file])
