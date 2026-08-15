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

import json
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
from api.schemas import (
    DamagedRun,
    RunListResponse,
    RunSummary,
    StartAnalysisRequest,
    StartAnalysisResponse,
)
from tradingagents.agents.schemas import (
    clear_governed_decision_context,
    set_governed_decision_context,
)
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import (
    DEFAULT_CONFIG,
    get_stockbee_grounding,
    set_active_prompt_grounding,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.knowledge.stockbee_retrieval import SUPPORTED_PROFILES
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
from tradingagents.scanners.unified import (
    AnalysisPurpose,
    SelectionRecordRef,
    SelectionSystem,
    UnifiedCandidate,
    UnifiedCandidateError,
    derive_analysis_governance,
    validate_unified_candidate,
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


@app.get("/api/runs", response_model=RunListResponse)
def list_runs(runs_dir: Path = Depends(get_runs_dir)) -> RunListResponse:
    if not runs_dir.is_dir():
        return RunListResponse(runs=[], damaged_runs=[])

    summaries: list[RunSummary] = []
    damaged: list[DamagedRun] = []
    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        run_id = entry.name
        status_path = entry / STATUS_FILENAME
        if not status_path.is_file():
            # Not a run directory — skip, don't report as damaged.
            continue

        status_raw = status_path.read_text(encoding="utf-8")
        try:
            status_dict = json.loads(status_raw)
        except json.JSONDecodeError:
            damaged.append(
                DamagedRun(
                    run_id=run_id,
                    reason="corrupt_status_json",
                    message=f"status.json for run {run_id!r} is not valid JSON",
                )
            )
            continue
        try:
            status = RunStatus.model_validate(status_dict)
        except ValidationError:
            damaged.append(
                DamagedRun(
                    run_id=run_id,
                    reason="invalid_status_schema",
                    message=f"status.json for run {run_id!r} failed schema validation",
                )
            )
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
            except (ValidationError, ValueError):
                # Corrupt or schema-invalid manifest — keep the run healthy
                # but leave ticker/date as None (never fabricate metadata).
                pass

        summaries.append(
            RunSummary(
                run_id=run_id,
                ticker=ticker,
                analysis_date=analysis_date,
                analysis_status=status.analysis_status,
                overall_status=status.overall_status,
                updated_at=status.updated_at,
            )
        )
    return RunListResponse(runs=summaries, damaged_runs=damaged)


@app.get("/api/runs/{run_id}/status", response_model=RunStatus)
def get_status(run_id: str, runs_dir: Path = Depends(get_runs_dir)) -> RunStatus:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    path = run_dir / STATUS_FILENAME
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"status not available for run {run_id!r}")
    try:
        return RunStatus.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"status.json for run {run_id!r} is corrupted or invalid",
        ) from exc


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
    try:
        return AnalysisManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"analysis_manifest.json for run {run_id!r} is corrupted or invalid",
        ) from exc


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
        except (ValidationError, ValueError):
            # Tolerate a corrupt or truncated line (append_run_event's own
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


def _strategy_profile_is_stockbee(strategy_profile: str | None) -> bool:
    """Return True when the profile is a known frozen Stockbee KB profile.

    KB-independent: checks membership in the frozen ``SUPPORTED_PROFILES``
    registry so a foreign grounding combination can be rejected for a
    Traditional baseline without any frozen-KB I/O.
    """
    return strategy_profile is not None and strategy_profile in SUPPORTED_PROFILES


