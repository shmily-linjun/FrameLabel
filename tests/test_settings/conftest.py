"""Shared setup for the settings test package.

Some settings tests only need a ``QCoreApplication`` while the dialog tests
need a ``QApplication``. Qt allows a single application instance per process
and creating a ``QApplication`` after a bare ``QCoreApplication`` makes Qt
abort, so make sure a headless ``QApplication`` exists before any test in this
package runs.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtWidgets

    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
except Exception:  # pragma: no cover - PyQt6 may be unavailable
    _APP = None
