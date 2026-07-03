"""Shared markdown-field extraction for the run report tree (Phase 1A).

Used by both ``tradingagents.legacy_importer`` (historical report
directories) and ``tradingagents.deepseek_analysis_runner`` (freshly-written
live-run report directories): both read the same
``1_analysts/2_research/3_trading/4_risk/5_portfolio`` tree shape produced by
``tradingagents.reporting.write_report_tree``, so the field-extraction logic
is identical regardless of whether the tree is old or brand new. This is a
consequence of the current graph never preserving the raw structured
Pydantic objects (``TraderProposal``/``ResearchPlan``/``PortfolioDecision``)
past their markdown rendering -- see ``deepseek_analysis_runner.py`` for
detail.

Deliberately does not know about run identity (run_id/ticker/analysis_date/
created_at): those come from the directory name for legacy imports and
directly from the caller for live runs, which is why identity parsing stays
out of this shared module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tradingagents.agents.schemas import PortfolioRating, TraderAction
from tradingagents.agents.utils.rating import parse_rating
from tradingagents.run_contract import AgentId, AgentStatus

# The report tree's file-to-agent correspondence, per
# tradingagents.reporting.write_report_tree / run_contract.REPORT_TREE.
AGENT_REPORT_FILE_MAP: dict[tuple[str, str], AgentId] = {
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


def extract_bold_field(text: str, field_name: str) -> str | None:
    """Extract the value of a rendered ``**FieldName**: value`` markdown line."""
    pattern = rf"^\*\*{re.escape(field_name)}\*\*:\s*(.+)$"
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip()


@dataclass(frozen=True)
class ReportTreeFields:
    """Fields extractable purely from an on-disk report tree's markdown content."""

    draft_rating: PortfolioRating | None
    trader_action: TraderAction | None
    research_manager_recommendation: PortfolioRating | None
    stop_loss: float | None
    position_sizing: str | None
    time_horizon: str | None
    agent_statuses: dict[AgentId, AgentStatus] = field(default_factory=dict)
    data_quality_flags: list[str] = field(default_factory=list)


def extract_report_tree_fields(run_dir: Path | str) -> ReportTreeFields:
    """Read the report tree under ``run_dir`` and extract every derivable field.

    Pure with respect to run identity: does not know or care about
    run_id/ticker/analysis_date/created_at. A missing report-tree file
    yields ``AgentStatus.NOT_SELECTED`` for that agent with no
    ``data_quality_flags`` entry (normal agent selection, not a data
    problem); a present-but-unparseable field yields ``None`` plus a
    ``"legacy_import:unparseable_<field>"`` flag.
    """
    run_dir = Path(run_dir)
    agent_statuses: dict[AgentId, AgentStatus] = {}
    texts: dict[AgentId, str] = {}
    flags: list[str] = []

    for (subdir, filename), agent_id in AGENT_REPORT_FILE_MAP.items():
        path = run_dir / subdir / filename
        if not path.exists():
            agent_statuses[agent_id] = AgentStatus.NOT_SELECTED
            continue
        agent_statuses[agent_id] = AgentStatus.COMPLETED
        try:
            texts[agent_id] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            flags.append(f"legacy_import:unreadable_{agent_id.value}")

    trader_text = texts.get(AgentId.TRADER)
    manager_text = texts.get(AgentId.RESEARCH_MANAGER)
    decision_text = texts.get(AgentId.PORTFOLIO_MANAGER)

    trader_action: TraderAction | None = None
    if trader_text is not None:
        raw = extract_bold_field(trader_text, "Action")
        if raw is not None:
            try:
                trader_action = TraderAction(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_trader_action")

    stop_loss: float | None = None
    if trader_text is not None:
        raw = extract_bold_field(trader_text, "Stop Loss")
        if raw is not None:
            try:
                stop_loss = float(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_stop_loss")

    position_sizing = extract_bold_field(trader_text, "Position Sizing") if trader_text else None

    research_manager_recommendation: PortfolioRating | None = None
    if manager_text is not None:
        raw = extract_bold_field(manager_text, "Recommendation")
        if raw is not None:
            try:
                research_manager_recommendation = PortfolioRating(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_research_manager_recommendation")

    # draft_rating reuses the same heuristic propagate() itself relies on
    # (tradingagents.agents.utils.rating.parse_rating) to compute its own
    # "decision" return value from this exact text -- default=None so a
    # miss stays null instead of that function's own "Hold" fallback.
    draft_rating: PortfolioRating | None = None
    if decision_text is not None:
        raw = parse_rating(decision_text, default=None)
        if raw is not None:
            try:
                draft_rating = PortfolioRating(raw)
            except ValueError:
                flags.append("legacy_import:unparseable_draft_rating")

    time_horizon = extract_bold_field(decision_text, "Time Horizon") if decision_text else None

    return ReportTreeFields(
        draft_rating=draft_rating,
        trader_action=trader_action,
        research_manager_recommendation=research_manager_recommendation,
        stop_loss=stop_loss,
        position_sizing=position_sizing,
        time_horizon=time_horizon,
        agent_statuses=agent_statuses,
        data_quality_flags=flags,
    )
