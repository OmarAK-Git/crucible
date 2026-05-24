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
    print("Building codebase corpus for Crucible (README.md, main.py, orchestrator.py)...")
    
    files_to_read = [
        ("README.md", "c:/Users/oalan/Crucible/README.md"),
        ("backend/main.py", "c:/Users/oalan/Crucible/backend/main.py"),
        ("backend/orchestrator.py", "c:/Users/oalan/Crucible/backend/orchestrator.py")
    ]
    
    scanned_files = []
    for relative_path, absolute_path in files_to_read:
        p = Path(absolute_path)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
            scanned_files.append({
                "path": relative_path,
                "size_bytes": len(content),
                "redacted": False,
                "truncated": False,
                "skipped": False,
                "content": content,
                "original_content": content.encode("utf-8")
            })
            
    corpus = build_evidence_bundle(scanned_files)
    
    prompt = "turn Crucible into a chatbot that helps users plan their wedding"
    
    print("Initializing database...")
    db.init_db()
    
    print("Running debate session on real models (claude-sonnet-4-5, gpt-5) in auto-answer mode...")
    event_queue = asyncio.Queue()
    
    debate_task = asyncio.create_task(run_debate(
        prompt, corpus, event_queue=event_queue, questions_mode="on"
    ))
    
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
                print("New Proposals:")
                for p in data['response']['new_proposals']:
                    print(f"  - Severity: {p['severity']} | Citation: {p['groundednessCitation']}")
                    print(f"    Text: {p['text']}")
                if 'questions_for_human' in data['response'] and data['response']['questions_for_human']:
                    print("Questions:")
                    for q in data['response']['questions_for_human']:
                        print(f"  - Question: {q['question']}")
            elif event_type == "questions_auto_answered":
                print(f"Auto-answered for {data['adversary']} in Round {data['round_number']}:")
                for ans in data['answers']:
                    print(f"  - Question: {ans['question']} -> Answer: {ans['answer']}")
            elif event_type == "round_scored":
                print(f"Round: {data['round_number']}")
                print(f"Scores Gained - Def: {data['defender_score']:.1f}, Chal: {data['challenger_score']:.1f}")
                print(f"Cumulative Scores - Def: {data['cumulative']['defender']:.1f}, Chal: {data['cumulative']['challenger']:.1f}")
            elif event_type == "termination":
                print("Reason:", data["reason"])
            elif event_type == "synthesis_completed":
                print("Final prompt:")
                print(data["final_prompt"][:500] + "...")
            event_queue.task_done()
        except asyncio.TimeoutError:
            pass

    result = await debate_task
    
    print("\n================ DEBATE RESULTS ================")
    print(f"Winner: {result.winner}")
    print(f"Termination Reason: {result.termination_reason}")
    print(f"Defender Score: {result.defender_score:.1f}")
    print(f"Challenger Score: {result.challenger_score:.1f}")
    
    output_path = Path(__file__).parent / "wedding_planner_debate_output.json"
    
    rounds_serialized = [r.model_dump() for r in result.rounds]
        
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
