import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from .schemas import Round, TurnResponse, Proposal, OpponentScore, DebateResult

def get_db_path() -> Path:
    """
    Returns the path to the SQLite database.
    Allows override via CRUCIBLE_DB_PATH environment variable for testing.
    """
    env_path = os.environ.get("CRUCIBLE_DB_PATH")
    if env_path:
        p = Path(env_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    db_dir = Path.home() / ".crucible"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "crucible.db"

def get_connection():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """
    Performs schema migrations on startup (creates tables if missing).
    """
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                corpus TEXT NOT NULL,
                status TEXT NOT NULL,
                winner TEXT,
                termination_reason TEXT,
                final_prompt TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            
            # Check/Add questions_mode column to sessions table
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN questions_mode TEXT DEFAULT 'off';")
            except sqlite3.OperationalError:
                # Column already exists
                pass

            conn.execute("""
            CREATE TABLE IF NOT EXISTS rounds (
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                working_prompt_after TEXT NOT NULL,
                PRIMARY KEY (session_id, round_number),
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            );
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                adversary TEXT NOT NULL,
                summary TEXT,
                disagreements_json TEXT, -- Serialized JSON list of addressed disagreements
                PRIMARY KEY (session_id, round_number, adversary),
                FOREIGN KEY (session_id, round_number) REFERENCES rounds (session_id, round_number) ON DELETE CASCADE
            );
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                proposal_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                adversary TEXT NOT NULL,
                text TEXT NOT NULL,
                severity TEXT NOT NULL,
                groundedness_citation TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                FOREIGN KEY (session_id, round_number, adversary) REFERENCES turns (session_id, round_number, adversary) ON DELETE CASCADE
            );
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                proposal_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                scorer TEXT NOT NULL,
                verdict TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                modification TEXT,
                PRIMARY KEY (proposal_id, session_id, round_number, scorer),
                FOREIGN KEY (proposal_id) REFERENCES proposals (proposal_id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            );
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS question_answers (
                question_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                adversary TEXT NOT NULL,
                question TEXT NOT NULL,
                why_it_matters TEXT NOT NULL,
                recommended_default TEXT NOT NULL,
                default_reasoning TEXT NOT NULL,
                answer TEXT,
                source TEXT,  -- "human" or "auto_default", NULL while pending
                answered_at TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            );
            """)
    finally:
        conn.close()

def create_session(session_id: str, prompt: str, corpus: str, status: str = "running", questions_mode: str = "off"):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO sessions (session_id, prompt, corpus, status, questions_mode) VALUES (?, ?, ?, ?, ?);",
                (session_id, prompt, corpus, status, questions_mode)
            )
    finally:
        conn.close()

def update_session(
    session_id: str,
    status: str,
    winner: Optional[str] = None,
    termination_reason: Optional[str] = None,
    final_prompt: Optional[str] = None
):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                UPDATE sessions 
                SET status = ?, winner = ?, termination_reason = ?, final_prompt = ?
                WHERE session_id = ?;
                """,
                (status, winner, termination_reason, final_prompt, session_id)
            )
    finally:
        conn.close()

def save_round(session_id: str, round_number: int, working_prompt_after: str):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO rounds (session_id, round_number, working_prompt_after)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id, round_number) DO UPDATE SET
                    working_prompt_after = excluded.working_prompt_after;
                """,
                (session_id, round_number, working_prompt_after)
            )
    finally:
        conn.close()

