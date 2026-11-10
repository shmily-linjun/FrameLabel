"""Read and write per-image metadata stored in X-AnyLabeling JSON files.

The annotation files are treated as JSON documents that may contain keys this
module does not know about; :func:`write_split` only touches the ``split``
field and preserves everything else. Files that do not exist yet are created
in the same format :class:`~anylabeling.views.labeling.label_file.LabelFile`
uses, so the labeling application can load them without extra fixes.
"""

import dataclasses
import datetime
import json
import os
import os.path as osp
import tempfile
from typing import Union

from anylabeling.app_info import __version__

from .image import get_pil_img_dim

SPLIT_NONE = "none"
SPLIT_TRAIN = "train"
SPLIT_VAL = "val"
SPLIT_TEST = "test"

SPLIT_KEYS = (SPLIT_NONE, SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST)

SPLIT_LABELS = {
    SPLIT_NONE: {"zh": "未划分", "en": "None"},
    SPLIT_TRAIN: {"zh": "训练", "en": "Train"},
    SPLIT_VAL: {"zh": "验证", "en": "Val"},
    SPLIT_TEST: {"zh": "测试", "en": "Test"},
}

_EMPTY_TIME_LABEL = "—"
_TIME_FORMAT = "%Y-%m-%d %H:%M"

#: Sidecar file written next to the images to remember when each image was
#: first imported. It is app metadata, so it deliberately does not live in the
#: annotation JSON files (those may not exist for unlabeled images).
IMPORT_TIME_FILENAME = ".xanylabeling_import_time.json"
_IMPORT_TIME_VERSION = 1


@dataclasses.dataclass
class FileMeta:
    """Metadata shown for one image in the file list."""

    exists: bool
    checked: Union[bool, str]
    shape_count: int
    split: str
    import_time: float


def read_file_meta(image_path, label_file=None):
    """Collect :class:`FileMeta` for ``image_path``.

    ``label_file`` defaults to the sidecar JSON path derived from the image
    path. A missing, unreadable or malformed annotation file is not an error:
    ``exists`` is ``False`` and all other fields keep their empty defaults.
    """
    import_time = _stat_mtime(image_path)
    if label_file is None:
        label_file = _default_label_file(image_path)
    path = _to_path(label_file)
    if not path:
        return FileMeta(False, False, 0, SPLIT_NONE, import_time)

    data = _load_json(path)
    if not isinstance(data, dict):
        return FileMeta(False, False, 0, SPLIT_NONE, import_time)

    shapes = data.get("shapes") or []
    try:
        shape_count = len(shapes)
    except TypeError:
        shape_count = 0
    checked = _normalize_checked(data.get("checked", False))
    split = _normalize_split(data.get("split", SPLIT_NONE))
    return FileMeta(True, checked, shape_count, split, import_time)


def format_import_time(ts):
    """Render an ``mtime`` timestamp for display, or ``"—"`` if unusable."""
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return _EMPTY_TIME_LABEL
    if value <= 0:
        return _EMPTY_TIME_LABEL
    try:
        return datetime.datetime.fromtimestamp(value).strftime(_TIME_FORMAT)
    except (OSError, OverflowError, ValueError):
        return _EMPTY_TIME_LABEL


def import_time_file_for(image_path):
    """Return the sidecar path that stores import times for ``image_path``."""
    path = _to_path(image_path)
    if not path:
        return ""
    directory = osp.dirname(osp.abspath(path))
    if not directory:
        return ""
    return osp.join(directory, IMPORT_TIME_FILENAME)


def read_import_times(directory):
    """Read the import-time sidecar of ``directory`` (``{}`` when missing)."""
    path = _to_path(directory)
    if not path:
        return {}
    return _read_import_time_sidecar(
        osp.join(path, IMPORT_TIME_FILENAME)
    )


def read_import_time(image_path):
    """Return the persisted import time of ``image_path``.

    Falls back to the file ``mtime`` when the sidecar has no entry yet, so
    files that pre-date this feature still show something meaningful.
    """
    path = _to_path(image_path)
    if not path:
        return 0.0
    sidecar = read_import_times(osp.dirname(osp.abspath(path)))
    name = osp.basename(path)
    value = sidecar.get(name)
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return _stat_mtime(path)


