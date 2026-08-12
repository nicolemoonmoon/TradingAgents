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
