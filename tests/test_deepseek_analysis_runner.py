"""DeepSeekAnalysisRunner (Phase 1A): calls a TradingAgentsGraph-like object's
propagate()/save_reports() and turns the result into structured run
artifacts. No real DeepSeek/LLM call anywhere in these tests -- the graph
is a small in-memory fake whose propagate() returns a canned final_state
(or raises), and whose save_reports() delegates to the real, already-tested
tradingagents.reporting.write_report_tree.
"""

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import PortfolioRating, TraderAction
from tradingagents.deepseek_analysis_runner import (
    DeepSeekAnalysisRunner,
    DeepSeekAnalysisRunnerError,
)
from tradingagents.run_contract import (
    ANALYSIS_MANIFEST_FILENAME,
    EVENTS_FILENAME,
    STATUS_FILENAME,
    AgentId,
    AgentStatus,
    AnalysisStatus,
    OverallStatus,
    RunStatus,
)

FIXED_TIME = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)


def _config(**overrides):
    base = {
        "llm_provider": "deepseek",
        "quick_think_llm": "deepseek-v4-flash",
        "deep_think_llm": "deepseek-v4-pro",
    }
    base.update(overrides)
    return base


def _final_state(**overrides):
    base = {
        "market_report": "Market analysis text.",
        "sentiment_report": "Sentiment analysis text.",
        "news_report": "News analysis text.",
        "fundamentals_report": "Fundamentals analysis text.",
        "investment_debate_state": {
            "bull_history": "Bull case text.",
            "bear_history": "Bear case text.",
            "judge_decision": (
                "**Recommendation**: Underweight\n\n"
                "**Rationale**: Bear arguments win.\n\n"
                "**Strategic Actions**: Reduce position."
            ),
        },
        "trader_investment_plan": (
            "**Action**: Hold\n\n"
            "**Reasoning**: Wait for confirmation.\n\n"
            "**Stop Loss**: 83.0\n\n"
            "**Position Sizing**: Reduce to 50%-70% of standard allocation\n\n"
            "FINAL TRANSACTION PROPOSAL: **HOLD**"
        ),
        "risk_debate_state": {
            "aggressive_history": "Aggressive risk text.",
            "conservative_history": "Conservative risk text.",
            "neutral_history": "Neutral risk text.",
            "judge_decision": (
                "**Rating**: Hold\n\n"
                "**Executive Summary**: Maintain position.\n\n"
                "**Investment Thesis**: Balanced risk/reward.\n\n"
                "**Time Horizon**: 3-6 months"
            ),
        },
    }
    base.update(overrides)
    return base


class _FakeGraph:
    def __init__(
        self,
        config,
        final_state=None,
        raise_exc=None,
        on_propagate=None,
        raise_in_save_reports=None,
        on_save_reports=None,
    ):
        self.config = config
        self._final_state = final_state
        self._raise_exc = raise_exc
        self._on_propagate = on_propagate
        self._raise_in_save_reports = raise_in_save_reports
        self._on_save_reports = on_save_reports
        self.propagate_calls = []
        self.save_reports_calls = []

    def propagate(self, ticker, analysis_date, asset_type="stock"):
        self.propagate_calls.append((ticker, analysis_date, asset_type))
        if self._on_propagate is not None:
            self._on_propagate()
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._final_state, "Hold"

    def save_reports(self, final_state, ticker, save_path=None):
        from tradingagents.reporting import write_report_tree

        self.save_reports_calls.append((final_state, ticker, save_path))
        if self._on_save_reports is not None:
            self._on_save_reports()
        if self._raise_in_save_reports is not None:
            raise self._raise_in_save_reports
        return write_report_tree(final_state, ticker, save_path)


def _fixed_clock():
    return FIXED_TIME


