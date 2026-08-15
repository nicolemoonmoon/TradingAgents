"""Tests for structured-output agents (Trader, Research Manager, Sentiment Analyst).

The Portfolio Manager has its own coverage in tests/test_memory_log.py
(which exercises the full memory-log → PM injection cycle).  This file
covers the parallel schemas, render functions, and graceful-fallback
behavior we added for the Trader, Research Manager, and Sentiment Analyst
so they share the same deterministic output shape.
"""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.agents.managers.portfolio_manager import _invoke_governed_pm
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    SentimentBand,
    SentimentReport,
    TraderAction,
    TraderProposal,
    render_research_plan,
    render_sentiment_report,
    render_trader_proposal,
)
from tradingagents.agents.trader.trader import create_trader

# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderTraderProposal:
    def test_minimal_required_fields(self):
        p = TraderProposal(action=TraderAction.HOLD, reasoning="Balanced setup; no edge.")
        md = render_trader_proposal(p)
        assert "**Action**: Hold" in md
        assert "**Reasoning**: Balanced setup; no edge." in md
        # The trailing FINAL TRANSACTION PROPOSAL line is preserved for the
        # analyst stop-signal text and any external code that greps for it.
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in md

    def test_optional_fields_included_when_present(self):
        p = TraderProposal(
            action=TraderAction.BUY,
            reasoning="Strong technicals + fundamentals.",
            entry_price=189.5,
            stop_loss=178.0,
            position_sizing="6% of portfolio",
        )
        md = render_trader_proposal(p)
        assert "**Action**: Buy" in md
        assert "**Entry Price**: 189.5" in md
        assert "**Stop Loss**: 178.0" in md
        assert "**Position Sizing**: 6% of portfolio" in md
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in md

    def test_optional_fields_omitted_when_absent(self):
        p = TraderProposal(action=TraderAction.SELL, reasoning="Guidance cut.")
        md = render_trader_proposal(p)
        assert "Entry Price" not in md
        assert "Stop Loss" not in md
        assert "Position Sizing" not in md
        assert "FINAL TRANSACTION PROPOSAL: **SELL**" in md


@pytest.mark.unit
class TestNullishFloatCoercion:
    """A weak LLM may write "None"/"N/A" into an optional float field (#1058);
    coerce those to None so the structured call validates instead of erroring."""

    def test_trader_nullish_strings_coerce_to_none(self):
        for sentinel in ("None", "N/A", "null", "-", "", "TBD"):
            p = TraderProposal(
                action=TraderAction.HOLD,
                reasoning="x",
                entry_price=sentinel,
                stop_loss=sentinel,
            )
            assert p.entry_price is None
            assert p.stop_loss is None

    def test_trader_real_numeric_string_still_parses(self):
        p = TraderProposal(action=TraderAction.BUY, reasoning="x", entry_price="189.5")
        assert p.entry_price == 189.5

    def test_pm_nullish_price_target_coerces_to_none(self):
        d = PortfolioDecision(
            rating=PortfolioRating.OVERWEIGHT,
            executive_summary="s",
            investment_thesis="t",
            price_target="N/A",
        )
        assert d.price_target is None


@pytest.mark.unit
class TestRenderResearchPlan:
    def test_required_fields(self):
        p = ResearchPlan(
            recommendation=PortfolioRating.OVERWEIGHT,
            rationale="Bull case carried; tailwinds intact.",
            strategic_actions="Build position over two weeks; cap at 5%.",
        )
        md = render_research_plan(p)
        assert "**Recommendation**: Overweight" in md
        assert "**Rationale**: Bull case carried" in md
        assert "**Strategic Actions**: Build position" in md

    def test_all_5_tier_ratings_render(self):
        for rating in PortfolioRating:
            p = ResearchPlan(
                recommendation=rating,
                rationale="r",
                strategic_actions="s",
            )
            md = render_research_plan(p)
            assert f"**Recommendation**: {rating.value}" in md


# ---------------------------------------------------------------------------
# Trader agent: structured happy path + fallback
# ---------------------------------------------------------------------------


def _make_trader_state():
    return {
        "company_of_interest": "NVDA",
        "investment_plan": "**Recommendation**: Buy\n**Rationale**: ...\n**Strategic Actions**: ...",
    }


