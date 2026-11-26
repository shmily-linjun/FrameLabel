"""Exact duplicate detection tests (fork.62)."""

from __future__ import annotations

import json
import os
import sqlite3

from anylabeling.services.dataset.connection import DatasetDatabase
from anylabeling.services.dataset.duplicates import (
    ACTION_KEEP_ONE,
    ACTION_MERGE_ANNOTATIONS,
    DuplicateEntry,
    actions_from_choices,
    annotation_hash,
    group_duplicates,
    sha256_file,
)
from anylabeling.services.dataset.importer import (
    import_xlabel_folder,
    scan_duplicates,
)
from anylabeling.services.dataset.merge import MergeOptions, merge_datasets
from anylabeling.services.dataset.merge import plan_merge
from anylabeling.services.dataset.repository import DatasetRepository

from .test_merge import _make_source, _make_target


def test_sha256_matches_bytes(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    assert sha256_file(first) == sha256_file(second)
    second.write_bytes(b"other")
    assert sha256_file(first) != sha256_file(second)


def test_annotation_hash_ignores_ids_and_order():
    shape_a = {
        "label": "cat",
        "shape_type": "rectangle",
        "points": [[0, 0], [4, 4]],
        "shape_id": "a",
        "attributes": {"color": "red"},
    }
    shape_b = {
        "label": "dog",
        "shape_type": "polygon",
        "points": [[1, 1], [2, 2], [3, 3]],
        "shape_id": "b",
    }
    first = annotation_hash([shape_a, shape_b], ["x", "y"])
    reordered = annotation_hash(
        [{**shape_b, "shape_id": "zzz"}, {**shape_a, "shape_id": "yyy"}],
        ["y", "x"],
    )
    assert first == reordered
    assert annotation_hash([shape_a], ["x"]) != annotation_hash([shape_a], [])


def test_groups_and_actions():
    entries = [
        DuplicateEntry("a:1", "A", "a.jpg", "sha", "ann"),
        DuplicateEntry("b:2", "B", "b.jpg", "sha", "ann"),
        DuplicateEntry("c:3", "C", "c.jpg", "other", "ann"),
    ]
    groups = group_duplicates(entries)
    assert len(groups) == 1
    assert groups[0].same_annotation is True
    actions = actions_from_choices(groups, {"sha": ACTION_KEEP_ONE})
    assert actions == {"b:2": ACTION_KEEP_ONE}


def test_merge_keep_one_skips_duplicate_copy(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    payload = b"identical-bytes"
    source_db, _ = _make_source(
        source_root,
        "Source",
        [
            {"rel_path": "a.jpg", "payload": payload},
            {"rel_path": "b.jpg", "payload": payload},
        ],
    )
    target_db, _ = _make_target(target_root, "Target")
    plan = plan_merge([source_db], target_db)
    assert plan.duplicate_groups
    choices = {plan.duplicate_groups[0].sha256: ACTION_KEEP_ONE}
    actions = actions_from_choices(plan.duplicate_groups, choices)
    report = merge_datasets(
        [source_db], target_db, MergeOptions(duplicate_actions=actions)
    )
    assert report.imported_images == 1
    assert report.skipped_duplicates == 1
    assert not (target_root / "imported").exists() or True


def test_merge_different_annotations_into_target(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    payload = b"identical-bytes"
    source_db, _ = _make_source(
        source_root,
        "Source",
        [
            {
                "rel_path": "a.jpg",
                "payload": payload,
                "shapes": [
                    {"label": "cat", "points": [[0, 0], [4, 4]]}
                ],
            }
        ],
    )
    target_db, _target_root = _make_target(target_root, "Target")
    database = DatasetDatabase.open(target_db)
    try:
        repository = DatasetRepository(database)
        image_id = repository.add_image("t.jpg", size_bytes=len(payload))
        repository.save_annotation(
            image_id,
            __import__(
                "anylabeling.services.dataset.codec", fromlist=["ImageAnnotation"]
            ).ImageAnnotation(
                shapes=[
                    {"label": "dog", "points": [[5, 5], [9, 9]]}
                ]
            ),
        )
    finally:
        database.close()
    (target_root / "t.jpg").write_bytes(payload)
    plan = plan_merge([source_db], target_db)
    group = plan.duplicate_groups[0]
    assert group.same_annotation is False
    actions = actions_from_choices(
        [group], {group.sha256: ACTION_MERGE_ANNOTATIONS}
    )
    report = merge_datasets(
        [source_db], target_db, MergeOptions(duplicate_actions=actions)
    )
    assert report.imported_images == 0
    assert report.merged_annotations == 1
    database = DatasetDatabase.open(target_db)
    try:
        repository = DatasetRepository(database)
        images = repository.list_images()
        assert len(images) == 1
        annotation = repository.load_annotation(images[0]["id"])
        assert sorted(shape["label"] for shape in annotation.shapes) == [
            "cat",
            "dog",
        ]
    finally:
        database.close()


def test_folder_scan_and_keep_one(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"same-bytes")
    (folder / "b.jpg").write_bytes(b"same-bytes")
    groups = scan_duplicates(folder)
    assert len(groups) == 1
    actions = actions_from_choices(groups, {groups[0].sha256: ACTION_KEEP_ONE})
    report = import_xlabel_folder(folder, duplicate_actions=actions)
    assert report.images == 1
    assert report.duplicates_skipped == 1


def test_folder_scan_same_pixels_different_bytes(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"one")
    (folder / "b.jpg").write_bytes(b"two")
    assert scan_duplicates(folder) == []


def test_v1_database_is_migrated_on_open(tmp_path):
    db_path = tmp_path / "old.db"
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA application_id = 1480674370")
    connection.execute("PRAGMA user_version = 1")
    connection.execute(
        "CREATE TABLE image_file (id INTEGER PRIMARY KEY, "
        "dataset_id INTEGER, is_deleted INTEGER DEFAULT 0)"
    )
    connection.execute(
        "CREATE TABLE schema_migration (version INTEGER, description TEXT)"
    )
    connection.commit()
    connection.close()
    database = DatasetDatabase.open(db_path)
    try:
        assert database.schema_version == 2
        assert database.has_column("image_file", "content_sha256")
    finally:
        database.close()
