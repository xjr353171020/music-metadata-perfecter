# -*- coding: utf-8 -*-
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from main_window import MusicEditorWindow


class CapturingFetchWorker(QThread):
    progress_sig = pyqtSignal(str)
    finished_sig = pyqtSignal(bool, dict, list, str, str, int, bool)
    instances = []

    def __init__(
        self,
        title,
        artist,
        album,
        local_track,
        local_disc,
        mbid,
        apple_collection_id,
        mode,
        path,
        no_cache,
        local_metadata,
        request_id=0,
        cancel_event=None,
    ):
        super().__init__()
        self.query = {
            "title": title,
            "artist": artist,
            "album": album,
            "track": local_track,
            "disc": local_disc,
            "mbid": mbid,
            "apple_collection_id": apple_collection_id,
            "mode": mode,
            "no_cache": no_cache,
        }
        self.path = path
        self.local_metadata = dict(local_metadata)
        self.request_id = request_id
        self.cancel_event = cancel_event or threading.Event()
        self.instances.append(self)

    def cancel(self):
        self.cancel_event.set()
        self.requestInterruption()

    def run(self):
        self.finished_sig.emit(
            False,
            {},
            [],
            "controlled result",
            self.path,
            self.request_id,
            False,
        )


class ProviderEditorDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MusicEditorWindow(os.getcwd())
        self.window.show()
        self.paths = [
            os.path.join(os.getcwd(), "provider-draft-one.mp3"),
            os.path.join(os.getcwd(), "provider-draft-two.mp3"),
        ]
        data = {
            self.paths[0]: self._metadata(
                title="Loaded One",
                artist=r"Loaded Lead\\Loaded Guest",
                album="Loaded Album",
                track="1",
                disc="1",
            ),
            self.paths[1]: self._metadata(
                title="Loaded Two",
                artist="Other Artist",
                album="Loaded Album",
                track="2",
                disc="1",
            ),
        }
        sortable = [
            (("Loaded Album", 1, index + 1, os.path.basename(path)), path)
            for index, path in enumerate(self.paths)
        ]
        self.window.album_session.all_files_data = data
        self.window.full_sortable_list = sortable
        self.window.populate_file_list(sortable)
        first = self.window._track_item_cache[self.paths[0]]
        self.window.file_list.setCurrentItem(first)
        first.setSelected(True)
        self.window.on_file_selected()
        self.app.processEvents()
        CapturingFetchWorker.instances = []

    def tearDown(self):
        if self.window.is_metadata_search_running():
            self.window.cancel_active_search()
        self._wait_until(lambda: not self.window.is_metadata_search_running())
        self._wait_until(lambda: getattr(self.window, "worker", None) is None)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    @staticmethod
    def _metadata(**updates):
        values = {
            "title": "",
            "artist": "",
            "album": "",
            "album_artist": "",
            "composer": "",
            "track": "",
            "disc": "",
            "date": "",
            "genre": "",
            "comment": "",
            "cover_data": b"cover",
        }
        values.update(updates)
        return values

    def _wait_until(self, predicate, timeout=3000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("timed out waiting for Qt condition")

    def test_search_uses_unsaved_editor_identity_and_keeps_loaded_debug_snapshot(self):
        draft = {
            "title": "Edited Title",
            "artist": r"Edited Lead\\Edited Guest",
            "album": "Edited Album",
            "track": "07",
            "disc": "02",
        }
        for key, value in draft.items():
            self.window.update_combo_text(self.window.inputs[key], value)

        with patch("main_window.FetchWorker", CapturingFetchWorker):
            self.window.do_fetch("auto", is_auto=True)
            worker = CapturingFetchWorker.instances[-1]
            self._wait_until(lambda: getattr(self.window, "worker", None) is None)

        self.assertEqual(
            worker.query,
            {
                "title": "Edited Title",
                "artist": "Edited Lead",
                "album": "Edited Album",
                "track": "07",
                "disc": "02",
                "mbid": "",
                "apple_collection_id": "",
                "mode": "auto",
                "no_cache": False,
            },
        )
        self.assertEqual(worker.local_metadata["title"], "Loaded One")
        self.assertEqual(
            worker.local_metadata["artist"],
            r"Loaded Lead\\Loaded Guest",
        )
        self.assertNotIn("cover_data", worker.local_metadata)

    def test_candidate_style_refreshes_after_manual_and_provider_edits(self):
        self.window.last_fetch_success = True
        self.window._fill_mb_panel({"title": "Provider Title"})
        candidate = self.window.mb_inputs["title"]

        self.assertIn("#e57373", candidate.styleSheet())

        line_edit = self.window.inputs["title"].lineEdit()
        line_edit.setFocus()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, "Provider Title")
        self.app.processEvents()

        self.assertIn("#27ae60", candidate.styleSheet())
        self.assertIn("当前编辑", candidate.toolTip())

        line_edit.selectAll()
        QTest.keyClicks(line_edit, "Another Draft")
        self.app.processEvents()
        self.assertIn("#e57373", candidate.styleSheet())

        self.window.apply_mb_field("title")
        self.assertIn("#27ae60", candidate.styleSheet())

        self.window.perform_undo()
        self.assertIn("#e57373", candidate.styleSheet())

    def test_multiselect_concrete_editor_value_replaces_loaded_comparison_baseline(self):
        second = self.window._track_item_cache[self.paths[1]]
        second.setSelected(True)
        self.window.on_file_selected()
        self.app.processEvents()
        self.assertEqual(self.window.inputs["title"].currentText(), "<保留>")

        self.window.last_fetch_success = True
        self.window._fill_mb_panel({"title": "Shared Draft"})
        candidate = self.window.mb_inputs["title"]
        self.assertIn("#e57373", candidate.styleSheet())

        self.window.update_combo_text(
            self.window.inputs["title"],
            "Shared Draft",
        )
        self.app.processEvents()

        self.assertIn("#27ae60", candidate.styleSheet())


if __name__ == "__main__":
    unittest.main()
