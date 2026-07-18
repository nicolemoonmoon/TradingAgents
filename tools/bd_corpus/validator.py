"""Phase 10D: B+D corpus validator with provenance subsystem."""

from __future__ import annotations

import json, re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qsl

from tools.bd_corpus.models import (
    MAX_DIRECT_QUOTE_WORDS, MAX_SEGMENT_WORDS, MAX_SOURCE_RETAINED_WORDS,
    ENTITY_ID_MAX_LENGTHS, ENTITY_ID_RE,
    _B_APPROVED_HOSTS, _B_CHANNEL_HANDLE, _B_CHANNEL_URL,
    _D_PRIMARY_SPEAKER,
    _GENERIC_DOMAIN_MARKERS, _PROHIBITED_ACCESS_MARKERS, _VIDEO_ID_RE,
    CaptionType, CardKind, Category, Confidence,
    CorpusValidationReport, CuratedCard, ExtractionType,
    ProvenanceManifestEntry, ProvenanceStatus,
    ResourceKind, SegmentEntry, SourceGroup, SourceManifestEntry, SourceType,
    ValidationCode, ValidationIssue,
)

_MB_PROFILE = "stockbee_momentum_burst"
_EP_PROFILE = "stockbee_episodic_pivot"
_PRADEEP_V1 = "pradeep_v1"
_STOCKBEE_PROFILES = {_MB_PROFILE, _EP_PROFILE}
_VALID_SOURCE_GROUPS = {SourceGroup.B_OFFICIAL_YOUTUBE, SourceGroup.D_INTERVIEW_PRIMARY_VOICE}
_SORT_ORDER = {"error": 0, "warning": 1}
_RECORD_ORDER = {"provenance": -1, "manifest": 0, "segment": 1, "card": 2}
_SCHEMA_MSG = "Record failed schema validation."

def _word_count(text: str) -> int: return len(text.split())

def _issue(level, entity_type, entity_id, code, field, message):
    return ValidationIssue(level=level, entity_type=entity_type, entity_id=str(entity_id),
                           code=code, field=field, message=message)

def _safe_entity_id(value: object, entity_type: str) -> str:
    """Return a valid persisted ID for the record type or '<unknown>'."""
    max_length = ENTITY_ID_MAX_LENGTHS.get(entity_type)
    if (
        max_length is None
        or not isinstance(value, str)
        or not value
        or len(value) > max_length
        or not ENTITY_ID_RE.fullmatch(value)
    ):
        return "<unknown>"
    return value

def _is_mapping(obj) -> bool:
    return isinstance(obj, dict)

# ===========================================================================
# Strict YouTube parser
# ===========================================================================

def _strict_parse_youtube(url: str) -> tuple[str | None, str | None]:
    try: parsed = urlparse(url)
    except ValueError: return None, ValidationCode.UNSUPPORTED_RESOURCE_URL
    except Exception: return None, ValidationCode.MALFORMED_CANONICAL_ID
    if parsed.scheme != "https":
        return None, ValidationCode.UNSUPPORTED_RESOURCE_URL
    if parsed.username or parsed.password:
        return None, ValidationCode.UNSUPPORTED_RESOURCE_URL
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _B_APPROVED_HOSTS:
        return None, ValidationCode.HOST_NOT_APPROVED
    try: port = parsed.port
    except ValueError: return None, ValidationCode.UNSUPPORTED_RESOURCE_URL
    if port is not None: return None, ValidationCode.UNSUPPORTED_RESOURCE_URL
    path = parsed.path.rstrip("/")
    if host != "youtu.be" and path == "/watch":
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        v_pairs = [(k, v) for k, v in pairs if k == "v"]
        if len(v_pairs) != 1: return None, ValidationCode.MALFORMED_CANONICAL_ID
        vid = v_pairs[0][1]
        if not vid or not _VIDEO_ID_RE.fullmatch(vid):
            return None, ValidationCode.MALFORMED_CANONICAL_ID
        return vid, None
    if host == "youtu.be":
        segs = [s for s in path.split("/") if s]
        if len(segs) != 1: return None, ValidationCode.UNSUPPORTED_RESOURCE_URL
        vid = segs[0]
        if not _VIDEO_ID_RE.fullmatch(vid): return None, ValidationCode.MALFORMED_CANONICAL_ID
        return vid, None
    return None, ValidationCode.UNSUPPORTED_RESOURCE_URL

