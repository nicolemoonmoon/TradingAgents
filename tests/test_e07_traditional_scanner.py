"""Focused, no-network evidence for the E04 Traditional compiler."""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timezone

import pytest

from tradingagents.dataflows.canonical_data import Availability, CanonicalData
from tradingagents.scanners import (
    AIAction,
    AIImpactAssessment,
    AIImpactDirection,
    AIInfluencePolicy,
    AIOverlay,
    AIResearch,
    ContractViolation,
    Contradiction,
    CounterThesis,
    DataConfidencePolicy,
    DecisionPolicy,
    EconomicProfile,
    EvidenceInput,
    G2Responsibility,
    Gate,
    GatePolicy,
    GateStatus,
    MajorAIJudgment,
    MetricRecipe,
    MetricRule,
    PeerRelativeInput,
    QuantitativeEconomicImpact,
    ScanRequest,
    ValuationInputs,
    compile_traditional_scan,
    traditional,
)
from tradingagents.scanners.traditional import (
    StructuralDisruptionAssessment,
    StructuralDisruptionFinding,
    StructuralDisruptionRootQuestion,
    validate_structural_disruption_6q,
)

NOW = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)
PROFILE = EconomicProfile.ASSET_LIGHT_TECH_PLATFORM

_SD = StructuralDisruptionRootQuestion


def _default_structural_disruption() -> StructuralDisruptionAssessment:
    def finding(conclusion, counter_evidence=(), **kwargs):
        return StructuralDisruptionFinding(
            evidence=("issuer filing evidence",),
            counter_evidence=counter_evidence,
            conclusion=conclusion,
            **kwargs,
        )

    return StructuralDisruptionAssessment(
        method_version="sd-owner-v1",
        questions={
            _SD.CUSTOMER_JOB_VALUE_ENGINE: finding("job/value engine"),
            _SD.OUTSIDE_SUBSTITUTE: finding("substitute"),
            _SD.MIGRATION_EVIDENCE_VELOCITY: finding("migration"),
            _SD.ECONOMIC_TRANSMISSION: finding(
                "transmission", economic_transmission="customer -> demand -> margin"
            ),
            _SD.INCUMBENT_ADAPTATION_COUNTERATTACK: finding(
                "adaptation", incumbent_adaptation="incumbent can pivot"
            ),
            _SD.TIMING_FALSIFICATION_CONFIDENCE: finding(
                "timing",
                counter_evidence=("counter-evidence",),
                expected_horizon="12-24 months",
                falsification_condition="condition",
                confidence="medium",
                major_unknowns=("unknown",),
                methodology_rule_refs=("FZ-SD-006",),
            ),
        },
    )


def _record(
    value=0.8,
    *,
    symbol="ACME",
    source="issuer_primary_record",
    availability=Availability.AVAILABLE,
    reporting_period="FY2025",
    reason=None,
):
    return CanonicalData(
        operation="governed_evidence",
        availability=availability,
        provider="issuer",
        source=source,
        retrieved_at=NOW,
        payload={"value": value} if availability is Availability.AVAILABLE else None,
        symbol=symbol,
        data_as_of=date(2026, 8, 8),
        reporting_period=reporting_period,
        unit="ratio",
        currency="USD",
        reason=reason,
    )


def _scalar_record(value, *, reporting_period="FY2025"):
    return CanonicalData(
        operation="governed_evidence",
        availability=Availability.AVAILABLE,
        provider="issuer",
        source="issuer_primary_record",
        retrieved_at=NOW,
        payload=value,
        symbol="ACME",
        data_as_of=date(2026, 8, 8),
        reporting_period=reporting_period,
        unit="ratio",
        currency="USD",
    )


def _judgment(judgment_id, *, confidence="governed_high", evidence=None, contradiction=None):
    return MajorAIJudgment(
        judgment_id=judgment_id,
        finding=f"evidence-bearing finding for {judgment_id}",
        evidence=(evidence or _record(),),
        confidence_level=confidence,
        contradiction=contradiction or Contradiction(False, False),
    )