def _structured_trader_llm(captured: dict, proposal: TraderProposal | None = None):
    """Build a MagicMock LLM whose with_structured_output binding captures the
    prompt and returns a real TraderProposal so render_trader_proposal works.
    """
    if proposal is None:
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="Strong setup.",
        )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or proposal
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
def test_invoke_structured_falls_back_when_result_is_none():
    # A thinking model can answer in plain text, leaving the parser with None.
    # That must fall back to free text, not crash on render(None) (#1051).
    from tradingagents.agents.utils.structured import invoke_structured_or_freetext

    structured = MagicMock()
    structured.invoke.return_value = None
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="FREETEXT")

    out = invoke_structured_or_freetext(
        structured, plain, "prompt", render=lambda r: r.rating, agent_name="t"
    )
    assert out == "FREETEXT"
    plain.invoke.assert_called_once()


@pytest.mark.unit
class TestTraderAgent:
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        proposal = TraderProposal(
            action=TraderAction.BUY,
            reasoning="AI capex cycle intact; institutional flows constructive.",
            entry_price=189.5,
            stop_loss=178.0,
            position_sizing="6% of portfolio",
        )
        llm = _structured_trader_llm(captured, proposal)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        plan = result["trader_investment_plan"]
        assert "**Action**: Buy" in plan
        assert "**Entry Price**: 189.5" in plan
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in plan
        # The same rendered markdown is also added to messages for downstream agents.
        assert plan in result["messages"][0].content

    def test_prompt_includes_investment_plan(self):
        captured = {}
        llm = _structured_trader_llm(captured)
        trader = create_trader(llm)
        trader(_make_trader_state())
        # The investment plan is in the user message of the captured prompt.
        prompt = captured["prompt"]
        assert any("Proposed Investment Plan" in m["content"] for m in prompt)

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = (
            "**Action**: Sell\n\nGuidance cut hits margins.\n\n"
            "FINAL TRANSACTION PROPOSAL: **SELL**"
        )
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        assert result["trader_investment_plan"] == plain_response


# ---------------------------------------------------------------------------
# Research Manager agent: structured happy path + fallback
# ---------------------------------------------------------------------------


def _make_rm_state():
    return {
        "company_of_interest": "NVDA",
        "investment_debate_state": {
            "history": "Bull and bear arguments here.",
            "bull_history": "Bull says...",
            "bear_history": "Bear says...",
            "current_response": "",
            "judge_decision": "",
            "count": 1,
        },
    }


def _structured_rm_llm(captured: dict, plan: ResearchPlan | None = None):
    if plan is None:
        plan = ResearchPlan(
            recommendation=PortfolioRating.HOLD,
            rationale="Balanced view across both sides.",
            strategic_actions="Hold current position; reassess after earnings.",
        )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or plan
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
class TestResearchManagerAgent:
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        plan = ResearchPlan(
            recommendation=PortfolioRating.OVERWEIGHT,
            rationale="Bull case is stronger; AI tailwind intact.",
            strategic_actions="Build position gradually over two weeks.",
        )
        llm = _structured_rm_llm(captured, plan)
        rm = create_research_manager(llm)
        result = rm(_make_rm_state())
        ip = result["investment_plan"]
        assert "**Recommendation**: Overweight" in ip
        assert "**Rationale**: Bull case" in ip
        assert "**Strategic Actions**: Build position" in ip

    def test_prompt_uses_5_tier_rating_scale(self):
        """The RM prompt must list all five tiers so the schema enum matches user expectations."""
        captured = {}
        llm = _structured_rm_llm(captured)
        rm = create_research_manager(llm)
        rm(_make_rm_state())
        prompt = captured["prompt"]
        for tier in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
            assert f"**{tier}**" in prompt, f"missing {tier} in prompt"

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = "**Recommendation**: Sell\n\n**Rationale**: ...\n\n**Strategic Actions**: ..."
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        rm = create_research_manager(llm)
        result = rm(_make_rm_state())
        assert result["investment_plan"] == plain_response


