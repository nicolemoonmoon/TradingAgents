"""Run artifact contract: Pydantic schema for analysis_manifest.json, status.json,
and events.jsonl (Phase 0A of the web blueprint, docs/TradingAgents_Web_Claude_Execution_Blueprint.md section 4).

Schema-only: no filesystem I/O, no wiring into the real graph/CLI/reporting.
"""

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import (
    EntryDecision,
    ExecutionAvailability,
    ExitReason,
    PortfolioRating,
    PositionDecision,
    TraderAction,
)
from tradingagents.run_contract import (
    REPORT_TREE,
    AgentId,
    AgentStatus,
    AnalysisManifest,
    AnalysisStatus,
    EventType,
    OverallStatus,
    ReviewManifestStub,
    ReviewStatus,
    RunEvent,
    RunStatus,
    derive_overall_status,
)

CREATED_AT = "2026-07-01T16:51:31+00:00"

SELECTED_AGENTS = [
    "market",
    "fundamentals",
    "sentiment",
    "news",
    "bull",
    "bear",
    "research_manager",
    "trader",
    "aggressive_risk",
    "neutral_risk",
    "conservative_risk",
    "portfolio_manager",
]

# Governed report fields added as additive optional transport (run-result
# transport). A pre-governed manifest omits these entirely.
_GOVERNED_FIELDS = {
    "entry_decision",
    "why_wait",
    "what_needs_to_change",
    "recheck_trigger",
    "review_due",
    "execution_availability",
    "position_decision",
    "exit_reason",
}


def _manifest_dict(**overrides):
    base = {
        "schema_version": "1.0",
        "artifact_type": "analysis_manifest",
        "run_id": "AAPL_20260701_165131",
        "ticker": "AAPL",
        "analysis_date": "2026-07-01",
        "created_at": CREATED_AT,
        "analysis_status": "completed",
        "analysis_provider": "deepseek",
        "quick_model": "deepseek-v4-flash",
        "deep_model": "deepseek-v4-pro",
        "selected_agents": SELECTED_AGENTS,
        "draft_rating": None,
        "trader_action": None,
        "research_manager_recommendation": None,
        "stop_loss": None,
        "position_sizing": None,
        "time_horizon": None,
        "position_context_available": False,
        "data_quality_assessment": "not_available",
        "data_quality_flags": [],
        "disclaimer_version": "research-only-v1",
        "entry_decision": None,
        "why_wait": None,
        "what_needs_to_change": None,
        "recheck_trigger": None,
        "review_due": None,
        "execution_availability": None,
        "position_decision": None,
        "exit_reason": None,
        "strategy_profile": None,
        "knowledge_version": None,
        "matched_rules": [],
        "strategy_score": None,
        "knowledge_context_ids": [],
    }
    base.update(overrides)
    return base