def _normalize_resource_url(url: str) -> str:
    try:
        p = urlparse(url)
        from urllib.parse import urlunparse
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, p.params, p.query, ""))
    except Exception: return url

# ===========================================================================
# Provenance validation
# ===========================================================================

def _validate_provenance_entry(entry, issues):
    eid = entry.provenance_id; et = "provenance"
    if entry.status == ProvenanceStatus.VERIFIED:
        for fname in ("verified_by", "verified_at", "verification_method", "evidence_digest"):
            if not getattr(entry, fname):
                issues.append(_issue("error", et, eid, ValidationCode.PROV_VERIFICATION_METADATA_INVALID, fname, f"verified entry requires non-empty {fname}"))
    if entry.resource_kind == ResourceKind.YOUTUBE_VIDEO:
        if not entry.approved_channel_handle:
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_HANDLE_MISMATCH, "approved_channel_handle", "B requires approved_channel_handle"))
        elif entry.approved_channel_handle != _B_CHANNEL_HANDLE:
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_HANDLE_MISMATCH, "approved_channel_handle", "B channel handle does not match approved value"))
        if not entry.approved_channel_url:
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_URL_MISMATCH, "approved_channel_url", "B requires approved_channel_url"))
        elif _normalize_resource_url(entry.approved_channel_url) != _B_CHANNEL_URL:
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_URL_MISMATCH, "approved_channel_url", "B channel URL does not match approved value"))
        pvid, perr = _strict_parse_youtube(entry.canonical_resource_url)
        if perr:
            issues.append(_issue("error", et, eid, perr, "canonical_resource_url", "Cannot parse provenance canonical resource URL."))
        elif pvid != entry.canonical_resource_id:
            issues.append(_issue("error", et, eid, ValidationCode.RESOURCE_ID_MISMATCH, "canonical_resource_url", "Canonical resource identity does not match the approved binding."))
        if entry.approved_source_type is not None:
            issues.append(_issue("error", et, eid, ValidationCode.SOURCE_TYPE_MISMATCH, "approved_source_type", "B must not set approved_source_type"))
        if entry.approved_primary_speaker is not None:
            issues.append(_issue("error", et, eid, ValidationCode.SPEAKER_MISMATCH, "approved_primary_speaker", "B must not set approved_primary_speaker"))
        if entry.approved_platform is not None:
            issues.append(_issue("error", et, eid, ValidationCode.PLATFORM_MISMATCH, "approved_platform", "B must not set approved_platform"))
    if entry.resource_kind == ResourceKind.D_RESOURCE:
        if not entry.approved_source_type:
            issues.append(_issue("error", et, eid, ValidationCode.SOURCE_TYPE_MISMATCH, "approved_source_type", "D requires approved_source_type"))
        if not entry.approved_primary_speaker:
            issues.append(_issue("error", et, eid, ValidationCode.SPEAKER_MISMATCH, "approved_primary_speaker", "D requires approved_primary_speaker"))
        elif entry.approved_primary_speaker != _D_PRIMARY_SPEAKER:
            issues.append(_issue("error", et, eid, ValidationCode.SPEAKER_MISMATCH, "approved_primary_speaker", "D primary speaker does not match approved value"))
        if not entry.approved_platform or not entry.approved_platform.strip():
            issues.append(_issue("error", et, eid, ValidationCode.PROV_VERIFICATION_METADATA_INVALID, "approved_platform", "D requires non-empty approved_platform"))
        if entry.approved_channel_handle is not None:
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_HANDLE_MISMATCH, "approved_channel_handle", "D must not set approved_channel_handle"))
        if entry.approved_channel_url is not None:
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_URL_MISMATCH, "approved_channel_url", "D must not set approved_channel_url"))
    if entry.superseded_by_provenance_id == eid:
        issues.append(_issue("error", et, eid, ValidationCode.PROV_SUPERSESSION_SELF, "superseded_by_provenance_id", "provenance entry cannot supersede itself"))