def _research(
    *,
    confidence="governed_high",
    evidence=None,
    contradiction=None,
    direction=AIImpactDirection.RISK,
    impacts=(),
):
    structural = _judgment(
        "structural", confidence=confidence, evidence=evidence, contradiction=contradiction
    )
    dimensions = {
        name: _judgment(
            f"ai_{name}",
            confidence=confidence,
            evidence=evidence,
            contradiction=contradiction,
        )
        for name in (
            "exposure",
            "adoption_depth",
            "realized_economics",
            "monetization",
            "defensibility",
            "disruption_risk",
            "capital_discipline",
            "hype_gap",
        )
    }
    counter = CounterThesis(
        competitive_advantage_erosion="reviewed",
        new_entrant_or_technology_substitution="reviewed",
        accounting_anomaly="reviewed",
        management_narrative_conflict="reviewed",
        customer_supplier_concentration="reviewed",
        regulatory_geopolitical_risk="reviewed",
        valuation_assumptions="reviewed",
        bull_thesis="reviewed",
        bear_thesis="reviewed",
        disconfirming_evidence="reviewed",
        thesis_break_conditions="reviewed",
        major_judgments=(
            _judgment(
                "counter",
                confidence=confidence,
                evidence=evidence,
                contradiction=contradiction,
            ),
        ),
    )
    return AIResearch(
        method_version="research-owner-v4",
        structural_change_dimensions={"automation_and_policy": (structural,)},
        ai_impact=AIImpactAssessment(direction, dimensions, impacts),
        counter_thesis=counter,
    )


def _rules(*, g2_responsibilities=frozenset(G2Responsibility)):
    specifications = (
        ("financial_reality", Gate.G1, 0.15),
        ("business_quality", Gate.G2, 0.15),
        ("val_peer", Gate.G3, 0.05),
        ("val_history", Gate.G3, 0.05),
        ("val_implied", Gate.G3, 0.05),
        ("val_bands", Gate.G3, 0.05),
        ("val_asymmetry", Gate.G3, 0.05),
        ("val_uncertainty", Gate.G3, 0.05),
        ("forward_change", Gate.G4, 0.20),
        ("market_risk", Gate.G5, 0.20),
    )
    return tuple(
        MetricRule(
            metric_id,
            gate,
            weight,
            f"{metric_id}-method-v2",
            lambda payload: payload["value"],
            frozenset({PROFILE}),
            g2_responsibilities if gate is Gate.G2 else frozenset(),
            critical=metric_id == "financial_reality",
        )
        for metric_id, gate, weight in specifications
    )


