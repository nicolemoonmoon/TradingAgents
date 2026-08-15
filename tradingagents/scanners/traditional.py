"""E04-governed Traditional scanner over caller-supplied canonical evidence.

This module is deliberately a compiler, not a data provider or policy owner.
Versioned caller policies supply financial formulas, thresholds, confidence
cut-offs, and tier labels.  The compiler enforces the stable E04 relationships
around those policies and never performs network or model work.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from tradingagents.dataflows.canonical_data import Availability, CanonicalData

if TYPE_CHECKING:  # pragma: no cover - annotations only, never imported at runtime
    from tradingagents.scanners.unified import SharedFact, SystemEvidenceClaim

MAX_UNAVAILABLE_DETERMINISTIC_WEIGHT = 0.25
MIN_PEER_COUNT = 20


class ContractViolation(ValueError):
    """Raised when caller-owned configuration is not a valid governed method."""


class Gate(str, Enum):
    """The frozen E04 gate topology."""

    G0 = "G0_DATA_IDENTITY_FRESHNESS_PROFILE"
    G1 = "G1_FINANCIAL_REALITY_CRITICAL_ACCOUNTING"
    G2 = "G2_BUSINESS_QUALITY_TRAJECTORY"
    G3 = "G3_VALUATION_EMBEDDED_EXPECTATIONS"
    G4 = "G4_FORWARD_FUNDAMENTAL_CHANGE"
    G5 = "G5_MARKET_CONFIRMATION_RISK"
    G6 = "G6_STRUCTURAL_CHANGE_AI_COUNTER_THESIS"
    G7 = "G7_FINAL_CANDIDATE_TIER"


DETERMINISTIC_GATES = (Gate.G1, Gate.G2, Gate.G3, Gate.G4, Gate.G5)


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EconomicProfile(str, Enum):
    ASSET_LIGHT_TECH_PLATFORM = "ASSET_LIGHT_TECH_PLATFORM"
    SEMICONDUCTOR_HARDWARE = "SEMICONDUCTOR_HARDWARE"
    CONSUMER_STAPLES = "CONSUMER_STAPLES"
    CONSUMER_DISCRETIONARY_RETAIL = "CONSUMER_DISCRETIONARY_RETAIL"
    INDUSTRIAL_MANUFACTURING = "INDUSTRIAL_MANUFACTURING"
    BANK = "BANK"
    INSURANCE = "INSURANCE"
    HEALTHCARE_PROFITABLE = "HEALTHCARE_PROFITABLE"
    BIOTECH_PRE_REVENUE = "BIOTECH_PRE_REVENUE"
    ENERGY_MATERIALS = "ENERGY_MATERIALS"
    REAL_ESTATE_REIT = "REAL_ESTATE_REIT"
    UTILITIES_INFRASTRUCTURE = "UTILITIES_INFRASTRUCTURE"
    MIXED_UNRESOLVED = "MIXED_UNRESOLVED"


class G2Responsibility(str, Enum):
    """Stable E04 responsibilities represented by governed G2 rules."""

    BUSINESS_QUALITY_CAPITAL_EFFICIENCY = "BUSINESS_QUALITY_CAPITAL_EFFICIENCY"
    FUNDAMENTAL_TRAJECTORY = "FUNDAMENTAL_TRAJECTORY"


REQUIRED_G2_RESPONSIBILITIES = frozenset(G2Responsibility)


class AIImpactDirection(str, Enum):
    BENEFIT = "BENEFIT"
    RISK = "RISK"
    NEUTRAL = "NEUTRAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AIAction(str, Enum):
    NONE = "NONE"
    MOVE_TIER = "MOVE_TIER"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    VETO = "VETO"


AI_DIMENSIONS = frozenset(
    {
        "exposure",
        "adoption_depth",
        "realized_economics",
        "monetization",
        "defensibility",
        "disruption_risk",
        "capital_discipline",
        "hype_gap",
    }
)


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{name} must be non-empty")
    return value


def _unit_interval(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ContractViolation(f"{name} must be a finite value in [0, 1]")
    return number


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    """A named canonical input plus an explicit unresolved-conflict signal."""

    metric_id: str
    data: CanonicalData[Any]
    source_conflict: bool = False
    conflict_reason: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.metric_id, "metric_id")
        if self.source_conflict and not (self.conflict_reason or "").strip():
            raise ContractViolation("source_conflict requires conflict_reason")
        if not self.source_conflict and self.conflict_reason is not None:
            raise ContractViolation("conflict_reason requires source_conflict")


@dataclass(frozen=True, slots=True)
class MetricRule:
    """One versioned, profile-aware deterministic transformation."""

    metric_id: str
    gate: Gate
    weight: float
    method_version: str
    scorer: Callable[[Any], float]
    profiles: frozenset[EconomicProfile] = frozenset()
    g2_responsibilities: frozenset[G2Responsibility] = frozenset()
    critical: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.metric_id, "metric_id")
        _nonempty(self.method_version, "metric method_version")
        if self.gate not in DETERMINISTIC_GATES:
            raise ContractViolation("metric rules may only belong to G1..G5")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ContractViolation("metric weight must be finite and positive")
        if not callable(self.scorer):
            raise ContractViolation("metric scorer must be callable")
        responsibilities = frozenset(self.g2_responsibilities)
        if not responsibilities <= REQUIRED_G2_RESPONSIBILITIES:
            raise ContractViolation("metric rule contains an unknown G2 responsibility")
        if self.gate is not Gate.G2 and responsibilities:
            raise ContractViolation("G2 responsibilities may only belong to G2 rules")
        object.__setattr__(self, "g2_responsibilities", responsibilities)

    def applies_to(self, profile: EconomicProfile) -> bool:
        return not self.profiles or profile in self.profiles


@dataclass(frozen=True, slots=True)
class MetricRecipe:
    method_version: str
    rules: tuple[MetricRule, ...]
    allow_missing_renormalization: bool
    score_aggregator: Callable[[Sequence[tuple[float, float]]], float]

    def __post_init__(self) -> None:
        _nonempty(self.method_version, "recipe method_version")
        if not self.rules:
            raise ContractViolation("metric recipe must contain rules")
        ids = [rule.metric_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ContractViolation("metric recipe contains duplicate metric_id values")
        if not callable(self.score_aggregator):
            raise ContractViolation("metric recipe score_aggregator must be callable")


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """Caller-governed thresholds and hard-gate designation."""

    method_version: str
    minimum_scores: Mapping[Gate, float]
    hard_gates: frozenset[Gate]

    def __post_init__(self) -> None:
        _nonempty(self.method_version, "gate policy method_version")
        if set(self.minimum_scores) != set(DETERMINISTIC_GATES):
            raise ContractViolation("minimum_scores must define every deterministic gate G1..G5")
        object.__setattr__(
            self,
            "minimum_scores",
            MappingProxyType(
                {
                    gate: _unit_interval(score, f"minimum score for {gate.value}")
                    for gate, score in self.minimum_scores.items()
                }
            ),
        )
        allowed_hard_gates = {Gate.G0, *DETERMINISTIC_GATES, Gate.G6}
        if Gate.G0 not in self.hard_gates or not self.hard_gates <= allowed_hard_gates:
            raise ContractViolation("hard_gates must include G0 and contain only G0..G6")


@dataclass(frozen=True, slots=True)
class DataConfidencePolicy:
    """Caller-owned DATA_CONFIDENCE method and actionability rule."""

    method_version: str
    assess: Callable[[float, tuple[str, ...]], Any]
    is_actionable: Callable[[Any], bool]
    is_reduced: Callable[[Any, Any], bool]

    def __post_init__(self) -> None:
        _nonempty(self.method_version, "data-confidence method_version")
        if not all(
            callable(method)
            for method in (self.assess, self.is_actionable, self.is_reduced)
        ):
            raise ContractViolation("data-confidence policy methods must be callable")


@dataclass(frozen=True, slots=True)
class PeerRelativeInput:
    """Caller-owned percentile method with its actual peer observations."""

    target_metric_id: str
    peer_evidence: tuple[EvidenceInput, ...]
    value_reader: Callable[[Any], float]
    percentile_method: Callable[[float, Sequence[float]], float]
    method_version: str
    narrow_provider_industry: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.target_metric_id, "peer target_metric_id")
        _nonempty(self.method_version, "peer method_version")
        if not callable(self.value_reader) or not callable(self.percentile_method):
            raise ContractViolation("peer value_reader and percentile_method must be callable")
        if self.narrow_provider_industry is not None:
            _nonempty(self.narrow_provider_industry, "narrow_provider_industry")


@dataclass(frozen=True, slots=True)
class ValuationInputs:
    """The six simultaneous E04 valuation outputs, bound to G3 evidence."""

    peer_relative: PeerRelativeInput
    historical_range_metric_id: str
    price_implied_assumptions_metric_id: str
    bull_base_bear_bands_metric_id: str
    upside_downside_asymmetry_metric_id: str
    uncertainty_metric_id: str

    @property
    def metric_ids(self) -> tuple[str, ...]:
        return (
            self.peer_relative.target_metric_id,
            self.historical_range_metric_id,
            self.price_implied_assumptions_metric_id,
            self.bull_base_bear_bands_metric_id,
            self.upside_downside_asymmetry_metric_id,
            self.uncertainty_metric_id,
        )

    def __post_init__(self) -> None:
        for metric_id in self.metric_ids:
            _nonempty(metric_id, "valuation metric_id")
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ContractViolation("valuation dimensions must use distinct metric ids")


@dataclass(frozen=True, slots=True)
class Contradiction:
    """One machine state; human-readable state is derived from it."""

    present: bool
    resolved: bool
    description: str | None = None

    def __post_init__(self) -> None:
        if self.resolved and not self.present:
            raise ContractViolation("a contradiction cannot be resolved if none is present")
        if self.present and not (self.description or "").strip():
            raise ContractViolation("a present contradiction requires a description")

    @property
    def state(self) -> str:
        if not self.present:
            return "NONE"
        return "RESOLVED" if self.resolved else "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class MajorAIJudgment:
    judgment_id: str
    finding: str
    evidence: tuple[CanonicalData[Any], ...]
    confidence_level: str
    contradiction: Contradiction

    def __post_init__(self) -> None:
        _nonempty(self.judgment_id, "judgment_id")
        _nonempty(self.finding, "finding")
        _nonempty(self.confidence_level, "confidence_level")
        if not self.evidence:
            raise ContractViolation("major AI judgments require evidence")


@dataclass(frozen=True, slots=True)
class QuantitativeEconomicImpact:
    """A quantitative claim bound to a value inside canonical evidence."""

    metric_name: str
    value: float
    value_path: tuple[str | int, ...]
    comparison_basis: str
    evidence: CanonicalData[Any]

    def __post_init__(self) -> None:
        _nonempty(self.metric_name, "economic-impact metric_name")
        _nonempty(self.comparison_basis, "economic-impact comparison_basis")
        if not self.value_path:
            raise ContractViolation("economic-impact value_path must be non-empty")
        if not math.isfinite(self.value):
            raise ContractViolation("economic-impact value must be finite")


@dataclass(frozen=True, slots=True)
class AIImpactAssessment:
    direction: AIImpactDirection
    dimensions: Mapping[str, MajorAIJudgment]
    quantitative_impacts: tuple[QuantitativeEconomicImpact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimensions", _freeze_mapping(self.dimensions))


@dataclass(frozen=True, slots=True)
class CounterThesis:
    competitive_advantage_erosion: str
    new_entrant_or_technology_substitution: str
    accounting_anomaly: str
    management_narrative_conflict: str
    customer_supplier_concentration: str
    regulatory_geopolitical_risk: str
    valuation_assumptions: str
    bull_thesis: str
    bear_thesis: str
    disconfirming_evidence: str
    thesis_break_conditions: str
    major_judgments: tuple[MajorAIJudgment, ...]

    def __post_init__(self) -> None:
        for name in (
            "competitive_advantage_erosion",
            "new_entrant_or_technology_substitution",
            "accounting_anomaly",
            "management_narrative_conflict",
            "customer_supplier_concentration",
            "regulatory_geopolitical_risk",
            "valuation_assumptions",
            "bull_thesis",
            "bear_thesis",
            "disconfirming_evidence",
            "thesis_break_conditions",
        ):
            _nonempty(getattr(self, name), f"counter_thesis.{name}")
        if not self.major_judgments:
            raise ContractViolation("counter-thesis requires evidence-bearing major judgments")


@dataclass(frozen=True, slots=True)
class AIResearch:
    method_version: str
    structural_change_dimensions: Mapping[str, tuple[MajorAIJudgment, ...]]
    ai_impact: AIImpactAssessment
    counter_thesis: CounterThesis

    def __post_init__(self) -> None:
        _nonempty(self.method_version, "AI research method_version")
        if not self.structural_change_dimensions:
            raise ContractViolation("structural-change research must not be empty")
        for dimension, judgments in self.structural_change_dimensions.items():
            _nonempty(dimension, "structural-change dimension")
            if not judgments:
                raise ContractViolation("each structural-change dimension requires a judgment")
        object.__setattr__(
            self,
            "structural_change_dimensions",
            MappingProxyType(
                {key: tuple(value) for key, value in self.structural_change_dimensions.items()}
            ),
        )

    @property
    def judgments(self) -> tuple[MajorAIJudgment, ...]:
        structural = tuple(
            judgment
            for judgments in self.structural_change_dimensions.values()
            for judgment in judgments
        )
        return structural + tuple(self.ai_impact.dimensions.values()) + self.counter_thesis.major_judgments


class StructuralDisruptionRootQuestion(str, Enum):
    """The six frozen Structural Disruption root questions (FZ-SD-001..006).

    A Traditional long-term candidate MUST cover all six.  These are stable
    coverage semantics, not versionable sub-dimensions: the exact question
    set is frozen, while per-question findings and evidence remain
    caller-owned and versionable.
    """

    CUSTOMER_JOB_VALUE_ENGINE = "CUSTOMER_JOB_VALUE_ENGINE"
    OUTSIDE_SUBSTITUTE = "OUTSIDE_SUBSTITUTE"
    MIGRATION_EVIDENCE_VELOCITY = "MIGRATION_EVIDENCE_VELOCITY"
    ECONOMIC_TRANSMISSION = "ECONOMIC_TRANSMISSION"
    INCUMBENT_ADAPTATION_COUNTERATTACK = "INCUMBENT_ADAPTATION_COUNTERATTACK"
    TIMING_FALSIFICATION_CONFIDENCE = "TIMING_FALSIFICATION_CONFIDENCE"


STRUCTURAL_DISRUPTION_ROOT_QUESTIONS = frozenset(StructuralDisruptionRootQuestion)


@dataclass(frozen=True, slots=True)
class StructuralDisruptionFinding:
    """One root question's structured, evidence-bearing finding.

    Carries evidence and counter-evidence (FZ-SD-001..006 / FZ-EXP-001) plus
    the question-specific structured rationale fields: economic transmission
    (Q4), incumbent adaptation/counterattack (Q5), and timing / falsification
    / confidence / major unknowns (Q6).  ``methodology_rule_refs`` preserves
    the derivation path for later methodology explanations (CUR-007).
    """

    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    conclusion: str
    economic_transmission: str | None = None
    incumbent_adaptation: str | None = None
    expected_horizon: str | None = None
    falsification_condition: str | None = None
    confidence: str | None = None
    major_unknowns: tuple[str, ...] = ()
    methodology_rule_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ContractViolation("structural-disruption finding requires evidence")
        for text in self.evidence:
            _nonempty(text, "structural-disruption evidence")
        for text in self.counter_evidence:
            _nonempty(text, "structural-disruption counter-evidence")
        for text in self.major_unknowns:
            _nonempty(text, "structural-disruption major_unknowns")
        for ref in self.methodology_rule_refs:
            _nonempty(ref, "structural-disruption methodology_rule_refs")
        _nonempty(self.conclusion, "structural-disruption conclusion")


@dataclass(frozen=True, slots=True)
class StructuralDisruptionAssessment:
    """Frozen coverage contract over the six root questions (CUR-001)."""

    method_version: str
    questions: Mapping[StructuralDisruptionRootQuestion, StructuralDisruptionFinding]

    def __post_init__(self) -> None:
        _nonempty(self.method_version, "structural-disruption method_version")
        object.__setattr__(
            self,
            "questions",
            MappingProxyType(
                {
                    StructuralDisruptionRootQuestion(question): finding
                    for question, finding in self.questions.items()
                }
            ),
        )
        _validate_structural_disruption_6q(self)


def _validate_structural_disruption_6q(assessment: StructuralDisruptionAssessment) -> None:
    """Fail closed unless the assessment covers all six frozen root questions."""
    questions = assessment.questions
    if set(questions) != STRUCTURAL_DISRUPTION_ROOT_QUESTIONS:
        missing = sorted(
            question.value for question in STRUCTURAL_DISRUPTION_ROOT_QUESTIONS - set(questions)
        )
        extra = sorted(
            question.value for question in set(questions) - STRUCTURAL_DISRUPTION_ROOT_QUESTIONS
        )
        raise ContractViolation(
            "structural disruption must cover exactly the six frozen root questions; "
            f"missing={missing!r} extra={extra!r}"
        )
    for question, finding in questions.items():
        if not isinstance(finding, StructuralDisruptionFinding):
            raise ContractViolation(
                f"structural-disruption question {question.value} requires a finding"
            )
    timing = questions[StructuralDisruptionRootQuestion.TIMING_FALSIFICATION_CONFIDENCE]
    if not (timing.expected_horizon and timing.falsification_condition and timing.confidence):
        raise ContractViolation(
            "TIMING_FALSIFICATION_CONFIDENCE requires expected_horizon, "
            "falsification_condition, and confidence"
        )
    if not timing.counter_evidence:
        raise ContractViolation(
            "TIMING_FALSIFICATION_CONFIDENCE requires counter-evidence (evidence against)"
        )
    transmission = questions[StructuralDisruptionRootQuestion.ECONOMIC_TRANSMISSION]
    if not transmission.economic_transmission:
        raise ContractViolation("ECONOMIC_TRANSMISSION requires an economic-transmission path")
    adaptation = questions[
        StructuralDisruptionRootQuestion.INCUMBENT_ADAPTATION_COUNTERATTACK
    ]
    if not adaptation.incumbent_adaptation:
        raise ContractViolation(
            "INCUMBENT_ADAPTATION_COUNTERATTACK requires an incumbent-adaptation analysis"
        )


def validate_structural_disruption_6q(assessment: StructuralDisruptionAssessment) -> None:
    """Public fail-closed validator for the six-question coverage contract."""
    if not isinstance(assessment, StructuralDisruptionAssessment):
        raise ContractViolation("assessment must be a StructuralDisruptionAssessment")
    _validate_structural_disruption_6q(assessment)


@dataclass(frozen=True, slots=True)
class DecisionContext:
    gate_scores: Mapping[Gate, float | None]
    company_quality_score: float | None
    valuation: ValuationResult
    data_confidence: Any


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """Versioned caller authority for opportunity state and base tier."""

    method_version: str
    tier_scale: tuple[str, ...]
    company_quality_calculator: Callable[[Mapping[str, MetricEvaluation]], float]
    opportunity_classifier: Callable[[DecisionContext], str]
    highest_tier_eligible: Callable[[DecisionContext], bool]
    base_tier_selector: Callable[[DecisionContext], str]

    def __post_init__(self) -> None:
        _nonempty(self.method_version, "decision policy method_version")
        if len(self.tier_scale) < 2 or len(set(self.tier_scale)) != len(self.tier_scale):
            raise ContractViolation("tier_scale requires at least two unique caller-owned tiers")
        for tier in self.tier_scale:
            _nonempty(tier, "tier label")
        if not all(
            callable(method)
            for method in (
                self.company_quality_calculator,
                self.opportunity_classifier,
                self.highest_tier_eligible,
                self.base_tier_selector,
            )
        ):
            raise ContractViolation("decision policy classifiers must be callable")


@dataclass(frozen=True, slots=True)
class AIInfluencePolicy:
    method_version: str
    known_confidence_levels: frozenset[str]
    high_confidence_levels: frozenset[str]
    sufficient_evidence: Callable[[AIResearch, tuple[MajorAIJudgment, ...]], bool]
    structural_gate: Callable[[AIResearch], GateStatus]
    reporting_period_applicable: Callable[
        [MajorAIJudgment, CanonicalData[Any]], bool
    ]

    def __post_init__(self) -> None:
        _nonempty(self.method_version, "AI influence method_version")
        if not self.known_confidence_levels:
            raise ContractViolation("known_confidence_levels must not be empty")
        if not self.high_confidence_levels <= self.known_confidence_levels:
            raise ContractViolation("high confidence levels must belong to the governed scale")
        if not all(
            callable(method)
            for method in (
                self.sufficient_evidence,
                self.structural_gate,
                self.reporting_period_applicable,
            )
        ):
            raise ContractViolation("AI policy evaluators must be callable")


@dataclass(frozen=True, slots=True)
class AIOverlay:
    action: AIAction = AIAction.NONE
    requested_tier: str | None = None
    supporting_judgment_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScanRequest:
    entity: str
    economic_profile: EconomicProfile
    evidence: Mapping[str, EvidenceInput]
    metric_recipe: MetricRecipe
    gate_policy: GatePolicy
    data_confidence_policy: DataConfidencePolicy
    valuation: ValuationInputs
    ai_research: AIResearch
    decision_policy: DecisionPolicy
    ai_influence_policy: AIInfluencePolicy
    structural_disruption: StructuralDisruptionAssessment
    ai_overlay: AIOverlay = AIOverlay()

    def __post_init__(self) -> None:
        _nonempty(self.entity, "entity")
        object.__setattr__(self, "evidence", _freeze_mapping(self.evidence))
        for key, item in self.evidence.items():
            if key != item.metric_id:
                raise ContractViolation("evidence mapping keys must equal metric_id")
        if not isinstance(self.structural_disruption, StructuralDisruptionAssessment):
            raise ContractViolation(
                "structural_disruption must be a StructuralDisruptionAssessment"
            )


@dataclass(frozen=True, slots=True)
class MetricEvaluation:
    metric_id: str
    gate: Gate
    original_weight: float
    effective_weight: float | None
    transformed_score: float | None
    weighted_contribution: float | None
    method_version: str
    evidence: CanonicalData[Any] | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class GateEvaluation:
    gate: Gate
    status: GateStatus
    score: float | None
    minimum_score: float | None
    hard_gate: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PeerRelativeResult:
    raw_target_value: float | None
    raw_peer_values: tuple[float, ...]
    percentile: float | None
    peer_count: int
    peer_definition: str
    method_version: str


@dataclass(frozen=True, slots=True)
class ValuationResult:
    peer_relative: PeerRelativeResult
    historical_range: MetricEvaluation
    price_implied_assumptions: MetricEvaluation
    bull_base_bear_bands: MetricEvaluation
    upside_downside_asymmetry: MetricEvaluation
    uncertainty: MetricEvaluation


@dataclass(frozen=True, slots=True)
class TraditionalScanResult:
    entity: str
    economic_profile: EconomicProfile
    metric_evaluations: Mapping[str, MetricEvaluation]
    gate_evaluations: Mapping[Gate, GateEvaluation]
    company_quality_score: float | None
    investment_opportunity_state: str
    valuation: ValuationResult
    data_confidence: Any
    unavailable_weight_fraction: float
    deterministic_core_eligible: bool
    deterministic_qualified: bool
    base_candidate_tier: str | None
    candidate_tier: str | None
    ai_action_applied: AIAction
    review_required: bool
    vetoed: bool
    recipe_method_version: str
    gate_policy_method_version: str
    data_confidence_method_version: str
    decision_method_version: str
    ai_method_version: str
    structural_disruption: StructuralDisruptionAssessment
    shared_facts: tuple[SharedFact, ...] = ()
    system_evidence_claims: tuple[SystemEvidenceClaim, ...] = ()


def _canonical_issue(
    evidence: EvidenceInput | None, entity: str
) -> str | None:
    if evidence is None:
        return "MISSING_INPUT"
    data = evidence.data
    if data.availability is not Availability.AVAILABLE:
        return f"{data.availability.value.upper()}:{data.reason}"
    if evidence.source_conflict:
        return f"SOURCE_CONFLICT:{evidence.conflict_reason}"
    if data.symbol is not None and data.symbol != entity:
        return f"ENTITY_MISMATCH:{data.symbol}"
    critical_provenance = {
        "data_as_of": data.data_as_of,
        "reporting_period": data.reporting_period,
        "unit": data.unit,
        "currency": data.currency,
    }
    missing = [name for name, value in critical_provenance.items() if value is None or value == ""]
    if missing:
        return f"INCOMPLETE_PROVENANCE:{','.join(missing)}"
    return None


def _resolve_path(payload: Any, path: tuple[str | int, ...]) -> Any:
    current = payload
    for part in path:
        try:
            current = current[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise ContractViolation(f"economic-impact value_path is not present: {path!r}") from exc
    return current


def _validate_ai_research(
    research: AIResearch,
    policy: AIInfluencePolicy,
    entity: str,
) -> tuple[str, ...]:
    issues: list[str] = []
    if set(research.ai_impact.dimensions) != AI_DIMENSIONS:
        issues.append("AI_DIMENSIONS_INCOMPLETE")

    ids: set[str] = set()
    for judgment in research.judgments:
        if judgment.judgment_id in ids:
            issues.append(f"DUPLICATE_JUDGMENT_ID:{judgment.judgment_id}")
        ids.add(judgment.judgment_id)
        if judgment.confidence_level not in policy.known_confidence_levels:
            issues.append(f"UNKNOWN_CONFIDENCE_LEVEL:{judgment.judgment_id}")
        if judgment.contradiction.present and not judgment.contradiction.resolved:
            issues.append(f"UNRESOLVED_CONTRADICTION:{judgment.judgment_id}")
        for data in judgment.evidence:
            try:
                reporting_period_applicable = policy.reporting_period_applicable(
                    judgment, data
                )
            except Exception as exc:
                raise ContractViolation(
                    "reporting-period applicability method failed for "
                    f"{judgment.judgment_id}: {exc}"
                ) from exc
            if not isinstance(reporting_period_applicable, bool):
                raise ContractViolation(
                    "reporting_period_applicable must return bool for "
                    f"{judgment.judgment_id}"
                )
            if data.availability is not Availability.AVAILABLE:
                issues.append(f"AI_EVIDENCE_NOT_AVAILABLE:{judgment.judgment_id}")
            if data.symbol != entity:
                issues.append(f"AI_EVIDENCE_ENTITY_MISMATCH:{judgment.judgment_id}")
            if data.data_as_of is None:
                issues.append(f"AI_EVIDENCE_SOURCE_DATE_MISSING:{judgment.judgment_id}")
            if reporting_period_applicable and not data.reporting_period:
                issues.append(f"AI_EVIDENCE_REPORTING_PERIOD_MISSING:{judgment.judgment_id}")

    impacts = research.ai_impact.quantitative_impacts
    if research.ai_impact.direction is AIImpactDirection.BENEFIT and not impacts:
        issues.append("AI_BENEFIT_WITHOUT_QUANTITATIVE_ECONOMIC_IMPACT")
    for impact in impacts:
        data = impact.evidence
        if data.availability is not Availability.AVAILABLE:
            issues.append(f"ECONOMIC_IMPACT_EVIDENCE_NOT_AVAILABLE:{impact.metric_name}")
            continue
        if data.symbol != entity or data.data_as_of is None or not data.reporting_period:
            issues.append(f"ECONOMIC_IMPACT_PROVENANCE_INCOMPLETE:{impact.metric_name}")
        if not data.unit or not data.currency:
            issues.append(f"ECONOMIC_IMPACT_UNIT_CURRENCY_MISSING:{impact.metric_name}")
        payload = data.payload
        if not isinstance(payload, Mapping):
            issues.append(f"ECONOMIC_IMPACT_BARE_SCALAR:{impact.metric_name}")
            continue
        try:
            bound_value = float(_resolve_path(payload, impact.value_path))
        except (ContractViolation, TypeError, ValueError):
            issues.append(f"ECONOMIC_IMPACT_VALUE_NOT_BOUND:{impact.metric_name}")
            continue
        if not math.isclose(bound_value, impact.value, rel_tol=1e-12, abs_tol=1e-12):
            issues.append(f"ECONOMIC_IMPACT_VALUE_MISMATCH:{impact.metric_name}")
    return tuple(dict.fromkeys(issues))


def _compute_peer_relative(
    request: ScanRequest,
    evaluations: Mapping[str, MetricEvaluation],
) -> PeerRelativeResult:
    peer = request.valuation.peer_relative
    target_evaluation = evaluations[peer.target_metric_id]
    peer_definition = (
        f"{request.economic_profile.value}+{peer.narrow_provider_industry}"
        if peer.narrow_provider_industry
        else request.economic_profile.value
    )
    if target_evaluation.evidence is None or target_evaluation.transformed_score is None:
        return PeerRelativeResult(None, (), None, 0, peer_definition, peer.method_version)

    target_raw = float(peer.value_reader(target_evaluation.evidence.require_available()))
    raw_peers: list[float] = []
    for item in peer.peer_evidence:
        if _canonical_issue(item, item.data.symbol or request.entity) is not None:
            continue
        value = float(peer.value_reader(item.data.require_available()))
        if math.isfinite(value):
            raw_peers.append(value)
    percentile = None
    if len(raw_peers) >= MIN_PEER_COUNT:
        percentile = _unit_interval(
            peer.percentile_method(target_raw, tuple(raw_peers)),
            "peer percentile",
        )
    return PeerRelativeResult(
        raw_target_value=target_raw,
        raw_peer_values=tuple(raw_peers),
        percentile=percentile,
        peer_count=len(raw_peers),
        peer_definition=peer_definition,
        method_version=peer.method_version,
    )


def _payload_repr(payload: Any) -> Any:
    """A deterministic, JSON-stable representation of an observed payload."""
    if isinstance(payload, Mapping):
        return {str(key): _payload_repr(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_payload_repr(value) for value in payload]
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, (int, str)) or payload is None:
        return payload
    if isinstance(payload, float):
        return payload if math.isfinite(payload) else repr(payload)
    return repr(payload)


def _observation_key(data: CanonicalData[Any]) -> str:
    """Stable identity of one underlying observation / causal chain.

    Two metric analyses that read the same canonical observation (same issuer
    symbol, source, as-of, reporting period, and observed payload) resolve to
    the same key, so correlated evidence is established once and only
    referenced thereafter (FZ-DATA-004 / CUR-002).
    """
    return json.dumps(
        {
            "symbol": data.symbol,
            "source": data.source,
            "provider": data.provider,
            "operation": data.operation,
            "data_as_of": None if data.data_as_of is None else data.data_as_of.isoformat(),
            "reporting_period": data.reporting_period,
            "unit": data.unit,
            "currency": data.currency,
            "payload": _payload_repr(data.payload),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _fact_identity(entity: str, data: CanonicalData[Any]) -> str:
    """Deterministic identity for one methodology-neutral canonical fact.

    The identity is a pure function of the company entity and the underlying
    observation identity (NOT the reading metric), so two metrics that read
    the same canonical observation always resolve to the same fact reference.
    This is the de-duplication anchor (FZ-DATA-004 / CUR-002).
    """
    digest = hashlib.sha256(_observation_key(data).encode("utf-8")).hexdigest()[:32]
    return f"fact:{entity}:{digest}"


def _fact_source_ref(data: CanonicalData[Any]) -> str:
    provenance = {
        "symbol": data.symbol,
        "source": data.source,
        "provider": data.provider,
        "operation": data.operation,
        "reporting_period": data.reporting_period,
        "unit": data.unit,
        "currency": data.currency,
    }
    return json.dumps(provenance, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _build_shared_facts(
    entity: str, evidence_inputs: Mapping[str, EvidenceInput]
) -> tuple[SharedFact, ...]:
    """Build methodology-neutral facts from the canonical evidence actually
    consumed by the compiler, de-duplicated by underlying-observation identity
    BEFORE any scoring (FZ-DATA-004 / CUR-002).

    The fact text carries the actual observed value/content and the source
    reference carries provenance; two metrics reading the same observation
    resolve to one fact identity and are never counted twice.
    """
    from tradingagents.scanners.unified import SharedFact

    facts: dict[str, SharedFact] = {}
    for metric_id in sorted(evidence_inputs):
        item = evidence_inputs[metric_id]
        data = item.data
        if data.availability is not Availability.AVAILABLE:
            continue
        fact_id = _fact_identity(entity, data)
        if fact_id in facts:
            continue
        data_as_of = None if data.data_as_of is None else data.data_as_of.isoformat()
        facts[fact_id] = SharedFact(
            fact_id=fact_id,
            fact_type="canonical_observation",
            fact=(
                f"canonical observation for {data.symbol or entity} from "
                f"{data.source or data.provider}, period "
                f"{data.reporting_period or 'unknown'}: "
                f"{_payload_repr(data.payload)} ({data.unit or 'unit not supplied'})"
            ),
            source_refs=(_fact_source_ref(data),),
            data_as_of=data_as_of,
            provenance=_fact_source_ref(data),
        )
    return tuple(facts[fact_id] for fact_id in sorted(facts))


def _fact_id_by_metric(
    entity: str, evidence_inputs: Mapping[str, EvidenceInput]
) -> dict[str, str]:
    """Map each available metric to its de-duplicated underlying fact identity."""
    result: dict[str, str] = {}
    for metric_id, item in evidence_inputs.items():
        data = item.data
        if data.availability is not Availability.AVAILABLE:
            continue
        result[metric_id] = _fact_identity(entity, data)
    return result


def _build_structural_disruption_claim(
    entity: str, assessment: StructuralDisruptionAssessment
) -> SystemEvidenceClaim:
    """A Traditional-scoped claim carrying the Structural Disruption 6Q
    rationale (evidence, counter-evidence, falsification, timing, confidence)
    and its methodology rule references (CUR-001/007 / FZ-SD)."""
    from tradingagents.scanners.unified import SelectionSystem, SystemEvidenceClaim

    parts: list[str] = [f"Structural Disruption 6Q ({assessment.method_version})"]
    refs: set[str] = set()
    for question in StructuralDisruptionRootQuestion:
        finding = assessment.questions[question]
        parts.append(f"{question.value}: {finding.conclusion}")
        if finding.evidence:
            parts.append(f"  evidence={'; '.join(finding.evidence)}")
        if finding.counter_evidence:
            parts.append(f"  counter_evidence={'; '.join(finding.counter_evidence)}")
        if finding.economic_transmission:
            parts.append(f"  economic_transmission={finding.economic_transmission}")
        if finding.incumbent_adaptation:
            parts.append(f"  incumbent_adaptation={finding.incumbent_adaptation}")
        if finding.expected_horizon:
            parts.append(f"  expected_horizon={finding.expected_horizon}")
        if finding.falsification_condition:
            parts.append(f"  falsification_condition={finding.falsification_condition}")
        if finding.confidence:
            parts.append(f"  confidence={finding.confidence}")
        if finding.major_unknowns:
            parts.append(f"  major_unknowns={'; '.join(finding.major_unknowns)}")
        refs.update(finding.methodology_rule_refs)
    return SystemEvidenceClaim(
        claim_id=f"claim:traditional:{entity}:structural_disruption_6q",
        system_scope=SelectionSystem.TRADITIONAL,
        claim_type="structural_disruption_6q",
        fact_refs=(),
        claim="\n".join(parts),
        confidence="high",
        methodology_rule_refs=tuple(sorted(refs)),
        data_as_of=None,
        provenance="traditional_e04_compiler",
    )


def _build_system_evidence_claims(
    entity: str,
    evaluations: Mapping[str, MetricEvaluation],
    gate_evaluations: Mapping[Gate, GateEvaluation],
    fact_id_by_metric: Mapping[str, str],
    structural_disruption: StructuralDisruptionAssessment,
) -> tuple[SystemEvidenceClaim, ...]:
    """Build Traditional-scoped evidence claims, one per gate conclusion, plus
    one structural-disruption rationale claim (FZ-DATA-003/004).

    Each gate claim references the de-duplicated shared facts its gate was
    computed from (by underlying-observation identity), so a correlated
    evidence source is never counted as an independent fact more than once.
    """
    from tradingagents.scanners.unified import SelectionSystem, SystemEvidenceClaim

    confidence_by_status = {
        GateStatus.PASS: "high",
        GateStatus.REVIEW_REQUIRED: "medium",
        GateStatus.FAIL: "low",
    }
    claims: list[SystemEvidenceClaim] = []
    for gate in Gate:
        evaluation = gate_evaluations[gate]
        metric_ids = sorted(
            metric_id for metric_id, item in evaluations.items() if item.gate is gate
        )
        fact_refs = tuple(
            sorted(
                {
                    fact_id_by_metric[metric_id]
                    for metric_id in metric_ids
                    if metric_id in fact_id_by_metric
                }
            )
        )
        method_refs = tuple(
            sorted({evaluations[metric_id].method_version for metric_id in metric_ids})
        )
        claim = f"{gate.value} {evaluation.status.value}"
        if evaluation.score is not None:
            claim += f" score={evaluation.score:.4f}"
        if evaluation.reasons:
            claim += f" reasons={','.join(evaluation.reasons)}"
        claims.append(
            SystemEvidenceClaim(
                claim_id=f"claim:traditional:{entity}:{gate.value}",
                system_scope=SelectionSystem.TRADITIONAL,
                claim_type="gate_conclusion",
                fact_refs=fact_refs,
                claim=claim,
                confidence=confidence_by_status[evaluation.status],
                methodology_rule_refs=method_refs,
                data_as_of=None,
                provenance="traditional_e04_compiler",
            )
        )
    claims.append(_build_structural_disruption_claim(entity, structural_disruption))
    return tuple(claims)


def compile_traditional_scan(request: ScanRequest) -> TraditionalScanResult:
    """Compile canonical evidence under caller-owned methods and E04 invariants."""
    # Fail closed on any six-question coverage gap before any scoring work
    # (FZ-SD / CUR-001). The request-level assessment is already validated at
    # construction; this is the deterministic compiler-side re-assertion.
    validate_structural_disruption_6q(request.structural_disruption)
    rules = tuple(
        rule for rule in request.metric_recipe.rules if rule.applies_to(request.economic_profile)
    )
    covered_gates = {rule.gate for rule in rules}
    if covered_gates != set(DETERMINISTIC_GATES):
        raise ContractViolation("the selected economic-profile recipe must cover every G1..G5 gate")
    covered_g2_responsibilities = frozenset(
        responsibility
        for rule in rules
        if rule.gate is Gate.G2
        for responsibility in rule.g2_responsibilities
    )
    if covered_g2_responsibilities != REQUIRED_G2_RESPONSIBILITIES:
        raise ContractViolation(
            "applicable G2 rules must cover Business Quality / Capital Efficiency "
            "and Fundamental Trajectory"
        )

    rule_by_id = {rule.metric_id: rule for rule in rules}
    valuation_ids = set(request.valuation.metric_ids)
    if not valuation_ids <= set(rule_by_id):
        raise ContractViolation("all valuation dimensions must bind to applicable recipe rules")
    if any(rule_by_id[metric_id].gate is not Gate.G3 for metric_id in valuation_ids):
        raise ContractViolation("all valuation dimensions must bind to G3 rules")

    # CUR-002 / FZ-DATA-004: establish canonical methodology-neutral facts from
    # the raw canonical evidence BEFORE any scoring, de-duplicated by
    # underlying-observation identity so correlated evidence can never be
    # counted as independent inputs to a score/gate/decision.
    shared_facts = _build_shared_facts(request.entity, request.evidence)
    fact_id_by_metric = _fact_id_by_metric(request.entity, request.evidence)

    total_weight = sum(rule.weight for rule in rules)
    pending: list[tuple[MetricRule, EvidenceInput | None, str | None, float | None]] = []
    missing_weight = 0.0
    critical_issues: list[str] = []
    for rule in rules:
        evidence = request.evidence.get(rule.metric_id)
        issue = _canonical_issue(evidence, request.entity)
        score = None
        if issue is None and evidence is not None:
            try:
                score = _unit_interval(
                    rule.scorer(evidence.data.require_available()),
                    f"score for {rule.metric_id}",
                )
            except ContractViolation:
                raise
            except Exception as exc:
                raise ContractViolation(f"scorer failed for {rule.metric_id}: {exc}") from exc
        else:
            missing_weight += rule.weight
            if rule.critical:
                critical_issues.append(f"{rule.metric_id}:{issue}")
        pending.append((rule, evidence, issue, score))

    # A SharedFact may legitimately support several methodology claims, but
    # two score-bearing metrics in one gate may not count the same underlying
    # observation twice. Detect that collision before effective weights or
    # weighted contributions are assigned, and fail the entire affected gate
    # closed to REVIEW_REQUIRED rather than inventing a weight-sharing rule.
    scored_fact_metrics: dict[tuple[Gate, str], list[str]] = {}
    for rule, _evidence, _issue, score in pending:
        fact_id = fact_id_by_metric.get(rule.metric_id)
        if score is not None and fact_id is not None:
            scored_fact_metrics.setdefault((rule.gate, fact_id), []).append(
                rule.metric_id
            )
    duplicate_fact_reasons: dict[Gate, tuple[str, ...]] = {}
    for (gate, fact_id), metric_ids in scored_fact_metrics.items():
        if len(metric_ids) >= 2:
            reason = (
                f"DUPLICATE_SCORE_BEARING_FACT:{fact_id}:"
                f"{','.join(sorted(metric_ids))}"
            )
            duplicate_fact_reasons[gate] = (
                *duplicate_fact_reasons.get(gate, ()),
                reason,
            )
    duplicate_fact_gates = frozenset(duplicate_fact_reasons)

    unavailable_fraction = missing_weight / total_weight
    coverage_failed = unavailable_fraction > MAX_UNAVAILABLE_DETERMINISTIC_WEIGHT
    renormalization_blocked = bool(missing_weight) and not (
        request.metric_recipe.allow_missing_renormalization
    )
    deterministic_core_eligible = not coverage_failed and not renormalization_blocked
    available_weight = total_weight - missing_weight
    try:
        full_data_confidence = request.data_confidence_policy.assess(0.0, ())
        data_confidence = request.data_confidence_policy.assess(
            unavailable_fraction, tuple(critical_issues)
        )
        data_confidence_actionable = bool(
            request.data_confidence_policy.is_actionable(data_confidence)
        )
        data_confidence_reduced = not missing_weight or bool(
            request.data_confidence_policy.is_reduced(
                full_data_confidence, data_confidence
            )
        )
    except Exception as exc:
        raise ContractViolation(f"data-confidence method failed: {exc}") from exc

    evaluations: dict[str, MetricEvaluation] = {}
    for rule, evidence, issue, score in pending:
        effective_weight = None
        contribution = None
        if (
            score is not None
            and deterministic_core_eligible
            and available_weight > 0
            and rule.gate not in duplicate_fact_gates
        ):
            effective_weight = rule.weight / available_weight
            contribution = effective_weight * score
        evaluations[rule.metric_id] = MetricEvaluation(
            metric_id=rule.metric_id,
            gate=rule.gate,
            original_weight=rule.weight,
            effective_weight=effective_weight,
            transformed_score=score,
            weighted_contribution=contribution,
            method_version=rule.method_version,
            evidence=evidence.data if evidence is not None else None,
            unavailable_reason=issue,
        )

    gate_evaluations: dict[Gate, GateEvaluation] = {}
    g0_reasons: list[str] = []
    if coverage_failed:
        g0_reasons.append("INSUFFICIENT_SCORE_COVERAGE")
    if renormalization_blocked:
        g0_reasons.append("RENORMALIZATION_NOT_AUTHORIZED")
    if not data_confidence_reduced:
        g0_reasons.append("DATA_CONFIDENCE_NOT_REDUCED")
    g0_status = GateStatus.FAIL if g0_reasons else GateStatus.PASS
    review_reasons = list(critical_issues)
    if not data_confidence_actionable:
        review_reasons.append("DATA_CONFIDENCE_NOT_ACTIONABLE")
    if review_reasons and g0_status is GateStatus.PASS:
        g0_status = GateStatus.REVIEW_REQUIRED
        g0_reasons.extend(review_reasons)
    gate_evaluations[Gate.G0] = GateEvaluation(
        Gate.G0, g0_status, data_confidence, None, True, tuple(g0_reasons)
    )

    for gate in DETERMINISTIC_GATES:
        gate_items = [item for item in evaluations.values() if item.gate is gate]
        available = [item for item in gate_items if item.transformed_score is not None]
        gate_weight = sum(item.original_weight for item in available)
        score = None
        if gate in duplicate_fact_gates:
            status = GateStatus.REVIEW_REQUIRED
            reasons = duplicate_fact_reasons[gate]
        elif deterministic_core_eligible and gate_weight > 0:
            score = _unit_interval(
                request.metric_recipe.score_aggregator(
                    tuple(
                        (item.original_weight, item.transformed_score)
                        for item in available
                    )
                ),
                f"aggregate score for {gate.value}",
            )
            minimum = request.gate_policy.minimum_scores[gate]
            status = GateStatus.PASS if score >= minimum else GateStatus.FAIL
            reasons = () if status is GateStatus.PASS else ("GOVERNED_THRESHOLD_NOT_MET",)
        else:
            status = GateStatus.FAIL
            reasons = ("GOVERNED_THRESHOLD_NOT_MET",)
        minimum = request.gate_policy.minimum_scores[gate]
        gate_evaluations[gate] = GateEvaluation(
            gate, status, score, minimum, gate in request.gate_policy.hard_gates, reasons
        )

    peer_result = _compute_peer_relative(request, evaluations)
    valuation = ValuationResult(
        peer_relative=peer_result,
        historical_range=evaluations[request.valuation.historical_range_metric_id],
        price_implied_assumptions=evaluations[
            request.valuation.price_implied_assumptions_metric_id
        ],
        bull_base_bear_bands=evaluations[request.valuation.bull_base_bear_bands_metric_id],
        upside_downside_asymmetry=evaluations[
            request.valuation.upside_downside_asymmetry_metric_id
        ],
        uncertainty=evaluations[request.valuation.uncertainty_metric_id],
    )
    quality_inputs = MappingProxyType(
        {
            metric_id: item
            for metric_id, item in evaluations.items()
            if item.gate in {Gate.G1, Gate.G2}
            and item.gate not in duplicate_fact_gates
            and item.transformed_score is not None
        }
    )
    company_quality = None
    if quality_inputs:
        company_quality = _unit_interval(
            request.decision_policy.company_quality_calculator(quality_inputs),
            "company quality score",
        )
    context = DecisionContext(
        gate_scores=MappingProxyType(
            {gate: gate_evaluations[gate].score for gate in DETERMINISTIC_GATES}
        ),
        company_quality_score=company_quality,
        valuation=valuation,
        data_confidence=data_confidence,
    )
    opportunity_state = _nonempty(
        request.decision_policy.opportunity_classifier(context),
        "investment opportunity state",
    )

    ai_issues = _validate_ai_research(
        request.ai_research, request.ai_influence_policy, request.entity
    )
    try:
        governed_g6 = request.ai_influence_policy.structural_gate(request.ai_research)
    except Exception as exc:
        raise ContractViolation(f"structural gate method failed: {exc}") from exc
    if not isinstance(governed_g6, GateStatus):
        raise ContractViolation("structural_gate must return GateStatus")
    g6_status = GateStatus.REVIEW_REQUIRED if ai_issues else governed_g6
    gate_evaluations[Gate.G6] = GateEvaluation(
        Gate.G6,
        g6_status,
        None,
        None,
        Gate.G6 in request.gate_policy.hard_gates,
        ai_issues,
    )

    deterministic_hard_gates = request.gate_policy.hard_gates - {Gate.G6}
    deterministic_hard_fail = any(
        gate_evaluations[gate].status is GateStatus.FAIL
        for gate in deterministic_hard_gates
    )
    deterministic_hard_review = any(
        gate_evaluations[gate].status is GateStatus.REVIEW_REQUIRED
        for gate in deterministic_hard_gates
    )
    deterministic_qualified = (
        deterministic_core_eligible
        and not deterministic_hard_fail
        and not deterministic_hard_review
        and not duplicate_fact_gates
    )
    hard_fail = deterministic_hard_fail or (
        Gate.G6 in request.gate_policy.hard_gates and g6_status is GateStatus.FAIL
    )
    hard_review = deterministic_hard_review or (
        Gate.G6 in request.gate_policy.hard_gates
        and g6_status is GateStatus.REVIEW_REQUIRED
    )

    base_tier = None
    candidate_tier = None
    applied_action = AIAction.NONE
    vetoed = False
    review_required = (
        hard_review
        or g6_status is GateStatus.REVIEW_REQUIRED
        or bool(duplicate_fact_gates)
    )
    if deterministic_qualified and g6_status is GateStatus.PASS:
        base_tier = _nonempty(request.decision_policy.base_tier_selector(context), "base tier")
        if base_tier not in request.decision_policy.tier_scale:
            raise ContractViolation("base_tier_selector returned a tier outside tier_scale")
        highest_tier_allowed = bool(
            request.decision_policy.highest_tier_eligible(context)
        )
        if (
            base_tier == request.decision_policy.tier_scale[-1]
            and not highest_tier_allowed
        ):
            review_required = True
        else:
            candidate_tier = base_tier

        overlay = request.ai_overlay
        if overlay.action is AIAction.NONE:
            if overlay.requested_tier is not None or overlay.supporting_judgment_ids:
                raise ContractViolation("NONE AI action cannot carry a tier or supporting judgments")
        else:
            judgment_by_id = {
                judgment.judgment_id: judgment for judgment in request.ai_research.judgments
            }
            support = tuple(
                judgment_by_id[judgment_id]
                for judgment_id in overlay.supporting_judgment_ids
                if judgment_id in judgment_by_id
            )
            support_ids_valid = len(support) == len(overlay.supporting_judgment_ids) and bool(
                support
            )
            confidence_valid = support_ids_valid and all(
                judgment.confidence_level
                in request.ai_influence_policy.high_confidence_levels
                for judgment in support
            )
            evidence_valid = False
            if confidence_valid:
                evidence_valid = bool(
                    request.ai_influence_policy.sufficient_evidence(
                        request.ai_research, support
                    )
                )
            governed_support = confidence_valid and evidence_valid

            if overlay.action is AIAction.MOVE_TIER:
                tier_valid = overlay.requested_tier in request.decision_policy.tier_scale
                adjacent = tier_valid and abs(
                    request.decision_policy.tier_scale.index(base_tier)
                    - request.decision_policy.tier_scale.index(overlay.requested_tier)
                ) == 1
                highest_tier_blocked = (
                    overlay.requested_tier == request.decision_policy.tier_scale[-1]
                    and not highest_tier_allowed
                )
                if governed_support and adjacent and not highest_tier_blocked:
                    candidate_tier = overlay.requested_tier
                    applied_action = AIAction.MOVE_TIER
                else:
                    candidate_tier = None
                    review_required = True
            elif overlay.action is AIAction.REVIEW_REQUIRED:
                candidate_tier = None
                review_required = True
                if governed_support:
                    applied_action = AIAction.REVIEW_REQUIRED
            elif overlay.action is AIAction.VETO:
                candidate_tier = None
                if governed_support:
                    vetoed = True
                    applied_action = AIAction.VETO
                else:
                    review_required = True
            else:
                raise ContractViolation("unsupported AI action")

    if candidate_tier is not None:
        g7_status = GateStatus.PASS
        g7_reasons: tuple[str, ...] = ()
    elif hard_fail or vetoed:
        g7_status = GateStatus.FAIL
        g7_reasons = ("EARLIER_HARD_GATE_FAILURE_OR_EVIDENCE_BACKED_VETO",)
    else:
        g7_status = GateStatus.REVIEW_REQUIRED
        g7_reasons = ("CANDIDATE_TIER_WITHHELD",)
        review_required = True
    gate_evaluations[Gate.G7] = GateEvaluation(
        Gate.G7, g7_status, None, None, False, g7_reasons
    )

    system_evidence_claims = _build_system_evidence_claims(
        request.entity, evaluations, gate_evaluations, fact_id_by_metric, request.structural_disruption
    )

    return TraditionalScanResult(
        entity=request.entity,
        economic_profile=request.economic_profile,
        metric_evaluations=MappingProxyType(evaluations),
        gate_evaluations=MappingProxyType(gate_evaluations),
        company_quality_score=company_quality,
        investment_opportunity_state=opportunity_state,
        valuation=valuation,
        data_confidence=data_confidence,
        unavailable_weight_fraction=unavailable_fraction,
        deterministic_core_eligible=deterministic_core_eligible,
        deterministic_qualified=deterministic_qualified,
        base_candidate_tier=base_tier,
        candidate_tier=candidate_tier,
        ai_action_applied=applied_action,
        review_required=review_required,
        vetoed=vetoed,
        recipe_method_version=request.metric_recipe.method_version,
        gate_policy_method_version=request.gate_policy.method_version,
        data_confidence_method_version=request.data_confidence_policy.method_version,
        decision_method_version=request.decision_policy.method_version,
        ai_method_version=request.ai_influence_policy.method_version,
        structural_disruption=request.structural_disruption,
        shared_facts=shared_facts,
        system_evidence_claims=system_evidence_claims,
    )
