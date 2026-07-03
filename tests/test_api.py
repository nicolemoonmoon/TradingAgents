"""Read-only backend API (Phase 2A). Uses FastAPI's TestClient (httpx-based,
already an installed transitive dependency) -- no real server process, no
real DeepSeek/LLM call, no access to any real ~/.tradingagents/ path.
Fixtures are built with the same run_contract/run_artifact_writer/reporting
functions the real runners use, never hand-rolled JSON strings.
"""

from datetime import datetime, timezone

import pytest

# fastapi is an optional dependency (the "api" extra) -- a default install
# (pip install tradingagents, no extras) must not fail test collection just
# because this module imports it. Skip the whole module instead.
pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.config import get_runs_dir  # noqa: E402
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


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_runs_dir] = lambda: tmp_path
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
