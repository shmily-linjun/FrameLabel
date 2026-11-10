import copy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtTest import QTest

from anylabeling import config as app_config
from anylabeling.app_info import __version__
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.label_widget import (
    FILE_COL_IMPORT_TIME,
    FILE_COL_INFERENCE,
    FILE_COL_NAME,
    FILE_COL_SHAPES,
    FILE_COL_SPLIT,
    FILE_ROW_HEIGHT,
    FILE_ROW_HEIGHT_COMPACT,
)
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.utils.file_meta import SPLIT_NONE, SPLIT_TRAIN
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    window = MainWindow(app, config=copy.deepcopy(load_template_config()))
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    yield window
    window.labeling_widget.view.dirty = False
    window.close()
    app.removeEventFilter(window.labeling_widget.view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _write_image(path, size=8):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QtGui.QImage(
        QtCore.QSize(size, size), QtGui.QImage.Format.Format_RGB32
    )
    image.fill(QtCore.Qt.GlobalColor.white)
    assert image.save(str(path))


def _write_label(path, shape_count, split=None, checked=False):
    data = {
        "version": "4.3.2",
        "flags": {},
        "shapes": [
            {
                "label": f"object_{index}",
                "points": [[1, 1], [2, 1], [1, 2]],
                "shape_type": "polygon",
                "flags": {},
            }
            for index in range(shape_count)
        ],
        "imagePath": path.name,
        "imageData": None,
        "imageHeight": 8,
        "imageWidth": 8,
        "checked": checked,
    }
    if split is not None:
        data["split"] = split
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_dataset(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    first = images / "first.png"
    second = images / "second.png"
    third = images / "third.png"
    for image in (first, second, third):
        _write_image(image)
    _write_label(first.with_suffix(".json"), 3, split=SPLIT_TRAIN)
    _write_label(
        third.with_suffix(".json"), 1, split="val", checked="failed"
    )
    return images, first, second, third


def test_file_paths_survive_annotation_status_roles(window, tmp_path):
    """Regression: the path must not be overwritten by the checked state."""
    widget = window.labeling_widget.view
    images, first, second, third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))

    expected = {str(first), str(second), str(third)}
    actual = {
        widget._file_path_at(row)
        for row in range(widget.file_list_widget.rowCount())
    }
    assert actual == expected
    assert widget._file_item_by_path(str(third)) is not None
    assert widget._file_item_annotation_checked(
        widget._file_item_by_path(str(third))
    ) is True  # "failed" counts as checked


def test_file_table_columns_rows_and_visibility(window, tmp_path):
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))

    table = widget.file_list_widget
    assert isinstance(table, QtWidgets.QTableWidget)
    assert table.columnCount() == 5
    assert table.count() == 3
    assert widget.fn_to_index[str(first)] == 0
    assert widget._file_path_at(0) == str(first)

    assert table.item(0, FILE_COL_SHAPES).text() == "3"
    assert table.item(1, FILE_COL_SHAPES).text() == "0"
    assert table.item(0, FILE_COL_INFERENCE).text() == "—"
    assert table.item(0, FILE_COL_SPLIT).text() == "Train"
    assert table.item(1, FILE_COL_SPLIT).text() == "None"

    flags = table.item(0, FILE_COL_NAME).flags()
    assert not (flags & QtCore.Qt.ItemFlag.ItemIsUserCheckable)

    # Row numbers come from the native vertical header.
    assert table.verticalHeader().isVisible()
    # The import time column is visible by default.
    assert not table.isColumnHidden(FILE_COL_IMPORT_TIME)
    assert widget._config["file_list"]["show_import_time"] is True

    # Column widths can be adjusted by the user and are persisted.
    header = table.horizontalHeader()
    assert (
        header.sectionResizeMode(FILE_COL_SHAPES)
        == QtWidgets.QHeaderView.ResizeMode.Interactive
    )
    widget.set_file_column_visible(FILE_COL_IMPORT_TIME, False)
    assert table.isColumnHidden(FILE_COL_IMPORT_TIME)
    widget.set_file_column_visible(FILE_COL_IMPORT_TIME, True)
    assert not table.isColumnHidden(FILE_COL_IMPORT_TIME)
    table.setColumnWidth(FILE_COL_SPLIT, 77)
    assert widget._config["file_list"]["column_widths"]["4"] == 77


def test_import_time_is_persisted_in_sidecar(window, tmp_path):
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    first_row = widget.fn_to_index[str(first)]
    stamp = widget.file_list_widget.item(
        first_row, FILE_COL_IMPORT_TIME
    ).text()
    sidecar = images / ".xanylabeling_import_time.json"
    assert sidecar.is_file()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert first.name in data["import_time"]

    # Re-importing keeps the original timestamp instead of the file mtime.
    widget.import_image_folder(str(images))
    assert (
        widget.file_list_widget.item(
            widget.fn_to_index[str(first)], FILE_COL_IMPORT_TIME
        ).text()
        == stamp
    )


