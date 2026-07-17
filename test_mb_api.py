import unittest

from mb_api import parse_artist_credit, select_release_track_title


class MusicBrainzNormalizationTests(unittest.TestCase):
    def test_artist_credit_uses_application_separator_for_all_joinphrases(self):
        self.assertEqual(
            parse_artist_credit([
                {"name": "HyuN", "joinphrase": " feat. "},
                {"name": "YURI", "joinphrase": ""},
            ]),
            "HyuN\\\\YURI",
        )
        self.assertEqual(
            parse_artist_credit([
                {"name": "HΔG", "joinphrase": " Remixed by "},
                {"name": "Mili", "joinphrase": ""},
            ]),
            "HΔG\\\\Mili",
        )
        self.assertEqual(
            parse_artist_credit([
                {"name": "Artist A", "joinphrase": ""},
                {"name": "Artist B", "joinphrase": ""},
            ]),
            "Artist A\\\\Artist B",
        )

    def test_release_track_title_precedes_shared_recording_title(self):
        self.assertEqual(
            select_release_track_title("Lady Lady Lady", "Lady, Lady, Lady"),
            "Lady Lady Lady",
        )
        self.assertEqual(select_release_track_title("", "Recording"), "Recording")


if __name__ == "__main__":
    unittest.main()
