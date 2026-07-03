"""DeepSeek Analysis Runner (Phase 1A).

Calls an already-constructed ``TradingAgentsGraph``-like object's
``propagate()``/``save_reports()`` and turns the result into the Phase
0A/0B structured run artifacts (``analysis_manifest.json``, ``status.json``,
``events.jsonl``) alongside the markdown report tree.

Does not construct ``TradingAgentsGraph`` itself, does not read interactive
CLI config, and does not import anything under ``cli/`` -- callers build the
graph however they like (see the module-level example below) and hand it to
``DeepSeekAnalysisRunner``. This keeps the class trivially testable with a
duck-typed fake graph and avoids coupling a headless runner to interactive
CLI dependencies.

``propagate()`` is a single blocking call with no per-agent visibility from
outside (see ``tradingagents.graph.trading_graph``), so this runner only
produces the coarse-grained event/status sequence blueprint section 7.4
describes as its MVP bar: ``run_queued -> analysis_started ->
analysis_completed`` (or ``analysis_failed``). Per-agent events require
bypassing ``propagate()`` in favor of the graph's internal streaming API,
which is a Phase 1B concern, not this module's.

Field extraction (draft_rating/trader_action/stop_loss/position_sizing/
research_manager_recommendation/time_horizon) reuses
``tradingagents.report_field_parsing`` -- the same regex-based extraction
``tradingagents.legacy_importer`` uses for historical reports, because the
graph does not preserve structured Pydantic objects
(``TraderProposal``/``ResearchPlan``/``PortfolioDecision``) past their
markdown rendering. That is a real gap in the current graph, not a design
choice made here; fixing it would mean touching
``tradingagents/agents/utils/structured.py`` and the manager/trader node
factories, which is out of Phase 1A's "don't touch the main pipeline" scope.

Example (not exercised by tests -- requires real API credentials)::

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.deepseek_analysis_runner import DeepSeekAnalysisRunner

    config = DEFAULT_CONFIG.copy()
    graph = TradingAgentsGraph(config=config, debug=False)
    runner = DeepSeekAnalysisRunner(graph)
    manifest, status = runner.run("AAPL", "2026-07-03")
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.report_field_parsing import extract_report_tree_fields
from tradingagents.run_artifact_writer import (
    append_run_event,
    write_analysis_manifest,
    write_run_status,
)
from tradingagents.run_contract import (
    RUNS_DIRNAME,
    AgentStatus,
    AnalysisManifest,
    AnalysisStatus,
    EventType,
    OverallStatus,
    ReviewStatus,
    RunEvent,
    RunStatus,
    derive_overall_status,
)


class DeepSeekAnalysisRunnerError(ValueError):
    """Raised when the runner can't proceed (bad config, run_dir collision)."""


class _GraphLike(Protocol):
    config: dict[str, Any]

    def propagate(
        self, company_name: str, trade_date: str, asset_type: str = "stock"
    ) -> tuple[dict, str]: ...

    def save_reports(
        self, final_state: dict, ticker: str, save_path: Path | str | None = None
    ) -> Path: ...


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


