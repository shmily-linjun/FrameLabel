"""Tests for storing converted uploads in a dataset database (fork.49)."""

import os.path as osp

import numpy as np
from PIL import Image

from anylabeling.services.dataset import DatasetDatabase, DatasetRepository
from anylabeling.services.dataset.annotation_import import (
    OUTCOME_FAILED,
    OUTCOME_SKIPPED,
    OUTCOME_WRITTEN,
    AnnotationImportResult,
    build_annotation,
    relative_to_root,
    store_annotation,
    store_annotations,
)
from anylabeling.services.dataset.codec import ImageAnnotation
from anylabeling.services.dataset.importer import import_xlabel_folder
from anylabeling.views.labeling.label_converter import LabelConverter


def make_dataset(root, names=("a", "b")):
    image_dir = root / "images" / "train"
    image_dir.mkdir(parents=True)
    for name in names:
        Image.fromarray(np.zeros((100, 200, 3), np.uint8)).save(
            image_dir / f"{name}.png"
        )
    import_xlabel_folder(str(root))
    database = DatasetDatabase.open(root / "xanylabeling.db")
    repository = DatasetRepository(database)
    return repository, database, image_dir


def payload_for(image_dir, name, shapes=1):
    label = image_dir.parent.parent / "labels" / "train" / f"{name}.txt"
    label.parent.mkdir(parents=True, exist_ok=True)
    label.write_text(
        "0 0.1 0.1 0.2 0.1 0.2 0.2\n" if shapes else "",
        encoding="utf-8",
    )
    converter = LabelConverter(classes=["face"], classes_source="dataset")
    return converter.yolo_to_custom(
        input_file=str(label),
        output_file="",
        image_file=str(image_dir / f"{name}.png"),
        mode="seg",
        write=False,
    )


def test_relative_to_root_rejects_outside_paths(dataset_tmp):
    inside = dataset_tmp / "images" / "a.png"
    inside.parent.mkdir(parents=True)
    inside.touch()
    assert relative_to_root(str(inside), str(dataset_tmp)) == "images/a.png"
    try:
        relative_to_root(str(dataset_tmp.parent / "other.png"), str(dataset_tmp))
    except ValueError as error:
        assert "outside" in str(error)
    else:  # pragma: no cover - the assertion is the point
        raise AssertionError("outside path was accepted")


def test_store_annotation_writes_shapes_and_categories(dataset_tmp):
    repository, database, image_dir = make_dataset(dataset_tmp)
    try:
        payload = payload_for(image_dir, "a")
        outcome, count, reason = store_annotation(
            repository, dataset_tmp, str(image_dir / "a.png"), payload
        )
        assert (outcome, count, reason) == (OUTCOME_WRITTEN, 1, "")
        image = repository.find_image("images/train/a.png")
        annotation = repository.load_annotation(image["id"])
        assert [shape["label"] for shape in annotation.shapes] == ["face"]
        assert annotation.shapes[0]["shape_type"] == "polygon"
        assert [
            category["name"] for category in repository.list_categories()
        ] == ["face"]
    finally:
        database.close()


def test_store_annotation_preserve_existing_appends(dataset_tmp):
    repository, database, image_dir = make_dataset(dataset_tmp)
    try:
        image_path = str(image_dir / "a.png")
        payload = payload_for(image_dir, "a")
        store_annotation(repository, dataset_tmp, image_path, payload)
        store_annotation(
            repository,
            dataset_tmp,
            image_path,
            payload,
            preserve_existing=True,
        )
        image = repository.find_image("images/train/a.png")
        assert len(repository.load_annotation(image["id"]).shapes) == 2
    finally:
        database.close()


def test_store_annotation_without_preserve_replaces(dataset_tmp):
    repository, database, image_dir = make_dataset(dataset_tmp)
    try:
        image_path = str(image_dir / "a.png")
        payload = payload_for(image_dir, "a", shapes=0)
        store_annotation(repository, dataset_tmp, image_path, payload)
        payload = payload_for(image_dir, "a")
        store_annotation(repository, dataset_tmp, image_path, payload)
        image = repository.find_image("images/train/a.png")
        assert len(repository.load_annotation(image["id"]).shapes) == 1

        store_annotation(repository, dataset_tmp, image_path, {"shapes": []})
        image = repository.find_image("images/train/a.png")
        assert repository.load_annotation(image["id"]).shapes == []
    finally:
        database.close()


def test_store_annotation_skips_unregistered_image(dataset_tmp):
    repository, database, image_dir = make_dataset(dataset_tmp)
    try:
        outside = dataset_tmp / "images" / "train" / "late.png"
        Image.fromarray(np.zeros((10, 10, 3), np.uint8)).save(outside)
        payload = payload_for(image_dir, "a")
        outcome, count, reason = store_annotation(
            repository, dataset_tmp, str(outside), payload
        )
        assert (outcome, count) == (OUTCOME_SKIPPED, 0)
        assert "not registered" in reason
    finally:
        database.close()


def test_store_annotations_aggregates_outcomes(dataset_tmp):
    repository, database, image_dir = make_dataset(dataset_tmp)
    try:
        items = [
            (str(image_dir / "a.png"), payload_for(image_dir, "a")),
            (str(image_dir / "b.png"), payload_for(image_dir, "b")),
            (str(dataset_tmp / "missing.png"), {"shapes": []}),
        ]
        result = store_annotations(repository, dataset_tmp, items)
        assert isinstance(result, AnnotationImportResult)
        assert result.written_count == 2
        assert result.object_count == 2
        assert len(result.skipped) == 1
    finally:
        database.close()


def test_build_annotation_keeps_existing_metadata():
    existing = ImageAnnotation(
        shapes=[{"label": "old", "shape_type": "rectangle", "points": []}],
        flags={"reviewed": True},
        tags=["night"],
        description="kept",
        split="train",
        relations=[],
        extra={"source": "import"},
    )
    annotation = build_annotation(
        {
            "shapes": [
                {"label": "new", "shape_type": "polygon", "points": []}
            ],
            "flags": {"reviewed": False},
        },
        existing,
    )
    assert [shape["label"] for shape in annotation.shapes] == ["old", "new"]
    assert annotation.flags == {"reviewed": True}
    assert annotation.tags == ["night"]
    assert annotation.description == "kept"
    assert annotation.split == "train"
    assert annotation.extra == {"source": "import"}
