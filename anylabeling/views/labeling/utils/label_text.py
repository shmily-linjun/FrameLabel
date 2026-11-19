"""Text helpers for the label and file lists.

These used to be private functions of ``label_widget.py``; the auto-labeling
handoff and the canvas file list need them too, so they live in the utils
package instead of in the window module.
"""

import html


def measure_text_width(font_metrics, text):
    """Return ``text`` width in pixels for both modern and legacy Qt APIs."""
    if hasattr(font_metrics, "horizontalAdvance"):
        return font_metrics.horizontalAdvance(text)
    return font_metrics.width(text)


def format_label_list_text(label, group_id):
    """Format one object-list entry, escaping the label and appending the GID."""
    text = html.escape(label)
    if group_id is None:
        return text
    return f"{text} ({group_id})"
