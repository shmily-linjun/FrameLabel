"""Tag library shown in the "Image Attributes" tab (fork.34).

The widget only renders the vocabulary; adding a tag to the current image and
persisting it is driven by ``LabelingWidget``.  Tags already present on the
current image are hidden: the row of chips above is the place to inspect or
remove them.
"""

from PyQt6 import QtCore, QtWidgets

from ..utils.theme import get_theme


class TagLibraryWidget(QtWidgets.QWidget):
    tag_clicked = QtCore.pyqtSignal(str)
    tag_search_requested = QtCore.pyqtSignal(str)

    def __init__(self, translate, parent=None):
        super().__init__(parent)
        self._tr = translate or (lambda text: text)
        self._entries = []
        self._current = set()
        self._collapsed = False
        self._editing_enabled = True
        theme = get_theme()
        self._theme = theme

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(6, 6, 6, 2)
        header.setSpacing(4)
        self.title_label = QtWidgets.QLabel(self._tr("Tag Library"))
        self.title_label.setStyleSheet(
            f"QLabel {{ color: {theme['text_secondary']};"
            " font-size: 11px; font-weight: 600; }"
        )
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setStyleSheet(
            f"QLabel {{ color: {theme['text_secondary']}; font-size: 11px; }}"
        )
        self.collapse_button = QtWidgets.QToolButton()
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.setArrowType(QtCore.Qt.ArrowType.DownArrow)
        self.collapse_button.setToolTip(self._tr("Collapse tag library"))
        self.collapse_button.clicked.connect(self._toggle_collapsed)
        header.addWidget(self.title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)
        header.addWidget(self.collapse_button)
        layout.addLayout(header)

        self.body = QtWidgets.QWidget(self)
        body_layout = QtWidgets.QVBoxLayout(self.body)
        body_layout.setContentsMargins(6, 0, 6, 6)
        body_layout.setSpacing(4)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText(self._tr("Search tags…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedHeight(24)
        self.search_edit.textChanged.connect(self._rebuild)
        body_layout.addWidget(self.search_edit)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setObjectName("TagLibrary")
        self.list_widget.setViewMode(
            QtWidgets.QListView.ViewMode.IconMode
        )
        self.list_widget.setFlow(QtWidgets.QListView.Flow.LeftToRight)
        self.list_widget.setWrapping(True)
        self.list_widget.setResizeMode(
            QtWidgets.QListView.ResizeMode.Adjust
        )
        self.list_widget.setMovement(
            QtWidgets.QListView.Movement.Static
        )
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setGridSize(QtCore.QSize(112, 26))
        self.list_widget.setSpacing(4)
        self.list_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.list_widget.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.list_widget.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.list_widget.setTextElideMode(
            QtCore.Qt.TextElideMode.ElideRight
        )
        self.list_widget.setStyleSheet(
            f"""
            QListWidget#TagLibrary {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QListWidget#TagLibrary::item {{
                background: {theme["surface"]};
                color: {theme["text"]};
                border: 1px solid {theme["border"]};
                border-radius: 10px;
                padding: 2px 6px;
            }}
            QListWidget#TagLibrary::item:hover {{
                background: {theme["surface_hover"]};
                border-color: {theme["border_light"]};
            }}
            QListWidget#TagLibrary::item:selected {{
                background: {theme["selection"]};
                color: {theme["selection_text"]};
                border-color: {theme["highlight"]};
            }}
            """
        )
        self.list_widget.setMinimumHeight(80)
        self.list_widget.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.list_widget.customContextMenuRequested.connect(
            self._on_context_menu
        )
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(
            self._on_item_double_clicked
        )
        self.list_widget.itemActivated.connect(
            self._on_item_double_clicked
        )
        body_layout.addWidget(self.list_widget, 1)

        self.empty_label = QtWidgets.QLabel("")
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(
            f"QLabel {{ color: {theme['text_secondary']};"
            " font-size: 11px; padding: 2px 0; }"
        )
        body_layout.addWidget(self.empty_label)

        self.hint_label = QtWidgets.QLabel(
            self._tr(
                "Double-click to add; right-click or Ctrl+click to show "
                "images using it."
            )
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(
            f"QLabel {{ color: {theme['text_secondary']};"
            " font-size: 11px; padding: 0; }"
        )
        body_layout.addWidget(self.hint_label)
        layout.addWidget(self.body, 1)

    # -- public API ----------------------------------------------------
    def set_entries(self, entries, current_tags):
        self._entries = list(entries)
        self._current = set(current_tags or ())
        self._rebuild()

    def set_editing_enabled(self, enabled):
        self._editing_enabled = bool(enabled)
        self.search_edit.setEnabled(self._editing_enabled)
        self.list_widget.setEnabled(self._editing_enabled)

    def is_collapsed(self):
        return self._collapsed

    def set_collapsed(self, collapsed):
        self._collapsed = bool(collapsed)
        self.body.setVisible(not self._collapsed)
        self.collapse_button.setArrowType(
            QtCore.Qt.ArrowType.RightArrow
            if self._collapsed
            else QtCore.Qt.ArrowType.DownArrow
        )
        self.collapse_button.setToolTip(
            self._tr("Expand tag library")
            if self._collapsed
            else self._tr("Collapse tag library")
        )

    # -- internals -----------------------------------------------------
    def _toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def _missing_entries(self):
        return [
            (tag, count)
            for tag, count in self._entries
            if tag not in self._current
        ]

    def _matching_entries(self, missing):
        query = self.search_edit.text().strip().casefold()
        if not query:
            return missing
        return [
            (tag, count)
            for tag, count in missing
            if query in tag.casefold()
        ]

    def _rebuild(self):
        missing = self._missing_entries()
        matching = self._matching_entries(missing)
        metrics = self.list_widget.fontMetrics()
        longest = max(
            (metrics.horizontalAdvance(tag) for tag, _ in matching),
            default=0,
        )
        cell_width = max(96, min(200, longest + 28))
        self.list_widget.setGridSize(QtCore.QSize(cell_width, 28))
        self.list_widget.clear()
        for tag, count in matching:
            item = QtWidgets.QListWidgetItem(tag)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, tag)
            item.setSizeHint(QtCore.QSize(cell_width, 28))
            item.setToolTip(
                self._tr("%s (used by %d images)") % (tag, count)
                + "\n"
                + self._tr("Double-click to add.")
            )
            self.list_widget.addItem(item)

        self.count_label.setText(
            "(%d)" % len(missing) if missing else ""
        )
        self.list_widget.setVisible(bool(matching))
        self.hint_label.setVisible(bool(missing))
        if not missing:
            self.empty_label.setText(
                self._tr("No other tags in the current file list.")
            )
            self.empty_label.setVisible(True)
        elif not matching:
            self.empty_label.setText(self._tr("No matching tags."))
            self.empty_label.setVisible(True)
        else:
            self.empty_label.setVisible(False)

    def _on_item_clicked(self, item):
        if item is None or not self._editing_enabled:
            return
        if not self._is_search_gesture():
            # A single click only selects; adding requires a double-click so
            # an accidental click does not write a tag (and attribution).
            return
        tag = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not tag:
            return
        QtCore.QTimer.singleShot(
            0, lambda value=str(tag): self.tag_search_requested.emit(value)
        )

    def _on_item_double_clicked(self, item):
        if item is None or not self._editing_enabled:
            return
        tag = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not tag:
            return
        QtCore.QTimer.singleShot(
            0, lambda value=str(tag): self.tag_clicked.emit(value)
        )

    def _is_search_gesture(self):
        return bool(
            QtWidgets.QApplication.keyboardModifiers()
            & QtCore.Qt.KeyboardModifier.ControlModifier
        )

    def _on_context_menu(self, position):
        item = self.list_widget.itemAt(position)
        if item is None:
            return
        tag = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not tag:
            return
        menu = QtWidgets.QMenu(self.list_widget)
        action = menu.addAction(self._tr("Show images with this tag"))
        action.triggered.connect(
            lambda _checked=False, value=str(tag): (
                self.tag_search_requested.emit(value)
            )
        )
        menu.exec(self.list_widget.viewport().mapToGlobal(position))
