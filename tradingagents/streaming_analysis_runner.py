"""Streaming DeepSeek Analysis Runner (Phase 1C: streaming progress runner).

Bypasses ``TradingAgentsGraph.propagate()`` and drives
``graph.graph.stream()`` directly instead -- the same pattern ``cli/main.py``
already uses to show live progress -- so real, non-fabricated per-agent
``agent_completed`` events can be emitted as the graph actually executes,
rather than the single opaque "graph_propagate" black box
``tradingagents.deepseek_analysis_runner.DeepSeekAnalysisRunner`` produces.

``Propagator.get_graph_args()`` hardcodes ``stream_mode="values"``
(``tradingagents/graph/propagation.py``), so each streamed chunk is the full
accumulated state after that step, not a ``{node_name: delta}`` mapping.
There is no field in a chunk naming which node just ran, so
``tradingagents.stream_progress.detect_newly_completed_agents`` diffs
consecutive chunks by tracked state-field truthiness -- the only reliable
"completed" signal. There is no reliable "started" signal at all (confirmed
by reading ``cli/main.py``'s own progress-display heuristics), so this
runner never emits ``agent_started`` -- doing so would be a fabrication.

Explicitly OUT OF SCOPE for Phase 1C -- do not extend this module to claim
otherwise: **no checkpoint-aware resume**. This runner does not attach a
checkpointer, does not inject a LangGraph ``thread_id``, and cannot resume
an interrupted run. Checkpoint-aware resume is deferred to a future phase,
once Phase 2's Web API defines the actual resume/cancel interaction it
would need to serve (see the Phase 1C plan for the full rationale).

Because this bypasses ``propagate()``, it also bypasses the two memory-log
*write* paths fused into ``propagate()``/``_run_graph()``
(``TradingAgentsGraph._resolve_pending_entries`` and
``TradingMemoryLog.store_decision``) -- this runner never writes to
``~/.tradingagents/memory/trading_memory.md``. It still calls
``graph.memory_log.get_past_context(...)`` (a pure read) and
``graph.resolve_instrument_context(...)`` to give agents the same context
quality a real ``propagate()`` call would, without any write side effect.

``tradingagents.deepseek_analysis_runner.DeepSeekAnalysisRunner`` is
untouched by this module and remains the default choice for callers that
just want the final artifacts with no progress visibility.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.deepseek_analysis_runner import DeepSeekAnalysisRunnerError
from tradingagents.report_field_parsing import extract_report_tree_fields
from tradingagents.run_artifact_writer import (
    append_run_event,
    write_analysis_manifest,
    write_run_status,
)
from tradingagents.run_contract import (
    ANALYSIS_MANIFEST_FILENAME,
    RUNS_DIRNAME,
    STATUS_FILENAME,
    AgentId,
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
from tradingagents.stream_progress import detect_newly_completed_agents

__all__ = ["DeepSeekAnalysisRunnerError", "StreamingDeepSeekAnalysisRunner"]

_STAGE_QUEUED = "queued"
_STAGE_ANALYSIS_STARTED = "analysis_started"
_STAGE_GRAPH_PROPAGATE = "graph_propagate"
_STAGE_REPORT_WRITE = "report_write"
_STAGE_MANIFEST_WRITE = "manifest_write"
_STAGE_COMPLETED = "completed"
_STAGE_FAILED = "failed"


class _StreamingGraphLike(Protocol):
    config: dict[str, Any]
    propagator: Any  # .create_initial_state(...), .get_graph_args(...)
    graph: Any  # .stream(init_state, **args) -> Iterator[dict]
    memory_log: Any  # .get_past_context(ticker) -> str

    def resolve_instrument_context(self, ticker: str, asset_type: str) -> str: ...

    def save_reports(
        self, final_state: dict, ticker: str, save_path: Path | str | None = None
    ) -> Path: ...


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _is_resumable_queued_placeholder(run_dir: Path) -> bool:
    """True iff ``run_dir`` holds only the minimal queued placeholder a
    caller (e.g. ``api/main.py``'s ``POST /api/runs``) writes synchronously
    before handing off to this runner -- ``status.json`` parses and says
    ``queued``, and no ``analysis_manifest.json`` exists yet (which would
    mean this is actually a real, already-completed historical run).
    Anything else is NOT resumable and must be treated as a genuine
    collision, never silently taken over.
    """
    if (run_dir / ANALYSIS_MANIFEST_FILENAME).exists():
        return False
    status_path = run_dir / STATUS_FILENAME
    if not status_path.is_file():
        return False
    try:
        status = RunStatus.model_validate_json(status_path.read_text(encoding="utf-8"))
    except (ValidationError, OSError):
        return False
    return status.analysis_status is AnalysisStatus.QUEUED


class StreamingDeepSeekAnalysisRunner:
    """Drives ``graph.graph.stream()`` directly to surface real agent-completed progress."""

    def __init__(
        self,
        graph: _StreamingGraphLike,
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
        agent_id: AgentId | None = None,
        latest_error: str | None = None,
        error: str | None = None,
    ) -> RunStatus:
        """Append one event and immediately write the status snapshot after it."""
        ts = self._clock()
        append_run_event(
            run_dir,
            RunEvent(
                event_type=event_type,
                run_id=run_id,
                created_at=ts,
                agent_id=agent_id,
                error=error,
            ),
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
        self,
        ticker: str,
        analysis_date: str,
        *,
        asset_type: str = "stock",
        run_id: str | None = None,
        allow_existing_queued_run: bool = False,
    ) -> tuple[AnalysisManifest, RunStatus]:
        created_at = self._clock()
        if run_id is None:
            run_id = f"{safe_ticker_component(ticker)}_{created_at:%Y%m%d_%H%M%S}"
        run_dir = self.runs_dir / run_id

        if run_dir.exists():
            if not (allow_existing_queued_run and _is_resumable_queued_placeholder(run_dir)):
                raise FileExistsError(
                    f"run_dir {run_dir} already exists; refusing to reuse it for a new run"
                )
            # Valid hand-off from a caller-written queued placeholder (e.g.
            # api/main.py's POST /api/runs, which writes this synchronously
            # so a client polling status immediately after the response
            # never sees a 404). Skip re-emitting run_queued -- the caller
            # already did.
        else:
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

        agents: dict[AgentId, AgentStatus] = {}
        try:
            self._emit(
                run_dir,
                run_id,
                EventType.GRAPH_PROPAGATE_STARTED,
                current_stage=_STAGE_GRAPH_PROPAGATE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents=dict(agents),
            )

            # Read-only context, matching _run_graph()'s own quality bar --
            # deliberately NOT calling _resolve_pending_entries() (has a
            # write side effect) or store_decision() (unconditional write).
            past_context = self.graph.memory_log.get_past_context(ticker)
            instrument_context = self.graph.resolve_instrument_context(ticker, asset_type)
            init_state = self.graph.propagator.create_initial_state(
                ticker,
                analysis_date,
                asset_type=asset_type,
                past_context=past_context,
                instrument_context=instrument_context,
            )
            args = self.graph.propagator.get_graph_args()

            previous_state: dict = init_state
            final_state: dict = init_state
            for chunk in self.graph.graph.stream(init_state, **args):
                for completed_agent in detect_newly_completed_agents(previous_state, chunk):
                    agents[completed_agent] = AgentStatus.COMPLETED
                    self._emit(
                        run_dir,
                        run_id,
                        EventType.AGENT_COMPLETED,
                        current_stage=_STAGE_GRAPH_PROPAGATE,
                        analysis_status=AnalysisStatus.RUNNING,
                        overall_status=OverallStatus.ANALYSIS_RUNNING,
                        agents=dict(agents),
                        agent_id=completed_agent,
                    )
                previous_state = chunk
                final_state = chunk

            self._emit(
                run_dir,
                run_id,
                EventType.GRAPH_PROPAGATE_COMPLETED,
                current_stage=_STAGE_GRAPH_PROPAGATE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents=dict(agents),
            )

            self._emit(
                run_dir,
                run_id,
                EventType.REPORT_WRITE_STARTED,
                current_stage=_STAGE_REPORT_WRITE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents=dict(agents),
            )
            self.graph.save_reports(final_state, ticker, save_path=run_dir)
            self._emit(
                run_dir,
                run_id,
                EventType.REPORT_WRITE_COMPLETED,
                current_stage=_STAGE_REPORT_WRITE,
                analysis_status=AnalysisStatus.RUNNING,
                overall_status=OverallStatus.ANALYSIS_RUNNING,
                agents=dict(agents),
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
                agents=dict(agents),
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
                agents=dict(agents),
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
            # Unlike the blocking DeepSeekAnalysisRunner (which has zero
            # mid-flight visibility and always records {} on failure), this
            # runner reports whichever agents genuinely completed before the
            # failure -- real observed progress, not a guess.
            self._emit(
                run_dir,
                run_id,
                EventType.ANALYSIS_FAILED,
                current_stage=_STAGE_FAILED,
                analysis_status=AnalysisStatus.FAILED,
                overall_status=OverallStatus.ANALYSIS_FAILED,
                agents=dict(agents),
                latest_error=str(exc),
                error=str(exc),
            )
            raise
