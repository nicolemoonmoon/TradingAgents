"""Focused, no-network tests for the frozen-E05 Pradeep compiler."""

from __future__ import annotations

import ast
import inspect
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest

from tradingagents import scanners
from tradingagents.scanners import (
    EP_9_MILLION,
    MAGNA,
    MB_FIRST_DAY_RANGE_EXPANSION,
    STOCKBEE_EPISODIC_PIVOT,
    STOCKBEE_MOMENTUM_BURST,
    SUPPORTED_PRADEEP_SETUP_IDS,
    EpisodicPivotObservations,
    MomentumBurstObservations,
    PradeepEvidenceRef,
    PradeepInputError,
    PradeepScanRequest,
    compile_pradeep_scan,
    pradeep,
)

NOW = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 8, 8)


def _evidence(methodology_ref: str, observation_ref: str = "issuer:ACME:2026Q2"):
    return PradeepEvidenceRef(
        methodology_ref=methodology_ref,
        observation_ref=observation_ref,
        description="Point-in-time ACME observation, separately bound to E05 methodology.",
    )


def _mb_request(**observation_overrides):
    return PradeepScanRequest(
        setup_id=STOCKBEE_MOMENTUM_BURST,
        detected_at=NOW,
        data_as_of=AS_OF,
        momentum_burst=MomentumBurstObservations(**observation_overrides),
    )


def _ep_request(**observation_overrides):
    return PradeepScanRequest(
        setup_id=STOCKBEE_EPISODIC_PIVOT,
        detected_at=NOW,
        data_as_of=AS_OF,
        episodic_pivot=EpisodicPivotObservations(**observation_overrides),
    )


def _ids(findings):
    return {finding.rule_id for finding in findings}


@pytest.mark.unit
def test_supported_setup_ids_are_exactly_the_two_frozen_e05_profiles():
    assert {
        "stockbee_momentum_burst",
        "stockbee_episodic_pivot",
    } == SUPPORTED_PRADEEP_SETUP_IDS


@pytest.mark.unit
@pytest.mark.parametrize("unsupported", ["Simple 9", "simple_9", "ep_9_million", MAGNA])
def test_stopped_or_context_only_designations_cannot_be_emitted_as_setups(unsupported):
    with pytest.raises(PradeepInputError, match="unsupported"):
        PradeepScanRequest(
            setup_id=unsupported,
            detected_at=NOW,
            data_as_of=AS_OF,
            momentum_burst=MomentumBurstObservations(),
        )


@pytest.mark.unit
def test_momentum_burst_selects_only_source_backed_first_day_event_without_calibration():
    result = compile_pradeep_scan(
        _mb_request(
            first_day_range_expansion=True,
            first_day_range_expansion_evidence=(
                _evidence("authority_pages/setups/momentum_burst.md"),
            ),
        )
    )

    assert result.selected
    assert _ids(result.matched_rules) == {MB_FIRST_DAY_RANGE_EXPANSION}
    assert {
        "MB_RANGE_EXPANSION_NUMERIC_THRESHOLD",
        "MB_ABOVE_AVERAGE_VOLUME_NUMERIC_THRESHOLD",
    } <= _ids(result.unknown_rules)
    assert not result.failed_rules
    assert not hasattr(result, "score")


@pytest.mark.unit
def test_source_undefined_momentum_thresholds_remain_unknown_and_fail_closed():
    result = compile_pradeep_scan(_mb_request(first_day_range_expansion=True))

    assert not result.selected
    assert not result.matched_rules
    assert MB_FIRST_DAY_RANGE_EXPANSION in _ids(result.unknown_rules)
    assert all("UNDEFINED" in finding.description for finding in result.unknown_rules[1:])


@pytest.mark.unit
def test_ep_scoped_50k_discovery_condition_is_not_sufficient_to_select():
    ep_ref = "authority_pages/setups/episodic_pivots.md"
    evidence = (_evidence(ep_ref),)
    result = compile_pradeep_scan(
        _ep_request(
            daily_discovery_neglect=False,
            daily_discovery_neglect_evidence=evidence,
            daily_discovery_significant_first_or_second_earnings_surprise=False,
            daily_discovery_significant_first_or_second_earnings_surprise_evidence=evidence,
            daily_discovery_gap_up=False,
            daily_discovery_gap_up_evidence=evidence,
            premarket_volume_shares=50_001,
            premarket_volume_evidence=evidence,
        )
    )

    assert "EP_PREMARKET_VOLUME_GT_50000_SHARES" in _ids(result.matched_rules)
    assert not result.selected
    assert result.selection_id is None


