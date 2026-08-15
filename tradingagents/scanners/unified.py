"""Thin E02 envelope bindings for frozen Traditional and Pradeep outputs.

This module is a pure adapter.  It performs no producer evaluation, retrieval,
ranking, routing, persistence, model work, or Technology selection work.
"""

from __future__ import annotations

import hashlib
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
    CounterThesis,
    Gate,
    GateStatus,
    ScanRequest,
    StructuralDisruptionAssessment,
    TraditionalScanResult,
    compile_traditional_scan,
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


class AnalysisPurpose(str, Enum):
    """Frozen analysis-purpose taxonomy (FZ-SEL-001)."""

    BASELINE_SYSTEM = "BASELINE_SYSTEM"
    EXPLORATORY_COMPARE = "EXPLORATORY_COMPARE"
    OWNER_MANUAL_REVIEW = "OWNER_MANUAL_REVIEW"


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
    # Optional Traditional-only payloads (already-computed, additive transport):
    # the six-question Structural Disruption assessment and the AI
    # Counter-Thesis. Serialized as plain JSON-compatible mappings via
    # _serialize_structural_disruption / _serialize_counter_thesis; never
    # populated for non-Traditional systems, never merged across systems, and
    # never turned into a score.
    structural_disruption: dict[str, object] | None = None
    counter_thesis: dict[str, object] | None = None

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
        if self.structural_disruption is not None and not isinstance(
            self.structural_disruption, dict
        ):
            raise UnifiedCandidateError("structural_disruption must be an object or null")
        if self.counter_thesis is not None and not isinstance(self.counter_thesis, dict):
            raise UnifiedCandidateError("counter_thesis must be an object or null")
        if (
            self.structural_disruption is not None or self.counter_thesis is not None
        ) and self.selection_system is not SelectionSystem.TRADITIONAL:
            raise UnifiedCandidateError(
                "structural_disruption and counter_thesis are Traditional-only payloads"
            )

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
        _exact_keys(
            value,
            "selection",
            required,
            frozenset({"structural_disruption", "counter_thesis"}),
        )
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
            structural_disruption=_optional_payload(
                value.get("structural_disruption"), "structural_disruption"
            ),
            counter_thesis=_optional_payload(value.get("counter_thesis"), "counter_thesis"),
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
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
        # Optional Traditional-only payloads are emitted only when present, so
        # selections without them serialize byte-identically to their
        # pre-transport shape (old manifests / envelopes unchanged).
        if self.structural_disruption is not None:
            result["structural_disruption"] = self.structural_disruption
        if self.counter_thesis is not None:
            result["counter_thesis"] = self.counter_thesis
        return result


def _raise_mapping(field_name: str) -> Any:
    raise UnifiedCandidateError(f"{field_name} must be an object")


