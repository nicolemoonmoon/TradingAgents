"""Pure diffing logic for streamed graph progress (Phase 1C).

``TradingAgentsGraph.propagator.get_graph_args()`` hardcodes
``stream_mode="values"`` (see ``tradingagents/graph/propagation.py``), so
each chunk yielded by ``graph.graph.stream(...)`` is the full accumulated
``AgentState`` dict after that step -- not a ``{node_name: delta}`` mapping.
There is no field anywhere in a chunk that names "the node that just ran";
the only reliable signal is a tracked state field going from falsy to
truthy between two consecutive chunks. This mirrors exactly what
``cli/main.py``'s streaming display already infers (a state field becoming
non-empty), and is the same field-to-agent correspondence
``tradingagents.report_field_parsing.AGENT_REPORT_FILE_MAP`` uses for the
on-disk report tree -- this module applies the same mapping to in-memory
state instead of files on disk.

There is deliberately no equivalent "agent started" detection: no such
signal exists in a ``stream_mode="values"`` chunk. Any "started" status
would have to be guessed (as the CLI's display layer does), which this
module refuses to do.
"""

from __future__ import annotations

from tradingagents.run_contract import AgentId

# AgentId -> path into an AgentState dict whose truthiness signals that
# agent has completed. Order matches AgentId's own canonical enum order, so
# multiple agents completing within a single chunk transition are reported
# in a deterministic, stable order rather than dict/insertion order.
_AGENT_STATE_PATHS: dict[AgentId, tuple[str, ...]] = {
    AgentId.MARKET: ("market_report",),
    AgentId.FUNDAMENTALS: ("fundamentals_report",),
    AgentId.SENTIMENT: ("sentiment_report",),
    AgentId.NEWS: ("news_report",),
    AgentId.BULL: ("investment_debate_state", "bull_history"),
    AgentId.BEAR: ("investment_debate_state", "bear_history"),
    AgentId.RESEARCH_MANAGER: ("investment_debate_state", "judge_decision"),
    AgentId.TRADER: ("trader_investment_plan",),
    AgentId.AGGRESSIVE_RISK: ("risk_debate_state", "aggressive_history"),
    AgentId.NEUTRAL_RISK: ("risk_debate_state", "neutral_history"),
    AgentId.CONSERVATIVE_RISK: ("risk_debate_state", "conservative_history"),
    AgentId.PORTFOLIO_MANAGER: ("risk_debate_state", "judge_decision"),
}


def _get_path(state: dict, path: tuple[str, ...]):
    value = state
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def detect_newly_completed_agents(previous_state: dict, current_state: dict) -> list[AgentId]:
    """Return the AgentIds whose tracked field became truthy in ``current_state``
    but was falsy (or absent) in ``previous_state``.

    Pure and side-effect-free: no I/O, no graph object. Missing nested keys
    (e.g. ``investment_debate_state`` entirely absent) are treated as falsy,
    not an error.
    """
    newly_completed = []
    for agent_id, path in _AGENT_STATE_PATHS.items():
        was_done = bool(_get_path(previous_state, path))
        is_done = bool(_get_path(current_state, path))
        if is_done and not was_done:
            newly_completed.append(agent_id)
    return newly_completed
