"""Materialize the training view of a dataset (fork.63).

Training consumes a dataset on disk.  Two things can make a derived copy
necessary:

* **class mapping / merging** — label files carry numeric class indices, so
  merging several annotation classes into one training class means rewriting
  the first column of every label line;
* **a missing train/val split** — an export whose images all sit in ``none``
  has nothing to validate on, so the ratio control partitions the images.

The derived copy only *links* images (hardlink first, symlink next, copy as the
last resort) and writes new label copies plus ``data.yaml`` and
``class_map.yaml``.  The source dataset is never modified — the annotation data
stays authoritative and training only reads a view of it.

An identity mapping on an already split dataset returns the source
``data.yaml`` unchanged, so the common case stages no files at all.
"""

from __future__ import annotations

import datetime
import os
import random
import shutil
from dataclasses import dataclass, field

from ._io import save_yaml_config
from .dataset_view import (
    DatasetEntry,
    DatasetSnapshot,
    dataset_entries,
    label_path_for,
)

KEPT_SPLITS = ("train", "val", "test")


@dataclass(frozen=True)
class MappingEntry:
    """One source class and the training class it is mapped to."""

    source: str
    target: str
    enabled: bool = True


@dataclass
class ClassMappingPlan:
    """Resolved class mapping of one training run."""

    targets: tuple = ()
    source_to_target: dict = field(default_factory=dict)
    index_to_target: dict = field(default_factory=dict)
    excluded: tuple = ()
    identity: bool = True
    merges: tuple = ()


@dataclass
class TrainingView:
    """The dataset a training run actually receives."""

    data_yaml: str = ""
    view_dir: str | None = None
    names: tuple = ()
    notes: tuple = ()
    class_map_path: str = ""
    remapped_objects: int = 0
    skipped_objects: int = 0
    staged_images: int = 0
    dropped_images: int = 0


def plan_class_mapping(
    snapshot: DatasetSnapshot, mapping=None
) -> ClassMappingPlan:
    """Resolve ``mapping`` (``{source: {"target": str, "enabled": bool}}``)."""

    mapping = mapping or {}
    targets: list[str] = []
    source_to_target: dict[str, int] = {}
    index_to_target: dict[int, int] = {}
    excluded = []
    grouped: dict[str, list[str]] = {}

    for index, name in enumerate(snapshot.names):
        entry = mapping.get(name) or {}
        if not entry.get("enabled", True):
            excluded.append(name)
            continue
        target = str(entry.get("target", "") or "").strip() or name
        if target not in targets:
            targets.append(target)
        target_index = targets.index(target)
        source_to_target[name] = target_index
        index_to_target[index] = target_index
        grouped.setdefault(target, []).append(name)

    merges = tuple(
        (target, tuple(sources))
        for target, sources in grouped.items()
        if len(sources) > 1
    )
    # The labels only need rewriting when an index moves; the data.yaml needs
    # rewriting when a name changes, so both must match for "no staging".
    identity = (
        not excluded
        and tuple(targets) == tuple(snapshot.names)
        and index_to_target
        == {index: index for index in range(len(snapshot.names))}
    )
    return ClassMappingPlan(
        targets=tuple(targets),
        source_to_target=source_to_target,
        index_to_target=index_to_target,
        excluded=tuple(excluded),
        identity=identity,
        merges=merges,
    )


def describe_plan(plan: ClassMappingPlan) -> list[str]:
    """Return log lines that explain the mapping (no Qt, no translation)."""

    lines = []
    if plan.excluded:
        lines.append("Excluded classes: " + ", ".join(plan.excluded))
    for target, sources in plan.merges:
        lines.append(f"Merged classes: {' + '.join(sources)} -> {target}")
    if plan.identity:
        lines.append("Class mapping: identity (no label rewrite)")
    return lines


