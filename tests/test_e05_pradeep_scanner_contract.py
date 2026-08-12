"""Hermetic invariants for the frozen E05 Pradeep producer contract."""

from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "docs" / "e05_pradeep_scanner_contract.md"


def _contract() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def test_contract_is_frozen_with_exactly_two_supported_profiles() -> None:
    contract = _contract()

    assert "**Status:** `FROZEN`" in contract
    assert "- `stockbee_momentum_burst`" in contract
    assert "- `stockbee_episodic_pivot`" in contract
    assert "`Simple 9` is `STOPPED/UNDEFINED`" in contract
    assert "not a third E05 profile" in contract


def test_contract_preserves_producer_and_e02_boundaries() -> None:
    contract = _contract()

    for prohibited_authority in (
        "broker actions",
        "orders",
        "portfolio construction",
        "position sizing",
        "stops",
        "exits",
    ):
        assert prohibited_authority in contract

    assert "independent of E04 Traditional selection logic" in contract
    assert "`selection_system` exactly `PRADEEP`" in contract
    assert "`system_rank: null`" in contract
    assert "no combined, overall, or cross-system score" in contract
    assert "d7f47de35c0a61f50be37254ce24dbfa8a8d591acf272221d8bf7994ee56f310" in contract
    assert "6d58383c781ee3a54de3128dc0fd19bc16cafe69d3677259f8dda2adcd215de7" in contract
    assert "cb28c4ab589d786dba5b0653838083b0e582cd952e105ec3f7f87e520b8e47ee" in contract


def test_contract_preserves_source_scope_and_numeric_qualifiers() -> None:
    contract = _contract()

    assert "first day of range expansion" in contract
    assert "above 50k shares" in contract
    assert "roughly 9–10 million shares traded" in contract
    assert "greater than about five" in contract
    assert "three or more" in contract
    assert "above roughly 100%" in contract
    assert "above roughly 29%" in contract
    assert "around 25%+" in contract
    assert "at least roughly 4%" in contract
    assert "not a universal predicate" in contract
    assert "must not convert it into an exact universal threshold" in contract
    assert "Any source-undefined threshold remains `UNDEFINED`" in contract


def test_contract_uses_compact_primary_authority_references() -> None:
    contract = _contract()

    for reference in (
        "authority_pages/setups/momentum_burst.md",
        "authority_pages/setups/episodic_pivots.md",
        "authority_pages/setups/ep_9_million.md",
        "authority_pages/setups/magna.md",
        "source_notes/p1_video_semantic_enrichment_notes.md",
    ):
        assert reference in contract


def test_contract_does_not_define_a_duplicate_e02_schema() -> None:
    contract = _contract()

    assert '"$schema"' not in contract
    assert '"$defs"' not in contract
    assert "This document is the frozen E05 contract." in contract