# ---------------------------------------------------------------------------
# Sentiment Analyst: schema, render, structured happy path + fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderSentimentReport:
    def test_header_contains_band_and_score(self):
        report = SentimentReport(
            overall_band=SentimentBand.BULLISH,
            overall_score=7.2,
            confidence="high",
            narrative="Source breakdown here.",
        )
        md = render_sentiment_report(report)
        assert "**Overall Sentiment:** **Bullish**" in md
        assert "(Score: 7.2/10)" in md

    def test_header_contains_confidence(self):
        report = SentimentReport(
            overall_band=SentimentBand.NEUTRAL,
            overall_score=5.0,
            confidence="low",
            narrative="Limited data.",
        )
        assert "**Confidence:** Low" in render_sentiment_report(report)

    def test_narrative_preserved_in_output(self):
        narrative = "## Breakdown\n\nStockTwits: 70% bullish.\n\n| Signal | Direction |\n|---|---|\n| News | Neutral |"
        report = SentimentReport(
            overall_band=SentimentBand.MILDLY_BULLISH,
            overall_score=6.0,
            confidence="medium",
            narrative=narrative,
        )
        assert narrative in render_sentiment_report(report)

    def test_all_six_bands_render(self):
        for band in SentimentBand:
            report = SentimentReport(
                overall_band=band, overall_score=5.0,
                confidence="medium", narrative="n",
            )
            assert band.value in render_sentiment_report(report)

    def test_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            SentimentReport(
                overall_band=SentimentBand.BULLISH, overall_score=11.0,
                confidence="high", narrative="n",
            )


def _make_sentiment_state():
    return {
        "company_of_interest": "NVDA",
        "trade_date": "2026-01-15",
        "asset_type": "stock",
        "messages": [],
    }


def _structured_sentiment_llm(captured: dict, report: SentimentReport | None = None):
    """MagicMock LLM whose structured binding captures the prompt and returns
    a real SentimentReport so render_sentiment_report works."""
    if report is None:
        report = SentimentReport(
            overall_band=SentimentBand.BULLISH, overall_score=7.5,
            confidence="high",
            narrative="StockTwits 75% bullish. News constructive. Reddit upbeat.",
        )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or report
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
class TestSentimentAnalystAgent:
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        report = SentimentReport(
            overall_band=SentimentBand.MILDLY_BEARISH, overall_score=4.0,
            confidence="medium", narrative="Mixed signals across sources.",
        )
        analyst = create_sentiment_analyst(_structured_sentiment_llm(captured, report))
        sr = analyst(_make_sentiment_state())["sentiment_report"]
        assert "**Overall Sentiment:** **Mildly Bearish**" in sr
        assert "(Score: 4.0/10)" in sr
        assert "Mixed signals across sources." in sr

    def test_sentiment_report_also_in_messages(self):
        captured = {}
        analyst = create_sentiment_analyst(_structured_sentiment_llm(captured))
        result = analyst(_make_sentiment_state())
        assert len(result["messages"]) == 1
        assert result["sentiment_report"] == result["messages"][0].content

    def test_prompt_contains_ticker(self):
        captured = {}
        create_sentiment_analyst(_structured_sentiment_llm(captured))(_make_sentiment_state())
        assert any("NVDA" in str(m) for m in captured["prompt"])

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain = "**Overall Sentiment:** **Bearish** (Score: 3.0/10)\n**Confidence:** Low\n\nLimited data."
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain)
        assert create_sentiment_analyst(llm)(_make_sentiment_state())["sentiment_report"] == plain

    def test_falls_back_to_freetext_when_structured_call_fails(self):
        plain = "Fallback free-text sentiment."
        structured = MagicMock()
        structured.invoke.side_effect = ValueError("bad JSON from model")
        llm = MagicMock()
        llm.with_structured_output.return_value = structured
        llm.invoke.return_value = MagicMock(content=plain)
        assert create_sentiment_analyst(llm)(_make_sentiment_state())["sentiment_report"] == plain


# ---------------------------------------------------------------------------
# G3/G4: NOT_HELD / HELD legal-state machine, WAIT recheck, and X1-X5 exit
# reasons (FZ-ENTRY-001..005, FZ-POS-001..008)
# ---------------------------------------------------------------------------


from tradingagents.agents.schemas import (  # noqa: E402
    EntryDecision,
    ExecutionAvailability,
    ExitReason,
    PositionDecision,
    PositionState,
    ReevaluationRequest,
    render_pm_decision,
    validate_entry_decision,
    validate_exit_reason,
    validate_position_decision,
    validate_wait_recheck,
)
from tradingagents.scanners.unified import (  # noqa: E402
    AnalysisPurpose,
    SelectionRecordRef,
    SelectionSystem,
    SystemPortfolioContext,
)


