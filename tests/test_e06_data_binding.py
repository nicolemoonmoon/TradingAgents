"""Deterministic, no-network tests for the E06 data-binding surface."""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from unittest import mock

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from tradingagents.dataflows import interface, openbb_adapter
from tradingagents.dataflows.canonical_data import (
    Availability,
    CanonicalData,
    CanonicalDataNotUsableError,
)
from tradingagents.dataflows.errors import VendorError
from tradingagents.dataflows.vectorbt_compute import portfolio_from_signals

NOW = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)


class _SuccessFetcher:
    calls: list[tuple[dict, dict | None]] = []

    @classmethod
    async def fetch_data(cls, params, credentials=None):
        cls.calls.append((params, credentials))
        return [
            {
                "symbol": params["symbol"],
                "date": date(2026, 8, 8),
                "close": 123.45,
                "currency": "USD",
            }
        ]


class _EmptyFetcher:
    @staticmethod
    async def fetch_data(params, credentials=None):
        raise EmptyDataError("no provider rows")


class _NoRowsFetcher:
    @staticmethod
    async def fetch_data(params, credentials=None):
        return []


class _ErrorFetcher:
    @staticmethod
    async def fetch_data(params, credentials=None):
        raise RuntimeError("provider broke")


def _record(availability, payload, reason=None):
    return CanonicalData(
        operation="quote",
        availability=availability,
        provider="yfinance",
        source="openbb_yfinance",
        retrieved_at=NOW,
        payload=payload,
        symbol="AAPL",
        data_as_of=date(2026, 8, 8),
        currency="USD",
        reason=reason,
        query={"symbol": "AAPL"},
    )


@pytest.mark.unit
def test_canonical_available_record_and_provenance_are_preserved():
    record = _record(Availability.AVAILABLE, {"last_price": 123.45})

    assert record.is_usable
    assert record.require_available()["last_price"] == 123.45
    assert record.symbol == "AAPL"
    assert record.provider == "yfinance"
    assert record.source == "openbb_yfinance"
    assert record.retrieved_at == NOW
    assert record.data_as_of == date(2026, 8, 8)
    assert record.currency == "USD"
    assert record.query["symbol"] == "AAPL"


@pytest.mark.unit
@pytest.mark.parametrize("state", [Availability.UNAVAILABLE, Availability.STALE])
def test_non_available_canonical_records_fail_closed(state):
    record = _record(state, None, "explicit reason")

    assert not record.is_usable
    with pytest.raises(CanonicalDataNotUsableError, match="explicit reason"):
        record.require_available()


@pytest.mark.unit
def test_non_available_records_reject_payloads_and_require_reasons():
    with pytest.raises(ValueError, match="cannot carry a payload"):
        _record(Availability.UNAVAILABLE, {"value": 0}, "not usable")
    with pytest.raises(ValueError, match="requires a reason"):
        _record(Availability.STALE, None)


@pytest.mark.unit
def test_canonical_record_is_mutation_resistant():
    record = _record(
        Availability.AVAILABLE,
        {"rows": [{"close": 123.45}]},
    )

    with pytest.raises((AttributeError, TypeError)):
        record.symbol = "MSFT"
    with pytest.raises(TypeError):
        record.payload["rows"][0]["close"] = 0
    with pytest.raises(TypeError):
        record.query["symbol"] = "MSFT"


@pytest.mark.unit
def test_openbb_direct_fetcher_success_maps_to_canonical_record():
    _SuccessFetcher.calls.clear()
    mapping = {
        "quote": ("yfinance", "openbb_yfinance", _SuccessFetcher),
    }
    with mock.patch.object(openbb_adapter, "_FETCHERS", mapping):
        result = openbb_adapter.fetch_openbb(
            "quote",
            {"symbol": "AAPL"},
            {"token": "caller-owned"},
            retrieved_at=NOW,
        )

    assert result.availability is Availability.AVAILABLE
    assert result.symbol == "AAPL"
    assert result.data_as_of == date(2026, 8, 8)
    assert result.currency == "USD"
    assert result.require_available()[0]["close"] == 123.45
    assert _SuccessFetcher.calls == [
        ({"symbol": "AAPL"}, {"token": "caller-owned"})
    ]


@pytest.mark.unit
@pytest.mark.parametrize("fetcher", [_EmptyFetcher, _NoRowsFetcher])
def test_openbb_no_data_maps_to_canonical_unavailable(fetcher):
    mapping = {"quote": ("yfinance", "openbb_yfinance", fetcher)}
    with mock.patch.object(openbb_adapter, "_FETCHERS", mapping):
        result = openbb_adapter.fetch_openbb(
            "quote", {"symbol": "NONE"}, retrieved_at=NOW
        )

    assert result.availability is Availability.UNAVAILABLE
    assert result.payload is None
    with pytest.raises(CanonicalDataNotUsableError):
        result.require_available()


