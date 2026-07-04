"""Backend API for run artifacts: read-only browsing (Phase 2A), a minimal
job worker to start new analyses (Phase 2B), and a minimal static Web UI
(Phase 2C).

Read endpoints only read files already written by
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

``POST /api/runs`` (Phase 2B) starts a new analysis: it validates the
request, synchronously writes a minimal ``queued`` placeholder
(``status.json`` + a ``run_queued`` event) so a client polling
``GET .../status`` immediately after the response never sees a spurious
404, then hands off to a background ``threading.Thread`` running
``StreamingDeepSeekAnalysisRunner`` (not ``BackgroundTasks`` -- see the
module docstring in ``tradingagents/streaming_analysis_runner.py`` history/
the Phase 2B plan for why: ``TestClient`` waits for ``BackgroundTasks`` to
finish before returning, which makes "the response doesn't block on
analysis completion" untestable). A genuine pre-existing run directory is
rejected with ``409`` before anything is written.

Phase 2E cost/safety guardrail: at most one analysis may be active (queued
or running) per server process at a time, regardless of ticker -- a second
``POST /api/runs`` while one is active gets ``409`` with the current
``active_run_id`` in the body, not just a same-``run_id`` collision check.
This deliberately trades away same-process concurrency for a hard limit on
how many real, billable LLM calls can be in flight at once.

The static Web UI (``api/static/index.html``/``app.js``/``style.css``) is
mounted via ``StaticFiles`` at the very end of this module, after every
``/api/...`` route is registered -- Starlette matches routes in registration
order, so this ordering is what keeps the catch-all static mount from
shadowing the API routes. This is an internal tool with no authentication:
run it bound to ``127.0.0.1`` only, never ``0.0.0.0``.

Run with: ``uvicorn api.main:app --reload --host 127.0.0.1`` (requires the
``api`` extra: ``pip install -e ".[api]"``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from api.config import get_clock, get_runs_dir
from api.schemas import RunSummary, StartAnalysisRequest, StartAnalysisResponse
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.run_artifact_writer import (
    ArtifactPathError,
    append_run_event,
    resolve_artifact_path,
    write_run_status,
)
from tradingagents.run_contract import (
    ANALYSIS_MANIFEST_FILENAME,
    COMPLETE_REPORT_FILENAME,
    EVENTS_FILENAME,
    REPORT_TREE,
    STATUS_FILENAME,
    AnalysisManifest,
    AnalysisStatus,
    EventType,
    ReviewStatus,
    RunEvent,
    RunStatus,
    derive_overall_status,
)
from tradingagents.streaming_analysis_runner import StreamingDeepSeekAnalysisRunner

logger = logging.getLogger(__name__)

app = FastAPI(title="TradingAgents Run Artifacts API", version="0.1.0")

# Single-slot guard (Phase 2E): at most one analysis may be active (queued or
# running) per server process at a time -- a cost/safety guardrail, not just
# a same-run_id collision check like Phase 2B's original per-run_id set. Any
# second POST while this slot is occupied gets 409 regardless of ticker. Does
# NOT protect against multi-process/multi-replica deployments.
_ACTIVE_RUN_LOCK = threading.Lock()
_ACTIVE_RUN_ID: str | None = None

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


def _build_graph(request: StartAnalysisRequest) -> TradingAgentsGraph:
    """Construct the real graph for a live run. The one seam tests replace
    wholesale (via ``monkeypatch.setattr("api.main._build_graph", ...)``) so
    endpoint tests never touch real LLM clients."""
    config = DEFAULT_CONFIG.copy()
    if request.quick_model:
        config["quick_think_llm"] = request.quick_model
    if request.deep_model:
        config["deep_think_llm"] = request.deep_model
    selected_analysts = request.selected_analysts or ("market", "social", "news", "fundamentals")
    return TradingAgentsGraph(selected_analysts=selected_analysts, config=config, debug=False)


def _execute_analysis_job(run_id: str, request: StartAnalysisRequest, runs_dir: Path) -> None:
    """Background thread target. ``StreamingDeepSeekAnalysisRunner.run()`` already
    records failure to status.json/events.jsonl and re-raises -- this wrapper
    just logs it (so it isn't silently lost) and always releases the active-run slot."""
    global _ACTIVE_RUN_ID
    try:
        graph = _build_graph(request)
        runner = StreamingDeepSeekAnalysisRunner(graph, runs_dir=runs_dir)
        runner.run(
            request.ticker,
            request.analysis_date,
            asset_type=request.asset_type,
            run_id=run_id,
            allow_existing_queued_run=True,
            strategy_profile=request.strategy_profile,
        )
    except Exception:
        logger.exception("background analysis job %r failed", run_id)
    finally:
        with _ACTIVE_RUN_LOCK:
            if run_id == _ACTIVE_RUN_ID:
                _ACTIVE_RUN_ID = None


@app.post("/api/runs", status_code=202, response_model=StartAnalysisResponse)
def start_analysis(
    request: StartAnalysisRequest,
    runs_dir: Path = Depends(get_runs_dir),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> StartAnalysisResponse:
    global _ACTIVE_RUN_ID
    created_at = clock()
    run_id = f"{safe_ticker_component(request.ticker)}_{created_at:%Y%m%d_%H%M%S}"
    run_dir = runs_dir / run_id

    with _ACTIVE_RUN_LOCK:
        if _ACTIVE_RUN_ID is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "active_run_exists",
                    "message": (
                        "Another analysis is already running. Only one active "
                        "analysis is allowed per server process."
                    ),
                    "active_run_id": _ACTIVE_RUN_ID,
                },
            )
        if run_dir.exists():
            raise HTTPException(
                status_code=409,
                detail=f"run {run_id!r} already exists; refusing to reuse it for a new run",
            )
        _ACTIVE_RUN_ID = run_id

    try:
        # Synchronous hand-off placeholder: written here, before any thread
        # is spawned, so GET .../status and GET .../events immediately after
        # this response never see a 404 -- filesystem artifacts are the
        # source of truth (Phase 2A already reads them that way). Starting
        # the background thread is inside this try too: a failure at any of
        # these three steps must release the active-run slot, not just a
        # failure writing the placeholder.
        append_run_event(
            run_dir, RunEvent(event_type=EventType.RUN_QUEUED, run_id=run_id, created_at=created_at)
        )
        write_run_status(
            run_dir,
            RunStatus(
                run_id=run_id,
                analysis_status=AnalysisStatus.QUEUED,
                review_status=ReviewStatus.NOT_REQUESTED,
                overall_status=derive_overall_status(
                    AnalysisStatus.QUEUED, ReviewStatus.NOT_REQUESTED
                ),
                agents={},
                updated_at=created_at,
                strategy_profile=request.strategy_profile,
            ),
        )
        thread = threading.Thread(
            target=_execute_analysis_job, args=(run_id, request, runs_dir), daemon=True
        )
        thread.start()
    except Exception:
        with _ACTIVE_RUN_LOCK:
            _ACTIVE_RUN_ID = None
        raise

    return StartAnalysisResponse(
        run_id=run_id,
        analysis_status=AnalysisStatus.QUEUED,
        strategy_profile=request.strategy_profile,
    )


# Mounted last, after every /api/... route above, so this catch-all can never
# shadow them (Starlette matches routes in registration order).
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="ui",
)
