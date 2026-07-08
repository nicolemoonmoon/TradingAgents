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

## Efficiency and Source-Safety Rules

- In Executor Mode, do not request one permission per tiny validation command when safe checks can be grouped.
- For blocker/regression, use one scoped repair pass only after scope/root cause is clear.
- In Architect Mode, if root cause is not clear, do not recommend patching.
- Do not tolerate agent bad habits: incomplete preview, truncated/corrupted code, prompt residue, TODO/stubs/placeholders, diff markers, markdown fences, broken fragments.
- If the edit path produces corrupted/truncated output twice, stop and recommend handoff to read-only diagnosis / unified diff / exact-match patch / architect review.

## Prompt Language Policy

- User ↔ GPT discussion can be Chinese.
- Project execution prompts sent to Claude/Codex should be English by default.
- Reason: reduce token cost, reduce ambiguity, and align with code/file/API terminology.
- Exceptions: Chinese is allowed when the task is about:
  - user-facing Chinese copy
  - translation
  - Chinese documentation
  - Chinese text/content review
  - any task where Chinese wording itself is the object being edited or evaluated
- This policy governs input prompts sent to project agents. It does not change any existing user-facing response-language preference.

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
