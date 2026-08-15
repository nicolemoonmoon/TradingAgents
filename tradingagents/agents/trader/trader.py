"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    PositionState,
    TraderProposal,
    invoke_governed_structured,
    is_governed_baseline,
    render_trader_proposal,
    validate_entry_decision,
    validate_wait_recheck,
)
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.default_config import get_active_prompt_grounding


def _render_validated_trader_proposal(proposal: TraderProposal) -> str:
    """Post-structured-output check at the production call site (SR-2).

    For a governed BASELINE entry the entry decision is mandatory (BUY|WAIT|
    REVIEW) and WAIT requires the full recheck set; a missing or illegal
    governed entry decision fails closed. For legacy/manual runs the optional
    fields remain optional for backward compatibility.
    """
    if is_governed_baseline():
        if proposal.position_state is not PositionState.NOT_HELD:
            raise ValueError("governed baseline entry requires position_state=NOT_HELD")
        if proposal.entry_decision is None:
            raise ValueError(
                "governed baseline entry requires entry_decision BUY/WAIT/REVIEW"
            )
        validate_entry_decision(proposal.position_state, proposal.entry_decision)
        validate_wait_recheck(
            proposal.entry_decision,
            proposal.why_wait,
            proposal.what_needs_to_change,
            proposal.recheck_trigger,
            proposal.review_due,
        )
    elif proposal.entry_decision is not None:
        validate_entry_decision(proposal.position_state, proposal.entry_decision)
        validate_wait_recheck(
            proposal.entry_decision,
            proposal.why_wait,
            proposal.what_needs_to_change,
            proposal.recheck_trigger,
            proposal.review_due,
        )
    return render_trader_proposal(proposal)


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]

        # Phase 10B.1: Stockbee prompt grounding — prepend if active
        grounding_prefix = ""
        active = get_active_prompt_grounding()
        if active:
            grounding_prefix = active + "\n\n---\n\n"

        messages = [
            {
                "role": "system",
                "content": (
                    grounding_prefix
                    + "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "Anchor your reasoning in the analysts' reports and the research plan. "
                    "You are evaluating an entry for a NOT_HELD position: the governed entry action "
                    "is exactly one of BUY, WAIT, or REVIEW. If the moment is not right to enter, "
                    "prefer WAIT and explain why_wait, what_needs_to_change, recheck_trigger, and "
                    "review_due rather than a bare Hold. Keep execution availability a separate "
                    "field from the investment judgment."
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by a team of analysts, here is an investment "
                    f"plan tailored for {company_name}. {instrument_context} This plan incorporates "
                    f"insights from current technical market trends, macroeconomic indicators, and "
                    f"social media sentiment. Use this plan as a foundation for evaluating your next "
                    f"trading decision.\n\nProposed Investment Plan: {investment_plan}\n\n"
                    f"Leverage these insights to make an informed and strategic decision."
                ),
            },
        ]

        # SR-2: a governed BASELINE entry must never fall back to unchecked
        # free text. It uses a fail-closed governed invocation; legacy/manual
        # runs keep the graceful structured->free-text fallback.
        if is_governed_baseline():
            trader_plan = invoke_governed_structured(
                structured_llm, messages, _render_validated_trader_proposal, "Trader"
            )
        else:
            trader_plan = invoke_structured_or_freetext(
                structured_llm,
                llm,
                messages,
                _render_validated_trader_proposal,
                "Trader",
            )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
