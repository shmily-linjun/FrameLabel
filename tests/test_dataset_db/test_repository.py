import json

import pytest

from anylabeling.services.dataset.codec import ImageAnnotation
from anylabeling.services.dataset.connection import DatasetDatabase
from anylabeling.services.dataset.errors import (
    DatasetConflictError,
    DatasetNotFoundError,
)
from anylabeling.services.dataset.repository import DatasetRepository


def rectangle(label, shape_id):
    return {
        "label": label,
        "score": None,
        "points": [[1.0, 2.0], [9.0, 2.0], [9.0, 8.0], [1.0, 8.0]],
        "group_id": None,
        "difficult": False,
        "shape_type": "rectangle",
        "flags": {},
        "attributes": {"occluded": False},
        "kie_linking": [],
        "shape_id": shape_id,
        "review_status": "pending",
    }


def polygon(label, shape_id):
    return {
        "label": label,
        "score": 0.75,
        "points": [[1.0, 1.0], [5.0, 1.0], [5.0, 5.0]],
        "group_id": 2,
        "difficult": True,
        "shape_type": "polygon",
        "flags": {"partial": True},
        "attributes": {"note": "x"},
        "kie_linking": [],
        "shape_id": shape_id,
        "review_status": "missed",
        "source": "auto_labeling",
        "source_model": "demo",
    }


def make_repository(dataset_tmp):
    database = DatasetDatabase.create(dataset_tmp / "xanylabeling.db", name="demo")
    return database, DatasetRepository(database)