def _status_dict(**overrides):
    base = {
        "schema_version": "1.0",
        "artifact_type": "run_status",
        "run_id": "AAPL_20260701_165131",
        "analysis_status": "completed",
        "review_status": "not_requested",
        "overall_status": "analysis_completed",
        "current_stage": "portfolio_decision",
        "agents": dict.fromkeys(SELECTED_AGENTS, "completed"),
        "latest_error": None,
        "updated_at": CREATED_AT,
        "strategy_profile": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Directory tree constant
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_report_tree_constant_matches_blueprint_layout():
    assert REPORT_TREE == {
        "1_analysts": ("market.md", "fundamentals.md", "sentiment.md", "news.md"),
        "2_research": ("bull.md", "bear.md", "manager.md"),
        "3_trading": ("trader.md",),
        "4_risk": ("aggressive.md", "neutral.md", "conservative.md"),
        "5_portfolio": ("decision.md",),
    }


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_analysis_status_enum_values():
    assert {s.value for s in AnalysisStatus} == {
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    }


@pytest.mark.unit
def test_review_status_enum_values():
    assert {s.value for s in ReviewStatus} == {
        "not_requested",
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
    }


@pytest.mark.unit
def test_agent_status_enum_values():
    assert {s.value for s in AgentStatus} == {
        "not_selected",
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
        "cancelled",
    }


@pytest.mark.unit
def test_agent_id_enum_matches_blueprint_selected_agents_example():
    assert {a.value for a in AgentId} == set(SELECTED_AGENTS)


@pytest.mark.unit
def test_event_type_includes_analysis_failed():
    # A run-level failure (propagate() raising outright, not a single
    # agent failing) needs its own terminal event distinct from
    # agent_failed -- otherwise events.jsonl has no closing event at all
    # for a run that failed before any agent-level event fired.
    assert "analysis_failed" in {e.value for e in EventType}


@pytest.mark.unit
def test_event_type_includes_stage_events():
    # Phase 1B: coarse runner-level stage boundaries around propagate()/
    # save_reports()/manifest construction, so events.jsonl isn't silent
    # for the minutes-long propagate() call. Not agent-level events.
    values = {e.value for e in EventType}
    assert {
        "graph_propagate_started",
        "graph_propagate_completed",
        "report_write_started",
        "report_write_completed",
        "manifest_write_started",
        "manifest_write_completed",
    } <= values


# ---------------------------------------------------------------------------
# derive_overall_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "analysis_status,review_status,expected",
    [
        (AnalysisStatus.QUEUED, ReviewStatus.NOT_REQUESTED, OverallStatus.ANALYSIS_QUEUED),
        (AnalysisStatus.RUNNING, ReviewStatus.NOT_REQUESTED, OverallStatus.ANALYSIS_RUNNING),
        (AnalysisStatus.FAILED, ReviewStatus.NOT_REQUESTED, OverallStatus.ANALYSIS_FAILED),
        (AnalysisStatus.CANCELLED, ReviewStatus.NOT_REQUESTED, OverallStatus.ANALYSIS_CANCELLED),
        (AnalysisStatus.COMPLETED, ReviewStatus.NOT_REQUESTED, OverallStatus.ANALYSIS_COMPLETED),
        (AnalysisStatus.COMPLETED, ReviewStatus.QUEUED, OverallStatus.REVIEW_QUEUED),
        (AnalysisStatus.COMPLETED, ReviewStatus.RUNNING, OverallStatus.REVIEW_RUNNING),
        (AnalysisStatus.COMPLETED, ReviewStatus.COMPLETED, OverallStatus.REVIEW_COMPLETED),
        (AnalysisStatus.COMPLETED, ReviewStatus.FAILED, OverallStatus.REVIEW_FAILED),
        (AnalysisStatus.COMPLETED, ReviewStatus.CANCELLED, OverallStatus.REVIEW_CANCELLED),
    ],
)
def test_derive_overall_status_valid_table(analysis_status, review_status, expected):
    assert derive_overall_status(analysis_status, review_status) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "analysis_status,review_status",
    [
        (AnalysisStatus.QUEUED, ReviewStatus.RUNNING),
        (AnalysisStatus.RUNNING, ReviewStatus.COMPLETED),
        (AnalysisStatus.FAILED, ReviewStatus.QUEUED),
        (AnalysisStatus.CANCELLED, ReviewStatus.FAILED),
    ],
)
def test_derive_overall_status_rejects_invalid_combinations(analysis_status, review_status):
    with pytest.raises(ValueError):
        derive_overall_status(analysis_status, review_status)


# ---------------------------------------------------------------------------
# AnalysisManifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_analysis_manifest_minimal_construction_applies_defaults():
    manifest = AnalysisManifest(
        run_id="AAPL_20260701_165131",
        ticker="AAPL",
        analysis_date="2026-07-01",
        created_at=CREATED_AT,
        analysis_status=AnalysisStatus.QUEUED,
        analysis_provider="deepseek",
        quick_model="deepseek-v4-flash",
        deep_model="deepseek-v4-pro",
    )
    assert manifest.disclaimer_version == "research-only-v1"
    assert manifest.data_quality_assessment == "not_available"
    assert manifest.draft_rating is None
    assert manifest.selected_agents == []
    assert manifest.schema_version == "1.0"


@pytest.mark.unit
def test_analysis_manifest_accepts_none_for_provider_and_models():
    # Legacy-imported manifests (Phase 0B) genuinely don't know the provider/model
    # that produced an old report -- these fields must accept None rather than
    # forcing a fabricated placeholder string.
    manifest = AnalysisManifest(
        **{
            **_manifest_dict(),
            "analysis_provider": None,
            "quick_model": None,
            "deep_model": None,
        }
    )
    assert manifest.analysis_provider is None
    assert manifest.quick_model is None
    assert manifest.deep_model is None


