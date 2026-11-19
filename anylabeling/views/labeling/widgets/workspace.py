"""Workspace assembly of the labeling window.

``LabelingWidget.__init__`` used to create the canvas view, the tool bars, the
right sidebar and the restored session state inline.  These builders keep that
assembly readable and out of the annotation flow (they only create widgets and
wire the host signals).

Host contract: the functions take the ``LabelingWidget`` instance and set its
attributes; they do not keep state of their own.
"""

import functools
import os.path as osp

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import utils
from ..file_list.constants import FILE_COL_NAME_WIDTH, FILE_COLUMN_WIDTHS
from ..logger import logger
from ..pointcloud.icons import get_icon
from ..settings import SettingsController
from ..utils.style import get_scrollbar_style, get_tab_widget_style
from ..utils.theme import get_theme
from ..widgets import (
    AttributionLabel,
    AutoLabelingWidget,
    Canvas,
    CanvasAdjustmentWidget,
    CompareViewManager,
    CompareViewSlider,
    ImageTagsWidget,
    OperatorBar,
)
from ..widgets.panel import HoverScrollBars, RoundedPanel
from ..widgets.statistics_table import StatisticsTable
from ..widgets.splitters import RightSplitter, SidebarSplitter


def build_canvas_view(host):
    """Create the canvas, its scroll area, overlays and image tag bar.

    Returns the scroll area that hosts the canvas.
    """
    host.canvas = host.label_list.canvas = Canvas(
        parent=host,
        label_font_size=host._config["canvas"]["label_font_size"],
        epsilon=host._config["canvas"]["epsilon"],
        double_click=host._config["canvas"]["double_click"],
        num_backups=host._config["canvas"]["num_backups"],
        wheel_navigation_mode=host._config["canvas"].get(
            "wheel_navigation_mode", "direct"
        ),
        wheel_rectangle_editing=host._config["canvas"][
            "wheel_rectangle_editing"
        ],
        auto_highlight_shape=host._config.get(
            "auto_highlight_shape", False
        ),
        attributes=host._config["canvas"].get("attributes", {}),
        rotation=host._config["canvas"].get("rotation", {}),
        mask=host._config["canvas"].get("mask", {}),
        brush=host._config["canvas"].get("brush", {}),
        magic_wand=host._config["canvas"].get("magic_wand", {}),
        cuboid=host._config["canvas"].get("cuboid", {}),
        double_click_edit_label=host._config["canvas"].get(
            "double_click_edit_label", True
        ),
    )
    host.canvas.zoom_request.connect(host.zoom_request)
    host.canvas.pan_request.connect(host.pan_canvas)
    host.canvas.interaction_started.connect(host._zoom_animation.stop)
    host._cursor_position = None
    host.canvas.mouse_position_changed.connect(
        host._on_canvas_mouse_moved
    )

    # Compare view support
    host.compare_view_manager = CompareViewManager(host.canvas, host)
    host.compare_view_manager.status_message.connect(host.status)
    host.compare_view_slider = CompareViewSlider(host)
    host.compare_view_slider.position_changed.connect(
        host.compare_view_manager.set_split_position
    )
    host.compare_view_slider.close_requested.connect(
        host.close_compare_view
    )
    host.compare_view_manager.compare_closed.connect(
        host.compare_view_slider.hide_slider
    )
    host.canvas.split_position_changed.connect(
        host.compare_view_slider.set_position
    )

    scroll_area = QScrollArea()
    scroll_area.setStyleSheet(get_scrollbar_style())
    scroll_bar_policy = (
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
        if host.canvas.wheel_navigation_mode == "traditional"
        else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    scroll_area.setHorizontalScrollBarPolicy(scroll_bar_policy)
    scroll_area.setVerticalScrollBarPolicy(scroll_bar_policy)
    scroll_area.setWidget(host.canvas)
    scroll_area.setWidgetResizable(True)
    host._canvas_scroll_area = scroll_area

    # Adjustment panel docked at the bottom-left of the canvas viewport.
    host.canvas_adjustment = CanvasAdjustmentWidget(scroll_area.viewport())
    host.canvas_adjustment.grid_changed.connect(host._on_grid_changed)
    host._on_grid_changed(
        host.canvas_adjustment.grid_opacity.value() > 0,
        host.canvas_adjustment.grid_size.value(),
        host.canvas_adjustment.grid_color.currentData(),
        host.canvas_adjustment.grid_opacity.value(),
        host.canvas_adjustment.grid_labels.isChecked(),
    )
    host.canvas_adjustment.opacity_changed.connect(
        host._on_shape_opacity_changed
    )
    host.canvas_adjustment.brightness_contrast_changed.connect(
        host._on_inline_brightness_contrast
    )
    host.canvas_adjustment.status_changed.connect(
        host.set_annotation_checked
    )
    host.canvas_adjustment.geometry_changed.connect(
        host._position_canvas_adjustment
    )
    # Hidden until an image is loaded (shown at the end of load_file).
    host.canvas_adjustment.hide()

    # Browse-mode badge: a clickable reminder anchored to the canvas
    # area itself.  Login state is otherwise only visible in window
    # chrome, which users do not look at while annotating.
    host.browse_mode_badge = QtWidgets.QPushButton(
        scroll_area.viewport()
    )
    host.browse_mode_badge.setObjectName("BrowseModeBadge")
    host.browse_mode_badge.setCursor(
        Qt.CursorShape.PointingHandCursor
    )
    host.browse_mode_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    host.browse_mode_badge.setToolTip(
        host.tr("Browse mode - editing annotations requires login")
    )
    host.browse_mode_badge.clicked.connect(host.open_operator_login)
    host.browse_mode_badge.hide()
    scroll_area.viewport().installEventFilter(host)

    host.scroll_bars = {
        Qt.Orientation.Vertical: scroll_area.verticalScrollBar(),
        Qt.Orientation.Horizontal: scroll_area.horizontalScrollBar(),
    }
    host.scroll_bars[Qt.Orientation.Vertical].valueChanged.connect(
        lambda: host.update_navigator_viewport()
    )
    host.scroll_bars[Qt.Orientation.Horizontal].valueChanged.connect(
        lambda: host.update_navigator_viewport()
    )
    host.scroll_bars[Qt.Orientation.Vertical].rangeChanged.connect(
        lambda *_: host.update_labeling_instruction()
    )
    host.scroll_bars[Qt.Orientation.Horizontal].rangeChanged.connect(
        lambda *_: host.update_labeling_instruction()
    )
    host.canvas.scroll_request.connect(host.scroll_request)
    host.canvas.new_shape.connect(host.new_shape)
    host.canvas.show_shape.connect(host.show_shape)
    host.canvas.show_line_length.connect(host.show_line_length)
    host.canvas.show_circle_radius.connect(host.show_circle_radius)
    host.canvas.shape_moved.connect(host.set_dirty)
    host.canvas.shape_rotated.connect(host.set_dirty)
    host.canvas.shapes_deleted.connect(host.on_canvas_shapes_deleted)
    host.canvas.selection_changed.connect(host.shape_selection_changed)
    host.canvas.drawing_polygon.connect(host.toggle_drawing_sensitive)
    host.canvas.edit_label_requested.connect(host.edit_label)
    host.canvas.relation_edit_requested.connect(host.edit_relation)
    host.canvas.relation_delete_requested.connect(
        host.delete_selected_relation
    )
    # Keep the brush-edit toggle in sync when the canvas exits brush
    # mode on its own (e.g. via a right-click).
    host.canvas.brush_mode_changed.connect(host.on_brush_mode_changed)
    host.canvas.brush_history_changed.connect(
        lambda can_undo: host.actions.undo.setEnabled(can_undo)
    )
    # [Feature] support for automatically switching to editing mode
    # when the cursor moves over an object
    host.canvas.h_shape_is_hovered = host._config.get(
        "auto_highlight_shape", False
    )
    host._settings_runtime_applier.set_auto_switch_to_edit_mode(
        host._config["auto_switch_to_edit_mode"]
    )

    # Crosshair
    host.crosshair_settings = host._config["canvas"]["crosshair"]
    host.canvas.set_cross_line(**host.crosshair_settings)

    host._central_widget = scroll_area

    host._image_tags_visibility = "auto"
    host.image_tags_widget = ImageTagsWidget(
        host._get_rgb_by_image_tag, host
    )
    host.image_tags_widget.tags_changed.connect(
        host._on_image_tags_changed
    )
    host.image_tags_widget.status_message.connect(host.status)
    host.image_tags_widget.set_interactions_enabled(False)
    host.image_tags_widget.show()
    return scroll_area


def build_instruction_bar(host):
    """Create the instruction label, the auto-labeling panel and buttons.

    Returns the instruction row layout that belongs above the canvas.
    """
    action = functools.partial(utils.new_action, host)
    host.label_instruction = QLabel(host.get_labeling_instruction(), host)
    host.label_instruction.setContentsMargins(0, 0, 0, 0)
    host.label_instruction.hide()
    host.auto_labeling_widget = AutoLabelingWidget(host)
    host.auto_labeling_widget.auto_segmentation_requested.connect(
        host.on_auto_segmentation_requested
    )
    host.auto_labeling_widget.auto_segmentation_disabled.connect(
        host.on_auto_segmentation_disabled
    )
    host.canvas.auto_labeling_marks_updated.connect(
        host.auto_labeling_widget.on_new_marks
    )
    host.auto_labeling_widget.auto_labeling_mode_changed.connect(
        host.canvas.set_auto_labeling_mode
    )
    host.auto_labeling_widget.auto_decode_mode_changed.connect(
        host.canvas.set_auto_decode_mode
    )
    host.auto_labeling_widget.cropping_mode_changed.connect(
        host.auto_labeling_widget.model_manager.set_cropping_mode
    )
    host.auto_labeling_widget.clear_auto_decode_requested.connect(
        host.canvas.reset_auto_decode_state
    )
    host.canvas.auto_decode_requested.connect(
        host.on_auto_decode_requested
    )
    host.canvas.auto_decode_finish_requested.connect(
        host.auto_labeling_widget.on_finish_clicked
    )
    host.canvas.shape_hover_changed.connect(
        lambda: (
            host.update_navigator_shapes()
            if (
                hasattr(host, "navigator_dialog")
                and host.navigator_dialog.isVisible()
            )
            else None
        )
    )
    host.auto_labeling_widget.clear_auto_labeling_action_requested.connect(
        host.clear_auto_labeling_marks
    )
    host.auto_labeling_widget.finish_auto_labeling_object_action_requested.connect(
        host.finish_auto_labeling_object
    )
    host.auto_labeling_widget.cache_auto_label_changed.connect(
        host.set_cache_auto_label
    )
    host.auto_labeling_widget.model_manager.prediction_started.connect(
        lambda: host.canvas.set_loading(True, host.tr("Please wait..."))
    )
    host.auto_labeling_widget.model_manager.prediction_finished.connect(
        lambda: host.canvas.set_loading(False)
    )
    host.auto_labeling_widget.model_manager.prediction_finished.connect(
        host.update_thumbnail_display
    )
    host.auto_labeling_widget.model_manager.model_loaded.connect(
        host.update_thumbnail_display
    )
    host.auto_labeling_widget.remote_server_select_combobox.currentIndexChanged.connect(
        host.update_thumbnail_display
    )
    host.auto_labeling_widget.remote_task_select_combobox.currentIndexChanged.connect(
        host.update_thumbnail_display
    )
    host.next_files_changed.connect(
        host.auto_labeling_widget.model_manager.on_next_files_changed
    )
    # NOTE(jack): this is not needed for now
    # self.auto_labeling_widget.model_manager.request_next_files_requested.connect(
    #     lambda: self.inform_next_files(self.filename)
    # )
    host.auto_labeling_widget.hide()  # Hide by default
    instruction_layout = QHBoxLayout()
    instruction_layout.setContentsMargins(0, 0, 0, 0)
    instruction_layout.setSpacing(2)
    theme = get_theme()
    toggle_style = f"""
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                color: {theme["text"]};
                padding: 3px;
                border-radius: 4px;
            }}
            QToolButton:hover:enabled {{
                background-color: {theme["surface_hover"]};
                border-color: {theme["border"]};
            }}
            QToolButton:pressed:enabled {{
                background-color: {theme["surface_pressed"]};
                border-color: {theme["border"]};
            }}
    """
    host.sidebar_toggle_button = QtWidgets.QToolButton()
    host._configure_toggle_button(
        host.sidebar_toggle_button,
        toggle_style,
        host.tr("Toggle right panel"),
    )
    host.sidebar_toggle_button.setIcon(
        host._panel_toggle_icon("sidebar", True)
    )
    host.sidebar_toggle_button.clicked.connect(host.toggle_right_sidebar)
    host.image_tags_toggle_button = QtWidgets.QToolButton()
    host._configure_toggle_button(
        host.image_tags_toggle_button,
        toggle_style,
        host.tr("Show or hide image tags"),
    )
    host.image_tags_toggle_button.setDefaultAction(
        host.actions.show_image_tags
    )
    # These two buttons live in the title bar in frameless mode and are
    # re-added to the toolbar in native mode (see MainWindow).
    host.window_control_buttons = (
        host.sidebar_toggle_button,
        host.image_tags_toggle_button,
    )
    host.shortcuts_button = QtWidgets.QToolButton()
    host.shortcuts_button.setIcon(
        get_icon("command", theme["text"], theme["primary"])
    )
    host.shortcuts_button.setIconSize(QtCore.QSize(18, 18))
    host.shortcuts_button.setFixedSize(26, 26)
    host.shortcuts_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    host.shortcuts_button.setToolTip(host.tr("Shortcuts"))
    host.shortcuts_button.setAccessibleName(
        host.shortcuts_button.toolTip()
    )
    host.shortcuts_button.setStyleSheet(toggle_style)
    host.shortcuts_button.clicked.connect(host.show_shortcuts)
    host.update_button = QtWidgets.QToolButton()
    host.update_button.setIcon(
        get_icon("circle-arrow-up", theme["primary"], theme["primary"])
    )
    host.update_button.setIconSize(QtCore.QSize(18, 18))
    host.update_button.setFixedSize(26, 26)
    host.update_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    host.update_button.setToolTip(host.tr("Update available"))
    host.update_button.setAccessibleName(host.tr("Update available"))
    host.update_button.setStyleSheet(toggle_style)
    host.update_button.hide()
    instruction_layout.addWidget(host.update_button)
    utility_actions = []
    utility_entries = []
    for key, title, button in (
        ("settings", host.tr("Settings"), host.settings_button),
        ("shortcuts", host.tr("Shortcuts"), host.shortcuts_button),
    ):
        button.setStyleSheet("")
        widget_action = QtWidgets.QWidgetAction(host)
        widget_action.setDefaultWidget(button)
        utility_actions.append(widget_action)
        # (key, title, action) so the toolbar settings page can hide these
        # pinned buttons like any other tool.
        utility_entries.append((key, title, widget_action))
    host.display_mode_group = QtGui.QActionGroup(host)
    host.display_mode_group.setExclusive(True)
    display_actions = []
    for mode, title, icon in (
        ("label", host.tr("Color by label"), "swatch-book"),
        ("instance", host.tr("Color by instance"), "component"),
        ("group", host.tr("Color by group"), "network"),
        ("bitmap", host.tr("Binary mask"), "contrast"),
    ):
        display_action = action(
            title,
            icon=icon,
            tip=title,
            checkable=True,
            checked=mode == "label",
        )
        display_action.setData(mode)
        host.display_mode_group.addAction(display_action)
        display_actions.append(display_action)
    host.display_mode_group.triggered.connect(
        lambda selected: host.canvas.set_display_mode(selected.data())
    )
    host.actions.tool += (
        None,
        *display_actions,
        None,
        *utility_actions,
    )
    host._utility_toolbar_actions = utility_actions
    host._utility_toolbar_entries = tuple(utility_entries)
    return instruction_layout


def build_operator_bar(host):
    """Create the operator chip/attribution bar and subscribe to the session."""
    host.operator_bar = OperatorBar(host.operator_service, host)
    host.operator_bar.login_requested.connect(host.open_operator_login)
    host.operator_bar.logout_requested.connect(host.logout_operator)
    host.attribution_label = AttributionLabel(host)
    host._operator_unsubscribe = host.operator_service.session.subscribe(
        host._on_operator_session_changed
    )
    host._apply_operator_gate()


def build_workspace(host, scroll_area, instruction_layout):
    """Assemble the central layout, the right sidebar tabs and the splitters."""
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)

    central_layout = QVBoxLayout()
    central_layout.setContentsMargins(0, 0, 0, 0)
    central_layout.setSpacing(4)
    central_layout.addLayout(instruction_layout)
    theme = get_theme()
    # The main window moves these two widgets into its menu bar corner
    # and status bar so they cost no canvas height.  Standalone embedding
    # (no menu bar host) keeps the compact bar above the canvas.
    window_host = getattr(host.parent, "parent", None)
    if window_host is None or not hasattr(window_host, "menuBar"):
        central_layout.addWidget(host.operator_bar)
    central_layout.addWidget(host.auto_labeling_widget)
    canvas_panel = RoundedPanel()
    canvas_panel_layout = QVBoxLayout(canvas_panel)
    canvas_panel_layout.setContentsMargins(0, 0, 0, 0)
    canvas_panel_layout.setSpacing(0)
    scroll_area.setFrameShape(QFrame.Shape.NoFrame)
    canvas_panel_layout.addWidget(scroll_area)
    central_layout.addWidget(canvas_panel, 1)
    central_layout.addWidget(host.compare_view_slider)
    central_layout.addWidget(host.image_tags_widget)
    central_widget = QWidget()
    central_widget.setLayout(central_layout)
    host.sidebar_splitter = SidebarSplitter(Qt.Orientation.Horizontal)
    host.sidebar_splitter.setObjectName("SidebarSplitter")
    host.sidebar_splitter.setHandleWidth(9)
    host.sidebar_splitter.setStyleSheet("""
            QSplitter#SidebarSplitter::handle:horizontal {
                background-color: transparent;
                width: 9px;
                border: none;
            }
        """)
    host.sidebar_splitter.setChildrenCollapsible(False)
    host.sidebar_splitter.addWidget(central_widget)
    layout.addWidget(host.sidebar_splitter)

    # Save central area for resize
    host._central_widget = scroll_area

    # Stretch central area (image view)
    layout.setStretch(1, 1)

    host.right_sidebar = QWidget()
    right_sidebar_layout = QVBoxLayout(host.right_sidebar)
    right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
    right_sidebar_layout.setSpacing(4)
    host.image_tags_widget.installEventFilter(host)

    # Thumbnail image display
    host.thumbnail_pixmap = None
    host.thumbnail_container = QWidget()
    thumbnail_image_layout = QVBoxLayout()
    thumbnail_image_layout.setContentsMargins(2, 2, 2, 2)
    host.thumbnail_image_label = QLabel()
    host.thumbnail_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    host.thumbnail_image_label.mousePressEvent = utils.on_thumbnail_click(
        host
    )
    thumbnail_image_layout.addWidget(host.thumbnail_image_label)
    host.thumbnail_container.setLayout(thumbnail_image_layout)
    host.thumbnail_container.hide()
    right_sidebar_layout.addWidget(host.thumbnail_container)

    # Shape attributes
    host.shape_attributes = QLabel(host.tr("Attributes"))
    host.grid_layout = QGridLayout()
    host.scroll_area = QScrollArea()
    # Show vertical scrollbar as needed
    host.scroll_area.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    # Disable horizontal scrollbar
    host.scroll_area.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    host.scroll_area.setWidgetResizable(True)
    # Create a container widget for the grid layout
    host.grid_layout_container = QWidget()
    host.grid_layout_container.setLayout(host.grid_layout)
    host.scroll_area.setWidget(host.grid_layout_container)
    host.shape_attributes.hide()
    host.scroll_area.hide()

    # ---- Right side: one tab panel with objects/classes/flags/description
    labels_panel = RoundedPanel()
    labels_panel_layout = QVBoxLayout(labels_panel)
    labels_panel_layout.setContentsMargins(0, 0, 0, 0)
    labels_panel_layout.setSpacing(0)
    labels_panel_layout.addWidget(host.unique_label_list, 1)

    objects_panel = RoundedPanel()
    objects_panel_layout = QVBoxLayout(objects_panel)
    objects_panel_layout.setContentsMargins(0, 0, 0, 0)
    objects_panel_layout.setSpacing(0)
    objects_panel_layout.addWidget(host.label_list, 1)

    flags_panel = RoundedPanel()
    flags_panel_layout = QVBoxLayout(flags_panel)
    flags_panel_layout.setContentsMargins(0, 0, 0, 0)
    flags_panel_layout.setSpacing(0)
    flags_panel_layout.addWidget(host.flag_widget, 1)

    description_panel = RoundedPanel()
    description_panel_layout = QVBoxLayout(description_panel)
    description_panel_layout.setContentsMargins(0, 0, 0, 0)
    description_panel_layout.setSpacing(0)
    description_panel_layout.addWidget(host.shape_text_edit, 1)

    host.statistics_table = StatisticsTable()
    host.statistics_table.filter_requested.connect(
        host._on_statistics_filter_requested
    )

    host.right_tabs = QTabWidget()
    host.right_tabs.setObjectName("RightTabs")
    host.right_tabs.setDocumentMode(True)
    host.right_tabs.setUsesScrollButtons(True)
    host.right_tabs.setStyleSheet(get_tab_widget_style())
    tab_bar = host.right_tabs.tabBar()
    tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tab_bar.customContextMenuRequested.connect(host.pop_right_tabs_menu)
    host._tab_pages = (
        ("objects", host.tr("Objects"), objects_panel),
        ("labels", host.tr("Classes"), labels_panel),
        ("flags", host.tr("Flags"), flags_panel),
        ("description", host.tr("Description"), description_panel),
        ("statistics", host.tr("Statistics"), host.statistics_table),
    )
    host._rebuild_right_tabs()
    host.right_tabs.currentChanged.connect(host._on_right_tab_changed)

    # ---- File table panel (search bar + image table, no dock wrapper)
    files_panel = RoundedPanel()
    files_panel_layout = QVBoxLayout(files_panel)
    files_panel_layout.setContentsMargins(0, 0, 0, 0)
    files_panel_layout.setSpacing(0)
    host.file_search.setStyleSheet(host.file_search.styleSheet() + f"""
            QLineEdit {{
                background-color: {theme["surface"]};
                border: none;
                border-bottom: 1px solid {theme["border"]};
                border-radius: 0;
            }}
            QLineEdit:focus {{
                border: none;
                border-bottom: 1px solid {theme["border"]};
            }}
    """)
    host.file_search.setTextMargins(4, 0, 4, 0)
    host.import_button = QtWidgets.QToolButton(host)
    host.import_button.setObjectName("ImportFilesButton")
    host.import_button.setFixedSize(26, 26)
    host.import_button.setCursor(
        QtCore.Qt.CursorShape.PointingHandCursor
    )
    host.import_button.setToolTip(host.tr("Import"))
    host.import_button.setIcon(
        utils.new_icon("circle-plus", "svg")
    )
    host.import_button.setIconSize(QtCore.QSize(16, 16))
    host.import_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    host.import_button.setPopupMode(
        QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
    )
    host.import_menu = QtWidgets.QMenu(host.import_button)
    host.import_menu.addAction(
        host.tr("Import Files"), host.import_files_dialog
    )
    host.import_menu.addAction(
        host.tr("Import Folder"), host.open_folder_dialog
    )
    host.import_button.setMenu(host.import_menu)
    search_row = QtWidgets.QHBoxLayout()
    search_row.setContentsMargins(0, 0, 2, 0)
    search_row.setSpacing(2)
    search_row.addWidget(host.file_search, 1)
    search_row.addWidget(host.import_button)
    files_panel_layout.addLayout(search_row)
    files_panel_layout.addWidget(host.file_list_widget, 1)

    # Tab panel and file table are vertically adjustable by the user.
    host.right_splitter = RightSplitter(Qt.Orientation.Vertical)
    host.right_splitter.setObjectName("RightSplitter")
    host.right_splitter.setChildrenCollapsible(False)
    host.right_splitter.setHandleWidth(9)
    host.right_splitter.setStyleSheet("""
            QSplitter#RightSplitter::handle:vertical {
                background-color: transparent;
                height: 9px;
                border: none;
            }
        """)
    host.right_splitter.addWidget(host.right_tabs)
    host.right_splitter.addWidget(files_panel)
    host.right_splitter.setStretchFactor(0, 1)
    host.right_splitter.setStretchFactor(1, 1)
    host.right_splitter.setSizes([320, 420])
    right_sidebar_layout.addWidget(host.right_splitter, 1)
    host._apply_right_tabs_config()
    for area in (
        host.unique_label_list,
        host.label_list,
        host.file_list_widget,
        host.flag_widget,
        host.shape_text_edit,
    ):
        HoverScrollBars(area)

    host.shape_text_edit.textChanged.connect(host.shape_text_changed)

    host.right_sidebar.ensurePolished()
    # Fit the visible file-table columns without a horizontal scrollbar on
    # first start; the user can still resize both sidebar and columns.
    file_table_width = FILE_COL_NAME_WIDTH + 80 + sum(
        width
        for column, width in FILE_COLUMN_WIDTHS.items()
        if not host.file_list_widget.isColumnHidden(column)
    )
    sidebar_width = max(
        host.right_sidebar.sizeHint().width(),
        min(file_table_width, 620),
    )
    # The minimum width only needs to keep the sidebar usable; the file
    # table gets a horizontal scrollbar when the user narrows it further.
    sidebar_min_width = max(
        220, round(host.right_sidebar.sizeHint().width() * 0.8)
    )
    host.right_sidebar.setMinimumWidth(sidebar_min_width)
    host.right_sidebar.setMaximumWidth(sidebar_width * 2)
    host._right_sidebar_width = sidebar_width
    host._sidebar_base_width = sidebar_width
    host._sidebar_min_width = sidebar_min_width
    host._sidebar_width_ratio = None
    host._ui_scale = 1.0
    host._ui_resize_timer = QtCore.QTimer(host)
    host._ui_resize_timer.setSingleShot(True)
    host._ui_resize_timer.timeout.connect(host._update_ui_density)
    host.sidebar_splitter.splitterMoved.connect(
        host._remember_sidebar_width
    )
    host.sidebar_splitter.addWidget(host.right_sidebar)
    host.sidebar_splitter.setStretchFactor(0, 1)
    host.sidebar_splitter.setStretchFactor(1, 0)
    host.sidebar_splitter.setSizes(
        [central_widget.sizeHint().width(), sidebar_width]
    )
    host.setLayout(layout)


