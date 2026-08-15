"""Focused E09 tests for the external-E02 unified candidate binding seam."""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from tradingagents.dataflows.canonical_data import Availability, CanonicalData
from tradingagents.scanners import (
    E02_SCHEMA_VERSION,
    MB_FIRST_DAY_RANGE_EXPANSION,
    STOCKBEE_MOMENTUM_BURST,
    CompanyIdentityBinding,
    EvidenceRef,
    Gate,
    GateEvaluation,
    GateStatus,
    IdentityStatus,
    MetricEvaluation,
    MomentumBurstObservations,
    PradeepEvidenceBinding,
    PradeepEvidenceRef,
    PradeepScanRequest,
    SelectionSystem,
    SystemRank,
    TraditionalEvidenceBinding,
    TraditionalScanResult,
    TraditionalSelectionBinding,
    UnifiedCandidateError,
    UnifiedSelection,
    assemble_unified_candidate,
    bind_pradeep_selection,
    bind_traditional_selection,
    compile_pradeep_scan,
    pradeep,
    traditional,
    unified,
    validate_unified_candidate,
)

NOW = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 8, 8)


def _canonical() -> CanonicalData[dict[str, float]]:
    return CanonicalData(
        operation="governed_evidence",
        availability=Availability.AVAILABLE,
        provider="issuer",
        source="issuer_primary_record",
        retrieved_at=NOW,
        payload={"value": 0.8},
        symbol="ACME",
        data_as_of=AS_OF,
        reporting_period="FY2025",
        unit="ratio",
        currency="USD",
    )


def _structural_disruption():
    from tradingagents.scanners.traditional import (
        StructuralDisruptionAssessment,
        StructuralDisruptionFinding,
        StructuralDisruptionRootQuestion,
    )

    root = StructuralDisruptionRootQuestion

    def finding(conclusion, counter_evidence=(), **kwargs):
        return StructuralDisruptionFinding(
            evidence=("evidence",),
            counter_evidence=counter_evidence,
            conclusion=conclusion,
            **kwargs,
        )

    return StructuralDisruptionAssessment(
        method_version="sd-owner-v1",
        questions={
            root.CUSTOMER_JOB_VALUE_ENGINE: finding("job/value engine"),
            root.OUTSIDE_SUBSTITUTE: finding("substitute"),
            root.MIGRATION_EVIDENCE_VELOCITY: finding("migration"),
            root.ECONOMIC_TRANSMISSION: finding(
                "transmission", economic_transmission="path"
            ),
            root.INCUMBENT_ADAPTATION_COUNTERATTACK: finding(
                "adaptation", incumbent_adaptation="pivot"
            ),
            root.TIMING_FALSIFICATION_CONFIDENCE: finding(
                "timing",
                counter_evidence=("counter",),
                expected_horizon="12m",
                falsification_condition="cond",
                confidence="medium",
            ),
        },
    )


def _traditional_result(*, selected: bool) -> TraditionalScanResult:
    metric = MetricEvaluation(
        metric_id="financial_reality",
        gate=Gate.G1,
        original_weight=1.0,
        effective_weight=1.0,
        transformed_score=0.8,
        weighted_contribution=0.8,
        method_version="frozen-rule-v1",
        evidence=_canonical(),
        unavailable_reason=None,
    )
    gates = {
        gate: GateEvaluation(
            gate=gate,
            status=(
                GateStatus.PASS
                if selected or gate is not Gate.G7
                else GateStatus.REVIEW_REQUIRED
            ),
            score=None,
            minimum_score=None,
            hard_gate=False,
        )
        for gate in Gate
    }
    return TraditionalScanResult(
        entity="ACME",
        economic_profile=traditional.EconomicProfile.ASSET_LIGHT_TECH_PLATFORM,
        metric_evaluations={"financial_reality": metric},
        gate_evaluations=gates,
        company_quality_score=0.8,
        investment_opportunity_state="owner_attractive",
        valuation=None,  # Runtime adapter does not reinterpret valuation.
        data_confidence=1.0,
        unavailable_weight_fraction=0.0,
        deterministic_core_eligible=selected,
        deterministic_qualified=selected,
        base_candidate_tier="owner_candidate" if selected else None,
        candidate_tier="owner_candidate" if selected else None,
        ai_action_applied=traditional.AIAction.NONE,
        review_required=not selected,
        vetoed=False,
        recipe_method_version="recipe-v1",
        gate_policy_method_version="gates-v1",
        data_confidence_method_version="confidence-v1",
        decision_method_version="decision-v1",
        ai_method_version="ai-v1",
        structural_disruption=_structural_disruption(),
    )