def _validate_source_provenance_binding(m, prov, all_prov_ids, issues):
    eid, et = m.source_id, "manifest"
    if m.provenance_id not in all_prov_ids:
        issues.append(_issue("error", et, eid, ValidationCode.PROV_MISSING, "provenance_id", "provenance_id not found"))
        return
    if prov is None: return
    if prov.status != ProvenanceStatus.VERIFIED:
        issues.append(_issue("error", et, eid, ValidationCode.PROV_NOT_VERIFIED, "provenance_id", "provenance entry is not verified"))
        return
    expected_kind = {SourceGroup.B_OFFICIAL_YOUTUBE: ResourceKind.YOUTUBE_VIDEO, SourceGroup.D_INTERVIEW_PRIMARY_VOICE: ResourceKind.D_RESOURCE}.get(m.source_group)
    if expected_kind and prov.resource_kind != expected_kind:
        issues.append(_issue("error", et, eid, ValidationCode.RESOURCE_ID_MISMATCH, "source_group", "source_group does not match provenance resource_kind"))
    if m.source_group == SourceGroup.B_OFFICIAL_YOUTUBE:
        vid, err = _strict_parse_youtube(m.source_url)
        if err:
            issues.append(_issue("error", et, eid, err, "source_url", "Source URL host is not approved."))
        elif vid != prov.canonical_resource_id:
            issues.append(_issue("error", et, eid, ValidationCode.RESOURCE_ID_MISMATCH, "source_url", "Canonical resource identity does not match the approved binding."))
        if m.channel_handle and m.channel_handle != prov.approved_channel_handle:
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_HANDLE_MISMATCH, "channel_handle", "Channel handle does not match approved provenance."))
        if m.channel_url and _normalize_resource_url(m.channel_url) != _normalize_resource_url(prov.approved_channel_url or ""):
            issues.append(_issue("error", et, eid, ValidationCode.CHANNEL_URL_MISMATCH, "channel_url", "Channel URL does not match approved provenance."))
    if m.source_group == SourceGroup.D_INTERVIEW_PRIMARY_VOICE:
        if _normalize_resource_url(m.source_url) != _normalize_resource_url(prov.canonical_resource_url):
            issues.append(_issue("error", et, eid, ValidationCode.RESOURCE_URL_MISMATCH, "source_url", "Source URL does not match provenance canonical resource URL."))
        if m.source_type != prov.approved_source_type:
            issues.append(_issue("error", et, eid, ValidationCode.SOURCE_TYPE_MISMATCH, "source_type", "Source type does not match approved provenance."))
        if (m.primary_speaker or "").strip() != (prov.approved_primary_speaker or ""):
            issues.append(_issue("error", et, eid, ValidationCode.SPEAKER_MISMATCH, "primary_speaker", "Primary speaker does not match approved provenance."))
        if prov.approved_platform is not None and m.platform != prov.approved_platform:
            issues.append(_issue("error", et, eid, ValidationCode.PLATFORM_MISMATCH, "platform", "Source platform does not match approved provenance."))

def _validate_card_source_url_binding(card, manifest_by_id, issues):
    source = manifest_by_id.get(card.source_id)
    if source and card.source_url != source.source_url:
        issues.append(_issue("error", "card", card.card_id, ValidationCode.CARD_URL_MISMATCH, "source_url", "Card source URL does not match manifest."))

# ===========================================================================
# Entry point
# ===========================================================================