@pytest.mark.unit
class TestEntryStateMachine:
    def test_not_held_allows_buy_wait_review(self):
        for decision in (EntryDecision.BUY, EntryDecision.WAIT, EntryDecision.REVIEW):
            validate_entry_decision(PositionState.NOT_HELD, decision)

    def test_held_rejects_entry_decisions(self):
        with pytest.raises(ValueError, match="illegal entry decision"):
            validate_entry_decision(PositionState.HELD, EntryDecision.BUY)

    def test_held_allows_hold_reduce_sell_review(self):
        for decision in (
            PositionDecision.HOLD,
            PositionDecision.REDUCE,
            PositionDecision.SELL,
            PositionDecision.REVIEW,
        ):
            validate_position_decision(PositionState.HELD, decision)

    def test_not_held_rejects_position_decisions(self):
        with pytest.raises(ValueError, match="illegal position decision"):
            validate_position_decision(PositionState.NOT_HELD, PositionDecision.HOLD)


@pytest.mark.unit
class TestWaitRecheck:
    def test_wait_requires_all_four_recheck_fields(self):
        validate_wait_recheck(EntryDecision.WAIT, "why", "what", "trigger", "2026-08-20")

    def test_wait_without_recheck_fields_fails_closed(self):
        with pytest.raises(ValueError, match="WAIT requires"):
            validate_wait_recheck(EntryDecision.WAIT, None, None, None, None)

    def test_buy_does_not_require_recheck_fields(self):
        validate_wait_recheck(EntryDecision.BUY, None, None, None, None)


@pytest.mark.unit
class TestExitReasons:
    def test_x1_x2_x3_do_not_require_portfolio_context(self):
        for reason in (
            ExitReason.THESIS_BROKEN,
            ExitReason.FORWARD_FUNDAMENTALS_MATERIALLY_DETERIORATED,
            ExitReason.PRICE_EXTREMELY_DISCONNECTED_FROM_REASONABLE_ECONOMICS,
        ):
            validate_exit_reason(reason)

    def test_x4_x5_require_same_system_portfolio_context(self):
        traditional_ctx = SystemPortfolioContext(
            portfolio_context_id="ctx:traditional:1",
            system_scope=SelectionSystem.TRADITIONAL,
            as_of=None,
        )
        pradeep_ctx = SystemPortfolioContext(
            portfolio_context_id="ctx:pradeep:1",
            system_scope=SelectionSystem.PRADEEP,
            as_of=None,
        )
        for reason in (
            ExitReason.BETTER_CAPITAL_ALLOCATION_OPPORTUNITY,
            ExitReason.PORTFOLIO_RISK,
        ):
            # No context -> fail closed.
            with pytest.raises(ValueError, match="portfolio context"):
                validate_exit_reason(reason)
            # Same-system context -> ok.
            validate_exit_reason(
                reason, traditional_ctx, consuming_system=SelectionSystem.TRADITIONAL
            )
            # Foreign context -> mechanically rejected (scoped, not a boolean).
            with pytest.raises(ValueError, match="foreign portfolio context"):
                validate_exit_reason(
                    reason, pradeep_ctx, consuming_system=SelectionSystem.TRADITIONAL
                )


@pytest.mark.unit
class TestGovernedRender:
    def test_trader_proposal_renders_governed_wait_fields(self):
        proposal = TraderProposal(
            action=TraderAction.HOLD,
            reasoning="Not the moment.",
            entry_decision=EntryDecision.WAIT,
            why_wait="extended above the entry zone",
            what_needs_to_change="pull back to support",
            recheck_trigger="daily close below 20 SMA",
            review_due="2026-08-20",
            execution_availability=ExecutionAvailability.AVAILABLE,
        )
        md = render_trader_proposal(proposal)
        assert "**Entry Decision**: WAIT" in md
        assert "**Execution Availability**: AVAILABLE" in md
        assert "**Why Wait**: extended above the entry zone" in md
        assert "**Recheck Trigger**: daily close below 20 SMA" in md

    def test_pm_decision_renders_position_decision_and_exit_reason(self):
        decision = PortfolioDecision(
            rating=PortfolioRating.SELL,
            executive_summary="Exit.",
            investment_thesis="Thesis broken.",
            position_state=PositionState.HELD,
            position_decision=PositionDecision.SELL,
            exit_reason=ExitReason.THESIS_BROKEN,
        )
        md = render_pm_decision(decision)
        assert "**Position Decision**: SELL" in md
        assert "**Exit Reason**: THESIS_BROKEN" in md

    def test_plain_trader_proposal_still_renders_without_new_fields(self):
        md = render_trader_proposal(
            TraderProposal(action=TraderAction.BUY, reasoning="Strong setup.")
        )
        assert "Entry Decision" not in md
        assert "**Action**: Buy" in md


