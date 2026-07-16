import os
import shutil
import subprocess
import tempfile
import unittest

from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX

from audio_tagger import AudioTagger
from metadata_save_service import MetadataRestoreService
from undo_manager import ManagedMetadataSnapshot, SavedFileChange


OLD_COVER = b"\x89PNG\r\n\x1a\nold-cover"
NEW_COVER = b"\xff\xd8\xffnew-cover"


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
class RealMetadataRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _audio(self, extension):
        path = os.path.join(self.temp_dir.name, f"sample.{extension}")
        codec = ["-c:a", "libmp3lame"] if extension == "mp3" else ["-c:a", "flac"]
        subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.15",
                *codec, "-y", path,
            ],
            check=True,
        )
        return path

    def _set_unmanaged(self, path):
        if path.endswith(".mp3"):
            tags = ID3(path)
            tags.add(TXXX(encoding=3, desc="CUSTOM_UNMANAGED", text=["keep-me"]))
            tags.save(path)
        else:
            audio = FLAC(path)
            audio["custom_unmanaged"] = ["keep-me"]
            audio.save()

    def _assert_unmanaged(self, path):
        if path.endswith(".mp3"):
            values = [
                frame.text[0]
                for frame in ID3(path).getall("TXXX")
                if frame.desc == "CUSTOM_UNMANAGED"
            ]
        else:
            values = FLAC(path).get("custom_unmanaged", [])
        self.assertEqual(values, ["keep-me"])

    def _exercise_restore(self, extension, original_cover):
        path = self._audio(extension)
        tagger = AudioTagger(path)
        original = {
            "title": "Original", "artist": "One\\\\Two", "album": "Album",
            "album_artist": "One\\\\Two", "composer": "Composer",
            "track": "", "disc": "1", "date": "2024-01-02",
            "genre": "Classical\\\\Live", "comment": "", "cover_data": original_cover,
        }
        tagger.restore_managed_tags(ManagedMetadataSnapshot.from_metadata(original))
        self._set_unmanaged(path)
        before = ManagedMetadataSnapshot.from_metadata(tagger.read_tags())

        changed = dict(before.restore_payload())
        changed.update({"title": "Changed", "track": "7", "comment": "new", "cover_data": NEW_COVER})
        tagger.update_tags(changed)
        after = ManagedMetadataSnapshot.from_metadata(tagger.read_tags())

        result = MetadataRestoreService().execute({
            path: SavedFileChange(path, before, after)
        })
        self.assertEqual(result.success_files, [path])
        restored = ManagedMetadataSnapshot.from_metadata(AudioTagger(path).read_tags())
        self.assertEqual(restored.fingerprint(), before.fingerprint())
        self.assertEqual(restored.track, "")
        self.assertEqual(restored.comment, "")
        self.assertEqual(restored.has_cover, original_cover is not None)
        self.assertEqual(restored.cover_data, original_cover)
        self.assertEqual(restored.artist, "One\\\\Two")
        self._assert_unmanaged(path)

    def test_mp3_restore_empty_fields_old_cover_and_unmanaged_tag(self):
        self._exercise_restore("mp3", OLD_COVER)

    def test_mp3_restore_removes_new_cover(self):
        self._exercise_restore("mp3", None)

    def test_flac_restore_empty_fields_old_cover_and_unmanaged_tag(self):
        self._exercise_restore("flac", OLD_COVER)

    def test_flac_restore_removes_new_cover(self):
        self._exercise_restore("flac", None)

    def test_external_change_is_skipped(self):
        path = self._audio("mp3")
        tagger = AudioTagger(path)
        before = ManagedMetadataSnapshot.from_metadata(tagger.read_tags())
        tagger.update_tags({"title": "Saved"})
        after = ManagedMetadataSnapshot.from_metadata(tagger.read_tags())
        tagger.update_tags({"title": "External"})

        result = MetadataRestoreService().execute({
            path: SavedFileChange(path, before, after)
        })
        self.assertEqual(result.conflict_files, [path])
        self.assertEqual(AudioTagger(path).read_tags()["title"], "External")

    def test_one_failure_does_not_stop_later_restore(self):
        class FakeTagger:
            values = {
                "bad.mp3": {"title": "after"},
                "good.flac": {"title": "after"},
            }

            def __init__(self, path):
                self.path = path

            def read_tags(self):
                return dict(self.values[self.path])

            def restore_managed_tags(self, snapshot):
                if self.path == "bad.mp3":
                    raise OSError("failed")
                self.values[self.path] = snapshot.restore_payload()

        before = ManagedMetadataSnapshot(title="before")
        after = ManagedMetadataSnapshot(title="after")
        changes = {
            path: SavedFileChange(path, before, after)
            for path in ("bad.mp3", "good.flac")
        }
        result = MetadataRestoreService(FakeTagger).execute(changes)
        self.assertEqual(result.failed_files, ["bad.mp3"])
        self.assertEqual(result.success_files, ["good.flac"])


if __name__ == "__main__":
    unittest.main()
