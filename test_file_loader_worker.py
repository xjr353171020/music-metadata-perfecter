# -*- coding: utf-8 -*-
import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from background_workers import FileLoaderWorker
from ui_components import FileLoadProgressDialog


class ConcurrentTagger:
    lock = threading.Lock()
    active = 0
    max_active = 0
    thread_ids = set()

    def __init__(self, path):
        self.path = path

    @classmethod
    def reset(cls):
        cls.active = 0
        cls.max_active = 0
        cls.thread_ids = set()

    def read_tags(self):
        with self.lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            type(self).thread_ids.add(threading.get_ident())
        try:
            time.sleep(0.03)
            if os.path.basename(self.path) == "bad.mp3":
                raise OSError("unreadable")
            number = int(os.path.basename(self.path).split("-", 1)[0])
            return {
                "album": "Album B" if number % 2 else "Album A",
                "disc": "1",
                "track": str(number),
                "title": f"Track {number}",
                "cover_data": None,
            }
        finally:
            with self.lock:
                type(self).active -= 1


class FileLoaderWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        ConcurrentTagger.reset()

    def test_uses_actual_worker_count_and_reports_each_lane(self):
        paths = [f"C:/library/{number}-track.mp3" for number in range(1, 8)]
        paths.append("C:/library/bad.mp3")
        configured = []
        progress = []
        finished = []
        worker = FileLoaderWorker("C:/library", worker_count=4)
        worker.configured_sig.connect(configured.append)
        worker.progress_sig.connect(lambda *args: progress.append(args))
        worker.finished_sig.connect(lambda *args: finished.append(args))

        with (
            patch("background_workers.glob.glob", side_effect=[paths, []]),
            patch("background_workers.AudioTagger", ConcurrentTagger),
        ):
            worker.run()
        self.app.processEvents()

        self.assertEqual(configured, [4])
        self.assertEqual(ConcurrentTagger.max_active, 4)
        self.assertEqual(len(ConcurrentTagger.thread_ids), 4)
        self.assertEqual(len(progress), len(paths))
        self.assertEqual({item[0] for item in progress}, {0, 1, 2, 3})
        self.assertEqual(sorted(item[3] for item in progress), list(range(1, 9)))
        for slot in range(4):
            lane_events = [item for item in progress if item[0] == slot]
            self.assertEqual([item[1] for item in lane_events], [1, 2])
            self.assertTrue(all(item[2] == 2 for item in lane_events))

        sortable, all_files_data = finished[0]
        self.assertNotIn("C:/library/bad.mp3", all_files_data)
        self.assertEqual(len(all_files_data), 7)
        self.assertEqual(sortable, sorted(sortable, key=lambda item: item[0]))

    def test_worker_count_is_limited_by_file_count(self):
        paths = ["C:/library/1-track.mp3", "C:/library/2-track.mp3"]
        configured = []
        worker = FileLoaderWorker("C:/library", worker_count=8)
        worker.configured_sig.connect(configured.append)

        with (
            patch("background_workers.glob.glob", side_effect=[paths, []]),
            patch("background_workers.AudioTagger", ConcurrentTagger),
        ):
            worker.run()

        self.assertEqual(configured, [2])
        self.assertEqual(len(ConcurrentTagger.thread_ids), 2)


class FileLoadProgressDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_progress_bar_count_tracks_configured_worker_count(self):
        dialog = FileLoadProgressDialog()
        dialog.configure_worker_count(3)
        self.assertEqual(len(dialog.progress_bars), 3)

        dialog.update_thread_progress(2, 4, 7, 11, 20, "track.mp3")
        self.assertEqual(dialog.progress_bars[2].maximum(), 7)
        self.assertEqual(dialog.progress_bars[2].value(), 4)
        self.assertEqual(dialog.progress_bars[2].format(), "4/7")
        self.assertIn("11/20", dialog.summary_label.text())

        dialog.configure_worker_count(5)
        self.assertEqual(len(dialog.progress_bars), 5)
        dialog.accept()


if __name__ == "__main__":
    unittest.main()
