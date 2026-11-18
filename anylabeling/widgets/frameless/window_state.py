"""Small window-state helpers shared by the chrome and the host window."""

from __future__ import annotations

MODE_NORMAL = "normal"
MODE_MAXIMIZED = "maximized"
MODE_FULLSCREEN = "fullscreen"


def mode_of(window) -> str:
    """Return the logical mode of ``window``."""
    if window.isFullScreen():
        return MODE_FULLSCREEN
    if window.isMaximized():
        return MODE_MAXIMIZED
    return MODE_NORMAL


def clamp_geometry(rect, screens):
    """Keep a restored ``QRect`` usable on at least one available screen.

    If the rect does not intersect any screen's available geometry, it is
    centered on the primary screen (the first entry) at its original size,
    with the size capped to the screen size.
    """
    screens = [screen for screen in screens if screen is not None]
    if not screens or rect is None or rect.isEmpty():
        return rect
    available = [screen.availableGeometry() for screen in screens]
    if any(area.intersects(rect) for area in available):
        return rect
    target = available[0]
    width = min(rect.width(), target.width())
    height = min(rect.height(), target.height())
    x = target.x() + (target.width() - width) // 2
    y = target.y() + (target.height() - height) // 2
    return rect.__class__(x, y, width, height)


def next_mode_after_restore(mode: str) -> str:
    """The mode a window returns to when leaving full screen."""
    return MODE_MAXIMIZED if mode == MODE_MAXIMIZED else MODE_NORMAL
