"""Input resolution for the YOLO annotation upload (fork.49).

The upload dialog used to ask for a ``classes.txt`` file and to start from
``dirname(dirname(image))``, which does not match the usual
``images/<split>`` + ``labels/<split>`` layout.  This module owns the three
facts the flow needs to work out by itself:

* which class names the numeric indices in the ``.txt`` files refer to
  (dataset categories first, then a detected ``classes.txt``/``data.yaml``);
* where the label files live (``images/<split>`` -> ``labels/<split>``);
* how to read ``data.yaml`` ``names`` in index order.

It is Qt-free on purpose so the precedence rules can be tested without a
window.
"""

from __future__ import annotations

import os
import os.path as osp
from dataclasses import dataclass
from pathlib import Path

import yaml

#: File names accepted as a plain "one class per line" class list.
CLASS_FILE_NAMES = ("classes.txt", "obj.names", "names.txt")

#: File names accepted as an Ultralytics-style dataset description.
DATA_YAML_NAMES = ("data.yaml", "data.yml", "dataset.yaml", "dataset.yml")

#: Directory names that map to the label directory.
IMAGE_DIR_NAME = "images"
LABEL_DIR_NAME = "labels"

#: How many parent directories are inspected when looking for class sources.
SEARCH_LEVELS = 3

SOURCE_DATASET = "dataset"
SOURCE_CLASSES = "classes"
SOURCE_YAML = "yaml"
SOURCE_PICKED = "picked"


@dataclass(frozen=True)
class ClassSource:
    """Class names plus where they came from.

    ``kind`` is one of :data:`SOURCE_DATASET`, :data:`SOURCE_CLASSES`,
    :data:`SOURCE_YAML` or :data:`SOURCE_PICKED`; ``path`` is empty for the
    dataset category table.
    """

    names: tuple[str, ...]
    kind: str
    path: str = ""

    @property
    def has_names(self) -> bool:
        return bool(self.names)


def dataset_category_names(repository) -> list[str]:
    """Return the dataset's category names in the "Classes" tab order.

    ``category.sort_index`` is the authoritative order used by the exporters;
    the uploader must read the same order so that a class index in a ``.txt``
    file keeps its meaning.  A missing/unreadable repository yields ``[]``.
    """

    if repository is None:
        return []
    try:
        rows = repository.category_counts()
        names = []
        for row in rows:
            name = str(row.get("name") or "").strip()
            if name:
                names.append(name)
    except Exception:  # noqa: BLE001 - upload must not fail on a stats read
        return []
    return names


def read_classes_file(path: str) -> list[str]:
    """Read a one-class-per-line file, dropping blank lines."""

    with open(path, "r", encoding="utf-8-sig") as handle:
        names = [line.strip() for line in handle.read().splitlines()]
    return [name for name in names if name]


def _sort_name_keys(keys) -> list:
    """Order ``data.yaml`` ``names`` keys numerically when possible."""

    def key_func(key):
        text = str(key)
        if text.lstrip("-").isdigit():
            return (0, int(text))
        return (1, text)

    return sorted(keys, key=key_func)


def read_data_yaml_names(path: str) -> list[str]:
    """Return the ``names`` entry of a YOLO ``data.yaml`` in index order."""

    with open(path, "r", encoding="utf-8-sig") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("names must be a mapping or a list")
    names = data.get("names")
    if isinstance(names, dict):
        ordered = [names[key] for key in _sort_name_keys(names.keys())]
    elif isinstance(names, list):
        ordered = list(names)
    else:
        raise ValueError("missing 'names' entry")
    result = [str(name).strip() for name in ordered]
    result = [name for name in result if name]
    if not result:
        raise ValueError("empty 'names' entry")
    return result


def _ancestor_dirs(start_dir: str, levels: int = SEARCH_LEVELS):
    """Yield ``start_dir`` and at most ``levels`` parents, outermost last."""

    current = Path(str(start_dir or ".")).expanduser()
    try:
        current = current.resolve()
    except OSError:
        pass
    for _ in range(levels + 1):
        yield current
        parent = current.parent
        if parent == current:
            return
        current = parent


def find_classes_file(start_dir: str, levels: int = SEARCH_LEVELS):
    """Return the closest plain class list at/above ``start_dir``."""

    for directory in _ancestor_dirs(start_dir, levels):
        for name in CLASS_FILE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return None


def find_data_yaml(start_dir: str, levels: int = SEARCH_LEVELS):
    """Return the closest YOLO ``data.yaml`` at/above ``start_dir``."""

    for directory in _ancestor_dirs(start_dir, levels):
        for name in DATA_YAML_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return None


def detect_class_source(image_dir: str) -> ClassSource | None:
    """Detect class names for a JSON folder (no dataset database).

    A plain ``classes.txt`` wins over ``data.yaml`` because that is the file
    the previous flow asked for; unreadable candidates are skipped instead of
    aborting the upload.
    """

    classes_file = find_classes_file(image_dir)
    if classes_file:
        try:
            names = read_classes_file(classes_file)
        except OSError:
            names = []
        if names:
            return ClassSource(tuple(names), SOURCE_CLASSES, classes_file)

    yaml_file = find_data_yaml(image_dir)
    if yaml_file:
        try:
            names = read_data_yaml_names(yaml_file)
        except (OSError, ValueError, yaml.YAMLError):
            names = []
        if names:
            return ClassSource(tuple(names), SOURCE_YAML, yaml_file)
    return None


def _labels_candidate(image_dir: str) -> str | None:
    parts = Path(image_dir).parts
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].lower() == IMAGE_DIR_NAME:
            return str(Path(*parts[:index], LABEL_DIR_NAME, *parts[index + 1 :]))
    return None


def guess_label_dir(image_dir: str, dataset_root: str | None = None) -> str:
    """Guess the label directory for an image directory.

    ``.../images/train`` maps to ``.../labels/train``; the split is preserved.
    When that path does not exist, common fallbacks are tried and the guess is
    returned anyway so the dialog can show it for correction.
    """

    replacement = _labels_candidate(image_dir)
    candidates = []
    if replacement:
        candidates.append(replacement)
    if dataset_root:
        candidates.append(osp.join(str(dataset_root), LABEL_DIR_NAME))
    candidates.append(osp.join(osp.dirname(str(image_dir)), LABEL_DIR_NAME))
    for candidate in candidates:
        if osp.isdir(candidate):
            return candidate
    return candidates[0] if candidates else osp.join(str(image_dir), LABEL_DIR_NAME)


def resolve_label_dir(chosen_dir: str, image_dir: str) -> str:
    """Resolve a user-entered label directory.

    Users often point at ``labels`` while the images live in ``images/train``.
    If the chosen directory has no direct match but contains a same-named
    split subdirectory, that subdirectory is used instead.  A non-existent
    path is returned unchanged so the caller can report the error.
    """

    chosen = str(chosen_dir or "").strip()
    if not chosen or not osp.isdir(chosen):
        return chosen
    if not osp.isdir(str(image_dir)):
        return chosen
    split_name = osp.basename(str(image_dir).rstrip("\\/"))
    if not split_name:
        return chosen
    nested = osp.join(chosen, split_name)
    if osp.isdir(nested) and split_name != osp.basename(chosen):
        try:
            has_direct = any(
                osp.splitext(name)[1].lower()
                in (".txt", ".xml", ".json", ".png")
                for name in os.listdir(chosen)
            )
        except OSError:
            has_direct = False
        if not has_direct:
            return nested
    return chosen
