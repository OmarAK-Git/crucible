# Crucible V1 — Specification

## What Crucible Is

Crucible is an adversarial prompt-hardening engine. It takes a feature-request prompt and a codebase corpus, runs two LLM adversaries through a structured debate where the only success metric is the prompt getting measurably stronger against that codebase, and returns a hardened Antigravity prompt.

Crucible's design thesis, distilled:

> Crossfire and ralph-ng both build adversarial review loops. Crossfire has real anti-sycophancy incentives (penalize agreement with flawed reasoning, reward refusing to be polite). Ralph-ng has rigorous defect-resolution. What neither has is a loop that optimizes for the artifact getting better. Their debates resolve individual positions. Crucible's loop optimizes the input→output delta as the only metric. A round that doesn't improve the prompt is a failed round, not a neutral one.

## What Crucible Is Not

- Not a code generator. Crucible produces a prompt, never code.
- Not a replacement for Tumbler. Tumbler reviews completed code. Crucible hardens prompts that will produce future code.
- Not a debate referee. The two adversaries are not negotiating to reach consensus; they are competing to improve the artifact.
- Not multi-tenant or cloud-hosted. Local-only, single-user, same threat model as Tumbler V1.

## Vibecoding Rules for This Build

These are non-negotiable. Same rules Tumbler V1 was built under.

1. **Phases are atomic.** Do not pull features forward from later phases. Each phase has an explicit "Build" list and an explicit "Do NOT build" list. Both are binding.
2. **Gate verification at the end of every phase.** A phase is not complete until its gate criteria are independently verified. No moving to the next phase until the current gate passes.
3. **Tumbler reviews itself.** After each phase, run Tumbler against Crucible's repo. If Tumbler returns FIX, fix the findings (or write a disagreement note) before moving on.
4. **No spec drift mid-phase.** If a decision needs to change, update this spec doc before changing code. The spec is the source of truth.
5. **Plain-language explanations over jargon.** Same as Tumbler — error messages, log lines, and UI strings explain what's happening in human terms.
6. **Process over shortcuts.** Enforced guarantees over convention. If the system relies on the user remembering something, it's a bug.

## Stack Decisions

- **Backend:** Python 3.11+ / FastAPI. Matches Tumbler's stack.
- **Frontend:** Plain HTML/JS/CSS, no framework. Matches Tumbler.
- **LLM providers:** Anthropic Claude (Defender role) + OpenAI GPT (Challenger role). Vertex AI Gemini is NOT used in Crucible — Crucible reviews Gemini's output, so the reviewers must be different models.
- **Persistence:** SQLite for session state. Same pattern as ralph-ng. Sessions survive restarts.
- **No Docker, no auth, no TLS** — V1 is single-user localhost, same as Tumbler.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (HTML/JS)                                          │
│  - Folder upload                                             │
│  - Prompt input box                                          │
│  - "Run Crucible" button                                     │
│  - Live debate viewer (SSE)                                  │
│  - Final hardened prompt display + copy button               │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI Backend                                             │
│                                                              │
│  ┌─────────────────────┐    ┌─────────────────────┐          │
│  │  Corpus Builder     │    │  Session Manager    │          │
│  │  (same as Tumbler)  │    │  (SQLite)           │          │
│  └─────────────────────┘    └─────────────────────┘          │
│           │                            │                     │
│           ▼                            ▼                     │
│  ┌─────────────────────────────────────────────────┐         │
│  │  Crucible Orchestrator                          │         │
│  │  - Round 1: parallel proposals                  │         │
│  │  - Rounds 2-N: sequential debate                │         │
│  │  - Deterministic scoring per round              │         │
│  │  - Multi-factor termination                     │         │
│  │  - Winner-writes-final synthesis                │         │
│  └─────────────────────────────────────────────────┘         │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────────┐    ┌─────────────────────┐          │
│  │  Claude Adapter     │    │  GPT Adapter        │          │
│  │  (Defender role)    │    │  (Challenger role)  │          │
│  └─────────────────────┘    └─────────────────────┘          │
└──────────────────────────────────────────────────────────────┘
```

## The Adversaries

### Claude — The Defender (Implementer Advocate)

Claude reads the prompt as if it's about to be handed to Antigravity. Its job is to find places where the prompt is vague, ungrounded, or unexecutable.

Attack surface:
- Ambiguity an executor would have to guess about
- File paths that don't exist in the corpus
- Acceptance criteria that aren't checkable
- Missing concrete instructions where the prompt hand-waves
- Conflicts between the prompt and existing code patterns

Persona (borrowed from Crossfire's Dr. Chen, adapted):

> You are the Implementer Advocate. You read every prompt as the agent who has to execute it. Your professional reputation depends on shipping things that work, not on being agreeable. You ruthlessly call out vagueness, hand-waving, and instructions that cannot actually be carried out as written.

### GPT — The Challenger (Red Team)

GPT reads the prompt assuming it's wrong somewhere. Its job is to find places where the prompt is unsafe, underspecified, or misaligned with what the codebase actually is.

Attack surface:
- Edge cases the prompt doesn't address
- Conflicts with the application's purpose (scope creep at the purpose level)
- Failure modes an executor might create
- Misalignment with existing architectural patterns
- Security or correctness regressions

Persona (borrowed from Crossfire's Dr. Rivera, adapted):

> You are the Red Team. You read every prompt as a plan about to ship and assume it is wrong somewhere. You consider it a professional failure if a bad prompt produces broken code because you were too polite to flag the flaw. Your reputation depends on thoroughness, not collegiality.

### Anti-Sycophancy Protocol (Shared)

This is the same protocol Crossfire used, applied to both adversaries every turn:

```
INDEPENDENCE PROTOCOL:
- Formulate your own analysis BEFORE considering your peer's position.
- Agreement must be EARNED through evidence, not assumed as default.
- If you change your position, state the SPECIFIC argument that changed your mind.
  Vague acknowledgments like "you raise a good point" are prohibited.
