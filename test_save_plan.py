import unittest

from metadata_save_service import MetadataSaveService
from save_plan import SaveItem, SavePlan, SavePlanRequest, build_save_plan


class SavePlanTests(unittest.TestCase):
    def _request(self, **overrides):
        base = {
            "selected_paths": ["one.mp3"],
            "field_updates": {},
            "checked_fields": frozenset(),
            "cover_modified": False,
            "cover_data": None,
            "all_files_data": {"one.mp3": {"album": "Album", "cover_data": b"cover"}},
            "selected_files_data": {"one.mp3": {"album": "Album", "cover_data": b"cover"}},
            "locks_data": {},
            "album_sync_keys": ("album", "album_artist", "date", "genre"),
            "virtual_album_map": {},
            "track_paths": ["one.mp3"],
        }
        base.update(overrides)
        return SavePlanRequest(**base)

    def test_single_file_writes_title_artist_album_date_and_cover(self):
        plan = build_save_plan(self._request(
            field_updates={
                "title": "Title",
                "artist": "Artist",
                "album": "New Album",
                "date": "2026-01-02",
            },
            checked_fields=frozenset({"title", "artist", "album", "date"}),
            cover_modified=True,
            cover_data=b"new-cover",
        ))

        self.assertEqual(len(plan.items), 1)
        item = plan.items[0]
        self.assertEqual(item.metadata["title"], "Title")
        self.assertEqual(item.metadata["artist"], "Artist")
        self.assertEqual(item.metadata["album"], "New Album")
        self.assertEqual(item.metadata["date"], "2026-01-02")
        self.assertTrue(item.write_cover)
        self.assertEqual(item.cover_data, b"new-cover")

    def test_multi_file_does_not_overwrite_track_specific_fields(self):
        files = {
            "one.mp3": {"title": "One", "artist": "A", "track": "1", "disc": "1", "album": "Old", "cover_data": b"cover"},
            "two.mp3": {"title": "Two", "artist": "B", "track": "2", "disc": "1", "album": "Old", "cover_data": b"cover"},
        }
        plan = build_save_plan(self._request(
            selected_paths=["one.mp3", "two.mp3"],
            field_updates={"album": "New Album"},
            checked_fields=frozenset({"album"}),
            all_files_data=files,
            selected_files_data=files,
            track_paths=list(files),
        ))

        self.assertEqual(len(plan.items), 2)
        for item in plan.items:
            self.assertEqual(item.metadata, {"album": "New Album"})
            for key in ("title", "artist", "track", "disc"):
                self.assertNotIn(key, item.metadata)

    def test_album_sync_uses_only_configured_keys(self):
        files = {
            "one.mp3": {
                "album": "Old", "album_artist": "Album Artist", "date": "2026", "genre": "Rock",
                "composer": "Composer A", "cover_data": b"cover",
            },
            "two.mp3": {
                "album": "Old", "album_artist": "Other", "date": "2025", "genre": "Jazz",
                "composer": "Composer B", "cover_data": b"cover",
            },
        }
        plan = build_save_plan(self._request(
            field_updates={"album": "New"},
            checked_fields=frozenset({"album", "album_artist", "date", "genre", "composer"}),
            all_files_data=files,
            selected_files_data=files,
            track_paths=list(files),
        ))

        sync = next(item for item in plan.items if item.kind == "sync")
        self.assertEqual(sync.metadata["album"], "New")
        self.assertEqual(sync.metadata["album_artist"], "Album Artist")
        self.assertEqual(sync.metadata["date"], "2026")
        self.assertEqual(sync.metadata["genre"], "Rock")
        self.assertNotIn("composer", sync.metadata)

    def test_locked_sync_field_is_not_included(self):
        files = {
            "one.mp3": {"album": "Old", "album_artist": "Album Artist", "date": "2026", "cover_data": b"cover"},
            "two.mp3": {"album": "Old", "album_artist": "Other", "date": "2025", "cover_data": b"cover"},
        }
        plan = build_save_plan(self._request(
            field_updates={"album": "New"},
            checked_fields=frozenset({"album", "album_artist", "date"}),
            all_files_data=files,
            selected_files_data=files,
            locks_data={"two.mp3": {"album_artist": True}},
            track_paths=list(files),
        ))

        sync = next(item for item in plan.items if item.kind == "sync")
        self.assertEqual(sync.metadata["album"], "New")
        self.assertEqual(sync.metadata["date"], "2026")
        self.assertNotIn("album_artist", sync.metadata)

    def test_lock_does_not_block_the_current_file_direct_save(self):
        plan = build_save_plan(self._request(
            field_updates={"album": "New"},
            checked_fields=frozenset({"album"}),
            locks_data={"one.mp3": {"album": True}},
        ))

        self.assertEqual(plan.items[0].metadata, {"album": "New"})


class MetadataSaveServiceTests(unittest.TestCase):
    def test_service_passes_cover_data_to_tagger(self):
        writes = []

        class FakeTagger:
            def __init__(self, path):
                self.path = path

            def update_tags(self, metadata):
                writes.append(metadata)

            def read_tags(self):
                return {"title": "Title", "cover_data": b"cover"}

        plan = SavePlan((SaveItem(
            "one.mp3",
            {"title": "Title", "artist": "Artist", "album": "Album", "date": "2026"},
            cover_data=b"cover",
            write_cover=True,
        ),))
        result = MetadataSaveService(FakeTagger).execute(plan)

        self.assertEqual(result.success_files, ["one.mp3"])
        self.assertEqual(writes[0]["cover_data"], b"cover")
        self.assertEqual(result.saved_metadata["one.mp3"]["cover_data"], b"cover")

    def test_failures_do_not_stop_remaining_files(self):
        writes = []

        class FakeTagger:
            def __init__(self, path):
                self.path = path

            def update_tags(self, metadata):
                if self.path == "bad.flac":
                    raise OSError("write failed")
                writes.append((self.path, metadata))

            def read_tags(self):
                return {"path": self.path}

        plan = SavePlan((
            SaveItem("one.mp3", {"title": "One"}),
            SaveItem("bad.flac", {"title": "Bad"}),
            SaveItem("two.mp3", {"title": "Two"}),
        ))
        result = MetadataSaveService(FakeTagger).execute(plan)

        self.assertEqual(result.success_files, ["one.mp3", "two.mp3"])
        self.assertEqual(result.failed_files, ["bad.flac"])
        self.assertEqual(result.errors, {"bad.flac": "write failed"})
        self.assertEqual([path for path, _ in writes], ["one.mp3", "two.mp3"])

    def test_progress_callback_reports_each_attempted_item(self):
        progress = []

        class FakeTagger:
            def __init__(self, path):
                self.path = path

            def update_tags(self, metadata):
                pass

            def read_tags(self):
                return {"path": self.path}

        plan = SavePlan((
            SaveItem("one.mp3", {"title": "One"}),
            SaveItem("two.mp3", {"album": "Album"}, kind="sync", depends_on="one.mp3"),
        ))
        MetadataSaveService(FakeTagger).execute(
            plan,
            progress_callback=lambda current, total, item: progress.append((current, total, item.path, item.kind)),
        )

        self.assertEqual(progress, [
            (1, 2, "one.mp3", "primary"),
            (2, 2, "two.mp3", "sync"),
        ])


if __name__ == "__main__":
    unittest.main()