def _optional_payload(value: object, field_name: str) -> dict[str, object] | None:
    """Return an optional payload mapping as a plain dict, or ``None``.

    ``structural_disruption`` and ``counter_thesis`` are already-computed,
    JSON-compatible payloads; this only checks the container shape (object or
    null) and never re-derives or validates the payload's internal semantics.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise UnifiedCandidateError(f"{field_name} must be an object or null")
    return dict(value)


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


def _serialize_structural_disruption(
    assessment: StructuralDisruptionAssessment,
) -> dict[str, object]:
    """Serialize the frozen six-question Structural Disruption assessment.

    Plain, auditable JSON mirroring the dataclass fields only -- no score, no
    pass/fail coloring, and no reinterpretation of the already-computed
    findings.
    """
    return {
        "method_version": assessment.method_version,
        "questions": [
            {
                "question": question.value,
                "conclusion": finding.conclusion,
                "evidence": list(finding.evidence),
                "counter_evidence": list(finding.counter_evidence),
                "economic_transmission": finding.economic_transmission,
                "incumbent_adaptation": finding.incumbent_adaptation,
                "expected_horizon": finding.expected_horizon,
                "falsification_condition": finding.falsification_condition,
                "confidence": finding.confidence,
                "major_unknowns": list(finding.major_unknowns),
                "methodology_rule_refs": list(finding.methodology_rule_refs),
            }
            for question, finding in sorted(
                assessment.questions.items(), key=lambda item: item[0].value
            )
        ],
    }


def _serialize_counter_thesis(counter: CounterThesis) -> dict[str, object]:
    """Serialize the already-computed AI Counter-Thesis as auditable prose.

    Major judgments carry their finding, confidence level, and machine-state
    contradiction, plus evidence provenance (never the raw canonical payload).
    No score is derived or emitted.
    """
    return {
        "competitive_advantage_erosion": counter.competitive_advantage_erosion,
        "new_entrant_or_technology_substitution": (
            counter.new_entrant_or_technology_substitution
        ),
        "accounting_anomaly": counter.accounting_anomaly,
        "management_narrative_conflict": counter.management_narrative_conflict,
        "customer_supplier_concentration": counter.customer_supplier_concentration,
        "regulatory_geopolitical_risk": counter.regulatory_geopolitical_risk,
        "valuation_assumptions": counter.valuation_assumptions,
        "bull_thesis": counter.bull_thesis,
        "bear_thesis": counter.bear_thesis,
        "disconfirming_evidence": counter.disconfirming_evidence,
        "thesis_break_conditions": counter.thesis_break_conditions,
        "major_judgments": [
            {
                "judgment_id": judgment.judgment_id,
                "finding": judgment.finding,
                "confidence_level": judgment.confidence_level,
                "contradiction": {
                    "present": judgment.contradiction.present,
                    "resolved": judgment.contradiction.resolved,
                    "description": judgment.contradiction.description,
                },
                "evidence": [_canonical_source_ref(data) for data in judgment.evidence],
            }
            for judgment in counter.major_judgments
        ],
    }


def bind_traditional_selection(
    result: TraditionalScanResult,
    binding: TraditionalSelectionBinding,
    *,
    counter_thesis: CounterThesis | None = None,
) -> UnifiedSelection | None:
    """Bind only a frozen Traditional result with an actual G7 candidate tier.

    ``counter_thesis`` is the already-computed AI Counter-Thesis from the scan
    request (caller-owned input, never re-derived here); when supplied it is
    transported verbatim onto the selection for auditable UI disclosure.
    """

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
        structural_disruption=_serialize_structural_disruption(
            result.structural_disruption
        ),
        counter_thesis=(
            None if counter_thesis is None else _serialize_counter_thesis(counter_thesis)
        ),
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


@dataclass(frozen=True, slots=True)
class SelectionRecordRef:
    """The exact E02 selection that produced a governed analysis origin.

    ``selection_system`` is the producing system (FZ-SEL-002).  A baseline
    analysis is only legitimate when this system equals the consuming
    ``system_scope``.
    """

    selection_id: str
    selection_system: SelectionSystem
    company_id: str | None = None

    def __post_init__(self) -> None:
        _string(self.selection_id, "selection_id", minimum=1, maximum=160)
        try:
            system = SelectionSystem(self.selection_system)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("selection_system is not allowed by E02") from exc
        object.__setattr__(self, "selection_system", system)
        _nullable_string(self.company_id, "company_id", minimum=1, maximum=160)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SelectionRecordRef:
        required = frozenset({"selection_id", "selection_system", "company_id"})
        _exact_keys(value, "selection_record_ref", required)
        return cls(
            selection_id=value["selection_id"],  # type: ignore[arg-type]
            selection_system=value["selection_system"],  # type: ignore[arg-type]
            company_id=value["company_id"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "selection_id": self.selection_id,
            "selection_system": self.selection_system.value,
            "company_id": self.company_id,
        }


@dataclass(frozen=True, slots=True)
class SharedFact:
    """A methodology-neutral fact that MAY be shared across systems (FZ-DATA-002).

    The frozen field set is intentionally free of every methodology field
    (no selection_score / setup_score / *_score / *_conclusion /
    entry_recommendation / position_recommendation / methodology_weight /
    methodology_rank).  This neutrality is structural, not documented-only.
    """

    fact_id: str
    fact_type: str
    fact: str
    source_refs: tuple[str, ...]
    data_as_of: str | None
    provenance: str

    def __post_init__(self) -> None:
        _string(self.fact_id, "fact_id", minimum=1, maximum=160)
        _string(self.fact_type, "fact_type", minimum=1, maximum=80)
        _string(self.fact, "fact", minimum=1, maximum=8000)
        if not isinstance(self.source_refs, tuple) or not self.source_refs:
            raise UnifiedCandidateError("shared fact requires source_refs")
        for ref in self.source_refs:
            _string(ref, "source_refs", minimum=1, maximum=1000)
        _nullable_string(self.data_as_of, "shared_fact.data_as_of", maximum=64)
        _string(self.provenance, "shared_fact.provenance", minimum=1, maximum=2000)


@dataclass(frozen=True, slots=True)
class SystemEvidenceClaim:
    """A system-scoped derived claim (FZ-DATA-003).

    Must only be consumed by the system named in ``system_scope``; any other
    system reading it is a cross-system contamination.
    """

    claim_id: str
    system_scope: SelectionSystem
    claim_type: str
    fact_refs: tuple[str, ...]
    claim: str
    confidence: str
    methodology_rule_refs: tuple[str, ...]
    data_as_of: str | None
    provenance: str

    def __post_init__(self) -> None:
        _string(self.claim_id, "claim_id", minimum=1, maximum=160)
        try:
            scope = SelectionSystem(self.system_scope)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("claim system_scope is not allowed by E02") from exc
        object.__setattr__(self, "system_scope", scope)
        _string(self.claim_type, "claim_type", minimum=1, maximum=80)
        if not isinstance(self.fact_refs, tuple):
            raise UnifiedCandidateError("claim fact_refs must be a tuple")
        for ref in self.fact_refs:
            _string(ref, "fact_refs", minimum=1, maximum=160)
        _string(self.claim, "claim", minimum=1, maximum=8000)
        _string(self.confidence, "claim confidence", minimum=1, maximum=64)
        for ref in self.methodology_rule_refs:
            _string(ref, "methodology_rule_refs", minimum=1, maximum=160)
        _nullable_string(self.data_as_of, "claim.data_as_of", maximum=64)
        _string(self.provenance, "claim provenance", minimum=1, maximum=2000)

    def require_system_scope(self, consuming_system: SelectionSystem) -> None:
        """Fail closed if a foreign system tries to consume this claim."""
        if self.system_scope is not consuming_system:
            raise UnifiedCandidateError(
                "CROSS_SYSTEM_CONTAMINATION: claim "
                f"{self.claim_id!r} is scoped to {self.system_scope.value!r}, "
                f"not {consuming_system.value!r}"
            )


@dataclass(frozen=True, slots=True)
class SystemAnalysisSnapshot:
    """A system-scoped, E02-bound analysis snapshot (FZ-DATA-005)."""

    snapshot_id: str
    system_scope: SelectionSystem
    methodology_version: str
    data_as_of: str | None
    candidate_ref: str
    selection_record_ref: SelectionRecordRef | None
    analysis_purpose: AnalysisPurpose
    portfolio_eligible: bool
    shared_fact_refs: tuple[str, ...]
    system_evidence_claim_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    payload_type: str
    payload_hash: str

    def __post_init__(self) -> None:
        _string(self.snapshot_id, "snapshot_id", minimum=1, maximum=160)
        try:
            scope = SelectionSystem(self.system_scope)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("snapshot system_scope is not allowed by E02") from exc
        object.__setattr__(self, "system_scope", scope)
        _string(self.methodology_version, "methodology_version", minimum=1, maximum=80)
        _nullable_string(self.data_as_of, "snapshot.data_as_of", maximum=64)
        _string(self.candidate_ref, "candidate_ref", minimum=1, maximum=160)
        if self.selection_record_ref is not None and not isinstance(
            self.selection_record_ref, SelectionRecordRef
        ):
            raise UnifiedCandidateError("selection_record_ref must be SelectionRecordRef or null")
        try:
            purpose = AnalysisPurpose(self.analysis_purpose)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("analysis_purpose is not allowed") from exc
        object.__setattr__(self, "analysis_purpose", purpose)
        if not isinstance(self.portfolio_eligible, bool):
            raise UnifiedCandidateError("portfolio_eligible must be boolean")
        for ref in self.shared_fact_refs:
            _string(ref, "shared_fact_refs", minimum=1, maximum=160)
        for ref in self.system_evidence_claim_refs:
            _string(ref, "system_evidence_claim_refs", minimum=1, maximum=160)
        for ref in self.provenance_refs:
            _string(ref, "provenance_refs", minimum=1, maximum=160)
        _string(self.payload_type, "payload_type", minimum=1, maximum=120)
        _string(self.payload_hash, "payload_hash", minimum=1, maximum=128)
        # Baseline eligibility: selection origin must match the consuming system.
        if purpose is AnalysisPurpose.BASELINE_SYSTEM:
            if self.selection_record_ref is None:
                raise UnifiedCandidateError(
                    "a baseline snapshot requires a selection_record_ref"
                )
            if self.selection_record_ref.selection_system is not scope:
                raise UnifiedCandidateError(
                    "baseline selection origin does not match snapshot system_scope"
                )
            if not self.portfolio_eligible:
                raise UnifiedCandidateError("a baseline snapshot must be portfolio_eligible")
        elif self.portfolio_eligible:
            raise UnifiedCandidateError(
                "only a baseline snapshot may be portfolio_eligible"
            )


@dataclass(frozen=True, slots=True)
class SystemPortfolioContext:
    """A system-scoped portfolio context (FZ-PCTX-001).

    The minimum semantic representation of a same-system portfolio context
    reused by current contracts. Positions/exposures/risk metrics stay
    opaque references because no portfolio engine is authorized; the frozen
    semantic is the ``system_scope``, which makes foreign-context rejection
    mechanically checkable.
    """

    portfolio_context_id: str
    system_scope: SelectionSystem
    as_of: str | None
    cash: str | None = None
    positions: str | None = None
    exposures: str | None = None
    risk_metrics: str | None = None
    source_portfolio_id: str | None = None

    def __post_init__(self) -> None:
        _string(self.portfolio_context_id, "portfolio_context_id", minimum=1, maximum=160)
        try:
            scope = SelectionSystem(self.system_scope)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("portfolio context system_scope is not allowed") from exc
        object.__setattr__(self, "system_scope", scope)
        _nullable_string(self.as_of, "portfolio_context.as_of", maximum=64)
        _nullable_string(self.cash, "portfolio_context.cash", maximum=1000)
        _nullable_string(self.positions, "portfolio_context.positions", maximum=8000)
        _nullable_string(self.exposures, "portfolio_context.exposures", maximum=8000)
        _nullable_string(self.risk_metrics, "portfolio_context.risk_metrics", maximum=8000)
        _nullable_string(
            self.source_portfolio_id, "portfolio_context.source_portfolio_id", maximum=160
        )

    def require_system_scope(self, consuming_system: SelectionSystem) -> None:
        """Fail closed if a foreign system tries to consume this context."""
        if self.system_scope is not consuming_system:
            raise UnifiedCandidateError(
                "CROSS_SYSTEM_CONTAMINATION: portfolio context "
                f"{self.portfolio_context_id!r} is scoped to {self.system_scope.value!r}, "
                f"not {consuming_system.value!r}"
            )


@dataclass(frozen=True, slots=True)
class SystemDecisionEvent:
    """A lean, system-scoped, E02-bound decision record (FZ-EVT-001).

    References its analysis snapshot by id + hash; it does not duplicate the
    full analysis rationale.
    """

    decision_id: str
    system_scope: SelectionSystem
    unified_candidate_ref: str
    selection_record_ref: SelectionRecordRef | None
    analysis_purpose: AnalysisPurpose
    portfolio_eligible: bool
    decision_time: str
    data_as_of: str | None
    position_state_at_decision: str
    action_intent: str
    methodology_decision_code: str
    reason_summary: str
    analysis_snapshot_ref: str
    analysis_snapshot_hash: str
    execution_availability: str | None = None
    reference_market_price: float | None = None
    portfolio_context_ref: SystemPortfolioContext | None = None
    approved_position_size_or_target_weight: str | None = None
    recheck_trigger: str | None = None
    review_due: str | None = None

    def __post_init__(self) -> None:
        _string(self.decision_id, "decision_id", minimum=1, maximum=160)
        try:
            scope = SelectionSystem(self.system_scope)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("decision system_scope is not allowed by E02") from exc
        object.__setattr__(self, "system_scope", scope)
        _string(self.unified_candidate_ref, "unified_candidate_ref", minimum=1, maximum=160)
        if self.selection_record_ref is not None and not isinstance(
            self.selection_record_ref, SelectionRecordRef
        ):
            raise UnifiedCandidateError("selection_record_ref must be SelectionRecordRef or null")
        try:
            purpose = AnalysisPurpose(self.analysis_purpose)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("analysis_purpose is not allowed") from exc
        object.__setattr__(self, "analysis_purpose", purpose)
        if not isinstance(self.portfolio_eligible, bool):
            raise UnifiedCandidateError("portfolio_eligible must be boolean")
        _string(self.decision_time, "decision_time", minimum=1, maximum=64)
        _nullable_string(self.data_as_of, "decision.data_as_of", maximum=64)
        _string(self.position_state_at_decision, "position_state_at_decision", minimum=1, maximum=32)
        _string(self.action_intent, "action_intent", minimum=1, maximum=32)
        _string(self.methodology_decision_code, "methodology_decision_code", minimum=1, maximum=120)
        _string(self.reason_summary, "reason_summary", minimum=1, maximum=4000)
        _string(self.analysis_snapshot_ref, "analysis_snapshot_ref", minimum=1, maximum=160)
        _string(self.analysis_snapshot_hash, "analysis_snapshot_hash", minimum=1, maximum=128)
        _nullable_string(self.execution_availability, "execution_availability", maximum=32)
        if self.reference_market_price is not None and not math.isfinite(
            self.reference_market_price
        ):
            raise UnifiedCandidateError("reference_market_price must be finite")
        if self.portfolio_context_ref is not None and not isinstance(
            self.portfolio_context_ref, SystemPortfolioContext
        ):
            raise UnifiedCandidateError(
                "portfolio_context_ref must be a SystemPortfolioContext or null"
            )
        if self.portfolio_context_ref is not None and (
            self.portfolio_context_ref.system_scope is not scope
        ):
            raise UnifiedCandidateError(
                "CROSS_SYSTEM_CONTAMINATION: decision "
                f"{self.decision_id!r} is scoped to {scope.value!r} but its "
                f"portfolio context {self.portfolio_context_ref.portfolio_context_id!r} "
                f"is scoped to {self.portfolio_context_ref.system_scope.value!r}"
            )
        _nullable_string(
            self.approved_position_size_or_target_weight,
            "approved_position_size_or_target_weight",
            maximum=120,
        )
        _nullable_string(self.recheck_trigger, "recheck_trigger", maximum=1000)
        _nullable_string(self.review_due, "review_due", maximum=64)
        if purpose is AnalysisPurpose.BASELINE_SYSTEM:
            if self.selection_record_ref is None:
                raise UnifiedCandidateError("a baseline decision requires a selection_record_ref")
            if self.selection_record_ref.selection_system is not scope:
                raise UnifiedCandidateError(
                    "baseline selection origin does not match decision system_scope"
                )
            if not self.portfolio_eligible:
                raise UnifiedCandidateError("a baseline decision must be portfolio_eligible")
        elif self.portfolio_eligible:
            raise UnifiedCandidateError("only a baseline decision may be portfolio_eligible")

    def require_matches_snapshot(self, snapshot: SystemAnalysisSnapshot) -> None:
        """Fail closed unless this decision's system and snapshot binding agree."""
        if not isinstance(snapshot, SystemAnalysisSnapshot):
            raise UnifiedCandidateError("snapshot must be a SystemAnalysisSnapshot")
        if self.system_scope is not snapshot.system_scope:
            raise UnifiedCandidateError(
                "CROSS_SYSTEM_CONTAMINATION: decision "
                f"{self.decision_id!r} is scoped to {self.system_scope.value!r} but its "
                f"snapshot {snapshot.snapshot_id!r} is scoped to {snapshot.system_scope.value!r}"
            )
        if self.analysis_snapshot_ref != snapshot.snapshot_id:
            raise UnifiedCandidateError(
                "decision snapshot ref does not match the bound snapshot id"
            )


