# -*- coding: utf-8 -*-
"""Background workers used by the music editor window."""

import glob
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QThread, pyqtSignal

from audio_tagger import AudioTagger
from filename_clue import analyze_filename_clues
from metadata_save_service import MetadataRestoreService, MetadataSaveService
from search_cancellation import SearchCancelled, check_cancelled


class FetchWorker(QThread):
    """Fetch normalized metadata without blocking the GUI thread."""

    progress_sig = pyqtSignal(str)
    finished_sig = pyqtSignal(bool, dict, list, str, str, int, bool)

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
        self.args = (title, artist, album, local_track, local_disc, mbid, mode, no_cache)
        self.apple_collection_id = apple_collection_id
        self.path = path
        self.local_metadata = local_metadata
        self.request_id = request_id
        self.cancel_event = cancel_event or threading.Event()

    def cancel(self):
        self.cancel_event.set()
        self.requestInterruption()

    def _emit_progress(self, text):
        if not self.cancel_event.is_set():
            self.progress_sig.emit(text)

    def run(self):
        from metadata_api import search_metadata

        try:
            check_cancelled(self.cancel_event)
            success, api_data, raw_json, msg = search_metadata(
                *self.args,
                progress_callback=self._emit_progress,
                apple_collection_id_override=self.apple_collection_id,
                cancel_event=self.cancel_event,
            )
            check_cancelled(self.cancel_event)
            raw_json.insert(0, (
                "💾 本地原始标签",
                json.dumps(self.local_metadata, indent=4, ensure_ascii=False, default=str),
            ))
        except SearchCancelled:
            self.finished_sig.emit(
                False, {}, [], "Search cancelled", self.path, self.request_id, True
            )
            return
        except Exception as exc:
            self.finished_sig.emit(
                False, {}, [], str(exc), self.path, self.request_id, False
            )
            return
        self.finished_sig.emit(
            success, api_data, raw_json, msg, self.path, self.request_id, False
        )


class FilenameClueWorker(QThread):
    """Analyze one filename without reading or mutating any widget state."""

    finished_sig = pyqtSignal(object, str, int, bool)

    def __init__(
        self,
        filename,
        path,
        request_id=0,
        cancel_event=None,
        parent=None,
    ):
        super().__init__(parent)
        self.filename = filename
        self.path = path
        self.request_id = request_id
        self.cancel_event = cancel_event or threading.Event()

    def cancel(self):
        self.cancel_event.set()
        self.requestInterruption()

    def run(self):
        if self.cancel_event.is_set():
            self.finished_sig.emit(None, self.path, self.request_id, True)
            return
        result = analyze_filename_clues(self.filename)
        cancelled = self.cancel_event.is_set()
        self.finished_sig.emit(
            None if cancelled else result,
            self.path,
            self.request_id,
            cancelled,
        )


class FileLoaderWorker(QThread):
    """Read local audio tags and produce the list's stable sort order."""

    DEFAULT_WORKER_COUNT = 4

    configured_sig = pyqtSignal(int)
    progress_sig = pyqtSignal(int, int, int, int, int, str)
    finished_sig = pyqtSignal(list, dict)

    def __init__(self, music_dir, worker_count=DEFAULT_WORKER_COUNT):
        super().__init__()
        self.music_dir = music_dir
        self.worker_count = max(1, int(worker_count))
        self._progress_lock = threading.Lock()
        self._completed_count = 0

    def run(self):
        files = glob.glob(os.path.join(self.music_dir, "*.mp3"))
        files += glob.glob(os.path.join(self.music_dir, "*.flac"))
        total = len(files)
        all_files_data = {}
        sortable = []

        active_worker_count = min(self.worker_count, total)
        self.configured_sig.emit(active_worker_count)
        partitions = [[] for _ in range(active_worker_count)]
        for index, file_path in enumerate(files):
            partitions[index % active_worker_count].append(file_path)

        active_partitions = [
            (slot, paths) for slot, paths in enumerate(partitions) if paths
        ]
        self._completed_count = 0
        start_barrier = threading.Barrier(len(active_partitions)) if active_partitions else None
        with ThreadPoolExecutor(
            max_workers=self.worker_count,
            thread_name_prefix="metadata-loader",
        ) as executor:
            futures = [
                executor.submit(
                    self._load_partition, slot, paths, total, start_barrier
                )
                for slot, paths in active_partitions
            ]
            for future in futures:
                partition_data, partition_sortable = future.result()
                all_files_data.update(partition_data)
                sortable.extend(partition_sortable)

        sortable.sort(key=lambda item: item[0])
        self.finished_sig.emit(sortable, all_files_data)

    def _load_partition(self, slot, paths, total, start_barrier):
        partition_data = {}
        partition_sortable = []
        if start_barrier is not None:
            start_barrier.wait()

        partition_total = len(paths)
        for current, file_path in enumerate(paths, start=1):
            try:
                data = AudioTagger(file_path).read_tags()
                partition_data[file_path] = data
                disc_num = self._tag_number(data.get("disc", ""))
                track_num = self._tag_number(data.get("track", ""))
                partition_sortable.append((
                    (data.get("album", ""), disc_num, track_num, os.path.basename(file_path)),
                    file_path,
                ))
            except Exception:
                pass

            with self._progress_lock:
                self._completed_count += 1
                completed = self._completed_count
            self.progress_sig.emit(
                slot,
                current,
                partition_total,
                completed,
                total,
                os.path.basename(file_path),
            )

        return partition_data, partition_sortable

    @staticmethod
    def _tag_number(value):
        number = str(value).split("/", 1)[0]
        return int(number) if number.isdigit() else 0


class SaveWorker(QThread):
    """Run a pre-built save plan without touching any QWidget state."""

    progress_sig = pyqtSignal(int, int, str, str)
    finished_sig = pyqtSignal(object)
    failed_sig = pyqtSignal(str)

    def __init__(self, plan, service=None, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.service = service or MetadataSaveService()

    def run(self):
        try:
            result = self.service.execute(
                self.plan,
                progress_callback=lambda current, total, item: self.progress_sig.emit(
                    current,
                    total,
                    os.path.basename(item.path),
                    item.kind,
                ),
            )
        except Exception as exc:
            self.failed_sig.emit(str(exc))
            return
        self.finished_sig.emit(result)


class RestoreWorker(QThread):
    """Restore one saved-metadata transaction without blocking the GUI."""

    progress_sig = pyqtSignal(int, int, str, str)
    finished_sig = pyqtSignal(object)
    failed_sig = pyqtSignal(str)

    def __init__(self, changes, service=None, parent=None):
        super().__init__(parent)
        self.changes = dict(changes)
        self.service = service or MetadataRestoreService()

    def run(self):
        try:
            result = self.service.execute(
                self.changes,
                progress_callback=lambda current, total, change: self.progress_sig.emit(
                    current,
                    total,
                    os.path.basename(change.path),
                    "restore",
                ),
            )
        except Exception as exc:
            self.failed_sig.emit(str(exc))
            return
        self.finished_sig.emit(result)
