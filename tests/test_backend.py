import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient
from fastapi import UploadFile

from backend.main import app
from backend.corpus import extract_and_read, build_evidence_bundle, UploadTooLargeError
from backend.sessions import _sessions

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_sessions():
    _sessions.clear()

@pytest.fixture
def mock_run_adversaries():
    with patch("backend.main.run_round_1_adversaries") as mock:
        mock.return_value = {
            "defender_response": {
                "proposals": [
                    {
                        "text": "Defender proposal text",
                        "severity": "critical",
                        "groundednessCitation": "folder/file1.txt",
                        "reasoning": "D reason"
                    }
                ]
            },
            "challenger_response": {
                "proposals": [
                    {
                        "text": "Challenger proposal text",
                        "severity": "important",
                        "groundednessCitation": "folder/file2.py",
                        "reasoning": "C reason"
                    }
                ]
            }
        }
        yield mock

def test_happy_path(mock_run_adversaries):
    # Prepare files for folder upload simulation
    file1 = ("files", ("folder/file1.txt", b"Hello from file 1"))
    file2 = ("files", ("folder/file2.py", b"print('Hello')"))
    
    response = client.post(
        "/api/sessions",
        data={"prompt": "Optimize this code"},
        files=[file1, file2]
    )
    
    assert response.status_code == 200
    json_data = response.json()
    assert "session_id" in json_data
    assert json_data["prompt"] == "Optimize this code"
    assert "defender_response" in json_data
    assert "challenger_response" in json_data
    assert json_data["defender_response"]["proposals"][0]["text"] == "Defender proposal text"
    assert json_data["challenger_response"]["proposals"][0]["text"] == "Challenger proposal text"
    
    mock_run_adversaries.assert_called_once()
    called_prompt, called_corpus = mock_run_adversaries.call_args[0]
    assert called_prompt == "Optimize this code"
    assert "file1.txt" in called_corpus
    assert "file2.py" in called_corpus

    # Test GET endpoint
    session_id = json_data["session_id"]
    get_response = client.get(f"/api/sessions/{session_id}")
    assert get_response.status_code == 200
    assert get_response.json() == json_data

def test_empty_prompt():
    file1 = ("files", ("folder/file1.txt", b"content"))
    
    response = client.post(
        "/api/sessions",
        data={"prompt": "  "},
        files=[file1]
    )
    
    assert response.status_code == 400
    assert response.json() == {"error": "The prompt cannot be empty"}

def test_no_files():
    response = client.post(
        "/api/sessions",
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
        
        # Create mocked UploadFiles with AsyncMock
        mock_files = [
            # 1. Normal file
            MagicMock(spec=UploadFile, filename="main.py", read=AsyncMock(side_effect=[b"print('hello')", b""])),
            # 2. Binary file
            MagicMock(spec=UploadFile, filename="logo.png", read=AsyncMock(side_effect=[b"\x89PNG\r\n\x1a\n", b""])),
            # 3. File in an ignored directory (e.g. node_modules) should be skipped during walk
            MagicMock(spec=UploadFile, filename="node_modules/index.js", read=AsyncMock(side_effect=[b"console.log()", b""]))
        ]

        scanned = await extract_and_read(temp_path, mock_files)
        
        scanned_by_path = {s["path"]: s for s in scanned}
        
        assert "main.py" in scanned_by_path
        assert scanned_by_path["main.py"]["skipped"] is False
        assert scanned_by_path["main.py"]["content"] == "print('hello')"
        
        assert "logo.png" in scanned_by_path
        assert scanned_by_path["logo.png"]["skipped"] is True
        assert scanned_by_path["logo.png"]["skip_reason"] == "binary file"
        
        # node_modules was ignored during walking
        assert "node_modules/index.js" not in scanned_by_path
        
        # Test build_evidence_bundle
        bundle = build_evidence_bundle(scanned)
        assert '<evidence path="main.py"' in bundle
        assert "print('hello')" in bundle
        assert '=== file: logo.png ===' in bundle
        assert '[Skipped: binary file]' in bundle

@pytest.mark.asyncio
async def test_corpus_size_limit():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Mock reading a chunk of 8192 bytes 7000 times (approx 57MB, exceeding 50MB)
        large_file = MagicMock(spec=UploadFile, filename="huge.txt")
        large_file.read = AsyncMock(side_effect=[b"a" * 8192] * 7000 + [b""])
        
        with pytest.raises(UploadTooLargeError):
            await extract_and_read(temp_path, [large_file])
