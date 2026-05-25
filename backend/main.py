import asyncio
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from dotenv import load_dotenv

# Load env variables
load_dotenv()

from .corpus import extract_and_read, build_evidence_bundle, UploadTooLargeError, load_pre_built_corpus
from . import db
from .orchestrator import run_debate, active_sessions
from pydantic import BaseModel

class AnswerPayload(BaseModel):
    question_id: str
    answer: str

class FromTumblerPayload(BaseModel):
    handoff_filename: str
    prompt: str
    questions_mode: str = "off"
    defender_model: str = "claude-sonnet-4-5"
    challenger_model: str = "gpt-5"


logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database on startup
    db.init_db()
    yield

app = FastAPI(title="Crucible", lifespan=lifespan)

frontend_dir = Path(__file__).parent.parent / "frontend"

@app.post("/api/sessions/stream")
async def start_or_resume_debate(
    prompt: str = Form(None),
    files: list[UploadFile] = File(default=[]),
    session_id: str = Form(None),
    questions_mode: str = Form("off"),
    defender_model: str = Form("claude-sonnet-4-5"),
    challenger_model: str = Form("gpt-5")
):
    """
    POST /api/sessions/stream
    Starts a new debate session or resumes an existing one, yielding SSE log events.
    If the SSE client disconnects (broken pipe), the orchestrator continues writing to SQLite in the background
    while the FastAPI generator catches the exception gracefully, logs it, and exits.
    """
    if session_id:
        # Resume flow
        state = db.load_session_state(session_id)
        if not state:
            return JSONResponse(
                status_code=404,
                content={"error": f"Session {session_id} not found to resume."}
            )
        # DEV NOTE: In V1 (single-user, single-process), any session with status="running" at startup
        # is dead by definition. We load its state and resume from the last completed turn.
        if state["status"] != "running" and state["status"] != "completed":
            # If not running/completed, we still allow starting/resuming it.
            # But the spec says running status means it can be resumed.
            pass
        
        # Load prompt and corpus from DB
        debate_prompt = state["prompt"]
        debate_corpus = state["corpus"]
        active_session_id = session_id
        active_defender_model = state.get("defender_model", "claude-sonnet-4-5")
        active_challenger_model = state.get("challenger_model", "gpt-5")
    else:
        # Start new flow
        # Check concurrency V1 constraint: reject new session if one is already running
        active = db.get_active_sessions()
        if active:
            return JSONResponse(
                status_code=409,
                content={"error": "A debate session is already active. V1 only supports one running session at a time."}
            )
            
        # Validate prompt
        if not prompt or not prompt.strip():
            return JSONResponse(
                status_code=400,
                content={"error": "The prompt cannot be empty"}
            )
        
        # Validate files (folder upload)
        valid_files = [f for f in files if f.filename and f.filename.strip()]
        if not valid_files:
            return JSONResponse(
                status_code=400,
                content={"error": "No files uploaded"}
            )
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                scanned_files_data = await extract_and_read(Path(temp_dir), valid_files)
                debate_corpus = build_evidence_bundle(scanned_files_data)
                debate_prompt = prompt.strip()
                # Create a session ID to track it immediately
                import uuid
                active_session_id = uuid.uuid4().hex
                # We save the session record now with status "running" and questions_mode
                db.create_session(
                    active_session_id, debate_prompt, debate_corpus,
                    questions_mode=questions_mode,
                    defender_model=defender_model,
                    challenger_model=challenger_model
                )
                active_defender_model = defender_model
                active_challenger_model = challenger_model
        except UploadTooLargeError as e:
            return JSONResponse(
                status_code=413,
                content={"error": str(e)}
            )
        except ValueError as e:
            return JSONResponse(
                status_code=400,
                content={"error": str(e)}
            )
        except Exception as e:
            logger.exception("Error extracting corpus")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error building corpus: {str(e)}"}
            )
 
    # Spawn the orchestrator in the background so it is not tied to the client connection
    event_queue = asyncio.Queue()
    debate_task = asyncio.create_task(run_debate(
        prompt=debate_prompt,
        corpus=debate_corpus,
        session_id=active_session_id,
        event_queue=event_queue,
        questions_mode=questions_mode,
        defender_model=active_defender_model,
        challenger_model=active_challenger_model
    ))

    async def event_generator():
        try:
            while True:
                # If debate is finished and all events are drained, stop streaming
                if debate_task.done() and event_queue.empty():
                    # If task raised an exception, propagate/log it
                    exc = debate_task.exception()
                    if exc:
                        logger.error(f"Debate task failed with exception: {exc}")
                        yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
                    break
                
                try:
                    # Non-blocking check with small timeout to allow keep-alives and task checking
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    event_type, data = event
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                    event_queue.task_done()
                except asyncio.TimeoutError:
                    if debate_task.done() and event_queue.empty():
                        break
                    # Keep connection alive with pings
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            # Client closed the connection mid-debate
            logger.info(f"SSE client disconnected gracefully for session {active_session_id}. The debate run will continue to execute and persist in the background.")
            # Do NOT cancel debate_task! Let it run to completion.
        except Exception as e:
            logger.error(f"Error in SSE stream for session {active_session_id}: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/sessions/active")
