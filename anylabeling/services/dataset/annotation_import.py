"""Store converted annotation payloads in a dataset database (fork.49).

The "Upload" menu converts an external annotation format into the XLABEL
payload.  In database mode the dataset tables are authoritative, so the
payload has to be written through :class:`DatasetRepository`; writing a JSON
sidecar there leaves the file table and the canvas unchanged.

This adapter is Qt-free so the merge/write rules can be tested without a
window.
"""

from __future__ import annotations

import os
import os.path as osp
from dataclasses import dataclass, field

from .codec import ImageAnnotation

OUTCOME_WRITTEN = "written"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"


@dataclass
class AnnotationImportResult:
    """Per-image outcome of a batch upload."""

    #: ``(image_path, object_count)`` for every image that was written.
    written: list = field(default_factory=list)
    #: Image paths that are not registered in the dataset.
    skipped: list = field(default_factory=list)
    #: ``(image_path, reason)`` for images that could not be written.
    failed: list = field(default_factory=list)

    @property
    def written_count(self) -> int:
        return len(self.written)

    @property
    def object_count(self) -> int:
        return sum(count for _path, count in self.written)


def relative_to_root(image_path, dataset_root) -> str:
    """Return ``image_path`` as a forward-slash path relative to the root.

    Raises ``ValueError`` when the image is outside the dataset root; the
    caller reports it per file instead of writing to a foreign path.
    """

    root = os.path.abspath(str(dataset_root))
    path = os.path.abspath(str(image_path))
    relative = osp.relpath(path, root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        raise ValueError("file is outside the dataset root")
    return relative.replace(os.sep, "/")


def _plain_points(shapes):
    """Copy shapes so the payload never leaks numpy scalars into SQLite."""

    result = []
    for shape in shapes or ():
        item = dict(shape)
        points = item.get("points")
        if isinstance(points, (list, tuple)):
            item["points"] = [
                [float(point[0]), float(point[1])]
                if isinstance(point, (list, tuple)) and len(point) >= 2
                else point
                for point in points
            ]
        result.append(item)
    return result


def build_annotation(payload, existing=None):
    """Merge a converted payload with the stored annotation.

    ``preserve_existing`` is expressed by passing the stored
    :class:`ImageAnnotation`; its objects/flags/tags/relations are kept and
    the payload shapes are appended.  Without it the payload replaces the
    annotation.
    """

    payload = payload or {}
    shapes = list(existing.shapes) if existing is not None else []
    shapes.extend(_plain_points(payload.get("shapes")))
    return ImageAnnotation(
        shapes=shapes,
        flags=dict(existing.flags) if existing is not None else dict(
            payload.get("flags") or {}
        ),
        tags=list(existing.tags) if existing is not None else [],
        description=(
            existing.description
            if existing is not None
            else str(payload.get("description") or "")
        ),
        split=(
            existing.split
            if existing is not None
            else payload.get("split")
        ),
        relations=list(existing.relations) if existing is not None else [],
        extra=dict(existing.extra) if existing is not None else {},
    )


def store_annotation(
    repository,
    dataset_root,
    image_path,
    payload,
    *,
    preserve_existing=False,
):
    """Write one converted payload into the dataset.

    Returns ``(outcome, object_count, reason)`` where ``outcome`` is one of
    :data:`OUTCOME_WRITTEN`, :data:`OUTCOME_SKIPPED` or
    :data:`OUTCOME_FAILED`.
    """

    try:
        relative = relative_to_root(image_path, dataset_root)
    except ValueError as exc:
        return OUTCOME_FAILED, 0, str(exc)
    image = repository.find_image(relative)
    if image is None:
        return OUTCOME_SKIPPED, 0, "image is not registered in the dataset"
    try:
        existing = (
            repository.load_annotation(image["id"])
            if preserve_existing
            else None
        )
        annotation = build_annotation(payload, existing)
        repository.save_annotation(image["id"], annotation)
    except Exception as exc:  # noqa: BLE001 - reported per file by the caller
        return OUTCOME_FAILED, 0, str(exc)
    return OUTCOME_WRITTEN, len(annotation.shapes), ""


def store_annotations(
    repository,
    dataset_root,
    items,
    *,
    preserve_existing=False,
):
    """Store an iterable of ``(image_path, payload)`` pairs.

    Failures never abort the batch: each image reports its own outcome so the
    operator sees exactly which files were accepted.
    """

    result = AnnotationImportResult()
    for image_path, payload in items or ():
        outcome, count, reason = store_annotation(
            repository,
            dataset_root,
            image_path,
            payload,
            preserve_existing=preserve_existing,
        )
        if outcome == OUTCOME_WRITTEN:
            result.written.append((str(image_path), count))
        elif outcome == OUTCOME_SKIPPED:
            result.skipped.append(str(image_path))
        else:
            result.failed.append((str(image_path), reason))
    return result
