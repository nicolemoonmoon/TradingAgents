"""Run artifact contract for the web blueprint (Phase 0A).

Defines the JSON contract for a run's on-disk artifacts under ``runs/{run_id}/``:
``analysis_manifest.json``, ``status.json``, and ``events.jsonl`` records, per
docs/TradingAgents_Web_Claude_Execution_Blueprint.md section 4.

This module is pure schema/contract: no filesystem I/O, and no import of
``tradingagents.reporting``, ``tradingagents.graph``, ``cli``, or any LLM
client. Building an ``AnalysisManifest``/``RunStatus`` from a real graph
``final_state`` (or from legacy markdown reports) is Phase 0B/1A's job, not
this module's.

``ReviewManifestStub`` is a deliberately minimal placeholder for the
``reviews/{review_id}/`` artifact family; Phase 3 (Claude Final Review) will
define the actual decision payload. Do not add review/decision fields here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from tradingagents.agents.schemas import PortfolioRating, TraderAction
from tradingagents.dataflows.utils import safe_ticker_component

# ---------------------------------------------------------------------------
# Directory / filename constants (section 4.2) -- descriptive only, nothing
# here creates a directory or file on disk.
# ---------------------------------------------------------------------------

RUNS_DIRNAME = "runs"
REVIEWS_DIRNAME = "reviews"
ANALYSIS_MANIFEST_FILENAME = "analysis_manifest.json"
STATUS_FILENAME = "status.json"
EVENTS_FILENAME = "events.jsonl"
COMPLETE_REPORT_FILENAME = "complete_report.md"
REVIEW_MANIFEST_FILENAME = "review_manifest.json"
REVIEW_DECISION_JSON_FILENAME = "decision.json"
REVIEW_DECISION_MD_FILENAME = "decision.md"

REPORT_TREE: dict[str, tuple[str, ...]] = {
    "1_analysts": ("market.md", "fundamentals.md", "sentiment.md", "news.md"),
    "2_research": ("bull.md", "bear.md", "manager.md"),
    "3_trading": ("trader.md",),
    "4_risk": ("aggressive.md", "neutral.md", "conservative.md"),
    "5_portfolio": ("decision.md",),
}


# ---------------------------------------------------------------------------
# Enums (section 4.6, plus AgentId/EventType/OverallStatus needed to make the
# contract unambiguous)
# ---------------------------------------------------------------------------


class AnalysisStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStatus(str, Enum):
    NOT_SELECTED = "not_selected"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class AgentId(str, Enum):
    """The 12 canonical agent ids used in ``selected_agents`` / ``agents``."""

    MARKET = "market"
    FUNDAMENTALS = "fundamentals"
    SENTIMENT = "sentiment"
    NEWS = "news"
    BULL = "bull"
    BEAR = "bear"
    RESEARCH_MANAGER = "research_manager"
    TRADER = "trader"
    AGGRESSIVE_RISK = "aggressive_risk"
    NEUTRAL_RISK = "neutral_risk"
    CONSERVATIVE_RISK = "conservative_risk"
    PORTFOLIO_MANAGER = "portfolio_manager"


class EventType(str, Enum):
    RUN_QUEUED = "run_queued"
    ANALYSIS_STARTED = "analysis_started"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    ANALYSIS_COMPLETED = "analysis_completed"
    # Run-level failure (e.g. propagate() raising outright), distinct from a
    # single agent_failed -- without this, a run that fails before any
    # agent-level event fires has no closing event at all in events.jsonl.
    ANALYSIS_FAILED = "analysis_failed"
    # Coarse runner-level stage boundaries (Phase 1B) around the
    # DeepSeekAnalysisRunner's own call sites -- propagate()/save_reports()/
    # manifest construction. Not agent-level: propagate() gives no
    # per-agent visibility from outside (see deepseek_analysis_runner.py).
    GRAPH_PROPAGATE_STARTED = "graph_propagate_started"
    GRAPH_PROPAGATE_COMPLETED = "graph_propagate_completed"
    REPORT_WRITE_STARTED = "report_write_started"
    REPORT_WRITE_COMPLETED = "report_write_completed"
    MANIFEST_WRITE_STARTED = "manifest_write_started"
    MANIFEST_WRITE_COMPLETED = "manifest_write_completed"


class OverallStatus(str, Enum):
    ANALYSIS_QUEUED = "analysis_queued"
    ANALYSIS_RUNNING = "analysis_running"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_CANCELLED = "analysis_cancelled"
    ANALYSIS_COMPLETED = "analysis_completed"
    REVIEW_QUEUED = "review_queued"
    REVIEW_RUNNING = "review_running"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_FAILED = "review_failed"
    REVIEW_CANCELLED = "review_cancelled"


# ---------------------------------------------------------------------------
# overall_status derivation
#
# Review can only leave "not_requested" once analysis has reached
# "completed" -- that collapses the 5x6 combination grid down to the 10
# valid cells below. Every other combination (e.g. review running while
# analysis is still queued) represents an inconsistent upstream state
# machine, not something safe to guess at, so it raises.
# ---------------------------------------------------------------------------

_OVERALL_STATUS_TABLE: dict[tuple[AnalysisStatus, ReviewStatus], OverallStatus] = {
    (AnalysisStatus.QUEUED, ReviewStatus.NOT_REQUESTED): OverallStatus.ANALYSIS_QUEUED,
    (AnalysisStatus.RUNNING, ReviewStatus.NOT_REQUESTED): OverallStatus.ANALYSIS_RUNNING,
    (AnalysisStatus.FAILED, ReviewStatus.NOT_REQUESTED): OverallStatus.ANALYSIS_FAILED,
    (AnalysisStatus.CANCELLED, ReviewStatus.NOT_REQUESTED): OverallStatus.ANALYSIS_CANCELLED,
    (AnalysisStatus.COMPLETED, ReviewStatus.NOT_REQUESTED): OverallStatus.ANALYSIS_COMPLETED,
    (AnalysisStatus.COMPLETED, ReviewStatus.QUEUED): OverallStatus.REVIEW_QUEUED,
    (AnalysisStatus.COMPLETED, ReviewStatus.RUNNING): OverallStatus.REVIEW_RUNNING,
    (AnalysisStatus.COMPLETED, ReviewStatus.COMPLETED): OverallStatus.REVIEW_COMPLETED,
    (AnalysisStatus.COMPLETED, ReviewStatus.FAILED): OverallStatus.REVIEW_FAILED,
    (AnalysisStatus.COMPLETED, ReviewStatus.CANCELLED): OverallStatus.REVIEW_CANCELLED,
}


def derive_overall_status(
    analysis_status: AnalysisStatus, review_status: ReviewStatus
) -> OverallStatus:
    """Look up the single valid ``overall_status`` for a status pair.

    Raises ``ValueError`` for any of the 20 combinations outside the 10
    valid cells (e.g. review already running while analysis is still
    queued) -- those represent a broken state machine upstream, not
    something this function should paper over with a guess.
    """
    try:
        return _OVERALL_STATUS_TABLE[(analysis_status, review_status)]
    except KeyError as exc:
        raise ValueError(
            "invalid combination: analysis_status="
            f"{analysis_status.value!r} review_status={review_status.value!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Shared field validators
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_run_id(value: str) -> str:
    """Guard a run/review id against unsafe path components.

    Deliberately permissive: this does not enforce the
    ``{TICKER}_{YYYYMMDD_HHMMSS}`` shape or second-granularity uniqueness --
    collision-avoidance for concurrent run creation is a Phase 1A/2 concern,
    not a schema concern.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("run_id must be a non-empty string")
    if len(value) > 128:
        raise ValueError(f"run_id exceeds 128 chars: {value!r}")
    if not _RUN_ID_RE.fullmatch(value):
        raise ValueError(f"run_id contains characters unsafe for a path component: {value!r}")
    return value