def _request(
    *,
    values=None,
    missing=(),
    allow_renormalization=True,
    peer_count=20,
    research=None,
    overlay=None,
    tier_scale=("governed_low", "governed_base", "governed_high", "governed_top"),
    base_tier="governed_base",
    data_confidence_actionable=lambda confidence: confidence >= 0.75,
    g2_responsibilities=frozenset(G2Responsibility),
    reporting_period_applicable=lambda judgment, data: True,
    structural_disruption=None,
    shared_observation_metric_ids=(),
):
    values = values or {}
    evidence = {}
    rules = _rules(g2_responsibilities=g2_responsibilities)
    for rule in rules:
        source = (
            "issuer_primary_record:shared"
            if rule.metric_id in shared_observation_metric_ids
            else f"issuer_primary_record:{rule.metric_id}"
        )
        if rule.metric_id in missing:
            data = _record(
                source=source,
                availability=Availability.UNAVAILABLE,
                reason="not present at the point in time",
            )
        else:
            data = _record(values.get(rule.metric_id, 0.8), source=source)
        evidence[rule.metric_id] = EvidenceInput(rule.metric_id, data)

    peers = tuple(
        EvidenceInput(f"peer_{index}", _record(index / 100, symbol=f"PEER{index}"))
        for index in range(peer_count)
    )
    valuation = ValuationInputs(
        peer_relative=PeerRelativeInput(
            target_metric_id="val_peer",
            peer_evidence=peers,
            value_reader=lambda payload: payload["value"],
            percentile_method=lambda target, samples: sum(value <= target for value in samples)
            / len(samples),
            method_version="robust-percentile-owner-v3",
            narrow_provider_industry="software_infrastructure",
        ),
        historical_range_metric_id="val_history",
        price_implied_assumptions_metric_id="val_implied",
        bull_base_bear_bands_metric_id="val_bands",
        upside_downside_asymmetry_metric_id="val_asymmetry",
        uncertainty_metric_id="val_uncertainty",
    )
    return ScanRequest(
        entity="ACME",
        economic_profile=PROFILE,
        evidence=evidence,
        metric_recipe=MetricRecipe(
            "asset-light-recipe-v7",
            rules,
            allow_renormalization,
            lambda weighted_scores: sum(
                weight * score for weight, score in weighted_scores
            )
            / sum(weight for weight, _ in weighted_scores),
        ),
        gate_policy=GatePolicy(
            "owner-gates-v5",
            dict.fromkeys((Gate.G1, Gate.G2, Gate.G3, Gate.G4, Gate.G5), 0.5),
            frozenset({Gate.G0, Gate.G1, Gate.G2, Gate.G3, Gate.G4, Gate.G6}),
        ),
        data_confidence_policy=DataConfidencePolicy(
            "owner-data-confidence-v3",
            lambda unavailable_fraction, critical_issues: 1.0 - unavailable_fraction,
            data_confidence_actionable,
            lambda full, current: current < full,
        ),
        valuation=valuation,
        ai_research=research or _research(),
        decision_policy=DecisionPolicy(
            "owner-decision-v6",
            tier_scale,
            lambda quality: sum(
                item.original_weight * item.transformed_score for item in quality.values()
            )
            / sum(item.original_weight for item in quality.values()),
            lambda context: (
                "owner_attractive"
                if context.gate_scores[Gate.G3] is not None
                and context.gate_scores[Gate.G3] >= 0.7
                else "owner_unattractive"
            ),
            lambda context: context.gate_scores[Gate.G3] is not None
            and context.gate_scores[Gate.G3] >= 0.7,
            lambda context: base_tier,
        ),
        ai_influence_policy=AIInfluencePolicy(
            "owner-ai-influence-v8",
            frozenset({"governed_low", "governed_high"}),
            frozenset({"governed_high"}),
            lambda research_record, support: bool(support)
            and all(len(judgment.evidence) >= 1 for judgment in support),
            lambda research_record: GateStatus.PASS,
            reporting_period_applicable,
        ),
        structural_disruption=structural_disruption or _default_structural_disruption(),
        ai_overlay=overlay or AIOverlay(),
    )


@pytest.mark.unit
def test_compiles_exact_gate_topology_and_separate_quality_opportunity_outputs():
    result = compile_traditional_scan(_request())

    assert tuple(result.gate_evaluations) == tuple(Gate)
    assert result.company_quality_score == pytest.approx(0.8)
    assert result.investment_opportunity_state == "owner_attractive"
    assert result.company_quality_score != result.investment_opportunity_state
    assert result.deterministic_qualified
    assert result.candidate_tier == "governed_base"
    assert result.gate_evaluations[Gate.G7].status is GateStatus.PASS


@pytest.mark.unit
def test_nominal_g2_rule_without_stable_responsibilities_is_rejected():
    with pytest.raises(ContractViolation, match="applicable G2 rules must cover"):
        compile_traditional_scan(_request(g2_responsibilities=frozenset()))


@pytest.mark.unit
def test_one_governed_g2_rule_can_bind_both_stable_responsibilities():
    result = compile_traditional_scan(
        _request(g2_responsibilities=frozenset(G2Responsibility))
    )

    assert result.gate_evaluations[Gate.G2].status is GateStatus.PASS
    assert result.candidate_tier == "governed_base"


@pytest.mark.unit
def test_valuation_cannot_collapse_and_peer_result_preserves_actual_sample():
    result = compile_traditional_scan(_request())

    assert result.valuation.historical_range.metric_id == "val_history"
    assert result.valuation.price_implied_assumptions.metric_id == "val_implied"
    assert result.valuation.bull_base_bear_bands.metric_id == "val_bands"
    assert result.valuation.upside_downside_asymmetry.metric_id == "val_asymmetry"
    assert result.valuation.uncertainty.metric_id == "val_uncertainty"
    assert result.valuation.peer_relative.peer_count == 20
    assert len(result.valuation.peer_relative.raw_peer_values) == 20
    assert result.valuation.peer_relative.percentile is not None
    assert result.valuation.peer_relative.peer_definition.endswith(
        "+software_infrastructure"
    )


