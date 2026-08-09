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


def _extract_p_text(body: str, element_id: str) -> str:
    """Whitespace-normalized text content of a ``<p id="...">`` element.

    String-based, not an HTML parser -- relies on none of these particular
    hint paragraphs nesting another tag inside them (true for every id this
    is used with). Avoids both a new parsing dependency and false negatives
    from HTML line-wrapping splitting a phrase across a newline.
    """
    marker = f'id="{element_id}"'
    start = body.index(marker)
    open_tag_end = body.index(">", start) + 1
    close_tag_start = body.index("</p>", open_tag_end)
    return " ".join(body[open_tag_end:close_tag_start].split())


def _extract_section_html(body: str, section_id: str) -> str:
    """Raw HTML of a ``<section id="...">`` element through its first
    ``</section>``. None of this project's tab sections nest another
    ``<section>`` inside them, so the first closing tag after the opening
    one is always the matching one.
    """
    marker = f'<section id="{section_id}"'
    start = body.index(marker)
    end = body.index("</section>", start) + len("</section>")
    return body[start:end]


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


# ---------------------------------------------------------------------------
# Phase 4D: status-cancelled CSS presence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_style_css_has_status_cancelled_label_rule(client):
    """Phase 4D: the #status-label element must have a .status-cancelled
    variant rule so a cancelled run's status text renders with distinct styling
    rather than falling through to the default (unstyled) color."""
    body = client.get("/style.css").text
    assert "#status-label.status-cancelled" in body


@pytest.mark.unit
def test_style_css_has_status_cancelled_badge_rule(client):
    """Phase 4D: the .status-badge component must have a .status-cancelled
    variant rule so cancelled agent status badges are visually distinct from
    the base gray badge style."""
    body = client.get("/style.css").text
    assert ".status-badge.status-cancelled" in body


@pytest.mark.unit
def test_api_routes_still_work_after_static_mount(client):
    # A misordered app.mount("/", StaticFiles(...)) added before the /api/...
    # routes would shadow them entirely (every /api/... request would resolve
    # against the static mount and 404 as "file not found" instead of
    # reaching the real endpoint). This is the regression that matters most.
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == {"runs": [], "damaged_runs": []}

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
def test_index_html_exposes_only_verified_analysis_grounding_profiles(client):
    body = client.get("/").text
    assert 'id="strategy-profile-input"' in body
    assert '<option value="">None / Manual analysis</option>' in body
    assert '<option value="stockbee_momentum_burst">Stockbee — Momentum Burst</option>' in body
    assert '<option value="stockbee_episodic_pivot">Stockbee — Episodic Pivot</option>' in body
    assert "placeholder_pradeep_" not in body


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
def test_shared_run_settings_scope_hint(client):
    # Phase 2K Step 4B: the shared settings block is used by both Start
    # Analysis and a candidate's Analyze action -- Scanner/Compare
    # Board/Load Run never touch it. Scoped to the hint's own text, not a
    # global body assertion, and not an exact-wording match (only stable
    # phrases) so future copy edits don't need to touch this test.
    body = client.get("/").text

    assert body.count('id="shared-run-settings-scope-hint"') == 1

    settings_section = _extract_section_html(body, "shared-run-settings")
    assert 'id="shared-run-settings-scope-hint"' in settings_section

    hint_text = _extract_p_text(body, "shared-run-settings-scope-hint")
    assert hint_text != ""
    for phrase in (
        "used only when you start a real analysis",
        "Discovery",
        "Compare Board",
        "Results",
        "do not use",
    ):
        assert phrase in hint_text


# ---------------------------------------------------------------------------
# Phase 2K Step 5B: navigation defaults -- tab DOM order and the
# checked/hidden state the page loads with. Identified as untested in Step
# 5A's audit: every prior test only checked id/text presence, never order or
# attribute state.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mode_switch_tab_order(client):
    body = client.get("/").text
    mode_switch_html = _extract_section_html(body, "mode-switch")
    positions = {
        tab: mode_switch_html.index(f'id="mode-{tab}"')
        for tab in ("scanner", "candidates", "compare", "new", "load")
    }
    assert positions["scanner"] < positions["candidates"] < positions["compare"]
    assert positions["compare"] < positions["new"] < positions["load"]


