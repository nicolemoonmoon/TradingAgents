from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

DEFAULT_KB_ROOT = Path.home() / "ResearchData" / "pradeep_stockbee"
MAX_GROUNDING_CHARS = 12_000

EXPECTED_KB_INVENTORY_SHA256 = (
    "e300b7c54e52b79dec0a7ce31e76f6e376bb18d08c25c93bf43272a6af067126"
)
EXPECTED_SIMPLE9_REOPEN_CONDITION_IDS = (
    "INCIDENTAL_PRIMARY_SOURCE_DISCOVERY",
    "AGENT_EVAL_MATERIAL_IMPACT",
)
EXPECTED_PERMANENT_DATA_EXCLUSIONS = (
    "Stockbee 50 daily dynamic data",
    "Market Monitor/MM daily dynamic data",
    "paid/login-gated materials",
)

SUPPORTED_PROFILES: dict[str, tuple[str, ...]] = {
    "stockbee_momentum_burst": (
        "wiki/setups/momentum_burst.md",
        "wiki/concepts/entry_mechanics.md",
        "wiki/concepts/risk_control.md",
        "wiki/process/swing_trading_process.md",
        "wiki/process/watchlist_building.md",
    ),
    "stockbee_episodic_pivot": (
        "wiki/setups/episodic_pivots.md",
        "wiki/setups/magna.md",
        "wiki/setups/ep_9_million.md",
        "wiki/concepts/anticipation.md",
        "wiki/concepts/risk_control.md",
        "wiki/concepts/setup_design.md",
        "wiki/process/watchlist_building.md",
    ),
}

_CLOSURE = "manifests/batch6_phase9_v1_closure.json"
_INVENTORY = "manifests/batch6_phase9_v1_inventory.json"
_URL_RE = re.compile(r"https://[^\s)\]>`\"']+")
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_FORBIDDEN_DYNAMIC_URL_MARKERS = ("/p/stockbee-50", "/p/mm")

class StockbeeKnowledgeError(RuntimeError):
    """Frozen Stockbee KB is unavailable or fails integrity checks."""

@dataclass(frozen=True)
class GroundingBundle:
    strategy_profile: str
    knowledge_inventory_sha256: str
    context_ids: tuple[str, ...]
    grounding_text: str
    source_urls: tuple[str, ...]


