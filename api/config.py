"""Backend API configuration (Phase 2A).

Deliberately separate from ``tradingagents/default_config.py``: that module
configures the analysis pipeline (LLM provider/models/checkpointing); this
module configures the read-only API layer (where to find existing run
artifacts). The two are different concerns and don't share config state.
"""

from __future__ import annotations

import os
from pathlib import Path

from tradingagents.run_contract import RUNS_DIRNAME


def get_runs_dir() -> Path:
    """FastAPI dependency: the directory containing ``{run_id}/`` run artifacts.

    Reads ``TRADINGAGENTS_RUNS_DIR``, defaulting to ``run_contract.RUNS_DIRNAME``
    (``"runs"``, relative to the current working directory) -- never a
    hardcoded smoke-test path. Override via ``app.dependency_overrides`` in
    tests rather than the environment variable.
    """
    return Path(os.getenv("TRADINGAGENTS_RUNS_DIR", RUNS_DIRNAME))
