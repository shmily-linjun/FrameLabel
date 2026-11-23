"""Tests for the Qt-free tag catalog (fork.34)."""

import json
import shutil
import uuid
from pathlib import Path

from anylabeling.views.labeling.utils.tag_library import TagCatalog

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORK_ROOT = _REPO_ROOT / "temporary" / "pytest-tag-library"


def _make_work_dir():
    _WORK_ROOT.mkdir(parents=True, exist_ok=True)
    directory = _WORK_ROOT / uuid.uuid4().hex
    directory.mkdir()
    return directory


def _make_image(directory, name, tags):
    image = directory / name
    image.write_bytes(b"not-an-image")
    label = image.with_suffix(".json")
    label.write_text(
        json.dumps(
            {
                "version": "4.3.2",
                "shapes": [],
                "tags": list(tags),
                "imagePath": name,
            }
        ),
        encoding="utf-8",
    )
    return image


def _label_file_for(path):
    return str(Path(path).with_suffix(".json"))


def test_catalog_counts_and_sorts_by_usage():
    directory = _make_work_dir()
    try:
        first = _make_image(directory, "a.png", ["defect", "blur"])
        second = _make_image(directory, "b.png", ["defect"])
        third = _make_image(directory, "c.png", ["scratch"])

        catalog = TagCatalog()
        entries = catalog.load(
            [first, second, third], _label_file_for
        )

        assert entries == [
            ("defect", 2),
            ("blur", 1),
            ("scratch", 1),
        ]
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_catalog_updates_and_removes_without_rereading():
    directory = _make_work_dir()
    try:
        first = _make_image(directory, "a.png", ["defect"])
        second = _make_image(directory, "b.png", ["blur"])
        catalog = TagCatalog()
        catalog.load([first, second], _label_file_for)

        catalog.update(first, ["scratch", "scratch"])
        assert catalog.entries() == [
            ("blur", 1),
            ("scratch", 1),
        ]

        catalog.remove([second])
        assert catalog.entries() == [("scratch", 1)]
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_catalog_ignores_missing_and_bad_files():
    directory = _make_work_dir()
    try:
        good = _make_image(directory, "good.png", ["defect"])
        bad = directory / "bad.png"
        bad.write_bytes(b"x")
        bad.with_suffix(".json").write_text("{bad json", encoding="utf-8")

        catalog = TagCatalog()
        entries = catalog.load(
            [good, bad, directory / "missing.png"], _label_file_for
        )

        assert entries == [("defect", 1)]
    finally:
        shutil.rmtree(directory, ignore_errors=True)
