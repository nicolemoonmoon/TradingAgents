"""Read-only backend API for browsing existing run artifacts (Phase 2A).

Does not start new analyses, does not call any LLM/DeepSeek client, does not
serve a UI. Every endpoint only reads files already written by
``tradingagents.deepseek_analysis_runner``/``tradingagents.streaming_analysis_runner``/
``tradingagents.legacy_importer`` under a configured ``runs_dir``
(``api.config.get_runs_dir``).

Path safety: ``run_id`` is resolved via
``tradingagents.run_artifact_writer.resolve_artifact_path`` (the same,
already-tested primitive Phase 0B's writers use) before any filesystem
access -- this matters because ``run_contract.RunId``'s own schema-level
regex does not by itself reject a value of exactly ``"."``/``".."``.
``resolve_artifact_path`` does. Report file paths never take a free-form
path from the caller at all: ``section`` is a closed enum built from
``run_contract.REPORT_TREE`` (code, not user input), so there is no path
string for a request to influence beyond picking one of a fixed set of keys.

Run with: ``uvicorn api.main:app --reload`` (requires the ``api`` extra:
``pip install -e ".[api]"``).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError

from api.config import get_runs_dir
from api.schemas import RunSummary
from tradingagents.run_artifact_writer import ArtifactPathError, resolve_artifact_path
from tradingagents.run_contract import (
    ANALYSIS_MANIFEST_FILENAME,
    COMPLETE_REPORT_FILENAME,
    EVENTS_FILENAME,
    REPORT_TREE,
    STATUS_FILENAME,
    AnalysisManifest,
    RunEvent,
    RunStatus,
)

app = FastAPI(title="TradingAgents Run Artifacts API", version="0.1.0")

# section -> (subdir, filename), built from REPORT_TREE so it can never drift
# from the actual on-disk layout. "complete_report" is the one entry outside
# REPORT_TREE's five subdirectories.
_SECTION_FILES: dict[str, tuple[str, str]] = {
    filename.removesuffix(".md"): (subdir, filename)
    for subdir, filenames in REPORT_TREE.items()
    for filename in filenames
}
_SECTION_FILES["complete_report"] = ("", COMPLETE_REPORT_FILENAME)

ReportSection = Enum("ReportSection", {key.upper(): key for key in _SECTION_FILES}, type=str)


def _resolve_run_dir(runs_dir: Path, run_id: str) -> Path:
    try:
        run_dir = resolve_artifact_path(runs_dir, run_id)
    except ArtifactPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return run_dir


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs(runs_dir: Path = Depends(get_runs_dir)) -> list[RunSummary]:
    if not runs_dir.is_dir():
        return []

    summaries: list[RunSummary] = []
    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        status_path = entry / STATUS_FILENAME
        if not status_path.is_file():
            continue
        try:
            status = RunStatus.model_validate_json(status_path.read_text(encoding="utf-8"))
        except ValidationError:
            continue

        ticker = None
        analysis_date = None
        manifest_path = entry / ANALYSIS_MANIFEST_FILENAME
        if manifest_path.is_file():
            try:
                manifest = AnalysisManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
                ticker = manifest.ticker
                analysis_date = manifest.analysis_date
            except ValidationError:
                pass

        summaries.append(
            RunSummary(
                run_id=entry.name,
                ticker=ticker,
                analysis_date=analysis_date,
                analysis_status=status.analysis_status,
                overall_status=status.overall_status,
            )
        )
    return summaries


@app.get("/api/runs/{run_id}/status", response_model=RunStatus)
def get_status(run_id: str, runs_dir: Path = Depends(get_runs_dir)) -> RunStatus:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    path = run_dir / STATUS_FILENAME
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"status not available for run {run_id!r}")
    return RunStatus.model_validate_json(path.read_text(encoding="utf-8"))


@app.get("/api/runs/{run_id}/manifest", response_model=AnalysisManifest)
def get_manifest(run_id: str, runs_dir: Path = Depends(get_runs_dir)) -> AnalysisManifest:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    path = run_dir / ANALYSIS_MANIFEST_FILENAME
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"manifest not available for run {run_id!r} "
            "(analysis may still be running or may have failed)",
        )
    return AnalysisManifest.model_validate_json(path.read_text(encoding="utf-8"))


@app.get("/api/runs/{run_id}/events", response_model=list[RunEvent])
def get_events(run_id: str, runs_dir: Path = Depends(get_runs_dir)) -> list[RunEvent]:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    path = run_dir / EVENTS_FILENAME
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"events not available for run {run_id!r}")

    events: list[RunEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(RunEvent.model_validate_json(line))
        except ValidationError:
            # Tolerate a truncated trailing line (append_run_event's own
            # documented durability caveat: a crash mid-write can leave one
            # unparsable final line) rather than failing the whole request.
            continue
    return events


@app.get("/api/runs/{run_id}/reports/{section}")
def get_report(
    run_id: str, section: ReportSection, runs_dir: Path = Depends(get_runs_dir)
) -> PlainTextResponse:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    subdir, filename = _SECTION_FILES[section.value]
    path = (run_dir / subdir / filename) if subdir else (run_dir / filename)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"report section {section.value!r} not available for run {run_id!r}",
        )
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")
