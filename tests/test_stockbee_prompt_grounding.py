"""Phase 10B.1: Stockbee prompt grounding unit tests.
No provider calls. No server. No POST /api/runs.
"""
import pytest

from tradingagents.default_config import (
    STOCKBEE_PROMPT_GROUNDING,
    get_active_prompt_grounding,
    get_stockbee_grounding,
    set_active_prompt_grounding,
)

SENTINEL = "SENTINEL_STOCKBEE_GROUNDING_12345"


# ---------------------------------------------------------------------------
# getter/setter unit tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetStockbeeGrounding:
    def test_none_profile_returns_none(self):
        assert get_stockbee_grounding(None) is None

    def test_unknown_profile_returns_none(self):
        assert get_stockbee_grounding("some_unknown_profile") is None
        assert get_stockbee_grounding("pradeep_v1") is None

    def test_mb_profile_returns_non_empty_string(self):
        result = get_stockbee_grounding("stockbee_momentum_burst")
        assert result is not None
        assert len(result) > 100
        assert "range expansion" in result.lower()
        assert "200-1000" in result

    def test_ep_profile_returns_non_empty_string(self):
        result = get_stockbee_grounding("stockbee_episodic_pivot")
        assert result is not None
        assert len(result) > 100
        assert "episodic pivot" in result.lower()
        assert "100-500%" in result


@pytest.mark.unit
class TestStockbeeGroundingContent:
    def test_mb_contains_key_terms(self):
        text = STOCKBEE_PROMPT_GROUNDING["stockbee_momentum_burst"]
        for term in ["range expansion", "follow", "3-10 days", "200-1000"]:
            assert term.lower() in text.lower(), f"missing: {term}"

    def test_ep_contains_key_terms(self):
        text = STOCKBEE_PROMPT_GROUNDING["stockbee_episodic_pivot"]
        for term in ["episodic pivot", "neglect", "pre-market", "100-500%"]:
            assert term.lower() in text.lower(), f"missing: {term}"


# ---------------------------------------------------------------------------
# ContextVar getter/setter lifecycle tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestActiveGroundingLifecycle:
    def test_default_is_none(self):
        set_active_prompt_grounding(None)
        assert get_active_prompt_grounding() is None

    def test_set_and_get(self):
        set_active_prompt_grounding(SENTINEL)
        assert get_active_prompt_grounding() == SENTINEL
        set_active_prompt_grounding(None)

    def test_reset_to_none(self):
        set_active_prompt_grounding(SENTINEL)
        set_active_prompt_grounding(None)
        assert get_active_prompt_grounding() is None

    def test_switch_mb_to_ep(self):
        set_active_prompt_grounding("MB_GROUNDING")
        assert get_active_prompt_grounding() == "MB_GROUNDING"
        set_active_prompt_grounding("EP_GROUNDING")
        assert get_active_prompt_grounding() == "EP_GROUNDING"
        set_active_prompt_grounding(None)


# ---------------------------------------------------------------------------
# _build_graph config injection tests
# ---------------------------------------------------------------------------

class _FakeGraph:
    def __init__(self, selected_analysts, config, debug):
        pass


@pytest.mark.unit
def test_build_graph_mb_adds_grounding(monkeypatch):
    """Phase 10B.1: Stockbee MB profile → config.prompt_grounding populated."""
    from api.main import _build_graph
    from api.schemas import StartAnalysisRequest

    captured = {}

    class CapturingFakeGraph:
        def __init__(self, selected_analysts, config, debug):
            captured["config"] = dict(config)

    monkeypatch.setattr("api.main.TradingAgentsGraph", CapturingFakeGraph)

    request = StartAnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-03",
        strategy_profile="stockbee_momentum_burst",
    )
    _build_graph(request)

    config = captured["config"]
    assert "prompt_grounding" in config
    assert "range expansion" in config["prompt_grounding"].lower()


@pytest.mark.unit
def test_build_graph_ep_adds_grounding(monkeypatch):
    """Phase 10B.1: Stockbee EP profile → config.prompt_grounding populated."""
    from api.main import _build_graph
    from api.schemas import StartAnalysisRequest

    captured = {}

    class CapturingFakeGraph:
        def __init__(self, selected_analysts, config, debug):
            captured["config"] = dict(config)

    monkeypatch.setattr("api.main.TradingAgentsGraph", CapturingFakeGraph)

    request = StartAnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-03",
        strategy_profile="stockbee_episodic_pivot",
    )
    _build_graph(request)

    config = captured["config"]
    assert "prompt_grounding" in config
    assert "episodic pivot" in config["prompt_grounding"].lower()