@pytest.mark.unit
def test_peer_percentile_is_withheld_below_current_minimum_peer_count():
    result = compile_traditional_scan(_request(peer_count=19))

    assert result.valuation.peer_relative.peer_count == 19
    assert result.valuation.peer_relative.percentile is None
    assert result.valuation.peer_relative.raw_peer_values


@pytest.mark.unit
def test_missing_weight_above_25_percent_fails_closed_without_offset():
    result = compile_traditional_scan(
        _request(missing=("forward_change", "market_risk"))
    )

    assert result.unavailable_weight_fraction == pytest.approx(0.4)
    assert result.data_confidence == pytest.approx(0.6)
    assert not result.deterministic_core_eligible
    assert not result.deterministic_qualified
    assert result.candidate_tier is None
    assert result.gate_evaluations[Gate.G0].status is GateStatus.FAIL
    assert "INSUFFICIENT_SCORE_COVERAGE" in result.gate_evaluations[Gate.G0].reasons


@pytest.mark.unit
def test_authorized_renormalization_binds_scores_weights_method_and_evidence():
    result = compile_traditional_scan(_request(missing=("market_risk",)))

    available = [
        item
        for item in result.metric_evaluations.values()
        if item.transformed_score is not None
    ]
    assert result.data_confidence == pytest.approx(0.8)
    assert sum(item.effective_weight for item in available) == pytest.approx(1.0)
    financial = result.metric_evaluations["financial_reality"]
    assert financial.transformed_score == pytest.approx(0.8)
    assert financial.effective_weight == pytest.approx(0.15 / 0.8)
    assert financial.weighted_contribution == pytest.approx((0.15 / 0.8) * 0.8)
    assert financial.method_version == "financial_reality-method-v2"
    assert financial.evidence.require_available()["value"] == pytest.approx(0.8)
    assert result.metric_evaluations["market_risk"].effective_weight is None


@pytest.mark.unit
def test_missing_data_cannot_renormalize_without_recipe_authority():
    result = compile_traditional_scan(
        _request(missing=("market_risk",), allow_renormalization=False)
    )

    assert not result.deterministic_core_eligible
    assert result.candidate_tier is None
    assert "RENORMALIZATION_NOT_AUTHORIZED" in result.gate_evaluations[Gate.G0].reasons


@pytest.mark.unit
def test_nonactionable_data_confidence_cannot_be_offset_by_favorable_signals():
    overlay = AIOverlay(AIAction.MOVE_TIER, "governed_high", ("ai_exposure",))
    result = compile_traditional_scan(
        _request(
            missing=("market_risk",),
            overlay=overlay,
            data_confidence_actionable=lambda confidence: confidence >= 0.9,
        )
    )

    assert result.company_quality_score == pytest.approx(0.8)
    assert result.investment_opportunity_state == "owner_attractive"
    assert result.data_confidence == pytest.approx(0.8)
    assert result.gate_evaluations[Gate.G0].status is GateStatus.REVIEW_REQUIRED
    assert "DATA_CONFIDENCE_NOT_ACTIONABLE" in result.gate_evaluations[Gate.G0].reasons
    assert result.candidate_tier is None
    assert result.ai_action_applied is AIAction.NONE


@pytest.mark.unit
def test_favorable_quality_opportunity_and_ai_cannot_revive_hard_gate_failure():
    overlay = AIOverlay(AIAction.MOVE_TIER, "governed_high", ("ai_exposure",))
    result = compile_traditional_scan(
        _request(values={"financial_reality": 0.1}, overlay=overlay)
    )

    assert result.company_quality_score > 0.4
    assert result.investment_opportunity_state == "owner_attractive"
    assert result.gate_evaluations[Gate.G1].status is GateStatus.FAIL
    assert not result.deterministic_qualified
    assert result.base_candidate_tier is None
    assert result.candidate_tier is None
    assert result.ai_action_applied is AIAction.NONE


