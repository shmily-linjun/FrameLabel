"""Native file and folder dialogs (fork.60).

Every file/folder picker should go through these helpers so the
native-dialog policy lives in one place:

* the ``DontUseNativeDialog`` option is never set, so Qt uses the platform
  dialog on Windows and macOS, the platform theme dialog on Linux desktops
  (GTK/KDE/portal) and falls back to its own widget dialog when the platform
  has no native integration (for example ``QT_QPA_PLATFORM=offscreen``);
* the returned paths are normalized to plain strings (Qt returns `str` for
  directories and `(str, str)` for files).

Native dialogs cannot host custom widgets, so the old
``FileDialogPreview`` (an image/JSON preview pane added to the dialog layout)
was removed: it required the non-native ``QFileDialog`` and crashed when the
native dialog was enabled (fork.42 → fork.59 regression).  See the design doc
§4.5 for the decision.
"""

from __future__ import annotations

from PyQt6 import QtWidgets

DIRECTORY_OPTIONS = (
    QtWidgets.QFileDialog.Option.ShowDirsOnly
    | QtWidgets.QFileDialog.Option.DontResolveSymlinks
)


def choose_directory(
    parent,
    title: str,
    directory: str = "",
    options=QtWidgets.QFileDialog.Option(0),
) -> str:
    """Pick one directory; empty string means the user cancelled."""

    path = QtWidgets.QFileDialog.getExistingDirectory(
        parent, title, directory or "", options
    )
    return str(path or "")


def choose_open_file(
    parent,
    title: str,
    directory: str = "",
    filters: str = "",
    options=QtWidgets.QFileDialog.Option(0),
) -> str:
    """Pick one existing file; empty string means the user cancelled."""

    path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
        parent, title, directory or "", filters or "", options=options
    )
    return str(path or "")


def choose_open_files(
    parent,
    title: str,
    directory: str = "",
    filters: str = "",
    options=QtWidgets.QFileDialog.Option(0),
) -> list:
    """Pick existing files; an empty list means the user cancelled."""

    paths, _selected_filter = QtWidgets.QFileDialog.getOpenFileNames(
        parent, title, directory or "", filters or "", options=options
    )
    return [str(path) for path in paths or ()]


def choose_save_file(
    parent,
    title: str,
    directory: str = "",
    filters: str = "",
    options=QtWidgets.QFileDialog.Option(0),
) -> str:
    """Pick a save path; empty string means the user cancelled."""

    path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
        parent, title, directory or "", filters or "", options=options
    )
    return str(path or "")