def _validate_analysis_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"analysis_date must be YYYY-MM-DD: {value!r}") from exc
    return value


_STRATEGY_PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_strategy_profile(value: str | None) -> str | None:
    """Phase 2F placeholder: a future Pradeep-style knowledge base/scanner
    hasn't been built yet, so this only validates shape (safe charset,
    reasonable length), not membership in any real profile registry --
    there is no such registry to check against. ``None`` (the default,
    meaning "manual analysis, no profile") always passes through."""
    if value is None:
        return value
    if not _STRATEGY_PROFILE_RE.fullmatch(value):
        raise ValueError(
            f"strategy_profile must be 1-64 chars of [A-Za-z0-9_-] or null: {value!r}"
        )
    return value


RunId = Annotated[str, AfterValidator(_validate_run_id)]
Ticker = Annotated[str, AfterValidator(safe_ticker_component)]
AnalysisDate = Annotated[str, AfterValidator(_validate_analysis_date)]
StrategyProfile = Annotated[str | None, AfterValidator(_validate_strategy_profile)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class _RunArtifactBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"


class AnalysisManifest(_RunArtifactBase):
    """``analysis_manifest.json`` (section 4.4). Sealed once analysis completes."""

    artifact_type: Literal["analysis_manifest"] = "analysis_manifest"
    run_id: RunId
    ticker: Ticker
    analysis_date: AnalysisDate
    created_at: datetime
    analysis_status: AnalysisStatus
    # Optional: a live Phase 1A run always knows these; the Phase 0B legacy
    # importer genuinely doesn't (old markdown reports carry no provider/model
    # data) and must record that as None rather than a fabricated placeholder.
    analysis_provider: str | None = None
    quick_model: str | None = None
    deep_model: str | None = None
    selected_agents: list[AgentId] = Field(default_factory=list)
    draft_rating: PortfolioRating | None = None
    trader_action: TraderAction | None = None
    research_manager_recommendation: PortfolioRating | None = None
    stop_loss: float | None = None
    position_sizing: str | None = None
    time_horizon: str | None = None
    position_context_available: bool = False
    data_quality_assessment: str = "not_available"
    data_quality_flags: list[str] = Field(default_factory=list)
    disclaimer_version: str = "research-only-v1"
    # Phase 2F placeholders for a future Pradeep-style knowledge base /
    # rule-matching scanner. Pure passthrough or schema reservation -- none
    # of these are computed or consulted by anything in this codebase yet.
    # All default to "nothing was used" so every existing manifest (Phase
    # 0B-imported or produced by any pre-Phase-2F runner) round-trips
    # unchanged.
    strategy_profile: StrategyProfile = None
    knowledge_version: str | None = None
    matched_rules: list[str] = Field(default_factory=list)
    strategy_score: float | None = None
    knowledge_context_ids: list[str] = Field(default_factory=list)


class RunStatus(_RunArtifactBase):
    """``status.json`` (section 4.5). Mutable view of a run in progress."""

    artifact_type: Literal["run_status"] = "run_status"
    run_id: RunId
    analysis_status: AnalysisStatus
    review_status: ReviewStatus = ReviewStatus.NOT_REQUESTED
    overall_status: OverallStatus
    current_stage: str | None = None
    agents: dict[AgentId, AgentStatus] = Field(default_factory=dict)
    latest_error: str | None = None
    updated_at: datetime
    # Phase 2F placeholder, pure passthrough from the request -- present
    # here (not just AnalysisManifest) so a future Compare Board can group
    # in-progress runs by profile before they've completed.
    strategy_profile: StrategyProfile = None

    @model_validator(mode="after")
    def _overall_status_must_match_derivation(self) -> RunStatus:
        expected = derive_overall_status(self.analysis_status, self.review_status)
        if self.overall_status != expected:
            raise ValueError(
                "overall_status "
                f"{self.overall_status.value!r} is inconsistent with "
                f"analysis_status={self.analysis_status.value!r} "
                f"review_status={self.review_status.value!r} "
                f"(expected {expected.value!r})"
            )
        return self


class RunEvent(BaseModel):
    """One ``events.jsonl`` record (section 4.7).

    Deliberately does not inherit ``_RunArtifactBase``: the blueprint's own
    example event lines carry no ``schema_version``/``artifact_type`` keys.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    run_id: RunId
    created_at: datetime
    agent_id: AgentId | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _agent_fields_required_for_agent_events(self) -> RunEvent:
        agent_events = {EventType.AGENT_STARTED, EventType.AGENT_COMPLETED, EventType.AGENT_FAILED}
        if self.event_type in agent_events and self.agent_id is None:
            raise ValueError(f"event_type={self.event_type.value!r} requires agent_id")
        if self.event_type is EventType.AGENT_FAILED and not self.error:
            raise ValueError("event_type='agent_failed' requires a non-empty error")
        if self.event_type is EventType.ANALYSIS_FAILED and not self.error:
            raise ValueError("event_type='analysis_failed' requires a non-empty error")
        return self


class ReviewManifestStub(_RunArtifactBase):
    """Minimal placeholder for ``reviews/{review_id}/review_manifest.json``.

    Phase 3 (Claude Final Review) will extend this with the actual review
    scope/decision payload; treat this as unstable/additive-only until then.
    """

    artifact_type: Literal["review_manifest"] = "review_manifest"
    review_id: RunId
    run_id: RunId
    review_status: ReviewStatus
    created_at: datetime
