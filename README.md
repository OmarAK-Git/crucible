# Crucible

Crucible is an adversarial prompt-hardening engine designed to optimize Antigravity prompts against a codebase corpus through structured debate between LLM adversaries.

For details on the design, architecture, and phased implementation schedule, please see [CRUCIBLE_SPEC.md](CRUCIBLE_SPEC.md).

## Phase 5 — Tumbler→Crucible Pipeline (V1 Complete)

This repository currently implements **Phase 5 (Tumbler→Crucible Pipeline)**. The engine is fully wired with Tumbler to receive verified PASS codebases via a one-way file-based handoff, allowing users to type and debate their feature-addition prompts directly against a pre-built clean codebase.

### Key Features
- **Tumbler→Crucible Pipeline:** Receives clean codebase handoffs from Tumbler (`~/.crucible/incoming/<session_id>.json`). The incoming list displays on the Crucible home page, letting the user enter a prompt and start a debate session. Consumed files are moved to `~/.crucible/consumed/`.
- **Human-in-the-Loop Questions:** Allows adversaries to pause the debate to ask fundamental clarifying questions. Questions Mode radio buttons on the frontend control whether the orchestrator pauses for manual input (Mode OFF) or auto-answers using recommended defaults (Mode ON).
- **Scope-at-Purpose Evaluation:** Personas evaluate prompt changes against the core application purpose to prevent scope creep, flagging violations as critical severity.
- **Sequential Turn Orchestration:** Round 1 runs in parallel. Rounds 2 through 5 run sequentially, alternating Defender and Challenger turns.
- **Deterministic Scoring Engine:** Evaluates each model's proposal based on severity (Critical = 10, Important = 5, Minor = 2), groundedness (1.0 vs 0.2), and opponent acceptance verdict (Accept = 1.0, Modify = 0.6, Reject = 0.0).
- **Proposals Merging:** Merges accepted and modified proposals monotonically as refinements appended to the working prompt.
- **Multi-Factor Termination:** Terminates the debate when either:
  1. No new proposals are made and all disagreements are resolved.
  2. The net score delta between rounds converges.
  3. A hard cap of 5 rounds is reached.
- **Winner-Writes-Final Synthesis:** The adversary with the highest cumulative score (or Claude as tiebreaker) writes the final synthesized prompt.
- **SSE Event Streaming:** Live-streams debate events (turn boundaries, round summaries, proposal updates, scores, and completion) directly to the frontend.
- **SQLite Persistence & Resumption:** Persists sessions, rounds, turns, proposals, and scores to a local SQLite database (`~/.crucible/crucible.db`). Supports seamless resumption of active debates after server restarts.

### Setup and Running

1. Install backend dependencies in your python virtual environment:
   ```bash
   pip install -r requirements.txt
   ```
2. Configure API keys in a `.env` file:
   ```env
   ANTHROPIC_API_KEY="your-anthropic-key"
   OPENAI_API_KEY="your-openai-key"
   ```
3. Run the backend uvicorn server:
   ```bash
   python -m uvicorn backend.main:app --port 8000
   ```
4. Open `frontend/index.html` in a web browser to run and view debate sessions.
