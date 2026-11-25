import json
import jsonlines
import os
import os.path as osp
import time
import yaml

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from anylabeling.services.dataset.annotation_import import (
    OUTCOME_SKIPPED,
    OUTCOME_WRITTEN,
    store_annotation,
)
from anylabeling.views.labeling.label_converter import LabelConverter
from anylabeling.views.labeling.logger import logger
from anylabeling.views.labeling.widgets import Popup
from anylabeling.views.labeling.widgets.upload_dialogs import (
    UploadCategorySection,
    UploadConfirmDialog,
    UploadFolderDialog,
    UploadProgressDialog,
)
from anylabeling.views.labeling.utils.qt import new_icon_path
from anylabeling.views.labeling.utils.style import *
from anylabeling.views.labeling.utils.export import _check_filename_exist
from anylabeling.views.labeling.utils.yolo_import import (
    ClassSource,
    SOURCE_DATASET,
    SOURCE_PICKED,
    dataset_category_names,
    detect_class_source,
    guess_label_dir,
    read_classes_file,
    resolve_label_dir,
)

# pylupdate6 only records `tr()` calls inside class bodies.  These
# modules also translate text through `host.tr`/`self.tr` in free
# functions and helpers, where the receiver is the LabelingWidget; the
# constant tells `scripts/translation_scan.py` which context to use
# (see docs/dev/CODE_STRUCTURE_REPORT.md).
TR_CONTEXT = "LabelingWidget"


def _refresh_uploaded_file_items(self):
    for index in range(self.file_list_widget.count()):
        item = self.file_list_widget.item(index)
        image_file = item.text()
        label_file = osp.splitext(image_file)[0] + ".json"
        if self.output_dir:
            label_file = osp.join(self.output_dir, osp.basename(label_file))
        check_state = (
            Qt.CheckState.Checked
            if osp.isfile(label_file)
            else Qt.CheckState.Unchecked
        )
        item.setCheckState(check_state)
        self._set_file_item_checked(item, self._label_file_checked(label_file))


def _refresh_after_annotation_upload(self):
    _refresh_uploaded_file_items(self)
    self.load_file(self.filename)
    panel = getattr(self, "label_manager_widget", None)
    if panel is not None:
        panel.invalidate()


def _reject_dataset_mode_upload(host):
    """Refuse a JSON-only upload while a dataset database is open.

    The dataset tables are authoritative in database mode, so writing a JSON
    sidecar would look successful and change nothing.  Only the YOLO formats
    can be stored in the database so far (fork.49); the remaining adapters
    arrive with the P3b import work.
    """

    if getattr(host, "dataset_repository", None) is None:
        return False
    popup = Popup(
        host.tr(
            "This annotation format cannot be imported into a dataset yet.\n"
            "Dataset import currently supports YOLO detection, segmentation, "
            "OBB and pose uploads only."
        ),
        host,
        icon=new_icon_path("warning", "svg"),
    )
    popup.show_popup(host, position="center")
    return True


class UploadPPOCRThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, converter, input_file, output_path, image_path, mode):
        super().__init__()
        self.converter = converter
        self.input_file = input_file
        self.output_path = output_path
        self.image_path = image_path
        self.mode = mode

    def run(self):
        try:
            time.sleep(1)

            self.converter.ppocr_to_custom(
                input_file=self.input_file,
                output_path=self.output_path,
                image_path=self.image_path,
                mode=self.mode,
            )

            self.finished.emit(True, "")

        except Exception as e:
            self.finished.emit(False, str(e))


class UploadOdvgThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, converter, input_file, output_path):
        super().__init__()
        self.converter = converter
        self.input_file = input_file
        self.output_path = output_path

    def run(self):
        try:
            time.sleep(1)

            self.converter.odvg_to_custom(
                input_file=self.input_file,
                output_path=self.output_path,
            )

            self.finished.emit(True, "")

        except Exception as e:
            self.finished.emit(False, str(e))


class UploadMotThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, converter, gt_file, output_path, image_path):
        super().__init__()
        self.converter = converter
        self.gt_file = gt_file
        self.output_path = output_path
        self.image_path = image_path

    def run(self):
        try:
            time.sleep(1)

            self.converter.mot_to_custom(
                input_file=self.gt_file,
                output_path=self.output_path,
                image_path=self.image_path,
            )

            self.finished.emit(True, "")

        except Exception as e:
            self.finished.emit(False, str(e))


class UploadCocoThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, converter, input_file, output_dir_path, mode):
        super().__init__()
        self.converter = converter
        self.input_file = input_file
        self.output_dir_path = output_dir_path
        self.mode = mode

    def run(self):
        try:
            time.sleep(1)

            self.converter.coco_to_custom(
                input_file=self.input_file,
                output_dir_path=self.output_dir_path,
                mode=self.mode,
            )

            self.finished.emit(True, "")

        except Exception as e:
            self.finished.emit(False, str(e))


def upload_vlm_r1_ovd_annotation(self):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    filter = "Attribute Files (*.jsonl);;All Files (*)"
    input_file, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a custom vlm_r1_ovd annotation file"),
        "",
        filter,
    )

    if not input_file:
        return

    output_dir_path = osp.dirname(self.filename)
    if self.output_dir:
        output_dir_path = self.output_dir

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    image_list = self.image_list if self.image_list else [self.filename]
    progress_dialog = UploadProgressDialog(self, maximum=len(image_list))

    converter = LabelConverter()

    try:
        # parse input_data
        input_data = {}
        with jsonlines.open(input_file, "r") as reader:
            for data in list(reader):
                image_path = osp.basename(data["image"])
                input_data[image_path] = data["conversations"][1]["value"]

        for i, image_file in enumerate(image_list):
            image_filename = osp.basename(image_file)
            label_filename = osp.splitext(image_filename)[0] + ".json"
            output_file = osp.join(output_dir_path, label_filename)

            converter.vlm_r1_ovd_to_custom(
                input_data=input_data[image_filename],
                output_file=output_file,
                image_file=image_file,
            )

            progress_dialog.setValue(i)
            if progress_dialog.wasCanceled():
                break

        progress_dialog.close()
        template = self.tr(
            "Uploading annotations successfully!\n"
            "Results have been saved to:\n"
            "%s"
        )
        message_text = template % output_dir_path
        popup = Popup(
            message_text,
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

        _refresh_after_annotation_upload(self)

    except Exception as e:
        progress_dialog.close()
        message = f"Error occurred while uploading annotations: {str(e)}"
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def upload_ppocr_annotation(self, mode):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    if mode == "rec":
        filter = "Attribute Files (*.txt);;All Files (*)"
        input_file, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select a custom annotation file (Label.txt)"),
            "",
            filter,
        )

        if not input_file:
            return

    elif mode == "kie":
        filter = "Attribute Files (*.json);;All Files (*)"
        input_file, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select a custom annotation file (ppocr_kie.json)"),
            "",
            filter,
        )

        if not input_file:
            return

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    progress_dialog = UploadProgressDialog(self, maximum=0)

    converter = LabelConverter()
    image_path = osp.dirname(self.filename)
    output_path = osp.dirname(self.filename)
    if self.output_dir:
        output_path = self.output_dir
    self.upload_thread = UploadPPOCRThread(
        converter, input_file, output_path, image_path, mode
    )

    def on_upload_finished(success, error_msg):
        progress_dialog.close()
        if success:
            _refresh_after_annotation_upload(self)

            popup = Popup(
                self.tr("Uploading annotations successfully!"),
                self,
                icon=new_icon_path("copy-green", "svg"),
            )
            popup.show_popup(self, popup_height=65, position="center")
        else:
            message = (
                f"Error occurred while uploading annotations: {str(error_msg)}"
            )
            logger.error(message)
            popup = Popup(
                message,
                self,
                icon=new_icon_path("error", "svg"),
            )
            popup.show_popup(self, position="center")

    self.upload_thread.finished.connect(on_upload_finished)

    progress_dialog.show()
    self.upload_thread.start()

    progress_dialog.canceled.connect(self.upload_thread.terminate)


def upload_odvg_annotation(self):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    filter = "OD Files (*.json *.jsonl);;All Files (*)"
    input_file, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific OD file"),
        "",
        filter,
    )

    if not input_file:
        return

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    progress_dialog = UploadProgressDialog(self, maximum=0)

    converter = LabelConverter()
    output_path = osp.dirname(self.filename)
    if self.output_dir:
        output_path = self.output_dir
    self.upload_thread = UploadOdvgThread(converter, input_file, output_path)

    def on_upload_finished(success, error_msg):
        progress_dialog.close()
        if success:
            _refresh_after_annotation_upload(self)

            popup = Popup(
                self.tr("Uploading annotations successfully!"),
                self,
                icon=new_icon_path("copy-green", "svg"),
            )
            popup.show_popup(self, popup_height=65, position="center")
        else:
            message = (
                f"Error occurred while uploading annotations: {str(error_msg)}"
            )
            logger.error(message)
            popup = Popup(
                message,
                self,
                icon=new_icon_path("error", "svg"),
            )
            popup.show_popup(self, position="center")

    self.upload_thread.finished.connect(on_upload_finished)

    progress_dialog.show()
    self.upload_thread.start()

    progress_dialog.canceled.connect(self.upload_thread.terminate)


