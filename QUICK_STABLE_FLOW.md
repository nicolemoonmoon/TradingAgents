# Quick Stable Flow v4.2

## Purpose

A stable, low-maintenance, token-efficient workflow — without lowering quality.

## Core Principles

- High-risk work gets design/read-only diagnosis first; low-risk work gets short, scoped execution.
- Read-only QA steps may be combined; code changes must stay isolated.
- Validation is part of the main workflow, not a cleanup step tacked on afterward.
- Token saving means less rework, less drift, less repeated explanation — not skipping steps.
- No guessing. No blind patching.

## Role Split

- **GPT / User** — product goals, tradeoffs, approval decisions, prompt/Task Brief generation, flow control.
- **Claude Architect** — read-only architecture, root-cause analysis, state-flow tracing, boundary decisions.
- **Claude Executor** — scoped coding/docs/tests, only after an approved Task Brief.
- **Codex / Reviewer** — second opinion, architecture counter-argument (反证), contract/tests/review, final gate.

### Step A — Role Split

The role split above is the confirmed division of responsibility for this workflow. Every terminal/session operates under exactly one of these roles.

### Step B — Permission Matrix

**Level 0 — Read-only safe**
git status, git diff, rg/sed/cat, node --check, git diff --check, safe pytest validation that does not trigger a real POST / DeepSeek call / worker.

**Level 1 — Docs/governance only**
QUICK_STABLE_FLOW.md, AGENTS.md, CLAUDE.md, docs/**

**Level 2 — Tests-only**
tests/** only; no implementation fix.

**Level 3 — Scoped product patch**
Requires: allowed files clear, forbidden files clear, visible diff, validation plan, no protected files touched.

**Level 4 — High-risk / architecture / protected / unclear**
Default: no. Return to Architect/GPT review.

### Must Reject

- "Allow all edits"
- Auto mode
- Broad rewrite
- Whole-file rewrite unless explicitly approved
- Incomplete/corrupted preview
- .env read
- POST /api/runs
- DeepSeek/provider call
- Server/worker start
- Protected files
- A third same-direction blind patch after two failures

### Step C — Terminal / Session Policy

- One role + one step + one stop condition = one terminal/session.
- **Architect terminal**: read-only, no patch, no commit.
- **Executor terminal**: scoped task only, no architecture drift.
- **Reviewer terminal**: read-only review/final gate, no fixing.
- **Terminal mismatch rule**: if the current terminal's role does not match the task type, stop and output a recommended handoff Task Brief.
- A stop condition is required for every terminal task.

### Step D — Repo File Policy

First-batch governance files:
- QUICK_STABLE_FLOW.md
- AGENTS.md
- CLAUDE.md
- docs/phase_cards/phase4.md
- docs/handoffs/phase3.md
- docs/backlog.md

Later only:
- scripts/guards/
- pre-commit / executable checks

## Validation Tiers

- **Tier 0** — read-only audit
- **Tier 1** — small scoped patch
- **Tier 2** — lifecycle/API/backend patch
- **Tier 3** — phase checkpoint

## Two-Failure Stop Rule

If the same issue returns after 2 modification attempts, stop patching immediately and switch to read-only diagnosis / architect review / call-chain evidence gathering.

- This is the global rule for repeated failure on the same issue.
- The bad edit-path fallback (see Efficiency and Source-Safety Rules) is a source-safety application of this same rule: if the same edit path produces corrupted/truncated/incomplete output twice, stop using that edit path.
- Blocker/regression scoped repair (see Efficiency and Source-Safety Rules) is the preferred first repair shape when root cause and scope are clear: diagnosis + minimal fix + targeted tests + validation + compact report.
- If the scoped repair fails twice, or produces bad fragments twice, this Two-Failure Stop Rule applies: stop and switch to read-only diagnosis / unified diff / exact-match patch / architect review.

## Context Hygiene

Every terminal gets only:
- Persistent Rules Summary
- Current Phase Card
- Current Task Brief

No full chat-history dumps.

## Protected Files

- cli/main.py
- tradingagents/graph/trading_graph.py
- tradingagents/reporting.py

## Default Forbidden Actions

- POST /api/runs
- DeepSeek/provider call
- .env read
- server/worker start
- auto mode
- allow-all edits
- broad rewrite
- whole-file rewrite
- commit without explicit approval

## Efficiency and Source-Safety Rules

- If multiple read-only checks, syntax checks, diff checks, unsafe-fragment scans, and targeted validations are safe within the same scoped task, they should be batched into one approval/request instead of one-by-one permission loops.
- Read-only QA may be combined.
- Code changes must still remain isolated to allowed files.
- For blocker/regression bugs, do not patch line-by-line through repeated micro-edits.
- Use one scoped repair pass: diagnosis + minimal fix + targeted tests + validation + compact report.
- The scoped repair must only address the blocker. Do not do cosmetic polish or unrelated cleanup.
- Do not tolerate agent bad habits: incomplete preview, truncated/corrupted code, prompt residue, TODO/stubs/placeholders, diff markers, markdown fences, broken fragments.
- If bad fragments appear more than once, stop using that edit path and switch to read-only diagnosis, unified diff, exact-match patch, or architect review.
- This rule saves token by reducing rework, not by skipping validation.

## Prompt Language Policy

- User ↔ GPT discussion can be Chinese.
- Prompts sent to Claude/Codex for project execution should be English by default.
- Reason: reduce token cost, reduce ambiguity, and align with code/file/API terminology.
- Exceptions: Chinese is allowed when the task is about:
  - user-facing Chinese copy
  - translation
  - Chinese documentation
  - Chinese text/content review
  - any task where Chinese wording itself is the object being edited or evaluated
- This policy governs input prompts sent to project agents. It does not change any existing user-facing response-language preference.

## Required Report Format

```
Step result:
Files changed:
Scope confirmation:
Validation:
Risks:
Next recommended action:
```
