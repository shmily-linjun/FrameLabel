"""Apply one image-tag list to several images (fork.32).

The file-list context menu lets the user tag a batch of images with the same
values.  This module owns the merge rule and the two write paths:

* database mode goes through :class:`DatasetRepository`, so tags land in
  ``image_tag`` and the image row is stamped with the operator;
* JSON mode updates the annotation file in place (or creates a minimal one)
  and stamps ``author``/``modified_at``.

It is Qt-free on purpose so the merge and write rules can be tested without a
window.
"""

from dataclasses import dataclass, field
import os
import os.path as osp

from .file_meta import read_file_meta, write_tags
from .image_tags import normalize_image_tags


@dataclass
class BatchTagsResult:
    """Per-image outcome of :func:`apply_image_tags`."""

    #: Paths whose tags changed and were written.
    updated: list = field(default_factory=list)
    #: Paths that already had exactly the target tags.
    unchanged: list = field(default_factory=list)
    #: Paths that could not be read or written.
    failed: list = field(default_factory=list)
    #: Final tags per written/unchanged path, used to refresh the open image.
    tags_by_path: dict = field(default_factory=dict)

    @property
    def changed(self) -> int:
        return len(self.updated)


def merge_image_tags(existing, tags, replace):
    """Return the tag list an image should end up with.

    ``replace`` sets exactly ``tags``; otherwise the incoming tags are appended
    to the existing ones without duplicates.  Input order is preserved.
    """
    incoming = normalize_image_tags(
        list(tags) if isinstance(tags, (list, tuple)) else []
    )
    if replace:
        return incoming
    merged = normalize_image_tags(
        list(existing) if isinstance(existing, (list, tuple)) else []
    )
    for tag in incoming:
        if tag not in merged:
            merged.append(tag)
    return merged


def apply_image_tags(
    paths,
    tags,
    *,
    replace,
    repository=None,
    dataset_root=None,
    output_dir=None,
    author=None,
    modified_at=None,
):
    """Apply ``tags`` to every image in ``paths`` and report the outcome.

    ``replace=False`` appends the tags to each image's existing tags.
    Unchanged images are not rewritten and therefore not re-stamped.
    """
    result = BatchTagsResult()
    for path in paths or ():
        image_path = str(path)
        if repository is not None:
            outcome, target = _write_database(
                repository,
                image_path,
                tags,
                replace,
                dataset_root=dataset_root,
                author=author,
                modified_at=modified_at,
            )
        else:
            outcome, target = _write_json(
                image_path,
                tags,
                replace,
                output_dir=output_dir,
                author=author,
                modified_at=modified_at,
            )
        if outcome == "updated":
            result.updated.append(image_path)
        elif outcome == "unchanged":
            result.unchanged.append(image_path)
        else:
            result.failed.append(image_path)
            continue
        result.tags_by_path[image_path] = target
    return result


def _write_database(
    repository,
    path,
    tags,
    replace,
    *,
    dataset_root,
    author,
    modified_at,
):
    image = _find_image(repository, path, dataset_root)
    if image is None:
        return "failed", []
    try:
        annotation = repository.load_annotation(image["id"])
        current = normalize_image_tags(list(annotation.tags or []))
        target = merge_image_tags(current, tags, replace)
        if target == current:
            return "unchanged", target
        annotation.tags = target
        repository.save_annotation(
            image["id"],
            annotation,
            editor=author or None,
            modified_at=modified_at or None,
        )
    except Exception:  # noqa: BLE001 - reported per file by the caller
        return "failed", []
    return "updated", target


def _write_json(
    path,
    tags,
    replace,
    *,
    output_dir,
    author,
    modified_at,
):
    label_file = _label_file_for(path, output_dir)
    try:
        current = normalize_image_tags(
            list(read_file_meta(path, label_file).tags or [])
        )
        target = merge_image_tags(current, tags, replace)
        if target == current:
            return "unchanged", target
        written = write_tags(
            label_file,
            target,
            image_path=path,
            author=author,
            modified_at=modified_at,
        )
    except Exception:  # noqa: BLE001 - reported per file by the caller
        return "failed", []
    return ("updated" if written else "failed"), target


def _find_image(repository, path, dataset_root):
    if not dataset_root:
        return None
    relative = osp.relpath(path, dataset_root).replace(os.sep, "/")
    return repository.find_image(relative)


def _label_file_for(path, output_dir):
    label_file = osp.splitext(path)[0] + ".json"
    if output_dir:
        label_file = osp.join(output_dir, osp.basename(label_file))
    return label_file
