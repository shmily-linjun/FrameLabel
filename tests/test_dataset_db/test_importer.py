import hashlib
import json
from pathlib import Path

from PIL import Image

from anylabeling.services.dataset.connection import DatasetDatabase
from anylabeling.services.dataset.importer import import_xlabel_folder
from anylabeling.services.dataset.repository import DatasetRepository


def write_image(path, size=(64, 48)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def xlabel_payload(image_name="img1.png", shapes=None):
    return {
        "version": "4.3.2",
        "flags": {"blurry": False},
        "checked": True,
        "shapes": shapes
        if shapes is not None
        else [
            {
                "label": "bolt",
                "score": None,
                "points": [[1, 2], [9, 2], [9, 8], [1, 8]],
                "group_id": None,
                "difficult": False,
                "shape_type": "rectangle",
                "flags": {},
                "attributes": {"occluded": False},
                "kie_linking": [],
                "shape_id": "s1",
            },
            {
                "label": "nut",
                "score": 0.5,
                "points": [[2, 2], [6, 2], [6, 6], [2, 6]],
                "group_id": None,
                "difficult": False,
                "shape_type": "polygon",
                "flags": {"partial": True},
                "attributes": {},
                "kie_linking": [],
                "shape_id": "s2",
            },
        ],
        "imagePath": image_name,
        "imageData": None,
        "imageHeight": 48,
        "imageWidth": 64,
        "tags": ["line-a", "shift-1"],
        "description": "demo",
        "split": "train",
        "author": "alice",
        "modified_at": "2026-11-20T12:00:00+08:00",
        "relations": [
            {"subject_id": "s1", "object_id": "s2", "label": "has", "score": None}
        ],
        "vqaData": {"question": "q"},
    }


def make_folder(dataset_tmp):
    root = dataset_tmp / "dataset"
    write_image(root / "images" / "img1.png")
    write_image(root / "images" / "img2.jpg")
    write_json(root / "images" / "img1.json", xlabel_payload())
    write_image(root / "images" / "nested" / "img3.png")
    write_json(
        root / "images" / "nested" / "img3.json",
        {
            **xlabel_payload("img3.png"),
            "shapes": [],
            "tags": [],
            "relations": [],
            "author": "none",
            "modified_at": "",
            "split": "none",
        },
    )
    return root


def test_import_xlabel_folder_roundtrip(dataset_tmp):
    root = make_folder(dataset_tmp)
    source_json = root / "images" / "img1.json"
    source_hash = hashlib.sha256(source_json.read_bytes()).hexdigest()

    report = import_xlabel_folder(root)
    assert report.images == 3
    assert report.labeled_images == 2
    assert report.objects == 2
    assert report.tags == 2
    assert report.relations == 1
    assert report.errors == []

    database = DatasetDatabase.open(report.database_path)
    try:
        repository = DatasetRepository(database)
        images = repository.list_images()
        assert [image["rel_path"] for image in images] == [
            "images/img1.png",
            "images/img2.jpg",
            "images/nested/img3.png",
        ]
        assert database.table_counts()["annotation_object"] == 2
        assert database.table_counts()["image_tag"] == 2
        assert database.table_counts()["object_relation"] == 1

        image = repository.find_image("images/img1.png")
        assert image["editor"] == "alice"
        assert image["modified_at"] == "2026-11-20T12:00:00+08:00"
        assert image["split"] == "train"
        assert image["description"] == "demo"
        annotation = repository.load_annotation(image["id"])
        assert [shape["shape_id"] for shape in annotation.shapes] == ["s1", "s2"]
        assert annotation.tags == ["line-a", "shift-1"]
        assert annotation.extra == {"vqaData": {"question": "q"}}
        assert annotation.relations[0]["label"] == "has"

        empty = repository.find_image("images/img2.jpg")
        assert repository.load_annotation(empty["id"]).shapes == []
        assert empty["editor"] == ""
        assert empty["split"] == "none"
    finally:
        database.close()

    assert hashlib.sha256(source_json.read_bytes()).hexdigest() == source_hash


def test_import_twice_skip_then_replace_and_backup(dataset_tmp):
    root = make_folder(dataset_tmp)
    first = import_xlabel_folder(root)
    assert first.objects == 2
    assert first.backup_path is None

    second = import_xlabel_folder(root)
    assert second.backup_path is not None
    assert second.backup_path.is_file()
    assert second.skipped == 3
    assert second.objects == 0

    payload = xlabel_payload()
    payload["shapes"] = payload["shapes"][:1]
    payload["tags"] = ["line-b"]
    payload["relations"] = []
    payload["description"] = "replaced"
    write_json(root / "images" / "img1.json", payload)

    third = import_xlabel_folder(root, overwrite="replace")
    assert third.objects == 1
    assert third.skipped == 0

    database = DatasetDatabase.open(first.database_path)
    try:
        repository = DatasetRepository(database)
        image = repository.find_image("images/img1.png")
        annotation = repository.load_annotation(image["id"])
        assert [shape["shape_id"] for shape in annotation.shapes] == ["s1"]
        assert annotation.tags == ["line-b"]
        assert annotation.relations == []
        assert image["description"] == "replaced"
        assert database.query_one(
            "SELECT COUNT(*) AS n FROM annotation_object "
            "WHERE image_id = ? AND is_deleted = 0",
            (image["id"],),
        )["n"] == 1
    finally:
        database.close()


def test_import_reports_bad_json_and_keeps_going(dataset_tmp):
    root = dataset_tmp / "dataset"
    write_image(root / "a.png")
    (root / "a.json").write_text("{not json", encoding="utf-8")
    write_image(root / "b.png")
    write_json(root / "b.json", xlabel_payload("b.png", shapes=[]))

    report = import_xlabel_folder(root)
    assert report.errors
    assert any("a.png" in error for error in report.errors)
    assert report.images == 1
    database = DatasetDatabase.open(report.database_path)
    try:
        repository = DatasetRepository(database)
        assert [image["rel_path"] for image in repository.list_images()] == ["b.png"]
    finally:
        database.close()
