"""Tag library shown in the "Image Attributes" tab (fork.34).

The widget renders the whole tag vocabulary of the current file list.
Adding a tag to the current image and persisting it is driven by
``LabelingWidget``.  Tags already present on the current image stay in the
list (marked) so the vocabulary is stable for search and the same widget
can be reused by the batch dialog (fork.58).
"""

from PyQt6 import QtCore, QtGui, QtWidgets

from ..utils.theme import get_theme


class TagLibraryWidget(QtWidgets.QWidget):
    tag_clicked = QtCore.pyqtSignal(str)
    tag_search_requested = QtCore.pyqtSignal(str)
    status_message = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        header.setContentsMargins(6, 4, 6, 2)
        header.setSpacing(4)
        self.title_label = QtWidgets.QLabel(self.tr("Tag Library"))
        self.title_label.setStyleSheet(
            f"QLabel {{ color: {theme['text_secondary']};"
            " font-size: 11px; font-weight: 600; }"
        )
        self.title_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.title_label.setToolTip(self.tr("Tag Library"))
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setStyleSheet(
            f"QLabel {{ color: {theme['text_secondary']}; font-size: 11px; }}"
        )
        self.count_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText(self.tr("Search tags…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedHeight(24)
        self.search_edit.setMinimumWidth(52)
        self.search_edit.setMaximumWidth(180)
        self.search_edit.setToolTip(self.tr("Search tags…"))
        self.search_edit.textChanged.connect(self._rebuild)
        self.collapse_button = QtWidgets.QToolButton()
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.setArrowType(QtCore.Qt.ArrowType.DownArrow)
        self.collapse_button.setToolTip(self.tr("Collapse tag library"))
        self.collapse_button.clicked.connect(self._toggle_collapsed)
        header.addWidget(self.title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)
        header.addWidget(self.search_edit)
        header.addWidget(self.collapse_button)
        layout.addLayout(header)

        self.body = QtWidgets.QWidget(self)
        body_layout = QtWidgets.QVBoxLayout(self.body)
        body_layout.setContentsMargins(6, 0, 6, 6)
        body_layout.setSpacing(4)

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
            self.tr(
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
    def sizeHint(self):
        # The search field belongs to the header, but must not raise the right
        # sidebar's minimum width back to a wide value.
        hint = super().sizeHint()
        return QtCore.QSize(160, hint.height())

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QtCore.QSize(0, hint.height())

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
            self.tr("Expand tag library")
            if self._collapsed
            else self.tr("Collapse tag library")
        )

    # -- internals -----------------------------------------------------
    def _toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def _matching_entries(self, entries):
        query = self.search_edit.text().strip().casefold()
        if not query:
            return entries
        return [
            (tag, count)
            for tag, count in entries
            if query in tag.casefold()
        ]

    def _rebuild(self):
        # fork.58: the library always shows the whole tag vocabulary.  Applied
        # tags are marked instead of removed, so the list stays stable for
        # searching and the same widget can be reused by the batch dialog.
        entries = list(self._entries)
        matching = self._matching_entries(entries)
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
            applied = tag in self._current
            item.setForeground(
                QtGui.QColor(self._theme["text_secondary"])
                if applied
                else self.palette().color(QtGui.QPalette.ColorRole.Text)
            )
            item.setToolTip(
                self.tr("%s (used by %d images)") % (tag, count)
                + "\n"
                + self.tr("Double-click to add.")
                + (
                    "\n" + self.tr("Already on this image.")
                    if applied
                    else ""
                )
            )
            self.list_widget.addItem(item)

        self.count_label.setText(
            "(%d)" % len(entries) if entries else ""
        )
        self.list_widget.setVisible(bool(matching))
        self.hint_label.setVisible(bool(entries))
        if not entries:
            self.empty_label.setText(
                self.tr("No tags in the current file list.")
            )
            self.empty_label.setVisible(True)
        elif not matching:
            self.empty_label.setText(self.tr("No matching tags."))
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
        if tag in self._current:
            self.status_message.emit(
                self.tr("This tag is already on the image.")
            )
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
        action = menu.addAction(self.tr("Show images with this tag"))
        action.triggered.connect(
            lambda _checked=False, value=str(tag): (
                self.tag_search_requested.emit(value)
            )
        )
        menu.exec(self.list_widget.viewport().mapToGlobal(position))
