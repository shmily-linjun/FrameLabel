import functools
import html
import json
import math
import os
import os.path as osp
import re
import shutil
import zlib
from typing import Optional
from uuid import uuid4

import cv2
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import QLabel, QLineEdit, QMessageBox

from anylabeling.services.auto_labeling.types import AutoLabelingMode
from anylabeling.services.auto_labeling import _THUMBNAIL_RENDER_MODELS
from anylabeling.services.identity import get_operator_service
from anylabeling.views.training import UltralyticsDialog

from ...app_info import __appname__
from . import utils
from .utils.qt import apply_application_font
from .utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_ok_btn_style,
)
from ...config import get_config, save_config
from .actions.builder import build_actions
from .actions.menus import build_menus
from .actions.toolbar import ToolbarPolicy
from .auto_labeling_handoff import AutoLabelingHandoff
from .constants import LABEL_OPACITY
from .file_list import FileListController
from .file_list.constants import FILE_COL_NAME
from .operator import (  # noqa: F401
    OPERATOR_MODE_ACTIONS,
    OPERATOR_REQUIRED_ACTIONS,
    OperatorGate,
)
from .label_file import LabelFile, LabelFileError
from .logger import logger
from .schema import CHECKED_FIELD, IMAGE_TAGS_FIELD
from .settings import SettingsDialog
from .settings.runtime_applier import SettingsRuntimeApplier
from .settings.schema import (
    SETTINGS_SHORTCUT_SECTIONS,
    fields_for_page,
    load_template_config,
)
from .shape import Shape
from .utils.file_search import (
    escape_query_value,
    filter_image_files,
    parse_search_query,
)
from .utils.label_text import (
    format_label_list_text as _format_label_list_text,
    measure_text_width as _measure_text_width,
)
from .utils.qt import new_icon_path
from .utils.theme import get_theme
from .pointcloud.icons import get_icon
from .widgets.attributes_panel import AttributesPanel
from .widgets.description_editor import DescriptionEditor
from .widgets.relation_dialog import (
    RelationDialog,
    RelationManagerDialog,
    show_relation_message,
)
from .widgets.workspace import (
    build_canvas_view,
    build_instruction_bar,
    build_operator_bar,
    build_workspace,
    restore_session_state,
)
from .widgets import (
    AboutDialog,
    BrightnessContrastProcessor,
    ChatbotDialog,
    ClassifierDialog,
    VQADialog,
    FileDialogPreview,
    PPOCRDialog,
    VideoClassifierDialog,
    ShapeModifyDialog,
    GroupIDFilterComboBox,
    LabelDialog,
    LabelFilterComboBox,
    LabelListWidget,
    LabelListWidgetItem,
    DigitShortcutDialog,
    LabelModifyDialog,
    GroupIDModifyDialog,
    OverviewDialog,
    Popup,
    SearchBar,
    ToolBar,
    UniqueLabelQListWidget,
    ZoomWidget,
    NavigatorDialog,
)

LABEL_COLORMAP = utils.label_colormap()
CHECKED_FIELD_PATTERN = re.compile(r'"checked"\s*:\s*(true|false|"failed")')


def _set_label_list_item_lock(item, locked):
    item.set_locked(locked)


def _find_next_label_loop_shape(shapes, start_index, canvas_shapes):
    canvas_shape_ids = {id(shape) for shape in canvas_shapes}
    for index in range(start_index, len(shapes)):
        shape = shapes[index]
        if id(shape) in canvas_shape_ids:
            return index, shape
    return len(shapes), None


