"""Narrow OpenBB provider binding for canonical E06 data operations.

Only direct provider ``Fetcher`` classes are used.  This module deliberately
does not import the OpenBB application interface or create a routing layer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from typing import Any

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError
from openbb_core.provider.utils.helpers import run_async
from openbb_finra.models.equity_short_interest import FinraShortInterestFetcher
from openbb_yfinance.models.balance_sheet import YFinanceBalanceSheetFetcher
from openbb_yfinance.models.cash_flow import YFinanceCashFlowStatementFetcher
from openbb_yfinance.models.equity_historical import YFinanceEquityHistoricalFetcher
from openbb_yfinance.models.equity_profile import YFinanceEquityProfileFetcher
from openbb_yfinance.models.equity_quote import YFinanceEquityQuoteFetcher
from openbb_yfinance.models.income_statement import YFinanceIncomeStatementFetcher
from openbb_yfinance.models.key_metrics import YFinanceKeyMetricsFetcher
from openbb_yfinance.models.price_target_consensus import (
    YFinancePriceTargetConsensusFetcher,
)
from openbb_yfinance.models.share_statistics import YFinanceShareStatisticsFetcher

from .canonical_data import Availability, CanonicalData
from .errors import VendorError, VendorNotConfiguredError


class OpenBBProviderError(VendorError):
    """A direct OpenBB provider failed to satisfy a supported operation."""


_FETCHERS: Mapping[str, tuple[str, str, type[Any]]] = {
    "historical_ohlcv": (
        "yfinance",
        "openbb_yfinance",
        YFinanceEquityHistoricalFetcher,
    ),
    "quote": ("yfinance", "openbb_yfinance", YFinanceEquityQuoteFetcher),
    "profile": ("yfinance", "openbb_yfinance", YFinanceEquityProfileFetcher),
    "balance_sheet": (
        "yfinance",
        "openbb_yfinance",
        YFinanceBalanceSheetFetcher,
    ),
    "cash_flow_statement": (
        "yfinance",
        "openbb_yfinance",
        YFinanceCashFlowStatementFetcher,
    ),
    "income_statement": (
        "yfinance",
        "openbb_yfinance",
        YFinanceIncomeStatementFetcher,
    ),
    "key_metrics": ("yfinance", "openbb_yfinance", YFinanceKeyMetricsFetcher),
    "share_statistics": (
        "yfinance",
        "openbb_yfinance",
        YFinanceShareStatisticsFetcher,
    ),
    "price_target_consensus": (
        "yfinance",
        "openbb_yfinance",
        YFinancePriceTargetConsensusFetcher,
    ),
    "finra_short_interest": (
        "finra",
        "openbb_finra",
        FinraShortInterestFetcher,
    ),
}

_UNSUPPORTED_OPERATIONS = frozenset(
    {
        "premarket_volume",
        "issuer_earnings_events",
        "analyst_revision_history",
        "governed_peer_economic_profile",
    }
)

_AS_OF_FIELDS = (
    "date",
    "datetime",
    "timestamp",
    "period_ending",
    "settlement_date",
)


def _model_to_mapping(value: Any) -> Mapping[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"unsupported provider result type: {type(value).__name__}")


def _serialize_result(result: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(result, AnnotatedResult):
        result = result.result
    if result is None:
        return ()
    values = result if isinstance(result, (list, tuple)) else [result]
    return tuple(_model_to_mapping(value) for value in values)


def _coerce_temporal(value: Any) -> date | datetime | None:
    if isinstance(value, (date, datetime)):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.date() if "T" not in value and " " not in value else parsed
        except ValueError:
            return None
    return None


def _latest_as_of(rows: tuple[Mapping[str, Any], ...]) -> date | datetime | None:
    values: list[date | datetime] = []
    for row in rows:
        for field in _AS_OF_FIELDS:
            value = _coerce_temporal(row.get(field))
            if value is not None:
                values.append(value)
                break
    if not values:
        return None
    normalized = [
        value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time())
        for value in values
    ]
    latest = values[normalized.index(max(normalized))]
    return latest


def _first_present(rows: tuple[Mapping[str, Any], ...], field: str) -> str | None:
    for row in rows:
        value = row.get(field)
        if value is not None:
            return str(value)
    return None


def _unavailable(
    operation: str,
    provider: str,
    source: str,
    query: Mapping[str, Any],
    retrieved_at: datetime,
    reason: str,
) -> CanonicalData[Any]:
    return CanonicalData(
        operation=operation,
        availability=Availability.UNAVAILABLE,
        provider=provider,
        source=source,
        retrieved_at=retrieved_at,
        payload=None,
        symbol=str(query["symbol"]) if query.get("symbol") is not None else None,
        reason=reason,
        query=query,
    )


def fetch_openbb(
    operation: str,
    query_params: Mapping[str, Any],
    credentials: Mapping[str, str] | None = None,
    *,
    retrieved_at: datetime | None = None,
    stale_before: date | datetime | None = None,
) -> CanonicalData[Any]:
    """Execute one explicitly supported direct Fetcher operation.

    ``stale_before`` is entirely caller supplied.  No freshness threshold or
    scanner/business policy is embedded in this adapter.
    """
    query = dict(query_params)
    now = retrieved_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")

    if operation in _UNSUPPORTED_OPERATIONS:
        return _unavailable(
            operation,
            "unsupported",
            "e06_capability_boundary",
            query,
            now,
            f"{operation} is explicitly unsupported in E06",
        )
    if operation not in _FETCHERS:
        raise ValueError(f"unknown OpenBB operation: {operation}")

    provider, source, fetcher = _FETCHERS[operation]
    try:
        result = run_async(
            fetcher.fetch_data,
            params=query,
            credentials=dict(credentials) if credentials is not None else None,
        )
        rows = _serialize_result(result)
    except EmptyDataError as exc:
        return _unavailable(operation, provider, source, query, now, str(exc))
    except UnauthorizedError as exc:
        raise VendorNotConfiguredError(str(exc)) from exc
    except VendorError:
        raise
    except Exception as exc:
        raise OpenBBProviderError(
            f"{source} failed for {operation}: {exc}"
        ) from exc

    if not rows:
        return _unavailable(
            operation, provider, source, query, now, "provider returned no data"
        )

    data_as_of = _latest_as_of(rows)
    if stale_before is not None and data_as_of is not None:
        left = data_as_of.date() if isinstance(data_as_of, datetime) else data_as_of
        right = stale_before.date() if isinstance(stale_before, datetime) else stale_before
        if left < right:
            return CanonicalData(
                operation=operation,
                availability=Availability.STALE,
                provider=provider,
                source=source,
                retrieved_at=now,
                payload=None,
                symbol=str(query["symbol"]) if query.get("symbol") is not None else None,
                data_as_of=data_as_of,
                reporting_period=(
                    str(query["period"]) if query.get("period") is not None else None
                ),
                unit=_first_present(rows, "unit"),
                currency=_first_present(rows, "currency"),
                reason=f"latest provider data predates caller boundary {stale_before}",
                query=query,
            )

    return CanonicalData(
        operation=operation,
        availability=Availability.AVAILABLE,
        provider=provider,
        source=source,
        retrieved_at=now,
        payload=rows,
        symbol=str(query["symbol"]) if query.get("symbol") is not None else None,
        data_as_of=data_as_of,
        reporting_period=(
            str(query["period"]) if query.get("period") is not None else None
        ),
        unit=_first_present(rows, "unit"),
        currency=_first_present(rows, "currency"),
        query=query,
    )


def _operation(name: str) -> Callable[..., CanonicalData[Any]]:
    def invoke(
        query_params: Mapping[str, Any],
        credentials: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> CanonicalData[Any]:
        return fetch_openbb(name, query_params, credentials, **kwargs)

    return invoke


get_openbb_historical = _operation("historical_ohlcv")
get_openbb_quote = _operation("quote")
get_openbb_profile = _operation("profile")
get_openbb_balance_sheet = _operation("balance_sheet")
get_openbb_cash_flow_statement = _operation("cash_flow_statement")
get_openbb_income_statement = _operation("income_statement")
get_openbb_key_metrics = _operation("key_metrics")
get_openbb_share_statistics = _operation("share_statistics")
get_openbb_price_target_consensus = _operation("price_target_consensus")
get_openbb_finra_short_interest = _operation("finra_short_interest")