def _verify_baseline_selection_authority(
    selection_ref: SelectionRecordRef, request_ticker: str
) -> None:
    """Reject a fabricated-but-shape-valid or foreign baseline origin (BR-3/B-08).

    A BASELINE_SYSTEM ``selection_record_ref`` must correspond to an actual
    E02 selection already present in the process-local scanner-candidate feed
    (``_CANDIDATE_FEED``), with matching selection id, selection system, and
    company identity. SR-4: the authoritative candidate's ticker/company
    identity must equal the analyzed request ticker after the repository's
    canonical normalization, so a real AAPL selection can never authorize an
    MSFT baseline analysis.
    """
    if selection_ref.company_id is None:
        raise HTTPException(
            status_code=422,
            detail="baseline selection origin is missing company_id",
        )
    with _CANDIDATE_FEED_LOCK:
        candidate = _CANDIDATE_FEED.get(selection_ref.company_id)
    if candidate is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "baseline selection origin not found in the current E02 "
                "candidate authority"
            ),
        )
    for selection in candidate.selections:
        if (
            selection.selection_id == selection_ref.selection_id
            and selection.selection_system is selection_ref.selection_system
        ):
            # SR-4: bind the analyzed request ticker to the authoritative
            # candidate identity, after canonical ticker normalization.
            if candidate.ticker is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "baseline selection candidate has no public ticker "
                        "identity; cannot authorize a ticker-based analysis"
                    ),
                )
            if normalize_symbol(candidate.ticker) != normalize_symbol(request_ticker):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"baseline selection origin {candidate.ticker!r} cannot "
                        f"authorize analysis of {request_ticker!r}"
                    ),
                )
            return
    raise HTTPException(
        status_code=422,
        detail=(
            "baseline selection origin does not match any selection in the "
            "current E02 candidate authority"
        ),
    )


def _resolve_analysis_governance(request: StartAnalysisRequest):
    """Resolve selection origin -> purpose + portfolio eligibility, fail closed.

    Raises ``HTTPException(422)`` on any ambiguous or foreign origin so the
    synchronous POST returns a clear rejection before any run artifact is
    written.
    """
    selection_ref = None
    if request.selection_record_ref is not None:
        try:
            selection_ref = SelectionRecordRef.from_mapping(request.selection_record_ref)
        except UnifiedCandidateError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid selection_record_ref: {exc}"
            ) from exc
    try:
        return derive_analysis_governance(
            request.system_scope, selection_ref, request.analysis_purpose
        )
    except UnifiedCandidateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_governed_request(request: StartAnalysisRequest):
    """Synchronous fail-closed checks for a governed analysis request."""
    governance = _resolve_analysis_governance(request)
    if governance.analysis_purpose is AnalysisPurpose.BASELINE_SYSTEM:
        # BR-3 / B-08: a baseline selection origin must be a real E02
        # selection already in the process-local candidate authority, not
        # merely a shape-valid client assertion.
        if request.selection_record_ref is None:
            raise HTTPException(
                status_code=422, detail="baseline selection origin is missing"
            )
        selection_ref = SelectionRecordRef.from_mapping(request.selection_record_ref)
        _verify_baseline_selection_authority(selection_ref, request.ticker)
    if governance.system_scope is SelectionSystem.TECHNOLOGY:
        raise HTTPException(
            status_code=422,
            detail="Technology analysis is not connected; reserved for E10.",
        )
    if (
        governance.system_scope is SelectionSystem.TRADITIONAL
        and _strategy_profile_is_stockbee(request.strategy_profile)
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Traditional baseline analysis must never receive Stockbee "
                "methodology grounding."
            ),
        )
    return governance


