"""Menu construction for the labeling window.

The menus consume the action registry built by
:func:`anylabeling.views.labeling.actions.builder.build_actions`, so the action
definitions and their menu placement stay in one place each.
"""

from PyQt6 import QtWidgets

from .. import utils

# pylupdate6 only records `tr()` calls inside class bodies.  These
# modules also translate text through `host.tr`/`self.tr` in free
# functions and helpers, where the receiver is the LabelingWidget; the
# constant tells `scripts/translation_scan.py` which context to use
# (see docs/dev/CODE_STRUCTURE_REPORT.md).
TR_CONTEXT = "LabelingWidget"


def build_menus(host):
    """Create the top-level menus of the labeling window."""
    menus = utils.Struct(
        file=host.menu(host.tr("File")),
        edit=host.menu(host.tr("Edit")),
        view=host.menu(host.tr("View")),
        theme=host.menu(host.tr("Theme")),
        language=host.menu(host.tr("Language")),
        upload=host.menu(host.tr("Upload")),
        export=host.menu(host.tr("Export")),
        tool=host.menu(host.tr("Tool")),
        workflow=host.menu(host.tr("Workflow")),
        train=host.menu(host.tr("Train")),
        help=host.menu(host.tr("Help")),
        recent_files=QtWidgets.QMenu(host.tr("Open Recent")),
    )
    menus.recent_files.setIcon(utils.new_icon("rotate-ccw-clock"))
    menus.recent_files.aboutToShow.connect(host.update_file_menu)
    host.canvas_label_filter_menu_0 = None
    host.canvas_gid_filter_menu_0 = None
    host.canvas_label_filter_menu_1 = None
    host.canvas_gid_filter_menu_1 = None

    utils.add_actions(
        menus.file,
        (
            host.actions.open,
            host.actions.open_next_image,
            host.actions.open_prev_image,
            host.actions.open_next_unchecked_image,
            host.actions.open_prev_unchecked_image,
            host.actions.open_dir,
            host.actions.open_video,
            host.actions.import_project,
            host.actions.dataset_center,
            host.actions.show_trash,
            host.actions.toggle_compare_view,
            menus.recent_files,
            host.actions.save,
            host.actions.save_as,
            host.actions.save_auto,
            host.actions.save_with_image_data,
            host.actions.change_output_dir,
            host.actions.close,
            host.actions.delete_file,
            host.actions.delete_image_file,
            None,
            host.actions.open_settings,
        ),
    )
    utils.add_actions(
        menus.train,
        (
            host.actions.ultralytics_train,
            None,
            host.actions.training_analysis,
            host.actions.sam_tool,
            host.actions.rf_detr_tool,
            host.actions.efficient_tool,
        ),
    )
    utils.add_actions(
        menus.workflow,
        (
            host.actions.open_chatbot,
            host.actions.open_vqa,
            host.actions.open_classifier,
            host.actions.open_paddleocr,
            host.actions.open_video_classifier,
            host.actions.open_pointcloud,
        ),
    )
    utils.add_actions(
        menus.tool,
        (
            host.actions.overview,
            None,
            host.actions.save_crop,
            host.actions.save_visualization_image,
            host.actions.save_visualization_video,
            None,
            host.actions.digit_shortcut_manager,
            host.actions.label_manager,
            host.actions.gid_manager,
            host.actions.shape_manager,
            None,
            host.actions.shape_converter,
        ),
    )
    utils.add_actions(
        menus.help,
        (
            host.actions.documentation,
            host.actions.sponsor,
            None,
            host.actions.about,
        ),
    )
    utils.add_actions(
        menus.language,
        (
            host.actions.select_lang_en,
            host.actions.select_lang_zh,
            host.actions.select_lang_jp,
            host.actions.select_lang_ko,
        ),
    )
    utils.add_actions(menus.theme, host.actions.theme_mode_actions)
    utils.add_actions(
        menus.upload,
        (
            host.actions.upload_image_flags_file,
            host.actions.upload_label_flags_file,
            host.actions.upload_label_classes_file,
            None,
            host.actions.upload_yolo_hbb_annotation,
            host.actions.upload_yolo_obb_annotation,
            host.actions.upload_yolo_seg_annotation,
            host.actions.upload_yolo_pose_annotation,
            None,
            host.actions.upload_voc_det_annotation,
            host.actions.upload_voc_seg_annotation,
            None,
            host.actions.upload_coco_det_annotation,
            host.actions.upload_coco_seg_annotation,
            host.actions.upload_coco_pose_annotation,
            None,
            host.actions.upload_dota_annotation,
            host.actions.upload_mask_annotation,
            host.actions.upload_mot_annotation,
            host.actions.upload_odvg_annotation,
            host.actions.upload_mmgd_annotation,
            None,
            host.actions.upload_ppocr_rec_annotation,
            host.actions.upload_ppocr_kie_annotation,
            None,
            host.actions.upload_vlm_r1_ovd_annotation,
        ),
    )
    utils.add_actions(
        menus.export,
        (
            host.actions.export_yolo_hbb_annotation,
            host.actions.export_yolo_obb_annotation,
            host.actions.export_yolo_seg_annotation,
            host.actions.export_yolo_pose_annotation,
            None,
            host.actions.export_voc_det_annotation,
            host.actions.export_voc_seg_annotation,
            None,
            host.actions.export_coco_det_annotation,
            host.actions.export_coco_seg_annotation,
            host.actions.export_coco_pose_annotation,
            None,
            host.actions.export_dota_annotation,
            host.actions.export_mask_annotation,
            host.actions.export_odvg_annotation,
            None,
            host.actions.export_mot_annotation,
            host.actions.export_mots_annotation,
            None,
            host.actions.export_pporc_rec_annotation,
            host.actions.export_pporc_kie_annotation,
            None,
            host.actions.export_vlm_r1_ovd_annotation,
        ),
    )
    utils.add_actions(
        menus.view,
        (
            host.actions.show_navigator,
            host.actions.show_image_tags,
            host.actions.fill_drawing,
            host.actions.loop_thru_labels,
            host.actions.loop_select_labels,
            None,
            host.actions.zoom_in,
            host.actions.zoom_out,
            host.actions.zoom_org,
            None,
            host.actions.keep_prev_scale,
            host.actions.keep_prev_brightness,
            host.actions.keep_prev_contrast,
            None,
            host.actions.fit_window,
            host.actions.fit_width,
            None,
            host.actions.show_masks,
            host.actions.show_texts,
            host.actions.show_labels,
            host.actions.show_scores,
            host.actions.show_degrees,
            host.actions.show_attributes,
            host.actions.show_linking,
            host.actions.show_groups,
            host.actions.hide_selected_polygons,
            host.actions.show_hidden_polygons,
            host.actions.group_selected_shapes,
            host.actions.ungroup_selected_shapes,
        ),
    )

    host._view_menu_filter = utils.StayOpenMenuFilter(menus.view)
    menus.view.installEventFilter(host._view_menu_filter)

    menus.file.aboutToShow.connect(host.update_file_menu)
    return menus
