# CLAUDE.md

Target audience: Claude Code, working in this repo.

This file supplements [QUICK_STABLE_FLOW.md](./QUICK_STABLE_FLOW.md), which defines the full role split, permission levels, and validation tiers. Read that file first.

## Declare a Mode at Task Start

Every task must begin by declaring exactly one mode:

- **Architect Mode**
- **Executor Mode**
- **Reviewer Mode**

### Architect Mode

- Read-only.
- No edits, no patch, no commit.
- Output: evidence / call chain / state flow / root cause (or explicit uncertainty) / allowed files / forbidden files / validation tier.
- Include a 反证检查 (counter-evidence check) for every recommendation:
  - What would make this recommendation wrong?
  - What evidence is missing?
  - Which alternative is second-best?
  - Why not choose the second-best now?

### Executor Mode

- Only execute the approved Task Brief.
- No architecture drift.
- No broad rewrite.
- No TODOs, stubs, or placeholders.
- Validation is required before reporting done.
- Compact report only.

### Reviewer Mode

- Read-only final gate / second opinion.
- No fixing.

## Terminal Mismatch Rule

If the task does not match the current declared mode, stop and output a recommended handoff Task Brief instead of proceeding.

## Stop Condition Rule

Every task must stop after delivering the requested report/patch/validation. Do not continue into unrequested work.

## Context Hygiene

Use only:
- Persistent Rules Summary
- Current Phase Card
- Current Task Brief

Do not pull in full chat history.

## Default Forbidden Actions

- POST /api/runs
- DeepSeek/provider call
- .env read
- server/worker start
- auto mode
- allow-all edits
- protected files (see QUICK_STABLE_FLOW.md)
- broad rewrite
- whole-file rewrite