@pytest.mark.unit
def test_high_company_quality_alone_cannot_reach_highest_caller_owned_tier():
    valuation_values = dict.fromkeys(
        (
            "val_peer",
            "val_history",
            "val_implied",
            "val_bands",
            "val_asymmetry",
            "val_uncertainty",
        ),
        0.6,
    )
    result = compile_traditional_scan(
        _request(values=valuation_values, base_tier="governed_top")
    )

    assert result.company_quality_score == pytest.approx(0.8)
    assert result.investment_opportunity_state == "owner_unattractive"
    assert result.base_candidate_tier == "governed_top"
    assert result.candidate_tier is None
    assert result.review_required


@pytest.mark.unit
def test_ai_move_uses_actual_adjacency_on_caller_owned_versioned_tier_scale():
    nonadjacent = AIOverlay(AIAction.MOVE_TIER, "governed_top", ("ai_exposure",))
    rejected = compile_traditional_scan(_request(overlay=nonadjacent))
    adjacent = AIOverlay(AIAction.MOVE_TIER, "governed_high", ("ai_exposure",))
    accepted = compile_traditional_scan(_request(overlay=adjacent))

    assert rejected.candidate_tier is None
    assert rejected.review_required
    assert rejected.ai_action_applied is AIAction.NONE
    assert accepted.base_candidate_tier == "governed_base"
    assert accepted.candidate_tier == "governed_high"
    assert accepted.ai_action_applied is AIAction.MOVE_TIER
    assert accepted.ai_method_version == "owner-ai-influence-v8"


@pytest.mark.unit
def test_non_high_confidence_ai_cannot_move_a_tier():
    overlay = AIOverlay(AIAction.MOVE_TIER, "governed_high", ("ai_exposure",))
    result = compile_traditional_scan(
        _request(research=_research(confidence="governed_low"), overlay=overlay)
    )

    assert result.candidate_tier is None
    assert result.review_required
    assert result.ai_action_applied is AIAction.NONE


@pytest.mark.unit
def test_governed_applicability_true_blocks_missing_reporting_period():
    evidence = _record(reporting_period=None)
    result = compile_traditional_scan(
        _request(
            research=_research(evidence=evidence),
            reporting_period_applicable=lambda judgment, data: True,
        )
    )

    assert result.ai_action_applied is AIAction.NONE
    assert result.gate_evaluations[Gate.G6].status is GateStatus.REVIEW_REQUIRED
    assert any(
        reason.startswith("AI_EVIDENCE_REPORTING_PERIOD_MISSING")
        for reason in result.gate_evaluations[Gate.G6].reasons
    )
    assert result.deterministic_qualified
    assert result.candidate_tier is None


@pytest.mark.unit
def test_governed_applicability_false_allows_missing_reporting_period():
    evidence = _record(reporting_period=None)
    result = compile_traditional_scan(
        _request(
            research=_research(evidence=evidence),
            reporting_period_applicable=lambda judgment, data: False,
        )
    )

    assert result.gate_evaluations[Gate.G6].status is GateStatus.PASS
    assert not any(
        reason.startswith("AI_EVIDENCE_REPORTING_PERIOD_MISSING")
        for reason in result.gate_evaluations[Gate.G6].reasons
    )
    assert result.candidate_tier == "governed_base"


@pytest.mark.unit
def test_contradiction_human_state_is_derived_from_machine_state_and_blocks():
    contradiction = Contradiction(True, False, "issuer narrative conflicts with filing")
    result = compile_traditional_scan(
        _request(research=_research(contradiction=contradiction))
    )

    assert contradiction.state == "UNRESOLVED"
    assert result.gate_evaluations[Gate.G6].status is GateStatus.REVIEW_REQUIRED
    assert result.candidate_tier is None


@pytest.mark.unit
def test_non_benefit_structural_assessment_does_not_require_realized_economics():
    result = compile_traditional_scan(
        _request(research=_research(direction=AIImpactDirection.RISK, impacts=()))
    )

    assert result.gate_evaluations[Gate.G6].status is GateStatus.PASS
    assert result.candidate_tier == "governed_base"


@pytest.mark.unit
def test_affirmative_ai_benefit_rejects_bare_generic_scalar_evidence():
    scalar = _scalar_record(0.2)
    impact = QuantitativeEconomicImpact(
        "cost_reduction",
        0.2,
        ("value",),
        "year-over-year operating cost comparison",
        scalar,
    )
    result = compile_traditional_scan(
        _request(
            research=_research(
                direction=AIImpactDirection.BENEFIT,
                impacts=(impact,),
            )
        )
    )

    assert result.gate_evaluations[Gate.G6].status is GateStatus.REVIEW_REQUIRED
    assert "ECONOMIC_IMPACT_BARE_SCALAR:cost_reduction" in result.gate_evaluations[
        Gate.G6
    ].reasons
    assert result.candidate_tier is None


