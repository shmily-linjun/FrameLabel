import unittest
import importlib.util
import sys
import types
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "anylabeling/config.py"
INSERTED_MODULES = []


def _inject_module(name, module):
    if name not in sys.modules:
        sys.modules[name] = module
        INSERTED_MODULES.append(name)

fake_anylabeling = types.ModuleType("anylabeling")
fake_anylabeling_configs = types.ModuleType("anylabeling.configs")
fake_anylabeling.configs = fake_anylabeling_configs
_inject_module("anylabeling", fake_anylabeling)
_inject_module("anylabeling.configs", fake_anylabeling_configs)

fake_views = types.ModuleType("anylabeling.views")
fake_labeling = types.ModuleType("anylabeling.views.labeling")
fake_logger_module = types.ModuleType("anylabeling.views.labeling.logger")


class _DummyLogger:
    def warning(self, *_args, **_kwargs):
        return None

    def info(self, *_args, **_kwargs):
        return None


fake_logger_module.logger = _DummyLogger()
_inject_module("anylabeling.views", fake_views)
_inject_module("anylabeling.views.labeling", fake_labeling)
_inject_module("anylabeling.views.labeling.logger", fake_logger_module)

SPEC = importlib.util.spec_from_file_location("config_module", MODULE_PATH)
CONFIG_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG_MODULE)
normalize_user_config = CONFIG_MODULE.normalize_user_config
update_dict = CONFIG_MODULE.update_dict
validate_config_item = CONFIG_MODULE.validate_config_item

for module_name in INSERTED_MODULES:
    sys.modules.pop(module_name, None)


class TestConfigNormalization(unittest.TestCase):

    def test_normalize_legacy_keys_and_shortcuts(self):
        user_config = {
            "epsilon": 8.5,
            "show_cross_line": True,
            "ui": {"legacy": True},
            "shortcuts": {
                "open_next": ["D", "Ctrl+Shift+D"],
                "open_prev": ["A", "Ctrl+Shift+A"],
                "zoom_in": "Ctrl+=",
            },
        }

        normalized = normalize_user_config(user_config)

        self.assertNotIn("epsilon", normalized)
        self.assertNotIn("show_cross_line", normalized)
        self.assertNotIn("ui", normalized)
        self.assertEqual(normalized["canvas"]["epsilon"], 8.5)
        self.assertTrue(normalized["canvas"]["crosshair"]["show"])
        self.assertEqual(normalized["shortcuts"]["open_next"], "D")
        self.assertEqual(normalized["shortcuts"]["open_prev"], "A")
        self.assertEqual(normalized["shortcuts"]["zoom_in"], ["Ctrl+="])

    def test_legacy_key_does_not_override_new_path(self):
        user_config = {
            "show_cross_line": True,
            "canvas": {"crosshair": {"show": False}},
        }
        normalized = normalize_user_config(user_config)
        self.assertFalse(normalized["canvas"]["crosshair"]["show"])


class _RecordingLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *_args, **_kwargs):
        self.warnings.append(message)

    def info(self, *_args, **_kwargs):
        return None


class TestRemovedConfigKeys(unittest.TestCase):
    REMOVED_KEYS = (
        "description_dock",
        "file_dock",
        "flag_dock",
        "label_dock",
        "shape_dock",
        "file_list_checkbox_editable",
    )

    def _user_config(self):
        return {
            "description_dock": {"show": True},
            "file_dock": {"show": False},
            "flag_dock": {"show": True},
            "label_dock": {"show": True},
            "shape_dock": {"show": True},
            "file_list_checkbox_editable": False,
            "right_tabs": {"hidden": ["flags"]},
            "file_list": {"show_thumbnails": False},
            "auto_save": False,
        }

    def test_removed_keys_are_dropped_and_new_keys_kept(self):
        normalized = normalize_user_config(self._user_config())

        for key in self.REMOVED_KEYS:
            self.assertNotIn(key, normalized)
        self.assertEqual(normalized["right_tabs"], {"hidden": ["flags"]})
        self.assertEqual(normalized["file_list"], {"show_thumbnails": False})
        self.assertFalse(normalized["auto_save"])

    def test_removed_keys_do_not_warn_but_unknown_keys_do(self):
        target = {
            "auto_save": True,
            "right_tabs": {"hidden": []},
            "file_list": {"show_thumbnails": True},
        }
        original_logger = CONFIG_MODULE.logger
        recording_logger = _RecordingLogger()
        CONFIG_MODULE.logger = recording_logger
        try:
            update_dict(
                target,
                normalize_user_config(self._user_config()),
                validate_item=validate_config_item,
            )
            self.assertEqual(recording_logger.warnings, [])

            recording_logger.warnings.clear()
            update_dict(
                target,
                normalize_user_config(
                    {"right_tabs": {"hidden": []}, "test_typo_key": True}
                ),
                validate_item=validate_config_item,
            )
            self.assertEqual(len(recording_logger.warnings), 1)
            self.assertIn("test_typo_key", recording_logger.warnings[0])
        finally:
            CONFIG_MODULE.logger = original_logger


if __name__ == "__main__":
    unittest.main()
