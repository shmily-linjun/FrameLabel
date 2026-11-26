"""Guard against silently losing translations (fork.49).

`pylupdate6` only records ``*.tr()`` calls written inside a class body.  The
labeling window builds dialogs, menus and messages in free functions too, and
those strings used to vanish from the ``.ts`` files without any visible error.

These tests enforce the two halves of the fix:

* every translatable literal resolves to a context (``TR_CONTEXT`` or
  ``QCoreApplication.translate``), so nothing is dropped silently;
* every resolved ``(context, source)`` pair is present and translated in the
  primary languages, and the compiled ``.qm`` files agree with the ``.ts``.
"""

import importlib.util
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS = REPO_ROOT / "anylabeling" / "resources" / "translations"
LANGUAGES = ("en_US", "zh_CN", "ja_JP", "ko_KR")
#: The fork keeps these two complete; ja_JP/ko_KR fall back to English for
#: strings that were added in this batch (tracked in the changelog).
COMPLETE_LANGUAGES = ("en_US", "zh_CN")


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "translation_scan", REPO_ROOT / "scripts" / "translation_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    # dataclasses inspects sys.modules[cls.__module__] while decorating.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


@pytest.fixture(scope="module")
def scan_result():
    return scanner.scan(str(REPO_ROOT / "anylabeling"))


def test_every_translatable_call_has_a_runtime_context(scan_result):
    assert scan_result.entries, "no translatable strings were found"
    unresolved = "\n".join(
        f"{path}:{line}: {label}"
        for path, line, label in scan_result.unresolved
    )
    assert unresolved == "", (
        "declare TR_CONTEXT or use QCoreApplication.translate(...):\n"
        + unresolved
    )


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_string_is_registered(scan_result, language):
    ts_path = TRANSLATIONS / f"{language}.ts"
    missing = scanner.missing_entries(scan_result, str(ts_path))
    assert missing == [], "\n".join(
        f"{entry.path}:{entry.line} [{entry.context}] {entry.text!r}"
        for entry in missing[:20]
    )


@pytest.mark.parametrize("language", COMPLETE_LANGUAGES)
def test_primary_languages_have_translations(scan_result, language):
    existing = scanner.read_ts(str(TRANSLATIONS / f"{language}.ts"))
    untranslated = [
        entry
        for entry in scan_result.entries
        if not existing.get((entry.context, entry.text), "").strip()
    ]
    assert untranslated == [], "\n".join(
        f"{entry.path}:{entry.line} [{entry.context}] {entry.text!r}"
        for entry in untranslated[:20]
    )