def restore_session_state(host, filename, output_file, output_dir, config):
    """Restore QSettings/state and schedule the first file load."""

    if output_file is not None and host._config["auto_save"]:
        logger.warning(
            "If `auto_save` argument is True, `output_file` argument "
            "is ignored and output filename is automatically "
            "set as IMAGE_BASENAME.json."
        )
    host.output_file = output_file
    host.output_dir = output_dir

    # Application state.
    host.image = QtGui.QImage()
    host.image_path = None
    host.recent_files = []
    host.max_recent = 7
    host.other_data = {}
    host.zoom_level = 100
    host.fit_window = False
    host.zoom_values = {}  # key=filename, value=(zoom_mode, zoom_value)
    host.pan_values = {}
    host.brightness_contrast_values = {}
    host.scroll_values = {
        Qt.Orientation.Horizontal: {},
        Qt.Orientation.Vertical: {},
    }  # key=filename, value=scroll_value

    if filename is not None and osp.isdir(filename):
        host.import_image_folder(filename, load=False)
    else:
        host.filename = filename

    if config["file_search"]:
        host.file_search.setText(config["file_search"])
        host.file_search_changed()

    # XXX: Could be completely declarative.
    # Restore application settings.
    host.settings = QtCore.QSettings("anylabeling", "anylabeling")
    host._toolbar_show_labels = host.settings.value(
        "toolbar/show_labels", True, type=bool
    )
    hidden = host.settings.value("toolbar/hidden_actions", []) or []
    host._toolbar_hidden_keys = {str(key) for key in hidden}
    if hasattr(host, "tools"):
        host.tools.set_label_mode(host._toolbar_show_labels)
    host.recent_files = host.settings.value("recent_files", []) or []
    host.last_open_dir = host.settings.value("last_open_dir", None) or None

    # Populate the File menu dynamically.
    host.update_file_menu()

    # Since loading the file may take some time,
    # make sure it runs in the background.
    if host.filename is not None:
        host.queue_event(functools.partial(host.load_file, host.filename))

    # Callbacks:
    host.zoom_widget.valueChanged.connect(host.set_zoom)

    host.populate_mode_actions()
    host._settings_controller = SettingsController(
        config=host._config,
        apply_callback=host._settings_runtime_applier.apply_change,
        parent=host,
        defer_runtime_apply=True,
        preview_keys={"shape.line_width", "canvas.crosshair.width"},
    )
    host._settings_runtime_applier.build_shortcut_action_map()

    host.set_text_editing(False)

    QtCore.QTimer.singleShot(100, host.restore_navigator_state)
