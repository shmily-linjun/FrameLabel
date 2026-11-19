"""Regression tests for browse mode, the login guard and theme contrast."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.services.identity.store import Operator  # noqa: E402
from anylabeling.views.labeling.label_widget import (  # noqa: E402
    OPERATOR_MODE_ACTIONS,
    OPERATOR_REQUIRED_ACTIONS,
    LabelingWidget,
)
from anylabeling.views.labeling.utils.theme import (  # noqa: E402
    DARK,
    LIGHT,
    get_dark_palette,
    init_theme,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))


def test_mode_actions_and_command_actions_are_disjoint():
    assert set(OPERATOR_MODE_ACTIONS) & set(OPERATOR_REQUIRED_ACTIONS) == set()
    assert "create_rectangle_mode" in OPERATOR_MODE_ACTIONS
    assert "edit_mode" in OPERATOR_MODE_ACTIONS
    assert "delete" in OPERATOR_REQUIRED_ACTIONS
    assert "run_all_images" in OPERATOR_REQUIRED_ACTIONS


def test_disabled_text_is_fainter_than_secondary_text():
    """Disabled text must be clearly weaker than secondary body text.

    ``text_secondary`` is a readable body colour; using it for disabled
    toolbar labels made browse mode look enabled in the dark theme.
    """

    def rel_luminance(color):
        color = QtGui.QColor(color)

        def channel(value):
            value = value / 255.0
            return (
                value / 12.92
                if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4
            )

        return (
            0.2126 * channel(color.red())
            + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue())
        )

    def contrast(fg, bg):
        first, second = rel_luminance(fg), rel_luminance(bg)
        if first < second:
            first, second = second, first
        return (first + 0.05) / (second + 0.05)

    for theme in (DARK, LIGHT):
        background = theme["background"]
        assert "text_disabled" in theme
        disabled = contrast(theme["text_disabled"], background)
        secondary = contrast(theme["text_secondary"], background)
        text = contrast(theme["text"], background)
        # Disabled text is the faintest of the three, but still visible.
        assert disabled < secondary < text
        assert disabled > 1.6


def test_warning_text_stays_readable_in_both_themes():
    """The browse-mode hint uses a warning tone; amber cannot carry text on
    white, so the light theme needs its own darker tone."""

    def contrast(fg, bg):
        def channel(value):
            value = value / 255.0
            return (
                value / 12.92
                if value <= 0.03928
                else ((value + 0.055) / 1.055) ** 2.4
            )

        def luminance(color):
            color = QtGui.QColor(color)
            return (
                0.2126 * channel(color.red())
                + 0.7152 * channel(color.green())
                + 0.0722 * channel(color.blue())
            )

        first, second = luminance(fg), luminance(bg)
        if first < second:
            first, second = second, first
        return (first + 0.05) / (second + 0.05)

    for theme in (DARK, LIGHT):
        assert "warning_text" in theme
        assert contrast(theme["warning_text"], theme["background"]) >= 4.5
    assert LIGHT["warning_text"] != DARK["warning_text"]


def test_dark_palette_uses_text_disabled_for_disabled_group():
    init_theme("dark")
    try:
        palette = get_dark_palette()
        assert palette is not None
        for role in (
            QtGui.QPalette.ColorRole.WindowText,
            QtGui.QPalette.ColorRole.Text,
            QtGui.QPalette.ColorRole.ButtonText,
        ):
            color = palette.color(
                QtGui.QPalette.ColorGroup.Disabled, role
            ).name()
            assert color == DARK["text_disabled"]
    finally:
        init_theme("light")


def test_toolbar_stylesheet_has_disabled_rule():
    from anylabeling.views.labeling.widgets.toolbar import ToolBar

    init_theme("dark")
    try:
        toolbar = ToolBar("Tools")
        assert "QToolButton:disabled" in toolbar.styleSheet()
        assert DARK["text_disabled"] in toolbar.styleSheet()
    finally:
        init_theme("light")
        toolbar.deleteLater()


def test_icon_carries_dimmed_disabled_variant():
    import anylabeling.resources.resources  # noqa: F401 - icon resources
    from anylabeling.views.labeling.utils.qt import (
        new_icon,
        with_disabled_variant,
    )

    init_theme("dark")
    try:
        source = new_icon("rectangle")
        assert not source.isNull()
        result = with_disabled_variant(source)
        normal = result.pixmap(QtCore.QSize(24, 24), QtGui.QIcon.Mode.Normal)
        disabled = result.pixmap(
            QtCore.QSize(24, 24), QtGui.QIcon.Mode.Disabled
        )
        assert not normal.isNull() and not disabled.isNull()

        # The disabled pixmap is drawn with reduced opacity; comparing the
        # composited result is what the user actually sees on the surface.
        def mean_coverage(pixmap):
            image = pixmap.toImage()
            total = 0.0
            for y in range(image.height()):
                for x in range(image.width()):
                    total += image.pixelColor(x, y).alphaF()
            return total / (image.width() * image.height())

        assert mean_coverage(disabled) < mean_coverage(normal) * 0.6
    finally:
        init_theme("light")


def test_canvas_read_only_blocks_content_gestures():
    import anylabeling.resources.resources  # noqa: F401 - icon resources
    from anylabeling.views.labeling.shape import Shape
    from anylabeling.views.labeling.widgets.canvas import Canvas

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # ``Canvas`` expects the labeling widget as ``parent``; the drag helpers
    # used here do not call back into it.
    canvas = Canvas(parent=QtWidgets.QWidget())
    try:
        canvas.load_pixmap(QtGui.QPixmap(200, 200))
        shape = Shape(label="cat", shape_type="rectangle")
        shape.points = [
            QtCore.QPointF(10.0, 10.0),
            QtCore.QPointF(60.0, 60.0),
        ]
        canvas.load_shapes([shape])
        canvas.select_shapes([shape])
        canvas.set_read_only(True)
        assert canvas.is_read_only()
        before = [(p.x(), p.y()) for p in shape.points]
        assert (
            canvas.bounded_move_shapes([shape], QtCore.QPointF(40, 40))
            is False
        )
        assert [(p.x(), p.y()) for p in shape.points] == before

        canvas.set_read_only(False)
        assert not canvas.is_read_only()
        assert (
            canvas.bounded_move_shapes([shape], QtCore.QPointF(40, 40))
            is True
        )
        assert [(p.x(), p.y()) for p in shape.points] != before
    finally:
        canvas.deleteLater()
        app.processEvents()