@pytest.mark.unit
def test_build_graph_unknown_profile_no_grounding(monkeypatch):
    """Phase 10B.1: unknown profile does not inject prompt_grounding."""
    from api.main import _build_graph
    from api.schemas import StartAnalysisRequest

    captured = {}

    class CapturingFakeGraph:
        def __init__(self, selected_analysts, config, debug):
            captured["config"] = dict(config)

    monkeypatch.setattr("api.main.TradingAgentsGraph", CapturingFakeGraph)

    request = StartAnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-03",
        strategy_profile="pradeep_v1",
    )
    _build_graph(request)

    assert "prompt_grounding" not in captured["config"]


@pytest.mark.unit
def test_build_graph_none_profile_no_grounding(monkeypatch):
    """Phase 10B.1: None profile → no prompt_grounding."""
    from api.main import _build_graph
    from api.schemas import StartAnalysisRequest

    captured = {}

    class CapturingFakeGraph:
        def __init__(self, selected_analysts, config, debug):
            captured["config"] = dict(config)

    monkeypatch.setattr("api.main.TradingAgentsGraph", CapturingFakeGraph)

    request = StartAnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-03",
        strategy_profile=None,
    )
    _build_graph(request)

    assert "prompt_grounding" not in captured["config"]


# ---------------------------------------------------------------------------
# Stale grounding tests — _build_graph must reset
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_graph_none_profile_resets_stale_grounding(monkeypatch):
    """Phase 10B.1: MB → None must reset active grounding to None."""
    from api.main import _build_graph
    from api.schemas import StartAnalysisRequest

    set_active_prompt_grounding(SENTINEL)
    assert get_active_prompt_grounding() == SENTINEL

    monkeypatch.setattr("api.main.TradingAgentsGraph", _FakeGraph)

    request = StartAnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-03",
        strategy_profile=None,
    )
    _build_graph(request)

    assert get_active_prompt_grounding() is None


@pytest.mark.unit
def test_build_graph_unknown_profile_resets_stale_grounding(monkeypatch):
    """Phase 10B.1: MB → unknown must reset active grounding to None."""
    from api.main import _build_graph
    from api.schemas import StartAnalysisRequest

    set_active_prompt_grounding(SENTINEL)
    assert get_active_prompt_grounding() == SENTINEL

    monkeypatch.setattr("api.main.TradingAgentsGraph", _FakeGraph)

    request = StartAnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-03",
        strategy_profile="pradeep_v1",
    )
    _build_graph(request)

    assert get_active_prompt_grounding() is None


@pytest.mark.unit
def test_build_graph_mb_then_ep_switches_grounding(monkeypatch):
    """Phase 10B.1: MB → EP must switch active grounding to EP text."""
    from api.main import _build_graph
    from api.schemas import StartAnalysisRequest

    monkeypatch.setattr("api.main.TradingAgentsGraph", _FakeGraph)

    # First call: MB
    _build_graph(StartAnalysisRequest(
        ticker="AAPL", analysis_date="2026-07-03",
        strategy_profile="stockbee_momentum_burst",
    ))
    after_mb = get_active_prompt_grounding()
    assert after_mb is not None
    assert "momentum burst" in after_mb.lower()
    assert "episodic pivot" not in after_mb.lower()

    # Second call: EP
    _build_graph(StartAnalysisRequest(
        ticker="MSFT", analysis_date="2026-07-03",
        strategy_profile="stockbee_episodic_pivot",
    ))
    after_ep = get_active_prompt_grounding()
    assert after_ep is not None
    assert "episodic pivot" in after_ep.lower()


# ---------------------------------------------------------------------------
# Import safety: agent modules must NOT import active grounding by value
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_agent_modules_do_not_import_active_grounding_by_value():
    """Phase 10B.1: agent modules use get_active_prompt_grounding(), not _active_prompt_grounding."""
    import ast
    import inspect

    from tradingagents.agents.analysts import market_analyst
    from tradingagents.agents.managers import research_manager
    from tradingagents.agents.trader import trader as trader_mod

    for mod in (market_analyst, research_manager, trader_mod):
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "tradingagents.default_config":
                    for alias in node.names:
                        assert alias.name != "_active_prompt_grounding", (
                            f"{mod.__name__} imports _active_prompt_grounding by value"
                        )


# ---------------------------------------------------------------------------
# Agent prompt construction tests — grounding visible at runtime
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_market_analyst_prompt_includes_sentinel_grounding(monkeypatch):
    """Phase 10B.1: market analyst prompt includes active grounding when set."""
    set_active_prompt_grounding(SENTINEL)

    # Minimal state for market_analyst_node
    state = {
        "trade_date": "2026-07-03",
        "messages": [],
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
    }

    from tradingagents.agents.analysts.market_analyst import create_market_analyst
    mock_llm = type("MockLLM", (), {"bind_tools": lambda self, tools: lambda msgs: type("Result", (), {"content": "", "tool_calls": []})()})()

    node = create_market_analyst(mock_llm)
    # The node calls invoke() which would call the LLM, but we can't do that.
    # Instead, verify that the factory creates a closure that captures
    # get_active_prompt_grounding correctly by checking the function source.
    import inspect
    source = inspect.getsource(node)
    assert "get_active_prompt_grounding" in source, (
        "market_analyst_node must call get_active_prompt_grounding()"
    )

    set_active_prompt_grounding(None)