def upload_mmgd_annotation(self, LABEL_OPACITY):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    filter = "Classes Files (*.txt);;All Files (*)"
    classes_file, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific classes file"),
        "",
        filter,
    )
    if not classes_file:
        return

    try:
        with open(classes_file, "r", encoding="utf-8") as f:
            classes = f.read().splitlines()
    except Exception as e:
        popup = Popup(
            self.tr("Error reading classes file: %s") % str(e),
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")
        return

    section = UploadCategorySection(classes)

    def build_categories(dialog):
        dialog.body.addWidget(section)

    dialog = UploadFolderDialog(
        self,
        placeholder=self.tr(
            "Please select a folder containing annotation files"
        ),
        extra_builder=build_categories,
    )
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return

    selected = section.selected()
    if not selected:
        popup = Popup(
            self.tr("Please select at least one category!"),
            self,
            icon=new_icon_path("warning", "svg"),
        )
        popup.show_popup(self, position="center")
        return
    labels = [name for name, _threshold in selected]
    thresholds = dict(selected)

    label_dir_path = dialog.folder()
    image_dir_path = osp.dirname(self.filename)
    image_file_list = os.listdir(image_dir_path)
    label_file_list = os.listdir(label_dir_path)
    output_dir_path = self.output_dir if self.output_dir else image_dir_path
    converter = LabelConverter(classes_file=classes_file)

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    progress_dialog = UploadProgressDialog(self, maximum=len(image_file_list))

    try:
        for i, image_filename in enumerate(image_file_list):
            label_filename = osp.splitext(image_filename)[0] + ".json"
            if (
                image_filename.endswith(".json")
                or label_filename not in label_file_list
            ):
                continue

            converter.mmgd_to_custom(
                input_file=osp.join(label_dir_path, label_filename),
                output_file=osp.join(output_dir_path, label_filename),
                image_file=osp.join(image_dir_path, image_filename),
                labels=labels,
                thresholds=thresholds,
            )

            progress_dialog.setValue(i)
            if progress_dialog.wasCanceled():
                break

        progress_dialog.close()
        template = self.tr(
            "Uploading annotations successfully!\n"
            "Results have been saved to:\n"
            "%s"
        )
        message_text = template % output_dir_path
        popup = Popup(
            message_text,
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

        for label in labels:
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.unique_label_list.set_item_label(
                    item, label, rgb, LABEL_OPACITY
                )

        _refresh_after_annotation_upload(self)

    except Exception as e:
        progress_dialog.close()
        message = f"Error occurred while uploading annotations: {str(e)}"
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def upload_mot_annotation(self, LABEL_OPACITY):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    filter = "Classes Files (*.txt);;All Files (*)"
    classes_file, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific classes file"),
        "",
        filter,
    )

    if not classes_file:
        return

    filter = "Gt Files (*.txt);;All Files (*)"
    gt_file, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific gt file"),
        "",
        filter,
    )

    if not gt_file:
        popup = Popup(
            self.tr("Please select a specific gt file!"),
            self,
            icon=new_icon_path("warning", "svg"),
        )
        popup.show_popup(self, position="center")
        return

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    # Initialize unique labels
    with open(classes_file, "r", encoding="utf-8") as f:
        labels = f.read().splitlines()
        for label in labels:
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.unique_label_list.set_item_label(
                    item, label, rgb, LABEL_OPACITY
                )

    progress_dialog = UploadProgressDialog(self, maximum=0)

    converter = LabelConverter(classes_file=classes_file)
    image_path = osp.dirname(self.filename)
    output_path = image_path
    if self.output_dir:
        output_path = self.output_dir
    self.upload_thread = UploadMotThread(
        converter, gt_file, output_path, image_path
    )

    def on_upload_finished(success, error_msg):
        progress_dialog.close()
        if success:
            _refresh_after_annotation_upload(self)

            popup = Popup(
                self.tr("Uploading annotations successfully!"),
                self,
                icon=new_icon_path("copy-green", "svg"),
            )
            popup.show_popup(self, popup_height=65, position="center")
        else:
            message = (
                f"Error occurred while uploading annotations: {str(error_msg)}"
            )
            logger.error(message)
            popup = Popup(
                message,
                self,
                icon=new_icon_path("error", "svg"),
            )
            popup.show_popup(self, position="center")

    self.upload_thread.finished.connect(on_upload_finished)

    progress_dialog.show()
    self.upload_thread.start()

    progress_dialog.canceled.connect(self.upload_thread.terminate)