- You will NOT be penalized for disagreement. You WILL be penalized for agreeing
  with flawed reasoning.
- Treat your peer's output with professional skepticism. Critique the reasoning
  directly, not the person.
```

## The Loop

### Round 1: Parallel Independent Analysis

Both adversaries receive the prompt and corpus simultaneously. Neither sees the other's work. Each produces:

- A list of proposed changes to the prompt
- Severity tag per change: `critical` / `important` / `minor`
- Groundedness citation per change: which file/function/line in the corpus or original spec the change is anchored to
- Reasoning for each change

Round 1 has no scoring step — there's nothing yet to score.

### Rounds 2 through N: Sequential Debate

After round 1, the orchestrator merges proposals into a new working prompt (using deterministic merge logic — see Scoring section), then enters sequential turns.

Each turn produces:

1. **Score the previous turn's proposals.** For each proposal the opponent made in the previous turn, the current adversary marks it as:
   - `accept` — the change is a net improvement, grounded, and survives in the working prompt
   - `reject` — the change is ungrounded, cosmetic, or harmful, and is removed from the working prompt
   - `modify` — the change has merit but needs adjustment; propose the adjustment
2. **Propose new changes** against the current working prompt with severity tags and groundedness citations
3. **Disagreements left open** from the previous turn — must be addressed, not silently dropped

### Termination

A round ends when ANY of these is true:

1. Both adversaries produce zero new proposals AND zero open disagreements remain
2. Net score delta across the last 2 rounds is below threshold (default: 5% of total possible severity-weighted score)
3. Hard cap of 5 rounds reached
4. Critical-severity disagreement count has been zero for 2 consecutive rounds AND important-severity is also zero

The orchestrator emits an SSE event when the loop terminates, naming the reason.

## Scoring

### The Deterministic Rubric

Every proposal a model makes is scored as follows:

```
proposal_score = severity_weight × groundedness_multiplier × acceptance_factor
```

- `severity_weight`: critical=10, important=5, minor=2
- `groundedness_multiplier`: grounded (cites real file/spec)=1.0, ungrounded (general best practice)=0.2
- `acceptance_factor`: accepted by opponent=1.0, modified=0.6, rejected by opponent=0.0

The scoring is applied by the orchestrator (Python code), not by an LLM. Both adversaries are scored against the exact same rubric. Neither adversary's "accept/reject/modify" judgments can score their own proposals — only the opponent's.

### Net Score Delta (Termination Signal)

```
delta_round_N = total_severity_weighted_proposals_in_round_N - total_in_round_N-1
```

If `delta` shrinks below 5% of the maximum possible delta for 2 consecutive rounds, the loop terminates. This catches the "still proposing but nothing landing" failure mode.

### Cumulative Score (Who Writes the Final)

Each adversary accumulates score across all rounds. The adversary with the higher cumulative score at termination writes the final hardened prompt. If tied, Claude writes (deterministic tiebreaker — arbitrary but consistent).

The writer receives:
- The original prompt
- The corpus
- The full debate transcript
- The list of all accepted/modified proposals
- Instructions to fold accepted changes into a coherent final prompt without adding new substance

## Human-in-the-Loop

A radio button in the UI: **Questions Mode**.

- **OFF (default):** If an adversary's turn produces a `questionsForHuman` field, the orchestrator pauses, surfaces the question in the UI, and waits for a response.
- **ON:** Questions still get generated, but the orchestrator auto-selects the adversary's `recommendedDefault` (which must be present alongside any question) and proceeds without pausing. The auto-selection is logged in the transcript so the user can review what was decided.

Every question raised by an adversary MUST include:
- The question in plain English
- Why it matters
- The adversary's recommended default
- The reasoning behind that default

This is borrowed directly from Crossfire's question-debate contract.

## Scope-at-Purpose Evaluation

Both adversaries are instructed in their system prompts:

> The codebase you are reviewing has an *application purpose* and a *historical spec*. The historical spec is context, not a constraint — feature additions by definition extend the spec. However, the application's *purpose* is binding. A feature that changes the application's purpose is out of scope. Flag scope-at-purpose violations as `critical` severity.
>
> Example: Tumbler's purpose is "structured code review with PASS/FIX verdicts." A feature that adds a new verdict category is in scope. A feature that turns Tumbler into a chat assistant is out of scope.

The adversaries determine the application's purpose by reading the README, the spec document if present, and the file structure.

## Phased Build

### Phase 1 — Walking Skeleton

**Goal:** End-to-end stub. Folder upload, prompt entry, one round of one adversary, return the (unchanged) prompt. Proves the plumbing.

**Build:**
- FastAPI backend skeleton with `/api/sessions` (create), `/api/sessions/{id}` (get)
- Folder upload endpoint that calls Tumbler's existing corpus builder (vendor the code; do NOT add Tumbler as a runtime dependency)
- Single Claude API call that takes the prompt and corpus, returns "hello from Claude"
- HTML frontend with upload form and result display

**Do NOT build in Phase 1:**
- Adversarial loop
- Scoring
- GPT integration
- SQLite persistence
- SSE
- Personas
- Anti-sycophancy protocol
- Termination logic
- Human-in-the-loop
- Frontend styling beyond basic readability

**Gate (Phase 1 complete only when ALL pass):**
1. `pytest` green, ≥1 test per endpoint
2. Uploading a folder + prompt returns a 200 with Claude's stub response
3. Tumbler reviewing Phase 1 returns PASS or FIX with only minor findings (no blockers)

### Phase 2 — Adversaries and Personas

**Goal:** Both adversaries running with their personas and the anti-sycophancy protocol, but in parallel-only mode (no debate yet, no scoring). Proves the LLM contracts work.

**Build:**
- GPT API integration (OpenAI adapter, parallel to Claude adapter)
- Persona prompts for Defender (Claude) and Challenger (GPT) — direct port of Crossfire's persona blocks
- Anti-sycophancy protocol injected into every turn
- Structured JSON output contract for both adversaries: proposals with `text`, `severity`, `groundednessCitation`, `reasoning`
- Round 1 parallel execution: both adversaries called concurrently, both outputs collected
- Display both adversaries' raw proposals in the frontend (no merging yet)

**Do NOT build in Phase 2:**
- Sequential rounds
- Scoring
- Termination
- Merging proposals
- SSE (results returned after both adversaries complete)
- Human-in-the-loop
- Final synthesis

**Gate (Phase 2 complete only when ALL pass):**
1. `pytest` green, ≥1 test per adapter, ≥1 test confirming the persona text appears in the prompt sent to the model
2. Uploading a folder + prompt returns proposals from both adversaries, each with valid severity tags and groundedness citations
3. Manual review: Defender finds executability issues, Challenger finds correctness/safety issues (asymmetric attack surfaces working)
4. Tumbler reviewing Phase 2 returns PASS or FIX with only minor findings

### Phase 3 — Sequential Debate and Scoring

**Goal:** The full loop. Round 1 parallel → rounds 2+ sequential → deterministic scoring → multi-factor termination → winner writes final synthesis.

**Build:**
- Sequential turn orchestration (rounds 2 through N)
- Deterministic proposal merging logic (round 1 → working prompt; per-turn → working prompt update)
- Scoring engine implementing the rubric exactly as specified above
- Multi-factor termination logic
- Winner-writes-final synthesis call
- SSE streaming of debate events to the frontend (turn boundaries, proposals, scores, termination reason)
- Frontend debate viewer
- SQLite persistence: sessions, turns, proposals, scores
- Resume-after-restart support

**Do NOT build in Phase 3:**
- Human-in-the-loop (radio button stays disabled in UI)
- Scope-at-purpose evaluation (instructed in prompts but not specially tested)

**Gate (Phase 3 complete only when ALL pass):**
1. `pytest` green, ≥1 test per major component (orchestrator, scoring, termination, merge, synthesis)
2. End-to-end run on a real Tumbler-shaped codebase produces a hardened prompt that is materially different from and stronger than the input prompt
3. Scoring rubric audited: pick 3 proposals from a real run, compute their score manually, verify the engine produces the same number
4. Termination triggers correctly across all 4 conditions in test cases
5. Tumbler reviewing Phase 3 returns PASS or FIX with only minor findings

### Phase 4 — Human-in-the-Loop and Scope Evaluation

**Goal:** Radio-button question handling and explicit scope-at-purpose evaluation.

**Build:**
- Frontend radio button: Questions Mode ON/OFF
- Adversaries' system prompts updated to include the `questionsForHuman` and `recommendedDefault` contract
- Orchestrator: pause-and-wait flow for Questions Mode OFF; auto-select-default flow for Questions Mode ON
- Question/answer events streamed via SSE
- Scope-at-purpose evaluation language added to both adversary system prompts
- Test cases for scope violations (feature requests that change app purpose should produce critical-severity findings)

**Do NOT build in Phase 4:**
- Tumbler→Crucible push pipeline (that's Phase 5)
- Anything else

**Gate (Phase 4 complete only when ALL pass):**
1. `pytest` green
2. Questions Mode OFF: a prompt that triggers a question pauses the run, displays the question, accepts an answer, resumes
3. Questions Mode ON: same prompt auto-selects the default, logs the auto-selection, completes without pausing
4. Scope test: a feature request that turns Tumbler into something it isn't produces a critical-severity finding from at least one adversary
5. Tumbler reviewing Phase 4 returns PASS or FIX with only minor findings

### Phase 5 — Tumbler→Crucible Pipeline

**Goal:** Tumbler can push its corpus + a generated Antigravity prompt directly to Crucible. The standalone upload path still works.

**Build:**
- Tumbler change: when a verdict is produced (PASS or FIX), Tumbler optionally writes a handoff file `~/.crucible/incoming/<session_id>.json` containing the cleaned corpus string and the Antigravity prompt. Gated behind a `--push-to-crucible` flag or UI toggle.
- Crucible change: new endpoint `/api/sessions/from-tumbler` that reads from `~/.crucible/incoming/` and creates a session with that corpus + prompt pre-loaded
- Frontend: list of incoming Tumbler handoffs on Crucible's home page, click to start a Crucible session

**Do NOT build in Phase 5:**
- Bidirectional integration (Crucible does not call back into Tumbler)
- Anything else

**Gate (Phase 5 complete only when ALL pass):**
1. `pytest` green on both Tumbler's and Crucible's added tests
2. Manual end-to-end: run Tumbler against a project, get a FIX verdict with the push toggle on, see the handoff appear in Crucible, click it, run the full Crucible loop, get a hardened prompt
3. Standalone Crucible upload still works (regression test)
4. Tumbler reviewing both repos (Tumbler and Crucible) at this final state returns PASS or FIX with only minor findings

## V2 Backlog

Things deliberately deferred from V1. Do not pull into V1 phases.

- Local LLM provider for adversaries (privacy / offline use)
- Multi-tenant / shared-server hardening
- Crucible reviewing Crucible's own output (Crucible-on-Crucible)
- Direct integration with Antigravity (push hardened prompt directly into Antigravity)
- Cost tracking / token accounting per session
- Replay-from-state for completed sessions
- Configurable scoring weights via UI

## Open Questions Tracked for V1

- **OpenAI API key handling.** Same approach as Tumbler's Vertex credentials: env var, fail fast at startup if missing. Add to `.env.example`.
- **Concurrency.** V1 is single-user, single-session-at-a-time. Reject new sessions while one is running. Concurrency is V2.
- **Cost.** A full Crucible run on a real codebase will use significant tokens (corpus + prompt × multiple turns × two models). Log token usage per turn for visibility, but do not enforce limits in V1.
