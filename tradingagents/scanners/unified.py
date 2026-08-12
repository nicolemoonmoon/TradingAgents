"""Thin E02 envelope bindings for frozen Traditional and Pradeep outputs.

This module is a pure adapter.  It performs no producer evaluation, retrieval,
ranking, routing, persistence, model work, or Technology selection work.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from tradingagents.dataflows.canonical_data import Availability, CanonicalData
from tradingagents.scanners.pradeep import PradeepEvidenceRef, PradeepScanResult
from tradingagents.scanners.traditional import (
    Gate,
    GateStatus,
    TraditionalScanResult,
)

E02_SCHEMA_VERSION = "1.0.0"


class UnifiedCandidateError(ValueError):
    """Raised when an E02 envelope or producer binding fails closed."""


class IdentityStatus(str, Enum):
    PROVISIONAL = "provisional"
    CANONICAL = "canonical"


class SelectionSystem(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    PRADEEP = "PRADEEP"
    TECHNOLOGY = "TECHNOLOGY"


def _string(
    value: object,
    field_name: str,
    *,
    minimum: int = 0,
    maximum: int,
) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise UnifiedCandidateError(
            f"{field_name} must be a string with length in [{minimum}, {maximum}]"
        )
    return value


def _nullable_string(
    value: object,
    field_name: str,
    *,
    minimum: int = 0,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _string(value, field_name, minimum=minimum, maximum=maximum)


def _exact_keys(
    value: Mapping[str, object],
    field_name: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing or extra:
        raise UnifiedCandidateError(
            f"{field_name} has missing keys {sorted(missing)!r} "
            f"and additional keys {sorted(extra)!r}"
        )


def _array(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise UnifiedCandidateError(f"{field_name} must be an array")
    return value


def _iso_temporal(value: date | datetime, field_name: str) -> str:
    if not isinstance(value, (date, datetime)):
        raise UnifiedCandidateError(f"{field_name} must be a date or datetime")
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    evidence_id: str
    source_type: str
    source_ref: str
    source_url: str | None
    data_as_of: str | None

    def __post_init__(self) -> None:
        _string(self.evidence_id, "evidence_id", minimum=1, maximum=160)
        _string(self.source_type, "source_type", minimum=1, maximum=80)
        _string(self.source_ref, "source_ref", minimum=1, maximum=1000)
        _nullable_string(self.source_url, "source_url", maximum=2000)
        _nullable_string(self.data_as_of, "evidence.data_as_of", maximum=64)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EvidenceRef:
        required = frozenset(
            {"evidence_id", "source_type", "source_ref", "source_url", "data_as_of"}
        )
        _exact_keys(value, "evidence", required)
        return cls(
            evidence_id=value["evidence_id"],  # type: ignore[arg-type]
            source_type=value["source_type"],  # type: ignore[arg-type]
            source_ref=value["source_ref"],  # type: ignore[arg-type]
            source_url=value["source_url"],  # type: ignore[arg-type]
            data_as_of=value["data_as_of"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "source_url": self.source_url,
            "data_as_of": self.data_as_of,
        }


@dataclass(frozen=True, slots=True)
class SystemRank:
    value: float
    meaning: str
    higher_is_better: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not math.isfinite(self.value)
        ):
            raise UnifiedCandidateError("system_rank.value must be a finite number")
        _string(self.meaning, "system_rank.meaning", minimum=1, maximum=240)
        if not isinstance(self.higher_is_better, bool):
            raise UnifiedCandidateError("system_rank.higher_is_better must be boolean")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SystemRank:
        _exact_keys(
            value,
            "system_rank",
            frozenset({"value", "meaning", "higher_is_better"}),
        )
        return cls(
            value=value["value"],  # type: ignore[arg-type]
            meaning=value["meaning"],  # type: ignore[arg-type]
            higher_is_better=value["higher_is_better"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "meaning": self.meaning,
            "higher_is_better": self.higher_is_better,
        }


@dataclass(frozen=True, slots=True)
class UnifiedSelection:
    selection_id: str
    selection_system: SelectionSystem
    producer_version: str
    scanner_id: str
    setup_id: str | None
    matched_rules: tuple[str, ...]
    failed_rules: tuple[str, ...]
    unknown_rules: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    detected_at: str
    data_as_of: str
    system_rank: SystemRank | None

    def __post_init__(self) -> None:
        _string(self.selection_id, "selection_id", minimum=1, maximum=160)
        try:
            system = SelectionSystem(self.selection_system)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("selection_system is not allowed by E02") from exc
        object.__setattr__(self, "selection_system", system)
        _string(self.producer_version, "producer_version", minimum=1, maximum=80)
        _string(self.scanner_id, "scanner_id", minimum=1, maximum=120)
        _nullable_string(self.setup_id, "setup_id", minimum=1, maximum=120)
        _string(self.detected_at, "detected_at", minimum=1, maximum=64)
        _string(self.data_as_of, "selection.data_as_of", minimum=1, maximum=64)

        groups = (self.matched_rules, self.failed_rules, self.unknown_rules)
        if any(not isinstance(group, tuple) for group in groups):
            raise UnifiedCandidateError("rule groups must be tuples")
        for group_name, group in zip(
            ("matched_rules", "failed_rules", "unknown_rules"), groups, strict=True
        ):
            for rule_id in group:
                _string(rule_id, group_name, minimum=1, maximum=160)
        all_rule_ids = tuple(rule_id for group in groups for rule_id in group)
        if len(all_rule_ids) != len(set(all_rule_ids)):
            raise UnifiedCandidateError(
                "matched, failed, and unknown rule IDs must be unique and disjoint"
            )
        if not self.matched_rules:
            raise UnifiedCandidateError("an actual selection requires a matched rule")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise UnifiedCandidateError("an actual selection requires evidence")
        if any(not isinstance(item, EvidenceRef) for item in self.evidence_refs):
            raise UnifiedCandidateError("evidence_refs must contain EvidenceRef values")
        evidence_ids = tuple(item.evidence_id for item in self.evidence_refs)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise UnifiedCandidateError("evidence_id values must be unique per selection")
        if self.system_rank is not None and not isinstance(self.system_rank, SystemRank):
            raise UnifiedCandidateError("system_rank must be SystemRank or null")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> UnifiedSelection:
        required = frozenset(
            {
                "selection_id",
                "selection_system",
                "producer_version",
                "scanner_id",
                "setup_id",
                "matched_rules",
                "failed_rules",
                "unknown_rules",
                "evidence_refs",
                "detected_at",
                "data_as_of",
                "system_rank",
            }
        )
        _exact_keys(value, "selection", required)
        rank_value = value["system_rank"]
        if rank_value is None:
            rank = None
        elif isinstance(rank_value, Mapping):
            rank = SystemRank.from_mapping(rank_value)
        else:
            raise UnifiedCandidateError("system_rank must be an object or null")
        evidence = tuple(
            EvidenceRef.from_mapping(item)
            if isinstance(item, Mapping)
            else (_raise_mapping("evidence"))
            for item in _array(value["evidence_refs"], "evidence_refs")
        )
        return cls(
            selection_id=value["selection_id"],  # type: ignore[arg-type]
            selection_system=value["selection_system"],  # type: ignore[arg-type]
            producer_version=value["producer_version"],  # type: ignore[arg-type]
            scanner_id=value["scanner_id"],  # type: ignore[arg-type]
            setup_id=value["setup_id"],  # type: ignore[arg-type]
            matched_rules=tuple(
                _string(item, "matched_rules", minimum=1, maximum=160)
                for item in _array(value["matched_rules"], "matched_rules")
            ),
            failed_rules=tuple(
                _string(item, "failed_rules", minimum=1, maximum=160)
                for item in _array(value["failed_rules"], "failed_rules")
            ),
            unknown_rules=tuple(
                _string(item, "unknown_rules", minimum=1, maximum=160)
                for item in _array(value["unknown_rules"], "unknown_rules")
            ),
            evidence_refs=evidence,
            detected_at=value["detected_at"],  # type: ignore[arg-type]
            data_as_of=value["data_as_of"],  # type: ignore[arg-type]
            system_rank=rank,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "selection_id": self.selection_id,
            "selection_system": self.selection_system.value,
            "producer_version": self.producer_version,
            "scanner_id": self.scanner_id,
            "setup_id": self.setup_id,
            "matched_rules": list(self.matched_rules),
            "failed_rules": list(self.failed_rules),
            "unknown_rules": list(self.unknown_rules),
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "detected_at": self.detected_at,
            "data_as_of": self.data_as_of,
            "system_rank": None if self.system_rank is None else self.system_rank.to_dict(),
        }


def _raise_mapping(field_name: str) -> Any:
    raise UnifiedCandidateError(f"{field_name} must be an object")


@dataclass(frozen=True, slots=True)
class CompanyIdentityBinding:
    company_id: str
    identity_status: IdentityStatus
    ticker: str | None
    display_name: str | None

    def __post_init__(self) -> None:
        _validate_identity(
            self.company_id,
            self.identity_status,
            self.ticker,
            self.display_name,
        )
        object.__setattr__(self, "identity_status", IdentityStatus(self.identity_status))


def _validate_identity(
    company_id: object,
    identity_status: object,
    ticker: object,
    display_name: object,
) -> None:
    company = _string(company_id, "company_id", minimum=1, maximum=160)
    try:
        status = IdentityStatus(identity_status)
    except (TypeError, ValueError) as exc:
        raise UnifiedCandidateError("identity_status is not allowed by E02") from exc
    symbol = _nullable_string(ticker, "ticker", minimum=1, maximum=32)
    _nullable_string(display_name, "display_name", minimum=1, maximum=240)
    if status is IdentityStatus.PROVISIONAL:
        if symbol is None or symbol != symbol.upper():
            raise UnifiedCandidateError(
                "provisional public identity requires an uppercase ticker"
            )
        if company != f"ticker:{symbol}":
            raise UnifiedCandidateError(
                "provisional company_id must use ticker:<UPPERCASE_SYMBOL>"
            )


@dataclass(frozen=True, slots=True)
class UnifiedCandidate:
    company_id: str
    identity_status: IdentityStatus
    ticker: str | None
    selections: tuple[UnifiedSelection, ...]
    display_name: str | None = None
    schema_version: str = E02_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != E02_SCHEMA_VERSION:
            raise UnifiedCandidateError("schema_version must be exactly 1.0.0")
        _validate_identity(
            self.company_id,
            self.identity_status,
            self.ticker,
            self.display_name,
        )
        object.__setattr__(self, "identity_status", IdentityStatus(self.identity_status))
        if not isinstance(self.selections, tuple) or not self.selections:
            raise UnifiedCandidateError("a unified candidate requires selections")
        if any(not isinstance(item, UnifiedSelection) for item in self.selections):
            raise UnifiedCandidateError("selections must contain UnifiedSelection values")
        selection_ids = tuple(item.selection_id for item in self.selections)
        if len(selection_ids) != len(set(selection_ids)):
            raise UnifiedCandidateError("selection_id values must be unique per candidate")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> UnifiedCandidate:
        required = frozenset(
            {"schema_version", "company_id", "identity_status", "ticker", "selections"}
        )
        _exact_keys(value, "candidate", required, frozenset({"display_name"}))
        selections = tuple(
            UnifiedSelection.from_mapping(item)
            if isinstance(item, Mapping)
            else (_raise_mapping("selection"))
            for item in _array(value["selections"], "selections")
        )
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            company_id=value["company_id"],  # type: ignore[arg-type]
            display_name=value.get("display_name"),  # type: ignore[arg-type]
            identity_status=value["identity_status"],  # type: ignore[arg-type]
            ticker=value["ticker"],  # type: ignore[arg-type]
            selections=selections,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "company_id": self.company_id,
            "display_name": self.display_name,
            "identity_status": self.identity_status.value,
            "ticker": self.ticker,
            "selections": [item.to_dict() for item in self.selections],
        }


@dataclass(frozen=True, slots=True)
class TraditionalEvidenceBinding:
    metric_id: str
    evidence_id: str
    source_type: str
    source_url: str | None

    def __post_init__(self) -> None:
        _string(self.metric_id, "metric_id", minimum=1, maximum=160)
        _string(self.evidence_id, "evidence_id", minimum=1, maximum=160)
        _string(self.source_type, "source_type", minimum=1, maximum=80)
        _nullable_string(self.source_url, "source_url", maximum=2000)


@dataclass(frozen=True, slots=True)
class TraditionalSelectionBinding:
    selection_id: str
    producer_version: str
    scanner_id: str
    setup_id: str | None
    detected_at: str
    data_as_of: str
    evidence: tuple[TraditionalEvidenceBinding, ...]

    def __post_init__(self) -> None:
        _string(self.selection_id, "selection_id", minimum=1, maximum=160)
        _string(self.producer_version, "producer_version", minimum=1, maximum=80)
        _string(self.scanner_id, "scanner_id", minimum=1, maximum=120)
        _nullable_string(self.setup_id, "setup_id", minimum=1, maximum=120)
        if self.setup_id is not None:
            raise UnifiedCandidateError(
                "Traditional setup_id must remain null because the producer defines no setup"
            )
        _string(self.detected_at, "detected_at", minimum=1, maximum=64)
        _string(self.data_as_of, "selection.data_as_of", minimum=1, maximum=64)
        if not isinstance(self.evidence, tuple):
            raise UnifiedCandidateError("Traditional evidence bindings must be a tuple")
        if any(not isinstance(item, TraditionalEvidenceBinding) for item in self.evidence):
            raise UnifiedCandidateError(
                "Traditional evidence must contain TraditionalEvidenceBinding values"
            )


@dataclass(frozen=True, slots=True)
class PradeepEvidenceBinding:
    reference: PradeepEvidenceRef
    evidence_id: str
    source_type: str
    source_url: str | None
    data_as_of: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, PradeepEvidenceRef):
            raise UnifiedCandidateError("reference must be PradeepEvidenceRef")
        _string(self.evidence_id, "evidence_id", minimum=1, maximum=160)
        _string(self.source_type, "source_type", minimum=1, maximum=80)
        _nullable_string(self.source_url, "source_url", maximum=2000)
        _nullable_string(self.data_as_of, "evidence.data_as_of", maximum=64)


def _canonical_source_ref(data: CanonicalData[Any]) -> str:
    provenance = {
        "currency": data.currency,
        "operation": data.operation,
        "provider": data.provider,
        "reporting_period": data.reporting_period,
        "source": data.source,
        "unit": data.unit,
    }
    return json.dumps(provenance, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _pradeep_source_ref(reference: PradeepEvidenceRef) -> str:
    provenance = {
        "description": reference.description,
        "methodology_ref": reference.methodology_ref,
        "observation_ref": reference.observation_ref,
    }
    return json.dumps(provenance, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _bind_traditional_evidence(
    result: TraditionalScanResult,
    binding: TraditionalEvidenceBinding,
) -> EvidenceRef:
    evaluation = result.metric_evaluations.get(binding.metric_id)
    if evaluation is None or evaluation.evidence is None:
        raise UnifiedCandidateError(
            f"Traditional evidence binding is not present in producer output: {binding.metric_id}"
        )
    data = evaluation.evidence
    if data.availability is not Availability.AVAILABLE:
        raise UnifiedCandidateError("Traditional evidence must be available")
    data_as_of = (
        None
        if data.data_as_of is None
        else _iso_temporal(data.data_as_of, "canonical data_as_of")
    )
    return EvidenceRef(
        evidence_id=binding.evidence_id,
        source_type=binding.source_type,
        source_ref=_canonical_source_ref(data),
        source_url=binding.source_url,
        data_as_of=data_as_of,
    )


def bind_traditional_selection(
    result: TraditionalScanResult,
    binding: TraditionalSelectionBinding,
) -> UnifiedSelection | None:
    """Bind only a frozen Traditional result with an actual G7 candidate tier."""

    if not isinstance(result, TraditionalScanResult):
        raise UnifiedCandidateError("result must be TraditionalScanResult")
    g7 = result.gate_evaluations.get(Gate.G7)
    actual = result.candidate_tier is not None and (
        g7 is not None and g7.status is GateStatus.PASS
    )
    if not actual:
        if result.candidate_tier is not None or (
            g7 is not None and g7.status is GateStatus.PASS
        ):
            raise UnifiedCandidateError("inconsistent Traditional G7 candidate state")
        return None
    if set(result.gate_evaluations) != set(Gate):
        raise UnifiedCandidateError("Traditional output must contain the exact G0..G7 gates")

    matched: list[str] = []
    failed: list[str] = []
    unknown: list[str] = []
    status_groups = {
        GateStatus.PASS: matched,
        GateStatus.FAIL: failed,
        GateStatus.REVIEW_REQUIRED: unknown,
    }
    for gate in Gate:
        evaluation = result.gate_evaluations[gate]
        status_groups[evaluation.status].append(evaluation.gate.value)

    evidence_refs = tuple(
        _bind_traditional_evidence(result, item) for item in binding.evidence
    )
    return UnifiedSelection(
        selection_id=binding.selection_id,
        selection_system=SelectionSystem.TRADITIONAL,
        producer_version=binding.producer_version,
        scanner_id=binding.scanner_id,
        setup_id=binding.setup_id,
        matched_rules=tuple(matched),
        failed_rules=tuple(failed),
        unknown_rules=tuple(unknown),
        evidence_refs=evidence_refs,
        detected_at=binding.detected_at,
        data_as_of=binding.data_as_of,
        system_rank=None,
    )


def bind_pradeep_selection(
    result: PradeepScanResult,
    evidence_bindings: Sequence[PradeepEvidenceBinding],
) -> UnifiedSelection | None:
    """Bind only an actual frozen Pradeep selection without altering its decision."""

    if not isinstance(result, PradeepScanResult):
        raise UnifiedCandidateError("result must be PradeepScanResult")
    if not result.selected:
        return None
    if result.selection_id is None or result.detected_at is None or result.data_as_of is None:
        raise UnifiedCandidateError("selected Pradeep output is incomplete")
    if result.system_rank is not None:
        raise UnifiedCandidateError("Pradeep system_rank must remain null")

    by_reference: dict[PradeepEvidenceRef, PradeepEvidenceBinding] = {}
    for binding in evidence_bindings:
        if not isinstance(binding, PradeepEvidenceBinding):
            raise UnifiedCandidateError(
                "Pradeep evidence must contain PradeepEvidenceBinding values"
            )
        if binding.reference in by_reference:
            raise UnifiedCandidateError("Pradeep evidence reference was bound more than once")
        by_reference[binding.reference] = binding
    if set(by_reference) != set(result.evidence_refs):
        raise UnifiedCandidateError(
            "Pradeep evidence bindings must exactly cover producer evidence"
        )
    evidence_refs = tuple(
        EvidenceRef(
            evidence_id=by_reference[reference].evidence_id,
            source_type=by_reference[reference].source_type,
            source_ref=_pradeep_source_ref(reference),
            source_url=by_reference[reference].source_url,
            data_as_of=by_reference[reference].data_as_of,
        )
        for reference in result.evidence_refs
    )
    return UnifiedSelection(
        selection_id=result.selection_id,
        selection_system=SelectionSystem.PRADEEP,
        producer_version=result.producer_version,
        scanner_id=result.scanner_id,
        setup_id=result.setup_id,
        matched_rules=tuple(item.rule_id for item in result.matched_rules),
        failed_rules=tuple(item.rule_id for item in result.failed_rules),
        unknown_rules=tuple(item.rule_id for item in result.unknown_rules),
        evidence_refs=evidence_refs,
        detected_at=_iso_temporal(result.detected_at, "Pradeep detected_at"),
        data_as_of=_iso_temporal(result.data_as_of, "Pradeep data_as_of"),
        system_rank=None,
    )


def assemble_unified_candidate(
    identity: CompanyIdentityBinding,
    selections: Sequence[UnifiedSelection | None],
) -> UnifiedCandidate:
    """Assemble one company envelope, rejecting a zero-selection candidate."""

    if not isinstance(identity, CompanyIdentityBinding):
        raise UnifiedCandidateError("identity must be an explicit CompanyIdentityBinding")
    actual = tuple(item for item in selections if item is not None)
    if any(not isinstance(item, UnifiedSelection) for item in actual):
        raise UnifiedCandidateError("selections contains an invalid value")
    return UnifiedCandidate(
        company_id=identity.company_id,
        display_name=identity.display_name,
        identity_status=identity.identity_status,
        ticker=identity.ticker,
        selections=actual,
    )


def validate_unified_candidate(
    value: UnifiedCandidate | Mapping[str, object],
) -> UnifiedCandidate:
    """Validate a typed candidate or strictly parse an exact E02 mapping."""

    if isinstance(value, UnifiedCandidate):
        return value
    if not isinstance(value, Mapping):
        raise UnifiedCandidateError("candidate must be UnifiedCandidate or object")
    return UnifiedCandidate.from_mapping(value)