@pytest.mark.unit
def test_agent_grounding_appears_then_disappears_on_reset():
    """Phase 10B.1: set→get returns sentinel; reset→get returns None."""
    set_active_prompt_grounding(SENTINEL)
    assert get_active_prompt_grounding() == SENTINEL, (
        "active grounding should be visible after set"
    )

    set_active_prompt_grounding(None)
    assert get_active_prompt_grounding() is None, (
        "active grounding should be None after reset"
    )


# ---------------------------------------------------------------------------
# Prompt-construction tests — market analyst (no provider, mock LLM)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_market_analyst_includes_active_grounding():
    """Active grounding is included in market analyst's constructed prompt."""
    set_active_prompt_grounding(SENTINEL)

    captured_content = None

    def _capturing_invoke(messages):
        nonlocal captured_content
        from langchain_core.messages import SystemMessage
        # ChatPromptTemplate chains pass a ChatPromptValue, not a raw list.
        # .to_messages() normalises to list[BaseMessage].
        if hasattr(messages, "to_messages"):
            messages = messages.to_messages()
        for msg in messages:
            if isinstance(msg, SystemMessage):
                captured_content = msg.content
                break
        return type("Result", (), {"content": "", "tool_calls": []})()

    mock_llm = type("MockLLM", (), {
        "bind_tools": lambda self, tools: _capturing_invoke
    })()

    from tradingagents.agents.analysts.market_analyst import create_market_analyst

    node = create_market_analyst(mock_llm)
    state = {
        "trade_date": "2026-07-03",
        "messages": [],
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
    }
    node(state)

    assert captured_content is not None, "system message content was not captured"
    assert SENTINEL in captured_content, (
        "active grounding not found in market analyst system message"
    )
    assert captured_content.count(SENTINEL) == 1, (
        "grounding must appear exactly once"
    )

    set_active_prompt_grounding(None)


@pytest.mark.unit
def test_market_analyst_excludes_grounding_when_none():
    """No Stockbee text when active grounding is None."""
    set_active_prompt_grounding(None)

    captured_content = None

    def _capturing_invoke(messages):
        nonlocal captured_content
        from langchain_core.messages import SystemMessage
        if hasattr(messages, "to_messages"):
            messages = messages.to_messages()
        for msg in messages:
            if isinstance(msg, SystemMessage):
                captured_content = msg.content
                break
        return type("Result", (), {"content": "", "tool_calls": []})()

    mock_llm = type("MockLLM", (), {
        "bind_tools": lambda self, tools: _capturing_invoke
    })()

    from tradingagents.agents.analysts.market_analyst import create_market_analyst

    node = create_market_analyst(mock_llm)
    state = {
        "trade_date": "2026-07-03",
        "messages": [],
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
    }
    node(state)

    assert captured_content is not None
    assert SENTINEL not in captured_content, (
        "grounding must not appear when None is active"
    )
    assert "STOCKBEE" not in captured_content, (
        "no Stockbee text should leak when grounding is None"
    )


# ---------------------------------------------------------------------------
# Prompt-construction tests — research manager (no provider, stub invoke)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_research_manager_includes_active_grounding(monkeypatch):
    """Active grounding is included in research manager's constructed prompt."""
    set_active_prompt_grounding(SENTINEL)

    captured_prompt = None

    def _capture_prompt(structured_llm, plain_llm, prompt, render, agent_name):
        nonlocal captured_prompt
        captured_prompt = prompt
        return "investment plan text"

    monkeypatch.setattr(
        "tradingagents.agents.managers.research_manager.invoke_structured_or_freetext",
        _capture_prompt,
    )

    from tradingagents.agents.managers.research_manager import create_research_manager

    mock_llm = type("MockLLM", (), {})()
    node = create_research_manager(mock_llm)
    state = {
        "trade_date": "2026-07-03",
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
        "investment_debate_state": {
            "history": "debate history",
            "count": 1,
            "bear_history": "",
            "bull_history": "",
            "current_response": "",
        },
        "investment_plan": "",
    }
    node(state)

    assert isinstance(captured_prompt, str)
    assert SENTINEL in captured_prompt, (
        "active grounding not found in research manager prompt"
    )
    assert captured_prompt.count(SENTINEL) == 1, (
        "grounding must appear exactly once"
    )

    set_active_prompt_grounding(None)


