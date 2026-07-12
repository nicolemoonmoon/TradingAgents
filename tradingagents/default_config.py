import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    # Provider-specific reasoning/thinking knobs (None = each provider's own
    # default). Settable here for non-interactive runs; the CLI also offers an
    # interactive choice, which is skipped when the matching var is set.
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value.

    Invalid values raise ``ValueError`` rather than silently falling back to a
    default — a misspelled boolean (e.g. ``treu``) or non-numeric int should fail
    loudly at startup, not quietly misconfigure an unattended run.
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.5",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Sampling temperature, forwarded to every provider when set. None leaves
    # each provider at its own default. Lower values reduce run-to-run
    # variation on models that honor it; reasoning models largely ignore it
    # and no setting makes LLM output bit-identical across runs (see README).
    "temperature": None,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category).
    # The configured value is the exact vendor chain — requests are NOT silently
    # routed to vendors you didn't choose. For ordered fallback, list several,
    # e.g. "yfinance,alpha_vantage". "default" uses all available vendors.
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
        "macro_data": "fred",                # Options: fred (needs FRED_API_KEY)
        "prediction_markets": "polymarket",  # Options: polymarket (keyless)
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",       # NSE India (Nifty 50)
        ".BO":  "^BSESN",      # BSE India (Sensex)
        ".T":   "^N225",       # Tokyo (Nikkei 225)
        ".HK":  "^HSI",        # Hong Kong (Hang Seng)
        ".L":   "^FTSE",       # London (FTSE 100)
        ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
        ".AX":  "^AXJO",       # Australia (ASX 200)
        ".SS":  "000001.SS",   # Shanghai (SSE Composite)
        ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
        "":     "SPY",         # default for US-listed tickers (no suffix)
    },
})

# ---------------------------------------------------------------------------
# Phase 10B.1: Stockbee prompt grounding
# ---------------------------------------------------------------------------

STOCKBEE_PROMPT_GROUNDING = {
    "stockbee_momentum_burst": (
        "STOCKBEE MOMENTUM BURST CONTEXT\n\n"
        "You are evaluating this stock for a potential Momentum Burst setup. "
        "Key criteria: (1) Has the stock shown a range expansion — a wide-range, "
        "high-volume day — after 4-5 days of weakness or flat action? "
        "(2) Is today day 1 of the potential swing move? Entries on day 3+ are "
        "low-probability per Stockbee methodology. "
        "(3) Does volume confirm the range expansion (above 1.5x 20-day average)? "
        "(4) What is the 3-10 day upside potential? "
        "(5) You do NOT need a specific catalyst for this setup — momentum bursts "
        "are pattern-and-probability based.\n\n"
        "TRADING RULES: Buy on the range expansion day. Exit during the explosive "
        "phase — after 3-10 days, stocks typically give back burst gains. "
        "Cut losses ruthlessly if the trade does not follow through immediately. "
        "This is a 200-1000 trades/year compounding strategy with 5-20% per-trade targets."
    ),
    "stockbee_episodic_pivot": (
        "STOCKBEE EPISODIC PIVOT CONTEXT\n\n"
        "You are evaluating whether this stock's recent earnings constitutes an "
        "Episodic Pivot (EP). Key criteria: (1) How surprising was the earnings "
        "report versus consensus? (2) Was the stock neglected for months/years "
        "prior — low volume, flat/declining price? (3) Pre-market reaction: "
        "gap-up magnitude and volume >50k shares? (4) Is this at the beginning "
        "of a new market rally?\n\n"
        "TRADING RULES: Best EPs are on low-priced, deeply neglected stocks — "
        "moves of 100-500%+ in weeks/months are possible. Position size for "
        "15-20% account growth per trade. Only 1-12 EP opportunities appear "
        "per year — be extremely selective. Most earnings reports produce day "
        "trades, not EPs."
    ),
}

# ---------------------------------------------------------------------------
# Phase 10B.1: Stockbee prompt grounding — ContextVar-backed getter/setter.
#
# Phase 10B.1 is a minimal feature-gated experiment. This does not provide
# full graph-instance isolation. If concurrent graph execution is needed,
# move grounding into graph/config threading in a later protected-file review.
# ---------------------------------------------------------------------------

from contextvars import ContextVar  # noqa: E402 (Phase 10B.1; stdlib since 3.7)

_active_prompt_grounding_var: ContextVar[str | None] = ContextVar(
    "active_prompt_grounding", default=None
)


def set_active_prompt_grounding(value: str | None) -> None:
    """Set the active prompt grounding text. Call at graph construction time.

    Phase 10B.1: called from _build_graph() in api/main.py.
    Call with None to reset.
    """
    _active_prompt_grounding_var.set(value)


def get_active_prompt_grounding() -> str | None:
    """Return the active prompt grounding text, or None.

    Phase 10B.1: called by agent prompt-construction functions at runtime.
    Only non-None when a known Stockbee strategy_profile is active.
    """
    return _active_prompt_grounding_var.get()


def get_stockbee_grounding(strategy_profile: str | None) -> str | None:
    """Return prompt grounding text for a known Stockbee profile, or None.

    Phase 10B.1: feature-gated behind strategy_profile selection.
    Unknown profiles and None return None — no grounding injected.
    """
    if strategy_profile is None:
        return None
    return STOCKBEE_PROMPT_GROUNDING.get(strategy_profile)
