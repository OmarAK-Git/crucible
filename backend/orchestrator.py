import asyncio
import uuid
import json
import logging
from typing import Optional, Dict, Any, List
from . import db
from .schemas import Round, TurnResponse, Proposal, OpponentScore, DebateResult, Question, QuestionAnswer
from .adversary import run_round_1_adversaries, build_adversary_prompt
from .personas import DEFENDER_PERSONA, CHALLENGER_PERSONA
from .claude_adapter import call_claude_adversary
from .gpt_adapter import call_gpt_adversary
from .scoring import score_round, score_proposal
from .termination import should_terminate
from .synthesis import write_final_prompt
from .merge import apply_accepted_proposals

logger = logging.getLogger(__name__)

def get_round_n_system_prompt(role: str, persona: str, round_number: int) -> str:
    """
    Assembles the system prompt for rounds 2+ by appending the sequential debate turn instructions.
    """
    from .personas import ANTI_SYCOPHANCY
    base_system = f"Role: {role}\n\n{persona}\n\n{ANTI_SYCOPHANCY}"
    
    sequential_instructions = f"""
PHASE: ROUND {round_number} — SEQUENTIAL DEBATE
You have seen your opponent's previous-turn proposals. Your job is to:

SCORE each opponent proposal as one of:
- "accept": this is a real improvement, grounded in the corpus, and should be folded into the working prompt as-is.
- "modify": this has merit but needs adjustment. Provide the adjustment.
- "reject": this is ungrounded, cosmetic, redundant, or harmful. Explain why.

Do NOT silently drop any opponent proposal. Score every one.

PROPOSE new changes against the current working prompt. Same rules as round 1: grounded citations only, severity reflects impact, no general best practices.
Do NOT re-propose anything that has already been accepted into the working prompt. Read the working prompt carefully before proposing.

If you have NO new proposals AND zero open disagreements with the opponent, return an empty proposals array and an empty disagreements array. The orchestrator uses this signal to terminate.

Your output must be a valid JSON object matching this schema:
{{
  "summary": "Brief summary of your turn",
  "opponent_scores": [
    {{
      "proposal_id": "ID of opponent proposal being evaluated",
      "verdict": "accept" | "modify" | "reject",
      "reasoning": "Reasoning for the score",
      "modification": "Modification string (only required if verdict is modify)"
    }}
  ],
  "new_proposals": [
    {{
      "text": "Proposed change to the prompt",
      "severity": "critical" | "important" | "minor",
      "groundednessCitation": "File path, function, or line number in the corpus, or 'original spec'",
      "reasoning": "Reasoning for the change"
    }}
  ],
  "disagreements": [
    "Any addressed disagreements or counter-arguments resolving previous modify/reject feedback on your own proposals"
  ],
  "questions_for_human": [
    {{
      "question": "The question in plain English",
      "why_it_matters": "Why it matters (one sentence)",
      "recommended_default": "Your recommended default answer",
      "default_reasoning": "The reasoning behind that default"
    }}
  ]
}}
Output ONLY the JSON object — no markdown fences.

QUESTIONS FOR THE HUMAN
If a feature request is too vague to evaluate confidently, you MAY ask the human a question — but only if you cannot make a reasonable judgment from the corpus alone. Every question you ask MUST come with:

The question in plain English.
Why it matters (one sentence).
Your recommended default answer (what you would assume if the human doesn't respond).
The reasoning behind that default.

Use questions sparingly. Most ambiguity should be flagged as a proposal, not escalated to the human. Reserve questions for cases where the ambiguity is so fundamental that no proposal can address it without a human decision.
Output questions in the questions_for_human field of your response.
"""
    return f"{base_system}\n\n{sequential_instructions}"

async def emit_event(event_queue: Optional[asyncio.Queue], event_type: str, data: dict):
    if event_queue:
        await event_queue.put((event_type, data))