def _traditional_binding(selection_id: str = "traditional:ACME:1"):
    return TraditionalSelectionBinding(
        selection_id=selection_id,
        producer_version="e04-compiler-binding-v1",
        scanner_id="e04_traditional_scanner",
        setup_id=None,
        detected_at="2026-08-10T03:00:00+00:00",
        data_as_of="2026-08-08",
        evidence=(
            TraditionalEvidenceBinding(
                metric_id="financial_reality",
                evidence_id="traditional-evidence-1",
                source_type="fundamentals",
                source_url=None,
            ),
        ),
    )


def _pradeep_evidence() -> PradeepEvidenceRef:
    return PradeepEvidenceRef(
        methodology_ref="authority_pages/setups/momentum_burst.md",
        observation_ref="issuer:ACME:2026-08-08",
        description="Qualified first-day range expansion; no numeric threshold inferred.",
    )


def _pradeep_result(*, selected: bool):
    evidence = _pradeep_evidence()
    return compile_pradeep_scan(
        PradeepScanRequest(
            setup_id=STOCKBEE_MOMENTUM_BURST,
            detected_at=NOW,
            data_as_of=AS_OF,
            momentum_burst=MomentumBurstObservations(
                first_day_range_expansion=selected,
                first_day_range_expansion_evidence=(evidence,),
            ),
        )
    )


def _pradeep_binding(reference: PradeepEvidenceRef):
    return PradeepEvidenceBinding(
        reference=reference,
        evidence_id="pradeep-evidence-1",
        source_type="primary_methodology_and_observation",
        source_url=None,
        data_as_of="2026-08-08",
    )


def _identity(
    company_id: str = "ticker:ACME",
    status: IdentityStatus = IdentityStatus.PROVISIONAL,
    ticker: str | None = "ACME",
):
    return CompanyIdentityBinding(company_id, status, ticker, "Acme Limited")


def _valid_mapping(system: str = "TRADITIONAL") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "company_id": "ticker:ACME",
        "display_name": "Acme Limited",
        "identity_status": "provisional",
        "ticker": "ACME",
        "selections": [
            {
                "selection_id": "selection:1",
                "selection_system": system,
                "producer_version": "producer-v1",
                "scanner_id": "scanner-1",
                "setup_id": None,
                "matched_rules": ["rule.match"],
                "failed_rules": [],
                "unknown_rules": [],
                "evidence_refs": [
                    {
                        "evidence_id": "evidence:1",
                        "source_type": "fundamentals",
                        "source_ref": "issuer:filing:1",
                        "source_url": None,
                        "data_as_of": "2026-08-08",
                    }
                ],
                "detected_at": "2026-08-10T03:00:00+00:00",
                "data_as_of": "2026-08-08",
                "system_rank": None,
            }
        ],
    }


@pytest.mark.unit
def test_exact_top_level_version_required_fields_and_serialization_shape():
    candidate = validate_unified_candidate(_valid_mapping())

    assert candidate.schema_version == E02_SCHEMA_VERSION == "1.0.0"
    assert candidate.to_dict() == _valid_mapping()
    assert set(candidate.to_dict()) == {
        "schema_version",
        "company_id",
        "display_name",
        "identity_status",
        "ticker",
        "selections",
    }

    wrong_version = _valid_mapping()
    wrong_version["schema_version"] = "1.0.1"
    with pytest.raises(UnifiedCandidateError, match="schema_version"):
        validate_unified_candidate(wrong_version)

    missing_ticker = _valid_mapping()
    del missing_ticker["ticker"]
    with pytest.raises(UnifiedCandidateError, match="missing keys"):
        validate_unified_candidate(missing_ticker)


