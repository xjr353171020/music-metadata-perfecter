# -*- coding: utf-8 -*-
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QAbstractAnimation, QEvent, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
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


class TailFetchWorker(QThread):
    progress_sig = pyqtSignal(str)
    finished_sig = pyqtSignal(bool, dict, list, str, str, int, bool)

    def __init__(self, *args, request_id=0, cancel_event=None):
        super().__init__()
        self.path = args[8]
        self.request_id = request_id
        self.result_emitted = threading.Event()
        self.tail_release = threading.Event()

    def cancel(self):
        self.tail_release.set()
        self.requestInterruption()

    def run(self):
        self.finished_sig.emit(
            False, {}, [], "probe result", self.path, self.request_id, False
        )
        self.result_emitted.set()
        self.tail_release.wait(2)


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

    def test_enter_release_during_save_does_not_block_next_press(self):
        self.window.advance_to_next_item = lambda *args, **kwargs: None
        self.window.file_list.setFocus()

        QTest.keyClick(self.window.file_list, Qt.Key.Key_Return)
        self.assertTrue(self.window._save_in_progress)
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(self.window._blocked_key_releases, set())

        QTest.keyClick(self.window.file_list, Qt.Key.Key_Return)
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(len(SlowTagger.writes), 2)

    def test_metadata_overlay_stays_until_thread_finishes_then_enter_saves(self):
        self.window.advance_to_next_item = lambda *args, **kwargs: None
        self.window.file_list.setFocus()

        with patch("main_window.FetchWorker", TailFetchWorker):
            self.window.do_fetch("auto", is_auto=True)
            worker = self.window.worker
            self._wait_until(worker.result_emitted.is_set)
            self._wait_until(lambda: self.window._active_metadata_search_id is None)

            self.assertTrue(worker.isRunning())
            self.assertTrue(self.window.overlay.isVisible())
            QTest.keyClick(self.window.file_list, Qt.Key.Key_Return)
            self.assertFalse(self.window._save_in_progress)

            worker.tail_release.set()
            self._wait_until(lambda: self.window.worker is None)

        self.assertFalse(self.window.overlay.isVisible())
        QTest.keyClick(self.window.file_list, Qt.Key.Key_Return)
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(len(SlowTagger.writes), 1)

    def test_enter_saves_after_focus_returns_to_metadata_combo(self):
        self.window.advance_to_next_item = lambda *args, **kwargs: None
        line_edit = self.window.inputs["title"].lineEdit()
        line_edit.setFocus()
        self.app.processEvents()

        QTest.keyClick(line_edit, Qt.Key.Key_Return)

        self.assertTrue(self.window._save_in_progress)
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(len(SlowTagger.writes), 1)
        self.assertEqual(self.window._blocked_key_releases, set())

    def test_local_search_enter_still_filters_instead_of_saving(self):
        self.window.search_input.setText("track 7")
        self.window.search_input.setFocus()
        self.app.processEvents()

        QTest.keyClick(self.window.search_input, Qt.Key.Key_Return)

        self.assertFalse(self.window._save_in_progress)
        self.assertEqual(SlowTagger.writes, [])
        self.assertLess(
            sum(not item.isHidden() for item in self.window._track_item_cache.values()),
            8,
        )

    def test_search_clear_defers_full_list_restore(self):
        self.window.search_input.setText("track 7")
        self.window.perform_local_search()
        self.assertTrue(self.window._local_search_active)

        self.window.search_input.clear()

        self.assertTrue(self.window._local_search_active)
        self._wait_until(lambda: not self.window._local_search_active)
        self.assertEqual(
            sum(not item.isHidden() for item in self.window._track_item_cache.values()),
            len(self.window._track_item_cache),
        )

    def test_unsaved_metadata_prompts_before_selection_switch(self):
        original_path = self.window._loaded_selection_paths[0]
        line_edit = self.window.inputs["title"].lineEdit()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, "Unsaved title")
        target = next(
            item
            for path, item in self.window._track_item_cache.items()
            if path != original_path
        )

        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.No,
        ) as question:
            self.window.file_list.blockSignals(True)
            self.window.file_list.clearSelection()
            target.setSelected(True)
            self.window.file_list.setCurrentItem(target)
            self.window.file_list.blockSignals(False)
            self.window.on_file_selected()

        question.assert_called_once()
        self.assertEqual(self.window._loaded_selection_paths, (original_path,))
        self.assertEqual(self.window.inputs["title"].currentText(), "Unsaved title")
        self.assertTrue(self.window._track_item_cache[original_path].isSelected())

    def test_direct_apple_score_wraps_without_horizontal_scrollbar(self):
        self.window.mb_score_label.setText(
            "Match Confidence: 100% (Direct Apple Collection ID)  |  "
            "MusicBrainz 80%；Apple Music 100%"
        )
        self.app.processEvents()

        self.assertTrue(self.window.mb_score_label.wordWrap())
        self.assertEqual(
            self.window.metadata_result_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

    def test_additional_window_settings_are_runtime_isolated(self):
        child = MusicEditorWindow(
            self.window.music_dir,
            self.window.window_settings,
        )
        try:
            child.window_settings["VIP_DOWNLOAD_DIR"] = "child-only"
            child.window_settings["MAIN_MUSIC_DIR"] = "child-library"

            self.assertNotEqual(
                self.window.window_settings["VIP_DOWNLOAD_DIR"],
                child.window_settings["VIP_DOWNLOAD_DIR"],
            )
            self.assertEqual(self.window.music_dir, os.getcwd())
            self.assertEqual(self.window.windowTitle(), "Music Metadata Perfecter")
        finally:
            child.close()
            child.deleteLater()
            self.app.processEvents()

    def test_successful_save_flashes_only_written_fields(self):
        for key, checkbox in self.window.checkboxes.items():
            checkbox.setChecked(key == "title")
        self.window.inputs["title"].setCurrentText("Changed")
        self.window.save_left_only_and_stay()
        self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(set(self.window._field_flash_animations), {self.window.inputs["title"]})
        self._wait_until(lambda: not self.window._field_flash_animations, timeout=1500)

    def test_metadata_editor_preserves_typed_case_without_completion(self):
        combo = self.window.inputs["album_artist"]
        self.assertIsNone(combo.completer())
        combo.clear()
        combo.addItems(["Life-work", "<留白>"])
        combo.setCurrentText("Life-work")

        line_edit = combo.lineEdit()
        line_edit.setFocus()
        line_edit.setSelection(5, 1)
        QTest.keyClicks(line_edit, "W")
        QTest.keyClick(line_edit, Qt.Key.Key_Right)
        self.assertEqual(combo.currentText(), "Life-Work")

        for key, checkbox in self.window.checkboxes.items():
            checkbox.setChecked(key == "album_artist")
        self.window.album_session.album_sync_keys = []
        self.window.save_left_only_and_stay()
        self._wait_until(lambda: not self.window._save_in_progress)

        self.assertEqual(len(SlowTagger.writes), 1)
        self.assertEqual(SlowTagger.writes[0][1]["album_artist"], "Life-Work")
        self.assertEqual(combo.currentText(), "Life-Work")

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
        self._wait_until(lambda: not self.window._local_search_active)
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
