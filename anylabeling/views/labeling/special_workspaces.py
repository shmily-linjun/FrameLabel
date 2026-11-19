"""Entry points for the specialized workspaces and auxiliary windows.

Point cloud, PPOCR, VQA, chatbot, image/video classification,
training, overview and the manager dialogs are separate windows
owned by the labeling widget.  Creating them (and cleaning up their
references) used to be a block of methods on ``LabelingWidget``.
"""

import html

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from ...config import save_config
from ...views.training import UltralyticsDialog
from . import utils
from .constants import LABEL_OPACITY
from .logger import logger
from .widgets import (
    AboutDialog,
    ChatbotDialog,
    ClassifierDialog,
    DigitShortcutDialog,
    GroupIDModifyDialog,
    LabelModifyDialog,
    OverviewDialog,
    PPOCRDialog,
    Popup,
    ShapeModifyDialog,
    VQADialog,
    VideoClassifierDialog,
)


class SpecialWorkspaces:
    """Window factories for the specialized workspaces."""

    def __init__(self, host):
        self.host = host

    def start_training(self, mode):
        if mode != "ultralytics":
            return

        try:
            if self.host.training_dialog is None:
                self.host.training_dialog = UltralyticsDialog(self.host)
                self.host.training_dialog.destroyed.connect(
                    self.host.on_training_dialog_destroyed
                )
            self.host.training_dialog.showNormal()
            self.host.training_dialog.raise_()
            self.host.training_dialog.activateWindow()
        except Exception as e:
            self.host.error_message(
                "Start Error", f"Failed to start training dialog: {str(e)}"
            )

    def on_training_dialog_destroyed(self, _dialog=None):
        self.host.training_dialog = None

    def overview(self):
        if self.host.filename:
            OverviewDialog(parent=self.host)

    def digit_shortcut_manager(self):
        digit_shortcut_dialog = DigitShortcutDialog(parent=self.host)
        result = digit_shortcut_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self.host._config["digit_shortcuts"] = self.host.drawing_digit_shortcuts
            save_config(self.host._config)

    def label_manager(self):
        modify_label_dialog = LabelModifyDialog(
            parent=self.host, opacity=LABEL_OPACITY
        )
        result = modify_label_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if self.host.filename and modify_label_dialog.annotations_changed:
                self.host.load_file(self.host.filename)

    def gid_manager(self):
        modify_gid_dialog = GroupIDModifyDialog(parent=self.host)
        result = modify_gid_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self.host.load_file(self.host.filename)

    def shape_manager(self):
        modify_shape_dialog = ShapeModifyDialog(parent=self.host)
        result = modify_shape_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if modify_shape_dialog.need_reload and self.host.filename:
                self.host.load_file(self.host.filename)

    def open_chatbot(self):
        dialog = ChatbotDialog(self.host)
        _ = dialog.exec()

    def open_vqa(self):
        if not self.host.image_list:
            self.host.error_message(
                self.host.tr("No images loaded"),
                self.host.tr(
                    "Please load an image folder before opening the VQA dialog."
                ),
            )
            return

        if not hasattr(self.host, "vqa_window") or self.host.vqa_window is None:
            self.host.vqa_window = VQADialog(self.host)
            self.host.vqa_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.host.vqa_window.isVisible():
            self.host.vqa_window.raise_()
            self.host.vqa_window.activateWindow()
        else:
            self.host.vqa_window.show()

    def open_pointcloud(self):
        if self.host.pointcloud_window is None:
            try:
                from .widgets.pointcloud_dialog import PointCloudDialog

                window = PointCloudDialog(self.host)
            except (ImportError, OSError, RuntimeError) as error:
                logger.error(f"Failed to open point cloud workspace: {error}")
                self.host.error_message(
                    self.host.tr("Point cloud unavailable"),
                    self.host.tr("Unable to open the point cloud workspace: %s")
                    % html.escape(str(error)),
                )
                return
            window.destroyed.connect(self.host.on_pointcloud_window_destroyed)
            self.host.pointcloud_window = window
        if self.host.pointcloud_window.isMinimized():
            self.host.pointcloud_window.showNormal()
        else:
            self.host.pointcloud_window.show()
        self.host.pointcloud_window.raise_()
        self.host.pointcloud_window.activateWindow()

    def on_pointcloud_window_destroyed(self, _window=None):
        self.host.pointcloud_window = None

    def open_paddleocr(self):
        if not hasattr(self.host, "ppocr_window") or self.host.ppocr_window is None:
            self.host.ppocr_window = PPOCRDialog(self.host)
            self.host.ppocr_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.host.ppocr_window.isVisible():
            self.host.ppocr_window.raise_()
            self.host.ppocr_window.activateWindow()
        else:
            self.host.ppocr_window.show()

    def open_video_classifier(self):
        if VideoClassifierDialog is None:
            popup = Popup(
                text=self.host.tr(
                    "Video Classifier requires QtMultimedia, which this "
                    "Qt build does not provide."
                ),
                parent=self.host,
            )
            popup.show_popup(self.host, position="center")
            return
        if (
            not hasattr(self.host, "video_classifier_window")
            or self.host.video_classifier_window is None
        ):
            self.host.video_classifier_window = VideoClassifierDialog(self.host)
            self.host.video_classifier_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, True
            )
            self.host.video_classifier_window.destroyed.connect(
                lambda _obj=None: setattr(
                    self.host, "video_classifier_window", None
                )
            )
        if self.host.video_classifier_window.isVisible():
            self.host.video_classifier_window.raise_()
            self.host.video_classifier_window.activateWindow()
        else:
            self.host.video_classifier_window.showMaximized()

    def open_image_classifier(self):
        if not self.host.image_list:
            self.host.error_message(
                self.host.tr("No images loaded"),
                self.host.tr(
                    "Please load an image folder before opening the Classification dialog."
                ),
            )
            return

        if (
            not hasattr(self.host, "image_classifier_window")
            or self.host.image_classifier_window is None
        ):
            self.host.image_classifier_window = ClassifierDialog(self.host)
            self.host.image_classifier_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.host.image_classifier_window.isVisible():
            self.host.image_classifier_window.raise_()
            self.host.image_classifier_window.activateWindow()
        else:
            self.host.image_classifier_window.show()

    def open_classifier(self):
        return self.host.open_image_classifier()

    def documentation(self):
        locale = "/zh-Hans" if self.host._config["language"] == "zh_CN" else ""
        url = (
            f"https://xanylabeling.com{locale}/docs/"
            "x-anylabeling/get_started"
        )
        utils.general.open_url(url)

    def sponsor(self):
        utils.general.open_url("https://xanylabeling.com/sponsor")

    def about(self):
        about_dialog = AboutDialog(self.host)
        _ = about_dialog.exec()
