"""Compute-only vectorbt binding with caller-owned inputs and parameters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import vectorbt as vbt


def _stable_value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, Mapping):
        return {str(key): _stable_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    return value


def _fingerprint(close: Any, entries: Any, exits: Any, parameters: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {
            "close": _stable_value(close),
            "entries": _stable_value(entries),
            "exits": _stable_value(exits),
            "parameters": _stable_value(parameters),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class VectorbtComputation:
    """A vectorbt result and deterministic metadata describing its exact inputs."""

    portfolio: Any
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def portfolio_from_signals(
    close: Sequence[float] | Any,
    entries: Sequence[bool] | Any,
    exits: Sequence[bool] | Any,
    parameters: Mapping[str, Any],
) -> VectorbtComputation:
    """Compute a portfolio using only caller-supplied data, signals, and kwargs."""
    caller_parameters = dict(parameters)
    portfolio = vbt.Portfolio.from_signals(
        close=close,
        entries=entries,
        exits=exits,
        **caller_parameters,
    )
    metadata = {
        "engine": "vectorbt",
        "engine_version": vbt.__version__,
        "input_fingerprint_sha256": _fingerprint(
            close, entries, exits, caller_parameters
        ),
        "parameters": MappingProxyType(caller_parameters),
    }
    return VectorbtComputation(portfolio=portfolio, metadata=metadata)
