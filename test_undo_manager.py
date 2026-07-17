import unittest

from undo_manager import (
    EditorStateSnapshot,
    EditorUndoCommand,
    ManagedMetadataSnapshot,
    SavedFileChange,
    SavedMetadataTransaction,
    UndoManager,
)


class UndoManagerTests(unittest.TestCase):
    def _state(self, title, cover=None):
        return EditorStateSnapshot(
            selected_paths=("one.mp3",),
            field_values={"title": title},
            cover_has_data=cover is not None,
            cover_data=cover,
        )

    def test_lifo_and_continuous_typing_merge(self):
        manager = UndoManager(merge_window_seconds=1.0)
        manager.push(EditorUndoCommand(
            "title", self._state("A"), self._state("AB"),
            ("one.mp3",), "field:title", timestamp=1.0,
        ))
        manager.push(EditorUndoCommand(
            "title", self._state("AB"), self._state("ABC"),
            ("one.mp3",), "field:title", timestamp=1.2,
        ))
        manager.push(EditorUndoCommand(
            "artist", self._state("ABC"), self._state("ABC"),
            ("one.mp3",), "field:artist", timestamp=1.3,
        ))

        self.assertEqual(manager.count, 2)
        self.assertEqual(manager.pop().description, "artist")
        merged = manager.pop()
        self.assertEqual(merged.before.field_values["title"], "A")
        self.assertEqual(merged.after.field_values["title"], "ABC")

    def test_suspension_and_clear(self):
        manager = UndoManager()
        with manager.suspend_recording():
            manager.push(EditorUndoCommand("ignored", self._state("A"), self._state("B")))
        self.assertFalse(manager.can_undo)
        manager.push(EditorUndoCommand("kept", self._state("A"), self._state("B")))
        manager.clear()
        self.assertFalse(manager.can_undo)
        self.assertEqual(manager.memory_bytes, 0)

    def test_undo_and_redo_stacks_move_commands_and_new_push_clears_redo(self):
        manager = UndoManager()
        command = EditorUndoCommand(
            "title", self._state("A"), self._state("B"), ("one.mp3",)
        )
        manager.push(command)

        self.assertTrue(manager.move_undo_to_redo(manager.peek()))
        self.assertFalse(manager.can_undo)
        self.assertTrue(manager.can_redo)
        redo_command = manager.peek_redo()
        self.assertTrue(manager.move_redo_to_undo(redo_command))
        self.assertTrue(manager.can_undo)
        self.assertFalse(manager.can_redo)

        manager.move_undo_to_redo(manager.peek())
        manager.push(EditorUndoCommand("new", self._state("B"), self._state("C")))
        self.assertFalse(manager.can_redo)

    def test_saved_transaction_builds_a_reversed_redo_transaction(self):
        before = ManagedMetadataSnapshot(title="before")
        after = ManagedMetadataSnapshot(title="after")
        transaction = SavedMetadataTransaction.create([
            SavedFileChange("one.mp3", before, after)
        ])
        transaction.mark_restored(["one.mp3"])

        redo = transaction.reversed("redo")

        change = redo.changes["one.mp3"]
        self.assertEqual(redo.action, "redo")
        self.assertEqual(change.before.title, "after")
        self.assertEqual(change.after.title, "before")

    def test_cover_bytes_are_deduplicated_and_limits_evict_oldest(self):
        manager = UndoManager(max_commands=2)
        cover = b"same-cover" * 100
        for index in range(3):
            manager.push(EditorUndoCommand(
                str(index), self._state(str(index), cover),
                self._state(str(index + 1), cover),
            ))
        self.assertEqual(manager.count, 2)
        self.assertEqual(manager.pop().description, "2")

    def test_partial_saved_transaction_remains_retryable(self):
        before = ManagedMetadataSnapshot(title="before")
        after = ManagedMetadataSnapshot(title="after")
        transaction = SavedMetadataTransaction.create([
            SavedFileChange("one.mp3", before, after),
            SavedFileChange("two.flac", before, after),
        ])
        manager = UndoManager()
        manager.push(transaction)
        transaction.mark_restored(["one.mp3"])
        manager.refresh_limits()

        self.assertIs(manager.peek(), transaction)
        self.assertEqual(transaction.affected_paths, ("two.flac",))
        self.assertFalse(transaction.is_complete)

    def test_snapshot_fingerprint_includes_empty_fields_and_cover_state(self):
        no_cover = ManagedMetadataSnapshot(title="A")
        with_cover = ManagedMetadataSnapshot(title="A", has_cover=True, cover_data=b"x")
        empty_title = ManagedMetadataSnapshot(title="", has_cover=True, cover_data=b"x")
        self.assertNotEqual(no_cover.fingerprint(), with_cover.fingerprint())
        self.assertNotEqual(with_cover.fingerprint(), empty_title.fingerprint())


if __name__ == "__main__":
    unittest.main()