@dataclass(frozen=True, slots=True)
class AnalysisGovernance:
    """Resolved analysis purpose and portfolio eligibility (FZ-SEL)."""

    analysis_purpose: AnalysisPurpose
    system_scope: SelectionSystem | None
    portfolio_eligible: bool


def derive_analysis_governance(
    system_scope: SelectionSystem | str | None,
    selection_record_ref: SelectionRecordRef | None,
    analysis_purpose: AnalysisPurpose | str | None,
) -> AnalysisGovernance:
    """Resolve purpose + portfolio eligibility, failing closed on ambiguity.

    - No selection origin -> OWNER_MANUAL_REVIEW, portfolio_eligible=False.
    - EXPLORATORY_COMPARE -> portfolio_eligible=False.
    - BASELINE_SYSTEM -> requires a selection origin whose selection_system
      equals the consuming ``system_scope``; only then portfolio_eligible=True.
    """

    scope: SelectionSystem | None
    if system_scope is None:
        scope = None
    else:
        try:
            scope = SelectionSystem(system_scope)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("system_scope is not allowed by E02") from exc

    purpose: AnalysisPurpose
    if analysis_purpose is None:
        purpose = (
            AnalysisPurpose.OWNER_MANUAL_REVIEW
            if selection_record_ref is None
            else AnalysisPurpose.BASELINE_SYSTEM
        )
    else:
        try:
            purpose = AnalysisPurpose(analysis_purpose)
        except (TypeError, ValueError) as exc:
            raise UnifiedCandidateError("analysis_purpose is not allowed") from exc

    if selection_record_ref is None:
        if purpose is not AnalysisPurpose.OWNER_MANUAL_REVIEW:
            raise UnifiedCandidateError(
                "a governed purpose requires a selection_record_ref; "
                "missing origin must fail closed as OWNER_MANUAL_REVIEW"
            )
        return AnalysisGovernance(
            analysis_purpose=AnalysisPurpose.OWNER_MANUAL_REVIEW,
            system_scope=scope,
            portfolio_eligible=False,
        )

    # A selection origin is present: a consuming system_scope is mandatory.
    if scope is None:
        raise UnifiedCandidateError(
            "a selection_record_ref requires an explicit system_scope; "
            "refusing to infer scope from the selection"
        )
    if purpose is AnalysisPurpose.BASELINE_SYSTEM:
        if selection_record_ref.selection_system is not scope:
            raise UnifiedCandidateError(
                "baseline selection origin does not match system_scope; "
                "refusing to promote a foreign selection to baseline"
            )
        return AnalysisGovernance(
            analysis_purpose=AnalysisPurpose.BASELINE_SYSTEM,
            system_scope=scope,
            portfolio_eligible=True,
        )
    return AnalysisGovernance(
        analysis_purpose=purpose,
        system_scope=scope,
        portfolio_eligible=False,
    )


