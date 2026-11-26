import json
import sqlite3
from pathlib import Path

from anylabeling.services.dataset.schema import SCHEMA_SQL


def _normalized_master(connection):
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return [
        (row[0], row[1], row[2], " ".join((row[3] or "").split()))
        for row in rows
    ]


def _columns(connection):
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {
        table: [
            (row[1], row[2], row[3], row[4])
            for row in connection.execute(f"PRAGMA table_info({table})")
        ]
        for table in tables
    }


def test_package_schema_matches_design_asset():
    design_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "dev"
        / "db_design_assets"
        / "schema.sql"
    )
    design_sql = design_path.read_text(encoding="utf-8")

    packaged = sqlite3.connect(":memory:")
    design = sqlite3.connect(":memory:")
    try:
        packaged.executescript(SCHEMA_SQL)
        design.executescript(design_sql)
        assert _normalized_master(packaged) == _normalized_master(design)
        assert _columns(packaged) == _columns(design)
    finally:
        packaged.close()
        design.close()


def test_package_schema_has_expected_shape():
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(SCHEMA_SQL)
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        views = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            )
        ]
        columns = sum(
            len(connection.execute(f"PRAGMA table_info({table})").fetchall())
            for table in tables
        )
        assert len(tables) == 8
        assert len(views) == 3
        assert columns == 87
        image_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(image_file)")
        }
        assert {"editor", "modified_at", "deleted_at", "content_sha256"} <= image_columns
        assert "checked" not in image_columns
        index_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='index' AND name='ux_image_file_rel_path'"
        ).fetchone()[0]
        assert "COLLATE NOCASE" in index_sql
    finally:
        connection.close()