def _build_graph(request: StartAnalysisRequest) -> TradingAgentsGraph:
    """Construct the real graph for a live run. The one seam tests replace
    wholesale (via ``monkeypatch.setattr("api.main._build_graph", ...)``) so
    endpoint tests never touch real LLM clients."""
    config = DEFAULT_CONFIG.copy()
    if request.quick_model:
        config["quick_think_llm"] = request.quick_model
    if request.deep_model:
        config["deep_think_llm"] = request.deep_model

    # G5: resolve selection origin -> purpose/portfolio eligibility, then
    # thread the governed system_scope into config. The memory log (and any
    # downstream governed snapshot/decision object) reads this scope; a
    # Traditional baseline therefore uses a Traditional memory namespace and
    # never receives foreign grounding. Fails closed on ambiguity.
    governance = _resolve_analysis_governance(request)
    config["system_scope"] = (
        governance.system_scope.value if governance.system_scope else None
    )
    config["analysis_purpose"] = governance.analysis_purpose.value
    config["portfolio_eligible"] = governance.portfolio_eligible

    # Phase 10B.1: Stockbee prompt grounding, now gated by system_scope.
    # A Traditional baseline run must never receive Stockbee grounding; a
    # Pradeep-scoped (or legacy unscoped manual) run may. Reset on every call
    # so stale grounding from a previous profile never leaks.
    set_active_prompt_grounding(None)
    if (
        request.strategy_profile
        and governance.system_scope is not SelectionSystem.TRADITIONAL
    ):
        grounding = get_stockbee_grounding(request.strategy_profile)
        if grounding:
            config["prompt_grounding"] = grounding
            set_active_prompt_grounding(grounding)

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
        governance = _resolve_analysis_governance(request)
        context_token = set_governed_decision_context(
            analysis_purpose=governance.analysis_purpose.value,
            system_scope=(
                governance.system_scope.value if governance.system_scope else None
            ),
            portfolio_eligible=governance.portfolio_eligible,
        )
        try:
            runner.run(
                request.ticker,
                request.analysis_date,
                asset_type=request.asset_type,
                run_id=run_id,
                allow_existing_queued_run=True,
                strategy_profile=request.strategy_profile,
            )
        finally:
            clear_governed_decision_context(context_token)
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
    # G5: fail closed synchronously on ambiguous/foreign origin and on a
    # Traditional baseline that would receive Stockbee grounding — before any
    # run directory or event is written.
    _validate_governed_request(request)
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


def _store_candidate(candidate: UnifiedCandidate) -> UnifiedCandidate:
    """Merge ``candidate`` into the process-local feed, preserving independent
    per-system selections, and return the merged candidate."""
    with _CANDIDATE_FEED_LOCK:
        existing = _CANDIDATE_FEED.get(candidate.company_id)
        if existing is None:
            merged = candidate
        else:
            try:
                merged = UnifiedCandidate(
                    company_id=candidate.company_id,
                    identity_status=candidate.identity_status,
                    ticker=candidate.ticker,
                    selections=existing.selections + candidate.selections,
                    display_name=candidate.display_name or existing.display_name,
                )
            except UnifiedCandidateError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        _CANDIDATE_FEED[candidate.company_id] = merged
    return merged


# E09: process-local scanner-candidate feed. A transient, in-memory-only
# store for already-assembled E02 UnifiedCandidate envelopes (produced
# externally by Traditional/Pradeep scanner runs) -- no database, no
# filesystem persistence, no background task. This is only a temporary
# product data feed for the existing Candidate/Compare surfaces; it carries
# no policy, routing, lifecycle, activation, or persistence authority.
# Keyed by company_id so independent Traditional/Pradeep selections for the
# same company accumulate onto one candidate instead of overwriting it.
_CANDIDATE_FEED_LOCK = threading.Lock()
_CANDIDATE_FEED: dict[str, UnifiedCandidate] = {}


@app.post("/api/scanner-candidates", status_code=201)
def ingest_scanner_candidate(payload: dict) -> dict:
    """Accept one E02 UnifiedCandidate envelope and fail closed on any contract
    violation. Technology is reserved for E10: an envelope containing an
    actual TECHNOLOGY selection is rejected outright."""
    try:
        candidate = validate_unified_candidate(payload)
    except UnifiedCandidateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if any(
        selection.selection_system is SelectionSystem.TECHNOLOGY
        for selection in candidate.selections
    ):
        raise HTTPException(
            status_code=422,
            detail="Technology selections are not connected in E09; reserved for E10.",
        )

    return _store_candidate(candidate).to_dict()


@app.get("/api/scanner-candidates")
def list_scanner_candidates() -> list[dict]:
    with _CANDIDATE_FEED_LOCK:
        return [candidate.to_dict() for candidate in _CANDIDATE_FEED.values()]


# Mounted last, after every /api/... route above, so this catch-all can never
# shadow them (Starlette matches routes in registration order).
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="ui",
)
