"""Helpers for the auto-labeling model storage directory.

Downloaded models are stored below a single directory. It defaults to
``<work_dir>/xanylabeling_data/models`` but the user can pick a custom
directory through the settings dialog (the ``model_directory`` config key).

This module is intentionally free of Qt dependencies so it can be unit
tested with temporary directories only.
"""

from __future__ import annotations

import os
import shutil

from anylabeling.config import get_work_directory

DEFAULT_DATA_DIRNAME = "xanylabeling_data"
DEFAULT_MODELS_DIRNAME = "models"


def _default_model_directory_path(work_dir: str | None = None) -> str:
    base_directory = work_dir if work_dir is not None else get_work_directory()
    return os.path.abspath(
        os.path.join(
            os.path.expanduser(base_directory),
            DEFAULT_DATA_DIRNAME,
            DEFAULT_MODELS_DIRNAME,
        )
    )


def default_model_directory(work_dir: str | None = None) -> str:
    """Return the default model directory, creating it when missing."""
    directory = _default_model_directory_path(work_dir)
    os.makedirs(directory, exist_ok=True)
    return directory


def _configured_model_directory(config) -> str | None:
    if config is None:
        return None
    if isinstance(config, dict):
        value = config.get("model_directory")
    else:
        value = getattr(config, "model_directory", None)
    if value in (None, ""):
        return None
    directory = os.path.expanduser(str(value).strip())
    return directory or None


def resolve_model_directory(
    config,
    work_dir: str | None = None,
    create: bool = True,
) -> str:
    """Resolve the active model directory for ``config``.

    When ``config.model_directory`` is set it is used (``~`` is expanded and
    the path is made absolute); otherwise the default location below
    ``work_dir`` is returned. The directory is created unless ``create`` is
    false.
    """
    configured_directory = _configured_model_directory(config)
    if configured_directory:
        directory = os.path.abspath(configured_directory)
        if create:
            os.makedirs(directory, exist_ok=True)
        return directory
    if create:
        return default_model_directory(work_dir)
    return _default_model_directory_path(work_dir)


def migrate_model_directory(old_dir, new_dir) -> list[str]:
    """Move every top-level entry from ``old_dir`` into ``new_dir``.

    Existing destinations with the same name are skipped. Errors are
    collected and returned as human-readable messages; files that could not
    be moved are never deleted and remain in ``old_dir``.
    """
    errors: list[str] = []
    if not old_dir or not new_dir:
        return errors

    old_path = os.path.abspath(os.path.expanduser(str(old_dir)))
    new_path = os.path.abspath(os.path.expanduser(str(new_dir)))
    if os.path.normcase(old_path) == os.path.normcase(new_path):
        return errors
    if not os.path.isdir(old_path):
        return errors
    if os.path.lexists(new_path) and not os.path.isdir(new_path):
        return [f"{new_path}: target exists and is not a directory"]

    try:
        os.makedirs(new_path, exist_ok=True)
    except OSError as exc:
        return [f"{new_path}: {exc}"]

    try:
        with os.scandir(old_path) as entries:
            sorted_entries = sorted(entries, key=lambda entry: entry.name)
    except OSError as exc:
        return [f"{old_path}: {exc}"]

    for entry in sorted_entries:
        source = entry.path
        destination = os.path.join(new_path, entry.name)
        if os.path.lexists(destination):
            continue
        try:
            shutil.move(source, destination)
        except OSError as exc:
            errors.append(f"{entry.name}: {exc}")
    return errors
