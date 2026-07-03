"""API-presentation-only response models (Phase 2A/2B).

Everything that maps 1:1 to an existing run artifact reuses the real
``tradingagents.run_contract`` models directly (``RunStatus``,
``AnalysisManifest``, ``RunEvent``) as FastAPI response models -- no
duplicate field definitions. ``RunSummary``/``StartAnalysisRequest``/
``StartAnalysisResponse`` are the genuinely new shapes here: request/response
concepts no single artifact file already represents, so they live in the
API layer, not in ``run_contract.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
from tradingagents.run_contract import AnalysisDate, AnalysisStatus, OverallStatus, Ticker


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


class StartAnalysisRequest(BaseModel):
    """Body of ``POST /api/runs``.

    ``ticker``/``analysis_date`` reuse ``run_contract``'s own validated
    types -- same path-safety/format rules the rest of the contract already
    enforces, not reinvented here.
    """

    ticker: Ticker
    analysis_date: AnalysisDate
    selected_analysts: list[str] | None = None
    quick_model: str | None = None
    deep_model: str | None = None
    asset_type: str = "stock"

    @field_validator("selected_analysts")
    @classmethod
    def _validate_selected_analysts(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("selected_analysts must not be empty when provided")
        unknown = sorted(set(value) - set(ANALYST_NODE_SPECS))
        if unknown:
            raise ValueError(
                f"unknown analyst key(s): {unknown}; valid keys are "
                f"{sorted(ANALYST_NODE_SPECS)} (the sentiment analyst's key is 'social')"
            )
        return value


class StartAnalysisResponse(BaseModel):
    """Response of ``POST /api/runs`` -- an acceptance receipt, not a status read.

    ``analysis_status`` is always ``queued`` here: it reflects what was just
    written to disk synchronously (see ``api/main.py``), not a fresh read of
    ``status.json``.
    """

    run_id: str
    analysis_status: AnalysisStatus
