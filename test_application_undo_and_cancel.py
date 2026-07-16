import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QAbstractAnimation, QEvent, QPoint, Qt
from PyQt6.QtGui import QImage, QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from background_workers import FetchWorker
from cover_fetch_worker import CoverFetchWorker
from library_widgets import TouchSafeFileList
from main_window import MusicEditorWindow
from metadata_save_service import MetadataRestoreService, MetadataSaveService
from search_cancellation import SearchCancelled
from undo_manager import EditorUndoCommand, SavedMetadataTransaction


class InMemoryTagger:
    values = {}

    def __init__(self, path):
        self.path = path

    def read_tags(self):
        return dict(self.values[self.path])

    def update_tags(self, metadata):
        self.values[self.path].update(metadata)

    def restore_managed_tags(self, snapshot):
        self.values[self.path].update(snapshot.restore_payload())


class ApplicationUndoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MusicEditorWindow(os.getcwd())
        self.window.show()
        self.paths = [os.path.join(os.getcwd(), f"undo-track-{index}.mp3") for index in range(2)]
        data = {
            path: {
                "title": f"Original {index}", "artist": "Artist", "album": "Album",
                "album_artist": "Artist", "composer": "", "track": str(index + 1),
                "disc": "1", "date": "2026", "genre": "", "comment": "",
                "cover_data": None,
            }
            for index, path in enumerate(self.paths)
        }
        sortable = [
            (("Album", 1, index + 1, os.path.basename(path)), path)
            for index, path in enumerate(self.paths)
        ]
        self.window.album_session.all_files_data = data
        self.window.full_sortable_list = sortable
        self.window.populate_file_list(sortable)
        item = self.window._track_item_cache[self.paths[0]]
        item.setSelected(True)
        self.window.file_list.setCurrentItem(item)
        self.window.on_file_selected()
        self.app.processEvents()

    def tearDown(self):
        if self.window.is_metadata_search_running() or self.window.is_cover_search_running():
            self.window.cancel_active_search()
        self._wait_until(lambda: not self.window.is_metadata_search_running())
        self._wait_until(lambda: not self.window.is_cover_search_running())
        self._wait_until(lambda: not self.window._save_in_progress)
        self._wait_until(lambda: not self.window._undo_in_progress)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _wait_until(self, predicate, timeout=4000):
        end = time.monotonic() + timeout / 1000
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("timed out waiting for Qt condition")

    def test_text_editing_merges_and_ctrl_z_in_combo_line_edit_is_global(self):
        line_edit = self.window.inputs["title"].lineEdit()
        line_edit.setFocus()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, "Changed")
        self.app.processEvents()

        self.assertEqual(self.window.undo_manager.count, 1)
        self.assertIsInstance(self.window.undo_manager.peek(), EditorUndoCommand)
        QTest.keyClick(line_edit, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()

        self.assertEqual(self.window.inputs["title"].currentText(), "Original 0")
        self.assertFalse(self.window.undo_manager.can_undo)

    def test_two_fields_undo_in_reverse_order(self):
        for key, value in (("title", "Changed title"), ("artist", "Changed artist")):
            line_edit = self.window.inputs[key].lineEdit()
            line_edit.setFocus()
            line_edit.selectAll()
            QTest.keyClicks(line_edit, value)
            self.app.processEvents()
        self.window.perform_undo()
        self.assertEqual(self.window.inputs["artist"].currentText(), "Artist")
        self.assertEqual(self.window.inputs["title"].currentText(), "Changed title")
        self.window.perform_undo()
        self.assertEqual(self.window.inputs["title"].currentText(), "Original 0")

    def test_apply_all_is_one_action_and_undo_does_not_record_again(self):
        self.window.mb_inputs["title"].setText("API title")
        self.window.mb_inputs["artist"].setText("API artist")
        before = self.window.undo_manager.count
        self.window.apply_all_mb_fields()
        self.assertEqual(self.window.undo_manager.count, before + 1)
        self.window.perform_undo()
        self.assertEqual(self.window.inputs["title"].currentText(), "Original 0")
        self.assertEqual(self.window.inputs["artist"].currentText(), "Artist")
        self.assertEqual(self.window.undo_manager.count, before)

    def test_single_apply_checkbox_and_lock_are_each_undoable(self):
        self.window.mb_inputs["title"].setText("API title")
        self.window.apply_mb_field("title")
        self.assertEqual(self.window.inputs["title"].currentText(), "API title")
        self.window.perform_undo()
        self.assertEqual(self.window.inputs["title"].currentText(), "Original 0")

        checkbox = self.window.checkboxes["title"]
        QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton)
        changed = checkbox.isChecked()
        self.window.perform_undo()
        self.assertNotEqual(checkbox.isChecked(), changed)

        lock = self.window.lock_btns["title"]
        QTest.mouseClick(lock, Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.album_session.is_locked(self.paths[0], "title"))
        self.assertEqual(lock.text(), "🔒")
        QTest.mouseClick(lock, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.album_session.is_locked(self.paths[0], "title"))
        self.assertEqual(lock.text(), "🔓")
        self.window.perform_undo()
        self.assertTrue(self.window.album_session.is_locked(self.paths[0], "title"))
        self.assertTrue(lock.isChecked())
        self.assertEqual(lock.text(), "🔒")
        self.window.perform_undo()
        self.assertFalse(self.window.album_session.is_locked(self.paths[0], "title"))
        self.assertFalse(lock.isChecked())
        self.assertEqual(lock.text(), "🔓")

    def test_pasted_cover_undo_restores_no_cover_and_modified_flag(self):
        image = QImage(8, 6, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.red)
        QApplication.clipboard().setImage(image)
        self.window.paste_cover_from_clipboard()
        self.assertIsNotNone(self.window.current_cover_data)
        self.assertTrue(self.window.cover_modified_in_batch)
        self.assertIn("8x6", self.window.resolution_label.text())

        self.window.perform_undo()
        self.assertIsNone(self.window.current_cover_data)
        self.assertFalse(self.window.cover_modified_in_batch)

    def test_gallery_cover_selection_is_one_undoable_action(self):
        class Gallery:
            selected_data = b"gallery-cover"

            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                return True

        self.window._active_cover_search_id = 3
        with patch("main_window.CoverGalleryDialog", Gallery):
            self.window.on_cover_fetch_finished(
                [{"source": "test", "data": b"gallery-cover"}],
                {}, [], 3, False,
            )
        self.assertEqual(self.window.current_cover_data, b"gallery-cover")
        self.assertEqual(self.window.undo_manager.count, 1)
        self.window.perform_undo()
        self.assertIsNone(self.window.current_cover_data)

    def test_metadata_source_switch_is_one_action(self):
        mb = {"title": "MB title", "match_score": 0.8, "source_quality_score": 0.8}
        apple = {"title": "Apple title", "match_score": 0.9, "source_quality_score": 0.9}
        self.window.available_source_results = {"MusicBrainz": mb, "Apple Music": apple}
        self.window.current_api_file_path = self.paths[0]
        self.window._fill_mb_panel(mb)
        self.window._set_available_sources(self.window.available_source_results, "MusicBrainz")
        self.window._editor_baseline = self.window._capture_editor_state()

        self.window.select_metadata_source("Apple Music")
        self.assertEqual(self.window.mb_inputs["title"].text(), "Apple title")
        self.assertEqual(self.window.undo_manager.count, 1)
        self.window.perform_undo()
        self.assertEqual(self.window.mb_inputs["title"].text(), "MB title")
        self.assertEqual(self.window._current_metadata_source, "MusicBrainz")

    def test_save_then_first_ctrl_z_restores_saved_file_and_reselects_it(self):
        InMemoryTagger.values = {
            path: dict(metadata)
            for path, metadata in self.window.album_session.all_files_data.items()
        }
        self.window._save_service_factory = lambda: MetadataSaveService(InMemoryTagger)
        self.window._restore_service_factory = lambda: MetadataRestoreService(InMemoryTagger)
        for key, checkbox in self.window.checkboxes.items():
            checkbox.setChecked(key == "title")
        line_edit = self.window.inputs["title"].lineEdit()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, "Saved title")
        self.window.save_left_only_and_stay()
        self._wait_until(lambda: not self.window._save_in_progress)

        self.assertEqual(InMemoryTagger.values[self.paths[0]]["title"], "Saved title")
        self.assertIsInstance(self.window.undo_manager.peek(), SavedMetadataTransaction)
        QTest.keyClick(line_edit, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self._wait_until(lambda: not self.window._undo_in_progress)
        self.assertEqual(InMemoryTagger.values[self.paths[0]]["title"], "Original 0")
        self.assertEqual(self.window._item_path(self.window.file_list.currentItem()), self.paths[0])
        self.assertEqual(self.window.inputs["title"].currentText(), "Original 0")

    def test_album_sync_files_share_one_saved_transaction(self):
        InMemoryTagger.values = {
            path: dict(metadata)
            for path, metadata in self.window.album_session.all_files_data.items()
        }
        self.window._save_service_factory = lambda: MetadataSaveService(InMemoryTagger)
        self.window._restore_service_factory = lambda: MetadataRestoreService(InMemoryTagger)
        for key, checkbox in self.window.checkboxes.items():
            checkbox.setChecked(key == "album_artist")
        line_edit = self.window.inputs["album_artist"].lineEdit()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, "New album artist")
        self.window.save_left_only_and_stay()
        self._wait_until(lambda: not self.window._save_in_progress)

        transaction = self.window.undo_manager.peek()
        self.assertIsInstance(transaction, SavedMetadataTransaction)
        self.assertEqual(set(transaction.changes), set(self.paths))
        self.assertTrue(all(
            InMemoryTagger.values[path]["album_artist"] == "New album artist"
            for path in self.paths
        ))
        self.window.perform_undo()
        self._wait_until(lambda: not self.window._undo_in_progress)
        self.assertTrue(all(
            InMemoryTagger.values[path]["album_artist"] == "Artist"
            for path in self.paths
        ))

    def test_two_saves_restore_in_reverse_order(self):
        InMemoryTagger.values = {
            path: dict(metadata)
            for path, metadata in self.window.album_session.all_files_data.items()
        }
        self.window._save_service_factory = lambda: MetadataSaveService(InMemoryTagger)
        self.window._restore_service_factory = lambda: MetadataRestoreService(InMemoryTagger)
        for key, checkbox in self.window.checkboxes.items():
            checkbox.setChecked(key == "title")
        line_edit = self.window.inputs["title"].lineEdit()
        for value in ("Second", "Third"):
            line_edit.selectAll()
            QTest.keyClicks(line_edit, value)
            self.window.save_left_only_and_stay()
            self._wait_until(lambda: not self.window._save_in_progress)
        self.assertEqual(InMemoryTagger.values[self.paths[0]]["title"], "Third")

        self.window.perform_undo()
        self._wait_until(lambda: not self.window._undo_in_progress)
        self.assertEqual(InMemoryTagger.values[self.paths[0]]["title"], "Second")
        self.window.perform_undo()
        self._wait_until(lambda: not self.window._undo_in_progress)
        self.assertEqual(InMemoryTagger.values[self.paths[0]]["title"], "Original 0")

    def test_directory_reload_clears_history(self):
        self.window.inputs["title"].lineEdit().setFocus()
        QTest.keyClicks(self.window.inputs["title"].lineEdit(), "x")
        self.assertTrue(self.window.undo_manager.can_undo)
        with patch("main_window.os.path.exists", return_value=False):
            self.window.load_file_list()
        self.assertFalse(self.window.undo_manager.can_undo)


class SearchCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait_until(self, predicate, timeout=3000):
        end = time.monotonic() + timeout / 1000
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("timed out waiting for Qt condition")

    def test_fetch_worker_cancel_is_cooperative_and_reports_cancelled(self):
        def blocking_search(*args, cancel_event=None, **kwargs):
            while not cancel_event.wait(0.01):
                pass
            raise SearchCancelled()

        worker = FetchWorker(
            "Title", "Artist", "Album", "1", "1", "", "", "auto",
            "one.mp3", False, {}, request_id=7,
        )
        output = []
        worker.finished_sig.connect(lambda *args: output.append(args))
        with patch("metadata_api.search_metadata", side_effect=blocking_search):
            worker.start()
            self._wait_until(worker.isRunning)
            worker.cancel()
            self._wait_until(lambda: bool(output))
            self._wait_until(lambda: not worker.isRunning())
        self.assertTrue(output)
        self.assertEqual(output[0][5], 7)
        self.assertTrue(output[0][6])
        worker.deleteLater()

    def test_escape_prioritizes_metadata_then_cover_and_is_noop_when_idle(self):
        window = MusicEditorWindow(os.getcwd())
        window.show()

        class DummyWorker:
            def __init__(self):
                self.running = True
                self.cancelled = False

            def isRunning(self):
                return self.running

            def cancel(self):
                self.cancelled = True
                self.running = False

        metadata = DummyWorker()
        cover = DummyWorker()
        window.worker = metadata
        window.cover_worker = cover
        window._active_metadata_search_id = 1
        window._active_cover_search_id = 1
        QTest.keyClick(window, Qt.Key.Key_Escape)
        self.assertTrue(metadata.cancelled)
        self.assertFalse(cover.cancelled)

        window.worker = None
        QTest.keyClick(window, Qt.Key.Key_Escape)
        self.assertTrue(cover.cancelled)

        window.cover_worker = None
        before = window.mb_status_label.text()
        QTest.keyClick(window, Qt.Key.Key_Escape)
        self.assertEqual(window.mb_status_label.text(), before)
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def test_stale_metadata_result_does_not_touch_current_ui(self):
        window = MusicEditorWindow(os.getcwd())
        window.show()
        window._active_metadata_search_id = 2
        window.mb_status_label.setText("current search")
        window.on_fetch_finished(
            True, {"title": "stale"}, [], "old", "old.mp3", 1, False
        )
        self.assertEqual(window.mb_status_label.text(), "current search")
        self.assertEqual(window._active_metadata_search_id, 2)
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def test_cover_worker_cancel_is_cooperative(self):
        worker = CoverFetchWorker("Artist", "Album", "", request_id=9)
        output = []
        worker.finished_sig.connect(lambda *args: output.append(args))

        class Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"resultCount": 0, "results": []}

        def blocking_get(*args, **kwargs):
            while not worker.cancel_event.wait(0.01):
                pass
            return Response()

        with patch("cover_fetch_worker.requests.Session.get", side_effect=blocking_get):
            worker.start()
            self._wait_until(worker.isRunning)
            worker.cancel()
            self._wait_until(lambda: not worker.isRunning())
        self.assertTrue(output)
        self.assertEqual(output[0][3], 9)
        self.assertTrue(output[0][4])
        worker.deleteLater()


