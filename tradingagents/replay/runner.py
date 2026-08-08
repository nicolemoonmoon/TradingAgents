"""Offline deterministic fixture-backed replay/backtest seam.

This module is intentionally self-contained and uses only the Python
standard library. It has no capability to open network connections, read
process environment variables, run subprocesses, import modules
dynamically, patch runtime symbols, or talk to a broker/order-management
system -- none of those facilities are imported anywhere below, so the
corresponding ``enforce_*_denied`` methods are unconditional: there is no
code path in this module that could do the denied thing even if the
caller wanted it to.

Public API
----------
``ReplayRunner`` exposes:

* ``run`` -- execute one deterministic, fixture-backed replay/backtest
  cycle and return a canonical, hashable result record. Denies before
  normal execution if the caller-supplied dependency_lock_sha256 does
  not exactly match the frozen dependency lock hash bound to this seam.
* ``save_checkpoint`` / ``resume_from_checkpoint`` -- persist and resume
  a run, binding dataset, code, config, dependency-lock and seed hashes.
  Checkpoint paths are authorized only if they resolve under the frozen
  checkpoint root. Authorization is enforced by opening ``/`` as a
  directory descriptor and walking every path component -- first the
  frozen checkpoint-root ancestry, then every requested parent
  component, then the leaf -- descriptor-relative with
  ``O_DIRECTORY | O_NOFOLLOW`` (``O_NOFOLLOW`` alone for the leaf). All
  checkpoint bytes I/O happens only through the descriptor obtained from
  that final, already-validated open; there is no separate resolve/stat
  step followed by a later pathname reopen, so a symlink swapped in
  after a check but before the open still fails closed because the open
  itself carries ``O_NOFOLLOW``. Symlink traversal or a symlink leaf at
  any level raises ``PolicyDeniedError`` before any outside-root read or
  write. Missing parent directories are never created by this module.
* ``enforce_network_denied``, ``enforce_live_execution_denied``,
  ``enforce_broker_write_denied``, ``enforce_production_credentials_denied``,
  ``enforce_cross_project_write_denied``, ``enforce_global_direct_write_denied``
  -- explicit, always-deny policy probes that produce a deterministic
  error record for audit/verification purposes.

All file inputs/outputs are explicit, caller-supplied paths. Nothing in
this module infers, guesses, or writes to a default/global/project path.
"""

from __future__ import annotations

import csv
import errno
import hashlib
import io
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ReplaySeamError",
    "FixtureIntegrityError",
    "ConfigValidationError",
    "MarketCalendarError",
    "FutureDataAccessError",
    "CheckpointBindingMismatchError",
    "PolicyDeniedError",
    "ReplayRunner",
]


class ReplaySeamError(Exception):
    """Base class for all errors raised by this replay seam."""


class FixtureIntegrityError(ReplaySeamError):
    """Raised when a fixture's SHA-256 does not match its source metadata."""


class ConfigValidationError(ReplaySeamError):
    """Raised when a config artifact is missing required fields or asserts
    a non-deny/non-disabled posture that this offline seam does not permit."""


class MarketCalendarError(ReplaySeamError):
    """Raised when market-time/calendar context is missing, inconsistent,
    or leaves no data available for the replay."""


class FutureDataAccessError(ReplaySeamError):
    """Raised when a row later than authoritative_as_of_utc is explicitly
    requested for consumption (lookahead-bias rejection)."""


class CheckpointBindingMismatchError(ReplaySeamError):
    """Raised when a checkpoint resume is attempted with a dataset, code,
    config, dependency-lock, or seed binding that does not exactly match
    the checkpoint's recorded binding, or when the checkpoint path does
    not exist. Also raised by ``run`` when the caller-supplied
    dependency_lock_sha256 does not exactly match the frozen dependency
    lock hash bound to this seam, before any other execution takes
    place."""


