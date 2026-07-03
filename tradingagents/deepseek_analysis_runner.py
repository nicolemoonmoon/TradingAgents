"""DeepSeek Analysis Runner (Phase 1A/1B).

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
outside (see ``tradingagents.graph.trading_graph``). Phase 1B adds coarse,
*runner-level* stage events/status around this runner's own call
boundaries -- before/after ``propagate()``, before/after ``save_reports()``,
before/after building+writing the manifest -- so ``events.jsonl``/
``status.json`` aren't silent for the minutes a real analysis can take.
These are not agent-level events: this runner has no visibility into which
agent the graph is currently executing, and does not pretend otherwise
(``status.json``'s ``agents`` field stays ``{}`` until the run actually
completes, at which point it reflects real, file-presence-derived per-agent
completion). True per-agent progress would require bypassing ``propagate()``
in favor of the graph's internal streaming API, which stays out of scope
here per Phase 1B's explicit constraint.

Field extraction (draft_rating/trader_action/stop_loss/position_sizing/
research_manager_recommendation/time_horizon) reuses
``tradingagents.report_field_parsing`` -- the same regex-based extraction
``tradingagents.legacy_importer`` uses for historical reports, because the
graph does not preserve structured Pydantic objects
(``TraderProposal``/``ResearchPlan``/``PortfolioDecision``) past their
markdown rendering. That is a real gap in the current graph, not a design
choice made here; fixing it would mean touching
``tradingagents/agents/utils/structured.py`` and the manager/trader node
factories, which stays out of scope. When that extraction can't recover a
field (e.g. the Portfolio Manager's structured-output call fell back to
free text with no parseable rating), the field stays ``None`` and
``report_field_parsing`` records why in ``data_quality_flags`` -- this
runner never guesses a value to fill the gap.

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

# current_stage vocabulary (Phase 1B). Free-form str in the RunStatus
# contract (no enum in run_contract.py) -- this vocabulary is specific to
# this runner's own stages, not a cross-module contract.
_STAGE_QUEUED = "queued"
_STAGE_ANALYSIS_STARTED = "analysis_started"
_STAGE_GRAPH_PROPAGATE = "graph_propagate"
_STAGE_REPORT_WRITE = "report_write"
_STAGE_MANIFEST_WRITE = "manifest_write"
_STAGE_COMPLETED = "completed"
_STAGE_FAILED = "failed"


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

    def _emit(
        self,
        run_dir: Path,
        run_id: str,
        event_type: EventType,
        *,
        current_stage: str,
        analysis_status: AnalysisStatus,
        overall_status: OverallStatus,
        agents: dict,
        latest_error: str | None = None,
        error: str | None = None,
    ) -> RunStatus:
        """Append one event and immediately write the status snapshot after it.

        Every event gets a paired status write reflecting the state right
        after that event -- simple, predictable, and gives a real
        ``updated_at`` heartbeat at every stage boundary (Phase 1B decision
        B). Returns the written ``RunStatus`` so the final call's result can
        be returned directly from ``run()``.
        """
        ts = self._clock()
        append_run_event(
            run_dir, RunEvent(event_type=event_type, run_id=run_id, created_at=ts, error=error)
        )
        status = RunStatus(
            run_id=run_id,
            analysis_status=analysis_status,
            review_status=ReviewStatus.NOT_REQUESTED,
            overall_status=overall_status,
            current_stage=current_stage,
            agents=agents,
            latest_error=latest_error,
            updated_at=ts,
        )
        write_run_status(run_dir, status)
        return status

    def run(
        self, ticker: str, analysis_date: str, *, asset_type: str = "stock"
    ) -> tuple[AnalysisManifest, RunStatus]:
        created_at = self._clock()
        run_id = f"{safe_ticker_component(ticker)}_{created_at:%Y%m%d_%H%M%S}"
        run_dir = self.runs_dir / run_id
        if run_dir.exists():
            raise FileExistsError(
                f"run_dir {run_dir} already exists; refusing to reuse it for a new run"
            )

        self._emit(
            run_dir,
            run_id,
            EventType.RUN_QUEUED,
            current_stage=_STAGE_QUEUED,
            analysis_status=AnalysisStatus.QUEUED,
            overall_status=OverallStatus.ANALYSIS_QUEUED,
            agents={},
        )
        self._emit(
            run_dir,
            run_id,
            EventType.ANALYSIS_STARTED,
            current_stage=_STAGE_ANALYSIS_STARTED,
            analysis_status=AnalysisStatus.RUNNING,
            overall_status=OverallStatus.ANALYSIS_RUNNING,
            agents={},
        )

        try:
            # Everything from here on is also part of the "did this run
            # succeed" question: a failure in save_reports()/manifest
            # construction/writing is just as much a failed run as
            # propagate() itself raising, and must be recorded the same
            # way. Markdown already written by save_reports() at the point
            # of failure is left exactly as-is -- no rollback.
            self._emit(
                run_dir,
                run_id,
                EventType.GRAPH_PROPAGATE_STARTED,
                current_stage=_STAGE_GRAPH_PROPAGATE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents={},
            )
            final_state, _decision = self.graph.propagate(
                ticker, analysis_date, asset_type=asset_type
            )
            self._emit(
                run_dir,
                run_id,
                EventType.GRAPH_PROPAGATE_COMPLETED,
                current_stage=_STAGE_GRAPH_PROPAGATE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents={},
            )

            self._emit(
                run_dir,
                run_id,
                EventType.REPORT_WRITE_STARTED,
                current_stage=_STAGE_REPORT_WRITE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents={},
            )
            self.graph.save_reports(final_state, ticker, save_path=run_dir)
            self._emit(
                run_dir,
                run_id,
                EventType.REPORT_WRITE_COMPLETED,
                current_stage=_STAGE_REPORT_WRITE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents={},
            )

            fields = extract_report_tree_fields(run_dir)
            selected_agents = [
                agent_id
                for agent_id, s in fields.agent_statuses.items()
                if s is AgentStatus.COMPLETED
            ]

            self._emit(
                run_dir,
                run_id,
                EventType.MANIFEST_WRITE_STARTED,
                current_stage=_STAGE_MANIFEST_WRITE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents={},
            )
            manifest = AnalysisManifest(
                run_id=run_id,
                ticker=ticker,
                analysis_date=analysis_date,
                created_at=created_at,
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
            self._emit(
                run_dir,
                run_id,
                EventType.MANIFEST_WRITE_COMPLETED,
                current_stage=_STAGE_MANIFEST_WRITE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents={},
            )

            status = self._emit(
                run_dir,
                run_id,
                EventType.ANALYSIS_COMPLETED,
                current_stage=_STAGE_COMPLETED,
                analysis_status=AnalysisStatus.COMPLETED,
                overall_status=derive_overall_status(
                    AnalysisStatus.COMPLETED, ReviewStatus.NOT_REQUESTED
                ),
                agents=fields.agent_statuses,
            )

            return manifest, status
        except Exception as exc:
            self._emit(
                run_dir,
                run_id,
                EventType.ANALYSIS_FAILED,
                current_stage=_STAGE_FAILED,
                analysis_status=AnalysisStatus.FAILED,
                overall_status=OverallStatus.ANALYSIS_FAILED,
                agents={},
                latest_error=str(exc),
                error=str(exc),
            )
            raise