async def get_active_sessions_endpoint():
    """
    GET /api/sessions/active
    Retrieves the list of active running sessions from the database.
    """
    sessions = db.get_active_sessions()
    return JSONResponse(status_code=200, content=sessions)

@app.get("/api/sessions/{id}")
async def get_session_endpoint(id: str):
    """
    GET /api/sessions/{id}
    Loads the completed or stored session details from SQLite database.
    """
    state = db.load_session_state(id)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session not found"}
        )
    
    # We can format the return dict to be JSON serializable
    # Need to convert round objects to dicts
    serializable_rounds = []
    for r in state.get("rounds", []):
        r_dict = r.model_dump()
        serializable_rounds.append(r_dict)
        
    return JSONResponse(status_code=200, content={
        "session_id": state["session_id"],
        "prompt": state["prompt"],
        "status": state["status"],
        "winner": state["winner"],
        "termination_reason": state["termination_reason"],
        "final_prompt": state["final_prompt"],
        "rounds": serializable_rounds
    })

@app.post("/api/sessions/{id}/answers")
async def post_answer_endpoint(id: str, payload: AnswerPayload):
    # Validate answer
    ans = payload.answer.strip()
    if not ans:
        raise HTTPException(
            status_code=400,
            detail="The answer cannot be empty."
        )
    if len(ans) > 4000:
        raise HTTPException(
            status_code=400,
            detail="The answer cannot exceed 4000 characters."
        )
        
    # Check if session exists
    session = db.get_session(id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session {id} not found."
        )
        
    # Check if the question exists and is pending
    pending = db.get_pending_questions(id)
    target_q = None
    for q in pending:
        if q["question_id"] == payload.question_id:
            target_q = q
            break
            
    if not target_q:
        # Check if the question has already been answered (to handle duplicate submissions gracefully)
        answered_q = db.get_question(payload.question_id)
        if answered_q and answered_q["session_id"] == id:
            return JSONResponse(status_code=200, content={"status": "success", "message": "Answer already saved."})
            
        raise HTTPException(
            status_code=404,
            detail=f"Pending question {payload.question_id} not found for this session."
        )
        
    # Persist the answer
    db.save_answer(payload.question_id, ans, "human")
    
    # Check if all pending questions for the current turn are now answered.
    round_number = target_q["round_number"]
    adversary = target_q["adversary"]
    
    remaining = db.get_pending_questions_for_turn(id, round_number, adversary)
    if not remaining:
        # Resume the orchestrator if it is currently active in memory
        if id in active_sessions:
            active_sessions[id].set()
            logger.info(f"Signaled active orchestrator for session {id} to resume.")
        else:
            logger.info(f"Session {id} updated in database. Orchestrator will resume from SQLite state when stream is reconnected.")
            
    return JSONResponse(status_code=200, content={"status": "success", "message": "Answer saved."})

@app.get("/api/sessions/{id}/pending-questions")
async def get_pending_questions_endpoint(id: str):
    session = db.get_session(id)
    if not session:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {id} not found."}
        )
    pending = db.get_pending_questions(id)
    return JSONResponse(status_code=200, content=pending)