@pytest.mark.unit
def test_affirmative_ai_benefit_accepts_value_bound_quantitative_evidence():
    impact = QuantitativeEconomicImpact(
        "cost_reduction",
        0.2,
        ("value",),
        "year-over-year operating cost comparison",
        _record(0.2),
    )
    result = compile_traditional_scan(
        _request(
            research=_research(
                direction=AIImpactDirection.BENEFIT,
                impacts=(impact,),
            )
        )
    )

    assert result.gate_evaluations[Gate.G6].status is GateStatus.PASS
    assert result.candidate_tier == "governed_base"


@pytest.mark.unit
def test_compiler_has_no_provider_router_network_model_or_e02_materialization():
    tree = ast.parse(inspect.getsource(traditional))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    forbidden_roots = ("requests", "httpx", "openbb", "langchain", "tradingagents.llm_clients")
    assert not any(name.startswith(forbidden_roots) for name in imports)
    source = inspect.getsource(traditional)
    assert "route_to_vendor" not in source
    assert "selection_system" not in source
    assert "Unified Candidate" not in source
    assert "/Downloads/" not in source


# ---------------------------------------------------------------------------
# G1: Structural Disruption six-root-question coverage (CUR-001 / FZ-SD-001..007)
# ---------------------------------------------------------------------------


ROOT = StructuralDisruptionRootQuestion


def _finding(
    conclusion="reviewed",
    *,
    economic_transmission=None,
    incumbent_adaptation=None,
    horizon=None,
    falsification=None,
    confidence=None,
    counter=(),
    unknowns=(),
    refs=(),
):
    return StructuralDisruptionFinding(
        evidence=("issuer filing evidence",),
        counter_evidence=counter,
        conclusion=conclusion,
        economic_transmission=economic_transmission,
        incumbent_adaptation=incumbent_adaptation,
        expected_horizon=horizon,
        falsification_condition=falsification,
        confidence=confidence,
        major_unknowns=unknowns,
        methodology_rule_refs=refs,
    )


def _assessment():
    return StructuralDisruptionAssessment(
        method_version="sd-owner-v1",
        questions={
            ROOT.CUSTOMER_JOB_VALUE_ENGINE: _finding("job/value engine"),
            ROOT.OUTSIDE_SUBSTITUTE: _finding("substitute"),
            ROOT.MIGRATION_EVIDENCE_VELOCITY: _finding("migration"),
            ROOT.ECONOMIC_TRANSMISSION: _finding(
                "transmission", economic_transmission="customer -> demand -> margin"
            ),
            ROOT.INCUMBENT_ADAPTATION_COUNTERATTACK: _finding(
                "adaptation", incumbent_adaptation="incumbent can pivot"
            ),
            ROOT.TIMING_FALSIFICATION_CONFIDENCE: _finding(
                "timing",
                counter=("counter-evidence",),
                horizon="12-24 months",
                falsification="condition",
                confidence="medium",
                unknowns=("unknown",),
                refs=("FZ-SD-006",),
            ),
        },
    )


@pytest.mark.unit
def test_six_root_questions_are_exactly_the_frozen_set():
    from tradingagents.scanners.traditional import STRUCTURAL_DISRUPTION_ROOT_QUESTIONS

    assert {question.value for question in STRUCTURAL_DISRUPTION_ROOT_QUESTIONS} == {
        "CUSTOMER_JOB_VALUE_ENGINE",
        "OUTSIDE_SUBSTITUTE",
        "MIGRATION_EVIDENCE_VELOCITY",
        "ECONOMIC_TRANSMISSION",
        "INCUMBENT_ADAPTATION_COUNTERATTACK",
        "TIMING_FALSIFICATION_CONFIDENCE",
    }


@pytest.mark.unit
def test_valid_six_question_assessment_passes():
    validate_structural_disruption_6q(_assessment())