@pytest.mark.unit
class TestReevaluationRequestInterface:
    def test_minimal_reevaluation_request(self):
        request = ReevaluationRequest(
            request_id="req:1",
            target_system=SelectionSystem.TRADITIONAL,
            unified_candidate_ref="ticker:ACME",
            selection_record_ref=SelectionRecordRef(
                "traditional:ACME:1", SelectionSystem.TRADITIONAL, "ticker:ACME"
            ),
            analysis_purpose=AnalysisPurpose.BASELINE_SYSTEM,
            reason_code="REVIEW_DUE",
            triggered_at="2026-08-10T03:00:00+00:00",
        )
        assert request.portfolio_context_ref is None
        assert request.target_system is SelectionSystem.TRADITIONAL

    def test_portfolio_context_ref_is_nullable(self):
        request = ReevaluationRequest(
            request_id="req:2",
            target_system=SelectionSystem.PRADEEP,
            unified_candidate_ref="ticker:ACME",
            analysis_purpose=AnalysisPurpose.OWNER_MANUAL_REVIEW,
            reason_code="MATERIAL_EVENT",
            triggered_at="2026-08-10T03:00:00+00:00",
            portfolio_context_ref=None,
        )
        assert request.portfolio_context_ref is None

    def test_baseline_requires_own_selection_provenance(self):
        with pytest.raises(ValidationError, match="selection_record_ref"):
            ReevaluationRequest(
                request_id="req:3",
                target_system=SelectionSystem.TRADITIONAL,
                unified_candidate_ref="ticker:ACME",
                analysis_purpose=AnalysisPurpose.BASELINE_SYSTEM,
                reason_code="REVIEW_DUE",
                triggered_at="2026-08-10T03:00:00+00:00",
            )

    def test_baseline_rejects_foreign_selection_provenance(self):
        with pytest.raises(ValidationError, match="does not match"):
            ReevaluationRequest(
                request_id="req:4",
                target_system=SelectionSystem.TRADITIONAL,
                unified_candidate_ref="ticker:ACME",
                selection_record_ref=SelectionRecordRef(
                    "pradeep:ACME:1", SelectionSystem.PRADEEP, "ticker:ACME"
                ),
                analysis_purpose=AnalysisPurpose.BASELINE_SYSTEM,
                reason_code="REVIEW_DUE",
                triggered_at="2026-08-10T03:00:00+00:00",
            )

    def test_foreign_portfolio_context_rejected(self):
        foreign = SystemPortfolioContext(
            portfolio_context_id="ctx:pradeep:1",
            system_scope=SelectionSystem.PRADEEP,
            as_of=None,
        )
        with pytest.raises(ValidationError, match="foreign portfolio context"):
            ReevaluationRequest(
                request_id="req:5",
                target_system=SelectionSystem.TRADITIONAL,
                unified_candidate_ref="ticker:ACME",
                analysis_purpose=AnalysisPurpose.OWNER_MANUAL_REVIEW,
                reason_code="MATERIAL_EVENT",
                triggered_at="2026-08-10T03:00:00+00:00",
                portfolio_context_ref=foreign,
            )


