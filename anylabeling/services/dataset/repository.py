"""Dataset table operations used by the T3 storage layer.

This module is Qt-free.  The GUI will call it through a thin adapter; the
importer uses it directly.  All multi-row writes run in one transaction.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .codec import (
    ImageAnnotation,
    SPLITS,
    relation_rows,
    relations_from_rows,
    row_to_shape,
    shape_to_row,
)
from .connection import DatasetDatabase
from .errors import DatasetConflictError, DatasetFormatError, DatasetNotFoundError

_OBJECT_UPDATE_COLUMNS = (
    "category_id = ?",
    "shape_type = ?",
    "sort_index = ?",
    "points_json = ?",
    "score = ?",
    "group_id = ?",
    "difficult = ?",
    "direction = ?",
    "description = ?",
    "review_status = ?",
    "source = ?",
    "source_model = ?",
    "attributes_json = ?",
    "flags_json = ?",
    "kie_linking_json = ?",
    "extra_json = ?",
    "is_deleted = 0",
    "updated_at = ?",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: Any, default: Any, label: str) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise DatasetFormatError(f"invalid {label} JSON: {exc}") from exc


def _normalize_rel_path(rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise DatasetFormatError("rel_path must be a non-empty string")
    value = rel_path.replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    value = value.lstrip("/")
    if not value or ".." in Path(value).parts:
        raise DatasetFormatError(f"invalid rel_path: {rel_path!r}")
    return value


class DatasetRepository:
    """CRUD for one dataset database."""

    def __init__(self, database: DatasetDatabase):
        self.db = database
        row = database.query_one("SELECT id FROM dataset ORDER BY id LIMIT 1")
        if row is None:
            raise DatasetNotFoundError("dataset table has no row")
        self.dataset_id = int(row["id"])

    # -- dataset / categories ---------------------------------------------
    def dataset(self) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM dataset WHERE id = ?", (self.dataset_id,)
        )
        if row is None:
            raise DatasetNotFoundError("dataset row disappeared")
        return dict(row)

    def update_dataset_metadata(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update the dataset display name and/or its free-text note.

        Both fields are dataset-level metadata: the dataset center writes them
        (fork.53).  ``updated_at`` is refreshed on every write; ``description``
        is capped so a pasted document cannot bloat the database.
        """

        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise DatasetFormatError("dataset name must not be empty")
            name = name.strip()
            if len(name) > 128:
                raise DatasetFormatError("dataset name is too long")
        if description is not None:
            if not isinstance(description, str):
                raise DatasetFormatError("dataset description must be a string")
            if len(description) > 10000:
                raise DatasetFormatError("dataset description is too long")
        current = self.dataset()
        values = []
        assignments = []
        if name is not None:
            assignments.append("name = ?")
            values.append(name)
        if description is not None:
            assignments.append("description = ?")
            values.append(description)
        if not assignments:
            return current
        assignments.append("updated_at = ?")
        values.append(_now())
        values.append(self.dataset_id)
        self.db.execute(
            "UPDATE dataset SET " + ", ".join(assignments) + " WHERE id = ?",
            tuple(values),
        )
        return self.dataset()

    def overview(self) -> dict[str, Any]:
        """Return the dataset-center counters.

        Everything is aggregated in SQL (no image decoding, no JSON scan):
        active/trashed images, objects, categories, split counts, per-category
        image/object counts and the image-tag vocabulary.
        """

        totals = self.db.query_one(
            "SELECT "
            "(SELECT COUNT(*) FROM image_file "
            " WHERE dataset_id = ? AND is_deleted = 0) AS images, "
            "(SELECT COUNT(*) FROM image_file "
            " WHERE dataset_id = ? AND is_deleted = 1) AS trashed, "
            "(SELECT COUNT(*) FROM annotation_object o "
            " JOIN image_file f ON f.id = o.image_id "
            " WHERE f.dataset_id = ? AND f.is_deleted = 0 "
            "   AND o.is_deleted = 0) AS objects, "
            "(SELECT COUNT(*) FROM category "
            " WHERE dataset_id = ? AND is_deleted = 0) AS categories",
            (self.dataset_id,) * 4,
        )
        split_rows = self.db.query(
            "SELECT split, COUNT(*) AS count FROM image_file "
            "WHERE dataset_id = ? AND is_deleted = 0 GROUP BY split",
            (self.dataset_id,),
        )
        splits = {str(row["split"]): int(row["count"]) for row in split_rows}
        category_rows = self.db.query(
            "SELECT c.name AS name, "
            " (SELECT COUNT(DISTINCT o.image_id) FROM annotation_object o "
            "  JOIN image_file f ON f.id = o.image_id "
            "  WHERE o.category_id = c.id AND o.is_deleted = 0 "
            "    AND f.is_deleted = 0) AS image_count, "
            " (SELECT COUNT(*) FROM annotation_object o "
            "  JOIN image_file f ON f.id = o.image_id "
            "  WHERE o.category_id = c.id AND o.is_deleted = 0 "
            "    AND f.is_deleted = 0) AS object_count "
            "FROM category c "
            "WHERE c.dataset_id = ? AND c.is_deleted = 0 "
            "ORDER BY c.sort_index, c.name COLLATE NOCASE",
            (self.dataset_id,),
        )
        tags = self.tag_counts()
        return {
            "dataset": self.dataset(),
            "totals": {
                "images": int(totals["images"]),
                "trashed": int(totals["trashed"]),
                "objects": int(totals["objects"]),
                "categories": int(totals["categories"]),
                "tag_kinds": len(tags),
            },
            "splits": {
                split: int(splits.get(split, 0))
                for split in ("train", "val", "test", "none")
            },
            "categories": [
                {
                    "name": row["name"],
                    "image_count": int(row["image_count"]),
                    "object_count": int(row["object_count"]),
                }
                for row in category_rows
            ],
            "tags": [
                {
                    "tag": row["tag"],
                    "image_count": int(row["image_count"]),
                }
                for row in tags
            ],
        }

    def list_categories(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT id, name, color, sort_index, in_class_list, description "
            "FROM category WHERE dataset_id = ? AND is_deleted = 0 "
            "ORDER BY sort_index, name",
            (self.dataset_id,),
        )
        return [dict(row) for row in rows]

    def ensure_category(self, name: str, color: str | None = None) -> int:
        if not isinstance(name, str) or not name.strip():
            raise DatasetFormatError("category name must be a non-empty string")
        value = name.strip()
        row = self.db.query_one(
            "SELECT id, color FROM category "
            "WHERE dataset_id = ? AND name = ? AND is_deleted = 0",
            (self.dataset_id, value),
        )
        if row is not None:
            if color and not row["color"]:
                self.db.execute(
                    "UPDATE category SET color = ?, updated_at = ? WHERE id = ?",
                    (color, _now(), row["id"]),
                )
            return int(row["id"])
        deleted = self.db.query_one(
            "SELECT id FROM category "
            "WHERE dataset_id = ? AND name = ? AND is_deleted = 1",
            (self.dataset_id, value),
        )
        if deleted is not None:
            self.db.execute(
                "UPDATE category SET is_deleted = 0, color = COALESCE(?, color), "
                "updated_at = ? WHERE id = ?",
                (color, _now(), deleted["id"]),
            )
            return int(deleted["id"])
        row = self.db.query_one(
            "SELECT COALESCE(MAX(sort_index), -1) + 1 AS next_index "
            "FROM category WHERE dataset_id = ?",
            (self.dataset_id,),
        )
        sort_index = int(row["next_index"]) if row else 0
        cursor = self.db.execute(
            "INSERT INTO category (dataset_id, name, color, sort_index) "
            "VALUES (?, ?, ?, ?)",
            (self.dataset_id, value, color, sort_index),
        )
        return int(cursor.lastrowid)

    def category_object_count(self, name: str) -> int:
        """Return the number of active objects in a category."""
        row = self.db.query_one(
            "SELECT COUNT(o.id) AS count "
            "FROM category c "
            "LEFT JOIN annotation_object o "
            "  ON o.category_id = c.id AND o.is_deleted = 0 "
            "WHERE c.dataset_id = ? AND c.name = ? AND c.is_deleted = 0",
            (self.dataset_id, str(name)),
        )
        return int(row["count"]) if row is not None else 0

    def rename_category(self, old: str, new: str) -> bool:
        """Rename an empty category row (used by batch import/rename)."""
        old = str(old).strip()
        new = str(new).strip()
        if not old or not new:
            return False
        if old == new:
            return True
        row = self.db.query_one(
            "SELECT id FROM category "
            "WHERE dataset_id = ? AND name = ? AND is_deleted = 0",
            (self.dataset_id, old),
        )
        if row is None:
            return False
        conflict = self.db.query_one(
            "SELECT id FROM category "
            "WHERE dataset_id = ? AND name = ? AND is_deleted = 0",
            (self.dataset_id, new),
        )
        if conflict is not None:
            return False
        self.db.execute(
            "UPDATE category SET name = ?, updated_at = ? WHERE id = ?",
            (new, _now(), row["id"]),
        )
        return True

    def delete_category(self, name: str) -> bool:
        """Soft-delete an empty category row."""
        if self.category_object_count(name) > 0:
            return False
        cursor = self.db.execute(
            "UPDATE category SET is_deleted = 1, updated_at = ? "
            "WHERE dataset_id = ? AND name = ? AND is_deleted = 0",
            (_now(), self.dataset_id, str(name)),
        )
        return cursor.rowcount > 0

    def category_names(self) -> dict[int, str]:
        rows = self.db.query(
            "SELECT id, name FROM category WHERE dataset_id = ? AND is_deleted = 0",
            (self.dataset_id,),
        )
        return {int(row["id"]): row["name"] for row in rows}

    # -- images ------------------------------------------------------------
    def list_images(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM image_file WHERE dataset_id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY rel_path COLLATE NOCASE"
        return [dict(row) for row in self.db.query(sql, (self.dataset_id,))]

    def image_summaries(
        self,
        *,
        labels: list[str] | None = None,
        tags: list[str] | None = None,
        split: str | None = None,
        objectless: bool = False,
        filename: str | None = None,
        editor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Rows for the file table: image fields + object count + tags.

        ``labels``/``tags``/``editor``/``split``/``objectless``/``filename``
        are a fast SQL path for the common search terms (``label::``,
        ``tags::``, ``editor::``, ``split::``, ``shape::0``, plain filename
        text); complex boolean expressions still fall back to the in-Python
        query evaluator.
        """

        where = ["f.dataset_id = ?", "f.is_deleted = 0"]
        params: list[Any] = [self.dataset_id]
        if split is not None:
            where.append("f.split = ?")
            params.append(split)
        if objectless:
            where.append(
                "NOT EXISTS (SELECT 1 FROM annotation_object o "
                "WHERE o.image_id = f.id AND o.is_deleted = 0)"
            )
        if filename:
            where.append("instr(f.file_name, ?) > 0")
            params.append(filename)
        if editor:
            where.append("f.editor = ? COLLATE NOCASE")
            params.append(editor)
        for label in labels or ():
            where.append(
                "EXISTS (SELECT 1 FROM annotation_object o "
                "JOIN category c ON c.id = o.category_id "
                "WHERE o.image_id = f.id AND o.is_deleted = 0 "
                "AND c.name = ?)"
            )
            params.append(label)
        for tag in tags or ():
            where.append(
                "EXISTS (SELECT 1 FROM image_tag t "
                "WHERE t.image_id = f.id AND t.tag = ? COLLATE NOCASE)"
            )
            params.append(tag)
        rows = self.db.query(
            "SELECT f.*, "
            " (SELECT COUNT(*) FROM annotation_object o "
            "   WHERE o.image_id = f.id AND o.is_deleted = 0) AS object_count, "
            " (SELECT GROUP_CONCAT(tag, char(31)) FROM ("
            "    SELECT tag FROM image_tag WHERE image_id = f.id "
            "    ORDER BY sort_index, tag)) AS tags "
            "FROM image_file f "
            "WHERE " + " AND ".join(where) + " "
            "ORDER BY f.rel_path COLLATE NOCASE",
            tuple(params),
        )
        result = []
        for row in rows:
            item = dict(row)
            text = item.get("tags") or ""
            item["tags"] = [tag for tag in text.split(chr(31)) if tag]
            result.append(item)
        return result

    def statistics_rows(self) -> list[dict[str, Any]]:
        """Per-image labels/split for the statistics tab (one row per image)."""

        rows = self.db.query(
            "SELECT f.id, f.rel_path, f.split, c.name AS label "
            "FROM image_file f "
            "LEFT JOIN annotation_object o "
            "  ON o.image_id = f.id AND o.is_deleted = 0 "
            "LEFT JOIN category c ON c.id = o.category_id "
            "WHERE f.dataset_id = ? AND f.is_deleted = 0 "
            "ORDER BY f.id, o.sort_index, o.id",
            (self.dataset_id,),
        )
        result = []
        by_image = {}
        for row in rows:
            image_id = row["id"]
            item = by_image.get(image_id)
            if item is None:
                item = {
                    "path": row["rel_path"],
                    "split": row["split"],
                    "labels": [],
                }
                by_image[image_id] = item
                result.append(item)
            if row["label"] is not None:
                item["labels"].append(row["label"])
        return result

    def category_counts(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT c.name, COUNT(o.id) AS object_count "
            "FROM category c "
            "LEFT JOIN annotation_object o "
            "  ON o.category_id = c.id AND o.is_deleted = 0 "
            "WHERE c.dataset_id = ? AND c.is_deleted = 0 "
            "GROUP BY c.id "
            "ORDER BY c.sort_index, c.name COLLATE NOCASE",
            (self.dataset_id,),
        )
        return [dict(row) for row in rows]

    def tag_counts(
        self, rel_paths: Iterable[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return the image-tag vocabulary of active images.

        ``rel_paths`` restricts the counts to the images currently shown in
        the file table; ``None`` means the whole dataset.  Results are ordered
        by usage (most used first), then case-insensitively by name.
        """

        base_sql = (
            "SELECT t.tag AS tag, COUNT(*) AS image_count "
            "FROM image_tag t "
            "JOIN image_file f ON f.id = t.image_id "
            "WHERE f.dataset_id = ? AND f.is_deleted = 0 "
        )
        if rel_paths is None:
            rows = self.db.query(
                base_sql
                + "GROUP BY t.tag "
                "ORDER BY image_count DESC, t.tag COLLATE NOCASE, t.tag",
                (self.dataset_id,),
            )
            return [dict(row) for row in rows]

        values = []
        seen = set()
        for path in rel_paths:
            value = _normalize_rel_path(path)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        if not values:
            return []
        counts: dict[str, int] = {}
        for start in range(0, len(values), 900):
            chunk = values[start : start + 900]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.db.query(
                base_sql
                + f"AND f.rel_path IN ({placeholders}) "
                "GROUP BY t.tag",
                [self.dataset_id, *chunk],
            )
            for row in rows:
                tag = row["tag"]
                counts[tag] = counts.get(tag, 0) + int(row["image_count"])
        return [
            {"tag": tag, "image_count": count}
            for tag, count in sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0].casefold(), item[0]),
            )
        ]

    def set_category_order(self, names: Iterable[str]) -> bool:
        """Persist the display order of categories (D7/D18).

        ``names`` is the desired order of the categories that are currently
        visible; categories missing from the list keep their relative slots
        (for example categories that only exist in the class dictionary).
        ``sort_index`` is rewritten for the whole dataset, so later exports
        read the same order.
        """

        wanted = [str(name) for name in names]
        if not wanted or len(set(wanted)) != len(wanted):
            return False
        ordered = [row["name"] for row in self.list_categories()]
        visible = set(wanted)
        slots = [
            index
            for index, name in enumerate(ordered)
            if name in visible
        ]
        if len(slots) != len(wanted):
            return False
        result = list(ordered)
        for slot, name in zip(slots, wanted):
            result[slot] = name
        now = _now()
        with self.db.transaction():
            for index, name in enumerate(result):
                self.db.execute(
                    "UPDATE category SET sort_index = ?, updated_at = ? "
                    "WHERE dataset_id = ? AND name = ? AND is_deleted = 0",
                    (index, now, self.dataset_id, name),
                )
        return True

    def rewrite_categories(
        self,
        image_ids: list[int],
        renames: dict[str, str],
        deletes: set[str],
    ) -> int:
        """Apply category renames/deletes to the active objects of images."""

        if not image_ids or (not renames and not deletes):
            return 0
        for old, new in renames.items():
            if not isinstance(old, str) or not isinstance(new, str) or not new:
                raise DatasetFormatError("invalid category rename")
        ids = sorted({int(image_id) for image_id in image_ids})
        now = _now()
        changed = 0
        with self.db.transaction():
            for image_id in ids:
                image_changed = 0
                rows = self.db.query(
                    "SELECT o.id, c.name AS label "
                    "FROM annotation_object o "
                    "JOIN category c ON c.id = o.category_id "
                    "WHERE o.image_id = ? AND o.is_deleted = 0",
                    (image_id,),
                )
                for row in rows:
                    label = row["label"]
                    if label in deletes:
                        self.db.execute(
                            "UPDATE annotation_object SET is_deleted = 1, "
                            "updated_at = ? WHERE id = ?",
                            (now, row["id"]),
                        )
                        image_changed += 1
                    elif label in renames:
                        target = renames[label]
                        category_id = self.ensure_category(target)
                        self.db.execute(
                            "UPDATE annotation_object SET category_id = ?, "
                            "updated_at = ? WHERE id = ?",
                            (category_id, now, row["id"]),
                        )
                        image_changed += 1
                if image_changed:
                    self.db.execute(
                        "UPDATE image_file SET updated_at = ? WHERE id = ?",
                        (now, image_id),
                    )
                    changed += image_changed
        return changed

    def move_image(self, image_id: int, rel_path: str) -> bool:
        """Move an image row to a new relative path inside the dataset."""
        value = _normalize_rel_path(rel_path)
        image = self.get_image(image_id)
        if image is None:
            return False
        conflict = self.find_image(value)
        if conflict is not None and int(conflict["id"]) != int(image_id):
            raise DatasetConflictError(
                f"cannot move image to {value}: path is already active"
            )
        path = Path(value)
        self.db.execute(
            "UPDATE image_file SET rel_path = ?, file_name = ?, ext = ?, "
            "updated_at = ? WHERE id = ?",
            (value, path.name, path.suffix.lower(), _now(), image_id),
        )
        return True

    def get_image(
        self, image_id: int, *, include_deleted: bool = False
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM image_file WHERE id = ? AND dataset_id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        row = self.db.query_one(sql, (image_id, self.dataset_id))
        return dict(row) if row is not None else None

    def find_image(self, rel_path: str) -> dict[str, Any] | None:
        value = _normalize_rel_path(rel_path)
        row = self.db.query_one(
            "SELECT * FROM image_file "
            "WHERE dataset_id = ? AND rel_path = ? COLLATE NOCASE "
            "AND is_deleted = 0",
            (self.dataset_id, value),
        )
        return dict(row) if row is not None else None

    def set_split(self, image_id: int, split: str) -> bool:
        if split not in SPLITS:
            raise DatasetFormatError(f"unsupported split: {split!r}")
        cursor = self.db.execute(
            "UPDATE image_file SET split = ?, updated_at = ? "
            "WHERE id = ? AND dataset_id = ? AND is_deleted = 0",
            (split, _now(), image_id, self.dataset_id),
        )
        return cursor.rowcount > 0

    def add_image(
        self,
        rel_path: str,
        *,
        width: int | None = None,
        height: int | None = None,
        size_bytes: int | None = None,
        mtime_ns: int | None = None,
        split: str | None = None,
        description: str | None = None,
        flags: Mapping[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
        editor: str | None = None,
        modified_at: str | None = None,
        import_session_id: int | None = None,
        content_sha256: str = "",
    ) -> int:
        value = _normalize_rel_path(rel_path)
        if split is not None and split not in SPLITS:
            raise DatasetFormatError(f"unsupported split: {split!r}")
        path = Path(value)
        file_name = path.name
        ext = path.suffix.lower()
        existing = self.find_image(value)
        if existing is not None:
            fields = []
            parameters: list[Any] = []
            for column, item in (
                ("width", width),
                ("height", height),
                ("size_bytes", size_bytes),
                ("mtime_ns", mtime_ns),
                ("content_sha256", content_sha256 or None),
                ("split", split),
                ("description", description),
                ("editor", editor),
                ("modified_at", modified_at),
            ):
                if item is not None:
                    fields.append(f"{column} = ?")
                    parameters.append(item)
            if flags is not None:
                fields.append("flags_json = ?")
                parameters.append(_dump(dict(flags)))
            if extra is not None:
                fields.append("extra_json = ?")
                parameters.append(_dump(dict(extra)))
            if import_session_id is not None:
                fields.append("import_session_id = ?")
                parameters.append(import_session_id)
            if fields:
                fields.append("updated_at = ?")
                parameters.append(_now())
                parameters.append(existing["id"])
                self.db.execute(
                    f"UPDATE image_file SET {', '.join(fields)} WHERE id = ?",
                    parameters,
                )
            return int(existing["id"])

        cursor = self.db.execute(
            "INSERT INTO image_file "
            "(dataset_id, rel_path, file_name, ext, width, height, size_bytes, "
            " mtime_ns, split, description, flags_json, extra_json, editor, "
            " modified_at, import_session_id, content_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.dataset_id,
                value,
                file_name,
                ext,
                width,
                height,
                size_bytes,
                mtime_ns,
                split or "none",
                description or "",
                _dump(dict(flags or {})),
                _dump(dict(extra or {})),
                editor or "",
                modified_at or "",
                import_session_id,
                content_sha256 or "",
            ),
        )
        return int(cursor.lastrowid)

    # -- annotation reads --------------------------------------------------
    def load_annotation(self, image_id: int) -> ImageAnnotation:
        image = self.get_image(image_id)
        if image is None:
            raise DatasetNotFoundError(f"image not found: {image_id}")
        rows = self.db.query(
            "SELECT o.*, c.name AS category_name FROM annotation_object o "
            "JOIN category c ON c.id = o.category_id "
            "WHERE o.image_id = ? AND o.is_deleted = 0 "
            "ORDER BY o.sort_index, o.id",
            (image_id,),
        )
        shapes = [row_to_shape(row, row["category_name"]) for row in rows]
        tags = [
            row["tag"]
            for row in self.db.query(
                "SELECT tag FROM image_tag WHERE image_id = ? ORDER BY sort_index, tag",
                (image_id,),
            )
        ]
        relation_rows_db = self.db.query(
            "SELECT r.*, su.uuid AS subject_uuid, ou.uuid AS object_uuid "
            "FROM object_relation r "
            "JOIN annotation_object su ON su.id = r.subject_object_id "
            "JOIN annotation_object ou ON ou.id = r.object_object_id "
            "WHERE r.image_id = ? ORDER BY r.id",
            (image_id,),
        )
        return ImageAnnotation(
            shapes=shapes,
            flags=_load(image["flags_json"], {}, "image flags"),
            tags=tags,
            description=image["description"] or "",
            split=image["split"],
            relations=relations_from_rows(relation_rows_db),
            extra=_load(image["extra_json"], {}, "image extra"),
            editor=image["editor"] or "",
            modified_at=image["modified_at"] or "",
        )

    # -- annotation writes -------------------------------------------------
    def save_annotation(
        self,
        image_id: int,
        annotation: ImageAnnotation,
        *,
        editor: str | None = None,
        modified_at: str | None = None,
    ) -> int:
        """Replace one image's annotation in a single transaction.

        Objects are upserted by ``shape_id``/uuid; objects missing from the
        payload are soft-deleted, and restored if their uuid comes back.
        ``editor``/``modified_at`` are written only when the caller has
        detected a real content change.
        """

        image = self.get_image(image_id)
        if image is None:
            raise DatasetNotFoundError(f"image not found: {image_id}")
        if annotation.split is not None and annotation.split not in SPLITS:
            raise DatasetFormatError(f"unsupported split: {annotation.split!r}")

        with self.db.transaction():
            category_ids: dict[str, int] = {}
            for shape in annotation.shapes:
                label = shape.get("label")
                if not isinstance(label, str) or not label.strip():
                    raise DatasetFormatError("shape label must be a non-empty string")
                if label not in category_ids:
                    category_ids[label] = self.ensure_category(label)

            existing = self.db.query(
                "SELECT id, uuid FROM annotation_object WHERE image_id = ?",
                (image_id,),
            )
            by_uuid = {row["uuid"]: int(row["id"]) for row in existing}
            seen: set[str] = set()
            now = _now()
            for sort_index, shape in enumerate(annotation.shapes):
                label = shape["label"]
                uuid = shape.get("shape_id") or uuid4().hex
                if not isinstance(uuid, str) or not uuid:
                    raise DatasetFormatError("shape_id must be a non-empty string")
                if uuid in seen:
                    raise DatasetFormatError(f"duplicate shape_id in payload: {uuid}")
                seen.add(uuid)
                row = shape_to_row(
                    shape,
                    image_id=image_id,
                    category_id=category_ids[label],
                    sort_index=sort_index,
                    uuid=uuid,
                )
                other = self.db.query_one(
                    "SELECT image_id FROM annotation_object WHERE uuid = ?",
                    (uuid,),
                )
                if other is not None and int(other["image_id"]) != image_id:
                    raise DatasetConflictError(
                        f"shape_id {uuid} already belongs to another image"
                    )
                if uuid in by_uuid:
                    parameters = [
                        row["category_id"],
                        row["shape_type"],
                        row["sort_index"],
                        row["points_json"],
                        row["score"],
                        row["group_id"],
                        row["difficult"],
                        row["direction"],
                        row["description"],
                        row["review_status"],
                        row["source"],
                        row["source_model"],
                        row["attributes_json"],
                        row["flags_json"],
                        row["kie_linking_json"],
                        row["extra_json"],
                        now,
                        uuid,
                    ]
                    self.db.execute(
                        f"UPDATE annotation_object SET {', '.join(_OBJECT_UPDATE_COLUMNS)} "
                        "WHERE uuid = ?",
                        parameters,
                    )
                else:
                    self.db.execute(
                        "INSERT INTO annotation_object "
                        "(uuid, image_id, category_id, shape_type, sort_index, "
                        " points_json, score, group_id, difficult, direction, "
                        " description, review_status, source, source_model, "
                        " attributes_json, flags_json, kie_linking_json, extra_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row["uuid"],
                            row["image_id"],
                            row["category_id"],
                            row["shape_type"],
                            row["sort_index"],
                            row["points_json"],
                            row["score"],
                            row["group_id"],
                            row["difficult"],
                            row["direction"],
                            row["description"],
                            row["review_status"],
                            row["source"],
                            row["source_model"],
                            row["attributes_json"],
                            row["flags_json"],
                            row["kie_linking_json"],
                            row["extra_json"],
                        ),
                    )

            if seen:
                placeholders = ", ".join("?" for _ in seen)
                self.db.execute(
                    "UPDATE annotation_object SET is_deleted = 1, updated_at = ? "
                    f"WHERE image_id = ? AND is_deleted = 0 AND uuid NOT IN ({placeholders})",
                    (now, image_id, *seen),
                )
            else:
                self.db.execute(
                    "UPDATE annotation_object SET is_deleted = 1, updated_at = ? "
                    "WHERE image_id = ? AND is_deleted = 0",
                    (now, image_id),
                )

            self.db.execute("DELETE FROM image_tag WHERE image_id = ?", (image_id,))
            for sort_index, tag in enumerate(annotation.tags):
                self.db.execute(
                    "INSERT INTO image_tag (image_id, tag, sort_index) VALUES (?, ?, ?)",
                    (image_id, tag, sort_index),
                )

            self.db.execute(
                "DELETE FROM object_relation WHERE image_id = ?", (image_id,)
            )
            id_by_uuid = {
                row["uuid"]: int(row["id"])
                for row in self.db.query(
                    "SELECT uuid, id FROM annotation_object "
                    "WHERE image_id = ? AND is_deleted = 0",
                    (image_id,),
                )
            }
            for relation in relation_rows(
                annotation.relations,
                image_id=image_id,
                uuid_to_object_id=id_by_uuid,
            ):
                self.db.execute(
                    "INSERT INTO object_relation "
                    "(image_id, subject_object_id, object_object_id, label, score) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        relation["image_id"],
                        relation["subject_object_id"],
                        relation["object_object_id"],
                        relation["label"],
                        relation["score"],
                    ),
                )

            fields = [
                "description = ?",
                "flags_json = ?",
                "extra_json = ?",
                "updated_at = ?",
            ]
            parameters: list[Any] = [
                annotation.description,
                _dump(annotation.flags),
                _dump(annotation.extra),
                now,
            ]
            if annotation.split is not None:
                fields.append("split = ?")
                parameters.append(annotation.split)
            if editor is not None:
                fields.append("editor = ?")
                parameters.append(editor)
            if modified_at is not None:
                fields.append("modified_at = ?")
                parameters.append(modified_at)
            parameters.append(image_id)
            self.db.execute(
                f"UPDATE image_file SET {', '.join(fields)} WHERE id = ?",
                parameters,
            )
        return len(seen)

    # -- recycle bin -------------------------------------------------------
    def delete_image(self, image_id: int) -> bool:
        image = self.get_image(image_id)
        if image is None:
            return False
        self.db.execute(
            "UPDATE image_file SET is_deleted = 1, deleted_at = ?, updated_at = ? "
            "WHERE id = ?",
            (_now(), _now(), image_id),
        )
        return True

    def restore_image(self, image_id: int) -> bool:
        image = self.get_image(image_id, include_deleted=True)
        if image is None:
            return False
        conflict = self.db.query_one(
            "SELECT id FROM image_file "
            "WHERE dataset_id = ? AND rel_path = ? COLLATE NOCASE "
            "AND is_deleted = 0 AND id <> ?",
            (self.dataset_id, image["rel_path"], image_id),
        )
        if conflict is not None:
            raise DatasetConflictError(
                f"cannot restore {image['rel_path']}: path is already active"
            )
        self.db.execute(
            "UPDATE image_file SET is_deleted = 0, deleted_at = NULL, updated_at = ? "
            "WHERE id = ?",
            (_now(), image_id),
        )
        return True

    def purge_image(self, image_id: int) -> bool:
        cursor = self.db.execute(
            "DELETE FROM image_file WHERE id = ? AND dataset_id = ?",
            (image_id, self.dataset_id),
        )
        return cursor.rowcount > 0

    def list_trash(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM image_file "
            "WHERE dataset_id = ? AND is_deleted = 1 "
            "ORDER BY deleted_at DESC, id DESC",
            (self.dataset_id,),
        )
        return [dict(row) for row in rows]

    # -- import sessions ---------------------------------------------------
    def create_import_session(
        self,
        source_format: str,
        *,
        source_path: str = "",
        class_source: str = "",
        options: Mapping[str, Any] | None = None,
        app_version: str = "",
    ) -> int:
        cursor = self.db.execute(
            "INSERT INTO import_session "
            "(dataset_id, source_format, source_path, class_source, "
            " options_json, category_map_json, stats_json, app_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.dataset_id,
                source_format,
                source_path,
                class_source,
                _dump(dict(options or {})),
                "[]",
                "{}",
                app_version,
            ),
        )
        return int(cursor.lastrowid)

    def finish_import_session(
        self, session_id: int, stats: Mapping[str, Any]
    ) -> None:
        self.db.execute(
            "UPDATE import_session SET stats_json = ? WHERE id = ?",
            (_dump(dict(stats)), session_id),
        )