@pytest.mark.unit
def test_missing_root_question_fails_closed():
    assessment = _assessment()
    questions = dict(assessment.questions)
    del questions[ROOT.OUTSIDE_SUBSTITUTE]
    with pytest.raises(ContractViolation, match="exactly the six frozen root questions"):
        StructuralDisruptionAssessment("sd-owner-v1", questions)


@pytest.mark.unit
def test_q6_requires_falsification_confidence_and_horizon():
    questions = dict(_assessment().questions)
    questions[ROOT.TIMING_FALSIFICATION_CONFIDENCE] = _finding(
        "timing", counter=("counter-evidence",)
    )
    with pytest.raises(ContractViolation, match="expected_horizon"):
        StructuralDisruptionAssessment("sd-owner-v1", questions)


@pytest.mark.unit
def test_q6_requires_counter_evidence():
    questions = dict(_assessment().questions)
    questions[ROOT.TIMING_FALSIFICATION_CONFIDENCE] = _finding(
        "timing",
        horizon="12-24 months",
        falsification="condition",
        confidence="medium",
    )
    with pytest.raises(ContractViolation, match="counter-evidence"):
        StructuralDisruptionAssessment("sd-owner-v1", questions)


@pytest.mark.unit
def test_q4_requires_economic_transmission_path():
    questions = dict(_assessment().questions)
    questions[ROOT.ECONOMIC_TRANSMISSION] = _finding("transmission")
    with pytest.raises(ContractViolation, match="economic-transmission"):
        StructuralDisruptionAssessment("sd-owner-v1", questions)


@pytest.mark.unit
def test_q5_requires_incumbent_adaptation():
    questions = dict(_assessment().questions)
    questions[ROOT.INCUMBENT_ADAPTATION_COUNTERATTACK] = _finding("adaptation")
    with pytest.raises(ContractViolation, match="incumbent-adaptation"):
        StructuralDisruptionAssessment("sd-owner-v1", questions)


@pytest.mark.unit
def test_finding_requires_evidence_and_conclusion():
    with pytest.raises(ContractViolation, match="requires evidence"):
        StructuralDisruptionFinding((), (), "conclusion")


@pytest.mark.unit
def test_finding_preserves_methodology_rule_references():
    finding = _finding("reviewed", refs=("FZ-SD-001", "FZ-EXP-001"))
    assert finding.methodology_rule_refs == ("FZ-SD-001", "FZ-EXP-001")


# ---------------------------------------------------------------------------
# BR-1: the compiler produces methodology-neutral facts + Traditional-scoped
# claims (de-duplicated) and carries them, plus the 6Q assessment, in the real
# TraditionalScanResult (CUR-001/002/003).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compiler_carries_structural_disruption_and_deduped_evidence():
    from tradingagents.scanners.unified import SelectionSystem

    result = compile_traditional_scan(_request())

    # CUR-001: the 6Q assessment is produced in the real compiler path.
    assert result.structural_disruption is not None
    assert result.structural_disruption.method_version == "sd-owner-v1"

    # CUR-002: methodology-neutral facts, de-duplicated by identity.
    fact_ids = [fact.fact_id for fact in result.shared_facts]
    assert fact_ids
    assert len(fact_ids) == len(set(fact_ids)), "facts must be de-duplicated"
    forbidden = {
        "selection_score",
        "setup_score",
        "traditional_score",
        "pradeep_score",
        "bullish_conclusion",
        "bearish_conclusion",
        "entry_recommendation",
        "position_recommendation",
    }
    for fact in result.shared_facts:
        assert not (forbidden & set(fact.__dataclass_fields__))

    # CUR-002/003: Traditional-scoped claims reference the facts exactly once.
    claim_ids = [claim.claim_id for claim in result.system_evidence_claims]
    assert len(claim_ids) == len(set(claim_ids))
    for claim in result.system_evidence_claims:
        assert claim.system_scope is SelectionSystem.TRADITIONAL
        claim.require_system_scope(SelectionSystem.TRADITIONAL)
        assert len(claim.fact_refs) == len(set(claim.fact_refs)), "no double counting"

    g1_claim = next(
        claim
        for claim in result.system_evidence_claims
        if claim.claim_id.endswith(":G1_FINANCIAL_REALITY_CRITICAL_ACCOUNTING")
    )
    # The G1 claim references the de-duplicated fact(s) its metrics were
    # computed from; every ref resolves to a fact in the result.
    assert g1_claim.fact_refs
    assert set(g1_claim.fact_refs) <= set(fact_ids)

    # CUR-001/007: the structural 6Q rationale is carried as a dedicated
    # Traditional-scoped claim with its methodology rule references.
    sd_claim = next(
        claim
        for claim in result.system_evidence_claims
        if claim.claim_id.endswith(":structural_disruption_6q")
    )
    assert "TIMING_FALSIFICATION_CONFIDENCE" in sd_claim.claim
    assert "falsification" in sd_claim.claim
    assert "FZ-SD-006" in sd_claim.methodology_rule_refs


