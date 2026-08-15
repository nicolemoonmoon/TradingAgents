"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from tradingagents.scanners.unified import (
    AnalysisPurpose,
    SelectionRecordRef,
    SelectionSystem,
    SystemPortfolioContext,
)

# LLMs sometimes write a placeholder string ("None", "N/A", ...) into an optional
# numeric field instead of omitting it. Coerce those to None so the structured
# call validates instead of erroring (#1058). Pydantic still parses real numeric
# strings ("189.5") to float.
_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}


def _coerce_optional_float(value):
    if isinstance(value, str) and value.strip().lower() in _NULLISH_FLOAT:
        return None
    return value


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


class PositionState(str, Enum):
    """Frozen position-state boundary (FZ-ENTRY-001)."""

    NOT_HELD = "NOT_HELD"
    HELD = "HELD"


class EntryDecision(str, Enum):
    """Legal governed entry actions for a NOT_HELD position (FZ-ENTRY-002)."""

    BUY = "BUY"
    WAIT = "WAIT"
    REVIEW = "REVIEW"


class PositionDecision(str, Enum):
    """Legal governed position actions for a HELD position (FZ-POS-002)."""

    HOLD = "HOLD"
    REDUCE = "REDUCE"
    SELL = "SELL"
    REVIEW = "REVIEW"


class ExitReason(str, Enum):
    """Frozen exit reasons X1..X5 (FZ-POS-004..008)."""

    THESIS_BROKEN = "THESIS_BROKEN"
    FORWARD_FUNDAMENTALS_MATERIALLY_DETERIORATED = (
        "FORWARD_FUNDAMENTALS_MATERIALLY_DETERIORATED"
    )
    PRICE_EXTREMELY_DISCONNECTED_FROM_REASONABLE_ECONOMICS = (
        "PRICE_EXTREMELY_DISCONNECTED_FROM_REASONABLE_ECONOMICS"
    )
    BETTER_CAPITAL_ALLOCATION_OPPORTUNITY = "BETTER_CAPITAL_ALLOCATION_OPPORTUNITY"
    PORTFOLIO_RISK = "PORTFOLIO_RISK"


