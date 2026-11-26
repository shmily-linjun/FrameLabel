"""Tests for the training view built from a dataset plus a class mapping."""

import os

import pytest

from anylabeling.services.auto_training.ultralytics._io import (
    load_yaml_config,
)
from anylabeling.services.auto_training.ultralytics.dataset_view import (
    clear_cache,
    inspect_dataset,
)
from anylabeling.services.auto_training.ultralytics.training_view import (
    build_training_view,
    plan_class_mapping,
)


def write_image(path):
    with open(path, "wb") as handle:
        handle.write(b"\xff\xd8\xff")


def write_pair(images_dir, labels_dir, name, lines):
    write_image(os.path.join(images_dir, name))
    if lines is None:
        return
    with open(
        os.path.join(labels_dir, os.path.splitext(name)[0] + ".txt"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write("".join(line + "\n" for line in lines))


def build_dataset(root, splits):
    for split, count in splits.items():
        images_dir = os.path.join(root, "images", split)
        labels_dir = os.path.join(root, "labels", split)
        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(labels_dir, exist_ok=True)
        for index in range(count):
            name = f"{split}_{index}.jpg"
            lines = (
                ["0 0.5 0.5 0.2 0.2", "1 0.4 0.4 0.1 0.1"]
                if index % 2 == 0
                else ["2 0.3 0.3 0.1 0.1"]
            )
            write_pair(images_dir, labels_dir, name, lines)
    data_yaml = os.path.join(root, "data.yaml")
    content = [f"path: {root.replace(os.sep, '/')}"]
    for split in ("train", "val", "test"):
        if split in splits:
            content.append(f"{split}: images/{split}")
    content.append("nc: 3")
    content.append("names:\n  0: bolt\n  1: nut\n  2: scratch")
    with open(data_yaml, "w", encoding="utf-8") as handle:
        handle.write("\n".join(content) + "\n")
    return data_yaml


@pytest.fixture(autouse=True)
def isolated_cache():
    clear_cache()
    yield
    clear_cache()


def test_identity_mapping_reuses_the_source_dataset(tmp_path):
    root = str(tmp_path / "dataset")
    data_yaml = build_dataset(root, {"train": 2, "val": 1})
    snapshot = inspect_dataset(data_yaml)

    view = build_training_view(snapshot, {}, 0.8, str(tmp_path / "work"))

    assert view.data_yaml == data_yaml
    assert view.view_dir is None
    assert view.notes


def test_plan_detects_merge_exclusion_and_identity():
    from types import SimpleNamespace

    snapshot = SimpleNamespace(names=("bolt", "nut", "scratch"))
    mapping = {
        "bolt": {"target": "fastener", "enabled": True},
        "nut": {"target": "fastener", "enabled": True},
        "scratch": {"target": "scratch", "enabled": False},
    }

    plan = plan_class_mapping(snapshot, mapping)

    assert plan.targets == ("fastener",)
    assert plan.index_to_target == {0: 0, 1: 0}
    assert plan.excluded == ("scratch",)
    assert plan.identity is False
    assert plan.merges == (("fastener", ("bolt", "nut")),)

    identity = plan_class_mapping(snapshot, {})
    assert identity.identity is True
    assert identity.targets == ("bolt", "nut", "scratch")


def test_build_training_view_remaps_labels_and_writes_class_map(tmp_path):
    root = str(tmp_path / "dataset")
    data_yaml = build_dataset(root, {"train": 2, "val": 2})
    snapshot = inspect_dataset(data_yaml)
    mapping = {
        "bolt": {"target": "fastener", "enabled": True},
        "nut": {"target": "fastener", "enabled": True},
        "scratch": {"target": "scratch", "enabled": False},
    }

    view = build_training_view(
        snapshot, mapping, 0.8, str(tmp_path / "work"), "Detect"
    )

    assert view.view_dir is not None
    assert view.names == ("fastener",)
    assert view.staged_images == 4
    assert view.remapped_objects == 2
    assert view.skipped_objects == 2
    view_yaml = load_yaml_config(view.data_yaml)
    assert view_yaml["nc"] == 1
    assert view_yaml["names"] == {0: "fastener"}
    assert view_yaml["path"] == view.view_dir
    assert os.path.isfile(view.class_map_path)
    record = load_yaml_config(view.class_map_path)
    assert record["names"] == ["fastener"]
    assert record["excluded"] == ["scratch"]
    assert record["merges"] == {"fastener": ["bolt", "nut"]}
    assert record["source_dataset"] == data_yaml
    label_path = os.path.join(view.view_dir, "labels", "train", "train_0.txt")
    with open(label_path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    assert lines == ["0 0.5 0.5 0.2 0.2", "0 0.4 0.4 0.1 0.1"]
    excluded_label = os.path.join(
        view.view_dir, "labels", "train", "train_1.txt"
    )
    with open(excluded_label, encoding="utf-8") as handle:
        assert handle.read().strip() == ""


def test_build_training_view_partitions_a_dataset_without_split(tmp_path):
    root = str(tmp_path / "flat")
    data_yaml = build_dataset(root, {"none": 9})
    snapshot = inspect_dataset(data_yaml)
    assert snapshot.prepared is False

    view = build_training_view(
        snapshot, {}, 0.8, str(tmp_path / "work"), "Detect"
    )

    train = os.listdir(os.path.join(view.view_dir, "images", "train"))
    val = os.listdir(os.path.join(view.view_dir, "images", "val"))
    assert (len(train), len(val)) == (7, 2)
    view_yaml = load_yaml_config(view.data_yaml)
    assert view_yaml["train"] == "images/train"
    assert view_yaml["val"] == "images/val"
    record = load_yaml_config(view.class_map_path)
    assert record["apply_split"] is True
    assert record["dataset_ratio"] == 0.8


def test_partition_is_deterministic(tmp_path):
    root = str(tmp_path / "flat")
    data_yaml = build_dataset(root, {"none": 9})
    snapshot = inspect_dataset(data_yaml)

    first = build_training_view(
        snapshot, {}, 0.7, str(tmp_path / "a"), "Detect"
    )
    second = build_training_view(
        snapshot, {}, 0.7, str(tmp_path / "b"), "Detect"
    )

    first_names = sorted(
        os.listdir(os.path.join(first.view_dir, "images", "train"))
    )
    second_names = sorted(
        os.listdir(os.path.join(second.view_dir, "images", "train"))
    )
    assert first_names == second_names


def test_two_runs_in_the_same_second_get_separate_view_dirs(tmp_path):
    root = str(tmp_path / "dataset")
    data_yaml = build_dataset(root, {"train": 2, "val": 1})
    snapshot = inspect_dataset(data_yaml)
    mapping = {"bolt": {"target": "b", "enabled": True}}

    first = build_training_view(
        snapshot, mapping, 0.8, str(tmp_path / "work"), "Detect"
    )
    second = build_training_view(
        snapshot, mapping, 0.8, str(tmp_path / "work"), "Detect"
    )

    assert first.view_dir != second.view_dir


def test_classification_view_links_images_per_class(tmp_path):
    root = tmp_path / "classify"
    for split, count in (("train", 2), ("val", 1)):
        for name in ("cat", "dog"):
            folder = root / split / name
            folder.mkdir(parents=True)
            for index in range(count):
                write_image(str(folder / f"{name}_{index}.jpg"))
    snapshot = inspect_dataset(str(root))
    mapping = {
        "cat": {"target": "animal", "enabled": True},
        "dog": {"target": "animal", "enabled": True},
    }

    view = build_training_view(
        snapshot, mapping, 0.8, str(tmp_path / "work"), "Classify"
    )

    assert view.names == ("animal",)
    staged = os.listdir(os.path.join(view.view_dir, "train", "animal"))
    assert len(staged) == 4
    view_yaml = load_yaml_config(view.data_yaml)
    assert view_yaml["train"] == "train"
    assert view_yaml["val"] == "val"


def test_every_class_excluded_is_rejected(tmp_path):
    root = str(tmp_path / "dataset")
    data_yaml = build_dataset(root, {"train": 1, "val": 1})
    snapshot = inspect_dataset(data_yaml)
    mapping = {
        name: {"target": name, "enabled": False} for name in snapshot.names
    }

    with pytest.raises(ValueError, match="at least one class"):
        build_training_view(snapshot, mapping, 0.8, str(tmp_path))


def test_unusable_snapshot_is_rejected(tmp_path):
    data_yaml = tmp_path / "data.yaml"
    data_yaml.write_text("names: [cat]\n", encoding="utf-8")
    snapshot = inspect_dataset(str(data_yaml))

    with pytest.raises(ValueError, match="no image folder"):
        build_training_view(snapshot, {}, 0.8, str(tmp_path))
