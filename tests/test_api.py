"""Read-only backend API (Phase 2A). Uses FastAPI's TestClient (httpx-based,
already an installed transitive dependency) -- no real server process, no
real DeepSeek/LLM call, no access to any real ~/.tradingagents/ path.
Fixtures are built with the same run_contract/run_artifact_writer/reporting
functions the real runners use, never hand-rolled JSON strings.
"""

import threading
import time
from datetime import datetime, timezone

import pytest

# fastapi is an optional dependency (the "api" extra) -- a default install
# (pip install tradingagents, no extras) must not fail test collection just
# because this module imports it. Skip the whole module instead.
pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.config import get_clock, get_runs_dir  # noqa: E402
from api.main import _resolve_run_dir, app  # noqa: E402
from tradingagents.report_field_parsing import extract_report_tree_fields  # noqa: E402
from tradingagents.reporting import write_report_tree  # noqa: E402
from tradingagents.run_artifact_writer import (  # noqa: E402
    append_run_event,
    write_analysis_manifest,
    write_run_status,
)
from tradingagents.run_contract import (  # noqa: E402
    AgentStatus,
    AnalysisManifest,
    AnalysisStatus,
    EventType,
    ReviewStatus,
    RunEvent,
    RunStatus,
    derive_overall_status,
)
from tradingagents.streaming_analysis_runner import StreamingDeepSeekAnalysisRunner  # noqa: E402

CREATED_AT = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)


def _final_state():
    return {
        "market_report": "Market analysis text.",
        "fundamentals_report": "Fundamentals analysis text.",
        "news_report": "News analysis text.",
        # sentiment_report intentionally omitted -> sentiment.md never gets written.
        "investment_debate_state": {
            "bull_history": "Bull case.",
            "bear_history": "Bear case.",
            "judge_decision": (
                "**Recommendation**: Hold\n\n**Rationale**: text\n\n**Strategic Actions**: text"
            ),
        },
        "trader_investment_plan": (
            "**Action**: Hold\n\n**Reasoning**: text\n\nFINAL TRANSACTION PROPOSAL: **HOLD**"
        ),
        "risk_debate_state": {
            "aggressive_history": "Aggressive.",
            "conservative_history": "Conservative.",
            "neutral_history": "Neutral.",
            "judge_decision": (
                "**Rating**: Hold\n\n**Executive Summary**: text\n\n"
                "**Investment Thesis**: text\n\n**Time Horizon**: 3-6 months"
            ),
        },
    }


