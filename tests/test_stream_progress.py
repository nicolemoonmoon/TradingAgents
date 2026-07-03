"""Pure state-diffing logic for Phase 1C streaming progress (no graph, no I/O).

detect_newly_completed_agents() compares two AgentState-shaped dicts (the
previous and current stream_mode="values" chunk from graph.graph.stream())
and reports which AgentIds' tracked field went from falsy to truthy --
the only reliable "agent completed" signal available. There is no reliable
"agent started" signal, so this module never produces one.
"""

import pytest

from tradingagents.run_contract import AgentId
from tradingagents.stream_progress import detect_newly_completed_agents


@pytest.mark.unit
def test_detect_newly_completed_agents_empty_states_yields_nothing():
    assert detect_newly_completed_agents({}, {}) == []


@pytest.mark.unit
def test_detect_newly_completed_agents_top_level_report_field():
    current = {"market_report": "Market analysis text."}
    assert detect_newly_completed_agents({}, current) == [AgentId.MARKET]


@pytest.mark.unit
def test_detect_newly_completed_agents_does_not_repeat_already_completed():
    state = {"market_report": "Market analysis text."}
    assert detect_newly_completed_agents(state, state) == []


@pytest.mark.unit
def test_detect_newly_completed_agents_nested_investment_debate_state():
    previous = {"investment_debate_state": {"bull_history": "", "judge_decision": ""}}
    current = {"investment_debate_state": {"bull_history": "Bull case.", "judge_decision": ""}}
    assert detect_newly_completed_agents(previous, current) == [AgentId.BULL]


@pytest.mark.unit
def test_detect_newly_completed_agents_nested_risk_debate_state():
    previous = {"risk_debate_state": {"judge_decision": ""}}
    current = {"risk_debate_state": {"judge_decision": "**Rating**: Hold"}}
    assert detect_newly_completed_agents(previous, current) == [AgentId.PORTFOLIO_MANAGER]


@pytest.mark.unit
def test_detect_newly_completed_agents_multiple_in_one_transition_preserve_canonical_order():
    current = {"news_report": "News text.", "market_report": "Market text."}
    # Canonical AgentId order has MARKET before NEWS, regardless of dict key order.
    assert detect_newly_completed_agents({}, current) == [AgentId.MARKET, AgentId.NEWS]


@pytest.mark.unit
def test_detect_newly_completed_agents_covers_all_twelve_state_paths():
    current = {
        "market_report": "x",
        "fundamentals_report": "x",
        "sentiment_report": "x",
        "news_report": "x",
        "investment_debate_state": {
            "bull_history": "x",
            "bear_history": "x",
            "judge_decision": "x",
        },
        "trader_investment_plan": "x",
        "risk_debate_state": {
            "aggressive_history": "x",
            "neutral_history": "x",
            "conservative_history": "x",
            "judge_decision": "x",
        },
    }
    assert set(detect_newly_completed_agents({}, current)) == set(AgentId)


@pytest.mark.unit
def test_detect_newly_completed_agents_ignores_falsy_to_falsy_transition():
    assert detect_newly_completed_agents({"market_report": ""}, {"market_report": ""}) == []


@pytest.mark.unit
def test_detect_newly_completed_agents_handles_missing_nested_dict_gracefully():
    current = {"trader_investment_plan": "Trader plan."}
    # investment_debate_state/risk_debate_state entirely absent in both states -- must not raise.
    assert detect_newly_completed_agents({}, current) == [AgentId.TRADER]
