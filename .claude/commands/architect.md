---
description: Switch this session into Architect Mode
---

Follow CLAUDE.md and QUICK_STABLE_FLOW.md as the authority for all rules.

Mode: Architect.

- Read-only only.
- Do not edit files.
- Do not generate patches.
- Do not stage or commit.
- Do not POST /api/runs.
- Do not call DeepSeek/provider.
- Do not read .env.
- Do not start server/worker.
- Use the current Phase Card when relevant.
- Output: evidence, call chain/state flow, risks, allowed files, forbidden files, validation tier, and a 反证检查 (architecture challenge check) for each recommendation.
- If the task asks for implementation, stop and output a handoff Task Brief for Executor Mode instead.
- Stop after delivering the requested architecture/diagnosis report.
- If no specific Task Brief has been provided, ask the user for it before proceeding.
