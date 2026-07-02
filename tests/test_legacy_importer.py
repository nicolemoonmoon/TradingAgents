"""Legacy markdown-report importer (Phase 0B).

Every test copies the tracked fixture at
tests/fixtures/legacy_reports/SERVICENOW_20260702_165131/ into tmp_path
before running the importer -- the importer never touches the fixture
directory itself, and tests never depend on the real (gitignored)
reports/ directory on the developer's machine.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradingagents.agents.schemas import PortfolioRating, TraderAction
from tradingagents.legacy_importer import (
    LegacyImportError,
    extract_legacy_fields,
    import_legacy_report_dir,
)
from tradingagents.run_contract import (
    ANALYSIS_MANIFEST_FILENAME,
    STATUS_FILENAME,
    AgentId,
    AgentStatus,
    AnalysisManifest,
    AnalysisStatus,
    OverallStatus,
    ReviewStatus,
    RunStatus,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "legacy_reports" / "SERVICENOW_20260702_165131"


def _copy_fixture(tmp_path, dirname="SERVICENOW_20260702_165131") -> Path:
    dest = tmp_path / dirname
    shutil.copytree(FIXTURE_DIR, dest)
    return dest


# ---------------------------------------------------------------------------
# extract_legacy_fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_legacy_fields_reads_ticker_date_and_created_at_from_dirname(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    extraction = extract_legacy_fields(run_dir)

    assert extraction.ticker == "SERVICENOW"
    assert extraction.analysis_date == "2026-07-02"
    assert extraction.created_at == datetime(2026, 7, 2, 16, 51, 31, tzinfo=timezone.utc)


@pytest.mark.unit
def test_extract_legacy_fields_reads_trader_action_stop_loss_and_position_sizing(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    extraction = extract_legacy_fields(run_dir)

    assert extraction.trader_action == TraderAction.HOLD
    assert extraction.stop_loss == 83.0
    assert extraction.position_sizing is not None
    assert "50%" in extraction.position_sizing


@pytest.mark.unit
def test_extract_legacy_fields_reads_research_manager_recommendation(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    extraction = extract_legacy_fields(run_dir)

    assert extraction.research_manager_recommendation == PortfolioRating.UNDERWEIGHT


@pytest.mark.unit
def test_extract_legacy_fields_reads_draft_rating_and_time_horizon(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    extraction = extract_legacy_fields(run_dir)

    assert extraction.draft_rating == PortfolioRating.HOLD
    assert extraction.time_horizon == "3-6个月，视下一份财报和技术面突破情况动态调整"


@pytest.mark.unit
def test_extract_legacy_fields_marks_all_present_files_as_completed_agents(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    extraction = extract_legacy_fields(run_dir)

    assert extraction.agent_statuses == dict.fromkeys(AgentId, AgentStatus.COMPLETED)


@pytest.mark.unit
def test_extract_legacy_fields_no_data_quality_flags_when_all_fields_parse_cleanly(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    extraction = extract_legacy_fields(run_dir)

    assert extraction.data_quality_flags == []


@pytest.mark.unit
def test_extract_legacy_fields_raises_for_nonexistent_directory(tmp_path):
    with pytest.raises(LegacyImportError):
        extract_legacy_fields(tmp_path / "does_not_exist")


# ---------------------------------------------------------------------------
# import_legacy_report_dir
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_legacy_report_dir_sets_data_quality_assessment_to_legacy_import_limited(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    manifest, _status = import_legacy_report_dir(run_dir)

    assert manifest.data_quality_assessment == "legacy_import_limited"


@pytest.mark.unit
def test_import_legacy_report_dir_leaves_provider_and_model_fields_none(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    manifest, _status = import_legacy_report_dir(run_dir)

    assert manifest.analysis_provider is None
    assert manifest.quick_model is None
    assert manifest.deep_model is None


@pytest.mark.unit
def test_import_legacy_report_dir_writes_valid_manifest_and_status_json_into_run_dir(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    manifest, status = import_legacy_report_dir(run_dir)

    manifest_path = run_dir / ANALYSIS_MANIFEST_FILENAME
    status_path = run_dir / STATUS_FILENAME
    assert manifest_path.exists()
    assert status_path.exists()
    assert AnalysisManifest.model_validate_json(manifest_path.read_text(encoding="utf-8")) == manifest
    assert RunStatus.model_validate_json(status_path.read_text(encoding="utf-8")) == status


@pytest.mark.unit
def test_import_legacy_report_dir_overall_status_is_analysis_completed(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    _manifest, status = import_legacy_report_dir(run_dir)

    assert status.analysis_status == AnalysisStatus.COMPLETED
    assert status.review_status == ReviewStatus.NOT_REQUESTED
    assert status.overall_status == OverallStatus.ANALYSIS_COMPLETED


@pytest.mark.unit
def test_import_legacy_report_dir_default_overwrite_false_raises_on_second_call(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    import_legacy_report_dir(run_dir)

    with pytest.raises(LegacyImportError):
        import_legacy_report_dir(run_dir)


@pytest.mark.unit
def test_import_legacy_report_dir_overwrite_true_reimports_cleanly(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    import_legacy_report_dir(run_dir)

    manifest, status = import_legacy_report_dir(run_dir, overwrite=True)

    assert manifest.data_quality_assessment == "legacy_import_limited"
    assert status.overall_status == OverallStatus.ANALYSIS_COMPLETED


@pytest.mark.unit
def test_import_legacy_report_dir_missing_agent_file_yields_not_selected_no_flag(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    (run_dir / "1_analysts" / "sentiment.md").unlink()

    manifest, status = import_legacy_report_dir(run_dir)

    assert AgentId.SENTIMENT not in manifest.selected_agents
    assert status.agents[AgentId.SENTIMENT] == AgentStatus.NOT_SELECTED
    assert not any("sentiment" in flag for flag in manifest.data_quality_flags)


@pytest.mark.unit
def test_import_legacy_report_dir_existing_file_with_unparseable_field_adds_flag(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    trader_md = run_dir / "3_trading" / "trader.md"
    trader_md.write_text(
        trader_md.read_text(encoding="utf-8").replace("**Action**: Hold", "**Action**: Maybe"),
        encoding="utf-8",
    )

    manifest, _status = import_legacy_report_dir(run_dir)

    assert manifest.trader_action is None
    assert "legacy_import:unparseable_trader_action" in manifest.data_quality_flags


@pytest.mark.unit
def test_import_legacy_report_dir_rejects_bad_dirname(tmp_path):
    bad_dir = _copy_fixture(tmp_path, dirname="not_a_valid_name")

    with pytest.raises(LegacyImportError):
        import_legacy_report_dir(bad_dir)


@pytest.mark.unit
def test_import_legacy_report_dir_rejects_empty_directory(tmp_path):
    empty_dir = tmp_path / "AAPL_20260101_000000"
    empty_dir.mkdir()

    with pytest.raises(LegacyImportError):
        import_legacy_report_dir(empty_dir)


@pytest.mark.unit
def test_import_legacy_report_dir_analysis_status_completed_even_with_partial_files(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    (run_dir / "1_analysts" / "sentiment.md").unlink()
    (run_dir / "1_analysts" / "news.md").unlink()
    (run_dir / "4_risk" / "neutral.md").unlink()

    manifest, status = import_legacy_report_dir(run_dir)

    assert manifest.analysis_status == AnalysisStatus.COMPLETED
    assert status.analysis_status == AnalysisStatus.COMPLETED


@pytest.mark.unit
def test_import_legacy_report_dir_imported_at_param_is_used_verbatim_for_updated_at(tmp_path):
    run_dir = _copy_fixture(tmp_path)
    fixed = datetime(2026, 7, 3, 9, 0, 0, tzinfo=timezone.utc)

    _manifest, status = import_legacy_report_dir(run_dir, imported_at=fixed)

    assert status.updated_at == fixed
