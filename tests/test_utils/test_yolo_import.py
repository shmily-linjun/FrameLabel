"""Tests for the YOLO upload input resolution (fork.49)."""

import os
import os.path as osp

import yaml

from anylabeling.views.labeling.utils.yolo_import import (
    SOURCE_CLASSES,
    SOURCE_DATASET,
    SOURCE_YAML,
    ClassSource,
    dataset_category_names,
    detect_class_source,
    find_classes_file,
    find_data_yaml,
    guess_label_dir,
    read_data_yaml_names,
    resolve_label_dir,
)


def write(path, text):
    os.makedirs(osp.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def make_dataset(tmp_path):
    root = tmp_path / "20260608_face"
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    return root


def test_guess_label_dir_preserves_split(tmp_path):
    root = make_dataset(tmp_path)
    assert guess_label_dir(str(root / "images" / "train")) == str(
        root / "labels" / "train"
    )


def test_guess_label_dir_without_images_segment(tmp_path):
    image_dir = tmp_path / "shots"
    image_dir.mkdir()
    (tmp_path / "labels").mkdir()
    assert guess_label_dir(str(image_dir)) == str(tmp_path / "labels")


def test_guess_label_dir_returns_candidate_when_nothing_exists(tmp_path):
    image_dir = tmp_path / "images" / "val"
    image_dir.mkdir(parents=True)
    assert guess_label_dir(str(image_dir)) == str(tmp_path / "labels" / "val")


def test_resolve_label_dir_drills_into_split_subdirectory(tmp_path):
    root = make_dataset(tmp_path)
    chosen = str(root / "labels")
    assert resolve_label_dir(chosen, str(root / "images" / "train")) == str(
        root / "labels" / "train"
    )


def test_resolve_label_dir_keeps_directory_with_direct_files(tmp_path):
    root = make_dataset(tmp_path)
    write(str(root / "labels" / "a.txt"), "0 0.5 0.5 0.2 0.2\n")
    chosen = str(root / "labels")
    assert resolve_label_dir(chosen, str(root / "images" / "train")) == chosen


def test_detect_class_source_prefers_classes_txt(tmp_path):
    root = make_dataset(tmp_path)
    write(str(root / "classes.txt"), "face\nperson\n")
    write(str(root / "data.yaml"), "names: [a, b, c]\n")
    source = detect_class_source(str(root / "images" / "train"))
    assert source.kind == SOURCE_CLASSES
    assert source.names == ("face", "person")


def test_detect_class_source_reads_yaml_names_in_index_order(tmp_path):
    root = make_dataset(tmp_path)
    write(str(root / "data.yaml"), "names:\n  2: c\n  0: a\n  1: b\n")
    source = detect_class_source(str(root / "images" / "train"))
    assert source.kind == SOURCE_YAML
    assert source.names == ("a", "b", "c")


def test_detect_class_source_skips_unreadable_yaml(tmp_path):
    root = make_dataset(tmp_path)
    write(str(root / "data.yaml"), "names: not-a-list\n")
    assert detect_class_source(str(root / "images" / "train")) is None


def test_read_data_yaml_names_list(tmp_path):
    path = tmp_path / "data.yaml"
    path.write_text("names: [cat, dog]\n", encoding="utf-8")
    assert read_data_yaml_names(str(path)) == ["cat", "dog"]


def test_find_classes_file_prefers_closest_ancestor(tmp_path):
    root = make_dataset(tmp_path)
    write(str(root / "classes.txt"), "outer\n")
    write(str(root / "images" / "classes.txt"), "inner\n")
    found = find_classes_file(str(root / "images" / "train"))
    assert found == str(root / "images" / "classes.txt")


def test_find_data_yaml_returns_none_without_file(tmp_path):
    root = make_dataset(tmp_path)
    assert find_data_yaml(str(root / "images" / "train")) is None


def test_dataset_category_names_uses_repository_order():
    class Repository:
        def category_counts(self):
            return [
                {"name": "zebra", "object_count": 3},
                {"name": "cat", "object_count": 1},
                {"name": "", "object_count": 0},
            ]

    assert dataset_category_names(Repository()) == ["zebra", "cat"]


def test_dataset_category_names_tolerates_missing_repository():
    class Broken:
        def category_counts(self):
            raise RuntimeError("database is gone")

    assert dataset_category_names(None) == []
    assert dataset_category_names(Broken()) == []


def test_class_source_kind_constants_are_distinct():
    assert len({SOURCE_DATASET, SOURCE_CLASSES, SOURCE_YAML}) == 3
    assert ClassSource(("a",), SOURCE_DATASET).has_names


def test_yaml_dependency_is_used(tmp_path):
    # Guard against accidentally dropping the yaml import of this module.
    path = tmp_path / "data.yaml"
    path.write_text(yaml.safe_dump({"names": {"0": "a"}}), encoding="utf-8")
    assert read_data_yaml_names(str(path)) == ["a"]
