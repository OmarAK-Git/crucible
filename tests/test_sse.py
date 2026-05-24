import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

@pytest.fixture
def mock_run_debate():
    with patch("backend.main.run_debate", new_callable=AsyncMock) as mock:
        async def mock_debate_impl(prompt, corpus, session_id, event_queue, questions_mode="off"):
            await event_queue.put(("session_started", {"session_id": session_id, "prompt": prompt}))
            await event_queue.put(("corpus_built", {"file_count": 2, "total_chars": 50}))
            await event_queue.put(("synthesis_completed", {"final_prompt": "Hardened prompt"}))
            # Mock return of DebateResult-like object
            class FakeResult:
                rounds = []
                final_prompt = "Hardened prompt"
                winner = "defender"
                termination_reason = "Done"
                defender_score = 0.0
                challenger_score = 0.0
            return FakeResult()
            
        mock.side_effect = mock_debate_impl
        yield mock

def test_sse_stream_success(mock_run_debate):
    file_data = ("files", ("main.py", b"print('hello')"))
    
    # We use client.post which reads the stream response
    # For TestClient, StreamingResponse returns a response whose .iter_lines() can be iterated.
    response = client.post(
        "/api/sessions/stream",
        data={"prompt": "Optimize"},
        files=[file_data]
    )
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    lines = list(response.iter_lines())
    
    # Filter and decode lines
    events = [l for l in lines if l]
    
    # Verify events sequence (event followed by data)
    assert "event: session_started" in events[0]
    assert "data: " in events[1]
    assert "event: corpus_built" in events[2]
    assert "data: " in events[3]
    assert "event: synthesis_completed" in events[4]
