"""Legacy markdown-report importer (Phase 0B).

LEGACY-ONLY: this module is the *only* place in the codebase that parses
rendered markdown via regex to recover structured fields. New live runs
(Phase 1A onward) must build ``AnalysisManifest``/``RunStatus`` directly
from the graph's structured Pydantic outputs (``tradingagents.agents.schemas``),
never by parsing markdown back out -- do not copy this module's approach
into any live-run code path.

Imports an EXISTING new-format report directory (the
``1_analysts/2_research/3_trading/4_risk/5_portfolio`` tree produced by
``tradingagents.reporting.write_report_tree``) and synthesizes
``analysis_manifest.json`` + ``status.json`` into that same directory.
Never constructs the older flat ``reports/{TICKER}/{date}/reports/*.md``
shape.

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


# The report tree's file-to-agent correspondence, per
# tradingagents.reporting.write_report_tree / run_contract.REPORT_TREE.
_AGENT_FILE_MAP: dict[tuple[str, str], AgentId] = {
    ("1_analysts", "market.md"): AgentId.MARKET,
    ("1_analysts", "fundamentals.md"): AgentId.FUNDAMENTALS,
    ("1_analysts", "sentiment.md"): AgentId.SENTIMENT,
    ("1_analysts", "news.md"): AgentId.NEWS,
    ("2_research", "bull.md"): AgentId.BULL,
    ("2_research", "bear.md"): AgentId.BEAR,
    ("2_research", "manager.md"): AgentId.RESEARCH_MANAGER,
    ("3_trading", "trader.md"): AgentId.TRADER,
    ("4_risk", "aggressive.md"): AgentId.AGGRESSIVE_RISK,
    ("4_risk", "neutral.md"): AgentId.NEUTRAL_RISK,
    ("4_risk", "conservative.md"): AgentId.CONSERVATIVE_RISK,
    ("5_portfolio", "decision.md"): AgentId.PORTFOLIO_MANAGER,
}

_DIRNAME_RE = re.compile(r"^(?P<ticker>[^_]+)_(?P<date>\d{8})_(?P<time>\d{6})$")


def _extract_bold_field(text: str, field_name: str) -> str | None:
    pattern = rf"^\*\*{re.escape(field_name)}\*\*:\s*(.+)$"
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip()


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

    agent_statuses: dict[AgentId, AgentStatus] = {}
    texts: dict[AgentId, str] = {}
    flags: list[str] = []

    for (subdir, filename), agent_id in _AGENT_FILE_MAP.items():
        path = run_dir / subdir / filename
        if not path.exists():
            agent_statuses[agent_id] = AgentStatus.NOT_SELECTED
            continue
        agent_statuses[agent_id] = AgentStatus.COMPLETED
        try:
            texts[agent_id] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            flags.append(f"legacy_import:unreadable_{agent_id.value}")

    if not any(status is AgentStatus.COMPLETED for status in agent_statuses.values()):
        raise LegacyImportError(f"no report files found under {run_dir}; nothing to import")

    trader_text = texts.get(AgentId.TRADER)
    manager_text = texts.get(AgentId.RESEARCH_MANAGER)
    decision_text = texts.get(AgentId.PORTFOLIO_MANAGER)

    trader_action: TraderAction | None = None
    if trader_text is not None:
        raw = _extract_bold_field(trader_text, "Action")
        if raw is not None:
            try:
                trader_action = TraderAction(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_trader_action")

    stop_loss: float | None = None
    if trader_text is not None:
        raw = _extract_bold_field(trader_text, "Stop Loss")
        if raw is not None:
            try:
                stop_loss = float(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_stop_loss")

    position_sizing = _extract_bold_field(trader_text, "Position Sizing") if trader_text else None

    research_manager_recommendation: PortfolioRating | None = None
    if manager_text is not None:
        raw = _extract_bold_field(manager_text, "Recommendation")
        if raw is not None:
            try:
                research_manager_recommendation = PortfolioRating(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_research_manager_recommendation")

    draft_rating: PortfolioRating | None = None
    if decision_text is not None:
        raw = _extract_bold_field(decision_text, "Rating")
        if raw is not None:
            try:
                draft_rating = PortfolioRating(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_draft_rating")

    time_horizon = _extract_bold_field(decision_text, "Time Horizon") if decision_text else None

    return LegacyExtraction(
        ticker=ticker,
        analysis_date=analysis_date,
        created_at=created_at,
        draft_rating=draft_rating,
        trader_action=trader_action,
        research_manager_recommendation=research_manager_recommendation,
        stop_loss=stop_loss,
        position_sizing=position_sizing,
        time_horizon=time_horizon,
        agent_statuses=agent_statuses,
        data_quality_flags=flags,
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