# ---------------------------------------------------------------------------
# BR-2: the structured-output schemas themselves mechanically reject illegal
# governed states (production call sites), not just the free validator helpers.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGovernedSchemaEnforcement:
    def test_trader_proposal_rejects_dead_wait(self):
        with pytest.raises(ValidationError, match="WAIT requires"):
            TraderProposal(
                action=TraderAction.HOLD, reasoning="x", entry_decision=EntryDecision.WAIT
            )

    def test_trader_proposal_rejects_held_entry_decision(self):
        with pytest.raises(ValidationError, match="illegal entry decision"):
            TraderProposal(
                action=TraderAction.BUY,
                reasoning="x",
                position_state=PositionState.HELD,
                entry_decision=EntryDecision.BUY,
            )

    def test_portfolio_decision_rejects_x4_x5_without_context(self):
        for reason in (
            ExitReason.BETTER_CAPITAL_ALLOCATION_OPPORTUNITY,
            ExitReason.PORTFOLIO_RISK,
        ):
            with pytest.raises(ValidationError, match="portfolio context"):
                PortfolioDecision(
                    rating=PortfolioRating.SELL,
                    executive_summary="e",
                    investment_thesis="t",
                    position_state=PositionState.HELD,
                    position_decision=PositionDecision.SELL,
                    exit_reason=reason,
                )

    def test_portfolio_decision_rejects_position_decision_without_held(self):
        with pytest.raises(ValidationError, match="position_state=HELD"):
            PortfolioDecision(
                rating=PortfolioRating.SELL,
                executive_summary="e",
                investment_thesis="t",
                position_decision=PositionDecision.SELL,
            )


# ---------------------------------------------------------------------------
# SR-2/SR-3: governed entry/position fail-closed and scoped X4/X5 context.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGovernedEntryFailClosed:
    def test_governed_baseline_entry_requires_entry_decision(self):
        from tradingagents.agents.schemas import (
            clear_governed_decision_context,
            set_governed_decision_context,
        )

        set_governed_decision_context(
            analysis_purpose="BASELINE_SYSTEM",
            system_scope="TRADITIONAL",
            portfolio_eligible=True,
        )
        try:
            captured = {}
            # A governed BASELINE entry with no entry_decision must fail closed
            # rather than render a legacy BUY.
            proposal = TraderProposal(action=TraderAction.BUY, reasoning="Strong setup.")
            llm = _structured_trader_llm(captured, proposal)
            trader = create_trader(llm)
            with pytest.raises(ValueError, match="entry_decision"):
                trader(_make_trader_state())
        finally:
            clear_governed_decision_context()

    def test_governed_invalid_structured_does_not_freetext_fallback(self):
        from tradingagents.agents.schemas import (
            clear_governed_decision_context,
            set_governed_decision_context,
        )

        set_governed_decision_context(
            analysis_purpose="BASELINE_SYSTEM",
            system_scope="TRADITIONAL",
            portfolio_eligible=True,
        )
        try:
            # A thinking model returns None from the structured call. The governed
            # path must fail closed, and must NOT fall back to unchecked free text.
            llm = MagicMock()
            structured = MagicMock()
            structured.invoke.return_value = None
            llm.with_structured_output.return_value = structured
            llm.invoke.return_value = MagicMock(
                content="FINAL TRANSACTION PROPOSAL: **BUY**"
            )
            trader = create_trader(llm)
            with pytest.raises(ValueError, match="no parsed result"):
                trader(_make_trader_state())
            llm.invoke.assert_not_called()
        finally:
            clear_governed_decision_context()


