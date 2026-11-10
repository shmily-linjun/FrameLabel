"""Tests for the file metadata helpers."""

import datetime
import json
import os
import pathlib
import shutil
import uuid

import pytest
from PIL import Image

from anylabeling import app_info
from anylabeling.views.labeling.label_file import LabelFile
from anylabeling.views.labeling.utils.file_meta import (
    SPLIT_KEYS,
    SPLIT_LABELS,
    SPLIT_NONE,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
    FileMeta,
    format_import_time,
    read_file_meta,
    read_split,
    write_split,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TEMPORARY_ROOT = _REPO_ROOT / "temporary" / "pytest-utils"


@pytest.fixture()
def work_dir():
    # The pytest ``tmp_path`` fixture creates directories with mode 0o700,
    # which the Windows sandbox used for this repository cannot access; keep
    # all temporary files under the repository's own ``temporary`` folder
    # instead.
    directory = _TEMPORARY_ROOT / uuid.uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        try:
            _TEMPORARY_ROOT.rmdir()
        except OSError:
            pass


def _make_image(directory, name="image.png", size=(30, 20)):
    path = directory / name
    Image.new("RGB", size, "red").save(path)
    return str(path)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def _read_json(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def test_split_constants_are_stable():
    assert SPLIT_NONE == "none"
    assert SPLIT_TRAIN == "train"
    assert SPLIT_VAL == "val"
    assert SPLIT_TEST == "test"
    assert SPLIT_KEYS == ("none", "train", "val", "test")
    for key in SPLIT_KEYS:
        assert set(SPLIT_LABELS[key]) == {"zh", "en"}
        assert SPLIT_LABELS[key]["zh"]
        assert SPLIT_LABELS[key]["en"]
    assert len({labels["zh"] for labels in SPLIT_LABELS.values()}) == 4
    assert len({labels["en"] for labels in SPLIT_LABELS.values()}) == 4


def test_read_file_meta_missing_label_file(work_dir):
    image_path = _make_image(work_dir)

    meta = read_file_meta(image_path)

    assert isinstance(meta, FileMeta)
    assert meta.exists is False
    assert meta.checked is False
    assert meta.shape_count == 0
    assert meta.split == SPLIT_NONE
    assert meta.import_time == pytest.approx(os.stat(image_path).st_mtime)
    assert meta.import_time > 0


def test_read_file_meta_derives_default_label_file(work_dir):
    image_path = _make_image(work_dir)
    _write_json(
        work_dir / "image.json",
        {"shapes": [{"label": "a"}], "checked": True, "split": SPLIT_TRAIN},
    )

    meta = read_file_meta(image_path)

    assert meta.exists is True
    assert meta.checked is True
    assert meta.shape_count == 1
    assert meta.split == SPLIT_TRAIN


def test_read_file_meta_reads_all_fields(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"
    _write_json(
        label_path,
        {
            "version": "4.3.2",
            "flags": {},
            "checked": "failed",
            "shapes": [{"label": "a"}, {"label": "b"}],
            "imagePath": "image.png",
            "imageData": None,
            "imageHeight": 20,
            "imageWidth": 30,
            "split": SPLIT_VAL,
        },
    )

    meta = read_file_meta(image_path, str(label_path))

    assert meta.exists is True
    assert meta.checked == "failed"
    assert meta.shape_count == 2
    assert meta.split == SPLIT_VAL
    assert meta.import_time == pytest.approx(os.stat(image_path).st_mtime)


def test_read_file_meta_checked_values(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"
    _write_json(label_path, {"shapes": [], "checked": True, "split": SPLIT_TRAIN})

    meta = read_file_meta(image_path, str(label_path))
    assert meta.checked is True
    assert meta.shape_count == 0
    assert meta.split == SPLIT_TRAIN

    _write_json(label_path, {"shapes": []})
    meta = read_file_meta(image_path, str(label_path))
    assert meta.checked is False
    assert meta.split == SPLIT_NONE

    _write_json(label_path, {"shapes": None, "checked": False})
    meta = read_file_meta(image_path, str(label_path))
    assert meta.checked is False
    assert meta.shape_count == 0


def test_read_file_meta_tolerates_invalid_json(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"
    label_path.write_text("{not valid json", encoding="utf-8")

    meta = read_file_meta(image_path, str(label_path))

    assert meta.exists is False
    assert meta.checked is False
    assert meta.shape_count == 0
    assert meta.split == SPLIT_NONE


def test_read_file_meta_tolerates_non_dict_json(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"
    label_path.write_text("[1, 2, 3]", encoding="utf-8")

    meta = read_file_meta(image_path, str(label_path))

    assert meta.exists is False
    assert meta.checked is False
    assert meta.shape_count == 0
    assert meta.split == SPLIT_NONE


def test_read_file_meta_unknown_split_falls_back_to_none(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"
    _write_json(label_path, {"shapes": [], "split": "validation"})

    assert read_file_meta(image_path, str(label_path)).split == SPLIT_NONE


def test_read_file_meta_missing_image_has_zero_import_time(work_dir):
    meta = read_file_meta(str(work_dir / "missing.png"))
    assert meta.import_time == 0.0


def test_format_import_time():
    timestamp = datetime.datetime(2024, 1, 2, 3, 4).timestamp()
    assert format_import_time(timestamp) == "2024-01-02 03:04"
    assert format_import_time(0) == "—"
    assert format_import_time(-1) == "—"
    assert format_import_time(None) == "—"
    assert format_import_time("not-a-number") == "—"


def test_read_split(work_dir):
    label_path = work_dir / "image.json"
    assert read_split(str(label_path)) == SPLIT_NONE
    assert read_split("") == SPLIT_NONE

    _write_json(label_path, {"shapes": [], "split": SPLIT_TEST})
    assert read_split(str(label_path)) == SPLIT_TEST

    _write_json(label_path, {"shapes": []})
    assert read_split(str(label_path)) == SPLIT_NONE

    label_path.write_text("broken", encoding="utf-8")
    assert read_split(str(label_path)) == SPLIT_NONE


def test_write_split_rejects_invalid_split(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"

    assert write_split(str(label_path), "validation", image_path) is False
    assert write_split(str(label_path), "TRAIN", image_path) is False
    assert write_split(str(label_path), "", image_path) is False
    assert not label_path.exists()

    original = {"shapes": [], "custom": 1}
    _write_json(label_path, original)
    assert write_split(str(label_path), "unknown", image_path) is False
    assert _read_json(label_path) == original


def test_write_split_rejects_empty_label_file(work_dir):
    image_path = _make_image(work_dir)
    assert write_split("", SPLIT_TRAIN, image_path) is False
    assert write_split(None, SPLIT_TRAIN, image_path) is False


def test_write_split_preserves_existing_keys(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"
    original = {
        "version": "4.3.2",
        "flags": {"reviewed": True},
        "checked": "failed",
        "shapes": [{"label": "cat", "points": [[0, 0], [1, 1]]}],
        "imagePath": "image.png",
        "imageData": None,
        "imageHeight": 20,
        "imageWidth": 30,
        "custom_key": {"nested": [1, 2]},
    }
    _write_json(label_path, original)

    assert write_split(str(label_path), SPLIT_TRAIN, image_path) is True

    data = _read_json(label_path)
    assert data["split"] == SPLIT_TRAIN
    assert set(data) == set(original) | {"split"}
    for key, value in original.items():
        assert data[key] == value

    # The update is atomic: no temporary file may be left behind.
    assert sorted(os.listdir(work_dir)) == ["image.json", "image.png"]


def test_write_split_creates_minimal_loadable_label_file(work_dir):
    image_path = _make_image(work_dir, size=(30, 20))
    label_path = work_dir / "image.json"

    assert write_split(str(label_path), SPLIT_VAL, image_path) is True

    data = _read_json(label_path)
    assert data["version"] == app_info.__version__
    assert data["flags"] == {}
    assert data["shapes"] == []
    assert data["imagePath"] == "image.png"
    assert data["imageData"] is None
    assert data["imageHeight"] == 20
    assert data["imageWidth"] == 30
    assert data["split"] == SPLIT_VAL
    assert "checked" not in data

    # The created file must be loadable by the application itself.
    label_file = LabelFile(filename=str(label_path))
    assert label_file.shapes == []
    assert label_file.image_path == "image.png"

    # Round-trip through the metadata reader.
    meta = read_file_meta(image_path, str(label_path))
    assert meta.exists is True
    assert meta.checked is False
    assert meta.shape_count == 0
    assert meta.split == SPLIT_VAL


def test_write_split_creation_without_image_path(work_dir):
    label_path = work_dir / "image.json"

    assert write_split(str(label_path), SPLIT_TEST) is True

    data = _read_json(label_path)
    assert data["imagePath"] == ""
    assert data["imageHeight"] is None
    assert data["imageWidth"] is None
    assert data["split"] == SPLIT_TEST


def test_write_split_creation_with_unreadable_image(work_dir):
    label_path = work_dir / "image.json"
    missing_image = str(work_dir / "missing.png")

    assert write_split(str(label_path), SPLIT_TRAIN, missing_image) is True

    data = _read_json(label_path)
    assert data["imagePath"] == "missing.png"
    assert data["imageHeight"] is None
    assert data["imageWidth"] is None


def test_write_split_does_not_clobber_invalid_json(work_dir):
    image_path = _make_image(work_dir)
    label_path = work_dir / "image.json"
    label_path.write_text("{broken", encoding="utf-8")

    assert write_split(str(label_path), SPLIT_TRAIN, image_path) is False
    assert label_path.read_text(encoding="utf-8") == "{broken"


def test_write_split_failure_returns_false(work_dir):
    image_path = _make_image(work_dir)
    missing_directory = work_dir / "missing" / "image.json"

    assert (
        write_split(str(missing_directory), SPLIT_TRAIN, image_path) is False
    )
    assert not missing_directory.exists()
