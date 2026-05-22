import tempfile
import uuid
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

# Load env variables
load_dotenv()

from .corpus import extract_and_read, build_evidence_bundle, UploadTooLargeError
from .adversary import run_round_1_adversaries
from .sessions import store_session, get_session

app = FastAPI(title="Crucible Phase 2 - Adversaries and Personas")

frontend_dir = Path(__file__).parent.parent / "frontend"

@app.post("/api/sessions")
async def create_session(
    prompt: str = Form(""),
    files: list[UploadFile] = File(default=[])
):
    # Validate prompt
    stripped_prompt = prompt.strip()
    if not stripped_prompt:
        return JSONResponse(
            status_code=400,
            content={"error": "The prompt cannot be empty"}
        )
    
    # Validate files (folder upload)
    # Check if files list is empty or if we received only dummy empty files
    valid_files = [f for f in files if f.filename and f.filename.strip()]
    if not valid_files:
        return JSONResponse(
            status_code=400,
            content={"error": "No files uploaded"}
        )
        
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            scanned_files_data = await extract_and_read(Path(temp_dir), valid_files)
            corpus = build_evidence_bundle(scanned_files_data)
            
            # Run adversaries concurrently
            adversary_results = await run_round_1_adversaries(stripped_prompt, corpus)
            
            # Generate session ID and store session
            session_id = uuid.uuid4().hex
            stored = store_session(
                session_id,
                stripped_prompt,
                adversary_results["defender_response"],
                adversary_results["challenger_response"]
            )
            
            return JSONResponse(status_code=200, content=stored)
            
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
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal server error: {str(e)}"}
        )

@app.get("/api/sessions/{id}")
async def get_session_endpoint(id: str):
    session = get_session(id)
    if not session:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session not found"}
        )
    return JSONResponse(status_code=200, content=session)

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
