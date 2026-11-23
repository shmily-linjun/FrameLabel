"""Label manager panel hosted by the "Classes" tab.

This panel used to be the modal ``LabelModifyDialog`` ("Label Change
Manager").  It manages categories across the images of the current file list:
renaming and deleting categories inside a file range, plus the session-only
visibility, lock and colour policies.  Hosting it in the right-sidebar tab
keeps the category entry one click away without opening a second window.

Host contract (``LabelingWidget`` provides it):

* ``filename`` / ``file_list_widget`` / ``output_dir``;
* ``label_info`` -- per-category ``{delete, value, color, opacity, visible,
  locked}`` state shared with the canvas and the object list;
* ``unique_label_list`` -- session registry of the current image's categories
  (it keeps ``lock_states`` and the per-category colours);
* ``label_dialog`` -- the class history shown by the category editor;
* ``_get_rgb_by_label()`` / ``apply_label_visibility()`` / ``load_file()`` /
  ``_refresh_statistics_if_visible()`` / ``_operator_edit_allowed()`` /
  ``tr()`` / ``status()``.

The panel writes annotation JSON files directly (like the dialog did) and is
disabled while nobody is logged in.
"""

import json
import os

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import QColorDialog, QTableWidgetItem

from ..logger import logger
from ..utils.category_names import parse_category_names
from ..utils.qt import new_icon, new_icon_path
from ..utils.style import (
    get_compact_ok_btn_style,
    get_compact_spinbox_style,
)
from .label_dialog import natural_sort_key
from .popup import Popup

#: Translation context of this panel (its own, not ``LabelingWidget``).
TRANSLATION_CONTEXT = "LabelManagerPanel"

#: Delay used to coalesce several category changes (a file load can add many
#: categories) into one rebuild of the visible table.
REFRESH_DELAY_MS = 120


class LabelColorButton(QtWidgets.QWidget):
    """Small colour swatch that opens a colour dialog when clicked."""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self._on_click = None
        self.setFixedSize(28, 20)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def set_color(self, color):
        self._color = QtGui.QColor(color)
        self.update()

    def color(self):
        return QtGui.QColor(self._color)

    def set_on_click(self, callback):
        self._on_click = callback

    def mousePressEvent(self, event):
        if self._on_click is not None and event.button() == (
            QtCore.Qt.MouseButton.LeftButton
        ):
            self._on_click(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor("#8C98A4"), 1))
        painter.setBrush(self._color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)
        painter.end()