def build_training_view(
    snapshot: DatasetSnapshot,
    mapping,
    ratio: float,
    dest_root: str,
    task_type: str = "detect",
) -> TrainingView:
    """Return the dataset view a training run should use.

    No copy is made when the mapping is the identity and the dataset already
    carries ``train``/``val`` splits.
    """

    if not snapshot.ok:
        raise ValueError(snapshot.error or "Dataset is not usable")
    plan = plan_class_mapping(snapshot, mapping)
    if not plan.targets:
        raise ValueError(
            "Every class is excluded from training; keep at least one class"
        )
    needs_split = not snapshot.prepared
    if plan.identity and not needs_split:
        return TrainingView(
            data_yaml=snapshot.data_yaml or snapshot.root,
            names=tuple(snapshot.names),
            notes=(
                "Dataset already has train/val splits and the class mapping "
                "is the identity one; using it without staging files",
            ),
        )

    entries = dataset_entries(snapshot)
    if not entries:
        raise ValueError("Dataset contains no image")
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        ratio = 0.8
    ratio = min(max(ratio, 0.05), 0.95)

    assignments = _assign_splits(entries, needs_split, ratio)
    view_dir = _create_view_dir(snapshot, dest_root, task_type)
    stats = _stage(snapshot, plan, assignments, view_dir)
    data_yaml = _write_data_yaml(
        view_dir=view_dir,
        snapshot=snapshot,
        plan=plan,
        has_test=any(split == "test" for _, split in assignments),
    )
    class_map_path = _write_class_map(
        view_dir=view_dir,
        snapshot=snapshot,
        plan=plan,
        ratio=ratio,
        needs_split=needs_split,
        stats=stats,
    )

    notes = describe_plan(plan)
    if needs_split:
        notes.append(
            "Dataset had no train/val split; images were partitioned with "
            f"ratio {ratio:.2f}"
        )
    notes.append(f"Training view: {view_dir}")
    notes.append(f"Class map: {class_map_path}")
    return TrainingView(
        data_yaml=data_yaml,
        view_dir=view_dir,
        names=plan.targets,
        notes=tuple(notes),
        class_map_path=class_map_path,
        remapped_objects=stats["remapped_objects"],
        skipped_objects=stats["skipped_objects"],
        staged_images=stats["staged_images"],
        dropped_images=stats["dropped_images"],
    )


# -- staging -----------------------------------------------------------------
def _assign_splits(
    entries: list[DatasetEntry], needs_split: bool, ratio: float
) -> list[tuple[DatasetEntry, str]]:
    if needs_split:
        shuffled = list(entries)
        # Deterministic shuffle: the same dataset always yields the same split,
        # so a retrain stays comparable while ordering bias is removed.
        random.Random(0).shuffle(shuffled)
        train_count = max(1, int(len(shuffled) * ratio))
        if len(shuffled) > 1:
            train_count = min(train_count, len(shuffled) - 1)
        return [
            (entry, "train" if index < train_count else "val")
            for index, entry in enumerate(shuffled)
        ]
    return [
        (entry, entry.split) for entry in entries if entry.split in KEPT_SPLITS
    ]


def _create_view_dir(
    snapshot: DatasetSnapshot, dest_root: str, task_type: str
) -> str:
    stem = os.path.splitext(
        os.path.basename(snapshot.data_yaml or snapshot.root)
    )[0]
    stem = (stem or "dataset").replace(" ", "_")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    parent = os.path.join(dest_root, "views", str(task_type).lower())
    os.makedirs(parent, exist_ok=True)
    view_dir = os.path.join(parent, f"{stem}_{timestamp}")
    suffix = 1
    # Two runs in the same second must not share a view: staging into a
    # non-empty folder would silently mix the two mappings.
    while os.path.exists(view_dir):
        suffix += 1
        view_dir = os.path.join(parent, f"{stem}_{timestamp}_{suffix}")
    os.makedirs(view_dir)
    return view_dir


def _stage(
    snapshot: DatasetSnapshot,
    plan: ClassMappingPlan,
    assignments: list[tuple[DatasetEntry, str]],
    view_dir: str,
) -> dict:
    stats = {
        "staged_images": 0,
        "dropped_images": 0,
        "remapped_objects": 0,
        "skipped_objects": 0,
        "empty_label_images": 0,
    }
    if snapshot.mode == "imagefolder":
        _stage_imagefolder(plan, assignments, view_dir, stats)
    else:
        _stage_yaml(plan, assignments, view_dir, stats)
    return stats


def _stage_imagefolder(
    plan: ClassMappingPlan,
    assignments: list[tuple[DatasetEntry, str]],
    view_dir: str,
    stats: dict,
) -> None:
    for entry, split in assignments:
        if entry.class_index is None:
            stats["skipped_objects"] += 1
            continue
        target = plan.index_to_target.get(entry.class_index)
        if target is None:
            stats["dropped_images"] += 1
            continue
        destination = os.path.join(
            view_dir,
            split,
            plan.targets[target],
            os.path.basename(entry.image_path),
        )
        if _link_image(entry.image_path, destination):
            stats["staged_images"] += 1
        else:
            stats["dropped_images"] += 1


