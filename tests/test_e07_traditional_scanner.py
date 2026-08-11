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

NOW = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)
PROFILE = EconomicProfile.ASSET_LIGHT_TECH_PLATFORM


def _record(
    value=0.8,
    *,
    symbol="ACME",
    availability=Availability.AVAILABLE,
    reporting_period="FY2025",
    reason=None,
):
    return CanonicalData(
        operation="governed_evidence",
        availability=availability,
        provider="issuer",
        source="issuer_primary_record",
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
):
    values = values or {}
    evidence = {}
    rules = _rules(g2_responsibilities=g2_responsibilities)
    for rule in rules:
        if rule.metric_id in missing:
            data = _record(
                availability=Availability.UNAVAILABLE,
                reason="not present at the point in time",
            )
        else:
            data = _record(values.get(rule.metric_id, 0.8))
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