@app.get("/api/handoffs/incoming")
async def get_incoming_handoffs_endpoint():
    """
    GET /api/handoffs/incoming
    Scans ~/.crucible/incoming/ for handoff files, parsing their metadata.
    """
    incoming_dir = Path.home() / ".crucible" / "incoming"
    if not incoming_dir.exists():
        return JSONResponse(status_code=200, content=[])
        
    handoffs = []
    for file_path in incoming_dir.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            handoffs.append({
                "filename": file_path.name,
                "tumbler_session_id": data.get("tumbler_session_id", ""),
                "created_at": data.get("created_at", ""),
                "tumbler_verdict": data.get("tumbler_verdict", "PASS")
            })
        except Exception:
            # Skip invalid/malformed files
            pass
            
    # Sort by created_at descending
    handoffs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return JSONResponse(status_code=200, content=handoffs)

@app.post("/api/sessions/from-tumbler")
async def create_session_from_tumbler_endpoint(payload: FromTumblerPayload):
    """
    POST /api/sessions/from-tumbler
    Creates a new Crucible debate session from a Tumbler handoff file.
    Moves the handoff file from incoming to consumed directory.
    """
    # Prevent directory traversal
    safe_filename = Path(payload.handoff_filename).name
    handoff_path = Path.home() / ".crucible" / "incoming" / safe_filename
    
    if not handoff_path.exists():
        raise HTTPException(status_code=404, detail="Handoff file not found.")
        
    try:
        with open(handoff_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="The handoff file contains malformed JSON.")
        
    corpus_bundle = data.get("corpus_bundle", "")
    try:
        load_pre_built_corpus(corpus_bundle)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="The prompt cannot be empty.")
        
    import uuid
    new_session_id = uuid.uuid4().hex
    
    # Save the session to SQLite
    db.create_session(
        session_id=new_session_id,
        prompt=prompt,
        corpus=corpus_bundle,
        status="running",
        questions_mode=payload.questions_mode,
        defender_model=payload.defender_model,
        challenger_model=payload.challenger_model
    )
    
    # Move the handoff file to consumed directory
    consumed_dir = Path.home() / ".crucible" / "consumed"
    consumed_dir.mkdir(parents=True, exist_ok=True)
    consumed_path = consumed_dir / f"{new_session_id}.json"
    
    import shutil
    try:
        shutil.move(str(handoff_path), str(consumed_path))
    except Exception as e:
        logger.exception("Failed to move handoff file to consumed")
        # Continue anyway as session is already saved in SQLite
        
    return JSONResponse(status_code=200, content={"session_id": new_session_id})

@app.get("/api/sessions/{id}/debug-export")
async def get_debug_export_endpoint(id: str):
    """
    GET /api/sessions/{id}/debug-export
    Fetches the entire session state plus all question answers to produce a complete debug JSON.
    """
    state = db.load_session_state(id)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {id} not found."}
        )
        
    # Reconstruct rounds to be dicts
    serializable_rounds = []
    for r in state.get("rounds", []):
        serializable_rounds.append(r.model_dump())
        
    # Get all question answers (both pending and completed)
    import sqlite3
    conn = db.get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM question_answers WHERE session_id = ? ORDER BY round_number ASC, question_id ASC;", (id,))
        qas = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
        
    return JSONResponse(status_code=200, content={
        "session_id": state["session_id"],
        "prompt": state["prompt"],
        "corpus": state["corpus"],
        "status": state["status"],
        "winner": state["winner"],
        "termination_reason": state["termination_reason"],
        "final_prompt": state["final_prompt"],
        "defender_model": state.get("defender_model"),
        "challenger_model": state.get("challenger_model"),
        "rounds": serializable_rounds,
        "question_answers": qas
    })

@app.get("/")
async def serve_index():
    index_file = frontend_dir / "index.html"
    if not index_file.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "Frontend index.html is missing"}
        )
    return FileResponse(index_file)

# Mount the static files directory to serve frontend assets.
# Note: This is placed at the end to ensure API routes are checked first.
app.mount("/", StaticFiles(directory=frontend_dir), name="frontend")