def _stage_yaml(
    plan: ClassMappingPlan,
    assignments: list[tuple[DatasetEntry, str]],
    view_dir: str,
    stats: dict,
) -> None:
    used: dict[str, set] = {}
    for entry, split in assignments:
        source_label = label_path_for(entry.image_path)
        images_dir = os.path.join(view_dir, "images", split)
        used_names = used.setdefault(split, set())
        filename = _unique_name(
            images_dir, os.path.basename(entry.image_path), used_names
        )
        destination = os.path.join(images_dir, filename)
        if not _link_image(entry.image_path, destination):
            stats["dropped_images"] += 1
            continue
        stats["staged_images"] += 1
        label_path = os.path.join(
            view_dir, "labels", split, os.path.splitext(filename)[0] + ".txt"
        )
        _rewrite_label(source_label, label_path, plan, stats)


def _unique_name(directory: str, filename: str, used: set) -> str:
    if filename not in used and not os.path.exists(
        os.path.join(directory, filename)
    ):
        used.add(filename)
        return filename
    stem, extension = os.path.splitext(filename)
    index = 1
    while True:
        candidate = f"{stem}_{index}{extension}"
        if candidate not in used and not os.path.exists(
            os.path.join(directory, candidate)
        ):
            used.add(candidate)
            return candidate
        index += 1


def _link_image(source: str, destination: str) -> bool:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if os.path.exists(destination):
        return True
    for linker in ("link", "symlink"):
        try:
            getattr(os, linker)(source, destination)
            return True
        except (OSError, NotImplementedError, AttributeError):
            continue
    try:
        shutil.copy2(source, destination)
        return True
    except OSError:
        return False


def _rewrite_label(
    source: str,
    destination: str,
    plan: ClassMappingPlan,
    stats: dict,
) -> None:
    """Rewrite the class column of one label file into the view."""

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    try:
        with open(source, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, UnicodeDecodeError):
        # A missing label file means "background image"; Ultralytics accepts an
        # empty label file, and an explicit empty file is simpler to reason
        # about than a missing one.
        stats["empty_label_images"] += 1
        _write_lines(destination, [])
        return

    output = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        try:
            class_id = int(float(parts[0]))
        except ValueError:
            stats["skipped_objects"] += 1
            continue
        target = plan.index_to_target.get(class_id)
        if target is None:
            stats["skipped_objects"] += 1
            continue
        if target != class_id:
            stats["remapped_objects"] += 1
        parts[0] = str(target)
        output.append(" ".join(parts))
    _write_lines(destination, output)


def _write_lines(destination: str, lines: list[str]) -> None:
    try:
        with open(destination, "w", encoding="utf-8") as handle:
            if lines:
                handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def _write_data_yaml(
    view_dir: str,
    snapshot: DatasetSnapshot,
    plan: ClassMappingPlan,
    has_test: bool,
) -> str:
    data = {
        "path": view_dir,
        "nc": len(plan.targets),
        "names": {index: name for index, name in enumerate(plan.targets)},
    }
    if snapshot.mode == "imagefolder":
        data["train"] = "train"
        data["val"] = "val"
    else:
        data["train"] = "images/train"
        data["val"] = "images/val"
        if has_test:
            data["test"] = "images/test"
    data_yaml = os.path.join(view_dir, "data.yaml")
    if not save_yaml_config(data, data_yaml):
        raise ValueError(f"Failed to write dataset YAML: {data_yaml}")
    return data_yaml


def _write_class_map(
    view_dir: str,
    snapshot: DatasetSnapshot,
    plan: ClassMappingPlan,
    ratio: float,
    needs_split: bool,
    stats: dict,
) -> str:
    classes = [
        {
            "source": name,
            "target": (
                plan.targets[plan.source_to_target[name]]
                if name in plan.source_to_target
                else ""
            ),
            "enabled": name in plan.source_to_target,
        }
        for name in snapshot.names
    ]
    record = {
        "format_version": 1,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_dataset": snapshot.data_yaml or snapshot.root,
        "source_mode": snapshot.mode,
        "names": list(plan.targets),
        "classes": classes,
        "excluded": list(plan.excluded),
        "merges": {target: list(sources) for target, sources in plan.merges},
        "apply_split": needs_split,
        "dataset_ratio": ratio,
        "stats": dict(stats),
    }
    class_map_path = os.path.join(view_dir, "class_map.yaml")
    if not save_yaml_config(record, class_map_path):
        raise ValueError(f"Failed to write class map: {class_map_path}")
    return class_map_path
