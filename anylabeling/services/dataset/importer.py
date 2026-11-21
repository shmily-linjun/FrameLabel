"""Import an X-AnyLabeling JSON directory into a dataset database.

P0 scope: XLABEL JSON only, sibling ``<image>.json`` files, one database per
dataset.  The source files are read-only; no image or JSON is moved or
rewritten.  Other formats (LabelMe/COCO/YOLO/...) are later phases.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from PIL import Image

from .codec import ImageAnnotation, parse_xlabel_data
from .connection import DATABASE_FILENAME, DatasetDatabase
from .errors import DatasetConflictError, DatasetFormatError
from .repository import DatasetRepository

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
}
SKIPPED_DIRECTORIES = {".trash", "__pycache__", "_delete_"}


@dataclass
class ImportReport:
    database_path: Path
    backup_path: Path | None = None
    images: int = 0
    labeled_images: int = 0
    objects: int = 0
    tags: int = 0
    relations: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_stats(self) -> dict[str, Any]:
        return {
            "images": self.images,
            "labeled_images": self.labeled_images,
            "objects": self.objects,
            "tags": self.tags,
            "relations": self.relations,
            "skipped": self.skipped,
            "errors": len(self.errors),
        }


def iter_image_files(folder: Path) -> Iterator[Path]:
    for root, directories, files in os.walk(folder):
        directories[:] = [
            name
            for name in sorted(directories)
            if name not in SKIPPED_DIRECTORIES
        ]
        for name in sorted(files):
            path = Path(root) / name
            if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
                yield path


def _image_size(
    image_path: Path, json_data: dict[str, Any] | None
) -> tuple[int | None, int | None]:
    if json_data:
        height = json_data.get("imageHeight")
        width = json_data.get("imageWidth")
        if (
            isinstance(height, int)
            and isinstance(width, int)
            and height > 0
            and width > 0
        ):
            return height, width
    try:
        with Image.open(image_path) as image:
            return image.height, image.width
    except Exception:
        return None, None


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise DatasetFormatError("annotation JSON must be an object")
    return data


def _backup_path(database_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    candidate = database_path.with_name(
        f"{database_path.stem}.backup-{stamp}.db"
    )
    counter = 1
    while candidate.exists():
        candidate = database_path.with_name(
            f"{database_path.stem}.backup-{stamp}-{counter}.db"
        )
        counter += 1
    return candidate


def import_xlabel_folder(
    folder: str | Path,
    *,
    database_path: str | Path | None = None,
    overwrite: str = "skip",
    backup: bool = True,
    name: str | None = None,
    task: str = "detect",
    app_version: str = "",
) -> ImportReport:
    """Import ``<image>.json`` pairs into ``<folder>/xanylabeling.db``.

    ``overwrite`` controls existing image rows: ``skip`` (default),
    ``replace`` or ``error``.
    """

    if overwrite not in {"skip", "replace", "error"}:
        raise ValueError("overwrite must be 'skip', 'replace' or 'error'")
    source = Path(folder)
    if not source.is_dir():
        raise DatasetFormatError(f"not a directory: {source}")
    target = (
        Path(database_path)
        if database_path is not None
        else source / DATABASE_FILENAME
    )

    backup_path: Path | None = None
    if target.exists():
        database = DatasetDatabase.open(target)
        if backup:
            backup_path = database.backup_to(_backup_path(target))
    else:
        database = DatasetDatabase.create(
            target,
            name=name or source.name,
            task=task,
            app_version=app_version,
        )

    report = ImportReport(database_path=target, backup_path=backup_path)
    repository = DatasetRepository(database)
    session_id = repository.create_import_session(
        "xlabel-json",
        source_path=str(source),
        options={"overwrite": overwrite},
        app_version=app_version,
    )
    try:
        for image_path in iter_image_files(source):
            relative = image_path.relative_to(source).as_posix()
            json_path = image_path.with_suffix(".json")
            data: dict[str, Any] | None = None
            annotation: ImageAnnotation | None = None
            if json_path.is_file():
                try:
                    data = _read_json(json_path)
                    annotation = parse_xlabel_data(data)
                except Exception as exc:  # noqa: BLE001 - reported per file
                    report.errors.append(f"{relative}: {exc}")
                    continue

            existing = repository.find_image(relative)
            if existing is not None and overwrite == "skip":
                report.skipped += 1
                continue
            if existing is not None and overwrite == "error":
                raise DatasetConflictError(
                    f"image already exists in dataset: {relative}"
                )

            height, width = _image_size(image_path, data)
            stat = image_path.stat()
            report.images += 1
            if annotation is not None:
                report.labeled_images += 1
                report.objects += len(annotation.shapes)
                report.tags += len(annotation.tags)
                report.relations += len(annotation.relations)
                editor = annotation.editor or None
                modified_at = annotation.modified_at or None
                split = annotation.split
                description = annotation.description
                flags = annotation.flags
                extra = annotation.extra
            else:
                annotation = ImageAnnotation(split=None, editor="", modified_at="")
                # Replacing a previously labeled image with an unlabeled one
                # must clear the old attribution, not keep it.
                editor = "" if existing is not None else None
                modified_at = "" if existing is not None else None
                split = None
                description = ""
                flags = {}
                extra = {}

            image_id = repository.add_image(
                relative,
                width=width,
                height=height,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                split=split,
                description=description,
                flags=flags,
                extra=extra,
                editor=editor,
                modified_at=modified_at,
                import_session_id=session_id,
            )
            repository.save_annotation(
                image_id,
                annotation,
                editor=editor,
                modified_at=modified_at,
            )
    finally:
        repository.finish_import_session(session_id, report.as_stats())
        database.close()

    return report