class FakeWheelEvent:
    def __init__(self, pixel=0, angle=0):
        self._pixel = QPoint(0, pixel)
        self._angle = QPoint(0, angle)
        self.accepted = False

    def pixelDelta(self):
        return self._pixel

    def angleDelta(self):
        return self._angle

    def accept(self):
        self.accepted = True


class SmoothWheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_angle_is_fast_animated_and_new_pixel_event_retargets(self):
        widget = TouchSafeFileList()
        widget.resize(300, 180)
        widget.addItems([f"item {index}" for index in range(200)])
        widget.show()
        self.app.processEvents()
        bar = widget.verticalScrollBar()
        bar.setValue(min(30, bar.maximum() // 4))
        widget.item(100).setSelected(True)
        selected = widget.selectedItems()

        angle_event = FakeWheelEvent(angle=-120)
        start = bar.value()
        widget.wheelEvent(angle_event)
        self.assertTrue(angle_event.accepted)
        self.assertEqual(widget._scroll_animation.endValue(), start + widget.ANGLE_STEP_DISTANCE)
        self.assertEqual(widget._scroll_animation.state(), QAbstractAnimation.State.Running)
        self.assertLessEqual(widget._scroll_animation.duration(), widget.WHEEL_MAX_DURATION_MS)

        current = bar.value()
        pixel_event = FakeWheelEvent(pixel=-10)
        widget.wheelEvent(pixel_event)
        self.assertTrue(pixel_event.accepted)
        self.assertEqual(widget._scroll_animation.startValue(), current)
        self.assertEqual(widget._scroll_animation.endValue(), current + 11)
        self.assertEqual(widget.selectedItems(), selected)

        widget.verticalScrollBar().sliderPressed.emit()
        self.assertEqual(widget._scroll_animation.state(), QAbstractAnimation.State.Stopped)
        widget.close()
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