def _sha_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _regular_file_under_root(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise StockbeeKnowledgeError(f"unsafe KB path: {relative}")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise StockbeeKnowledgeError(f"symlink not allowed in KB path: {relative}")
    try:
        current.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise StockbeeKnowledgeError(f"KB path escapes root: {relative}") from exc
    if not current.is_file():
        raise StockbeeKnowledgeError(f"required KB file missing: {relative}")
    return current


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StockbeeKnowledgeError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise StockbeeKnowledgeError(f"invalid {label} object: {path}")
    return value


def _inventory_map(inventory: dict) -> dict[str, str]:
    rows = inventory.get("files")
    if not isinstance(rows, list):
        raise StockbeeKnowledgeError("inventory files list missing")
    if inventory.get("file_count") != len(rows):
        raise StockbeeKnowledgeError("inventory file_count mismatch")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise StockbeeKnowledgeError("invalid inventory row")
        rel = row.get("path")
        digest = row.get("sha256")
        if not isinstance(rel, str) or not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            raise StockbeeKnowledgeError("invalid inventory row fields")
        if rel in result:
            raise StockbeeKnowledgeError(f"duplicate inventory path: {rel}")
        result[rel] = str(digest)
    return result


def _read_inventory_bound_file(root: Path, rel: str, inv_map: dict[str, str]) -> str:
    expected = inv_map.get(rel)
    if expected is None:
        raise StockbeeKnowledgeError(f"KB file absent from frozen inventory: {rel}")
    path = _regular_file_under_root(root, rel)
    actual = _sha_file(path)
    if actual != expected:
        raise StockbeeKnowledgeError(f"KB file hash drift: {rel}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise StockbeeKnowledgeError(f"KB file unreadable: {rel}") from exc


def _normalize_source_note_link(page_rel: str, href: str) -> str | None:
    href = href.strip().split("#", 1)[0]
    if not href or "://" in href:
        return None
    joined = (Path(page_rel).parent / href)
    parts: list[str] = []
    for part in joined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    rel = "/".join(parts)
    if not rel.startswith("wiki/source_notes/") or not rel.endswith(".md"):
        return None
    return rel


def _extract_urls(texts: Iterable[str]) -> tuple[str, ...]:
    urls: set[str] = set()
    for text in texts:
        for raw in _URL_RE.findall(text):
            url = raw.rstrip(".,;:")
            if any(marker in url for marker in _FORBIDDEN_DYNAMIC_URL_MARKERS):
                continue
            urls.add(url)
    return tuple(sorted(urls))


def _clip_context(text: str, budget: int) -> str:
    """Preserve both the definition/front and later P1 enrichment deterministically."""
    clean = text.strip()
    if len(clean) <= budget:
        return clean
    marker = "\n...[CONTEXT CLIPPED]...\n"
    if budget <= len(marker) + 80:
        return clean[:budget]
    front = (budget - len(marker)) * 2 // 3
    back = budget - len(marker) - front
    return clean[:front].rstrip() + marker + clean[-back:].lstrip()


def _render_grounding(
    profile: str,
    inventory_sha: str,
    context_ids: tuple[str, ...],
    source_urls: tuple[str, ...],
    bodies: list[tuple[str, str]],
) -> str:
    header_lines = [
        "STOCKBEE FROZEN-KB GROUNDING",
        f"strategy_profile: {profile}",
        f"knowledge_inventory_sha256: {inventory_sha}",
        "simple_9_policy: unresolved source gap; do not synthesize or infer a setup definition",
        "context_ids:",
    ]
    header_lines.extend(f"- {rel}" for rel in context_ids)
    header_lines.append("source_urls:")
    header_lines.extend(f"- {url}" for url in source_urls)
    header_lines.extend([
        "",
        "Use the following Stockbee methodology as bounded strategy context. "
        "Treat current market/fundamental/news tools as the source of truth for "
        "live facts; this KB supplies methodology, not live market data.",
        "",
    ])
    header = "\n".join(header_lines)
    if len(header) >= MAX_GROUNDING_CHARS:
        raise StockbeeKnowledgeError("grounding metadata exceeds size limit")

    labels = [f"\n\n[CONTEXT: {rel}]\n" for rel, _ in bodies]
    body_budget = MAX_GROUNDING_CHARS - len(header) - sum(map(len, labels))
    if body_budget <= 0:
        raise StockbeeKnowledgeError("grounding context metadata leaves no body budget")

    count = len(bodies)
    base = body_budget // count
    remainder = body_budget % count
    sections: list[str] = []
    for idx, ((rel, text), label) in enumerate(zip(bodies, labels, strict=False)):
        budget = base + (1 if idx < remainder else 0)
        clipped = _clip_context(text, budget)
        if not clipped:
            raise StockbeeKnowledgeError(f"empty selected KB context: {rel}")
        sections.append(label + clipped)

    rendered = header + "".join(sections)
    if len(rendered) > MAX_GROUNDING_CHARS:
        raise StockbeeKnowledgeError("grounding renderer exceeded size limit")
    return rendered


def retrieve_stockbee_grounding(strategy_profile: str | None, kb_root: Path | None = None) -> GroundingBundle | None:
    if strategy_profile is None or strategy_profile not in SUPPORTED_PROFILES:
        return None
    root = Path(kb_root) if kb_root is not None else DEFAULT_KB_ROOT
    if root.is_symlink() or not root.is_dir():
        raise StockbeeKnowledgeError(f"Stockbee KB root unavailable: {root}")

    closure_path = _regular_file_under_root(root, _CLOSURE)
    inventory_path = _regular_file_under_root(root, _INVENTORY)
    closure = _load_json(closure_path, "closure manifest")
    if closure.get("batch_status") != "CLOSED" or closure.get("phase9_v1_status") != "COMPLETE_WITH_DECLARED_SOURCE_GAP":
        raise StockbeeKnowledgeError("Stockbee KB is not in the frozen Phase 9 v1 closed state")
    if closure.get("simple9_active_search_policy") != "STOP":
        raise StockbeeKnowledgeError("Simple 9 freeze policy drift")
    if tuple(closure.get("simple9_reopen_condition_ids") or ()) != EXPECTED_SIMPLE9_REOPEN_CONDITION_IDS:
        raise StockbeeKnowledgeError("Simple 9 reopen policy drift")
    if tuple(closure.get("permanent_data_exclusions") or ()) != EXPECTED_PERMANENT_DATA_EXCLUSIONS:
        raise StockbeeKnowledgeError("permanent data-exclusion policy drift")

    closure_inventory_sha = closure.get("inventory_sha256")
    if closure_inventory_sha != EXPECTED_KB_INVENTORY_SHA256:
        raise StockbeeKnowledgeError("closure inventory authority drift")
    if _sha_file(inventory_path) != EXPECTED_KB_INVENTORY_SHA256:
        raise StockbeeKnowledgeError("frozen KB inventory hash drift")

    inventory = _load_json(inventory_path, "inventory")
    inv_map = _inventory_map(inventory)
    if closure.get("inventory_file_count") != inventory.get("file_count"):
        raise StockbeeKnowledgeError("closure/inventory file_count mismatch")
    selected = SUPPORTED_PROFILES[strategy_profile]
    note_rels: set[str] = set()
    bodies: list[tuple[str, str]] = []
    url_texts: list[str] = []
    for rel in selected:
        text = _read_inventory_bound_file(root, rel, inv_map)
        bodies.append((rel, text))
        url_texts.append(text)
        for href in _MD_LINK_RE.findall(text):
            note_rel = _normalize_source_note_link(rel, href)
            if note_rel:
                note_rels.add(note_rel)

    for rel in sorted(note_rels):
        note_text = _read_inventory_bound_file(root, rel, inv_map)
        url_texts.append(note_text)

    source_urls = _extract_urls(url_texts)
    if not source_urls:
        raise StockbeeKnowledgeError("grounding source URLs missing")
    context_ids = tuple(selected)
    grounding_text = _render_grounding(
        strategy_profile,
        EXPECTED_KB_INVENTORY_SHA256,
        context_ids,
        source_urls,
        bodies,
    )
    return GroundingBundle(
        strategy_profile,
        EXPECTED_KB_INVENTORY_SHA256,
        context_ids,
        grounding_text,
        source_urls,
    )


def get_stockbee_grounding_text(strategy_profile: str | None, kb_root: Path | None = None) -> str | None:
    bundle = retrieve_stockbee_grounding(strategy_profile, kb_root=kb_root)
    return None if bundle is None else bundle.grounding_text
