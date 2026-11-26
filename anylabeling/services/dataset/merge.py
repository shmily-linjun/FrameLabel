"""Dataset merge service (fork.53, T11/P1).

Merges one or more source datasets into a target dataset database.  The merge
is a union of images, annotation objects, image tags and categories; source
databases are opened read-only and never modified.

Decisions implemented here (design doc §4.7, R4–R11):

* copied images go below ``<target>/imported/<source-slug>-<session>/`` so the
  per-dataset ``rel_path`` cannot collide with existing files;
* categories are unified by name (the schema allows one live category per
  name); a cross-name mapping is optional and only comes from the caller;
* objects keep their geometry/attributes but get a fresh ``uuid``;
* ``split`` is kept unless the caller asks for a uniform value;
* images that look duplicated (same file name, size and mtime) are reported,
  never skipped automatically;
* every merge writes an ``import_session`` row so the provenance of each
  image object is traceable.

The module does not import Qt; the dialog calls :func:`plan_merge` for the
dry-run report and :func:`merge_datasets` for the execution.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field, replace as dataclass_replace
from pathlib import Path

from .codec import row_to_shape
from .connection import DatasetDatabase
from .duplicates import (
    ACTION_KEEP_ONE,
    ACTION_MERGE_ANNOTATIONS,
    DuplicateEntry,
    annotation_hash,
    entry_key,
    group_duplicates,
    sha256_file,
)
from .errors import DatasetError
from .repository import DatasetRepository

IMPORTED_DIRNAME = "imported"
MERGE_SOURCE_FORMAT = "dataset-merge"
SPLIT_VALUES = ("none", "train", "val", "test")


class MergeError(Exception):
    """Raised when a merge cannot start or must stop."""


@dataclass
class MergeOptions:
    """Caller decisions for one merge."""

    namespace: str = IMPORTED_DIRNAME
    keep_split: bool = True
    uniform_split: str | None = None
    category_map: dict = field(default_factory=dict)
    skip_empty_categories: bool = False
    check_duplicates: bool = True
    duplicate_actions: dict = field(default_factory=dict)
    batch_size: int = 200
    backup: bool = True
    cancel_check: object = None

    def split_for(self, value: str) -> str:
        if self.uniform_split in SPLIT_VALUES:
            return self.uniform_split
        if value in SPLIT_VALUES:
            return value
        return "none"


@dataclass(frozen=True)
class CategoryDecision:
    source_dataset: str
    source_name: str
    target_name: str
    action: str  # merged | mapped | created | skipped


@dataclass(frozen=True)
class MergeIssue:
    source: str
    path: str
    reason: str


@dataclass
class MergePlan:
    sources: list
    target_db: str
    target_root: str
    new_images: int = 0
    new_objects: int = 0
    duplicate_images: int = 0
    missing_images: int = 0
    categories: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    duplicate_groups: list = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "new_images": self.new_images,
            "new_objects": self.new_objects,
            "duplicate_images": self.duplicate_images,
            "missing_images": self.missing_images,
            "categories": len(self.categories),
        }


@dataclass
class MergeReport:
    plan: MergePlan
    imported_images: int = 0
    imported_objects: int = 0
    skipped_images: int = 0
    skipped_duplicates: int = 0
    merged_annotations: int = 0
    errors: list = field(default_factory=list)
    import_session_id: int | None = None
    target_root: str = ""
    created_root: str = ""
    backup_path: str = ""
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors and not self.cancelled


@dataclass
class _SourceData:
    db_path: str
    root: str
    name: str
    slug: str
    categories: dict
    images: list
    objects: dict
    tags: dict
    relations: dict


def _slug(value: str, fallback: str = "dataset") -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "-", (value or "").strip())
    text = text.strip("-.") or fallback
    return text[:40]


def _read_source(db_path: str) -> _SourceData:
    path = str(db_path)
    try:
        database = DatasetDatabase.open_for_reading(path)
    except Exception as error:  # noqa: BLE001 - surfaced as MergeError
        raise MergeError(f"cannot open source dataset {path}: {error}") from error
    try:
        repository = DatasetRepository(database)
        dataset = repository.dataset()
        root = dataset["root_path"] or str(Path(path).parent)
        categories = {
            int(row["id"]): dict(row)
            for row in database.query(
                "SELECT id, name, color, sort_index, is_deleted FROM category "
                "WHERE dataset_id = ?",
                (repository.dataset_id,),
            )
        }
        images = [
            dict(row)
            for row in database.query(
                "SELECT id, rel_path, file_name, ext, width, height, "
                "size_bytes, mtime_ns, split, description, flags_json, "
                "extra_json, source_label_path, source_label_format "
                "FROM image_file "
                "WHERE dataset_id = ? AND is_deleted = 0 ORDER BY id",
                (repository.dataset_id,),
            )
        ]
        image_ids = {int(row["id"]) for row in images}
        objects = {}
        for row in database.query(
            "SELECT o.id, o.uuid, o.image_id, o.category_id, o.shape_type, "
            "o.sort_index, o.points_json, o.score, o.group_id, "
            "o.difficult, o.direction, o.description, o.review_status, "
            "o.source, o.source_model, o.attributes_json, o.flags_json, "
            "o.kie_linking_json, o.extra_json "
            "FROM annotation_object o "
            "JOIN image_file f ON f.id = o.image_id "
            "WHERE f.dataset_id = ? AND f.is_deleted = 0 "
            "  AND o.is_deleted = 0 ORDER BY o.image_id, o.sort_index, o.id",
            (repository.dataset_id,),
        ):
            objects.setdefault(int(row["image_id"]), []).append(dict(row))
        tags = {}
        for row in database.query(
            "SELECT t.image_id, t.tag, t.sort_index FROM image_tag t "
            "JOIN image_file f ON f.id = t.image_id "
            "WHERE f.dataset_id = ? AND f.is_deleted = 0 "
            "ORDER BY t.image_id, t.sort_index, t.tag",
            (repository.dataset_id,),
        ):
            tags.setdefault(int(row["image_id"]), []).append(dict(row))
        relations = {}
        for row in database.query(
            "SELECT r.image_id, r.subject_object_id, r.object_object_id, "
            "r.label, r.score FROM object_relation r "
            "JOIN image_file f ON f.id = r.image_id "
            "WHERE f.dataset_id = ? AND f.is_deleted = 0",
            (repository.dataset_id,),
        ):
            relations.setdefault(int(row["image_id"]), []).append(dict(row))
        return _SourceData(
            db_path=path,
            root=root,
            name=dataset["name"] or Path(root).name,
            slug=_slug(dataset["name"] or Path(root).name),
            categories=categories,
            images=[row for row in images if int(row["id"]) in image_ids],
            objects=objects,
            tags=tags,
            relations=relations,
        )
    finally:
        database.close()


def _target_annotation_hash(database, dataset_id: int, image_id: int) -> str:
    rows = database.query(
        "SELECT o.*, c.name AS category_name FROM annotation_object o "
        "JOIN category c ON c.id = o.category_id "
        "WHERE o.image_id = ? AND o.is_deleted = 0 "
        "ORDER BY o.sort_index, o.id",
        (image_id,),
    )
    shapes = [row_to_shape(row, row["category_name"]) for row in rows]
    tags = [
        row["tag"]
        for row in database.query(
            "SELECT tag FROM image_tag WHERE image_id = ? "
            "ORDER BY sort_index, tag",
            (image_id,),
        )
    ]
    return annotation_hash(shapes, tags)


def _source_annotation_hash(source, image) -> str:
    shapes = []
    for obj in source.objects.get(int(image["id"]), []):
        category = source.categories.get(int(obj["category_id"]))
        if category is None or category["is_deleted"]:
            continue
        shapes.append(row_to_shape(obj, category["name"]))
    tags = [
        tag["tag"] for tag in source.tags.get(int(image["id"]), [])
    ]
    return annotation_hash(shapes, tags)


def _target_sha_map(target, dataset_id: int) -> dict:
    """``sha256 -> (image id, rel path)`` for images already in the target."""

    has_sha = target.has_column("image_file", "content_sha256")
    columns = "id, rel_path, content_sha256" if has_sha else "id, rel_path"
    rows = target.query(
        f"SELECT {columns} FROM image_file WHERE dataset_id = ? "
        "AND is_deleted = 0",
        (dataset_id,),
    )
    root_row = target.query_one(
        "SELECT root_path FROM dataset WHERE id = ?", (dataset_id,)
    )
    root = Path(root_row["root_path"] or Path(target.path).parent)
    mapping = {}
    for row in rows:
        sha = row["content_sha256"] if has_sha else ""
        if not sha:
            try:
                sha = sha256_file(root / row["rel_path"])
            except OSError:
                continue
            if has_sha:
                target.execute(
                    "UPDATE image_file SET content_sha256 = ? WHERE id = ?",
                    (sha, row["id"]),
                )
        mapping.setdefault(sha, (int(row["id"]), row["rel_path"]))
    return mapping


def _merge_into_target(
    target,
    repository,
    target_image_id,
    source,
    image,
    target_category_names,
    category_ids,
):
    """Append one source image's objects/tags to an existing target image."""

    existing = repository.load_annotation(target_image_id)
    known = {shape.get("shape_id") for shape in existing.shapes}
    appended = 0
    for obj in source.objects.get(int(image["id"]), []):
        category = source.categories.get(int(obj["category_id"]))
        if category is None or category["is_deleted"]:
            continue
        target_id = category_ids.get(
            (source.name, category["name"].casefold())
        )
        if target_id is None:
            continue
        shape = row_to_shape(
            obj, target_category_names.get(int(target_id), category["name"])
        )
        if shape.get("shape_id") in known:
            shape["shape_id"] = uuid.uuid4().hex
        known.add(shape["shape_id"])
        existing.shapes.append(shape)
        appended += 1
    existing.tags = list(
        dict.fromkeys(
            list(existing.tags)
            + [tag["tag"] for tag in source.tags.get(int(image["id"]), [])]
        )
    )
    repository.save_annotation(target_image_id, existing)
    return appended