class ExecutionAvailability(str, Enum):
    """Execution availability is separate from investment judgment (FZ-ENTRY)."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


_ENTRY_LEGAL_BY_STATE = {
    PositionState.NOT_HELD: frozenset(
        {EntryDecision.BUY, EntryDecision.WAIT, EntryDecision.REVIEW}
    ),
    PositionState.HELD: frozenset(),
}

_POSITION_LEGAL_BY_STATE = {
    PositionState.HELD: frozenset(
        {PositionDecision.HOLD, PositionDecision.REDUCE, PositionDecision.SELL, PositionDecision.REVIEW}
    ),
    PositionState.NOT_HELD: frozenset(),
}

# Exit reasons that require a same-system portfolio context (FZ-POS-007/008).
_PORTFOLIO_CONTEXT_REQUIRED_EXIT_REASONS = frozenset(
    {
        ExitReason.BETTER_CAPITAL_ALLOCATION_OPPORTUNITY,
        ExitReason.PORTFOLIO_RISK,
    }
)


def validate_entry_decision(position_state: PositionState, decision: EntryDecision) -> None:
    """Fail closed unless ``decision`` is legal for ``position_state``."""
    if decision not in _ENTRY_LEGAL_BY_STATE[position_state]:
        raise ValueError(
            f"illegal entry decision {decision.value!r} for state {position_state.value!r}; "
            "NOT_HELD allows BUY/WAIT/REVIEW only"
        )


def validate_position_decision(
    position_state: PositionState, decision: PositionDecision
) -> None:
    """Fail closed unless ``decision`` is legal for ``position_state``."""
    if decision not in _POSITION_LEGAL_BY_STATE[position_state]:
        raise ValueError(
            f"illegal position decision {decision.value!r} for state {position_state.value!r}; "
            "HELD allows HOLD/REDUCE/SELL/REVIEW only"
        )


def validate_exit_reason(
    reason: ExitReason,
    portfolio_context: SystemPortfolioContext | None = None,
    *,
    consuming_system: SelectionSystem | None = None,
) -> None:
    """Fail closed unless ``reason`` is usable given a same-system portfolio
    context.

    X4 (better capital allocation) and X5 (portfolio risk) may only be
    asserted when a mechanically scoped, same-system portfolio context is
    supplied, and only when a consuming ``system_scope`` is known so the
    context's system can be verified (FZ-PCTX-001/002). Missing context,
    missing consuming system, and foreign context all fail closed. The context
    is a typed ``SystemPortfolioContext`` -- not a caller-supplied boolean
    trust assertion -- so a foreign context is mechanically rejected.
    """
    if reason in _PORTFOLIO_CONTEXT_REQUIRED_EXIT_REASONS:
        if portfolio_context is None:
            raise ValueError(
                f"exit reason {reason.value!r} requires a system-scoped portfolio context"
            )
        if consuming_system is None:
            raise ValueError(
                f"exit reason {reason.value!r} requires a consuming system_scope "
                "to validate a same-system portfolio context"
            )
        if portfolio_context.system_scope is not consuming_system:
            raise ValueError(
                f"exit reason {reason.value!r} cannot use foreign portfolio context "
                f"{portfolio_context.portfolio_context_id!r} scoped to "
                f"{portfolio_context.system_scope.value!r} (consuming "
                f"{consuming_system.value!r})"
            )


def validate_wait_recheck(
    decision: EntryDecision,
    why_wait: str | None,
    what_needs_to_change: str | None,
    recheck_trigger: str | None,
    review_due: str | None,
) -> None:
    """Fail closed unless a WAIT carries full recheck semantics (FZ-ENTRY-004)."""
    if decision is EntryDecision.WAIT:
        missing = [
            name
            for name, value in (
                ("why_wait", why_wait),
                ("what_needs_to_change", what_needs_to_change),
                ("recheck_trigger", recheck_trigger),
                ("review_due", review_due),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "WAIT requires why_wait, what_needs_to_change, recheck_trigger, "
                f"and review_due; missing={missing!r}"
            )


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: float | None = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: float | None = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    position_sizing: str | None = Field(
        default=None,
        description="Optional sizing guidance, e.g. '5% of portfolio'.",
    )
    # Level-2 boundary enrichment (G3): governed entry semantics. Optional and
    # backward-compatible — a plain Buy/Hold/Sell proposal still validates.
    position_state: PositionState = Field(
        default=PositionState.NOT_HELD,
        description=(
            "The governed position state. NOT_HELD for entry evaluation, "
            "HELD for an existing position. Defaults to NOT_HELD."
        ),
    )
    entry_decision: EntryDecision | None = Field(
        default=None,
        description=(
            "Optional governed entry action for NOT_HELD: exactly one of "
            "BUY / WAIT / REVIEW. Execution availability stays a separate field."
        ),
    )
    why_wait: str | None = Field(
        default=None,
        description="Optional: why now is not the moment to enter (required when WAIT).",
    )
    what_needs_to_change: str | None = Field(
        default=None,
        description="Optional: what must change before entry (required when WAIT).",
    )
    recheck_trigger: str | None = Field(
        default=None,
        description="Optional: the trigger that should prompt a recheck (required when WAIT).",
    )
    review_due: str | None = Field(
        default=None,
        description="Optional: when a review is due (required when WAIT).",
    )
    execution_availability: ExecutionAvailability | None = Field(
        default=None,
        description=(
            "Optional: whether execution is currently available, independent "
            "of the investment judgment."
        ),
    )

    @field_validator("entry_price", "stop_loss", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)

    @model_validator(mode="after")
    def _enforce_governed_entry(self):
        # Mechanical runtime enforcement (BR-2): the governed entry state
        # machine is asserted at the structured-output boundary, not only in
        # prompt prose. NOT_HELD -> BUY|WAIT|REVIEW; WAIT requires the full
        # recheck set; HELD never carries an entry decision.
        if self.entry_decision is not None:
            validate_entry_decision(self.position_state, self.entry_decision)
            validate_wait_recheck(
                self.entry_decision,
                self.why_wait,
                self.what_needs_to_change,
                self.recheck_trigger,
                self.review_due,
            )
        return self


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    if proposal.entry_decision is not None:
        parts.extend(["", f"**Entry Decision**: {proposal.entry_decision.value}"])
    if proposal.execution_availability is not None:
        parts.extend(
            ["", f"**Execution Availability**: {proposal.execution_availability.value}"]
        )
    if proposal.entry_decision is EntryDecision.WAIT:
        if proposal.why_wait:
            parts.extend(["", f"**Why Wait**: {proposal.why_wait}"])
        if proposal.what_needs_to_change:
            parts.extend(["", f"**What Needs To Change**: {proposal.what_needs_to_change}"])
        if proposal.recheck_trigger:
            parts.extend(["", f"**Recheck Trigger**: {proposal.recheck_trigger}"])
        if proposal.review_due:
            parts.extend(["", f"**Review Due**: {proposal.review_due}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise action plan covering entry strategy, position sizing, "
            "key risk levels, and time horizon. Two to four sentences."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    price_target: float | None = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    time_horizon: str | None = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )
    # Level-2 boundary enrichment (G4): governed position semantics. Optional
    # and backward-compatible — a plain rating-only decision still validates.
    position_state: PositionState | None = Field(
        default=None,
        description=(
            "Optional governed position state for an existing position: "
            "HELD when reviewing a held position; omit for a fresh entry."
        ),
    )
    position_decision: PositionDecision | None = Field(
        default=None,
        description=(
            "Optional governed position action for HELD: exactly one of "
            "HOLD / REDUCE / SELL / REVIEW."
        ),
    )
    exit_reason: ExitReason | None = Field(
        default=None,
        description=(
            "Optional frozen exit reason X1..X5 (THESIS_BROKEN, "
            "FORWARD_FUNDAMENTALS_MATERIALLY_DETERIORATED, "
            "PRICE_EXTREMELY_DISCONNECTED_FROM_REASONABLE_ECONOMICS, "
            "BETTER_CAPITAL_ALLOCATION_OPPORTUNITY, PORTFOLIO_RISK)."
        ),
    )
    # BR-4: X4/X5 must receive a mechanically scoped, same-system portfolio
    # context -- never a boolean trust assertion. Null in the current runtime
    # (no portfolio engine is authorized), so X4/X5 fail closed.
    portfolio_context: SystemPortfolioContext | None = Field(
        default=None,
        description=(
            "Optional system-scoped portfolio context. Required before an "
            "X4 (better capital allocation) or X5 (portfolio risk) exit reason "
            "can be asserted."
        ),
    )
    # SR-3: the consuming/decision system scope. X4/X5 require a same-system
    # portfolio context; a foreign or missing system_scope fails closed.
    system_scope: SelectionSystem | None = Field(
        default=None,
        description=(
            "The consuming system this decision is scoped to. Required for X4 "
            "and X5 so the portfolio context's system can be verified."
        ),
    )

    @field_validator("price_target", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)

    @model_validator(mode="after")
    def _enforce_governed_position(self):
        # Mechanical runtime enforcement (SR-2/SR-3): HELD -> HOLD|REDUCE|
        # SELL|REVIEW (an explicit position_decision is required); a position
        # decision or exit reason is only legal for a HELD position; X4/X5
        # require a same-system portfolio context verified against this
        # decision's consuming system_scope.
        if self.position_state is PositionState.HELD and self.position_decision is None:
            raise ValueError(
                "position_state=HELD requires position_decision HOLD/REDUCE/SELL/REVIEW"
            )
        if self.position_decision is not None:
            if self.position_state is not PositionState.HELD:
                raise ValueError("position_decision requires position_state=HELD")
            validate_position_decision(self.position_state, self.position_decision)
        if self.exit_reason is not None:
            if self.position_state is not PositionState.HELD:
                raise ValueError("exit_reason requires position_state=HELD")
            validate_exit_reason(
                self.exit_reason,
                self.portfolio_context,
                consuming_system=self.system_scope,
            )
        return self


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    if decision.position_decision is not None:
        parts.extend(["", f"**Position Decision**: {decision.position_decision.value}"])
    if decision.exit_reason is not None:
        parts.extend(["", f"**Exit Reason**: {decision.exit_reason.value}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sentiment Analyst
# ---------------------------------------------------------------------------


class SentimentBand(str, Enum):
    """Discrete sentiment direction produced by the Sentiment Analyst.

    Six tiers keep the signal granular enough to be actionable while remaining
    small enough for every provider to map reliably from its JSON output.
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"
    MILDLY_BEARISH = "Mildly Bearish"
    BEARISH = "Bearish"