@pytest.mark.unit
def test_zero_actual_selections_never_forms_a_candidate():
    assert bind_traditional_selection(_traditional_result(selected=False), _traditional_binding()) is None
    assert bind_pradeep_selection(_pradeep_result(selected=False), ()) is None
    with pytest.raises(UnifiedCandidateError, match="requires selections"):
        assemble_unified_candidate(_identity(), (None, None))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("company_id", "status", "ticker"),
    [
        ("ACME", IdentityStatus.PROVISIONAL, "ACME"),
        ("ticker:acme", IdentityStatus.PROVISIONAL, "acme"),
        ("ticker:ACME", IdentityStatus.PROVISIONAL, None),
    ],
)
def test_provisional_identity_requires_exact_public_convention(company_id, status, ticker):
    with pytest.raises(UnifiedCandidateError, match="provisional"):
        _identity(company_id, status, ticker)


@pytest.mark.unit
def test_canonical_identity_may_have_no_ticker_and_rebinding_preserves_selection():
    selection = bind_traditional_selection(_traditional_result(selected=True), _traditional_binding())
    provisional = assemble_unified_candidate(_identity(), (selection,))
    canonical = assemble_unified_candidate(
        _identity("registry:company:42", IdentityStatus.CANONICAL, None),
        (selection,),
    )

    assert provisional.selections == canonical.selections
    assert canonical.ticker is None
    assert canonical.company_id == "registry:company:42"


@pytest.mark.unit
def test_actual_traditional_binding_uses_gates_and_explicit_envelope_provenance():
    selection = bind_traditional_selection(_traditional_result(selected=True), _traditional_binding())

    assert selection is not None
    assert selection.selection_system is SelectionSystem.TRADITIONAL
    assert selection.selection_id == "traditional:ACME:1"
    assert selection.setup_id is None
    assert selection.system_rank is None
    assert selection.matched_rules == tuple(gate.value for gate in Gate)
    assert not selection.failed_rules
    assert not selection.unknown_rules
    evidence = selection.evidence_refs[0]
    assert evidence.source_type == "fundamentals"
    assert evidence.data_as_of == "2026-08-08"
    provenance = json.loads(evidence.source_ref)
    assert provenance["provider"] == "issuer"
    assert provenance["source"] == "issuer_primary_record"
    assert provenance["reporting_period"] == "FY2025"


@pytest.mark.unit
def test_traditional_evidence_must_bind_an_actual_producer_record():
    binding = replace(
        _traditional_binding(),
        evidence=(
            TraditionalEvidenceBinding("not_in_output", "e1", "fundamentals", None),
        ),
    )
    with pytest.raises(UnifiedCandidateError, match="not present"):
        bind_traditional_selection(_traditional_result(selected=True), binding)


@pytest.mark.unit
def test_traditional_setup_semantics_cannot_be_invented_at_binding_boundary():
    with pytest.raises(UnifiedCandidateError, match="setup_id must remain null"):
        replace(_traditional_binding(), setup_id="invented-setup")


@pytest.mark.unit
def test_actual_pradeep_binding_preserves_metadata_rules_and_qualified_provenance():
    result = _pradeep_result(selected=True)
    selection = bind_pradeep_selection(result, (_pradeep_binding(result.evidence_refs[0]),))

    assert selection is not None
    assert selection.selection_id == result.selection_id
    assert selection.selection_system.value == result.selection_system == "PRADEEP"
    assert selection.producer_version == result.producer_version == "1.0.0"
    assert selection.scanner_id == result.scanner_id == "e05_pradeep_scanner"
    assert selection.setup_id == result.setup_id
    assert selection.matched_rules == tuple(item.rule_id for item in result.matched_rules)
    assert selection.failed_rules == tuple(item.rule_id for item in result.failed_rules)
    assert selection.unknown_rules == tuple(item.rule_id for item in result.unknown_rules)
    assert selection.matched_rules == (MB_FIRST_DAY_RANGE_EXPANSION,)
    assert selection.system_rank is None
    provenance = json.loads(selection.evidence_refs[0].source_ref)
    assert provenance["methodology_ref"] == result.evidence_refs[0].methodology_ref
    assert provenance["observation_ref"] == result.evidence_refs[0].observation_ref
    assert provenance["description"] == result.evidence_refs[0].description


@pytest.mark.unit
def test_pradeep_binding_requires_exact_explicit_evidence_coverage():
    result = _pradeep_result(selected=True)
    with pytest.raises(UnifiedCandidateError, match="exactly cover"):
        bind_pradeep_selection(result, ())