# ---------------------------------------------------------------------------
# __init__ validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("key", ["llm_provider", "quick_think_llm", "deep_think_llm"])
@pytest.mark.parametrize("bad_value", ["", None])
def test_runner_requires_non_empty_config_fields(tmp_path, key, bad_value):
    graph = _FakeGraph(_config(**{key: bad_value}))
    with pytest.raises(DeepSeekAnalysisRunnerError):
        DeepSeekAnalysisRunner(graph, runs_dir=tmp_path)
    assert graph.propagate_calls == []


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_success_writes_full_artifact_tree(tmp_path):
    graph = _FakeGraph(_config(), final_state=_final_state())
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, status = runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / manifest.run_id
    assert (run_dir / "complete_report.md").exists()
    assert (run_dir / "1_analysts" / "market.md").exists()
    assert (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()
    assert (run_dir / STATUS_FILENAME).exists()
    assert (run_dir / EVENTS_FILENAME).exists()

    assert manifest.analysis_status == AnalysisStatus.COMPLETED
    assert manifest.draft_rating == PortfolioRating.HOLD
    assert manifest.trader_action == TraderAction.HOLD
    assert manifest.research_manager_recommendation == PortfolioRating.UNDERWEIGHT
    assert manifest.stop_loss == 83.0
    assert manifest.position_sizing is not None
    assert manifest.time_horizon == "3-6 months"
    assert manifest.analysis_provider == "deepseek"
    assert manifest.quick_model == "deepseek-v4-flash"
    assert manifest.deep_model == "deepseek-v4-pro"
    assert set(manifest.selected_agents) == set(AgentId)
    assert manifest.data_quality_assessment == "not_available"

    assert status.analysis_status == AnalysisStatus.COMPLETED
    assert status.overall_status == OverallStatus.ANALYSIS_COMPLETED
    assert status.agents[AgentId.MARKET] == AgentStatus.COMPLETED


@pytest.mark.unit
def test_run_success_events_sequence_is_full_nine_stages(tmp_path):
    graph = _FakeGraph(_config(), final_state=_final_state())
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, _status = runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / manifest.run_id
    lines = (run_dir / EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
    event_types = [json.loads(line)["event_type"] for line in lines]
    assert event_types == [
        "run_queued",
        "analysis_started",
        "graph_propagate_started",
        "graph_propagate_completed",
        "report_write_started",
        "report_write_completed",
        "manifest_write_started",
        "manifest_write_completed",
        "analysis_completed",
    ]


@pytest.mark.unit
def test_run_id_matches_ticker_timestamp_convention(tmp_path):
    graph = _FakeGraph(_config(), final_state=_final_state())
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, status = runner.run("AAPL", "2026-07-03")

    assert manifest.run_id == "AAPL_20260703_120000"
    assert status.run_id == "AAPL_20260703_120000"
    assert (tmp_path / "AAPL_20260703_120000").is_dir()


@pytest.mark.unit
def test_run_passes_asset_type_through_to_graph_propagate(tmp_path):
    graph = _FakeGraph(_config(), final_state=_final_state())
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    runner.run("BTC-USD", "2026-07-03", asset_type="crypto")

    assert graph.propagate_calls == [("BTC-USD", "2026-07-03", "crypto")]


@pytest.mark.unit
def test_run_missing_optional_field_is_none_not_fabricated(tmp_path):
    final_state = _final_state()
    final_state["trader_investment_plan"] = (
        "**Action**: Hold\n\n**Reasoning**: No numeric levels given.\n\n"
        "FINAL TRANSACTION PROPOSAL: **HOLD**"
    )
    graph = _FakeGraph(_config(), final_state=final_state)
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, _status = runner.run("AAPL", "2026-07-03")

    assert manifest.stop_loss is None
    assert manifest.position_sizing is None
    assert manifest.trader_action == TraderAction.HOLD


@pytest.mark.unit
def test_run_writes_graph_propagate_stage_before_blocking_call(tmp_path):
    captured = {}

    def _capture():
        run_dir = tmp_path / "AAPL_20260703_120000"
        captured["status"] = RunStatus.model_validate_json(
            (run_dir / STATUS_FILENAME).read_text(encoding="utf-8")
        )

    graph = _FakeGraph(_config(), final_state=_final_state(), on_propagate=_capture)
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    runner.run("AAPL", "2026-07-03")

    assert captured["status"].analysis_status == AnalysisStatus.RUNNING
    assert captured["status"].overall_status == OverallStatus.ANALYSIS_RUNNING
    assert captured["status"].current_stage == "graph_propagate"
    assert captured["status"].agents == {}


@pytest.mark.unit
def test_run_writes_report_write_stage_before_save_reports_call(tmp_path):
    captured = {}

    def _capture():
        run_dir = tmp_path / "AAPL_20260703_120000"
        captured["status"] = RunStatus.model_validate_json(
            (run_dir / STATUS_FILENAME).read_text(encoding="utf-8")
        )

    graph = _FakeGraph(_config(), final_state=_final_state(), on_save_reports=_capture)
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    runner.run("AAPL", "2026-07-03")

    assert captured["status"].analysis_status == AnalysisStatus.RUNNING
    assert captured["status"].overall_status == OverallStatus.ANALYSIS_RUNNING
    assert captured["status"].current_stage == "report_write"
    assert captured["status"].agents == {}


@pytest.mark.unit
def test_run_final_status_current_stage_is_completed(tmp_path):
    graph = _FakeGraph(_config(), final_state=_final_state())
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    _manifest, status = runner.run("AAPL", "2026-07-03")

    assert status.current_stage == "completed"


@pytest.mark.unit
def test_run_flags_draft_rating_missing_when_pm_output_is_unstructured_free_text(tmp_path):
    # Reproduces the real Phase 1A smoke test observation (AAPL_20260703_022654):
    # the Portfolio Manager's structured-output call fell back to free text
    # with no "**Rating**:" label, so draft_rating stays None -- must be
    # flagged now, not silently absent.
    final_state = _final_state()
    final_state["risk_debate_state"]["judge_decision"] = (
        "好的，作为投资组合经理，我的最终决定是维持现有仓位不变。"
    )
    graph = _FakeGraph(_config(), final_state=final_state)
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, _status = runner.run("AAPL", "2026-07-03")

    assert manifest.draft_rating is None
    assert "draft_rating_missing" in manifest.data_quality_flags
    assert "portfolio_decision_unstructured_or_unparseable" in manifest.data_quality_flags


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_failure_records_status_failed_and_reraises(tmp_path):
    graph = _FakeGraph(_config(), raise_exc=RuntimeError("boom"))
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    with pytest.raises(RuntimeError, match="boom"):
        runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / "AAPL_20260703_120000"
    status = RunStatus.model_validate_json((run_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status.analysis_status == AnalysisStatus.FAILED
    assert status.overall_status == OverallStatus.ANALYSIS_FAILED
    assert status.current_stage == "failed"
    assert status.latest_error == "boom"
    assert not (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()

    lines = (run_dir / EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
    last_event = json.loads(lines[-1])
    assert last_event["event_type"] == "analysis_failed"
    assert last_event["error"] == "boom"


@pytest.mark.unit
def test_run_failure_in_save_reports_records_status_failed(tmp_path):
    # propagate() succeeds, but save_reports() itself raises -- markdown may
    # be partially written by write_report_tree before the failure, and must
    # NOT be rolled back; status/events must still accurately show failed.
    graph = _FakeGraph(
        _config(), final_state=_final_state(), raise_in_save_reports=RuntimeError("disk full")
    )
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    with pytest.raises(RuntimeError, match="disk full"):
        runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / "AAPL_20260703_120000"
    status = RunStatus.model_validate_json((run_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status.analysis_status == AnalysisStatus.FAILED
    assert status.overall_status == OverallStatus.ANALYSIS_FAILED
    assert status.latest_error == "disk full"
    assert not (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()

    lines = (run_dir / EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
    last_event = json.loads(lines[-1])
    assert last_event["event_type"] == "analysis_failed"
    assert last_event["error"] == "disk full"


@pytest.mark.unit
def test_run_failure_during_manifest_construction_preserves_markdown_and_records_failed(tmp_path):
    # save_reports() succeeds and writes the full markdown tree; the
    # analysis_date passed to run() is malformed, so building AnalysisManifest
    # raises a pydantic ValidationError -- this happens strictly after
    # save_reports(), so the already-written markdown must be left alone
    # (no rollback) while status/events must still show failed accurately.
    graph = _FakeGraph(_config(), final_state=_final_state())
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    with pytest.raises(ValidationError):
        runner.run("AAPL", "07/03/2026")

    run_dir = tmp_path / "AAPL_20260703_120000"
    assert (run_dir / "complete_report.md").exists()
    assert (run_dir / "1_analysts" / "market.md").exists()
    assert not (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()

    status = RunStatus.model_validate_json((run_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status.analysis_status == AnalysisStatus.FAILED
    assert status.overall_status == OverallStatus.ANALYSIS_FAILED
    assert status.latest_error

    lines = (run_dir / EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
    last_event = json.loads(lines[-1])
    assert last_event["event_type"] == "analysis_failed"
    assert last_event["error"]


# ---------------------------------------------------------------------------
# run_dir collision
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_rejects_existing_run_dir(tmp_path):
    graph = _FakeGraph(_config(), final_state=_final_state())
    runner = DeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)
    runner.run("AAPL", "2026-07-03")

    with pytest.raises(FileExistsError):
        runner.run("AAPL", "2026-07-03")