@pytest.mark.unit
def test_analysis_manifest_rejects_invalid_analysis_status():
    with pytest.raises(ValidationError):
        AnalysisManifest(**_manifest_dict(analysis_status="not_a_status"))


@pytest.mark.unit
def test_analysis_manifest_draft_rating_uses_shared_portfolio_rating_enum():
    import typing

    annotation = AnalysisManifest.model_fields["draft_rating"].annotation
    assert PortfolioRating in typing.get_args(annotation)


@pytest.mark.unit
def test_analysis_manifest_trader_action_uses_shared_enum():
    import typing

    annotation = AnalysisManifest.model_fields["trader_action"].annotation
    assert TraderAction in typing.get_args(annotation)


@pytest.mark.unit
def test_analysis_manifest_ticker_rejects_path_traversal():
    with pytest.raises(ValidationError):
        AnalysisManifest(**_manifest_dict(ticker="../../etc/passwd"))


@pytest.mark.unit
def test_analysis_manifest_rejects_bad_analysis_date_format():
    with pytest.raises(ValidationError):
        AnalysisManifest(**_manifest_dict(analysis_date="07/01/2026"))


@pytest.mark.unit
def test_analysis_manifest_round_trip_matches_blueprint_example():
    payload = _manifest_dict()
    manifest = AnalysisManifest(**payload)
    dumped = manifest.model_dump(mode="json")
    expected = dict(payload)
    expected["created_at"] = dumped["created_at"]
    assert dumped == expected


@pytest.mark.unit
def test_analysis_manifest_old_roundtrip_remains_valid_with_governed_fields_absent():
    # A pre-governed manifest (no entry/position/exit fields at all) must
    # still parse and round-trip; every governed field stays None.
    payload = {k: v for k, v in _manifest_dict().items() if k not in _GOVERNED_FIELDS}
    manifest = AnalysisManifest(**payload)
    assert manifest.entry_decision is None
    assert manifest.why_wait is None
    assert manifest.position_decision is None
    assert manifest.exit_reason is None
    assert manifest.execution_availability is None

    dumped = manifest.model_dump(mode="json")
    assert dumped["entry_decision"] is None
    assert dumped["position_decision"] is None
    assert dumped["exit_reason"] is None


@pytest.mark.unit
def test_analysis_manifest_governed_fields_parse_and_roundtrip_when_present():
    manifest = AnalysisManifest(
        **_manifest_dict(
            entry_decision="WAIT",
            why_wait="extended above the entry zone",
            what_needs_to_change="pull back to support",
            recheck_trigger="daily close below 20 SMA",
            review_due="2026-08-20",
            execution_availability="AVAILABLE",
            position_decision="SELL",
            exit_reason="THESIS_BROKEN",
        )
    )
    assert manifest.entry_decision == EntryDecision.WAIT
    assert manifest.why_wait == "extended above the entry zone"
    assert manifest.what_needs_to_change == "pull back to support"
    assert manifest.recheck_trigger == "daily close below 20 SMA"
    assert manifest.review_due == "2026-08-20"
    assert manifest.execution_availability == ExecutionAvailability.AVAILABLE
    assert manifest.position_decision == PositionDecision.SELL
    assert manifest.exit_reason == ExitReason.THESIS_BROKEN

    dumped = manifest.model_dump(mode="json")
    assert dumped["entry_decision"] == "WAIT"
    assert dumped["why_wait"] == "extended above the entry zone"
    assert dumped["position_decision"] == "SELL"
    assert dumped["exit_reason"] == "THESIS_BROKEN"

    # Round-trips through the exact on-disk JSON representation.
    assert AnalysisManifest.model_validate_json(manifest.model_dump_json()) == manifest


# ---------------------------------------------------------------------------
# RunStatus
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_status_overall_status_must_be_internally_consistent():
    with pytest.raises(ValidationError):
        RunStatus(**_status_dict(overall_status="review_running"))


@pytest.mark.unit
def test_run_status_round_trip_matches_blueprint_example():
    payload = _status_dict()
    status = RunStatus(**payload)
    dumped = status.model_dump(mode="json")
    expected = dict(payload)
    expected["updated_at"] = dumped["updated_at"]
    assert dumped == expected


@pytest.mark.unit
def test_run_status_rejects_unknown_agent_id_key():
    with pytest.raises(ValidationError):
        RunStatus(**_status_dict(agents={"not_a_real_agent": "completed"}))