def _target_existing_keys(database: DatasetDatabase, dataset_id: int) -> set:
    return {
        (
            row["file_name"],
            row["size_bytes"],
            row["mtime_ns"],
        )
        for row in database.query(
            "SELECT file_name, size_bytes, mtime_ns FROM image_file "
            "WHERE dataset_id = ? AND is_deleted = 0",
            (dataset_id,),
        )
    }


def plan_merge(
    source_paths, target_db_path, options: MergeOptions | None = None
) -> MergePlan:
    """Return the dry-run report for merging ``source_paths`` into a target."""

    options = options or MergeOptions()
    target_path = str(target_db_path)
    target_root = str(Path(target_path).parent)
    if not os.path.isfile(target_path):
        raise MergeError(f"target dataset does not exist: {target_path}")
    try:
        target = DatasetDatabase.open_for_reading(target_path)
    except Exception as error:  # noqa: BLE001 - surfaced as MergeError
        raise MergeError(f"cannot open target dataset: {error}") from error
    try:
        repository = DatasetRepository(target)
        dataset = repository.dataset()
        target_root = dataset["root_path"] or str(Path(target_path).parent)
        target_names = {
            row["name"].casefold(): row["name"]
            for row in repository.list_categories()
        }
        existing = _target_existing_keys(target, repository.dataset_id)
        has_sha = target.has_column("image_file", "content_sha256")
        columns = "id, rel_path, content_sha256" if has_sha else "id, rel_path"
        target_entries = []
        for row in target.query(
            f"SELECT {columns} FROM image_file WHERE dataset_id = ? "
            "AND is_deleted = 0",
            (repository.dataset_id,),
        ):
            sha = row["content_sha256"] if has_sha else ""
            if not sha:
                try:
                    sha = sha256_file(Path(target_root) / row["rel_path"])
                except OSError:
                    continue
            target_entries.append(
                DuplicateEntry(
                    key=entry_key(target_path, row["id"]),
                    source="target",
                    path=row["rel_path"],
                    sha256=sha,
                    annotation_hash="",
                    image_id=int(row["id"]),
                )
            )
        plan = MergePlan(
            sources=[str(path) for path in source_paths],
            target_db=target_path,
            target_root=target_root,
        )
        source_entries = []
        for source_path in source_paths:
            source = _read_source(source_path)
            for category_id, category in source.categories.items():
                if category["is_deleted"]:
                    continue
                used = any(
                    int(obj["category_id"]) == category_id
                    for objects in source.objects.values()
                    for obj in objects
                )
                if options.skip_empty_categories and not used:
                    plan.categories.append(
                        CategoryDecision(
                            source.name, category["name"], "", "skipped"
                        )
                    )
                    continue
                requested = options.category_map.get(
                    category["name"], category["name"]
                )
                target_name = target_names.get(requested.casefold(), requested)
                if target_name.casefold() in target_names:
                    action = (
                        "mapped" if requested != category["name"] else "merged"
                    )
                else:
                    action = "created"
                    target_names[target_name.casefold()] = target_name
                plan.categories.append(
                    CategoryDecision(
                        source.name, category["name"], target_name, action
                    )
                )
            for image in source.images:
                plan.new_images += 1
                plan.new_objects += len(
                    source.objects.get(int(image["id"]), [])
                )
                src = Path(source.root) / image["rel_path"]
                if not src.is_file():
                    plan.missing_images += 1
                    plan.issues.append(
                        MergeIssue(
                            source.name, image["rel_path"], "file not found"
                        )
                    )
                    continue
                if options.check_duplicates:
                    source_entries.append(
                        DuplicateEntry(
                            key=entry_key(source_path, image["id"]),
                            source=source.name,
                            path=image["rel_path"],
                            sha256=sha256_file(src),
                            annotation_hash=_source_annotation_hash(
                                source, image
                            ),
                            object_count=len(
                                source.objects.get(int(image["id"]), [])
                            ),
                            tag_count=len(
                                source.tags.get(int(image["id"]), [])
                            ),
                            image_id=int(image["id"]),
                        )
                    )
        if options.check_duplicates:
            groups = group_duplicates(
                list(target_entries) + source_entries
            )
            for group in groups:
                fixed = []
                for entry in group.entries:
                    if entry.source == "target":
                        entry = dataclass_replace(
                            entry,
                            annotation_hash=_target_annotation_hash(
                                target, repository.dataset_id, entry.image_id
                            ),
                        )
                    fixed.append(entry)
                group.entries = fixed
            plan.duplicate_groups = groups
            plan.duplicate_images = sum(
                len(group.entries) - 1 for group in groups
            )
        return plan
    finally:
        target.close()


