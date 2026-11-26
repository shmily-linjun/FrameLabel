"""Duplicate review dialog tests (fork.62)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

from anylabeling.services.dataset.duplicates import (
    ACTION_KEEP_ONE,
    ACTION_MERGE_ANNOTATIONS,
    DuplicateEntry,
    DuplicateGroup,
)
from anylabeling.views.duplicate_review import DuplicateReviewDialog


@pytest.fixture()
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _group(same_annotation: bool) -> DuplicateGroup:
    return DuplicateGroup(
        "sha",
        [
            DuplicateEntry(
                "a:1", "A", "a.jpg", "sha", "ann" if same_annotation else "x"
            ),
            DuplicateEntry(
                "b:2", "B", "b.jpg", "sha", "ann" if same_annotation else "y"
            ),
        ],
    )


def test_same_annotation_offers_keep_both_or_one(app):
    dialog = DuplicateReviewDialog([_group(True)])
    combo = dialog._combos["sha"]
    values = [combo.itemData(i) for i in range(combo.count())]
    assert values == ["keep_both", ACTION_KEEP_ONE]
    combo.setCurrentIndex(combo.findData(ACTION_KEEP_ONE))
    assert dialog.choices() == {"sha": ACTION_KEEP_ONE}
    dialog.deleteLater()
    app.processEvents()


def test_different_annotations_offers_merge(app):
    dialog = DuplicateReviewDialog([_group(False)])
    combo = dialog._combos["sha"]
    values = [combo.itemData(i) for i in range(combo.count())]
    assert values == ["keep_both", ACTION_MERGE_ANNOTATIONS]
    dialog._keep_all()
    assert dialog.choices() == {"sha": "keep_both"}
    dialog.deleteLater()
    app.processEvents()