@pytest.mark.unit
@pytest.mark.parametrize("premarket_volume_shares", [50_000, 49_999])
def test_ep_scoped_50k_discovery_condition_fails_at_or_below_50k(
    premarket_volume_shares,
):
    result = compile_pradeep_scan(
        _ep_request(
            premarket_volume_shares=premarket_volume_shares,
            premarket_volume_evidence=(
                _evidence("authority_pages/setups/episodic_pivots.md"),
            ),
        )
    )

    assert "EP_PREMARKET_VOLUME_GT_50000_SHARES" in _ids(result.failed_rules)
    assert not result.selected


@pytest.mark.unit
@pytest.mark.parametrize(
    "observation_overrides",
    [
        {"premarket_volume_shares": None, "premarket_volume_evidence": ()},
        {"premarket_volume_shares": 50_001, "premarket_volume_evidence": ()},
    ],
)
def test_ep_scoped_50k_discovery_condition_is_unknown_without_value_or_evidence(
    observation_overrides,
):
    result = compile_pradeep_scan(_ep_request(**observation_overrides))

    assert "EP_PREMARKET_VOLUME_GT_50000_SHARES" in _ids(result.unknown_rules)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("signal_field", "evidence_field"),
    [
        (
            "genuinely_surprising_earnings_report",
            "genuinely_surprising_earnings_report_evidence",
        ),
        (
            "big_gap_up_with_huge_premarket_volume",
            "big_gap_up_with_huge_premarket_volume_evidence",
        ),
    ],
)
def test_ep_named_catalyst_signal_alone_does_not_select(
    signal_field,
    evidence_field,
):
    evidence = (_evidence("authority_pages/setups/episodic_pivots.md"),)
    result = compile_pradeep_scan(
        _ep_request(**{signal_field: True, evidence_field: evidence})
    )

    assert not result.selected
    assert result.selection_id is None


@pytest.mark.unit
def test_ep_contextual_assessment_without_evidence_fails_closed():
    evidence = (_evidence("authority_pages/setups/episodic_pivots.md"),)
    result = compile_pradeep_scan(
        _ep_request(
            genuinely_surprising_earnings_report=True,
            genuinely_surprising_earnings_report_evidence=evidence,
            catalyst_driven_change_in_attention_assessed_in_context=True,
        )
    )

    assert not result.selected
    assert (
        "EP_CATALYST_DRIVEN_CHANGE_IN_ATTENTION_ASSESSED_IN_CONTEXT"
        in _ids(result.unknown_rules)
    )


@pytest.mark.unit
def test_ep_contextual_assessment_without_named_catalyst_signal_does_not_select():
    evidence = (_evidence("authority_pages/setups/episodic_pivots.md"),)
    result = compile_pradeep_scan(
        _ep_request(
            catalyst_driven_change_in_attention_assessed_in_context=True,
            catalyst_driven_change_in_attention_assessed_in_context_evidence=evidence,
        )
    )

    assert not result.selected
    assert result.selection_id is None


@pytest.mark.unit
def test_ep_named_catalyst_and_contextual_assessment_select_with_evidence():
    evidence = (_evidence("authority_pages/setups/episodic_pivots.md"),)
    result = compile_pradeep_scan(
        _ep_request(
            genuinely_surprising_earnings_report=True,
            genuinely_surprising_earnings_report_evidence=evidence,
            catalyst_driven_change_in_attention_assessed_in_context=True,
            catalyst_driven_change_in_attention_assessed_in_context_evidence=evidence,
        )
    )

    assert result.selected
    assert result.selection_id
    assert {
        "EP_GENUINELY_SURPRISING_EARNINGS_REPORT",
        "EP_CATALYST_DRIVEN_CHANGE_IN_ATTENTION_ASSESSED_IN_CONTEXT",
    } <= _ids(result.matched_rules)


@pytest.mark.unit
def test_ep_9_million_designation_and_rough_qualifier_are_context_only():
    result = compile_pradeep_scan(
        _ep_request(
            ep_9_million_context=True,
            ep_9_million_evidence=(
                _evidence("authority_pages/setups/ep_9_million.md"),
            ),
        )
    )

    finding = next(item for item in result.matched_rules if item.rule_id == EP_9_MILLION)
    assert finding.rule_id == "EP 9 Million"
    assert "roughly 9–10 million shares traded" in finding.description
    assert "exact universal threshold" in finding.description
    assert not result.selected


