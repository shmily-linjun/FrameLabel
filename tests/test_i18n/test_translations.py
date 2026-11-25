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
        entries = sorted(
            {(entry.context, entry.text) for entry in scan_result.entries}
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