class DeepSeekAnalysisRunner:
    """Wraps a ``TradingAgentsGraph``-like object to produce structured run artifacts."""

    def __init__(
        self,
        graph: _GraphLike,
        *,
        runs_dir: Path | str | None = None,
        clock: Callable[[], datetime] = _default_clock,
    ):
        for key in ("llm_provider", "quick_think_llm", "deep_think_llm"):
            if not graph.config.get(key):
                raise DeepSeekAnalysisRunnerError(
                    f"graph.config[{key!r}] must be a non-empty string for a live run "
                    "(only legacy-imported manifests may leave provider/model fields null)"
                )
        self.graph = graph
        self.runs_dir = Path(runs_dir) if runs_dir is not None else Path(RUNS_DIRNAME)
        self._clock = clock

    def run(
        self, ticker: str, analysis_date: str, *, asset_type: str = "stock"
    ) -> tuple[AnalysisManifest, RunStatus]:
        started_at = self._clock()
        run_id = f"{safe_ticker_component(ticker)}_{started_at:%Y%m%d_%H%M%S}"
        run_dir = self.runs_dir / run_id
        if run_dir.exists():
            raise FileExistsError(
                f"run_dir {run_dir} already exists; refusing to reuse it for a new run"
            )

        append_run_event(
            run_dir, RunEvent(event_type=EventType.RUN_QUEUED, run_id=run_id, created_at=started_at)
        )
        write_run_status(
            run_dir,
            RunStatus(
                run_id=run_id,
                analysis_status=AnalysisStatus.QUEUED,
                review_status=ReviewStatus.NOT_REQUESTED,
                overall_status=OverallStatus.ANALYSIS_QUEUED,
                agents={},
                updated_at=started_at,
            ),
        )

        append_run_event(
            run_dir,
            RunEvent(event_type=EventType.ANALYSIS_STARTED, run_id=run_id, created_at=started_at),
        )
        write_run_status(
            run_dir,
            RunStatus(
                run_id=run_id,
                analysis_status=AnalysisStatus.RUNNING,
                review_status=ReviewStatus.NOT_REQUESTED,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents={},
                updated_at=started_at,
            ),
        )

        try:
            final_state, _decision = self.graph.propagate(
                ticker, analysis_date, asset_type=asset_type
            )

            # Everything from here on is also part of the "did this run
            # succeed" question: a failure in save_reports()/manifest
            # construction/writing is just as much a failed run as
            # propagate() itself raising, and must be recorded the same
            # way. Markdown already written by save_reports() at the point
            # of failure is left exactly as-is -- no rollback.
            self.graph.save_reports(final_state, ticker, save_path=run_dir)
            fields = extract_report_tree_fields(run_dir)
            selected_agents = [
                agent_id
                for agent_id, s in fields.agent_statuses.items()
                if s is AgentStatus.COMPLETED
            ]

            manifest = AnalysisManifest(
                run_id=run_id,
                ticker=ticker,
                analysis_date=analysis_date,
                created_at=started_at,
                analysis_status=AnalysisStatus.COMPLETED,
                analysis_provider=self.graph.config["llm_provider"],
                quick_model=self.graph.config["quick_think_llm"],
                deep_model=self.graph.config["deep_think_llm"],
                selected_agents=selected_agents,
                draft_rating=fields.draft_rating,
                trader_action=fields.trader_action,
                research_manager_recommendation=fields.research_manager_recommendation,
                stop_loss=fields.stop_loss,
                position_sizing=fields.position_sizing,
                time_horizon=fields.time_horizon,
                position_context_available=False,
                data_quality_assessment="not_available",
                data_quality_flags=fields.data_quality_flags,
            )
            write_analysis_manifest(run_dir, manifest, overwrite=False)

            completed_at = self._clock()
            review_status = ReviewStatus.NOT_REQUESTED
            status = RunStatus(
                run_id=run_id,
                analysis_status=AnalysisStatus.COMPLETED,
                review_status=review_status,
                overall_status=derive_overall_status(AnalysisStatus.COMPLETED, review_status),
                agents=fields.agent_statuses,
                updated_at=completed_at,
            )
            write_run_status(run_dir, status)

            append_run_event(
                run_dir,
                RunEvent(
                    event_type=EventType.ANALYSIS_COMPLETED, run_id=run_id, created_at=completed_at
                ),
            )

            return manifest, status
        except Exception as exc:
            failed_at = self._clock()
            write_run_status(
                run_dir,
                RunStatus(
                    run_id=run_id,
                    analysis_status=AnalysisStatus.FAILED,
                    review_status=ReviewStatus.NOT_REQUESTED,
                    overall_status=OverallStatus.ANALYSIS_FAILED,
                    agents={},
                    latest_error=str(exc),
                    updated_at=failed_at,
                ),
            )
            append_run_event(
                run_dir,
                RunEvent(
                    event_type=EventType.ANALYSIS_FAILED,
                    run_id=run_id,
                    created_at=failed_at,
                    error=str(exc),
                ),
            )
            raise