def test_save_and_load_roundtrip(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image(
            "images/a.png", width=64, height=48, split="train"
        )
        annotation = ImageAnnotation(
            shapes=[rectangle("bolt", "s1"), polygon("nut", "s2")],
            flags={"blurry": False},
            tags=["a", "b"],
            description="demo image",
            split="val",
            relations=[
                {"subject_id": "s1", "object_id": "s2", "label": "has", "score": None}
            ],
            extra={"vqaData": {"question": "q"}},
        )
        assert repository.save_annotation(
            image_id,
            annotation,
            editor="alice",
            modified_at="2026-11-20T12:00:00+08:00",
        ) == 2

        loaded = repository.load_annotation(image_id)
        assert [shape["label"] for shape in loaded.shapes] == ["bolt", "nut"]
        assert [shape["shape_id"] for shape in loaded.shapes] == ["s1", "s2"]
        assert loaded.shapes[0]["points"] == [
            [1.0, 2.0],
            [9.0, 2.0],
            [9.0, 8.0],
            [1.0, 8.0],
        ]
        assert loaded.shapes[1]["difficult"] is True
        assert loaded.shapes[1]["review_status"] == "missed"
        assert loaded.shapes[1]["source"] == "auto_labeling"
        assert loaded.tags == ["a", "b"]
        assert loaded.flags == {"blurry": False}
        assert loaded.description == "demo image"
        assert loaded.split == "val"
        assert loaded.relations == [
            {"subject_id": "s1", "object_id": "s2", "label": "has", "score": None}
        ]
        assert loaded.extra == {"vqaData": {"question": "q"}}

        row = database.query_one("SELECT * FROM image_file WHERE id = ?", (image_id,))
        assert row["editor"] == "alice"
        assert row["modified_at"] == "2026-11-20T12:00:00+08:00"
        geometry = json.loads(
            database.query_one(
                "SELECT points_json FROM annotation_object WHERE uuid = 's1'"
            )["points_json"]
        )
        assert geometry["schema_version"] == 1
        assert geometry["outer"][0] == [1.0, 2.0]
        assert geometry["holes"] == []
    finally:
        database.close()


def test_upsert_soft_delete_and_restore(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image("images/a.png", width=64, height=48)
        original = ImageAnnotation(
            shapes=[rectangle("bolt", "s1"), polygon("nut", "s2")],
            tags=["a"],
        )
        repository.save_annotation(image_id, original)

        loaded = repository.load_annotation(image_id)
        first = loaded.shapes[0]
        first["label"] = "bolt2"
        first["points"] = [[2.0, 2.0], [8.0, 2.0], [8.0, 8.0], [2.0, 8.0]]
        third = rectangle("washer", "s3")
        loaded.shapes = [first, third]
        loaded.tags = ["c"]
        loaded.relations = []
        repository.save_annotation(
            image_id, loaded, editor="bob", modified_at="2026-11-20T13:00:00+08:00"
        )

        assert [
            shape["shape_id"] for shape in repository.load_annotation(image_id).shapes
        ] == ["s1", "s3"]
        deleted = database.query_one(
            "SELECT is_deleted FROM annotation_object WHERE uuid = 's2'"
        )
        assert deleted["is_deleted"] == 1
        assert database.query_one(
            "SELECT editor FROM image_file WHERE id = ?", (image_id,)
        )["editor"] == "bob"

        # Re-adding the same uuid revives the existing row instead of
        # inserting a duplicate.
        loaded = repository.load_annotation(image_id)
        loaded.shapes.append(polygon("nut", "s2"))
        repository.save_annotation(image_id, loaded)
        rows = database.query(
            "SELECT is_deleted FROM annotation_object WHERE uuid = 's2'"
        )
        assert len(rows) == 1
        assert rows[0]["is_deleted"] == 0
        assert len(repository.load_annotation(image_id).shapes) == 3
    finally:
        database.close()


def test_rewrite_categories_renames_and_soft_deletes(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image("images/rewrite.png")
        repository.save_annotation(
            image_id,
            ImageAnnotation(
                shapes=[rectangle("bolt", "s1"), polygon("nut", "s2")]
            ),
        )
        changed = repository.rewrite_categories(
            [image_id], {"bolt": "screw"}, {"nut"}
        )
        assert changed == 2
        loaded = repository.load_annotation(image_id)
        assert [shape["label"] for shape in loaded.shapes] == ["screw"]
        counts = {row["name"]: row["object_count"] for row in repository.category_counts()}
        assert counts["screw"] == 1
        assert counts["nut"] == 0
    finally:
        database.close()


def test_image_summaries_sql_filters(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        first = repository.add_image("a.png", split="train")
        repository.save_annotation(
            first, ImageAnnotation(shapes=[rectangle("bolt", "s1")])
        )
        second = repository.add_image("b.png", split="val")
        repository.save_annotation(
            second, ImageAnnotation(shapes=[polygon("nut", "s2")])
        )
        repository.add_image("c.png", split="none")

        assert [row["rel_path"] for row in repository.image_summaries(
            labels=["bolt"]
        )] == ["a.png"]
        assert [row["rel_path"] for row in repository.image_summaries(
            split="val"
        )] == ["b.png"]
        assert [row["rel_path"] for row in repository.image_summaries(
            objectless=True
        )] == ["c.png"]
        assert [row["rel_path"] for row in repository.image_summaries(
            filename="b.png"
        )] == ["b.png"]
        assert repository.image_summaries(
            labels=["bolt"], split="val"
        ) == []
    finally:
        database.close()


def test_statistics_and_category_counts(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image(
            "images/stats.png", width=64, height=48, split="val"
        )
        repository.save_annotation(
            image_id,
            ImageAnnotation(
                shapes=[rectangle("bolt", "s1"), polygon("nut", "s2")],
                tags=["t1"],
            ),
        )
        rows = repository.statistics_rows()
        assert rows == [
            {"path": "images/stats.png", "split": "val", "labels": ["bolt", "nut"]}
        ]
        counts = repository.category_counts()
        assert counts == [
            {"name": "bolt", "object_count": 1},
            {"name": "nut", "object_count": 1},
        ]
    finally:
        database.close()


def test_category_order_follows_sort_index(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image("images/order.png")
        repository.save_annotation(
            image_id,
            ImageAnnotation(
                shapes=[
                    rectangle("bolt", "s1"),
                    polygon("nut", "s2"),
                    rectangle("washer", "s3"),
                ]
            ),
        )
        # New categories are appended in first-use order.
        assert [
            row["name"] for row in repository.category_counts()
        ] == ["bolt", "nut", "washer"]

        assert repository.set_category_order(
            ["washer", "bolt", "nut"]
        ) is True
        assert [
            row["name"] for row in repository.category_counts()
        ] == ["washer", "bolt", "nut"]
        assert [
            row["name"] for row in repository.list_categories()
        ] == ["washer", "bolt", "nut"]

        # Unknown or duplicated names are rejected without a partial write.
        assert repository.set_category_order(["bolt", "ghost"]) is False
        assert repository.set_category_order(["bolt", "bolt"]) is False
        assert [
            row["name"] for row in repository.category_counts()
        ] == ["washer", "bolt", "nut"]
    finally:
        database.close()


def test_image_summaries_and_split_update(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image(
            "images/summary.png", width=64, height=48, split="train"
        )
        repository.save_annotation(
            image_id,
            ImageAnnotation(
                shapes=[rectangle("a", "s1"), rectangle("b", "s2")],
                tags=["t1", "t2"],
            ),
            editor="alice",
        )
        rows = repository.image_summaries()
        assert len(rows) == 1
        assert rows[0]["id"] == image_id
        assert rows[0]["object_count"] == 2
        assert rows[0]["tags"] == ["t1", "t2"]
        assert rows[0]["split"] == "train"

        assert repository.set_split(image_id, "val") is True
        assert repository.find_image("images/summary.png")["split"] == "val"
    finally:
        database.close()


def test_polygon_holes_and_unknown_shape_keys_roundtrip(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image("images/holes.png", width=64, height=48)
        shape = polygon("hole", "s1")
        shape["holes"] = [[[2.0, 2.0], [3.0, 2.0], [3.0, 3.0]]]
        shape["iscrowd"] = True
        shape["text"] = "ocr"
        repository.save_annotation(image_id, ImageAnnotation(shapes=[shape]))
        loaded = repository.load_annotation(image_id).shapes[0]
        assert loaded["holes"] == [[[2.0, 2.0], [3.0, 2.0], [3.0, 3.0]]]
        assert loaded["iscrowd"] is True
        assert loaded["text"] == "ocr"
    finally:
        database.close()


def test_duplicate_shape_id_is_rejected(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image("images/a.png", width=64, height=48)
        annotation = ImageAnnotation(
            shapes=[rectangle("bolt", "s1"), rectangle("bolt", "s1")]
        )
        with pytest.raises(Exception):
            repository.save_annotation(image_id, annotation)
    finally:
        database.close()


def test_recycle_bin_roundtrip_and_restore_conflict(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image("images/a.png", width=64, height=48)
        repository.save_annotation(image_id, ImageAnnotation(shapes=[rectangle("bolt", "s1")]))

        assert repository.delete_image(image_id) is True
        assert repository.get_image(image_id) is None
        assert repository.list_images() == []
        trash = repository.list_trash()
        assert len(trash) == 1
        assert trash[0]["deleted_at"]
        with pytest.raises(DatasetNotFoundError):
            repository.load_annotation(image_id)

        assert repository.restore_image(image_id) is True
        assert repository.get_image(image_id)["is_deleted"] == 0
        assert repository.list_trash() == []

        repository.delete_image(image_id)
        # A second active row on the same path makes restore ambiguous.
        repository.add_image("images/a.png", width=64, height=48)
        with pytest.raises(DatasetConflictError):
            repository.restore_image(image_id)

        assert repository.purge_image(image_id) is True
        assert repository.get_image(image_id, include_deleted=True) is None
    finally:
        database.close()


def test_rel_path_is_case_insensitive_on_windows(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        first = repository.add_image("images/A.png", width=10, height=10)
        second = repository.add_image("images/a.png", width=20, height=20)
        assert first == second
        assert len(repository.list_images()) == 1
        assert repository.get_image(first)["width"] == 20
    finally:
        database.close()


def test_add_image_updates_metadata_without_losing_imported_at(dataset_tmp):
    database, repository = make_repository(dataset_tmp)
    try:
        image_id = repository.add_image("images/a.png", width=10, height=10)
        imported_at = database.query_one(
            "SELECT imported_at FROM image_file WHERE id = ?", (image_id,)
        )["imported_at"]
        repository.add_image(
            "images/a.png",
            width=20,
            height=30,
            split="test",
            description="updated",
        )
        row = database.query_one("SELECT * FROM image_file WHERE id = ?", (image_id,))
        assert row["imported_at"] == imported_at
        assert row["width"] == 20
        assert row["split"] == "test"
        assert row["description"] == "updated"
    finally:
        database.close()
