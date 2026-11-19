"""Attribute editor of the right side panel.

Builds the per-shape attribute controls (radio groups, combo boxes, text
fields) from the label configuration, applies their values to the selected
shape and saves them through the labeling widget. It used to be a large block
of ``LabelingWidget`` methods; keeping the rules here keeps the widget focused
on the annotation flow.

The host (``LabelingWidget``) owns the panel widgets (``scroll_area``,
``grid_layout``, ``grid_layout_container``), the ``attributes`` config, the
canvas/label list and the save helpers used by this class.
"""

import os
import os.path as osp

from PyQt6 import QtCore
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ....services.auto_labeling.types import AutoLabelingMode
from .. import utils
from ..label_file import LabelFile, LabelFileError
from ..schema import CHECKED_FIELD
from ..utils.label_text import measure_text_width as _measure_text_width

class AttributesPanel:
    """Per-label attribute widgets and their value handling."""

    def __init__(self, host):
        self.host = host

    def reset_attribute(self, text, shape):
        # Skip validation for auto-labeling special constants
        if text in [
            AutoLabelingMode.OBJECT,
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            return text

        valid_labels = list(self.host.attributes.keys())
        if text not in valid_labels:
            most_similar_label = utils.find_most_similar_label(
                text, valid_labels
            )
            self.host.error_message(
                self.host.tr("Invalid label"),
                self.host.tr(
                    "Invalid label '{}' with validation type: {}!\n"
                    "Reset the label as {}."
                ).format(text, valid_labels, most_similar_label),
            )
            text = most_similar_label

        new_attributes = {
            attrs_key: (
                attrs_val[0]
                if isinstance(attrs_val, list) and attrs_val
                else attrs_val
            )
            for attrs_key, attrs_val in self.host.attributes[text].items()
        }
        shape.attributes = new_attributes
        return text

    def attribute_selection_changed(self, i, property, combo):
        selected_option = combo.currentText()
        tooltip = combo.currentData(Qt.ItemDataRole.ToolTipRole)
        combo.setToolTip(tooltip or "")
        if i < len(self.host.canvas.shapes):
            if not self.host.canvas.shapes[i].attributes:
                self.host.canvas.shapes[i].attributes = {}
            self.host.canvas.shapes[i].attributes[property] = selected_option
            self.host.save_attributes(self.host.canvas.shapes)
            self.host.canvas.update()

    def attribute_radio_changed(self, i, property, option, checked):
        if checked and i < len(self.host.canvas.shapes):
            if not self.host.canvas.shapes[i].attributes:
                self.host.canvas.shapes[i].attributes = {}
            self.host.canvas.shapes[i].attributes[property] = option
            self.host.save_attributes(self.host.canvas.shapes)
            self.host.canvas.update()

    def attribute_line_changed(self, i, property, line: QLineEdit):
        line_text = line.text()
        if i < len(self.host.canvas.shapes):
            if not self.host.canvas.shapes[i].attributes:
                self.host.canvas.shapes[i].attributes = {}
            self.host.canvas.shapes[i].attributes[property] = line_text
            self.host.save_attributes(self.host.canvas.shapes)
            self.host.canvas.update()

    def update_selected_options(self, selected_options):
        if not isinstance(selected_options, dict):
            return

        row_count = self.host.grid_layout.rowCount()
        for row in range(row_count):
            category_label = None
            property_widget = None
            if self.host.grid_layout.itemAtPosition(row, 0):
                category_label = self.host.grid_layout.itemAtPosition(
                    row, 0
                ).widget()
            if self.host.grid_layout.itemAtPosition(row, 1):
                property_widget = self.host.grid_layout.itemAtPosition(
                    row, 1
                ).widget()
            if category_label and property_widget:
                category = category_label.text()
                if category in selected_options:
                    selected_option = selected_options[category]

                    if isinstance(property_widget, QComboBox):
                        index = property_widget.findText(selected_option)
                        if index >= 0:
                            property_widget.setCurrentIndex(index)
                    elif isinstance(property_widget, QWidget):
                        for child in property_widget.findChildren(
                            QRadioButton
                        ):
                            if child.text() == selected_option:
                                child.setChecked(True)
                                break
        return

    def update_attributes(self, shape_index):
        if shape_index >= len(self.host.canvas.shapes) or shape_index < 0:
            self.host.hide_attributes_panel()
            return

        update_shape = self.host.canvas.shapes[shape_index]
        update_category = update_shape.label
        if update_category not in self.host.attributes:
            self.host.hide_attributes_panel()
            return

        current_attibute = self.host.attributes[update_category]
        if not update_shape.attributes:
            update_shape.attributes = {}
        attributes_changed = False

        self.host.grid_layout = QGridLayout()
        row_counter = 0

        def unknown_value_tooltip(value):
            return self.host.tr(
                "Value '{}' is not defined in the current attribute "
                "configuration."
            ).format(value)

        def set_current_combo_value(combo, value):
            value = str(value)
            index = combo.findText(value)
            if index < 0:
                combo.addItem(value)
                index = combo.count() - 1
                tooltip = unknown_value_tooltip(value)
                combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
                combo.setToolTip(tooltip)
            combo.setCurrentIndex(index)

        for property, options in current_attibute.items():
            widget_type = self.host.attribute_widget_types.get(
                update_category, {}
            ).get(property, "combobox")
            has_current_value = property in update_shape.attributes
            current_value = update_shape.attributes.get(property)
            current_value_text = (
                str(current_value) if has_current_value else None
            )
            if hasattr(self.host, "grid_layout_container"):
                font_metrics = QFontMetrics(self.host.grid_layout_container.font())
            else:
                font_metrics = QFontMetrics(QLabel().font())
            available_width = self.host.scroll_area.width() - 30
            property_display = property
            if _measure_text_width(font_metrics, property) > available_width:
                while (
                    _measure_text_width(font_metrics, property_display + "...")
                    > available_width
                    and len(property_display) > 1
                ):
                    property_display = property_display[:-1]
                property_display += "..."

            property_label = QLabel(property_display)
            if property_display != property:
                property_label.setToolTip(property)

            self.host.grid_layout.addWidget(property_label, row_counter, 0, 1, 2)
            row_counter += 1

            if widget_type == "radiobutton":
                radio_options = list(options)
                unknown_radio_value = None
                if (
                    has_current_value
                    and current_value_text not in radio_options
                ):
                    unknown_radio_value = current_value_text
                    radio_options.append(unknown_radio_value)
                radio_container = QWidget()
                radio_group = QButtonGroup(radio_container)
                main_layout = QVBoxLayout()
                main_layout.setContentsMargins(0, 0, 0, 0)
                main_layout.setSpacing(2)

                def get_truncated_text(text, max_width):
                    if _measure_text_width(font_metrics, text) <= max_width:
                        return text, text
                    truncated = text
                    while (
                        _measure_text_width(font_metrics, truncated + "...")
                        > max_width
                        and len(truncated) > 1
                    ):
                        truncated = truncated[:-1]
                    return truncated + "...", text

                def get_button_width(text):
                    return _measure_text_width(font_metrics, text) + 30

                def create_radio_button_with_handler(
                    display_text, original_text, prop, shape_idx
                ):
                    radio_button = QRadioButton(display_text)
                    if original_text == unknown_radio_value:
                        radio_button.setToolTip(
                            unknown_value_tooltip(original_text)
                        )
                    elif display_text != original_text:
                        radio_button.setToolTip(original_text)
                    radio_group.addButton(radio_button)

                    def handler(checked):
                        if checked:
                            self.host.attribute_radio_changed(
                                shape_idx, prop, original_text, checked
                            )

                    radio_button.toggled.connect(handler)
                    return radio_button

                buttons_data = []
                for option in radio_options:
                    display_text, original_text = get_truncated_text(
                        option, available_width
                    )
                    button_width = get_button_width(display_text)
                    buttons_data.append(
                        (display_text, original_text, button_width)
                    )

                current_row_buttons = []
                current_row_width = 0

                idx = 0
                while idx < len(buttons_data):
                    display_text, original_text, button_width = buttons_data[
                        idx
                    ]

                    if not current_row_buttons:
                        current_row_buttons.append(
                            (display_text, original_text)
                        )
                        current_row_width = button_width
                        idx += 1
                        continue

                    if current_row_width + button_width <= available_width:
                        current_row_buttons.append(
                            (display_text, original_text)
                        )
                        current_row_width += button_width
                        idx += 1
                    else:
                        if len(current_row_buttons) == 1:
                            (
                                first_display,
                                first_original,
                            ) = current_row_buttons[0]
                            first_truncated, _ = get_truncated_text(
                                first_original, available_width - button_width
                            )
                            first_truncated_width = get_button_width(
                                first_truncated
                            )

                            if (
                                first_truncated_width + button_width
                                <= available_width
                            ):
                                current_row_buttons = [
                                    (first_truncated, first_original),
                                    (display_text, original_text),
                                ]
                                current_row_width = (
                                    first_truncated_width + button_width
                                )
                                idx += 1
                            else:
                                row_layout = QHBoxLayout()
                                row_layout.setContentsMargins(0, 0, 0, 0)
                                row_layout.setSpacing(4)

                                for (
                                    btn_display,
                                    btn_original,
                                ) in current_row_buttons:
                                    radio_button = (
                                        create_radio_button_with_handler(
                                            btn_display,
                                            btn_original,
                                            property,
                                            shape_index,
                                        )
                                    )
                                    row_layout.addWidget(radio_button)
                                    if current_value_text == btn_original or (
                                        not has_current_value
                                        and btn_original == options[0]
                                    ):
                                        blocker = QtCore.QSignalBlocker(
                                            radio_button
                                        )
                                        radio_button.setChecked(True)
                                        del blocker
                                        if not has_current_value:
                                            update_shape.attributes[
                                                property
                                            ] = btn_original
                                            attributes_changed = True

                                row_layout.addStretch()
                                row_widget = QWidget()
                                row_widget.setLayout(row_layout)
                                main_layout.addWidget(row_widget)

                                current_row_buttons = []
                                current_row_width = 0
                                continue
                        else:
                            row_layout = QHBoxLayout()
                            row_layout.setContentsMargins(0, 0, 0, 0)
                            row_layout.setSpacing(4)
                            for (
                                btn_display,
                                btn_original,
                            ) in current_row_buttons:
                                radio_button = (
                                    create_radio_button_with_handler(
                                        btn_display,
                                        btn_original,
                                        property,
                                        shape_index,
                                    )
                                )
                                row_layout.addWidget(radio_button)
                                if current_value_text == btn_original or (
                                    not has_current_value
                                    and btn_original == options[0]
                                ):
                                    blocker = QtCore.QSignalBlocker(
                                        radio_button
                                    )
                                    radio_button.setChecked(True)
                                    del blocker
                                    if not has_current_value:
                                        update_shape.attributes[property] = (
                                            btn_original
                                        )
                                        attributes_changed = True

                            row_layout.addStretch()
                            row_widget = QWidget()
                            row_widget.setLayout(row_layout)
                            main_layout.addWidget(row_widget)

                            current_row_buttons = []
                            current_row_width = 0
                            continue

                if current_row_buttons:
                    row_layout = QHBoxLayout()
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(4)
                    for btn_display, btn_original in current_row_buttons:
                        radio_button = create_radio_button_with_handler(
                            btn_display, btn_original, property, shape_index
                        )
                        row_layout.addWidget(radio_button)
                        if current_value_text == btn_original or (
                            not has_current_value
                            and btn_original == options[0]
                        ):
                            blocker = QtCore.QSignalBlocker(radio_button)
                            radio_button.setChecked(True)
                            del blocker
                            if not has_current_value:
                                update_shape.attributes[property] = (
                                    btn_original
                                )
                                attributes_changed = True
                    row_layout.addStretch()
                    row_widget = QWidget()
                    row_widget.setLayout(row_layout)
                    main_layout.addWidget(row_widget)

                radio_container.setLayout(main_layout)
                self.host.grid_layout.addWidget(
                    radio_container, row_counter, 0, 1, 2
                )
                row_counter += 1
            elif widget_type == "group_id":
                property_combo = QComboBox()
                options = [""] + sorted(
                    {
                        str(obj.group_id)
                        for obj in self.host.canvas.shapes
                        if obj.group_id is not None
                    }
                )
                property_combo.addItems(options)
                if has_current_value:
                    set_current_combo_value(property_combo, current_value)
                property_combo.currentIndexChanged.connect(
                    lambda _, prop=property, combo=property_combo, shape_idx=shape_index: self.host.attribute_selection_changed(
                        shape_idx, prop, combo
                    )
                )
                self.host.grid_layout.addWidget(
                    property_combo, row_counter, 0, 1, 2
                )
                row_counter += 1
            elif widget_type == "lineedit":
                property_line = QLineEdit()
                if has_current_value:
                    property_line.setText(current_value_text)
                property_line.textChanged.connect(
                    lambda _, prop=property, line=property_line, shape_idx=shape_index: self.host.attribute_line_changed(
                        shape_idx, prop, line
                    )
                )
                self.host.grid_layout.addWidget(property_line, row_counter, 0, 1, 2)
                row_counter += 1
            else:
                property_combo = QComboBox()
                property_combo.addItems(options)
                if has_current_value:
                    set_current_combo_value(property_combo, current_value)
                else:
                    update_shape.attributes[property] = options[0]
                    attributes_changed = True
                property_combo.currentIndexChanged.connect(
                    lambda _, prop=property, combo=property_combo, shape_idx=shape_index: self.host.attribute_selection_changed(
                        shape_idx, prop, combo
                    )
                )
                self.host.grid_layout.addWidget(
                    property_combo, row_counter, 0, 1, 2
                )
                row_counter += 1

        self.host.grid_layout_container = QWidget()
        self.host.grid_layout_container.setLayout(self.host.grid_layout)
        self.host.scroll_area.setWidget(self.host.grid_layout_container)
        self.host.scroll_area.setWidgetResizable(True)
        if shape_index < len(self.host.canvas.shapes):
            self.host.canvas.shapes[shape_index] = update_shape
            if attributes_changed:
                self.host.save_attributes(self.host.canvas.shapes)
        self.host.show_attributes_panel()

    def show_attributes_panel(self):
        if hasattr(self.host, "scroll_area"):
            self.host.scroll_area.setVisible(True)

    def hide_attributes_panel(self):
        if hasattr(self.host, "scroll_area"):
            self.host.scroll_area.setVisible(False)

    def save_attributes(self, _shapes):
        filename = osp.splitext(self.host.image_path)[0] + ".json"
        if self.host.output_dir:
            label_file_without_path = osp.basename(filename)
            filename = osp.join(self.host.output_dir, label_file_without_path)
        label_file = LabelFile()

        # Get current shapes
        # Excluding auto labeling special shapes
        shapes = [
            shape.to_dict()
            for shape in _shapes
            if shape.label
            not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]
        ]
        flags = {}
        for i in range(self.host.flag_widget.count()):
            item = self.host.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.CheckState.Checked
            flags[key] = flag
        self.host.other_data[CHECKED_FIELD] = self.host._annotation_checked()
        signature, allowed = self.host._prepare_attribution(shapes, flags)
        if not allowed:
            return False
        try:
            image_path = osp.relpath(self.host.image_path, osp.dirname(filename))
            image_data = (
                self.host.image_data if self.host._config["store_data"] else None
            )
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))
            label_file.save(
                filename=filename,
                shapes=shapes,
                image_path=image_path,
                image_data=image_data,
                image_height=self.host.image.height(),
                image_width=self.host.image.width(),
                other_data=self.host._relation_data_for_shapes(shapes),
                flags=flags,
            )
            self.host.label_file = label_file
            self.host.operator_gate.baseline = signature
            self.host.actions.save.setIcon(utils.new_icon("save-check"))
            self.host._update_file_row_after_save(len(shapes))
            # disable allows next and previous image to proceed
            # self.filename = filename
            return True
        except LabelFileError as e:
            self.host.error_message(
                self.host.tr("Error saving label data"), self.host.tr("<b>%s</b>") % e
            )
            return False