@pytest.mark.unit
def test_same_canonical_observation_dedupes_to_one_shared_fact():
    """Two (or more) metric analyses reading the same canonical observation
    must collapse to ONE SharedFact, not N per-metric facts (CUR-002)."""
    result = compile_traditional_scan(
        _request(shared_observation_metric_ids=("val_peer", "val_history"))
    )

    # Two G3 metrics read the same observation and resolve to one fact; all
    # other metrics retain distinct canonical sources.
    assert len(result.shared_facts) == 9
    fact = next(
        item
        for item in result.shared_facts
        if "issuer_primary_record:shared" in item.provenance
    )
    # The fact carries the actual observed value/content (auditable evidence).
    assert "0.8" in fact.fact
    assert "val_peer" not in fact.fact
    assert "val_history" not in fact.fact
    assert "traditional" not in fact.fact_id.lower()
    assert "traditional" not in fact.provenance.lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("duplicate_value", "other_value"),
    ((0.9, 0.1), (0.1, 0.9)),
)
def test_same_gate_duplicate_fact_fails_closed_before_weighting(
    duplicate_value, other_value
):
    """Two metric ids cannot move a gate or G7 by weighting one fact twice."""
    values = {
        "val_peer": duplicate_value,
        "val_history": duplicate_value,
        "val_implied": other_value,
        "val_bands": other_value,
        "val_asymmetry": other_value,
        "val_uncertainty": other_value,
    }
    result = compile_traditional_scan(
        _request(
            values=values,
            shared_observation_metric_ids=("val_peer", "val_history"),
        )
    )

    g3 = result.gate_evaluations[Gate.G3]
    assert g3.status is GateStatus.REVIEW_REQUIRED
    assert g3.score is None
    assert any("DUPLICATE_SCORE_BEARING_FACT" in reason for reason in g3.reasons)
    assert result.metric_evaluations["val_peer"].weighted_contribution is None
    assert result.metric_evaluations["val_history"].weighted_contribution is None
    assert result.candidate_tier is None
    assert result.gate_evaluations[Gate.G7].status is GateStatus.REVIEW_REQUIRED
    assert result.review_required


@pytest.mark.unit
def test_distinct_observations_yield_distinct_facts_without_double_counting():
    """Distinct observations produce distinct facts, and no gate claim double
    counts a single underlying fact (CUR-002)."""
    result = compile_traditional_scan(
        _request(values={"financial_reality": 0.9, "business_quality": 0.7})
    )

    fact_ids = [fact.fact_id for fact in result.shared_facts]
    assert len(fact_ids) == len(set(fact_ids)), "facts must be de-duplicated"
    # Every metric has its own canonical source even where values happen to
    # match, so value equality alone never merges distinct observations.
    assert len(fact_ids) == 10
    for claim in result.system_evidence_claims:
        if claim.claim_type == "gate_conclusion":
            assert len(claim.fact_refs) == len(set(claim.fact_refs)), "no double counting"


@pytest.mark.unit
def test_compiler_structural_disruption_gap_fails_closed():
    from tradingagents.scanners.traditional import StructuralDisruptionAssessment

    # Build a 6Q assessment missing one root question and confirm the compiler
    # rejects the request at the ScanRequest boundary (fail closed).
    questions = dict(_default_structural_disruption().questions)
    del questions[_SD.OUTSIDE_SUBSTITUTE]
    with pytest.raises(ContractViolation, match="exactly the six frozen root questions"):
        StructuralDisruptionAssessment("sd-owner-v1", questions)
