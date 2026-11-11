import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "anylabeling/views/labeling/utils/file_search.py"
)
SPEC = importlib.util.spec_from_file_location(
    "file_search_module", MODULE_PATH
)
FILE_SEARCH_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILE_SEARCH_MODULE)

filter_image_files = FILE_SEARCH_MODULE.filter_image_files
parse_search_pattern = FILE_SEARCH_MODULE.parse_search_pattern
parse_search_query = FILE_SEARCH_MODULE.parse_search_query
escape_query_value = FILE_SEARCH_MODULE.escape_query_value
matches_filename = FILE_SEARCH_MODULE.matches_filename
matches_label_attribute = FILE_SEARCH_MODULE.matches_label_attribute
SearchPattern = FILE_SEARCH_MODULE.SearchPattern
SearchQuery = FILE_SEARCH_MODULE.SearchQuery


class TestFileSearch(unittest.TestCase):

    @staticmethod
    def _write_label(path, shapes):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"shapes": shapes}, f)

    @staticmethod
    def _write_label_data(path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_text_search(self):
        image_files = ["a_test.jpg", "b.jpg", "c_test.png"]
        pattern = parse_search_pattern("test")
        result = filter_image_files(image_files, pattern)

        self.assertEqual(result, ["a_test.jpg", "c_test.png"])

    def test_regex_search(self):
        image_files = ["a_test.jpg", "b.JPG", "c.png"]
        pattern = parse_search_pattern("<\\.jpg$>")
        result = filter_image_files(image_files, pattern)

        self.assertEqual(result, ["a_test.jpg", "b.JPG"])

    def test_index_search(self):
        image_files = ["a.jpg", "b.jpg", "c.jpg"]
        pattern = parse_search_pattern("#2")
        result = filter_image_files(image_files, pattern)

        self.assertEqual(result, ["b.jpg"])

    def test_index_search_out_of_range(self):
        image_files = ["a.jpg", "b.jpg", "c.jpg"]
        pattern = parse_search_pattern("#10")
        result = filter_image_files(image_files, pattern)

        self.assertEqual(result, [])

    def test_invalid_index_falls_back_to_text_search(self):
        pattern = parse_search_pattern("#0")

        self.assertEqual(pattern.mode, "normal")
        self.assertEqual(pattern.pattern, "#0")

    def test_attribute_search_modes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_files = [
                str(Path(temp_dir) / "a.jpg"),
                str(Path(temp_dir) / "b.jpg"),
                str(Path(temp_dir) / "c.jpg"),
            ]
            self._write_label(
                Path(temp_dir) / "a.json",
                [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "score": 0.4,
                        "description": "front view",
                        "difficult": True,
                        "group_id": 0,
                    }
                ],
            )
            self._write_label(
                Path(temp_dir) / "b.json",
                [
                    {
                        "label": "car",
                        "shape_type": "polygon",
                        "score": 0.8,
                        "description": "",
                        "difficult": False,
                        "group_id": 1,
                    }
                ],
            )
            self._write_label(Path(temp_dir) / "c.json", [])

            test_cases = [
                ("difficult::1", [image_files[0]]),
                ("gid::1", [image_files[1]]),
                ("shape::1", [image_files[0], image_files[1]]),
                ("label::person", [image_files[0]]),
                ("type::polygon", [image_files[1]]),
                ("score::[0,0.5]", [image_files[0]]),
                ("description::yes", [image_files[0]]),
            ]
            for query, expected in test_cases:
                with self.subTest(query=query):
                    pattern = parse_search_pattern(query)
                    result = filter_image_files(image_files, pattern)
                    self.assertEqual(result, expected)

    def test_checked_status_search_modes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_files = [
                str(Path(temp_dir) / "checked.jpg"),
                str(Path(temp_dir) / "unchecked.jpg"),
                str(Path(temp_dir) / "missing.jpg"),
                str(Path(temp_dir) / "failed.jpg"),
            ]
            self._write_label_data(
                Path(temp_dir) / "checked.json",
                {"checked": True, "shapes": []},
            )
            self._write_label_data(
                Path(temp_dir) / "unchecked.json",
                {"checked": False, "shapes": []},
            )

            self._write_label_data(
                Path(temp_dir) / "failed.json",
                {"checked": "failed", "shapes": []},
            )

            checked_pattern = parse_search_pattern("checked::1")
            unchecked_pattern = parse_search_pattern("checked::0")

            self.assertEqual(
                filter_image_files(image_files, checked_pattern),
                [image_files[0], image_files[3]],
            )
            self.assertEqual(
                filter_image_files(image_files, unchecked_pattern),
                [image_files[1], image_files[2]],
            )

    def test_object_review_search(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "labels"
            output_dir.mkdir()
            annotations = {
                "pending": [{"review_status": "pending"}],
                "missed": [{"review_status": "missed"}],
                "false_positive": [{"review_status": "false_positive"}],
                "mixed": [
                    {"review_status": "missed"},
                    {"review_status": "false_positive"},
                ],
                "legacy": [{"label": "person"}],
                "empty": [],
            }
            image_files = [
                str(Path(temp_dir) / f"{name}.jpg")
                for name in (*annotations, "missing", "invalid")
            ]
            for directory in (Path(temp_dir), output_dir):
                for name, shapes in annotations.items():
                    self._write_label_data(
                        directory / f"{name}.json",
                        {"checked": True, "shapes": shapes},
                    )
                (directory / "invalid.json").write_text("{", encoding="utf-8")
            for output in (None, str(output_dir)):
                for value, indices in (
                    ("pending", [0, 4]),
                    ("missed", [1, 3]),
                    ("false_positive", [2, 3]),
                    (" MISSED ", [1, 3]),
                ):
                    with self.subTest(output=output, value=value):
                        pattern = parse_search_pattern(f"review::{value}")
                        self.assertEqual(
                            filter_image_files(image_files, pattern, output),
                            [image_files[index] for index in indices],
                        )

    def test_invalid_object_review_falls_back_to_text(self):
        for query in ("review::", "review::unknown"):
            with self.subTest(query=query):
                pattern = parse_search_pattern(query)
                self.assertEqual(pattern.mode, "normal")
                self.assertEqual(pattern.pattern, query)

    def test_three_state_check_search_with_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "labels"
            output_dir.mkdir()
            image_files = [
                str(Path(temp_dir) / f"{name}.jpg")
                for name in (
                    "passed",
                    "failed",
                    "unchecked",
                    "legacy",
                    "missing",
                )
            ]
            for name, data in (
                ("passed", {"checked": True}),
                ("failed", {"checked": "failed"}),
                ("unchecked", {"checked": False}),
                ("legacy", {}),
            ):
                self._write_label_data(output_dir / f"{name}.json", data)
            for value, indices in (
                ("passed", [0]),
                ("failed", [1]),
                ("unchecked", [2, 3, 4]),
                ("PASSED", [0]),
                ("FAILED", [1]),
                ("UNCHECKED", [2, 3, 4]),
                ("1", [0, 1]),
                ("true", [0, 1]),
                ("yes", [0, 1]),
                ("0", [2, 3, 4]),
                ("false", [2, 3, 4]),
            ):
                with self.subTest(value=value):
                    pattern = parse_search_pattern(f"checked::{value}")
                    self.assertEqual(
                        filter_image_files(
                            image_files, pattern, str(output_dir)
                        ),
                        [image_files[index] for index in indices],
                    )


class TestSearchQueryEngine(unittest.TestCase):
    """Tests for the split keyword and the boolean query syntax."""

    ORDER = (
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
        "k",
        "l",
        "m",
        "n",
        "invalid",
    )

    def _specs(self):
        return {
            "a": {
                "split": "train",
                "checked": True,
                "shapes": [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "score": 0.4,
                        "description": "front view",
                        "difficult": True,
                        "group_id": 0,
                        "review_status": "pending",
                    },
                    {
                        "label": "car",
                        "shape_type": "polygon",
                        "score": 0.8,
                        "description": "",
                        "difficult": False,
                        "group_id": 1,
                        "review_status": "missed",
                    },
                ],
            },
            "b": {
                "split": "val",
                "checked": "failed",
                "shapes": [
                    {
                        "label": "car",
                        "shape_type": "polygon",
                        "score": 0.8,
                        "description": "",
                        "difficult": False,
                        "group_id": 1,
                        "review_status": "missed",
                    }
                ],
            },
            "c": {"split": "test", "checked": False, "shapes": []},
            "d": {
                "split": "none",
                "checked": True,
                "shapes": [{"label": "person"}, {"label": "dog"}],
            },
            "e": None,
            "f": {
                "split": "none",
                "checked": False,
                "shapes": [{"label": "cat"}],
            },
            "g": {
                "split": "train",
                "checked": True,
                "shapes": [{"label": "cat"}, {"label": "dog"}],
            },
            "h": {
                "split": "test",
                "checked": False,
                "shapes": [{"label": "a,b"}],
            },
            "i": {
                "split": "none",
                "checked": False,
                "shapes": [{"label": "x|y"}],
            },
            "j": {
                "split": "none",
                "checked": False,
                "shapes": [{"label": "back\\slash"}],
            },
            "k": {
                "split": "val",
                "checked": True,
                "shapes": [{"label": "front view"}],
            },
            "l": {
                "split": "none",
                "checked": False,
                "shapes": [{"label": " padded "}],
            },
            "m": {
                "split": "none",
                "checked": False,
                "shapes": [{"label": "(paren)"}],
            },
            "n": {
                "split": "none",
                "checked": False,
                "shapes": [{"label": "!bang"}],
            },
            "invalid": "broken",
        }

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self._temp_dir.name)
        self.addCleanup(self._temp_dir.cleanup)
        self.image_files = []
        self.files = {}
        self.label_files = {}
        specs = self._specs()
        for name in self.ORDER:
            image = self.temp_dir / f"img_{name}.jpg"
            label = self.temp_dir / f"img_{name}.json"
            self.image_files.append(str(image))
            self.files[name] = str(image)
            self.label_files[name] = str(label)
            data = specs[name]
            if data is None:
                continue
            with open(label, "w", encoding="utf-8") as stream:
                if isinstance(data, str):
                    stream.write("{")
                else:
                    json.dump(data, stream)

    def _expected(self, *names):
        return [self.files[name] for name in names]

    def _run(self, query):
        return filter_image_files(
            self.image_files, parse_search_query(query)
        )

    def _assert_query(self, query, *names):
        with self.subTest(query=query):
            self.assertEqual(self._run(query), self._expected(*names))

    def test_split_conditions(self):
        self._assert_query("split::train", "a", "g")
        self._assert_query("split::TRAIN", "a", "g")
        self._assert_query("split::训练", "a", "g")
        self._assert_query("split::val", "b", "k")
        self._assert_query("split::验证", "b", "k")
        self._assert_query("split::test", "c", "h")
        self._assert_query("split::测试", "c", "h")
        self._assert_query(
            "split::none", "d", "e", "f", "i", "j", "l", "m", "n", "invalid"
        )
        self._assert_query(
            "split::未划分", "d", "e", "f", "i", "j", "l", "m", "n", "invalid"
        )

    def test_label_multi_value_shorthand(self):
        self._assert_query("label::person", "a", "d")
        self._assert_query("label::PERSON", "a", "d")
        self._assert_query("label::cat|dog", "d", "f", "g")
        self._assert_query("label::cat,dog", "g")
        self._assert_query("label::dog|person", "a", "d", "g")
        self._assert_query("label::dog|cat", "d", "f", "g")
        self._assert_query("label::front view", "k")
        self._assert_query("label::missing-label", )

    def test_escaped_values(self):
        self._assert_query("label::a\\,b", "h")
        self._assert_query("label::x\\|y", "i")
        self._assert_query(
            "label::{}".format(escape_query_value("a,b")), "h"
        )
        self._assert_query(
            "label::{}".format(escape_query_value("x|y")), "i"
        )
        self._assert_query(
            "label::{}".format(escape_query_value("back\\slash")), "j"
        )
        self._assert_query(
            "label::{}".format(escape_query_value(" padded ")), "l"
        )
        self._assert_query(
            "label::{}".format(escape_query_value("(paren)")), "m"
        )
        self._assert_query(
            "label::{}".format(escape_query_value("!bang")), "n"
        )

    def test_escape_query_value(self):
        cases = [
            ("a,b", "a\\,b"),
            ("x|y", "x\\|y"),
            ("(paren)", "\\(paren\\)"),
            ("back\\slash", "back\\\\slash"),
            (" padded ", "\\ padded\\ "),
            ("!bang", "\\!bang"),
            ("front view", "front view"),
            ("plain", "plain"),
            ("", ""),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(escape_query_value(value), expected)

    def test_cross_field_boolean(self):
        self._assert_query("label::person,split::train", "a")
        self._assert_query("label::person|split::test", "a", "c", "d", "h")
        self._assert_query(
            "(label::person|label::cat),split::train", "a", "g"
        )
        self._assert_query("label::cat|label::dog,split::train", "f", "g")
        self._assert_query("label::cat,dog|split::val", "b", "g", "k")
        self._assert_query("shape::0,split::test", "c")
        self._assert_query("score::[0,0.5],split::train", "a", "g")
        self._assert_query("type::rectangle|type::polygon", "a", "b")
        self._assert_query("shape::1,label::cat", "f", "g")
        self._assert_query(
            "label::{}|split::val".format(escape_query_value("a,b")),
            "b",
            "h",
            "k",
        )

    def test_negation(self):
        self._assert_query(
            "!label::car",
            "c",
            "d",
            "e",
            "f",
            "g",
            "h",
            "i",
            "j",
            "k",
            "l",
            "m",
            "n",
            "invalid",
        )
        self._assert_query(
            "!(label::car|split::train)",
            "c",
            "d",
            "e",
            "f",
            "h",
            "i",
            "j",
            "k",
            "l",
            "m",
            "n",
            "invalid",
        )
        self._assert_query(
            "!split::train",
            "b",
            "c",
            "d",
            "e",
            "f",
            "h",
            "i",
            "j",
            "k",
            "l",
            "m",
            "n",
            "invalid",
        )
        self._assert_query("!!label::car", "a", "b")
        self._assert_query("!shape::1", "c", "e", "invalid")
        self._assert_query(
            "!label::cat,split::none", "d", "e", "i", "j", "l", "m", "n",
            "invalid",
        )
        self._assert_query("!review::pending", "b", "c", "e", "invalid")

    def test_no_object_graphs(self):
        self._assert_query("shape::0", "c", "e", "invalid")
        self._assert_query(
            "shape::1", "a", "b", "d", "f", "g", "h", "i", "j", "k", "l",
            "m", "n",
        )
        self._assert_query("shape::0|label::cat", "c", "e", "f", "g", "invalid")

    def test_precedence(self):
        # comma binds tighter than pipe: cat OR (dog AND train)
        self._assert_query("label::cat|label::dog,split::train", "f", "g")
        # (cat AND dog) OR val
        self._assert_query("label::cat,dog|split::val", "b", "g", "k")
        # parentheses override the precedence
        self._assert_query(
            "(label::cat|label::dog),split::train", "g"
        )

    def test_missing_and_unreadable_annotation(self):
        missing_label = str(self.temp_dir / "does_not_exist.json")
        cases = [
            ("split::none", True),
            ("split::train", False),
            ("shape::0", True),
            ("shape::1", False),
            ("checked::0", True),
            ("checked::1", False),
            ("checked::unchecked", True),
            ("checked::passed", False),
            ("label::person", False),
            ("review::pending", False),
            ("description::0", False),
        ]
        for query_text, expected in cases:
            with self.subTest(query=query_text):
                query = parse_search_query(query_text)
                self.assertEqual(
                    query.matches(
                        str(self.temp_dir / "missing.jpg"), missing_label
                    ),
                    expected,
                )

    def test_matches_derives_label_file(self):
        query = parse_search_query("split::val")
        self.assertTrue(query.matches(self.files["b"]))
        self.assertFalse(query.matches(self.files["a"]))

    def test_legacy_syntax_through_new_api(self):
        self._assert_query("#3", "c")
        self._assert_query("", *self.ORDER)
        self._assert_query("img_a|split::val", "a", "b", "k")
        self._assert_query(
            "!img_a",
            "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
            "n", "invalid",
        )
        self._assert_query(
            "<img_a\\.jpg$>", "a"
        )
        self._assert_query(
            "<img_a\\.jpg$>|split::val", "a", "b", "k"
        )
        self._assert_query("difficult::1", "a")
        self._assert_query("gid::1", "a", "b")
        self._assert_query("gid::0", "a")
        self._assert_query("checked::passed", "a", "d", "g", "k")
        self._assert_query("checked::failed", "b")
        self._assert_query(
            "checked::unchecked", "c", "e", "f", "h", "i", "j", "l", "m",
            "n", "invalid",
        )
        self._assert_query("review::missed", "a", "b")
        self._assert_query(
            "review::pending", "a", "d", "f", "g", "h", "i", "j", "k", "l",
            "m", "n",
        )
        self._assert_query("description::1", "a")
        self._assert_query("score::(0,0.8]", "a", "b")
        self._assert_query("type::rectangle", "a")
        self._assert_query("<[>", )  # invalid regex -> literal text

    def test_index_query_object(self):
        query = parse_search_query("#2")
        self.assertTrue(query.is_index)
        self.assertEqual(query.index, 2)
        self.assertEqual(
            filter_image_files(self.image_files, query), [self.files["b"]]
        )
        self.assertEqual(parse_search_query("#0").is_index, False)

    def test_legacy_parse_search_pattern(self):
        pattern = parse_search_pattern("label::cat|dog")
        self.assertEqual(pattern.mode, "query")
        self.assertEqual(
            filter_image_files(self.image_files, pattern),
            self._expected("d", "f", "g"),
        )

        pattern = parse_search_pattern("split::train")
        self.assertEqual(pattern.mode, "attribute")
        self.assertEqual(
            pattern.attribute_filter,
            {"type": "split", "value": "train"},
        )
        self.assertTrue(
            matches_label_attribute(
                self.files["a"], self.label_files["a"], pattern
            )
        )
        self.assertFalse(
            matches_label_attribute(
                self.files["b"], self.label_files["b"], pattern
            )
        )

        pattern = parse_search_pattern("label::person")
        self.assertEqual(pattern.mode, "attribute")
        self.assertTrue(
            matches_label_attribute(
                self.files["a"], self.label_files["a"], pattern
            )
        )
        self.assertFalse(
            matches_label_attribute(
                self.files["e"], self.label_files["e"], pattern
            )
        )
        self.assertTrue(matches_filename(self.files["a"], pattern))

        pattern = parse_search_pattern("img_a")
        self.assertEqual(pattern.mode, "normal")
        self.assertEqual(pattern.pattern, "img_a")
        self.assertTrue(matches_filename(self.files["a"], pattern))
        self.assertFalse(matches_filename(self.files["b"], pattern))

        pattern = parse_search_pattern("<img_a\\.jpg$>")
        self.assertEqual(pattern.mode, "regex")
        self.assertTrue(matches_filename(self.files["a"], pattern))
        self.assertFalse(matches_filename(self.files["b"], pattern))

        pattern = parse_search_pattern("#3")
        self.assertEqual(pattern.mode, "index")
        self.assertEqual(pattern.index, 3)

        self.assertIsNone(parse_search_pattern("").pattern)
        self.assertEqual(
            parse_search_pattern("review::").mode, "normal"
        )
        self.assertEqual(
            parse_search_pattern("review::").pattern, "review::"
        )

    def test_filter_accepts_pattern_and_text(self):
        pattern = parse_search_pattern("gid::1")
        self.assertEqual(
            filter_image_files(self.image_files, pattern),
            self._expected("a", "b"),
        )
        self.assertEqual(
            filter_image_files(self.image_files, "split::val"),
            self._expected("b", "k"),
        )
        self.assertEqual(
            filter_image_files(self.image_files, None),
            self._expected(*self.ORDER),
        )

    def test_empty_query_matches_everything(self):
        query = parse_search_query("   ")
        self.assertTrue(query.matches_all)
        self.assertEqual(
            filter_image_files(self.image_files, query),
            self._expected(*self.ORDER),
        )
