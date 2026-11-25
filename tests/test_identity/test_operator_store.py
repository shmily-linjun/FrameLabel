import os
import tempfile
import unittest

from anylabeling.services.identity import (
    OperatorCredentialsError,
    OperatorDisabledError,
    OperatorExistsError,
    OperatorPermissionError,
    OperatorStore,
    ReservedOperatorNameError,
    content_signature,
    default_database_path,
    ensure_attribution,
    legacy_database_path,
    migrate_legacy_database,
    previous_database_path,
    read_attribution,
    stamp_attribution,
)
from anylabeling.services.identity import passwords


class TestPasswords(unittest.TestCase):
    def test_hash_round_trip(self):
        hash_hex, salt_hex, iterations = passwords.hash_password("abcd")
        self.assertTrue(
            passwords.verify_password("abcd", hash_hex, salt_hex, iterations)
        )
        self.assertFalse(
            passwords.verify_password("abce", hash_hex, salt_hex, iterations)
        )

    def test_two_hashes_use_different_salts(self):
        first = passwords.hash_password("abcd")
        second = passwords.hash_password("abcd")
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])

    def test_short_password_is_rejected(self):
        with self.assertRaises(passwords.PasswordError):
            passwords.validate_password("abc")


class TestOperatorStore(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.db_path = os.path.join(self._temporary.name, "operators.db")
        self.store = OperatorStore(self.db_path)

    def test_first_account_is_admin(self):
        first = self.store.register("张三", "abcd")
        second = self.store.register("李四", "efgh")
        self.assertTrue(first.is_admin)
        self.assertFalse(second.is_admin)
        self.assertEqual(self.store.count(), 2)

    def test_names_are_unique_case_insensitively(self):
        self.store.register("Alice", "abcd")
        with self.assertRaises(OperatorExistsError):
            self.store.register("alice", "abcd")

    def test_reserved_none_is_rejected(self):
        for name in ("none", "None", "NONE"):
            with self.subTest(name=name):
                with self.assertRaises(ReservedOperatorNameError):
                    self.store.register(name, "abcd")

    def test_authenticate(self):
        self.store.register("张三", "abcd")
        self.assertEqual(self.store.authenticate("张三", "abcd").name, "张三")
        with self.assertRaises(OperatorCredentialsError):
            self.store.authenticate("张三", "wrong")
        with self.assertRaises(OperatorCredentialsError):
            self.store.authenticate("unknown", "abcd")

    def test_admin_changes_password(self):
        self.store.register("张三", "abcd")
        self.store.register("李四", "efgh")
        self.store.change_password(
            "李四", "newpass", admin_name="张三", admin_password="abcd"
        )
        self.assertEqual(
            self.store.authenticate("李四", "newpass").name, "李四"
        )

    def test_non_admin_cannot_change_password(self):
        self.store.register("张三", "abcd")
        self.store.register("李四", "efgh")
        with self.assertRaises(OperatorPermissionError):
            self.store.change_password(
                "张三", "hacked", admin_name="李四", admin_password="efgh"
            )

    def test_disabled_account_cannot_authenticate(self):
        self.store.register("张三", "abcd")
        self.store.register("李四", "efgh")
        self.store.set_disabled(
            "李四", True, admin_name="张三", admin_password="abcd"
        )
        with self.assertRaises(OperatorDisabledError):
            self.store.authenticate("李四", "efgh")


class TestAttribution(unittest.TestCase):
    def test_legacy_content_is_marked_none(self):
        other_data = {}
        self.assertTrue(ensure_attribution(other_data, True))
        self.assertEqual(other_data["author"], "none")
        self.assertFalse(ensure_attribution(other_data, True))

    def test_empty_content_gets_no_author(self):
        other_data = {}
        self.assertFalse(ensure_attribution(other_data, False))
        self.assertNotIn("author", other_data)

    def test_stamp_and_read(self):
        other_data = {"tags": []}
        stamp_attribution(other_data, "张三")
        author, modified_at = read_attribution(other_data)
        self.assertEqual(author, "张三")
        self.assertTrue(modified_at)

    def test_stamp_rejects_none(self):
        with self.assertRaises(ValueError):
            stamp_attribution({}, "none")

    def test_signature_ignores_attribution_and_review_state(self):
        shapes = [{"label": "cat", "points": [[0, 0], [1, 1]]}]
        other_data = {"tags": ["a"], "description": "", "checked": False}
        baseline = content_signature(shapes, {}, other_data)
        stamp_attribution(other_data, "张三")
        other_data["checked"] = True
        other_data["split"] = "train"
        self.assertEqual(
            baseline, content_signature(shapes, {}, other_data)
        )

    def test_signature_tracks_content_changes(self):
        shapes = [{"label": "cat", "points": [[0, 0], [1, 1]]}]
        other_data = {"tags": ["a"], "description": ""}
        baseline = content_signature(shapes, {}, other_data)
        self.assertNotEqual(
            baseline,
            content_signature(shapes, {}, {"tags": ["b"], "description": ""}),
        )
        self.assertNotEqual(
            baseline,
            content_signature([], {}, other_data),
        )
        self.assertNotEqual(
            baseline,
            content_signature(shapes, {"flag": True}, other_data),
        )


class TestAccountDatabaseLocation(unittest.TestCase):
    def test_default_path_is_not_derived_from_work_directory(self):
        path = default_database_path()
        self.assertTrue(
            path.endswith(os.path.join("platform", "platform.db"))
        )
        self.assertIn("X-AnyLabeling", path)
        self.assertNotEqual(
            os.path.normcase(path),
            os.path.normcase(legacy_database_path(os.path.join("C:", "p"))),
        )
        self.assertTrue(
            previous_database_path().endswith(
                os.path.join("operators", "operators.db")
            )
        )

    def test_schema_has_registry_tables_and_version_two(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "platform.db")
            store = OperatorStore(target)
            store.register("张三", "abcd")
            import sqlite3

            connection = sqlite3.connect(target)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                version = connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertIn("operator", tables)
            self.assertIn("dataset_registry", tables)
            self.assertIn("dataset_registry_event", tables)
            self.assertEqual(version, "2")

    def test_migrates_previous_operators_database(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.path.join(directory, "operators", "operators.db")
            os.makedirs(os.path.dirname(previous))
            OperatorStore(previous).register("李四", "abcd")
            target = os.path.join(directory, "platform", "platform.db")
            from unittest import mock

            with mock.patch(
                "anylabeling.services.identity.session.previous_database_path",
                return_value=previous,
            ):
                self.assertTrue(migrate_legacy_database(target))
            self.assertTrue(os.path.exists(target))
            self.assertTrue(os.path.exists(previous))
            self.assertEqual(OperatorStore(target).count(), 1)

    def test_migrates_legacy_database_once(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = os.path.join(directory, "legacy", "operators.db")
            os.makedirs(os.path.dirname(legacy))
            OperatorStore(legacy).register("张三", "abcd")
            target = os.path.join(directory, "app", "operators.db")

            self.assertTrue(migrate_legacy_database(target, legacy))
            self.assertTrue(os.path.exists(target))
            self.assertTrue(os.path.exists(legacy))
            self.assertEqual(OperatorStore(target).count(), 1)
            self.assertFalse(migrate_legacy_database(target, legacy))

    def test_missing_legacy_database_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "app", "operators.db")
            legacy = os.path.join(directory, "missing", "operators.db")
            self.assertFalse(migrate_legacy_database(target, legacy))
            self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
