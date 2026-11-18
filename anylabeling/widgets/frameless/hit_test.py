"""Pure geometry helpers for frameless resize and Windows hit testing.

The functions here take device-independent pixels and return edge names, so
they can be unit tested without a display.  ``window.py`` converts the edge
names to Qt edges or Windows ``HT*`` result codes.
"""

from __future__ import annotations

EDGE_LEFT = "left"
EDGE_RIGHT = "right"
EDGE_TOP = "top"
EDGE_BOTTOM = "bottom"

#: Windows hit-test result codes (winuser.h).
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

_HIT_TEST_CODES = {
    (EDGE_LEFT,): HTLEFT,
    (EDGE_RIGHT,): HTRIGHT,
    (EDGE_TOP,): HTTOP,
    (EDGE_BOTTOM,): HTBOTTOM,
    (EDGE_LEFT, EDGE_TOP): HTTOPLEFT,
    (EDGE_RIGHT, EDGE_TOP): HTTOPRIGHT,
    (EDGE_LEFT, EDGE_BOTTOM): HTBOTTOMLEFT,
    (EDGE_RIGHT, EDGE_BOTTOM): HTBOTTOMRIGHT,
}


def edges_at(
    x: int, y: int, width: int, height: int, margin: int
) -> tuple[str, ...]:
    """Return the window edges touched by a point inside the window.

    ``x``/``y`` are client coordinates.  ``margin`` is the resize border
    thickness; a non-positive value disables edge detection.
    """
    if margin <= 0 or width <= 0 or height <= 0:
        return ()
    edges = []
    if x < margin:
        edges.append(EDGE_LEFT)
    elif x > width - 1 - margin:
        edges.append(EDGE_RIGHT)
    if y < margin:
        edges.append(EDGE_TOP)
    elif y > height - 1 - margin:
        edges.append(EDGE_BOTTOM)
    return tuple(edges)


def hit_test_code(
    x: int, y: int, width: int, height: int, margin: int
) -> int:
    """Return the Windows ``HT*`` code for a client point."""
    edges = edges_at(x, y, width, height, margin)
    return _HIT_TEST_CODES.get(edges, HTCLIENT)


_QT_EDGE_NAMES = None


def qt_edges(edges: tuple[str, ...]):
    """Convert edge names to ``Qt.Edge`` flags (imported lazily for tests)."""
    global _QT_EDGE_NAMES
    if _QT_EDGE_NAMES is None:
        from PyQt6.QtCore import Qt

        _QT_EDGE_NAMES = {
            EDGE_LEFT: Qt.Edge.LeftEdge,
            EDGE_RIGHT: Qt.Edge.RightEdge,
            EDGE_TOP: Qt.Edge.TopEdge,
            EDGE_BOTTOM: Qt.Edge.BottomEdge,
        }
    result = None
    for edge in edges:
        flag = _QT_EDGE_NAMES[edge]
        result = flag if result is None else result | flag
    return result