def build_traditional_snapshot(
    result: TraditionalScanResult,
    selection: UnifiedSelection,
    selection_record_ref: SelectionRecordRef,
    *,
    analysis_purpose: AnalysisPurpose = AnalysisPurpose.BASELINE_SYSTEM,
    portfolio_eligible: bool = True,
    data_as_of: str | None = None,
    snapshot_id: str | None = None,
    candidate_ref: str | None = None,
) -> SystemAnalysisSnapshot:
    """Produce a real Traditional ``SystemAnalysisSnapshot`` at the binding
    boundary (FZ-DATA-005 / CUR-003).

    This is the smallest existing production boundary with sufficient data:
    the compiler's ``TraditionalScanResult`` (facts + claims + structural
    disruption) and the bound ``UnifiedSelection`` (E02 selection identity).
    The snapshot references the facts/claims the compiler de-duplicated rather
    than re-deriving them, so correlated evidence is never double counted.
    """
    if not isinstance(result, TraditionalScanResult):
        raise UnifiedCandidateError("result must be TraditionalScanResult")
    if not isinstance(selection, UnifiedSelection):
        raise UnifiedCandidateError("selection must be UnifiedSelection")
    if selection.selection_system is not SelectionSystem.TRADITIONAL:
        raise UnifiedCandidateError("a Traditional snapshot requires a Traditional selection")
    if not isinstance(selection_record_ref, SelectionRecordRef):
        raise UnifiedCandidateError("selection_record_ref must be SelectionRecordRef")

    resolved_snapshot_id = snapshot_id or f"snapshot:{selection.selection_id}"
    resolved_candidate_ref = candidate_ref or selection_record_ref.company_id or selection.selection_id
    resolved_data_as_of = data_as_of or selection.data_as_of

    # CUR-008 / FZ-DATA-003: the snapshot consumes the compiler's claims at a
    # real production boundary — fail closed on any foreign system_scope before
    # the claim ids are referenced, so a cross-system claim read is mechanically
    # rejected rather than silently copied.
    for claim in result.system_evidence_claims:
        claim.require_system_scope(SelectionSystem.TRADITIONAL)

    # CUR-001: the snapshot payload binds the structural 6Q rationale
    # (evidence, counter-evidence, falsification, timing, confidence, and
    # methodology refs), not just its method version, so a candidate's
    # structural thesis is part of the immutable snapshot identity.
    sd = result.structural_disruption
    sd_lines = [sd.method_version]
    for question in sorted(sd.questions, key=lambda q: q.value):
        finding = sd.questions[question]
        sd_lines.extend(
            [
                f"{question.value}:{finding.conclusion}",
                f"evidence:{'|'.join(finding.evidence)}",
                f"counter:{'|'.join(finding.counter_evidence)}",
                f"transmission:{finding.economic_transmission or ''}",
                f"adaptation:{finding.incumbent_adaptation or ''}",
                f"horizon:{finding.expected_horizon or ''}",
                f"falsification:{finding.falsification_condition or ''}",
                f"confidence:{finding.confidence or ''}",
                f"unknowns:{'|'.join(finding.major_unknowns)}",
                f"refs:{'|'.join(finding.methodology_rule_refs)}",
            ]
        )

    payload_parts = [
        result.entity,
        result.candidate_tier or "",
        "\n".join(sd_lines),
        ",".join(
            f"{gate.value}:{result.gate_evaluations[gate].status.value}" for gate in Gate
        ),
    ]
    payload_hash = hashlib.sha256("\n".join(payload_parts).encode("utf-8")).hexdigest()

    return SystemAnalysisSnapshot(
        snapshot_id=resolved_snapshot_id,
        system_scope=SelectionSystem.TRADITIONAL,
        methodology_version=selection.producer_version,
        data_as_of=resolved_data_as_of,
        candidate_ref=resolved_candidate_ref,
        selection_record_ref=selection_record_ref,
        analysis_purpose=analysis_purpose,
        portfolio_eligible=portfolio_eligible,
        shared_fact_refs=tuple(fact.fact_id for fact in result.shared_facts),
        system_evidence_claim_refs=tuple(
            claim.claim_id for claim in result.system_evidence_claims
        ),
        provenance_refs=tuple(ref.evidence_id for ref in selection.evidence_refs),
        payload_type="TraditionalAnalysisPayload",
        payload_hash=payload_hash,
    )