class SentimentReport(BaseModel):
    """Structured sentiment report produced by the Sentiment Analyst.

    Replaces the previous free-form prose output so downstream consumers
    (dashboards, audit logs, PDF renderers, other agents) can read
    ``overall_band`` and ``overall_score`` without maintaining fragile regex
    fallbacks that drift with every model release. ``narrative`` preserves the
    rich source-by-source analysis; ``render_sentiment_report`` prepends a
    deterministic header so the saved report stays human-readable.
    """

    overall_band: SentimentBand = Field(
        description=(
            "Overall sentiment direction. Exactly one of: "
            "Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. "
            "Use Mixed when sources point in clearly different directions. "
            "Use Neutral only when all sources are genuinely silent or non-committal."
        ),
    )
    overall_score: float = Field(
        ge=0.0,
        le=10.0,
        description=(
            "Numeric sentiment intensity on a 0–10 scale. "
            "0 = maximally bearish, 5 = neutral, 10 = maximally bullish. "
            "Guideline for consistency with overall_band: "
            "Bullish ~6.5–10, Mildly Bullish ~5.5–6.4, Neutral/Mixed ~4.5–5.5, "
            "Mildly Bearish ~3.5–4.4, Bearish ~0–3.4. "
            "Only the 0–10 bounds are enforced."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "Confidence in the assessment based on data quality and sample size. "
            "Use 'low' when one or more sources returned a placeholder or fewer "
            "than 5 data points; 'medium' when data is present but sparse; "
            "'high' when all three sources returned substantive data."
        ),
    )
    narrative: str = Field(
        description=(
            "Full sentiment report covering, in order: "
            "(1) source-by-source breakdown with specific evidence (cite message "
            "counts, ratios, notable posts); "
            "(2) cross-source divergences and alignments; "
            "(3) dominant narrative themes; "
            "(4) catalysts and risks surfaced by the data; "
            "(5) a markdown table summarising key sentiment signals, their "
            "direction, source, and supporting evidence. "
            "Keep it informative and substantive: develop each section thoroughly "
            "with concrete evidence so every point adds new signal for the trader."
        ),
    )


