"""Attribution contract for XLABEL annotation files.

Two optional top-level keys are written into the annotation JSON:

``author``
    Display name of the operator responsible for the last content change.
    ``"none"`` is a reserved sentinel for content that was not produced by a
    registered operator (for example data imported from another tool).  A
    missing key is read as ``"none"`` as well, so legacy files need no
    migration and the application never invents an author.

``modified_at``
    Local wall-clock timestamp of that change in ISO 8601 form with the UTC
    offset, for example ``2026-11-17T21:30:00+08:00``.  It is the clock of the
    machine that wrote the file, not a trusted timestamp.

Only a real content change (shapes, labels, attributes, image tags,
description or relations) updates these keys; opening a file, toggling the
review state or changing the dataset split must not.  :func:`content_signature`
exists to make that distinction explicit and testable.
"""

from __future__ import annotations

import datetime
import hashlib
import json

AUTHOR_FIELD = "author"
MODIFIED_AT_FIELD = "modified_at"
AUTHOR_NONE = "none"

_TIME_FORMAT = "%Y-%m-%d %H:%M"


def format_timestamp(value: datetime.datetime | None = None) -> str:
    """Return ``value`` (default: now) as a local ISO 8601 timestamp."""
    moment = value if value is not None else datetime.datetime.now()
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat(timespec="seconds")


def format_display_time(value: object) -> str:
    """Render a stored timestamp for the UI, or an empty string."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        moment = datetime.datetime.fromisoformat(value)
    except ValueError:
        return value.strip()
    return moment.strftime(_TIME_FORMAT)


def normalize_author(value: object) -> str:
    """Return a usable author name; unknown values become ``"none"``."""
    if isinstance(value, str):
        name = value.strip()
        if name and "\r" not in name and "\n" not in name:
            return name
    return AUTHOR_NONE


def ensure_attribution(other_data: dict, has_content: bool) -> bool:
    """Backfill ``author="none"`` for legacy content.

    Legacy files and files produced by importers/converter paths have no
    author.  Marking them explicitly as ``"none"`` keeps the file honest and
    makes the field self-describing.  Returns ``True`` when it changed
    ``other_data``.
    """
    if not isinstance(other_data, dict):
        return False
    if other_data.get(AUTHOR_FIELD):
        return False
    if not has_content:
        return False
    other_data[AUTHOR_FIELD] = AUTHOR_NONE
    return True


def read_attribution(other_data: dict) -> tuple[str, str]:
    """Return ``(author, modified_at)`` for display purposes."""
    if not isinstance(other_data, dict):
        return AUTHOR_NONE, ""
    author = normalize_author(other_data.get(AUTHOR_FIELD))
    modified_at = other_data.get(MODIFIED_AT_FIELD)
    return author, modified_at if isinstance(modified_at, str) else ""


def stamp_attribution(
    other_data: dict,
    operator_name: str,
    *,
    when: datetime.datetime | None = None,
) -> None:
    """Record ``operator_name`` as the author of the current content."""
    if not isinstance(other_data, dict):
        raise TypeError("other_data must be a dict")
    name = normalize_author(operator_name)
    if name == AUTHOR_NONE:
        raise ValueError("An attribution stamp needs a real operator name.")
    other_data[AUTHOR_FIELD] = name
    other_data[MODIFIED_AT_FIELD] = format_timestamp(when)


def content_signature(shapes, flags=None, other_data=None) -> str:
    """Return a stable hash of the annotation content.

    Deliberately excludes review state, split, inference status and the
    attribution keys themselves, so that only real content edits change it.
    """
    data = other_data if isinstance(other_data, dict) else {}
    payload = {
        "shapes": shapes or [],
        "flags": flags or {},
        "tags": data.get("tags") or [],
        "description": data.get("description") or "",
        "relations": data.get("relations") or [],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