class PolicyDeniedError(ReplaySeamError):
    """Raised by every ``enforce_*_denied`` policy probe, and by the
    checkpoint path boundary enforcement in ``save_checkpoint`` /
    ``resume_from_checkpoint`` when a checkpoint path does not resolve
    under the frozen checkpoint root or when any component along that
    path is (or races to become) a symlink. This seam has no implemented
    capability for the other denied actions; those probes exist to
    produce a deterministic, auditable denial record before any
    filesystem mutation occurs."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise TypeError(f"object of type {type(obj)!r} is not JSON serializable")


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default)


def _parse_utc(timestamp: str) -> datetime:
    text = timestamp.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SYMLINK_ESCAPE_ERRNOS: Tuple[int, ...] = (errno.ELOOP, errno.ENOTDIR)


class ReplayRunner:
    """Deterministic, offline, fixture-backed replay/backtest runner.

    Every method that touches the filesystem takes an explicit,
    caller-supplied path. Nothing is inferred, defaulted, or written to a
    global or cross-project location.
    """

    REQUIRED_CONFIG_KEYS = (
        "authoritative_as_of_utc",
        "market_calendar_id",
        "market_timezone",
        "random_seed",
        "transaction_cost_bps",
        "slippage_bps",
        "execution_enabled",
        "network",
        "live_execution",
        "broker_write",
        "production_credentials",
        "schema_version",
    )

    REQUIRED_CALENDAR_KEYS = ("calendar_id", "timezone", "sessions", "schema_version")

    # The exact dependency lock hash this seam is bound to. ``run`` denies
    # before any other execution if the caller-supplied
    # dependency_lock_sha256 does not exactly match this value.
    FROZEN_DEPENDENCY_LOCK_SHA256 = (
        "780d00165ef88dd162ab41a0df8ad1b7a8f73f973d5af6dab986676a2c7d859a"
    )

    # The exact, frozen checkpoint root. save_checkpoint/resume_from_checkpoint
    # authorize a checkpoint path only if it resolves under this root; the
    # check is enforced via descriptor-relative, no-follow directory
    # traversal anchored at "/", not by pattern-matching the path string.
    FROZEN_CHECKPOINT_ROOT = (
        "/Users/nicolemoonmoon/ClaudeWork/active-workspaces/"
        "tradingagents-laneb-offline-replay-pilot-artifacts/checkpoints"
    )

    _CHECKPOINT_ROOT_COMPONENTS: Tuple[str, ...] = tuple(
        part for part in FROZEN_CHECKPOINT_ROOT.split("/") if part
    )

    def __init__(self) -> None:
        self.enforcement_log: List[Dict[str, str]] = []

    # ------------------------------------------------------------------
    # Loading and validation
    # ------------------------------------------------------------------

    def load_config(self, config_path: str) -> Tuple[Dict[str, Any], str]:
        """Load and validate a run config; returns (config, config_sha256).

        Fails closed if any required key is missing or if the config
        asserts execution_enabled=true or any of network/live_execution/
        broker_write/production_credentials != "DENY".
        """
        path = Path(config_path)
        raw = path.read_bytes()
        config_sha256 = _sha256_hex(raw)
        config = json.loads(raw.decode("utf-8"))

        missing = [k for k in self.REQUIRED_CONFIG_KEYS if k not in config]
        if missing:
            raise ConfigValidationError(
                f"config missing required keys: {sorted(missing)}"
            )
        if config["execution_enabled"] is not False:
            raise ConfigValidationError("config execution_enabled must be false")
        for key in ("network", "live_execution", "broker_write", "production_credentials"):
            if config[key] != "DENY":
                raise ConfigValidationError(f"config field {key!r} must be 'DENY'")
        return config, config_sha256

    def load_market_calendar(self, market_calendar_path: str) -> Dict[str, Any]:
        """Load and validate a market calendar artifact."""
        path = Path(market_calendar_path)
        calendar = json.loads(path.read_bytes().decode("utf-8"))
        missing = [k for k in self.REQUIRED_CALENDAR_KEYS if k not in calendar]
        if missing:
            raise MarketCalendarError(
                f"market calendar missing required keys: {sorted(missing)}"
            )
        return calendar

    def validate_market_time_context(
        self, config: Dict[str, Any], calendar: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Cross-check config market timezone/calendar id against the
        calendar artifact and return an explicit market-time-context
        record. Fails closed on any inconsistency."""
        if config["market_calendar_id"] != calendar["calendar_id"]:
            raise MarketCalendarError(
                "config market_calendar_id does not match market calendar calendar_id"
            )
        if config["market_timezone"] != calendar["timezone"]:
            raise MarketCalendarError(
                "config market_timezone does not match market calendar timezone"
            )
        # Validates the as-of timestamp is well-formed; raises on malformed input.
        _parse_utc(config["authoritative_as_of_utc"])
        session_dates = sorted(s["date"] for s in calendar.get("sessions", []))
        return {
            "market_timezone": config["market_timezone"],
            "market_calendar_id": config["market_calendar_id"],
            "authoritative_as_of_utc": config["authoritative_as_of_utc"],
            "calendar_session_dates": session_dates,
        }

    def load_market_data(
        self, fixture_path: str, source_metadata_path: str
    ) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
        """Load a CSV market fixture, verify its raw SHA-256 against the
        source metadata artifact, and return (rows, dataset_sha256,
        source_metadata). Rows are sorted ascending by timestamp.
        """
        raw = Path(fixture_path).read_bytes()
        dataset_sha256 = _sha256_hex(raw)

        metadata = json.loads(Path(source_metadata_path).read_bytes().decode("utf-8"))
        expected = metadata.get("raw_snapshot_sha256")
        if expected != dataset_sha256:
            raise FixtureIntegrityError(
                f"fixture sha256 {dataset_sha256!r} does not match "
                f"source_metadata raw_snapshot_sha256 {expected!r}"
            )

        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        rows: List[Dict[str, Any]] = []
        for raw_row in reader:
            ts = _parse_utc(raw_row["timestamp_utc"])
            rows.append(
                {
                    "timestamp_utc": ts,
                    "timestamp_utc_str": raw_row["timestamp_utc"],
                    "symbol": raw_row["symbol"],
                    "open": float(raw_row["open"]),
                    "high": float(raw_row["high"]),
                    "low": float(raw_row["low"]),
                    "close": float(raw_row["close"]),
                    "volume": float(raw_row["volume"]),
                }
            )
        rows.sort(key=lambda r: r["timestamp_utc"])
        return rows, dataset_sha256, metadata

    # ------------------------------------------------------------------
    # Lookahead-bias enforcement
    # ------------------------------------------------------------------

    def available_rows(
        self, rows: List[Dict[str, Any]], as_of_utc: datetime
    ) -> List[Dict[str, Any]]:
        """Return only rows at or before as_of_utc. This is the normal,
        safe path used by ``run``; rows after the boundary are simply
        excluded, never silently consumed."""
        return [r for r in rows if r["timestamp_utc"] <= as_of_utc]

    def get_row_for_consumption(
        self, rows: List[Dict[str, Any]], index: int, as_of_utc: datetime
    ) -> Dict[str, Any]:
        """Explicitly fetch a single row for consumption. Fails closed
        with ``FutureDataAccessError`` (identifying the offending row) if
        the requested row is later than as_of_utc."""
        if index < 0 or index >= len(rows):
            raise IndexError(f"row index {index} out of range for {len(rows)} rows")
        row = rows[index]
        if row["timestamp_utc"] > as_of_utc:
            raise FutureDataAccessError(
                f"row at index {index} with timestamp_utc={row['timestamp_utc_str']!r} "
                f"is later than authoritative_as_of_utc={_format_utc(as_of_utc)!r}"
            )
        return row

    # ------------------------------------------------------------------
    # Deterministic computation
    # ------------------------------------------------------------------

    def _compute_metrics(
        self, used_rows: List[Dict[str, Any]], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        first_close = used_rows[0]["close"]
        last_close = used_rows[-1]["close"]
        raw_return_bps = ((last_close - first_close) / first_close) * 10000.0
        cost_bps = float(config["transaction_cost_bps"]) + float(config["slippage_bps"])
        net_return_bps = raw_return_bps - cost_bps
        return {
            "first_close": round(first_close, 6),
            "last_close": round(last_close, 6),
            "raw_return_bps": round(raw_return_bps, 6),
            "net_return_bps": round(net_return_bps, 6),
        }

    def build_trading_proposal(
        self, used_rows: List[Dict[str, Any]], config: Dict[str, Any], seed: int
    ) -> Dict[str, Any]:
        """Build a research-only trading proposal. execution_enabled is
        always False, order_submitted is always False, and there is no
        code path in this module capable of submitting an order."""
        rng = random.Random(seed)
        first_close = used_rows[0]["close"]
        last_close = used_rows[-1]["close"]
        momentum = last_close - first_close

        if momentum > 0:
            action = "BUY"
        elif momentum < 0:
            action = "SELL"
        else:
            action = "HOLD"

        momentum_ratio = (momentum / first_close) if first_close else 0.0
        base_confidence = min(1.0, abs(momentum_ratio) * 50.0)
        noise = rng.uniform(-0.01, 0.01)
        confidence = max(0.0, min(1.0, round(base_confidence + noise, 6)))

        slippage_adj = float(config["slippage_bps"]) / 10000.0
        cost_adj = float(config["transaction_cost_bps"]) / 10000.0
        if action == "BUY":
            estimated_fill_price = round(last_close * (1.0 + slippage_adj), 6)
        elif action == "SELL":
            estimated_fill_price = round(last_close * (1.0 - slippage_adj), 6)
        else:
            estimated_fill_price = round(last_close, 6)
        estimated_transaction_cost = round(abs(estimated_fill_price) * cost_adj, 6)

        return {
            "symbol": used_rows[-1]["symbol"],
            "as_of_utc": config["authoritative_as_of_utc"],
            "action": action,
            "confidence": confidence,
            "estimated_fill_price": estimated_fill_price,
            "estimated_transaction_cost": estimated_transaction_cost,
            "transaction_cost_bps": config["transaction_cost_bps"],
            "slippage_bps": config["slippage_bps"],
            "execution_enabled": False,
            "order_submitted": False,
            "broker_order_id": None,
            "disposition": "RESEARCH_ONLY_NO_EXECUTION_PATH",
        }

    # ------------------------------------------------------------------
    # Run / checkpoint / resume
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        fixture_path: str,
        source_metadata_path: str,
        market_calendar_path: str,
        config_path: str,
        code_commit_sha: str,
        dependency_lock_sha256: str,
        seed: int,
    ) -> Dict[str, Any]:
        """Execute one deterministic, fixture-backed replay/backtest
        cycle and return a canonical result record.

        Identical fixture_path/source_metadata_path/market_calendar_path
        contents, config contents, code_commit_sha, dependency_lock_sha256
        and seed produce a byte-identical canonical_result_hash.

        Raises CheckpointBindingMismatchError before any other execution
        if dependency_lock_sha256 does not exactly match this seam's
        frozen dependency lock hash (FROZEN_DEPENDENCY_LOCK_SHA256).
        Raises ConfigValidationError if seed does not match the config's
        random_seed, or if the config asserts a non-deny posture.
        Raises FixtureIntegrityError if the fixture's SHA-256 does not
        match its source metadata. Raises MarketCalendarError if market
        time context is inconsistent or no data is available at or before
        authoritative_as_of_utc.
        """
        if dependency_lock_sha256 != self.FROZEN_DEPENDENCY_LOCK_SHA256:
            raise CheckpointBindingMismatchError(
                f"dependency_lock_sha256 {dependency_lock_sha256!r} does not match "
                f"frozen dependency_lock_sha256 {self.FROZEN_DEPENDENCY_LOCK_SHA256!r}"
            )

        config, config_sha256 = self.load_config(config_path)
        if seed != config["random_seed"]:
            raise ConfigValidationError(
                f"seed mismatch: caller supplied {seed!r} but config "
                f"specifies random_seed={config['random_seed']!r}"
            )

        calendar = self.load_market_calendar(market_calendar_path)
        market_time_context = self.validate_market_time_context(config, calendar)
        as_of_utc = _parse_utc(config["authoritative_as_of_utc"])

        rows, dataset_sha256, _source_metadata = self.load_market_data(
            fixture_path, source_metadata_path
        )
        used_rows = self.available_rows(rows, as_of_utc)
        if not used_rows:
            raise MarketCalendarError(
                "no market data rows are available at or before authoritative_as_of_utc"
            )
        excluded_future_count = len(rows) - len(used_rows)

        metrics = self._compute_metrics(used_rows, config)
        proposal = self.build_trading_proposal(used_rows, config, seed)

        result: Dict[str, Any] = {
            "schema_version": "1.0.0",
            "binding": {
                "dataset_sha256": dataset_sha256,
                "code_commit_sha": code_commit_sha,
                "config_sha256": config_sha256,
                "dependency_lock_sha256": dependency_lock_sha256,
                "random_seed": seed,
            },
            "market_time_context": market_time_context,
            "cost_assumptions": {
                "transaction_cost_bps": config["transaction_cost_bps"],
                "slippage_bps": config["slippage_bps"],
            },
            "dataset_summary": {
                "rows_used": len(used_rows),
                "rows_excluded_future": excluded_future_count,
                "first_timestamp_utc": used_rows[0]["timestamp_utc_str"],
                "last_timestamp_utc": used_rows[-1]["timestamp_utc_str"],
            },
            "metrics": metrics,
            "trading_proposal": proposal,
        }
        result["canonical_result_hash"] = _sha256_hex(
            _canonical_json(result).encode("utf-8")
        )
        return result

    # ------------------------------------------------------------------
    # Checkpoint path boundary enforcement
    #
    # A checkpoint path is authorized only by successfully walking every
    # directory component from "/" down to its parent directory
    # descriptor-relative with O_DIRECTORY | O_NOFOLLOW, then opening the
    # leaf descriptor-relative to that parent with O_NOFOLLOW. There is no
    # separate resolve-or-stat step whose result is later used to open a
    # path string again: the walk itself *is* the open, so a component
    # swapped to a symlink between any two steps still fails closed
    # because every step's own open() carries O_NOFOLLOW.
    # ------------------------------------------------------------------

    def _relative_components_under_checkpoint_root(self, checkpoint_path: str) -> List[str]:
        if not os.path.isabs(checkpoint_path):
            self._deny("checkpoint_path_boundary")
        parts = [p for p in checkpoint_path.split("/") if p != ""]
        for part in parts:
            if part in (".", ".."):
                self._deny("checkpoint_path_boundary")
        root_len = len(self._CHECKPOINT_ROOT_COMPONENTS)
        if len(parts) <= root_len or tuple(parts[:root_len]) != self._CHECKPOINT_ROOT_COMPONENTS:
            self._deny("checkpoint_path_boundary")
        return parts[root_len:]

    def _walk_dir_components(self, start_fd: int, components: List[str]) -> int:
        fd = start_fd
        for name in components:
            try:
                next_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=fd,
                )
            except OSError as exc:
                os.close(fd)
                if exc.errno in _SYMLINK_ESCAPE_ERRNOS:
                    self._deny("checkpoint_path_symlink_escape")
                raise
            os.close(fd)
            fd = next_fd
        return fd

    def _open_checkpoint_root_fd(self) -> int:
        root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        return self._walk_dir_components(root_fd, list(self._CHECKPOINT_ROOT_COMPONENTS))

    def _secure_open_leaf_fd(
        self, parent_fd: int, leaf_name: str, flags: int, mode: int = 0o644
    ) -> int:
        try:
            return os.open(leaf_name, flags | os.O_NOFOLLOW, mode, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno in _SYMLINK_ESCAPE_ERRNOS:
                self._deny("checkpoint_path_symlink_escape")
            raise

    def _open_checkpoint_leaf_fd(
        self, checkpoint_path: str, flags: int, mode: int = 0o644
    ) -> int:
        """Resolve checkpoint_path to an open, already-authorized file
        descriptor. Raises ValueError if checkpoint_path is falsy: this
        module never infers or defaults a checkpoint location. Raises
        PolicyDeniedError if checkpoint_path does not resolve under
        FROZEN_CHECKPOINT_ROOT, contains a relative-traversal component,
        or if any directory/leaf component along the path is a symlink.
        Propagates OSError (e.g. a missing directory) for ordinary
        not-yet-created paths; this module never creates a missing parent
        directory itself.
        """
        if not checkpoint_path:
            raise ValueError("checkpoint_path must be an explicit caller-supplied path")

        relative_components = self._relative_components_under_checkpoint_root(checkpoint_path)
        parent_components, leaf_name = relative_components[:-1], relative_components[-1]

        root_fd = self._open_checkpoint_root_fd()
        parent_fd = self._walk_dir_components(root_fd, parent_components)
        try:
            return self._secure_open_leaf_fd(parent_fd, leaf_name, flags, mode)
        finally:
            os.close(parent_fd)

    def save_checkpoint(
        self, checkpoint_path: str, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Persist a checkpoint to an explicit caller-supplied path.

        See ``_open_checkpoint_leaf_fd`` for the full authorization and
        error semantics. No target is created until the descriptor-relative,
        no-follow leaf open succeeds.
        """
        checkpoint = {
            "schema_version": "1.0.0",
            "binding": dict(result["binding"]),
            "canonical_result_hash": result["canonical_result_hash"],
            "market_time_context": dict(result["market_time_context"]),
            "cost_assumptions": dict(result["cost_assumptions"]),
            "saved_at_utc": _format_utc(datetime.now(timezone.utc)),
            "result": result,
        }
        payload = _canonical_json(checkpoint).encode("utf-8")

        leaf_fd = self._open_checkpoint_leaf_fd(
            checkpoint_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        )
        with os.fdopen(leaf_fd, "wb") as fh:
            fh.write(payload)
        return checkpoint

    def resume_from_checkpoint(
        self,
        checkpoint_path: str,
        *,
        dataset_sha256: str,
        code_commit_sha: str,
        config_sha256: str,
        dependency_lock_sha256: str,
        seed: int,
    ) -> Dict[str, Any]:
        """Resume from a checkpoint. Succeeds only if dataset, code,
        config, dependency-lock and seed all exactly match the
        checkpoint's recorded binding; otherwise raises
        CheckpointBindingMismatchError naming every mismatched dimension.
        Also raises CheckpointBindingMismatchError if checkpoint_path does
        not exist. See ``_open_checkpoint_leaf_fd`` for the checkpoint
        path authorization semantics.
        """
        try:
            leaf_fd = self._open_checkpoint_leaf_fd(checkpoint_path, os.O_RDONLY)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise CheckpointBindingMismatchError(
                    f"checkpoint path does not exist: {checkpoint_path!r}"
                ) from exc
            raise

        with os.fdopen(leaf_fd, "rb") as fh:
            raw = fh.read()
        checkpoint = json.loads(raw.decode("utf-8"))
        binding = checkpoint.get("binding", {})
        expected = {
            "dataset_sha256": dataset_sha256,
            "code_commit_sha": code_commit_sha,
            "config_sha256": config_sha256,
            "dependency_lock_sha256": dependency_lock_sha256,
            "random_seed": seed,
        }
        mismatched = sorted(k for k, v in expected.items() if binding.get(k) != v)
        if mismatched:
            raise CheckpointBindingMismatchError(
                f"checkpoint binding mismatch on dimensions: {mismatched}"
            )
        return checkpoint

    # ------------------------------------------------------------------
    # Fail-closed policy probes
    #
    # This module imports no network, subprocess, dynamic-import, broker,
    # or database library, and reads no environment variable. Each probe
    # below is therefore an unconditional denial: there is no capability
    # in this seam for it to allow.
    # ------------------------------------------------------------------

    def _deny(self, category: str) -> None:
        record = {
            "category": category,
            "decision": "DENY",
            "denied_at_utc": _format_utc(datetime.now(timezone.utc)),
        }
        self.enforcement_log.append(record)
        raise PolicyDeniedError(f"{category} is denied in this offline replay seam")

    def enforce_network_denied(self) -> None:
        """Always raises PolicyDeniedError. No network-capable library is
        imported anywhere in this module."""
        self._deny("network")

    def enforce_live_execution_denied(self) -> None:
        """Always raises PolicyDeniedError. This module has no live
        execution code path."""
        self._deny("live_execution")

    def enforce_broker_write_denied(self) -> None:
        """Always raises PolicyDeniedError. This module has no broker
        SDK or order-write code path."""
        self._deny("broker_write")

    def enforce_production_credentials_denied(self) -> None:
        """Always raises PolicyDeniedError without reading any
        environment variable or credential store."""
        self._deny("production_credentials")

    def enforce_cross_project_write_denied(self) -> None:
        """Always raises PolicyDeniedError. This module has no code path
        that writes outside the frozen checkpoint root or any other
        caller-supplied path outside this project."""
        self._deny("cross_project_write")

    def enforce_global_direct_write_denied(self) -> None:
        """Always raises PolicyDeniedError. This module has no direct
        global-state write path; only a separate, out-of-scope Global
        State Writer could ever mutate global state."""
        self._deny("global_direct_state_write")