def test_right_side_has_tabs_and_no_dock_widgets(window):
    widget = window.labeling_widget.view
    assert not hasattr(widget, "file_dock")
    assert not hasattr(widget, "label_dock")
    assert not hasattr(widget, "shape_dock")
    assert not hasattr(widget, "description_dock")
    assert not hasattr(widget, "files_checkbox")
    assert widget.right_tabs.count() == 4
    assert isinstance(widget.right_splitter, QtWidgets.QSplitter)
    assert widget.right_splitter.orientation() == QtCore.Qt.Orientation.Vertical
    assert widget.right_splitter.count() == 2


def test_sorting_keeps_row_mapping_and_navigation_consistent(window, tmp_path):
    widget = window.labeling_widget.view
    images, first, second, third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))

    widget.sort_file_list_by_column(FILE_COL_SHAPES)
    table = widget.file_list_widget
    assert [table.item(row, FILE_COL_SHAPES).text() for row in range(3)] == [
        "0",
        "1",
        "3",
    ]
    assert widget._file_path_at(0) == str(second)
    assert widget._file_path_at(2) == str(first)
    assert widget.fn_to_index[str(first)] == 2
    assert widget.fn_to_index[str(second)] == 0
    assert widget.image_list == [
        str(second),
        str(third),
        str(first),
    ]
    assert widget._file_path_at(widget.fn_to_index[str(first)]) == str(first)

    widget.sort_file_list_by_column(FILE_COL_SHAPES)
    assert [table.item(row, FILE_COL_SHAPES).text() for row in range(3)] == [
        "3",
        "1",
        "0",
    ]
    assert widget._file_path_at(0) == str(first)


def test_split_action_writes_json_and_preserves_existing_keys(
    window, tmp_path
):
    widget = window.labeling_widget.view
    images, first, second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))

    second_row = widget.fn_to_index[str(second)]
    widget.set_file_split(second_row, SPLIT_TRAIN)
    second_json = second.with_suffix(".json")
    assert second_json.is_file()
    data = json.loads(second_json.read_text(encoding="utf-8"))
    assert data["split"] == SPLIT_TRAIN
    assert data["shapes"] == []
    assert data["version"] == __version__
    table = widget.file_list_widget
    assert table.item(second_row, FILE_COL_SPLIT).text() == "Train"

    first_row = widget.fn_to_index[str(first)]
    widget.set_file_split(first_row, SPLIT_NONE)
    first_data = json.loads(
        first.with_suffix(".json").read_text(encoding="utf-8")
    )
    assert first_data["split"] == SPLIT_NONE
    assert len(first_data["shapes"]) == 3


def test_row_removal_only_affects_the_list(window, tmp_path, monkeypatch):
    widget = window.labeling_widget.view
    images, first, second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))

    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    widget.remove_file_from_list(widget.fn_to_index[str(second)])

    assert widget.file_list_widget.count() == 2
    assert str(second) not in widget.fn_to_index
    assert second.is_file()
    assert not second.with_suffix(".json").exists()
    assert widget._file_path_at(widget.fn_to_index[str(first)]) == str(first)


def test_thumbnail_toggle_updates_row_height(window, tmp_path):
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    table = widget.file_list_widget

    assert table.verticalHeader().defaultSectionSize() == FILE_ROW_HEIGHT
    widget.set_file_thumbnails_visible(False)
    assert (
        table.verticalHeader().defaultSectionSize()
        == FILE_ROW_HEIGHT_COMPACT
    )
    assert table.iconSize().width() == 0
    assert widget._config["file_list"]["show_thumbnails"] is False
    widget.set_file_thumbnails_visible(True)
    assert table.iconSize().width() > 0


def test_right_tabs_visibility_and_guard(window):
    widget = window.labeling_widget.view
    tabs = widget.right_tabs
    assert tabs.count() == 4

    widget.set_right_tab_visible("labels", False)
    assert tabs.count() == 3
    assert "labels" in widget._config["right_tabs"]["hidden"]
    widget.set_right_tab_visible("labels", True)
    assert tabs.count() == 4

    widget.set_right_tab_visible("objects", False)
    widget.set_right_tab_visible("description", False)
    widget.set_right_tab_visible("flags", False)
    assert tabs.count() == 1
    widget.set_right_tab_visible("labels", False)
    assert tabs.count() == 1