@pytest.mark.unit
def test_run_status_run_id_rejects_unsafe_characters():
    with pytest.raises(ValidationError):
        RunStatus(**_status_dict(run_id="../x"))


# ---------------------------------------------------------------------------
# Phase 4B: cancelled status lifecycle invariants
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_status_accepts_cancelled_analysis_status():
    """Phase 4B: cancelled is a valid AnalysisStatus — constructing a RunStatus
    with it must succeed and derive ANALYSIS_CANCELLED overall_status."""
    status = RunStatus(
        **_status_dict(
            analysis_status="cancelled",
            overall_status="analysis_cancelled",
        )
    )
    assert status.analysis_status == AnalysisStatus.CANCELLED
    assert status.overall_status == OverallStatus.ANALYSIS_CANCELLED


@pytest.mark.unit
def test_run_status_cancelled_with_review_not_requested_is_valid():
    """Phase 4B: the only valid review_status for a cancelled analysis is
    not_requested — verify the derivation doesn't raise."""
    status = RunStatus(
        **_status_dict(
            analysis_status="cancelled",
            review_status="not_requested",
            overall_status="analysis_cancelled",
        )
    )
    assert status.analysis_status == AnalysisStatus.CANCELLED
    assert status.review_status == ReviewStatus.NOT_REQUESTED
    assert status.overall_status == OverallStatus.ANALYSIS_CANCELLED


@pytest.mark.unit
def test_run_status_cancelled_rejects_inconsistent_review_status():
    """Phase 4B: a cancelled analysis with any review_status other than
    not_requested is an invalid state machine combination and must raise."""
    with pytest.raises(ValidationError):
        RunStatus(
            **_status_dict(
                analysis_status="cancelled",
                review_status="queued",
                overall_status="analysis_cancelled",
            )
        )


# ---------------------------------------------------------------------------
# RunEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_event_round_trip_matches_blueprint_run_queued_example():
    payload = {
        "event_type": "run_queued",
        "run_id": "AAPL_20260701_165131",
        "created_at": CREATED_AT,
    }
    event = RunEvent(**payload)
    dumped = event.model_dump(mode="json", exclude_none=True)
    expected = dict(payload)
    expected["created_at"] = dumped["created_at"]
    assert dumped == expected


@pytest.mark.unit
def test_run_event_round_trip_matches_blueprint_agent_completed_example():
    payload = {
        "event_type": "agent_completed",
        "run_id": "AAPL_20260701_165131",
        "agent_id": "fundamentals",
        "created_at": CREATED_AT,
    }
    event = RunEvent(**payload)
    dumped = event.model_dump(mode="json", exclude_none=True)
    expected = dict(payload)
    expected["created_at"] = dumped["created_at"]
    assert dumped == expected


@pytest.mark.unit
def test_run_event_agent_started_requires_agent_id():
    with pytest.raises(ValidationError):
        RunEvent(event_type="agent_started", run_id="AAPL_20260701_165131", created_at=CREATED_AT)


@pytest.mark.unit
def test_run_event_agent_failed_requires_error_message():
    with pytest.raises(ValidationError):
        RunEvent(
            event_type="agent_failed",
            run_id="AAPL_20260701_165131",
            agent_id="sentiment",
            created_at=CREATED_AT,
        )


@pytest.mark.unit
def test_run_event_analysis_failed_requires_error_message():
    with pytest.raises(ValidationError):
        RunEvent(
            event_type=EventType.ANALYSIS_FAILED,
            run_id="AAPL_20260701_165131",
            created_at=CREATED_AT,
        )


@pytest.mark.unit
def test_run_event_analysis_failed_with_error_constructs_successfully():
    event = RunEvent(
        event_type=EventType.ANALYSIS_FAILED,
        run_id="AAPL_20260701_165131",
        created_at=CREATED_AT,
        error="propagate() raised RuntimeError: boom",
    )
    assert event.event_type == EventType.ANALYSIS_FAILED


@pytest.mark.unit
def test_run_event_rejects_unknown_event_type():
    with pytest.raises(ValidationError):
        RunEvent(event_type="something_else", run_id="AAPL_20260701_165131", created_at=CREATED_AT)


# ---------------------------------------------------------------------------
# schema_version
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_version_defaults_to_current_version():
    payload = {k: v for k, v in _manifest_dict().items() if k != "schema_version"}
    manifest = AnalysisManifest(**payload)
    assert manifest.schema_version == "1.0"