async def handle_turn_questions(
    session_id: str,
    round_number: int,
    adversary: str,
    questions: List[Question],
    questions_mode: str,
    event_queue: Optional[asyncio.Queue]
):
    if not questions:
        return
        
    for idx, q in enumerate(questions, 1):
        q_id = f"Q-R{round_number}-{adversary}-{idx}"
        db.save_question(session_id, round_number, adversary, q_id, q)
        
    if questions_mode == "on":
        auto_answers = []
        for idx, q in enumerate(questions, 1):
            q_id = f"Q-R{round_number}-{adversary}-{idx}"
            db.save_answer(q_id, q.recommended_default, "auto_default")
            auto_answers.append({
                "question_id": q_id,
                "question": q.question,
                "answer": q.recommended_default,
                "source": "auto_default"
            })
        await emit_event(event_queue, "questions_auto_answered", {
            "session_id": session_id,
            "round_number": round_number,
            "adversary": adversary,
            "answers": auto_answers
        })
    else:
        pending_qs = []
        for idx, q in enumerate(questions, 1):
            q_id = f"Q-R{round_number}-{adversary}-{idx}"
            pending_qs.append({
                "question_id": q_id,
                "question": q.question,
                "why_it_matters": q.why_it_matters,
                "recommended_default": q.recommended_default,
                "default_reasoning": q.default_reasoning
            })
        await emit_event(event_queue, "questions_pending", {
            "session_id": session_id,
            "round_number": round_number,
            "adversary": adversary,
            "questions": pending_qs
        })
        event = active_sessions.setdefault(session_id, asyncio.Event())
        event.clear()
        logger.info(f"Session {session_id} paused waiting for answers.")
        await event.wait()
        logger.info(f"Session {session_id} resumed.")

active_sessions: Dict[str, asyncio.Event] = {}

