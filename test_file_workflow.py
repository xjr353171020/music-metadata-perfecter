import os
import tempfile
import unittest
from unittest.mock import patch

from file_workflow import _converter_batches, convert_ncm_files


class FileWorkflowTests(unittest.TestCase):
    def test_convert_passes_multiple_ncm_files_to_one_process(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name in ("one.ncm", "two.ncm", "three.ncm"):
                path = os.path.join(directory, name)
                open(path, "wb").close()
                paths.append(path)
            converter = os.path.join(directory, "Ncm拖一拖.exe")
            open(converter, "wb").close()

            with patch(
                "file_workflow.get_bundled_exe_path", return_value=converter
            ), patch("file_workflow.subprocess.run") as run:
                success, message = convert_ncm_files(directory)

        self.assertTrue(success)
        self.assertIn("3", message)
        run.assert_called_once_with(
            [converter, *sorted(paths, key=lambda path: os.path.basename(path).casefold())],
            check=True,
            cwd=directory,
        )

    def test_converter_batches_only_split_when_command_line_is_too_long(self):
        converter = r"C:\tool.exe"
        files = [rf"C:\music\{'x' * 20}-{index}.ncm" for index in range(4)]

        batches = _converter_batches(converter, files, limit=75)

        self.assertGreater(len(batches), 1)
        self.assertEqual([path for batch in batches for path in batch], files)


if __name__ == "__main__":
    unittest.main()
