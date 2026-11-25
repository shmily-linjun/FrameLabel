"""Offscreen smoke test for the dataset center window (fork.53)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from anylabeling.services.dataset.connection import DatasetDatabase  # noqa: E402
from anylabeling.services.dataset.registry import RegistryStore  # noqa: E402
from anylabeling.services.dataset.repository import DatasetRepository  # noqa: E402
from anylabeling.services.identity.session import OperatorService  # noqa: E402
from anylabeling.views.dataset_center import DatasetCenterWindow  # noqa: E402


@pytest.fixture()
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def window(app, tmp_path):
    dataset_root = tmp_path / "ds"
    dataset_root.mkdir()
    database = DatasetDatabase.create(
        dataset_root / "xanylabeling.db", name="Demo"
    )
    repository = DatasetRepository(database)
    repository.add_image("images/a.jpg", split="train")
    database.close()

    app_db = str(tmp_path / "platform.db")
    registry = RegistryStore(app_db)
    registry.add_from_folder(str(dataset_root))
    operator_service = OperatorService(db_path=app_db)
    operator_service.register("tester", "abcd")
    center = DatasetCenterWindow(
        registry=registry,
        operator_service=operator_service,
    )
    yield center, registry, dataset_root, operator_service
    center.deleteLater()
    app.processEvents()


def test_lists_dataset_and_shows_overview(window):
    center, _registry, _dataset_root, _service = window
    assert center.table.rowCount() == 1
    assert center.table.item(0, 1).text() == "Demo"
    assert center.table.item(0, 2).text() == "1"
    assert center.summary_table.rowCount() == 9
    assert center.summary_table.item(0, 0).text() == "Images"
    assert center.summary_table.item(0, 1).text() == "1"
    assert "Demo" in center.overview_hint.text()


def test_missing_dataset_is_marked(window):
    center, registry, dataset_root, _service = window
    os.unlink(dataset_root / "xanylabeling.db")
    center.refresh()
    assert center.table.item(0, 0).text() == "缺失"
    assert "missing" in center.overview_hint.text().lower()
    [entry] = registry.list()
    assert entry.state == "missing"


def test_requires_login_for_changes(window, monkeypatch):
    center, _registry, _dataset_root, operator_service = window
    operator_service.logout()
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args),
    )
    assert center._require_login() is None
    assert warnings


def test_registers_the_dataset_open_in_the_window(app, tmp_path):
    """Opening a folder must make the center list that dataset (fork.54)."""

    dataset_root = tmp_path / "current"
    dataset_root.mkdir()
    database = DatasetDatabase.create(
        dataset_root / "xanylabeling.db", name="Current"
    )
    database.close()
    app_db = str(tmp_path / "platform.db")
    registry = RegistryStore(app_db)
    operator_service = OperatorService(db_path=app_db)
    operator_service.register("tester", "abcd")
    center = DatasetCenterWindow(
        registry=registry,
        operator_service=operator_service,
        current_dataset_provider=lambda: str(dataset_root),
    )
    try:
        [entry] = registry.list()
        assert entry.display_name == "Current"
        assert center.table.rowCount() == 1
    finally:
        center.deleteLater()
        app.processEvents()


def test_merge_target_combo_shows_the_path(app, tmp_path):
    """Equal display names must be distinguishable by their database path."""

    from anylabeling.views.dataset_center_merge import MergeDialog

    roots = []
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        database = DatasetDatabase.create(
            root / "xanylabeling.db", name="Same"
        )
        database.close()
        roots.append(root)

    app_db = str(tmp_path / "platform.db")
    registry = RegistryStore(app_db)
    entries = [registry.add_from_folder(str(root)) for root in roots]
    operator_service = OperatorService(db_path=app_db)
    operator_service.register("tester", "abcd")

    dialog = MergeDialog(
        sources=[entries[0]],
        registry=registry,
        operator_service=operator_service,
    )
    try:
        label = dialog.existing_combo.itemText(0)
        assert "Same" in label
        assert (
            str(roots[0] / "xanylabeling.db") in label
            or str(roots[1] / "xanylabeling.db") in label
        )
    finally:
        dialog.deleteLater()
        app.processEvents()
