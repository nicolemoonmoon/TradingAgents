"""StreamingDeepSeekAnalysisRunner (Phase 1C: streaming progress runner).

Bypasses graph.propagate() and drives graph.graph.stream() directly (the
same pattern cli/main.py already uses) to emit real, non-fabricated
agent_completed events as they're observed in stream chunks. No real
DeepSeek/LLM call anywhere -- the graph is a small in-memory fake whose
propagator/graph/memory_log are all hand-built fakes.

Explicitly NOT covered here (Phase 1C scope): checkpoint-aware resume.
This runner does not attach a checkpointer and cannot resume an
interrupted run.
"""

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import PortfolioRating, TraderAction
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
from tradingagents.streaming_analysis_runner import (
    DeepSeekAnalysisRunnerError,
    StreamingDeepSeekAnalysisRunner,
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


def _fixed_clock():
    return FIXED_TIME


def _default_chunks():
    chunk1 = {"market_report": "Market analysis text."}
    chunk2 = {
        **chunk1,
        "sentiment_report": "Sentiment analysis text.",
        "news_report": "News analysis text.",
        "fundamentals_report": "Fundamentals analysis text.",
    }
    chunk3 = {
        **chunk2,
        "investment_debate_state": {"bull_history": "Bull case.", "bear_history": "", "judge_decision": ""},
    }
    chunk4 = {
        **chunk3,
        "investment_debate_state": {**chunk3["investment_debate_state"], "bear_history": "Bear case."},
    }
    chunk5 = {
        **chunk4,
        "investment_debate_state": {
            **chunk4["investment_debate_state"],
            "judge_decision": (
                "**Recommendation**: Underweight\n\n"
                "**Rationale**: Bear arguments win.\n\n"
                "**Strategic Actions**: Reduce position."
            ),
        },
    }
    chunk6 = {
        **chunk5,
        "trader_investment_plan": (
            "**Action**: Hold\n\n**Reasoning**: Wait for confirmation.\n\n"
            "**Stop Loss**: 83.0\n\n**Position Sizing**: Reduce to 50%\n\n"
            "FINAL TRANSACTION PROPOSAL: **HOLD**"
        ),
    }
    chunk7 = {
        **chunk6,
        "risk_debate_state": {
            "aggressive_history": "Aggressive.",
            "conservative_history": "",
            "neutral_history": "",
            "judge_decision": "",
        },
    }
    chunk8 = {
        **chunk7,
        "risk_debate_state": {
            **chunk7["risk_debate_state"],
            "conservative_history": "Conservative.",
            "neutral_history": "Neutral.",
        },
    }
    chunk9 = {
        **chunk8,
        "risk_debate_state": {
            **chunk8["risk_debate_state"],
            "judge_decision": (
                "**Rating**: Hold\n\n**Executive Summary**: Maintain position.\n\n"
                "**Investment Thesis**: Balanced risk/reward.\n\n**Time Horizon**: 3-6 months"
            ),
        },
    }
    return [chunk1, chunk2, chunk3, chunk4, chunk5, chunk6, chunk7, chunk8, chunk9]


class _FakeMemoryLog:
    def __init__(self, past_context=""):
        self.past_context = past_context
        self.get_past_context_calls = []

    def get_past_context(self, ticker):
        self.get_past_context_calls.append(ticker)
        return self.past_context

    def store_decision(self, **kwargs):
        raise AssertionError(
            "store_decision must never be called by StreamingDeepSeekAnalysisRunner"
        )


class _FakePropagator:
    def __init__(self):
        self.create_initial_state_calls = []

    def create_initial_state(
        self, company_name, trade_date, asset_type="stock", past_context="", instrument_context=""
    ):
        self.create_initial_state_calls.append(
            {
                "company_name": company_name,
                "trade_date": trade_date,
                "asset_type": asset_type,
                "past_context": past_context,
                "instrument_context": instrument_context,
            }
        )
        return {}

    def get_graph_args(self, callbacks=None):
        return {"stream_mode": "values", "config": {"recursion_limit": 100}}


class _FakeCompiledGraph:
    def __init__(self, chunks, raise_exc=None, raise_after=None, on_chunk=None):
        self._chunks = chunks
        self._raise_exc = raise_exc
        self._raise_after = raise_after
        self._on_chunk = on_chunk

    def stream(self, init_state, **kwargs):
        for i, chunk in enumerate(self._chunks):
            yield chunk
            if self._on_chunk is not None:
                self._on_chunk(i)
            if self._raise_after is not None and i + 1 == self._raise_after:
                raise self._raise_exc


class _FakeGraph:
    def __init__(
        self,
        config,
        chunks=None,
        raise_exc=None,
        raise_after=None,
        raise_in_save_reports=None,
        past_context="prior lessons text",
        on_chunk=None,
    ):
        self.config = config
        self.propagator = _FakePropagator()
        self.memory_log = _FakeMemoryLog(past_context=past_context)
        self.graph = _FakeCompiledGraph(
            chunks or [], raise_exc=raise_exc, raise_after=raise_after, on_chunk=on_chunk
        )
        self._raise_in_save_reports = raise_in_save_reports
        self.resolve_instrument_context_calls = []
        self.save_reports_calls = []

    def resolve_instrument_context(self, ticker, asset_type):
        self.resolve_instrument_context_calls.append((ticker, asset_type))
        return f"{ticker} ({asset_type})"

    def save_reports(self, final_state, ticker, save_path=None):
        from tradingagents.reporting import write_report_tree

        self.save_reports_calls.append((final_state, ticker, save_path))
        if self._raise_in_save_reports is not None:
            raise self._raise_in_save_reports
        return write_report_tree(final_state, ticker, save_path)

    def _resolve_pending_entries(self, *args, **kwargs):
        raise AssertionError(
            "_resolve_pending_entries must never be called by StreamingDeepSeekAnalysisRunner"
        )


# ---------------------------------------------------------------------------
# __init__ validation (same rule as DeepSeekAnalysisRunner)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("key", ["llm_provider", "quick_think_llm", "deep_think_llm"])
def test_streaming_runner_requires_non_empty_config_fields(tmp_path, key):
    graph = _FakeGraph(_config(**{key: ""}))
    with pytest.raises(DeepSeekAnalysisRunnerError):
        StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_emits_agent_completed_for_every_newly_completed_agent(tmp_path):
    graph = _FakeGraph(_config(), chunks=_default_chunks())
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, status = runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / manifest.run_id
    lines = (run_dir / EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    agent_completed_ids = [e["agent_id"] for e in events if e["event_type"] == "agent_completed"]

    assert set(agent_completed_ids) == {a.value for a in AgentId}
    assert len(agent_completed_ids) == 12  # one per agent, no duplicates


@pytest.mark.unit
def test_run_never_emits_agent_started(tmp_path):
    graph = _FakeGraph(_config(), chunks=_default_chunks())
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, _status = runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / manifest.run_id
    lines = (run_dir / EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
    event_types = {json.loads(line)["event_type"] for line in lines}
    assert "agent_started" not in event_types


@pytest.mark.unit
def test_run_writes_status_json_incrementally_as_chunks_arrive(tmp_path):
    run_dir = tmp_path / "AAPL_20260703_120000"
    captured = []

    def _capture(_chunk_index):
        captured.append(
            RunStatus.model_validate_json((run_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
        )

    graph = _FakeGraph(_config(), chunks=_default_chunks(), on_chunk=_capture)
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    runner.run("AAPL", "2026-07-03")

    # After chunk 1 (MARKET only), status.json must already show MARKET
    # completed -- a real, non-fabricated increment, not a guess.
    assert captured[0].agents.get(AgentId.MARKET) == AgentStatus.COMPLETED
    assert AgentId.TRADER not in captured[0].agents
    # By the last chunk (PORTFOLIO_MANAGER's judge_decision lands), all 12
    # should be visible in the running status already.
    assert captured[-1].agents.get(AgentId.PORTFOLIO_MANAGER) == AgentStatus.COMPLETED
    assert captured[-1].analysis_status == AnalysisStatus.RUNNING


@pytest.mark.unit
def test_run_status_agents_reflects_only_the_agents_that_actually_ran(tmp_path):
    chunks = _default_chunks()
    single_chunk_graph = _FakeGraph(_config(), chunks=[chunks[0]])
    runner = StreamingDeepSeekAnalysisRunner(single_chunk_graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, status = runner.run("AAPL", "2026-07-03")

    # Only MARKET's file exists on disk (write_report_tree only writes
    # sections truthy in final_state), so the final, disk-derived agents map
    # should show MARKET completed and the rest not_selected.
    assert status.agents[AgentId.MARKET] == AgentStatus.COMPLETED
    assert status.agents[AgentId.FUNDAMENTALS] == AgentStatus.NOT_SELECTED
    assert manifest.selected_agents == [AgentId.MARKET]


@pytest.mark.unit
def test_run_success_writes_full_artifact_tree_and_manifest_fields(tmp_path):
    graph = _FakeGraph(_config(), chunks=_default_chunks())
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    manifest, status = runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / manifest.run_id
    assert (run_dir / "complete_report.md").exists()
    assert (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()
    assert (run_dir / STATUS_FILENAME).exists()
    assert (run_dir / EVENTS_FILENAME).exists()

    assert manifest.analysis_status == AnalysisStatus.COMPLETED
    assert manifest.draft_rating == PortfolioRating.HOLD
    assert manifest.trader_action == TraderAction.HOLD
    assert manifest.research_manager_recommendation == PortfolioRating.UNDERWEIGHT
    assert set(manifest.selected_agents) == set(AgentId)
    assert status.overall_status == OverallStatus.ANALYSIS_COMPLETED
    assert status.agents[AgentId.PORTFOLIO_MANAGER] == AgentStatus.COMPLETED


@pytest.mark.unit
def test_run_uses_past_context_and_instrument_context_but_never_writes_memory(tmp_path):
    graph = _FakeGraph(_config(), chunks=_default_chunks(), past_context="learned lesson: X")
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    runner.run("AAPL", "2026-07-03")

    assert graph.memory_log.get_past_context_calls == ["AAPL"]
    assert graph.resolve_instrument_context_calls == [("AAPL", "stock")]
    create_state_call = graph.propagator.create_initial_state_calls[0]
    assert create_state_call["past_context"] == "learned lesson: X"
    assert create_state_call["instrument_context"] == "AAPL (stock)"
    # _resolve_pending_entries / store_decision raise AssertionError if called
    # at all (see _FakeGraph/_FakeMemoryLog) -- reaching this line proves
    # neither was invoked.


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_failure_mid_stream_records_real_partial_agent_progress(tmp_path):
    chunks = _default_chunks()
    # Fail right after chunk 3 (MARKET, SENTIMENT/NEWS/FUNDAMENTALS, BULL done).
    graph = _FakeGraph(_config(), chunks=chunks[:3], raise_exc=RuntimeError("boom"), raise_after=3)
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    with pytest.raises(RuntimeError, match="boom"):
        runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / "AAPL_20260703_120000"
    status = RunStatus.model_validate_json((run_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status.analysis_status == AnalysisStatus.FAILED
    assert status.overall_status == OverallStatus.ANALYSIS_FAILED
    assert status.latest_error == "boom"
    # Real, observed partial progress -- not {} -- because streaming actually
    # saw these agents complete before the failure.
    assert status.agents[AgentId.MARKET] == AgentStatus.COMPLETED
    assert status.agents[AgentId.BULL] == AgentStatus.COMPLETED
    assert AgentId.TRADER not in status.agents

    assert not (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()
    lines = (run_dir / EVENTS_FILENAME).read_text(encoding="utf-8").splitlines()
    last_event = json.loads(lines[-1])
    assert last_event["event_type"] == "analysis_failed"
    assert last_event["error"] == "boom"


@pytest.mark.unit
def test_run_failure_in_save_reports_records_status_failed(tmp_path):
    graph = _FakeGraph(
        _config(), chunks=_default_chunks(), raise_in_save_reports=RuntimeError("disk full")
    )
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    with pytest.raises(RuntimeError, match="disk full"):
        runner.run("AAPL", "2026-07-03")

    run_dir = tmp_path / "AAPL_20260703_120000"
    status = RunStatus.model_validate_json((run_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status.analysis_status == AnalysisStatus.FAILED
    assert status.latest_error == "disk full"
    # All 12 agents had already completed in the stream before save_reports() failed.
    assert status.agents[AgentId.PORTFOLIO_MANAGER] == AgentStatus.COMPLETED
    assert not (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()


@pytest.mark.unit
def test_run_failure_during_manifest_construction_preserves_markdown_and_records_failed(tmp_path):
    graph = _FakeGraph(_config(), chunks=_default_chunks())
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)

    with pytest.raises(ValidationError):
        runner.run("AAPL", "07/03/2026")

    run_dir = tmp_path / "AAPL_20260703_120000"
    assert (run_dir / "complete_report.md").exists()
    assert not (run_dir / ANALYSIS_MANIFEST_FILENAME).exists()

    status = RunStatus.model_validate_json((run_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status.analysis_status == AnalysisStatus.FAILED
    assert status.latest_error


# ---------------------------------------------------------------------------
# run_dir collision
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_rejects_existing_run_dir(tmp_path):
    graph = _FakeGraph(_config(), chunks=_default_chunks())
    runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=tmp_path, clock=_fixed_clock)
    runner.run("AAPL", "2026-07-03")

    with pytest.raises(FileExistsError):
        runner.run("AAPL", "2026-07-03")
