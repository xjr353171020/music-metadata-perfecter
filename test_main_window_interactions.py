# -*- coding: utf-8 -*-
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QAbstractAnimation, QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from main_window import MusicEditorWindow
from metadata_save_service import MetadataSaveService
from save_plan import SaveItem, SavePlan


class SlowTagger:
    writes = []
    fail_paths = set()

    def __init__(self, path):
        self.path = path

    def update_tags(self, metadata):
        time.sleep(0.03)
        if self.path in self.fail_paths:
            raise OSError("write failed")
        self.writes.append((self.path, metadata))

    def read_tags(self):
        return {"title": "saved", "album": "Album", "cover_data": b"cover"}


class WindowInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MusicEditorWindow(os.getcwd())
        self.window.show()
        self._populate(8)
        self.window._save_service_factory = lambda: MetadataSaveService(SlowTagger)
        SlowTagger.writes = []
        SlowTagger.fail_paths = set()

    def tearDown(self):
        self._wait_until(lambda: not self.window._save_in_progress)
        self._wait_until(lambda: getattr(self.window, "save_worker", None) is None)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _populate(self, count):
        data = {}
        sortable = []
        for index in range(count):
            path = os.path.join(os.getcwd(), f"test-track-{index:04}.mp3")
            album = f"Album {index // 2:02}"
            data[path] = {
                "title": f"Track {index}", "artist": "Artist", "album": album,
                "album_artist": "Artist", "track": str(index + 1), "disc": "1",
                "date": "2026", "genre": "Rock", "comment": "", "cover_data": b"cover",
            }
            sortable.append(((album, 1, index + 1, os.path.basename(path)), path))
        self.window.album_session.all_files_data = data
        self.window.full_sortable_list = sortable
        self.window.populate_file_list(sortable)
        first = next(item for item in self.window._track_item_cache.values() if self.window.file_list.row(item) >= 0)
        self.window.file_list.setCurrentItem(first)
        first.setSelected(True)
        self.window.on_file_selected()
        self.app.processEvents()

    def _wait_until(self, predicate, timeout=3000):
        end = time.monotonic() + timeout / 1000
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("timed out waiting for Qt condition")

    def _send_key(self, event_type, key, modifiers=Qt.KeyboardModifier.NoModifier, autorepeat=False):
        event = QKeyEvent(event_type, key, modifiers, "", autorepeat)
        QApplication.sendEvent(self.window, event)

    def test_save_busy_state_blocks_repeated_and_modified_enter(self):
        actions = []
        self.window.skip_current_files = lambda: actions.append("skip")
        self.window.do_fetch = lambda *args, **kwargs: actions.append("fetch")
        self.window.save_current_files()
        self.assertTrue(self.window._save_in_progress)
        self.window.save_current_files()
        self._send_key(QEvent.Type.KeyPress, Qt.Key.Key_Return, autorepeat=True)
        self._send_key(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self._send_key(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(self.window._save_in_progress)
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(len(SlowTagger.writes), 1)
        self.assertEqual(actions, [])
        self._send_key(QEvent.Type.KeyPress, Qt.Key.Key_Return, autorepeat=True)
        self.app.processEvents()
        self.assertEqual(len(SlowTagger.writes), 1)
        self._send_key(QEvent.Type.KeyRelease, Qt.Key.Key_Return)
        self._send_key(QEvent.Type.KeyPress, Qt.Key.Key_Return)
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(len(SlowTagger.writes), 2)

    def test_successful_save_flashes_only_written_fields(self):
        for key, checkbox in self.window.checkboxes.items():
            checkbox.setChecked(key == "title")
        self.window.inputs["title"].setCurrentText("Changed")
        self.window.save_left_only_and_stay()
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(set(self.window._field_flash_animations), {self.window.inputs["title"]})
        self._wait_until(lambda: not self.window._field_flash_animations, timeout=1500)

    def test_save_progress_partial_failure_and_field_flash(self):
        tracks = [
            item for item in self.window._track_item_cache.values()
            if self.window.file_list.row(item) >= 0
        ]
        tracks[1].setSelected(True)
        selected_path = self.window._item_path(tracks[0])
        SlowTagger.fail_paths = {selected_path}
        original_warning = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *args: QMessageBox.StandardButton.Ok)
        try:
            self.window.save_current_files()
            self.assertIsNotNone(self.window.save_progress_dialog)
            self._wait_until(lambda: "直接保存" in self.window.save_progress_dialog.labelText())
            self._wait_until(lambda: not self.window._save_in_progress)
        finally:
            QMessageBox.warning = original_warning
        self.assertTrue(self.window.btn_save_apply.isEnabled())
        self.assertEqual(len(SlowTagger.writes), 1)
        self.assertTrue(self.window._field_flash_animations)
        self._wait_until(lambda: not self.window._field_flash_animations, timeout=1500)

    def test_search_restore_group_and_index_geometry(self):
        original_count = self.window.file_list.count()
        selected_first = self.window.file_list.currentItem()
        self.window.search_input.setText("track 7")
        self.window.perform_local_search()
        self.assertLess(sum(not item.isHidden() for item in self.window._track_item_cache.values()), 8)
        self.assertFalse(selected_first.isSelected())
        self.window.search_input.clear()
        self.app.processEvents()
        self.assertEqual(self.window.file_list.count(), original_count)
        self.assertTrue(selected_first.isSelected())
        first = next(item for item in self.window._track_item_cache.values() if self.window.file_list.row(item) >= 0)
        self.window.file_list.clearSelection()
        first.setSelected(True)
        self.window.file_list.setCurrentItem(first)
        self.window.toggle_virtual_album_group()
        self.window.toggle_virtual_album_group()
        self.window._position_album_index()
        self.assertGreaterEqual(self.window.album_index.x(), self.window.file_list.x())
        self.assertLessEqual(
            self.window.album_index.x() + self.window.album_index.width(),
            self.window.file_list.viewport().geometry().left() + self.window.file_list.x() + 24,
        )

    def test_smooth_scroll_animation_is_reused(self):
        self._populate(100)
        items = [item for item in self.window._track_item_cache.values() if self.window.file_list.row(item) >= 0]
        self.window.file_list.smooth_scroll_to_item(items[-1])
        animation = self.window.file_list._scroll_animation
        self.assertNotEqual(animation.state(), QAbstractAnimation.State.Stopped)
        self.window.file_list.smooth_scroll_to_item(items[0])
        self.assertIs(animation, self.window.file_list._scroll_animation)


if __name__ == "__main__":
    unittest.main()
