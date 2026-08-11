"""Frozen-E05 Pradeep scanner compiler over caller-supplied observations.

The compiler performs no retrieval, scoring, ranking, or execution work.  Its
methodology references and selectable observations are closed over the primary
authority inventory named by the frozen E05 contract.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import date, datetime
from typing import Literal
from uuid import uuid4

PRADEEP_SELECTION_SYSTEM = "PRADEEP"
PRADEEP_PRODUCER_VERSION = "1.0.0"
PRADEEP_SCANNER_ID = "e05_pradeep_scanner"

STOCKBEE_MOMENTUM_BURST = "stockbee_momentum_burst"
STOCKBEE_EPISODIC_PIVOT = "stockbee_episodic_pivot"
SUPPORTED_PRADEEP_SETUP_IDS = frozenset(
    {STOCKBEE_MOMENTUM_BURST, STOCKBEE_EPISODIC_PIVOT}
)

MB_FIRST_DAY_RANGE_EXPANSION = "MB_FIRST_DAY_RANGE_EXPANSION"
MB_RANGE_EXPANSION_NUMERIC_THRESHOLD = "MB_RANGE_EXPANSION_NUMERIC_THRESHOLD"
MB_ABOVE_AVERAGE_VOLUME_NUMERIC_THRESHOLD = (
    "MB_ABOVE_AVERAGE_VOLUME_NUMERIC_THRESHOLD"
)

EP_GENUINELY_SURPRISING_EARNINGS_REPORT = (
    "EP_GENUINELY_SURPRISING_EARNINGS_REPORT"
)
EP_BIG_GAP_UP_WITH_HUGE_PREMARKET_VOLUME = (
    "EP_BIG_GAP_UP_WITH_HUGE_PREMARKET_VOLUME"
)
EP_CATALYST_DRIVEN_CHANGE_IN_ATTENTION_ASSESSED_IN_CONTEXT = (
    "EP_CATALYST_DRIVEN_CHANGE_IN_ATTENTION_ASSESSED_IN_CONTEXT"
)
EP_DAILY_DISCOVERY_NEGLECT = "EP_DAILY_DISCOVERY_NEGLECT"
EP_DAILY_DISCOVERY_SIGNIFICANT_FIRST_OR_SECOND_EARNINGS_SURPRISE = (
    "EP_DAILY_DISCOVERY_SIGNIFICANT_FIRST_OR_SECOND_EARNINGS_SURPRISE"
)
EP_DAILY_DISCOVERY_GAP_UP = "EP_DAILY_DISCOVERY_GAP_UP"
EP_PREMARKET_VOLUME_GT_50000_SHARES = "EP_PREMARKET_VOLUME_GT_50000_SHARES"
EP_9_MILLION = "EP 9 Million"
MAGNA = "MAGNA/MAGNA53"

_MOMENTUM_BURST_REFS = frozenset(
    {
        "authority_pages/setups/momentum_burst.md",
        "source_notes/blog_2014_08_005_notes.md",
        "authority_pages/concepts/entry_mechanics.md",
        "source_notes/blog_2014_09_002_notes.md",
    }
)
_EPISODIC_PIVOT_REFS = frozenset(
    {
        "authority_pages/setups/episodic_pivots.md",
        "source_notes/blog_2014_09_004_notes.md",
    }
)
_EP_9_MILLION_REFS = frozenset(
    {
        "authority_pages/setups/ep_9_million.md",
        "source_notes/p1_video_semantic_enrichment_notes.md",
    }
)
_MAGNA_REFS = frozenset(
    {
        "authority_pages/setups/magna.md",
        "p9e_83522827cec8",
        "p9e_06458387fe86",
    }
)
_PRIMARY_AUTHORITY_REFS = frozenset(
    {
        *_MOMENTUM_BURST_REFS,
        *_EPISODIC_PIVOT_REFS,
        *_EP_9_MILLION_REFS,
        *_MAGNA_REFS,
        "authority_pages/concepts/risk_control.md",
        "authority_pages/concepts/setup_design.md",
        "authority_pages/concepts/anticipation.md",
        "authority_pages/process/watchlist_building.md",
        "authority_pages/process/swing_trading_process.md",
    }
)
_COMPILED_RESULT_TOKEN = object()


class PradeepInputError(ValueError):
    """Raised when input attempts to exceed the frozen E05 boundary."""


def _nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PradeepInputError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class PradeepEvidenceRef:
    """Separate methodology authority from observed company evidence."""

    methodology_ref: str
    observation_ref: str
    description: str

    def __post_init__(self) -> None:
        if self.methodology_ref not in _PRIMARY_AUTHORITY_REFS:
            raise PradeepInputError(
                "methodology_ref is not an inventory-bound E05 primary authority"
            )
        _nonempty(self.observation_ref, "observation_ref")
        _nonempty(self.description, "evidence description")


@dataclass(frozen=True, slots=True)
class MomentumBurstObservations:
    """The mechanically source-backed Momentum Burst event available in E05."""

    first_day_range_expansion: bool | None = None
    first_day_range_expansion_evidence: tuple[PradeepEvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class EpisodicPivotObservations:
    """Exact E05 EP signals and non-selecting discovery/context observations."""

    genuinely_surprising_earnings_report: bool | None = None
    genuinely_surprising_earnings_report_evidence: tuple[
        PradeepEvidenceRef, ...
    ] = ()
    big_gap_up_with_huge_premarket_volume: bool | None = None
    big_gap_up_with_huge_premarket_volume_evidence: tuple[
        PradeepEvidenceRef, ...
    ] = ()
    catalyst_driven_change_in_attention_assessed_in_context: bool | None = None
    catalyst_driven_change_in_attention_assessed_in_context_evidence: tuple[
        PradeepEvidenceRef, ...
    ] = ()
    daily_discovery_neglect: bool | None = None
    daily_discovery_neglect_evidence: tuple[PradeepEvidenceRef, ...] = ()
    daily_discovery_significant_first_or_second_earnings_surprise: bool | None = None
    daily_discovery_significant_first_or_second_earnings_surprise_evidence: tuple[
        PradeepEvidenceRef, ...
    ] = ()
    daily_discovery_gap_up: bool | None = None
    daily_discovery_gap_up_evidence: tuple[PradeepEvidenceRef, ...] = ()
    premarket_volume_shares: int | None = None
    premarket_volume_evidence: tuple[PradeepEvidenceRef, ...] = ()
    ep_9_million_context: bool | None = None
    ep_9_million_evidence: tuple[PradeepEvidenceRef, ...] = ()
    magna_context: bool | None = None
    magna_evidence: tuple[PradeepEvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if self.premarket_volume_shares is not None and (
            isinstance(self.premarket_volume_shares, bool)
            or not isinstance(self.premarket_volume_shares, int)
            or self.premarket_volume_shares < 0
        ):
            raise PradeepInputError(
                "premarket_volume_shares must be a non-negative integer or None"
            )


@dataclass(frozen=True, slots=True)
class PradeepScanRequest:
    setup_id: Literal["stockbee_momentum_burst", "stockbee_episodic_pivot"]
    detected_at: datetime | None
    data_as_of: date | datetime | None
    momentum_burst: MomentumBurstObservations | None = None
    episodic_pivot: EpisodicPivotObservations | None = None

    def __post_init__(self) -> None:
        if self.setup_id not in SUPPORTED_PRADEEP_SETUP_IDS:
            raise PradeepInputError("unsupported Pradeep setup_id")
        if self.setup_id == STOCKBEE_MOMENTUM_BURST:
            if self.momentum_burst is None or self.episodic_pivot is not None:
                raise PradeepInputError(
                    "Momentum Burst requires only momentum_burst observations"
                )
        elif self.episodic_pivot is None or self.momentum_burst is not None:
            raise PradeepInputError(
                "Episodic Pivot requires only episodic_pivot observations"
            )


@dataclass(frozen=True, slots=True)
class _PradeepRuleFinding:
    rule_id: str
    description: str
    evidence_refs: tuple[PradeepEvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class PradeepScanResult:
    """Internal E08 result; external E02 materialization belongs to E09."""

    selected: bool
    selection_system: str
    producer_version: str
    scanner_id: str
    setup_id: str
    selection_id: str | None
    matched_rules: tuple[_PradeepRuleFinding, ...]
    failed_rules: tuple[_PradeepRuleFinding, ...]
    unknown_rules: tuple[_PradeepRuleFinding, ...]
    evidence_refs: tuple[PradeepEvidenceRef, ...]
    detected_at: datetime | None
    data_as_of: date | datetime | None
    system_rank: None = None
    _compiler_token: InitVar[object] = None

    def __post_init__(self, _compiler_token: object) -> None:
        if _compiler_token is not _COMPILED_RESULT_TOKEN:
            raise PradeepInputError("Pradeep results are compiler-owned")
        if (
            self.selection_system != PRADEEP_SELECTION_SYSTEM
            or self.producer_version != PRADEEP_PRODUCER_VERSION
            or self.scanner_id != PRADEEP_SCANNER_ID
            or self.setup_id not in SUPPORTED_PRADEEP_SETUP_IDS
            or self.system_rank is not None
        ):
            raise PradeepInputError("result fields exceed the frozen E05 producer contract")
        groups = (
            {finding.rule_id for finding in self.matched_rules},
            {finding.rule_id for finding in self.failed_rules},
            {finding.rule_id for finding in self.unknown_rules},
        )
        if any(left & right for index, left in enumerate(groups) for right in groups[index + 1 :]):
            raise PradeepInputError("matched, failed, and unknown rule IDs must be disjoint")
        if self.selected and (
            self.selection_id is None
            or not self.matched_rules
            or not self.evidence_refs
            or self.detected_at is None
            or self.data_as_of is None
        ):
            raise PradeepInputError("an actual selection requires complete E05 producer fields")
        if not self.selected and self.selection_id is not None:
            raise PradeepInputError("a non-selection cannot carry a selection_id")


def _validate_evidence_scope(
    evidence: tuple[PradeepEvidenceRef, ...], allowed_refs: frozenset[str]
) -> None:
    for reference in evidence:
        if reference.methodology_ref not in allowed_refs:
            raise PradeepInputError(
                "methodology_ref is not valid for this E05 observation"
            )


def _finding(
    rule_id: str,
    description: str,
    evidence: tuple[PradeepEvidenceRef, ...] = (),
) -> _PradeepRuleFinding:
    return _PradeepRuleFinding(rule_id, description, evidence)


def _assess_observation(
    *,
    rule_id: str,
    description: str,
    observed: bool | None,
    evidence: tuple[PradeepEvidenceRef, ...],
    allowed_refs: frozenset[str],
) -> tuple[str, _PradeepRuleFinding]:
    _validate_evidence_scope(evidence, allowed_refs)
    finding = _finding(rule_id, description, evidence)
    if observed is None or not evidence:
        return "unknown", finding
    if observed:
        return "matched", finding
    return "failed", finding


def _append_assessment(
    assessment: tuple[str, _PradeepRuleFinding],
    matched: list[_PradeepRuleFinding],
    failed: list[_PradeepRuleFinding],
    unknown: list[_PradeepRuleFinding],
) -> None:
    state, finding = assessment
    {"matched": matched, "failed": failed, "unknown": unknown}[state].append(finding)


def _compile_momentum_burst(
    observations: MomentumBurstObservations,
) -> tuple[
    list[_PradeepRuleFinding],
    list[_PradeepRuleFinding],
    list[_PradeepRuleFinding],
    bool,
]:
    matched: list[_PradeepRuleFinding] = []
    failed: list[_PradeepRuleFinding] = []
    unknown: list[_PradeepRuleFinding] = []
    _append_assessment(
        _assess_observation(
            rule_id=MB_FIRST_DAY_RANGE_EXPANSION,
            description=(
                "Source-backed first day of range expansion; E05 supplies no "
                "universal numeric range or volume calibration."
            ),
            observed=observations.first_day_range_expansion,
            evidence=observations.first_day_range_expansion_evidence,
            allowed_refs=_MOMENTUM_BURST_REFS,
        ),
        matched,
        failed,
        unknown,
    )
    unknown.extend(
        (
            _finding(
                MB_RANGE_EXPANSION_NUMERIC_THRESHOLD,
                "UNDEFINED in E05; no numeric range-expansion threshold is inferred.",
            ),
            _finding(
                MB_ABOVE_AVERAGE_VOLUME_NUMERIC_THRESHOLD,
                "UNDEFINED in E05; no numeric above-average-volume threshold is inferred.",
            ),
        )
    )
    selectable = any(
        finding.rule_id == MB_FIRST_DAY_RANGE_EXPANSION for finding in matched
    )
    return matched, failed, unknown, selectable


def _compile_episodic_pivot(
    observations: EpisodicPivotObservations,
) -> tuple[
    list[_PradeepRuleFinding],
    list[_PradeepRuleFinding],
    list[_PradeepRuleFinding],
    bool,
]:
    matched: list[_PradeepRuleFinding] = []
    failed: list[_PradeepRuleFinding] = []
    unknown: list[_PradeepRuleFinding] = []

    assessments = (
        _assess_observation(
            rule_id=EP_GENUINELY_SURPRISING_EARNINGS_REPORT,
            description=(
                "A genuinely surprising earnings report is an E05 "
                "game-changing catalyst signal."
            ),
            observed=observations.genuinely_surprising_earnings_report,
            evidence=observations.genuinely_surprising_earnings_report_evidence,
            allowed_refs=_EPISODIC_PIVOT_REFS,
        ),
        _assess_observation(
            rule_id=EP_BIG_GAP_UP_WITH_HUGE_PREMARKET_VOLUME,
            description=(
                "A big gap up with huge pre-market volume evidences the E05 "
                "game-changing catalyst signal."
            ),
            observed=observations.big_gap_up_with_huge_premarket_volume,
            evidence=observations.big_gap_up_with_huge_premarket_volume_evidence,
            allowed_refs=_EPISODIC_PIVOT_REFS,
        ),
        _assess_observation(
            rule_id=EP_CATALYST_DRIVEN_CHANGE_IN_ATTENTION_ASSESSED_IN_CONTEXT,
            description=(
                "The catalyst-driven change in attention is assessed in the "
                "source-defined Episodic Pivot context rather than as a chart "
                "pattern alone."
            ),
            observed=(
                observations.catalyst_driven_change_in_attention_assessed_in_context
            ),
            evidence=(
                observations.catalyst_driven_change_in_attention_assessed_in_context_evidence
            ),
            allowed_refs=_EPISODIC_PIVOT_REFS,
        ),
        _assess_observation(
            rule_id=EP_DAILY_DISCOVERY_NEGLECT,
            description="Neglect in the source's scoped daily EP discovery context.",
            observed=observations.daily_discovery_neglect,
            evidence=observations.daily_discovery_neglect_evidence,
            allowed_refs=_EPISODIC_PIVOT_REFS,
        ),
        _assess_observation(
            rule_id=EP_DAILY_DISCOVERY_SIGNIFICANT_FIRST_OR_SECOND_EARNINGS_SURPRISE,
            description=(
                "A significant first or second earnings surprise in the source's "
                "scoped daily EP discovery context."
            ),
            observed=(
                observations.daily_discovery_significant_first_or_second_earnings_surprise
            ),
            evidence=(
                observations.daily_discovery_significant_first_or_second_earnings_surprise_evidence
            ),
            allowed_refs=_EPISODIC_PIVOT_REFS,
        ),
        _assess_observation(
            rule_id=EP_DAILY_DISCOVERY_GAP_UP,
            description="A gap up in the source's scoped daily EP discovery context.",
            observed=observations.daily_discovery_gap_up,
            evidence=observations.daily_discovery_gap_up_evidence,
            allowed_refs=_EPISODIC_PIVOT_REFS,
        ),
        _assess_observation(
            rule_id=EP_9_MILLION,
            description=(
                "EP 9 Million context: roughly 9–10 million shares traded is an "
                "empirical discovery/catalyst proxy, never an exact universal "
                "threshold or automatic selection predicate."
            ),
            observed=observations.ep_9_million_context,
            evidence=observations.ep_9_million_evidence,
            allowed_refs=_EP_9_MILLION_REFS,
        ),
        _assess_observation(
            rule_id=MAGNA,
            description=(
                "MAGNA/MAGNA53 is approximate, supporting candidate-quality and "
                "catalyst context; its figures are not universal exact gates."
            ),
            observed=observations.magna_context,
            evidence=observations.magna_evidence,
            allowed_refs=_MAGNA_REFS,
        ),
    )
    for assessment in assessments:
        _append_assessment(assessment, matched, failed, unknown)

    _validate_evidence_scope(
        observations.premarket_volume_evidence, _EPISODIC_PIVOT_REFS
    )
    volume_finding = _finding(
        EP_PREMARKET_VOLUME_GT_50000_SHARES,
        (
            "Above 50k shares only in the source's daily EP discovery context; "
            "sub-50k is not meaningful there and 50k may be insignificant for a "
            "large-cap. This is not a universal predicate, guarantee, rank, or score."
        ),
        observations.premarket_volume_evidence,
    )
    if (
        observations.premarket_volume_shares is None
        or not observations.premarket_volume_evidence
    ):
        unknown.append(volume_finding)
    elif observations.premarket_volume_shares > 50_000:
        matched.append(volume_finding)
    else:
        failed.append(volume_finding)

    catalyst_signal_ids = {
        EP_GENUINELY_SURPRISING_EARNINGS_REPORT,
        EP_BIG_GAP_UP_WITH_HUGE_PREMARKET_VOLUME,
    }
    matched_ids = {finding.rule_id for finding in matched}
    selectable = bool(catalyst_signal_ids & matched_ids) and (
        EP_CATALYST_DRIVEN_CHANGE_IN_ATTENTION_ASSESSED_IN_CONTEXT in matched_ids
    )
    return matched, failed, unknown, selectable


def compile_pradeep_scan(request: PradeepScanRequest) -> PradeepScanResult:
    """Compile one frozen-E05 decision without external E02 materialization."""

    if request.setup_id == STOCKBEE_MOMENTUM_BURST:
        assert request.momentum_burst is not None
        matched, failed, unknown, source_selectable = _compile_momentum_burst(
            request.momentum_burst
        )
    else:
        assert request.episodic_pivot is not None
        matched, failed, unknown, source_selectable = _compile_episodic_pivot(
            request.episodic_pivot
        )

    selected = (
        source_selectable
        and request.detected_at is not None
        and request.data_as_of is not None
    )
    evidence_by_identity = {
        (reference.methodology_ref, reference.observation_ref, reference.description): reference
        for finding in matched
        for reference in finding.evidence_refs
    }
    evidence_refs = tuple(evidence_by_identity.values())

    return PradeepScanResult(
        selected=selected,
        selection_system=PRADEEP_SELECTION_SYSTEM,
        producer_version=PRADEEP_PRODUCER_VERSION,
        scanner_id=PRADEEP_SCANNER_ID,
        setup_id=request.setup_id,
        selection_id=str(uuid4()) if selected else None,
        matched_rules=tuple(matched),
        failed_rules=tuple(failed),
        unknown_rules=tuple(unknown),
        evidence_refs=evidence_refs,
        detected_at=request.detected_at,
        data_as_of=request.data_as_of,
        _compiler_token=_COMPILED_RESULT_TOKEN,
    )