def validate_corpus(manifest_path, segments_path, cards_path, provenance_path) -> CorpusValidationReport:
    issues: list[ValidationIssue] = []
    manifest = _load_jsonl(manifest_path, "manifest", issues)
    segments = _load_jsonl(segments_path, "segment", issues)
    cards = _load_jsonl(cards_path, "card", issues)
    prov_raw = _load_jsonl(provenance_path, "provenance", issues)

    parsed_manifest, manifest_by_id, _amb_m = _parse_manifest(manifest, issues)
    parsed_segments, segment_by_id, _amb_s = _parse_segments(segments, issues)
    parsed_cards, card_by_id, _amb_c = _parse_cards(cards, issues)
    parsed_prov, prov_by_id, _amb_p = _parse_provenance(prov_raw, issues)

    if not parsed_manifest or not parsed_segments or not parsed_cards:
        return _finalize(issues, {})

    _check_uniqueness(parsed_manifest, "source_id", "manifest", issues)
    _check_uniqueness(parsed_segments, "segment_id", "segment", issues)
    _check_uniqueness(parsed_cards, "card_id", "card", issues)
    _check_uniqueness(parsed_prov, "provenance_id", "provenance", issues)
    _check_provenance_binding_uniqueness(parsed_prov, issues)

    for p in parsed_prov:
        _validate_provenance_entry(p, issues)

    all_pids = set(prov_by_id)
    for p in parsed_prov:
        t = p.superseded_by_provenance_id
        if t and t not in all_pids:
            issues.append(_issue("error", "provenance", p.provenance_id, ValidationCode.PROV_SUPERSESSION_DANGLING, "superseded_by_provenance_id", "superseded_by target not found"))

    _check_referential_integrity(parsed_segments, manifest_by_id, "source_id", "segment", issues)
    _check_referential_integrity(parsed_cards, manifest_by_id, "source_id", "card", issues)
    segment_ids = set(segment_by_id)
    for card in parsed_cards:
        for seg_id in card.supporting_segment_ids:
            if seg_id not in segment_ids:
                issues.append(_issue("error", "card", card.card_id, None, "supporting_segment_ids", "supporting segment not found"))

    for m in parsed_manifest:
        if m.source_group not in _VALID_SOURCE_GROUPS:
            issues.append(_issue("error", "manifest", m.source_id, None, "source_group", "source_group not allowed"))
        if _is_generic_domain(m.source_url):
            issues.append(_issue("error", "manifest", m.source_id, None, "source_url", "generic domain rejected"))

    for m in parsed_manifest:
        _validate_source_provenance_binding(m, prov_by_id.get(m.provenance_id), all_pids, issues)

    for m in parsed_manifest:
        markers = _contains_prohibited_marker(m.title) + _contains_prohibited_marker(m.source_url) + _contains_prohibited_marker(m.ingestion_method)
        if markers:
            issues.append(_issue("error", "manifest", m.source_id, None, "public_or_paid", "prohibited access markers detected"))

    event_index: dict[str, list[str]] = defaultdict(list)
    for source_id in sorted(manifest_by_id):
        ref = manifest_by_id[source_id]
        if ref.canonical_event_id:
            event_index[ref.canonical_event_id].append(source_id)

    for seg in parsed_segments:
        ref = manifest_by_id.get(seg.source_id)
        if (
            seg.canonical_event_id
            and ref is not None
            and seg.canonical_event_id != ref.canonical_event_id
        ):
            issues.append(_issue("error", "segment", seg.segment_id, None, "canonical_event_id", "canonical_event_id mismatch"))
    for card in parsed_cards:
        ref = manifest_by_id.get(card.source_id)
        if (
            card.canonical_event_id
            and ref is not None
            and card.canonical_event_id != ref.canonical_event_id
        ):
            issues.append(_issue("error", "card", card.card_id, None, "canonical_event_id", "canonical_event_id mismatch"))

    all_card_ids = set(card_by_id)
    for card in parsed_cards:
        for t in card.contradicts:
            if t == card.card_id: issues.append(_issue("error", "card", card.card_id, None, "contradicts", "self-link"))
            elif t not in all_card_ids: issues.append(_issue("error", "card", card.card_id, None, "contradicts", "dangling link"))
        if card.card_kind == CardKind.CONTRADICTION and not [t for t in card.contradicts if t != card.card_id and t in all_card_ids]:
            issues.append(_issue("error", "card", card.card_id, None, "contradicts", "contradiction-designated card requires valid target"))
        for t in card.superseded_by:
            if t == card.card_id: issues.append(_issue("error", "card", card.card_id, None, "superseded_by", "self-link"))
            elif t not in all_card_ids: issues.append(_issue("error", "card", card.card_id, None, "superseded_by", "dangling link"))

    for card in parsed_cards:
        _validate_card_source_url_binding(card, manifest_by_id, issues)
    for card in parsed_cards:
        _validate_card(card, segment_by_id, manifest_by_id, issues)
    _check_retention_caps(parsed_segments, parsed_cards, issues)
    return _finalize(issues, event_index)