def test_toolbar_can_be_docked_left_and_hidden(window):
    toolbar = window.findChild(QtWidgets.QToolBar, "ToolsToolBar")
    window.dock_toolbar(QtCore.Qt.ToolBarArea.LeftToolBarArea)
    assert (
        window.toolBarArea(toolbar) == QtCore.Qt.ToolBarArea.LeftToolBarArea
    )
    assert toolbar.orientation() == QtCore.Qt.Orientation.Vertical

    window.dock_toolbar(QtCore.Qt.ToolBarArea.TopToolBarArea)
    assert (
        window.toolBarArea(toolbar) == QtCore.Qt.ToolBarArea.TopToolBarArea
    )

    window.set_toolbar_visible(False)
    assert not toolbar.isVisible()
    window.set_toolbar_visible(True)
    assert toolbar.isVisible()

    view_menu = window.labeling_widget.view.menus.view
    labels = [action.text() for action in view_menu.actions()]
    assert "Dock Toolbar at Top" in labels
    assert "Dock Toolbar at Left" in labels


def test_toolbar_is_installed_and_dockable(window):
    toolbar = window.findChild(QtWidgets.QToolBar, "ToolsToolBar")
    assert toolbar is not None
    assert window.toolBarArea(toolbar) == QtCore.Qt.ToolBarArea.TopToolBarArea
    assert toolbar.isMovable()
    assert not toolbar.isFloatable()
    areas = toolbar.allowedAreas()
    assert areas & QtCore.Qt.ToolBarArea.TopToolBarArea
    assert areas & QtCore.Qt.ToolBarArea.LeftToolBarArea


def _settle_ui():
    """Let the deferred (100 ms) UI-density update run before measuring."""
    QTest.qWait(150)
    app = QtWidgets.QApplication.instance()
    app.processEvents()


def _drag_sidebar(splitter, target_width):
    """Drag the sidebar splitter handle like a user would."""
    handle = splitter.handle(1)
    assert handle is not None
    target_x = splitter.width() - splitter.handleWidth() - target_width
    start_x = handle.x()
    start = QtCore.QPoint(handle.width() // 2, handle.height() // 2)
    end = QtCore.QPoint(start.x() + (target_x - start_x), start.y())
    QTest.mousePress(
        handle,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        start,
    )
    QTest.mouseMove(handle, end)
    QTest.mouseRelease(
        handle,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        end,
    )
    return splitter.sizes()[1]


def test_sidebar_minimum_width_allows_narrowing(window, tmp_path):
    """Regression: the sidebar minimum width must not be locked wide.

    The right sidebar used to be pinned near its initial width, so the user
    could not drag it narrow.
    """
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    _settle_ui()

    sidebar = widget.right_sidebar
    splitter = widget.sidebar_splitter
    table = widget.file_list_widget

    default_width = widget._sidebar_base_width
    min_width = sidebar.minimumWidth()
    assert sidebar.width() >= default_width - 4

    # Clearly narrower than the initial width, and still usable.
    assert 200 <= min_width <= 260
    assert min_width <= round(default_width * 0.6)
    # No child (tabs / file table) may force the sidebar wider.
    assert sidebar.minimumSizeHint().width() <= min_width

    # Squeeze the sidebar as a splitter drag would; it must reach the
    # minimum instead of stopping at the old, much wider width.
    total = splitter.width() - splitter.handleWidth()
    splitter.setSizes([total - min_width, min_width])
    app.processEvents()
    assert abs(sidebar.width() - min_width) <= 4
    assert abs(splitter.sizes()[1] - min_width) <= 4

    # An even narrower request clamps to the minimum, it does not grow back.
    splitter.setSizes([total - 120, 120])
    app.processEvents()
    assert abs(sidebar.width() - min_width) <= 4

    # The file table is still visible; its columns overflow and scroll.
    assert table.isVisible()
    assert table.width() >= 150
    horizontal = table.horizontalScrollBar()
    assert horizontal.maximum() > 0
    horizontal.setValue(horizontal.maximum())
    assert horizontal.value() == horizontal.maximum()


def test_sidebar_can_be_dragged_to_minimum_width(window, tmp_path):
    """The user drag path must reach the minimum width, not just setSizes."""
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    _settle_ui()

    sidebar = widget.right_sidebar
    splitter = widget.sidebar_splitter
    min_width = sidebar.minimumWidth()

    # Drag to a still-usable width below the default.
    assert abs(_drag_sidebar(splitter, 260) - 260) <= 4
    assert abs(sidebar.width() - 260) <= 4

    # Dragging further ends up at the minimum width.
    assert abs(_drag_sidebar(splitter, 160) - min_width) <= 4
    assert abs(sidebar.width() - min_width) <= 4
    assert widget.file_list_widget.isVisible()
