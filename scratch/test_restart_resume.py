import subprocess
import time
import sys
import os
import signal
import httpx
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env")

# Use working models (claude-sonnet-4-5 and gpt-5)
if "CRUCIBLE_GPT_MODEL" in os.environ:
    del os.environ["CRUCIBLE_GPT_MODEL"]
if "CRUCIBLE_CLAUDE_MODEL" in os.environ:
    del os.environ["CRUCIBLE_CLAUDE_MODEL"]

def log_subprocess_output(pipe):
    for line in iter(pipe.readline, ""):
        print(f"[SERVER] {line.strip()}")

def start_server():
    print("[TEST SETUP] Starting uvicorn server...")
    env = os.environ.copy()
    # Force python to run unbuffered
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8089"],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    import threading
    t = threading.Thread(target=log_subprocess_output, args=(proc.stdout,), daemon=True)
    t.start()
    return proc

def kill_server(proc):
    print("[TEST SETUP] Killing uvicorn server process...")
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.terminate()
        proc.wait()

async def read_stream_until_round2(session_id_holder):
    app_py_path = project_root / "scratch" / "test_flask_app" / "app.py"
    if not app_py_path.exists():
        print(f"Error: {app_py_path} not found.")
        return False

    with open(app_py_path, "rb") as f:
        file_bytes = f.read()

    files = [
        ("files", ("app.py", file_bytes, "text/plain"))
    ]
    data = {
        "prompt": "add user authentication"
    }

    url = "http://127.0.0.1:8089/api/sessions/stream"
    print(f"[TEST CLIENT] Connecting to {url} to start new debate...")

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", url, data=data, files=files) as response:
                if response.status_code != 200:
                    print(f"Error: Server returned status {response.status_code}")
                    return False
                
                # Read SSE lines
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    print(f"[NEW SSE EVENT] {line}")
                    
                    if line.startswith("event: session_started"):
                        # Next line is data
                        pass
                    if line.startswith("data:"):
                        # Check for session_id
                        import json
                        try:
                            payload = json.loads(line[5:].strip())
                            if "session_id" in payload:
                                session_id_holder[0] = payload["session_id"]
                                print(f"[TEST CLIENT] Captured Session ID: {session_id_holder[0]}")
                        except Exception:
                            pass
                    
                    # Kill when Round 2 starts (or after Round 1 finishes)
                    if "round_number\": 2" in line:
                        print("[TEST CLIENT] Round 2 started! Preparing to kill process mid-round...")
                        return True
        except httpx.RemoteProtocolError:
            # Server was killed, connection reset
            print("[TEST CLIENT] Connection reset (expected as server is killed).")
            return True
        except Exception as e:
            print(f"[TEST CLIENT] Request stream exception: {e}")
            return False

async def resume_debate(session_id):
    url = "http://127.0.0.1:8089/api/sessions/stream"
    data = {
        "session_id": session_id
    }
    print(f"[TEST CLIENT] Reconnecting to {url} to resume session {session_id}...")
    
    events_log = []
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream("POST", url, data=data) as response:
                if response.status_code != 200:
                    print(f"Error: Server returned status {response.status_code}")
                    return None
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    print(f"[RESUME SSE EVENT] {line}")
                    events_log.append(line)
                    
                    if "synthesis_completed" in line or "event: synthesis_completed" in line:
                        print("[TEST CLIENT] synthesis_completed received! Resume test success.")
                        break
        except Exception as e:
            print(f"[TEST CLIENT] Resume request stream exception: {e}")
            return None
    return events_log

async def main():
    # 1. Start uvicorn
    proc = start_server()
    time.sleep(3) # Wait for startup
    
    session_id_holder = [None]
    
    try:
        # 2. Start debate and read until round 2 starts
        success = await read_stream_until_round2(session_id_holder)
        if not success or not session_id_holder[0]:
            print("[TEST FAIL] Failed to initialize debate session.")
            kill_server(proc)
            return
        
        # Give it 2 seconds to make sure it started executing some tasks before kill
        time.sleep(2)
        
        # 3. Kill server mid-round
        kill_server(proc)
        print("[TEST SETUP] Server killed successfully. Waiting 3 seconds...")
        time.sleep(3)
        
        # 4. Restart server
        proc2 = start_server()
        time.sleep(3) # Wait for startup
        
        try:
            # 5. Resume session
            events = await resume_debate(session_id_holder[0])
            if events:
                print("\n================ SSE EVENT LOG FOR RESUME ================")
                for e in events:
                    print(e)
                print("==========================================================")
                
                # Save events to evidence
                evidence_dir = project_root / "evidence"
                evidence_dir.mkdir(exist_ok=True)
                with open(evidence_dir / "resume-sse-log.txt", "w", encoding="utf-8") as f:
                    f.write("\n".join(events))
                print(f"Saved resume events log to {evidence_dir / 'resume-sse-log.txt'}")
            else:
                print("[TEST FAIL] Resume failed.")
        finally:
            kill_server(proc2)
            
    except Exception as e:
        print(f"Error: {e}")
        kill_server(proc)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
