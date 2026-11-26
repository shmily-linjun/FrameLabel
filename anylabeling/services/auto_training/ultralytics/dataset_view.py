"""Read-only inspection of the dataset a training run consumes (fork.63).

Training no longer derives its data from the labeling workspace: it consumes a
dataset on disk, either the ``data.yaml`` written by the YOLO export contract
(``images/<split>`` + ``labels/<split>`` + ``data.yaml``) or a classification
image folder.  This module turns such a dataset into the rows the training
dialog shows (overview / classes), so the statistics live in one testable place
instead of inside the dialog.

Rules:

* nothing is written; every source file is opened read-only;
* no Qt import, so the counters can be unit tested;
* the snapshot is cached by path plus the mtimes of the ``data.yaml``, the
  ``images`` and the ``labels`` directories.  Editing a label file in place
  does not change a directory mtime, so the caller passes ``force=True`` when
  the operator asks for a refresh.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

from ._io import load_yaml_config

SPLITS = ("train", "val", "test", "none")
YAML_NAMES = ("data.yaml", "data.yml", "dataset.yaml", "dataset.yml")
IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)


@dataclass(frozen=True)
class CategoryRow:
    """One class of the dataset and its counters."""

    name: str
    image_count: int
    object_count: int


@dataclass(frozen=True)
class SplitRow:
    """One split (train/val/test/none) and its counters."""

    split: str
    images: int
    objects: int
    labeled_images: int
    missing_labels: int


@dataclass(frozen=True)
class DatasetEntry:
    """One image plus the split (YAML) or class (folder) it came from."""

    image_path: str
    split: str = "none"
    class_index: int | None = None


@dataclass
class DatasetSnapshot:
    """Everything the dialog shows about the selected dataset."""

    source: str = ""
    data_yaml: str | None = None
    root: str = ""
    mode: str = "yaml"  # "yaml" | "imagefolder"
    names: tuple = ()
    splits: tuple = ()
    categories: tuple = ()
    total_images: int = 0
    total_objects: int = 0
    labeled_images: int = 0
    empty_label_images: int = 0
    missing_labels: int = 0
    unknown_class_ids: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def prepared(self) -> bool:
        """True when train **and** val already carry images."""

        counts = {row.split: row.images for row in self.splits if row.images}
        return bool(counts.get("train")) and bool(counts.get("val"))

    def split_images(self, split: str) -> int:
        for row in self.splits:
            if row.split == split:
                return row.images
        return 0


_CACHE: dict = {}


def clear_cache() -> None:
    """Drop every cached snapshot (used after a dataset is edited)."""

    _CACHE.clear()


def locate_dataset_yaml(path: str) -> str | None:
    """Return the ``data.yaml`` for a file or directory path, if any.

    A directory is accepted because the export writes the dataset into a root
    folder such as ``yolo_dataset``; one level of sub directory is searched so
    ``<root>/<task>/data.yaml`` also resolves.
    """

    if not path:
        return None
    path = os.path.abspath(path)
    if os.path.isfile(path):
        return path
    if not os.path.isdir(path):
        return None
    for name in YAML_NAMES:
        candidate = os.path.join(path, name)
        if os.path.isfile(candidate):
            return candidate
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return None
    for entry in entries:
        sub = os.path.join(path, entry)
        if not os.path.isdir(sub):
            continue
        for name in YAML_NAMES:
            candidate = os.path.join(sub, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def inspect_dataset(path: str, force: bool = False) -> DatasetSnapshot:
    """Inspect ``path`` and return its counters (cached when possible)."""

    if not path:
        return DatasetSnapshot(error="Dataset path is empty")
    path = os.path.abspath(path)
    data_yaml = locate_dataset_yaml(path)
    signature = _signature(path, data_yaml)
    cached = _CACHE.get(path)
    if cached is not None and not force and cached[0] == signature:
        return cached[1]
    snapshot = (
        _inspect_yaml(data_yaml) if data_yaml else _inspect_imagefolder(path)
    )
    _CACHE[path] = (signature, snapshot)
    return snapshot


def dataset_entries(snapshot: DatasetSnapshot) -> list[DatasetEntry]:
    """Return every image of the dataset with its split or class."""

    if not snapshot.ok:
        return []
    if snapshot.mode == "imagefolder":
        return _imagefolder_entries(snapshot)
    entries = []
    split_dirs = _split_directories_of(snapshot)
    for split in [name for name in SPLITS if name in split_dirs]:
        for directory in split_dirs[split]:
            for image in _iter_images(directory):
                entries.append(DatasetEntry(image_path=image, split=split))
    return entries


# -- helpers -----------------------------------------------------------------
def _signature(path: str, data_yaml: str | None) -> tuple:
    def mtime(candidate: str) -> float:
        try:
            return os.path.getmtime(candidate)
        except OSError:
            return 0.0

    root = os.path.dirname(data_yaml) if data_yaml else path
    return (
        mtime(data_yaml) if data_yaml else mtime(path),
        mtime(os.path.join(root, "images")),
        mtime(os.path.join(root, "labels")),
        mtime(os.path.join(root, "train")),
        mtime(os.path.join(root, "val")),
    )


def _iter_images(directory: str) -> Iterator[str]:
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if not entry.is_file():
                        continue
                except OSError:
                    continue
                if os.path.splitext(entry.name)[1].lower() in IMAGE_EXTENSIONS:
                    yield entry.path
    except OSError:
        return


def _label_path(image_path: str) -> str:
    """Return the YOLO label path for an image (``images`` -> ``labels``)."""

    normalized = os.path.normpath(image_path)
    marker = f"{os.sep}images{os.sep}"
    if marker in normalized:
        head, _, tail = normalized.rpartition(marker)
        stem, _ = os.path.splitext(tail)
        return f"{head}{os.sep}labels{os.sep}{stem}.txt"
    parent = os.path.dirname(normalized)
    stem, _ = os.path.splitext(os.path.basename(normalized))
    if os.path.basename(parent).lower() == "images":
        return os.path.join(os.path.dirname(parent), "labels", stem + ".txt")
    return os.path.join(parent, stem + ".txt")


def label_path_for(image_path: str) -> str:
    """Public alias of :func:`_label_path` for the training view builder."""

    return _label_path(image_path)


def _count_label_file(label_path: str) -> tuple:
    """Return ``(object_count, class_ids)``; ``-1`` means "no label file"."""

    try:
        with open(label_path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return -1, ()
    class_ids = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        try:
            class_ids.append(int(float(parts[0])))
        except ValueError:
            continue
    return len(class_ids), class_ids


def _names_from_data(data: dict) -> list[str]:
    names = data.get("names")
    if isinstance(names, dict):
        def sort_key(item):
            try:
                return (0, int(item[0]), "")
            except (TypeError, ValueError):
                return (1, 0, str(item[0]))

        return [str(value) for _, value in sorted(names.items(), key=sort_key)]
    if isinstance(names, (list, tuple)):
        return [str(value) for value in names]
    return []


def _resolve_dir(root: str, value: str) -> str:
    value = os.path.expanduser(os.path.expandvars(value))
    if not os.path.isabs(value):
        value = os.path.join(root, value)
    return os.path.normpath(value)


def _inspect_yaml(data_yaml: str) -> DatasetSnapshot:
    data = load_yaml_config(data_yaml)
    if not isinstance(data, dict):
        return DatasetSnapshot(
            source=data_yaml,
            data_yaml=data_yaml,
            error=f"Failed to parse dataset YAML: {data_yaml}",
        )
    root_value = data.get("path")
    root = (
        _resolve_dir(os.path.dirname(os.path.abspath(data_yaml)), root_value)
        if isinstance(root_value, str) and root_value.strip()
        else os.path.dirname(os.path.abspath(data_yaml))
    )
    if not os.path.isdir(root):
        return DatasetSnapshot(
            source=data_yaml,
            data_yaml=data_yaml,
            root=root,
            error=f"Dataset root does not exist: {root}",
        )

    names = _names_from_data(data)
    split_dirs = _split_dirs_from_data(data, root)
    if not split_dirs:
        return DatasetSnapshot(
            source=data_yaml,
            data_yaml=data_yaml,
            root=root,
            names=tuple(names),
            error=(
                "Dataset has no image folder: expected an 'images' folder or "
                f"train/val keys pointing at existing folders under {root}"
            ),
        )

    per_class_images: dict[int, int] = {}
    per_class_objects: dict[int, int] = {}
    split_rows = []
    total_images = 0
    total_objects = 0
    labeled_images = 0
    empty_label_images = 0
    missing_labels = 0
    unknown_class_ids = 0

    for split in [name for name in SPLITS if name in split_dirs]:
        split_images = split_objects = split_labeled = split_missing = 0
        for directory in split_dirs[split]:
            for image_path in _iter_images(directory):
                split_images += 1
                object_count, class_ids = _count_label_file(
                    _label_path(image_path)
                )
                if object_count < 0:
                    split_missing += 1
                    continue
                if object_count == 0:
                    empty_label_images += 1
                    continue
                split_labeled += 1
                split_objects += object_count
                seen = set()
                for class_id in class_ids:
                    if class_id < 0:
                        continue
                    if class_id >= len(names):
                        unknown_class_ids += 1
                        continue
                    per_class_objects[class_id] = (
                        per_class_objects.get(class_id, 0) + 1
                    )
                    if class_id not in seen:
                        seen.add(class_id)
                        per_class_images[class_id] = (
                            per_class_images.get(class_id, 0) + 1
                        )
        total_images += split_images
        total_objects += split_objects
        labeled_images += split_labeled
        missing_labels += split_missing
        split_rows.append(
            SplitRow(
                split=split,
                images=split_images,
                objects=split_objects,
                labeled_images=split_labeled,
                missing_labels=split_missing,
            )
        )

    if not names:
        names = [f"class {index}" for index in sorted(per_class_images)]
    categories = tuple(
        CategoryRow(
            name=str(name),
            image_count=per_class_images.get(index, 0),
            object_count=per_class_objects.get(index, 0),
        )
        for index, name in enumerate(names)
    )
    return DatasetSnapshot(
        source=data_yaml,
        data_yaml=data_yaml,
        root=root,
        mode="yaml",
        names=tuple(str(name) for name in names),
        splits=tuple(split_rows),
        categories=categories,
        total_images=total_images,
        total_objects=total_objects,
        labeled_images=labeled_images,
        empty_label_images=empty_label_images,
        missing_labels=missing_labels,
        unknown_class_ids=unknown_class_ids,
    )


def _split_dirs_from_data(data: dict, root: str) -> dict:
    split_dirs: dict[str, list[str]] = {}
    for split in ("train", "val", "test"):
        value = data.get(split)
        if not isinstance(value, str) or not value.strip():
            continue
        directory = _resolve_dir(root, value)
        if os.path.isdir(directory):
            split_dirs.setdefault(split, []).append(directory)
    images_root = os.path.join(root, "images")
    if os.path.isdir(images_root):
        try:
            entries = sorted(os.listdir(images_root))
        except OSError:
            entries = []
        for entry in entries:
            directory = os.path.join(images_root, entry)
            if not os.path.isdir(directory) or entry in split_dirs:
                continue
            split_dirs[entry] = [directory]
        flat = os.path.join(root, "images")
        if "none" not in split_dirs and next(_iter_images(flat), None):
            split_dirs["none"] = [flat]
    return split_dirs


def _split_directories_of(snapshot: DatasetSnapshot) -> dict[str, list[str]]:
    data = load_yaml_config(snapshot.data_yaml or "") or {}
    return _split_dirs_from_data(data, snapshot.root)


def _imagefolder_split_dirs(root: str) -> dict[str, str]:
    split_dirs = {}
    for split in ("train", "val", "test"):
        directory = os.path.join(root, split)
        if os.path.isdir(directory):
            split_dirs[split] = directory
    if not split_dirs:
        split_dirs = {"all": root}
    return split_dirs


def _inspect_imagefolder(path: str) -> DatasetSnapshot:
    """Inspect a classification image folder.

    Accepted shapes are ``<root>/<class>/*.jpg`` and the split form
    ``<root>/{train,val,test}/<class>/*.jpg`` that Ultralytics expects.
    """

    if not os.path.isdir(path):
        return DatasetSnapshot(
            source=path, error=f"Dataset folder does not exist: {path}"
        )
    split_dirs = _imagefolder_split_dirs(path)

    class_images: dict[str, dict[str, int]] = {}
    for split, directory in split_dirs.items():
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            continue
        for entry in entries:
            class_dir = os.path.join(directory, entry)
            if not os.path.isdir(class_dir):
                continue
            class_images.setdefault(entry, {})[split] = sum(
                1 for _ in _iter_images(class_dir)
            )

    if not class_images:
        return DatasetSnapshot(
            source=path,
            root=path,
            mode="imagefolder",
            error=(
                "Classification dataset must contain one folder per class "
                f"(optionally under train/ and val/): {path}"
            ),
        )

    names = sorted(class_images)
    categories = tuple(
        CategoryRow(
            name=name,
            image_count=sum(class_images[name].values()),
            object_count=0,
        )
        for name in names
    )
    split_rows = tuple(
        SplitRow(
            split=split,
            images=sum(class_images[name].get(split, 0) for name in names),
            objects=0,
            labeled_images=sum(
                class_images[name].get(split, 0) for name in names
            ),
            missing_labels=0,
        )
        for split in split_dirs
    )
    return DatasetSnapshot(
        source=path,
        root=path,
        mode="imagefolder",
        names=tuple(names),
        splits=split_rows,
        categories=categories,
        total_images=sum(row.images for row in split_rows),
        total_objects=0,
        labeled_images=sum(row.labeled_images for row in split_rows),
    )


def _imagefolder_entries(snapshot: DatasetSnapshot) -> list[DatasetEntry]:
    entries = []
    for split, directory in _imagefolder_split_dirs(snapshot.root).items():
        for index, name in enumerate(snapshot.names):
            class_dir = os.path.join(directory, name)
            for image in _iter_images(class_dir):
                entries.append(
                    DatasetEntry(
                        image_path=image, split=split, class_index=index
                    )
                )
    return entries
