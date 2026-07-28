# -*- coding: utf-8 -*-
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from main_window import MusicEditorWindow


class FilenameClueWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MusicEditorWindow(os.getcwd())
        self.window.show()

    def tearDown(self):
        self._wait_until(
            lambda: getattr(self.window, "filename_clue_worker", None) is None
        )
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _populate(self, entries, locks=None):
        data = {}
        sortable = []
        for index, (filename, metadata) in enumerate(entries):
            path = os.path.join(os.getcwd(), filename)
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
                "cover_data": None,
            }
            values.update(metadata)
            data[path] = values
            sortable.append(
                (
                    (
                        values["album"],
                        int(values["disc"] or 0),
                        int(values["track"] or 0),
                        filename,
                    ),
                    path,
                )
            )

        self.window.album_session.all_files_data = data
        self.window.album_session.locks_data = locks or {}
        self.window.full_sortable_list = sortable
        self.window.populate_file_list(sortable)
        items = [
            self.window._track_item_cache[path]
            for path in data
            if self.window.file_list.row(self.window._track_item_cache[path]) >= 0
        ]
        self.window.file_list.setCurrentItem(items[0])
        items[0].setSelected(True)
        self.window.on_file_selected()
        self.app.processEvents()
        return list(data), items

    def _wait_until(self, predicate, timeout=3000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("timed out waiting for Qt condition")

    def test_single_track_analysis_is_one_undoable_editor_draft(self):
        filename = "01 - Artist - Song (Live).flac"
        path = os.path.join(os.getcwd(), filename)
        self._populate(
            [(filename, {})],
            locks={path: {"title": True}},
        )
        self.window.checkboxes["artist"].setChecked(False)
        provider_or_save_actions = []
        self.window.do_fetch = lambda *args, **kwargs: provider_or_save_actions.append(
            "provider"
        )
        self.window._execute_save = (
            lambda *args, **kwargs: provider_or_save_actions.append("save")
        )

        self.assertTrue(self.window.btn_filename_clue.isEnabled())
        self.window.btn_filename_clue.click()
        self._wait_until(
            lambda: getattr(self.window, "filename_clue_worker", None) is None
        )

        self.assertEqual(self.window.inputs["title"].currentText(), "")
        self.assertEqual(self.window.inputs["artist"].currentText(), "Artist")
        self.assertEqual(self.window.inputs["track"].currentText(), "01")
        self.assertFalse(self.window.checkboxes["artist"].isChecked())
        self.assertEqual(self.window.filename_clue_status_label.text(), "本地规则解析")
        self.assertEqual(self.window.undo_manager.count, 1)
        self.assertEqual(provider_or_save_actions, [])
        request_generation = self.window._filename_clue_generation

        self.window.perform_undo()
        self.assertEqual(self.window.inputs["artist"].currentText(), "")
        self.assertEqual(self.window.inputs["track"].currentText(), "")
        self.assertEqual(self.window.filename_clue_status_label.text(), "")

        self.window.perform_redo()
        self.assertEqual(self.window.inputs["artist"].currentText(), "Artist")
        self.assertEqual(self.window.inputs["track"].currentText(), "01")
        self.assertEqual(self.window.filename_clue_status_label.text(), "本地规则解析")
        self.assertEqual(self.window._filename_clue_generation, request_generation)

    def test_action_is_disabled_for_complete_identity_or_multiple_selection(self):
        paths, items = self._populate(
            [
                (
                    "complete.mp3",
                    {"title": "Song", "artist": "Artist", "album": "Album"},
                ),
                ("empty.mp3", {}),
            ]
        )

        self.assertFalse(self.window.btn_filename_clue.isEnabled())

        items[1].setSelected(True)
        self.window.on_file_selected()
        self.app.processEvents()

        self.assertEqual(set(self.window.album_session.selected_files_data), set(paths))
        self.assertFalse(self.window.btn_filename_clue.isEnabled())

    def test_action_is_disabled_when_every_blank_target_is_locked(self):
        filename = "Artist - Song.mp3"
        path = os.path.join(os.getcwd(), filename)
        self._populate(
            [(filename, {})],
            locks={
                path: {
                    "title": True,
                    "artist": True,
                    "album": True,
                    "track": True,
                    "disc": True,
                }
            },
        )

        self.assertFalse(self.window.btn_filename_clue.isEnabled())

    def test_no_applicable_clue_shows_status_without_undo(self):
        self._populate(
            [
                (
                    "Artist - Song.mp3",
                    {"title": "Song", "artist": "Artist", "album": ""},
                )
            ]
        )

        self.assertTrue(self.window.btn_filename_clue.isEnabled())
        self.window.btn_filename_clue.click()
        self._wait_until(
            lambda: getattr(self.window, "filename_clue_worker", None) is None
        )

        self.assertEqual(
            self.window.filename_clue_status_label.text(),
            "未从文件名提取到可填线索",
        )
        self.assertEqual(self.window.undo_manager.count, 0)


if __name__ == "__main__":
    unittest.main()
