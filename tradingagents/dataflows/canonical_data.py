"""Project-owned canonical data and provenance records.

The contract separates a provider payload from its availability state.  Callers
must explicitly unwrap available data; unavailable and stale records raise
instead of being accidentally consumed as usable values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Generic, TypeVar, cast

T = TypeVar("T")


class Availability(str, Enum):
    """Availability state for a canonical provider result."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class CanonicalDataNotUsableError(RuntimeError):
    """Raised when unavailable or stale data is accessed as usable data."""


def _freeze(value: Any) -> Any:
    """Recursively convert common mutable containers to read-only values."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class CanonicalData(Generic[T]):
    """Mutation-resistant provider data with explicit provenance and state."""

    operation: str
    availability: Availability
    provider: str
    source: str
    retrieved_at: datetime
    payload: T | None
    symbol: str | None = None
    data_as_of: date | datetime | None = None
    reporting_period: str | None = None
    unit: str | None = None
    currency: str | None = None
    reason: str | None = None
    query: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must be non-empty")
        if not self.provider.strip() or not self.source.strip():
            raise ValueError("provider and source must be non-empty")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")

        if self.availability is Availability.AVAILABLE:
            if self.payload is None:
                raise ValueError("available data requires a payload")
            if self.reason is not None:
                raise ValueError("available data cannot carry an unavailable reason")
        else:
            if self.payload is not None:
                raise ValueError("unavailable or stale data cannot carry a payload")
            if not self.reason or not self.reason.strip():
                raise ValueError("unavailable or stale data requires a reason")

        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "query", _freeze(self.query or {}))

    @property
    def is_usable(self) -> bool:
        """Return whether the record may be consumed as data."""
        return self.availability is Availability.AVAILABLE

    def require_available(self) -> T:
        """Return the payload, failing closed for unavailable or stale records."""
        if not self.is_usable:
            raise CanonicalDataNotUsableError(
                f"{self.operation} from {self.provider} is "
                f"{self.availability.value}: {self.reason}"
            )
        return cast(T, self.payload)
