import json
import os
import tempfile
import unittest

from PIL import Image

from anylabeling.services.identity.attribution import (
    AUTHOR_FIELD,
    MODIFIED_AT_FIELD,
)
from anylabeling.views.labeling import label_file

SHAPE = {
    "label": "cat",
    "points": [[0.0, 0.0], [1.0, 1.0]],
    "shape_type": "rectangle",
}


class TestLabelFileAuthor(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.directory = self._temporary.name
        self.image_path = os.path.join(self.directory, "image.png")
        Image.new("RGB", (4, 4), "white").save(self.image_path)
        self.label_path = os.path.join(self.directory, "image.json")

    def _write_label(self, extra=None):
        data = {
            "version": "test",
            "flags": {},
            "checked": False,
            "shapes": [dict(SHAPE)],
            "imagePath": "image.png",
            "imageData": None,
            "imageHeight": 4,
            "imageWidth": 4,
        }
        data.update(extra or {})
        with open(self.label_path, "w", encoding="utf-8") as stream:
            json.dump(data, stream)

    def test_legacy_file_with_shapes_reads_as_none(self):
        self._write_label()
        loaded = label_file.LabelFile(self.label_path)
        self.assertEqual(loaded.other_data[AUTHOR_FIELD], "none")

    def test_existing_author_is_preserved(self):
        self._write_label(
            {
                AUTHOR_FIELD: "张三",
                MODIFIED_AT_FIELD: "2026-11-17T09:00:00+08:00",
            }
        )
        loaded = label_file.LabelFile(self.label_path)
        self.assertEqual(loaded.other_data[AUTHOR_FIELD], "张三")
        self.assertEqual(
            loaded.other_data[MODIFIED_AT_FIELD], "2026-11-17T09:00:00+08:00"
        )

    def test_empty_annotation_gets_no_author(self):
        self._write_label({"shapes": []})
        loaded = label_file.LabelFile(self.label_path)
        self.assertNotIn(AUTHOR_FIELD, loaded.other_data)

    def test_author_survives_save_round_trip(self):
        saved = label_file.LabelFile()
        saved.save(
            filename=self.label_path,
            shapes=[dict(SHAPE)],
            image_path="image.png",
            image_height=4,
            image_width=4,
            other_data={
                AUTHOR_FIELD: "李四",
                MODIFIED_AT_FIELD: "2026-11-17T10:30:00+08:00",
            },
        )
        with open(self.label_path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        self.assertEqual(data[AUTHOR_FIELD], "李四")
        self.assertEqual(
            data[MODIFIED_AT_FIELD], "2026-11-17T10:30:00+08:00"
        )
        reloaded = label_file.LabelFile(self.label_path)
        self.assertEqual(reloaded.other_data[AUTHOR_FIELD], "李四")


if __name__ == "__main__":
    unittest.main()
