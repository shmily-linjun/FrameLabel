import copy
import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtTest import QTest

from anylabeling import config as app_config
from anylabeling.app_info import __version__
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.file_list.constants import (
    FILE_COL_IMPORT_TIME,
    FILE_COL_INFERENCE,
    FILE_COL_NAME,
    FILE_COL_SHAPES,
    FILE_COL_SPLIT,
    FILE_ROW_HEIGHT,
    FILE_ROW_HEIGHT_COMPACT,
)
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.labeling.utils.dataset_statistics import (
    StatisticsFilter,
)
from anylabeling.views.labeling.utils.file_meta import SPLIT_NONE, SPLIT_TRAIN
from anylabeling.views.labeling.widgets.label_manager import REFRESH_DELAY_MS
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
    assert widget.right_tabs.count() == 5
    assert isinstance(widget.right_splitter, QtWidgets.QSplitter)
    assert widget.right_splitter.orientation() == QtCore.Qt.Orientation.Vertical
    assert widget.right_splitter.count() == 2


def test_objects_and_classes_tabs_are_plain_lists(window):
    widget = window.labeling_widget.view
    # The old per-tab header (show/hide + lock-all buttons) is gone.
    for name in (
        "labels_visibility_button",
        "labels_lock_button",
        "shapes_visibility_button",
        "shapes_lock_button",
    ):
        assert not hasattr(widget, name)
    assert isinstance(widget.label_list, QtWidgets.QListWidget)
    assert isinstance(widget.unique_label_list, QtWidgets.QListWidget)


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
    assert tabs.count() == 5
    assert [
        tabs.tabText(i) for i in range(tabs.count())
    ] == [
        "Objects",
        "Classes",
        "Image Attributes",
        "Description",
        "Statistics",
    ]

    widget.set_right_tab_visible("labels", False)
    assert tabs.count() == 4
    assert "labels" in widget._config["right_tabs"]["hidden"]
    widget.set_right_tab_visible("labels", True)
    assert tabs.count() == 5

    # The attributes tab is the only UI for image tags and image flags, so it
    # cannot be hidden (neither through the menu nor through a stale config).
    widget.set_right_tab_visible("flags", False)
    assert tabs.count() == 5
    assert "flags" not in widget._config["right_tabs"]["hidden"]
    assert "flags" not in widget._hidden_tabs

    widget.set_right_tab_visible("objects", False)
    widget.set_right_tab_visible("description", False)
    widget.set_right_tab_visible("statistics", False)
    assert tabs.count() == 2
    widget.set_right_tab_visible("labels", False)
    assert tabs.count() == 1
    widget.set_right_tab_visible("flags", False)
    assert tabs.count() == 1
    assert tabs.tabText(0) == "Image Attributes"


def test_stale_config_cannot_hide_the_attributes_tab(window):
    widget = window.labeling_widget.view
    widget._config["right_tabs"] = {"hidden": ["flags"]}
    widget._apply_right_tabs_config()
    assert "flags" not in widget._hidden_tabs
    assert [
        widget.right_tabs.tabText(index)
        for index in range(widget.right_tabs.count())
    ] == [
        "Objects",
        "Classes",
        "Image Attributes",
        "Description",
        "Statistics",
    ]