async def run_debate(
    prompt: str,
    corpus: str,
    session_id: Optional[str] = None,
    event_queue: Optional[asyncio.Queue] = None,
    questions_mode: str = "off"
) -> DebateResult:
    """
    Runs the full Crucible Phase 3 debate loop.
    Supports resuming an interrupted session if session_id is provided and status is 'running'.
    """
    is_resume = False
    state = None
    
    if session_id:
        state = db.load_session_state(session_id)
        # DEV NOTE: In V1 (single-user, single-process), any session with status="running" at startup
        # is dead by definition. We load its state and resume from the last completed turn.
        if state and state["status"] == "running":
            is_resume = True
            questions_mode = state.get("questions_mode", questions_mode)
            logger.info(f"Resuming session {session_id} with questions_mode {questions_mode}")
            
    if not is_resume:
        session_id = uuid.uuid4().hex
        db.create_session(session_id, prompt, corpus, questions_mode=questions_mode)
        logger.info(f"Started fresh debate session {session_id} with questions_mode {questions_mode}")
    else:
        db.update_session_questions_mode(session_id, questions_mode)

    # Initialize the event for this session
    active_sessions[session_id] = asyncio.Event()

    # Check if there are any pending questions in the database from prior rounds
    pending_qs = db.get_pending_questions(session_id)
    if pending_qs:
        logger.info(f"Session {session_id} has pending questions upon resumption. Entering pause.")
        await emit_event(event_queue, "questions_pending", {
            "session_id": session_id,
            "round_number": pending_qs[0]["round_number"],
            "adversary": pending_qs[0]["adversary"],
            "questions": [
                {
                    "question_id": q["question_id"],
                    "question": q["question"],
                    "why_it_matters": q["why_it_matters"],
                    "recommended_default": q["recommended_default"],
                    "default_reasoning": q["default_reasoning"]
                }
                for q in pending_qs
            ]
        })
        active_sessions[session_id].clear()
        await active_sessions[session_id].wait()
        logger.info(f"Session {session_id} resumed after answering pending questions from restart.")
        
    # Get file count and characters for corpus built notification
    # Simple lines count / stats
    file_count = corpus.count("=== file:") + corpus.count("<evidence path=")
    total_chars = len(corpus)
    
    await emit_event(event_queue, "session_started", {"session_id": session_id, "prompt": prompt})
    await emit_event(event_queue, "corpus_built", {"file_count": file_count, "total_chars": total_chars})
    
    rounds: List[Round] = []
    proposals_by_id: Dict[str, Proposal] = {}
    working_prompt = prompt
    def_cumulative = 0.0
    chal_cumulative = 0.0
    
    start_round = 1
    resume_turn = None # "defender" or "challenger"
    
    if is_resume and state:
        rounds = state["rounds"]
        proposals_by_id = state["proposals_by_id"]
        
        # Calculate cumulative scores up to here
        for r in rounds:
            def_cumulative += r.scores_this_round.get("defender", 0.0)
            chal_cumulative += r.scores_this_round.get("challenger", 0.0)
            
        if rounds:
            last_r = rounds[-1]
            working_prompt = last_r.working_prompt_after
            
            if not last_r.defender_turn:
                # Defender has not finished turn in this round
                start_round = last_r.number
                resume_turn = "defender"
            elif last_r.defender_turn and not last_r.challenger_turn:
                # Defender finished turn, Challenger is next in this round
                start_round = last_r.number
                resume_turn = "challenger"
            else:
                # Both finished, start next round with Defender
                start_round = last_r.number + 1
                resume_turn = "defender"
        else:
            start_round = 1
            resume_turn = None
            
    # ROUND 1 - Parallel independent analysis
    if start_round == 1:
        await emit_event(event_queue, "round_started", {"round_number": 1})
        
        # Defender
        await emit_event(event_queue, "turn_started", {"round_number": 1, "adversary": "defender"})
        # Challenger
        await emit_event(event_queue, "turn_started", {"round_number": 1, "adversary": "challenger"})
        
        # Run concurrently
        round_1_results = await run_round_1_adversaries(prompt, corpus)
        
        # Map Defender
        def_raw = round_1_results["defender_response"]["proposals"]
        defender_proposals = []
        for i, p_dict in enumerate(def_raw, 1):
            p = Proposal(
                id=f"D-R1-P{i}",
                adversary="defender",
                text=p_dict["text"],
                severity=p_dict["severity"],
                groundednessCitation=p_dict["groundednessCitation"],
                reasoning=p_dict["reasoning"]
            )
            defender_proposals.append(p)
            proposals_by_id[p.id] = p
            
        def_qs_raw = round_1_results["defender_response"].get("questions_for_human", [])
        def_qs = [Question(**q) for q in def_qs_raw]
        
        def_turn = TurnResponse(
            summary="Round 1 initial proposals",
            opponent_scores=[],
            new_proposals=defender_proposals,
            disagreements=[],
            questions_for_human=def_qs
        )
        
        # Map Challenger
        chal_raw = round_1_results["challenger_response"]["proposals"]
        challenger_proposals = []
        for i, p_dict in enumerate(chal_raw, 1):
            p = Proposal(
                id=f"C-R1-P{i}",
                adversary="challenger",
                text=p_dict["text"],
                severity=p_dict["severity"],
                groundednessCitation=p_dict["groundednessCitation"],
                reasoning=p_dict["reasoning"]
            )
            challenger_proposals.append(p)
            proposals_by_id[p.id] = p
            
        chal_qs_raw = round_1_results["challenger_response"].get("questions_for_human", [])
        chal_qs = [Question(**q) for q in chal_qs_raw]
        
        chal_turn = TurnResponse(
            summary="Round 1 initial proposals",
            opponent_scores=[],
            new_proposals=challenger_proposals,
            disagreements=[],
            questions_for_human=chal_qs
        )
        
        # Merge all round 1 proposals as the initial working prompt
        all_r1 = [p.model_dump() for p in defender_proposals + challenger_proposals]
        working_prompt = apply_accepted_proposals(prompt, all_r1)
        db.save_round(session_id, 1, working_prompt)
        
        # Save Round 1 components in SQLite
        db.save_turn(session_id, 1, "defender", def_turn.summary, def_turn.disagreements)
        db.save_proposals(session_id, 1, "defender", defender_proposals)
        
        db.save_turn(session_id, 1, "challenger", chal_turn.summary, chal_turn.disagreements)
        db.save_proposals(session_id, 1, "challenger", challenger_proposals)
        
        # Handle Round 1 questions if any
        if def_qs:
            await handle_turn_questions(session_id, 1, "defender", def_qs, questions_mode, event_queue)
        if chal_qs:
            await handle_turn_questions(session_id, 1, "challenger", chal_qs, questions_mode, event_queue)
            
        r1_obj = Round(
            number=1,
            defender_turn=def_turn,
            challenger_turn=chal_turn,
            working_prompt_after=working_prompt,
            scores_this_round={"defender": 0.0, "challenger": 0.0}
        )
        rounds.append(r1_obj)
        
        await emit_event(event_queue, "turn_completed", {"round_number": 1, "adversary": "defender", "response": def_turn.model_dump()})
        await emit_event(event_queue, "turn_completed", {"round_number": 1, "adversary": "challenger", "response": chal_turn.model_dump()})
        await emit_event(event_queue, "round_scored", {
            "round_number": 1,
            "defender_score": 0.0,
            "challenger_score": 0.0,
            "cumulative": {"defender": def_cumulative, "challenger": chal_cumulative}
        })
        
        start_round = 2
        resume_turn = "defender"

    # ROUNDS 2-5: Sequential Debate
    for round_number in range(start_round, 6):
        # Determine if we need to load or create this round object
        if len(rounds) < round_number:
            current_round = Round(
                number=round_number,
                defender_turn=None,
                challenger_turn=None,
                working_prompt_after=working_prompt,
                scores_this_round={"defender": 0.0, "challenger": 0.0}
            )
            rounds.append(current_round)
        else:
            current_round = rounds[round_number - 1]
            
        # Ensure round record exists in SQLite to satisfy foreign key constraints
        db.save_round(session_id, round_number, working_prompt)
        
        await emit_event(event_queue, "round_started", {"round_number": round_number})
        
        # 1. DEFENDER TURN
        if resume_turn == "defender" or not current_round.defender_turn:
            resume_turn = None # reset resume flag
            await emit_event(event_queue, "turn_started", {"round_number": round_number, "adversary": "defender"})
            
            # Opponent previous proposals = Challenger's proposals from the previous round (round_number - 1)
            prev_round = rounds[round_number - 2]
            opp_proposals = prev_round.challenger_turn.new_proposals
            
            opp_content = "Opponent's previous-turn proposals to score:\n"
            for p in opp_proposals:
                opp_content += (
                    f"- ID: {p.id}\n"
                    f"  Text: {p.text}\n"
                    f"  Citation: {p.groundednessCitation}\n"
                    f"  Severity: {p.severity}\n"
                    f"  Reasoning: {p.reasoning}\n\n"
                )
                
            # Load prior Q&As for this session
            # DEV NOTE: Unbounded question context accumulation, V2 to add a cap.
            prior_qas = db.get_all_question_answers(session_id)
            qa_context = ""
            if prior_qas:
                qa_context = "Prior Clarifications (Answers provided by the user/system):\n"
                for qa in prior_qas:
                    if qa["answer"] is not None:
                        qa_context += (
                            f"- Question: {qa['question']}\n"
                            f"  Answer: {qa['answer']} (Source: {qa['source']})\n"
                        )
                qa_context += "\n"

            user_content = (
                f"Original Prompt:\n{prompt}\n\n"
                f"Working Prompt:\n{working_prompt}\n\n"
                f"{qa_context}"
                f"Codebase Corpus:\n{corpus}\n\n"
                f"{opp_content}"
            )
            
            system_prompt = get_round_n_system_prompt("Defender", DEFENDER_PERSONA, round_number)
            
            # Call Claude (Defender)
            defender_turn_resp: TurnResponse = await call_claude_adversary(
                system_prompt, user_content, "", response_model=TurnResponse
            )
            
            # Assign IDs to Defender's new proposals
            for i, p in enumerate(defender_turn_resp.new_proposals, 1):
                p.id = f"D-R{round_number}-P{i}"
                p.adversary = "defender"
                proposals_by_id[p.id] = p
                
            current_round.defender_turn = defender_turn_resp
            
            # Save to SQLite
            db.save_turn(session_id, round_number, "defender", defender_turn_resp.summary, defender_turn_resp.disagreements)
            db.save_proposals(session_id, round_number, "defender", defender_turn_resp.new_proposals)
            for sc in defender_turn_resp.opponent_scores:
                if sc.proposal_id in proposals_by_id:
                    db.save_score(sc.proposal_id, session_id, round_number, "defender", sc.verdict, sc.reasoning, sc.modification)
                else:
                    logger.warning(f"Defender tried to score non-existent proposal ID {sc.proposal_id}")
                
            # Handle turn questions if any
            if defender_turn_resp.questions_for_human:
                await handle_turn_questions(
                    session_id, round_number, "defender",
                    defender_turn_resp.questions_for_human,
                    questions_mode, event_queue
                )

            # Update working prompt immediately using evaluated opponent proposals
            accepted_this_turn = []
            for sc in defender_turn_resp.opponent_scores:
                if sc.verdict == "accept":
                    orig = proposals_by_id.get(sc.proposal_id)
                    if orig:
                        accepted_this_turn.append({"text": orig.text, "severity": orig.severity})
                elif sc.verdict == "modify":
                    orig = proposals_by_id.get(sc.proposal_id)
                    if orig and sc.modification:
                        accepted_this_turn.append({"text": sc.modification, "severity": orig.severity})
            
            if accepted_this_turn:
                # Merge newly accepted into working_prompt
                # We need all accepted across all history to group and format properly
                all_accepted = await reconstruct_all_accepted(session_id, proposals_by_id)
                working_prompt = apply_accepted_proposals(prompt, all_accepted)
                db.save_round(session_id, round_number, working_prompt)
                current_round.working_prompt_after = working_prompt
                
            await emit_event(event_queue, "turn_completed", {
                "round_number": round_number, "adversary": "defender", "response": defender_turn_resp.model_dump()
            })
            
        # 2. CHALLENGER TURN
        if resume_turn == "challenger" or not current_round.challenger_turn:
            resume_turn = None # reset resume flag
            await emit_event(event_queue, "turn_started", {"round_number": round_number, "adversary": "challenger"})
            
            # Opponent previous proposals = Defender's proposals from the current round
            opp_proposals = current_round.defender_turn.new_proposals
            
            opp_content = "Opponent's previous-turn proposals to score:\n"
            for p in opp_proposals:
                opp_content += (
                    f"- ID: {p.id}\n"
                    f"  Text: {p.text}\n"
                    f"  Citation: {p.groundednessCitation}\n"
                    f"  Severity: {p.severity}\n"
                    f"  Reasoning: {p.reasoning}\n\n"
                )
                
            # Load prior Q&As for this session
            # DEV NOTE: Unbounded question context accumulation, V2 to add a cap.
            prior_qas = db.get_all_question_answers(session_id)
            qa_context = ""
            if prior_qas:
                qa_context = "Prior Clarifications (Answers provided by the user/system):\n"
                for qa in prior_qas:
                    if qa["answer"] is not None:
                        qa_context += (
                            f"- Question: {qa['question']}\n"
                            f"  Answer: {qa['answer']} (Source: {qa['source']})\n"
                        )
                qa_context += "\n"

            user_content = (
                f"Original Prompt:\n{prompt}\n\n"
                f"Working Prompt:\n{working_prompt}\n\n"
                f"{qa_context}"
                f"Codebase Corpus:\n{corpus}\n\n"
                f"{opp_content}"
            )
            
            system_prompt = get_round_n_system_prompt("Challenger", CHALLENGER_PERSONA, round_number)
            
            # Call GPT (Challenger)
            challenger_turn_resp: TurnResponse = await call_gpt_adversary(
                system_prompt, user_content, "", response_model=TurnResponse
            )
            
            # Assign IDs to Challenger's new proposals
            for i, p in enumerate(challenger_turn_resp.new_proposals, 1):
                p.id = f"C-R{round_number}-P{i}"
                p.adversary = "challenger"
                proposals_by_id[p.id] = p
                
            current_round.challenger_turn = challenger_turn_resp
            
            # Save to SQLite
            db.save_turn(session_id, round_number, "challenger", challenger_turn_resp.summary, challenger_turn_resp.disagreements)
            db.save_proposals(session_id, round_number, "challenger", challenger_turn_resp.new_proposals)
            for sc in challenger_turn_resp.opponent_scores:
                if sc.proposal_id in proposals_by_id:
                    db.save_score(sc.proposal_id, session_id, round_number, "challenger", sc.verdict, sc.reasoning, sc.modification)
                else:
                    logger.warning(f"Challenger tried to score non-existent proposal ID {sc.proposal_id}")
                
            # Handle turn questions if any
            if challenger_turn_resp.questions_for_human:
                await handle_turn_questions(
                    session_id, round_number, "challenger",
                    challenger_turn_resp.questions_for_human,
                    questions_mode, event_queue
                )

            # Update working prompt immediately using evaluated opponent proposals
            accepted_this_turn = []
            for sc in challenger_turn_resp.opponent_scores:
                if sc.verdict == "accept":
                    orig = proposals_by_id.get(sc.proposal_id)
                    if orig:
                        accepted_this_turn.append({"text": orig.text, "severity": orig.severity})
                elif sc.verdict == "modify":
                    orig = proposals_by_id.get(sc.proposal_id)
                    if orig and sc.modification:
                        accepted_this_turn.append({"text": sc.modification, "severity": orig.severity})
            
            if accepted_this_turn:
                # Merge newly accepted into working_prompt
                all_accepted = await reconstruct_all_accepted(session_id, proposals_by_id)
                working_prompt = apply_accepted_proposals(prompt, all_accepted)
                db.save_round(session_id, round_number, working_prompt)
                current_round.working_prompt_after = working_prompt
                
            await emit_event(event_queue, "turn_completed", {
                "round_number": round_number, "adversary": "challenger", "response": challenger_turn_resp.model_dump()
            })
            
        # Compute scoring for this round
        scores_gained = score_round(current_round, proposals_by_id)
        current_round.scores_this_round = scores_gained
        
        def_cumulative += scores_gained["defender"]
        chal_cumulative += scores_gained["challenger"]
        
        await emit_event(event_queue, "round_scored", {
            "round_number": round_number,
            "defender_score": scores_gained["defender"],
            "challenger_score": scores_gained["challenger"],
            "cumulative": {"defender": def_cumulative, "challenger": chal_cumulative}
        })
        
        # Check termination conditions
        terminated, reason = should_terminate(rounds)
        if terminated and reason:
            await emit_event(event_queue, "termination", {"reason": reason})
            logger.info(f"Debate session {session_id} terminated: {reason}")
            db.update_session(session_id, "completed", winner=None, termination_reason=reason)
            break
            
    # FINAL SYNTHESIS
    # 1. Determine winner
    if def_cumulative > chal_cumulative:
        winner = "defender"
    elif chal_cumulative > def_cumulative:
        winner = "challenger"
    else:
        winner = "tied"
        
    await emit_event(event_queue, "synthesis_started", {"winner": winner})
    
    # 2. Write final prompt
    final_prompt = await write_final_prompt(prompt, corpus, rounds, winner)
    
    # 3. Save completed session details
    db.update_session(
        session_id,
        "completed",
        winner=winner,
        termination_reason=state["termination_reason"] if is_resume and state and state["termination_reason"] else "Loop completed",
        final_prompt=final_prompt
    )
    
    await emit_event(event_queue, "synthesis_completed", {"final_prompt": final_prompt})
    
    return DebateResult(
        rounds=rounds,
        final_prompt=final_prompt,
        winner=winner,
        termination_reason="Loop completed",
        defender_score=def_cumulative,
        challenger_score=chal_cumulative
    )

async def reconstruct_all_accepted(session_id: str, proposals_by_id: dict) -> List[Dict[str, Any]]:
    """
    Helper to reconstruct all currently accepted/modified proposals for merge.
    Queries the SQLite scores table.
    """
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT proposal_id, verdict, modification FROM scores WHERE session_id = ? AND verdict IN ('accept', 'modify');",
            (session_id,)
        )
        rows = cur.fetchall()
        
        accepted_list = []
        for row in rows:
            pid = row[0]
            verdict = row[1]
            modification = row[2]
            
            orig = proposals_by_id.get(pid)
            if not orig:
                # Query original proposal text/severity
                cur.execute("SELECT text, severity FROM proposals WHERE proposal_id = ?;", (pid,))
                p_row = cur.fetchone()
                if p_row:
                    text = p_row[0]
                    severity = p_row[1]
                else:
                    continue
            else:
                text = orig.text
                severity = orig.severity
                
            final_text = modification if verdict == "modify" and modification else text
            accepted_list.append({
                "text": final_text,
                "severity": severity
            })
        return accepted_list
    finally:
        conn.close()