@pytest.mark.unit
def test_traditional_and_pradeep_coexist_without_merging_provenance_or_rules():
    traditional_selection = bind_traditional_selection(
        _traditional_result(selected=True), _traditional_binding()
    )
    pradeep_result = _pradeep_result(selected=True)
    pradeep_selection = bind_pradeep_selection(
        pradeep_result,
        (_pradeep_binding(pradeep_result.evidence_refs[0]),),
    )
    candidate = assemble_unified_candidate(
        _identity(), (traditional_selection, pradeep_selection)
    )

    assert tuple(item.selection_system for item in candidate.selections) == (
        SelectionSystem.TRADITIONAL,
        SelectionSystem.PRADEEP,
    )
    assert candidate.selections[0].matched_rules != candidate.selections[1].matched_rules
    assert candidate.selections[0].evidence_refs != candidate.selections[1].evidence_refs
    assert not any("score" in key for key in candidate.to_dict())


@pytest.mark.unit
def test_duplicate_selection_id_is_rejected():
    first = bind_traditional_selection(_traditional_result(selected=True), _traditional_binding("dup"))
    second = bind_traditional_selection(_traditional_result(selected=True), _traditional_binding("dup"))
    with pytest.raises(UnifiedCandidateError, match="selection_id"):
        assemble_unified_candidate(_identity(), (first, second))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda selection: replace(
                selection, failed_rules=(selection.matched_rules[0],)
            ),
            "unique and disjoint",
        ),
        (lambda selection: replace(selection, matched_rules=()), "matched rule"),
        (lambda selection: replace(selection, evidence_refs=()), "requires evidence"),
        (
            lambda selection: replace(
                selection,
                evidence_refs=(selection.evidence_refs[0], selection.evidence_refs[0]),
            ),
            "evidence_id",
        ),
    ],
)
def test_selection_rule_and_evidence_invariants_fail_closed(mutation, message):
    selection = bind_traditional_selection(_traditional_result(selected=True), _traditional_binding())
    with pytest.raises(UnifiedCandidateError, match=message):
        mutation(selection)


@pytest.mark.unit
def test_exact_allowed_systems_and_producer_local_rank_representation():
    assert tuple(item.value for item in SelectionSystem) == (
        "TRADITIONAL",
        "PRADEEP",
        "TECHNOLOGY",
    )
    technology_shape = _valid_mapping("TECHNOLOGY")
    assert validate_unified_candidate(technology_shape).selections[0].selection_system is (
        SelectionSystem.TECHNOLOGY
    )

    unknown = _valid_mapping("MIXED")
    with pytest.raises(UnifiedCandidateError, match="selection_system"):
        validate_unified_candidate(unknown)

    ranked = _valid_mapping()
    ranked_selection = ranked["selections"][0]
    ranked_selection["system_rank"] = {
        "value": 3,
        "meaning": "within the producing Traditional selection only",
        "higher_is_better": False,
    }
    parsed = validate_unified_candidate(ranked)
    assert parsed.selections[0].system_rank == SystemRank(
        3, "within the producing Traditional selection only", False
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("combined_score", 91),
        ("overall_score", 91),
        ("cross_system_score", 91),
    ],
)
def test_cross_system_scores_are_impossible_and_strictly_rejected(field_name, value):
    candidate = _valid_mapping()
    candidate[field_name] = value
    with pytest.raises(UnifiedCandidateError, match="additional keys"):
        validate_unified_candidate(candidate)
    assert field_name not in UnifiedSelection.__dataclass_fields__


@pytest.mark.unit
def test_exact_mapping_rejects_extra_nested_fields_and_duplicate_evidence_ids():
    extra = _valid_mapping()
    extra["selections"][0]["producer_score"] = 0.8
    with pytest.raises(UnifiedCandidateError, match="additional keys"):
        validate_unified_candidate(extra)

    duplicate = _valid_mapping()
    reference = duplicate["selections"][0]["evidence_refs"][0]
    duplicate["selections"][0]["evidence_refs"].append(dict(reference))
    with pytest.raises(UnifiedCandidateError, match="evidence_id"):
        validate_unified_candidate(duplicate)


