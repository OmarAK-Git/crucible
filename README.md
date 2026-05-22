# Crucible

Crucible is an adversarial prompt-hardening engine designed to optimize Antigravity prompts against a codebase corpus through structured debate between LLM adversaries.

For details on the design, architecture, and phased implementation schedule, please see [CRUCIBLE_SPEC.md](CRUCIBLE_SPEC.md).

## Phase 2 — Adversaries and Personas
This repository currently implements Phase 2 (Adversaries and Personas), featuring concurrent execution of both Claude (Defender) and GPT (Challenger) adversaries with distinct personas, an anti-sycophancy protocol, structured JSON schema validation, and a side-by-side frontend dashboard showing the generated proposals.
