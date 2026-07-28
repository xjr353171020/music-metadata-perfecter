# -*- coding: utf-8 -*-
import copy
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from main_window import MusicEditorWindow
from metadata_save_service import MetadataSaveService


class MemoryTagger:
    store = {}

    def __init__(self, path):
        self.path = path

    def read_tags(self):
        return copy.deepcopy(self.store[self.path])

    def read_managed_tags(self):
        return self.read_tags()

    def update_tags(self, metadata):
        self.store[self.path].update(copy.deepcopy(metadata))


class PendingFieldIndicatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MusicEditorWindow(os.getcwd())
        self.window.resize(1400, 900)
        self.window.show()
        self.paths = [
            os.path.join(os.getcwd(), "pending-one.mp3"),
            os.path.join(os.getcwd(), "pending-two.mp3"),
        ]
        data = {
            self.paths[0]: self._metadata(
                title="Original One",
                artist="Artist",
                track="1",
            ),
            self.paths[1]: self._metadata(
                title="Original Two",
                artist="Artist",
                track="2",
            ),
        }
        sortable = [
            (("Album", 1, index + 1, os.path.basename(path)), path)
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

    def tearDown(self):
        self._wait_until(lambda: not self.window._save_in_progress)
        self._wait_until(lambda: getattr(self.window, "save_worker", None) is None)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    @staticmethod
    def _metadata(**updates):
        values = {
            "title": "",
            "artist": "",
            "album": "Album",
            "album_artist": "Artist",
            "composer": "",
            "track": "",
            "disc": "1",
            "date": "2026",
            "genre": "",
            "comment": "",
            "cover_data": None,
        }
        values.update(updates)
        return values

    def _set_editor_text(self, key, value):
        line_edit = self.window.inputs[key].lineEdit()
        line_edit.setFocus()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, value)
        self.app.processEvents()

    def _wait_until(self, predicate, timeout=3000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("timed out waiting for Qt condition")

    def test_single_selection_tracks_direct_save_semantics(self):
        indicator = self.window.pending_field_indicators["title"]

        self.assertFalse(indicator.property("pending"))
        self.assertEqual(
            indicator.toolTip(),
            "Loaded metadata：Original One",
        )

        self._set_editor_text("title", "Changed")
        self.assertTrue(indicator.property("pending"))

        self._set_editor_text("title", "Original One")
        self.assertFalse(indicator.property("pending"))

        self.window.update_combo_text(self.window.inputs["title"], "<留白>")
        self.app.processEvents()
        self.assertTrue(indicator.property("pending"))

        self.window.checkboxes["title"].setChecked(False)
        self.app.processEvents()
        self.assertFalse(indicator.property("pending"))

        self.window.checkboxes["title"].setChecked(True)
        self.app.processEvents()
        self.assertTrue(indicator.property("pending"))

        self.window.update_combo_text(self.window.inputs["title"], "<保留>")
        self.app.processEvents()
        self.assertFalse(indicator.property("pending"))

    def test_blank_loaded_value_and_lock_follow_existing_save_rules(self):
        composer_indicator = self.window.pending_field_indicators["composer"]
        self.window.checkboxes["composer"].setChecked(True)
        self.window.update_combo_text(
            self.window.inputs["composer"],
            "<留白>",
        )
        self.app.processEvents()

        self.assertFalse(composer_indicator.property("pending"))
        self.assertEqual(
            composer_indicator.toolTip(),
            "Loaded metadata：（空）",
        )

        self.window.update_combo_text(
            self.window.inputs["composer"],
            "New Composer",
        )
        self.app.processEvents()
        self.assertTrue(composer_indicator.property("pending"))

        self.window.lock_btns["composer"].click()
        self.app.processEvents()
        self.assertTrue(self.window.lock_btns["composer"].isChecked())
        self.assertTrue(composer_indicator.property("pending"))

    def test_multiselect_uses_any_changed_primary_and_mixed_tooltip(self):
        second = self.window._track_item_cache[self.paths[1]]
        second.setSelected(True)
        self.window.on_file_selected()
        self.app.processEvents()
        indicator = self.window.pending_field_indicators["title"]

        self.assertEqual(self.window.inputs["title"].currentText(), "<保留>")
        self.assertFalse(indicator.property("pending"))
        self.assertEqual(
            indicator.toolTip(),
            "Loaded metadata：多个不同值",
        )

        self.window.update_combo_text(
            self.window.inputs["title"],
            "Original One",
        )
        self.app.processEvents()
        self.assertTrue(indicator.property("pending"))

        self.window.checkboxes["title"].setChecked(False)
        self.app.processEvents()
        self.assertFalse(indicator.property("pending"))

    def test_indicator_is_noninteractive_and_geometry_is_stable(self):
        self.assertEqual(
            set(self.window.pending_field_indicators),
            set(self.window.inputs),
        )
        indicator = self.window.pending_field_indicators["title"]
        combo = self.window.inputs["title"]
        indicator_size = indicator.size()
        indicator_geometry = indicator.geometry()
        combo_geometry = combo.geometry()
        undo_count = self.window.undo_manager.count
        editor_text = combo.currentText()

        self.assertEqual(indicator.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(
            indicator.textInteractionFlags(),
            Qt.TextInteractionFlag.NoTextInteraction,
        )

        QTest.mouseClick(indicator, Qt.MouseButton.LeftButton)
        self.app.processEvents()

        self.assertEqual(combo.currentText(), editor_text)
        self.assertEqual(self.window.undo_manager.count, undo_count)

        self._set_editor_text("title", "Changed")

        self.assertEqual(indicator.size(), indicator_size)
        self.assertEqual(indicator.geometry(), indicator_geometry)
        self.assertEqual(combo.geometry(), combo_geometry)

    def test_directory_reload_clears_derived_indicator_state(self):
        indicator = self.window.pending_field_indicators["title"]
        self._set_editor_text("title", "Changed")
        self.assertTrue(indicator.property("pending"))
        self.window.music_dir = os.path.join(
            os.getcwd(),
            ".missing-music-directory",
        )

        self.window.load_file_list()
        self.app.processEvents()

        self.assertFalse(indicator.property("pending"))
        self.assertEqual(
            indicator.toolTip(),
            "Loaded metadata：未选择曲目",
        )

    def test_successful_save_refreshes_loaded_baseline(self):
        indicator = self.window.pending_field_indicators["title"]
        self._set_editor_text("title", "Saved Title")
        self.assertTrue(indicator.property("pending"))
        MemoryTagger.store = copy.deepcopy(
            self.window.album_session.all_files_data
        )
        self.window._save_service_factory = lambda: MetadataSaveService(
            MemoryTagger
        )

        self.window.save_left_only_and_stay()
        self._wait_until(lambda: not self.window._save_in_progress)

        self.assertEqual(
            self.window.album_session.all_files_data[self.paths[0]]["title"],
            "Saved Title",
        )
        self.assertFalse(indicator.property("pending"))
        self.assertEqual(
            indicator.toolTip(),
            "Loaded metadata：Saved Title",
        )


if __name__ == "__main__":
    unittest.main()
