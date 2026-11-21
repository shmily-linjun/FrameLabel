"""P1 adapter tests: DB folder detection, file rows and DB save (no window)."""

from anylabeling.services.dataset.codec import ImageAnnotation
from anylabeling.services.dataset.connection import DatasetDatabase
from anylabeling.services.dataset.repository import DatasetRepository
from anylabeling.views.labeling.annotation_editor import AnnotationEditor
from anylabeling.views.labeling.file_session import FileSession


class FakeAction:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = enabled


class FakeActions:
    def __init__(self):
        for name in (
            "open_next_image",
            "open_prev_image",
            "open_next_unchecked_image",
            "open_prev_unchecked_image",
        ):
            setattr(self, name, FakeAction())
        self.save = type(
            "SaveAction", (), {"setIcon": lambda self, icon: None}
        )()


class FakeFiles:
    def __init__(self, host):
        self.host = host
        self.rows = []

    def append_db_row(self, file, meta):
        self.rows.append((file, meta))


class FakeFileList:
    def __init__(self, host):
        self.host = host
        self.current_row = -1

    def fill_name_column(self):
        pass

    def count(self):
        return len(self.host.files.rows)

    def setCurrentRow(self, row):
        self.current_row = row


class FakeGate:
    baseline = None


class FakeHost:
    def __init__(self):
        self.files = FakeFiles(self)
        self.file_list_widget = FakeFileList(self)
        self.actions = FakeActions()
        self.operator_gate = FakeGate()
        self.dataset_database = None
        self.dataset_repository = None
        self.dataset_root = None
        self.dataset_image_id = None
        self.output_dir = "/legacy-output"
        self._cli_output_dir = "/cli-output"
        self._no_selection_slot = False
        self.last_open_dir = None
        self.filename = None
        self.status_messages = []
        self.error_messages = []
        self.opened = None

    def _file_path_at(self, row):
        if 0 <= row < len(self.files.rows):
            return self.files.rows[row][0]
        return None

    def tr(self, text):
        return text

    def status(self, text):
        self.status_messages.append(text)

    def error_message(self, title, message):
        self.error_messages.append((title, message))

    def update_browse_actions(self):
        pass

    def _clear_file_list(self):
        self.files.rows.clear()
        self.file_list_widget.current_row = -1

    def toggle_actions(self, enabled):
        self.actions_enabled = enabled

    def _refresh_statistics_if_visible(self):
        pass

    def open_next_image(self, load=True):
        self.opened = load


def make_db(root):
    database = DatasetDatabase.create(root / "xanylabeling.db", name="demo")
    repository = DatasetRepository(database)
    image_id = repository.add_image(
        "images/a.png", width=64, height=48, split="train"
    )
    repository.save_annotation(
        image_id,
        ImageAnnotation(
            shapes=[
                {
                    "label": "bolt",
                    "shape_type": "rectangle",
                    "points": [[1, 1], [5, 1], [5, 5], [1, 5]],
                    "shape_id": "s1",
                }
            ],
            tags=["a"],
        ),
    )
    return database, repository, image_id


def test_open_dataset_for_folder_and_file_rows(dataset_tmp):
    root = dataset_tmp / "dataset"
    root.mkdir()
    database, _, _ = make_db(root)
    database.close()

    host = FakeHost()
    session = FileSession(host)
    repository = session._open_dataset_for_folder(root)
    try:
        assert repository is not None
        assert host.dataset_repository is repository
        assert host.dataset_root == str(root.resolve())
        assert host.output_dir is None

        session._load_database_folder(root, repository, load=False)
        assert len(host.files.rows) == 1
        file_path, meta = host.files.rows[0]
        assert file_path.endswith("images\\a.png") or file_path.endswith(
            "images/a.png"
        )
        assert meta.exists is True
        assert meta.checked is False
        assert meta.shape_count == 1
        assert meta.split == "train"
        assert meta.tags == ("a",)
        assert meta.import_time > 0
        assert host.opened is None
    finally:
        session._close_dataset()


def test_database_folder_search_uses_annotation_payload(dataset_tmp):
    root = dataset_tmp / "dataset"
    root.mkdir()
    database, repository, _ = make_db(root)
    try:
        host = FakeHost()
        session = FileSession(host)
        session._load_database_folder(root, repository, load=False, pattern="label::bolt")
        assert len(host.files.rows) == 1
        session._load_database_folder(root, repository, load=False, pattern="label::nut")
        assert host.files.rows == []
        session._load_database_folder(root, repository, load=False, pattern="shape::0")
        assert host.files.rows == []
        session._load_database_folder(
            root, repository, load=False, pattern="label::bolt,split::train"
        )
        assert len(host.files.rows) == 1
        session._load_database_folder(
            root, repository, load=False, pattern="a.png"
        )
        assert len(host.files.rows) == 1
        session._load_database_folder(root, repository, load=False, pattern="#1")
        assert len(host.files.rows) == 1
    finally:
        database.close()


def test_save_database_labels_writes_through_repository(dataset_tmp, monkeypatch):
    root = dataset_tmp / "dataset"
    root.mkdir()
    database, repository, image_id = make_db(root)
    try:
        monkeypatch.setattr(
            'anylabeling.views.labeling.annotation_editor.utils.new_icon',
            lambda name: None,
        )
        host = FakeHost()
        host.dataset_image_id = image_id
        host.dataset_repository = repository
        host.other_data = {
            "description": "updated",
            "tags": ["x", "y"],
            "split": "val",
            "relations": [],
            "author": "alice",
            "modified_at": "2026-11-20T12:00:00+08:00",
            "vqaData": {"q": "v"},
        }
        host._relation_data_for_shapes = lambda shapes: dict(host.other_data)
        updated = []
        host._update_file_row_after_save = lambda count: updated.append(count)
        host.actions.save = type(
            "SaveAction", (), {"setIcon": lambda self, icon: None}
        )()
        shape = {
            "label": "bolt2",
            "shape_type": "polygon",
            "points": [[1, 1], [3, 1], [3, 3]],
            "shape_id": "s2",
        }
        editor = AnnotationEditor(host)
        assert editor._save_database_labels(repository, [shape], {"blurry": True}, "sig")

        loaded = repository.load_annotation(image_id)
        assert [item["label"] for item in loaded.shapes] == ["bolt2"]
        assert loaded.tags == ["x", "y"]
        assert loaded.description == "updated"
        assert loaded.split == "val"
        assert loaded.flags == {"blurry": True}
        assert loaded.extra == {"vqaData": {"q": "v"}}
        assert loaded.editor == "alice"
        assert loaded.modified_at == "2026-11-20T12:00:00+08:00"
        assert updated == [1]
        assert host.operator_gate.baseline == "sig"
    finally:
        database.close()
