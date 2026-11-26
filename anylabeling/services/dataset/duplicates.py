"""Exact image duplicate detection (fork.62).

Identity is the SHA-256 of the file bytes: two files with the same digest are
byte-for-byte identical, so files copied under another name are detected while
data-augmentation derivatives (rotation, mirror, crop, re-encode) stay distinct
on purpose.  Perceptual hashes are intentionally not implemented yet.

The module is pure Python (no Qt, no SQL) and is shared by:

* dataset merge (``services/dataset/merge.py``);
* importing a folder that has no database yet (``services/dataset/importer.py``).

"Same annotation" is a canonical fingerprint of the shapes and tags only:
object ids/uuids, scores, editor, timestamps, split, description, flags and
relations are excluded, so the comparison reflects what the annotator drew, not
how the file was produced.  Relations are deliberately excluded from the
fingerprint in v1: merging relation graphs needs endpoint remapping that is
out of scope for exact-duplicate classification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_SIZE = 1024 * 1024

ACTION_KEEP_BOTH = "keep_both"
ACTION_KEEP_ONE = "keep_one"
ACTION_MERGE_ANNOTATIONS = "merge_annotations"

ACTION_LABELS = {
    ACTION_KEEP_BOTH: "Keep both",
    ACTION_KEEP_ONE: "Keep one",
    ACTION_MERGE_ANNOTATIONS: "Merge annotations",
}


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of one file, streaming in 1 MiB chunks."""

    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _points(value) -> list:
    points = []
    for point in value or ():
        try:
            points.append([round(float(point[0]), 6), round(float(point[1]), 6)])
        except (TypeError, ValueError, IndexError):
            points.append(list(point))
    return points


def annotation_hash(shapes, tags) -> str:
    """Canonical fingerprint of the drawn content (shapes + tags only)."""

    normalized = []
    for shape in shapes or ():
        normalized.append(
            {
                "label": str(shape.get("label", "")),
                "shape_type": str(shape.get("shape_type", "")),
                "points": _points(shape.get("points")),
                "attributes": shape.get("attributes") or {},
                "flags": shape.get("flags") or {},
                "difficult": bool(shape.get("difficult", False)),
                "direction": shape.get("direction"),
                "group_id": shape.get("group_id"),
            }
        )
    normalized.sort(key=_canonical)
    payload = {
        "shapes": normalized,
        "tags": sorted(str(tag) for tag in tags or ()),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def entry_key(db_path: str | Path, image_id: int) -> str:
    return f"{str(db_path)}:{int(image_id)}"


@dataclass(frozen=True)
class DuplicateEntry:
    """One image that participates in a duplicate group."""

    key: str
    source: str
    path: str
    sha256: str
    annotation_hash: str
    object_count: int = 0
    tag_count: int = 0
    image_id: int | None = None
    annotation: object = None


@dataclass
class DuplicateGroup:
    sha256: str
    entries: list = field(default_factory=list)

    @property
    def object_counts(self) -> list:
        return [entry.object_count for entry in self.entries]

    @property
    def same_annotation(self) -> bool:
        return len({entry.annotation_hash for entry in self.entries}) == 1

    def action_options(self) -> list:
        if self.same_annotation:
            return [ACTION_KEEP_BOTH, ACTION_KEEP_ONE]
        return [ACTION_KEEP_BOTH, ACTION_MERGE_ANNOTATIONS]


def group_duplicates(entries) -> list:
    """Group entries by digest; groups with one entry are dropped."""

    by_sha: dict[str, list] = {}
    for entry in entries:
        by_sha.setdefault(entry.sha256, []).append(entry)
    groups = [
        DuplicateGroup(sha, items)
        for sha, items in by_sha.items()
        if len(items) > 1
    ]
    groups.sort(key=lambda group: (-len(group.entries), group.sha256))
    return groups


def actions_from_choices(groups, choices) -> dict:
    """Turn ``{sha: action}`` into ``{entry key: action}`` for duplicates.

    The first entry of each group is always kept; only the remaining entries
    receive an action.  ``keep_both`` produces no actions (current behavior).
    """

    decisions = {}
    for group in groups:
        action = (choices or {}).get(group.sha256, ACTION_KEEP_BOTH)
        if action not in group.action_options():
            action = ACTION_KEEP_BOTH
        if action == ACTION_KEEP_BOTH:
            continue
        for entry in group.entries[1:]:
            decisions[entry.key] = action
    return decisions
