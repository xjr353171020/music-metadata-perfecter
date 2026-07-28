# -*- coding: utf-8 -*-
import unittest

from filename_clue import FilenameClueSource, analyze_filename_clues


class FilenameClueAnalysisTests(unittest.TestCase):
    def test_local_analysis_preserves_filename_evidence(self):
        result = analyze_filename_clues("01 - Artist - Song (Live).flac")

        self.assertEqual(result.source, FilenameClueSource.LOCAL_RULES)
        self.assertEqual(
            result.values,
            {
                "title": "Song (Live)",
                "artist": "Artist",
                "album": "",
                "track": "01",
                "disc": "",
            },
        )

    def test_ambiguous_delimiters_keep_the_complete_stem_as_title(self):
        result = analyze_filename_clues("Artist - Album - Song (Remastered).mp3")

        self.assertEqual(
            result.values,
            {
                "title": "Artist - Album - Song (Remastered)",
                "artist": "",
                "album": "",
                "track": "",
                "disc": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
