"""Tests for the dataset statistics aggregation helpers."""

import json
from pathlib import Path

from anylabeling.views.labeling.utils import dataset_statistics
from anylabeling.views.labeling.utils.dataset_statistics import (
    COLUMN_COUNT,
    COLUMN_HEADERS,
    COLUMN_SPLITS,
    COLUMN_TOTAL,
    OBJECTLESS_ROW_LABEL,
    ROW_KIND_CLASS,
    ROW_KIND_OBJECTLESS,
    ROW_KIND_TOTAL,
    SPLIT_INDEX_TOTAL,
    SPLIT_NONE,
    SPLIT_ORDER,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
    STATISTICS_TAB_TITLE,
    TOTAL_COLUMN_HEADER,
    TOTAL_ROW_LABEL,
    ClassSplitTable,
    FileStatisticsEntry,
    StatisticsFilter,
    build_class_split_table,
    collect_entries,
    filter_for_cell,
    image_label_file,
    normalize_split,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)


def _make_images(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    return images


def _make_entries():
    """Small hand-built dataset: two classes, objectless and invalid split."""
    return [
        FileStatisticsEntry("a.jpg", SPLIT_TRAIN, ("person", "car"), True),
        FileStatisticsEntry("b.jpg", SPLIT_VAL, ("person",), True),
        FileStatisticsEntry("c.jpg", SPLIT_TEST, (), True),
        FileStatisticsEntry("d.jpg", SPLIT_NONE, (), False),
        FileStatisticsEntry("e.jpg", "bogus", ("car", "car"), True),
    ]


# -- module constants -----------------------------------------------------
def test_display_constants_match_the_specification():
    assert SPLIT_ORDER == (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST, SPLIT_NONE)
    # tr() sources are English; zh/ja/ko are provided by the .ts files.
    assert COLUMN_HEADERS == (
        "Class",
        "Train",
        "Val",
        "Test",
        "Unassigned",
        "Total",
    )
    assert COLUMN_COUNT == 6
    assert COLUMN_SPLITS == (1, 2, 3, 4)
    assert COLUMN_TOTAL == 5
    assert SPLIT_INDEX_TOTAL == 4
    assert TOTAL_COLUMN_HEADER == "Total"
    assert OBJECTLESS_ROW_LABEL == "(No objects)"
    assert TOTAL_ROW_LABEL == "Total"
    assert STATISTICS_TAB_TITLE == "Statistics"


def test_normalize_split():
    assert normalize_split("train") == SPLIT_TRAIN
    assert normalize_split(SPLIT_VAL) == SPLIT_VAL
    assert normalize_split("bogus") == SPLIT_NONE
    assert normalize_split(None) == SPLIT_NONE
    assert normalize_split(3) == SPLIT_NONE


# -- collect_entries ------------------------------------------------------
def test_collect_entries_labels_split_and_missing_json(tmp_path):
    images = _make_images(tmp_path)
    _write_json(
        images / "a.json",
        {
            "split": "train",
            "shapes": [
                {"label": "person"},
                {"label": "car"},
                {"label": "person"},
            ],
        },
    )
    _write_json(images / "b.json", {"shapes": [{"label": "dog"}]})
    _write_json(
        images / "c.json",
        {
            "split": "bogus",
            "shapes": [
                {"label": ""},
                {"label": 3},
                {"label": "dog"},
                {"oops": 1},
                "not-a-shape",
            ],
        },
    )
    (images / "broken.json").write_text("{not json", encoding="utf-8")

    files = [
        str(images / name)
        for name in (
            "a.jpg",
            "b.jpg",
            "c.jpg",
            "broken.jpg",
            "missing.jpg",
        )
    ]
    entries = collect_entries(files)

    assert [entry.path for entry in entries] == files
    assert entries[0].split == SPLIT_TRAIN
    assert entries[0].labels == ("car", "person")
    assert entries[0].has_label_file is True
    assert entries[0].is_objectless is False

    assert entries[1].split == SPLIT_NONE
    assert entries[1].labels == ("dog",)

    # Invalid split values fall back to ``none`` and unusable labels are
    # ignored; the remaining valid label is kept.
    assert entries[2].split == SPLIT_NONE
    assert entries[2].labels == ("dog",)

    assert entries[3].has_label_file is False
    assert entries[3].split == SPLIT_NONE
    assert entries[3].labels == ()
    assert entries[3].is_objectless is True

    assert entries[4].has_label_file is False
    assert entries[4].labels == ()
    assert entries[4].is_objectless is True


def test_collect_entries_prefers_output_dir_annotations(tmp_path):
    images = _make_images(tmp_path)
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    image_path = images / "x.jpg"
    _write_json(
        images / "x.json",
        {"split": "train", "shapes": [{"label": "next-to-image"}]},
    )
    _write_json(
        labels_dir / "x.json",
        {"split": "val", "shapes": [{"label": "in-output-dir"}]},
    )

    entries = collect_entries([str(image_path)], str(labels_dir))

    assert len(entries) == 1
    assert entries[0].path == str(image_path)
    assert entries[0].split == SPLIT_VAL
    assert entries[0].labels == ("in-output-dir",)

    # pathlib output directories are accepted as well
    entries_with_path = collect_entries([image_path], labels_dir)
    assert entries_with_path[0].labels == ("in-output-dir",)


def test_collect_entries_handles_empty_input():
    assert collect_entries([]) == []
    assert collect_entries(None) == []


def test_image_label_file_resolution(tmp_path):
    images = _make_images(tmp_path)
    labels_dir = tmp_path / "labels"
    image_path = images / "photo.png"

    assert image_label_file(str(image_path)) == str(images / "photo.json")
    assert (
        image_label_file(str(image_path), str(labels_dir))
        == str(labels_dir / "photo.json")
    )
    assert image_label_file(image_path, labels_dir) == str(
        labels_dir / "photo.json"
    )
    assert image_label_file("") == ""


# -- build_class_split_table ---------------------------------------------
def test_build_class_split_table_counts_and_totals():
    table = build_class_split_table(_make_entries())

    assert isinstance(table, ClassSplitTable)
    assert table.classes == ("car", "person")
    assert table.splits == SPLIT_ORDER

    # A multi-label image contributes to every class row it contains.
    assert table.counts["car"] == {
        SPLIT_TRAIN: 1,
        SPLIT_VAL: 0,
        SPLIT_TEST: 0,
        SPLIT_NONE: 1,
    }
    assert table.counts["person"] == {
        SPLIT_TRAIN: 1,
        SPLIT_VAL: 1,
        SPLIT_TEST: 0,
        SPLIT_NONE: 0,
    }
    # Duplicate labels inside a hand-built entry count once.
    assert table.count_for("car", SPLIT_TRAIN) == 1
    assert table.count_for("person", SPLIT_VAL) == 1
    assert table.count_for("missing", SPLIT_TRAIN) == 0

    assert table.objectless_counts == {
        SPLIT_TRAIN: 0,
        SPLIT_VAL: 0,
        SPLIT_TEST: 1,
        SPLIT_NONE: 1,
    }
    assert table.objectless_for(SPLIT_TEST) == 1
    assert table.objectless_total == 2

    assert table.class_totals == {"car": 2, "person": 2}
    assert table.total_for_class("person") == 2

    # The totals row counts *files* per split (one image with two classes is
    # counted once), so it is NOT the sum of the class cells above it.
    assert table.split_totals == {
        SPLIT_TRAIN: 1,
        SPLIT_VAL: 1,
        SPLIT_TEST: 1,
        SPLIT_NONE: 2,
    }
    assert table.total_for_split(SPLIT_TRAIN) == 1
    assert table.total == 5
    assert table.total == table.entry_count
    assert table.entry_count == 5
    assert table.is_empty is False


def test_split_totals_count_files_not_class_cells():
    """A multi-label image must be counted once in the totals row."""
    entries = [
        FileStatisticsEntry(
            "overlap.jpg", SPLIT_NONE, ("1234", "all_defect"), True
        ),
        FileStatisticsEntry("defect.jpg", SPLIT_NONE, ("all_defect",), True),
        FileStatisticsEntry("train.jpg", SPLIT_TRAIN, ("1234",), True),
    ]

    table = build_class_split_table(entries)

    # Class cells duplicate the multi-label image: 1 + 2 = 3 cells ...
    assert table.count_for("1234", SPLIT_NONE) == 1
    assert table.count_for("all_defect", SPLIT_NONE) == 2
    # ... but the totals row counts files (2), not the 3 class cells.
    assert table.split_totals[SPLIT_NONE] == 2
    assert table.split_totals[SPLIT_TRAIN] == 1
    assert table.total == 3
    # Class-row totals stay per-class image counts.
    assert table.class_totals == {"1234": 2, "all_defect": 2}
    assert table.objectless_total == 0


def test_reference_screenshot_numbers():
    """Reproduce the reference screenshot: bottom row = file counts."""
    entries = [
        FileStatisticsEntry(
            "overlap.jpg", SPLIT_NONE, ("1234", "all_defect"), True
        )
    ]
    entries += [
        FileStatisticsEntry(
            "defect-%d.jpg" % index, SPLIT_NONE, ("all_defect",), True
        )
        for index in range(1810)
    ]
    entries += [
        FileStatisticsEntry("empty-%d.jpg" % index, SPLIT_NONE, (), True)
        for index in range(5888)
    ]
    entries += [
        FileStatisticsEntry("train-%d.jpg" % index, SPLIT_TRAIN, (), True)
        for index in range(2)
    ]

    table = build_class_split_table(entries)

    # Class rows: 1234: none=1, total=1; all_defect: none=1811, total=1811.
    assert table.count_for("1234", SPLIT_NONE) == 1
    assert table.class_totals["1234"] == 1
    assert table.count_for("all_defect", SPLIT_NONE) == 1811
    assert table.class_totals["all_defect"] == 1811

    # Objectless row: train=2, none=5888, total=5890.
    assert table.objectless_for(SPLIT_TRAIN) == 2
    assert table.objectless_for(SPLIT_NONE) == 5888
    assert table.objectless_total == 5890

    # Totals row: train=2, none=7699 (files, not 1+1811+5888=7700),
    # bottom-right = 7701 total images.
    assert table.split_totals == {
        SPLIT_TRAIN: 2,
        SPLIT_VAL: 0,
        SPLIT_TEST: 0,
        SPLIT_NONE: 7699,
    }
    assert table.total == 7701
    assert table.total == table.entry_count


def test_build_class_split_table_empty_dataset():
    for empty in ([], None):
        table = build_class_split_table(empty)
        assert table.classes == ()
        assert table.counts == {}
        assert table.objectless_counts == {
            split: 0 for split in SPLIT_ORDER
        }
        assert table.class_totals == {}
        assert table.split_totals == {split: 0 for split in SPLIT_ORDER}
        assert table.objectless_total == 0
        assert table.total == 0
        assert table.entry_count == 0
        assert table.is_empty is True


def test_build_class_split_table_from_collected_entries(tmp_path):
    images = _make_images(tmp_path)
    _write_json(
        images / "a.json",
        {"split": "train", "shapes": [{"label": "person"}]},
    )
    _write_json(
        images / "b.json",
        {"split": "test", "shapes": [{"label": "car"}]},
    )
    files = [str(images / "a.jpg"), str(images / "b.jpg")]

    table = build_class_split_table(collect_entries(files))

    assert table.classes == ("car", "person")
    assert table.count_for("car", SPLIT_TEST) == 1
    assert table.count_for("person", SPLIT_TRAIN) == 1
    assert table.objectless_total == 0
    assert table.total == 2
    assert table.entry_count == 2


# -- filter_for_cell ------------------------------------------------------
def test_filter_for_class_split_cell():
    table = build_class_split_table(_make_entries())
    person_index = table.classes.index("person")

    result = filter_for_cell(
        table,
        ROW_KIND_CLASS,
        class_index=person_index,
        split_index=1,
    )

    assert result == StatisticsFilter(label="person", split=SPLIT_VAL)


def test_filter_for_class_name_cell_ignores_split():
    table = build_class_split_table(_make_entries())
    car_index = table.classes.index("car")

    result = filter_for_cell(
        table, ROW_KIND_CLASS, class_index=car_index, split_index=None
    )

    assert result == StatisticsFilter(label="car", split=None)


def test_filter_for_objectless_cells():
    table = build_class_split_table(_make_entries())

    assert filter_for_cell(
        table, ROW_KIND_OBJECTLESS, split_index=0
    ) == StatisticsFilter(label=None, split=SPLIT_TRAIN, objectless=True)
    assert filter_for_cell(
        table, ROW_KIND_OBJECTLESS, split_index=None
    ) == StatisticsFilter(label=None, split=None, objectless=True)


def test_totals_rows_and_columns_are_not_clickable():
    table = build_class_split_table(_make_entries())

    assert (
        filter_for_cell(table, ROW_KIND_TOTAL, class_index=0, split_index=0)
        is None
    )
    assert (
        filter_for_cell(
            table,
            ROW_KIND_CLASS,
            class_index=0,
            split_index=SPLIT_INDEX_TOTAL,
        )
        is None
    )
    assert (
        filter_for_cell(
            table,
            ROW_KIND_OBJECTLESS,
            split_index=SPLIT_INDEX_TOTAL,
        )
        is None
    )


def test_filter_for_invalid_arguments_returns_none():
    table = build_class_split_table(_make_entries())

    assert filter_for_cell(None, ROW_KIND_CLASS) is None
    assert (
        filter_for_cell(table, ROW_KIND_CLASS, class_index=99, split_index=0)
        is None
    )
    assert (
        filter_for_cell(table, ROW_KIND_CLASS, class_index=0, split_index=99)
        is None
    )
    assert filter_for_cell(table, "unknown", class_index=0) is None


def test_module_has_no_qt_dependency():
    """The aggregation module must stay importable without Qt."""
    source = Path(dataset_statistics.__file__).read_text(encoding="utf-8")

    assert "PyQt" not in source