def compile_traditional_candidate(
    request: ScanRequest,
    binding: TraditionalSelectionBinding,
    identity: CompanyIdentityBinding,
    selection_record_ref: SelectionRecordRef,
    *,
    analysis_purpose: AnalysisPurpose = AnalysisPurpose.BASELINE_SYSTEM,
    portfolio_eligible: bool = True,
) -> tuple[UnifiedCandidate, SystemAnalysisSnapshot, TraditionalScanResult]:
    """Drive the real Traditional production path end to end.

    Compiles caller-supplied canonical evidence under the E04 compiler, binds
    the result to an E02 ``UnifiedSelection``, produces and binds a
    system-scoped ``SystemAnalysisSnapshot``, and assembles the E02 candidate.
    This is the single production seam that owns Traditional scanner/analysis
    integration — it reuses the existing compiler (E04), binder (E09), snapshot
    builder, and E02 assembly rather than a second candidate schema or runtime.
    """
    result = compile_traditional_scan(request)
    selection = bind_traditional_selection(
        result,
        binding,
        counter_thesis=request.ai_research.counter_thesis,
    )
    if selection is None:
        raise UnifiedCandidateError(
            "Traditional compiler produced no actual G7 candidate selection; "
            "cannot assemble a candidate or snapshot"
        )
    snapshot = build_traditional_snapshot(
        result,
        selection,
        selection_record_ref,
        analysis_purpose=analysis_purpose,
        portfolio_eligible=portfolio_eligible,
    )
    candidate = assemble_unified_candidate(identity, (selection,))
    return candidate, snapshot, result