def ensure_import_times(image_paths):
    """Remember the current time for images that have no import time yet.

    ``image_paths`` may span several directories; each directory gets its own
    sidecar file. Returns ``{image_path: import_time}`` for every path.
    """
    now = datetime.datetime.now().timestamp()
    result = {}
    per_directory = {}
    for image_path in image_paths or ():
        path = _to_path(image_path)
        if not path:
            continue
        directory = osp.dirname(osp.abspath(path))
        per_directory.setdefault(directory, []).append(path)

    for directory, paths in per_directory.items():
        sidecar_path = osp.join(directory, IMPORT_TIME_FILENAME)
        sidecar = _read_import_time_sidecar(sidecar_path)
        changed = False
        for path in paths:
            name = osp.basename(path)
            value = sidecar.get(name)
            if not isinstance(value, (int, float)) or float(value) <= 0:
                sidecar[name] = now
                changed = True
            result[path] = float(sidecar[name])
        if changed and sidecar:
            _atomic_write_json(
                sidecar_path,
                {"version": _IMPORT_TIME_VERSION, "import_time": sidecar},
            )
    return result


def read_split(label_file):
    """Return the ``split`` stored in ``label_file`` (defaults to ``none``)."""
    path = _to_path(label_file)
    if not path:
        return SPLIT_NONE
    data = _load_json(path)
    if not isinstance(data, dict):
        return SPLIT_NONE
    return _normalize_split(data.get("split", SPLIT_NONE))


def write_split(label_file, split, image_path=None):
    """Store ``split`` in ``label_file`` and return whether it was written.

    An existing annotation file is updated in place: every other key is
    preserved and the file is replaced atomically. When the file is missing a
    minimal loadable label file is created; ``image_path`` is then used for
    ``imagePath`` and the ``imageHeight``/``imageWidth`` fields.
    """
    path = _to_path(label_file)
    if not path or not _is_valid_split(split):
        return False

    if osp.exists(path):
        data = _load_json(path)
        if not isinstance(data, dict):
            return False
    else:
        data = _build_minimal_label_file(image_path, split)

    data["split"] = split
    return _atomic_write_json(path, data)


# -- helpers ------------------------------------------------------------
def _is_valid_split(split):
    return isinstance(split, str) and split in SPLIT_KEYS


def _normalize_split(value):
    return value if _is_valid_split(value) else SPLIT_NONE


def _normalize_checked(value):
    if value == "failed":
        return "failed"
    return value is True


def _to_path(value):
    if value is None:
        return ""
    try:
        path = os.fspath(value)
    except TypeError:
        path = value
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, str):
        path = str(path)
    return path


def _default_label_file(image_path):
    path = _to_path(image_path)
    if not path:
        return ""
    if path.lower().endswith(".json"):
        return path
    return osp.splitext(path)[0] + ".json"


def _stat_mtime(image_path):
    path = _to_path(image_path)
    if not path:
        return 0.0
    try:
        return float(os.stat(path).st_mtime)
    except (OSError, ValueError):
        return 0.0


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError, TypeError):
        return None
    return data


def _read_import_time_sidecar(sidecar_path):
    path = _to_path(sidecar_path)
    if not path or not osp.isfile(path):
        return {}
    data = _load_json(path)
    if not isinstance(data, dict):
        return {}
    values = data.get("import_time")
    if not isinstance(values, dict):
        return {}
    cleaned = {}
    for name, value in values.items():
        if isinstance(name, str) and isinstance(value, (int, float)):
            cleaned[name] = float(value)
    return cleaned


def _build_minimal_label_file(image_path, split):
    image_name = ""
    image_height = None
    image_width = None
    path = _to_path(image_path)
    if path:
        image_name = osp.basename(path)
        try:
            image_width, image_height = get_pil_img_dim(path)
        except Exception:
            image_height = None
            image_width = None
    return {
        "version": __version__,
        "flags": {},
        "shapes": [],
        "imagePath": image_name,
        "imageData": None,
        "imageHeight": image_height,
        "imageWidth": image_width,
        "split": split,
    }


def _atomic_write_json(path, data):
    directory = osp.dirname(osp.abspath(path))
    temporary_file = None
    try:
        fd, temporary_file = tempfile.mkstemp(
            prefix=".xal_",
            suffix=".tmp",
            dir=directory,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_file, path)
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if temporary_file and osp.exists(temporary_file):
            try:
                os.remove(temporary_file)
            except OSError:
                pass