@pytest.mark.unit
def test_schema_version_rejects_unknown_version_on_analysis_manifest():
    with pytest.raises(ValidationError):
        AnalysisManifest(**_manifest_dict(schema_version="2.0"))


@pytest.mark.unit
def test_schema_version_rejects_unknown_version_on_run_status():
    with pytest.raises(ValidationError):
        RunStatus(**_status_dict(schema_version="2.0"))


# ---------------------------------------------------------------------------
# ReviewManifestStub -- Phase 3 placeholder only, no decision/review fields yet
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_review_manifest_stub_minimal_construction():
    stub = ReviewManifestStub(
        review_id="review_20260701_001",
        run_id="AAPL_20260701_165131",
        review_status=ReviewStatus.NOT_REQUESTED,
        created_at=CREATED_AT,
    )
    assert stub.schema_version == "1.0"
    assert stub.artifact_type == "review_manifest"


# ---------------------------------------------------------------------------
# extra="forbid"
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_analysis_manifest_rejects_unknown_extra_fields():
    with pytest.raises(ValidationError):
        AnalysisManifest(**_manifest_dict(some_made_up_field="x"))


@pytest.mark.unit
def test_run_status_rejects_unknown_extra_fields():
    with pytest.raises(ValidationError):
        RunStatus(**_status_dict(some_made_up_field="x"))


@pytest.mark.unit
def test_run_event_rejects_unknown_extra_fields():
    with pytest.raises(ValidationError):
        RunEvent(
            event_type="run_queued",
            run_id="AAPL_20260701_165131",
            created_at=CREATED_AT,
            some_made_up_field="x",
        )


# ---------------------------------------------------------------------------
# Phase 2F: strategy/knowledge-base placeholder fields -- pure passthrough,
# never computed or consulted by anything. Defaults must be None/[] so every
# existing manifest/status (including Phase 0B legacy imports, none of which
# know about these fields) round-trips unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_analysis_manifest_strategy_fields_default_to_none_and_empty():
    manifest = AnalysisManifest(
        run_id="AAPL_20260701_165131",
        ticker="AAPL",
        analysis_date="2026-07-01",
        created_at=CREATED_AT,
        analysis_status=AnalysisStatus.QUEUED,
        analysis_provider="deepseek",
        quick_model="deepseek-v4-flash",
        deep_model="deepseek-v4-pro",
    )
    assert manifest.strategy_profile is None
    assert manifest.knowledge_version is None
    assert manifest.matched_rules == []
    assert manifest.strategy_score is None
    assert manifest.knowledge_context_ids == []


@pytest.mark.unit
def test_run_status_strategy_profile_defaults_to_none():
    status = RunStatus(**{k: v for k, v in _status_dict().items() if k != "strategy_profile"})
    assert status.strategy_profile is None


@pytest.mark.unit
def test_legacy_manifest_json_without_strategy_fields_still_parses():
    # Simulates a Phase 0B-imported (or any pre-Phase-2F) manifest on disk
    # that has never heard of these 5 keys -- it must still parse, with the
    # new fields falling back to their defaults, not raise.
    payload = _manifest_dict()
    for key in (
        "strategy_profile",
        "knowledge_version",
        "matched_rules",
        "strategy_score",
        "knowledge_context_ids",
    ):
        del payload[key]
    import json

    manifest = AnalysisManifest.model_validate_json(json.dumps(payload))
    assert manifest.strategy_profile is None
    assert manifest.knowledge_version is None
    assert manifest.matched_rules == []
    assert manifest.strategy_score is None
    assert manifest.knowledge_context_ids == []


@pytest.mark.unit
@pytest.mark.parametrize("bad_value", ["has space", "a!b", "", "x" * 65])
def test_analysis_manifest_rejects_invalid_strategy_profile(bad_value):
    with pytest.raises(ValidationError):
        AnalysisManifest(**_manifest_dict(strategy_profile=bad_value))


@pytest.mark.unit
def test_run_status_rejects_invalid_strategy_profile():
    with pytest.raises(ValidationError):
        RunStatus(**_status_dict(strategy_profile="bad profile!"))


@pytest.mark.unit
def test_analysis_manifest_accepts_valid_strategy_profile():
    manifest = AnalysisManifest(**_manifest_dict(strategy_profile="pradeep_v1"))
    assert manifest.strategy_profile == "pradeep_v1"