def test_statistics_tab_click_filters_search(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    widget.dirty = False
    widget.import_image_folder(str(images))
    widget.dirty = False

    table = widget.statistics_table
    widget.right_tabs.setCurrentWidget(table)
    app.processEvents()
    assert table.rowCount() == 5
    assert table.columnCount() == 6
    headers = [table.item(row, 0).text() for row in range(table.rowCount())]
    assert headers == [
        "object_0",
        "object_1",
        "object_2",
        "(No objects)",
        "Total",
    ]
    # The "Total" row counts files per split (3 files, 1 in train, 1 in val).
    assert table.item(headers.index("Total"), 1).text() == "1"
    assert table.item(headers.index("Total"), 6 - 1).text() == "3"

    table.cellClicked.emit(headers.index("object_0"), 1)
    app.processEvents()
    assert widget.file_search.text() == "label::object_0,split::train"
    assert widget.file_list_widget.rowCount() == 1
    assert widget._file_path_at(0) == str(first)

    table.cellClicked.emit(headers.index("(No objects)"), 4)
    app.processEvents()
    assert widget.file_search.text() == "shape::0,split::none"
    assert widget.file_list_widget.rowCount() == 1


def test_file_search_supports_split_and_boolean_queries(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, _first, second, _third = _make_dataset(tmp_path)
    widget.dirty = False
    widget.import_image_folder(str(images))
    widget.dirty = False

    def search(text):
        widget.dirty = False
        widget.file_search.setText(text)
        widget.file_search_changed()
        widget.dirty = False
        app.processEvents()
        return widget.file_list_widget.rowCount()

    assert search("split::train") == 1
    assert search("split::训练") == 1
    assert search("split::val") == 1
    assert search("label::object_0") == 2
    assert search("label::object_0,split::train") == 1
    assert search("label::object_0|object_1") == 2
    assert search("!label::object_0") == 1
    assert search("shape::0") == 1  # second.png has no label file
    assert search("") == 3


def test_toolbar_can_be_docked_left_and_hidden(window):
    toolbar = window.findChild(QtWidgets.QToolBar, "ToolsToolBar")
    scroll = window.findChild(QtWidgets.QScrollArea, "ToolsToolBarScroll")
    dock = window.findChild(QtWidgets.QDockWidget, "ToolsDock")
    assert scroll is not None and dock is not None
    window.dock_toolbar(QtCore.Qt.ToolBarArea.LeftToolBarArea)
    assert (
        window.dockWidgetArea(dock)
        == QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
    )
    assert toolbar.orientation() == QtCore.Qt.Orientation.Vertical
    assert (
        scroll.verticalScrollBarPolicy()
        == QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert (
        scroll.horizontalScrollBarPolicy()
        == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )

    window.dock_toolbar(QtCore.Qt.ToolBarArea.TopToolBarArea)
    assert (
        window.dockWidgetArea(dock)
        == QtCore.Qt.DockWidgetArea.TopDockWidgetArea
    )
    assert toolbar.orientation() == QtCore.Qt.Orientation.Horizontal
    assert (
        scroll.horizontalScrollBarPolicy()
        == QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert (
        scroll.verticalScrollBarPolicy()
        == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
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
    dock = window.findChild(QtWidgets.QDockWidget, "ToolsDock")
    assert toolbar is not None
    assert dock is not None
    assert (
        window.dockWidgetArea(dock)
        == QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
    )
    assert not toolbar.isMovable()
    assert not toolbar.isFloatable()
    areas = toolbar.allowedAreas()
    assert areas & QtCore.Qt.ToolBarArea.TopToolBarArea
    assert areas & QtCore.Qt.ToolBarArea.LeftToolBarArea


def test_toolbar_scrolls_the_whole_tool_set(window):
    toolbar = window.findChild(QtWidgets.QToolBar, "ToolsToolBar")
    scroll = window.findChild(QtWidgets.QScrollArea, "ToolsToolBarScroll")
    view = window.labeling_widget.view
    app = QtWidgets.QApplication.instance()

    window.dock_toolbar(QtCore.Qt.ToolBarArea.LeftToolBarArea)
    view.apply_toolbar_preferences(False, set())
    app.processEvents()
    assert scroll.verticalScrollBar().maximum() > 0
    assert scroll.horizontalScrollBar().maximum() == 0

    # No separator widgets are inserted into the toolbar: in icon-only mode
    # they used to leave unlabelled dark blocks between adjacent tools.
    assert not any(action.isSeparator() for action in toolbar.actions())
    for action in toolbar.actions():
        assert isinstance(
            toolbar.widgetForAction(action), QtWidgets.QToolButton
        )
    extension = toolbar.findChild(
        QtWidgets.QToolButton, "qt_toolbar_ext_button"
    )
    assert extension is None or not extension.isVisible()

    window.dock_toolbar(QtCore.Qt.ToolBarArea.TopToolBarArea)
    view.apply_toolbar_preferences(True, set())
    app.processEvents()
    assert scroll.horizontalScrollBar().maximum() > 0
    assert scroll.verticalScrollBar().maximum() == 0


def test_toolbar_settings_page_can_hide_pinned_buttons(window):
    view = window.labeling_widget.view
    entries = view.toolbar_entries()
    keys = {key for key, _name, _tip in entries}
    assert "settings" in keys
    assert "shortcuts" in keys

    def in_toolbar(button):
        return any(
            view.tools.widgetForAction(action) is button
            for action in view.tools.actions()
        )

    assert in_toolbar(view.settings_button)
    assert in_toolbar(view.shortcuts_button)

    view.apply_toolbar_preferences(True, {"settings"})
    assert not in_toolbar(view.settings_button)
    assert in_toolbar(view.shortcuts_button)

    view.apply_toolbar_preferences(True, {"settings", "shortcuts"})
    assert not in_toolbar(view.settings_button)
    assert not in_toolbar(view.shortcuts_button)

    view.apply_toolbar_preferences(True, set())
    assert in_toolbar(view.settings_button)
    assert in_toolbar(view.shortcuts_button)


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


def _click_row(table, row, modifier=None):
    index = table.model().index(row, FILE_COL_NAME)
    QTest.mouseClick(
        table.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        modifier or QtCore.Qt.KeyboardModifier.NoModifier,
        table.visualRect(index).center(),
    )


def test_ctrl_click_extends_selection_without_opening(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()
    table = widget.file_list_widget

    _click_row(table, 0)
    app.processEvents()
    assert table.currentRow() == 0
    assert table.selected_rows() == [0]
    assert widget.filename == str(first)

    # Ctrl+click extends the target set but must not open the clicked image.
    _click_row(table, 1, QtCore.Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert table.selected_rows() == [0, 1]
    assert widget.filename == str(first)

    # Shift+click extends the range the same way.
    _click_row(table, 2, QtCore.Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    assert table.selected_rows() in ([1, 2], [0, 1, 2])
    assert widget.filename == str(first)

    # A plain click still opens the image.
    _click_row(table, 1)
    app.processEvents()
    assert table.selected_rows() == [1]
    assert widget.filename == str(second)


def test_ctrl_a_selects_every_row_instead_of_auto_labeling(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, second, third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()
    table = widget.file_list_widget

    _click_row(table, 0)
    app.processEvents()
    auto_labeling_visible = widget.auto_labeling_widget.isVisible()

    table.setFocus()
    app.processEvents()
    QTest.keyClick(
        table,
        QtCore.Qt.Key.Key_A,
        QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    app.processEvents()

    assert table.selected_rows() == [0, 1, 2]
    # The window-level Ctrl+A shortcut (auto labeling) must not fire here.
    assert widget.auto_labeling_widget.isVisible() == auto_labeling_visible
    # Select-all is a selection gesture: the open image does not change.
    assert widget.filename == str(first)
    assert table.currentRow() == 0
    assert {str(first), str(second), str(third)} == {
        widget._file_path_at(row) for row in table.selected_rows()
    }


def test_shift_arrow_extends_selection_without_opening(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()
    table = widget.file_list_widget

    _click_row(table, 0)
    app.processEvents()
    table.setFocus()
    QTest.keyClick(
        table,
        QtCore.Qt.Key.Key_Down,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
    )
    app.processEvents()

    assert table.selected_rows() == [0, 1]
    assert widget.filename == str(first)


def test_batch_split_applies_to_all_selected_rows(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, second, third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()
    table = widget.file_list_widget
    table.selectAll()
    app.processEvents()
    assert len(table.selected_rows()) == 3

    widget.files.set_split_rows(table.selected_rows(), SPLIT_TRAIN)

    for image in (first, second, third):
        data = json.loads(
            image.with_suffix(".json").read_text(encoding="utf-8")
        )
        assert data["split"] == SPLIT_TRAIN
    for row in range(3):
        assert table.item(row, FILE_COL_SPLIT).text() == "Train"


def test_batch_remove_keeps_files_and_reindexes(window, tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, second, third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()
    table = widget.file_list_widget

    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    rows = [table.rowCount() - 1, 1]
    widget.files.remove_rows(rows)

    assert table.rowCount() == 1
    assert [widget._file_path_at(0)] == [str(first)]
    assert widget.fn_to_index[str(first)] == 0
    assert str(second) not in widget.fn_to_index
    assert str(third) not in widget.fn_to_index
    # Files and annotation files are untouched.
    for image in (second, third):
        assert image.is_file()


def test_classes_tab_hosts_the_label_manager(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()

    panel = widget.label_manager_widget
    page = panel.parentWidget()
    tabs = widget.right_tabs
    assert tabs.indexOf(page) == 1
    assert tabs.tabText(1) == "Classes"

    # Tools > Label manager (Alt+L) opens that tab instead of a dialog.
    widget.right_tabs.setCurrentIndex(0)
    widget.actions.label_manager.trigger()
    app.processEvents()
    assert tabs.currentWidget() is page

    # The table is editable exactly when the operator gate allows editing
    # (the process-level session may already be logged in from another test).
    widget._apply_operator_gate()
    assert panel._editing_enabled == widget.operator_gate.logged_in()
    assert panel.table.isEnabled() == panel._editing_enabled


def test_file_table_has_no_tags_column(window, tmp_path):
    """Image tags belong to the attributes tab, not to the file table."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    data = json.loads(
        first.with_suffix(".json").read_text(encoding="utf-8")
    )
    data["tags"] = ["defect", "blur"]
    first.with_suffix(".json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()
    table = widget.file_list_widget
    headers = [
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    ]
    assert headers == [
        "Files",
        "Objects",
        "Import Time",
        "Inference",
        "Split",
    ]
    # Tags are still image metadata; the attributes editor owns them.
    assert widget.image_tags_widget.tags == ["defect", "blur"]


def test_attributes_tab_hosts_the_image_tags_editor(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()

    tabs = widget.right_tabs
    attributes_page = widget.image_tags_widget.parentWidget()
    index = tabs.indexOf(attributes_page)
    assert index >= 0
    assert tabs.tabText(index) == "Image Attributes"
    # Image tags and image flags share that page.
    assert widget.flag_widget.parentWidget() is attributes_page

    # The tags editor is not part of the canvas area any more, so it costs no
    # canvas height.
    canvas_panel = widget._central_widget.parentWidget()
    assert widget.image_tags_widget not in canvas_panel.findChildren(
        QtWidgets.QWidget
    )

    # The action behind Ctrl+Shift+T / View > Image Tags opens that tab.
    widget.right_tabs.setCurrentWidget(widget.label_list.parentWidget())
    assert widget.right_tabs.currentWidget() is not attributes_page
    widget.actions.show_image_tags.trigger()
    app.processEvents()
    assert widget.right_tabs.currentWidget() is attributes_page
    assert not widget.actions.show_image_tags.isCheckable()


def test_title_bar_has_a_fullscreen_toggle_and_no_image_tags_button(window):
    widget = window.labeling_widget.view
    # The "Edit image tags" title-bar button was removed; the action remains
    # available through the View menu and its shortcut.
    assert not hasattr(widget, "image_tags_toggle_button")
    title_bar = window.title_bar
    if title_bar is None:
        pytest.skip("frameless title bar required")
    assert title_bar.button("window-control-1") is None
    button = title_bar.button("window-control-fullscreen")
    assert button is not None
    assert button.defaultAction() is window.fullscreen_action

    # Full screen was moved out of the title-bar context menu.
    texts = [
        action.text()
        for action in title_bar.build_context_menu().actions()
    ]
    assert "Full Screen" not in texts
    assert "Exit Full Screen" not in texts


def test_fullscreen_toggle_button_reflects_window_state(window):
    app = QtWidgets.QApplication.instance()
    title_bar = window.title_bar
    if title_bar is None:
        pytest.skip("frameless title bar required")
    button = title_bar.button("window-control-fullscreen")
    button.click()
    app.processEvents()
    assert window.isFullScreen()
    assert window.fullscreen_action.isChecked()
    assert window.fullscreen_action.text() == window.tr("Exit Full Screen")
    assert button.toolTip() == window.tr("Exit Full Screen")

    button.click()
    app.processEvents()
    assert not window.isFullScreen()
    assert not window.fullscreen_action.isChecked()
    assert window.fullscreen_action.text() == window.tr("Full Screen")


def _extra_rectangle(label="extra", shape_id="extra-shape"):
    return {
        "label": label,
        "score": None,
        "points": [[1.0, 1.0], [4.0, 1.0], [4.0, 4.0], [1.0, 4.0]],
        "group_id": None,
        "difficult": False,
        "shape_type": "rectangle",
        "flags": {},
        "attributes": {},
        "kie_linking": [],
        "shape_id": shape_id,
        "review_status": "pending",
    }


def test_classes_tab_refreshes_live_when_visible(window, tmp_path):
    """A visible "Classes" tab re-reads categories without Alt+L."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()

    panel = widget.label_manager_widget
    repository = widget.dataset_repository
    assert repository is not None
    widget.right_tabs.setCurrentWidget(panel.parentWidget())
    app.processEvents()
    labels_before = [
        panel.table.item(row, 0).text()
        for row in range(panel.table.rowCount())
    ]
    assert "extra" not in labels_before

    image = repository.find_image(first.name)
    annotation = repository.load_annotation(image["id"])
    annotation.shapes.append(_extra_rectangle())
    repository.save_annotation(image["id"], annotation)

    # The save path invalidates the panel; the visible tab must rebuild by
    # itself (no Tools > Label manager click, no tab switch).
    panel.invalidate()
    QTest.qWait(REFRESH_DELAY_MS + 120)
    app.processEvents()
    labels_after = [
        panel.table.item(row, 0).text()
        for row in range(panel.table.rowCount())
    ]
    assert "extra" in labels_after


def test_classes_tab_builds_when_activated_after_import(window, tmp_path):
    """Startup on another tab + import must still fill "Classes" on switch."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    panel = widget.label_manager_widget
    # A fresh window starts on the "Objects" tab and never builds the table.
    assert widget.right_tabs.currentWidget() is not panel.parentWidget()
    assert panel.table.rowCount() == 0

    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.right_tabs.setCurrentIndex(0)
    app.processEvents()
    assert panel.table.rowCount() == 0

    widget.show_right_tab("labels")
    app.processEvents()
    labels = [
        panel.table.item(row, 0).text()
        for row in range(panel.table.rowCount())
    ]
    assert labels == ["object_0", "object_1", "object_2"]


def test_batch_tags_applies_to_selected_rows(
    window, tmp_path, monkeypatch
):
    """The file-list "Set Tags…" entry writes every selected image."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, first, second, third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    widget.dirty = False
    app.processEvents()
    repository = widget.dataset_repository
    assert repository is not None

    class FakeDialog:
        def __init__(
            self, _count, _library=None, _parent=None, translate=None
        ):
            pass

        def exec(self):
            return QtWidgets.QDialog.DialogCode.Accepted

        def mode(self):
            return "add"

        def tags(self):
            return ["defect", "blur"]

        def old_tags(self):
            return []

    import anylabeling.views.labeling.file_list.controller as controller_module

    monkeypatch.setattr(controller_module, "BatchTagsDialog", FakeDialog)
    monkeypatch.setattr(widget, "_ensure_operator", lambda: True)
    monkeypatch.setattr(
        widget,
        "operator_service",
        SimpleNamespace(
            session=SimpleNamespace(
                operator_name="tester", is_logged_in=True
            )
        ),
    )

    widget.files.set_tags_rows(
        [widget.fn_to_index[str(first)], widget.fn_to_index[str(second)]]
    )

    def tags_of(path):
        image = repository.find_image(path.name)
        return repository.load_annotation(image["id"]).tags

    assert tags_of(first) == ["defect", "blur"]
    assert tags_of(second) == ["defect", "blur"]
    assert tags_of(third) == []
    # The open image (first row) is refreshed in memory too.
    assert widget.other_data["tags"] == ["defect", "blur"]
    assert widget.image_tags_widget.tags == ["defect", "blur"]


def test_batch_tags_replaces_only_the_specified_tag(
    window, tmp_path, monkeypatch
):
    widget = window.labeling_widget.view
    images, first, second, third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    repository = widget.dataset_repository
    assert repository is not None

    def annotation_of(path):
        image = repository.find_image(path.name)
        return image["id"], repository.load_annotation(image["id"])

    first_id, first_annotation = annotation_of(first)
    first_annotation.tags = ["keep", "old"]
    repository.save_annotation(first_id, first_annotation)
    second_id, second_annotation = annotation_of(second)
    second_annotation.tags = ["old"]
    repository.save_annotation(second_id, second_annotation)

    class FakeDialog:
        def __init__(
            self, _count, _library=None, _parent=None, translate=None
        ):
            pass

        def exec(self):
            return QtWidgets.QDialog.DialogCode.Accepted

        def mode(self):
            return "replace"

        def tags(self):
            return ["new"]

        def old_tags(self):
            return ["old"]

    import anylabeling.views.labeling.file_list.controller as controller_module

    monkeypatch.setattr(controller_module, "BatchTagsDialog", FakeDialog)
    monkeypatch.setattr(widget, "_ensure_operator", lambda: True)
    monkeypatch.setattr(
        widget.operator_gate,
        "service",
        SimpleNamespace(
            session=SimpleNamespace(
                operator_name="tester", is_logged_in=True
            )
        ),
    )

    widget.files.set_tags_rows(
        [widget.fn_to_index[str(first)], widget.fn_to_index[str(second)]]
    )

    assert annotation_of(first)[1].tags == ["keep", "new"]
    assert annotation_of(second)[1].tags == ["new"]
    assert annotation_of(third)[1].tags == []


def test_statistics_totals_clear_or_set_filters(window):
    """Totals cells must drive the search bar like the other cells."""
    widget = window.labeling_widget.view
    widget.file_search.setText("label::object_0")
    widget.statistics_table.filter_requested.emit(
        StatisticsFilter(all_images=True)
    )
    assert widget.file_search.text() == ""

    widget.statistics_table.filter_requested.emit(
        StatisticsFilter(split="train")
    )
    assert widget.file_search.text() == "split::train"

    widget.file_search.clear()
    widget.statistics_table.filter_requested.emit(
        StatisticsFilter(label="object_0")
    )
    assert widget.file_search.text() == "label::object_0"


def test_object_column_has_no_status_circle(window, tmp_path):
    """The object count cell must not paint the legacy ``checked`` icon."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    app.processEvents()

    item = widget.file_list_widget.item(0, FILE_COL_SHAPES)
    assert item is not None
    assert item.icon().isNull()
    assert item.text() == "3"


def test_move_to_folder_updates_db_and_file_table(
    window, tmp_path, monkeypatch
):
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    destination = images / "moved"
    destination.mkdir()
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(destination)),
    )
    monkeypatch.setattr(widget, "_ensure_operator", lambda: True)

    widget.files.move_rows_to_folder([widget.fn_to_index[str(first)]])

    new_path = destination / first.name
    assert new_path.is_file()
    assert not first.exists()
    assert new_path.with_suffix(".json").is_file()
    assert str(new_path) in widget.fn_to_index
    repository = widget.dataset_repository
    assert repository is not None
    assert repository.find_image("moved/" + first.name) is not None
    assert repository.find_image(first.name) is None


def test_category_import_button_is_shown_on_classes_tab(window):
    widget = window.labeling_widget.view
    button = widget.category_import_button
    widget.show_right_tab("labels")
    assert button.isVisible()
    widget.show_right_tab("objects")
    assert not button.isVisible()


def test_folder_open_always_creates_database(window, tmp_path):
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)

    widget.import_image_folder(str(images))

    assert (images / "xanylabeling.db").is_file()
    assert widget.dataset_repository is not None
    assert widget.dataset_root == str(images.resolve())


def test_missing_file_can_be_removed_from_db_list(window, tmp_path):
    widget = window.labeling_widget.view
    images, first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images))
    repository = widget.dataset_repository
    assert repository is not None
    first.unlink()

    widget.files.remove_missing_path(str(first))

    assert str(first) not in widget.fn_to_index
    assert repository.find_image(first.name) is None


def test_tag_library_keeps_folder_vocabulary_when_filtered(
    window, tmp_path
):
    """Searching the file list must not shrink the tag vocabulary."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, _first, _second, third = _make_dataset(tmp_path)
    source_label = third.with_suffix(".json")
    data = json.loads(source_label.read_text(encoding="utf-8"))
    data["tags"] = ["defect"]
    source_label.write_text(json.dumps(data), encoding="utf-8")

    widget.import_image_folder(str(images), auto_db=False)
    app.processEvents()
    assert "defect" in dict(widget._tag_library_source())

    # Simulate a search that shows only the first image.
    widget.files.table.setRowCount(1)
    widget._tag_library_dirty = True
    widget._refresh_tag_library()
    app.processEvents()

    list_widget = widget.tag_library_widget.list_widget
    texts = [
        list_widget.item(index).text()
        for index in range(list_widget.count())
    ]
    assert "defect" in texts


def test_tag_library_click_requires_login(window, tmp_path, monkeypatch):
    """The library stays clickable when logged out so it can ask for login."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    images, _first, _second, _third = _make_dataset(tmp_path)
    widget.import_image_folder(str(images), auto_db=False)
    app.processEvents()

    assert widget.tag_library_widget.list_widget.isEnabled() is True
    calls = []
    monkeypatch.setattr(
        widget,
        "_ensure_operator",
        lambda: calls.append(True) or False,
    )

    widget._on_tag_library_tag_clicked("defect")

    assert calls == [True]
    assert "defect" not in widget.image_tags_widget.tags


def test_tag_library_click_adds_tag_and_writes_attribution(
    window, monkeypatch
):
    """A library click must persist the tag and stamp the author at once."""
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    # The JSON save path uses mkstemp; pytest's tmp_path carries an
    # owner-only DACL that the DSH sandbox cannot write, so use a normal
    # directory for the write-through assertion.
    base = (
        Path(__file__).resolve().parents[2]
        / "temporary"
        / "pytest-tag-library-ui"
        / uuid.uuid4().hex
    )
    base.mkdir(parents=True, exist_ok=True)
    try:
        images, first, _second, third = _make_dataset(base)
        source_label = third.with_suffix(".json")
        data = json.loads(source_label.read_text(encoding="utf-8"))
        data["tags"] = ["defect"]
        source_label.write_text(json.dumps(data), encoding="utf-8")

        widget.import_image_folder(str(images), auto_db=False)
        widget.show_right_tab("flags")
        app.processEvents()

        session = SimpleNamespace(
            operator_name="tester", is_logged_in=True
        )
        monkeypatch.setattr(
            widget.operator_gate,
            "service",
            SimpleNamespace(session=session),
        )
        widget.tag_library_widget.set_editing_enabled(True)
        widget._tag_library_dirty = True
        widget._refresh_tag_library()
        app.processEvents()

        list_widget = widget.tag_library_widget.list_widget
        texts = [
            list_widget.item(index).text()
            for index in range(list_widget.count())
        ]
        assert "defect" in texts

        list_widget.itemDoubleClicked.emit(
            list_widget.item(texts.index("defect"))
        )
        QTest.qWait(30)
        app.processEvents()

        saved = json.loads(
            first.with_suffix(".json").read_text(encoding="utf-8")
        )
        assert "defect" in saved["tags"]
        assert saved["author"] == "tester"
        assert saved["modified_at"]
        assert "defect" in widget.image_tags_widget.tags

        remaining = [
            list_widget.item(index).text()
            for index in range(list_widget.count())
        ]
        assert "defect" not in remaining
        assert widget.dirty is False

        # Ctrl+click / the context menu turns a tag into a tags:: search.
        searches = []
        monkeypatch.setattr(
            widget,
            "file_search_changed",
            lambda: searches.append(widget.file_search.text()),
        )
        widget._search_tag_from_library("defect")
        assert widget.file_search.text() == "tags::defect"
        assert searches == ["tags::defect"]
        widget._search_tag_from_library("a,b")
        assert widget.file_search.text() == "tags::a\\,b"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_batch_tags_dialog_parses_tags_and_mode(window):
    from anylabeling.views.labeling.file_list.tags_dialog import (
        BatchTagsDialog,
    )

    dialog = BatchTagsDialog(
        3, ["defect", "blur"], translate=lambda text: text
    )
    dialog.library_widget.tag_clicked.emit("defect")
    assert dialog.tags_edit.text() == "defect"
    dialog.tags_edit.setText(" defect, blur ,defect ")
    assert dialog.tags() == ["defect", "blur"]
    assert dialog.mode() == "add"

    dialog.mode_combo.setCurrentIndex(1)
    dialog.old_tag_combo.setCurrentText("defect")
    dialog.new_tags_edit.setText("new, defect")
    assert dialog.mode() == "replace"
    assert dialog.old_tags() == ["defect"]
    assert dialog.tags() == ["new", "defect"]

    dialog.mode_combo.setCurrentIndex(2)
    assert dialog.mode() == "delete_all"
    assert dialog.tags() == []
    dialog.close()
