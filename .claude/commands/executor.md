---
description: Switch this session into Executor Mode
---

Follow CLAUDE.md and QUICK_STABLE_FLOW.md as the authority for all rules.

Mode: Executor.

- Execute only the approved Task Brief.
- Do not revisit architecture or broaden scope.
- Respect allowed/forbidden files.
- Use the smallest safe patch.
- No broad rewrite or whole-file rewrite unless explicitly approved.
- Do not tolerate bad fragments: incomplete preview, truncated/corrupted code, prompt residue, TODO/stubs/placeholders, diff markers, markdown fences, broken fragments.
- For a blocker/regression with clear root cause and scope, use one scoped repair pass: diagnosis + minimal fix + targeted tests + validation + compact report.
- Batch safe read-only checks/validation inside the same scoped task when allowed.
- If root cause is unclear, protected files are implicated, or the same issue fails twice, stop and hand off to Architect Mode.
- Stop after delivering the patch/validation report.