def test_compiled_qm_matches_the_ts_files(scan_result):
    from PyQt6 import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translator = QtCore.QTranslator()
    assert translator.load(str(TRANSLATIONS / "zh_CN.qm"))
    app.installTranslator(translator)
    try:
        existing = scanner.read_ts(str(TRANSLATIONS / "zh_CN.ts"))
        entries = sorted(
            {
                (entry.context, entry.text)
                for entry in scan_result.entries
                # Proper nouns are translated as themselves ("YOLO Pose",
                # "Form"); Qt returning the source text is correct for them.
                if existing.get((entry.context, entry.text), "")
                and existing[(entry.context, entry.text)] != entry.text
            }
        )
        # Sample deterministically: the cost of checking all 2000+ strings is
        # not worth it, but a fixed sample catches a stale .qm.
        sample = entries[:: max(1, len(entries) // 50)]
        missing = [
            (context, text)
            for context, text in sample
            if QtCore.QCoreApplication.translate(context, text) == text
        ]
        assert missing == [], f"stale zh_CN.qm for: {missing[:10]}"
    finally:
        app.removeTranslator(translator)


def test_upload_dialog_strings_are_translated():
    from PyQt6 import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translator = QtCore.QTranslator()
    assert translator.load(str(TRANSLATIONS / "zh_CN.qm"))
    app.installTranslator(translator)
    try:
        checks = [
            ("UploadFolderDialog", "Upload Options"),
            ("UploadFolderDialog", "Select Upload Folder"),
            ("UploadFolderDialog", "Preserve existing annotations"),
            ("UploadConfirmDialog", "Current annotation will be lost"),
            ("UploadProgressDialog", "Uploading..."),
            ("BaseDialog", "Browse"),
            ("BaseDialog", "Cancel"),
            ("BaseDialog", "OK"),
        ]
        untranslated = [
            (context, text)
            for context, text in checks
            if QtCore.QCoreApplication.translate(context, text) == text
        ]
        assert untranslated == []
    finally:
        app.removeTranslator(translator)


_FORMAT_SPECIFIER = re.compile(
    r"%(?:\([^)]*\))?[#0\- +]?\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa%]"
)


def _specifiers(text):
    """Return the ordered ``%`` specifiers of a template (``%%`` skipped)."""

    return [
        match.group(0)
        for match in _FORMAT_SPECIFIER.finditer(text)
        if match.group(0) != "%%"
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_placeholder_order_matches_source(language):
    """A translation must keep the source's ``%`` order and types.

    The code formats translated templates with Python's ``%`` operator, so a
    translation that swaps ``%d`` and ``%s`` raises ``TypeError`` at run time
    (fork.50: the YOLO upload dialog crashed before it could open).
    """

    messages = scanner.read_ts(str(TRANSLATIONS / f"{language}.ts"))
    mismatched = []
    for (context, source), translation in messages.items():
        if not translation.strip():
            continue
        source_specs = _specifiers(source)
        translated_specs = _specifiers(translation)
        if source_specs != translated_specs:
            mismatched.append(
                (context, source, translation, source_specs, translated_specs)
            )
    assert mismatched == [], "\n".join(
        f"[{context}] {source!r} {source_specs} -> "
        f"{translation!r} {translated_specs}"
        for context, source, translation, source_specs, translated_specs in (
            mismatched[:20]
        )
    )


def test_classes_hint_template_accepts_its_arguments():
    """Regression: formatting the class-source hint must not raise."""

    from PyQt6 import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translator = QtCore.QTranslator()
    assert translator.load(str(TRANSLATIONS / "zh_CN.qm"))
    app.installTranslator(translator)
    try:
        template = QtCore.QCoreApplication.translate(
            "LabelingWidget", "Classes: %d from %s"
        )
        rendered = template % (2, "D:/dataset/classes.txt")
        assert "2" in rendered
        assert "classes.txt" in rendered
    finally:
        app.removeTranslator(translator)


def test_right_sidebar_widgets_are_translated():
    """Regression: the right tab widget must not fall back to English.

    fork.51: ``pylupdate6 --no-obsolete`` dropped every dynamic message
    (``self._tr``, constant headers, generated form) and the whole sidebar
    showed English text.
    """

    from PyQt6 import QtCore, QtWidgets

    from anylabeling.views.labeling.widgets.label_manager import (
        LabelManagerPanel,
    )
    from anylabeling.views.labeling.widgets.statistics_table import (
        StatisticsTable,
    )

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translator = QtCore.QTranslator()
    assert translator.load(str(TRANSLATIONS / "zh_CN.qm"))
    app.installTranslator(translator)
    try:
        translated = {
            text: QtCore.QCoreApplication.translate("LabelingWidget", text)
            for text in (
                "Objects",
                "Classes",
                "Image Attributes",
                "Description",
                "Statistics",
            )
        }
        assert translated == {
            "Objects": "对象",
            "Classes": "类别",
            "Image Attributes": "图像属性",
            "Description": "描述",
            "Statistics": "统计",
        }

        table = StatisticsTable()
        try:
            headers = [
                table.horizontalHeaderItem(index).text()
                for index in range(table.columnCount())
            ]
            assert headers == [
                "类别",
                "训练",
                "验证",
                "测试",
                "未划分",
                "合计",
            ]
            assert table.accessibleName() == "统计"
        finally:
            table.deleteLater()

        host = type("Host", (), {"dataset_repository": None})()
        panel = LabelManagerPanel(host)
        try:
            panel_headers = [
                panel.table.horizontalHeaderItem(index).text()
                for index in range(panel.table.columnCount())
            ]
            assert panel_headers == ["类别", "删除", "可见", "锁定", "颜色"]
        finally:
            panel.deleteLater()

        for context, text, expected in (
            ("TrashDialog", "Recycle Bin", "回收站"),
            ("TrashDialog", "Restore", "恢复"),
            ("LabelManagerPanel", "Category", "类别"),
            ("SettingsDialog", "Edit Image Tags", "编辑图片标签"),
        ):
            assert (
                QtCore.QCoreApplication.translate(context, text) == expected
            )
    finally:
        app.removeTranslator(translator)


def test_image_attributes_tag_library_is_translated():
    """Regression: the injected-translate widgets stayed English.

    ``TagLibraryWidget``/``BatchTagsDialog`` used to accept a ``translate``
    callable and pass ``host.tr`` at the call site, so their literals were
    registered under the class name but looked up with the ``LabelingWidget``
    context (fork.52 removed the injection).
    """

    from PyQt6 import QtCore, QtWidgets

    from anylabeling.views.labeling.file_list.tags_dialog import (
        BatchTagsDialog,
    )
    from anylabeling.views.labeling.widgets.tag_library import (
        TagLibraryWidget,
    )

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translator = QtCore.QTranslator()
    assert translator.load(str(TRANSLATIONS / "zh_CN.qm"))
    app.installTranslator(translator)
    try:
        widget = TagLibraryWidget()
        try:
            assert widget.title_label.text() == "标签库"
            assert widget.search_edit.placeholderText() == "搜索标签…"
            assert widget.collapse_button.toolTip() == "收起标签库"
            widget.set_entries([], [])
            assert (
                widget.empty_label.text()
                == "当前文件列表中没有标签。"
            )
        finally:
            widget.deleteLater()

        dialog = BatchTagsDialog(3, ["defect"], None)
        try:
            assert dialog.windowTitle() == "批量设置图片标签"
            modes = [
                dialog.mode_combo.itemText(index)
                for index in range(dialog.mode_combo.count())
            ]
            assert modes == [
                "添加到现有标签",
                "替换指定标签",
                "删除所有图片标签",
            ]
            assert dialog.mode_combo.itemData(0) == "add"
        finally:
            dialog.deleteLater()
    finally:
        app.removeTranslator(translator)


def test_training_dialog_labels_are_translated():
    """Regression: the whole Ultralytics window used to stay English.

    fork.63: the form labels, group titles, check boxes, task buttons and the
    window title were bare strings (``layout.addRow("Project:", ...)``), and two
    ``self.tr(f"...")`` calls could never be extracted.
    """

    from PyQt6 import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    translator = QtCore.QTranslator()
    assert translator.load(str(TRANSLATIONS / "zh_CN.qm"))
    app.installTranslator(translator)
    try:
        checks = {
            "Project:": "项目：",
            "Name:": "名称：",
            "Dataset Ratio:": "划分比例：",
            "Training Strategy": "训练策略",
            "Training class": "训练类别",
            "Detect": "检测",
            "Browse": "浏览",
        }
        untranslated = {
            text: QtCore.QCoreApplication.translate("UltralyticsDialog", text)
            for text in checks
            if QtCore.QCoreApplication.translate(
                "UltralyticsDialog", text
            )
            == text
        }
        assert untranslated == {}
        translated = {
            text: QtCore.QCoreApplication.translate("UltralyticsDialog", text)
            for text in checks
        }
        assert translated == checks
        # formattable templates must survive translation + formatting
        template = QtCore.QCoreApplication.translate(
            "UltralyticsDialog", "%s: %d images, %d objects, %d classes"
        )
        rendered = template % ("YOLO 数据集", 3, 5, 2)
        assert "3" in rendered and "5" in rendered and "2" in rendered
    finally:
        app.removeTranslator(translator)


def test_scanner_resolves_dynamic_translation_patterns(tmp_path):
    """Dynamic call styles must stay extractable.

    These are the patterns that ``pylupdate6`` cannot see; the scanner must
    resolve them or a regeneration drops their translations again.
    """

    package = tmp_path / "pkg"
    package.mkdir()

    def write(name, content):
        (package / name).write_text(content, encoding="utf-8")

    write(
        "helpers.py",
        "from PyQt6.QtCore import QCoreApplication\n"
        'TRANSLATION_CONTEXT = "HelperPanel"\n'
        "class Helper:\n"
        "    def _tr(self, text):\n"
        "        return QCoreApplication.translate(TRANSLATION_CONTEXT, text)\n"
        "    def build(self):\n"
        '        self._tr("Helper String")\n'
        "class Delegating:\n"
        "    def build(self, owner):\n"
        '        owner._tr("Delegated String")\n',
    )
    write(
        "form_ui.py",
        "from PyQt6 import QtCore\n"
        "_translate = QtCore.QCoreApplication.translate\n"
        'def setup(form):\n'
        '    form.setWindowTitle(_translate("my_form", "Form Title"))\n',
    )
    write(
        "constants.py",
        'TITLE = "My Title"\n'
        'HEADERS = ("Alpha", "Beta")\n',
    )
    write(
        "table.py",
        "from .constants import HEADERS, TITLE\n"
        "class Table:\n"
        "    def tr(self, text):\n"
        "        return text\n"
        "    def build(self):\n"
        "        self.tr(TITLE)\n"
        "        for header in HEADERS:\n"
        "            self.tr(header)\n",
    )
    write(
        "noop.py",
        "from PyQt6.QtCore import QT_TRANSLATE_NOOP\n"
        'CONTEXT = "NoopDialog"\n'
        'QT_TRANSLATE_NOOP(CONTEXT, "Noop String")\n',
    )

    result = scanner.scan(str(package))
    found = {(entry.context, entry.text) for entry in result.entries}
    assert found == {
        ("HelperPanel", "Helper String"),
        ("my_form", "Form Title"),
        ("Table", "My Title"),
        ("Table", "Alpha"),
        ("Table", "Beta"),
        ("NoopDialog", "Noop String"),
    }
    assert result.unresolved == []
