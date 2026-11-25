"""Registry and overview tests for the dataset center (fork.53)."""

from __future__ import annotations

import os

import pytest

from anylabeling.services.dataset.codec import ImageAnnotation
from anylabeling.services.dataset.connection import DatasetDatabase
from anylabeling.services.dataset.registry import (
    STATE_ACTIVE,
    STATE_DELETED,
    STATE_MISSING,
    RegistryStore,
)
from anylabeling.services.dataset.repository import DatasetRepository


def _make_dataset(root, name="demo", description=""):
    database = DatasetDatabase.create(
        os.path.join(str(root), "xanylabeling.db"),
        name=name,
        description=description,
    )
    return database, DatasetRepository(database)


def test_registry_add_list_check_and_missing(tmp_path):
    dataset_root = tmp_path / "ds1"
    dataset_root.mkdir()
    database, _repository = _make_dataset(dataset_root)
    database.close()
    store = RegistryStore(str(tmp_path / "platform.db"))

    entry = store.add_from_folder(str(dataset_root))
    assert entry.state == STATE_ACTIVE
    assert entry.display_name == "demo"
    assert os.path.normcase(entry.root_path) == os.path.normcase(
        str(dataset_root)
    )
    # Adding the same folder again returns the existing entry.
    assert store.add_from_folder(str(dataset_root)).uuid == entry.uuid
    assert [item.uuid for item in store.list()] == [entry.uuid]

    check = store.check_dataset(entry.db_path)
    assert check.ok and check.name == "demo"

    # A deleted database file flips the entry to missing.
    os.unlink(entry.db_path)
    store.mark_missing(entry.uuid, reason="gone")
    [missing] = store.list()
    assert missing.state == STATE_MISSING
    assert not store.check_dataset(entry.db_path).ok
    actions = [event["action"] for event in store.events(entry.uuid)]
    assert "mark_missing" in actions and "add" in actions


def test_registry_relocate_and_remove_record(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    database, _repository = _make_dataset(first)
    database.close()
    store = RegistryStore(str(tmp_path / "platform.db"))
    entry = store.add_from_folder(str(first))

    moved, _repository = _make_dataset(second)
    moved.close()
    store.relocate(
        entry.uuid, os.path.join(str(second), "xanylabeling.db")
    )
    [relocated] = store.list()
    assert os.path.normcase(relocated.db_path) == os.path.normcase(
        os.path.join(str(second), "xanylabeling.db")
    )
    assert relocated.state == STATE_ACTIVE

    store.remove_record(entry.uuid)
    assert store.list() == []
    assert "remove_record" in [
        event["action"] for event in store.events(entry.uuid)
    ]


def test_registry_rename_and_delete_state(tmp_path):
    root = tmp_path / "ds"
    root.mkdir()
    database, _repository = _make_dataset(root)
    database.close()
    store = RegistryStore(str(tmp_path / "platform.db"))
    entry = store.add_from_folder(str(root))

    renamed = store.rename(entry.uuid, "Renamed")
    assert renamed.display_name == "Renamed"
    with pytest.raises(Exception):
        store.rename(entry.uuid, "  ")

    store.mark_deleted(
        entry.uuid, delete_mode="database", backup_path="C:/backup.db"
    )
    assert store.list() == []
    [deleted] = store.list(include_deleted=True)
    assert deleted.state == STATE_DELETED
    assert deleted.delete_mode == "database"
    assert deleted.backup_path == "C:/backup.db"
    assert deleted.deleted_at


def test_overview_counts_tags_splits_and_metadata(tmp_path):
    root = tmp_path / "ds"
    root.mkdir()
    database, repository = _make_dataset(root)
    try:
        train_id = repository.add_image(
            "images/train/a.jpg", split="train"
        )
        repository.save_annotation(
            train_id,
            ImageAnnotation(
                shapes=[
                    {"label": "cat", "points": [[0, 0], [4, 4]]},
                    {"label": "dog", "points": [[5, 5], [9, 9]]},
                ],
                tags=["aaa", "bbb"],
                description="first",
            ),
        )
        repository.add_image("images/none/b.jpg", split="none")
        repository.add_image("images/trash/c.jpg", split="val")
        trashed = repository.find_image("images/trash/c.jpg")
        repository.delete_image(trashed["id"])

        overview = repository.overview()
        assert overview["totals"] == {
            "images": 2,
            "trashed": 1,
            "objects": 2,
            "categories": 2,
            "tag_kinds": 2,
        }
        assert overview["splits"] == {
            "train": 1,
            "val": 0,
            "test": 0,
            "none": 1,
        }
        tags = {row["tag"]: row["image_count"] for row in overview["tags"]}
        assert tags == {"aaa": 1, "bbb": 1}
        categories = {
            row["name"]: (row["image_count"], row["object_count"])
            for row in overview["categories"]
        }
        assert categories == {"cat": (1, 1), "dog": (1, 1)}

        repository.update_dataset_metadata(
            name="Renamed", description="note"
        )
        dataset = repository.dataset()
        assert dataset["name"] == "Renamed"
        assert dataset["description"] == "note"
        with pytest.raises(Exception):
            repository.update_dataset_metadata(name="")
        with pytest.raises(Exception):
            repository.update_dataset_metadata(description="x" * 10001)
    finally:
        database.close()