def _build_completed_run(run_dir, ticker="AAPL", run_id=None):
    run_id = run_id or run_dir.name
    write_report_tree(_final_state(), ticker, run_dir)
    fields = extract_report_tree_fields(run_dir)

    manifest = AnalysisManifest(
        run_id=run_id,
        ticker=ticker,
        analysis_date="2026-07-03",
        created_at=CREATED_AT,
        analysis_status=AnalysisStatus.COMPLETED,
        analysis_provider="deepseek",
        quick_model="deepseek-v4-flash",
        deep_model="deepseek-v4-flash",
        selected_agents=[a for a, s in fields.agent_statuses.items() if s is AgentStatus.COMPLETED],
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
    write_analysis_manifest(run_dir, manifest)

    status = RunStatus(
        run_id=run_id,
        analysis_status=AnalysisStatus.COMPLETED,
        review_status=ReviewStatus.NOT_REQUESTED,
        overall_status=derive_overall_status(AnalysisStatus.COMPLETED, ReviewStatus.NOT_REQUESTED),
        agents=fields.agent_statuses,
        updated_at=CREATED_AT,
    )
    write_run_status(run_dir, status)

    append_run_event(
        run_dir, RunEvent(event_type=EventType.RUN_QUEUED, run_id=run_id, created_at=CREATED_AT)
    )
    append_run_event(
        run_dir,
        RunEvent(event_type=EventType.ANALYSIS_COMPLETED, run_id=run_id, created_at=CREATED_AT),
    )
    return manifest, status


def _build_status_only_run(run_dir, run_id=None, analysis_status=AnalysisStatus.RUNNING):
    run_id = run_id or run_dir.name
    review_status = ReviewStatus.NOT_REQUESTED
    overall = derive_overall_status(analysis_status, review_status)
    status = RunStatus(
        run_id=run_id,
        analysis_status=analysis_status,
        review_status=review_status,
        overall_status=overall,
        agents={},
        updated_at=CREATED_AT,
    )
    write_run_status(run_dir, status)
    return status


POST_TIME = datetime(2026, 7, 3, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_runs_dir] = lambda: tmp_path
    app.dependency_overrides[get_clock] = lambda: (lambda: POST_TIME)
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/runs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_runs_returns_completed_run(client, tmp_path):
    _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["run_id"] == "AAPL_20260703_120000"
    assert body[0]["ticker"] == "AAPL"
    assert body[0]["analysis_status"] == "completed"


@pytest.mark.unit
def test_list_runs_includes_in_progress_run_with_null_ticker(client, tmp_path):
    _build_status_only_run(tmp_path / "AAPL_20260703_130000", analysis_status=AnalysisStatus.RUNNING)

    resp = client.get("/api/runs")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["ticker"] is None
    assert body[0]["analysis_status"] == "running"


@pytest.mark.unit
def test_list_runs_skips_directory_without_status_json(client, tmp_path):
    stray = tmp_path / "not_a_run"
    stray.mkdir()
    (stray / "readme.txt").write_text("hello", encoding="utf-8")

    resp = client.get("/api/runs")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.unit
def test_list_runs_empty_when_runs_dir_missing(tmp_path):
    app.dependency_overrides[get_runs_dir] = lambda: tmp_path / "does_not_exist"
    try:
        resp = TestClient(app).get("/api/runs")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_status_returns_run_status(client, tmp_path):
    _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs/AAPL_20260703_120000/status")

    assert resp.status_code == 200
    assert resp.json()["analysis_status"] == "completed"
    assert resp.json()["overall_status"] == "analysis_completed"


@pytest.mark.unit
def test_get_status_404_for_unknown_run(client):
    resp = client.get("/api/runs/DOES_NOT_EXIST/status")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/manifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_manifest_returns_manifest_when_present(client, tmp_path):
    manifest, _status = _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs/AAPL_20260703_120000/manifest")

    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"
    assert resp.json()["trader_action"] == manifest.trader_action.value


@pytest.mark.unit
def test_get_manifest_404_when_not_yet_written(client, tmp_path):
    _build_status_only_run(tmp_path / "AAPL_20260703_130000")

    resp = client.get("/api/runs/AAPL_20260703_130000/manifest")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/events
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_events_returns_parsed_events_in_order(client, tmp_path):
    _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs/AAPL_20260703_120000/events")

    assert resp.status_code == 200
    event_types = [e["event_type"] for e in resp.json()]
    assert event_types == ["run_queued", "analysis_completed"]


@pytest.mark.unit
def test_get_events_skips_truncated_trailing_line(client, tmp_path):
    run_dir = tmp_path / "AAPL_20260703_120000"
    _build_completed_run(run_dir)
    events_path = run_dir / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as f:
        f.write('{"event_type": "analysis_failed", "run_id": "AAPL_2026070')  # truncated, no newline

    resp = client.get("/api/runs/AAPL_20260703_120000/events")

    assert resp.status_code == 200
    event_types = [e["event_type"] for e in resp.json()]
    assert event_types == ["run_queued", "analysis_completed"]


@pytest.mark.unit
def test_get_events_404_for_unknown_run(client):
    resp = client.get("/api/runs/DOES_NOT_EXIST/events")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/reports/{section}
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_report_returns_markdown_for_existing_section(client, tmp_path):
    _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs/AAPL_20260703_120000/reports/market")

    assert resp.status_code == 200
    assert resp.text == "Market analysis text."
    assert "text/markdown" in resp.headers["content-type"]


@pytest.mark.unit
def test_get_report_returns_complete_report(client, tmp_path):
    _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs/AAPL_20260703_120000/reports/complete_report")

    assert resp.status_code == 200
    assert "Trading Analysis Report" in resp.text


@pytest.mark.unit
def test_get_report_404_for_section_not_written(client, tmp_path):
    # sentiment_report is intentionally absent from _final_state(), so
    # sentiment.md never got written -- this is a normal "agent not
    # selected" case, not a server error.
    _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs/AAPL_20260703_120000/reports/sentiment")

    assert resp.status_code == 404


@pytest.mark.unit
def test_get_report_422_for_unknown_section(client, tmp_path):
    _build_completed_run(tmp_path / "AAPL_20260703_120000")

    resp = client.get("/api/runs/AAPL_20260703_120000/reports/not_a_real_section")

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Path traversal safety
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_run_dir_rejects_dot_dot_directly(tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        _resolve_run_dir(tmp_path, "..")
    assert exc_info.value.status_code == 400


@pytest.mark.unit
def test_resolve_run_dir_rejects_path_with_separator_directly(tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        _resolve_run_dir(tmp_path, "../../etc/passwd")
    assert exc_info.value.status_code == 400


@pytest.mark.unit
def test_resolve_run_dir_rejects_absolute_path_directly(tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        _resolve_run_dir(tmp_path, "/etc/passwd")
    assert exc_info.value.status_code == 400


@pytest.mark.unit
def test_run_id_percent_encoded_dot_dot_never_returns_200(client, tmp_path):
    # A secret file just outside runs_dir (tmp_path's parent) that a
    # traversal exploit would try to reach.
    secret = tmp_path.parent / "secret_outside_runs_dir.txt"
    secret.write_text("should never be served", encoding="utf-8")
    try:
        # %2e%2e decodes server-side to ".." -- must not resolve outside tmp_path.
        resp = client.get("/api/runs/%2e%2e/status")
        assert resp.status_code in (400, 404)
        assert "should never be served" not in resp.text
    finally:
        secret.unlink()


@pytest.mark.unit
def test_run_id_single_dot_rejected(client):
    resp = client.get("/api/runs/%2e/status")
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# POST /api/runs (Phase 2B) -- job worker. No real DeepSeek/TradingAgentsGraph
# anywhere: `_build_graph` is monkeypatched in every test below.
# ---------------------------------------------------------------------------


class _TrivialFakeGraph:
    """Enough to pass StreamingDeepSeekAnalysisRunner.__init__'s validation.
    Used in tests that also monkeypatch .run() itself, so nothing beyond
    .config is ever touched."""

    config = {"llm_provider": "deepseek", "quick_think_llm": "x", "deep_think_llm": "y"}


class _MinimalFakePropagator:
    def create_initial_state(
        self, company_name, trade_date, asset_type="stock", past_context="", instrument_context=""
    ):
        return {}

    def get_graph_args(self, callbacks=None):
        return {"stream_mode": "values", "config": {}}


class _MinimalFakeMemoryLog:
    def get_past_context(self, ticker):
        return ""


class _OneChunkCompiledGraph:
    def stream(self, init_state, **kwargs):
        yield {"market_report": "Market analysis text."}


class _RaisingCompiledGraph:
    def stream(self, init_state, **kwargs):
        raise RuntimeError("boom")


class _MinimalFakeGraph:
    """A real (not mocked-out) StreamingDeepSeekAnalysisRunner.run() can
    execute against this end to end -- used for the tests that need the
    runner's *actual* collision-handling/failure-handling logic to run,
    not just the API's own orchestration."""

    def __init__(self, compiled_graph=None):
        self.config = {"llm_provider": "deepseek", "quick_think_llm": "x", "deep_think_llm": "y"}
        self.propagator = _MinimalFakePropagator()
        self.memory_log = _MinimalFakeMemoryLog()
        self.graph = compiled_graph or _OneChunkCompiledGraph()

    def resolve_instrument_context(self, ticker, asset_type):
        return ticker

    def save_reports(self, final_state, ticker, save_path=None):
        return write_report_tree(final_state, ticker, save_path)


def _expected_run_id(ticker: str) -> str:
    return f"{ticker}_{POST_TIME:%Y%m%d_%H%M%S}"


@pytest.mark.unit
def test_post_runs_does_not_block_and_immediate_gets_see_queued(client, monkeypatch):
    started_event = threading.Event()
    proceed_event = threading.Event()

    def fake_run(self, ticker, analysis_date, *, asset_type="stock", run_id=None, allow_existing_queued_run=False):
        started_event.set()
        proceed_event.wait(timeout=2)

    monkeypatch.setattr("api.main._build_graph", lambda request: _TrivialFakeGraph())
    monkeypatch.setattr(StreamingDeepSeekAnalysisRunner, "run", fake_run)

    t0 = time.monotonic()
    resp = client.post("/api/runs", json={"ticker": "AAPL", "analysis_date": "2026-07-03"})
    elapsed = time.monotonic() - t0

    assert resp.status_code == 202
    assert elapsed < 1.0, "POST waited for the background thread instead of returning immediately"
    run_id = resp.json()["run_id"]
    assert run_id == _expected_run_id("AAPL")
    assert resp.json()["analysis_status"] == "queued"

    # Requirement 1: immediate GET status must be 200 queued, never 404.
    status_resp = client.get(f"/api/runs/{run_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["analysis_status"] == "queued"

    # Requirement 2: immediate GET events must already have run_queued.
    events_resp = client.get(f"/api/runs/{run_id}/events")
    assert events_resp.status_code == 200
    event_types = [e["event_type"] for e in events_resp.json()]
    assert event_types[0] == "run_queued"

    assert started_event.wait(timeout=2), "background thread never started"
    proceed_event.set()  # release the thread so it doesn't leak past the test


@pytest.mark.unit
def test_post_runs_background_thread_takes_over_prewritten_queued_dir(client, monkeypatch):
    # No .run() mock here -- the REAL StreamingDeepSeekAnalysisRunner.run()
    # must take over the queued placeholder api/main.py already wrote,
    # without raising FileExistsError.
    monkeypatch.setattr("api.main._build_graph", lambda request: _MinimalFakeGraph())

    resp = client.post("/api/runs", json={"ticker": "AAPL", "analysis_date": "2026-07-03"})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    status = {}
    for _ in range(50):
        status = client.get(f"/api/runs/{run_id}/status").json()
        if status["analysis_status"] in ("completed", "failed"):
            break
        time.sleep(0.02)

    assert status["analysis_status"] == "completed"


@pytest.mark.unit
def test_post_runs_background_failure_still_returns_202_and_records_failed_status(
    client, monkeypatch
):
    # No .run() mock -- let the real failure-handling inside run() itself
    # write status=failed; the API layer must not reinvent that logic.
    monkeypatch.setattr(
        "api.main._build_graph",
        lambda request: _MinimalFakeGraph(compiled_graph=_RaisingCompiledGraph()),
    )

    resp = client.post("/api/runs", json={"ticker": "AAPL", "analysis_date": "2026-07-03"})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    status = {}
    for _ in range(50):
        status = client.get(f"/api/runs/{run_id}/status").json()
        if status["analysis_status"] == "failed":
            break
        time.sleep(0.02)

    assert status["analysis_status"] == "failed"
    assert status["latest_error"] == "boom"

    events = client.get(f"/api/runs/{run_id}/events").json()
    assert events[-1]["event_type"] == "analysis_failed"
    assert (
        client.get(f"/api/runs/{run_id}/manifest").status_code != 200
    ), "a failed run must not have a manifest"


@pytest.mark.unit
def test_post_runs_rejects_when_run_id_already_completed(client, tmp_path, monkeypatch):
    build_graph_calls = []
    monkeypatch.setattr(
        "api.main._build_graph",
        lambda request: (build_graph_calls.append(request), _TrivialFakeGraph())[1],
    )

    run_id = _expected_run_id("AAPL")
    run_dir = tmp_path / run_id
    _build_completed_run(run_dir, ticker="AAPL", run_id=run_id)
    manifest_before = (run_dir / "analysis_manifest.json").read_text(encoding="utf-8")
    status_before = (run_dir / "status.json").read_text(encoding="utf-8")

    resp = client.post("/api/runs", json={"ticker": "AAPL", "analysis_date": "2026-07-03"})

    assert resp.status_code == 409
    assert build_graph_calls == []
    assert (run_dir / "analysis_manifest.json").read_text(encoding="utf-8") == manifest_before
    assert (run_dir / "status.json").read_text(encoding="utf-8") == status_before


@pytest.mark.unit
def test_post_runs_second_request_for_same_run_id_gets_409(client, monkeypatch):
    proceed_event = threading.Event()

    def fake_run(self, *args, **kwargs):
        proceed_event.wait(timeout=2)

    monkeypatch.setattr("api.main._build_graph", lambda request: _TrivialFakeGraph())
    monkeypatch.setattr(StreamingDeepSeekAnalysisRunner, "run", fake_run)

    resp1 = client.post("/api/runs", json={"ticker": "AAPL", "analysis_date": "2026-07-03"})
    assert resp1.status_code == 202

    resp2 = client.post("/api/runs", json={"ticker": "AAPL", "analysis_date": "2026-07-03"})
    assert resp2.status_code == 409

    proceed_event.set()


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "../../etc", "analysis_date": "2026-07-03"},
        {"ticker": "AAPL", "analysis_date": "07/03/2026"},
        {"ticker": "AAPL", "analysis_date": "2026-07-03", "selected_analysts": []},
        {"ticker": "AAPL", "analysis_date": "2026-07-03", "selected_analysts": ["sentiment"]},
    ],
)
def test_post_runs_rejects_invalid_request_before_dispatch(client, tmp_path, monkeypatch, payload):
    build_calls = []
    run_calls = []
    monkeypatch.setattr(
        "api.main._build_graph",
        lambda request: (build_calls.append(request), _TrivialFakeGraph())[1],
    )
    monkeypatch.setattr(
        StreamingDeepSeekAnalysisRunner, "run", lambda self, *a, **kw: run_calls.append(1)
    )

    resp = client.post("/api/runs", json=payload)

    assert resp.status_code == 422
    assert build_calls == []
    assert run_calls == []
    assert list(tmp_path.iterdir()) == []
