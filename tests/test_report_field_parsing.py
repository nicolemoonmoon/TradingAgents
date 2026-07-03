"""Shared report-tree field extraction (Phase 1A), decoupled from legacy
importer's directory-name parsing -- tests operate directly on a copy of
the tracked fixture at tests/fixtures/legacy_reports/SERVICENOW_20260702_165131/.
"""

import shutil
from pathlib import Path

import pytest

from tradingagents.agents.schemas import PortfolioRating, TraderAction
from tradingagents.report_field_parsing import (
    AGENT_REPORT_FILE_MAP,
    AgentId,
    extract_bold_field,
    extract_report_tree_fields,
)
from tradingagents.run_contract import AgentStatus

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "legacy_reports" / "SERVICENOW_20260702_165131"


def _copy_fixture(tmp_path) -> Path:
    dest = tmp_path / "run"
    shutil.copytree(FIXTURE_DIR, dest)
    return dest


@pytest.mark.unit
def test_extract_bold_field_finds_labeled_line():
    text = "**Action**: Hold\n\nsome prose\n"
    assert extract_bold_field(text, "Action") == "Hold"


@pytest.mark.unit
def test_extract_bold_field_returns_none_when_absent():
    assert extract_bold_field("no labeled fields here", "Action") is None


@pytest.mark.unit
def test_extract_report_tree_fields_reads_trader_action_stop_loss_position_sizing(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    fields = extract_report_tree_fields(run_dir)

    assert fields.trader_action == TraderAction.HOLD
    assert fields.stop_loss == 83.0
    assert fields.position_sizing is not None and "50%" in fields.position_sizing


@pytest.mark.unit
def test_extract_report_tree_fields_reads_research_manager_recommendation(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    fields = extract_report_tree_fields(run_dir)

    assert fields.research_manager_recommendation == PortfolioRating.UNDERWEIGHT


@pytest.mark.unit
def test_extract_report_tree_fields_reads_draft_rating_via_parse_rating(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    fields = extract_report_tree_fields(run_dir)

    assert fields.draft_rating == PortfolioRating.HOLD


@pytest.mark.unit
def test_extract_report_tree_fields_flags_draft_rating_missing_when_no_rating_label(tmp_path):
    # Reproduces the real Phase 1A smoke test observation: the Portfolio
    # Manager's structured-output call fell back to free text with no
    # "**Rating**:" label at all, so draft_rating stays None -- this must
    # now be flagged, not silently absent.
    run_dir = _copy_fixture(tmp_path)
    decision_md = run_dir / "5_portfolio" / "decision.md"
    decision_md.write_text(
        "好的，作为投资组合经理，我的最终决定是维持现有仓位不变。",
        encoding="utf-8",
    )

    fields = extract_report_tree_fields(run_dir)

    assert fields.draft_rating is None
    assert "draft_rating_missing" in fields.data_quality_flags
    assert "portfolio_decision_unstructured_or_unparseable" in fields.data_quality_flags


@pytest.mark.unit
def test_extract_report_tree_fields_reads_time_horizon(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    fields = extract_report_tree_fields(run_dir)

    assert fields.time_horizon == "3-6个月，视下一份财报和技术面突破情况动态调整"


@pytest.mark.unit
def test_extract_report_tree_fields_marks_all_present_files_completed(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    fields = extract_report_tree_fields(run_dir)

    assert fields.agent_statuses == dict.fromkeys(AgentId, AgentStatus.COMPLETED)
    assert fields.data_quality_flags == []


@pytest.mark.unit
def test_extract_report_tree_fields_missing_file_yields_not_selected_no_flag(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    (run_dir / "1_analysts" / "sentiment.md").unlink()

    fields = extract_report_tree_fields(run_dir)

    assert fields.agent_statuses[AgentId.SENTIMENT] == AgentStatus.NOT_SELECTED
    assert not any("sentiment" in flag for flag in fields.data_quality_flags)


@pytest.mark.unit
def test_extract_report_tree_fields_missing_stop_loss_line_is_none_not_fabricated(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    trader_md = run_dir / "3_trading" / "trader.md"
    lines = [
        line
        for line in trader_md.read_text(encoding="utf-8").splitlines()
        if not line.startswith("**Stop Loss**:")
    ]
    trader_md.write_text("\n".join(lines), encoding="utf-8")

    fields = extract_report_tree_fields(run_dir)

    assert fields.stop_loss is None
    assert not any("stop_loss" in flag for flag in fields.data_quality_flags)


@pytest.mark.unit
def test_extract_report_tree_fields_empty_run_dir_yields_all_not_selected(tmp_path):
    empty_dir = tmp_path / "empty_run"
    empty_dir.mkdir()

    fields = extract_report_tree_fields(empty_dir)

    assert fields.agent_statuses == dict.fromkeys(AgentId, AgentStatus.NOT_SELECTED)
    assert fields.draft_rating is None
    assert fields.trader_action is None


@pytest.mark.unit
def test_agent_report_file_map_covers_all_twelve_agents():
    assert set(AGENT_REPORT_FILE_MAP.values()) == set(AgentId)