def upload_mask_annotation(self, LABEL_OPACITY):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    filter = "Attribute Files (*.json);;All Files (*)"
    color_map_file, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific color_map file"),
        "",
        filter,
    )

    if not color_map_file:
        return

    dialog = UploadFolderDialog(
        self,
        initial_path=osp.dirname(osp.dirname(self.filename)),
        placeholder=self.tr(
            "Please select a folder containing annotation files"
        ),
    )
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    # Initialize unique labels
    with open(color_map_file, "r", encoding="utf-8") as f:
        mapping_table = json.load(f)
        classes = list(mapping_table["colors"].keys())
        for label in classes:
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.unique_label_list.set_item_label(
                    item, label, rgb, LABEL_OPACITY
                )

    label_dir_path = dialog.folder()
    image_dir_path = osp.dirname(self.filename)
    image_file_list = os.listdir(image_dir_path)
    label_file_list = os.listdir(label_dir_path)
    output_dir_path = self.output_dir if self.output_dir else image_dir_path
    converter = LabelConverter()

    image_list = self.image_list if self.image_list else [self.filename]
    progress_dialog = UploadProgressDialog(self, maximum=len(image_list))

    try:
        for i, image_filename in enumerate(image_file_list):
            if image_filename.endswith(".json"):
                continue
            data_filename = osp.splitext(image_filename)[0] + ".json"
            if osp.splitext(image_filename)[0] + ".png" in label_file_list:
                label_filename = osp.splitext(image_filename)[0] + ".png"
            elif osp.splitext(image_filename)[0] + ".jpg" in label_file_list:
                label_filename = osp.splitext(image_filename)[0] + ".jpg"
            else:
                continue
            input_file = osp.join(label_dir_path, label_filename)
            output_file = osp.join(output_dir_path, data_filename)
            image_file = osp.join(image_dir_path, image_filename)
            converter.mask_to_custom(
                input_file=input_file,
                output_file=output_file,
                image_file=image_file,
                mapping_table=mapping_table,
            )

            progress_dialog.setValue(i)
            if progress_dialog.wasCanceled():
                break

        progress_dialog.close()
        template = self.tr(
            "Uploading annotations successfully!\n"
            "Results have been saved to:\n"
            "%s"
        )
        message_text = template % output_dir_path
        popup = Popup(
            message_text,
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

        _refresh_after_annotation_upload(self)

    except Exception as e:
        progress_dialog.close()
        message = f"Error occurred while uploading annotations: {str(e)}"
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def upload_dota_annotation(self):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    dialog = UploadFolderDialog(
        self,
        initial_path=osp.dirname(osp.dirname(self.filename)),
        placeholder=self.tr(
            "Please select a folder containing annotation files"
        ),
    )
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return

    label_dir_path = dialog.folder()
    image_dir_path = osp.dirname(self.filename)
    label_file_list = os.listdir(label_dir_path)
    output_dir_path = self.output_dir if self.output_dir else image_dir_path
    converter = LabelConverter()

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    image_list = self.image_list if self.image_list else [self.filename]
    progress_dialog = UploadProgressDialog(self, maximum=len(image_list))

    try:
        for i, image_path in enumerate(image_list):
            image_filename = osp.basename(image_path)
            label_filename = osp.splitext(image_filename)[0] + ".txt"
            if label_filename not in label_file_list:
                continue

            input_file = osp.join(label_dir_path, label_filename)
            output_file = osp.join(
                output_dir_path, osp.splitext(image_filename)[0] + ".json"
            )
            image_file = osp.join(image_dir_path, image_filename)

            converter.dota_to_custom(
                input_file=input_file,
                output_file=output_file,
                image_file=image_file,
            )

            progress_dialog.setValue(i)
            if progress_dialog.wasCanceled():
                break

        progress_dialog.close()
        template = self.tr(
            "Uploading annotations successfully!\n"
            "Results have been saved to:\n"
            "%s"
        )
        message_text = template % output_dir_path
        popup = Popup(
            message_text,
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

        _refresh_after_annotation_upload(self)

    except Exception as e:
        progress_dialog.close()
        message = f"Error occurred while uploading annotations: {str(e)}"
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def upload_coco_annotation(self, mode):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    filter = "Attribute Files (*.json);;All Files (*)"
    input_file, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a custom coco annotation file"),
        "",
        filter,
    )

    if not input_file:
        return

    output_dir_path = osp.dirname(self.filename)
    if self.output_dir:
        output_dir_path = self.output_dir

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    progress_dialog = UploadProgressDialog(self, maximum=0)

    self.upload_thread = UploadCocoThread(
        LabelConverter(), input_file, output_dir_path, mode
    )

    def on_upload_finished(success, error_msg):
        progress_dialog.close()
        if success:
            _refresh_after_annotation_upload(self)

            popup = Popup(
                self.tr("Uploading annotations successfully!"),
                self,
                icon=new_icon_path("copy-green", "svg"),
            )
            popup.show_popup(self, popup_height=65, position="center")
        else:
            message = (
                f"Error occurred while uploading annotations: {str(error_msg)}"
            )
            logger.error(message)
            popup = Popup(
                message,
                self,
                icon=new_icon_path("error", "svg"),
            )
            popup.show_popup(self, position="center")

    self.upload_thread.finished.connect(on_upload_finished)

    progress_dialog.show()
    self.upload_thread.start()

    progress_dialog.canceled.connect(self.upload_thread.terminate)


def upload_voc_annotation(self, mode):
    if not _check_filename_exist(self):
        return

    if _reject_dataset_mode_upload(self):
        return

    dialog = UploadFolderDialog(
        self,
        initial_path=osp.dirname(osp.dirname(self.filename)),
        placeholder=self.tr(
            "Please select a folder containing annotation files"
        ),
    )
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return

    label_dir_path = dialog.folder()
    image_dir_path = osp.dirname(self.filename)
    label_file_list = os.listdir(label_dir_path)
    output_dir_path = self.output_dir if self.output_dir else image_dir_path
    converter = LabelConverter()

    if not UploadConfirmDialog(self).ask_annotations(False):
        return

    image_list = self.image_list if self.image_list else [self.filename]
    progress_dialog = UploadProgressDialog(self, maximum=len(image_list))

    try:
        for i, image_path in enumerate(image_list):
            image_filename = osp.basename(image_path)
            label_filename = osp.splitext(image_filename)[0] + ".xml"
            if label_filename not in label_file_list:
                continue

            input_file = osp.join(label_dir_path, label_filename)
            output_file = osp.join(
                output_dir_path, osp.splitext(image_filename)[0] + ".json"
            )
            converter.voc_to_custom(
                input_file=input_file,
                output_file=output_file,
                image_filename=image_filename,
                mode=mode,
            )

            progress_dialog.setValue(i)
            if progress_dialog.wasCanceled():
                break

        progress_dialog.close()
        template = self.tr(
            "Uploading annotations successfully!\n"
            "Results have been saved to:\n"
            "%s"
        )
        message_text = template % output_dir_path
        popup = Popup(
            message_text,
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

        _refresh_after_annotation_upload(self)

    except Exception as e:
        progress_dialog.close()
        message = f"Error occurred while uploading annotations: {str(e)}"
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def _dataset_class_source(host):
    """Class names stored in the open dataset ("Classes" tab order)."""

    names = dataset_category_names(getattr(host, "dataset_repository", None))
    if not names:
        return None
    return ClassSource(tuple(names), SOURCE_DATASET)


def _pick_classes_file(host):
    """Fallback picker used when no class source can be detected."""

    file_filter = "Classes Files (*.txt);;All Files (*)"
    path, _selected = QtWidgets.QFileDialog.getOpenFileName(
        host,
        host.tr("Select a specific classes file"),
        "",
        file_filter,
    )
    if not path:
        return None
    try:
        names = read_classes_file(path)
    except OSError as exc:
        popup = Popup(
            host.tr("Error reading classes file: %s") % str(exc),
            host,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(host, position="center")
        return None
    if not names:
        popup = Popup(
            host.tr("No class names found in: %s") % path,
            host,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(host, position="center")
        return None
    host.classes_file = path
    return ClassSource(tuple(names), SOURCE_PICKED, path)


def _resolve_yolo_class_source(host, image_dir):
    """Dataset categories first, then a detected file, then the picker."""

    source = _dataset_class_source(host)
    if source is not None:
        return source
    source = detect_class_source(image_dir)
    if source is not None:
        return source
    return _pick_classes_file(host)


def _class_source_text(host, source):
    """Operator-facing description of where the class names came from."""

    count = len(source.names)
    if source.kind == SOURCE_DATASET:
        return host.tr("Classes: %d from the dataset categories") % count
    return host.tr("Classes: %d from %s") % (count, source.path)


def _read_existing_shapes(output_file):
    """Shapes already stored in a JSON sidecar (JSON mode, preserve option)."""

    if not osp.isfile(output_file):
        return []
    try:
        with open(output_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    shapes = data.get("shapes") if isinstance(data, dict) else None
    return list(shapes) if isinstance(shapes, list) else []


def _merge_existing_shapes(output_file, payload, existing_shapes):
    """Rewrite the payload with the preserved shapes placed first."""

    payload["shapes"] = list(existing_shapes) + list(
        payload.get("shapes") or []
    )
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _refresh_after_dataset_upload(host, written):
    """Refresh the table, statistics and canvas after a database upload."""

    files = getattr(host, "files", None)
    for image_path, shape_count in written:
        if files is None:
            break
        row = files.row_of(image_path)
        if row is not None:
            files.apply_row_state(row, shape_count)
    if files is not None:
        files.invalidate_label_manager()
    host._refresh_statistics_if_visible()
    if host.filename:
        host.load_file(host.filename)


def upload_yolo_annotation(self, mode, LABEL_OPACITY):
    if not _check_filename_exist(self):
        return

    repository = getattr(self, "dataset_repository", None)
    dataset_root = getattr(self, "dataset_root", None)
    image_dir = osp.dirname(self.filename) if self.filename else ""

    if mode == "pose":
        filter = "Classes Files (*.yaml);;All Files (*)"
        self.yaml_file, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select a specific yolo-pose config file"),
            "",
            filter,
        )
        if not self.yaml_file:
            return

        try:
            converter = LabelConverter(pose_cfg_file=self.yaml_file)
        except Exception as e:
            logger.error(f"Failed to load pose config: {self.yaml_file}: {e}")
            popup = Popup(
                self.tr("Invalid pose config file:\n%s") % str(e),
                self,
                icon=new_icon_path("error", "svg"),
            )
            popup.show_popup(self, popup_height=65, position="center")
            return

        labels = []
        for class_name, keypoint_name in converter.pose_classes.items():
            labels.append(class_name)
            labels.extend(keypoint_name)
        class_text = self.tr("Classes: %d from %s") % (
            len(converter.classes),
            osp.basename(self.yaml_file),
        )
    else:
        source = _resolve_yolo_class_source(self, image_dir)
        if source is None:
            return
        converter = LabelConverter(
            classes=list(source.names),
            classes_source=source.path or "dataset categories",
        )
        labels = list(source.names)
        class_text = _class_source_text(self, source)

    label_dir = guess_label_dir(image_dir, dataset_root)

    dialog = UploadFolderDialog(
        self,
        initial_path=label_dir,
        hint_text=class_text,
        placeholder=self.tr(
            "Please select a folder containing annotation files"
        ),
        preserve_option=True,
    )
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return

    label_dir = resolve_label_dir(dialog.folder(), image_dir)
    if not osp.isdir(label_dir):
        popup = Popup(
            self.tr("Label folder does not exist: %s") % label_dir,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")
        return

    preserve_existing = dialog.preserve_existing
    if not UploadConfirmDialog(self).ask_annotations(preserve_existing):
        return

    output_dir = self.output_dir if self.output_dir else image_dir
    image_names = sorted(
        name
        for name in os.listdir(image_dir)
        if osp.splitext(name)[1].lower() != ".json"
    )
    progress = UploadProgressDialog(self, maximum=len(image_names))
    written = []
    errors = []
    skipped = 0
    not_registered = 0
    objects = 0

    try:
        for index, image_name in enumerate(image_names):
            if progress.wasCanceled():
                break
            progress.setValue(index + 1)
            stem = osp.splitext(image_name)[0]
            label_file = osp.join(label_dir, stem + ".txt")
            if not osp.isfile(label_file):
                skipped += 1
                continue
            image_file = osp.join(image_dir, image_name)
            output_file = osp.join(output_dir, stem + ".json")
            existing_shapes = []
            if repository is None and preserve_existing:
                existing_shapes = _read_existing_shapes(output_file)
            try:
                if mode in ("hbb", "seg"):
                    payload = converter.yolo_to_custom(
                        input_file=label_file,
                        output_file=output_file,
                        image_file=image_file,
                        mode=mode,
                        write=repository is None,
                    )
                elif mode == "obb":
                    payload = converter.yolo_obb_to_custom(
                        input_file=label_file,
                        output_file=output_file,
                        image_file=image_file,
                        write=repository is None,
                    )
                else:
                    payload = converter.yolo_pose_to_custom(
                        input_file=label_file,
                        output_file=output_file,
                        image_file=image_file,
                        write=repository is None,
                    )
                if repository is None:
                    if existing_shapes:
                        _merge_existing_shapes(
                            output_file, payload, existing_shapes
                        )
                    shape_count = len(payload.get("shapes") or [])
                    written.append((image_file, shape_count))
                    objects += shape_count
                else:
                    outcome, shape_count, reason = store_annotation(
                        repository,
                        dataset_root,
                        image_file,
                        payload,
                        preserve_existing=preserve_existing,
                    )
                    if outcome == OUTCOME_WRITTEN:
                        written.append((image_file, shape_count))
                        objects += shape_count
                    elif outcome == OUTCOME_SKIPPED:
                        not_registered += 1
                    else:
                        errors.append(f"{image_name}: {reason}")
            except Exception as e:  # noqa: BLE001 - reported per file
                errors.append(str(e))
    finally:
        progress.close()

    if repository is None:
        _refresh_after_annotation_upload(self)
    else:
        _refresh_after_dataset_upload(self, written)

    for label in labels:
        if not self.unique_label_list.find_items_by_label(label):
            item = self.unique_label_list.create_item_from_label(label)
            self.unique_label_list.addItem(item)
            rgb = self._get_rgb_by_label(label)
            self.unique_label_list.set_item_label(
                item, label, rgb, LABEL_OPACITY
            )

    lines = [
        self.tr("Uploaded: %d images, %d objects.") % (len(written), objects),
        self.tr("Skipped (no matching .txt): %d images.") % skipped,
    ]
    if repository is not None:
        lines.append(
            self.tr("Skipped (not in the dataset): %d images.")
            % not_registered
        )
    lines.append(self.tr("Failed: %d images.") % len(errors))
    if errors:
        lines.append("")
        lines.append(self.tr("First errors:"))
        lines.extend(errors[:5])
        logger.warning("YOLO upload finished with errors: %s", errors)
    popup = Popup(
        "\n".join(lines),
        self,
        icon=new_icon_path("copy-green" if written else "error", "svg"),
    )
    popup.show_popup(self, position="center")


def upload_label_classes_file(self):
    filter = "Label Files (*.txt);;All Files (*)"
    file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific label classes file"),
        "",
        filter,
    )
    if not file_path:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            labels = [line.strip() for line in f.readlines()]

        if not labels:
            popup = Popup(
                self.tr("No labels found in the file!"),
                self,
                icon=new_icon_path("error", "svg"),
            )
            popup.show_popup(self, position="center")
            return

        if not UploadConfirmDialog(self).ask_labels():
            return

        # Update unique_label_list
        self.unique_label_list.clear()
        self.load_labels(labels)

        # Update label_dialog.label_list
        self.label_dialog.label_list.clear()
        self.label_dialog.label_list.addItems(labels)
        if self.label_dialog._sort_labels:
            self.label_dialog.sort_labels()

        panel = getattr(self, "label_manager_widget", None)
        if panel is not None:
            panel.invalidate()

        popup = Popup(
            self.tr("Successfully loaded %d labels!") % len(set(labels)),
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, position="center")

    except Exception as e:
        message = (
            f"Error occurred while uploading label classes file: {str(e)}"
        )
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def validate_shape_attributes_config(attributes_data):
    """
    Validates and separates a shape attributes configuration.

    Args:
        attributes_data (dict): Parsed shape attributes configuration.

    Returns:
        tuple: Attribute definitions and widget type mappings.

    Raises:
        ValueError: If the configuration structure is invalid.
    """

    def invalid(label, property_name, widget_type, value, expected):
        raise ValueError(
            "Invalid shape attribute configuration: "
            f"label={label!r}, property={property_name!r}, "
            f"widget_type={widget_type!r}, "
            f"actual_type={type(value).__name__!r}, "
            f"expected={expected!r}"
        )

    if not isinstance(attributes_data, dict):
        invalid(
            "<root>",
            "<root>",
            "<none>",
            attributes_data,
            "a dictionary",
        )

    attributes = {
        label: properties
        for label, properties in attributes_data.items()
        if not label.startswith("__")
    }
    for label, properties in attributes.items():
        if not isinstance(properties, dict):
            invalid(
                label,
                "<all>",
                "<unknown>",
                properties,
                "a dictionary of attribute definitions",
            )

    widget_types = attributes_data.get("__widget_types__", {})
    if not isinstance(widget_types, dict):
        invalid(
            "__widget_types__",
            "<all>",
            "<mapping>",
            widget_types,
            "a dictionary of label widget mappings",
        )

    supported_widget_types = {
        "combobox",
        "radiobutton",
        "group_id",
        "lineedit",
    }
    for label, property_types in widget_types.items():
        if label not in attributes:
            invalid(
                label,
                "<all>",
                "<mapping>",
                None,
                "an existing attribute label",
            )
        if not isinstance(property_types, dict):
            invalid(
                label,
                "<all>",
                "<mapping>",
                property_types,
                "a dictionary of property widget types",
            )
        for property_name, widget_type in property_types.items():
            if property_name not in attributes[label]:
                invalid(
                    label,
                    property_name,
                    widget_type,
                    None,
                    "an existing attribute property",
                )
            if (
                not isinstance(widget_type, str)
                or widget_type not in supported_widget_types
            ):
                invalid(
                    label,
                    property_name,
                    widget_type,
                    widget_type,
                    "one of combobox, radiobutton, group_id, or lineedit",
                )

    for label, properties in attributes.items():
        property_types = widget_types.get(label, {})
        for property_name, value in properties.items():
            widget_type = property_types.get(property_name, "combobox")
            if widget_type in {"combobox", "radiobutton"}:
                if (
                    not isinstance(value, list)
                    or not value
                    or not all(isinstance(option, str) for option in value)
                ):
                    invalid(
                        label,
                        property_name,
                        widget_type,
                        value,
                        "a non-empty list of strings",
                    )
            elif widget_type == "lineedit" and not isinstance(value, str):
                invalid(
                    label,
                    property_name,
                    widget_type,
                    value,
                    "a string",
                )
            elif widget_type == "group_id" and value != []:
                invalid(
                    label,
                    property_name,
                    widget_type,
                    value,
                    "an empty list",
                )

    return attributes, widget_types


def upload_shape_attrs_file(self, LABEL_OPACITY):
    filter = "Shape Attributes Files (*.json);;All Files (*)"
    file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific shape attributes file"),
        "",
        filter,
    )
    if not file_path:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            attributes_data = json.load(f)

        attributes, widget_types = validate_shape_attributes_config(
            attributes_data
        )
        self.attributes = attributes
        self.attribute_widget_types = widget_types
        for label in self.attributes:
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.unique_label_list.set_item_label(
                    item, label, rgb, LABEL_OPACITY
                )

        self.canvas.h_shape_is_hovered = False

        popup = Popup(
            self.tr("Uploading shape attributes file successfully!"),
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

    except Exception as e:
        message = (
            f"Error occurred while uploading shape attributes file: {str(e)}"
        )
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def upload_label_flags_file(self, LABEL_OPACITY):
    filter = "Label Flags Files (*.yaml);;All Files (*)"
    file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific flags file"),
        "",
        filter,
    )
    if not file_path:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            # Each line in the file is an flag-level flag
            self.label_flags = yaml.safe_load(f)
            for label in list(self.label_flags.keys()):
                if not self.unique_label_list.find_items_by_label(label):
                    item = self.unique_label_list.create_item_from_label(label)
                    self.unique_label_list.addItem(item)
                    rgb = self._get_rgb_by_label(label)
                    self.unique_label_list.set_item_label(
                        item, label, rgb, LABEL_OPACITY
                    )

        # update the label dialog
        self.label_dialog.upload_flags(self.label_flags)

        popup = Popup(
            self.tr("Uploading flags file successfully!"),
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

    except Exception as e:
        message = f"Error occurred while uploading flags file: {str(e)}"
        logger.error(message)

        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def upload_image_flags_file(self):
    filter = "Image Flags Files (*.txt);;All Files (*)"
    file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        self.tr("Select a specific flags file"),
        "",
        filter,
    )
    if not file_path:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            # Each line in the file is an image-level flag
            self.image_flags = f.read().splitlines()
            self.load_flags({k: False for k in self.image_flags})
        if hasattr(self, "show_flags_page"):
            self.show_flags_page()

        self.load_file(self.filename)

        popup = Popup(
            self.tr("Uploading flags file successfully!"),
            self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, popup_height=65, position="center")

    except Exception as e:
        message = f"Error occurred while uploading flags file: {str(e)}"
        logger.error(message)
        popup = Popup(
            message,
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")