@pytest.mark.unit
def test_mode_switch_default_radio_and_panel_state(client):
    body = client.get("/").text
    mode_switch_html = _extract_section_html(body, "mode-switch")

    assert mode_switch_html.count('name="mode"') == 5
    assert mode_switch_html.count("checked") == 1
    assert 'id="mode-scanner" value="scanner" checked' in mode_switch_html

    assert '<section id="scanner-board">' in body
    assert '<section id="new-run-form" hidden>' in body
    assert '<section id="load-run-form" hidden>' in body
    assert '<section id="candidate-board" hidden>' in body
    assert '<section id="compare-board" hidden>' in body


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
@pytest.mark.parametrize(
    "section_id, table_id",
    [
        ("candidate-board", "candidate-table"),
        ("compare-board", "compare-table"),
    ],
)
def test_table_is_wrapped_in_table_scroll(client, section_id, table_id):
    body = client.get("/").text
    assert f'id="{table_id}"' in body

    section_html = _extract_section_html(body, section_id)
    wrapper_start = section_html.index('class="table-scroll"')
    table_start = section_html.index(f'id="{table_id}"')
    table_close = section_html.index("</table>", table_start)
    wrapper_close = section_html.index("</div>", table_close)

    assert wrapper_start < table_start < table_close < wrapper_close


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
# E03: Three-system Discovery UI foundation.
# The legacy DOM ids ``mode-scanner`` / ``scanner-board`` are intentionally
# retained to avoid unrelated JS churn; their user-facing meaning is now
# Discovery. Scanner execution itself remains disconnected in E03.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_index_html_has_discovery_mode(client):
    body = client.get("/").text
    mode_switch = _extract_section_html(body, "mode-switch")
    assert 'id="mode-scanner"' in mode_switch
    assert "Discovery" in mode_switch
    assert "Scanner\n" not in mode_switch


@pytest.mark.unit
def test_discovery_has_three_independent_selection_systems(client):
    body = client.get("/").text
    section = _extract_section_html(body, "scanner-board")
    for system, panel_id in (
        ("TRADITIONAL", "discovery-traditional"),
        ("PRADEEP", "discovery-pradeep"),
        ("TECHNOLOGY", "discovery-technology"),
    ):
        assert f'id="{panel_id}"' in section
        assert f'data-selection-system="{system}"' in section


@pytest.mark.unit
def test_discovery_truthfully_labels_staged_connectivity(client):
    body = client.get("/").text
    section = _extract_section_html(body, "scanner-board")
    for phrase in (
        "Not connected",
        "Scanner not connected",
        "Interface reserved",
        "Technology KB is not built",
        "continuous tracking are not connected",
    ):
        assert phrase in section


@pytest.mark.unit
def test_pradeep_discovery_preserves_scanner_architecture_without_fake_rules(client):
    body = client.get("/").text
    section = _extract_section_html(body, "scanner-board")
    for family in (
        "Momentum Burst",
        "Episodic Pivot",
        "EP 9 Million",
        "MAGNA / MAGNA53",
        "Breakout Anticipation",
    ):
        assert family in section
    for legacy in (
        "placeholder_pradeep_9m",
        "placeholder_pradeep_ep",
        "placeholder_pradeep_magna",
        "placeholder_pradeep_anticipation",
        "price > 3 (placeholder)",
        "day change > 4% (placeholder)",
    ):
        assert legacy not in body