def save_turn(session_id: str, round_number: int, adversary: str, summary: str, disagreements: List[str] = None):
    import json
    dis_json = json.dumps(disagreements or [])
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO turns (session_id, round_number, adversary, summary, disagreements_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, round_number, adversary) DO UPDATE SET
                    summary = excluded.summary,
                    disagreements_json = excluded.disagreements_json;
                """,
                (session_id, round_number, adversary, summary, dis_json)
            )
    finally:
        conn.close()

def save_proposals(session_id: str, round_number: int, adversary: str, proposals: List[Proposal]):
    print(f"[DATABASE DEBUG] save_proposals: session_id={session_id}, round_number={round_number}, adversary={adversary}, count={len(proposals)}")
    for p in proposals:
        print(f"  Saving proposal: id={p.id}, adversary={p.adversary}, text={p.text[:30] if p.text else ''}")
    conn = get_connection()
    try:
        with conn:
            for p in proposals:
                conn.execute(
                    """
                    INSERT INTO proposals (proposal_id, session_id, round_number, adversary, text, severity, groundedness_citation, reasoning)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(proposal_id) DO UPDATE SET
                        session_id = excluded.session_id,
                        round_number = excluded.round_number,
                        adversary = excluded.adversary,
                        text = excluded.text,
                        severity = excluded.severity,
                        groundedness_citation = excluded.groundedness_citation,
                        reasoning = excluded.reasoning;
                    """,
                    (p.id, session_id, round_number, adversary, p.text, p.severity, p.groundednessCitation, p.reasoning)
                )
    finally:
        conn.close()

def save_score(proposal_id: str, session_id: str, round_number: int, scorer: str, verdict: str, reasoning: str, modification: str = None):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scores (proposal_id, session_id, round_number, scorer, verdict, reasoning, modification)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id, session_id, round_number, scorer) DO UPDATE SET
                    verdict = excluded.verdict,
                    reasoning = excluded.reasoning,
                    modification = excluded.modification;
                """,
                (proposal_id, session_id, round_number, scorer, verdict, reasoning, modification)
            )
    except sqlite3.IntegrityError as e:
        print(f"\n[DATABASE DEBUG] IntegrityError in save_score:")
        print(f"  Attempting to insert score:")
        print(f"    proposal_id: {proposal_id}")
        print(f"    session_id: {session_id}")
        print(f"    round_number: {round_number}")
        print(f"    scorer: {scorer}")
        print(f"    verdict: {verdict}")
        
        cur = conn.cursor()
        # Check session
        cur.execute("SELECT session_id FROM sessions WHERE session_id = ?;", (session_id,))
        sess_exists = cur.fetchone() is not None
        print(f"  Session exists in DB: {sess_exists}")
        
        # Check proposal
        cur.execute("SELECT proposal_id, session_id, round_number, adversary FROM proposals WHERE proposal_id = ?;", (proposal_id,))
        prop_row = cur.fetchone()
        print(f"  Proposal '{proposal_id}' exists in DB: {prop_row is not None}")
        if prop_row:
            print(f"    Proposal detail in DB: session_id={prop_row[1]}, round_number={prop_row[2]}, adversary={prop_row[3]}")
        else:
            cur.execute("SELECT proposal_id, session_id, round_number, adversary FROM proposals;")
            all_props = cur.fetchall()
            print(f"  All proposals currently in DB ({len(all_props)}):")
            for ap in all_props:
                print(f"    {ap[0]} (session_id={ap[1]}, round_number={ap[2]}, adversary={ap[3]})")
            
        raise e
    finally:
        conn.close()

