# Phase 10D: B+D Corpus Contract with Provenance Subsystem

**Status:** Local-only schema + validator + provenance. No network, no runtime.

## Overview

Phase 10D implements the B+D corpus pipeline with a separately governed
local provenance approval snapshot. Only `verified` entries are corpus-eligible.
Pending, rejected, and revoked entries fail closed. The validator does not
prove live platform ownership, channel membership, or speaker identity.

## Schema

### ProvenanceManifestEntry

- `extra="forbid"` — unknown fields rejected
- `provenance_id`: required, immutable, unique
- `resource_kind`: `youtube_video` or `d_resource`
- `canonical_resource_id`: B: parsed YT video ID; D: reviewer-assigned
- `canonical_resource_url`: one concrete resource URL; for B, parsed by strict YouTube parser and must derive the same video ID as `canonical_resource_id`
- `status`: verified / pending / rejected / revoked
- B required: `approved_channel_handle` (exactly `@stockbeevideos`), `approved_channel_url` (exactly `https://www.youtube.com/@stockbeevideos`)
- B forbidden: `approved_source_type`, `approved_primary_speaker`, `approved_platform`
- D required: `approved_source_type`, `approved_primary_speaker` (exactly `Pradeep Bonde`), `approved_platform` (non-empty and exactly equal to the linked source platform)
- D forbidden: `approved_channel_handle`, `approved_channel_url`
- Verified governance: `verified_by`, `verified_at`, `verification_method`, `evidence_digest` all required
- `evidence_digest`: exact `sha256:<64 lowercase hex>` — uses `re.fullmatch()`

### SourceManifestEntry / SegmentEntry / CuratedCard

- All use `extra="forbid"` — unknown fields rejected
- `provenance_id` is required on SourceManifestEntry (FK → provenance)
- Persisted-ID bounds: SourceManifestEntry.source_id, SegmentEntry.source_id, and ProvenanceManifestEntry.provenance_id use `^[a-z0-9_-]+$` with a 128-character maximum; SegmentEntry.segment_id and CuratedCard.card_id use the same charset with a 160-character maximum
- SegmentEntry.source_id inherits the referenced source-ID policy, not SegmentEntry.segment_id's independent 160-character policy
- `CuratedCard.source_url` must equal SourceManifestEntry.source_url (CARD_URL_MISMATCH)

## Validation Rules

### provenance_path REQUIRED
- Fourth argument to `validate_corpus()` is required (no default)
- Omission fails at the API boundary with `TypeError`

### Strict YouTube parser
- HTTPS only
- Exact host membership: `youtube.com`, `www.youtube.com`, `m.youtube.com`, `youtu.be`
- No explicit ports (rejects even :443)
- No userinfo
- `/watch?v=VIDEO_ID`: exactly one non-empty `v` parameter (duplicate/missing/empty `v` fails)
- `youtu.be/VIDEO_ID`: exactly one non-empty path segment
- Video ID: 11 chars, alphanumeric + `_` `-`
- Uses `parse_qsl(keep_blank_values=True)` for raw query inspection

### B canonical_resource_url binding
- Provenance `canonical_resource_url` is parsed by the same strict YouTube parser
- Derived video ID must equal `canonical_resource_id`
- Source URL is also parsed; derived video ID must match provenance

### Deterministic diagnostics
- All duplicate detection and complete validation reports are input-order independent
- Duplicate IDs are ambiguous and excluded from authoritative source, provenance, segment, and card maps
- Canonical-event indexes use only unambiguous source entries
- Canonical-event mismatch checks run only when a linked source is unambiguous
- Missing or ambiguous source references are reported by referential-integrity diagnostics
- There is no first-record-wins, last-record-wins, or input-position authority
- `PROV_DUPLICATE_ID` emitted for duplicate provenance IDs
- `PROV_DUPLICATE_BINDING` emitted for duplicate resource/URL bindings
- Issue sort key: severity → record_type → entity_id → code → field → message

### Sanitized errors
- Schema errors use `SCHEMA_VALIDATION_ERROR` with a fixed message
- Malformed JSON uses `JSON_PARSE_ERROR` with a fixed message
- Non-object JSON rows fail safely as `SCHEMA_VALIDATION_ERROR` with entity ID `<unknown>`
- Retained entity IDs are type-aware: manifest/source and provenance IDs are at most 128 characters; segment and card IDs are at most 160 characters
- IDs with an invalid charset, invalid type, or excess length become `<unknown>`; malformed values are never truncated or repaired
- No raw rejected URLs, IDs, paths, query strings, fragments, Pydantic exception text, parser exception text, or traceback is retained in issues
- A valid SegmentEntry.segment_id remains the schema-error entity ID when its source_id is rejected; the rejected source_id is absent from the complete serialized report
- Source retention-cap diagnostics use the fixed message `source retained text exceeds cap` and the existing type-aware safe-ID policy for their entity ID; no raw source ID or word count is interpolated into the message
- URL parse errors mapped to stable codes

### Validation codes
PROV_MISSING, PROV_NOT_VERIFIED, PROV_VERIFICATION_METADATA_INVALID,
PROV_DUPLICATE_ID, PROV_DUPLICATE_BINDING, PROV_SUPERSESSION_DANGLING,
PROV_SUPERSESSION_SELF, RESOURCE_ID_MISMATCH, RESOURCE_URL_MISMATCH,
CHANNEL_HANDLE_MISMATCH, CHANNEL_URL_MISMATCH, SOURCE_TYPE_MISMATCH,
PLATFORM_MISMATCH, SPEAKER_MISMATCH, CARD_URL_MISMATCH,
HOST_NOT_APPROVED, MALFORMED_CANONICAL_ID, UNSUPPORTED_RESOURCE_URL,
SCHEMA_VALIDATION_ERROR, JSON_PARSE_ERROR

## Fixture inventory

- `synthetic_manifest.jsonl`: 2 sources
- `synthetic_segments.jsonl`: 5 segments
- `synthetic_cards.jsonl`: 8 curated cards
- `synthetic_provenance_manifest.jsonl`: 2 local provenance records

The fixtures are synthetic and are not evidence of remote platform verification.

### Limitations
- No remote ownership verification
- No live channel membership / speaker verification
- No signature/cryptographic tamper protection
- Local provenance is a governed repository snapshot, not remote truth
- Human approval and repository governance remain required
- Synthetic fixtures are test-only (verified_by: test_fixture_owner)
- Runtime retrieval, providers, graph integration, API/UI changes, and vector storage remain out of scope

## Tests

Expected post-application count: `tests/test_bd_corpus_validator.py` — 150 tests.

Run: `python3 -m pytest tests/test_bd_corpus_validator.py -q`

Generated `tools/bd_corpus/__pycache__/` and `tests/__pycache__/` artifacts must not be committed. Cache cleanup requires separate authorization.
