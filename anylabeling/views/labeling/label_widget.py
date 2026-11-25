import functools
import math
import os
import os.path as osp
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import QLabel, QLineEdit

from anylabeling.services.auto_labeling import _THUMBNAIL_RENDER_MODELS
from anylabeling.services.identity import get_operator_service

from ...config import get_config, save_config
from . import utils
from .actions.builder import build_actions
from .actions.menus import build_menus
from .actions.toolbar import ToolbarPolicy
from .annotation_editor import AnnotationEditor
from .appearance import AppearanceController
from .auto_labeling_handoff import AutoLabelingHandoff
from .canvas_navigation import CanvasNavigation
from .draw_modes import DrawModeController
from .file_list import FileListController
from .file_session import FileSession
from .label_filters import LabelFilterController
from .label_loop import LabelLoop
from .label_loop import _find_next_label_loop_shape  # noqa: F401 (re-export)
from .logger import logger
from .object_editor import ObjectEditor
from .operator import OperatorGate
from .operator import (  # noqa: F401 (re-exported gate contract)
    OPERATOR_MODE_ACTIONS,
    OPERATOR_REQUIRED_ACTIONS,
)
from .relations import RelationController
from .right_sidebar import RightSidebarTabs
from .schema import IMAGE_TAGS_FIELD
from .settings.runtime_applier import SettingsRuntimeApplier
from .shape import Shape
from .shape_commands import ShapeCommands
from .special_workspaces import SpecialWorkspaces
from .status import DocumentStatus
from .utils.label_text import (  # noqa: F401 (re-exported helpers)
    format_label_list_text as _format_label_list_text,
    measure_text_width as _measure_text_width,
)
from .utils.image_tags import normalize_image_tag, normalize_image_tags
from .utils.file_search import escape_query_value
from .utils.qt import apply_application_font, new_icon_path
from .utils.tag_library import TagCatalog
from .utils.theme import get_theme
from .widgets import (
    BrightnessContrastProcessor,
    GroupIDFilterComboBox,
    LabelDialog,
    LabelFilterComboBox,
    LabelListWidget,
    NavigatorDialog,
    Popup,
    SearchBar,
    ToolBar,
    UniqueLabelQListWidget,
    ZoomWidget,
)
from .widgets.attributes_panel import AttributesPanel
from .widgets.description_editor import DescriptionEditor
from .widgets.label_list_widget import set_item_locked
from .widgets.workspace import (
    build_canvas_view,
    build_instruction_bar,
    build_operator_bar,
    build_workspace,
    restore_session_state,
)

# Backwards-compatible alias for the label manager / tests.
_set_label_list_item_lock = set_item_locked




