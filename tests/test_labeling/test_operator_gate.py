"""Browse-mode gate and attribution stamping tests.

The policy lives in :class:`anylabeling.views.labeling.operator.gate.
OperatorGate`; the tests drive it with a stand-in host so the widget layout is
not needed.
"""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from anylabeling.services.identity.attribution import content_signature
    from anylabeling.views.labeling.operator import (
        OPERATOR_MODE_ACTIONS,
        OPERATOR_REQUIRED_ACTIONS,
        OperatorGate,
    )

    PYQT_AVAILABLE = True
except Exception:
    PYQT_AVAILABLE = False

SHAPES = [{"label": "cat", "points": [[0, 0], [1, 1]]}]
FLAGS = {}


class _Action:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = value


def _make_gate(*, operator_name="", image_loaded=True):
    session = SimpleNamespace(
        operator_name=operator_name,
        is_logged_in=bool(operator_name),
    )
    actions = SimpleNamespace(
        **{
            name: _Action()
            for name in OPERATOR_REQUIRED_ACTIONS + OPERATOR_MODE_ACTIONS
        }
    )
    tags_widget = SimpleNamespace(set_interactions_enabled=Mock())
    canvas = SimpleNamespace(set_read_only=Mock())
    service = SimpleNamespace(session=session)
    widget = SimpleNamespace(
        operator_service=service,
        filename="image.png" if image_loaded else None,
        image_path="image.png" if image_loaded else None,
        actions=actions,
        canvas=canvas,
        image_tags_widget=tags_widget,
        other_data={"tags": [], "description": ""},
        _refresh_browse_mode_badge=Mock(),
        tr=lambda text: text,
        status=Mock(),
    )
    gate = OperatorGate(widget, service)
    gate.ensure_operator = Mock(return_value=True)
    gate.open_login = Mock(return_value=True)
    return widget, gate


@unittest.skipUnless(
    PYQT_AVAILABLE, "PyQt6 is required for operator gate tests"
)
class TestOperatorGate(unittest.TestCase):
    def test_browse_mode_disables_annotation_actions(self):
        widget, gate = _make_gate()
        gate.apply()
        for name in OPERATOR_REQUIRED_ACTIONS:
            self.assertFalse(
                getattr(widget.actions, name).enabled, name
            )
        enabled = widget.image_tags_widget.set_interactions_enabled
        enabled.assert_called_once_with(False)

    def test_browse_mode_keeps_tool_modes_clickable(self):
        # A disabled tool button cannot explain why it does nothing, so the
        # mode actions stay enabled and the login prompt answers the click.
        widget, gate = _make_gate()
        gate.apply()
        for name in OPERATOR_MODE_ACTIONS:
            self.assertTrue(getattr(widget.actions, name).enabled, name)
        widget.canvas.set_read_only.assert_called_once_with(True)

    def test_annotation_mode_makes_canvas_editable(self):
        widget, gate = _make_gate(operator_name="张三")
        gate.apply()
        widget.canvas.set_read_only.assert_called_once_with(False)
        for name in OPERATOR_MODE_ACTIONS:
            self.assertTrue(getattr(widget.actions, name).enabled, name)

    def test_annotation_mode_enables_tools_with_an_image(self):
        widget, gate = _make_gate(operator_name="张三")
        gate.apply()
        for name in OPERATOR_REQUIRED_ACTIONS:
            self.assertTrue(getattr(widget.actions, name).enabled, name)
        enabled = widget.image_tags_widget.set_interactions_enabled
        enabled.assert_called_once_with(True)

    def test_annotation_mode_without_image_keeps_tags_disabled(self):
        widget, gate = _make_gate(operator_name="张三", image_loaded=False)
        gate.apply()
        enabled = widget.image_tags_widget.set_interactions_enabled
        enabled.assert_called_once_with(False)


@unittest.skipUnless(
    PYQT_AVAILABLE, "PyQt6 is required for operator gate tests"
)
class TestAttributionPreparation(unittest.TestCase):
    def test_unchanged_content_does_not_stamp(self):
        widget, gate = _make_gate(operator_name="张三")
        gate.baseline = content_signature(
            SHAPES, FLAGS, widget.other_data
        )
        signature, allowed = gate.prepare_attribution(SHAPES, FLAGS)
        self.assertTrue(allowed)
        self.assertEqual(signature, gate.baseline)
        self.assertNotIn("author", widget.other_data)
        gate.ensure_operator.assert_not_called()

    def test_changed_content_stamps_the_logged_in_operator(self):
        widget, gate = _make_gate(operator_name="李四")
        gate.baseline = "stale"
        signature, allowed = gate.prepare_attribution(SHAPES, FLAGS)
        self.assertTrue(allowed)
        self.assertNotEqual(signature, gate.baseline)
        self.assertEqual(widget.other_data["author"], "李四")
        self.assertIn("modified_at", widget.other_data)

    def test_cancelled_login_refuses_to_write(self):
        widget, gate = _make_gate()
        gate.baseline = "stale"
        gate.ensure_operator = Mock(return_value=False)
        signature, allowed = gate.prepare_attribution(SHAPES, FLAGS)
        self.assertFalse(allowed)
        self.assertNotIn("author", widget.other_data)
        gate.ensure_operator.assert_called_once_with()

    def test_suppressed_attribution_never_prompts(self):
        widget, gate = _make_gate()
        gate.baseline = "stale"
        gate.suppress = True
        _signature, allowed = gate.prepare_attribution(SHAPES, FLAGS)
        self.assertTrue(allowed)
        self.assertNotIn("author", widget.other_data)
        gate.ensure_operator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