def render_sentiment_report(report: SentimentReport) -> str:
    """Render a SentimentReport to the markdown shape the rest of the system expects.

    The structured header (band + score + confidence) is prepended to the
    narrative so the saved report is both human-readable and machine-parseable
    without regex.
    """
    return "\n".join([
        f"**Overall Sentiment:** **{report.overall_band.value}** "
        f"(Score: {report.overall_score:.1f}/10)",
        f"**Confidence:** {report.confidence.capitalize()}",
        "",
        report.narrative,
    ])


# ---------------------------------------------------------------------------
# Level-2 boundary enrichment (G7): minimal future interface semantics only.
# No scheduler, no tracking daemon, no persistent Decision Ledger, no Paper
# Portfolio engine. These types only keep future services from being blocked.
# ---------------------------------------------------------------------------


class WaitRecheckInfo(BaseModel):
    """Reusable WAIT recheck semantics (FZ-ENTRY-004): no dead WAIT."""

    why_wait: str = Field(description="Why now is not the moment to act.")
    what_needs_to_change: str = Field(
        description="What must change before the decision can proceed."
    )
    recheck_trigger: str = Field(
        description="The concrete trigger that should prompt a recheck."
    )
    review_due: str = Field(description="When a review is due.")


class ReevaluationRequest(BaseModel):
    """Minimal reevaluation request transport contract (FZ-IF-001/002/003).

    Interface-only: nothing in the current runtime schedules or consumes this.
    Target system and analysis purpose are constrained enums; baseline
    reevaluation must bind its own selection provenance; and a portfolio
    context, when supplied, must be same-system (foreign context rejected).
    """

    request_id: str = Field(description="Unique reevaluation request id.")
    target_system: SelectionSystem = Field(
        description="The system this reevaluation targets (TRADITIONAL/PRADEEP)."
    )
    unified_candidate_ref: str = Field(
        description="The E02 unified candidate this reevaluation concerns."
    )
    selection_record_ref: SelectionRecordRef | None = Field(
        default=None,
        description="Nullable selection origin. Baseline reevaluation must bind its own system provenance.",
    )
    analysis_purpose: AnalysisPurpose = Field(
        description="One of BASELINE_SYSTEM / EXPLORATORY_COMPARE / OWNER_MANUAL_REVIEW."
    )
    reason_code: str = Field(description="Why this reevaluation is being requested.")
    triggered_at: str = Field(description="When the request was triggered.")
    event_or_source_ref: str | None = Field(
        default=None, description="Optional source/event that triggered the request."
    )
    portfolio_context_ref: SystemPortfolioContext | None = Field(
        default=None, description="Nullable system-scoped portfolio context reference."
    )
    data_as_of_hint: str | None = Field(
        default=None, description="Optional data as-of hint for the reevaluation."
    )

    @model_validator(mode="after")
    def _enforce_reevaluation_semantics(self):
        # FZ-IF-002/003: baseline reevaluation requires own-selection
        # provenance whose selection system matches the target system.
        if self.analysis_purpose is AnalysisPurpose.BASELINE_SYSTEM:
            if self.selection_record_ref is None:
                raise ValueError(
                    "a baseline reevaluation requires a selection_record_ref"
                )
            if self.selection_record_ref.selection_system is not self.target_system:
                raise ValueError(
                    "baseline reevaluation selection origin does not match "
                    "target_system"
                )
        # FZ-PCTX: foreign portfolio context must fail closed.
        if (
            self.portfolio_context_ref is not None
            and self.portfolio_context_ref.system_scope is not self.target_system
        ):
            raise ValueError(
                f"foreign portfolio context "
                f"{self.portfolio_context_ref.portfolio_context_id!r} is scoped to "
                f"{self.portfolio_context_ref.system_scope.value!r}, not "
                f"{self.target_system.value!r}"
            )
        return self


