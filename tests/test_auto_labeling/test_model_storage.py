import os
from types import SimpleNamespace

import pytest

from anylabeling.services.auto_labeling import model_storage


def _write_file(path, content=b"model"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_default_model_directory_creates_default_location(tmp_path):
    directory = model_storage.default_model_directory(str(tmp_path))

    assert directory == str(tmp_path / "xanylabeling_data" / "models")
    assert os.path.isdir(directory)


def test_default_model_directory_uses_work_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(
        model_storage, "get_work_directory", lambda: str(tmp_path)
    )

    directory = model_storage.default_model_directory()

    assert directory == str(tmp_path / "xanylabeling_data" / "models")
    assert os.path.isdir(directory)


def test_resolve_model_directory_prefers_configured_directory(tmp_path):
    configured = tmp_path / "custom" / "models"

    directory = model_storage.resolve_model_directory(
        {"model_directory": str(configured)}
    )

    assert directory == str(configured)
    assert os.path.isdir(configured)


@pytest.mark.parametrize("config", [{}, {"model_directory": None}, None])
def test_resolve_model_directory_falls_back_to_default(
    monkeypatch, tmp_path, config
):
    monkeypatch.setattr(
        model_storage, "get_work_directory", lambda: str(tmp_path)
    )

    directory = model_storage.resolve_model_directory(config)

    assert directory == str(tmp_path / "xanylabeling_data" / "models")
    assert os.path.isdir(directory)


def test_resolve_model_directory_expands_user_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    directory = model_storage.resolve_model_directory(
        {"model_directory": "~/custom-models"}
    )

    assert directory == str(tmp_path / "custom-models")
    assert (tmp_path / "custom-models").is_dir()


def test_resolve_model_directory_accepts_attribute_config(tmp_path):
    config = SimpleNamespace(model_directory=str(tmp_path / "models"))

    directory = model_storage.resolve_model_directory(config)

    assert directory == str(tmp_path / "models")


def test_resolve_model_directory_can_skip_creation(tmp_path):
    expected = tmp_path / "not-created"

    directory = model_storage.resolve_model_directory(
        {"model_directory": str(expected)}, create=False
    )

    assert directory == str(expected)
    assert not expected.exists()


def test_migrate_model_directory_moves_top_level_entries(tmp_path):
    old_directory = tmp_path / "old"
    new_directory = tmp_path / "new"
    _write_file(old_directory / "demo" / "encoder.onnx")
    _write_file(old_directory / "other" / "weights.pth")
    _write_file(old_directory / "notes.txt")

    errors = model_storage.migrate_model_directory(
        old_directory, new_directory
    )

    assert errors == []
    assert (new_directory / "demo" / "encoder.onnx").is_file()
    assert (new_directory / "other" / "weights.pth").is_file()
    assert (new_directory / "notes.txt").is_file()
    assert os.listdir(old_directory) == []


def test_migrate_model_directory_skips_existing_destination(tmp_path):
    old_directory = tmp_path / "old"
    new_directory = tmp_path / "new"
    _write_file(old_directory / "demo" / "encoder.onnx", b"old")
    _write_file(new_directory / "demo" / "encoder.onnx", b"new")

    errors = model_storage.migrate_model_directory(
        old_directory, new_directory
    )

    assert errors == []
    assert (new_directory / "demo" / "encoder.onnx").read_bytes() == b"new"
    assert (old_directory / "demo" / "encoder.onnx").read_bytes() == b"old"


def test_migrate_model_directory_reports_errors_without_raising(
    tmp_path, monkeypatch
):
    old_directory = tmp_path / "old"
    new_directory = tmp_path / "new"
    pending_file = _write_file(old_directory / "demo" / "encoder.onnx")

    def deny(_source, _destination):
        raise PermissionError("access denied")

    monkeypatch.setattr(model_storage.shutil, "move", deny)

    errors = model_storage.migrate_model_directory(
        old_directory, new_directory
    )

    assert len(errors) == 1
    assert "demo" in errors[0]
    assert pending_file.is_file()


def test_migrate_model_directory_ignores_same_and_missing_directories(
    tmp_path,
):
    assert (
        model_storage.migrate_model_directory(tmp_path, tmp_path) == []
    )
    assert (
        model_storage.migrate_model_directory(
            tmp_path / "missing", tmp_path / "new"
        )
        == []
    )


def test_migrate_model_directory_rejects_file_as_target(tmp_path):
    old_directory = tmp_path / "old"
    new_directory = tmp_path / "new"
    _write_file(old_directory / "demo" / "encoder.onnx")
    new_directory.write_bytes(b"not a directory")

    errors = model_storage.migrate_model_directory(
        old_directory, new_directory
    )

    assert len(errors) == 1
    assert (old_directory / "demo" / "encoder.onnx").is_file()
