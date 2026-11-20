"""Controller for the labeling file list.

The controller owns the six-column file table, its row index, sorting and
column layout, thumbnails, the per-row split/checked decorations and the
multi-row commands.  It is deliberately separate from
:class:`anylabeling.views.labeling.label_widget.LabelingWidget` so the
file-list rules can be read, tested and changed without touching the
annotation editing flow.

The host object passed to the constructor must provide this small surface
(``LabelingWidget`` does):

* ``_config`` -- application configuration dict;
* ``tr()`` -- translation helper;
* ``output_dir`` -- directory of the annotation files, or ``None``;
* ``filename`` -- currently opened image path (read and written);
* ``actions`` -- action struct (unused here, kept for future row actions);
* ``load_file()`` / ``status()`` / ``copy_file_path()``;
* ``import_files_dialog()`` / ``open_folder_dialog()``;
* ``_annotation_checked_text()`` -- localized review status;
* ``_refresh_statistics_if_visible()`` / ``update_browse_actions()``;
* ``_no_selection_slot`` -- re-entrancy guard for selection changes;
* ``_ui_scale`` -- current interface scale used for row height.

Selection model: the table allows extended (Ctrl/Shift) selection, but only a
plain click or keyboard navigation may open the image.  ``FileTableWidget``
reports an extending press through ``selection_only_gesture()`` and
``LabelingWidget.file_selection_changed`` ignores that gesture.
"""

import os.path as osp

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import utils
from ..utils.file_meta import (
    SPLIT_KEYS,
    SPLIT_NONE,
    ensure_import_times,
    format_import_time,
    read_file_meta,
    read_import_time,
    write_split,
)
from ..utils.style import get_file_table_style
from ..utils.thumbnail import THUMBNAIL_SIZE, ThumbnailLoader
from .constants import (
    FILE_CHECKED_COLOR,
    FILE_COL_IMPORT_TIME,
    FILE_COL_INFERENCE,
    FILE_COL_NAME,
    FILE_COL_SHAPES,
    FILE_COL_SPLIT,
    FILE_COL_TAGS,
    FILE_COL_NAME_WIDTH,
    FILE_COLUMN_COUNT,
    FILE_COLUMN_WIDTHS,
    FILE_FAILED_COLOR,
    FILE_PATH_ROLE,
    FILE_ROW_HEIGHT,
    FILE_ROW_HEIGHT_COMPACT,
    FILE_SORT_ROLE,
    FILE_UNCHECKED_COLOR,
)
from .table import (
    FileNameDelegate,
    FileTableItem,
    FileTableWidget,
    create_file_status_icon,
)