class LabelingWidget(LabelDialog):
    """The main widget for labeling images"""

    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = 0, 1, 2
    next_files_changed = QtCore.pyqtSignal(list)

    def __init__(  # noqa: C901
        self,
        parent=None,
        config=None,
        filename=None,
        output=None,
        output_file=None,
        output_dir=None,
        operator_service=None,
    ):
        self.parent = parent
        if output is not None:
            logger.warning(
                "argument output is deprecated, use output_file instead"
            )
            if output_file is None:
                output_file = output

        self.filename = None
        self.image_path = None
        self.image_data = None
        self.label_file = None
        self.other_data = {}
        self.classes_file = None
        self.attributes = {}
        self.attribute_widget_types = {}
        self.current_category = None
        self.selected_polygon_stack = []
        self.supported_shape = Shape.get_supported_shape()
        self.label_info = {}
        self.image_flags = []
        self.cache_auto_label = None
        self.cache_auto_label_group_id = None

        # see configs/anylabeling_config.yaml for valid configuration
        if config is None:
            config = get_config()
        self._config = config
        self.label_flags = self._config["label_flags"]
        self.label_loop_count = -1
        self.label_loop_shapes = None
        self.label_loop_popup = None
        self.select_loop_count = -1
        self.digit_to_label = None
        self.drawing_digit_shortcuts = self._config.get("digit_shortcuts", {})
        self._runtime_shape_color_shift = int(
            self._config.get("shift_auto_shape_color", 0)
        )
        self._settings_controller = None
        self._settings_dialog = None
        self.training_dialog = None
        self.pointcloud_window = None
        self._settings_runtime_applier = SettingsRuntimeApplier(self)
        self._auto_switch_signal_connected = False

        # Operator identity: who may edit and who is credited for the labels.
        self.operator_service = (
            operator_service
            if operator_service is not None
            else get_operator_service()
        )
        self.operator_gate = OperatorGate(self, self.operator_service)
        self.auto_labeling_handoff = AutoLabelingHandoff(self)

        # set default shape colors
        Shape.line_color = QtGui.QColor(*self._config["shape"]["line_color"])
        Shape.fill_color = QtGui.QColor(*self._config["shape"]["fill_color"])
        Shape.select_line_color = QtGui.QColor(
            *self._config["shape"]["select_line_color"]
        )
        Shape.select_fill_color = QtGui.QColor(
            *self._config["shape"]["select_fill_color"]
        )
        Shape.vertex_fill_color = QtGui.QColor(
            *self._config["shape"]["vertex_fill_color"]
        )
        Shape.hvertex_fill_color = QtGui.QColor(
            *self._config["shape"]["hvertex_fill_color"]
        )

        # Set point size from config file
        Shape.point_size = self._config["shape"]["point_size"]
        # Set line width from config file
        Shape.line_width = self._config["shape"]["line_width"]

        super(LabelDialog, self).__init__()

        # Whether we need to save or not.
        self.dirty = False

        self._no_selection_slot = False
        self._session_shape_locks = {}
        self._copied_shapes = None
        self._copied_group_id = None
        self._batch_edit_warning_shown = False
        self._batch_processing_active = False

        self.brightness_contrast_processor = BrightnessContrastProcessor()

        # Main widgets and related state.
        self.label_dialog = LabelDialog(
            parent=self,
            labels=self._config["labels"],
            sort_labels=self._config["sort_labels"],
            show_text_field=self._config["show_label_text_field"],
            completion=self._config["label_completion"],
            fit_to_content=self._config["fit_to_content"],
            flags=self.label_flags,
        )

        self.label_list = LabelListWidget()
        self.label_list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.last_open_dir = None

        self.flag_widget = QtWidgets.QListWidget()
        if config["flags"]:
            self.image_flags = config["flags"]
            self.load_flags({k: False for k in self.image_flags})
        self.flag_widget.itemChanged.connect(self.set_dirty)

        self.label_filter_combobox = LabelFilterComboBox(self)
        self.gid_filter_combobox = GroupIDFilterComboBox(self)
        self.label_filter_combobox.hide()
        self.gid_filter_combobox.hide()
        self.select_toggle_action = None

        self.label_list.item_selection_changed.connect(
            self.label_selection_changed
        )
        self.label_list.item_double_clicked.connect(self.edit_label)
        self.label_list.item_changed.connect(self.label_item_changed)

        self.unique_label_list = UniqueLabelQListWidget()
        self.load_labels(self._config["labels"])

        self.shape_text_label = QLabel("Object Text")
        self.shape_text_edit = DescriptionEditor()

        self.file_search = SearchBar()
        self.file_search.setPlaceholderText(self.tr("Search files..."))
        self.file_search.setToolTip(
            self.tr(
                "Supported search syntax:\n"
                "- Text: plain text matches the file name\n"
                "- Index: #N (e.g., #1, #10)\n"
                "- Regex: <pattern> (e.g., <\\.png$>)\n"
                "- Attributes: label::xxx, split::train, shape::1, type::xxx,\n"
                "  gid::0, difficult::1, score::[0,0.5], description::1,\n"
                "  checked::passed, review::pending\n"
                "- split values: none/train/val/test (also 未划分/训练/验证/测试)\n"
                "- Several values: label::cat|dog (or), label::cat,dog (and)\n"
                "- Combine conditions: label::cat,split::train\n"
                "- Negate: !label::cat\n"
                "- Group with parentheses: (label::cat|dog),split::train\n"
                "- ',' binds tighter than '|'; press Enter to search."
            )
        )
        self.file_search.returnPressed.connect(self.file_search_changed)
        self.file_search.returnPressed.connect(self.file_search.setFocus)
        self.settings_button = QtWidgets.QToolButton(self)
        self.settings_button.setFixedSize(26, 26)
        self.settings_button.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor
        )
        self.settings_button.setToolTip(self.tr("Settings"))
        self.settings_button.setIcon(utils.new_icon("settings", "svg"))
        self.settings_button.setIconSize(QtCore.QSize(18, 18))
        self.settings_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings_button.setAccessibleName(self.settings_button.toolTip())
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.files = FileListController(self)
        self.file_list_widget = self.files.table
        self._hidden_tabs = set()
        self._file_column_actions = {}
        self._tab_visibility_actions = {}

        self.zoom_widget = ZoomWidget()
        self._zoom_animation = QtCore.QVariantAnimation(self)
        self._zoom_animation.setDuration(90)
        self._zoom_animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._zoom_animation.valueChanged.connect(self._animate_zoom)

        self.navigator_dialog = NavigatorDialog(self)
        self.navigator_dialog.navigator.navigation_requested.connect(
            self.on_navigator_request
        )
        self.navigator_dialog.closeEvent = self._navigator_close_event
        self.navigator_dialog.zoom_changed[int].connect(
            lambda zoom: self.on_navigator_zoom_changed(zoom, None)
        )
        self.navigator_dialog.zoom_changed[int, QtCore.QPoint].connect(
            self.on_navigator_zoom_changed
        )
        self.navigator_dialog.viewport_update_requested.connect(
            self.on_navigator_viewport_update_requested
        )
        self.async_exif_scanner = utils.AsyncExifScanner(self)
        self.async_exif_scanner.exif_detected.connect(self.on_exif_detected)

        self.setAcceptDrops(True)

        scroll_area = build_canvas_view(self)

        # Actions
        action = functools.partial(utils.new_action, self)
        self.actions = build_actions(self)

        self.menus = build_menus(self)

        # Custom context menu for the canvas widget:
        utils.add_actions(self.canvas.menus[0], self.actions.canvas_menu)
        utils.add_actions(
            self.canvas.menus[1],
            (
                action("&Copy here", self.copy_shape),
                action("&Move here", self.move_shape),
            ),
        )
        (
            self.canvas_label_filter_menu_0,
            self.canvas_gid_filter_menu_0,
        ) = self._append_filter_submenus(
            self.canvas.menus[0],
            prepend=True,
            after_filter_actions=(self.annotation_check_menu.menuAction(),),
        )
        self.canvas.menus[0].aboutToShow.connect(self.refresh_filter_menus)
        self.canvas.menus[0].aboutToShow.connect(
            self.refresh_shape_lock_action
        )

        self.tools = self.toolbar("Tools")
        instruction_layout = build_instruction_bar(self)
        build_operator_bar(self)
        build_workspace(self, scroll_area, instruction_layout)
        restore_session_state(
            self, filename, output_file, output_dir, config
        )

    def show_shortcuts(self):
        from .pointcloud.controls import ShortcutsDialog

        shortcuts = self._config["shortcuts"]
        groups = []
        for section in SETTINGS_SHORTCUT_SECTIONS:
            entries = []
            for field in fields_for_page("Shortcuts", section):
                value = shortcuts.get(field.key.removeprefix("shortcuts."))
                values = value if isinstance(value, (list, tuple)) else [value]
                keys = [
                    QtGui.QKeySequence(key).toString(
                        QtGui.QKeySequence.SequenceFormat.NativeText
                    )
                    for key in values
                    if key
                ]
                if keys:
                    entries.append(
                        (
                            QtCore.QCoreApplication.translate(
                                "SettingsDialog", field.label
                            ),
                            keys,
                        )
                    )
            if section == "Shape":
                entries.extend(
                    (
                        getattr(
                            self.actions, f"digit_shortcut_{digit}"
                        ).text(),
                        [str(digit)],
                    )
                    for digit in range(10)
                )
            groups.append(
                (
                    QtCore.QCoreApplication.translate(
                        "SettingsDialog", section
                    ),
                    entries,
                )
            )
        ShortcutsDialog(groups, self).exec()

    def _configure_toggle_button(self, button, style, tooltip):
        return ToolbarPolicy(self)._configure_toggle_button(button, style, tooltip)

    def _panel_toggle_icon(self, kind, visible):
        return ToolbarPolicy(self)._panel_toggle_icon(kind, visible)

    def _sync_panel_toggle_icons(self):
        return ToolbarPolicy(self)._sync_panel_toggle_icons()

    def toggle_right_sidebar(self):
        return ToolbarPolicy(self).toggle_right_sidebar()

    def restore_navigator_state(self) -> None:
        try:
            navigator_visible: bool = self.settings.value(
                "navigator/visible", False, type=bool
            )

            if navigator_visible:
                self.navigator_dialog.show()

                if hasattr(self, "image") and not self.image.isNull():
                    self.navigator_dialog.set_image(
                        QtGui.QPixmap.fromImage(self.image)
                    )
                    self.update_navigator_viewport()
                else:
                    self._should_restore_navigator = True

                # Restore geometry information
                geometry = self.settings.value("navigator/geometry")
                if geometry:
                    self.navigator_dialog.restoreGeometry(geometry)
                else:
                    # Fallback: restore position and size separately
                    saved_size = self.settings.value("navigator/size")
                    saved_position = self.settings.value("navigator/position")

                    if saved_size:
                        self.navigator_dialog.resize(saved_size)
                    if saved_position:
                        self.navigator_dialog.move(saved_position)

                if hasattr(self, "actions") and hasattr(
                    self.actions, "show_navigator"
                ):
                    self.actions.show_navigator.setChecked(True)

        except Exception as e:
            print(f"Error restoring navigator state: {e}")

    def _navigator_close_event(self, event: QtGui.QCloseEvent) -> None:
        if hasattr(self, "actions") and hasattr(
            self.actions, "show_navigator"
        ):
            self.actions.show_navigator.setChecked(False)

        self.settings.setValue("navigator/visible", False)

        NavigatorDialog.closeEvent(self.navigator_dialog, event)

    def set_language(self, language):
        if self._config["language"] == language:
            return
        self._config["language"] = language

        # Show dialog to restart application
        msg_box = QMessageBox()
        msg_box.setText(
            self.tr("Please restart the application to apply changes.")
        )
        msg_box.exec()
        self.parent.parent.close()

    def _on_theme_changed(self, mode: str) -> None:
        """Handle Theme menu selection (System / Light / Dark)."""
        prev_mode = self._config.get("theme", "auto")
        if prev_mode == mode:
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("Theme"))
        dialog.setFixedWidth(360)
        dialog.setWindowFlags(
            dialog.windowFlags()
            & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        dialog.setStyleSheet(get_dialog_style())

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        label = QLabel(
            self.tr(
                "The new theme will take effect after restarting the application. Apply this setting now?"
            )
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(8)
        cancel_btn = QtWidgets.QPushButton(self.tr("Cancel"))
        cancel_btn.setFixedWidth(100)
        cancel_btn.setStyleSheet(get_cancel_btn_style())
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn = QtWidgets.QPushButton(self.tr("OK"))
        ok_btn.setFixedWidth(100)
        ok_btn.setStyleSheet(get_ok_btn_style())
        ok_btn.clicked.connect(dialog.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._config["theme"] = mode
            save_config(self._config)
            popup = Popup(
                text=self.tr(
                    "Please restart the application to apply changes."
                ),
                parent=self,
            )
            popup.show_popup(self, position="center")
        else:
            # Revert the checkmark to the previously active mode
            prev_act = self._theme_actions.get(prev_mode)
            if prev_act:
                prev_act.setChecked(True)

    def get_labeling_instruction(self):
        text_mode = self.tr("Mode:")
        text_shortcuts = self.tr("Shortcuts:")
        text_settings = self.tr("Settings")
        text_previous = self.tr("Previous")
        text_next = self.tr("Next")
        text_rectangle = self.tr("Rectangle")
        text_polygon = self.tr("Polygon")
        text_rotation = self.tr("Rotation")
        text_quadrilateral = self.tr("Quadrilateral")
        shortcuts = self._config.get("shortcuts", {})
        return (
            f"<b>{text_mode}</b> {self.canvas.get_mode()} | "
            f"<b>{text_shortcuts}</b>"
            f" {text_previous}({self._format_instruction_shortcut(shortcuts.get('open_prev'))}),"
            f" {text_next}({self._format_instruction_shortcut(shortcuts.get('open_next'))}),"
            f" {text_rectangle}({self._format_instruction_shortcut(shortcuts.get('create_rectangle'))}),"
            f" {text_polygon}({self._format_instruction_shortcut(shortcuts.get('create_polygon'))}),"
            f" {text_rotation}({self._format_instruction_shortcut(shortcuts.get('create_rotation'))}),"
            f" {text_quadrilateral}({self._format_instruction_shortcut(shortcuts.get('create_quadrilateral'))}),"
            f" {text_settings}({self._format_instruction_shortcut(shortcuts.get('open_settings'))})"
        )

    def _should_show_space_pan_tip(self):
        if not self.canvas.drawing() or self.canvas.current is None:
            return False
        return any(
            scroll_bar.maximum() > 0
            for scroll_bar in self.scroll_bars.values()
        )

    def _space_pan_tip_message(self):
        return self.tr(
            "Tip: Hold Alt and drag with the left mouse button, or drag with the middle mouse button, to pan the canvas while drawing."
        )

    def update_space_pan_tip(self):
        message = self._space_pan_tip_message()
        status_bar = self.statusBar()
        if self._should_show_space_pan_tip():
            status_bar.showMessage(message)
        elif status_bar.currentMessage() == message:
            status_bar.clearMessage()

    def update_labeling_instruction(self):
        if not hasattr(self, "label_instruction"):
            return
        self.label_instruction.setText(self.get_labeling_instruction())
        self.update_space_pan_tip()

    def _format_instruction_shortcut(self, value):
        text = self._settings_runtime_applier.shortcut_value_to_text(
            value
        ).strip()
        if not text:
            return "<b>-</b>"
        sequences = [
            chunk.strip() for chunk in text.split(",") if chunk.strip()
        ]
        if not sequences:
            return "<b>-</b>"
        formatted = []
        for sequence in sequences:
            keys = [
                part.strip() for part in sequence.split("+") if part.strip()
            ]
            if not keys:
                continue
            formatted.append(
                "+".join(f"<b>{html.escape(key)}</b>" for key in keys)
            )
        if not formatted:
            return "<b>-</b>"
        return ", ".join(formatted)

    @pyqtSlot()
    def on_auto_segmentation_requested(self):
        self.canvas.set_auto_labeling(True)
        self.update_labeling_instruction()

    @pyqtSlot()
    def on_auto_segmentation_disabled(self):
        self.canvas.set_auto_labeling(False)
        self.update_labeling_instruction()

    @pyqtSlot(list)
    def on_exif_detected(self, exif_files):
        if utils.ExifProcessingDialog.show_detection_dialog(
            self, len(exif_files)
        ):
            logger.info("Start processing EXIF orientation")
            utils.ExifProcessingDialog.process_exif_files_with_progress(
                self, exif_files
            )

    @pyqtSlot(list)
    def on_auto_decode_requested(self, marks):
        """Handle auto decode request"""
        self.auto_labeling_widget.model_manager.set_auto_labeling_marks(marks)
        self.auto_labeling_widget.run_prediction()

    def menu(self, title, actions=None):
        menu = self.parent.parent.menuBar().addMenu(title)
        if actions:
            utils.add_actions(menu, actions)
        return menu

    def central_widget(self):
        return self._central_widget

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title, parent=self)
        toolbar.setObjectName(f"{title}ToolBar")
        toolbar.setOrientation(Qt.Orientation.Horizontal)
        toolbar.set_label_mode(getattr(self, "_toolbar_show_labels", True))
        toolbar.setIconSize(QtCore.QSize(18, 18))
        if actions:
            utils.add_actions(toolbar, actions)
        return toolbar

    @staticmethod
    def _short_tool_label(text):
        return ToolbarPolicy._short_tool_label(text)

    def _apply_toolbar_short_labels(self, toolbar):
        return ToolbarPolicy(self)._apply_toolbar_short_labels(toolbar)

    def statusBar(self):
        return self.parent.parent.statusBar()

    def no_shape(self):
        return len(self.label_list) == 0

    def toolbar_preferences(self):
        return ToolbarPolicy(self).toolbar_preferences()

    def refresh_toolbar_geometry(self):
        return ToolbarPolicy(self).refresh_toolbar_geometry()

    def toolbar_entries(self):
        return ToolbarPolicy(self).toolbar_entries()

    def apply_toolbar_preferences(self, show_labels, hidden_keys):
        return ToolbarPolicy(self).apply_toolbar_preferences(show_labels, hidden_keys)

    def populate_mode_actions(self):
        return ToolbarPolicy(self).populate_mode_actions()

    def set_dirty(self):
        self.actions.save.setIcon(utils.new_icon("save"))
        # Even if we autosave the file, we keep the ability to undo
        self.actions.undo.setEnabled(self.canvas.is_shape_restorable)

        if self._config["auto_save"]:
            label_file = osp.splitext(self.image_path)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.output_dir + "/" + label_file_without_path
            if not self.save_labels(label_file):
                # The save was refused (no operator yet): keep the content
                # marked as unsaved so it is not silently lost.
                self.dirty = True
                self.actions.save.setEnabled(True)
                self.update_progress_title()
                return
            if (
                hasattr(self, "navigator_dialog")
                and self.navigator_dialog.isVisible()
            ):
                self.update_navigator_shapes()
            return
        self.dirty = True
        self.actions.save.setEnabled(True)
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()
        self.update_progress_title()

    def _on_image_tags_changed(self, tags):
        if not self.image_path:
            return
        self.other_data[IMAGE_TAGS_FIELD] = list(tags)
        self.set_dirty()

    # -- operator identity ---------------------------------------------------
    # The browse-mode policy and the attribution baseline live in
    # ``labeling/operator/gate.py``; these thin wrappers keep the widget the
    # entry point for its own code and for the batch auto-labeling helper.
    def _operator_edit_allowed(self):
        return self.operator_gate.logged_in()

    def _on_operator_session_changed(self, session=None):
        self.operator_gate.on_session_changed(session)

    def _apply_operator_gate(self):
        self.operator_gate.apply()

    def open_operator_login(self):
        return self.operator_gate.open_login()

    def logout_operator(self):
        self.operator_gate.logout()

    def _ensure_operator(self):
        return self.operator_gate.ensure_operator()

    def _ensure_operator_for_edit(self):
        return self.operator_gate.ensure_for_edit()

    def _prepare_attribution(self, shapes, flags):
        return self.operator_gate.prepare_attribution(shapes, flags)

    def _content_signature_now(self):
        return self.operator_gate.content_signature_now()

    def _refresh_attribution_display(self):
        self.operator_gate.refresh_display()

    def toggle_image_tags_visibility(self, checked):
        self._image_tags_visibility = (
            "explicit_visible" if checked else "explicit_hidden"
        )
        self.image_tags_widget.setVisible(checked)

    def _auto_show_image_tags(self):
        if self._image_tags_visibility != "auto":
            return
        with QtCore.QSignalBlocker(self.actions.show_image_tags):
            self.actions.show_image_tags.setChecked(True)
        self.image_tags_widget.show()

    def _get_rgb_by_image_tag(self, label):
        for shape in self.canvas.shapes:
            if shape.label == label:
                return shape.line_color.getRgb()[:3]
        label_colors = self._config.get("label_colors") or {}
        if label in label_colors:
            return tuple(label_colors[label])
        label_id = zlib.crc32(label.encode("utf-8"))
        hue = label_id % 360
        saturation = 110 + ((label_id >> 9) % 66)
        value = 225 + ((label_id >> 16) % 26)
        return QtGui.QColor.fromHsv(hue, saturation, value).getRgb()[:3]

    def _document_status_text(self):
        """Cursor position and current filename for the status bar."""
        if self.filename is None:
            return ""
        position = getattr(self, "_cursor_position", None)
        if position is None:
            coords = "-,-"
        else:
            coords = f"{position[0]},{position[1]}"
        return f"[{coords}|{osp.abspath(str(self.filename))}]"

    def _refresh_document_status(self):
        updater = getattr(self.parent.parent, "update_document_status", None)
        if updater is not None:
            updater(self._document_status_text())

    def _on_canvas_mouse_moved(self, x, y):
        self._cursor_position = (
            None if x < 0 or y < 0 else (int(round(x)), int(round(y)))
        )
        self._refresh_document_status()

    def _window_title(self):
        if self.filename is None:
            return __appname__
        return f"{__appname__} - {self._document_status_text()}"

    def update_progress_title(self):
        self.parent.parent.setWindowTitle(self._window_title())
        self._refresh_document_status()

    def set_clean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.save.setIcon(
            utils.new_icon("save-check" if self.label_file else "save")
        )
        self.actions.union_selection.setEnabled(False)
        self.actions.create_mode.setEnabled(True)
        self.actions.create_brush_polygon_mode.setEnabled(True)
        self.actions.create_magic_wand_mode.setEnabled(True)
        self.actions.create_rectangle_mode.setEnabled(True)
        self.actions.create_cuboid_mode.setEnabled(True)
        self.actions.create_rotation_mode.setEnabled(True)
        self.actions.create_quadrilateral_mode.setEnabled(True)
        self.actions.create_circle_mode.setEnabled(True)
        self.actions.create_line_mode.setEnabled(True)
        self.actions.create_point_mode.setEnabled(True)
        self.actions.create_line_strip_mode.setEnabled(True)
        self.actions.digit_shortcut_0.setEnabled(True)
        self.actions.digit_shortcut_1.setEnabled(True)
        self.actions.digit_shortcut_2.setEnabled(True)
        self.actions.digit_shortcut_3.setEnabled(True)
        self.actions.digit_shortcut_4.setEnabled(True)
        self.actions.digit_shortcut_5.setEnabled(True)
        self.actions.digit_shortcut_6.setEnabled(True)
        self.actions.digit_shortcut_7.setEnabled(True)
        self.actions.digit_shortcut_8.setEnabled(True)
        self.actions.digit_shortcut_9.setEnabled(True)

        self.update_progress_title()

        if self.has_label_file():
            self.actions.delete_file.setEnabled(True)
        else:
            self.actions.delete_file.setEnabled(False)
        self._apply_operator_gate()

    def get_image_progress_info(self):
        if self.filename and self.filename in self.fn_to_index:
            current_index = self.fn_to_index[str(self.filename)]
            total_count = self.file_list_widget.count()
            return current_index + 1, total_count
        return 1, 1

    def toggle_actions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for action in self.actions.zoom_actions:
            action.setEnabled(value)
        for action in self.actions.on_load_active:
            action.setEnabled(value)
        if not value:
            self.actions.edit_brush_mode.setEnabled(False)

        if value and self.file_list_widget.count() > 0:
            self.actions.shape_manager.setEnabled(True)
        else:
            self.actions.shape_manager.setEnabled(False)
        self.update_browse_actions()
        self._apply_operator_gate()

    def update_browse_actions(self):
        index = self.fn_to_index.get(str(self.filename), -1)
        count = self.file_list_widget.count()
        valid = 0 <= index < count
        step = self._config["image_jump_step"]
        self.actions.jump_next_images.setEnabled(
            valid and index + step < count
        )
        self.actions.jump_prev_images.setEnabled(valid and index >= step)
        for action, text, tip in (
            (
                self.actions.jump_next_images,
                self.tr("Forward %s Images"),
                self.tr("Move forward by %s images"),
            ),
            (
                self.actions.jump_prev_images,
                self.tr("Back %s Images"),
                self.tr("Move back by %s images"),
            ),
        ):
            action.setText(text % step)
            action.setIconText((text % step).replace(" ", "\n"))
            action.setToolTip(tip % step)
            action.setStatusTip(tip % step)

    def jump_images(self, offset):
        if not self.may_continue():
            return
        index = self.fn_to_index.get(str(self.filename), -1)
        target = index + offset
        if index >= 0 and 0 <= target < self.file_list_widget.count():
            self.load_file(self.file_list_widget.item(target).text())

    def queue_event(self, function):
        QtCore.QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    @staticmethod
    def _shape_lock_key(shape):
        return (
            shape.label,
            shape.shape_type,
            shape.group_id,
            tuple((point.x(), point.y()) for point in shape.points),
        )

    def _remember_shape_locks(self):
        if not self.image_path:
            return
        states = {}
        for shape in self.canvas.shapes:
            states.setdefault(self._shape_lock_key(shape), []).append(
                shape.locked
            )
        self._session_shape_locks[osp.abspath(self.image_path)] = states

    def _restore_shape_locks(self):
        states = self._session_shape_locks.get(
            osp.abspath(self.image_path), {}
        )
        offsets = {}
        for shape in self.canvas.shapes:
            key = self._shape_lock_key(shape)
            index = offsets.get(key, 0)
            offsets[key] = index + 1
            if key in states and index < len(states[key]):
                shape.locked = states[key][index]
                item = self.label_list.find_item_by_shape(shape)
                if item is not None:
                    item.set_locked(shape.locked)
        self.refresh_panel_controls()

    def reset_state(self):
        self._remember_shape_locks()
        self._zoom_animation.stop()
        if self.filename is not None:
            for orientation, bar in self.scroll_bars.items():
                self.scroll_values[orientation][self.filename] = bar.value()
        self._reset_label_loop()
        self.select_loop_count = -1
        self.label_list.clear()
        self.filename = None
        self.update_browse_actions()
        self.image_path = None
        self.image_data = None
        self.label_file = None
        self.other_data = {}
        if hasattr(self, "image_tags_widget"):
            self.image_tags_widget.set_interactions_enabled(False)
            self.image_tags_widget.set_tags([])
        self.canvas.reset_state()
        self.canvas.relations = []
        self.actions.create_relation.setEnabled(False)
        self.brightness_contrast_processor.clear_image()
        if hasattr(self, "canvas_adjustment"):
            self.canvas_adjustment.hide()
        self.compare_view_manager.reset()
        self.label_filter_combobox.text_box.clear()
        self.gid_filter_combobox.gid_box.clear()
        self._update_select_toggle_button_tooltip()

    def toggle_select_all(self):
        if self.select_toggle_action is None:
            return
        if self._has_active_shape_filter():
            self._update_select_toggle_button_tooltip()
            return
        if not self.canvas.shapes:
            self._update_select_toggle_button_tooltip()
            return

        all_visible = self._are_all_shapes_visible()
        self._set_all_objects_visibility(not all_visible)
        self._update_select_toggle_button_tooltip()

    def _has_active_shape_filter(self):
        current_label = self.label_filter_combobox.text_box.currentText()
        current_gid = self.gid_filter_combobox.gid_box.currentText()
        return bool(current_label) or current_gid not in ["", "-1"]

    def _update_select_toggle_button_tooltip(self):
        self.refresh_panel_controls()
        if self.select_toggle_action is None:
            return
        if self._has_active_shape_filter():
            tooltip = self.tr(
                "Toggle shapes visibility is unavailable while a label or group filter is active"
            )
            self.select_toggle_action.setEnabled(False)
            self.select_toggle_action.setToolTip(tooltip)
            self.select_toggle_action.setStatusTip(tooltip)
            return
        self.select_toggle_action.setEnabled(bool(self.canvas.shapes))
        if self._are_all_shapes_visible():
            tooltip = self.tr("Hide all shapes")
            icon = utils.new_icon("eye")
        else:
            tooltip = self.tr("Show all shapes")
            icon = utils.new_icon("eye-off")
        self.select_toggle_action.setIcon(icon)
        self.select_toggle_action.setToolTip(tooltip)
        self.select_toggle_action.setStatusTip(tooltip)

    def _are_all_shapes_visible(self):
        if len(self.label_list) == 0:
            return True
        for item in self.label_list:
            if item.checkState() != Qt.CheckState.Checked:
                return False
            shape = item.shape()
            if shape is not None and not shape.visible:
                return False
        return True

    def _set_all_objects_visibility(self, visible):
        """Set all Objects panel checkboxes and shape visibility to visible (True/False)."""
        for item in self.label_list:
            label = item.shape().label
            if label in self.label_info:
                self.label_info[label]["visible"] = visible
        self._sync_label_list_visibility(lambda _item: visible)

    def reset_attribute(self, text, shape):
        return AttributesPanel(self).reset_attribute(text, shape)

    def current_item(self):
        items = self.label_list.selected_items()
        if items:
            return items[0]
        return None

    def add_recent_file(self, filename):
        if filename in self.recent_files:
            self.recent_files.remove(filename)
        elif len(self.recent_files) >= self.max_recent:
            self.recent_files.pop()
        self.recent_files.insert(0, filename)

    # Callbacks
    def undo_shape_edit(self):
        # In brush-edit mode, undo reverts the last brush stroke instead of
        # the global shape history.
        if getattr(self.canvas, "is_brush_mode", False):
            self.canvas.brush_undo()
            self.actions.undo.setEnabled(self.canvas.brush_can_undo())
            return
        self.canvas.restore_shape()
        self.label_list.clear()
        self.load_shapes(self.canvas.shapes, update_last_label=False)
        self.actions.undo.setEnabled(self.canvas.is_shape_restorable)
        self.set_dirty()

    def get_label_file_list(self):
        label_file_list = []
        if not self.image_list and self.filename:
            dir_path, filename = osp.split(self.filename)
            label_file = osp.join(
                dir_path, osp.splitext(filename)[0] + ".json"
            )
            if osp.exists(label_file):
                label_file_list = [label_file]
        elif self.image_list and not self.output_dir and self.filename:
            file_list = os.listdir(osp.dirname(self.filename))
            for file_name in file_list:
                if not file_name.endswith(".json"):
                    continue
                label_file_list.append(
                    osp.join(osp.dirname(self.filename), file_name)
                )
        if self.output_dir:
            for file_name in os.listdir(self.output_dir):
                if not file_name.endswith(".json"):
                    continue
                label_file_list.append(osp.join(self.output_dir, file_name))
        return label_file_list

    def copy_shape_coordinates(self):
        item = self.current_item()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return

        points = shape.points
        if shape.shape_type == "rectangle":
            if len(points) >= 2:
                x1, y1 = points[0].x(), points[0].y()
                x2, y2 = points[2].x(), points[2].y()
                coordinates = [x1, y1, x2, y2]
                coordinates = list(map(int, coordinates))
            else:
                return
        else:
            coordinates = []
            for point in points:
                coordinates.extend([point.x(), point.y()])

        coordinates_str = str(coordinates)
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(coordinates_str)

    def union_selection(self):
        if any(shape.locked for shape in self.canvas.selected_shapes):
            return
        rectangle_shapes, polygon_shapes = [], []
        for shape in self.canvas.selected_shapes:
            points = shape.points
            if shape.shape_type == "rectangle":
                xmin, ymin = (points[0].x(), points[0].y())
                xmax, ymax = (points[2].x(), points[2].y())
                rectangle_shapes.append([xmin, ymin, xmax, ymax])
            else:
                polygon_shapes.append([(p.x(), p.y()) for p in points])

        union_shape = shape.copy()
        union_shape.other_data.pop("shape_id", None)
        union_shape._relation_identity = uuid4().hex

        if len(rectangle_shapes) > 0:
            min_x = min([bbox[0] for bbox in rectangle_shapes])
            min_y = min([bbox[1] for bbox in rectangle_shapes])
            max_x = max([bbox[2] for bbox in rectangle_shapes])
            max_y = max([bbox[3] for bbox in rectangle_shapes])

            union_shape.points[0].setX(min_x)
            union_shape.points[0].setY(min_y)
            union_shape.points[1].setX(max_x)
            union_shape.points[1].setY(min_y)
            union_shape.points[2].setX(max_x)
            union_shape.points[2].setY(max_y)
            union_shape.points[3].setX(min_x)
            union_shape.points[3].setY(max_y)
        else:
            # Create a blank mask
            min_x = min([min(p[0] for p in poly) for poly in polygon_shapes])
            min_y = min([min(p[1] for p in poly) for poly in polygon_shapes])
            max_x = max([max(p[0] for p in poly) for poly in polygon_shapes])
            max_y = max([max(p[1] for p in poly) for poly in polygon_shapes])

            width = int(max_x - min_x + 10)
            height = int(max_y - min_y + 10)
            mask = np.zeros((height, width), dtype=np.uint8)

            # Draw all polygons on the mask
            for polygon in polygon_shapes:
                contour = np.array(polygon, dtype=np.int32)
                shifted_contour = contour - np.array(
                    [min_x - 5, min_y - 5], dtype=np.int32
                )
                shifted_contour = shifted_contour.reshape((-1, 1, 2))
                cv2.fillPoly(mask, [shifted_contour], 255)

            # Find contours of the merged shape
            merged_contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if merged_contours:
                largest_contour = max(merged_contours, key=cv2.contourArea)
                epsilon = 0.001 * cv2.arcLength(largest_contour, True)
                approx_contour = cv2.approxPolyDP(
                    largest_contour, epsilon, True
                )
                approx_contour = approx_contour.reshape(-1, 2) + np.array(
                    [min_x - 5, min_y - 5], dtype=np.int32
                )
                union_shape.points = [
                    QtCore.QPointF(float(x), float(y))
                    for x, y in approx_contour
                ]

        # Append merged shape and remove selected shapes
        self.add_label(union_shape)
        self.remove_labels(self.canvas.delete_selected())
        self.set_dirty()

        # Update UI state
        if self.no_shape():
            for action in self.actions.on_shapes_present:
                action.setEnabled(False)

    # Trainer
    def start_training(self, mode):
        if mode != "ultralytics":
            return

        try:
            if self.training_dialog is None:
                self.training_dialog = UltralyticsDialog(self)
                self.training_dialog.destroyed.connect(
                    self.on_training_dialog_destroyed
                )
            self.training_dialog.showNormal()
            self.training_dialog.raise_()
            self.training_dialog.activateWindow()
        except Exception as e:
            self.error_message(
                "Start Error", f"Failed to start training dialog: {str(e)}"
            )

    def on_training_dialog_destroyed(self, _dialog=None):
        self.training_dialog = None

    # Tools
    def overview(self):
        if self.filename:
            OverviewDialog(parent=self)

    def digit_shortcut_manager(self):
        digit_shortcut_dialog = DigitShortcutDialog(parent=self)
        result = digit_shortcut_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self._config["digit_shortcuts"] = self.drawing_digit_shortcuts
            save_config(self._config)

    def label_manager(self):
        modify_label_dialog = LabelModifyDialog(
            parent=self, opacity=LABEL_OPACITY
        )
        result = modify_label_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if self.filename and modify_label_dialog.annotations_changed:
                self.load_file(self.filename)

    def gid_manager(self):
        modify_gid_dialog = GroupIDModifyDialog(parent=self)
        result = modify_gid_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self.load_file(self.filename)

    def shape_manager(self):
        modify_shape_dialog = ShapeModifyDialog(parent=self)
        result = modify_shape_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if modify_shape_dialog.need_reload and self.filename:
                self.load_file(self.filename)

    def open_chatbot(self):
        dialog = ChatbotDialog(self)
        _ = dialog.exec()

    def open_vqa(self):
        if not self.image_list:
            self.error_message(
                self.tr("No images loaded"),
                self.tr(
                    "Please load an image folder before opening the VQA dialog."
                ),
            )
            return

        if not hasattr(self, "vqa_window") or self.vqa_window is None:
            self.vqa_window = VQADialog(self)
            self.vqa_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.vqa_window.isVisible():
            self.vqa_window.raise_()
            self.vqa_window.activateWindow()
        else:
            self.vqa_window.show()

    def open_pointcloud(self):
        if self.pointcloud_window is None:
            try:
                from .widgets.pointcloud_dialog import PointCloudDialog

                window = PointCloudDialog(self)
            except (ImportError, OSError, RuntimeError) as error:
                logger.error(f"Failed to open point cloud workspace: {error}")
                self.error_message(
                    self.tr("Point cloud unavailable"),
                    self.tr("Unable to open the point cloud workspace: %s")
                    % html.escape(str(error)),
                )
                return
            window.destroyed.connect(self.on_pointcloud_window_destroyed)
            self.pointcloud_window = window
        if self.pointcloud_window.isMinimized():
            self.pointcloud_window.showNormal()
        else:
            self.pointcloud_window.show()
        self.pointcloud_window.raise_()
        self.pointcloud_window.activateWindow()

    def on_pointcloud_window_destroyed(self, _window=None):
        self.pointcloud_window = None

    def open_paddleocr(self):
        if not hasattr(self, "ppocr_window") or self.ppocr_window is None:
            self.ppocr_window = PPOCRDialog(self)
            self.ppocr_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.ppocr_window.isVisible():
            self.ppocr_window.raise_()
            self.ppocr_window.activateWindow()
        else:
            self.ppocr_window.show()

    def open_video_classifier(self):
        if VideoClassifierDialog is None:
            popup = Popup(
                text=self.tr(
                    "Video Classifier requires QtMultimedia, which this "
                    "Qt build does not provide."
                ),
                parent=self,
            )
            popup.show_popup(self, position="center")
            return
        if (
            not hasattr(self, "video_classifier_window")
            or self.video_classifier_window is None
        ):
            self.video_classifier_window = VideoClassifierDialog(self)
            self.video_classifier_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, True
            )
            self.video_classifier_window.destroyed.connect(
                lambda _obj=None: setattr(
                    self, "video_classifier_window", None
                )
            )
        if self.video_classifier_window.isVisible():
            self.video_classifier_window.raise_()
            self.video_classifier_window.activateWindow()
        else:
            self.video_classifier_window.showMaximized()

    def open_image_classifier(self):
        if not self.image_list:
            self.error_message(
                self.tr("No images loaded"),
                self.tr(
                    "Please load an image folder before opening the Classification dialog."
                ),
            )
            return

        if (
            not hasattr(self, "image_classifier_window")
            or self.image_classifier_window is None
        ):
            self.image_classifier_window = ClassifierDialog(self)
            self.image_classifier_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.image_classifier_window.isVisible():
            self.image_classifier_window.raise_()
            self.image_classifier_window.activateWindow()
        else:
            self.image_classifier_window.show()

    def open_classifier(self):
        return self.open_image_classifier()

    # Help
    def documentation(self):
        locale = "/zh-Hans" if self._config["language"] == "zh_CN" else ""
        url = (
            f"https://xanylabeling.com{locale}/docs/"
            "x-anylabeling/get_started"
        )
        utils.general.open_url(url)

    def sponsor(self):
        utils.general.open_url("https://xanylabeling.com/sponsor")

    def about(self):
        about_dialog = AboutDialog(self)
        _ = about_dialog.exec()

    def _reset_label_loop(self):
        self.label_loop_count = -1
        self.label_loop_shapes = None
        if self.label_loop_popup is not None:
            self.label_loop_popup.close()

    def _show_label_loop_popup(self, text):
        if self.label_loop_popup is None:
            self.label_loop_popup = Popup(
                text,
                parent=self,
                msec=1800,
                icon=new_icon_path("copy-green", "svg"),
            )
            self.label_loop_popup.label.setTextFormat(Qt.TextFormat.PlainText)
            self.label_loop_popup.setAttribute(
                Qt.WidgetAttribute.WA_ShowWithoutActivating
            )
            self.label_loop_popup.setWindowFlag(
                Qt.WindowType.WindowDoesNotAcceptFocus, True
            )
            self.label_loop_popup.setWindowFlag(
                Qt.WindowType.WindowTransparentForInput, True
            )
        else:
            self.label_loop_popup.set_text(text)
        self.label_loop_popup.show_popup(
            self.central_widget().viewport(), top_offset=24
        )

    def loop_thru_labels(self):
        is_new_loop = self.label_loop_shapes is None
        if is_new_loop:
            self.label_loop_shapes = list(self.canvas.shapes)

        self.label_loop_count, shape = _find_next_label_loop_shape(
            self.label_loop_shapes,
            self.label_loop_count + 1,
            self.canvas.shapes,
        )
        if shape is None:
            message = (
                self.tr("No objects to review")
                if is_new_loop
                else self.tr("Review complete")
            )
            self._reset_label_loop()
            if not is_new_loop:
                self.canvas.deselect_shape()
                self.set_fit_window()
            self._show_label_loop_popup(message)
            return

        width = self.central_widget().width() - 2.0
        height = self.central_widget().height() - 2.0

        im_width = self.canvas.pixmap.width()
        im_height = self.canvas.pixmap.height()

        zoom_scale = 4

        xs = []
        ys = []
        # loop through all points on this label
        for point in shape.points:
            xs.append(point.x())
            ys.append(point.y())

        # Set minimum label width to 30px this should handle point
        # lables and very tiny labels gracefully
        label_width = max(int(max(xs) - min(xs)), 30)
        x = (max(xs) + min(xs)) / 2
        y = (max(ys) + min(ys)) / 2

        zoom = int(100 * width / (zoom_scale * label_width))
        # Don't go past the max zoom which is 1000
        zoom = min(1000, zoom)

        self.set_zoom(zoom)
        self.canvas.pan_offset = QtCore.QPointF()
        self.pan_values[self.filename] = QtCore.QPointF()

        x_range = self.scroll_bars[Qt.Orientation.Horizontal].maximum()
        x_step = self.scroll_bars[Qt.Orientation.Horizontal].pageStep()

        y_range = self.scroll_bars[Qt.Orientation.Vertical].maximum()
        # QT docs says Document length = maximum() - minimum() + pageStep().
        # so there's a weird pageStep thing we gotta add
        y_step = self.scroll_bars[Qt.Orientation.Vertical].pageStep()
        screen_width = width / (zoom / 100)
        # add half a screen to this
        x_scroll = int((x - screen_width / 2) / im_width * (x_range + x_step))
        x_scroll = min(max(0, x_scroll), x_range)

        screen_height = height / (zoom / 100)

        y_scroll = int(
            (y - screen_height / 2) / (im_height) * (y_range + y_step)
        )
        y_scroll = min(max(0, y_scroll), y_range)

        self.set_scroll(Qt.Orientation.Horizontal, x_scroll)
        self.set_scroll(Qt.Orientation.Vertical, y_scroll)
        self.canvas.prev_h_shape = self.canvas.h_shape = shape
        self.canvas.select_shapes([shape])

        progress = self.tr("Reviewing {current} / {total}").format(
            current=self.label_loop_count + 1,
            total=len(self.label_loop_shapes),
        )
        font_metrics = self.fontMetrics()
        label_width = min(
            240,
            max(
                0,
                self.central_widget().viewport().width()
                - _measure_text_width(font_metrics, progress)
                - 56,
            ),
        )
        label = font_metrics.elidedText(
            str(shape.label or ""), Qt.TextElideMode.ElideRight, label_width
        )
        if label:
            progress = f"{progress} - {label}"
        self._show_label_loop_popup(progress)

    def loop_select_labels(self):
        self.select_loop_count += 1
        if len(self.label_list) == 0 or self.select_loop_count >= len(
            self.label_list
        ):
            self.select_loop_count = -1
            self.canvas.deselect_shape()
            return

        item = self.label_list[self.select_loop_count]
        shape = item.shape()
        self.canvas.select_shapes([shape])

    def copy_to_clipboard(self, text):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(
            self,
            self.tr("Copied"),
            self.tr("The information has been copied to the clipboard."),
        )

    # General
    def toggle_drawing_sensitive(self, drawing=True):
        """Toggle drawing sensitive.

        In the middle of drawing, toggling between modes should be disabled.
        """
        self.actions.edit_mode.setEnabled(not drawing)
        self.actions.undo_last_point.setEnabled(drawing)
        self.actions.undo.setEnabled(not drawing)
        self.actions.delete.setEnabled(not drawing)
        self.actions.union_selection.setEnabled(not drawing)
        self.update_labeling_instruction()

    def create_digit_mode(self, digit_num):
        if self.drawing_digit_shortcuts is None:
            return

        data = self.drawing_digit_shortcuts.get(digit_num, None)
        if not data:
            return

        label = data.get("label", "object")
        create_mode = data.get("mode", None)

        if create_mode not in Shape.get_supported_shape():
            return

        self.digit_to_label = label
        self.toggle_draw_mode(edit=False, create_mode=create_mode)

    def toggle_draw_mode(
        self,
        edit=True,
        create_mode="rectangle",
        disable_auto_labeling=True,
        preserve_brush_mode=False,
    ):
        if not edit and not self._ensure_operator_for_edit():
            # Every "create ..." entry point (toolbar, menu, digit shortcut,
            # auto-labeling hand-off) funnels through here, so a cancelled
            # login stops before the canvas switches to a drawing mode.
            return
        if not preserve_brush_mode:
            if getattr(self.canvas, "is_brush_mode", False):
                self.canvas.cancel_brush_mode()
            elif self.actions.edit_brush_mode.isChecked():
                self.actions.edit_brush_mode.setChecked(False)
        self.canvas.set_magic_wand_mode(False)
        # Disable auto labeling if needed
        if (
            disable_auto_labeling
            and self.auto_labeling_widget.auto_labeling_mode
            != AutoLabelingMode.NONE
        ):
            self.clear_auto_labeling_marks()
            self.auto_labeling_widget.set_auto_labeling_mode(None)

        if not edit:
            self.set_text_editing(False)

        self.canvas.set_editing(edit)
        self.canvas.create_mode = create_mode
        self.canvas._brush_drawing = False
        if edit:
            self.actions.create_mode.setEnabled(True)
            self.actions.create_brush_polygon_mode.setEnabled(True)
            self.actions.create_magic_wand_mode.setEnabled(True)
            self.actions.create_rectangle_mode.setEnabled(True)
            self.actions.create_cuboid_mode.setEnabled(True)
            self.actions.create_rotation_mode.setEnabled(True)
            self.actions.create_quadrilateral_mode.setEnabled(True)
            self.actions.create_circle_mode.setEnabled(True)
            self.actions.create_line_mode.setEnabled(True)
            self.actions.create_point_mode.setEnabled(True)
            self.actions.create_line_strip_mode.setEnabled(True)
            self.actions.digit_shortcut_0.setEnabled(True)
            self.actions.digit_shortcut_1.setEnabled(True)
            self.actions.digit_shortcut_2.setEnabled(True)
            self.actions.digit_shortcut_3.setEnabled(True)
            self.actions.digit_shortcut_4.setEnabled(True)
            self.actions.digit_shortcut_5.setEnabled(True)
            self.actions.digit_shortcut_6.setEnabled(True)
            self.actions.digit_shortcut_7.setEnabled(True)
            self.actions.digit_shortcut_8.setEnabled(True)
            self.actions.digit_shortcut_9.setEnabled(True)
        else:
            self.hide_attributes_panel()
            self.actions.union_selection.setEnabled(False)
            create_actions = {
                "polygon": self.actions.create_mode,
                "rectangle": self.actions.create_rectangle_mode,
                "cuboid": self.actions.create_cuboid_mode,
                "line": self.actions.create_line_mode,
                "point": self.actions.create_point_mode,
                "circle": self.actions.create_circle_mode,
                "linestrip": self.actions.create_line_strip_mode,
                "rotation": self.actions.create_rotation_mode,
                "quadrilateral": self.actions.create_quadrilateral_mode,
            }
            if create_mode not in create_actions:
                raise ValueError(f"Unsupported create_mode: {create_mode}")
            self.actions.create_mode.setEnabled(True)
            self.actions.create_brush_polygon_mode.setEnabled(True)
            self.actions.create_magic_wand_mode.setEnabled(True)
            self.actions.create_rectangle_mode.setEnabled(True)
            self.actions.create_cuboid_mode.setEnabled(True)
            self.actions.create_rotation_mode.setEnabled(True)
            self.actions.create_quadrilateral_mode.setEnabled(True)
            self.actions.create_circle_mode.setEnabled(True)
            self.actions.create_line_mode.setEnabled(True)
            self.actions.create_point_mode.setEnabled(True)
            self.actions.create_line_strip_mode.setEnabled(True)
            create_actions[create_mode].setEnabled(False)
        self.actions.edit_mode.setEnabled(not edit)
        self.update_labeling_instruction()
        self._apply_operator_gate()

    def toggle_brush_polygon_mode(self):
        """Toggle brush drawing mode for polygons."""
        if (
            self.canvas.drawing()
            and self.canvas.create_mode == "polygon"
            and self.canvas._brush_drawing
        ):
            self.toggle_draw_mode(True)
            return
        self.toggle_draw_mode(False, create_mode="polygon")
        self.canvas._brush_drawing = True
        self.actions.create_mode.setEnabled(True)
        self.actions.create_brush_polygon_mode.setEnabled(False)

    def toggle_magic_wand_mode(self):
        """Toggle thresholded flood selection for polygon creation."""
        if self.canvas.drawing() and self.canvas.is_magic_wand_mode:
            self.toggle_draw_mode(True)
            return
        self.toggle_draw_mode(False, create_mode="polygon")
        self.canvas.set_magic_wand_mode(True)
        self.actions.create_mode.setEnabled(True)
        self.actions.create_magic_wand_mode.setEnabled(False)

    def set_edit_mode(self):
        self.clear_auto_labeling_marks()
        self.auto_labeling_widget.set_auto_labeling_mode(None)

        self.toggle_draw_mode(True)
        self.set_text_editing(True)
        self.update_labeling_instruction()

    def _enter_edit_mode_from_toolbar(self):
        """Toolbar/menu entry for "Edit Object": ask for a login first."""
        if not self._ensure_operator_for_edit():
            return
        self.set_edit_mode()

    def toggle_brush_mode(self, checked: bool) -> None:
        """Enable or disable brush editing for a polygon.

        Enabling requires exactly one selected polygon and switches the
        canvas to edit mode before brush editing starts.

        Args:
            checked: ``True`` when the toolbar toggle is switched on.
        """
        if checked:
            if not self._ensure_operator_for_edit():
                self.actions.edit_brush_mode.setChecked(False)
                return
            selected_shapes = self.canvas.selected_shapes
            if (
                len(selected_shapes) != 1
                or selected_shapes[0].shape_type != "polygon"
                or selected_shapes[0].locked
            ):
                self.actions.edit_brush_mode.setChecked(False)
                return
            if self.canvas.current is not None:
                self.canvas.current = None
                self.canvas.set_hiding(False)
                self.canvas.drawing_polygon.emit(False)
                self.canvas.update()
            self.toggle_draw_mode(True, preserve_brush_mode=True)
            self.set_text_editing(True)
            self.canvas.set_brush_mode(True)
            self.update_labeling_instruction()
            return

        if getattr(self.canvas, "is_brush_mode", False):
            self.canvas.set_brush_mode(False)
        self.update_labeling_instruction()

    def on_brush_mode_changed(self, enabled: bool) -> None:
        """Synchronize brush action and lock the active shape selection."""
        self.actions.edit_brush_mode.setChecked(enabled)
        self.label_list.setEnabled(not enabled)

    def update_file_menu(self):
        current = self.filename

        def exists(filename):
            return osp.exists(str(filename))

        menu = self.menus.recent_files
        menu.clear()
        files = [f for f in self.recent_files if f != current and exists(f)]
        if self.last_open_dir and osp.isdir(self.last_open_dir):
            dir_name = (
                QtCore.QFileInfo(self.last_open_dir).fileName()
                or self.last_open_dir
            )
            action = QtGui.QAction(
                utils.new_icon("open"),
                self.tr("Open Last Dir: %s") % dir_name,
                self,
            )
            action.triggered.connect(
                functools.partial(self.load_recent_dir, self.last_open_dir)
            )
            menu.addAction(action)
            if files:
                menu.addSeparator()
        for i, f in enumerate(files):
            icon = utils.new_icon("file")
            action = QtGui.QAction(
                icon, "&%d %s" % (i + 1, QtCore.QFileInfo(f).fileName()), self
            )
            action.triggered.connect(functools.partial(self.load_recent, f))
            menu.addAction(action)

    def refresh_shape_lock_action(self):
        self.refresh_panel_controls()
        items = self.label_list.selected_items()
        shapes = [item.shape() for item in items if item.shape() is not None]
        action = self.actions.toggle_shape_lock
        action.setEnabled(bool(shapes))
        with QtCore.QSignalBlocker(action):
            action.setChecked(bool(shapes) and all(s.locked for s in shapes))

    def toggle_label_items_lock(self, items):
        shapes = [item.shape() for item in items if item.shape() is not None]
        if not shapes:
            return
        for shape in shapes:
            shape.locked = not shape.locked
        self._update_shapes_lock(shapes)

    def refresh_panel_controls(self):
        if not hasattr(self, "shapes_visibility_button"):
            return
        theme = get_theme()
        items = [
            self.unique_label_list.item(row)
            for row in range(self.unique_label_list.count())
        ]
        labels = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        for button, visible in (
            (
                self.labels_visibility_button,
                any(
                    self.label_info.get(label, {}).get("visible", True)
                    for label in labels
                ),
            ),
            (
                self.shapes_visibility_button,
                any(s.visible for s in self.canvas.shapes),
            ),
        ):
            button.setIcon(
                get_icon(
                    "eye" if visible else "eye-off",
                    theme["text"],
                    theme["primary"],
                )
            )
        self.labels_lock_button.setChecked(
            any(
                self.unique_label_list.lock_states.get(label, False)
                for label in labels
            )
        )
        self.shapes_lock_button.setChecked(
            any(shape.locked for shape in self.canvas.shapes)
        )

        for button in (self.labels_lock_button, self.shapes_lock_button):
            button.setIcon(
                get_icon(
                    "lock" if button.isChecked() else "unlock",
                    theme["text"],
                    theme["primary"],
                )
            )

    def toggle_all_labels_visibility(self):
        labels = [
            self.unique_label_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.unique_label_list.count())
        ]
        visible = not any(
            self.label_info.get(label, {}).get("visible", True)
            for label in labels
        )
        for label in labels:
            if label not in self.label_info:
                self.label_info[label] = dict(
                    delete=False,
                    value=None,
                    color=list(self._get_rgb_by_label(label)),
                    opacity=LABEL_OPACITY,
                    visible=visible,
                )
            else:
                self.label_info[label]["visible"] = visible
        self._refresh_shape_filters()

    def toggle_all_shapes_visibility(self):
        self._set_all_objects_visibility(
            not any(s.visible for s in self.canvas.shapes)
        )

    def toggle_all_labels_lock(self):
        items = [
            self.unique_label_list.item(row)
            for row in range(self.unique_label_list.count())
        ]
        states = self.unique_label_list.lock_states
        locked = not any(
            states.get(item.data(Qt.ItemDataRole.UserRole), False)
            for item in items
        )
        self.toggle_unique_label_items_lock(items, locked=locked)

    def toggle_all_shapes_lock(self):
        shapes = self.canvas.shapes
        if not shapes:
            return
        locked = not any(shape.locked for shape in shapes)
        labels = {shape.label for shape in shapes}
        for label in labels:
            self.unique_label_list.lock_states.pop(label, None)
            for item in self.unique_label_list.find_items_by_label(label):
                self.unique_label_list.set_item_locked(item, False)
        self._set_shapes_locked(shapes, locked)

    def toggle_unique_label_items_lock(self, items, locked=None):
        states = self.unique_label_list.lock_states
        labels = set()
        for item in items:
            label = item.data(Qt.ItemDataRole.UserRole)
            states[label] = (
                not states.get(label, False) if locked is None else locked
            )
            labels.add(label)
            self.unique_label_list.set_item_locked(item, states[label])
        for states_by_shape in self._session_shape_locks.values():
            for key in list(states_by_shape):
                if key[0] in labels:
                    del states_by_shape[key]
        shapes = [s for s in self.canvas.shapes if s.label in labels]
        for shape in shapes:
            shape.locked = states[shape.label]
        if shapes:
            self._update_shapes_lock(shapes)
        self.refresh_panel_controls()

    def toggle_selected_shapes_lock(self, locked):
        items = self.label_list.selected_items()
        shapes = [item.shape() for item in items if item.shape() is not None]
        if not shapes:
            shapes = list(self.canvas.selected_shapes)
        if not shapes:
            return
        self._set_shapes_locked(shapes, locked)

    def _set_shapes_locked(self, shapes, locked):
        for shape in shapes:
            shape.locked = locked
        self._update_shapes_lock(shapes)

    def _update_shapes_lock(self, shapes):
        for shape in shapes:
            item = self.label_list.find_item_by_shape(shape)
            if item is not None:
                _set_label_list_item_lock(item, shape.locked)
        self.canvas.store_shapes()
        self.canvas.update()
        if self.canvas.editing():
            self.shape_selection_changed(self.canvas.selected_shapes)
        else:
            self.refresh_shape_lock_action()

    # ------------------------------------------------------------------
    # File table helpers
    #
    # The table widget, its columns, sorting, thumbnails and the per-file
    # context menu live in ``file_list/``.  The methods below stay on the
    # widget because callers and tests use the widget as the entry point.
    # ------------------------------------------------------------------
    @property
    def fn_to_index(self):
        return self.files.fn_to_index

    def _file_path_at(self, row):
        return self.files.path_at(row)

    def _file_item_by_path(self, path):
        return self.files.item_by_path(path)

    def sort_file_list_by_column(self, column):
        self.files.sort_by_column(column)

    def set_file_column_visible(self, column, visible):
        self.files.set_column_visible(column, visible)

    def set_file_thumbnails_visible(self, visible, persist=True):
        self.files.set_thumbnails_visible(visible, persist=persist)

    def set_file_split(self, row, split):
        self.files.set_split(row, split)

    def remove_file_from_list(self, row):
        self.files.remove_row(row)

    def _clear_file_list(self):
        self.files.clear()

    # ------------------------------------------------------------------
    # Right side tab helpers
    # ------------------------------------------------------------------
    def _tab_key_for_page(self, page):
        for key, _title, candidate in self._tab_pages:
            if candidate is page:
                return key
        return None

    def _rebuild_right_tabs(self):
        tabs = getattr(self, "right_tabs", None)
        if tabs is None:
            return
        pages = getattr(self, "_tab_pages", ())
        current_page = tabs.currentWidget()
        tabs.blockSignals(True)
        try:
            while tabs.count():
                tabs.removeTab(0)
            for key, title, page in pages:
                if key in self._hidden_tabs:
                    continue
                page.setParent(tabs)
                tabs.addTab(page, title)
            if current_page is not None and tabs.indexOf(current_page) >= 0:
                tabs.setCurrentWidget(current_page)
        finally:
            tabs.blockSignals(False)

    def _apply_right_tabs_config(self):
        pages = getattr(self, "_tab_pages", ())
        valid_keys = {key for key, _title, _page in pages}
        section = self._config.get("right_tabs")
        hidden = section.get("hidden") if isinstance(section, dict) else None
        hidden_keys = []
        if isinstance(hidden, (list, tuple)):
            hidden_keys = [
                str(item) for item in hidden if str(item) in valid_keys
            ]
        elif isinstance(hidden, str):
            hidden_keys = [hidden] if hidden in valid_keys else []
        hidden_keys = [key for key in hidden_keys if key in valid_keys]
        if len(hidden_keys) >= len(valid_keys) and valid_keys:
            hidden_keys = sorted(valid_keys - {pages[0][0]})
        self._hidden_tabs = set(hidden_keys)
        self._rebuild_right_tabs()

    def set_right_tab_visible(self, key, visible):
        pages = getattr(self, "_tab_pages", ())
        valid_keys = {page_key for page_key, _title, _page in pages}
        if key not in valid_keys:
            return
        hidden = set(self._hidden_tabs)
        if visible:
            hidden.discard(key)
        else:
            if len(valid_keys) - len(hidden) <= 1:
                self.status(self.tr("At least one panel must stay visible"))
                return
            hidden.add(key)
        self._hidden_tabs = hidden
        self._rebuild_right_tabs()
        section = self._config.setdefault("right_tabs", {})
        if isinstance(section, dict):
            section["hidden"] = sorted(self._hidden_tabs)

    def show_right_tab(self, key):
        if key in self._hidden_tabs:
            self.set_right_tab_visible(key, True)
        pages = getattr(self, "_tab_pages", ())
        for page_key, _title, page in pages:
            if page_key != key:
                continue
            index = self.right_tabs.indexOf(page)
            if index >= 0:
                self.right_tabs.setCurrentIndex(index)
            return

    def pop_right_tabs_menu(self, point):
        if not hasattr(self, "right_tabs"):
            return
        menu = QtWidgets.QMenu(self.right_tabs)
        for key, title, _page in self._tab_pages:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(key not in self._hidden_tabs)
            action.setData(key)
        chosen = menu.exec(self.right_tabs.tabBar().mapToGlobal(point))
        if chosen is None:
            return
        self.set_right_tab_visible(chosen.data(), chosen.isChecked())

    def show_flags_page(self):
        self.show_right_tab("flags")

    def _on_right_tab_changed(self, _index):
        page = self.right_tabs.currentWidget()
        if page is getattr(self, "statistics_table", None):
            self._refresh_statistics()

    def _refresh_statistics(self):
        table = getattr(self, "statistics_table", None)
        if table is None:
            return
        try:
            table.refresh(self.image_list, self.output_dir)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to refresh statistics table", exc_info=True)

    def _refresh_statistics_if_visible(self):
        table = getattr(self, "statistics_table", None)
        if table is None or self.right_tabs.currentWidget() is not table:
            return
        self._refresh_statistics()

    def _on_statistics_filter_requested(self, statistics_filter):
        """Turn a statistics-table click into a search query."""
        parts = []
        if statistics_filter.objectless:
            parts.append("shape::0")
        elif statistics_filter.label:
            parts.append(
                "label::" + escape_query_value(statistics_filter.label)
            )
        if statistics_filter.split:
            parts.append("split::" + statistics_filter.split)
        if not parts:
            return
        self.file_search.setText(",".join(parts))
        self.file_search_changed()

    def copy_file_path(self, file_path):
        popup = Popup(
            self.tr("Copy Successful"),
            parent=self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, copy_msg=file_path, position="default")

    def _label_file_checked(self, label_file):
        if not QtCore.QFile.exists(label_file):
            return False
        try:
            buffer = ""
            with open(label_file, "r", encoding="utf-8") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    buffer = buffer[-32:] + chunk
                    match = CHECKED_FIELD_PATTERN.search(buffer)
                    if match:
                        return (
                            "failed"
                            if match.group(1) == '"failed"'
                            else match.group(1) == "true"
                        )
        except Exception:
            return False
        return False

    def _set_file_item_checked(self, item, checked, shape_count=None):
        if item is None:
            return
        if (
            item.data(Qt.ItemDataRole.UserRole) == checked
            and shape_count is None
        ):
            return
        item.setData(Qt.ItemDataRole.UserRole, checked)
        item.setToolTip(
            f"{item.text()}\n{self._annotation_checked_text(checked)}"
        )
        row = self.files.row_of(item.text())
        if row is not None:
            self.files.apply_row_state(row, checked, shape_count)

    def _file_item_annotation_checked(self, item):
        return item.data(Qt.ItemDataRole.UserRole) in (True, "failed")

    def _create_file_list_item(self, file, label_file=None):
        if label_file is None:
            label_file = self.files.label_file_for(file)
        return self.files.build_row_cells(file, label_file)[FILE_COL_NAME]

    def _current_file_item(self):
        if str(self.filename) not in self.fn_to_index:
            return None
        return self.file_list_widget.item(self.fn_to_index[str(self.filename)])

    def _annotation_checked(self):
        checked = self.other_data.get(CHECKED_FIELD, False)
        return "failed" if checked == "failed" else checked is True

    def _annotation_checked_text(self, checked=None):
        if checked is None:
            checked = self._annotation_checked()
        return {
            False: self.tr("Unchecked"),
            True: self.tr("Check Passed"),
            "failed": self.tr("Check Failed"),
        }[checked]

    def _update_annotation_checked_action(self):
        if not hasattr(self, "actions"):
            return
        checked = self._annotation_checked()
        for action, status in (
            (self.actions.clear_annotation_checked, False),
            (self.actions.toggle_annotation_checked, True),
            (self.actions.fail_annotation_checked, "failed"),
        ):
            action.setChecked(checked == status)

    def _update_file_row_after_save(self, shape_count):
        path = str(self.image_path)
        item = self.files.item_by_path(path)
        if item is None:
            return
        item.setCheckState(Qt.CheckState.Checked)
        self._set_file_item_checked(
            item, self._annotation_checked(), shape_count
        )

    def _update_current_file_checked_item(self):
        item = self._current_file_item()
        if item is not None:
            self._set_file_item_checked(
                item, self._annotation_checked(), len(self.canvas.shapes)
            )

    def _sync_annotation_checked_state(self):
        self.canvas_adjustment.set_status(self._annotation_checked())
        self._update_annotation_checked_action()
        self._update_current_file_checked_item()
        self.update_progress_title()

    def set_annotation_checked(self, checked):
        if self.filename is None or self.image.isNull():
            return
        self.other_data[CHECKED_FIELD] = (
            "failed" if checked == "failed" else bool(checked)
        )
        self._sync_annotation_checked_state()
        label_file = self.get_label_file()
        if self.save_labels(label_file):
            self.set_clean()

    def _append_filter_submenus(
        self, parent_menu, prepend=False, after_filter_actions=None
    ):
        label_menu = QtWidgets.QMenu(self.tr("Filter by Label"), parent_menu)
        gid_menu = QtWidgets.QMenu(self.tr("Filter by Group ID"), parent_menu)
        if prepend and parent_menu.actions():
            first_action = parent_menu.actions()[0]
            parent_menu.insertMenu(first_action, label_menu)
            parent_menu.insertMenu(first_action, gid_menu)
            parent_menu.insertSeparator(first_action)
            if after_filter_actions:
                for action in after_filter_actions:
                    parent_menu.insertAction(first_action, action)
                parent_menu.insertSeparator(first_action)
        else:
            parent_menu.addSeparator()
            parent_menu.addMenu(label_menu)
            parent_menu.addMenu(gid_menu)
            if after_filter_actions:
                parent_menu.addSeparator()
                utils.add_actions(parent_menu, after_filter_actions)
        return label_menu, gid_menu

    def _populate_label_filter_menu(self, menu):
        menu.clear()
        action_group = QtGui.QActionGroup(menu)
        action_group.setExclusive(True)
        current_label = self.label_filter_combobox.text_box.currentText()
        for label in self.label_filter_combobox.items:
            text = self.tr("All Labels") if label == "" else label
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(label == current_label)
            action.triggered.connect(
                functools.partial(self.set_label_filter_value, label)
            )
            action_group.addAction(action)

    def _populate_gid_filter_menu(self, menu):
        menu.clear()
        action_group = QtGui.QActionGroup(menu)
        action_group.setExclusive(True)
        current_gid = self.gid_filter_combobox.gid_box.currentText()
        for gid in self.gid_filter_combobox.items:
            text = self.tr("All Group IDs") if gid == "-1" else gid
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(gid == current_gid)
            action.triggered.connect(
                functools.partial(self.set_gid_filter_value, gid)
            )
            action_group.addAction(action)

    def refresh_filter_menus(self):
        self.update_combo_box(block_signal=True)
        self.update_gid_box(block_signal=True)

        menus = [
            (self.canvas_label_filter_menu_0, self.canvas_gid_filter_menu_0),
            (self.canvas_label_filter_menu_1, self.canvas_gid_filter_menu_1),
        ]
        for label_menu, gid_menu in menus:
            if label_menu is not None:
                self._populate_label_filter_menu(label_menu)
            if gid_menu is not None:
                self._populate_gid_filter_menu(gid_menu)

    def set_label_filter_value(
        self, label, _checked=False, block_signal=False
    ):
        index = self.label_filter_combobox.text_box.findText(str(label))
        if index < 0:
            index = self.label_filter_combobox.text_box.findText("")
        if index >= 0:
            blocker = None
            if block_signal:
                blocker = QtCore.QSignalBlocker(
                    self.label_filter_combobox.text_box
                )
            self.label_filter_combobox.text_box.setCurrentIndex(index)
            del blocker

    def set_gid_filter_value(self, gid, _checked=False, block_signal=False):
        index = self.gid_filter_combobox.gid_box.findText(str(gid))
        if index < 0:
            index = self.gid_filter_combobox.gid_box.findText("-1")
        if index >= 0:
            blocker = None
            if block_signal:
                blocker = QtCore.QSignalBlocker(
                    self.gid_filter_combobox.gid_box
                )
            self.gid_filter_combobox.gid_box.setCurrentIndex(index)
            del blocker

    def validate_label(self, label):
        # no validation
        if self._config["validate_label"] is None:
            return True

        for i in range(self.unique_label_list.count()):
            label_i = self.unique_label_list.item(i).data(
                Qt.ItemDataRole.UserRole
            )
            if self._config["validate_label"] in ["exact"]:
                if label_i == label:
                    return True
        return False

    def batch_edit_labels(self, shapes):
        if not self._batch_edit_warning_shown:
            reply = QtWidgets.QMessageBox.question(
                self,
                self.tr("Batch Edit"),
                self.tr(
                    "You are about to edit multiple shapes in batch mode. "
                    "This operation cannot be undone.\n\n"
                    "This warning will only be shown once. Do you want to continue?"
                ),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )

            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

            self._batch_edit_warning_shown = True

        first_shape = shapes[0]
        result = self.label_dialog.pop_up(
            text=first_shape.label,
            flags=first_shape.flags,
            group_id=first_shape.group_id,
            description=first_shape.description,
            difficult=first_shape.difficult,
            kie_linking=first_shape.kie_linking,
            review_status=first_shape.other_data.get(
                "review_status", "pending"
            ),
            move_mode="center",
        )

        if result[0] is None:
            return

        text, flags, group_id, description, difficult, kie_linking = result

        if not self.validate_label(text):
            self.error_message(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            return

        for shape in shapes:
            if self.attributes and text and text != shape.label:
                text = self.reset_attribute(text, shape)

            shape.label = text
            shape.flags = flags
            shape.group_id = group_id
            shape.description = description
            shape.difficult = difficult
            shape.kie_linking = kie_linking
            shape.other_data["review_status"] = (
                self.label_dialog.get_review_status()
            )

            self._update_shape_color(shape)

            item = self.label_list.find_item_by_shape(shape)
            if item is not None:
                if shape.group_id is None:
                    color = self._get_rgb_by_label(shape.label)
                    item.setText(
                        _format_label_list_text(shape.label, shape.group_id)
                    )
                    item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
                else:
                    item.setText(
                        _format_label_list_text(shape.label, shape.group_id)
                    )

        self.label_dialog.add_label_history(text)

        if not self.unique_label_list.find_items_by_label(text):
            unique_label_item = self.unique_label_list.create_item_from_label(
                text
            )
            self.unique_label_list.addItem(unique_label_item)
            rgb = self._get_rgb_by_label(text)
            self.unique_label_list.set_item_label(
                unique_label_item, text, rgb, LABEL_OPACITY
            )

        self.set_dirty()
        self._refresh_shape_filters()

    def edit_label(self, item=None):
        if item and not isinstance(item, LabelListWidgetItem):
            raise TypeError("item must be LabelListWidgetItem type")

        if not self.canvas.editing():
            return

        selected_shapes = self.canvas.selected_shapes
        if not selected_shapes:
            return

        if len(selected_shapes) > 1:
            return self.batch_edit_labels(selected_shapes)

        if not item:
            item = self.current_item()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return
        (
            text,
            flags,
            group_id,
            description,
            difficult,
            kie_linking,
        ) = self.label_dialog.pop_up(
            text=shape.label,
            flags=shape.flags,
            group_id=shape.group_id,
            description=shape.description,
            difficult=shape.difficult,
            kie_linking=shape.kie_linking,
            review_status=shape.other_data.get("review_status", "pending"),
            move_mode=self._config.get("move_mode", "auto"),
        )
        if text is None:
            return
        if not self.validate_label(text):
            self.error_message(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            return
        if self.attributes and text and text != shape.label:
            text = self.reset_attribute(text, shape)
        shape.label = text
        shape.flags = flags
        shape.group_id = group_id
        shape.description = description
        shape.difficult = difficult
        shape.kie_linking = kie_linking
        shape.other_data["review_status"] = (
            self.label_dialog.get_review_status()
        )

        # Add to label history
        self.label_dialog.add_label_history(shape.label)

        # Update last group_id
        if group_id is not None:
            self.label_dialog._last_gid = group_id

        # Update unique label list
        if not self.unique_label_list.find_items_by_label(shape.label):
            unique_label_item = self.unique_label_list.create_item_from_label(
                shape.label
            )
            self.unique_label_list.addItem(unique_label_item)
            rgb = self._get_rgb_by_label(shape.label)
            self.unique_label_list.set_item_label(
                unique_label_item, shape.label, rgb, LABEL_OPACITY
            )

        self._update_shape_color(shape)
        if shape.group_id is None:
            color = self._get_rgb_by_label(shape.label)
            item.setText(_format_label_list_text(shape.label, shape.group_id))
            item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
        else:
            item.setText(_format_label_list_text(shape.label, shape.group_id))
        self.set_dirty()
        self._refresh_shape_filters()

    def file_search_changed(self):
        search_text = self.file_search.text()
        self.import_image_folder(
            self.last_open_dir,
            pattern=search_text,
            load=False,
        )

    def file_selection_changed(self):
        row = self.file_list_widget.currentRow()
        if row < 0:
            return
        if not self.may_continue():
            return
        filename = self._file_path_at(row)
        if filename:
            self.load_file(filename)

    def attribute_selection_changed(self, i, property, combo):
        return AttributesPanel(self).attribute_selection_changed(i, property, combo)

    def attribute_radio_changed(self, i, property, option, checked):
        return AttributesPanel(self).attribute_radio_changed(i, property, option, checked)

    def attribute_line_changed(self, i, property, line: QLineEdit):
        return AttributesPanel(self).attribute_line_changed(i, property, line)

    def update_selected_options(self, selected_options):
        return AttributesPanel(self).update_selected_options(selected_options)

    def update_attributes(self, shape_index):
        return AttributesPanel(self).update_attributes(shape_index)

    def show_attributes_panel(self):
        return AttributesPanel(self).show_attributes_panel()

    def hide_attributes_panel(self):
        return AttributesPanel(self).hide_attributes_panel()

    def save_attributes(self, _shapes):
        return AttributesPanel(self).save_attributes(_shapes)

    # React to canvas signals.
    def shape_selection_changed(self, selected_shapes):
        if selected_shapes and self.canvas.selected_relation is not None:
            self.canvas.selected_relation = None
            self.canvas.update()
        if self.canvas.is_brush_mode:
            target = self.canvas._brush_target_shape
            if selected_shapes != [target]:
                self._no_selection_slot = True
                self.label_list.clearSelection()
                item = self.label_list.find_item_by_shape(target)
                if item is not None:
                    self.label_list.select_item(item)
                    self.label_list.scroll_to_item(item)
                self._no_selection_slot = False
                return
        self._no_selection_slot = True
        for shape in self.canvas.selected_shapes:
            shape.selected = False
        self.label_list.clearSelection()
        self.canvas.selected_shapes = selected_shapes
        allow_merge_shape_type = {"rectangle": 0, "polygon": 0}
        for shape in self.canvas.selected_shapes:
            shape.selected = True
            if shape.shape_type in ["rectangle", "polygon"]:
                allow_merge_shape_type[shape.shape_type] += 1
            item = self.label_list.find_item_by_shape(shape)
            # NOTE: Handle the case when the shape is not found
            if item is not None:
                self.label_list.select_item(item)
                self.label_list.scroll_to_item(item)
        self._no_selection_slot = False
        n_selected = len(selected_shapes)
        self.actions.create_relation.setEnabled(n_selected == 2)
        same_type = (
            len(set(shape.shape_type for shape in selected_shapes)) <= 1
        )
        has_locked = any(shape.locked for shape in selected_shapes)
        has_unlocked = any(not shape.locked for shape in selected_shapes)
        group_shapes = self.canvas._active_group_shapes()
        self.actions.delete.setEnabled(
            has_unlocked and not (group_shapes and has_locked)
        )
        self.actions.duplicate.setEnabled(n_selected)
        self.actions.copy.setEnabled(n_selected)
        self.actions.edit.setEnabled(n_selected >= 1 and same_type)
        self.actions.copy_coordinates.setEnabled(n_selected == 1)
        can_brush_edit = (
            n_selected == 1
            and selected_shapes[0].shape_type == "polygon"
            and not selected_shapes[0].locked
        )
        self.actions.edit_brush_mode.setEnabled(can_brush_edit)
        self.actions.union_selection.setEnabled(
            not has_locked
            and not all(value > 0 for value in allow_merge_shape_type.values())
            and (
                allow_merge_shape_type["rectangle"] > 1
                or allow_merge_shape_type["polygon"] > 1
            )
        )
        self.refresh_shape_lock_action()
        self.set_text_editing(True)

    def add_label(self, shape, update_last_label=True, refresh_filters=True):
        if shape.label in self.unique_label_list.lock_states:
            shape.locked = self.unique_label_list.lock_states[shape.label]
        if shape.group_id is None:
            text = shape.label
        else:
            text = f"{shape.label} ({shape.group_id})"
        label_list_item = LabelListWidgetItem(text, shape)
        if not self.unique_label_list.find_items_by_label(shape.label):
            item = self.unique_label_list.create_item_from_label(shape.label)
            self.unique_label_list.addItem(item)
            rgb = self._get_rgb_by_label(shape.label)
            self.unique_label_list.set_item_label(
                item, shape.label, rgb, LABEL_OPACITY
            )

        if shape.label not in self.label_info:
            rgb = self._get_rgb_by_label(shape.label)
            self.label_info[shape.label] = dict(
                delete=False,
                value=None,
                color=list(rgb),
                opacity=LABEL_OPACITY,
                visible=True,
            )

        # Add label to history if it is not a special label
        if shape.label not in [
            AutoLabelingMode.OBJECT,
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            self.label_dialog.add_label_history(
                shape.label, update_last_label=update_last_label
            )
            if update_last_label and shape.group_id is not None:
                self.label_dialog._last_gid = shape.group_id

        for action in self.actions.on_shapes_present:
            action.setEnabled(True)

        self._update_shape_color(shape)
        color = self._get_rgb_by_label(shape.label)
        label_list_item.setText(
            _format_label_list_text(shape.label, shape.group_id)
        )
        _set_label_list_item_lock(label_list_item, shape.locked)
        label_list_item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
        self.label_list.add_iem(label_list_item)
        if refresh_filters:
            self._refresh_shape_filters()

    def load_labels(self, labels, clear_existing=True):
        """
        Load labels to the unique label list widget.

        Args:
            labels (list): List of label names to load
            clear_existing (bool): Whether to clear existing labels before loading new ones
        """
        if not labels:
            return

        if clear_existing:
            self.unique_label_list.clear()

        for label in labels:
            # Check if label already exists to avoid duplicates
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.unique_label_list.set_item_label(
                    item, label, rgb, LABEL_OPACITY
                )

    def _update_shape_color(self, shape):
        r, g, b = self._get_rgb_by_label(shape.label)
        shape_config = self._config["shape"]
        defaults = load_template_config()["shape"]
        colors = {
            "line_color": (r, g, b, 255),
            "vertex_fill_color": (r, g, b, 255),
            "hvertex_fill_color": (255, 255, 255, 255),
            "fill_color": (r, g, b, 128),
            "select_line_color": (255, 255, 255, 255),
            "select_fill_color": (r, g, b, 155),
        }
        for key, color in colors.items():
            if shape_config[key] != defaults[key]:
                color = shape_config[key]
            setattr(shape, key, QtGui.QColor(*color))

    def _get_rgb_by_label(self, label, skip_label_info=False):
        if label == "AUTOLABEL_ADD":
            return (144, 238, 144)
        if label == "AUTOLABEL_REMOVE":
            return (255, 182, 193)
        if label in self.label_info and not skip_label_info:
            return tuple(self.label_info[label]["color"])
        if self._config["shape_color"] == "auto":
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
            item = self.unique_label_list.find_items_by_label(label)[0]
            label_id = self.unique_label_list.indexFromItem(item).row() + 1
            label_id += self._runtime_shape_color_shift
            return LABEL_COLORMAP[label_id % len(LABEL_COLORMAP)]
        if (
            self._config["shape_color"] == "manual"
            and self._config["label_colors"]
            and label in self._config["label_colors"]
        ):
            return self._config["label_colors"][label]
        if self._config["default_shape_color"]:
            return self._config["default_shape_color"]
        return (0, 255, 0)

    def remove_labels(self, shapes):
        for shape in shapes:
            item = self.label_list.find_item_by_shape(shape)
            self.label_list.remove_item(item)
        self._refresh_shape_filters()

    def _relation_data_for_shapes(self, shapes):
        other_data = dict(self.other_data)
        if "relations" in other_data:
            ids = {shape.get("shape_id") for shape in shapes}
            other_data["relations"] = [
                relation
                for relation in self.canvas.relations
                if relation.get("subject_id") in ids
                and relation.get("object_id") in ids
            ]
        return other_data

    def create_relation(self, _checked=False):
        if len(self.canvas.selected_shapes) == 2:
            self._relation_dialog()

    def edit_relation(self, index):
        if 0 <= index < len(self.canvas.relations):
            self._relation_dialog(index)

    def delete_selected_relation(self):
        selected = self.canvas.selected_relation
        for index, relation in enumerate(self.canvas.relations):
            if relation is selected:
                del self.canvas.relations[index]
                self.canvas.selected_relation = None
                self.other_data["relations"] = self.canvas.relations
                self.other_data[CHECKED_FIELD] = False
                self._sync_annotation_checked_state()
                self.canvas.update()
                self.set_dirty()
                return

    def manage_relations(self, _checked=False):
        dialog = RelationManagerDialog(self)

        def preview_selected(index):
            self.canvas.preview_relation = (
                self.canvas.relations[index]
                if index is not None
                and 0 <= index < len(self.canvas.relations)
                else None
            )
            self.canvas.update()

        def edit_selected(index):
            self.edit_relation(index)
            dialog.refresh(self.canvas.shapes, self.canvas.relations)

        dialog.preview_requested.connect(preview_selected)
        dialog.edit_requested.connect(edit_selected)
        dialog.refresh(self.canvas.shapes, self.canvas.relations)
        try:
            dialog.exec()
        finally:
            self.canvas.preview_relation = None
            self.canvas.update()

    def _relation_dialog(self, index=None):  # noqa: C901
        shapes = [shape for shape in self.canvas.shapes if shape.points]
        if len(shapes) < 2:
            self._show_relation_message(
                QtWidgets.QMessageBox.Icon.Information,
                self.tr("At least two shapes are required."),
            )
            return
        relation = self.canvas.relations[index] if index is not None else None
        dialog = RelationDialog(
            shapes, self.canvas.selected_shapes, relation, parent=self
        )
        while True:
            result = dialog.exec()
            if result == 2:
                del self.canvas.relations[index]
                if self.canvas.selected_relation is relation:
                    self.canvas.selected_relation = None
                break
            if result != QtWidgets.QDialog.DialogCode.Accepted:
                return
            subject_shape, object_shape, text = dialog.values()
            if subject_shape is object_shape or not text:
                self._show_relation_message(
                    QtWidgets.QMessageBox.Icon.Warning,
                    self.tr(
                        "Choose two different shapes and enter a relation label."
                    ),
                    dialog,
                )
                continue
            for shape in (subject_shape, object_shape):
                if not shape.other_data.get("shape_id"):
                    shape.other_data["shape_id"] = uuid4().hex
                    for backup in self.canvas.shapes_backups:
                        for previous in backup:
                            if (
                                previous._relation_identity
                                == shape._relation_identity
                            ):
                                previous.other_data["shape_id"] = (
                                    shape.other_data["shape_id"]
                                )
            updated = {
                "subject_id": subject_shape.other_data["shape_id"],
                "object_id": object_shape.other_data["shape_id"],
                "label": text,
                "score": None,
            }
            if relation is not None:
                if all(
                    updated[key] == relation.get(key)
                    for key in ("subject_id", "object_id", "label")
                ):
                    return
                self.canvas.relations[index] = updated
                if self.canvas.selected_relation is relation:
                    self.canvas.selected_relation = updated
            else:
                self.canvas.relations.append(updated)
            break
        self.other_data["relations"] = self.canvas.relations
        self.other_data[CHECKED_FIELD] = False
        self._sync_annotation_checked_state()
        self.canvas.update()
        self.set_dirty()

    def _show_relation_message(self, icon, text, parent=None):
        show_relation_message(icon, text, parent or self)

    def on_canvas_shapes_deleted(self, shapes):
        self.remove_labels(shapes)
        self.set_dirty()
        if self.no_shape():
            for action in self.actions.on_shapes_present:
                action.setEnabled(False)

    def load_shapes(self, shapes, replace=True, update_last_label=True):
        self._no_selection_slot = True
        self.label_list.setUpdatesEnabled(False)
        try:
            for shape in shapes:
                self.add_label(
                    shape,
                    update_last_label=update_last_label,
                    refresh_filters=False,
                )
            self.label_list.clearSelection()
        finally:
            self.label_list.setUpdatesEnabled(True)
            self._no_selection_slot = False
        self.canvas.load_shapes(shapes, replace=replace)
        self._refresh_shape_filters()

    def load_flags(self, flags):
        self.flag_widget.clear()
        for key, flag in flags.items():
            item = QtWidgets.QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if flag else Qt.CheckState.Unchecked
            )
            self.flag_widget.addItem(item)

    def _sync_label_list_visibility(self, get_visible):
        with QtCore.QSignalBlocker(self.unique_label_list):
            for row in range(self.unique_label_list.count()):
                item = self.unique_label_list.item(row)
                visible = self.label_info.get(
                    item.data(Qt.ItemDataRole.UserRole), {}
                ).get("visible", True)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if visible
                    else Qt.CheckState.Unchecked
                )
        model = self.label_list.model()
        blocker = QtCore.QSignalBlocker(model)
        self.label_list.setUpdatesEnabled(False)
        try:
            for item in self.label_list:
                is_visible = bool(get_visible(item))
                check_state = (
                    Qt.CheckState.Checked
                    if is_visible
                    else Qt.CheckState.Unchecked
                )
                if item.checkState() != check_state:
                    item.setCheckState(check_state)
                shape = item.shape()
                shape.visible = is_visible
                self.canvas.visible[shape] = is_visible
        finally:
            self.label_list.setUpdatesEnabled(True)
            del blocker
        self.canvas.update()
        self._update_select_toggle_button_tooltip()
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()

    def _refresh_shape_filters(self):
        self.update_combo_box(block_signal=True)
        self.update_gid_box(block_signal=True)
        current_gid = self.gid_filter_combobox.gid_box.currentText()
        if current_gid and current_gid != "-1":
            self.gid_selection_changed(
                self.gid_filter_combobox.gid_box.currentIndex()
            )
            return
        current_label = self.label_filter_combobox.text_box.currentText()
        if current_label:
            self.text_selection_changed(
                self.label_filter_combobox.text_box.currentIndex()
            )
            return
        self.apply_label_visibility()

    def set_label_visibility(self, label, visible):
        if label not in self.label_info:
            self.label_info[label] = dict(
                delete=False,
                value=None,
                color=list(self._get_rgb_by_label(label)),
                opacity=LABEL_OPACITY,
                visible=visible,
            )
        else:
            self.label_info[label]["visible"] = visible
        self._refresh_shape_filters()

    def apply_label_visibility(self):
        self._sync_label_list_visibility(
            lambda item: self.label_info.get(item.shape().label, {}).get(
                "visible", True
            )
        )

    def update_combo_box(self, block_signal=False):
        current_label = self.label_filter_combobox.text_box.currentText()

        # Get the unique labels and add them to the Combobox.
        labels_list = []
        for item in self.label_list:
            label = item.shape().label
            labels_list.append(str(label))
        unique_labels_list = list(set(labels_list))

        # Add a null row for showing all the labels
        unique_labels_list.append("")
        unique_labels_list.sort()
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(
                self.label_filter_combobox.text_box
            )
        self.label_filter_combobox.update_items(unique_labels_list)
        if current_label in unique_labels_list:
            self.set_label_filter_value(
                current_label, block_signal=block_signal
            )
        else:
            self.set_label_filter_value("", block_signal=block_signal)
        del blocker

    def update_gid_box(self, block_signal=False):
        current_gid = self.gid_filter_combobox.gid_box.currentText()

        # Get the unique group ids and add them to the Combobox.
        gid_list = []
        for item in self.label_list:
            gid = item.shape().group_id
            if gid is not None:
                gid_list.append(str(gid))
        unique_gid_list = list(set(gid_list))

        # Add a null row for showing all the labels
        unique_gid_list.append("-1")
        unique_gid_list.sort()
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(self.gid_filter_combobox.gid_box)
        self.gid_filter_combobox.update_items(unique_gid_list)
        if current_gid in unique_gid_list:
            self.set_gid_filter_value(current_gid, block_signal=block_signal)
        else:
            self.set_gid_filter_value("-1", block_signal=block_signal)
        del blocker

    def save_labels(self, filename):
        label_file = LabelFile()
        # Get current shapes
        # Excluding auto labeling special shapes
        shapes = [
            item.shape().to_dict()
            for item in self.label_list
            if item.shape().label
            not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]
        ]
        flags = {}
        for i in range(self.flag_widget.count()):
            item = self.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.CheckState.Checked
            flags[key] = flag
        self.other_data[CHECKED_FIELD] = self._annotation_checked()
        signature, allowed = self._prepare_attribution(shapes, flags)
        if not allowed:
            return False
        try:
            image_path = osp.relpath(self.image_path, osp.dirname(filename))
            image_data = (
                self.image_data if self._config["store_data"] else None
            )
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))

            label_file.save(
                filename=filename,
                shapes=shapes,
                image_path=image_path,
                image_data=image_data,
                image_height=self.image.height(),
                image_width=self.image.width(),
                other_data=self._relation_data_for_shapes(shapes),
                flags=flags,
            )
            self.label_file = label_file
            self.operator_gate.baseline = signature
            self.actions.save.setIcon(utils.new_icon("save-check"))
            self._update_file_row_after_save(len(shapes))
            # disable allows next and previous image to proceed
            # self.filename = filename
            return True
        except LabelFileError as e:
            self.error_message(
                self.tr("Error saving label data"), self.tr("<b>%s</b>") % e
            )
            return False

    def duplicate_selected_shape(self):
        added_shapes = self.canvas.duplicate_selected_shapes()
        self.label_list.clearSelection()
        self.label_list.setUpdatesEnabled(False)
        try:
            for shape in added_shapes:
                self.add_label(shape, refresh_filters=False)
        finally:
            self.label_list.setUpdatesEnabled(True)
        if added_shapes:
            self._refresh_shape_filters()
        self.set_dirty()

    def paste_selected_shape(self):
        if self._config["system_clipboard"]:
            clipboard = QtWidgets.QApplication.clipboard()
            json_str = clipboard.text()
            shapes = []
            try:
                shapeDicts = json.loads(json_str)
                for shapeDict in shapeDicts:
                    shapes.append(Shape().load_from_dict(shapeDict))
            except json.JSONDecodeError as e:
                self.error_message(
                    self.tr("Error pasting shapes"),
                    self.tr("Error decoding shapes: %s") % str(e),
                )
                return
        else:
            shapes = self._copied_shapes
        shapes = self.canvas.prepare_pasted_shapes(
            shapes, self._copied_group_id
        )
        self.load_shapes(shapes, replace=False)
        self.set_dirty()

    def toggle_system_clipboard(self, system_clipboard):
        self._config["system_clipboard"] = system_clipboard
        self.actions.paste.setEnabled(
            bool(system_clipboard or self._copied_shapes)
        )

    def copy_selected_shape(self):
        group_shapes = self.canvas._active_group_shapes()
        self._copied_group_id = (
            self.canvas._selected_group_id if group_shapes else None
        )
        if self._config["system_clipboard"]:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(
                json.dumps([s.to_dict() for s in self.canvas.selected_shapes])
            )
        else:
            self._copied_shapes = [
                s.copy() for s in self.canvas.selected_shapes
            ]
            self.actions.paste.setEnabled(len(self._copied_shapes) > 0)

    def text_selection_changed(self, index):
        label = self.label_filter_combobox.text_box.itemText(index)
        self._sync_label_list_visibility(
            lambda item: label in ["", item.shape().label]
            and self.label_info.get(item.shape().label, {}).get(
                "visible", True
            )
        )

    def gid_selection_changed(self, index):
        gid = self.gid_filter_combobox.gid_box.itemText(index)
        self._sync_label_list_visibility(
            lambda item: str(gid)
            in (
                ["-1", str(item.shape().group_id)]
                if item.shape().group_id is not None
                else ["-1"]
            )
            and self.label_info.get(item.shape().label, {}).get(
                "visible", True
            )
        )

    def label_selection_changed(self):
        if self._no_selection_slot:
            return
        if self.canvas.is_brush_mode:
            return
        if self.canvas.editing():
            selected_shapes = []
            for item in self.label_list.selected_items():
                selected_shapes.append(item.shape())
            if selected_shapes:
                self.canvas.select_shapes(selected_shapes)
            else:
                self.canvas.deselect_shape()

    def label_item_changed(self, item):
        shape = item.shape()
        shape.visible = item.checkState() == Qt.CheckState.Checked
        self.canvas.set_shape_visible(
            shape, item.checkState() == Qt.CheckState.Checked
        )
        self._update_select_toggle_button_tooltip()
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()

    # Callback functions:
    def new_shape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        items = self.unique_label_list.selectedItems()
        text = None
        if items:
            text = items[0].data(Qt.ItemDataRole.UserRole)
        flags = {}
        group_id = None
        description = ""
        difficult = False
        kie_linking = []
        review_status = "pending"

        if self.canvas.shapes[-1].label in [
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            text = self.canvas.shapes[-1].label
        elif (
            self._config["display_label_popup"]
            or not text
            or self.canvas.shapes[-1].label == AutoLabelingMode.OBJECT
        ):
            last_label = self.find_last_label()
            last_gid = (
                self.find_last_gid()
                if self._config["auto_use_last_gid"]
                else None
            )
            if self.digit_to_label is not None:
                text = self.digit_to_label
                self.digit_to_label = None
                if last_gid is not None:
                    group_id = last_gid
            elif self._config["auto_use_last_label"] and last_label:
                text = last_label
                if last_gid is not None:
                    group_id = last_gid
            else:
                previous_text = self.label_dialog.edit.text()
                (
                    text,
                    flags,
                    group_id,
                    description,
                    difficult,
                    kie_linking,
                ) = self.label_dialog.pop_up(
                    text,
                    group_id=last_gid,
                    move_mode=self._config.get("move_mode", "auto"),
                )
                review_status = self.label_dialog.get_review_status()
                if not text:
                    self.label_dialog.edit.setText(previous_text)

        if text and not self.validate_label(text):
            self.error_message(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            text = ""
            return

        if self.attributes and text:
            text = self.reset_attribute(text, self.canvas.shapes[-1])

        if text:
            self.label_list.clearSelection()
            shape = self.canvas.set_last_label(text, flags, group_id)
            shape.group_id = group_id
            shape.description = description
            if text not in [AutoLabelingMode.ADD, AutoLabelingMode.REMOVE]:
                shape.label = text
            shape.difficult = difficult
            shape.kie_linking = kie_linking
            shape.other_data["review_status"] = review_status
            self.add_label(shape)
            self.actions.edit_mode.setEnabled(True)
            self.actions.undo_last_point.setEnabled(False)
            self.actions.undo.setEnabled(True)
            self.set_dirty()
            if (
                self.canvas.drawing()
                and self.canvas.create_mode == "polygon"
                and not self.actions.create_brush_polygon_mode.isEnabled()
            ):
                self.canvas._brush_drawing = True

        else:
            if self.canvas.is_magic_wand_mode:
                self.canvas.shapes.pop()
                self.canvas.shapes_backups.pop()
                self.canvas.update()
            else:
                self.canvas.undo_last_line()
                self.canvas.shapes_backups.pop()

    def show_line_length(self, length, pos):
        if self.canvas.create_mode == "linestrip":
            points = self.canvas.current.points
            total_length = length + sum(
                utils.distance(points[i] - points[i - 1])
                for i in range(1, len(points))
            )
            self.status(
                self.tr("L: %.2f px | Total: %.2f px")
                % (length, total_length)
            )
            return
        self.status(self.tr("L: %.2f px") % length)

    def show_circle_radius(self, radius, pos):
        self.status(
            self.tr("R: %.2f px | C: %.2f px")
            % (radius, 2 * math.pi * radius)
        )

    def show_shape(self, shape_height, shape_width, pos):
        """Display annotation width and height while hovering inside.

        Coordinates are shown by the status bar's ``[x,y|path]`` label, so
        this hint only reports the shape size.
        """
        if shape_height > 0 and shape_width > 0:
            self.status(
                str(self.tr("H: %d, W: %d"))
                % (shape_height, shape_width)
            )

    def on_navigator_request(self, x_ratio, y_ratio):
        """Handle navigation request from navigator widget."""
        if not hasattr(self, "image") or self.image.isNull():
            return

        image_pos = QtCore.QPointF(
            x_ratio * self.canvas.pixmap.width(),
            y_ratio * self.canvas.pixmap.height(),
        )
        canvas_pos = (
            image_pos + self.canvas.offset_to_center()
        ) * self.canvas.scale
        center = QtCore.QPointF(
            self._canvas_scroll_area.viewport().rect().center()
            - self.canvas.pos()
        )
        self.pan_canvas(center - canvas_pos)

    def update_navigator_viewport(self):
        """Update the viewport rectangle in the navigator."""
        if not hasattr(self, "navigator_dialog") or not hasattr(self, "image"):
            return

        if not self.navigator_dialog.isVisible():
            return

        if self.image.isNull():
            return

        scroll_area = self._central_widget
        canvas_size = self.canvas.pixmap.size() * self.canvas.scale
        scroll_area_size = scroll_area.viewport().size()
        if canvas_size.width() <= 0 or canvas_size.height() <= 0:
            return

        origin = self.canvas.transform_pos(QtCore.QPointF(-self.canvas.pos()))
        x_ratio = origin.x() / self.canvas.pixmap.width()
        y_ratio = origin.y() / self.canvas.pixmap.height()
        width_ratio = scroll_area_size.width() / canvas_size.width()
        height_ratio = scroll_area_size.height() / canvas_size.height()

        self.navigator_dialog.set_viewport(
            x_ratio, y_ratio, width_ratio, height_ratio
        )
        self.update_navigator_shapes()

    def update_navigator_shapes(self):
        """Update shapes overlay in navigator."""
        if (
            not hasattr(self, "navigator_dialog")
            or not self.navigator_dialog.isVisible()
        ):
            return

        shapes = getattr(self.canvas, "shapes", [])
        canvas_visible = getattr(self.canvas, "visible", {})
        h_shape = getattr(self.canvas, "h_shape", None)
        for shape in shapes:
            shape._is_highlighted = shape == h_shape
        self.navigator_dialog.set_shapes(shapes, canvas_visible)

    def on_navigator_zoom_changed(
        self, zoom_percentage: int, mouse_pos: Optional[QtCore.QPoint] = None
    ) -> None:
        """Handle zoom change from navigator controls."""

        if not hasattr(self, "image") or self.image.isNull():
            return

        if mouse_pos is not None:
            canvas_pos = self._convert_navigator_pos_to_canvas(mouse_pos)
            if canvas_pos is not None:
                self.set_zoom(zoom_percentage, pos=canvas_pos)
                return

        # Handle direct zoom changes
        self.set_zoom(zoom_percentage)

    def _convert_navigator_pos_to_canvas(
        self, navigator_pos: QtCore.QPoint
    ) -> Optional[QtCore.QPoint]:
        """Convert navigator mouse position to canvas coordinates."""
        if (
            not hasattr(self, "navigator_dialog")
            or not self.navigator_dialog.isVisible()
        ):
            return None

        navigator_widget = self.navigator_dialog.navigator
        if (
            not navigator_widget.image_rect
            or navigator_widget.image_rect.isEmpty()
        ):
            return None

        relative_x = navigator_pos.x() - navigator_widget.image_rect.x()
        relative_y = navigator_pos.y() - navigator_widget.image_rect.y()
        if (
            relative_x < 0
            or relative_x > navigator_widget.image_rect.width()
            or relative_y < 0
            or relative_y > navigator_widget.image_rect.height()
        ):
            return None

        # Convert to ratio (0.0 to 1.0)
        x_ratio = relative_x / navigator_widget.image_rect.width()
        y_ratio = relative_y / navigator_widget.image_rect.height()

        # Convert to canvas coordinates
        offset = self.canvas.offset_to_center()
        canvas_x = round(
            (x_ratio * self.canvas.pixmap.width() + offset.x())
            * self.canvas.scale
        )
        canvas_y = round(
            (y_ratio * self.canvas.pixmap.height() + offset.y())
            * self.canvas.scale
        )

        return QtCore.QPoint(canvas_x, canvas_y)

    def on_navigator_viewport_update_requested(self):
        """Handle viewport update request from navigator resize"""
        QtCore.QTimer.singleShot(50, self.update_navigator_viewport)

    def toggle_navigator(self):
        """Toggle the navigator window visibility"""
        if self.navigator_dialog.isVisible():
            self.navigator_dialog.hide()
            if hasattr(self, "actions") and hasattr(
                self.actions, "show_navigator"
            ):
                self.actions.show_navigator.setChecked(False)
        else:
            self.navigator_dialog.show()
            if hasattr(self, "image") and not self.image.isNull():
                self.navigator_dialog.set_image(
                    QtGui.QPixmap.fromImage(self.image)
                )
                self.update_navigator_viewport()
            if hasattr(self, "actions") and hasattr(
                self.actions, "show_navigator"
            ):
                self.actions.show_navigator.setChecked(True)

    def scroll_request(self, delta, orientation, mode):
        scroll_bar = self.scroll_bars[orientation]
        units = -delta * (0.1 if mode == 0 else 1)
        step = scroll_bar.singleStep() if mode == 0 else scroll_bar.maximum()
        value = scroll_bar.value() + step * units
        self.set_scroll(orientation, value)

    def set_scroll(self, orientation, value):
        self.scroll_bars[orientation].setValue(round(value))
        self.scroll_values[orientation][self.filename] = value
        self.update_navigator_viewport()

    def set_zoom(self, value, *, pos=None):
        self._zoom_animation.stop()
        self.actions.fit_width.setChecked(False)
        self.actions.fit_window.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        if pos is None:
            self._apply_zoom(value)
        else:
            self._apply_zoom(
                value,
                self.canvas.transform_pos(QtCore.QPointF(pos)),
                QtCore.QPointF(pos) + QtCore.QPointF(self.canvas.pos()),
            )

    def add_zoom(self, increment=1.1):
        zoom_value = self.canvas.scale * 100 * increment
        if increment > 1:
            zoom_value = math.ceil(zoom_value)
        else:
            zoom_value = math.floor(zoom_value)
        self.set_zoom(zoom_value)

    def zoom_request(self, delta, pos):
        if not delta or self.image.isNull():
            return
        animation = self._zoom_animation
        value = self.canvas.scale * 100
        if animation.state() == QtCore.QAbstractAnimation.State.Running:
            value = animation.endValue()
        animation.stop()
        value *= 1.1 ** (max(-12000, min(12000, delta)) / 120.0)
        value = max(
            self.zoom_widget.minimum(), min(self.zoom_widget.maximum(), value)
        )
        self.actions.fit_width.setChecked(False)
        self.actions.fit_window.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        self._zoom_anchor_image = self.canvas.transform_pos(
            QtCore.QPointF(pos)
        )
        self._zoom_anchor_viewport = QtCore.QPointF(pos) + QtCore.QPointF(
            self.canvas.pos()
        )
        with QtCore.QSignalBlocker(animation):
            animation.setStartValue(self.canvas.scale * 100)
            animation.setEndValue(float(value))
        animation.start()

    def _animate_zoom(self, value):
        self._apply_zoom(
            value, self._zoom_anchor_image, self._zoom_anchor_viewport
        )

    def _apply_zoom(self, value, image_pos=None, viewport_pos=None):
        if self.image.isNull():
            return
        value = max(
            self.zoom_widget.minimum(), min(self.zoom_widget.maximum(), value)
        )
        if viewport_pos is None:
            viewport_pos = QtCore.QPointF(
                self._canvas_scroll_area.viewport().rect().center()
            )
        if image_pos is None:
            image_pos = self.canvas.transform_pos(
                viewport_pos - QtCore.QPointF(self.canvas.pos())
            )
        with QtCore.QSignalBlocker(self.zoom_widget):
            self.zoom_widget.setValue(round(value))
        self.canvas.scale = value / 100.0
        self.canvas.adjustSize()
        canvas_pos = (
            image_pos + self.canvas.offset_to_center()
        ) * self.canvas.scale
        self.canvas.pan_offset += (
            viewport_pos - QtCore.QPointF(self.canvas.pos()) - canvas_pos
        )
        self.zoom_values[self.filename] = (self.zoom_mode, value)
        self.constrain_canvas_pan()
        self.pan_values[self.filename] = QtCore.QPointF(self.canvas.pan_offset)
        self.canvas.update()
        if hasattr(self, "navigator_dialog"):
            self.navigator_dialog.set_zoom_value(round(value))
        self.update_navigator_viewport()

    def constrain_canvas_pan(self):
        if self.canvas.wheel_navigation_mode != "traditional":
            return
        offset = self.canvas.pan_offset
        self.canvas.pan_offset = QtCore.QPointF()
        area = self._canvas_scroll_area
        for bar, delta in (
            (area.horizontalScrollBar(), offset.x()),
            (area.verticalScrollBar(), offset.y()),
        ):
            bar.setValue(round(bar.value() - delta))
            self.scroll_values[bar.orientation()][self.filename] = bar.value()
        self.pan_values[self.filename] = QtCore.QPointF()
        self.canvas.update()
        self.update_navigator_viewport()

    def pan_canvas(self, delta):
        self._zoom_animation.stop()
        self.actions.fit_width.setChecked(False)
        self.actions.fit_window.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        self.zoom_values[self.filename] = (
            self.zoom_mode,
            self.canvas.scale * 100,
        )
        self.canvas.pan_offset += delta
        self.constrain_canvas_pan()
        self.pan_values[self.filename] = QtCore.QPointF(self.canvas.pan_offset)
        self.canvas.update()
        self.update_navigator_viewport()

    def set_fit_window(self, value=True):
        if value:
            self.actions.fit_width.setChecked(False)
        self.zoom_mode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_fit_width(self, value=True):
        if value:
            self.actions.fit_window.setChecked(False)
        self.zoom_mode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_canvas_params(self, key, value):
        self._config[key] = value
        assert hasattr(self.canvas, key), f"Canvas has no attribute {key}"
        setattr(self.canvas, key, value)
        if key in ("show_labels", "show_linking") and not value:
            self.canvas.selected_relation = None
        self.canvas.update()

    def open_settings_dialog(self, _checked=False, field_key=None):
        if self._settings_controller is None:
            return
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(
                self, self._settings_controller
            )
        if field_key is not None:
            self._settings_dialog.show_field(field_key)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def add_point_to_edge(self):
        shape = self.canvas.prev_h_shape
        edge_index = self.canvas.prev_h_edge
        point = self.canvas.prev_move_point
        if shape is None or edge_index is None or point is None:
            return
        self.canvas.add_point_to_edge()
        self.canvas.update()
        self.set_dirty()

    def _on_shape_opacity_changed(self, value):
        """Update annotation fill opacity from the slider value (0-100)."""
        self.canvas.shape_opacity = value / 100.0
        self.canvas.update()

    def _on_inline_brightness_contrast(self, brightness, contrast):
        """Apply brightness/contrast from the inline adjustment sliders.

        Reuses ``brightness_contrast_processor`` so 16-bit grayscale handling
        remains supported. The source image is refreshed on every image load.
        """
        if self.image_data is None or self.filename is None:
            return
        qimage = self.brightness_contrast_processor.adjust(
            brightness, contrast
        )
        self.canvas.load_pixmap(
            QtGui.QPixmap.fromImage(qimage), clear_shapes=False
        )
        self.brightness_contrast_values[self.filename] = (brightness, contrast)

    def _on_grid_changed(self, enabled, size, color, opacity, labels):
        self.canvas.grid_enabled = enabled
        self.canvas.grid_size = size
        self.canvas.grid_color = color
        self.canvas.grid_opacity = opacity
        self.canvas.grid_labels = labels
        self.canvas.update()

    def _position_canvas_adjustment(self):
        """Keep the adjustment panel anchored to the viewport's bottom-left."""
        if not hasattr(self, "canvas_adjustment"):
            return
        viewport = self._canvas_scroll_area.viewport()
        self.canvas_adjustment.adjustSize()
        margin = 10
        height = self.canvas_adjustment.height()
        self.canvas_adjustment.move(
            margin, max(0, viewport.height() - height - margin)
        )
        self.canvas_adjustment.raise_()
        self._position_browse_mode_badge()

    def _position_browse_mode_badge(self):
        """Keep the browse-mode badge at the viewport's top-left."""
        badge = getattr(self, "browse_mode_badge", None)
        if badge is None:
            return
        viewport = self._canvas_scroll_area.viewport()
        badge.adjustSize()
        badge.move(12, 12)
        if badge.isVisible():
            badge.raise_()
        self._ensure_badge_fits(viewport, badge)

    def _ensure_badge_fits(self, viewport, badge):
        max_width = max(120, viewport.width() - 24)
        if badge.width() > max_width:
            badge.setFixedWidth(max_width)

    def _refresh_browse_mode_badge(self):
        """Show or hide the browse-mode badge and refresh its wording."""
        badge = getattr(self, "browse_mode_badge", None)
        if badge is None:
            return
        theme = get_theme()
        if self._operator_edit_allowed():
            badge.hide()
            return
        badge.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX: let it re-measure
        badge.setText(self.tr("Login to edit annotations"))
        badge.setStyleSheet(
            f"QPushButton#BrowseModeBadge {{"
            f" background: {theme['background_secondary']};"
            f" color: {theme['warning_text']};"
            f" border: 1px solid {theme['warning_text']};"
            f" border-radius: 12px;"
            f" padding: 4px 10px;"
            f" font-size: 12px;"
            f" font-weight: 600;"
            f" }}"
            f"QPushButton#BrowseModeBadge:hover {{"
            f" background: {theme['surface_hover']};"
            f" }}"
        )
        badge.show()
        self._position_browse_mode_badge()

    def eventFilter(self, obj, event):
        if obj is getattr(
            self, "image_tags_widget", None
        ) and event.type() in (
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.Hide,
            QtCore.QEvent.Type.Resize,
        ):
            height = (
                0
                if event.type() == QtCore.QEvent.Type.Hide
                else self.image_tags_widget.height() + 4
            )
            self.right_sidebar.layout().setContentsMargins(0, 0, 0, height)
        if (
            hasattr(self, "_canvas_scroll_area")
            and obj is self._canvas_scroll_area.viewport()
            and event.type() == QtCore.QEvent.Type.Resize
        ):
            self._position_canvas_adjustment()
        return super().eventFilter(obj, event)

    def hide_selected_polygons(self):
        shapes_to_hide = []
        for item in self.label_list:
            if item.shape().selected:
                item.setCheckState(Qt.CheckState.Unchecked)
                item.shape().visible = False
                shapes_to_hide.append(item.shape())

        self.selected_polygon_stack.extend(shapes_to_hide)
        self.canvas.update()
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()

    def show_hidden_polygons(self):
        if self.selected_polygon_stack:
            shape_to_show = self.selected_polygon_stack.pop()
            item = self.label_list.find_item_by_shape(shape_to_show)
            if item:
                item.setCheckState(Qt.CheckState.Checked)
                shape_to_show.visible = True
                self.canvas.update()
                if (
                    hasattr(self, "navigator_dialog")
                    and self.navigator_dialog.isVisible()
                ):
                    self.update_navigator_shapes()
            else:
                logger.warning(
                    f"Shape associated with the hidden item was not found in label list, could not show."
                )

    def get_next_files(self, filename, num_files):
        """Get the next files in the list."""
        if not self.image_list:
            return []
        filenames = []
        current_index = 0
        if filename is not None:
            try:
                current_index = self.fn_to_index[str(filename)]
            except ValueError:
                return []
            filenames.append(filename)
        for _ in range(num_files):
            if current_index + 1 < len(self.image_list):
                filenames.append(self.image_list[current_index + 1])
                current_index += 1
            else:
                filenames.append(self.image_list[-1])
                break
        return filenames

    def inform_next_files(self, filename):
        """Inform the next files to be annotated.
        This list can be used by the user to preload the next files
        or running a background process to process them
        """
        next_files = self.get_next_files(filename, 5)
        if next_files:
            self.next_files_changed.emit(next_files)

    def load_file(self, filename=None):  # noqa: C901
        """Load the specified file, or the last opened file if None."""

        self._cursor_position = None

        # NOTE(jack): Does we need to save the config here?
        # save_config(self._config)

        # For auto labeling, clear the previous marks
        # and inform the next files to be annotated
        # NOTE(jack): this is not needed for now
        # self.clear_auto_labeling_marks()
        # self.inform_next_files(filename)

        # Changing file_list_widget loads file
        if str(filename) in self.fn_to_index and (
            self.file_list_widget.currentRow()
            != self.fn_to_index[str(filename)]
        ):
            self.file_list_widget.setCurrentRow(
                self.fn_to_index[str(filename)]
            )
            self.file_list_widget.update()
            return False

        self.reset_state()
        self.canvas.setEnabled(False)

        if filename is None:
            filename = self.settings.value("filename", "")
        filename = str(filename)
        if not QtCore.QFile.exists(filename):
            self.error_message(
                self.tr("Error opening file"),
                self.tr("No such file: <b>%s</b>") % filename,
            )
            return False

        # assumes same name, but json extension
        label_file = osp.splitext(filename)[0] + ".json"
        image_dir = None
        if self.output_dir:
            image_dir = osp.dirname(filename)
            label_file_without_path = osp.basename(label_file)
            label_file = self.output_dir + "/" + label_file_without_path

        if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
            label_file
        ):
            try:
                self.label_file = LabelFile(
                    label_file,
                    image_dir,
                    image_path=(
                        None if LabelFile.is_label_file(filename) else filename
                    ),
                )
            except LabelFileError as e:
                self.error_message(
                    self.tr("Error opening file"),
                    self.tr(
                        "<p><b>%s</b></p>"
                        "<p>Make sure <i>%s</i> is a valid label file."
                    )
                    % (e, label_file),
                )
                self.status(self.tr("Error reading %s") % label_file)
                return False
            self.image_data = self.label_file.image_data
            self.image_path = self.label_file.resolved_image_path
            self.other_data = self.label_file.other_data
            self.other_data[CHECKED_FIELD] = self._annotation_checked()
            with QtCore.QSignalBlocker(self.shape_text_edit):
                self.shape_text_edit.setPlainText(
                    self.other_data.get("description", "")
                )
        else:
            self.image_data = LabelFile.load_image_file(filename)
            if self.image_data:
                self.image_path = filename
            self.label_file = None
            self.other_data = {CHECKED_FIELD: False}
            with QtCore.QSignalBlocker(self.shape_text_edit):
                self.shape_text_edit.setPlainText("")
        self.shape_text_label.setText(self.tr("Image Description"))
        self.shape_text_edit.setDisabled(False)
        self.canvas.relations = self.other_data.get("relations", [])
        self.operator_gate.baseline = None

        # TODO(jack): icc profile issue warning
        # - qt.gui.icc: fromIccProfile: failed minimal tag size sanity
        # - qt.gui.icc: fromIccProfile: invalid tag offset alignment
        image = utils.img_data_to_qimage(self.image_data, filename)

        if image.isNull():
            formats = [
                f"*{ext}" for ext in utils.get_supported_image_extensions()
            ]
            self.error_message(
                self.tr("Error opening file"),
                self.tr(
                    "<p>Make sure <i>{0}</i> is a valid image file.<br/>"
                    "Supported image formats: {1}</p>"
                ).format(filename, ",".join(formats)),
            )
            self.status(self.tr("Error reading %s") % filename)
            return False
        self.image = image
        self.filename = filename
        has_image_tags = IMAGE_TAGS_FIELD in self.other_data
        self.image_tags_widget.set_tags(
            self.other_data.get(IMAGE_TAGS_FIELD, [])
        )
        self.image_tags_widget.set_interactions_enabled(
            self._operator_edit_allowed()
        )
        if has_image_tags:
            self._auto_show_image_tags()

        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.navigator_dialog.set_image(QtGui.QPixmap.fromImage(image))
            self.update_navigator_shapes()
        if (
            hasattr(self, "_should_restore_navigator")
            and self._should_restore_navigator
        ):
            self._should_restore_navigator = False
            if self.navigator_dialog.isVisible():
                self.update_navigator_viewport()
        if self._config["keep_prev"]:
            prev_shapes = self.canvas.shapes
        self.canvas.load_pixmap(QtGui.QPixmap.fromImage(image))

        # load label flags
        flags = {k: False for k in self.image_flags or []}
        if self.label_file:
            for shape in self.label_file.shapes:
                default_flags = {}
                if self._config["label_flags"]:
                    for pattern, keys in self._config["label_flags"].items():
                        if re.match(pattern, shape.label):
                            for key in keys:
                                default_flags[key] = False
                    shape.flags = {
                        **default_flags,
                        **shape.flags,
                    }
            self.load_shapes(self.label_file.shapes, update_last_label=False)
            self._restore_shape_locks()
            self.image_tags_widget.refresh_colors()
            if self.label_file.flags is not None:
                flags.update(self.label_file.flags)
        self.load_flags(flags)

        # load shapes
        if self._config["keep_prev"] and self.no_shape():
            # Carrying shapes over from the previous image is not an operator
            # edit: keep the attribution of the loaded file untouched.
            self.operator_gate.suppress = True
            try:
                self.load_shapes(
                    prev_shapes, replace=False, update_last_label=False
                )
                self.set_dirty()
            finally:
                self.operator_gate.suppress = False
        else:
            self.set_clean()
        self.operator_gate.baseline = self._content_signature_now()
        self._refresh_attribution_display()
        self.canvas.setEnabled(True)

        saved_pan = QtCore.QPointF(
            self.pan_values.get(self.filename, QtCore.QPointF())
        )
        saved_scroll = {
            orientation: values[self.filename]
            for orientation, values in self.scroll_values.items()
            if self.filename in values
        }
        # set zoom values
        is_initial_load = not self.zoom_values
        if self.filename in self.zoom_values:
            self.zoom_mode = self.zoom_values[self.filename][0]
            self.set_zoom(self.zoom_values[self.filename][1])
        elif is_initial_load or not self._config["keep_prev_scale"]:
            self.adjust_scale(initial=True)
        # set scroll values
        for orientation, value in saved_scroll.items():
            self.set_scroll(orientation, value)
        self.canvas.pan_offset = saved_pan
        self.pan_values[self.filename] = QtCore.QPointF(saved_pan)
        self.constrain_canvas_pan()

        if (
            not self.canvas_adjustment.opacity_pin.isChecked()
            and self.recent_files
            and self.recent_files[0] != self.filename
        ):
            self.canvas_adjustment.opacity_slider.setValue(
                self.canvas_adjustment.OPACITY_DEFAULT
            )

        # set brightness contrast values
        brightness, contrast = self.brightness_contrast_values.get(
            self.filename, (None, None)
        )
        if self._config["keep_prev_brightness"] and self.recent_files:
            brightness, _ = self.brightness_contrast_values.get(
                self.recent_files[0], (None, None)
            )
        if self._config["keep_prev_contrast"] and self.recent_files:
            _, contrast = self.brightness_contrast_values.get(
                self.recent_files[0], (None, None)
            )
        self.brightness_contrast_values[self.filename] = (brightness, contrast)
        # Always refresh the source image used by the inline adjustment panel.
        self.brightness_contrast_processor.update_image(
            utils.img_data_to_pil(self.image_data)
        )
        if brightness is not None or contrast is not None:
            qimage = self.brightness_contrast_processor.adjust(
                brightness if brightness is not None else 50,
                contrast if contrast is not None else 50,
            )
            self.canvas.load_pixmap(
                QtGui.QPixmap.fromImage(qimage), clear_shapes=False
            )
        # Sync the inline adjustment sliders (50 is the neutral value).
        self.canvas_adjustment.set_brightness_contrast(
            brightness if brightness is not None else 50,
            contrast if contrast is not None else 50,
        )

        self.paint_canvas()
        self.add_recent_file(self.filename)
        self.toggle_actions(True)
        self.canvas.setFocus()
        self._sync_annotation_checked_state()
        self.update_thumbnail_display()

        # Reveal the adjustment panel now that an image is loaded.
        self.canvas_adjustment.show()
        self._position_canvas_adjustment()

        if self.compare_view_manager.is_active():
            self.compare_view_manager.load_compare_for_file(self.filename)

        return True

    # QT Overload
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.image_tags_widget.cancel_active_mode():
                event.accept()
                return
            if getattr(self.canvas, "is_brush_mode", False):
                self.canvas.cancel_brush_mode()
            elif self.actions.edit_brush_mode.isChecked():
                self.actions.edit_brush_mode.setChecked(False)
            event.accept()
            return
        super(LabelingWidget, self).keyPressEvent(event)

    def _remember_sidebar_width(self, position, index):
        available = (
            self.sidebar_splitter.width() - self.sidebar_splitter.handleWidth()
        )
        if available > 0 and not self.right_sidebar.isHidden():
            self._sidebar_width_ratio = self.right_sidebar.width() / available

    def _update_ui_density(self):
        window = self.window()
        scale = min(
            1.5, max(1.0, min(window.width() / 1920, window.height() / 1000))
        )
        scale = round(scale * 8) / 8
        if scale != self._ui_scale:
            self._ui_scale = scale
            app = QtWidgets.QApplication.instance()
            app._xanylabeling_ui_scale = scale
            apply_application_font(self._config.get("font_family"))
            self.tools.setUiScale(scale)
            self.files.update_row_height()

        base_width = round(self._sidebar_base_width * scale)
        min_width = round(self._sidebar_min_width * scale)
        self.right_sidebar.setMinimumWidth(min_width)
        self.right_sidebar.setMaximumWidth(base_width * 2)
        available = (
            self.sidebar_splitter.width() - self.sidebar_splitter.handleWidth()
        )
        target = (
            round(available * self._sidebar_width_ratio)
            if self._sidebar_width_ratio is not None
            else base_width
        )
        self._right_sidebar_width = max(
            min_width, min(base_width * 2, target)
        )
        if not self.right_sidebar.isHidden():
            self.sidebar_splitter.setSizes(
                [
                    max(1, available - self._right_sidebar_width),
                    self._right_sidebar_width,
                ]
            )

    def resizeEvent(self, _):
        if hasattr(self, "_ui_resize_timer"):
            self._ui_resize_timer.start(100)
        if (
            self.canvas
            and not self.image.isNull()
            and self.zoom_mode != self.MANUAL_ZOOM
        ):
            self.adjust_scale()
        self.update_thumbnail_pixmap()
        self._position_canvas_adjustment()

    def paint_canvas(self):
        if self.image.isNull():
            return
        self._zoom_animation.stop()
        self.canvas.adjustSize()
        self.canvas.update()
        self.update_navigator_viewport()

    def adjust_scale(self, initial=False):
        self._zoom_animation.stop()
        self.canvas.pan_offset = QtCore.QPointF()
        self.pan_values[self.filename] = QtCore.QPointF()
        value = self.scalers[self.FIT_WINDOW if initial else self.zoom_mode]()
        value = max(
            self.zoom_widget.minimum(),
            min(self.zoom_widget.maximum(), int(100 * value)),
        )
        with QtCore.QSignalBlocker(self.zoom_widget):
            self.zoom_widget.setValue(value)
        self.canvas.scale = 0.01 * self.zoom_widget.value()
        for scroll_bar in self.scroll_bars.values():
            scroll_bar.setValue(0)
        self.paint_canvas()
        self.zoom_values[self.filename] = (self.zoom_mode, value)
        if hasattr(self, "navigator_dialog"):
            self.navigator_dialog.set_zoom_value(value)

    def scale_fit_window(self):
        """Figure out the size of the pixmap to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.central_widget().width() - e
        h1 = self.central_widget().height() - e
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        if h1 <= 0 or w2 <= 0 or h2 <= 0:
            return 1.0
        wh_ratio1 = w1 / h1
        wh_ratio2 = w2 / h2
        return w1 / w2 if wh_ratio2 >= wh_ratio1 else h1 / h2

    def scale_fit_width(self):
        # The epsilon does not seem to work too well here.
        w = self.central_widget().width() - 2.0
        pw = self.canvas.pixmap.width()
        if self.canvas.wheel_navigation_mode == "traditional" and pw > 0:
            area = self._canvas_scroll_area
            available = area.maximumViewportSize()
            w = available.width() - 2.0
            if self.canvas.pixmap.height() * w / pw > available.height():
                w -= area.verticalScrollBar().sizeHint().width()
        return w / pw if pw > 0 else 1.0

    # QT Overload
    def closeEvent(self, event):
        if not self.may_continue():
            event.ignore()
            return
        if self.pointcloud_window is not None:
            if not self.pointcloud_window.can_close():
                event.ignore()
                return
        if event.isAccepted() and self.training_dialog is not None:
            if not self.training_dialog.prepare_for_application_close():
                event.ignore()
                return
            self.training_dialog.close()
        if event.isAccepted() and hasattr(self, "video_classifier_window"):
            if self.video_classifier_window is not None:
                self.video_classifier_window.close()
                if (
                    self.video_classifier_window is not None
                    and self.video_classifier_window.isVisible()
                ):
                    event.ignore()
                    return
        if self.pointcloud_window is not None:
            self.pointcloud_window.close_after_approval()
        self.settings.setValue(
            "filename", self.filename if self.filename else ""
        )
        self.settings.setValue("recent_files", self.recent_files)
        if self.last_open_dir:
            self.settings.setValue("last_open_dir", self.last_open_dir)

        if hasattr(self, "navigator_dialog"):
            navigator_visible = self.navigator_dialog.isVisible()
            self.settings.setValue("navigator/visible", navigator_visible)
            if navigator_visible:
                self.settings.setValue(
                    "navigator/geometry", self.navigator_dialog.saveGeometry()
                )
                self.settings.setValue(
                    "navigator/size", self.navigator_dialog.size()
                )
                self.settings.setValue(
                    "navigator/position", self.navigator_dialog.pos()
                )

        if self._settings_controller is not None:
            self._settings_controller.close_session()

        save_config(self._config)

        if hasattr(self, "async_exif_scanner") and self.async_exif_scanner:
            try:
                self.async_exif_scanner.stop_scan()
            except (RuntimeError, AttributeError):
                pass

        files = getattr(self, "files", None)
        if files is not None:
            try:
                files.shutdown()
            except (RuntimeError, AttributeError):
                pass

        unsubscribe = getattr(self, "_operator_unsubscribe", None)
        if unsubscribe is not None:
            unsubscribe()

        # ask the use for where to save the labels
        # self.settings.setValue('window/geometry', self.saveGeometry())

    # QT Overload
    def dragEnterEvent(self, event):
        extensions = utils.get_supported_image_extensions()
        if event.mimeData().hasUrls():
            items = [i.toLocalFile() for i in event.mimeData().urls()]
            if any(i.lower().endswith(tuple(extensions)) for i in items):
                event.accept()
        else:
            event.ignore()

    # QT Overload
    def dropEvent(self, event):
        if not self.may_continue():
            event.ignore()
            return
        items = [i.toLocalFile() for i in event.mimeData().urls()]
        self.import_dropped_image_files(items)

    def load_recent(self, filename):
        if self.may_continue():
            self.load_file(filename)

    def load_recent_dir(self, dirpath):
        self.import_image_folder(dirpath)

    def open_prev_unchecked_image(self):
        if (
            not self.may_continue()
            or len(self.image_list) <= 0
            or self.filename is None
        ):
            return

        current_index = self.fn_to_index[str(self.filename)]
        for i in range(current_index - 1, -1, -1):
            if not self._file_item_annotation_checked(
                self.file_list_widget.item(i)
            ):
                filename = self.image_list[i]
                if filename:
                    self.load_file(filename)
                break

    def open_next_unchecked_image(self, _value=False):
        if (
            not self.may_continue()
            or len(self.image_list) <= 0
            or self.filename is None
        ):
            return

        current_index = self.fn_to_index[str(self.filename)]
        for i in range(current_index + 1, len(self.image_list)):
            if not self._file_item_annotation_checked(
                self.file_list_widget.item(i)
            ):
                filename = self.image_list[i]
                if filename:
                    self.load_file(filename)
                break

    def open_prev_image(self, _value=False):
        if not self.may_continue():
            return
        if self.file_list_widget.count() <= 0:
            return
        if self.filename is None:
            return
        current_index = self.fn_to_index[str(self.filename)]
        if current_index - 1 >= 0:
            filename = self._file_path_at(current_index - 1)
            if filename:
                self.load_file(filename)

    def open_next_image(self, _value=False, load=True):
        if not self.may_continue():
            return
        count = self.file_list_widget.count()
        if count <= 0:
            return
        filename = None
        if self.filename is None:
            filename = self._file_path_at(0)
        else:
            current_index = self.fn_to_index[str(self.filename)]
            if current_index + 1 < count:
                filename = self._file_path_at(current_index + 1)
            else:
                filename = self._file_path_at(count - 1)
        self.filename = filename
        if self.filename and load:
            self.load_file(self.filename)

    # File
    def open_file(self, _value=False):
        if not self.may_continue():
            return
        path = osp.dirname(str(self.filename)) if self.filename else "."
        formats = [f"*{ext}" for ext in utils.get_supported_image_extensions()]
        filters = self.tr("Image & Label files (%s)") % " ".join(
            formats + [f"*{LabelFile.suffix}"]
        )
        file_dialog = FileDialogPreview(self)
        file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        file_dialog.setNameFilter(filters)
        file_dialog.setWindowTitle(
            self.tr("%s - Choose Image or Label file") % __appname__,
        )
        file_dialog.setWindowFilePath(path)
        file_dialog.setViewMode(QtWidgets.QFileDialog.ViewMode.Detail)
        if file_dialog.exec():
            filename = file_dialog.selectedFiles()[0]
            if filename:
                self._clear_file_list()
                self.load_file(filename)

    def change_output_dir_dialog(self, _value=False):
        default_output_dir = self.output_dir
        if default_output_dir is None and self.filename:
            default_output_dir = osp.dirname(self.filename)
        if default_output_dir is None:
            default_output_dir = self.current_path()

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("%s - Save/Load Annotations in Directory") % __appname__,
            default_output_dir,
            QtWidgets.QFileDialog.Option.ShowDirsOnly
            | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
        )
        output_dir = str(output_dir)

        if not output_dir:
            return

        self.output_dir = output_dir

        self.statusBar().showMessage(
            self.tr("%s . Annotations will be saved/loaded in %s")
            % ("Change Annotations Dir", self.output_dir)
        )
        self.statusBar().show()

        current_filename = self.filename
        self.import_image_folder(self.last_open_dir, load=False)

        if current_filename in self.image_list:
            # retain currently selected file
            self.file_list_widget.setCurrentRow(
                self.fn_to_index[str(current_filename)]
            )
            self.file_list_widget.repaint()

    def save_file(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        if self.label_file:
            # DL20180323 - overwrite when in directory
            self._save_file(self.label_file.filename)
        elif self.output_file:
            self._save_file(self.output_file)
            self.close()
        else:
            self._save_file(self.save_file_dialog())

    def save_file_as(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._save_file(self.save_file_dialog())

    def save_file_dialog(self):
        caption = self.tr("%s - Choose File") % __appname__
        filters = self.tr("Label files (*%s)") % LabelFile.suffix
        if self.output_dir:
            file_dialog = QtWidgets.QFileDialog(
                self, caption, self.output_dir, filters
            )
        else:
            file_dialog = QtWidgets.QFileDialog(
                self, caption, self.current_path(), filters
            )
        file_dialog.setDefaultSuffix(LabelFile.suffix[1:])
        file_dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setOption(
            QtWidgets.QFileDialog.Option.DontConfirmOverwrite, False
        )
        file_dialog.setOption(
            QtWidgets.QFileDialog.Option.DontUseNativeDialog, False
        )
        basename = osp.basename(osp.splitext(self.filename)[0])
        if self.output_dir:
            default_labelfile_name = osp.join(
                self.output_dir, basename + LabelFile.suffix
            )
        else:
            default_labelfile_name = osp.join(
                self.current_path(), basename + LabelFile.suffix
            )
        filename = file_dialog.getSaveFileName(
            self,
            self.tr("Choose File"),
            default_labelfile_name,
            self.tr("Label files (*%s)") % LabelFile.suffix,
        )
        if isinstance(filename, tuple):
            filename, _ = filename
        return filename

    def _save_file(self, filename):
        if filename and self.save_labels(filename):
            self.add_recent_file(filename)
            self.set_clean()

    def close_file(self, _value=False):
        if not self.may_continue():
            return
        self.reset_state()
        self.set_clean()
        self.toggle_actions(False)
        self.canvas.setEnabled(False)
        self.actions.save_as.setEnabled(False)

    def toggle_compare_view(self):
        """Toggle the compare view on or off."""
        if self.compare_view_manager.is_active():
            self.close_compare_view()
            return

        if not self.filename:
            self.status(self.tr("Please open an image first"), 3000)
            return

        compare_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Compare Image Directory"),
            "",
            QtWidgets.QFileDialog.Option.ShowDirsOnly
            | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
        )
        if not compare_dir:
            return

        if not self.compare_view_manager.set_compare_directory(compare_dir):
            self.status(self.tr("Invalid compare directory"), 3000)
            return

        self.compare_view_manager.load_compare_for_file(self.filename)
        self.compare_view_slider.show_slider()

    def close_compare_view(self, confirm=True):
        """Close the compare view."""
        if confirm:
            reply = QtWidgets.QMessageBox.question(
                self,
                self.tr("Close Compare View"),
                self.tr("Are you sure you want to close the compare view?"),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.compare_view_manager.close()
        self.compare_view_slider.hide_slider()

    def get_label_file(self):
        if self.label_file:
            return self.label_file.filename
        base = self.image_path if self.image_path else self.filename
        if base.lower().endswith(".json"):
            return base
        lf = osp.splitext(base)[0] + ".json"
        if self.output_dir:
            lf = osp.join(self.output_dir, osp.basename(lf))
        return lf

    def get_image_file(self):
        if not self.filename.lower().endswith(".json"):
            image_file = self.filename
        else:
            image_file = self.image_path

        return image_file

    def delete_file(self):
        mb = QtWidgets.QMessageBox
        if self._config.get("keep_prev", False):
            mb.warning(
                self,
                self.tr("Attention"),
                self.tr(
                    "Please disable 'Keep Previous Annotation' before deleting the label file."
                ),
                mb.StandardButton.Ok,
            )
            return

        msg = self.tr(
            "You are about to permanently delete this label file, "
            "proceed anyway?"
        )
        answer = mb.warning(
            self,
            self.tr("Attention"),
            msg,
            mb.StandardButton.Yes | mb.StandardButton.No,
        )
        if answer != mb.StandardButton.Yes:
            return

        label_file = self.get_label_file()
        if osp.exists(label_file):
            os.remove(label_file)
            logger.info(f"Label file is removed: {label_file}")

            item = self.file_list_widget.currentItem()
            item.setCheckState(Qt.CheckState.Unchecked)
            self._set_file_item_checked(item, False)

            filename = self.filename
            self.reset_state()
            self.filename = filename
            if self.filename:
                self.load_file(self.filename)

    def delete_image_file(self):
        if len(self.image_list) < 2:
            return

        mb = QtWidgets.QMessageBox
        if self._config.get("keep_prev", False):
            mb.warning(
                self,
                self.tr("Attention"),
                self.tr(
                    "Please disable 'Keep Previous Annotation' before deleting the image file."
                ),
                mb.StandardButton.Ok,
            )
            return

        msg = self.tr(
            "You are about to permanently delete this image file, "
            "proceed anyway?"
        )
        answer = mb.warning(
            self,
            self.tr("Attention"),
            msg,
            mb.StandardButton.Yes | mb.StandardButton.No,
        )
        if answer != mb.StandardButton.Yes:
            return

        image_file = self.get_image_file()
        if osp.exists(image_file):
            image_path, image_name = osp.split(image_file)
            save_path = osp.join(image_path, "..", "_delete_")
            os.makedirs(save_path, exist_ok=True)
            save_file = osp.join(save_path, image_name)
            shutil.move(image_file, save_file)
            logger.info(f"Image file is moved to: {osp.realpath(save_file)}")

            label_dir_path = osp.dirname(self.filename)
            if self.output_dir:
                label_dir_path = self.output_dir
            label_name = osp.splitext(image_name)[0] + ".json"
            label_file = osp.join(label_dir_path, label_name)
            if not osp.exists(label_file):
                label_file = osp.join(osp.dirname(image_file), label_name)
            if osp.exists(label_file):
                os.remove(label_file)
                logger.info(f"Label file is removed: {image_file}")

            filename = None
            if self.filename is None:
                filename = self.image_list[0]
            else:
                current_index = self.fn_to_index[str(self.filename)]
                if current_index + 1 < len(self.image_list):
                    filename = self.image_list[current_index + 1]
                else:
                    filename = self.image_list[0]

            self.reset_state()
            if osp.isfile(image_path):
                image_path = osp.dirname(image_path)
            self.import_image_folder(image_path)

            self.filename = filename
            if self.filename:
                self.load_file(self.filename)

    # Message Dialogs. #
    def has_labels(self):
        if self.no_shape():
            self.error_message(
                "No objects labeled",
                "You must label at least one object to save the file.",
            )
            return False
        return True

    def has_label_file(self):
        if self.filename is None:
            return False

        label_file = self.get_label_file()
        return osp.exists(label_file)

    def may_continue(self):
        self.image_tags_widget.finish_for_image_change()
        if not self.dirty:
            return True
        mb = QtWidgets.QMessageBox
        msg = self.tr(
            f'Save annotations to "{self.filename!r}" before closing?'
        )
        answer = mb.question(
            self,
            self.tr("Save annotations?"),
            msg,
            mb.StandardButton.Save
            | mb.StandardButton.Discard
            | mb.StandardButton.Cancel,
            mb.StandardButton.Save,
        )
        if answer == mb.StandardButton.Discard:
            return True
        if answer == mb.StandardButton.Save:
            self.save_file()
            return not self.dirty
        # answer == mb.Cancel
        return False

    def error_message(self, title, message):
        return QtWidgets.QMessageBox.critical(
            self, title, f"<p><b>{title}</b></p>{message}"
        )

    def current_path(self):
        return osp.dirname(str(self.filename)) if self.filename else "."

    def toggle_visibility_shapes(self, value):
        for index, item in enumerate(self.label_list):
            item.setCheckState(
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
            )
            self.label_list[index].shape().visible = True if value else False
        self._config["show_shapes"] = value
        self._update_select_toggle_button_tooltip()
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()

    def remove_selected_point(self):
        self.canvas.remove_selected_point()
        self.canvas.update()
        if self.canvas.h_shape is not None and not self.canvas.h_shape.points:
            self.canvas.delete_shape(self.canvas.h_shape)
            self.remove_labels([self.canvas.h_shape])
            self.set_dirty()
            if self.no_shape():
                for action in self.actions.on_shapes_present:
                    action.setEnabled(False)

    def delete_selected_shape(self):
        group_shapes = self.canvas._active_group_shapes()
        if group_shapes:
            answer = QtWidgets.QMessageBox.warning(
                self,
                self.tr("Delete Group"),
                self.tr(
                    "Deleting this group will remove %d shapes. "
                    "This action cannot be undone. Do you want to continue?"
                )
                % len(group_shapes),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.remove_labels(self.canvas.delete_selected())
        self.shape_selection_changed(self.canvas.selected_shapes)
        self.set_dirty()
        if self.no_shape():
            for action in self.actions.on_shapes_present:
                action.setEnabled(False)

    def copy_shape(self):
        self.canvas.end_move(copy=True)
        self.label_list.setUpdatesEnabled(False)
        try:
            for shape in self.canvas.selected_shapes:
                self.add_label(shape, refresh_filters=False)
        finally:
            self.label_list.setUpdatesEnabled(True)
        if self.canvas.selected_shapes:
            self._refresh_shape_filters()
        self.label_list.clearSelection()
        self.set_dirty()

    def move_shape(self):
        self.canvas.end_move(copy=False)
        self.set_dirty()

    def import_files_dialog(self):
        if not self.may_continue():
            return
        default_dir = self.last_open_dir
        if not default_dir:
            default_dir = (
                osp.dirname(str(self.filename)) if self.filename else "."
            )
        formats = [
            f"*{ext}" for ext in utils.get_supported_image_extensions()
        ]
        files, _selected_filter = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            self.tr("%s - Import Files") % __appname__,
            default_dir,
            self.tr("Image files (%s)") % " ".join(formats),
        )
        files = [str(file) for file in files if file]
        if files:
            self.import_dropped_image_files(files)

    def open_folder_dialog(self, _value=False, dirpath=None):
        if not self.may_continue():
            return

        default_open_dir_path = dirpath if dirpath else "."
        if self.last_open_dir and osp.exists(self.last_open_dir):
            default_open_dir_path = self.last_open_dir
        else:
            default_open_dir_path = (
                osp.dirname(self.filename) if self.filename else "."
            )

        target_dir_path = str(
            QtWidgets.QFileDialog.getExistingDirectory(
                self,
                self.tr("%s - Open Directory") % __appname__,
                default_open_dir_path,
                QtWidgets.QFileDialog.Option.ShowDirsOnly
                | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
            )
        )
        self.import_image_folder(target_dir_path)

    @property
    def image_list(self):
        return [
            self._file_path_at(row)
            for row in range(self.file_list_widget.rowCount())
        ]

    def _clear_file_list(self):
        self.files.clear()


    def import_dropped_image_files(self, image_files):
        extensions = utils.get_supported_image_extensions()

        self.filename = None
        valid_files = []
        rows = []
        for file in image_files:
            if file in self.image_list or not file.lower().endswith(
                tuple(extensions)
            ):
                continue
            valid_files.append(file)
            label_file = osp.splitext(file)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.output_dir + "/" + label_file_without_path
            rows.append((file, label_file))

        self.files.update_import_times(valid_files)
        for file, label_file in rows:
            self.files.append_row(file, label_file)
        self.file_list_widget.fill_name_column()

        if len(self.image_list) > 1:
            self.actions.open_next_image.setEnabled(True)
            self.actions.open_prev_image.setEnabled(True)
            self.actions.open_next_unchecked_image.setEnabled(True)
            self.actions.open_prev_unchecked_image.setEnabled(True)

        self.toggle_actions(True)
        self.open_next_image()

        if valid_files and self._config.get("exif_scan_enabled", True):
            self.async_exif_scanner.start_scan(valid_files)

    def import_image_folder(self, dirpath, pattern=None, load=True):
        if not self.may_continue() or not dirpath:
            return

        if self.compare_view_manager.is_active():
            self.close_compare_view(confirm=False)

        self.last_open_dir = dirpath
        self.filename = None
        self.update_browse_actions()
        self._clear_file_list()

        files_on_disk = list(utils.scan_all_images(dirpath))
        if pattern:
            query = parse_search_query(pattern)
            image_files = filter_image_files(
                files_on_disk, query, self.output_dir
            )
        else:
            image_files = files_on_disk

        self.files.update_import_times(image_files)
        for filename in image_files:
            label_file = osp.splitext(filename)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.output_dir + "/" + label_file_without_path
            self.files.append_row(filename, label_file)
        self.file_list_widget.fill_name_column()

        self.actions.open_next_image.setEnabled(True)
        self.actions.open_prev_image.setEnabled(True)
        self.actions.open_next_unchecked_image.setEnabled(True)
        self.actions.open_prev_unchecked_image.setEnabled(True)
        self.toggle_actions(True)
        self.open_next_image(load=load)

        if image_files and self._config.get("exif_scan_enabled", True):
            self.async_exif_scanner.start_scan(image_files)
        self._refresh_statistics_if_visible()

    # -- auto labeling handoff -------------------------------------------
    # The merge/finish rules live in ``auto_labeling_handoff.py``; the widget
    # stays the signal target and delegates the work.
    def toggle_auto_labeling_widget(self):
        return self.auto_labeling_handoff.toggle_auto_labeling_widget()

    def new_shapes_from_auto_labeling(self, auto_labeling_result):
        return self.auto_labeling_handoff.new_shapes_from_auto_labeling(
            auto_labeling_result
        )

    def clear_auto_labeling_marks(self):
        return self.auto_labeling_handoff.clear_auto_labeling_marks()

    def find_last_label(self):
        return self.auto_labeling_handoff.find_last_label()

    def find_last_gid(self):
        return self.auto_labeling_handoff.find_last_gid()

    def set_cache_auto_label(self):
        return self.auto_labeling_handoff.set_cache_auto_label()

    def finish_auto_labeling_object(self):
        return self.auto_labeling_handoff.finish_auto_labeling_object()

    def shape_text_changed(self):
        description = self.shape_text_edit.toPlainText()
        if self.canvas.current is not None:
            self.canvas.current.description = description
        elif self.canvas.editing() and len(self.canvas.selected_shapes) == 1:
            self.canvas.selected_shapes[0].description = description
        else:
            self.other_data["description"] = description
        self.set_dirty()

    def set_text_editing(self, enable):
        """Set text editing."""
        if enable:
            # Enable text editing and set shape text from selected shape
            if len(self.canvas.selected_shapes) == 1:
                self.shape_text_label.setText(self.tr("Object Description"))
                with QtCore.QSignalBlocker(self.shape_text_edit):
                    self.shape_text_edit.setPlainText(
                        self.canvas.selected_shapes[0].description or ""
                    )
            else:
                self.shape_text_label.setText(self.tr("Image Description"))
                with QtCore.QSignalBlocker(self.shape_text_edit):
                    self.shape_text_edit.setPlainText(
                        self.other_data.get("description", "")
                    )
            self.shape_text_edit.setDisabled(False)
        else:
            self.shape_text_edit.setDisabled(True)
            self.shape_text_label.setText(self.tr("Description"))
            with QtCore.QSignalBlocker(self.shape_text_edit):
                self.shape_text_edit.setPlainText("")

    def group_selected_shapes(self):
        self.canvas.group_selected_shapes()
        self.set_dirty()
        self.load_file(self.filename)

    def ungroup_selected_shapes(self):
        self.canvas.ungroup_selected_shapes()
        self.set_dirty()
        self.load_file(self.filename)

    def update_thumbnail_pixmap(self):
        if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
            width = self.thumbnail_image_label.width()
            if width > 0:
                self.thumbnail_image_label.setPixmap(
                    self.thumbnail_pixmap.scaledToWidth(
                        width,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def update_thumbnail_display(self):
        self.thumbnail_pixmap = None
        self.thumbnail_image_label.clear()
        self.thumbnail_container.hide()

        model_config = (
            self.auto_labeling_widget.model_manager.loaded_model_config
        )
        if model_config and model_config.get("type") == "remote_server":
            thumbnail_path = model_config["model"].get_preview_path(
                self.filename
            )
            if thumbnail_path:
                self.thumbnail_pixmap = QtGui.QPixmap(thumbnail_path)
                if not self.thumbnail_pixmap.isNull():
                    self.thumbnail_container.show()
                    self.update_thumbnail_pixmap()
            return
        supported_model_list = list(_THUMBNAIL_RENDER_MODELS.keys())
        if not (
            model_config
            and model_config.get("type") in supported_model_list
            and self.image_list
        ):
            return

        try:
            image_dir = osp.dirname(self.filename)
            parent_dir = osp.dirname(image_dir)
            base_name = osp.splitext(osp.basename(self.filename))[0]
            save_dir, _thumbnail_file_ext = _THUMBNAIL_RENDER_MODELS[
                model_config["type"]
            ]
            thumbnail_dir = osp.join(parent_dir, save_dir)
            thumbnail_path = osp.join(
                thumbnail_dir, base_name + _thumbnail_file_ext
            )
            if not osp.exists(thumbnail_path):
                return

            self.thumbnail_pixmap = QtGui.QPixmap(thumbnail_path)
            if not self.thumbnail_pixmap.isNull():
                self.thumbnail_container.show()
                self.update_thumbnail_pixmap()

        except Exception as e:
            logger.error(f"Failed to load thumbnail image: {str(e)}")