@pytest.mark.unit
def test_openbb_provider_error_uses_existing_vendor_error_taxonomy():
    mapping = {"quote": ("yfinance", "openbb_yfinance", _ErrorFetcher)}
    with mock.patch.object(openbb_adapter, "_FETCHERS", mapping), pytest.raises(
        VendorError, match="provider broke"
    ):
        openbb_adapter.fetch_openbb(
            "quote", {"symbol": "AAPL"}, retrieved_at=NOW
        )


@pytest.mark.unit
def test_openbb_caller_freshness_boundary_maps_stale_fail_closed():
    mapping = {
        "historical_ohlcv": (
            "yfinance",
            "openbb_yfinance",
            _SuccessFetcher,
        )
    }
    with mock.patch.object(openbb_adapter, "_FETCHERS", mapping):
        result = openbb_adapter.fetch_openbb(
            "historical_ohlcv",
            {"symbol": "AAPL"},
            retrieved_at=NOW,
            stale_before=date(2026, 8, 9),
        )

    assert result.availability is Availability.STALE
    with pytest.raises(CanonicalDataNotUsableError):
        result.require_available()


@pytest.mark.unit
def test_finra_short_interest_maps_identity_and_days_to_cover():
    class _FinraFetcher:
        @staticmethod
        async def fetch_data(params, credentials=None):
            return [
                {
                    "symbol": params["symbol"],
                    "current_short_position": 4000,
                    "avg_daily_volume": 1000,
                    "days_to_cover": 4.0,
                    "settlement_date": date(2026, 7, 31),
                }
            ]

    mapping = {
        "finra_short_interest": ("finra", "openbb_finra", _FinraFetcher)
    }
    with mock.patch.object(openbb_adapter, "_FETCHERS", mapping):
        result = openbb_adapter.fetch_openbb(
            "finra_short_interest", {"symbol": "AAPL"}, retrieved_at=NOW
        )

    assert result.provider == "finra"
    assert result.source == "openbb_finra"
    assert result.data_as_of == date(2026, 7, 31)
    assert result.require_available()[0]["days_to_cover"] == 4.0


@pytest.mark.unit
@pytest.mark.parametrize("operation", sorted(openbb_adapter._UNSUPPORTED_OPERATIONS))
def test_e06_unsupported_provider_gaps_fail_closed(operation):
    with mock.patch.object(
        _SuccessFetcher, "fetch_data", side_effect=AssertionError("must not call")
    ):
        result = openbb_adapter.fetch_openbb(
            operation, {"symbol": "AAPL"}, retrieved_at=NOW
        )

    assert result.availability is Availability.UNAVAILABLE
    assert "unsupported in E06" in result.reason


@pytest.mark.unit
def test_adapter_does_not_import_openbb_application_router_or_interface():
    tree = ast.parse(inspect.getsource(openbb_adapter))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert "openbb" not in imported
    assert not any(name.startswith("openbb_core.app") for name in imported)


@pytest.mark.unit
def test_vectorbt_wrapper_uses_caller_series_signals_and_parameters():
    close = [10.0, 11.0, 12.0, 11.0]
    entries = [True, False, False, False]
    exits = [False, False, True, False]
    parameters = {"init_cash": 1000.0, "fees": 0.0, "freq": "1D"}

    first = portfolio_from_signals(close, entries, exits, parameters)
    second = portfolio_from_signals(close, entries, exits, parameters)

    assert first.portfolio is not None
    assert first.metadata["parameters"] == parameters
    assert (
        first.metadata["input_fingerprint_sha256"]
        == second.metadata["input_fingerprint_sha256"]
    )
    assert isinstance(first.metadata, MappingProxyType)


@pytest.mark.unit
def test_vectorbt_wrapper_has_no_hidden_business_parameter_defaults():
    signature = inspect.signature(portfolio_from_signals)
    assert signature.parameters["parameters"].default is inspect.Parameter.empty
    source = inspect.getsource(portfolio_from_signals).lower()
    for policy_name in ("threshold", "rank", "tier", "candidate"):
        assert policy_name not in source


@pytest.mark.unit
def test_existing_router_is_the_single_router_and_exposes_e06_operations():
    assert callable(interface.route_to_vendor)
    assert interface.get_category_for_method("get_openbb_quote") == (
        "canonical_market_data"
    )
    assert set(interface.VENDOR_METHODS["get_openbb_quote"]) == {"openbb_yfinance"}
    assert set(interface.VENDOR_METHODS["get_openbb_finra_short_interest"]) == {
        "openbb_finra"
    }
    adapter_source = inspect.getsource(openbb_adapter)
    assert "def route_to_vendor" not in adapter_source


@pytest.mark.unit
def test_e06_contract_has_no_candidate_or_scanner_authority_fields():
    fields = set(CanonicalData.__dataclass_fields__)
    assert fields.isdisjoint({"score", "rank", "tier", "candidate"})


@pytest.mark.unit
def test_e06_runtime_modules_do_not_depend_on_external_evidence_paths():
    module_paths = [
        Path(inspect.getsourcefile(openbb_adapter)),
        Path(inspect.getsourcefile(portfolio_from_signals)),
        Path(inspect.getsourcefile(CanonicalData)),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in module_paths)
    assert "/Downloads/" not in combined
    assert "TradingAgents E04 FROZEN" not in combined