class FileListController:
    """Own the file table and every row/column/selection rule around it."""

    def __init__(self, host):
        self.host = host
        self.fn_to_index = {}
        self._sort_column = None
        self._sort_order = QtCore.Qt.SortOrder.AscendingOrder
        self._show_thumbnails = True
        self._import_times = {}
        self._applying_file_columns = False
        self._thumbnail_loader = ThumbnailLoader(host)
        self._thumbnail_loader.thumbnail_ready.connect(
            self.on_thumbnail_ready
        )
        self.table = self._create_table()
        self.apply_config()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _create_table(self):
        host = self.host
        table = FileTableWidget()
        table.setObjectName("FileList")
        table.setColumnCount(FILE_COLUMN_COUNT)
        table.setHorizontalHeaderLabels(
            [
                host.tr("Files"),
                host.tr("Objects"),
                host.tr("Import Time"),
                host.tr("Inference"),
                host.tr("Split"),
                host.tr("Tags"),
            ]
        )
        table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.verticalHeader().setVisible(True)
        table.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Fixed
        )
        table.verticalHeader().setDefaultSectionSize(FILE_ROW_HEIGHT)
        table.verticalHeader().setMinimumWidth(22)
        header = table.horizontalHeader()
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive
        )
        header.setStretchLastSection(False)
        for column in range(FILE_COLUMN_COUNT):
            table.setColumnWidth(
                column, self.default_column_width(column)
            )
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.setMinimumSectionSize(40)
        header.sectionClicked.connect(self.sort_by_column)
        header.sectionResized.connect(self.on_column_resized)
        header.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        header.customContextMenuRequested.connect(self.pop_header_menu)
        table.setItemDelegateForColumn(
            FILE_COL_NAME, FileNameDelegate(table)
        )
        table.setIconSize(QtCore.QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        table.setStyleSheet(get_file_table_style())
        self.status_icons = {
            True: create_file_status_icon(FILE_CHECKED_COLOR),
            "failed": create_file_status_icon(FILE_FAILED_COLOR),
            False: create_file_status_icon(
                FILE_UNCHECKED_COLOR, filled=False
            ),
        }
        table.itemSelectionChanged.connect(host.file_selection_changed)
        table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        table.customContextMenuRequested.connect(self.pop_context_menu)
        return table

    def shutdown(self):
        """Stop the background thumbnail loader."""
        self._thumbnail_loader.shutdown()

    # ------------------------------------------------------------------
    # Row access
    # ------------------------------------------------------------------
    def label_file_for(self, file):
        label_file = osp.splitext(file)[0] + ".json"
        if self.host.output_dir:
            label_file = osp.join(
                self.host.output_dir, osp.basename(label_file)
            )
        return label_file

    def path_at(self, row):
        item = self.table.item(row, FILE_COL_NAME)
        if item is None:
            return ""
        path = item.data(FILE_PATH_ROLE)
        return str(path) if path else item.text()

    def row_of(self, path):
        mapping = self.fn_to_index or {}
        return mapping.get(str(path))

    def item_by_path(self, path):
        row = self.row_of(path)
        if row is None:
            return None
        return self.table.item(row, FILE_COL_NAME)

    def split_text(self, split):
        host = self.host
        return {
            SPLIT_NONE: host.tr("None"),
            "train": host.tr("Train"),
            "val": host.tr("Val"),
            "test": host.tr("Test"),
        }.get(split, host.tr("None"))

    # ------------------------------------------------------------------
    # Row construction and refresh
    # ------------------------------------------------------------------
    def build_row_cells(self, file, label_file=None, meta=None):
        if meta is None:
            if label_file is None:
                label_file = self.label_file_for(file)
            meta = read_file_meta(file, label_file)
        import_time = self._import_times.get(file)
        if import_time is None:
            import_time = read_import_time(file)

        name_item = FileTableItem(file, sort_key=osp.basename(file).lower())
        name_item.setData(FILE_PATH_ROLE, file)
        name_item.setCheckState(
            QtCore.Qt.CheckState.Checked
            if meta.exists
            else QtCore.Qt.CheckState.Unchecked
        )
        name_item.setData(
            QtCore.Qt.ItemDataRole.UserRole, meta.checked
        )
        name_item.setToolTip(
            f"{file}\n{self.host._annotation_checked_text(meta.checked)}"
        )

        shapes_item = FileTableItem(
            str(meta.shape_count), sort_key=meta.shape_count
        )
        shapes_item.setIcon(
            self.status_icons.get(
                meta.checked, self.status_icons[False]
            )
        )
        shapes_item.setToolTip(
            self.host._annotation_checked_text(meta.checked)
        )
        shapes_item.setTextAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        time_item = FileTableItem(
            format_import_time(import_time), sort_key=import_time
        )

        inference_item = FileTableItem("—", sort_key="")

        split = meta.split if meta.split in SPLIT_KEYS else SPLIT_NONE
        split_item = FileTableItem(
            self.split_text(split), sort_key=SPLIT_KEYS.index(split)
        )
        tags_item = self.build_tags_item(meta.tags)
        cells = [
            name_item,
            shapes_item,
            time_item,
            inference_item,
            split_item,
            tags_item,
        ]
        row_flags = (
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
        )
        for cell in cells:
            cell.setFlags(row_flags)
        return cells

    @staticmethod
    def tags_text(tags):
        """Format image tags for the file table (``"—"`` when empty)."""
        values = [str(tag) for tag in tags or ()]
        return ", ".join(values) if values else "—"

    def build_tags_item(self, tags):
        text = self.tags_text(tags)
        item = FileTableItem(
            text, sort_key="" if text == "—" else text.lower()
        )
        if text != "—":
            item.setToolTip(text)
        return item

    def append_row(self, file, label_file=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        cells = self.build_row_cells(file, label_file)
        for column, item in enumerate(cells):
            self.table.setItem(row, column, item)
        self.fn_to_index[file] = row
        self.request_thumbnail(row, file)
        self.invalidate_label_manager()
        return row

    def append_db_row(self, file, meta):
        """Append a row whose metadata came from the dataset database."""

        self._import_times[file] = meta.import_time
        row = self.table.rowCount()
        self.table.insertRow(row)
        cells = self.build_row_cells(file, meta=meta)
        for column, item in enumerate(cells):
            self.table.setItem(row, column, item)
        self.fn_to_index[file] = row
        self.request_thumbnail(row, file)
        self.invalidate_label_manager()
        return row

    def invalidate_label_manager(self):
        """Let the label manager re-scan when the file list changes."""
        panel = getattr(self.host, "label_manager_widget", None)
        if panel is not None:
            panel.invalidate()

    def apply_row_state(self, row, checked, shape_count=None):
        shapes_item = self.table.item(row, FILE_COL_SHAPES)
        if shapes_item is None:
            return
        if shape_count is None:
            path = self.path_at(row)
            meta = read_file_meta(path, self.label_file_for(path))
            shape_count = meta.shape_count
        shapes_item.setText(str(shape_count))
        shapes_item.setData(FILE_SORT_ROLE, shape_count)
        shapes_item.setIcon(
            self.status_icons.get(checked, self.status_icons[False])
        )
        shapes_item.setToolTip(self.host._annotation_checked_text(checked))

    def refresh_row(self, row, checked=None, shape_count=None):
        path = self.path_at(row)
        if not path:
            return
        meta = read_file_meta(path, self.label_file_for(path))
        name_item = self.table.item(row, FILE_COL_NAME)
        if name_item is not None:
            name_item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if meta.exists
                else QtCore.Qt.CheckState.Unchecked
            )
        effective_checked = meta.checked if checked is None else checked
        effective_count = (
            meta.shape_count if shape_count is None else shape_count
        )
        name_item = self.table.item(row, FILE_COL_NAME)
        if name_item is not None:
            name_item.setData(
                QtCore.Qt.ItemDataRole.UserRole, effective_checked
            )
            name_item.setToolTip(
                f"{path}\n"
                f"{self.host._annotation_checked_text(effective_checked)}"
            )
        self.apply_row_state(row, effective_checked, effective_count)
        split_item = self.table.item(row, FILE_COL_SPLIT)
        if split_item is not None:
            split = meta.split if meta.split in SPLIT_KEYS else SPLIT_NONE
            split_item.setText(self.split_text(split))
            split_item.setData(FILE_SORT_ROLE, SPLIT_KEYS.index(split))
        time_item = self.table.item(row, FILE_COL_IMPORT_TIME)
        if time_item is not None:
            time_item.setText(format_import_time(meta.import_time))
        self._apply_tags_item(
            self.table.item(row, FILE_COL_TAGS), meta.tags
        )

    def _apply_tags_item(self, item, tags):
        if item is None:
            return
        text = self.tags_text(tags)
        item.setText(text)
        item.setData(FILE_SORT_ROLE, "" if text == "—" else text.lower())
        item.setToolTip("" if text == "—" else text)

    def set_row_tags(self, path, tags):
        """Update the tags cell of ``path`` without re-reading the file.

        The image tags editor works on in-memory data until the file is saved,
        so the file table cannot take the tags from disk in that window.
        """
        row = self.row_of(str(path))
        if row is None:
            return
        self._apply_tags_item(self.table.item(row, FILE_COL_TAGS), tags)

    def rebuild_index(self):
        mapping = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, FILE_COL_NAME)
            if item is None:
                continue
            path = item.data(FILE_PATH_ROLE)
            mapping[str(path if path else item.text())] = row
        self.fn_to_index = mapping

    def update_import_times(self, files):
        self._import_times.update(ensure_import_times(files))

    # ------------------------------------------------------------------
    # Sorting and selection
    # ------------------------------------------------------------------
    def sort_by_column(self, column):
        if not 0 <= column < FILE_COLUMN_COUNT:
            return
        if self._sort_column == column:
            order = (
                QtCore.Qt.SortOrder.DescendingOrder
                if self._sort_order == QtCore.Qt.SortOrder.AscendingOrder
                else QtCore.Qt.SortOrder.AscendingOrder
            )
        else:
            order = QtCore.Qt.SortOrder.AscendingOrder
        self._sort_column = column
        self._sort_order = order
        self.sort(column, order)

    def sort(self, column, order):
        table = self.table
        rows = table.rowCount()
        if rows <= 1:
            return
        sortable = []
        for row in range(rows):
            item = table.item(row, column)
            key = item.data(FILE_SORT_ROLE) if item is not None else None
            if key is None:
                key = item.text() if item is not None else ""
            sortable.append((self.sort_key_value(key), row))
        sortable.sort(
            key=lambda pair: pair[0],
            reverse=order == QtCore.Qt.SortOrder.DescendingOrder,
        )
        order_rows = [row for _, row in sortable]
        table.blockSignals(True)
        try:
            taken = [
                [table.takeItem(row, col) for col in range(FILE_COLUMN_COUNT)]
                for row in range(rows)
            ]
            for new_row, old_row in enumerate(order_rows):
                for col, item in enumerate(taken[old_row]):
                    if item is not None:
                        table.setItem(new_row, col, item)
        finally:
            table.blockSignals(False)
        self.rebuild_index()
        table.horizontalHeader().setSortIndicator(column, order)
        self.sync_selection()
        self.invalidate_label_manager()

    @staticmethod
    def sort_key_value(key):
        if isinstance(key, (int, float)) and not isinstance(key, bool):
            return (0, float(key), "")
        return (1, 0.0, str(key).lower())

    def reset_sort(self):
        self._sort_column = None
        self._sort_order = QtCore.Qt.SortOrder.AscendingOrder
        header = self.table.horizontalHeader()
        header.setSortIndicator(-1, QtCore.Qt.SortOrder.AscendingOrder)

    def sync_selection(self):
        row = self.row_of(str(self.host.filename))
        if row is None:
            return
        self.host._no_selection_slot = True
        try:
            self.table.setCurrentCell(row, FILE_COL_NAME)
        finally:
            self.host._no_selection_slot = False

    def context_target_rows(self, item):
        """Rows a context-menu command applies to.

        Right-clicking inside a multi-row selection keeps that selection as
        the command target; right-clicking any other row targets only that
        row, which mirrors how file managers behave.
        """
        selected = self.table.selected_rows()
        if item is not None:
            row = item.row()
            if len(selected) > 1 and row in selected:
                return sorted(selected)
            return [row]
        return sorted(selected)

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------
    def request_thumbnail(self, row, path):
        if not self._show_thumbnails:
            return
        pixmap = self._thumbnail_loader.request(path)
        if pixmap is None:
            return
        item = self.table.item(row, FILE_COL_NAME)
        if item is not None:
            item.setIcon(QtGui.QIcon(pixmap))

    def on_thumbnail_ready(self, image_path, pixmap):
        if not self._show_thumbnails or pixmap is None or pixmap.isNull():
            return
        row = self.row_of(image_path)
        if row is None:
            return
        item = self.table.item(row, FILE_COL_NAME)
        if item is not None:
            item.setIcon(QtGui.QIcon(pixmap))

    def update_row_height(self):
        scale = getattr(self.host, "_ui_scale", 1.0) or 1.0
        base = (
            FILE_ROW_HEIGHT
            if self._show_thumbnails
            else FILE_ROW_HEIGHT_COMPACT
        )
        self.table.verticalHeader().setDefaultSectionSize(
            max(16, round(base * scale))
        )

    # ------------------------------------------------------------------
    # Column layout and persistence
    # ------------------------------------------------------------------
    def option(self, key, default=True):
        section = self.host._config.get("file_list")
        if not isinstance(section, dict):
            return default
        value = section.get(key, default)
        return default if value is None else bool(value)

    @staticmethod
    def default_column_width(column):
        if column == FILE_COL_NAME:
            return FILE_COL_NAME_WIDTH
        return FILE_COLUMN_WIDTHS.get(column, 80)

    def saved_column_widths(self):
        section = self.host._config.get("file_list")
        if not isinstance(section, dict):
            return {}
        widths = section.get("column_widths")
        if not isinstance(widths, dict):
            return {}
        cleaned = {}
        for column in range(FILE_COLUMN_COUNT):
            value = widths.get(str(column), widths.get(column))
            if isinstance(value, (int, float)) and value > 0:
                cleaned[column] = int(value)
        return cleaned

    def apply_config(self):
        for column, key in (
            (FILE_COL_IMPORT_TIME, "show_import_time"),
            (FILE_COL_INFERENCE, "show_inference"),
            (FILE_COL_SPLIT, "show_split"),
            (FILE_COL_TAGS, "show_tags"),
        ):
            self.table.setColumnHidden(
                column, not self.option(key, True)
            )
        saved_widths = self.saved_column_widths()
        self._applying_file_columns = True
        try:
            for column in range(FILE_COLUMN_COUNT):
                self.table.setColumnWidth(
                    column,
                    saved_widths.get(
                        column, self.default_column_width(column)
                    ),
                )
        finally:
            self._applying_file_columns = False
        if FILE_COL_NAME in saved_widths:
            self.table._auto_fill_name_column = False
        self.set_thumbnails_visible(
            self.option("show_thumbnails", True), persist=False
        )

    def on_column_resized(self, column, _old_size, new_size):
        if (
            self._applying_file_columns
            or self.table._adjusting_columns
            or new_size <= 0
        ):
            return
        if column == FILE_COL_NAME:
            # The user took manual control of the file column width.
            self.table._auto_fill_name_column = False
        else:
            self.table.fill_name_column()
        section = self.host._config.setdefault("file_list", {})
        if not isinstance(section, dict):
            return
        widths = section.get("column_widths")
        if not isinstance(widths, dict):
            widths = {}
            section["column_widths"] = widths
        widths[str(column)] = int(new_size)

    def set_column_visible(self, column, visible):
        if column == FILE_COL_NAME:
            return
        self.table.setColumnHidden(column, not visible)
        key = {
            FILE_COL_IMPORT_TIME: "show_import_time",
            FILE_COL_INFERENCE: "show_inference",
            FILE_COL_SPLIT: "show_split",
            FILE_COL_TAGS: "show_tags",
        }.get(column)
        if key:
            section = self.host._config.setdefault("file_list", {})
            if isinstance(section, dict):
                section[key] = bool(visible)

    def set_thumbnails_visible(self, visible, persist=True):
        self._show_thumbnails = bool(visible)
        self.table.setIconSize(
            QtCore.QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
            if self._show_thumbnails
            else QtCore.QSize(0, 0)
        )
        self.update_row_height()
        if self._show_thumbnails:
            for row in range(self.table.rowCount()):
                self.request_thumbnail(row, self.path_at(row))
        if persist:
            section = self.host._config.setdefault("file_list", {})
            if isinstance(section, dict):
                section["show_thumbnails"] = self._show_thumbnails

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------
    def pop_header_menu(self, point):
        header = self.table.horizontalHeader()
        menu = QtWidgets.QMenu(header)
        columns = (
            (FILE_COL_SHAPES, self.host.tr("Objects")),
            (FILE_COL_IMPORT_TIME, self.host.tr("Import Time")),
            (FILE_COL_INFERENCE, self.host.tr("Inference")),
            (FILE_COL_SPLIT, self.host.tr("Split")),
            (FILE_COL_TAGS, self.host.tr("Tags")),
        )
        for column, title in columns:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(column))
            action.setData(column)
        chosen = menu.exec(header.mapToGlobal(point))
        if chosen is not None:
            self.set_column_visible(chosen.data(), chosen.isChecked())

    def pop_context_menu(self, point):
        host = self.host
        item = self.table.itemAt(point)
        menu = QtWidgets.QMenu(self.table)
        import_files_action = menu.addAction(
            utils.new_icon("import-export", "svg"),
            host.tr("Import Files"),
        )
        import_folder_action = menu.addAction(
            utils.new_icon("folder-open", "svg"),
            host.tr("Import Folder"),
        )

        targets = self.context_target_rows(item)
        paths = [self.path_at(row) for row in targets]
        paths = [path for path in paths if path]
        multi = len(paths) > 1
        split_actions = {}
        copy_name_action = None
        copy_path_action = None
        thumbnail_action = None
        remove_action = None
        if targets:
            menu.addSeparator()
            copy_name_action = menu.addAction(
                utils.new_icon("copy", "svg"),
                host.tr("Copy File Names")
                if multi
                else host.tr("Copy File Name"),
            )
            copy_path_action = menu.addAction(
                utils.new_icon("copy", "svg"),
                host.tr("Copy File Paths")
                if multi
                else host.tr("Copy File Path"),
            )
            menu.addSeparator()
            split_menu = menu.addMenu(host.tr("Split"))
            split_group = QtGui.QActionGroup(split_menu)
            split_group.setExclusive(True)
            splits = {
                read_file_meta(path, self.label_file_for(path)).split
                for path in paths
            }
            current_split = splits.pop() if len(splits) == 1 else None
            for split_key in ("train", "val", "test", SPLIT_NONE):
                split_action = split_menu.addAction(
                    self.split_text(split_key)
                )
                split_action.setCheckable(True)
                split_action.setChecked(split_key == current_split)
                split_action.setData(split_key)
                split_group.addAction(split_action)
                split_actions[split_action] = split_key

            menu.addSeparator()
            thumbnail_action = menu.addAction(
                host.tr("Hide Thumbnails")
                if self._show_thumbnails
                else host.tr("Show Thumbnails")
            )
            remove_action = menu.addAction(
                host.tr("Remove %d Files from List") % len(paths)
                if multi
                else host.tr("Remove from List")
            )

        chosen = menu.exec(self.table.viewport().mapToGlobal(point))
        if chosen is None:
            return
        if chosen is import_files_action:
            host.import_files_dialog()
            return
        if chosen is import_folder_action:
            host.open_folder_dialog()
            return
        if not targets:
            return
        if chosen is copy_name_action:
            host.copy_file_path(
                "\n".join(osp.basename(path) for path in paths)
            )
        elif chosen is copy_path_action:
            host.copy_file_path("\n".join(paths))
        elif chosen is thumbnail_action:
            self.set_thumbnails_visible(not self._show_thumbnails)
        elif chosen is remove_action:
            self.remove_rows(targets)
        elif chosen in split_actions:
            self.set_split_rows(targets, split_actions[chosen])

    # ------------------------------------------------------------------
    # Row mutations
    # ------------------------------------------------------------------
    def set_split(self, row, split):
        self.set_split_rows([row], split)

    def _apply_split_item(self, row, split):
        item = self.table.item(row, FILE_COL_SPLIT)
        if item is None:
            return
        item.setText(self.split_text(split))
        item.setData(FILE_SORT_ROLE, SPLIT_KEYS.index(split))

    def set_split_rows(self, rows, split):
        """Store ``split`` for every row; one status message for the batch."""
        host = self.host
        targets = [
            row
            for row in dict.fromkeys(rows)
            if 0 <= row < self.table.rowCount()
        ]
        if not targets:
            return
        repository = getattr(host, "dataset_repository", None)
        root = getattr(host, "dataset_root", None)
        updated = 0
        failed = []
        for row in targets:
            file_path = self.path_at(row)
            if not file_path:
                continue
            if repository is not None:
                relative = None
                if root:
                    relative = osp.relpath(file_path, root).replace("\\", "/")
                image = (
                    repository.find_image(relative) if relative else None
                )
                if image is not None and repository.set_split(
                    image["id"], split
                ):
                    self._apply_split_item(row, split)
                    if (
                        host.image_path
                        and osp.normcase(osp.abspath(file_path))
                        == osp.normcase(osp.abspath(host.image_path))
                    ):
                        host.other_data["split"] = split
                    updated += 1
                else:
                    failed.append(file_path)
            elif write_split(
                self.label_file_for(file_path), split, image_path=file_path
            ):
                self.refresh_row(row)
                updated += 1
            else:
                failed.append(file_path)
        host._refresh_statistics_if_visible()
        if failed:
            host.status(
                host.tr("Failed to update split for %s")
                % ", ".join(osp.basename(path) for path in failed)
            )
            return
        if updated == 1:
            host.status(
                host.tr("Split of %s set to %s")
                % (
                    osp.basename(self.path_at(targets[0])),
                    self.split_text(split),
                )
            )
            return
        host.status(
            host.tr("Split of %d files set to %s")
            % (updated, self.split_text(split))
        )

    def remove_row(self, row):
        self.remove_rows([row])

    def remove_rows(self, rows):
        """Remove rows from the list (images and JSON files stay on disk)."""
        host = self.host
        targets = sorted(
            {row for row in rows if 0 <= row < self.table.rowCount()}
        )
        if not targets:
            return
        paths = [self.path_at(row) for row in targets]
        paths = [path for path in paths if path]
        if len(paths) == 1:
            question = host.tr(
                'Remove "%s" from the file list?\n'
                "The image file and its annotation file will NOT be deleted."
            ) % osp.basename(paths[0])
        else:
            question = host.tr(
                "Remove %d files from the file list?\n"
                "The image files and their annotation files "
                "will NOT be deleted."
            ) % len(paths)
        answer = QtWidgets.QMessageBox.question(
            host,
            host.tr("Remove File"),
            question,
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        was_current = str(host.filename) in {str(path) for path in paths}
        first_row = targets[0]
        self.table.blockSignals(True)
        try:
            for row in reversed(targets):
                self.table.removeRow(row)
        finally:
            self.table.blockSignals(False)
        self.rebuild_index()
        if was_current:
            if self.table.count() > 0:
                next_row = min(first_row, self.table.count() - 1)
                host.filename = None
                self.table.setCurrentCell(next_row, FILE_COL_NAME)
                next_path = self.path_at(next_row)
                if next_path:
                    host.load_file(next_path)
            else:
                host.filename = None
        elif str(host.filename) in self.fn_to_index:
            self.sync_selection()
        host.update_browse_actions()
        host._refresh_statistics_if_visible()
        self.invalidate_label_manager()

    def clear(self):
        self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setRowCount(0)
        finally:
            self.table.blockSignals(False)
        self.fn_to_index.clear()
        self._import_times = {}
        self.reset_sort()
        self._thumbnail_loader.clear()
        self.invalidate_label_manager()
