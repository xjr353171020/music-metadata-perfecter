import unittest

from album_session import AlbumSession


class AlbumSessionTests(unittest.TestCase):
    def test_initial_state_is_empty_and_uses_default_sync_keys(self):
        session = AlbumSession()

        self.assertEqual(session.all_files_data, {})
        self.assertEqual(session.selected_files_data, {})
        self.assertEqual(session.virtual_album_map, {})
        self.assertEqual(session.virtual_album_anchors, {})
        self.assertEqual(session.next_group_id, 1)
        self.assertEqual(session.recycled_groups, [])
        self.assertEqual(session.locks_data, {})
        self.assertEqual(
            session.album_sync_keys,
            ["album", "album_artist", "date", "genre"],
        )
        self.assertIsNone(session.last_selected_album)

    def test_virtual_album_lifecycle_reuses_removed_group_id(self):
        session = AlbumSession()

        group_id = session.create_virtual_album(["one.mp3"])
        session.add_to_virtual_album(group_id, ["two.mp3"])

        self.assertEqual(group_id, 1)
        self.assertEqual(session.virtual_album_map, {"one.mp3": 1, "two.mp3": 1})
        self.assertEqual(session.virtual_album_anchors, {1: "one.mp3"})
        self.assertEqual(session.selected_virtual_album_group(["one.mp3", "two.mp3"]), 1)

        self.assertEqual(session.remove_virtual_album(group_id), ["one.mp3", "two.mp3"])
        self.assertEqual(session.virtual_album_map, {})
        self.assertEqual(session.virtual_album_anchors, {})
        self.assertEqual(session.recycled_groups, [1])

        self.assertEqual(session.create_virtual_album(["three.mp3"]), 1)

    def test_moving_path_repairs_source_album_anchor(self):
        session = AlbumSession()

        source_group = session.create_virtual_album(["one.mp3", "two.mp3"])
        destination_group = session.create_virtual_album(["three.mp3"])
        session.add_to_virtual_album(destination_group, ["one.mp3"])

        self.assertEqual(session.virtual_album_anchors[source_group], "two.mp3")
        self.assertEqual(session.virtual_album_anchors[destination_group], "three.mp3")
        self.assertEqual(session.virtual_album_map["one.mp3"], destination_group)

    def test_locks_can_be_set_and_queried(self):
        session = AlbumSession()

        session.set_lock("one.mp3", "album", True)
        self.assertTrue(session.is_locked("one.mp3", "album"))
        self.assertFalse(session.is_locked("one.mp3", "artist"))

        session.set_lock("one.mp3", "album", False)
        self.assertFalse(session.is_locked("one.mp3", "album"))

    def test_reset_restores_the_initial_session_state(self):
        session = AlbumSession()
        session.all_files_data["old/one.mp3"] = {"title": "One"}
        session.selected_files_data["old/one.mp3"] = {"title": "One"}
        session.create_virtual_album(["old/one.mp3"])
        session.set_lock("old/one.mp3", "title", True)
        session.last_selected_album = "Old Album"
        session.album_sync_keys.append("custom")

        session.reset()

        self.assertEqual(session.all_files_data, {})
        self.assertEqual(session.selected_files_data, {})
        self.assertEqual(session.virtual_album_map, {})
        self.assertEqual(session.virtual_album_anchors, {})
        self.assertEqual(session.next_group_id, 1)
        self.assertEqual(session.recycled_groups, [])
        self.assertEqual(session.locks_data, {})
        self.assertEqual(session.album_sync_keys, AlbumSession.DEFAULT_ALBUM_SYNC_KEYS)
        self.assertIsNone(session.last_selected_album)

    def test_reset_for_file_load_clears_directory_data_and_preserves_sync_configuration(self):
        session = AlbumSession()
        session.all_files_data["old/one.mp3"] = {"title": "One"}
        session.selected_files_data["old/one.mp3"] = {"title": "One"}
        session.album_sync_keys.append("custom")

        session.reset_for_file_load()

        self.assertEqual(session.all_files_data, {})
        self.assertEqual(session.selected_files_data, {})
        self.assertEqual(session.album_sync_keys, ["album", "album_artist", "date", "genre", "custom"])

    def test_new_directory_state_never_retains_old_directory_paths(self):
        session = AlbumSession()
        old_path = "old-library/one.mp3"
        new_path = "new-library/two.mp3"
        session.all_files_data[old_path] = {"title": "One"}
        session.selected_files_data[old_path] = {"title": "One"}

        session.reset_for_file_load()
        session.all_files_data[new_path] = {"title": "Two"}

        exported = session.export_state()
        self.assertNotIn(old_path, exported["all_files_data"])
        self.assertNotIn(old_path, exported["selected_files_data"])
        self.assertEqual(exported["all_files_data"], {new_path: {"title": "Two"}})

    def test_new_directory_load_clears_virtual_albums_locks_and_last_album(self):
        session = AlbumSession()
        paths = ["old-library/one.mp3", "old-library/two.mp3"]
        group_id = session.create_virtual_album(paths)
        session.set_lock(paths[0], "album", True)
        session.last_selected_album = "Old Album"

        session.reset_for_file_load()

        self.assertEqual(session.virtual_album_map, {})
        self.assertEqual(session.virtual_album_anchors, {})
        self.assertEqual(session.recycled_groups, [])
        self.assertEqual(session.next_group_id, 1)
        self.assertEqual(session.locks_data, {})
        self.assertIsNone(session.last_selected_album)
        self.assertNotIn(group_id, session.virtual_album_anchors)

    def test_instances_do_not_share_state(self):
        first = AlbumSession()
        second = AlbumSession()

        first.all_files_data["one.mp3"] = {"title": "One"}
        first.selected_files_data["one.mp3"] = {"title": "One"}
        first.create_virtual_album(["one.mp3"])
        first.set_lock("one.mp3", "title", True)
        first.last_selected_album = "Album One"

        self.assertEqual(second.all_files_data, {})
        self.assertEqual(second.selected_files_data, {})
        self.assertEqual(second.virtual_album_map, {})
        self.assertEqual(second.locks_data, {})
        self.assertIsNone(second.last_selected_album)

        first.reset_for_file_load()

        self.assertEqual(second.all_files_data, {})
        self.assertEqual(second.selected_files_data, {})
        self.assertEqual(second.virtual_album_map, {})
        self.assertEqual(second.locks_data, {})
        self.assertIsNone(second.last_selected_album)

    def test_exported_state_references_only_its_own_session(self):
        first = AlbumSession()
        second = AlbumSession()
        first.all_files_data["one.mp3"] = {"title": "One"}
        first.set_lock("one.mp3", "title", True)

        exported = first.export_state()

        self.assertIs(exported["all_files_data"], first.all_files_data)
        self.assertIs(exported["locks_data"], first.locks_data)
        self.assertEqual(exported["all_files_data"], {"one.mp3": {"title": "One"}})
        self.assertEqual(second.export_state()["all_files_data"], {})
        self.assertEqual(second.export_state()["locks_data"], {})


if __name__ == "__main__":
    unittest.main()
