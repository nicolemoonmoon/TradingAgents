"""Portfolio Manager: synthesises the risk-analyst debate into the final decision.

Uses LangChain's ``with_structured_output`` so the LLM produces a typed
``PortfolioDecision`` directly, in a single call.  The result is rendered
back to markdown for storage in ``final_trade_decision`` so memory log,
CLI display, and saved reports continue to consume the same shape they do
today.  When a provider does not expose structured output, the agent falls
back gracefully to free-text generation.
"""

from __future__ import annotations

from typing import Any

from tradingagents.agents.schemas import (
    PortfolioDecision,
    get_governed_decision_context,
    is_governed_baseline,
    render_pm_decision,
    validate_exit_reason,
    validate_position_decision,
)
from tradingagents.agents.utils.agent_utils import (
    get_evidence_scope_instruction,
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.scanners.unified import SelectionSystem


def _render_validated_pm_decision(decision: PortfolioDecision) -> str:
    """Post-structured-output check at the production call site (SR-2/SR-3).

    Re-asserts the governed position state machine and the scoped X4/X5
    portfolio-context requirement before rendering, so prompt prose is never
    the only guard. Governed invocation replaces the model declaration with
    the trusted runtime consuming scope before this boundary.
    """
    if decision.position_decision is not None:
        if decision.position_state is None:
            raise ValueError("position_decision requires position_state=HELD")
        validate_position_decision(decision.position_state, decision.position_decision)
    if decision.exit_reason is not None:
        if decision.position_state is None:
            raise ValueError("exit_reason requires position_state=HELD")
        validate_exit_reason(
            decision.exit_reason,
            decision.portfolio_context,
            consuming_system=decision.system_scope,
        )
    return render_pm_decision(decision)


def _invoke_governed_pm(
    structured_llm: Any | None, prompt: str, system_scope: SelectionSystem | None
) -> str:
    """Governed Portfolio Manager invocation (SR-2/SR-3).

    Never falls back to unchecked free text. The runtime ``system_scope`` is
    authoritative: a conflicting non-null model declaration is rejected. The
    current runtime has no trusted Portfolio context producer, so any context
    returned by the model is rejected before the trusted scope is installed
    and before the render/validation boundary.
    """
    if structured_llm is None:
        raise ValueError(
            "Portfolio Manager: governed baseline requires structured output; "
            "the provider does not support with_structured_output"
        )
    decision = structured_llm.invoke(prompt)
    if decision is None:
        raise ValueError("Portfolio Manager: structured output returned no parsed result")
    if system_scope is None:
        raise ValueError(
            "Portfolio Manager: governed baseline requires a trusted runtime system_scope"
        )
    if decision.system_scope is not None and decision.system_scope is not system_scope:
        raise ValueError(
            "CROSS_SYSTEM_CONTAMINATION: model-declared system_scope "
            f"{decision.system_scope.value!r} conflicts with trusted runtime "
            f"scope {system_scope.value!r}"
        )
    if decision.portfolio_context is not None:
        raise ValueError(
            "TRUST_SOURCE_CONTAMINATION: model-supplied portfolio_context is "
            "untrusted; no trusted runtime Portfolio context producer is connected"
        )
    decision = decision.model_copy(update={"system_scope": system_scope})
    return _render_validated_pm_decision(decision)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        evidence_scope = get_evidence_scope_instruction(state)

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- Lessons from prior decisions and outcomes:\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{evidence_scope}

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

When reviewing an existing (HELD) position, the governed position action is exactly one of HOLD / REDUCE / SELL / REVIEW. If you exit or reduce, bind one frozen exit reason: THESIS_BROKEN (X1), FORWARD_FUNDAMENTALS_MATERIALLY_DETERIORATED (X2), PRICE_EXTREMELY_DISCONNECTED_FROM_REASONABLE_ECONOMICS (X3), BETTER_CAPITAL_ALLOCATION_OPPORTUNITY (X4), or PORTFOLIO_RISK (X5). X4 and X5 may only be asserted when a same-system portfolio context is available; otherwise fail closed and do not claim them.

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
{lessons_line}
**Risk Analysts Debate History:**
{history}

---

Be decisive and ground every conclusion in specific evidence from the analysts.{get_language_instruction()}"""

        # SR-2/SR-3: a governed BASELINE decision must never fall back to
        # unchecked free text, and must carry its consuming system_scope so
        # X4/X5 same-system portfolio-context checks are mechanical. Legacy/
        # manual runs keep the graceful structured->free-text fallback.
        if is_governed_baseline():
            ctx = get_governed_decision_context()
            system_scope_raw = ctx.get("system_scope")
            system_scope = (
                SelectionSystem(system_scope_raw) if system_scope_raw else None
            )
            final_trade_decision = _invoke_governed_pm(
                structured_llm, prompt, system_scope
            )
        else:
            final_trade_decision = invoke_structured_or_freetext(
                structured_llm,
                llm,
                prompt,
                _render_validated_pm_decision,
                "Portfolio Manager",
            )

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