# ---------------------------------------------------------------------------
# Governed decision context (SR-2/SR-3).
#
# Threaded from the run boundary to the Trader and Portfolio Manager so
# production validators can distinguish a governed baseline decision from
# legacy/manual free-text, and know the trusted consuming system for X4/X5
# same-system portfolio-context checks. Context-local state prevents a run in
# one thread/task from leaking governance into another execution context.
# ---------------------------------------------------------------------------

_governed_decision_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "governed_decision_context", default=None
)


def set_governed_decision_context(
    *,
    analysis_purpose: str | None,
    system_scope: str | None,
    portfolio_eligible: bool,
) -> Token:
    """Set governed state for this execution context and return its reset token."""
    return _governed_decision_context.set(
        {
            "analysis_purpose": analysis_purpose,
            "system_scope": system_scope,
            "portfolio_eligible": portfolio_eligible,
        }
    )


def clear_governed_decision_context(token: Token | None = None) -> None:
    """Clear governed state, or restore the exact state preceding ``token``."""
    if token is None:
        _governed_decision_context.set(None)
    else:
        _governed_decision_context.reset(token)


def get_governed_decision_context() -> dict[str, Any]:
    return dict(_governed_decision_context.get() or {})


def is_governed_baseline() -> bool:
    """True when the current run is a governed BASELINE_SYSTEM decision."""
    return (
        (_governed_decision_context.get() or {}).get("analysis_purpose")
        == "BASELINE_SYSTEM"
    )


def invoke_governed_structured(
    structured_llm: Any,
    prompt: Any,
    render: Callable[[Any], str],
    agent_name: str,
) -> str:
    """Run a governed structured call that NEVER falls back to unchecked free
    text (SR-2). A provider without structured output, a null result, or any
    validation/render failure raises (fail closed) instead of silently
    accepting free-text BUY/HOLD/SELL."""
    if structured_llm is None:
        raise ValueError(
            f"{agent_name}: governed baseline requires structured output; "
            "the provider does not support with_structured_output"
        )
    result = structured_llm.invoke(prompt)
    if result is None:
        raise ValueError(f"{agent_name}: structured output returned no parsed result")
    return render(result)
