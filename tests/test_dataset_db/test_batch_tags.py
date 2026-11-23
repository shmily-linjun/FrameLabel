"""Tests for batch image-tag writes (file-list context menu, fork.32)."""

import json

from anylabeling.services.dataset.codec import ImageAnnotation
from anylabeling.services.dataset.connection import DatasetDatabase
from anylabeling.services.dataset.repository import DatasetRepository
from anylabeling.views.labeling.utils.batch_tags import (
    apply_image_tags,
    merge_image_tags,
)
from anylabeling.views.labeling.utils.file_meta import read_file_meta

AUTHOR = "alice"
STAMP = "2026-11-23T10:00:00+08:00"


def _image(directory, name="a.png"):
    path = directory / name
    path.write_bytes(b"not-a-real-image")
    return path


def _label(path, tags=(), shapes=None):
    data = {
        "version": "4.3.2",
        "flags": {},
        "shapes": shapes or [],
        "imagePath": path.name,
        "imageData": None,
        "imageHeight": 8,
        "imageWidth": 8,
        "tags": list(tags),
    }
    path.with_suffix(".json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    return path.with_suffix(".json")


def _make_repository(root):
    database = DatasetDatabase.create(root / "xanylabeling.db", name="tags")
    return database, DatasetRepository(database)


# -- merge rule ----------------------------------------------------------
def test_merge_adds_only_missing_tags_and_keeps_order():
    assert merge_image_tags(["a", "b"], ["b", "c"], False) == [
        "a",
        "b",
        "c",
    ]
    assert merge_image_tags(["a"], ["a"], False) == ["a"]


def test_merge_replaces_and_normalizes():
    assert merge_image_tags(["a", "b"], ["c", " c ", ""], True) == ["c"]
    assert merge_image_tags(["a"], [], True) == []


# -- JSON mode -----------------------------------------------------------
def test_add_mode_merges_and_stamps_attribution(dataset_tmp):
    image = _image(dataset_tmp)
    label = _label(image, tags=["old"], shapes=[{"label": "car"}])

    result = apply_image_tags(
        [image],
        ["new", "old"],
        replace=False,
        author=AUTHOR,
        modified_at=STAMP,
    )

    assert result.updated == [str(image)]
    assert result.tags_by_path[str(image)] == ["old", "new"]
    data = json.loads(label.read_text(encoding="utf-8"))
    assert data["tags"] == ["old", "new"]
    assert data["shapes"] == [{"label": "car"}]
    assert data["author"] == AUTHOR
    assert data["modified_at"] == STAMP


def test_replace_mode_can_clear_all_tags(dataset_tmp):
    image = _image(dataset_tmp)
    label = _label(image, tags=["a", "b"])

    result = apply_image_tags(
        [image], [], replace=True, author=AUTHOR, modified_at=STAMP
    )

    assert result.updated == [str(image)]
    data = json.loads(label.read_text(encoding="utf-8"))
    assert data["tags"] == []
    assert data["author"] == AUTHOR


def test_unchanged_image_is_not_rewritten(dataset_tmp):
    image = _image(dataset_tmp)
    label = _label(image, tags=["a"])
    before = label.read_bytes()

    result = apply_image_tags(
        [image], ["a"], replace=True, author=AUTHOR, modified_at=STAMP
    )

    assert result.updated == []
    assert result.unchanged == [str(image)]
    assert label.read_bytes() == before


def test_missing_label_file_is_created(dataset_tmp):
    image = _image(dataset_tmp)

    result = apply_image_tags(
        [image], ["defect"], replace=True, author=AUTHOR, modified_at=STAMP
    )

    assert result.updated == [str(image)]
    meta = read_file_meta(image)
    assert meta.tags == ("defect",)
    data = json.loads(
        image.with_suffix(".json").read_text(encoding="utf-8")
    )
    assert data["author"] == AUTHOR
    assert data["shapes"] == []


def test_malformed_label_file_is_reported_and_not_overwritten(dataset_tmp):
    image = _image(dataset_tmp)
    label = image.with_suffix(".json")
    label.write_text("{not json", encoding="utf-8")

    result = apply_image_tags(
        [image], ["defect"], replace=True, author=AUTHOR, modified_at=STAMP
    )

    assert result.failed == [str(image)]
    assert label.read_text(encoding="utf-8") == "{not json"


# -- database mode -------------------------------------------------------
def test_database_mode_merges_and_stamps(dataset_tmp):
    database, repository = _make_repository(dataset_tmp)
    try:
        image = _image(dataset_tmp)
        image_id = repository.add_image(image.name)
        repository.save_annotation(
            image_id,
            ImageAnnotation(
                shapes=[
                    {
                        "label": "car",
                        "shape_id": "s1",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [4, 0], [4, 4], [0, 4]],
                    }
                ],
                tags=["old"],
            ),
        )

        result = apply_image_tags(
            [image],
            ["new"],
            replace=False,
            repository=repository,
            dataset_root=str(dataset_tmp),
            author=AUTHOR,
            modified_at=STAMP,
        )

        assert result.updated == [str(image)]
        assert repository.load_annotation(image_id).tags == ["old", "new"]
        row = database.query_one(
            "SELECT editor, modified_at FROM image_file WHERE id = ?",
            (image_id,),
        )
        assert row["editor"] == AUTHOR
        assert row["modified_at"] == STAMP

        # Re-applying the same tags is a no-op.
        again = apply_image_tags(
            [image],
            ["new"],
            replace=False,
            repository=repository,
            dataset_root=str(dataset_tmp),
            author=AUTHOR,
            modified_at=STAMP,
        )
        assert again.updated == []
        assert again.unchanged == [str(image)]
    finally:
        database.close()


def test_database_mode_unknown_image_is_reported(dataset_tmp):
    database, repository = _make_repository(dataset_tmp)
    try:
        image = _image(dataset_tmp)
        result = apply_image_tags(
            [image],
            ["defect"],
            replace=True,
            repository=repository,
            dataset_root=str(dataset_tmp),
            author=AUTHOR,
            modified_at=STAMP,
        )
        assert result.failed == [str(image)]
    finally:
        database.close()
