"""Tests for the read-only dataset inspection used by the training tab."""

import os

import pytest

from anylabeling.services.auto_training.ultralytics import dataset_view
from anylabeling.services.auto_training.ultralytics.dataset_view import (
    clear_cache,
    dataset_entries,
    inspect_dataset,
    locate_dataset_yaml,
)


def write_image(path):
    with open(path, "wb") as handle:
        handle.write(b"\xff\xd8\xff")


def write_pair(images_dir, labels_dir, name, lines):
    write_image(os.path.join(images_dir, name))
    if lines is None:
        return
    label_path = os.path.join(labels_dir, os.path.splitext(name)[0] + ".txt")
    with open(label_path, "w", encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in lines))


def build_dataset(root, splits, names=("bolt", "nut", "scratch")):
    """Create a YOLO dataset: ``splits`` maps a split name to image count."""

    os.makedirs(root, exist_ok=True)
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
        write_pair(images_dir, labels_dir, f"{split}_background.jpg", None)
    data_yaml = os.path.join(root, "data.yaml")
    content = [f"path: {root.replace(os.sep, '/')}"]
    for split in ("train", "val", "test"):
        if split in splits:
            content.append(f"{split}: images/{split}")
    content.append("nc: 3")
    content.append(
        "names:\n" + "\n".join(
            f"  {index}: {name}" for index, name in enumerate(names)
        )
    )
    with open(data_yaml, "w", encoding="utf-8") as handle:
        handle.write("\n".join(content) + "\n")
    return data_yaml


@pytest.fixture(autouse=True)
def isolated_cache():
    clear_cache()
    yield
    clear_cache()


def test_locate_dataset_yaml_accepts_file_and_root(tmp_path):
    data_yaml = build_dataset(str(tmp_path / "dataset"), {"train": 1})
    assert locate_dataset_yaml(data_yaml) == os.path.abspath(data_yaml)
    assert locate_dataset_yaml(str(tmp_path / "dataset")) == os.path.abspath(
        data_yaml
    )
    assert locate_dataset_yaml(str(tmp_path / "missing")) is None


def test_inspect_dataset_counts_split_objects_and_missing_labels(tmp_path):
    data_yaml = build_dataset(
        str(tmp_path / "dataset"), {"train": 4, "val": 2}
    )

    snapshot = inspect_dataset(data_yaml)

    assert snapshot.ok, snapshot.error
    assert snapshot.mode == "yaml"
    assert snapshot.names == ("bolt", "nut", "scratch")
    assert [(row.split, row.images) for row in snapshot.splits] == [
        ("train", 5),
        ("val", 3),
    ]
    assert snapshot.total_images == 8
    # train: 2x2 + 2x1 = 6 objects, val: 1x2 + 1x1 = 3
    assert snapshot.total_objects == 9
    assert snapshot.labeled_images == 6
    assert snapshot.empty_label_images == 0
    assert snapshot.missing_labels == 2
    assert snapshot.prepared is True
    rows = {
        row.name: (row.image_count, row.object_count)
        for row in snapshot.categories
    }
    assert rows == {"bolt": (3, 3), "nut": (3, 3), "scratch": (3, 3)}
    assert len(dataset_entries(snapshot)) == 8


def test_inspect_dataset_reports_missing_root(tmp_path):
    data_yaml = tmp_path / "data.yaml"
    data_yaml.write_text(
        "path: /does/not/exist\ntrain: images/train\nval: images/val\n"
        "names: [cat]\n",
        encoding="utf-8",
    )

    snapshot = inspect_dataset(str(data_yaml))

    assert not snapshot.ok
    assert "Dataset root does not exist" in snapshot.error


def test_inspect_dataset_requires_an_image_folder(tmp_path):
    data_yaml = tmp_path / "data.yaml"
    data_yaml.write_text("names: [cat]\n", encoding="utf-8")

    snapshot = inspect_dataset(str(data_yaml))

    assert not snapshot.ok
    assert "no image folder" in snapshot.error
    assert snapshot.names == ("cat",)


def test_dataset_without_split_reports_none_and_is_not_prepared(tmp_path):
    data_yaml = build_dataset(str(tmp_path / "dataset"), {"none": 9})

    snapshot = inspect_dataset(data_yaml)

    assert snapshot.ok, snapshot.error
    assert snapshot.prepared is False
    assert snapshot.total_images == 10
    assert snapshot.split_images("none") == 10


def test_inspect_imagefolder_reads_class_folders(tmp_path):
    root = tmp_path / "classify"
    for split, count in (("train", 2), ("val", 1)):
        for name in ("cat", "dog"):
            folder = root / split / name
            folder.mkdir(parents=True)
            for index in range(count):
                write_image(str(folder / f"{name}_{index}.jpg"))

    snapshot = inspect_dataset(str(root))

    assert snapshot.ok, snapshot.error
    assert snapshot.mode == "imagefolder"
    assert snapshot.names == ("cat", "dog")
    assert snapshot.prepared is True
    assert snapshot.total_images == 6
    assert snapshot.total_objects == 0
    assert len(dataset_entries(snapshot)) == 6


def test_inspect_imagefolder_without_class_folder_reports_help(tmp_path):
    root = tmp_path / "flat"
    root.mkdir()
    write_image(str(root / "a.jpg"))

    snapshot = inspect_dataset(str(root))

    assert not snapshot.ok
    assert "one folder per class" in snapshot.error


def test_snapshot_is_cached_until_forced(tmp_path):
    data_yaml = build_dataset(str(tmp_path / "dataset"), {"train": 2})
    first = inspect_dataset(data_yaml)

    write_pair(
        os.path.join(os.path.dirname(data_yaml), "images", "train"),
        os.path.join(os.path.dirname(data_yaml), "labels", "train"),
        "train_extra.jpg",
        ["0 0.5 0.5 0.2 0.2"],
    )
    cached = inspect_dataset(data_yaml)
    forced = inspect_dataset(data_yaml, force=True)

    assert cached.total_images == first.total_images
    assert forced.total_images == first.total_images + 1


def test_unknown_class_ids_are_counted_without_breaking(tmp_path):
    root = str(tmp_path / "dataset")
    data_yaml = build_dataset(root, {"train": 1}, names=("cat",))
    labels_dir = os.path.join(root, "labels", "train")
    with open(
        os.path.join(labels_dir, "train_0.txt"), "w", encoding="utf-8"
    ) as handle:
        handle.write("0 0.5 0.5 0.2 0.2\n7 0.4 0.4 0.1 0.1\n")

    snapshot = inspect_dataset(data_yaml, force=True)

    assert snapshot.unknown_class_ids == 1
    assert snapshot.total_objects == 2
    assert snapshot.categories[0].object_count == 1


def test_label_path_mapping_follows_images_to_labels(tmp_path):
    root = os.path.join(str(tmp_path), "dataset")
    image_path = os.path.join(root, "images", "train", "a.jpg")

    assert dataset_view.label_path_for(image_path) == os.path.join(
        root, "labels", "train", "a.txt"
    )
