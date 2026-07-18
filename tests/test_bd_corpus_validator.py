"""Phase 10D: B+D corpus validator tests with provenance subsystem.

No network, no provider, no yfinance, no runtime code.
Uses synthetic fixtures only.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.bd_corpus.validator import validate_corpus

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "tools" / "bd_corpus" / "fixtures"
MANIFEST = FIXTURES / "synthetic_manifest.jsonl"
SEGMENTS = FIXTURES / "synthetic_segments.jsonl"
CARDS = FIXTURES / "synthetic_cards.jsonl"
PROVENANCE = FIXTURES / "synthetic_provenance_manifest.jsonl"


# ===========================================================================
# Positive: valid fixture passes
# ===========================================================================


@pytest.mark.unit
def test_valid_fixture_passes():
    report = validate_corpus(MANIFEST, SEGMENTS, CARDS, PROVENANCE)
    assert report.passed, [i.message for i in report.issues]


@pytest.mark.unit
def test_canonical_event_dedup_coverage():
    report = validate_corpus(MANIFEST, SEGMENTS, CARDS, PROVENANCE)
    assert "evt_range_expansion_2024" in report.coverage_counts
    assert report.coverage_counts["evt_range_expansion_2024"] == 1


@pytest.mark.unit
def test_contradiction_links_preserved():
    rows = _load(CARDS)
    cc = next(r for r in rows if r["card_id"] == "card_contradiction_example")
    assert "card_complete_setup_definition" in cc["contradicts"]


@pytest.mark.unit
def test_no_runtime_imports():
    import tools.bd_corpus.validator as vmod
    source = Path(vmod.__file__).read_text()
    forbidden = [
        "tradingagents.graph", "api.main", "fastapi", "uvicorn",
        "yfinance", "contextvars", "langchain", "tradingagents.default_config",
    ]
    for term in forbidden:
        assert term not in source, f"imports forbidden: {term}"


@pytest.mark.unit
def test_deterministic_issue_ordering():
    report = validate_corpus(MANIFEST, SEGMENTS, CARDS, PROVENANCE)
    for i in range(len(report.issues) - 1):
        a, b = report.issues[i], report.issues[i + 1]
        sev_a = 0 if a.level == "error" else 1
        sev_b = 0 if b.level == "error" else 1
        assert sev_a <= sev_b


# ===========================================================================
# Existing negative tests (adapted for provenance)
# ===========================================================================


@pytest.mark.unit
def test_manifest_missing_required_field_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        del rows[0]["source_id"]
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_duplicate_source_id_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows.append(dict(rows[0]))
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("duplicate" in i.message.lower() for i in report.issues)


@pytest.mark.unit
def test_duplicate_segment_id_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        rows = _load(SEGMENTS)
        rows.append(dict(rows[0]))
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_duplicate_card_id_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows.append(dict(rows[0]))
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_broken_supporting_segment_id_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows[0]["supporting_segment_ids"] = ["nonexistent_seg_999"]
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_direct_quote_missing_timestamp_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        for r in rows:
            if r.get("extraction_type") == "direct_quote":
                r["timestamp"] = None
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_direct_quote_missing_source_url_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        for r in rows:
            if r.get("extraction_type") == "direct_quote":
                r["source_url"] = ""
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_segment_over_120_words_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        rows = _load(SEGMENTS)
        rows[0]["text"] = "word " * 121
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_direct_quote_over_25_words_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        for r in rows:
            if r.get("extraction_type") == "direct_quote":
                r["text"] = "word " * 26
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_source_over_1200_words_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        rows = _load(SEGMENTS)
        words_100 = "word " * 100
        for row in rows:
            row["text"] = words_100
        for i in range(10):
            rows.append({
                "segment_id": f"seg_extra_{i}",
                "source_id": "stockbee_yt_range_expansion",
                "canonical_event_id": "evt_range_expansion_2024",
                "start_ts": "00:00", "end_ts": "00:10",
                "source_group": "B_official_youtube",
                "speaker": "Pradeep Bonde",
                "caption_type": "auto",
                "text": words_100,
                "topic_tags": [], "confidence": "medium",
            })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        retention_issues = [
            issue for issue in report.issues
            if issue.entity_type == "segment"
            and issue.field == "text"
            and issue.message == "source retained text exceeds cap"
        ]
        assert not report.passed
        assert retention_issues
        assert all(
            issue.entity_id == "stockbee_yt_range_expansion"
            for issue in retention_issues
        )
        assert all(
            "stockbee_yt_range_expansion" not in issue.message
            for issue in retention_issues
        )


@pytest.mark.unit
def test_profile_conflict_pradeep_v1():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows.append({
            "card_id": "card_pradeep_v1_conflict", "card_kind": "curated",
            "category": "market_context", "subtopic": "profile_isolation_test",
            "extraction_type": "analyst_inference",
            "text": "Synthetic test card.",
            "source_id": "stockbee_yt_range_expansion",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "canonical_event_id": "evt_range_expansion_2024",
            "timestamp": "03:15",
            "supporting_segment_ids": ["seg_range_expansion_001"],
            "confidence": "low", "temporal_context": "test",
            "contradicts": [], "superseded_by": [],
            "profile_tags": ["stockbee_momentum_burst", "pradeep_v1"],
            "grounding_eligible": False,
        })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
    issues = [i for i in report.issues if i.entity_id == "card_pradeep_v1_conflict"]
    assert len(issues) >= 1


@pytest.mark.unit
def test_paid_public_or_paid_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["public_or_paid"] = "paid"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_prohibited_access_marker_in_title_fails():
    for marker in ["paid", "member", "private", "paywall"]:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "manifest.jsonl"
            rows = _load(MANIFEST)
            rows[0]["title"] = f"Stockbee {marker}-only content"
            _write(bad, rows)
            report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
            assert not report.passed


@pytest.mark.unit
def test_a_lite_anchor_source_group_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_group"] = "A_lite_anchor"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("a_lite_anchor" in i.message.lower() or "schema" in i.message.lower()
                   for i in report.issues)


@pytest.mark.unit
def test_invalid_extraction_type_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows[0]["extraction_type"] = "invalid_type"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_dangling_contradicts_link_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows[0]["contradicts"] = ["card_nonexistent_999"]
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_self_contradicts_link_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        own_id = rows[0]["card_id"]
        rows[0]["contradicts"] = [own_id]
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_dangling_superseded_by_link_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows[0]["superseded_by"] = ["card_nonexistent_888"]
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_card_canonical_event_mismatch_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows[0]["canonical_event_id"] = "evt_wrong_event_id"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_segment_canonical_event_mismatch_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        rows = _load(SEGMENTS)
        rows[0]["canonical_event_id"] = "evt_wrong_event_id"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        assert not report.passed


# ===========================================================================
# Contradiction card_kind tests
# ===========================================================================


@pytest.mark.unit
def test_contradiction_card_without_contradicts_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows.append({
            "card_id": "card_contra_empty", "card_kind": "contradiction",
            "category": "risk", "subtopic": "test",
            "extraction_type": "analyst_inference",
            "text": "No targets.", "source_id": "stockbee_yt_range_expansion",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "canonical_event_id": "evt_range_expansion_2024",
            "timestamp": "03:15", "confidence": "medium",
            "contradicts": [], "superseded_by": [],
            "profile_tags": [], "grounding_eligible": False,
        })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed
        assert any("contradiction-designated" in i.message.lower()
                   or "valid" in i.message.lower()
                   for i in report.issues)


@pytest.mark.unit
def test_contradiction_card_with_dangling_contradicts_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows.append({
            "card_id": "card_contra_dangling", "card_kind": "contradiction",
            "category": "risk", "subtopic": "test",
            "extraction_type": "analyst_inference",
            "text": "Dangling.", "source_id": "stockbee_yt_range_expansion",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "canonical_event_id": "evt_range_expansion_2024",
            "timestamp": "03:15", "confidence": "medium",
            "contradicts": ["card_nonexistent_xyz"],
            "superseded_by": [], "profile_tags": [], "grounding_eligible": False,
        })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_contradiction_card_with_self_link_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        cid = "card_contra_self"
        rows.append({
            "card_id": cid, "card_kind": "contradiction",
            "category": "risk", "subtopic": "test",
            "extraction_type": "analyst_inference",
            "text": "Self.", "source_id": "stockbee_yt_range_expansion",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "canonical_event_id": "evt_range_expansion_2024",
            "timestamp": "03:15", "confidence": "medium",
            "contradicts": [cid], "superseded_by": [],
            "profile_tags": [], "grounding_eligible": False,
        })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_valid_contradiction_card_passes():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows.append({
            "card_id": "card_contra_valid", "card_kind": "contradiction",
            "category": "risk", "subtopic": "test",
            "extraction_type": "analyst_inference",
            "text": "Valid contradiction.", "source_id": "stockbee_yt_range_expansion",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "canonical_event_id": "evt_range_expansion_2024",
            "timestamp": "03:15", "confidence": "medium",
            "contradicts": ["card_volume_confirmation"],
            "superseded_by": [], "profile_tags": [], "grounding_eligible": False,
        })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        issues = [i for i in report.issues
                  if i.entity_id == "card_contra_valid"
                  and "contradiction" in i.message.lower()]
        assert not issues


# ===========================================================================
# Deterministic tests
# ===========================================================================


@pytest.mark.unit
def test_canonical_event_index_sorted():
    report = validate_corpus(MANIFEST, SEGMENTS, CARDS, PROVENANCE)
    idx = report.canonical_event_index
    assert list(idx.keys()) == sorted(idx.keys())
    for sids in idx.values():
        assert sids == sorted(sids)


@pytest.mark.unit
def test_shuffled_input_produces_identical_report():
    import random
    rng = random.Random(42)
    rows = _load(MANIFEST)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "m_o.jsonl"; s = Path(td) / "m_s.jsonl"
        _write(o, rows); _write(s, shuffled)
        r1 = validate_corpus(o, SEGMENTS, CARDS, PROVENANCE)
        r2 = validate_corpus(s, SEGMENTS, CARDS, PROVENANCE)
        assert len(r1.issues) == len(r2.issues)
        for a, b in zip(r1.issues, r2.issues):
            assert (a.level, a.entity_type, a.entity_id, a.code, a.field, a.message) == \
                   (b.level, b.entity_type, b.entity_id, b.code, b.field, b.message)
        assert r1.canonical_event_index == r2.canonical_event_index


# ===========================================================================
# Provenance: status tests
# ===========================================================================


@pytest.mark.unit
def test_missing_provenance_fails():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, [])
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_MISSING" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_pending_provenance_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["status"] = "pending"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_NOT_VERIFIED" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_rejected_provenance_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["status"] = "rejected"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_revoked_provenance_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["status"] = "revoked"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_duplicate_provenance_id_fails():
    _prov = _load(PROVENANCE)
    _prov.append(dict(_prov[0]))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("duplicate" in i.message.lower() for i in report.issues)


@pytest.mark.unit
def test_duplicate_conflicting_canonical_resource_binding_fails():
    _prov = _load(PROVENANCE)
    dup = dict(_prov[0])
    dup["provenance_id"] = "prov_dup_binding"
    _prov.append(dup)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_DUPLICATE_BINDING" in (i.code or "")
                   for i in report.issues)


@pytest.mark.unit
def test_duplicate_conflicting_canonical_url_binding_fails():
    _prov = _load(PROVENANCE)
    dup = dict(_prov[0])
    dup["provenance_id"] = "prov_dup_url"
    dup["canonical_resource_id"] = "different_vid_123"
    _prov.append(dup)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_DUPLICATE_BINDING" in (i.code or "")
                   for i in report.issues)


@pytest.mark.unit
def test_verified_missing_verified_by_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["verified_by"] = None
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_verified_missing_verified_at_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["verified_at"] = None
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_verified_missing_verification_method_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["verification_method"] = None
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_verified_malformed_evidence_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "not-a-valid-digest"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_dangling_superseded_provenance_link_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["superseded_by_provenance_id"] = "prov_nonexistent"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_SUPERSESSION_DANGLING" in (i.code or "")
                   for i in report.issues)


@pytest.mark.unit
def test_self_superseded_provenance_link_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["superseded_by_provenance_id"] = _prov[0]["provenance_id"]
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_SUPERSESSION_SELF" in (i.code or "")
                   for i in report.issues)


# ===========================================================================
# B adversarial host tests
# ===========================================================================


@pytest.mark.unit
def test_evil_youtube_subdomain_fails():
    """evil.youtube.com must not be treated as approved YouTube host."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://evil.youtube.com/watch?v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("HOST_NOT_APPROVED" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_youtube_dot_com_evil_example_fails():
    """youtube.com.evil.example must be rejected."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_youtube_example_dot_com_fails():
    """youtube.example.com must be rejected."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://youtube.example.com/watch?v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_evil_youtube_com_fails():
    """evil-youtube.com must be rejected."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://evil-youtube.com/watch?v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_generic_blog_with_stockbee_in_url_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://tradingblog.com/stockbee-method"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_valid_yt_url_absent_from_provenance_fails():
    """A valid YouTube URL not in provenance must fail."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"
        rows = _load(MANIFEST)
        rows[0]["provenance_id"] = "prov_nonexistent_xyz"
        _write(m, rows)
        report = validate_corpus(m, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("PROV_MISSING" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_wrong_channel_handle_vs_provenance_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["channel_handle"] = "@WrongChannel"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("CHANNEL_HANDLE_MISMATCH" in (i.code or "")
                   for i in report.issues)


@pytest.mark.unit
def test_wrong_channel_url_vs_provenance_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["channel_url"] = "https://youtube.com/@wrong"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("CHANNEL_URL_MISMATCH" in (i.code or "")
                   for i in report.issues)


@pytest.mark.unit
def test_handle_in_fragment_provides_no_trust():
    """@stockbeevideos in URL fragment must not count as proof.
    Fragment is ignored by resource identity parser — video ID matches."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; c = Path(td) / "c.jsonl"; p = Path(td) / "p.jsonl"
        m_rows = _load(MANIFEST)
        new_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ#@stockbeevideos"
        m_rows[0]["source_url"] = new_url
        c_rows = _load(CARDS)
        for r in c_rows:
            if r["source_id"] == "stockbee_yt_range_expansion":
                r["source_url"] = new_url
        _write(m, m_rows); _write(c, c_rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, c, p)
        # Fragment ignored by resource parser; provenance match succeeds; card URLs match
        assert report.passed, [i.message for i in report.issues]


@pytest.mark.unit
def test_unsupported_youtube_path_fails():
    """Arbitrary YouTube channel paths must be rejected."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://www.youtube.com/@stockbeevideos"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_valid_youtu_be_binding_passes():
    """youtu.be short URL should parse correctly and match provenance."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; c = Path(td) / "c.jsonl"; p = Path(td) / "p.jsonl"
        m_rows = _load(MANIFEST)
        new_url = "https://youtu.be/dQw4w9WgXcQ"
        m_rows[0]["source_url"] = new_url
        c_rows = _load(CARDS)
        for r in c_rows:
            if r["source_id"] == "stockbee_yt_range_expansion":
                r["source_url"] = new_url
        _write(m, m_rows); _write(c, c_rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, c, p)
        assert report.passed, [i.message for i in report.issues]


@pytest.mark.unit
def test_duplicate_v_param_fails():
    """Multiple v= params must be rejected."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=other"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_empty_v_param_fails():
    """Empty v= parameter must be rejected."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://www.youtube.com/watch?v="
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


# ===========================================================================
# D adversarial tests
# ===========================================================================


@pytest.mark.unit
def test_generic_url_with_podcast_assertion_but_no_binding_fails():
    """A generic URL self-declared as podcast without verified provenance fails."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[1]["source_url"] = "https://example.com/podcast/fake"
        rows[1]["provenance_id"] = "prov_nonexistent"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_d_source_with_wrong_primary_speaker_vs_provenance_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[1]["primary_speaker"] = "John Smith"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("SPEAKER_MISMATCH" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_d_source_type_mismatch_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[1]["source_type"] = "interview"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("SOURCE_TYPE_MISMATCH" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_d_platform_mismatch_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[1]["platform"] = "apple_podcasts"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PLATFORM_MISMATCH" in (i.code or "") for i in report.issues)


# ===========================================================================
# Card URL binding tests
# ===========================================================================


@pytest.mark.unit
def test_matching_card_url_passes():
    """Card source_url matching source manifest passes (no CARD_URL_MISMATCH)."""
    report = validate_corpus(MANIFEST, SEGMENTS, CARDS, PROVENANCE)
    card_issues = [i for i in report.issues if i.code == "CARD_URL_MISMATCH"]
    assert not card_issues, [i.message for i in card_issues]


@pytest.mark.unit
def test_mismatched_card_url_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows[0]["source_url"] = "https://wrong-url.example.com"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert any("CARD_URL_MISMATCH" in (i.code or "") for i in report.issues)


# ===========================================================================
# provenance_path required
# ===========================================================================


@pytest.mark.unit
def test_missing_provenance_path_fails():
    """Omission of provenance_path must fail at the API boundary."""
    with pytest.raises(TypeError):
        validate_corpus(MANIFEST, SEGMENTS, CARDS)  # missing 4th arg


# ===========================================================================
# B: port / scheme / query / duplicate-v tests
# ===========================================================================


@pytest.mark.unit
def test_non_default_youtube_port_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://youtube.com:444/watch?v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_v_eq_empty_and_v_eq_valid_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://www.youtube.com/watch?v=&v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_v_eq_valid_and_v_eq_empty_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v="
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_duplicate_distinct_v_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=OTHER1234567"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_single_valid_v_passes():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; c = Path(td) / "c.jsonl"; p = Path(td) / "p.jsonl"
        m_rows = _load(MANIFEST)
        new_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        m_rows[0]["source_url"] = new_url
        c_rows = _load(CARDS)
        for r in c_rows:
            if r["source_id"] == "stockbee_yt_range_expansion":
                r["source_url"] = new_url
        _write(m, m_rows); _write(c, c_rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, c, p)
        assert report.passed, [i.message for i in report.issues]


@pytest.mark.unit
def test_extra_youtu_be_path_segment_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://youtu.be/dQw4w9WgXcQ/extra"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_empty_youtu_be_path_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://youtu.be/"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_userinfo_in_url_fails():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://user@youtube.com/watch?v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        assert not report.passed


# ===========================================================================
# B canonical_resource_url validation
# ===========================================================================


@pytest.mark.unit
def test_prov_canonical_url_different_video_id_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["canonical_resource_url"] = "https://www.youtube.com/watch?v=abcdefghijk"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("RESOURCE_ID_MISMATCH" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_prov_url_on_generic_host_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["canonical_resource_url"] = "https://example.com/watch?v=dQw4w9WgXcQ"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_prov_url_on_evil_youtube_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["canonical_resource_url"] = "https://evil.youtube.com/watch?v=dQw4w9WgXcQ"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_prov_url_with_port_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["canonical_resource_url"] = "https://www.youtube.com:443/watch?v=dQw4w9WgXcQ"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_prov_unsupported_youtube_path_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["canonical_resource_url"] = "https://www.youtube.com/embed/dQw4w9WgXcQ"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


# ===========================================================================
# B/D conditional field exclusivity
# ===========================================================================


@pytest.mark.unit
def test_b_entry_with_approved_platform_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["approved_platform"] = "youtube"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PLATFORM_MISMATCH" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_d_entry_with_approved_channel_handle_fails():
    _prov = _load(PROVENANCE)
    _prov[1]["approved_channel_handle"] = "@stockbeevideos"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("CHANNEL_HANDLE_MISMATCH" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_d_entry_with_approved_channel_url_fails():
    _prov = _load(PROVENANCE)
    _prov[1]["approved_channel_url"] = "https://www.youtube.com/@stockbeevideos"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("CHANNEL_URL_MISMATCH" in (i.code or "") for i in report.issues)


# ===========================================================================
# evidence_digest exact validation
# ===========================================================================


@pytest.mark.unit
def test_exact_valid_digest_passes():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:" + "0" * 64
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert report.passed, [i.message for i in report.issues]


@pytest.mark.unit
def test_trailing_newline_in_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:" + "0" * 64 + "\n"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_uppercase_hex_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:" + "A" * 64
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_63_hex_chars_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:" + "0" * 63
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_65_hex_chars_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:" + "0" * 65
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_wrong_prefix_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha512:" + "0" * 64
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


# ===========================================================================
# Validation code contract
# ===========================================================================


@pytest.mark.unit
def test_prov_duplicate_id_code_emitted():
    _prov = _load(PROVENANCE)
    _prov.append(dict(_prov[0]))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert any("PROV_DUPLICATE_ID" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_prov_metadata_invalid_code_emitted():
    _prov = _load(PROVENANCE)
    _prov[0]["verified_by"] = None
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert any("PROV_VERIFICATION_METADATA_INVALID" in (i.code or "") for i in report.issues)


# ===========================================================================
# Sanitized schema errors
# ===========================================================================


@pytest.mark.unit
def test_sanitized_schema_error_no_raw_exception():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = None  # will cause schema error
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        for i in report.issues:
            assert "Traceback" not in i.message
            assert "ValidationError" not in i.message
            assert "pydantic" not in i.message.lower()


@pytest.mark.unit
def test_malformed_url_port_no_raw_valueerror():
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_url"] = "https://youtube.com:badport/watch?v=dQw4w9WgXcQ"
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        for i in report.issues:
            assert "ValueError" not in i.message
            assert "Traceback" not in i.message


# ===========================================================================
# Unknown extra field rejection
# ===========================================================================


@pytest.mark.unit
def test_unknown_field_in_provenance_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["bogus_field"] = "evil"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"
        _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_unknown_field_in_source_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["bogus"] = "evil"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_unknown_field_in_segment_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        rows = _load(SEGMENTS)
        rows[0]["bogus"] = "evil"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_unknown_field_in_card_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        rows = _load(CARDS)
        rows[0]["bogus"] = "evil"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed


# ===========================================================================
# Deterministic duplicate diagnostics
# ===========================================================================


@pytest.mark.unit
def test_shuffled_duplicate_provenance_ids_identical_report():
    import random
    rng = random.Random(99)
    _prov = _load(PROVENANCE)
    dup = dict(_prov[0]); dup["provenance_id"] = "prov_dup"
    rows = _prov + [dup]
    shuffled = list(rows); rng.shuffle(shuffled)
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "po.jsonl"; s = Path(td) / "ps.jsonl"
        _write(o, rows); _write(s, shuffled)
        r1 = validate_corpus(MANIFEST, SEGMENTS, CARDS, o)
        r2 = validate_corpus(MANIFEST, SEGMENTS, CARDS, s)
        assert len(r1.issues) == len(r2.issues)
        for a, b in zip(r1.issues, r2.issues):
            assert (a.code, a.entity_id, a.message) == (b.code, b.entity_id, b.message)
        assert r1.canonical_event_index == r2.canonical_event_index


# ===========================================================================
# D approved_platform enforcement
# ===========================================================================


@pytest.mark.unit
def test_d_missing_approved_platform_fails():
    _prov = _load(PROVENANCE)
    del _prov[1]["approved_platform"]
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"; _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_VERIFICATION_METADATA_INVALID" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_d_empty_approved_platform_fails():
    _prov = _load(PROVENANCE)
    _prov[1]["approved_platform"] = ""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"; _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed
        assert any("PROV_VERIFICATION_METADATA_INVALID" in (i.code or "") for i in report.issues)


# ===========================================================================
# JSONL total parsing (non-object rows)
# ===========================================================================


@pytest.mark.unit
def test_json_array_row_returns_schema_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write_text(bad, '["not", "an", "object"]\n')
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("SCHEMA_VALIDATION_ERROR" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_json_string_row_returns_schema_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write_text(bad, '"just a string"\n')
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("SCHEMA_VALIDATION_ERROR" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_json_number_row_returns_schema_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write_text(bad, '42\n')
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("SCHEMA_VALIDATION_ERROR" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_json_bool_row_returns_schema_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write_text(bad, 'true\n')
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("SCHEMA_VALIDATION_ERROR" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_json_null_row_returns_schema_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write_text(bad, 'null\n')
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("SCHEMA_VALIDATION_ERROR" in (i.code or "") for i in report.issues)


@pytest.mark.unit
def test_object_with_dict_id_returns_sanitized_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_id"] = {"nested": "evil"}
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        for i in report.issues:
            assert "nested" not in i.entity_id
            assert "evil" not in i.message


@pytest.mark.unit
def test_object_with_list_id_returns_sanitized_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_id"] = ["list", "id"]
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        for i in report.issues:
            assert "list" not in str(i.entity_id)
            assert "list" not in i.message


@pytest.mark.unit
def test_object_with_long_id_does_not_retain_raw():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_id"] = "x" * 500
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        for i in report.issues:
            assert len(i.entity_id) <= 300


@pytest.mark.unit
def test_invalid_json_syntax_returns_parse_error():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write_text(bad, 'this is not json {{{{{\n')
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any("JSON_PARSE_ERROR" in (i.code or "") for i in report.issues)


# ===========================================================================
# Duplicate-ID not authoritative (no last-record-wins)
# ===========================================================================


@pytest.mark.unit
def test_shuffled_duplicate_source_ids_identical():
    import random; rng = random.Random(42)
    rows = _load(MANIFEST)
    # Two entries with same source_id, different provenance_ids
    dup = dict(rows[0]); dup["provenance_id"] = "prov_other"; dup["source_url"] = "https://other.example.com"
    rows2 = list(rows) + [dup]
    shuffled = list(rows2); rng.shuffle(shuffled)
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "m_o.jsonl"; s = Path(td) / "m_s.jsonl"
        _write(o, rows2); _write(s, shuffled)
        r1 = validate_corpus(o, SEGMENTS, CARDS, PROVENANCE)
        r2 = validate_corpus(s, SEGMENTS, CARDS, PROVENANCE)
        assert len(r1.issues) == len(r2.issues)
        for a, b in zip(r1.issues, r2.issues):
            assert (a.code, a.entity_id, a.message) == (b.code, b.entity_id, b.message)


@pytest.mark.unit
def test_shuffled_duplicate_prov_ids_identical():
    import random; rng = random.Random(7)
    _prov = _load(PROVENANCE)
    dup = dict(_prov[0]); dup["provenance_id"] = _prov[0]["provenance_id"]
    dup["canonical_resource_url"] = "https://www.youtube.com/watch?v=abcdefghijk"
    rows = _prov + [dup]
    shuffled = list(rows); rng.shuffle(shuffled)
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "po.jsonl"; s = Path(td) / "ps.jsonl"
        _write(o, rows); _write(s, shuffled)
        r1 = validate_corpus(MANIFEST, SEGMENTS, CARDS, o)
        r2 = validate_corpus(MANIFEST, SEGMENTS, CARDS, s)
        assert len(r1.issues) == len(r2.issues)
        for a, b in zip(r1.issues, r2.issues):
            assert (a.code, a.entity_id, a.message) == (b.code, b.entity_id, b.message)


@pytest.mark.unit
def test_shuffled_duplicate_segment_ids_identical():
    import random; rng = random.Random(13)
    rows = _load(SEGMENTS)
    dup = dict(rows[0]); dup["text"] = "different content for duplicate"
    rows2 = list(rows) + [dup]
    shuffled = list(rows2); rng.shuffle(shuffled)
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "so.jsonl"; s = Path(td) / "ss.jsonl"
        _write(o, rows2); _write(s, shuffled)
        r1 = validate_corpus(MANIFEST, o, CARDS, PROVENANCE)
        r2 = validate_corpus(MANIFEST, s, CARDS, PROVENANCE)
        assert len(r1.issues) == len(r2.issues)
        for a, b in zip(r1.issues, r2.issues):
            assert (a.code, a.entity_id, a.message) == (b.code, b.entity_id, b.message)


@pytest.mark.unit
def test_shuffled_duplicate_card_ids_identical():
    import random; rng = random.Random(21)
    rows = _load(CARDS)
    dup = dict(rows[0]); dup["text"] = "different card content"
    rows2 = list(rows) + [dup]
    shuffled = list(rows2); rng.shuffle(shuffled)
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "co.jsonl"; s = Path(td) / "cs.jsonl"
        _write(o, rows2); _write(s, shuffled)
        r1 = validate_corpus(MANIFEST, SEGMENTS, o, PROVENANCE)
        r2 = validate_corpus(MANIFEST, SEGMENTS, s, PROVENANCE)
        assert len(r1.issues) == len(r2.issues)
        for a, b in zip(r1.issues, r2.issues):
            assert (a.code, a.entity_id, a.message) == (b.code, b.entity_id, b.message)


# ===========================================================================
# Sanitized URL/ID in issues
# ===========================================================================


@pytest.mark.unit
def test_hostile_long_url_absent_from_report():
    long_url = "https://youtube.com/watch?v=" + "x" * 500
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"; p = Path(td) / "p.jsonl"
        rows = _load(MANIFEST); rows[0]["source_url"] = long_url
        _write(m, rows); _write(p, _load(PROVENANCE))
        report = validate_corpus(m, SEGMENTS, CARDS, p)
        raw = json.dumps([i.model_dump() for i in report.issues])
        assert "x" * 400 not in raw


@pytest.mark.unit
def test_malformed_canonical_id_absent_from_report():
    _prov = _load(PROVENANCE)
    _prov[0]["canonical_resource_id"] = "MALFORMED" * 50
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"; _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        raw = json.dumps([i.model_dump() for i in report.issues])
        assert "MALFORMED" not in raw


# ===========================================================================
# Access marker coverage
# ===========================================================================


@pytest.mark.unit
def test_logged_in_marker_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST); rows[0]["title"] = "logged-in content"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_bypass_marker_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST); rows[0]["title"] = "bypass paywall"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed


@pytest.mark.unit
def test_subscriber_only_marker_fails():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST); rows[0]["title"] = "subscriber-only content"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed


# ===========================================================================
# Canonical event determinism
# ===========================================================================


@pytest.mark.unit
def test_two_sources_share_canonical_event():
    """Two source records share one canonical_event_id — coverage=1, both in index."""
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.jsonl"
        rows = _load(MANIFEST)
        # Add a second source with same canonical_event_id
        rows.append({
            "source_id": "src_extra_b", "provenance_id": "prov_stockbee_yt_range_expansion",
            "source_group": "B_official_youtube",
            "title": "Stockbee Bonus Video",
            "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "platform": "youtube", "speaker": "Pradeep Bonde",
            "primary_speaker": None, "channel_handle": "@stockbeevideos",
            "channel_url": "https://www.youtube.com/@stockbeevideos",
            "public_or_paid": "public", "ingestion_method": "manual_caption_export",
            "transcript_status": "auto_generated",
            "retrieved_at": "2026-07-16T10:00:00Z",
            "confidence": "medium", "topic_tags": [], "canonical_event_id": "evt_range_expansion_2024",
            "source_type": None,
        })
        _write(m, rows)
        report = validate_corpus(m, SEGMENTS, CARDS, PROVENANCE)
        assert report.coverage_counts.get("evt_range_expansion_2024") == 1
        assert len(report.canonical_event_index.get("evt_range_expansion_2024", [])) == 2


# ===========================================================================
# evidence_digest coverage
# ===========================================================================


@pytest.mark.unit
def test_leading_whitespace_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = " sha256:" + "0" * 64
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"; _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_trailing_whitespace_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:" + "0" * 64 + " "
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"; _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_extra_suffix_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:" + "0" * 64 + ":extra"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"; _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed


@pytest.mark.unit
def test_embedded_newline_digest_fails():
    _prov = _load(PROVENANCE)
    _prov[0]["evidence_digest"] = "sha256:\n" + "0" * 64
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prov.jsonl"; _write(p, _prov)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, p)
        assert not report.passed



# ===========================================================================
# Remaining Phase 10D adversarial coverage
# ===========================================================================


@pytest.mark.unit
def test_malformed_short_source_id_is_redacted_from_serialized_report():
    raw_id = "source-id!"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_id"] = raw_id
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        serialized = json.dumps(report.model_dump(), sort_keys=True)
        assert raw_id not in serialized
        assert "<unknown>" in serialized


@pytest.mark.unit
def test_129_character_source_id_is_redacted_from_serialized_report():
    raw_id = "s" * 129
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["source_id"] = raw_id
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert raw_id not in json.dumps(report.model_dump(), sort_keys=True)


@pytest.mark.unit
def test_129_character_provenance_id_is_redacted_from_serialized_report():
    raw_id = "p" * 129
    rows = _load(PROVENANCE)
    rows[0]["provenance_id"] = raw_id
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "provenance.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, bad)
        assert raw_id not in json.dumps(report.model_dump(), sort_keys=True)


@pytest.mark.unit
def test_valid_160_character_segment_id_is_retained_when_another_field_fails():
    valid_id = "s" * 160
    rows = _load(SEGMENTS)
    rows[0]["segment_id"] = valid_id
    rows[0]["source_id"] = "missing_source"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        assert valid_id in json.dumps(report.model_dump(), sort_keys=True)


@pytest.mark.unit
def test_valid_160_character_card_id_is_retained_when_another_field_fails():
    valid_id = "c" * 160
    rows = _load(CARDS)
    rows[0]["card_id"] = valid_id
    rows[0]["source_id"] = "missing_source"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert valid_id in json.dumps(report.model_dump(), sort_keys=True)


@pytest.mark.unit
def test_161_character_segment_id_is_redacted_from_serialized_report():
    raw_id = "s" * 161
    rows = _load(SEGMENTS)
    rows[0]["segment_id"] = raw_id
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        assert raw_id not in json.dumps(report.model_dump(), sort_keys=True)


@pytest.mark.unit
def test_161_character_card_id_is_redacted_from_serialized_report():
    raw_id = "c" * 161
    rows = _load(CARDS)
    rows[0]["card_id"] = raw_id
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert raw_id not in json.dumps(report.model_dump(), sort_keys=True)


@pytest.mark.unit
def test_scalar_source_id_is_redacted_from_serialized_report():
    raw_id = 987654321
    rows = _load(MANIFEST)
    rows[0]["source_id"] = raw_id
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert str(raw_id) not in json.dumps(report.model_dump(), sort_keys=True)


@pytest.mark.unit
def test_hostile_missing_file_path_is_absent_from_serialized_report():
    hostile_path = Path("/private/tmp/phase10d-" + "q" * 500)
    report = validate_corpus(hostile_path, SEGMENTS, CARDS, PROVENANCE)
    serialized = json.dumps(report.model_dump(), sort_keys=True)
    assert str(hostile_path) not in serialized
    assert any(issue.message == "input file not found" for issue in report.issues)


@pytest.mark.unit
def test_passing_validation_does_not_mutate_input_files():
    paths = [MANIFEST, SEGMENTS, CARDS, PROVENANCE]
    before = {path: path.read_bytes() for path in paths}
    report = validate_corpus(MANIFEST, SEGMENTS, CARDS, PROVENANCE)
    after = {path: path.read_bytes() for path in paths}
    assert report.passed
    assert before == after


@pytest.mark.unit
def test_failing_validation_does_not_mutate_input_files():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        rows = _load(MANIFEST)
        rows[0]["public_or_paid"] = "paid"
        _write(bad, rows)
        paths = [bad, SEGMENTS, CARDS, PROVENANCE]
        before = {path: path.read_bytes() for path in paths}
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        after = {path: path.read_bytes() for path in paths}
        assert not report.passed
        assert before == after


@pytest.mark.unit
def test_b_entry_with_approved_source_type_fails():
    rows = _load(PROVENANCE)
    rows[0]["approved_source_type"] = "podcast"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "provenance.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, bad)
        assert not report.passed
        assert any(issue.code == "SOURCE_TYPE_MISMATCH" for issue in report.issues)


@pytest.mark.unit
def test_b_entry_with_approved_primary_speaker_fails():
    rows = _load(PROVENANCE)
    rows[0]["approved_primary_speaker"] = "Pradeep Bonde"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "provenance.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, bad)
        assert not report.passed
        assert any(issue.code == "SPEAKER_MISMATCH" for issue in report.issues)


@pytest.mark.unit
def test_card_superseded_by_self_link_fails():
    rows = _load(CARDS)
    rows[0]["superseded_by"] = [rows[0]["card_id"]]
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not report.passed
        assert any(
            issue.entity_id == rows[0]["card_id"]
            and issue.field == "superseded_by"
            for issue in report.issues
        )


@pytest.mark.unit
def test_card_superseded_by_valid_target_passes():
    rows = _load(CARDS)
    rows[0]["superseded_by"] = ["card_volume_confirmation"]
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "cards.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, bad, PROVENANCE)
        assert not any(
            issue.entity_id == rows[0]["card_id"]
            and issue.field == "superseded_by"
            for issue in report.issues
        )


@pytest.mark.unit
def test_uppercase_approved_youtube_hostname_passes():
    source_url = "https://WWW.YOUTUBE.COM/watch?v=dQw4w9WgXcQ"
    manifest_rows = _load(MANIFEST)
    card_rows = _load(CARDS)
    manifest_rows[0]["source_url"] = source_url
    for card in card_rows:
        if card["source_id"] == "stockbee_yt_range_expansion":
            card["source_url"] = source_url
    with tempfile.TemporaryDirectory() as td:
        manifest_path = Path(td) / "manifest.jsonl"
        cards_path = Path(td) / "cards.jsonl"
        _write(manifest_path, manifest_rows)
        _write(cards_path, card_rows)
        report = validate_corpus(manifest_path, SEGMENTS, cards_path, PROVENANCE)
        assert report.passed, [issue.message for issue in report.issues]


@pytest.mark.unit
def test_percent_encoded_youtube_path_fails():
    rows = _load(MANIFEST)
    rows[0]["source_url"] = "https://www.youtube.com/%77atch?v=dQw4w9WgXcQ"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any(issue.code == "UNSUPPORTED_RESOURCE_URL" for issue in report.issues)


@pytest.mark.unit
def test_duplicate_identical_youtube_v_parameter_fails():
    rows = _load(MANIFEST)
    rows[0]["source_url"] = (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=dQw4w9WgXcQ"
    )
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any(issue.code == "MALFORMED_CANONICAL_ID" for issue in report.issues)


@pytest.mark.unit
def test_provenance_canonical_url_with_userinfo_fails():
    rows = _load(PROVENANCE)
    rows[0]["canonical_resource_url"] = (
        "https://user@www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "provenance.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, bad)
        assert not report.passed
        assert any(issue.code == "UNSUPPORTED_RESOURCE_URL" for issue in report.issues)


@pytest.mark.unit
def test_source_provenance_video_identity_cross_combination_fails():
    rows = _load(MANIFEST)
    rows[0]["source_url"] = "https://www.youtube.com/watch?v=abcdefghijk"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any(issue.code == "RESOURCE_ID_MISMATCH" for issue in report.issues)


@pytest.mark.unit
def test_verified_d_provenance_with_mismatching_source_url_fails():
    rows = _load(MANIFEST)
    rows[1]["source_url"] = "https://podcast-fake.example.com/episodes/other"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert not report.passed
        assert any(issue.code == "RESOURCE_URL_MISMATCH" for issue in report.issues)


@pytest.mark.unit
def test_duplicate_source_conflicting_event_is_fully_deterministic():
    rows = _load(MANIFEST)
    duplicate = dict(rows[0])
    duplicate["canonical_event_id"] = "evt_conflicting_duplicate"
    forward = rows + [duplicate]
    reversed_rows = list(reversed(forward))
    with tempfile.TemporaryDirectory() as td:
        forward_path = Path(td) / "forward.jsonl"
        reverse_path = Path(td) / "reverse.jsonl"
        _write(forward_path, forward)
        _write(reverse_path, reversed_rows)
        forward_report = validate_corpus(forward_path, SEGMENTS, CARDS, PROVENANCE)
        reverse_report = validate_corpus(reverse_path, SEGMENTS, CARDS, PROVENANCE)
        assert forward_report.model_dump() == reverse_report.model_dump()
        assert forward_report.canonical_event_index == reverse_report.canonical_event_index
        assert forward_report.coverage_counts == reverse_report.coverage_counts
        assert all(
            "stockbee_yt_range_expansion" not in source_ids
            for source_ids in forward_report.canonical_event_index.values()
        )
        assert not any(
            issue.field == "canonical_event_id"
            and issue.entity_type in {"segment", "card"}
            for issue in forward_report.issues
        )
        assert any(
            issue.field == "source_id"
            and issue.entity_type in {"segment", "card"}
            for issue in forward_report.issues
        )


@pytest.mark.unit
def test_duplicate_provenance_conflicting_payload_is_fully_deterministic():
    rows = _load(PROVENANCE)
    duplicate = dict(rows[0])
    duplicate["canonical_resource_url"] = (
        "https://www.youtube.com/watch?v=abcdefghijk"
    )
    forward = rows + [duplicate]
    reversed_rows = list(reversed(forward))
    with tempfile.TemporaryDirectory() as td:
        forward_path = Path(td) / "forward.jsonl"
        reverse_path = Path(td) / "reverse.jsonl"
        _write(forward_path, forward)
        _write(reverse_path, reversed_rows)
        forward_report = validate_corpus(MANIFEST, SEGMENTS, CARDS, forward_path)
        reverse_report = validate_corpus(MANIFEST, SEGMENTS, CARDS, reverse_path)
        assert forward_report.model_dump() == reverse_report.model_dump()
        assert forward_report.canonical_event_index == reverse_report.canonical_event_index
        assert forward_report.coverage_counts == reverse_report.coverage_counts


@pytest.mark.unit
def test_duplicate_segment_conflicting_payload_is_fully_deterministic():
    rows = _load(SEGMENTS)
    duplicate = dict(rows[0])
    duplicate["text"] = "different content for duplicate"
    forward = rows + [duplicate]
    reversed_rows = list(reversed(forward))
    with tempfile.TemporaryDirectory() as td:
        forward_path = Path(td) / "forward.jsonl"
        reverse_path = Path(td) / "reverse.jsonl"
        _write(forward_path, forward)
        _write(reverse_path, reversed_rows)
        forward_report = validate_corpus(MANIFEST, forward_path, CARDS, PROVENANCE)
        reverse_report = validate_corpus(MANIFEST, reverse_path, CARDS, PROVENANCE)
        assert forward_report.model_dump() == reverse_report.model_dump()
        assert forward_report.canonical_event_index == reverse_report.canonical_event_index
        assert forward_report.coverage_counts == reverse_report.coverage_counts


@pytest.mark.unit
def test_duplicate_card_conflicting_payload_is_fully_deterministic():
    rows = _load(CARDS)
    duplicate = dict(rows[0])
    duplicate["text"] = "different card content"
    forward = rows + [duplicate]
    reversed_rows = list(reversed(forward))
    with tempfile.TemporaryDirectory() as td:
        forward_path = Path(td) / "forward.jsonl"
        reverse_path = Path(td) / "reverse.jsonl"
        _write(forward_path, forward)
        _write(reverse_path, reversed_rows)
        forward_report = validate_corpus(MANIFEST, SEGMENTS, forward_path, PROVENANCE)
        reverse_report = validate_corpus(MANIFEST, SEGMENTS, reverse_path, PROVENANCE)
        assert forward_report.model_dump() == reverse_report.model_dump()
        assert forward_report.canonical_event_index == reverse_report.canonical_event_index
        assert forward_report.coverage_counts == reverse_report.coverage_counts


@pytest.mark.unit
def test_two_unambiguous_sources_share_event_deterministically():
    rows = _load(MANIFEST)
    rows.append({
        "source_id": "src_extra_b",
        "provenance_id": "prov_stockbee_yt_range_expansion",
        "source_group": "B_official_youtube",
        "title": "Stockbee Bonus Video",
        "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "source_type": None,
        "platform": "youtube",
        "speaker": "Pradeep Bonde",
        "primary_speaker": None,
        "channel_handle": "@stockbeevideos",
        "channel_url": "https://www.youtube.com/@stockbeevideos",
        "public_or_paid": "public",
        "ingestion_method": "manual_caption_export",
        "transcript_status": "auto_generated",
        "retrieved_at": "2026-07-16T10:00:00Z",
        "confidence": "medium",
        "topic_tags": [],
        "canonical_event_id": "evt_range_expansion_2024",
    })
    reversed_rows = list(reversed(rows))
    with tempfile.TemporaryDirectory() as td:
        forward_path = Path(td) / "forward.jsonl"
        reverse_path = Path(td) / "reverse.jsonl"
        _write(forward_path, rows)
        _write(reverse_path, reversed_rows)
        forward_report = validate_corpus(forward_path, SEGMENTS, CARDS, PROVENANCE)
        reverse_report = validate_corpus(reverse_path, SEGMENTS, CARDS, PROVENANCE)
        assert forward_report.model_dump() == reverse_report.model_dump()
        assert forward_report.canonical_event_index["evt_range_expansion_2024"] == [
            "src_extra_b",
            "stockbee_yt_range_expansion",
        ]
        assert forward_report.coverage_counts["evt_range_expansion_2024"] == 1

# ===========================================================================
# SegmentEntry source-ID retention-cap sanitization
# ===========================================================================


@pytest.mark.unit
def test_valid_128_character_source_id_is_retained_for_schema_error():
    valid_id = "s" * 128
    rows = _load(MANIFEST)
    rows[0]["source_id"] = valid_id
    rows[0]["source_url"] = None
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "manifest.jsonl"
        _write(bad, rows)
        report = validate_corpus(bad, SEGMENTS, CARDS, PROVENANCE)
        assert any(
            issue.code == "SCHEMA_VALIDATION_ERROR"
            and issue.entity_type == "manifest"
            and issue.entity_id == valid_id
            for issue in report.issues
        )


@pytest.mark.unit
def test_valid_128_character_provenance_id_is_retained_for_schema_error():
    valid_id = "p" * 128
    rows = _load(PROVENANCE)
    rows[0]["provenance_id"] = valid_id
    rows[0]["canonical_resource_url"] = None
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "provenance.jsonl"
        _write(bad, rows)
        report = validate_corpus(MANIFEST, SEGMENTS, CARDS, bad)
        assert any(
            issue.code == "SCHEMA_VALIDATION_ERROR"
            and issue.entity_type == "provenance"
            and issue.entity_id == valid_id
            for issue in report.issues
        )


@pytest.mark.unit
def test_malformed_segment_source_id_is_redacted_before_retention_aggregation():
    raw_id = "bad source!"
    valid_segment_id = "seg_invalid_source_short"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        rows = _load(SEGMENTS)
        rows[0]["segment_id"] = valid_segment_id
        rows[0]["source_id"] = raw_id
        rows[0]["text"] = "word " * 120
        for i in range(10):
            rows.append({
                "segment_id": f"seg_retention_valid_{i}",
                "source_id": "stockbee_yt_range_expansion",
                "canonical_event_id": "evt_range_expansion_2024",
                "start_ts": "00:00",
                "end_ts": "00:10",
                "source_group": "B_official_youtube",
                "speaker": "Pradeep Bonde",
                "caption_type": "auto",
                "text": "word " * 120,
                "topic_tags": [],
                "confidence": "medium",
            })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        serialized = json.dumps(report.model_dump(), sort_keys=True)
        assert not report.passed
        assert raw_id not in serialized
        assert any(
            issue.code == "SCHEMA_VALIDATION_ERROR"
            and issue.entity_type == "segment"
            and issue.entity_id == valid_segment_id
            for issue in report.issues
        )
        assert any(
            issue.entity_type == "segment"
            and issue.field == "text"
            and issue.message == "source retained text exceeds cap"
            and issue.entity_id == "stockbee_yt_range_expansion"
            for issue in report.issues
        )


@pytest.mark.unit
def test_overlimit_segment_source_id_is_redacted_before_retention_aggregation():
    raw_id = "s" * 129
    valid_segment_id = "seg_invalid_source_129"
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "segments.jsonl"
        rows = _load(SEGMENTS)
        rows[0]["segment_id"] = valid_segment_id
        rows[0]["source_id"] = raw_id
        rows[0]["text"] = "word " * 120
        for i in range(10):
            rows.append({
                "segment_id": f"seg_retention_overlimit_{i}",
                "source_id": "stockbee_yt_range_expansion",
                "canonical_event_id": "evt_range_expansion_2024",
                "start_ts": "00:00",
                "end_ts": "00:10",
                "source_group": "B_official_youtube",
                "speaker": "Pradeep Bonde",
                "caption_type": "auto",
                "text": "word " * 120,
                "topic_tags": [],
                "confidence": "medium",
            })
        _write(bad, rows)
        report = validate_corpus(MANIFEST, bad, CARDS, PROVENANCE)
        serialized = json.dumps(report.model_dump(), sort_keys=True)
        assert not report.passed
        assert raw_id not in serialized
        assert any(
            issue.code == "SCHEMA_VALIDATION_ERROR"
            and issue.entity_type == "segment"
            and issue.entity_id == valid_segment_id
            for issue in report.issues
        )
        assert any(
            issue.entity_type == "segment"
            and issue.field == "text"
            and issue.message == "source retained text exceeds cap"
            and issue.entity_id == "stockbee_yt_range_expansion"
            for issue in report.issues
        )


# ===========================================================================
# Helpers
# ===========================================================================


def _load(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line: rows.append(json.loads(line))
    return rows


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
