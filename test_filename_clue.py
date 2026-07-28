# -*- coding: utf-8 -*-
import json
import os
import threading
import unittest

from filename_clue import (
    FilenameClueSource,
    analyze_filename_clues,
)
from search_cancellation import SearchCancelled


class FilenameClueAnalysisTests(unittest.TestCase):
    @staticmethod
    def _deepseek_response(values):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(values, ensure_ascii=False),
                    }
                }
            ]
        }

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

    def test_standalone_version_qualifier_keeps_complete_stem_as_title(self):
        for filename in ("Song - Live.mp3", "Song - Remastered.flac"):
            with self.subTest(filename=filename):
                result = analyze_filename_clues(filename)

                self.assertEqual(result.values["title"], os.path.splitext(filename)[0])
                self.assertEqual(result.values["artist"], "")

    def test_deepseek_receives_only_filename_stem_and_fixed_contract(self):
        observed = {}

        def transport(*, payload, api_key, timeout):
            observed.update(
                payload=payload,
                api_key=api_key,
                timeout=timeout,
            )
            return self._deepseek_response(
                {
                    "title": "Song",
                    "artist": "Artist",
                    "album": "",
                    "track": "01",
                    "disc": "",
                }
            )

        result = analyze_filename_clues(
            r"C:\Private Library\01 - Artist - Song.mp3",
            api_key="test-secret",
            transport=transport,
        )

        self.assertEqual(result.source, FilenameClueSource.DEEPSEEK)
        self.assertEqual(result.values["track"], "01")
        self.assertEqual(observed["timeout"], 15)
        self.assertEqual(observed["payload"]["model"], "deepseek-chat")
        self.assertEqual(
            observed["payload"]["response_format"],
            {"type": "json_object"},
        )
        serialized_payload = json.dumps(observed["payload"], ensure_ascii=False)
        self.assertIn("01 - Artist - Song", serialized_payload)
        self.assertNotIn("Private Library", serialized_payload)
        self.assertNotIn(".mp3", serialized_payload)
        self.assertNotIn("test-secret", serialized_payload)

    def test_extra_key_rejects_the_whole_deepseek_response(self):
        def transport(**_kwargs):
            return self._deepseek_response(
                {
                    "title": "AI title",
                    "artist": "Artist",
                    "album": "",
                    "track": "",
                    "disc": "",
                    "date": "2026",
                }
            )

        result = analyze_filename_clues(
            "Artist - Song.mp3",
            api_key="configured",
            transport=transport,
        )

        self.assertEqual(result.source, FilenameClueSource.LOCAL_RULES)
        self.assertEqual(result.values["artist"], "Artist")
        self.assertEqual(result.values["title"], "Song")
        self.assertNotIn("AI title", result.values.values())

    def test_duplicate_json_key_rejects_the_whole_deepseek_response(self):
        def transport(**_kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"Song","title":"Song","artist":"Artist",'
                                '"album":"","track":"","disc":""}'
                            ),
                        }
                    }
                ]
            }

        result = analyze_filename_clues(
            "Artist - Song.mp3",
            api_key="configured",
            transport=transport,
        )

        self.assertEqual(result.source, FilenameClueSource.LOCAL_RULES)
        self.assertEqual(result.values["artist"], "Artist")
        self.assertEqual(result.values["title"], "Song")

    def test_untraceable_character_rejects_deepseek_response(self):
        def transport(**_kwargs):
            return self._deepseek_response(
                {
                    "title": "Song",
                    "artist": "AC/DC",
                    "album": "",
                    "track": "",
                    "disc": "",
                }
            )

        result = analyze_filename_clues(
            "AC_DC - Song.flac",
            api_key="configured",
            transport=transport,
        )

        self.assertEqual(result.source, FilenameClueSource.LOCAL_RULES)
        self.assertEqual(result.values["artist"], "AC_DC")

    def test_invalid_types_and_numeric_values_reject_the_whole_response(self):
        invalid_values = (
            {
                "title": "Song",
                "artist": "Artist",
                "album": "",
                "track": 1,
                "disc": "",
            },
            {
                "title": "Song",
                "artist": "Artist",
                "album": "",
                "track": "1000",
                "disc": "",
            },
            {
                "title": "Song",
                "artist": "Artist",
                "album": "",
                "track": "02",
                "disc": "",
            },
        )

        for values in invalid_values:
            with self.subTest(values=values):
                result = analyze_filename_clues(
                    "01 - Artist - Song.mp3",
                    api_key="configured",
                    transport=lambda **_kwargs: self._deepseek_response(values),
                )
                self.assertEqual(result.source, FilenameClueSource.LOCAL_RULES)
                self.assertEqual(result.values["track"], "01")
                self.assertEqual(result.values["title"], "Song")

    def test_missing_key_skips_transport_and_uses_local_rules(self):
        def unexpected_transport(**_kwargs):
            self.fail("transport must not run without an API key")

        result = analyze_filename_clues(
            "Artist - Song.mp3",
            api_key="",
            transport=unexpected_transport,
        )

        self.assertEqual(result.source, FilenameClueSource.LOCAL_RULES)

    def test_transport_failure_makes_one_request_then_falls_back(self):
        calls = []

        def failing_transport(**kwargs):
            calls.append(kwargs)
            raise TimeoutError("controlled timeout")

        result = analyze_filename_clues(
            "01 - Song (Remastered).mp3",
            api_key="configured",
            transport=failing_transport,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(result.source, FilenameClueSource.LOCAL_RULES)
        self.assertEqual(result.values["track"], "01")
        self.assertEqual(result.values["title"], "Song (Remastered)")

    def test_each_explicit_analysis_makes_a_fresh_request(self):
        calls = []

        def transport(**kwargs):
            calls.append(kwargs)
            return self._deepseek_response(
                {
                    "title": "Song",
                    "artist": "Artist",
                    "album": "",
                    "track": "",
                    "disc": "",
                }
            )

        first = analyze_filename_clues(
            "Artist - Song.mp3",
            api_key="configured",
            transport=transport,
        )
        second = analyze_filename_clues(
            "Artist - Song.mp3",
            api_key="configured",
            transport=transport,
        )

        self.assertEqual(first.source, FilenameClueSource.DEEPSEEK)
        self.assertEqual(second.source, FilenameClueSource.DEEPSEEK)
        self.assertEqual(len(calls), 2)

    def test_cancellation_after_transport_does_not_run_local_fallback(self):
        cancel_event = threading.Event()

        def cancelling_transport(**_kwargs):
            cancel_event.set()
            return self._deepseek_response(
                {
                    "title": "Song",
                    "artist": "Artist",
                    "album": "",
                    "track": "",
                    "disc": "",
                }
            )

        with self.assertRaises(SearchCancelled):
            analyze_filename_clues(
                "Artist - Song.mp3",
                api_key="configured",
                transport=cancelling_transport,
                cancel_event=cancel_event,
            )


if __name__ == "__main__":
    unittest.main()
