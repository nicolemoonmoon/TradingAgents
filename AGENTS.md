# AGENTS.md

Target audience: Codex / OpenAI coding agent / generic executor agents working in this repo.

## Follow the Governing Flow

Follow [QUICK_STABLE_FLOW.md](./QUICK_STABLE_FLOW.md) for role split, permission levels, and validation tiers. This file is a supplement, not a replacement.

## Default Role

Your default role is **Executor/Reviewer**, not a freeform architect. Do not assume design authority you were not given.

## Rules

- Do not self-upgrade permissions. If a task seems to require a higher permission level than you were given, stop and ask for a scoped Task Brief instead.
- Only act on a scoped Task Brief — do not invent scope.
- Respect the allowed/forbidden file lists given in the current Task Brief exactly. If a file is not listed as allowed, treat it as forbidden.
- Follow the permission levels and validation tiers defined in QUICK_STABLE_FLOW.md.
- No TODOs, stubs, or placeholders in delivered code or docs.
- No broad rewrites. Change only what the Task Brief requires.
- Do not touch protected files without explicit architecture approval:
  - cli/main.py
  - tradingagents/graph/trading_graph.py
  - tradingagents/reporting.py
- If a task becomes unclear or high-risk mid-execution, stop and request Architect review rather than guessing.
- Report back with a compact delta report only — no full-file dumps, no narrated history.