def get_active_sessions() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT session_id, prompt, status, created_at FROM sessions WHERE status = 'running' ORDER BY created_at DESC;")
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the raw session record.
    """
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM sessions WHERE session_id = ?;", (session_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def load_session_state(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Loads all rounds, turns, proposals, and scores for a session to reconstruct its state.
    """
    session = get_session(session_id)
    if not session:
        return None
        
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 1. Fetch rounds
        cur.execute("SELECT round_number, working_prompt_after FROM rounds WHERE session_id = ? ORDER BY round_number ASC;", (session_id,))
        rounds_rows = cur.fetchall()
        
        rounds_list = []
        all_proposals = {}  # Cache proposals by ID
        
        for r_row in rounds_rows:
            round_num = r_row["round_number"]
            wp_after = r_row["working_prompt_after"]
            
            # Fetch turns in this round
            cur.execute("SELECT adversary, summary, disagreements_json FROM turns WHERE session_id = ? AND round_number = ?;", (session_id, round_num))
            turns_rows = cur.fetchall()
            
            turns_dict = {row["adversary"]: row for row in turns_rows}
            
            defender_turn = None
            challenger_turn = None
            
            # Helper to construct TurnResponse
            for adv in ["defender", "challenger"]:
                if adv in turns_dict:
                    t_row = turns_dict[adv]
                    summary = t_row["summary"]
                    dis_json = t_row["disagreements_json"]
                    import json
                    disagreements = json.loads(dis_json) if dis_json else []
                    
                    # Fetch proposals proposed by this adversary in this round
                    cur.execute(
                        "SELECT proposal_id, adversary, text, severity, groundedness_citation, reasoning FROM proposals WHERE session_id = ? AND round_number = ? AND adversary = ?;",
                        (session_id, round_num, adv)
                    )
                    prop_rows = cur.fetchall()
                    new_proposals = []
                    for pr in prop_rows:
                        p = Proposal(
                            id=pr["proposal_id"],
                            adversary=pr["adversary"],
                            text=pr["text"],
                            severity=pr["severity"],
                            groundednessCitation=pr["groundedness_citation"],
                            reasoning=pr["reasoning"]
                        )
                        new_proposals.append(p)
                        all_proposals[p.id] = p
                        
                    # Fetch scores evaluated by this adversary in this round (opponent scores)
                    cur.execute(
                        "SELECT proposal_id, verdict, reasoning, modification FROM scores WHERE session_id = ? AND round_number = ? AND scorer = ?;",
                        (session_id, round_num, adv)
                    )
                    score_rows = cur.fetchall()
                    opponent_scores = [
                        OpponentScore(
                            proposal_id=sr["proposal_id"],
                            verdict=sr["verdict"],
                            reasoning=sr["reasoning"],
                            modification=sr["modification"]
                        ) for sr in score_rows
                    ]
                    
                    t_resp = TurnResponse(
                        summary=summary,
                        opponent_scores=opponent_scores,
                        new_proposals=new_proposals,
                        disagreements=disagreements
                    )
                    if adv == "defender":
                        defender_turn = t_resp
                    else:
                        challenger_turn = t_resp
                        
            # Reconstruct scores_this_round from table
            cur.execute("SELECT scorer, verdict, proposal_id FROM scores WHERE session_id = ? AND round_number = ?;", (session_id, round_num))
            round_score_rows = cur.fetchall()
            
            # Recompute round scores using scoring engine rules to reconstruct
            # (or we can just calculate them locally since engine rules are fixed)
            from .scoring import score_proposal
            
            defender_gain = 0.0
            challenger_gain = 0.0
            
            for sr in round_score_rows:
                scorer = sr["scorer"]
                verdict = sr["verdict"]
                pid = sr["proposal_id"]
                # We need the proposal to score it
                # If proposal is not in our cache yet, fetch it
                if pid not in all_proposals:
                    cur.execute("SELECT proposal_id, adversary, text, severity, groundedness_citation, reasoning FROM proposals WHERE proposal_id = ?;", (pid,))
                    p_row = cur.fetchone()
                    if p_row:
                        all_proposals[pid] = Proposal(
                            id=p_row["proposal_id"],
                            adversary=p_row["adversary"],
                            text=p_row["text"],
                            severity=p_row["severity"],
                            groundednessCitation=p_row["groundedness_citation"],
                            reasoning=p_row["reasoning"]
                        )
                p = all_proposals.get(pid)
                if p:
                    gained = score_proposal(p, verdict)
                    if scorer == "defender":
                        challenger_gain += gained
                    else:
                        defender_gain += gained
                        
            rounds_list.append(Round(
                number=round_num,
                defender_turn=defender_turn,
                challenger_turn=challenger_turn,
                working_prompt_after=wp_after,
                scores_this_round={"defender": defender_gain, "challenger": challenger_gain}
            ))
            
        return {
            "session_id": session_id,
            "prompt": session["prompt"],
            "corpus": session["corpus"],
            "status": session["status"],
            "winner": session["winner"],
            "termination_reason": session["termination_reason"],
            "final_prompt": session["final_prompt"],
            "questions_mode": session.get("questions_mode", "off"),
            "rounds": rounds_list,
            "proposals_by_id": all_proposals
        }
    finally:
        conn.close()

def update_session_questions_mode(session_id: str, questions_mode: str):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE sessions SET questions_mode = ? WHERE session_id = ?;",
                (questions_mode, session_id)
            )
    finally:
        conn.close()

def save_question(session_id: str, round_number: int, adversary: str, question_id: str, q: Any):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO question_answers (
                    question_id, session_id, round_number, adversary,
                    question, why_it_matters, recommended_default, default_reasoning
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(question_id) DO NOTHING;
                """,
                (
                    question_id, session_id, round_number, adversary,
                    q.question, q.why_it_matters, q.recommended_default, q.default_reasoning
                )
            )
    finally:
        conn.close()

def save_answer(question_id: str, answer: str, source: str):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                UPDATE question_answers
                SET answer = ?, source = ?, answered_at = CURRENT_TIMESTAMP
                WHERE question_id = ?;
                """,
                (answer, source, question_id)
            )
    finally:
        conn.close()

def get_pending_questions(session_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM question_answers
            WHERE session_id = ? AND answer IS NULL
            ORDER BY question_id ASC;
            """,
            (session_id,)
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

def get_pending_questions_for_turn(session_id: str, round_number: int, adversary: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM question_answers
            WHERE session_id = ? AND round_number = ? AND adversary = ? AND answer IS NULL
            ORDER BY question_id ASC;
            """,
            (session_id, round_number, adversary)
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

def get_all_question_answers(session_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM question_answers
            WHERE session_id = ? AND answer IS NOT NULL
            ORDER BY round_number ASC, question_id ASC;
            """,
            (session_id,)
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
