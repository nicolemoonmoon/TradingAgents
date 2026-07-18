"""Phase 10D: B+D corpus data models."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceGroup(str, Enum):
    B_OFFICIAL_YOUTUBE = "B_official_youtube"
    D_INTERVIEW_PRIMARY_VOICE = "D_interview_primary_voice"


class SourceType(str, Enum):
    INTERVIEW = "interview"
    PODCAST = "podcast"
    CONFERENCE = "conference"
    CONFERENCE_TALK = "conference_talk"
    PRIMARY_VOICE_RECORDING = "primary_voice_recording"


class ResourceKind(str, Enum):
    YOUTUBE_VIDEO = "youtube_video"
    D_RESOURCE = "d_resource"


class ProvenanceStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    REVOKED = "revoked"


_PROHIBITED_ACCESS_MARKERS: frozenset[str] = frozenset({
    "paid", "member", "members-only", "members only",
    "logged-in", "logged in", "login required", "login-required",
    "private", "bypass", "paywall", "subscriber-only", "subscriber only",
})

_B_APPROVED_HOSTS: frozenset[str] = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
})

_B_CHANNEL_HANDLE: str = "@stockbeevideos"
_B_CHANNEL_URL: str = "https://www.youtube.com/@stockbeevideos"
_D_PRIMARY_SPEAKER: str = "Pradeep Bonde"

_GENERIC_DOMAIN_MARKERS: frozenset[str] = frozenset({
    "blog", "blogspot", "medium.com", "substack", "wordpress",
    "news", "article", "seo", "summary", "summar", "digest",
    "aggregat", "scrape", "repost",
})

_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_ENTITY_ID_PATTERN = r"^[a-z0-9_-]+$"
ENTITY_ID_RE = re.compile(_ENTITY_ID_PATTERN)
ENTITY_ID_MAX_LENGTHS: dict[str, int] = {
    "manifest": 128,
    "provenance": 128,
    "segment": 160,
    "card": 160,
}


class Confidence(str, Enum): HIGH = "high"; MEDIUM = "medium"; LOW = "low"
class CaptionType(str, Enum): AUTO = "auto"; MANUAL = "manual"; NONE = "none"
class ExtractionType(str, Enum):
    DIRECT_QUOTE = "direct_quote"; FAITHFUL_PARAPHRASE = "faithful_paraphrase"; ANALYST_INFERENCE = "analyst_inference"
class CardKind(str, Enum): CURATED = "curated"; CONTRADICTION = "contradiction"
class Category(str, Enum):
    SETUP = "setup"; PROCESS = "process"; RISK = "risk"; PSYCHOLOGY = "psychology"
    MARKET_CONTEXT = "market_context"; CATALYST_NARRATIVE_MOMENTUM = "catalyst_narrative_momentum"

MAX_SEGMENT_WORDS = 120; MAX_DIRECT_QUOTE_WORDS = 25; MAX_SOURCE_RETAINED_WORDS = 1200


class ValidationCode:
    PROV_MISSING = "PROV_MISSING"
    PROV_NOT_VERIFIED = "PROV_NOT_VERIFIED"
    PROV_VERIFICATION_METADATA_INVALID = "PROV_VERIFICATION_METADATA_INVALID"
    PROV_DUPLICATE_ID = "PROV_DUPLICATE_ID"
    PROV_DUPLICATE_BINDING = "PROV_DUPLICATE_BINDING"
    PROV_SUPERSESSION_DANGLING = "PROV_SUPERSESSION_DANGLING"
    PROV_SUPERSESSION_SELF = "PROV_SUPERSESSION_SELF"
    RESOURCE_ID_MISMATCH = "RESOURCE_ID_MISMATCH"
    RESOURCE_URL_MISMATCH = "RESOURCE_URL_MISMATCH"
    CHANNEL_HANDLE_MISMATCH = "CHANNEL_HANDLE_MISMATCH"
    CHANNEL_URL_MISMATCH = "CHANNEL_URL_MISMATCH"
    SOURCE_TYPE_MISMATCH = "SOURCE_TYPE_MISMATCH"
    PLATFORM_MISMATCH = "PLATFORM_MISMATCH"
    SPEAKER_MISMATCH = "SPEAKER_MISMATCH"
    CARD_URL_MISMATCH = "CARD_URL_MISMATCH"
    HOST_NOT_APPROVED = "HOST_NOT_APPROVED"
    MALFORMED_CANONICAL_ID = "MALFORMED_CANONICAL_ID"
    UNSUPPORTED_RESOURCE_URL = "UNSUPPORTED_RESOURCE_URL"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    JSON_PARSE_ERROR = "JSON_PARSE_ERROR"


class _ForbidExtra(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProvenanceManifestEntry(_ForbidExtra):
    provenance_id: str = Field(..., min_length=1, max_length=128, pattern=_ENTITY_ID_PATTERN)
    resource_kind: ResourceKind
    canonical_resource_id: str = Field(..., min_length=1)
    canonical_resource_url: str = Field(..., min_length=1)
    status: ProvenanceStatus
    approved_channel_handle: str | None = None
    approved_channel_url: str | None = None
    approved_source_type: SourceType | None = None
    approved_primary_speaker: str | None = None
    approved_platform: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    verification_method: str | None = None
    evidence_digest: str | None = None
    superseded_by_provenance_id: str | None = None
    notes: str | None = None

    @field_validator("evidence_digest")
    @classmethod
    def _check_digest(cls, v: str | None) -> str | None:
        if v is not None and not _DIGEST_RE.fullmatch(v):
            raise ValueError("evidence_digest must be sha256:<64 lowercase hex>")
        return v


class SourceManifestEntry(_ForbidExtra):
    source_id: str = Field(..., min_length=1, max_length=128, pattern=_ENTITY_ID_PATTERN)
    provenance_id: str = Field(..., min_length=1)
    source_group: SourceGroup
    title: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=1)
    source_type: SourceType | None = None
    platform: str = Field(default="youtube")
    speaker: str = Field(default="Pradeep Bonde / Stockbee")
    primary_speaker: str | None = None
    channel_handle: str | None = None
    channel_url: str | None = None
    public_or_paid: Literal["public"] = "public"
    ingestion_method: str = Field(default="manual_caption_export")
    transcript_status: Literal["auto_generated", "manual", "unavailable"] = "auto_generated"
    retrieved_at: str = Field(..., min_length=10)
    confidence: Confidence = Confidence.MEDIUM
    topic_tags: list[str] = Field(default_factory=list)
    canonical_event_id: str | None = None


class SegmentEntry(_ForbidExtra):
    segment_id: str = Field(..., min_length=1, max_length=160, pattern=_ENTITY_ID_PATTERN)
    source_id: str = Field(..., min_length=1, max_length=128, pattern=_ENTITY_ID_PATTERN)
    canonical_event_id: str | None = None
    start_ts: str = Field(default=""); end_ts: str = Field(default="")
    source_group: SourceGroup | None = None
    speaker: str | None = None
    caption_type: CaptionType = CaptionType.AUTO
    text: str = Field(..., min_length=1)
    topic_tags: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM


class CuratedCard(_ForbidExtra):
    card_id: str = Field(..., min_length=1, max_length=160, pattern=_ENTITY_ID_PATTERN)
    card_kind: CardKind = CardKind.CURATED
    category: Category; subtopic: str = Field(..., min_length=1, max_length=120)
    extraction_type: ExtractionType
    text: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=1)
    canonical_event_id: str | None = None
    timestamp: str | None = None
    supporting_segment_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM
    temporal_context: str | None = None
    contradicts: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)
    profile_tags: list[str] = Field(default_factory=list)
    grounding_eligible: bool = False

    @field_validator("profile_tags")
    @classmethod
    def _tags_lowercase(cls, v: list[str]) -> list[str]:
        return [t.lower() for t in v]


class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    entity_type: str
    entity_id: str
    code: str | None = None
    field: str | None = None
    message: str


class CorpusValidationReport(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    canonical_event_index: dict[str, list[str]] = Field(default_factory=dict)
    coverage_counts: dict[str, int] = Field(default_factory=dict)
