"""Translation between XLABEL annotation dictionaries and database rows.

The GUI's ``Shape.to_dict()`` output is the reference shape contract.  This
module is deliberately Qt-free so the storage layer and its tests can run
without a GUI (and so importers can reuse it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .errors import DatasetFormatError

SHAPE_TYPES = {
    "rectangle",
    "rotation",
    "quadrilateral",
    "polygon",
    "point",
    "line",
    "linestrip",
    "circle",
    "cuboid",
}
REVIEW_STATUSES = {"pending", "missed", "false_positive"}
SPLITS = {"none", "train", "val", "test"}

#: Keys that live in dedicated columns or in the geometry object.
KNOWN_SHAPE_KEYS = {
    "label",
    "score",
    "points",
    "group_id",
    "difficult",
    "shape_type",
    "flags",
    "description",
    "attributes",
    "kie_linking",
    "direction",
    "review_status",
    "source",
    "source_model",
    "shape_id",
    "holes",
    "locked",
}

#: Top-level XLABEL keys; everything else is preserved in image_file.extra_json.
KNOWN_TOP_LEVEL_KEYS = {
    "version",
    "flags",
    "checked",
    "shapes",
    "imagePath",
    "imageData",
    "imageHeight",
    "imageWidth",
    "tags",
    "description",
    "split",
    "relations",
    "author",
    "modified_at",
}


@dataclass
class ImageAnnotation:
    """The annotation part of one image."""

    shapes: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    description: str = ""
    split: str | None = None
    relations: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    editor: str = ""
    modified_at: str = ""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: Any, default: Any, label: str) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise DatasetFormatError(f"invalid {label} JSON: {exc}") from exc


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DatasetFormatError(f"{field_name} must be a number")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise DatasetFormatError(f"{field_name} must be finite")
    return result


def normalize_points(points: Iterable[Any], *, field_name: str = "points") -> list[list[float]]:
    """Validate and normalize a point list to ``[[x, y], ...]``."""

    if not isinstance(points, (list, tuple)) or not points:
        raise DatasetFormatError(f"{field_name} must be a non-empty list")
    normalized: list[list[float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise DatasetFormatError(f"{field_name} contains an invalid point")
        normalized.append([_number(point[0], "x"), _number(point[1], "y")])
    return normalized


def _normalize_shape(shape_type: str, points: Iterable[Any]) -> list[list[float]]:
    normalized = normalize_points(points)
    if shape_type == "rectangle" and len(normalized) == 2:
        # Legacy diagonal rectangle: normalize to the four-point contract.
        (x1, y1), (x2, y2) = normalized
        xmin, xmax = sorted((x1, x2))
        ymin, ymax = sorted((y1, y2))
        return [[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]]
    return normalized


def encode_geometry(points: Iterable[Any], holes: Iterable[Any] | None = None) -> str:
    """Encode points/holes as the versioned geometry object."""

    outer = normalize_points(points)
    normalized_holes: list[list[list[float]]] = []
    for ring in holes or []:
        normalized_holes.append(normalize_points(ring, field_name="holes"))
    return _dump(
        {
            "schema_version": 1,
            "outer": outer,
            "holes": normalized_holes,
        }
    )


def decode_geometry(value: str | None) -> tuple[list[list[float]], list[list[list[float]]]]:
    """Decode a geometry value; legacy bare point arrays are accepted."""

    parsed = _load_json(value, [], "points")
    if isinstance(parsed, list):
        return normalize_points(parsed), []
    if isinstance(parsed, dict):
        outer = normalize_points(parsed.get("outer", []), field_name="outer")
        holes = [
            normalize_points(ring, field_name="holes")
            for ring in parsed.get("holes", [])
        ]
        return outer, holes
    raise DatasetFormatError("geometry must be a point list or an object")


def _normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, (list, tuple)):
        raise DatasetFormatError("tags must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise DatasetFormatError("tags must contain strings")
        value = tag.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_relations(relations: Any) -> list[dict[str, Any]]:
    if relations is None:
        return []
    if not isinstance(relations, (list, tuple)):
        raise DatasetFormatError("relations must be a list")
    result: list[dict[str, Any]] = []
    for relation in relations:
        if not isinstance(relation, dict):
            raise DatasetFormatError("relation must be an object")
        subject = relation.get("subject_id")
        target = relation.get("object_id")
        label = relation.get("label")
        if not isinstance(subject, str) or not isinstance(target, str):
            raise DatasetFormatError("relation endpoints must be shape_id strings")
        if not isinstance(label, str) or not label.strip():
            raise DatasetFormatError("relation label must be a non-empty string")
        score = relation.get("score")
        if score is not None:
            score = _number(score, "relation score")
        result.append(
            {
                "subject_id": subject,
                "object_id": target,
                "label": label.strip(),
                "score": score,
            }
        )
    return result


def parse_xlabel_data(data: Mapping[str, Any]) -> ImageAnnotation:
    """Parse a decoded XLABEL JSON object into an :class:`ImageAnnotation`."""

    if not isinstance(data, Mapping):
        raise DatasetFormatError("annotation JSON must be an object")
    shapes = data.get("shapes", [])
    if not isinstance(shapes, (list, tuple)):
        raise DatasetFormatError("shapes must be a list")
    parsed_shapes: list[dict[str, Any]] = []
    for shape in shapes:
        if not isinstance(shape, Mapping):
            raise DatasetFormatError("shape must be an object")
        parsed_shapes.append(dict(shape))
    # Fail at the import boundary, before a partial image row is written.
    shape_ids = []
    for shape in parsed_shapes:
        shape_id = shape.get("shape_id")
        if shape_id is not None and not isinstance(shape_id, str):
            raise DatasetFormatError("shape_id must be a string")
        if shape_id:
            shape_ids.append(shape_id)
    if len(shape_ids) != len(set(shape_ids)):
        raise DatasetFormatError("duplicate shape_id in annotation")
    for index, shape in enumerate(parsed_shapes):
        shape_to_row(shape, image_id=0, category_id=0, sort_index=index)
    flags = data.get("flags", {})
    if flags is None:
        flags = {}
    if not isinstance(flags, dict):
        raise DatasetFormatError("flags must be an object")
    description = data.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise DatasetFormatError("description must be a string")
    split = data.get("split", "none")
    if split is None:
        split = "none"
    if split not in SPLITS:
        raise DatasetFormatError(f"unsupported split: {split!r}")
    author = data.get("author")
    editor = author.strip() if isinstance(author, str) else ""
    if not editor:
        editor = "none" if parsed_shapes else ""
    modified_at = data.get("modified_at")
    if not isinstance(modified_at, str):
        modified_at = ""
    extra = {
        key: value
        for key, value in data.items()
        if key not in KNOWN_TOP_LEVEL_KEYS
    }
    return ImageAnnotation(
        shapes=parsed_shapes,
        flags=flags,
        tags=_normalize_tags(data.get("tags", [])),
        description=description,
        split=split,
        relations=_normalize_relations(data.get("relations", [])),
        extra=extra,
        editor=editor,
        modified_at=modified_at,
    )


def shape_to_row(
    shape: Mapping[str, Any],
    *,
    image_id: int,
    category_id: int,
    sort_index: int,
    uuid: str | None = None,
) -> dict[str, Any]:
    """Translate one XLABEL shape dictionary into annotation_object columns."""

    shape_type = shape.get("shape_type", "polygon")
    if shape_type not in SHAPE_TYPES:
        raise DatasetFormatError(f"unsupported shape_type: {shape_type!r}")
    label = shape.get("label")
    if not isinstance(label, str) or not label.strip():
        raise DatasetFormatError("shape label must be a non-empty string")
    points = _normalize_shape(shape_type, shape.get("points", []))
    holes = shape.get("holes") or []
    if not isinstance(holes, list):
        raise DatasetFormatError("holes must be a list")
    attributes = shape.get("attributes") or {}
    flags = shape.get("flags") or {}
    if not isinstance(attributes, dict) or not isinstance(flags, dict):
        raise DatasetFormatError("shape attributes/flags must be objects")
    kie_linking = shape.get("kie_linking") or []
    if not isinstance(kie_linking, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or any(type(value) is not int for value in pair)
        for pair in kie_linking
    ):
        raise DatasetFormatError("kie_linking must be a list of integer pairs")
    review_status = shape.get("review_status", "pending")
    if review_status not in REVIEW_STATUSES:
        review_status = "pending"
    source = shape.get("source") or "manual"
    if not isinstance(source, str):
        raise DatasetFormatError("source must be a string")
    source_model = shape.get("source_model")
    if source_model is not None and not isinstance(source_model, str):
        raise DatasetFormatError("source_model must be a string or null")
    extra = {
        key: value
        for key, value in shape.items()
        if key not in KNOWN_SHAPE_KEYS
    }
    direction = shape.get("direction")
    if shape_type != "rotation":
        direction = None
    elif direction is not None:
        direction = _number(direction, "direction")
    score = shape.get("score")
    if score is not None:
        score = _number(score, "score")
    group_id = shape.get("group_id")
    if group_id is not None and (isinstance(group_id, bool) or not isinstance(group_id, int)):
        raise DatasetFormatError("group_id must be an integer or null")
    return {
        "uuid": uuid or shape.get("shape_id") or uuid4().hex,
        "image_id": image_id,
        "category_id": category_id,
        "shape_type": shape_type,
        "sort_index": sort_index,
        "points_json": encode_geometry(points, holes),
        "score": score,
        "group_id": group_id,
        "difficult": 1 if shape.get("difficult") else 0,
        "direction": direction,
        "description": str(shape.get("description") or ""),
        "review_status": review_status,
        "source": source,
        "source_model": source_model,
        "attributes_json": _dump(attributes),
        "flags_json": _dump(flags),
        "kie_linking_json": _dump(kie_linking),
        "extra_json": _dump(extra),
    }


def row_to_shape(row: Mapping[str, Any], category_name: str) -> dict[str, Any]:
    """Translate one annotation_object row into an XLABEL shape dictionary."""

    points, holes = decode_geometry(row["points_json"])
    shape: dict[str, Any] = {
        "label": category_name,
        "score": row["score"],
        "points": points,
        "group_id": row["group_id"],
        "difficult": bool(row["difficult"]),
        "shape_type": row["shape_type"],
        "flags": _load_json(row["flags_json"], {}, "shape flags"),
        "attributes": _load_json(row["attributes_json"], {}, "attributes"),
        "kie_linking": _load_json(row["kie_linking_json"], [], "kie_linking"),
        "description": row["description"] or "",
        "review_status": row["review_status"],
        "shape_id": row["uuid"],
    }
    if row["direction"] is not None:
        shape["direction"] = row["direction"]
    if row["source"] and row["source"] != "manual":
        shape["source"] = row["source"]
    if row["source_model"]:
        shape["source_model"] = row["source_model"]
    if holes:
        shape["holes"] = holes
    extra = _load_json(row["extra_json"], {}, "shape extra")
    if not isinstance(extra, dict):
        raise DatasetFormatError("shape extra_json must be an object")
    for key, value in extra.items():
        shape.setdefault(key, value)
    return shape


def relation_rows(
    relations: Iterable[Mapping[str, Any]],
    *,
    image_id: int,
    uuid_to_object_id: Mapping[str, int],
) -> list[dict[str, Any]]:
    """Map XLABEL relations (shape ids) to object_relation rows."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in relations:
        subject = relation.get("subject_id")
        target = relation.get("object_id")
        label = relation.get("label")
        if subject not in uuid_to_object_id or target not in uuid_to_object_id:
            # Shapes can disappear between editing steps; the current UI
            # filters dangling relations the same way.
            continue
        if not isinstance(label, str) or not label:
            continue
        key = (subject, target, label)
        if key in seen:
            continue
        seen.add(key)
        subject_id = uuid_to_object_id[subject]
        object_id = uuid_to_object_id[target]
        if subject_id == object_id:
            continue
        score = relation.get("score")
        result.append(
            {
                "image_id": image_id,
                "subject_object_id": subject_id,
                "object_object_id": object_id,
                "label": label,
                "score": score,
            }
        )
    return result


def relations_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "subject_id": row["subject_uuid"],
            "object_id": row["object_uuid"],
            "label": row["label"],
            "score": row["score"],
        }
        for row in rows
    ]