class LabelingWidget(LabelDialog):
    """The main widget for labeling images"""

    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = 0, 1, 2
    next_files_changed = QtCore.pyqtSignal(list)
    dataset_changed = QtCore.pyqtSignal()

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
        # Tag library cache: JSON mode keeps a per-file tag map; DB mode
        # re-queries ``DatasetRepository.tag_counts()`` when marked dirty.
        self._tag_catalog = None
        self._tag_library_entries = []
        self._tag_library_loaded = False
        self._tag_library_dirty = True
        #: All images imported from the current folder (not just the rows that
        #: match the search); the library intentionally keeps this vocabulary
        #: stable while the file list is filtered.
        self._tag_library_all_paths = None
        # Dataset database mode (T3/P1).  ``None`` means the classic JSON
        # workflow; ``dataset_repository`` switches file listing/load/save to
        # the SQLite store.
        self.dataset_database = None
        self.dataset_repository = None
        self.dataset_root = None
        self.dataset_image_id = None
        self._cli_output_dir = output_dir
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
                "- Attributes: label::xxx, tags::xxx, editor::张三,\n"
                "  split::train, shape::1, type::xxx, gid::0, difficult::1,\n"
                "  score::[0,0.5], description::1, review::pending\n"
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
        return AppearanceController(self).show_shortcuts()

    def _configure_toggle_button(self, button, style, tooltip):
        return ToolbarPolicy(self)._configure_toggle_button(button, style, tooltip)

    def _panel_toggle_icon(self, kind, visible):
        return ToolbarPolicy(self)._panel_toggle_icon(kind, visible)

    def _sync_panel_toggle_icons(self):
        return ToolbarPolicy(self)._sync_panel_toggle_icons()

    def toggle_right_sidebar(self):
        return ToolbarPolicy(self).toggle_right_sidebar()

    def restore_navigator_state(self) -> None:
        return CanvasNavigation(self).restore_navigator_state()

    def _navigator_close_event(self, event: QtGui.QCloseEvent) -> None:
        return CanvasNavigation(self)._navigator_close_event(event)

    def set_language(self, language):
        return AppearanceController(self).set_language(language)

    def _on_theme_changed(self, mode: str) -> None:
        return AppearanceController(self)._on_theme_changed(mode)

    def get_labeling_instruction(self):
        return AppearanceController(self).get_labeling_instruction()

    def _should_show_space_pan_tip(self):
        return AppearanceController(self)._should_show_space_pan_tip()

    def _space_pan_tip_message(self):
        return AppearanceController(self)._space_pan_tip_message()

    def update_space_pan_tip(self):
        return AppearanceController(self).update_space_pan_tip()

    def update_labeling_instruction(self):
        return AppearanceController(self).update_labeling_instruction()

    def _format_instruction_shortcut(self, value):
        return AppearanceController(self)._format_instruction_shortcut(value)

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
        return DocumentStatus(self).set_dirty()

    def _on_image_tags_changed(self, tags):
        if not self.image_path:
            return
        self.other_data[IMAGE_TAGS_FIELD] = list(tags)
        self.set_dirty()

    # -- tag library -----------------------------------------------------
    # The "Image Attributes" tab lists the tags already used by the current
    # file list, so a tag can be added with one click.  JSON mode caches the
    # per-file tags (``TagCatalog``) to avoid re-reading thousands of files;
    # DB mode asks ``DatasetRepository.tag_counts()``.
    def _tag_library_source(self):
        repository = getattr(self, "dataset_repository", None)
        if repository is not None:
            # The library is a dataset-wide vocabulary; a search that narrows
            # the file table must not change which tags can be added.
            return [
                (row["tag"], int(row["image_count"]))
                for row in repository.tag_counts()
            ]
        if self._tag_catalog is None:
            self._tag_catalog = TagCatalog()
        files = getattr(self, "files", None)
        if files is None:
            return []
        paths = getattr(self, "_tag_library_all_paths", None)
        if not paths:
            paths = [
                files.path_at(row)
                for row in range(files.table.rowCount())
            ]
        return self._tag_catalog.load(paths, files.label_file_for)

    def _refresh_tag_library(self):
        widget = getattr(self, "tag_library_widget", None)
        if widget is None:
            return
        if self._tag_library_dirty or not self._tag_library_loaded:
            try:
                self._tag_library_entries = self._tag_library_source()
            except Exception:  # noqa: BLE001 - never break the tab
                logger.warning(
                    "Failed to refresh the tag library", exc_info=True
                )
                self._tag_library_entries = []
            self._tag_library_loaded = True
            self._tag_library_dirty = False
        current = normalize_image_tags(
            list(self.other_data.get(IMAGE_TAGS_FIELD) or [])
        )
        widget.set_entries(self._tag_library_entries, current)

    def _refresh_tag_library_if_visible(self):
        widget = getattr(self, "tag_library_widget", None)
        tabs = getattr(self, "right_tabs", None)
        if widget is None or tabs is None:
            return
        page = tabs.currentWidget()
        if page is widget or (page is not None and page.isAncestorOf(widget)):
            self._refresh_tag_library()

    def _invalidate_tag_library(self):
        self._tag_library_dirty = True
        self._refresh_tag_library_if_visible()

    def _on_tags_persisted(self):
        """Update the library cache after a successful annotation save."""
        tags = normalize_image_tags(
            list(self.other_data.get(IMAGE_TAGS_FIELD) or [])
        )
        if self._tag_catalog is not None and self.image_path:
            self._tag_catalog.update(self.image_path, tags)
        self._tag_library_dirty = True
        self._refresh_tag_library_if_visible()

    def _on_batch_tags_persisted(self, tags_by_path):
        if self._tag_catalog is not None:
            for path, tags in tags_by_path.items():
                self._tag_catalog.update(path, tags)
        self._tag_library_dirty = True
        self._refresh_tag_library_if_visible()

    def _search_tag_from_library(self, tag):
        """Turn a tag-library lookup into ``tags::`` in the search box."""
        tag = str(tag or "").strip()
        if not tag:
            return
        self.file_search.setText("tags::" + escape_query_value(tag))
        self.file_search_changed()

    def _on_tag_library_tag_clicked(self, tag):
        tag = normalize_image_tag(tag)
        if not tag or not self.image_path:
            return
        if not self._ensure_operator():
            return
        current = normalize_image_tags(
            list(self.other_data.get(IMAGE_TAGS_FIELD) or [])
        )
        if tag in current:
            return
        tags = current + [tag]
        self.other_data[IMAGE_TAGS_FIELD] = tags
        self.image_tags_widget.set_tags(tags)
        label_file = self.files.label_file_for(self.image_path)
        # "Click = write": the save path stamps author/modified_at through
        # the attribution gate, so the tag is on disk immediately.
        if self._save_file(label_file):
            self.status(self.tr("Tag added: %s") % tag)
        else:
            self.status(self.tr("Failed to save the new tag"))
            self._refresh_tag_library_if_visible()

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

    def show_image_tags_editor(self):
        return AppearanceController(self).show_image_tags_editor()

    def _get_rgb_by_image_tag(self, label):
        return AppearanceController(self)._get_rgb_by_image_tag(label)

    def _document_status_text(self):
        return DocumentStatus(self)._document_status_text()

    def _refresh_document_status(self):
        return DocumentStatus(self)._refresh_document_status()

    def _on_canvas_mouse_moved(self, x, y):
        return DocumentStatus(self)._on_canvas_mouse_moved(x, y)

    def _window_title(self):
        return DocumentStatus(self)._window_title()

    def update_progress_title(self):
        return DocumentStatus(self).update_progress_title()

    def set_clean(self):
        return DocumentStatus(self).set_clean()

    def get_image_progress_info(self):
        return DocumentStatus(self).get_image_progress_info()

    def toggle_actions(self, value=True):
        return DocumentStatus(self).toggle_actions(value)

    def update_browse_actions(self):
        return DocumentStatus(self).update_browse_actions()

    def jump_images(self, offset):
        if not self.may_continue():
            return
        index = self.fn_to_index.get(str(self.filename), -1)
        target = index + offset
        if index >= 0 and 0 <= target < self.file_list_widget.count():
            self.load_file(self.file_list_widget.item(target).text())

    def queue_event(self, function):
        return DocumentStatus(self).queue_event(function)

    def status(self, message, delay=5000):
        return DocumentStatus(self).status(message, delay)

    @staticmethod
    def _shape_lock_key(shape):
        return ObjectEditor._shape_lock_key(shape)

    def _remember_shape_locks(self):
        return ObjectEditor(self)._remember_shape_locks()

    def _restore_shape_locks(self):
        return ObjectEditor(self)._restore_shape_locks()

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
        return ObjectEditor(self).toggle_select_all()

    def _has_active_shape_filter(self):
        return ObjectEditor(self)._has_active_shape_filter()

    def _update_select_toggle_button_tooltip(self):
        return ObjectEditor(self)._update_select_toggle_button_tooltip()

    def _are_all_shapes_visible(self):
        return ObjectEditor(self)._are_all_shapes_visible()

    def _set_all_objects_visibility(self, visible):
        return ObjectEditor(self)._set_all_objects_visibility(visible)

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
        return ShapeCommands(self).undo_shape_edit()

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
        return ShapeCommands(self).copy_shape_coordinates()

    def union_selection(self):
        return ShapeCommands(self).union_selection()

    # Trainer
    def start_training(self, mode):
        return SpecialWorkspaces(self).start_training(mode)

    def on_training_dialog_destroyed(self, _dialog=None):
        return SpecialWorkspaces(self).on_training_dialog_destroyed(_dialog)

    # Tools
    def overview(self):
        return SpecialWorkspaces(self).overview()

    def digit_shortcut_manager(self):
        return SpecialWorkspaces(self).digit_shortcut_manager()

    def label_manager(self):
        return SpecialWorkspaces(self).label_manager()

    def gid_manager(self):
        return SpecialWorkspaces(self).gid_manager()

    def shape_manager(self):
        return SpecialWorkspaces(self).shape_manager()

    def open_chatbot(self):
        return SpecialWorkspaces(self).open_chatbot()

    def open_vqa(self):
        return SpecialWorkspaces(self).open_vqa()

    def open_pointcloud(self):
        return SpecialWorkspaces(self).open_pointcloud()

    def on_pointcloud_window_destroyed(self, _window=None):
        return SpecialWorkspaces(self).on_pointcloud_window_destroyed(_window)

    def open_paddleocr(self):
        return SpecialWorkspaces(self).open_paddleocr()

    def open_video_classifier(self):
        return SpecialWorkspaces(self).open_video_classifier()

    def open_image_classifier(self):
        return SpecialWorkspaces(self).open_image_classifier()

    def open_classifier(self):
        return SpecialWorkspaces(self).open_classifier()

    # Help
    def documentation(self):
        return SpecialWorkspaces(self).documentation()

    def sponsor(self):
        return SpecialWorkspaces(self).sponsor()

    def about(self):
        return SpecialWorkspaces(self).about()

    def _reset_label_loop(self):
        return LabelLoop(self)._reset_label_loop()

    def _show_label_loop_popup(self, text):
        return LabelLoop(self)._show_label_loop_popup(text)

    def loop_thru_labels(self):
        return LabelLoop(self).loop_thru_labels()

    def loop_select_labels(self):
        return LabelLoop(self).loop_select_labels()

    def copy_to_clipboard(self, text):
        return LabelLoop(self).copy_to_clipboard(text)

    # General
    def toggle_drawing_sensitive(self, drawing=True):
        return DrawModeController(self).toggle_drawing_sensitive(drawing)

    def create_digit_mode(self, digit_num):
        return DrawModeController(self).create_digit_mode(digit_num)

    def toggle_draw_mode(self, edit=True, create_mode='rectangle', disable_auto_labeling=True, preserve_brush_mode=False):
        return DrawModeController(self).toggle_draw_mode(edit, create_mode, disable_auto_labeling, preserve_brush_mode)

    def toggle_brush_polygon_mode(self):
        return DrawModeController(self).toggle_brush_polygon_mode()

    def toggle_magic_wand_mode(self):
        return DrawModeController(self).toggle_magic_wand_mode()

    def set_edit_mode(self):
        return DrawModeController(self).set_edit_mode()

    def _enter_edit_mode_from_toolbar(self):
        return DrawModeController(self)._enter_edit_mode_from_toolbar()

    def toggle_brush_mode(self, checked: bool) -> None:
        return DrawModeController(self).toggle_brush_mode(checked)

    def on_brush_mode_changed(self, enabled: bool) -> None:
        return DrawModeController(self).on_brush_mode_changed(enabled)

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
        return ObjectEditor(self).refresh_shape_lock_action()

    def toggle_label_items_lock(self, items):
        return ObjectEditor(self).toggle_label_items_lock(items)

    def refresh_panel_controls(self):
        return ObjectEditor(self).refresh_panel_controls()

    def toggle_all_labels_visibility(self):
        return ObjectEditor(self).toggle_all_labels_visibility()

    def toggle_all_shapes_visibility(self):
        return ObjectEditor(self).toggle_all_shapes_visibility()

    def toggle_all_labels_lock(self):
        return ObjectEditor(self).toggle_all_labels_lock()

    def toggle_all_shapes_lock(self):
        return ObjectEditor(self).toggle_all_shapes_lock()

    def toggle_unique_label_items_lock(self, items, locked=None):
        return ObjectEditor(self).toggle_unique_label_items_lock(items, locked)

    def toggle_selected_shapes_lock(self, locked):
        return ObjectEditor(self).toggle_selected_shapes_lock(locked)

    def _set_shapes_locked(self, shapes, locked):
        return ObjectEditor(self)._set_shapes_locked(shapes, locked)

    def _update_shapes_lock(self, shapes):
        return ObjectEditor(self)._update_shapes_lock(shapes)

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
        return RightSidebarTabs(self)._tab_key_for_page(page)

    def _rebuild_right_tabs(self):
        return RightSidebarTabs(self)._rebuild_right_tabs()

    def _apply_right_tabs_config(self):
        return RightSidebarTabs(self)._apply_right_tabs_config()

    def set_right_tab_visible(self, key, visible):
        return RightSidebarTabs(self).set_right_tab_visible(key, visible)

    def show_right_tab(self, key):
        return RightSidebarTabs(self).show_right_tab(key)

    def pop_right_tabs_menu(self, point):
        return RightSidebarTabs(self).pop_right_tabs_menu(point)

    def show_flags_page(self):
        return RightSidebarTabs(self).show_flags_page()

    def _on_right_tab_changed(self, _index):
        return RightSidebarTabs(self)._on_right_tab_changed(_index)

    def _refresh_statistics(self):
        return RightSidebarTabs(self)._refresh_statistics()

    def _refresh_statistics_if_visible(self):
        return RightSidebarTabs(self)._refresh_statistics_if_visible()

    def _on_statistics_filter_requested(self, statistics_filter):
        return RightSidebarTabs(self)._on_statistics_filter_requested(statistics_filter)

    def copy_file_path(self, file_path):
        popup = Popup(
            self.tr("Copy Successful"),
            parent=self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, copy_msg=file_path, position="default")

    def _label_file_checked(self, label_file):
        return DocumentStatus(self)._label_file_checked(label_file)

    def _set_file_item_checked(self, item, checked, shape_count=None):
        return DocumentStatus(self)._set_file_item_checked(item, checked, shape_count)

    def _file_item_annotation_checked(self, item):
        return DocumentStatus(self)._file_item_annotation_checked(item)

    def _create_file_list_item(self, file, label_file=None):
        return DocumentStatus(self)._create_file_list_item(file, label_file)

    def _current_file_item(self):
        return DocumentStatus(self)._current_file_item()

    def _annotation_checked(self):
        return DocumentStatus(self)._annotation_checked()

    def _annotation_checked_text(self, checked=None):
        return DocumentStatus(self)._annotation_checked_text(checked)

    def _update_annotation_checked_action(self):
        return DocumentStatus(self)._update_annotation_checked_action()

    def _update_file_row_after_save(self, shape_count):
        return DocumentStatus(self)._update_file_row_after_save(shape_count)

    def _update_current_file_checked_item(self):
        return DocumentStatus(self)._update_current_file_checked_item()

    def _sync_annotation_checked_state(self):
        return DocumentStatus(self)._sync_annotation_checked_state()

    def set_annotation_checked(self, checked):
        return DocumentStatus(self).set_annotation_checked(checked)

    def _append_filter_submenus(self, parent_menu, prepend=False, after_filter_actions=None):
        return LabelFilterController(self)._append_filter_submenus(parent_menu, prepend, after_filter_actions)

    def _populate_label_filter_menu(self, menu):
        return LabelFilterController(self)._populate_label_filter_menu(menu)

    def _populate_gid_filter_menu(self, menu):
        return LabelFilterController(self)._populate_gid_filter_menu(menu)

    def refresh_filter_menus(self):
        return LabelFilterController(self).refresh_filter_menus()

    def set_label_filter_value(self, label, _checked=False, block_signal=False):
        return LabelFilterController(self).set_label_filter_value(label, _checked, block_signal)

    def set_gid_filter_value(self, gid, _checked=False, block_signal=False):
        return LabelFilterController(self).set_gid_filter_value(gid, _checked, block_signal)

    def validate_label(self, label):
        return ObjectEditor(self).validate_label(label)

    def batch_edit_labels(self, shapes):
        return ObjectEditor(self).batch_edit_labels(shapes)

    def edit_label(self, item=None):
        return ObjectEditor(self).edit_label(item)

    def file_search_changed(self):
        search_text = self.file_search.text()
        dataset_mode = getattr(self, "dataset_repository", None) is not None
        self.import_image_folder(
            self.last_open_dir,
            pattern=search_text,
            load=False,
            select_first=not dataset_mode,
        )

    def file_selection_changed(self):
        if self._no_selection_slot:
            return
        if self.file_list_widget.selection_only_gesture():
            # Ctrl/Shift clicks and keyboard range selection build the batch
            # target set; they must not open the clicked image.
            return
        row = self.file_list_widget.currentRow()
        if row < 0:
            return
        filename = self._file_path_at(row)
        if not filename or str(filename) == str(self.filename):
            return
        if not self.may_continue():
            return
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
        return ObjectEditor(self).shape_selection_changed(selected_shapes)

    def add_label(self, shape, update_last_label=True, refresh_filters=True):
        return AnnotationEditor(self).add_label(shape, update_last_label, refresh_filters)

    def load_labels(self, labels, clear_existing=True):
        return AnnotationEditor(self).load_labels(labels, clear_existing)

    def _update_shape_color(self, shape):
        return AnnotationEditor(self)._update_shape_color(shape)

    def _get_rgb_by_label(self, label, skip_label_info=False):
        return AnnotationEditor(self)._get_rgb_by_label(label, skip_label_info)

    def remove_labels(self, shapes):
        return AnnotationEditor(self).remove_labels(shapes)

    def _relation_data_for_shapes(self, shapes):
        return RelationController(self)._relation_data_for_shapes(shapes)

    def create_relation(self, _checked=False):
        return RelationController(self).create_relation(_checked)

    def edit_relation(self, index):
        return RelationController(self).edit_relation(index)

    def delete_selected_relation(self):
        return RelationController(self).delete_selected_relation()

    def manage_relations(self, _checked=False):
        return RelationController(self).manage_relations(_checked)

    def _relation_dialog(self, index=None):
        return RelationController(self)._relation_dialog(index)

    def _show_relation_message(self, icon, text, parent=None):
        return RelationController(self)._show_relation_message(icon, text, parent)

    def on_canvas_shapes_deleted(self, shapes):
        return RelationController(self).on_canvas_shapes_deleted(shapes)

    def load_shapes(self, shapes, replace=True, update_last_label=True):
        return AnnotationEditor(self).load_shapes(shapes, replace, update_last_label)

    def load_flags(self, flags):
        return AnnotationEditor(self).load_flags(flags)

    def _sync_label_list_visibility(self, get_visible):
        return LabelFilterController(self)._sync_label_list_visibility(get_visible)

    def _refresh_shape_filters(self):
        return LabelFilterController(self)._refresh_shape_filters()

    def set_label_visibility(self, label, visible):
        return LabelFilterController(self).set_label_visibility(label, visible)

    def apply_label_visibility(self):
        return LabelFilterController(self).apply_label_visibility()

    def update_combo_box(self, block_signal=False):
        return LabelFilterController(self).update_combo_box(block_signal)

    def update_gid_box(self, block_signal=False):
        return LabelFilterController(self).update_gid_box(block_signal)

    def save_labels(self, filename):
        return AnnotationEditor(self).save_labels(filename)

    def duplicate_selected_shape(self):
        return ShapeCommands(self).duplicate_selected_shape()

    def paste_selected_shape(self):
        return ShapeCommands(self).paste_selected_shape()

    def toggle_system_clipboard(self, system_clipboard):
        self._config["system_clipboard"] = system_clipboard
        self.actions.paste.setEnabled(
            bool(system_clipboard or self._copied_shapes)
        )

    def copy_selected_shape(self):
        return ShapeCommands(self).copy_selected_shape()

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
        return ObjectEditor(self).label_selection_changed()

    def label_item_changed(self, item):
        return ObjectEditor(self).label_item_changed(item)

    # Callback functions:
    def new_shape(self):
        return AnnotationEditor(self).new_shape()

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
        return CanvasNavigation(self).on_navigator_request(x_ratio, y_ratio)

    def update_navigator_viewport(self):
        return CanvasNavigation(self).update_navigator_viewport()

    def update_navigator_shapes(self):
        return CanvasNavigation(self).update_navigator_shapes()

    def on_navigator_zoom_changed(self, zoom_percentage: int, mouse_pos: Optional[QtCore.QPoint]=None) -> None:
        return CanvasNavigation(self).on_navigator_zoom_changed(zoom_percentage, mouse_pos)

    def _convert_navigator_pos_to_canvas(self, navigator_pos: QtCore.QPoint) -> Optional[QtCore.QPoint]:
        return CanvasNavigation(self)._convert_navigator_pos_to_canvas(navigator_pos)

    def on_navigator_viewport_update_requested(self):
        return CanvasNavigation(self).on_navigator_viewport_update_requested()

    def toggle_navigator(self):
        return CanvasNavigation(self).toggle_navigator()

    def scroll_request(self, delta, orientation, mode):
        return CanvasNavigation(self).scroll_request(delta, orientation, mode)

    def set_scroll(self, orientation, value):
        return CanvasNavigation(self).set_scroll(orientation, value)

    def set_zoom(self, value, *, pos=None):
        return CanvasNavigation(self).set_zoom(value, pos=pos)

    def add_zoom(self, increment=1.1):
        return CanvasNavigation(self).add_zoom(increment)

    def zoom_request(self, delta, pos):
        return CanvasNavigation(self).zoom_request(delta, pos)

    def _animate_zoom(self, value):
        return CanvasNavigation(self)._animate_zoom(value)

    def _apply_zoom(self, value, image_pos=None, viewport_pos=None):
        return CanvasNavigation(self)._apply_zoom(value, image_pos, viewport_pos)

    def constrain_canvas_pan(self):
        return CanvasNavigation(self).constrain_canvas_pan()

    def pan_canvas(self, delta):
        return CanvasNavigation(self).pan_canvas(delta)

    def set_fit_window(self, value=True):
        return CanvasNavigation(self).set_fit_window(value)

    def set_fit_width(self, value=True):
        return CanvasNavigation(self).set_fit_width(value)

    def set_canvas_params(self, key, value):
        return CanvasNavigation(self).set_canvas_params(key, value)

    def open_settings_dialog(self, _checked=False, field_key=None):
        return AppearanceController(self).open_settings_dialog(_checked, field_key)

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
        if (
            hasattr(self, "_canvas_scroll_area")
            and obj is self._canvas_scroll_area.viewport()
            and event.type() == QtCore.QEvent.Type.Resize
        ):
            self._position_canvas_adjustment()
        return super().eventFilter(obj, event)

    def hide_selected_polygons(self):
        return ShapeCommands(self).hide_selected_polygons()

    def show_hidden_polygons(self):
        return ShapeCommands(self).show_hidden_polygons()

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

    def load_file(self, filename=None):
        return FileSession(self).load_file(filename)

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
        return CanvasNavigation(self).paint_canvas()

    def adjust_scale(self, initial=False):
        return CanvasNavigation(self).adjust_scale(initial)

    def scale_fit_window(self):
        return CanvasNavigation(self).scale_fit_window()

    def scale_fit_width(self):
        return CanvasNavigation(self).scale_fit_width()

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

        # Close the dataset connection on a clean exit so SQLite can
        # checkpoint/truncate the WAL and release its -shm handle.
        try:
            FileSession(self)._close_dataset()
        except Exception:  # noqa: BLE001 - never block window close
            logger.exception("Failed to close dataset database")

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
        return FileSession(self).load_recent(filename)

    def load_recent_dir(self, dirpath):
        return FileSession(self).load_recent_dir(dirpath)

    def open_prev_unchecked_image(self):
        return FileSession(self).open_prev_unchecked_image()

    def open_next_unchecked_image(self, _value=False):
        return FileSession(self).open_next_unchecked_image(_value)

    def open_prev_image(self, _value=False):
        return FileSession(self).open_prev_image(_value)

    def open_next_image(self, _value=False, load=True):
        return FileSession(self).open_next_image(_value, load)

    # File
    def open_file(self, _value=False):
        return FileSession(self).open_file(_value)

    def change_output_dir_dialog(self, _value=False):
        return FileSession(self).change_output_dir_dialog(_value)

    def save_file(self, _value=False):
        return FileSession(self).save_file(_value)

    def save_file_as(self, _value=False):
        return FileSession(self).save_file_as(_value)

    def save_file_dialog(self):
        return FileSession(self).save_file_dialog()

    def _save_file(self, filename):
        return FileSession(self)._save_file(filename)

    def close_file(self, _value=False):
        return FileSession(self).close_file(_value)

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
        return FileSession(self).get_label_file()

    def get_image_file(self):
        return FileSession(self).get_image_file()

    def delete_file(self):
        return FileSession(self).delete_file()

    def delete_image_file(self):
        return FileSession(self).delete_image_file()

    # Message Dialogs. #
    def has_labels(self):
        return FileSession(self).has_labels()

    def has_label_file(self):
        return FileSession(self).has_label_file()

    def may_continue(self):
        return FileSession(self).may_continue()

    def error_message(self, title, message):
        return FileSession(self).error_message(title, message)

    def current_path(self):
        return FileSession(self).current_path()

    def toggle_visibility_shapes(self, value):
        return ShapeCommands(self).toggle_visibility_shapes(value)

    def remove_selected_point(self):
        return ShapeCommands(self).remove_selected_point()

    def delete_selected_shape(self):
        return ShapeCommands(self).delete_selected_shape()

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
        return FileSession(self).import_files_dialog()

    def open_folder_dialog(self, _value=False, dirpath=None):
        return FileSession(self).open_folder_dialog(_value, dirpath)

    def open_dataset_center(self):
        return FileSession(self).open_dataset_center()

    def close_dataset(self):
        return FileSession(self).close_dataset()

    @property
    def image_list(self):
        return FileSession(self).image_list

    def _clear_file_list(self):
        self.files.clear()


    def import_dropped_image_files(self, image_files):
        return FileSession(self).import_dropped_image_files(image_files)

    def import_image_folder(
        self,
        dirpath,
        pattern=None,
        load=True,
        auto_db=True,
        select_first=True,
    ):
        return FileSession(self).import_image_folder(
            dirpath, pattern, load, auto_db, select_first
        )

    def import_project_dialog(self):
        return FileSession(self).import_project_dialog()

    def show_trash_dialog(self):
        return FileSession(self).show_trash_dialog()

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
        return ShapeCommands(self).shape_text_changed()

    def set_text_editing(self, enable):
        return ShapeCommands(self).set_text_editing(enable)

    def group_selected_shapes(self):
        return ShapeCommands(self).group_selected_shapes()

    def ungroup_selected_shapes(self):
        return ShapeCommands(self).ungroup_selected_shapes()

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