# ===========================================================================
# Helpers
# ===========================================================================

def _url_host(url):
    try: return (urlparse(url).hostname or "").lower()
    except Exception: return ""

def _is_generic_domain(url): return any(m in _url_host(url) for m in _GENERIC_DOMAIN_MARKERS)

def _contains_prohibited_marker(text):
    lower = text.lower()
    return [m for m in _PROHIBITED_ACCESS_MARKERS if m in lower]

def _check_provenance_binding_uniqueness(entries, issues):
    by_kind_id = defaultdict(list); by_url = defaultdict(list)
    for p in entries:
        by_kind_id[(p.resource_kind.value, p.canonical_resource_id)].append(p.provenance_id)
        by_url[_normalize_resource_url(p.canonical_resource_url)].append(p.provenance_id)
    for key, pids in sorted(by_kind_id.items()):
        if len(pids) > 1:
            for pid in sorted(pids):
                issues.append(_issue("error", "provenance", pid, ValidationCode.PROV_DUPLICATE_BINDING, "canonical_resource_id", "duplicate binding"))
    for key, pids in sorted(by_url.items()):
        if len(pids) > 1:
            for pid in sorted(pids):
                issues.append(_issue("error", "provenance", pid, ValidationCode.PROV_DUPLICATE_BINDING, "canonical_resource_url", "duplicate URL binding"))

def _load_jsonl(path, entity_type, issues):
    p = Path(path)
    if not p.is_file():
        issues.append(_issue("error", entity_type, "<file>", None, None, "input file not found"))
        return []
    rows = []
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line: continue
        try: obj = json.loads(line)
        except json.JSONDecodeError:
            issues.append(_issue("error", entity_type, "<line>", ValidationCode.JSON_PARSE_ERROR, None, "invalid JSON"))
            continue
        if not _is_mapping(obj):
            issues.append(_issue("error", entity_type, "<unknown>", ValidationCode.SCHEMA_VALIDATION_ERROR, None, _SCHEMA_MSG))
            continue
        rows.append(obj)
    return rows

def _parse_with_ambiguous(raw, model_cls, id_field, entity_type, issues):
    """Parse rows. Returns (entries, by_id, ambiguous_id_set)."""
    entries = []; by_id = {}; id_counts = defaultdict(int)
    valid_rows = []
    for row in raw:
        try: e = model_cls(**row)
        except Exception:
            eid = _safe_entity_id(row.get(id_field), entity_type) if _is_mapping(row) else "<unknown>"
            issues.append(_issue("error", entity_type, eid, ValidationCode.SCHEMA_VALIDATION_ERROR, None, _SCHEMA_MSG))
            continue
        entries.append(e); valid_rows.append(e)
    for e in valid_rows:
        id_counts[getattr(e, id_field)] += 1
    ambiguous = {eid for eid, c in id_counts.items() if c > 1}
    for e in valid_rows:
        if getattr(e, id_field) not in ambiguous:
            by_id[getattr(e, id_field)] = e
    return entries, by_id, ambiguous

def _parse_manifest(raw, issues): return _parse_with_ambiguous(raw, SourceManifestEntry, "source_id", "manifest", issues)
def _parse_segments(raw, issues): return _parse_with_ambiguous(raw, SegmentEntry, "segment_id", "segment", issues)
def _parse_cards(raw, issues): return _parse_with_ambiguous(raw, CuratedCard, "card_id", "card", issues)
def _parse_provenance(raw, issues): return _parse_with_ambiguous(raw, ProvenanceManifestEntry, "provenance_id", "provenance", issues)

