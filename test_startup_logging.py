import io
import threading
import unittest
from datetime import datetime
from pathlib import Path

from config import APP_NAME, APP_VERSION
from startup_logging import TeeTextStream, build_runtime_log_path
from ui_components import build_debug_log_filename, format_debug_log


class StartupLoggingTests(unittest.TestCase):
    def test_product_name_is_shared_with_launcher(self):
        self.assertEqual(APP_NAME, "Music Metadata Perfecter")

    def test_runtime_log_path_contains_version_and_date(self):
        path = build_runtime_log_path(
            "C:/app", APP_VERSION, datetime(2026, 7, 16, 12, 30, 45)
        )

        self.assertEqual(
            path,
            Path("C:/app")
            / "runtime_logs"
            / f"runtime-v{APP_VERSION}-20260716.log",
        )

    def test_tee_writes_to_console_and_transcript(self):
        console = io.StringIO()
        transcript = io.StringIO()
        stream = TeeTextStream(console, transcript, threading.RLock())

        self.assertEqual(stream.write("diagnostic\n"), len("diagnostic\n"))
        self.assertEqual(console.getvalue(), "diagnostic\n")
        self.assertEqual(transcript.getvalue(), "diagnostic\n")

    def test_search_log_names_distinguish_type_and_version(self):
        timestamp = datetime(2026, 7, 16, 12, 30, 45)

        self.assertEqual(
            build_debug_log_filename("metadata-search", timestamp),
            f"metadata-search-v{APP_VERSION}-20260716-123045.log",
        )
        self.assertEqual(
            build_debug_log_filename("cover-search", timestamp),
            f"cover-search-v{APP_VERSION}-20260716-123045.log",
        )

    def test_exported_debug_log_contains_version_type_and_sections(self):
        content = format_debug_log(
            [("Request", "request details"), ("Response", "response details")],
            "cover-search",
        )

        self.assertTrue(content.startswith(f"App version: {APP_VERSION}\n"))
        self.assertIn("Log type: cover-search", content)
        self.assertIn("[1] Request", content)
        self.assertIn("[2] Response", content)


if __name__ == "__main__":
    unittest.main()