@pytest.mark.unit
class TestGovernedPositionFailClosed:
    def test_held_review_requires_position_decision(self):
        with pytest.raises(ValidationError, match="position_decision"):
            PortfolioDecision(
                rating=PortfolioRating.HOLD,
                executive_summary="e",
                investment_thesis="t",
                position_state=PositionState.HELD,
            )

    def test_traditional_x5_rejects_foreign_pradeep_context(self):
        pradeep_ctx = SystemPortfolioContext(
            portfolio_context_id="ctx:pradeep:1",
            system_scope=SelectionSystem.PRADEEP,
            as_of=None,
        )
        with pytest.raises(ValidationError, match="foreign portfolio context"):
            PortfolioDecision(
                rating=PortfolioRating.SELL,
                executive_summary="e",
                investment_thesis="t",
                position_state=PositionState.HELD,
                position_decision=PositionDecision.SELL,
                exit_reason=ExitReason.PORTFOLIO_RISK,
                portfolio_context=pradeep_ctx,
                system_scope=SelectionSystem.TRADITIONAL,
            )

    def test_x5_requires_consuming_system_scope(self):
        traditional_ctx = SystemPortfolioContext(
            portfolio_context_id="ctx:traditional:1",
            system_scope=SelectionSystem.TRADITIONAL,
            as_of=None,
        )
        with pytest.raises(ValidationError, match="consuming system_scope"):
            PortfolioDecision(
                rating=PortfolioRating.SELL,
                executive_summary="e",
                investment_thesis="t",
                position_state=PositionState.HELD,
                position_decision=PositionDecision.SELL,
                exit_reason=ExitReason.PORTFOLIO_RISK,
                portfolio_context=traditional_ctx,
            )

    def test_contract_oracle_allows_same_system_context_independent_of_llm(self):
        traditional_ctx = SystemPortfolioContext(
            portfolio_context_id="ctx:traditional:1",
            system_scope=SelectionSystem.TRADITIONAL,
            as_of=None,
        )
        traditional_ctx.require_system_scope(SelectionSystem.TRADITIONAL)
        decision = PortfolioDecision(
            rating=PortfolioRating.SELL,
            executive_summary="e",
            investment_thesis="t",
            position_state=PositionState.HELD,
            position_decision=PositionDecision.SELL,
            exit_reason=ExitReason.PORTFOLIO_RISK,
            portfolio_context=traditional_ctx,
            system_scope=SelectionSystem.TRADITIONAL,
        )
        assert decision.exit_reason is ExitReason.PORTFOLIO_RISK

    def test_model_supplied_same_system_context_is_rejected_before_render(
        self, monkeypatch
    ):
        traditional_ctx = SystemPortfolioContext(
            portfolio_context_id="ctx:model-traditional:1",
            system_scope=SelectionSystem.TRADITIONAL,
            as_of=None,
        )
        structured = MagicMock()
        structured.invoke.return_value = PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="e",
            investment_thesis="t",
            portfolio_context=traditional_ctx,
            system_scope=SelectionSystem.TRADITIONAL,
        )
        render = MagicMock(side_effect=AssertionError("must not render"))
        monkeypatch.setattr(
            "tradingagents.agents.managers.portfolio_manager._render_validated_pm_decision",
            render,
        )

        with pytest.raises(ValueError, match="TRUST_SOURCE_CONTAMINATION"):
            _invoke_governed_pm(
                structured,
                "prompt",
                SelectionSystem.TRADITIONAL,
            )
        render.assert_not_called()

    def test_model_declared_foreign_system_and_context_rejected_by_runtime(self):
        pradeep_ctx = SystemPortfolioContext(
            portfolio_context_id="ctx:model-pradeep:1",
            system_scope=SelectionSystem.PRADEEP,
            as_of=None,
        )
        structured = MagicMock()
        structured.invoke.return_value = PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="e",
            investment_thesis="t",
            portfolio_context=pradeep_ctx,
            system_scope=SelectionSystem.PRADEEP,
        )

        with pytest.raises(ValueError, match="CROSS_SYSTEM_CONTAMINATION"):
            _invoke_governed_pm(
                structured,
                "prompt",
                SelectionSystem.TRADITIONAL,
            )

    def test_governed_x1_x2_x3_without_portfolio_context_remain_valid(self):
        for reason in (
            ExitReason.THESIS_BROKEN,
            ExitReason.FORWARD_FUNDAMENTALS_MATERIALLY_DETERIORATED,
            ExitReason.PRICE_EXTREMELY_DISCONNECTED_FROM_REASONABLE_ECONOMICS,
        ):
            structured = MagicMock()
            structured.invoke.return_value = PortfolioDecision(
                rating=PortfolioRating.SELL,
                executive_summary="e",
                investment_thesis="t",
                position_state=PositionState.HELD,
                position_decision=PositionDecision.SELL,
                exit_reason=reason,
            )

            rendered = _invoke_governed_pm(
                structured,
                "prompt",
                SelectionSystem.TRADITIONAL,
            )
            assert f"**Exit Reason**: {reason.value}" in rendered

    def test_governed_context_token_restores_prior_context(self):
        from tradingagents.agents.schemas import (
            clear_governed_decision_context,
            get_governed_decision_context,
            set_governed_decision_context,
        )

        outer = set_governed_decision_context(
            analysis_purpose="OWNER_MANUAL_REVIEW",
            system_scope="PRADEEP",
            portfolio_eligible=False,
        )
        inner = set_governed_decision_context(
            analysis_purpose="BASELINE_SYSTEM",
            system_scope="TRADITIONAL",
            portfolio_eligible=True,
        )
        try:
            assert get_governed_decision_context()["system_scope"] == "TRADITIONAL"
            clear_governed_decision_context(inner)
            assert get_governed_decision_context()["system_scope"] == "PRADEEP"
        finally:
            clear_governed_decision_context(outer)
        assert get_governed_decision_context() == {}
