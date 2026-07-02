"""Atomic / append-only writers for a run's on-disk artifacts (Phase 0B).

Pure I/O layer: takes already-validated ``run_contract`` model instances and
writes them to disk. Never constructs those models from raw dicts or
markdown -- that's ``tradingagents.legacy_importer``'s job for historical
reports, and a future Phase 1A builder's job for live runs.

``analysis_manifest.json`` and ``status.json`` are written via a temp file
plus ``Path.replace()`` (the same idiom already used in
``tradingagents.agents.utils.memory``), so a reader never observes a
half-written file. ``events.jsonl`` is append-only.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePath

from tradingagents.run_contract import (
    ANALYSIS_MANIFEST_FILENAME,
    EVENTS_FILENAME,
    STATUS_FILENAME,
    AnalysisManifest,
    RunEvent,
    RunStatus,
)


class ArtifactPathError(ValueError):
    """Raised when a filename would resolve outside its run directory."""


def resolve_artifact_path(run_dir: Path | str, filename: str) -> Path:
    """Resolve ``filename`` as a direct child of ``run_dir``; refuse if it would escape.

    Rejects (``ArtifactPathError``) an empty filename, an absolute filename,
    a filename containing a path separator, or a filename of ``"."``/``".."``.
    Also rejects a filename that, once resolved against ``run_dir``, lands
    outside it (e.g. a symlink inside ``run_dir`` pointing elsewhere).
    Neither ``run_dir`` nor the target file need to exist; no directory is
    created.
    """
    if not filename or filename in (".", ".."):
        raise ArtifactPathError(f"invalid artifact filename: {filename!r}")
    if PurePath(filename).is_absolute():
        raise ArtifactPathError(f"artifact filename must be relative: {filename!r}")
    if "/" in filename or "\\" in filename:
        raise ArtifactPathError(f"artifact filename must not contain a path separator: {filename!r}")

    base = Path(run_dir).resolve()
    candidate = (base / filename).resolve()
    if not candidate.is_relative_to(base):
        raise ArtifactPathError(
            f"{filename!r} resolves outside run_dir {run_dir!r}"
        )
    return candidate


def _atomic_write_json_text(target: Path, text: str, *, overwrite: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} already exists (pass overwrite=True to replace it)")

    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    try:
        tmp_path.replace(target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_analysis_manifest(
    run_dir: Path | str, manifest: AnalysisManifest, *, overwrite: bool = False
) -> Path:
    """Atomically write ``analysis_manifest.json`` under ``run_dir``.

    Default ``overwrite=False``: the manifest is sealed once analysis
    completes, so a second call raises ``FileExistsError`` and leaves the
    existing file untouched, unless the caller explicitly opts in.
    """
    target = resolve_artifact_path(run_dir, ANALYSIS_MANIFEST_FILENAME)
    text = manifest.model_dump_json()
    _atomic_write_json_text(target, text, overwrite=overwrite)
    return target


def write_run_status(run_dir: Path | str, status: RunStatus, *, overwrite: bool = True) -> Path:
    """Atomically write ``status.json`` under ``run_dir``.

    Default ``overwrite=True``: ``status.json`` is a mutable view meant to
    be updated repeatedly over a run's lifecycle, so the common case (agent
    N completes, write again) must not require passing ``overwrite=True``
    every time. Pass ``overwrite=False`` to opt into a one-shot guard.
    """
    target = resolve_artifact_path(run_dir, STATUS_FILENAME)
    text = status.model_dump_json()
    _atomic_write_json_text(target, text, overwrite=overwrite)
    return target


def append_run_event(run_dir: Path | str, event: RunEvent) -> Path:
    """Append one JSON line for ``event`` to ``events.jsonl`` under ``run_dir``.

    Creates ``run_dir`` and ``events.jsonl`` if missing. Each call opens the
    file in append mode and writes exactly one line -- prior lines are never
    rewritten. This is append-mode durability, not transactional atomicity:
    a hard crash mid-write could still leave a truncated final line, so
    readers of ``events.jsonl`` should tolerate and skip an unparsable
    trailing line.
    """
    target = resolve_artifact_path(run_dir, EVENTS_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.model_dump(mode="json"))
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return target
