"""Toolbar and panel-button policy of the labeling window.

The toolbar is built from the action registry, but *which* entries are shown,
their short labels, the show/hide preferences and the geometry refresh after a
toggle all belong to this policy object. It used to live on
``LabelingWidget``; keeping it here makes the rules readable and testable
without building the whole window.

The host (``LabelingWidget``) owns the widgets (``tools``, toggle buttons,
``actions``) and the QSettings-backed preferences; this class is stateless and
only reads/mutates the host.
"""

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .. import utils
from ..pointcloud.icons import get_icon
from ..utils.theme import get_theme

# pylupdate6 only records `tr()` calls inside class bodies.  These
# modules also translate text through `host.tr`/`self.tr` in free
# functions and helpers, where the receiver is the LabelingWidget; the
# constant tells `scripts/translation_scan.py` which context to use
# (see docs/dev/CODE_STRUCTURE_REPORT.md).
TR_CONTEXT = "LabelingWidget"

class ToolbarPolicy:
    """Short labels, visibility preferences and geometry of the tool bar."""

    def __init__(self, host):
        self.host = host

    def _configure_toggle_button(self, button, style, tooltip):
        button.setIconSize(QtCore.QSize(18, 18))
        button.setFixedSize(26, 26)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setStyleSheet(style)

    def _panel_toggle_icon(self, kind, visible):
        """Draw a panel icon: ``sidebar`` or ``bottom`` (horizontal).

        The filled part indicates that the panel is visible, so the two title
        bar toggles read the same way as the right-panel toggle did before.
        """
        theme = get_theme()
        color = QtGui.QColor(
            theme["text"] if visible else theme["text_secondary"]
        )
        size = 18
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(color)
        pen.setWidthF(1.4)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        frame = QtCore.QRectF(2.5, 4.5, 13.0, 11.0)
        painter.drawRoundedRect(frame, 2.0, 2.0)
        if visible:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color)
            if kind == "sidebar":
                fill = QtCore.QRectF(11.0, 5.5, 3.0, 9.0)
            else:
                fill = QtCore.QRectF(3.5, 11.5, 11.0, 3.0)
            painter.drawRoundedRect(fill, 1.0, 1.0)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _sync_panel_toggle_icons(self):
        if hasattr(self.host, "sidebar_toggle_button"):
            self.host.sidebar_toggle_button.setIcon(
                self.host._panel_toggle_icon(
                    "sidebar", not self.host.right_sidebar.isHidden()
                )
            )

    def toggle_right_sidebar(self):
        show = self.host.right_sidebar.isHidden()
        if not show:
            self.host._right_sidebar_width = self.host.right_sidebar.width()
        self.host.right_sidebar.setVisible(show)
        if show:
            available_width = (
                self.host.sidebar_splitter.width()
                - self.host.sidebar_splitter.handleWidth()
            )
            self.host.sidebar_splitter.setSizes(
                [
                    max(1, available_width - self.host._right_sidebar_width),
                    self.host._right_sidebar_width,
                ]
            )
        self.host._sync_panel_toggle_icons()

    @staticmethod
    def _short_tool_label(text):
        """Return a compact label (at most four characters for CJK text)."""
        text = text.replace("&", "").strip()
        if not text:
            return text
        if len(text) <= 4:
            return text
        if all(ord(char) < 128 for char in text):
            return text.split()[0]
        return text[:4]

    def _apply_toolbar_short_labels(self, toolbar):
        for action in toolbar.actions():
            label = self.host._short_tool_label(action.text())
            if label:
                action.setIconText(label)
            button = toolbar.widgetForAction(action)
            if button is not None:
                if action.toolTip():
                    button.setToolTip(action.toolTip())
                # Fixed size keeps QToolBar from squeezing labels; the
                # overflow goes to the toolbar's extension button instead.
                if getattr(self.host, "_toolbar_show_labels", True):
                    hint = button.sizeHint()
                    button.setFixedSize(hint.width(), hint.height())
                else:
                    button.setFixedSize(26, 30)
        theme = get_theme()
        label_mode = getattr(self.host, "_toolbar_show_labels", True)
        for button, label, icon_name in (
            (self.host.settings_button, self.host.tr("Settings"), "settings"),
            (self.host.shortcuts_button, self.host.tr("Shortcuts"), "command"),
        ):
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon
                if label_mode
                else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            button.setText(
                self.host._short_tool_label(label) if label_mode else ""
            )
            button.setToolTip(label)
            button.setIcon(
                get_icon(icon_name, theme["text"], theme["primary"])
            )
            button.setIconSize(QtCore.QSize(18, 18))
            if label_mode:
                button.setFixedSize(56, 46)
            else:
                button.setFixedSize(26, 30)

    def toolbar_preferences(self):
        return (
            bool(getattr(self.host, "_toolbar_show_labels", True)),
            set(getattr(self.host, "_toolbar_hidden_keys", set())),
        )

    def refresh_toolbar_geometry(self):
        """Resize the toolbar to its natural size inside the scroll pane."""
        toolbar = getattr(self.host, "tools", None)
        if toolbar is None:
            return
        toolbar.adjustSize()
        toolbar.updateGeometry()
        parent = toolbar.parentWidget()
        while parent is not None:
            if isinstance(parent, QtWidgets.QScrollArea):
                parent.updateGeometry()
                break
            parent = parent.parentWidget()

    def toolbar_entries(self):
        entries = []
        for index, tool_action in enumerate(self.host.actions.tool):
            if tool_action is None:
                continue
            if not tool_action.text():
                continue
            entries.append(
                (str(index), tool_action.text(), tool_action.toolTip())
            )
        # Pinned utility buttons (Settings/Shortcuts) are QWidgetActions with
        # empty text, so they need their own keys to appear in the settings
        # list instead of being silently unreachable there.
        for key, title, _action in getattr(
            self.host, "_utility_toolbar_entries", ()
        ):
            entries.append((key, title, title))
        return entries

    def apply_toolbar_preferences(self, show_labels, hidden_keys):
        self.host._toolbar_show_labels = bool(show_labels)
        self.host._toolbar_hidden_keys = {str(key) for key in hidden_keys}
        self.host.settings.setValue(
            "toolbar/show_labels", self.host._toolbar_show_labels
        )
        self.host.settings.setValue(
            "toolbar/hidden_actions", sorted(self.host._toolbar_hidden_keys)
        )
        self.host.settings.sync()
        self.host.tools.set_label_mode(self.host._toolbar_show_labels)
        self.host.populate_mode_actions()
        self.host.refresh_toolbar_geometry()

    def populate_mode_actions(self):
        tool = self.host.actions.tool
        menu = self.host.actions.canvas_menu
        # The pinned Settings/Shortcuts buttons live at the end of
        # ``actions.tool`` as QWidgetActions; they are added below by their own
        # key so the settings page can hide them too.
        utility_entries = getattr(self.host, "_utility_toolbar_entries", ())
        utility_ids = {id(action) for _key, _title, action in utility_entries}
        hidden_keys = getattr(self.host, "_toolbar_hidden_keys", set())
        self.host.tools.clear()
        visible_tool = []
        for index, tool_action in enumerate(tool):
            if tool_action is None:
                continue
            if id(tool_action) in utility_ids:
                continue
            if str(index) not in hidden_keys:
                visible_tool.append(tool_action)
        utils.add_actions(self.host.tools, tuple(visible_tool))
        self.host._apply_toolbar_short_labels(self.host.tools)
        # Keep settings/shortcuts visible at the top of a vertical toolbar;
        # otherwise the overflow menu hides them on smaller windows.  They can
        # be hidden from the toolbar settings page like any other tool.
        for key, _title, action in reversed(utility_entries):
            if key in hidden_keys:
                continue
            actions = self.host.tools.actions()
            if actions:
                self.host.tools.insertAction(actions[0], action)
        self.host.refresh_toolbar_geometry()

        self.host.canvas.menus[0].clear()
        utils.add_actions(self.host.canvas.menus[0], menu)
        (
            self.host.canvas_label_filter_menu_0,
            self.host.canvas_gid_filter_menu_0,
        ) = self.host._append_filter_submenus(
            self.host.canvas.menus[0],
            prepend=True,
            after_filter_actions=(self.host.annotation_check_menu.menuAction(),),
        )
        self.host.menus.edit.clear()
        actions = (
            self.host.actions.create_mode,
            self.host.actions.create_brush_polygon_mode,
            self.host.actions.create_magic_wand_mode,
            self.host.actions.create_rectangle_mode,
            self.host.actions.create_cuboid_mode,
            self.host.actions.create_rotation_mode,
            self.host.actions.create_quadrilateral_mode,
            self.host.actions.create_circle_mode,
            self.host.actions.create_line_mode,
            self.host.actions.create_point_mode,
            self.host.actions.create_line_strip_mode,
            None,
            self.host.actions.edit_mode,
            self.host.actions.edit_brush_mode,
        )
        utils.add_actions(self.host.menus.edit, actions + self.host.actions.editMenu)
