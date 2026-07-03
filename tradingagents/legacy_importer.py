"""Legacy markdown-report importer (Phase 0B).

Imports an EXISTING new-format report directory (the
``1_analysts/2_research/3_trading/4_risk/5_portfolio`` tree produced by
``tradingagents.reporting.write_report_tree``) and synthesizes
``analysis_manifest.json`` + ``status.json`` into that same directory.
Never constructs the older flat ``reports/{TICKER}/{date}/reports/*.md``
shape.

The markdown-field extraction itself (``**Field**: value`` regex parsing)
lives in ``tradingagents.report_field_parsing`` and is shared with the
Phase 1A live runner (``deepseek_analysis_runner.py``) -- both read the same
report-tree shape today, since the graph doesn't preserve structured
Pydantic objects past rendering. This module's own, legacy-specific job is
narrower: turning a ``{TICKER}_{YYYYMMDD}_{HHMMSS}`` directory name into
run identity (ticker/analysis_date/created_at), which only makes sense for
*historical* directories -- a live run already knows its own identity from
the caller and never needs to reverse-engineer it from a directory name.

Never fabricates a field it cannot find: unextractable fields are left
``None``, never guessed. All manifests produced here get
``data_quality_assessment="legacy_import_limited"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tradingagents.agents.schemas import PortfolioRating, TraderAction
from tradingagents.report_field_parsing import extract_report_tree_fields
from tradingagents.run_artifact_writer import write_analysis_manifest, write_run_status
from tradingagents.run_contract import (
    AgentId,
    AgentStatus,
    AnalysisManifest,
    AnalysisStatus,
    ReviewStatus,
    RunStatus,
    derive_overall_status,
)


class LegacyImportError(ValueError):
    """Raised when a directory cannot be safely/faithfully legacy-imported."""


@dataclass(frozen=True)
class LegacyExtraction:
    """Pure extraction result -- no I/O, no model construction, no side effects."""

    ticker: str
    analysis_date: str
    created_at: datetime
    draft_rating: PortfolioRating | None
    trader_action: TraderAction | None
    research_manager_recommendation: PortfolioRating | None
    stop_loss: float | None
    position_sizing: str | None
    time_horizon: str | None
    agent_statuses: dict[AgentId, AgentStatus] = field(default_factory=dict)
    data_quality_flags: list[str] = field(default_factory=list)


_DIRNAME_RE = re.compile(r"^(?P<ticker>[^_]+)_(?P<date>\d{8})_(?P<time>\d{6})$")


def _parse_dirname(name: str) -> tuple[str, str, datetime]:
    match = _DIRNAME_RE.match(name)
    if match is None:
        raise LegacyImportError(
            f"{name!r} does not match the {{TICKER}}_{{YYYYMMDD}}_{{HHMMSS}} "
            "run-directory convention"
        )
    date_str, time_str = match.group("date"), match.group("time")
    try:
        created_at = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise LegacyImportError(f"{name!r} has an invalid date/time component") from exc
    analysis_date = f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return match.group("ticker"), analysis_date, created_at


def extract_legacy_fields(run_dir: Path | str) -> LegacyExtraction:
    """Read-only: parse the report tree under ``run_dir`` and return a ``LegacyExtraction``.

    Raises ``LegacyImportError`` if ``run_dir`` doesn't exist / isn't a
    directory, if its basename doesn't match the
    ``{TICKER}_{YYYYMMDD}_{HHMMSS}`` convention, or if none of the 12
    report-tree files are present.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise LegacyImportError(f"{run_dir} does not exist or is not a directory")

    ticker, analysis_date, created_at = _parse_dirname(run_dir.name)
    fields = extract_report_tree_fields(run_dir)

    if not any(status is AgentStatus.COMPLETED for status in fields.agent_statuses.values()):
        raise LegacyImportError(f"no report files found under {run_dir}; nothing to import")

    return LegacyExtraction(
        ticker=ticker,
        analysis_date=analysis_date,
        created_at=created_at,
        draft_rating=fields.draft_rating,
        trader_action=fields.trader_action,
        research_manager_recommendation=fields.research_manager_recommendation,
        stop_loss=fields.stop_loss,
        position_sizing=fields.position_sizing,
        time_horizon=fields.time_horizon,
        agent_statuses=fields.agent_statuses,
        data_quality_flags=fields.data_quality_flags,
    )


def import_legacy_report_dir(
    run_dir: Path | str,
    *,
    overwrite: bool = False,
    imported_at: datetime | None = None,
) -> tuple[AnalysisManifest, RunStatus]:
    """Extract + build + write ``analysis_manifest.json``/``status.json`` into ``run_dir``.

    ``overwrite`` defaults to ``False``: importing a historical directory is
    normally a one-shot, deliberate action -- re-running it and silently
    overwriting a previous import is more likely a mistake than an intended
    re-import. Pass ``overwrite=True`` to opt in.
    """
    run_dir = Path(run_dir)
    extraction = extract_legacy_fields(run_dir)

    selected_agents = [
        agent_id
        for agent_id in AgentId
        if extraction.agent_statuses.get(agent_id) is AgentStatus.COMPLETED
    ]

    manifest = AnalysisManifest(
        run_id=run_dir.name,
        ticker=extraction.ticker,
        analysis_date=extraction.analysis_date,
        created_at=extraction.created_at,
        analysis_status=AnalysisStatus.COMPLETED,
        analysis_provider=None,
        quick_model=None,
        deep_model=None,
        selected_agents=selected_agents,
        draft_rating=extraction.draft_rating,
        trader_action=extraction.trader_action,
        research_manager_recommendation=extraction.research_manager_recommendation,
        stop_loss=extraction.stop_loss,
        position_sizing=extraction.position_sizing,
        time_horizon=extraction.time_horizon,
        position_context_available=False,
        data_quality_assessment="legacy_import_limited",
        data_quality_flags=extraction.data_quality_flags,
    )

    review_status = ReviewStatus.NOT_REQUESTED
    status = RunStatus(
        run_id=run_dir.name,
        analysis_status=manifest.analysis_status,
        review_status=review_status,
        overall_status=derive_overall_status(manifest.analysis_status, review_status),
        current_stage=None,
        agents=extraction.agent_statuses,
        latest_error=None,
        updated_at=imported_at or datetime.now(timezone.utc),
    )

    try:
        write_analysis_manifest(run_dir, manifest, overwrite=overwrite)
        write_run_status(run_dir, status, overwrite=overwrite)
    except FileExistsError as exc:
        raise LegacyImportError(str(exc)) from exc

    return manifest, status