def _check_uniqueness(entries, id_field, entity_type, issues):
    groups = defaultdict(int)
    for e in entries: groups[getattr(e, id_field)] += 1
    for eid in sorted(groups):
        if groups[eid] > 1:
            issues.append(_issue("error", entity_type, eid, ValidationCode.PROV_DUPLICATE_ID if entity_type == "provenance" else None, None, f"duplicate {id_field}"))

def _check_referential_integrity(entries, ref_map, ref_field, entity_type, issues):
    for entry in entries:
        ref_val = getattr(entry, ref_field)
        if ref_val not in ref_map:
            issues.append(_issue("error", entity_type, getattr(entry, f"{entity_type}_id", ref_val), None, ref_field, f"{ref_field} not found"))

def _validate_card(card, segment_by_id, manifest_by_id, issues):
    try: ExtractionType(card.extraction_type)
    except ValueError:
        issues.append(_issue("error", "card", card.card_id, ValidationCode.SCHEMA_VALIDATION_ERROR, "extraction_type", "invalid extraction_type"))
    if card.grounding_eligible and not card.supporting_segment_ids:
        issues.append(_issue("error", "card", card.card_id, None, "supporting_segment_ids", "grounding-eligible card requires supporting segment"))
    if card.extraction_type == ExtractionType.DIRECT_QUOTE:
        source = manifest_by_id.get(card.source_id)
        if not (source and source.speaker): issues.append(_issue("error", "card", card.card_id, None, "speaker", "direct_quote requires speaker"))
        if not card.timestamp: issues.append(_issue("error", "card", card.card_id, None, "timestamp", "direct_quote requires timestamp"))
        if not card.source_url: issues.append(_issue("error", "card", card.card_id, None, "source_url", "direct_quote requires source_url"))
        if not card.supporting_segment_ids: issues.append(_issue("error", "card", card.card_id, None, "supporting_segment_ids", "direct_quote requires supporting segment"))
    tags = set(card.profile_tags)
    if tags and (_PRADEEP_V1 in tags) and (tags & _STOCKBEE_PROFILES):
        issues.append(_issue("error", "card", card.card_id, None, "profile_tags", "ambiguous profile tags"))

def _check_retention_caps(segments, cards, issues):
    for seg in segments:
        wc = _word_count(seg.text)
        if wc > MAX_SEGMENT_WORDS: issues.append(_issue("error", "segment", seg.segment_id, None, "text", f"segment {wc} words (cap: {MAX_SEGMENT_WORDS})"))
    for card in cards:
        if card.extraction_type == ExtractionType.DIRECT_QUOTE:
            wc = _word_count(card.text)
            if wc > MAX_DIRECT_QUOTE_WORDS: issues.append(_issue("error", "card", card.card_id, None, "text", f"direct_quote {wc} words (cap: {MAX_DIRECT_QUOTE_WORDS})"))
    source_words = defaultdict(int)
    for seg in segments: source_words[seg.source_id] += _word_count(seg.text)
    for sid, total in source_words.items():
        if total > MAX_SOURCE_RETAINED_WORDS:
            issues.append(_issue(
                "error",
                "segment",
                _safe_entity_id(sid, "manifest"),
                None,
                "text",
                "source retained text exceeds cap",
            ))

def _finalize(issues, event_index):
    issues.sort(key=_issue_sort_key)
    sorted_index = {eid: sorted(sids) for eid, sids in sorted(event_index.items())}
    return CorpusValidationReport(passed=not any(i.level == "error" for i in issues), issues=issues,
        canonical_event_index=sorted_index, coverage_counts={eid: 1 for eid in sorted_index})

def _issue_sort_key(issue):
    return (_SORT_ORDER.get(issue.level, 99), _RECORD_ORDER.get(issue.entity_type, 99),
            issue.entity_id, issue.code or "", issue.field or "", issue.message)