@pytest.mark.unit
def test_e09_has_no_technology_binder_or_new_runtime_authority():
    module_source = inspect.getsource(unified)
    tree = ast.parse(module_source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    forbidden_import_roots = (
        "requests",
        "httpx",
        "openbb",
        "langchain",
        "tradingagents.dataflows.interface",
        "tradingagents.llm_clients",
    )
    assert not any(name.startswith(forbidden_import_roots) for name in imports)
    assert not any(
        name.lower().startswith(("bind_technology", "compile_technology"))
        for name in vars(unified)
    )
    assert not {
        "router",
        "state_store",
        "orchestrator",
        "registry",
        "provider_client",
    } & set(vars(unified))


@pytest.mark.unit
def test_e09_does_not_modify_or_replace_frozen_producer_compilers():
    assert bind_traditional_selection.__module__ == "tradingagents.scanners.unified"
    assert bind_pradeep_selection.__module__ == "tradingagents.scanners.unified"
    assert traditional.compile_traditional_scan.__module__ == "tradingagents.scanners.traditional"
    assert pradeep.compile_pradeep_scan.__module__ == "tradingagents.scanners.pradeep"


@pytest.mark.unit
def test_external_e02_authority_files_are_not_materialized_in_repository():
    repository_root = inspect.getfile(unified)
    assert "e02_schema" not in repository_root
    assert "e02_policy" not in repository_root
    assert "e02_test_vectors" not in repository_root


@pytest.mark.unit
def test_evidence_exact_bounds_and_types_are_validated():
    with pytest.raises(UnifiedCandidateError, match="evidence_id"):
        EvidenceRef("", "type", "ref", None, None)
    with pytest.raises(UnifiedCandidateError, match="source_type"):
        EvidenceRef("id", "x" * 81, "ref", None, None)
    with pytest.raises(UnifiedCandidateError, match="finite"):
        SystemRank(float("nan"), "local", True)


# ---------------------------------------------------------------------------
# G2/G5: system-scoped evidence/snapshot/decision contract + selection-origin
# contamination guards (FZ-DATA-003/005, FZ-SEL-001..004; T01-T16 equivalents)
# ---------------------------------------------------------------------------


from tradingagents.scanners.unified import (  # noqa: E402
    AnalysisPurpose,
    SelectionRecordRef,
    SharedFact,
    SystemAnalysisSnapshot,
    SystemDecisionEvent,
    SystemEvidenceClaim,
    SystemPortfolioContext,
    build_traditional_snapshot,
    derive_analysis_governance,
)


def _trad_ref(selection_id="traditional:ACME:1"):
    return SelectionRecordRef(selection_id, SelectionSystem.TRADITIONAL, "ticker:ACME")


def _pradeep_ref(selection_id="pradeep:ACME:1"):
    return SelectionRecordRef(selection_id, SelectionSystem.PRADEEP, "ticker:ACME")


def _snapshot(
    *,
    system=SelectionSystem.TRADITIONAL,
    purpose=AnalysisPurpose.BASELINE_SYSTEM,
    eligible=True,
    ref=None,
):
    if ref is None:
        ref = _trad_ref() if system is SelectionSystem.TRADITIONAL else _pradeep_ref()
    return SystemAnalysisSnapshot(
        snapshot_id="snap:1",
        system_scope=system,
        methodology_version="v1",
        data_as_of=None,
        candidate_ref="ticker:ACME",
        selection_record_ref=ref,
        analysis_purpose=purpose,
        portfolio_eligible=eligible,
        shared_fact_refs=("fact:1",),
        system_evidence_claim_refs=("claim:1",),
        provenance_refs=("prov:1",),
        payload_type="TraditionalAnalysisPayload",
        payload_hash="abc123",
    )


def _decision(*, system=SelectionSystem.TRADITIONAL, snapshot_id="snap:1"):
    ref = _trad_ref() if system is SelectionSystem.TRADITIONAL else _pradeep_ref()
    return SystemDecisionEvent(
        decision_id="decision:1",
        system_scope=system,
        unified_candidate_ref="ticker:ACME",
        selection_record_ref=ref,
        analysis_purpose=AnalysisPurpose.BASELINE_SYSTEM,
        portfolio_eligible=True,
        decision_time="2026-08-10T03:00:00+00:00",
        data_as_of=None,
        position_state_at_decision="NOT_HELD",
        action_intent="BUY",
        methodology_decision_code="E04_G7_BUY",
        reason_summary="summary",
        analysis_snapshot_ref=snapshot_id,
        analysis_snapshot_hash="abc123",
    )


@pytest.mark.unit
def test_t03_shared_fact_has_no_methodology_fields():
    forbidden = (
        "selection_score",
        "setup_score",
        "traditional_score",
        "pradeep_score",
        "technology_score",
        "bullish_conclusion",
        "bearish_conclusion",
        "entry_recommendation",
        "position_recommendation",
        "methodology_weight",
        "methodology_rank",
    )
    fields = set(SharedFact.__dataclass_fields__)
    assert not fields & set(forbidden)
    fact = SharedFact(
        fact_id="fact:1",
        fact_type="filing",
        fact="issuer reported revenue",
        source_refs=("issuer:filing:1",),
        data_as_of="2026-08-08",
        provenance="issuer",
    )
    assert fact.fact_type == "filing"


@pytest.mark.unit
def test_t01_foreign_claim_read_rejected():
    claim = SystemEvidenceClaim(
        claim_id="claim:1",
        system_scope=SelectionSystem.TRADITIONAL,
        claim_type="valuation",
        fact_refs=("fact:1",),
        claim="fairly valued",
        confidence="medium",
        methodology_rule_refs=("G3-rule",),
        data_as_of="2026-08-08",
        provenance="issuer",
    )
    claim.require_system_scope(SelectionSystem.TRADITIONAL)  # own system: ok
    with pytest.raises(UnifiedCandidateError, match="CROSS_SYSTEM_CONTAMINATION"):
        claim.require_system_scope(SelectionSystem.PRADEEP)


@pytest.mark.unit
def test_t05_decision_event_system_matches_snapshot_system():
    traditional_snapshot = _snapshot(system=SelectionSystem.TRADITIONAL)
    pradeep_snapshot = _snapshot(system=SelectionSystem.PRADEEP)
    traditional_decision = _decision(system=SelectionSystem.TRADITIONAL)

    traditional_decision.require_matches_snapshot(traditional_snapshot)  # ok
    with pytest.raises(UnifiedCandidateError, match="CROSS_SYSTEM_CONTAMINATION"):
        traditional_decision.require_matches_snapshot(pradeep_snapshot)


@pytest.mark.unit
def test_t02_foreign_snapshot_ref_rejected():
    with pytest.raises(UnifiedCandidateError, match="baseline selection origin"):
        _snapshot(system=SelectionSystem.TRADITIONAL, ref=_pradeep_ref())


@pytest.mark.unit
def test_t11_baseline_selection_origin_matches_system():
    governance = derive_analysis_governance(
        SelectionSystem.TRADITIONAL, _trad_ref(), AnalysisPurpose.BASELINE_SYSTEM
    )
    assert governance.analysis_purpose is AnalysisPurpose.BASELINE_SYSTEM
    assert governance.system_scope is SelectionSystem.TRADITIONAL
    assert governance.portfolio_eligible is True


@pytest.mark.unit
def test_t06_t07_baseline_rejects_foreign_selection():
    with pytest.raises(UnifiedCandidateError, match="foreign selection"):
        derive_analysis_governance(
            SelectionSystem.TRADITIONAL, _pradeep_ref(), AnalysisPurpose.BASELINE_SYSTEM
        )
    with pytest.raises(UnifiedCandidateError, match="foreign selection"):
        derive_analysis_governance(
            SelectionSystem.PRADEEP, _trad_ref(), AnalysisPurpose.BASELINE_SYSTEM
        )


@pytest.mark.unit
def test_t12_exploratory_foreign_candidate_portfolio_ineligible():
    governance = derive_analysis_governance(
        SelectionSystem.TRADITIONAL, _pradeep_ref(), AnalysisPurpose.EXPLORATORY_COMPARE
    )
    assert governance.analysis_purpose is AnalysisPurpose.EXPLORATORY_COMPARE
    assert governance.portfolio_eligible is False


@pytest.mark.unit
def test_t13_manual_candidate_portfolio_ineligible_without_own_selection():
    governance = derive_analysis_governance(None, None, None)
    assert governance.analysis_purpose is AnalysisPurpose.OWNER_MANUAL_REVIEW
    assert governance.system_scope is None
    assert governance.portfolio_eligible is False

    with pytest.raises(UnifiedCandidateError, match="missing origin"):
        derive_analysis_governance(None, None, AnalysisPurpose.BASELINE_SYSTEM)


@pytest.mark.unit
def test_origin_requires_explicit_system_scope_not_inferred():
    with pytest.raises(UnifiedCandidateError, match="explicit system_scope"):
        derive_analysis_governance(None, _trad_ref(), AnalysisPurpose.BASELINE_SYSTEM)


@pytest.mark.unit
def test_t09_cross_system_combined_score_absent_in_new_objects():
    for cls in (
        SharedFact,
        SystemEvidenceClaim,
        SystemAnalysisSnapshot,
        SystemDecisionEvent,
    ):
        fields = set(cls.__dataclass_fields__)
        assert not fields & {"combined_score", "cross_system_score", "overall_score"}


@pytest.mark.unit
def test_t16_no_promotion_or_ledger_engine_symbols():
    forbidden = {
        "promote",
        "promotion",
        "promotion_engine",
        "decision_ledger",
        "paper_portfolio",
        "tracking_service",
        "pnl_engine",
    }
    assert not forbidden & set(vars(unified))
    assert not forbidden & set(vars(traditional))


@pytest.mark.unit
def test_baseline_snapshot_must_be_portfolio_eligible():
    with pytest.raises(UnifiedCandidateError, match="portfolio_eligible"):
        _snapshot(system=SelectionSystem.TRADITIONAL, eligible=False)


# ---------------------------------------------------------------------------
# BR-1 / BR-4: real snapshot creation/binding at the binding boundary, and
# mechanically scoped portfolio-context semantics (CUR-003, T14/T15).
# ---------------------------------------------------------------------------


def _snapshot_ready_result():
    """A selected TraditionalScanResult carrying one fact and one claim so the
    snapshot integration test exercises non-empty reference forwarding."""
    result = _traditional_result(selected=True)
    fact = SharedFact(
        fact_id="fact:traditional:ACME:financial_reality",
        fact_type="canonical_metric_observation",
        fact="issuer-reported financial_reality for FY2025 (ratio)",
        source_refs=("issuer:filing:1",),
        data_as_of="2026-08-08",
        provenance="traditional_e04_compiler",
    )
    claim = SystemEvidenceClaim(
        claim_id="claim:traditional:ACME:G1_FINANCIAL_REALITY_CRITICAL_ACCOUNTING",
        system_scope=SelectionSystem.TRADITIONAL,
        claim_type="gate_conclusion",
        fact_refs=(fact.fact_id,),
        claim="G1_FINANCIAL_REALITY_CRITICAL_ACCOUNTING PASS",
        confidence="high",
        methodology_rule_refs=("frozen-rule-v1",),
        data_as_of=None,
        provenance="traditional_e04_compiler",
    )
    return replace(result, shared_facts=(fact,), system_evidence_claims=(claim,))


@pytest.mark.unit
def test_build_traditional_snapshot_binds_facts_claims_and_selection():
    result = _snapshot_ready_result()
    selection = bind_traditional_selection(result, _traditional_binding())
    assert selection is not None
    ref = SelectionRecordRef("traditional:ACME:1", SelectionSystem.TRADITIONAL, "ticker:ACME")

    snapshot = build_traditional_snapshot(result, selection, ref)

    assert snapshot.system_scope is SelectionSystem.TRADITIONAL
    assert snapshot.selection_record_ref == ref
    assert snapshot.methodology_version == selection.producer_version
    assert snapshot.candidate_ref == "ticker:ACME"
    assert snapshot.shared_fact_refs == ("fact:traditional:ACME:financial_reality",)
    assert snapshot.system_evidence_claim_refs == (
        "claim:traditional:ACME:G1_FINANCIAL_REALITY_CRITICAL_ACCOUNTING",
    )
    assert snapshot.portfolio_eligible is True
    assert len(snapshot.payload_hash) == 64  # sha256 hex

    # A decision event binds to this snapshot (system + id match).
    decision = _decision(system=SelectionSystem.TRADITIONAL, snapshot_id=snapshot.snapshot_id)
    decision.require_matches_snapshot(snapshot)


@pytest.mark.unit
def test_build_traditional_snapshot_rejects_foreign_selection():
    result = _snapshot_ready_result()
    selection = bind_traditional_selection(result, _traditional_binding())
    assert selection is not None
    foreign_ref = SelectionRecordRef("traditional:ACME:1", SelectionSystem.PRADEEP, "ticker:ACME")
    with pytest.raises(UnifiedCandidateError, match="baseline selection origin"):
        build_traditional_snapshot(result, selection, foreign_ref)


@pytest.mark.unit
def test_snapshot_rejects_foreign_claim_at_consumption_boundary():
    """The snapshot consumes the compiler's claims at a real boundary and fails
    closed on a foreign system_scope (T01 / CUR-008)."""
    result = _snapshot_ready_result()
    foreign_claim = SystemEvidenceClaim(
        claim_id="claim:foreign:1",
        system_scope=SelectionSystem.PRADEEP,
        claim_type="gate_conclusion",
        fact_refs=(),
        claim="foreign claim",
        confidence="high",
        methodology_rule_refs=(),
        data_as_of=None,
        provenance="pradeep",
    )
    result = replace(result, system_evidence_claims=(foreign_claim,))
    selection = bind_traditional_selection(result, _traditional_binding())
    assert selection is not None
    ref = SelectionRecordRef("traditional:ACME:1", SelectionSystem.TRADITIONAL, "ticker:ACME")
    with pytest.raises(UnifiedCandidateError, match="CROSS_SYSTEM_CONTAMINATION"):
        build_traditional_snapshot(result, selection, ref)


@pytest.mark.unit
def test_t14_t15_portfolio_context_scope_is_mechanical():
    ctx = SystemPortfolioContext("ctx:1", SelectionSystem.TRADITIONAL, None)
    ctx.require_system_scope(SelectionSystem.TRADITIONAL)  # own system: ok
    with pytest.raises(UnifiedCandidateError, match="CROSS_SYSTEM_CONTAMINATION"):
        ctx.require_system_scope(SelectionSystem.PRADEEP)


@pytest.mark.unit
def test_decision_event_rejects_foreign_portfolio_context():
    foreign_ctx = SystemPortfolioContext("ctx:pradeep:1", SelectionSystem.PRADEEP, None)
    with pytest.raises(UnifiedCandidateError, match="portfolio context"):
        SystemDecisionEvent(
            decision_id="decision:2",
            system_scope=SelectionSystem.TRADITIONAL,
            unified_candidate_ref="ticker:ACME",
            selection_record_ref=_trad_ref(),
            analysis_purpose=AnalysisPurpose.BASELINE_SYSTEM,
            portfolio_eligible=True,
            decision_time="2026-08-10T03:00:00+00:00",
            data_as_of=None,
            position_state_at_decision="NOT_HELD",
            action_intent="BUY",
            methodology_decision_code="E04_G7_BUY",
            reason_summary="summary",
            analysis_snapshot_ref="snap:1",
            analysis_snapshot_hash="abc123",
            portfolio_context_ref=foreign_ctx,
        )


@pytest.mark.unit
def test_t14_t15_contract_does_not_require_live_portfolio_runtime():
    """A baseline decision with no portfolio service/context remains valid;
    only a supplied foreign context is prohibited by the contract oracle."""
    decision = SystemDecisionEvent(
        decision_id="decision:no-portfolio-runtime",
        system_scope=SelectionSystem.TRADITIONAL,
        unified_candidate_ref="ticker:ACME",
        selection_record_ref=_trad_ref(),
        analysis_purpose=AnalysisPurpose.BASELINE_SYSTEM,
        portfolio_eligible=True,
        decision_time="2026-08-10T03:00:00+00:00",
        data_as_of=None,
        position_state_at_decision="NOT_HELD",
        action_intent="REVIEW",
        methodology_decision_code="E04_REVIEW_REQUIRED",
        reason_summary="No trusted portfolio context is available.",
        analysis_snapshot_ref="snap:1",
        analysis_snapshot_hash="abc123",
        portfolio_context_ref=None,
    )
    assert decision.portfolio_context_ref is None
