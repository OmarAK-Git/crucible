import os
import sys
import json
import time
import shutil
import tempfile
import requests
from pathlib import Path

TUMBLER_URL = "http://127.0.0.1:8001"
CRUCIBLE_URL = "http://127.0.0.1:8000"

def create_clean_project(temp_dir):
    p = Path(temp_dir)
    # 1. Create code
    (p / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    # 2. Create README
    (p / "README.md").write_text("# Hello Project\nSimple clean project.\n", encoding="utf-8")
    # 3. Create evidence folder with test results
    ev_dir = p / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "test-results.txt").write_text("=================== 1 passed in 0.01s ===================\n", encoding="utf-8")
    return p

def create_dirty_project(temp_dir):
    p = Path(temp_dir)
    # 1. Create code with hardcoded API key secret
    (p / "main.py").write_text("def init_auth():\n    secret = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8")
    # 2. Create README
    (p / "README.md").write_text("# Dirty Project\n", encoding="utf-8")
    # 3. Create evidence
    ev_dir = p / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "test-results.txt").write_text("=================== 1 passed ===================\n", encoding="utf-8")
    return p

def run_e2e():
    print("=== STARTING PHASE 5 E2E INTEGRATION TEST ===")
    
    # Verify both servers are reachable
    try:
        requests.get(TUMBLER_URL)
    except Exception:
        print(f"Error: Tumbler server at {TUMBLER_URL} is not running.")
        sys.exit(1)
        
    try:
        requests.get(CRUCIBLE_URL)
    except Exception:
        print(f"Error: Crucible server at {CRUCIBLE_URL} is not running.")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as temp_dir_clean:
        clean_proj = create_clean_project(temp_dir_clean)
        
        print("\n--- 1. Submitting clean project to Tumbler ---")
        files = []
        for file_path in clean_proj.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(clean_proj)
                files.append(('files', (str(rel_path).replace("\\", "/"), open(file_path, 'rb'))))
                
        t0 = time.time()
        res_review = requests.post(f"{TUMBLER_URL}/api/review", files=files)
        # Close file handles
        for _, (_, f) in files:
            f.close()
            
        assert res_review.status_code == 200, f"Review failed: {res_review.text}"
        review_data = res_review.json()
        print(f"Tumbler response (took {time.time()-t0:.2f}s):")
        print(f"Verdict: {review_data.get('verdict')}")
        print(f"Summary: {review_data.get('summary')}")
        print(f"Session ID: {review_data.get('session_id')}")
        
        verdict = review_data.get("verdict")
        session_id = review_data.get("session_id")
        assert verdict == "PASS", f"Expected PASS verdict, got: {verdict}"
        assert session_id is not None, "Session ID missing from response"
        
        print("\n--- 2. Pushing PASS verdict from Tumbler to Crucible ---")
        res_push = requests.post(f"{TUMBLER_URL}/api/sessions/{session_id}/push-to-crucible")
        assert res_push.status_code == 200, f"Push failed: {res_push.text}"
        push_data = res_push.json()
        print(f"Push success. Handoff path: {push_data.get('handoff_path')}")
        
        expected_handoff = Path.home() / ".crucible" / "incoming" / f"{session_id}.json"
        assert expected_handoff.exists(), f"Handoff file does not exist at {expected_handoff}"
        print(f"Confirmed handoff file exists at expected path.")

    # Now verify Crucible lists it
    print("\n--- 3. Verifying Crucible GET /api/handoffs/incoming ---")
    res_incoming = requests.get(f"{CRUCIBLE_URL}/api/handoffs/incoming")
    assert res_incoming.status_code == 200
    incoming_list = res_incoming.json()
    
    matching_handoff = next((h for h in incoming_list if h["tumbler_session_id"] == session_id), None)
    assert matching_handoff is not None, f"Handoff session {session_id} not found in incoming list: {incoming_list}"
    print(f"Found matching handoff: {matching_handoff}")
    
    # POST to /api/sessions/from-tumbler to ingest handoff and start session
    print("\n--- 4. Consuming handoff in Crucible /api/sessions/from-tumbler ---")
    payload = {
        "handoff_filename": f"{session_id}.json",
        "prompt": "Add database caching for user sessions",
        "questions_mode": "on"  # Use ON to auto-answer and let debate run unimpeded
    }
    
    res_consume = requests.post(f"{CRUCIBLE_URL}/api/sessions/from-tumbler", json=payload)
    assert res_consume.status_code == 200, f"Consume failed: {res_consume.text}"
    consume_data = res_consume.json()
    new_session_id = consume_data.get("session_id")
    print(f"Crucible session created successfully: {new_session_id}")
    
    # Confirm handoff file is moved to consumed
    expected_consumed = Path.home() / ".crucible" / "consumed" / f"{new_session_id}.json"
    assert expected_consumed.exists(), f"Handoff not found in consumed directory: {expected_consumed}"
    assert not expected_handoff.exists(), "Handoff file was not removed from incoming folder"
    print("Confirmed handoff moved from incoming to consumed correctly.")
    
    # Stream debate end-to-end
    print("\n--- 5. Streaming debate end-to-end from Crucible ---")
    stream_data = {
        "session_id": new_session_id,
        "questions_mode": "on"
    }
    
    # Start post request with streaming enabled
    res_stream = requests.post(f"{CRUCIBLE_URL}/api/sessions/stream", data=stream_data, stream=True)
    assert res_stream.status_code == 200
    
    print("SSE LOG:")
    for line in res_stream.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("event:"):
                event_type = decoded_line.split(":", 1)[1].strip()
                print(f"\n[Event: {event_type}]")
            elif decoded_line.startswith("data:"):
                try:
                    data_json = json.loads(decoded_line.split(":", 1)[1].strip())
                    if event_type == "log":
                        print(f"  {data_json.get('message')}")
                    elif event_type == "synthesis_completed":
                        print("\n=== Hardened Synthesis Prompt ===")
                        print(data_json.get("final_prompt"))
                    elif event_type == "debate_completed":
                        print(f"\nDebate completed. Winner: {data_json.get('winner')}, Reason: {data_json.get('termination_reason')}")
                        print(f"Final Scores -> Defender: {data_json.get('defender_score')}, Challenger: {data_json.get('challenger_score')}")
                except Exception as e:
                    print(f"  Raw data: {decoded_line}")
                    
    print("\n=== E2E Integration Test Successful ===")

