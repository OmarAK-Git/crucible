import sys
import os
import asyncio
import json
from pathlib import Path

# Add Crucible to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path="c:/Users/oalan/Crucible/.env")

from backend.corpus import build_evidence_bundle
from backend.orchestrator import run_debate
from backend import db

async def main():
    print("Loading test codebase corpus...")
    app_py_path = Path("C:/Users/oalan/.gemini/antigravity/brain/c3703a6f-354d-44e3-9036-732920416055/scratch/test_flask_app/app.py")
    if not app_py_path.exists():
        print(f"Error: app.py not found at {app_py_path}")
        return
        
    with open(app_py_path, "r", encoding="utf-8") as f:
        app_content = f.read()
        
    scanned_files = [
        {
            "path": "app.py",
            "size_bytes": len(app_content),
            "redacted": False,
            "truncated": False,
            "skipped": False,
            "content": app_content,
            "original_content": app_content.encode("utf-8")
        }
    ]
    corpus = build_evidence_bundle(scanned_files)
    
    prompt = "add user authentication"
    
    print("Initializing database...")
    db.init_db()
    
    print("Running sequential debate (real models: claude-sonnet-4-5 and gpt-5)...")
    event_queue = asyncio.Queue()
    
    # Run the debate in a task, and consume event queue to print logs in real-time
    debate_task = asyncio.create_task(run_debate(prompt, corpus, event_queue=event_queue))
    
    while True:
        if debate_task.done() and event_queue.empty():
            break
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.5)
            event_type, data = event
            print(f"\n[EVENT: {event_type}]")
            if event_type == "turn_completed":
                print(f"Adversary: {data['adversary']}, Round: {data['round_number']}")
                print(f"Summary: {data['response']['summary']}")
                print("New Proposals count:", len(data['response']['new_proposals']))
                print("Opponent Scores count:", len(data['response']['opponent_scores']))
            elif event_type == "round_scored":
                print(f"Round: {data['round_number']}")
                print(f"Scores Gained - Def: {data['defender_score']:.1f}, Chal: {data['challenger_score']:.1f}")
                print(f"Cumulative Scores - Def: {data['cumulative']['defender']:.1f}, Chal: {data['cumulative']['challenger']:.1f}")
            elif event_type == "termination":
                print("Reason:", data["reason"])
            elif event_type == "synthesis_completed":
                print("Final hardened prompt synthesized!")
            event_queue.task_done()
        except asyncio.TimeoutError:
            pass

    # Wait for the task to fully finish and fetch result
    result = await debate_task
    
    print("\n================ DEBATE RESULTS ================")
    print(f"Winner: {result.winner}")
    print(f"Termination Reason: {result.termination_reason}")
    print(f"Defender Score: {result.defender_score:.1f}")
    print(f"Challenger Score: {result.challenger_score:.1f}")
    
    # Save the output details to a file for review
    output_path = Path(__file__).parent / "debate_run_output.json"
    
    # Construct a serializable version of rounds
    rounds_serialized = []
    for r in result.rounds:
        rounds_serialized.append(r.model_dump())
        
    output_data = {
        "original_prompt": prompt,
        "winner": result.winner,
        "defender_score": result.defender_score,
        "challenger_score": result.challenger_score,
        "termination_reason": result.termination_reason,
        "final_prompt": result.final_prompt,
        "rounds": rounds_serialized
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
        
    print(f"\nSaved full run details to {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