class LabelManagerPanel(QtWidgets.QWidget):
    """Category manager: rename/delete across a range, session policies."""

    #: Emitted after the annotation files (or the session state) changed.
    applied = QtCore.pyqtSignal()

    COL_LABEL = 0
    COL_DELETE = 1
    COL_VISIBLE = 2
    COL_LOCK = 3
    COL_COLOR = 4
    COLUMN_COUNT = 5

    def __init__(self, host, parent=None):
        super().__init__(parent)
        # Imported lazily: ``labeling.constants`` imports ``labeling.utils``,
        # which is still initializing while the widgets package is imported.
        from ..constants import LABEL_OPACITY

        self.host = host
        self.opacity = LABEL_OPACITY
        self._editing_enabled = False
        self._dirty = True
        self._built_for = None
        # Coalesced live refresh: ``invalidate()`` only schedules a rebuild
        # when the "Classes" tab is the visible page, so a file load that
        # introduces many categories still rebuilds once.
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(REFRESH_DELAY_MS)
        self._refresh_timer.timeout.connect(self._refresh_if_visible)
        self._build_ui()

    def _tr(self, text):
        return QtCore.QCoreApplication.translate(TRANSLATION_CONTEXT, text)

    def minimumSizeHint(self):
        # The sidebar may be dragged narrow; the table scrolls horizontally
        # instead of forcing the whole right panel wider.
        return QtCore.QSize(0, 0)

    def sizeHint(self):
        # A five-column table plus the range row would otherwise ask for
        # ~390px and raise the sidebar's minimum width (see
        # ``workspace.build_workspace``), so the panel advertises a modest
        # preferred width and lets the layout decide the real one.
        return QtCore.QSize(240, 240)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setObjectName("LabelManagerTable")
        self.table.setColumnCount(self.COLUMN_COUNT)
        self.table.setHorizontalHeaderLabels(
            [
                self._tr("Category"),
                self._tr("Delete"),
                self._tr("Visible"),
                self._tr("Lock"),
                self._tr("Color"),
            ]
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table.setMinimumWidth(0)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(24)
        header.setSectionResizeMode(
            self.COL_LABEL, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        for column in (
            self.COL_DELETE,
            self.COL_VISIBLE,
            self.COL_LOCK,
            self.COL_COLOR,
        ):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
        header.setStretchLastSection(False)
        self.table.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.table.customContextMenuRequested.connect(
            self._show_context_menu
        )
        layout.addWidget(self.table, 1)

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.setContentsMargins(2, 0, 2, 1)
        range_layout.setSpacing(3)
        self.from_input = QtWidgets.QSpinBox()
        self.from_input.setMinimum(1)
        self.from_input.setFixedSize(52, 22)
        self.from_input.setStyleSheet(get_compact_spinbox_style())
        self.to_input = QtWidgets.QSpinBox()
        self.to_input.setMinimum(1)
        self.to_input.setFixedSize(52, 22)
        self.to_input.setStyleSheet(get_compact_spinbox_style())
        self.range_button = QtWidgets.QPushButton(self._tr("Go"))
        self.range_button.setStyleSheet(get_compact_ok_btn_style())
        self.range_button.setFixedHeight(22)
        self.range_button.setMinimumWidth(36)
        self.range_button.setMaximumWidth(48)
        self.range_button.clicked.connect(self.apply_changes)
        from_label = QtWidgets.QLabel(self._tr("From"))
        from_label.setStyleSheet("font-size: 12px;")
        to_label = QtWidgets.QLabel(self._tr("To"))
        to_label.setStyleSheet("font-size: 12px;")
        range_layout.addWidget(from_label)
        range_layout.addWidget(self.from_input)
        range_layout.addWidget(to_label)
        range_layout.addWidget(self.to_input)
        range_layout.addWidget(self.range_button)
        range_layout.addStretch(1)
        # Category order is the export order (``category.sort_index``), so it
        # is edited here by moving the selected row up/down.
        self.move_up_button = self._create_reorder_button(
            "caret-up", self._tr("Move Up"), -1
        )
        self.move_down_button = self._create_reorder_button(
            "caret-down", self._tr("Move Down"), 1
        )
        range_layout.addWidget(self.move_up_button)
        range_layout.addWidget(self.move_down_button)
        layout.addLayout(range_layout)
        self.table.currentCellChanged.connect(
            lambda *_args: self._update_reorder_buttons()
        )

    def import_categories(self):
        """Append pasted category names to the dataset vocabulary."""
        if not self._editing_enabled:
            return
        repository = getattr(self.host, "dataset_repository", None)
        if repository is None:
            self._error(
                self._tr(
                    "Batch import is only available for dataset folders."
                )
            )
            return
        text, accepted = QtWidgets.QInputDialog.getMultiLineText(
            self,
            self._tr("Batch Import Categories"),
            self._tr(
                "Enter category names separated by commas, spaces, or "
                "newlines:"
            ),
            "",
        )
        if not accepted:
            return
        names = parse_category_names(text)
        if not names:
            self._error(self._tr("Enter at least one category."))
            return
        existing = {
            row["name"] for row in repository.category_counts()
        }
        added = 0
        try:
            for name in names:
                if name in existing:
                    continue
                repository.ensure_category(name)
                added += 1
        except Exception as error:  # noqa: BLE001 - surfaced as a popup
            logger.error(f"Failed to import categories: {error}")
            self._error(
                self._tr("An error occurred while importing categories.")
            )
            return
        self.invalidate()
        self.rebuild()
        self._success(
            self._tr("Imported %d categories.") % added
        )

    def _create_reorder_button(self, icon, tooltip, offset):
        button = QtWidgets.QToolButton(self)
        button.setIcon(new_icon(icon, "svg"))
        button.setIconSize(QtCore.QSize(14, 14))
        button.setFixedSize(24, 22)
        button.setAutoRaise(True)
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.clicked.connect(
            lambda _checked=False, step=offset: self.move_selected_category(
                step
            )
        )
        return button

    # ------------------------------------------------------------------
    # Host state helpers
    # ------------------------------------------------------------------
    def _files(self):
        table = self.host.file_list_widget
        return [table.item(row).text() for row in range(table.count())]

    def _label_file_for(self, image_file):
        directory, filename = os.path.split(image_file)
        if self.host.output_dir:
            directory = self.host.output_dir
        return os.path.join(
            directory, os.path.splitext(filename)[0] + ".json"
        )

    def _label_info(self, label):
        info = self.host.label_info.get(label)
        if info is None:
            info = {
                "delete": False,
                "value": None,
                "color": list(
                    self.host._get_rgb_by_label(label, skip_label_info=True)
                ),
                "opacity": self.opacity,
                "visible": True,
                "locked": False,
            }
            self.host.label_info[label] = info
        return info

    # ------------------------------------------------------------------
    # Building the table
    # ------------------------------------------------------------------
    def invalidate(self):
        """Mark the cached rows stale (file list or labels changed).

        When the "Classes" tab is the visible page the table is rebuilt after
        a short delay, so importing images or creating/deleting/renaming a
        category shows up without clicking the tab again.  Hidden pages only
        keep the dirty flag and rebuild on their next activation.
        """
        self._dirty = True
        if self._is_visible_page():
            self._refresh_timer.start()

    def _is_visible_page(self):
        tabs = getattr(self.host, "right_tabs", None)
        if tabs is None:
            return self.isVisible()
        page = tabs.currentWidget()
        if page is None:
            return False
        # The panel is hosted inside a rounded container that is the actual
        # tab page, so check the ancestor chain instead of identity.
        return page is self or page.isAncestorOf(self)

    def _refresh_if_visible(self):
        if not self._dirty or not self._is_visible_page():
            return
        if (
            self.table.state()
            == QtWidgets.QAbstractItemView.State.EditingState
        ):
            # A rename is in progress; rebuild after the editor closes so the
            # typed text is not thrown away.
            self._refresh_timer.start()
            return
        self.rebuild()

    def flush_refresh(self):
        """Apply a pending live refresh immediately (used by tests)."""
        self._refresh_timer.stop()
        self._refresh_if_visible()

    def ensure_built(self):
        files = self._files()
        if not self._dirty and files == self._built_for:
            return
        self.rebuild()

    def rebuild(self):
        self._refresh_timer.stop()
        files = self._files()
        previous_rows = self.table.rowCount()
        previous_range = (self.from_input.value(), self.to_input.value())
        previous_label = self._selected_category()
        self._built_for = list(files)
        self._dirty = False
        labels = self._collect_labels(files)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.table.setRowCount(len(labels))
            for row, label in enumerate(labels):
                self._fill_row(row, label)
        finally:
            self.table.blockSignals(False)
        total = max(1, len(files))
        self.from_input.setMaximum(total)
        self.to_input.setMaximum(total)
        if (
            previous_rows
            and 1 <= previous_range[0] <= total
            and previous_range[1] <= total
        ):
            # Keep the range the user picked; a rebuild triggered by an
            # annotation change must not silently widen it to every file.
            self.from_input.setValue(previous_range[0])
            self.to_input.setValue(previous_range[1])
        else:
            self.from_input.setValue(1)
            self.to_input.setValue(total)
        if previous_label is not None:
            self._select_category(previous_label)
        self.table.setEnabled(self._editing_enabled)
        self.range_button.setEnabled(
            self._editing_enabled and bool(labels)
        )
        self._update_reorder_buttons()

    def _selected_category(self):
        """Category data of the current row (``None`` without a row)."""
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, self.COL_LABEL)
        if item is None:
            return None
        label = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return label if isinstance(label, str) else None

    def _select_category(self, label):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_LABEL)
            if item is None:
                continue
            if item.data(QtCore.Qt.ItemDataRole.UserRole) == label:
                self.table.setCurrentCell(row, self.COL_LABEL)
                return

    def _collect_labels(self, files):
        repository = getattr(self.host, "dataset_repository", None)
        if repository is not None:
            # The database is authoritative and already ordered by
            # ``category.sort_index``.  Keep zero-object categories too:
            # batch import declares classes that have no objects yet, and the
            # export order must include them.
            return [
                row["name"]
                for row in repository.category_counts()
            ]
        labels = set()
        for image_file in files:
            label_file = self._label_file_for(image_file)
            if not os.path.exists(label_file):
                continue
            try:
                with open(label_file, "r", encoding="utf-8") as stream:
                    data = json.load(stream)
            except (OSError, ValueError) as error:
                logger.warning(
                    f"Label manager skipped {label_file}: {error}"
                )
                continue
            for shape in data.get("shapes") or []:
                label = shape.get("label")
                if isinstance(label, str):
                    labels.add(label)
        registry = getattr(self.host, "unique_label_list", None)
        if registry is not None:
            for row in range(registry.count()):
                label = registry.item(row).data(
                    QtCore.Qt.ItemDataRole.UserRole
                )
                if isinstance(label, str):
                    labels.add(label)
        return sorted(labels, key=natural_sort_key)

    def _fill_row(self, row, label):
        info = self._label_info(label)
        item = QTableWidgetItem(label)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, label)
        item.setToolTip(self._tr("Double-click to rename the category"))
        self.table.setItem(row, self.COL_LABEL, item)

        delete_checkbox = QtWidgets.QCheckBox()
        delete_checkbox.setChecked(bool(info.get("delete")))
        delete_checkbox.setToolTip(
            self._tr("Delete this category from the images in the range")
        )
        delete_checkbox.stateChanged.connect(
            lambda state, r=row: self._update_row_state(r)
        )
        self.table.setCellWidget(
            row, self.COL_DELETE, self._checkbox_container(delete_checkbox)
        )

        visible_checkbox = QtWidgets.QCheckBox()
        visible_checkbox.setChecked(info.get("visible", True))
        visible_checkbox.setToolTip(
            self._tr("Show or hide the category in this session")
        )
        self.table.setCellWidget(
            row,
            self.COL_VISIBLE,
            self._checkbox_container(visible_checkbox),
        )

        lock_checkbox = QtWidgets.QCheckBox()
        lock_checkbox.setChecked(
            bool(self.host.unique_label_list.lock_states.get(label, False))
        )
        lock_checkbox.setToolTip(
            self._tr("Session-only category lock; independent of the range")
        )
        self.table.setCellWidget(
            row, self.COL_LOCK, self._checkbox_container(lock_checkbox)
        )

        color = QtGui.QColor(*info["color"])
        color.setAlpha(info.get("opacity", self.opacity))
        color_button = LabelColorButton(color, self.table)
        color_button.set_on_click(
            lambda button, r=row: self._change_color(r, button)
        )
        self.table.setCellWidget(row, self.COL_COLOR, color_button)
        self._update_row_state(row)

    @staticmethod
    def _checkbox_container(checkbox):
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(checkbox)
        return container

    def _checkbox(self, row, column):
        container = self.table.cellWidget(row, column)
        if container is None:
            return None
        return container.layout().itemAt(0).widget()

    def _update_row_state(self, row):
        item = self.table.item(row, self.COL_LABEL)
        checkbox = self._checkbox(row, self.COL_DELETE)
        if item is None or checkbox is None:
            return
        if checkbox.isChecked():
            item.setFlags(
                item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
            )
        else:
            item.setFlags(
                item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable
            )

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------
    def set_editing_enabled(self, enabled):
        self._editing_enabled = bool(enabled)
        self.table.setEnabled(self._editing_enabled)
        self.from_input.setEnabled(self._editing_enabled)
        self.to_input.setEnabled(self._editing_enabled)
        self.range_button.setEnabled(
            self._editing_enabled and self.table.rowCount() > 0
        )
        import_button = getattr(self.host, "category_import_button", None)
        if import_button is not None:
            import_button.setEnabled(self._editing_enabled)
        hint = (
            ""
            if self._editing_enabled
            else self._tr(
                "Browse mode - editing annotations requires login"
            )
        )
        self.table.setToolTip(hint)
        self.range_button.setToolTip(hint)
        self._update_reorder_buttons()

    def _update_reorder_buttons(self):
        """Enable the up/down buttons only when a move is possible.

        Reordering is persisted through ``DatasetRepository``; without a
        dataset database there is no authority for the category order, so the
        buttons explain why they are disabled instead of reordering a table
        that the next refresh would sort again.
        """
        repository = getattr(self.host, "dataset_repository", None)
        row = self.table.currentRow()
        rows = self.table.rowCount()
        can_move = bool(self._editing_enabled and repository is not None)
        self.move_up_button.setEnabled(can_move and 0 < row < rows)
        self.move_down_button.setEnabled(can_move and 0 <= row < rows - 1)
        hint = (
            self._tr("Category order is stored in the dataset database")
            if repository is None
            else ""
        )
        for button, title in (
            (self.move_up_button, self._tr("Move Up")),
            (self.move_down_button, self._tr("Move Down")),
        ):
            tooltip = hint or title
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)

    def move_selected_category(self, offset):
        """Move the selected category one row up/down and persist the order."""
        if not self._editing_enabled:
            return
        repository = getattr(self.host, "dataset_repository", None)
        if repository is None:
            return
        row = self.table.currentRow()
        target = row + int(offset)
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        names = [
            self.table.item(index, self.COL_LABEL).data(
                QtCore.Qt.ItemDataRole.UserRole
            )
            for index in range(self.table.rowCount())
        ]
        names[row], names[target] = names[target], names[row]
        try:
            saved = repository.set_category_order(names)
        except Exception as error:  # noqa: BLE001 - surfaced as a popup
            logger.error(f"Failed to reorder categories: {error}")
            saved = False
        if not saved:
            self._error(
                self._tr(
                    "An error occurred while reordering the categories."
                )
            )
            return
        self._dirty = True
        self.rebuild()
        self._select_category(names[target])
        self._update_reorder_buttons()

    def selected_label(self):
        """Category of the current row, used as the default for new shapes."""
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, self.COL_LABEL)
        if item is None or not item.text().strip():
            return None
        checkbox = self._checkbox(row, self.COL_DELETE)
        if checkbox is not None and checkbox.isChecked():
            return None
        return item.text().strip()

    def _change_color(self, row, button):
        item = self.table.item(row, self.COL_LABEL)
        if item is None:
            return
        label = item.data(QtCore.Qt.ItemDataRole.UserRole)
        info = self._label_info(label)
        color = QColorDialog.getColor(QtGui.QColor(*info["color"]), self)
        if not color.isValid():
            return
        info["color"] = [color.red(), color.green(), color.blue()]
        info["opacity"] = color.alpha()
        button.set_color(color)
        registry = getattr(self.host, "unique_label_list", None)
        if registry is not None:
            registry.update_item_color(
                label, info["color"], info.get("opacity", self.opacity)
            )

    def _show_context_menu(self, pos):
        column = self.table.columnAt(pos.x())
        row = self.table.rowAt(pos.y())
        menu = QtWidgets.QMenu(self.table)
        if column in (self.COL_VISIBLE, self.COL_LOCK):
            select_all = menu.addAction(self._tr("Select All"))
            deselect_all = menu.addAction(self._tr("Deselect All"))
            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            checked = chosen is select_all
            for index in range(self.table.rowCount()):
                checkbox = self._checkbox(index, column)
                if checkbox is not None:
                    checkbox.setChecked(checked)
            return
        if column == self.COL_LABEL and row >= 0:
            copy_action = menu.addAction(self._tr("Copy Category"))
            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen is copy_action:
                item = self.table.item(row, self.COL_LABEL)
                if item is not None:
                    QtWidgets.QApplication.clipboard().setText(item.text())

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def _read_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_LABEL)
            if item is None:
                continue
            original = item.data(QtCore.Qt.ItemDataRole.UserRole)
            delete_checkbox = self._checkbox(row, self.COL_DELETE)
            visible_checkbox = self._checkbox(row, self.COL_VISIBLE)
            lock_checkbox = self._checkbox(row, self.COL_LOCK)
            rows.append(
                {
                    "original": original,
                    "label": item.text().strip() or original,
                    "delete": bool(
                        delete_checkbox and delete_checkbox.isChecked()
                    ),
                    "visible": bool(
                        visible_checkbox and visible_checkbox.isChecked()
                    ),
                    "locked": bool(
                        lock_checkbox and lock_checkbox.isChecked()
                    ),
                }
            )
        return rows

    def _validated_changes(self, rows):
        """Return ``(renames, deletes)`` or ``None`` after telling the user."""
        renames = {}
        deletes = set()
        finals = set()
        for row in rows:
            if row["delete"]:
                deletes.add(row["original"])
                continue
            label = row["label"]
            if not label:
                self._error(self._tr("Category cannot be empty"))
                return None
            if label in finals:
                self._error(
                    self._tr("Duplicate category: %s") % label
                )
                return None
            finals.add(label)
            if label != row["original"]:
                renames[row["original"]] = label
        return renames, deletes

    def apply_changes(self):
        if not self._editing_enabled:
            return
        files = self._files()
        if not files:
            self._error(self._tr("No images loaded"))
            return
        start = int(self.from_input.value())
        end = int(self.to_input.value())
        if start < 1 or end < start or end > len(files):
            self.from_input.setValue(1)
            self.to_input.setValue(len(files))
            self._error(self._tr("Please enter a valid range."))
            return
        rows = self._read_rows()
        if not rows:
            return
        validated = self._validated_changes(rows)
        if validated is None:
            return
        renames, deletes = validated
        if (renames or deletes) and not self._rewrite_files(
            files[start - 1 : end], renames, deletes
        ):
            self._error(
                self._tr("An error occurred while updating the labels.")
            )
            return
        self._apply_session_state(rows)
        if renames or deletes:
            self._label_dialog_history(renames, deletes)
            self.host._refresh_statistics_if_visible()
            if self.host.filename:
                self.host.load_file(self.host.filename)
        self.host.apply_label_visibility()
        self._success(self._tr("Labels modified successfully!"))
        self.applied.emit()
        self.invalidate()
        self.ensure_built()

    def _apply_session_state(self, rows):
        info_store = self.host.label_info
        states = self.host.unique_label_list.lock_states
        updated = {}
        for row in rows:
            original = row["original"]
            info = info_store.get(original)
            if info is None:
                continue
            if row["delete"]:
                info_store.pop(original, None)
                states.pop(original, None)
                continue
            target = row["label"]
            info["delete"] = False
            info["value"] = None
            info["visible"] = row["visible"]
            info["locked"] = row["locked"]
            updated[target] = info
            if target != original:
                info_store.pop(original, None)
                if original in states:
                    states[target] = states.pop(original)
            states[target] = bool(row["locked"])
        info_store.update(updated)
        registry = getattr(self.host, "unique_label_list", None)
        if registry is None:
            return
        for row in rows:
            original = row["original"]
            if row["delete"]:
                registry.remove_items_by_label(original)
                continue
            target = row["label"]
            if target != original:
                registry.remove_items_by_label(original)
            info = self.host.label_info.get(target)
            if info is None:
                continue
            registry.update_item_color(
                target,
                info["color"],
                info.get("opacity", self.opacity),
            )
            for item in registry.find_items_by_label(target):
                registry.set_item_locked(
                    item, states.get(target, False)
                )

    def _label_dialog_history(self, renames, deletes):
        dialog = getattr(self.host, "label_dialog", None)
        if dialog is None:
            return
        for label in deletes:
            dialog.remove_label_history(label)
        for old, new in renames.items():
            dialog.remove_label_history(old)
            dialog.add_label_history(new)

    def _rewrite_files(self, files, renames, deletes):
        repository = getattr(self.host, "dataset_repository", None)
        if repository is not None:
            return self._rewrite_database(repository, files, renames, deletes)
        try:
            for image_file in files:
                label_file = self._label_file_for(image_file)
                if not os.path.exists(label_file):
                    continue
                with open(label_file, "r", encoding="utf-8") as stream:
                    data = json.load(stream)
                shapes = []
                for shape in data.get("shapes") or []:
                    label = shape.get("label")
                    if label in deletes:
                        continue
                    if label in renames:
                        shape["label"] = renames[label]
                    shapes.append(shape)
                data["shapes"] = shapes
                with open(label_file, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, indent=2, ensure_ascii=False)
            return True
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.error(f"Error occurred while updating labels: {error}")
            return False

    def _rewrite_database(self, repository, files, renames, deletes):
        root = getattr(self.host, "dataset_root", None)
        if not root:
            return False
        image_ids = []
        for image_file in files:
            relative = os.path.relpath(image_file, root).replace(os.sep, "/")
            image = repository.find_image(relative)
            if image is not None:
                image_ids.append(image["id"])
        if not image_ids:
            return False
        try:
            counts = {
                row["name"]: int(row["object_count"])
                for row in repository.category_counts()
            }
            empty_renames = {
                old: new
                for old, new in renames.items()
                if counts.get(old, 0) == 0
            }
            empty_deletes = {
                old for old in deletes if counts.get(old, 0) == 0
            }
            for old, new in empty_renames.items():
                if not repository.rename_category(old, new):
                    return False
            for old in empty_deletes:
                if not repository.delete_category(old):
                    return False

            object_renames = {
                old: new
                for old, new in renames.items()
                if old not in empty_renames
            }
            object_deletes = {
                old for old in deletes if old not in empty_deletes
            }
            if object_renames or object_deletes:
                repository.rewrite_categories(
                    image_ids, object_renames, object_deletes
                )
            # If the selected range covered every object, the old name is now
            # empty; drop the category row so it does not linger in export.
            for old in object_renames:
                if repository.category_object_count(old) == 0:
                    repository.delete_category(old)
            for old in object_deletes:
                if repository.category_object_count(old) == 0:
                    repository.delete_category(old)
            return True
        except Exception as error:  # noqa: BLE001 - surfaced as a popup
            logger.error(f"Error occurred while updating labels: {error}")
            return False

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def _success(self, message):
        popup = Popup(
            message,
            self.host,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self.host)

    def _error(self, message):
        popup = Popup(
            message,
            self.host,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self.host)