def test_pass_only_gating():
    print("\n=== TESTING PASS-ONLY GATING (FIX VERDICT SCENARIO) ===")
    with tempfile.TemporaryDirectory() as temp_dir_dirty:
        dirty_proj = create_dirty_project(temp_dir_dirty)
        
        print("Submitting dirty project to Tumbler...")
        files = []
        for file_path in dirty_proj.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(dirty_proj)
                files.append(('files', (str(rel_path).replace("\\", "/"), open(file_path, 'rb'))))
                
        res_review = requests.post(f"{TUMBLER_URL}/api/review", files=files)
        for _, (_, f) in files:
            f.close()
            
        assert res_review.status_code == 200
        review_data = res_review.json()
        print(f"Verdict: {review_data.get('verdict')}")
        print(f"Session ID: {review_data.get('session_id')}")
        
        verdict = review_data.get("verdict")
        session_id = review_data.get("session_id")
        assert verdict == "FIX", f"Expected FIX verdict, got {verdict}"
        
        # Try pushing to Crucible, should return 400
        res_push = requests.post(f"{TUMBLER_URL}/api/sessions/{session_id}/push-to-crucible")
        print(f"Push to Crucible response: {res_push.status_code} - {res_push.text}")
        assert res_push.status_code == 400
        assert "Crucible push is only available for PASS verdicts" in res_push.json()["error"]
        print("Gating works! 400 correctly returned for FIX verdict push attempt.")

if __name__ == "__main__":
    try:
        run_e2e()
        test_pass_only_gating()
    except Exception as e:
        print(f"Verification script failed: {e}")
        sys.exit(1)
