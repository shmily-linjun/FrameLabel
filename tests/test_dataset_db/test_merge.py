"""Dataset merge tests (fork.53, T11/P1)."""

from __future__ import annotations

import os

from anylabeling.services.dataset.codec import ImageAnnotation
from anylabeling.services.dataset.connection import DatasetDatabase
from anylabeling.services.dataset.merge import (
    MergeOptions,
    create_target_dataset,
    merge_datasets,
    plan_merge,
)
from anylabeling.services.dataset.repository import DatasetRepository


def _write_image(root, rel_path, payload=b"fake-image-bytes"):
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _make_source(root, name, images):
    """Create a dataset and return ``(db_path, dataset_root)``."""

    db_path = os.path.join(str(root), "xanylabeling.db")
    database = DatasetDatabase.create(db_path, name=name)
    repository = DatasetRepository(database)
    for spec in images:
        _write_image(root, spec["rel_path"], spec.get("payload", b"image"))
        stat = os.stat(os.path.join(str(root), spec["rel_path"]))
        image_id = repository.add_image(
            spec["rel_path"],
            split=spec.get("split", "none"),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )
        if spec.get("shapes") or spec.get("tags"):
            repository.save_annotation(
                image_id,
                ImageAnnotation(
                    shapes=spec.get("shapes", []),
                    tags=spec.get("tags", []),
                ),
            )
    database.close()
    return db_path, str(root)


def _make_target(root, name, existing=()):
    db_path = os.path.join(str(root), "xanylabeling.db")
    database = DatasetDatabase.create(db_path, name=name)
    repository = DatasetRepository(database)
    for rel_path in existing:
        _write_image(root, rel_path)
        repository.add_image(
            rel_path,
            size_bytes=os.path.getsize(os.path.join(str(root), rel_path)),
        )
    database.close()
    return db_path, str(root)


def test_plan_and_merge_union_with_namespace_copy(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_db, source_path = _make_source(
        source_root,
        "Source",
        [
            {
                "rel_path": "images/train/a.jpg",
                "split": "train",
                "shapes": [
                    {"label": "cat", "points": [[0, 0], [4, 4]]}
                ],
                "tags": ["aaa"],
            },
            {"rel_path": "images/none/b.jpg", "split": "none"},
        ],
    )
    target_root = tmp_path / "target"
    target_root.mkdir()
    target_db, _target_path = _make_target(
        target_root, "Target", existing=("images/existing.jpg",)
    )

    plan = plan_merge([source_db], target_db)
    assert plan.new_images == 2
    assert plan.new_objects == 1
    assert plan.duplicate_images == 0
    assert plan.missing_images == 0
    assert [row.action for row in plan.categories] == ["created"]

    report = merge_datasets([source_db], target_db)
    assert report.imported_images == 2
    assert report.imported_objects == 1
    assert report.errors == []
    assert report.import_session_id is not None
    assert report.backup_path and os.path.isfile(report.backup_path)

    database = DatasetDatabase.open(target_db)
    try:
        repository = DatasetRepository(database)
        rows = repository.list_images()
        imported = [
            row
            for row in rows
            if row["rel_path"].startswith("imported/")
        ]
        assert len(imported) == 2
        assert {row["split"] for row in imported} == {"train", "none"}
        annotations = [
            repository.load_annotation(row["id"]) for row in imported
        ]
        labels = {
            shape["label"]
            for annotation in annotations
            for shape in annotation.shapes
        }
        assert labels == {"cat"}
        tags = {
            tag for annotation in annotations for tag in annotation.tags
        }
        assert tags == {"aaa"}
        session = database.query_one(
            "SELECT source_format, stats_json FROM import_session"
        )
        assert session["source_format"] == "dataset-merge"
        assert '"imported_images": 2' in session["stats_json"]
    finally:
        database.close()

    # The source dataset is untouched.
    source = DatasetDatabase.open(source_db, read_only=True)
    try:
        assert len(DatasetRepository(source).list_images()) == 2
    finally:
        source.close()


def test_merge_category_mapping_and_split_policy(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_db, _source_path = _make_source(
        source_root,
        "Source",
        [
            {
                "rel_path": "a.jpg",
                "split": "val",
                "shapes": [
                    {"label": "dog", "points": [[0, 0], [4, 4]]}
                ],
            }
        ],
    )
    target_root = tmp_path / "target"
    target_root.mkdir()
    target_db, _target_path = _make_target(target_root, "Target")

    options = MergeOptions(
        category_map={"dog": "animal"}, uniform_split="train"
    )
    report = merge_datasets([source_db], target_db, options)
    assert report.imported_images == 1
    assert report.imported_objects == 1

    database = DatasetDatabase.open(target_db)
    try:
        repository = DatasetRepository(database)
        names = [row["name"] for row in repository.list_categories()]
        assert names == ["animal"]
        [image] = repository.list_images()
        assert image["split"] == "train"
        [annotation] = [repository.load_annotation(image["id"])]
        assert [shape["label"] for shape in annotation.shapes] == ["animal"]
    finally:
        database.close()


def test_merge_skips_missing_source_files_and_reports_duplicates(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_db, _source_path = _make_source(
        source_root,
        "Source",
        [{"rel_path": "a.jpg"}, {"rel_path": "b.jpg"}],
    )
    os.unlink(source_root / "b.jpg")

    target_root = tmp_path / "target"
    target_root.mkdir()
    target_db, _target_path = _make_target(target_root, "Target")
    # Seed an image whose name/size/mtime matches the source one.
    source_stat = os.stat(source_root / "a.jpg")
    database = DatasetDatabase.open(target_db)
    try:
        repository = DatasetRepository(database)
        target_image = target_root / "a.jpg"
        target_image.write_bytes(b"image")
        repository.add_image(
            "a.jpg",
            size_bytes=source_stat.st_size,
            mtime_ns=source_stat.st_mtime_ns,
        )
    finally:
        database.close()

    plan = plan_merge([source_db], target_db)
    assert plan.duplicate_images == 1
    assert plan.missing_images == 1
    assert any(issue.reason == "file not found" for issue in plan.issues)

    report = merge_datasets([source_db], target_db)
    assert report.imported_images == 1
    assert report.skipped_images == 1
    assert any("missing file" in error for error in report.errors)


def test_create_target_dataset_and_merge_into_it(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_db, _source_path = _make_source(
        source_root,
        "Source",
        [
            {
                "rel_path": "a.jpg",
                "shapes": [{"label": "cat", "points": [[0, 0], [4, 4]]}],
            }
        ],
    )
    parent = tmp_path / "new"
    parent.mkdir()
    new_db = create_target_dataset(str(parent), "Merged", task="detect")
    assert os.path.isfile(new_db)

    report = merge_datasets([source_db], new_db)
    assert report.imported_images == 1
    assert report.imported_objects == 1
    assert report.target_root == os.path.dirname(new_db)

    database = DatasetDatabase.open(new_db)
    try:
        repository = DatasetRepository(database)
        assert repository.dataset()["name"] == "Merged"
        assert repository.dataset()["task"] == "detect"
        assert len(repository.list_images()) == 1
    finally:
        database.close()
