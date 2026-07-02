"""Atomic/append-only writers for run artifacts (Phase 0B).

Covers: path-traversal guard, atomic write of analysis_manifest.json /
status.json (temp file + rename, no half-written reads, overwrite guard),
and append-only events.jsonl writes.
"""

import json
from pathlib import Path

import pytest

from tradingagents.run_artifact_writer import (
    ArtifactPathError,
    append_run_event,
    resolve_artifact_path,
    write_analysis_manifest,
    write_run_status,
)
from tradingagents.run_contract import (
    ANALYSIS_MANIFEST_FILENAME,
    STATUS_FILENAME,
    AnalysisManifest,
    AnalysisStatus,
    EventType,
    OverallStatus,
    ReviewStatus,
    RunEvent,
    RunStatus,
    derive_overall_status,
)

CREATED_AT = "2026-07-01T16:51:31+00:00"


def _manifest(**overrides):
    base = {
        "run_id": "AAPL_20260701_165131",
        "ticker": "AAPL",
        "analysis_date": "2026-07-01",
        "created_at": CREATED_AT,
        "analysis_status": AnalysisStatus.QUEUED,
    }
    base.update(overrides)
    return AnalysisManifest(**base)


def _status(**overrides):
    analysis_status = overrides.pop("analysis_status", AnalysisStatus.COMPLETED)
    review_status = overrides.pop("review_status", ReviewStatus.NOT_REQUESTED)
    base = {
        "run_id": "AAPL_20260701_165131",
        "analysis_status": analysis_status,
        "review_status": review_status,
        "overall_status": derive_overall_status(analysis_status, review_status),
        "updated_at": CREATED_AT,
    }
    base.update(overrides)
    return RunStatus(**base)


def _event(**overrides):
    base = {
        "event_type": EventType.RUN_QUEUED,
        "run_id": "AAPL_20260701_165131",
        "created_at": CREATED_AT,
    }
    base.update(overrides)
    return RunEvent(**base)


# ---------------------------------------------------------------------------
# resolve_artifact_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_artifact_path_accepts_plain_filename_inside_run_dir(tmp_path):
    resolved = resolve_artifact_path(tmp_path, "analysis_manifest.json")
    assert resolved == (tmp_path / "analysis_manifest.json").resolve()


@pytest.mark.unit
@pytest.mark.parametrize(
    "filename",
    [
        "../x",
        "/etc/passwd",
        "a/../../b",
        "sub/x.json",
        "..",
        ".",
        "",
    ],
)
def test_resolve_artifact_path_rejects_unsafe_filenames(tmp_path, filename):
    with pytest.raises(ArtifactPathError):
        resolve_artifact_path(tmp_path, filename)


# ---------------------------------------------------------------------------
# write_analysis_manifest
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_analysis_manifest_creates_file_atomically_with_no_leftover_tmp(tmp_path):
    manifest = _manifest()
    out = write_analysis_manifest(tmp_path, manifest)

    assert out == tmp_path / ANALYSIS_MANIFEST_FILENAME
    assert out.exists()
    round_tripped = AnalysisManifest.model_validate_json(out.read_text(encoding="utf-8"))
    assert round_tripped == manifest
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_write_analysis_manifest_default_overwrite_false_raises_on_second_call(tmp_path):
    write_analysis_manifest(tmp_path, _manifest())
    target = tmp_path / ANALYSIS_MANIFEST_FILENAME
    original_bytes = target.read_bytes()

    with pytest.raises(FileExistsError):
        write_analysis_manifest(tmp_path, _manifest(analysis_status=AnalysisStatus.FAILED))

    assert target.read_bytes() == original_bytes
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_write_analysis_manifest_overwrite_true_replaces_content(tmp_path):
    write_analysis_manifest(tmp_path, _manifest(analysis_status=AnalysisStatus.QUEUED))
    write_analysis_manifest(
        tmp_path, _manifest(analysis_status=AnalysisStatus.FAILED), overwrite=True
    )

    target = tmp_path / ANALYSIS_MANIFEST_FILENAME
    round_tripped = AnalysisManifest.model_validate_json(target.read_text(encoding="utf-8"))
    assert round_tripped.analysis_status == AnalysisStatus.FAILED


@pytest.mark.unit
def test_write_analysis_manifest_serializes_enum_fields_as_plain_strings(tmp_path):
    write_analysis_manifest(tmp_path, _manifest(analysis_status=AnalysisStatus.QUEUED))
    raw = json.loads((tmp_path / ANALYSIS_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert raw["analysis_status"] == "queued"


@pytest.mark.unit
def test_write_functions_create_missing_run_dir(tmp_path):
    run_dir = tmp_path / "nested" / "AAPL_20260701_165131"
    assert not run_dir.exists()

    out = write_analysis_manifest(run_dir, _manifest())

    assert out.exists()
    assert out.parent == run_dir


@pytest.mark.unit
def test_atomic_write_leaves_no_partial_file_on_simulated_failure(tmp_path, monkeypatch):
    def boom(self, target):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "replace", boom)

    with pytest.raises(OSError):
        write_analysis_manifest(tmp_path, _manifest())

    assert not (tmp_path / ANALYSIS_MANIFEST_FILENAME).exists()
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# write_run_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_run_status_default_overwrite_true_allows_repeated_updates(tmp_path):
    write_run_status(tmp_path, _status(analysis_status=AnalysisStatus.QUEUED))
    write_run_status(tmp_path, _status(analysis_status=AnalysisStatus.RUNNING))
    write_run_status(tmp_path, _status(analysis_status=AnalysisStatus.COMPLETED))

    target = tmp_path / STATUS_FILENAME
    round_tripped = RunStatus.model_validate_json(target.read_text(encoding="utf-8"))
    assert round_tripped.analysis_status == AnalysisStatus.COMPLETED
    assert round_tripped.overall_status == OverallStatus.ANALYSIS_COMPLETED
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_write_run_status_overwrite_false_raises_when_file_exists(tmp_path):
    write_run_status(tmp_path, _status(analysis_status=AnalysisStatus.QUEUED))

    with pytest.raises(FileExistsError):
        write_run_status(
            tmp_path, _status(analysis_status=AnalysisStatus.RUNNING), overwrite=False
        )


# ---------------------------------------------------------------------------
# append_run_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_append_run_event_appends_without_truncating_prior_lines(tmp_path):
    append_run_event(tmp_path, _event(event_type=EventType.RUN_QUEUED))
    append_run_event(
        tmp_path,
        _event(event_type=EventType.ANALYSIS_STARTED),
    )

    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = RunEvent.model_validate_json(lines[0])
    second = RunEvent.model_validate_json(lines[1])
    assert first.event_type == EventType.RUN_QUEUED
    assert second.event_type == EventType.ANALYSIS_STARTED


@pytest.mark.unit
def test_append_run_event_creates_file_and_parent_dir_when_missing(tmp_path):
    run_dir = tmp_path / "nested" / "AAPL_20260701_165131"
    out = append_run_event(run_dir, _event())

    assert out == run_dir / "events.jsonl"
    assert out.exists()
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1
