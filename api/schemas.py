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

from datetime import datetime

from pydantic import BaseModel, field_validator

from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
from tradingagents.run_contract import (
    AnalysisDate,
    AnalysisStatus,
    OverallStatus,
    StrategyProfile,
    Ticker,
)
from tradingagents.scanners.unified import AnalysisPurpose, SelectionSystem


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
    updated_at: datetime | None = None


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
    # Phase 2F placeholder for a future Pradeep-style knowledge base /
    # scanner: pure passthrough to status/manifest, never read by
    # _build_graph or any analysis logic. Defaults to null ("manual
    # analysis, no profile").
    strategy_profile: StrategyProfile = None
    # Level-2 boundary enrichment (G5/R3): selection-origin thread. The
    # browser already holds exact E02 selection provenance; these fields
    # carry it end-to-end so the backend never has to infer origin from a
    # ticker (unsafe: one company can carry multiple system selections).
    system_scope: SelectionSystem | None = None
    selection_record_ref: dict | None = None
    analysis_purpose: AnalysisPurpose | None = None

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

    @field_validator("quick_model", "deep_model")
    @classmethod
    def _validate_model_not_empty(cls, value: str | None) -> str | None:
        """Phase 7C: reject empty or whitespace-only model override strings.
        None is allowed (meaning 'use default'). Non-empty free-form strings
        are allowed — no provider/model allowlist exists yet."""
        if value is not None and not value.strip():
            raise ValueError("model override must not be empty or whitespace-only")
        return value


class StartAnalysisResponse(BaseModel):
    """Response of ``POST /api/runs`` -- an acceptance receipt, not a status read.

    ``analysis_status`` is always ``queued`` here: it reflects what was just
    written to disk synchronously (see ``api/main.py``), not a fresh read of
    ``status.json``.
    """

    run_id: str
    analysis_status: AnalysisStatus
    strategy_profile: StrategyProfile = None


class DamagedRun(BaseModel):
    """One damaged run entry in ``GET /api/runs`` (Phase 5B).

    A damaged run is a directory under ``runs_dir`` that fails to parse as a
    valid run — either ``status.json`` is corrupt JSON or schema-invalid.
    Directories without ``status.json`` are NOT reported as damaged; they are
    simply skipped (they may not be run directories at all).
    """

    run_id: str
    reason: str
    message: str


class RunListResponse(BaseModel):
    """Wrapper response for ``GET /api/runs`` (Phase 5B).

    ``runs`` contains successfully parsed runs. ``damaged_runs`` contains
    directories that were identified as run directories but whose
    ``status.json`` could not be parsed — the API surfaces them rather than
    silently dropping them, so operators can detect and repair corruption.
    """

    runs: list[RunSummary]
    damaged_runs: list[DamagedRun] = []