@pytest.mark.unit
def test_magna_approximate_support_is_not_a_gate_or_third_profile():
    result = compile_pradeep_scan(
        _ep_request(
            magna_context=True,
            magna_evidence=(_evidence("authority_pages/setups/magna.md"),),
        )
    )

    finding = next(item for item in result.matched_rules if item.rule_id == MAGNA)
    assert "approximate" in finding.description
    assert "not universal exact gates" in finding.description
    assert not result.selected
    assert MAGNA not in SUPPORTED_PRADEEP_SETUP_IDS


@pytest.mark.unit
@pytest.mark.parametrize(
    "methodology_ref",
    [
        "https://example.com/arbitrary-method",
        "paid/login-gated/stockbee-50",
        "Market Monitor daily data",
    ],
)
def test_arbitrary_paid_and_unbound_methodology_sources_are_rejected(methodology_ref):
    with pytest.raises(PradeepInputError, match="inventory-bound"):
        _evidence(methodology_ref)


@pytest.mark.unit
def test_irrelevant_momentum_authority_cannot_support_ep_selection():
    with pytest.raises(PradeepInputError, match="not valid for this E05 observation"):
        compile_pradeep_scan(
            _ep_request(
                genuinely_surprising_earnings_report=True,
                genuinely_surprising_earnings_report_evidence=(
                    _evidence("authority_pages/setups/momentum_burst.md"),
                ),
            )
        )


@pytest.mark.unit
def test_rule_outcomes_are_disjoint_and_actual_selection_fields_are_complete():
    result = compile_pradeep_scan(
        _mb_request(
            first_day_range_expansion=True,
            first_day_range_expansion_evidence=(
                _evidence("authority_pages/concepts/entry_mechanics.md"),
            ),
        )
    )
    matched = _ids(result.matched_rules)
    failed = _ids(result.failed_rules)
    unknown = _ids(result.unknown_rules)

    assert not matched & failed
    assert not matched & unknown
    assert not failed & unknown
    assert result.selection_system == "PRADEEP"
    assert result.producer_version == "1.0.0"
    assert result.scanner_id == "e05_pradeep_scanner"
    assert result.selection_id
    assert result.evidence_refs
    assert result.detected_at == NOW
    assert result.data_as_of == AS_OF
    assert result.system_rank is None


@pytest.mark.unit
def test_missing_selection_timestamp_fails_closed():
    request = PradeepScanRequest(
        setup_id=STOCKBEE_MOMENTUM_BURST,
        detected_at=None,
        data_as_of=AS_OF,
        momentum_burst=MomentumBurstObservations(
            first_day_range_expansion=True,
            first_day_range_expansion_evidence=(
                _evidence("authority_pages/setups/momentum_burst.md"),
            ),
        ),
    )
    result = compile_pradeep_scan(request)

    assert not result.selected
    assert result.selection_id is None


@pytest.mark.unit
def test_repeated_and_parallel_actual_selections_receive_unique_ids():
    request = _mb_request(
        first_day_range_expansion=True,
        first_day_range_expansion_evidence=(
            _evidence("authority_pages/setups/momentum_burst.md"),
        ),
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(compile_pradeep_scan, (request,) * 64))

    ids = {result.selection_id for result in results}
    assert None not in ids
    assert len(ids) == len(results)


@pytest.mark.unit
def test_surface_has_no_generic_rule_callback_score_or_execution_authority():
    source = inspect.getsource(pradeep)
    tree = ast.parse(source)
    function_arguments = {
        argument.arg
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    }

    assert "Callable" not in source
    assert "scorer" not in source
    assert "threshold" not in function_arguments
    assert "rule_id" not in inspect.signature(compile_pradeep_scan).parameters
    assert "PradeepRuleFinding" not in scanners.__all__
    assert not {
        name
        for name in EpisodicPivotObservations.__dataclass_fields__
        if any(term in name for term in ("score", "rank", "threshold"))
    }
    for prohibited in ("broker", "order", "portfolio", "position_size", "stop", "exit"):
        assert prohibited not in PradeepScanRequest.__dataclass_fields__
        assert prohibited not in pradeep.PradeepScanResult.__dataclass_fields__


@pytest.mark.unit
def test_traditional_exports_remain_present():
    for existing_export in (
        "ScanRequest",
        "TraditionalScanResult",
        "compile_traditional_scan",
        "traditional",
    ):
        assert hasattr(scanners, existing_export)
