import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from config import APP_ICON_PATH, get_bundled_resource_path


class AppIconTests(unittest.TestCase):
    def test_source_icon_assets_exist(self):
        png_path = Path(APP_ICON_PATH)
        ico_path = png_path.with_suffix(".ico")

        self.assertTrue(png_path.is_file())
        self.assertGreater(png_path.stat().st_size, 0)
        self.assertTrue(ico_path.is_file())
        self.assertGreater(ico_path.stat().st_size, 0)

    def test_ico_contains_multiple_sizes(self):
        ico_path = Path(APP_ICON_PATH).with_suffix(".ico")
        reserved, image_type, image_count = struct.unpack(
            "<HHH", ico_path.read_bytes()[:6]
        )

        self.assertEqual(reserved, 0)
        self.assertEqual(image_type, 1)
        self.assertGreaterEqual(image_count, 8)

    def test_bundled_resource_path_uses_pyinstaller_root(self):
        bundle_root = Path("C:/temporary-pyinstaller-bundle")
        with patch.object(sys, "_MEIPASS", str(bundle_root), create=True):
            resolved = get_bundled_resource_path("assets", "app_icon.png")

        self.assertEqual(
            Path(resolved), bundle_root / "assets" / "app_icon.png"
        )


if __name__ == "__main__":
    unittest.main()
