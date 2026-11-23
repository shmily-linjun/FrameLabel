"""QAction table of the labeling window.

``build_actions(host)`` creates every ``QAction`` the annotation window exposes
(toolbar, menus and the canvas context menu) and returns them as a plain
attribute bag.  It used to live inline in ``LabelingWidget.__init__``; keeping
it here makes the action list readable and testable without touching the
window layout code.

The host object only needs the attributes and methods the actions call back
into, which is why this module does not import the labeling widget.
"""

import functools

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .. import utils
from ..constants import LABEL_OPACITY
from ..pointcloud.icons import get_icon
from ..utils.theme import get_theme


def build_actions(host):  # noqa: C901
    """Create and return the action registry of the labeling window."""
    action = functools.partial(utils.new_action, host)
    shortcuts = host._config["shortcuts"]

    open_ = action(
        host.tr("Open File"),
        host.open_file,
        shortcuts["open"],
        "file",
        host.tr("Open image or label file"),
    )
    openvideo = action(
        host.tr("Open Video"),
        lambda: utils.open_video_file(host),
        shortcuts["open_video"],
        "file-video-camera",
        host.tr("Open video file"),
    )
    opendir = action(
        host.tr("Open Dir"),
        host.open_folder_dialog,
        shortcuts["open_dir"],
        "open",
        host.tr("Open Dir"),
    )
    import_project = action(
        host.tr("Import Project (X-AnyLabeling)…"),
        host.import_project_dialog,
        None,
        None,
        host.tr("Import X-AnyLabeling JSON files into a dataset database"),
    )
    show_trash = action(
        host.tr("Recycle Bin…"),
        host.show_trash_dialog,
        None,
        None,
        host.tr("Restore or permanently delete trashed images"),
    )
    open_next_image = action(
        host.tr("Next Image"),
        host.open_next_image,
        shortcuts["open_next"],
        "next",
        host.tr("Open next image"),
        enabled=False,
    )
    open_prev_image = action(
        host.tr("Prev Image"),
        host.open_prev_image,
        shortcuts["open_prev"],
        "prev",
        host.tr("Open prev image"),
        enabled=False,
    )
    jump_next_images = action(
        host.tr("Forward %s Images") % host._config["image_jump_step"],
        lambda: host.jump_images(host._config["image_jump_step"]),
        icon="skip-next",
        tip=host.tr("Move forward by %s images")
        % host._config["image_jump_step"],
        enabled=False,
    )
    jump_prev_images = action(
        host.tr("Back %s Images") % host._config["image_jump_step"],
        lambda: host.jump_images(-host._config["image_jump_step"]),
        icon="skip-prev",
        tip=host.tr("Move back by %s images")
        % host._config["image_jump_step"],
        enabled=False,
    )
    open_next_unchecked_image = action(
        host.tr("Next Unchecked Image"),
        host.open_next_unchecked_image,
        shortcuts["open_next_unchecked"],
        "next",
        host.tr("Open next unchecked image"),
        enabled=False,
    )
    open_prev_unchecked_image = action(
        host.tr("Prev Unchecked Image"),
        host.open_prev_unchecked_image,
        shortcuts["open_prev_unchecked"],
        "prev",
        host.tr("Open previous unchecked image"),
        enabled=False,
    )
    save = action(
        host.tr("Save"),
        host.save_file,
        shortcuts["save"],
        "save",
        host.tr("Save labels to file"),
        enabled=False,
    )
    save_as = action(
        host.tr("Save As"),
        host.save_file_as,
        shortcuts["save_as"],
        "save-as",
        host.tr("Save labels to a different file"),
        enabled=False,
    )
    run_all_images = action(
        host.tr("Auto Run"),
        lambda: utils.run_all_images(host),
        shortcuts["auto_run"],
        "auto-run",
        host.tr("Auto run all images at once"),
        enabled=False,
    )
    delete_file = action(
        host.tr("Delete File"),
        host.delete_file,
        shortcuts["delete_file"],
        "delete",
        host.tr("Delete current label file"),
        enabled=False,
    )
    delete_image_file = action(
        host.tr("Delete Image File"),
        host.delete_image_file,
        shortcuts["delete_image_file"],
        "image-off",
        host.tr("Delete current image file"),
        enabled=True,
    )
    open_settings = action(
        host.tr("Settings"),
        host.open_settings_dialog,
        icon="settings",
    )
    toggle_annotation_checked = action(
        host.tr("Check Passed"),
        lambda: host.set_annotation_checked(True),
        shortcuts.get("toggle_annotation_checked"),
        checkable=True,
        enabled=False,
    )
    clear_annotation_checked = action(
        host.tr("Unchecked"),
        lambda: host.set_annotation_checked(False),
        shortcuts.get("clear_annotation_checked"),
        checkable=True,
        enabled=False,
    )
    fail_annotation_checked = action(
        host.tr("Check Failed"),
        lambda: host.set_annotation_checked("failed"),
        shortcuts.get("fail_annotation_checked"),
        checkable=True,
        enabled=False,
    )
    host.annotation_check_menu = QtWidgets.QMenu(
        host.tr("Check Status"), host
    )
    host.annotation_check_group = QtGui.QActionGroup(host)
    for check_action in (
        clear_annotation_checked,
        toggle_annotation_checked,
        fail_annotation_checked,
    ):
        host.annotation_check_group.addAction(check_action)
        host.annotation_check_menu.addAction(check_action)
        host.addAction(check_action)

    toggle_compare_view = action(
        host.tr("Compare View"),
        host.toggle_compare_view,
        shortcuts.get("toggle_compare_view"),
        "columns-2",
        host.tr("Toggle split-screen compare view"),
        enabled=True,
    )

    change_output_dir = action(
        host.tr("Change Output Dir"),
        slot=host.change_output_dir_dialog,
        shortcut=shortcuts["save_to"],
        icon="open",
        tip=host.tr("Change where annotations are loaded/saved"),
    )

    save_auto = action(
        text=host.tr("Save Automatically"),
        slot=lambda x: host._config.update({"auto_save": x}),
        icon=None,
        tip=host.tr("Save automatically"),
        checkable=True,
        enabled=True,
        checked=host._config["auto_save"],
    )

    save_with_image_data = action(
        text=host.tr("Save With Image Data"),
        slot=lambda x: host._config.update({"store_data": x}),
        icon=None,
        tip=host.tr("Save image data in label file"),
        checkable=True,
        checked=host._config["store_data"],
    )

    close = action(
        host.tr("Close"),
        host.close_file,
        shortcuts["close"],
        "cancel",
        host.tr("Close current file"),
    )

    keep_prev_mode = action(
        host.tr("Keep Previous Annotation"),
        lambda x: host._config.update({"keep_prev": x}),
        shortcuts["toggle_keep_prev_mode"],
        None,
        host.tr('Toggle "Keep Previous Annotation" mode'),
        checkable=True,
        checked=host._config["keep_prev"],
    )

    auto_use_last_label_mode = action(
        host.tr("Auto Use Last Label"),
        lambda x: host._config.update({"auto_use_last_label": x}),
        shortcuts["toggle_auto_use_last_label"],
        None,
        host.tr('Toggle "Auto Use Last Label" mode'),
        checkable=True,
        checked=host._config["auto_use_last_label"],
    )

    auto_use_last_gid_mode = action(
        host.tr("Auto Use Last Group ID"),
        lambda x: host._config.update({"auto_use_last_gid": x}),
        shortcuts["toggle_auto_use_last_gid"],
        None,
        host.tr('Toggle "Auto Use Last Group ID" mode'),
        checkable=True,
        checked=host._config["auto_use_last_gid"],
    )

    use_system_clipboard = action(
        host.tr("Use System Clipboard"),
        host.toggle_system_clipboard,
        tip=host.tr("Use system clipboard for copy and paste"),
        checkable=True,
        checked=host._config["system_clipboard"],
        enabled=True,
    )

    visibility_shapes_mode = action(
        host.tr("Visibility Shapes"),
        host.toggle_visibility_shapes,
        shortcuts["toggle_visibility_shapes"],
        None,
        host.tr('Toggle "Visibility Shapes" mode'),
        checkable=True,
        checked=host._config["show_shapes"],
    )

    create_mode = action(
        host.tr("Create Polygons"),
        lambda: host.toggle_draw_mode(False, create_mode="polygon"),
        shortcuts["create_polygon"],
        "polygon",
        host.tr("Start drawing polygons"),
        enabled=False,
    )
    create_brush_polygon_mode = action(
        host.tr("Create Brush Polygons"),
        host.toggle_brush_polygon_mode,
        shortcuts["create_brush_polygon"],
        "brush_polygon",
        host.tr("Toggle brush mode for drawing polygons"),
        enabled=False,
    )
    create_magic_wand_mode = action(
        host.tr("Magic Wand"),
        host.toggle_magic_wand_mode,
        shortcuts.get("create_magic_wand"),
        "magic_wand",
        host.tr(
            "Select a contiguous color region; drag to adjust tolerance; "
            "right-click to finish; press Esc to cancel"
        ),
        enabled=False,
    )
    create_rectangle_mode = action(
        host.tr("Create Rectangle"),
        lambda: host.toggle_draw_mode(False, create_mode="rectangle"),
        shortcuts["create_rectangle"],
        "rectangle",
        host.tr("Start drawing rectangles"),
        enabled=False,
    )
    create_rotation_mode = action(
        host.tr("Create Rotation"),
        lambda: host.toggle_draw_mode(False, create_mode="rotation"),
        shortcuts["create_rotation"],
        "rotation",
        host.tr("Start drawing rotations"),
        enabled=False,
    )
    create_quadrilateral_mode = action(
        host.tr("Create Quadrilateral"),
        lambda: host.toggle_draw_mode(False, create_mode="quadrilateral"),
        shortcuts["create_quadrilateral"],
        "quadrilateral",
        host.tr("Start drawing quadrilaterals (4 points, auto-closed)"),
        enabled=False,
    )
    create_circle_mode = action(
        host.tr("Create Circle"),
        lambda: host.toggle_draw_mode(False, create_mode="circle"),
        shortcuts["create_circle"],
        "circle",
        host.tr("Start drawing circles"),
        enabled=False,
    )
    create_line_mode = action(
        host.tr("Create Line"),
        lambda: host.toggle_draw_mode(False, create_mode="line"),
        shortcuts["create_line"],
        "line",
        host.tr("Start drawing lines"),
        enabled=False,
    )
    create_point_mode = action(
        host.tr("Create Point"),
        lambda: host.toggle_draw_mode(False, create_mode="point"),
        shortcuts["create_point"],
        "point",
        host.tr("Start drawing points"),
        enabled=False,
    )
    create_line_strip_mode = action(
        host.tr("Create LineStrip"),
        lambda: host.toggle_draw_mode(False, create_mode="linestrip"),
        shortcuts["create_linestrip"],
        "waypoints",
        host.tr("Start drawing linestrip. Ctrl+LeftClick ends creation."),
        enabled=False,
    )
    create_cuboid_mode = action(
        host.tr("Create Cuboid"),
        lambda: host.toggle_draw_mode(False, create_mode="cuboid"),
        shortcuts.get("create_cuboid"),
        "cuboid",
        host.tr("Start drawing cuboids from rectangle"),
        enabled=False,
    )
    digit_shortcut_0 = action(
        host.tr("Digit Shortcut 0"),
        lambda: host.create_digit_mode(0),
        "0",
        None,
        enabled=False,
    )
    digit_shortcut_1 = action(
        host.tr("Digit Shortcut 1"),
        lambda: host.create_digit_mode(1),
        "1",
        None,
        enabled=False,
    )
    digit_shortcut_2 = action(
        host.tr("Digit Shortcut 2"),
        lambda: host.create_digit_mode(2),
        "2",
        None,
        enabled=False,
    )
    digit_shortcut_3 = action(
        host.tr("Digit Shortcut 3"),
        lambda: host.create_digit_mode(3),
        "3",
        None,
        enabled=False,
    )
    digit_shortcut_4 = action(
        host.tr("Digit Shortcut 4"),
        lambda: host.create_digit_mode(4),
        "4",
        None,
        enabled=False,
    )
    digit_shortcut_5 = action(
        host.tr("Digit Shortcut 5"),
        lambda: host.create_digit_mode(5),
        "5",
        None,
        enabled=False,
    )
    digit_shortcut_6 = action(
        host.tr("Digit Shortcut 6"),
        lambda: host.create_digit_mode(6),
        "6",
        None,
        enabled=False,
    )
    digit_shortcut_7 = action(
        host.tr("Digit Shortcut 7"),
        lambda: host.create_digit_mode(7),
        "7",
        None,
        enabled=False,
    )
    digit_shortcut_8 = action(
        host.tr("Digit Shortcut 8"),
        lambda: host.create_digit_mode(8),
        "8",
        None,
        enabled=False,
    )
    digit_shortcut_9 = action(
        host.tr("Digit Shortcut 9"),
        lambda: host.create_digit_mode(9),
        "9",
        None,
        enabled=False,
    )
    edit_mode = action(
        host.tr("Edit Object"),
        host._enter_edit_mode_from_toolbar,
        shortcuts["edit_polygon"],
        "edit",
        host.tr("Move and edit the selected polygons"),
        enabled=False,
    )
    edit_brush_mode = action(
        host.tr("Edit Brush"),
        lambda checked: host.toggle_brush_mode(checked),
        shortcuts.get("edit_brush_mode", "Shift+B"),
        "brush",
        host.tr(
            "Select one polygon, then paint to add, hold Ctrl to erase, "
            "and use Alt+Wheel to resize the brush"
        ),
        enabled=False,
        checkable=True,
        checked=False,
    )
    group_selected_shapes = action(
        host.tr("Group Selected Shapes"),
        host.group_selected_shapes,
        shortcuts["group_selected_shapes"],
        "group",
        host.tr("Group shapes by assigning a same group_id"),
        enabled=True,
    )
    ungroup_selected_shapes = action(
        host.tr("Ungroup Selected Shapes"),
        host.ungroup_selected_shapes,
        shortcuts["ungroup_selected_shapes"],
        "ungroup",
        host.tr("Ungroup shapes"),
        enabled=True,
    )

    create_relation = action(
        host.tr("Create Relation"),
        host.create_relation,
        icon="line-strip",
        tip=host.tr(
            "Select exactly two shapes to create a directed relation"
        ),
        enabled=False,
    )
    manage_relations = action(
        host.tr("Manage Relations"),
        host.manage_relations,
        icon="edit",
        tip=host.tr("Review and edit directed relations"),
    )

    delete = action(
        host.tr("Delete"),
        host.delete_selected_shape,
        shortcuts["delete_polygon"],
        "cancel",
        host.tr("Delete the selected polygons"),
        enabled=False,
    )
    duplicate = action(
        host.tr("Duplicate Polygons"),
        host.duplicate_selected_shape,
        shortcuts["duplicate_polygon"],
        "copy-plus",
        host.tr("Create a duplicate of the selected polygons"),
        enabled=False,
    )
    copy = action(
        host.tr("Copy Object"),
        host.copy_selected_shape,
        shortcuts["copy_polygon"],
        "copy",
        host.tr("Copy selected polygons to clipboard"),
        enabled=False,
    )
    paste = action(
        host.tr("Paste Object"),
        host.paste_selected_shape,
        shortcuts["paste_polygon"],
        "clipboard-paste",
        host.tr("Paste copied polygons"),
        enabled=host._config["system_clipboard"],
    )
    undo_last_point = action(
        host.tr("Undo last point"),
        host.canvas.undo_last_point,
        shortcuts["undo_last_point"],
        "undo",
        host.tr("Undo last drawn point"),
        enabled=False,
    )
    remove_point = action(
        text=host.tr("Remove Selected Point"),
        slot=host.remove_selected_point,
        shortcut=shortcuts["remove_selected_point"],
        icon="circle-minus",
        tip=host.tr("Remove selected point from polygon"),
        enabled=False,
    )

    undo = action(
        host.tr("Undo"),
        host.undo_shape_edit,
        shortcuts["undo"],
        "undo",
        host.tr("Undo last add and edit of shape"),
        enabled=False,
    )
    hide_selected_polygons = action(
        host.tr("Hide Selected Polygons"),
        host.hide_selected_polygons,
        shortcuts["hide_selected_polygons"],
        "eye-off",
        host.tr("Hide selected polygons"),
        enabled=True,
    )
    show_hidden_polygons = action(
        host.tr("Show Hidden Polygons"),
        host.show_hidden_polygons,
        shortcuts["show_hidden_polygons"],
        "eye",
        host.tr("Show hidden polygons"),
        enabled=True,
    )

    overview = action(
        host.tr("Overview"),
        host.overview,
        shortcuts["show_overview"],
        icon="chart-column",
        tip=host.tr("Show annotations statistics"),
    )
    save_crop = action(
        host.tr("Save Cropped Image"),
        lambda: utils.save_crop(host),
        icon="crop",
        tip=host.tr(
            "Save cropped image. (Support rectangle/rotation/polygon shape_type)"
        ),
    )
    save_visualization_image = action(
        host.tr("Save Visualization Image"),
        lambda: utils.save_visualization(host, export_type="image"),
        icon="image-down",
        tip=host.tr("Save visualization image"),
    )
    save_visualization_video = action(
        host.tr("Save Visualization Video"),
        lambda: utils.save_visualization(host, export_type="video"),
        icon="video",
        tip=host.tr("Save visualization video"),
    )
    digit_shortcut_manager = action(
        host.tr("Digit Shortcut Manager"),
        host.digit_shortcut_manager,
        shortcuts["edit_digit_shortcut"],
        icon="edit",
        tip=host.tr(
            "Manage Digit Shortcuts: Assign Drawing Modes and Labels to Number Keys"
        ),
    )
    label_manager = action(
        host.tr("Label Manager"),
        host.label_manager,
        shortcuts["edit_labels"],
        icon="edit",
        tip=host.tr(
            "Manage Labels: Rename, Delete, Hide/Show, Adjust Color"
        ),
    )
    gid_manager = action(
        host.tr("Group ID Manager"),
        host.gid_manager,
        shortcuts["edit_group_id"],
        icon="edit",
        tip=host.tr("Manage Group ID"),
    )
    shape_manager = action(
        host.tr("Shape Manager"),
        host.shape_manager,
        shortcuts["edit_shapes"],
        icon="edit",
        tip=host.tr("Manage Shapes: Add, Delete, Remove"),
        enabled=False,
    )
    copy_coordinates = action(
        host.tr("Copy Coordinates"),
        host.copy_shape_coordinates,
        icon="map-pin",
        tip=host.tr("Copy shape coordinates to clipboard"),
        enabled=False,
    )
    union_selection = action(
        host.tr("Union Selection"),
        host.union_selection,
        shortcuts["union_selected_shapes"],
        icon="combine",
        tip=host.tr("Union multiple selected rectangle shapes"),
        enabled=False,
    )
    toggle_shape_lock = action(
        host.tr("Lock Shape"),
        host.toggle_selected_shapes_lock,
        tip=host.tr("Prevent changes to the selected shapes' coordinates"),
        checkable=True,
        enabled=False,
    )
    shape_converter = action(
        host.tr("Shape Converter"),
        lambda: utils.open_shape_converter(host),
        icon="file-cog",
        tip=host.tr("Open shape converter"),
    )
    open_chatbot = action(
        host.tr("ChatBot"),
        host.open_chatbot,
        shortcuts["open_chatbot"],
        icon="message-circle",
        tip=host.tr("Open chatbot dialog"),
    )
    open_vqa = action(
        host.tr("VQA"),
        host.open_vqa,
        shortcuts["open_vqa"],
        icon="message-circle-question-mark",
        tip=host.tr("Open VQA dialog"),
    )
    open_pointcloud = action(
        host.tr("Point Cloud"),
        host.open_pointcloud,
        shortcuts.get("open_pointcloud"),
        icon="chart-scatter",
        tip=host.tr("Open point cloud workspace"),
    )
    open_image_classifier = action(
        host.tr("Image Classifier"),
        host.open_image_classifier,
        shortcuts.get(
            "open_image_classifier", shortcuts.get("open_classifier")
        ),
        icon="folder-tree",
        tip=host.tr("Open image classifier dialog"),
    )
    open_video_classifier = action(
        host.tr("Video Classifier"),
        host.open_video_classifier,
        shortcuts.get("open_video_classifier"),
        icon="clapperboard",
        tip=host.tr("Open video classifier dialog"),
    )
    open_paddleocr = action(
        host.tr("Document Parser"),
        host.open_paddleocr,
        shortcuts["open_paddleocr"],
        icon="scan-text",
        tip=host.tr("Open document parser dialog"),
    )
    documentation = action(
        host.tr("Documentation"),
        host.documentation,
        icon="book-open",
        tip=host.tr("Show documentation"),
    )
    sponsor = action(
        host.tr("Sponsor"),
        host.sponsor,
        icon="heart-handshake",
        tip=host.tr("Open sponsor page"),
    )
    about = action(
        host.tr("About"),
        host.about,
        icon="info",
        tip=host.tr("Open about dialog"),
    )

    loop_thru_labels = action(
        host.tr("Loop Through Labels"),
        host.loop_thru_labels,
        shortcut=shortcuts["loop_thru_labels"],
        icon="loop",
        tip=host.tr("Loop through labels"),
        enabled=False,
    )
    loop_select_labels = action(
        host.tr("Loop Select Labels"),
        host.loop_select_labels,
        shortcut=shortcuts["loop_select_labels"],
        icon="circle-selection",
        tip=host.tr("Loop select labels"),
        enabled=False,
    )
    select_toggle_shapes = action(
        host.tr("Toggle Shapes Visibility"),
        host.toggle_select_all,
        icon="eye",
        tip=host.tr("Hide all shapes"),
        enabled=False,
    )
    host.select_toggle_action = select_toggle_shapes

    ultralytics_train = action(
        "Ultralytics",
        lambda: host.start_training("ultralytics"),
        icon="cpu-ai",
    )

    def planned_feature(name):
        return lambda: host.status(
            host.tr("%s is planned but not implemented yet.") % name
        )

    training_analysis = action(
        host.tr("Training Result Analysis"),
        planned_feature(host.tr("Training Result Analysis")),
        icon="chart-column",
        tip=host.tr("Planned: analyze training runs and metrics"),
    )
    sam_tool = action(
        "SAM",
        planned_feature("SAM"),
        icon="circle-selection",
        tip=host.tr("Planned: SAM prompt segmentation tool"),
    )
    rf_detr_tool = action(
        "RF-DETR",
        planned_feature("RF-DETR"),
        icon="component",
        tip=host.tr("Planned: RF-DETR model support"),
    )
    efficient_tool = action(
        "Efficient",
        planned_feature("Efficient"),
        icon="cpu-ai",
        tip=host.tr("Planned: Efficient model family support"),
    )

    zoom = QtWidgets.QWidgetAction(host)
    zoom.setDefaultWidget(host.zoom_widget)
    host.zoom_widget.setWhatsThis(
        str(
            host.tr(
                "Zoom in or out of the image. Also accessible with "
                "{} and {} from the canvas."
            )
        ).format(
            utils.fmt_shortcut(
                f"{shortcuts['zoom_in']},{shortcuts['zoom_out']}"
            ),
            host.tr("Wheel"),
        )
    )
    host.zoom_widget.setEnabled(False)

    zoom_in = action(
        host.tr("Zoom In"),
        functools.partial(host.add_zoom, 1.1),
        shortcuts["zoom_in"],
        "zoom-in",
        host.tr("Increase zoom level"),
        enabled=False,
    )
    zoom_out = action(
        host.tr("Zoom Out"),
        functools.partial(host.add_zoom, 0.9),
        shortcuts["zoom_out"],
        "zoom-out",
        host.tr("Decrease zoom level"),
        enabled=False,
    )
    zoom_org = action(
        host.tr("Original Size"),
        functools.partial(host.set_zoom, 100),
        shortcuts["zoom_to_original"],
        "scan-search",
        host.tr("Zoom to original size"),
        enabled=False,
    )
    keep_prev_scale = action(
        host.tr("Keep Previous Scale"),
        lambda x: host._config.update({"keep_prev_scale": x}),
        tip=host.tr("Keep previous zoom scale"),
        checkable=True,
        checked=host._config["keep_prev_scale"],
        enabled=True,
    )
    keep_prev_brightness = action(
        host.tr("Keep Previous Brightness"),
        lambda x: host._config.update({"keep_prev_brightness": x}),
        tip=host.tr("Keep previous brightness"),
        checkable=True,
        checked=host._config["keep_prev_brightness"],
        enabled=True,
    )
    keep_prev_contrast = action(
        host.tr("Keep Previous Contrast"),
        lambda x: host._config.update({"keep_prev_contrast": x}),
        tip=host.tr("Keep previous contrast"),
        checkable=True,
        checked=host._config["keep_prev_contrast"],
        enabled=True,
    )
    host.canvas_adjustment.opacity_pin.setChecked(True)
    for button, keep_action in (
        (host.canvas_adjustment.brightness_pin, keep_prev_brightness),
        (host.canvas_adjustment.contrast_pin, keep_prev_contrast),
    ):
        button.setChecked(keep_action.isChecked())
        button.clicked.connect(keep_action.trigger)
        keep_action.toggled.connect(button.setChecked)
    fit_window = action(
        host.tr("Fit Window"),
        host.set_fit_window,
        shortcuts["fit_window"],
        "fit-window",
        host.tr("Zoom follows window size"),
        checkable=True,
        enabled=False,
    )
    fit_window.setObjectName("fitWindow")
    fit_width = action(
        host.tr("Fit Width"),
        host.set_fit_width,
        shortcuts["fit_width"],
        "fit-width",
        host.tr("Zoom follows window width"),
        checkable=True,
        enabled=False,
    )
    show_groups = action(
        host.tr("Show Groups"),
        lambda x: host.set_canvas_params("show_groups", x),
        tip=host.tr("Show shape groups"),
        icon="tags",
        checkable=True,
        checked=host._config["show_groups"],
        enabled=True,
        auto_trigger=True,
    )
    show_masks = action(
        host.tr("Show Masks"),
        lambda x: host.set_canvas_params("show_masks", x),
        shortcut=shortcuts["show_masks"],
        tip=host.tr("Show semi-transparent masks for shapes"),
        icon="layers",
        checkable=True,
        checked=host._config["show_masks"],
        enabled=True,
        auto_trigger=True,
    )
    show_texts = action(
        host.tr("Show Texts"),
        lambda x: host.set_canvas_params("show_texts", x),
        shortcut=shortcuts["show_texts"],
        tip=host.tr("Show text above shapes"),
        icon="scan-text",
        checkable=True,
        checked=host._config["show_texts"],
        enabled=True,
        auto_trigger=True,
    )
    show_labels = action(
        host.tr("Show Labels"),
        lambda x: host.set_canvas_params("show_labels", x),
        shortcut=shortcuts["show_labels"],
        tip=host.tr("Show label inside shapes"),
        icon="tag",
        checkable=True,
        checked=host._config["show_labels"],
        enabled=True,
        auto_trigger=True,
    )
    show_scores = action(
        host.tr("Show Scores"),
        lambda x: host.set_canvas_params("show_scores", x),
        tip=host.tr("Show score inside shapes"),
        icon="badge-percent",
        checkable=True,
        checked=host._config["show_scores"],
        enabled=True,
        auto_trigger=True,
    )
    show_attributes = action(
        host.tr("Show Attributes"),
        lambda x: host.set_canvas_params("show_attributes", x),
        shortcut=shortcuts["show_attributes"],
        tip=host.tr("Show attribute inside shapes"),
        icon="list-checks",
        checkable=True,
        checked=host._config["show_attributes"],
        enabled=True,
        auto_trigger=True,
    )
    show_degrees = action(
        host.tr("Show Degress"),
        lambda x: host.set_canvas_params("show_degrees", x),
        tip=host.tr("Show degrees above rotated shapes"),
        icon="ruler",
        checkable=True,
        checked=host._config["show_degrees"],
        enabled=True,
        auto_trigger=True,
    )
    show_linking = action(
        host.tr("Show KIE Linking"),
        lambda x: host.set_canvas_params("show_linking", x),
        shortcut=shortcuts["show_linking"],
        tip=host.tr("Show KIE linking between key and value"),
        icon="link",
        checkable=True,
        checked=host._config["show_linking"],
        enabled=True,
        auto_trigger=True,
    )

    # Languages
    select_lang_en = action(
        "English",
        functools.partial(host.set_language, "en_US"),
        checkable=True,
        checked=host._config["language"] == "en_US",
        enabled=host._config["language"] != "en_US",
    )
    select_lang_zh = action(
        "中文",
        functools.partial(host.set_language, "zh_CN"),
        checkable=True,
        checked=host._config["language"] == "zh_CN",
        enabled=host._config["language"] != "zh_CN",
    )

    select_lang_jp = action(
        "日本語",
        functools.partial(host.set_language, "ja_JP"),
        checkable=True,
        checked=host._config["language"] == "ja_JP",
        enabled=host._config["language"] != "ja_JP",
    )
    select_lang_ko = action(
        "한국어",
        functools.partial(host.set_language, "ko_KR"),
        checkable=True,
        checked=host._config["language"] == "ko_KR",
        enabled=host._config["language"] != "ko_KR",
    )

    # Theme menu options (System / Light / Dark)
    theme_mode_actions = []
    theme_group = QtGui.QActionGroup(host)
    theme_group.setExclusive(True)
    host._theme_actions = {}
    current_appearance = host._config.get("theme", "auto")
    for _mode, _label, _icon in (
        ("auto", host.tr("System"), "monitor"),
        ("light", host.tr("Light"), "sun"),
        ("dark", host.tr("Dark"), "moon"),
    ):
        _act = QtGui.QAction(_label, theme_group)
        _act.setCheckable(True)
        _act.setChecked(current_appearance == _mode)
        _act.setData(_mode)
        _act.setIcon(utils.new_icon(_icon))
        _act.triggered.connect(
            functools.partial(host._on_theme_changed, _mode)
        )
        theme_mode_actions.append(_act)
        host._theme_actions[_mode] = _act

    # Upload
    upload_export_icon = "tag"
    upload_image_flags_file = action(
        host.tr("Image Flags"),
        lambda: utils.upload_image_flags_file(host),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom Image Flags File"),
    )
    upload_label_flags_file = action(
        host.tr("Label Flags"),
        lambda: utils.upload_label_flags_file(host, LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom Label Flags File"),
    )
    upload_shape_attrs_file = action(
        host.tr("Attributes"),
        lambda: utils.upload_shape_attrs_file(host, LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom Attributes File"),
    )
    upload_label_classes_file = action(
        host.tr("Label Classes"),
        lambda: utils.upload_label_classes_file(host),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom Label Classes File"),
    )
    upload_yolo_hbb_annotation = action(
        host.tr("YOLO HBB"),
        lambda: utils.upload_yolo_annotation(host, "hbb", LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Upload Custom YOLO Horizontal Bounding Boxes Annotations"
        ),
    )
    upload_yolo_obb_annotation = action(
        host.tr("YOLO OBB"),
        lambda: utils.upload_yolo_annotation(host, "obb", LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Upload Custom YOLO Oriented Bounding Boxes Annotations"
        ),
    )
    upload_yolo_seg_annotation = action(
        host.tr("YOLO Seg"),
        lambda: utils.upload_yolo_annotation(host, "seg", LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom YOLO Segmentation Annotations"),
    )
    upload_yolo_pose_annotation = action(
        host.tr("YOLO Pose"),
        lambda: utils.upload_yolo_annotation(host, "pose", LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom YOLO Pose Annotations"),
    )
    upload_voc_det_annotation = action(
        host.tr("VOC Detection"),
        lambda: utils.upload_voc_annotation(host, "rectangle"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom Pascal VOC Detection Annotations"),
    )
    upload_voc_seg_annotation = action(
        host.tr("VOC Segmentation"),
        lambda: utils.upload_voc_annotation(host, "polygon"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom Pascal VOC Segmentation Annotations"),
    )
    upload_coco_det_annotation = action(
        host.tr("COCO Detection"),
        lambda: utils.upload_coco_annotation(host, "rectangle"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom COCO Detection Annotations"),
    )
    upload_coco_seg_annotation = action(
        host.tr("COCO Segmentation"),
        lambda: utils.upload_coco_annotation(host, "polygon"),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Upload Custom COCO Instance Segmentation Annotations"
        ),
    )
    upload_coco_pose_annotation = action(
        host.tr("COCO Keypoints"),
        lambda: utils.upload_coco_annotation(host, "pose"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom COCO Keypoint Annotations"),
    )
    upload_dota_annotation = action(
        host.tr("DOTA"),
        lambda: utils.upload_dota_annotation(host),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom DOTA Annotations"),
    )
    upload_mask_annotation = action(
        host.tr("MASK"),
        lambda: utils.upload_mask_annotation(host, LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom MASK Annotations"),
    )
    upload_mot_annotation = action(
        host.tr("MOT"),
        lambda: utils.upload_mot_annotation(host, LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom Multi-Object-Tracking Annotations"),
    )
    upload_odvg_annotation = action(
        host.tr("ODVG"),
        lambda: utils.upload_odvg_annotation(host),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Upload Custom Object Detection Visual Grounding Annotations"
        ),
    )
    upload_mmgd_annotation = action(
        host.tr("MM-Grounding-DINO"),
        lambda: utils.upload_mmgd_annotation(host, LABEL_OPACITY),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom MM-Grounding-DINO Annotations"),
    )
    upload_ppocr_rec_annotation = action(
        host.tr("PPOCR Rec"),
        lambda: utils.upload_ppocr_annotation(host, "rec"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom PPOCR Recognition Annotations"),
    )
    upload_ppocr_kie_annotation = action(
        host.tr("PPOCR KIE"),
        lambda: utils.upload_ppocr_annotation(host, "kie"),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Upload Custom PPOCR Key Information Extraction (KIE - Semantic Entity Recognition & Relation Extraction) Annotations"
        ),
    )
    upload_vlm_r1_ovd_annotation = action(
        host.tr("VLM-R1 OVD"),
        lambda: utils.upload_vlm_r1_ovd_annotation(host),
        None,
        icon=upload_export_icon,
        tip=host.tr("Upload Custom VLM-R1 OVD Annotations"),
    )

    # Export
    export_yolo_hbb_annotation = action(
        host.tr("YOLO HBB"),
        lambda: utils.export_yolo_annotation(host, "hbb"),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Export Custom YOLO Horizontal Bounding Boxes Annotations"
        ),
    )
    export_yolo_obb_annotation = action(
        host.tr("YOLO OBB"),
        lambda: utils.export_yolo_annotation(host, "obb"),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Export Custom YOLO Oriented Bounding Boxes Annotations"
        ),
    )
    export_yolo_seg_annotation = action(
        host.tr("YOLO Seg"),
        lambda: utils.export_yolo_annotation(host, "seg"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom YOLO Segmentation Annotations"),
    )
    export_yolo_pose_annotation = action(
        host.tr("YOLO Pose"),
        lambda: utils.export_yolo_annotation(host, "pose"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom YOLO Pose Annotations"),
    )
    export_voc_det_annotation = action(
        host.tr("VOC Detection"),
        lambda: utils.export_voc_annotation(host, "rectangle"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom PASCAL VOC Detection Annotations"),
    )
    export_voc_seg_annotation = action(
        host.tr("VOC Segmentation"),
        lambda: utils.export_voc_annotation(host, "polygon"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom PASCAL VOC Segmentation Annotations"),
    )
    export_coco_det_annotation = action(
        host.tr("COCO Detection"),
        lambda: utils.export_coco_annotation(host, "rectangle"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom COCO Rectangle Annotations"),
    )
    export_coco_seg_annotation = action(
        host.tr("COCO Segmentation"),
        lambda: utils.export_coco_annotation(host, "polygon"),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Export Custom COCO Instance Segmentation Annotations"
        ),
    )
    export_coco_pose_annotation = action(
        host.tr("COCO Keypoints"),
        lambda: utils.export_coco_annotation(host, "pose"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom COCO Keypoint Annotations"),
    )
    export_dota_annotation = action(
        host.tr("DOTA"),
        lambda: utils.export_dota_annotation(host),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom DOTA Annotations"),
    )
    export_mask_annotation = action(
        host.tr("MASK"),
        lambda: utils.export_mask_annotation(host),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom MASK Annotations - RGB/Gray"),
    )
    export_mot_annotation = action(
        host.tr("MOT"),
        lambda: utils.export_mot_annotation(host, "mot"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom Multi-Object-Tracking Annotations"),
    )
    export_mots_annotation = action(
        host.tr("MOTS"),
        lambda: utils.export_mot_annotation(host, "mots"),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Export Custom Multi-Object-Tracking-Segmentation Annotations"
        ),
    )
    export_odvg_annotation = action(
        host.tr("ODVG"),
        lambda: utils.export_odvg_annotation(host),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Export Custom Object Detection Visual Grounding Annotations"
        ),
    )
    export_pporc_rec_annotation = action(
        host.tr("PPOCR Rec"),
        lambda: utils.export_pporc_annotation(host, "rec"),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom PPOCR Recognition Annotations"),
    )
    export_pporc_kie_annotation = action(
        host.tr("PPOCR KIE"),
        lambda: utils.export_pporc_annotation(host, "kie"),
        None,
        icon=upload_export_icon,
        tip=host.tr(
            "Export Custom PPOCR Key Information Extraction (KIE - Semantic Entity Recognition & Relation Extraction) Annotations"
        ),
    )
    export_vlm_r1_ovd_annotation = action(
        host.tr("VLM-R1 OVD"),
        lambda: utils.export_vlm_r1_ovd_annotation(host),
        None,
        icon=upload_export_icon,
        tip=host.tr("Export Custom VLM-R1 OVD Annotations"),
    )

    # Group zoom controls into a list for easier toggling.
    zoom_actions = (
        host.zoom_widget,
        zoom_in,
        zoom_out,
        zoom_org,
        fit_window,
        fit_width,
    )
    host.zoom_mode = host.FIT_WINDOW
    fit_window.setChecked(True)
    host.scalers = {
        host.FIT_WINDOW: host.scale_fit_window,
        host.FIT_WIDTH: host.scale_fit_width,
        # Set to one to scale to 100% when loading files.
        host.MANUAL_ZOOM: lambda: 1,
    }

    edit = action(
        host.tr("Edit Label"),
        host.edit_label,
        shortcuts["edit_label"],
        "edit",
        host.tr("Modify the label of the selected polygon"),
        enabled=False,
    )

    fill_drawing = action(
        host.tr("Fill Drawing Polygon"),
        host.canvas.set_fill_drawing,
        None,
        "palette",
        host.tr("Fill polygon while drawing"),
        checkable=True,
        enabled=True,
    )
    fill_drawing.trigger()

    show_navigator = action(
        host.tr("Navigator"),
        host.toggle_navigator,
        shortcuts["show_navigator"],
        "compass",
        host.tr("Show/hide the navigator window"),
        checkable=True,
        enabled=True,
    )

    show_image_tags = action(
        host.tr("Image Tags"),
        host.show_image_tags_editor,
        shortcuts["toggle_image_tags"],
        tip=host.tr("Edit image tags"),
        enabled=True,
        icon="tags",
    )
    show_image_tags.setObjectName("toggleImageTags")
    theme = get_theme()
    # The tags editor is a right-sidebar tab now, so the action only opens it;
    # it is no longer a checkable show/hide switch for a canvas-bottom bar.
    show_image_tags.setIcon(
        get_icon("panel-down", theme["text"], theme["primary"])
    )

    # AI Actions
    toggle_auto_labeling_widget = action(
        host.tr("Auto Labeling"),
        host.toggle_auto_labeling_widget,
        shortcuts["auto_label"],
        "brain",
        host.tr("Auto Labeling"),
    )

    host.label_list.setContextMenuPolicy(
        Qt.ContextMenuPolicy.NoContextMenu
    )

    # Store actions for further handling.
    actions = utils.Struct(
        save_auto=save_auto,
        save_with_image_data=save_with_image_data,
        change_output_dir=change_output_dir,
        save=save,
        save_as=save_as,
        open=open_,
        open_video=openvideo,
        open_dir=opendir,
        import_project=import_project,
        show_trash=show_trash,
        close=close,
        toggle_compare_view=toggle_compare_view,
        delete_file=delete_file,
        delete_image_file=delete_image_file,
        toggle_annotation_checked=toggle_annotation_checked,
        clear_annotation_checked=clear_annotation_checked,
        fail_annotation_checked=fail_annotation_checked,
        keep_prev_mode=keep_prev_mode,
        auto_use_last_label_mode=auto_use_last_label_mode,
        auto_use_last_gid_mode=auto_use_last_gid_mode,
        use_system_clipboard=use_system_clipboard,
        visibility_shapes_mode=visibility_shapes_mode,
        run_all_images=run_all_images,
        union_selection=union_selection,
        delete=delete,
        edit=edit,
        create_relation=create_relation,
        manage_relations=manage_relations,
        duplicate=duplicate,
        copy=copy,
        copy_coordinates=copy_coordinates,
        paste=paste,
        toggle_shape_lock=toggle_shape_lock,
        overview=overview,
        save_visualization_image=save_visualization_image,
        save_visualization_video=save_visualization_video,
        undo_last_point=undo_last_point,
        undo=undo,
        remove_point=remove_point,
        create_mode=create_mode,
        create_brush_polygon_mode=create_brush_polygon_mode,
        create_magic_wand_mode=create_magic_wand_mode,
        edit_mode=edit_mode,
        edit_brush_mode=edit_brush_mode,
        create_rectangle_mode=create_rectangle_mode,
        create_cuboid_mode=create_cuboid_mode,
        create_rotation_mode=create_rotation_mode,
        create_quadrilateral_mode=create_quadrilateral_mode,
        create_circle_mode=create_circle_mode,
        create_line_mode=create_line_mode,
        create_point_mode=create_point_mode,
        create_line_strip_mode=create_line_strip_mode,
        digit_shortcut_0=digit_shortcut_0,
        digit_shortcut_1=digit_shortcut_1,
        digit_shortcut_2=digit_shortcut_2,
        digit_shortcut_3=digit_shortcut_3,
        digit_shortcut_4=digit_shortcut_4,
        digit_shortcut_5=digit_shortcut_5,
        digit_shortcut_6=digit_shortcut_6,
        digit_shortcut_7=digit_shortcut_7,
        digit_shortcut_8=digit_shortcut_8,
        digit_shortcut_9=digit_shortcut_9,
        upload_image_flags_file=upload_image_flags_file,
        upload_label_flags_file=upload_label_flags_file,
        upload_shape_attrs_file=upload_shape_attrs_file,
        upload_label_classes_file=upload_label_classes_file,
        upload_yolo_hbb_annotation=upload_yolo_hbb_annotation,
        upload_yolo_obb_annotation=upload_yolo_obb_annotation,
        upload_yolo_seg_annotation=upload_yolo_seg_annotation,
        upload_yolo_pose_annotation=upload_yolo_pose_annotation,
        upload_voc_det_annotation=upload_voc_det_annotation,
        upload_voc_seg_annotation=upload_voc_seg_annotation,
        upload_coco_det_annotation=upload_coco_det_annotation,
        upload_coco_seg_annotation=upload_coco_seg_annotation,
        upload_coco_pose_annotation=upload_coco_pose_annotation,
        upload_dota_annotation=upload_dota_annotation,
        upload_mask_annotation=upload_mask_annotation,
        upload_mot_annotation=upload_mot_annotation,
        upload_odvg_annotation=upload_odvg_annotation,
        upload_mmgd_annotation=upload_mmgd_annotation,
        upload_ppocr_rec_annotation=upload_ppocr_rec_annotation,
        upload_ppocr_kie_annotation=upload_ppocr_kie_annotation,
        upload_vlm_r1_ovd_annotation=upload_vlm_r1_ovd_annotation,
        export_yolo_hbb_annotation=export_yolo_hbb_annotation,
        export_yolo_obb_annotation=export_yolo_obb_annotation,
        export_yolo_seg_annotation=export_yolo_seg_annotation,
        export_yolo_pose_annotation=export_yolo_pose_annotation,
        export_voc_det_annotation=export_voc_det_annotation,
        export_voc_seg_annotation=export_voc_seg_annotation,
        export_coco_det_annotation=export_coco_det_annotation,
        export_coco_seg_annotation=export_coco_seg_annotation,
        export_coco_pose_annotation=export_coco_pose_annotation,
        export_dota_annotation=export_dota_annotation,
        export_mask_annotation=export_mask_annotation,
        export_mot_annotation=export_mot_annotation,
        export_mots_annotation=export_mots_annotation,
        export_odvg_annotation=export_odvg_annotation,
        export_pporc_rec_annotation=export_pporc_rec_annotation,
        export_pporc_kie_annotation=export_pporc_kie_annotation,
        export_vlm_r1_ovd_annotation=export_vlm_r1_ovd_annotation,
        zoom=zoom,
        zoom_in=zoom_in,
        zoom_out=zoom_out,
        zoom_org=zoom_org,
        keep_prev_scale=keep_prev_scale,
        keep_prev_brightness=keep_prev_brightness,
        keep_prev_contrast=keep_prev_contrast,
        fit_window=fit_window,
        fit_width=fit_width,
        show_groups=show_groups,
        show_masks=show_masks,
        show_texts=show_texts,
        show_labels=show_labels,
        show_scores=show_scores,
        show_degrees=show_degrees,
        show_attributes=show_attributes,
        show_linking=show_linking,
        show_navigator=show_navigator,
        show_image_tags=show_image_tags,
        zoom_actions=zoom_actions,
        jump_next_images=jump_next_images,
        jump_prev_images=jump_prev_images,
        open_next_image=open_next_image,
        open_prev_image=open_prev_image,
        open_next_unchecked_image=open_next_unchecked_image,
        open_prev_unchecked_image=open_prev_unchecked_image,
        open_chatbot=open_chatbot,
        open_vqa=open_vqa,
        open_pointcloud=open_pointcloud,
        open_image_classifier=open_image_classifier,
        open_classifier=open_image_classifier,
        open_video_classifier=open_video_classifier,
        open_paddleocr=open_paddleocr,
        toggle_auto_labeling_widget=toggle_auto_labeling_widget,
        digit_shortcut_manager=digit_shortcut_manager,
        label_manager=label_manager,
        gid_manager=gid_manager,
        shape_manager=shape_manager,
        loop_thru_labels=loop_thru_labels,
        loop_select_labels=loop_select_labels,
        select_toggle_shapes=select_toggle_shapes,
        file_menu_actions=(
            open_,
            openvideo,
            opendir,
            save,
            save_as,
            close,
        ),
        tool=(),
        # XXX: need to add some actions here to activate the shortcut
        editMenu=(
            edit,
            create_relation,
            manage_relations,
            duplicate,
            delete,
            copy,
            paste,
            None,
            undo,
            undo_last_point,
            None,
            copy_coordinates,
            remove_point,
            union_selection,
            None,
            keep_prev_mode,
            auto_use_last_label_mode,
            auto_use_last_gid_mode,
            use_system_clipboard,
            visibility_shapes_mode,
        ),
        # Menu shown at right click on the canvas.  Tool modes are not
        # repeated here: they belong to the toolbar and the Edit menu.
        # What stays is the contextual work on the object under the cursor
        # (lock, label, relations, clipboard, undo) plus the view/status
        # actions that exist only in this menu.
        canvas_menu=(
            edit,
            create_relation,
            manage_relations,
            toggle_shape_lock,
            None,
            copy_coordinates,
            union_selection,
            duplicate,
            copy,
            paste,
            None,
            delete,
            undo,
            undo_last_point,
            remove_point,
        ),
        on_load_active=(
            close,
            create_mode,
            create_brush_polygon_mode,
            create_magic_wand_mode,
            create_rectangle_mode,
            create_cuboid_mode,
            create_rotation_mode,
            create_quadrilateral_mode,
            create_circle_mode,
            create_line_mode,
            create_point_mode,
            create_line_strip_mode,
            digit_shortcut_0,
            digit_shortcut_1,
            digit_shortcut_2,
            digit_shortcut_3,
            digit_shortcut_4,
            digit_shortcut_5,
            digit_shortcut_6,
            digit_shortcut_7,
            digit_shortcut_8,
            digit_shortcut_9,
            edit_mode,
            toggle_annotation_checked,
            clear_annotation_checked,
            fail_annotation_checked,
            shape_manager,
            loop_thru_labels,
            loop_select_labels,
            select_toggle_shapes,
        ),
        on_shapes_present=(save_as, delete),
        hide_selected_polygons=hide_selected_polygons,
        show_hidden_polygons=show_hidden_polygons,
        group_selected_shapes=group_selected_shapes,
        ungroup_selected_shapes=ungroup_selected_shapes,
    )

    for digit_action in (
        actions.digit_shortcut_0,
        actions.digit_shortcut_1,
        actions.digit_shortcut_2,
        actions.digit_shortcut_3,
        actions.digit_shortcut_4,
        actions.digit_shortcut_5,
        actions.digit_shortcut_6,
        actions.digit_shortcut_7,
        actions.digit_shortcut_8,
        actions.digit_shortcut_9,
    ):
        host.addAction(digit_action)

    host.canvas.vertex_selected.connect(
        actions.remove_point.setEnabled
    )
    actions.about = about
    actions.documentation = documentation
    actions.fill_drawing = fill_drawing
    actions.open_settings = open_settings
    actions.save_crop = save_crop
    actions.select_lang_en = select_lang_en
    actions.select_lang_jp = select_lang_jp
    actions.select_lang_ko = select_lang_ko
    actions.select_lang_zh = select_lang_zh
    actions.shape_converter = shape_converter
    actions.sponsor = sponsor
    actions.ultralytics_train = ultralytics_train
    actions.training_analysis = training_analysis
    actions.sam_tool = sam_tool
    actions.rf_detr_tool = rf_detr_tool
    actions.efficient_tool = efficient_tool
    actions.tool = (
        jump_next_images,
        open_next_image,
        open_prev_image,
        jump_prev_images,
        save,
        delete_file,
        None,
        create_mode,
        actions.create_brush_polygon_mode,
        actions.create_magic_wand_mode,
        actions.create_rectangle_mode,
        actions.create_cuboid_mode,
        actions.create_rotation_mode,
        actions.create_quadrilateral_mode,
        actions.create_circle_mode,
        actions.create_line_mode,
        actions.create_point_mode,
        actions.create_line_strip_mode,
        None,
        edit_brush_mode,
        edit_mode,
        create_relation,
        delete,
        undo,
        loop_thru_labels,
        loop_select_labels,
        select_toggle_shapes,
        fit_window,
        fit_width,
        None,
        toggle_auto_labeling_widget,
        run_all_images,
        None,
        show_masks,
        show_texts,
        show_labels,
        show_scores,
        show_degrees,
        show_attributes,
        show_linking,
        show_groups,
        group_selected_shapes,
        ungroup_selected_shapes,
    )
    actions.theme_mode_actions = tuple(theme_mode_actions)
    return actions
