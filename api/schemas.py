"""API-presentation-only response models (Phase 2A).

Everything that maps 1:1 to an existing run artifact reuses the real
``tradingagents.run_contract`` models directly (``RunStatus``,
``AnalysisManifest``, ``RunEvent``) as FastAPI response models -- no
duplicate field definitions. ``RunSummary`` is the one genuinely new shape
here: a "list runs" summary row that no single artifact file already
represents, so it lives in the API layer, not in ``run_contract.py``.
"""

from __future__ import annotations

from pydantic import BaseModel

from tradingagents.run_contract import AnalysisStatus, OverallStatus


class RunSummary(BaseModel):
    """One row of ``GET /api/runs``.

    ``ticker``/``analysis_date`` come from ``analysis_manifest.json``, which
    only exists once analysis has completed -- both stay ``None`` for a
    run that's still queued/running/failed before a manifest was ever
    written, per the "never fabricate" rule the rest of this project holds
    to.
    """

    run_id: str
    ticker: str | None = None
    analysis_date: str | None = None
    analysis_status: AnalysisStatus
    overall_status: OverallStatus