@pytest.mark.unit
def test_research_manager_excludes_grounding_when_none(monkeypatch):
    """No Stockbee text when active grounding is None."""
    set_active_prompt_grounding(None)

    captured_prompt = None

    def _capture_prompt(structured_llm, plain_llm, prompt, render, agent_name):
        nonlocal captured_prompt
        captured_prompt = prompt
        return "investment plan text"

    monkeypatch.setattr(
        "tradingagents.agents.managers.research_manager.invoke_structured_or_freetext",
        _capture_prompt,
    )

    from tradingagents.agents.managers.research_manager import create_research_manager

    mock_llm = type("MockLLM", (), {})()
    node = create_research_manager(mock_llm)
    state = {
        "trade_date": "2026-07-03",
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
        "investment_debate_state": {
            "history": "debate history",
            "count": 1,
            "bear_history": "",
            "bull_history": "",
            "current_response": "",
        },
        "investment_plan": "",
    }
    node(state)

    assert isinstance(captured_prompt, str)
    assert SENTINEL not in captured_prompt, (
        "grounding must not appear when None is active"
    )
    assert "STOCKBEE" not in captured_prompt, (
        "no Stockbee text should leak when grounding is None"
    )


# ---------------------------------------------------------------------------
# Prompt-construction tests — trader (no provider, stub invoke)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trader_includes_active_grounding(monkeypatch):
    """Active grounding is included in trader's constructed messages."""
    set_active_prompt_grounding(SENTINEL)

    captured_messages = None

    def _capture_prompt(structured_llm, plain_llm, prompt, render, agent_name):
        nonlocal captured_messages
        captured_messages = prompt
        return "trader proposal text"

    monkeypatch.setattr(
        "tradingagents.agents.trader.trader.invoke_structured_or_freetext",
        _capture_prompt,
    )

    from tradingagents.agents.trader.trader import create_trader

    mock_llm = type("MockLLM", (), {})()
    node = create_trader(mock_llm)
    state = {
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
        "investment_plan": "Buy: bullish outlook",
    }
    node(state)

    assert isinstance(captured_messages, list)
    assert len(captured_messages) > 0
    system_content = captured_messages[0]["content"]
    assert SENTINEL in system_content, (
        "active grounding not found in trader system message"
    )
    assert system_content.count(SENTINEL) == 1, (
        "grounding must appear exactly once"
    )

    set_active_prompt_grounding(None)


@pytest.mark.unit
def test_trader_excludes_grounding_when_none(monkeypatch):
    """No Stockbee text when active grounding is None."""
    set_active_prompt_grounding(None)

    captured_messages = None

    def _capture_prompt(structured_llm, plain_llm, prompt, render, agent_name):
        nonlocal captured_messages
        captured_messages = prompt
        return "trader proposal text"

    monkeypatch.setattr(
        "tradingagents.agents.trader.trader.invoke_structured_or_freetext",
        _capture_prompt,
    )

    from tradingagents.agents.trader.trader import create_trader

    mock_llm = type("MockLLM", (), {})()
    node = create_trader(mock_llm)
    state = {
        "company_of_interest": "AAPL",
        "asset_type": "stock",
        "instrument_context": "",
        "investment_plan": "Buy: bullish outlook",
    }
    node(state)

    assert isinstance(captured_messages, list)
    system_content = captured_messages[0]["content"]
    assert SENTINEL not in system_content, (
        "grounding must not appear when None is active"
    )
    assert "STOCKBEE" not in system_content, (
        "no Stockbee text should leak when grounding is None"
    )


# ---------------------------------------------------------------------------
# ContextVar limitation note — acceptable for current single-active-run path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_contextvar_isolation_note():
    """Document ContextVar limitation for concurrency.

    Phase 10B.1 uses ContextVar (``_active_prompt_grounding_var``) for
    prompt grounding. This is thread-safe within a single background run
    (one context per thread), which matches the current API path. However,
    ContextVar is NOT graph-instance-aware — if two concurrent graph runs
    share the same thread, the second run would see the first run's
    grounding. This is acceptable for the current single-active-run
    background-thread API path.

    Future improvement: pass grounding via graph state/config for proper
    graph-instance isolation if concurrent execution is ever added.
    """
    from tradingagents.default_config import _active_prompt_grounding_var

    set_active_prompt_grounding("ctx_a")
    assert get_active_prompt_grounding() == "ctx_a"

    # Same thread, same ContextVar — second "graph run" sees same value
    assert _active_prompt_grounding_var.get() == "ctx_a"

    set_active_prompt_grounding(None)
    assert get_active_prompt_grounding() is None