def create_target_dataset(
    parent_dir: str, name: str, task: str = "", description: str = ""
) -> str:
    """Create an empty dataset database and return its database path."""

    folder = Path(parent_dir) / _slug(name, fallback="dataset")
    if folder.exists() and any(folder.iterdir()):
        raise MergeError(f"target folder is not empty: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    db_path = folder / "xanylabeling.db"
    if db_path.exists():
        raise MergeError(f"target database already exists: {db_path}")
    database = DatasetDatabase.create(
        db_path, name=name, task=task, description=description
    )
    database.close()
    return str(db_path)


def merge_datasets(
    source_paths,
    target_db_path,
    options: MergeOptions | None = None,
    progress=None,
) -> MergeReport:
    """Merge ``source_paths`` into ``target_db_path`` and return a report."""

    options = options or MergeOptions()
    plan = plan_merge(source_paths, target_db_path, options)
    report = MergeReport(
        plan=plan,
        target_root=plan.target_root,
    )
    target_path = str(target_db_path)
    if options.backup:
        report.backup_path = _backup_target(target_path, plan.target_root)
    try:
        target = DatasetDatabase.open(target_path)
    except Exception as error:  # noqa: BLE001 - surfaced as MergeError
        raise MergeError(f"cannot open target dataset: {error}") from error
    try:
        repository = DatasetRepository(target)
        dataset_id = repository.dataset_id
        session_id = _create_import_session(
            target, dataset_id, source_paths, options
        )
        report.import_session_id = session_id
        token = uuid.uuid4().hex[:8]
        category_ids = _prepare_target_categories(
            repository, source_paths, options, report
        )
        sha_to_target = _target_sha_map(target, dataset_id)
        accepted_shas = set(sha_to_target)
        target_category_names = {
            int(row["id"]): row["name"]
            for row in repository.list_categories()
        }
        total = plan.new_images
        done = 0
        for source_path in source_paths:
            source = _read_source(source_path)
            prefix = (
                f"{options.namespace}/{source.slug}-{token}"
                if options.namespace
                else f"{source.slug}-{token}"
            )
            pending = []
            for image in source.images:
                if options.cancel_check is not None and options.cancel_check():
                    report.cancelled = True
                    break
                done += 1
                if progress is not None:
                    progress(done, total)
                src = Path(source.root) / image["rel_path"]
                if not src.is_file():
                    report.skipped_images += 1
                    report.errors.append(
                        f"{source.name}: missing file {image['rel_path']}"
                    )
                    continue
                content_sha256 = sha256_file(src)
                action = options.duplicate_actions.get(
                    entry_key(source_path, image["id"]), ""
                )
                existing_target = sha_to_target.get(content_sha256)
                duplicate_seen = (
                    content_sha256 in accepted_shas
                    or content_sha256 in {
                        item[5] for item in pending
                    }
                )
                if duplicate_seen and action == ACTION_KEEP_ONE:
                    report.skipped_duplicates += 1
                    continue
                if (
                    existing_target is not None
                    and action == ACTION_MERGE_ANNOTATIONS
                ):
                    appended = _merge_into_target(
                        target,
                        repository,
                        existing_target[0],
                        source,
                        image,
                        target_category_names,
                        category_ids,
                    )
                    report.merged_annotations += 1
                    report.imported_objects += appended
                    continue
                dest_rel = str(
                    Path(prefix) / image["rel_path"]
                ).replace(os.sep, "/")
                dest_abs = Path(plan.target_root) / dest_rel
                try:
                    dest_abs.parent.mkdir(parents=True, exist_ok=True)
                    if (
                        not dest_abs.exists()
                        or dest_abs.stat().st_size != src.stat().st_size
                    ):
                        shutil.copy2(src, dest_abs)
                except OSError as error:
                    report.skipped_images += 1
                    report.errors.append(
                        f"{source.name}: cannot copy "
                        f"{image['rel_path']}: {error}"
                    )
                    continue
                accepted_shas.add(content_sha256)
                pending.append(
                    (
                        source,
                        image,
                        dest_rel,
                        category_ids,
                        session_id,
                        content_sha256,
                    )
                )
                if len(pending) >= max(1, int(options.batch_size)):
                    _flush_batch(
                        target,
                        repository,
                        pending,
                        options,
                        report,
                        sha_to_target,
                    )
                    pending = []
            _flush_batch(
                target,
                repository,
                pending,
                options,
                report,
                sha_to_target,
            )
            if report.cancelled:
                break
        _finish_import_session(target, session_id, report)
    finally:
        target.close()
    return report


def _flush_batch(
    target, repository, pending, options, report, sha_to_target
) -> None:
    if not pending:
        return
    with target.transaction() as connection:
        for (
            source,
            image,
            dest_rel,
            category_ids,
            session_id,
            content_sha256,
        ) in pending:
            connection.execute("SAVEPOINT merge_image")
            try:
                image_id = _insert_image(
                    connection,
                    repository.dataset_id,
                    image,
                    dest_rel,
                    options,
                    session_id,
                    content_sha256,
                )
                object_map = _insert_objects(
                    connection,
                    source,
                    image,
                    image_id,
                    category_ids,
                )
                _insert_tags(connection, source, image, image_id)
                _insert_relations(connection, source, image, image_id, object_map)
                connection.execute("RELEASE merge_image")
                report.imported_images += 1
                report.imported_objects += len(object_map)
                sha_to_target.setdefault(
                    content_sha256, (image_id, dest_rel)
                )
            except Exception as error:  # noqa: BLE001 - keep going
                connection.execute("ROLLBACK TO merge_image")
                connection.execute("RELEASE merge_image")
                report.skipped_images += 1
                report.errors.append(
                    f"{source.name}: {image['rel_path']}: {error}"
                )


def _backup_target(target_path: str, root: str) -> str:
    backup_dir = Path(root) / ".backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"xanylabeling-merge-{stamp}.db"
    database = DatasetDatabase.open(target_path)
    try:
        return str(database.backup_to(backup))
    finally:
        database.close()


def _create_import_session(
    target, dataset_id: int, source_paths, options: MergeOptions
) -> int:
    with target.transaction():
        cursor = target.execute(
            "INSERT INTO import_session "
            "(dataset_id, source_format, source_path, class_source, "
            " options_json, category_map_json, stats_json, app_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dataset_id,
                MERGE_SOURCE_FORMAT,
                json.dumps([str(path) for path in source_paths]),
                "",
                json.dumps(
                    {
                        "namespace": options.namespace,
                        "uniform_split": options.uniform_split,
                        "skip_empty_categories": options.skip_empty_categories,
                        "batch_size": options.batch_size,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(options.category_map, ensure_ascii=False),
                "{}",
                "",
            ),
        )
        return int(cursor.lastrowid)


def _finish_import_session(target, session_id: int, report: MergeReport) -> None:
    with target.transaction():
        target.execute(
            "UPDATE import_session SET stats_json = ? WHERE id = ?",
            (
                json.dumps(
                    {
                        "imported_images": report.imported_images,
                        "imported_objects": report.imported_objects,
                        "skipped_images": report.skipped_images,
                        "errors": len(report.errors),
                    },
                    ensure_ascii=False,
                ),
                session_id,
            ),
        )


def _prepare_target_categories(
    repository, source_paths, options: MergeOptions, report: MergeReport
) -> dict:
    """Return ``{(source_name casefold): target category id}``."""

    mapping = {}
    target_names = {
        row["name"].casefold(): int(row["id"])
        for row in repository.list_categories()
    }
    for source_path in source_paths:
        source = _read_source(source_path)
        for category in source.categories.values():
            if category["is_deleted"]:
                continue
            requested = options.category_map.get(
                category["name"], category["name"]
            )
            key = requested.casefold()
            if key not in target_names:
                target_names[key] = repository.ensure_category(
                    requested, category.get("color")
                )
            mapping[(source.name, category["name"].casefold())] = target_names[key]
    return mapping


def _category_id(category_ids: dict, source_name: str, category_name: str) -> int:
    key = (source_name, (category_name or "").casefold())
    if key in category_ids:
        return category_ids[key]
    raise DatasetError(f"unknown category mapping for {category_name!r}")


def _insert_image(
    connection,
    dataset_id: int,
    image: dict,
    rel_path: str,
    options,
    session_id,
    content_sha256: str = "",
) -> int:
    cursor = connection.execute(
        "INSERT INTO image_file "
        "(dataset_id, rel_path, file_name, ext, width, height, size_bytes, "
        " mtime_ns, split, description, flags_json, extra_json, editor, "
        " modified_at, import_session_id, source_label_path, "
        " source_label_format, content_sha256) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            dataset_id,
            rel_path,
            image["file_name"],
            image["ext"],
            image["width"],
            image["height"],
            image["size_bytes"],
            image["mtime_ns"],
            options.split_for(image["split"]),
            image["description"],
            image["flags_json"],
            image["extra_json"],
            "",
            "",
            session_id,
            image["source_label_path"],
            image["source_label_format"],
            content_sha256,
        ),
    )
    return int(cursor.lastrowid)


def _insert_objects(
    connection, source, image, image_id: int, category_ids: dict
) -> dict:
    object_map = {}
    for obj in source.objects.get(int(image["id"]), []):
        category = source.categories.get(int(obj["category_id"]))
        if category is None or category["is_deleted"]:
            continue
        target_category = _category_id(
            category_ids, source.name, category["name"]
        )
        new_uuid = str(uuid.uuid4())
        cursor = connection.execute(
            "INSERT INTO annotation_object "
            "(uuid, image_id, category_id, shape_type, sort_index, "
            " points_json, score, group_id, difficult, direction, "
            " description, review_status, source, source_model, "
            " attributes_json, flags_json, kie_linking_json, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_uuid,
                image_id,
                target_category,
                obj["shape_type"],
                obj["sort_index"],
                obj["points_json"],
                obj["score"],
                obj["group_id"],
                obj["difficult"],
                obj["direction"],
                obj["description"],
                obj["review_status"],
                obj["source"],
                obj["source_model"],
                obj["attributes_json"],
                obj["flags_json"],
                obj["kie_linking_json"],
                obj["extra_json"],
            ),
        )
        object_map[int(obj["id"])] = int(cursor.lastrowid)
    return object_map


def _insert_tags(connection, source, image, image_id: int) -> None:
    for tag in source.tags.get(int(image["id"]), []):
        connection.execute(
            "INSERT OR IGNORE INTO image_tag (image_id, tag, sort_index) "
            "VALUES (?, ?, ?)",
            (image_id, tag["tag"], tag["sort_index"]),
        )


def _insert_relations(
    connection, source, image, image_id: int, object_map: dict
) -> None:
    for relation in source.relations.get(int(image["id"]), []):
        subject = object_map.get(int(relation["subject_object_id"]))
        target = object_map.get(int(relation["object_object_id"]))
        if subject is None or target is None:
            continue
        connection.execute(
            "INSERT OR IGNORE INTO object_relation "
            "(image_id, subject_object_id, object_object_id, label, score) "
            "VALUES (?, ?, ?, ?, ?)",
            (image_id, subject, target, relation["label"], relation["score"]),
        )
