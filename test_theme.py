# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from cover_gallery import CoverGalleryDialog
from theme import (
    DARK_COLORS,
    ThemeController,
    ThemeMode,
    apply_theme,
    build_application_stylesheet,
    detect_dark_mode,
    transform_stylesheet,
)


class ThemeDecisionTests(unittest.TestCase):
    def test_apps_preference_takes_priority_over_system_preference(self):
        values = {"AppsUseLightTheme": 0, "SystemUsesLightTheme": 1}
        self.assertTrue(detect_dark_mode(registry_reader=values.get))

    def test_light_apps_preference_disables_dark_mode(self):
        values = {"AppsUseLightTheme": 1, "SystemUsesLightTheme": 0}
        self.assertFalse(detect_dark_mode(registry_reader=values.get))

    def test_missing_registry_values_fall_back_to_light(self):
        self.assertFalse(detect_dark_mode(registry_reader=lambda _name: None))


class ThemeRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dark_stylesheet_translates_surface_text_and_border(self):
        source = "QLineEdit { background: #f4f6f7; color: #34495e; border: 1px solid #bdc3c7; }"
        rendered = transform_stylesheet(source, ThemeMode.DARK)
        self.assertIn(f"background: {DARK_COLORS.surface_alt}", rendered)
        self.assertIn(f"color: {DARK_COLORS.text}", rendered)
        self.assertIn(f"border: 1px solid {DARK_COLORS.border}", rendered)

    def test_dark_stylesheet_keeps_debug_editor_readable(self):
        source = "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; }"
        rendered = transform_stylesheet(source, ThemeMode.DARK)
        self.assertIn(f"background-color: {DARK_COLORS.debug_surface}", rendered)
        self.assertIn(f"color: {DARK_COLORS.debug_text}", rendered)

    def test_application_stylesheet_contains_dark_palette_values(self):
        stylesheet = build_application_stylesheet(ThemeMode.DARK)
        self.assertIn(DARK_COLORS.window, stylesheet)
        self.assertIn(DARK_COLORS.input, stylesheet)
        self.assertIn(DARK_COLORS.selection, stylesheet)

    def test_controller_rewrites_local_styles_and_restores_original(self):
        original_app_style = self.app.styleSheet()
        original_palette = self.app.palette()
        controller = ThemeController(self.app, poll_interval_ms=60000)
        widget = QWidget()
        label = QLabel("主题测试", widget)
        source = "background: #f4f6f7; color: #34495e; border: 1px solid #bdc3c7;"
        try:
            controller.apply(True)
            label.setStyleSheet(source)
            self.app.processEvents()
            self.assertIn(DARK_COLORS.surface_alt, label.styleSheet())
            self.assertIn(DARK_COLORS.text, label.styleSheet())
            self.assertIn(DARK_COLORS.border, label.styleSheet())

            controller.apply(False)
            self.app.processEvents()
            self.assertEqual(source, label.styleSheet())
        finally:
            controller.stop()
            self.app.removeEventFilter(controller)
            widget.deleteLater()
            controller.deleteLater()
            self.app.setStyleSheet(original_app_style)
            self.app.setPalette(original_palette)
            self.app.processEvents()

    def test_open_cover_gallery_refreshes_direct_item_colour_on_theme_change(self):
        original_app_style = self.app.styleSheet()
        original_palette = self.app.palette()
        controller = apply_theme(self.app, dark=True, monitor=False)
        image = QImage(1000, 1000, QImage.Format.Format_RGB32)
        image.fill(0xFF336699)
        data = bytes()
        buffer = None
        try:
            from PyQt6.QtCore import QBuffer, QIODevice

            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            data = bytes(buffer.data())
            dialog = CoverGalleryDialog([{"data": data, "source": "测试"}], {"am": "1", "mb": "0"})
            item = dialog.list_widget.item(0)
            self.assertEqual(item.foreground().color().name(), DARK_COLORS.success)

            controller.apply(False)
            self.app.processEvents()
            self.assertEqual(item.foreground().color().name(), "#27ae60")
        finally:
            if buffer is not None:
                buffer.close()
            if "dialog" in locals():
                dialog.close()
                dialog.deleteLater()
            controller.stop()
            self.app.removeEventFilter(controller)
            if hasattr(self.app, "_music_metadata_theme_controller"):
                delattr(self.app, "_music_metadata_theme_controller")
            controller.deleteLater()
            self.app.setStyleSheet(original_app_style)
            self.app.setPalette(original_palette)
            self.app.setProperty("music_metadata_theme", None)
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
