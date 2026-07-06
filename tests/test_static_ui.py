"""Minimal static Web UI (Phase 2C). Verifies only that the static assets are
served correctly and that mounting StaticFiles doesn't shadow the existing
``/api/...`` routes -- no analysis logic, no DeepSeek call, nothing to mock.
The polling/rendering behavior in app.js itself is verified manually in a
browser against an existing, already-completed run (see the Phase 2C plan);
this repo has no JS test framework and Phase 2C deliberately doesn't add one.
"""

import pytest

# fastapi is an optional dependency (the "api" extra) -- a default install
# (pip install tradingagents, no extras) must not fail test collection just
# because this module imports it. Skip the whole module instead.
pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")

from fastapi.testclient import TestClient  # noqa: E402

from api.config import get_runs_dir  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_runs_dir] = lambda: tmp_path
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_index_html_served_at_root(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert 'id="ticker-input"' in body
    assert 'id="start-button"' in body
    assert 'id="run-id-input"' in body
    assert 'id="load-run-button"' in body


@pytest.mark.unit
def test_app_js_served(client):
    resp = client.get("/app.js")

    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


@pytest.mark.unit
def test_style_css_served(client):
    resp = client.get("/style.css")

    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


@pytest.mark.unit
def test_api_routes_still_work_after_static_mount(client):
    # A misordered app.mount("/", StaticFiles(...)) added before the /api/...
    # routes would shadow them entirely (every /api/... request would resolve
    # against the static mount and 404 as "file not found" instead of
    # reaching the real endpoint). This is the regression that matters most.
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.get("/api/runs/DOES_NOT_EXIST/status")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Phase 2E: MVP guardrail copy -- risk/cost disclaimer, cost-tier hint,
# localhost-binding note. Content-substring checks only, not exact wording.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_html_has_risk_disclaimer(client):
    body = client.get("/").text
    assert "real LLM API calls" in body
    assert "real cost" in body
    assert "research-only analysis" in body
    assert "not trading advice" in body
    assert "never places or automates any order" in body


@pytest.mark.unit
def test_index_html_has_cost_tier_hint(client):
    body = client.get("/").text
    assert 'id="analysts-cost-hint"' in body
    assert "low-cost option" in body
    assert "increases both cost and run time" in body


@pytest.mark.unit
def test_index_html_has_localhost_bind_note(client):
    body = client.get("/").text
    assert 'id="bind-localhost-note"' in body
    assert "127.0.0.1" in body
    assert "0.0.0.0" in body


# ---------------------------------------------------------------------------
# Phase 2F: strategy profile dropdown -- placeholder only, single option.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_html_has_strategy_profile_dropdown_with_placeholder_option(client):
    body = client.get("/").text
    assert 'id="strategy-profile-input"' in body
    assert "None / Manual analysis" in body


# ---------------------------------------------------------------------------
# Phase 2G: Candidate Board -- shared run settings + a third mode tab.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_html_has_shared_run_settings_section(client):
    # Plan A: analysis_date/analysts/models/strategy_profile live in one
    # shared section used by both "Start new analysis" and Candidate Board,
    # not duplicated inside #new-run-form.
    body = client.get("/").text
    assert 'id="shared-run-settings"' in body
    assert 'id="analysis-date-input"' in body
    assert 'id="quick-model-input"' in body
    assert 'id="deep-model-input"' in body
    assert 'id="strategy-profile-input"' in body


@pytest.mark.unit
def test_index_html_has_candidate_board_tab(client):
    body = client.get("/").text
    assert 'id="mode-candidates"' in body
    assert "Candidate Board" in body


@pytest.mark.unit
def test_index_html_has_candidate_board_inputs(client):
    body = client.get("/").text
    assert 'id="candidate-board"' in body
    assert 'id="candidate-ticker-input"' in body
    assert 'id="candidate-add-button"' in body
    assert 'id="candidate-table-body"' in body


@pytest.mark.unit
def test_index_html_existing_start_and_load_ids_still_present(client):
    # Regression guard for the Plan A restructuring: the ids the existing
    # start-run/load-run flows depend on must survive unchanged.
    body = client.get("/").text
    for expected_id in (
        "ticker-input",
        "start-button",
        "reset-button",
        "run-id-input",
        "load-run-button",
        "mode-new",
        "mode-load",
    ):
        assert f'id="{expected_id}"' in body


@pytest.mark.unit
def test_index_html_existing_candidate_board_ids_still_present(client):
    # Regression guard for Phase 2H: Compare Board is additive and must not
    # touch Candidate Board's existing structure.
    body = client.get("/").text
    for expected_id in (
        "mode-candidates",
        "candidate-board",
        "candidate-ticker-input",
        "candidate-add-button",
        "candidate-table-body",
    ):
        assert f'id="{expected_id}"' in body


# ---------------------------------------------------------------------------
# Phase 2H: Compare Board -- reads the same in-memory candidates, no fetch.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_html_has_compare_board_tab(client):
    body = client.get("/").text
    assert 'id="mode-compare"' in body
    assert "Compare Board" in body


@pytest.mark.unit
def test_index_html_has_compare_table_container(client):
    body = client.get("/").text
    assert 'id="compare-board"' in body
    assert 'id="compare-table-body"' in body
    assert 'id="compare-empty-message"' in body


@pytest.mark.unit
def test_index_html_has_human_notes_column_header(client):
    body = client.get("/").text
    assert "Human Notes" in body


# ---------------------------------------------------------------------------
# Phase 2I: Scanner v0 -- pure UI placeholder, no fetch, no new API. Manually
# simulates scanner output and sends it into the same in-memory `candidates`
# array Candidate/Compare Board already render from (verified manually in a
# browser, same as the rest of app.js's dynamic behavior -- see the Phase 2I
# plan).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_html_has_scanner_tab(client):
    body = client.get("/").text
    assert 'id="mode-scanner"' in body
    assert "Scanner" in body


@pytest.mark.unit
def test_index_html_has_scanner_profile_selector_with_placeholder_options(client):
    body = client.get("/").text
    assert 'id="scanner-profile-input"' in body
    for label in (
        "Pradeep 9M placeholder",
        "Pradeep EP placeholder",
        "Pradeep MAGNA placeholder",
        "Pradeep Anticipation placeholder",
    ):
        assert label in body


@pytest.mark.unit
def test_index_html_has_scanner_output_input_and_send_button(client):
    body = client.get("/").text
    assert 'id="scanner-output-input"' in body
    assert 'id="scanner-send-button"' in body
    assert "Send to Candidates" in body


@pytest.mark.unit
def test_index_html_has_scanner_not_connected_notice(client):
    body = client.get("/").text
    assert 'id="scanner-not-connected-notice"' in body
    assert "not connected to real market data" in body
    assert "never calls" in body
    assert "POST /api/runs" in body


@pytest.mark.unit
def test_index_html_existing_ids_still_present_after_scanner_tab(client):
    # Regression guard for Phase 2I: Scanner is additive and must not touch
    # Start/Load/Candidate Board/Compare Board's existing structure.
    body = client.get("/").text
    for expected_id in (
        "ticker-input",
        "start-button",
        "reset-button",
        "run-id-input",
        "load-run-button",
        "mode-new",
        "mode-load",
        "mode-candidates",
        "candidate-board",
        "candidate-ticker-input",
        "candidate-add-button",
        "candidate-table-body",
        "mode-compare",
        "compare-board",
        "compare-table-body",
        "compare-empty-message",
    ):
        assert f'id="{expected_id}"' in body