@pytest.mark.unit
def test_discovery_foundation_has_no_scanner_action_controls(client):
    body = client.get("/").text
    section = _extract_section_html(body, "scanner-board")
    assert 'id="discovery-foundation-notice"' in section
    assert 'id="scanner-profile-input"' not in section
    assert 'id="scanner-output-input"' not in section
    assert 'id="scanner-send-button"' not in section
    assert "add tickers manually in Unified Candidate Board" in section


# ---------------------------------------------------------------------------
# Phase 2K Step 3C: each tab's cost/behavior hint must live inside its own
# tab section, not just exist somewhere on the page. Attribution + non-empty
# only -- no exact-wording match, so future copy edits don't need to touch
# this test.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "section_id, hint_id",
    [
        ("candidate-board", "candidate-analysis-cost-hint"),
        ("new-run-form", "start-analysis-cost-hint"),
        ("compare-board", "compare-session-hint"),
        ("load-run-form", "load-run-readonly-hint"),
    ],
)
def test_tab_hint_lives_inside_its_section(client, section_id, hint_id):
    body = client.get("/").text

    assert f'<section id="{section_id}"' in body  # parent section/form exists

    section_html = _extract_section_html(body, section_id)
    assert f'id="{hint_id}"' in section_html  # hint is inside the correct parent

    hint_text = _extract_p_text(body, hint_id)
    assert hint_text != ""  # non-empty


@pytest.mark.unit
def test_run_view_header_has_no_legacy_dash_status_format(client):
    # Phase 3 Step 3D-4: the run header used to be a single "Run: X -- status:
    # Y" line -- replaced with a structured .run-summary block. Structural
    # presence only, no CSS pixel/color assertions.
    body = client.get("/").text
    assert 'class="run-summary"' in body
    assert 'id="run-id-label"' in body
    assert 'id="status-label"' in body
    assert " -- status:" not in body


# ---------------------------------------------------------------------------
# Phase 7C: buildAnalysisPayload null-fallback regression
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_app_js_build_analysis_payload_uses_null_fallback_on_empty_model(client):
    """Phase 7C: buildAnalysisPayload must convert empty/whitespace model
    inputs to null (not send empty strings), so the backend schema validator
    never sees '' for quick_model or deep_model."""
    body = client.get("/app.js").text

    assert "quick_model: quickValue || null" in body
    assert "deep_model: deepValue || null" in body


# ---------------------------------------------------------------------------
# Phase 8B: Scanner / Candidate Board in-memory logic characterization.
# Static source-level assertions only — no JS runtime, no browser.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_app_js_parse_ticker_input_splits_trims_and_filters(client):
    """Phase 8B: parseTickerInput splits on comma, trims whitespace, and
    filters out empty strings — locking down the basic tokenizer contract."""
    body = client.get("/app.js").text
    assert ".split(" in body
    assert ".trim()" in body
    assert ".filter((t) => t.length > 0)" in body


@pytest.mark.unit
def test_app_js_add_candidates_dedup_by_uppercase_ticker(client):
    """Phase 8B: addCandidates deduplicates by uppercase ticker — a candidate
    already in the list (case-insensitive) is not added twice."""
    body = client.get("/app.js").text
    assert "toUpperCase()" in body
    assert "if (seen.has(key)) continue" in body


@pytest.mark.unit
def test_app_js_has_no_legacy_scanner_placeholder_registry(client):
    body = client.get("/app.js").text
    assert "SCANNER_PROFILES" not in body
    assert "scannerProfileInput" not in body
    assert "scannerSendButton" not in body
    assert "placeholder_pradeep_" not in body


@pytest.mark.unit
def test_app_js_discovery_foundation_is_non_executing(client):
    body = client.get("/app.js").text
    marker = "// Discovery foundation (E03):"
    assert marker in body
    block = body[body.index(marker):body.index("renderCandidates();", body.index(marker))]
    assert "fetch(" not in block
    assert "addCandidates(" not in block


@pytest.mark.unit
def test_index_html_has_discovery_foundation_notice(client):
    body = client.get("/").text
    assert 'id="discovery-foundation-notice"' in body
