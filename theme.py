# -*- coding: utf-8 -*-
"""Windows-aware Qt theme support for the desktop editor.

The application historically used many widget-local light colour literals.  This
module keeps those existing styles usable while translating their presentation
colours when Windows is using its dark app theme.  Metadata and workflow state
remain outside this module.
"""

from __future__ import annotations

import ctypes
import os
import re
import weakref
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QEvent, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class ThemeColors:
    window: str
    surface: str
    surface_alt: str
    input: str
    button: str
    border: str
    text: str
    text_muted: str
    disabled: str
    accent: str
    accent_hover: str
    selection: str
    selection_text: str
    success: str
    success_surface: str
    warning: str
    warning_surface: str
    danger: str
    danger_surface: str
    purple: str
    purple_surface: str
    info_surface: str
    header_surface: str
    debug_surface: str
    debug_text: str


LIGHT_COLORS = ThemeColors(
    window="#ffffff",
    surface="#ffffff",
    surface_alt="#f4f6f7",
    input="#ffffff",
    button="#f8f9fa",
    border="#bdc3c7",
    text="#2c3e50",
    text_muted="#7f8c8d",
    disabled="#95a5a6",
    accent="#2980b9",
    accent_hover="#3498db",
    selection="#3498db",
    selection_text="#ffffff",
    success="#27ae60",
    success_surface="#d5f5e3",
    warning="#d68910",
    warning_surface="#fdf3e7",
    danger="#e74c3c",
    danger_surface="#fdfbfb",
    purple="#8e44ad",
    purple_surface="#f5eef8",
    info_surface="#e8f4f8",
    header_surface="#f4f6f7",
    debug_surface="#1e1e1e",
    debug_text="#d4d4d4",
)

DARK_COLORS = ThemeColors(
    window="#202020",
    surface="#202020",
    surface_alt="#292929",
    input="#181818",
    button="#2b2b2b",
    border="#555555",
    text="#f1f1f1",
    text_muted="#b2b2b2",
    disabled="#858585",
    accent="#60cdff",
    accent_hover="#78d7ff",
    selection="#3d6f8f",
    selection_text="#ffffff",
    success="#55c98a",
    success_surface="#1f3b2c",
    warning="#ffbd63",
    warning_surface="#49361f",
    danger="#ff7777",
    danger_surface="#452727",
    purple="#c28bea",
    purple_surface="#382944",
    info_surface="#1d3542",
    header_surface="#292929",
    debug_surface="#141414",
    debug_text="#d4d4d4",
)


_BASE_STYLE_PROPERTY = "_music_theme_base_stylesheet"
_APPLIED_STYLE_PROPERTY = "_music_theme_applied_stylesheet"
_CONTROLLER_ATTRIBUTE = "_music_metadata_theme_controller"

_DECLARATION_RE = re.compile(
    r"(?P<property>[-\w]+)\s*:\s*(?P<value>[^;{}]+)",
    re.IGNORECASE,
)
_COLOR_TOKEN_RE = re.compile(
    r"#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|\b(?:white|black)\b",
    re.IGNORECASE,
)
_RGBA_RE = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)"
    r"(?:\s*,\s*([\d.]+%?))?\s*\)",
    re.IGNORECASE,
)


def _normalise_mode(mode) -> ThemeMode:
    if isinstance(mode, ThemeMode):
        return mode
    if isinstance(mode, bool):
        return ThemeMode.DARK if mode else ThemeMode.LIGHT
    if isinstance(mode, str):
        return ThemeMode.DARK if mode.lower() in {"dark", "night", "夜间", "深色"} else ThemeMode.LIGHT
    return ThemeMode.LIGHT


def colors_for_mode(mode) -> ThemeColors:
    return DARK_COLORS if _normalise_mode(mode) is ThemeMode.DARK else LIGHT_COLORS


def _read_windows_personalize_value(value_name: str):
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return winreg.QueryValueEx(key, value_name)[0]
    except (OSError, ImportError):
        return None


def detect_dark_mode(
    app: Optional[QApplication] = None,
    registry_reader: Optional[Callable[[str], object]] = None,
) -> bool:
    """Return whether Windows' app theme is dark.

    ``AppsUseLightTheme`` is the per-app preference used by Windows 10/11.  A
    reader is injectable so the decision can be tested without changing the
    user's registry.
    """

    reader = registry_reader or _read_windows_personalize_value
    for value_name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
        try:
            value = reader(value_name)
        except Exception:
            value = None
        if value is not None:
            try:
                return int(value) == 0
            except (TypeError, ValueError):
                pass

    if app is not None:
        try:
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False
        except (AttributeError, RuntimeError):
            pass

        try:
            colour = app.palette().color(QPalette.ColorRole.Window)
            return colour.lightnessF() < 0.5
        except (AttributeError, RuntimeError):
            pass
    return False


def _colour_category(property_name: str) -> str:
    name = property_name.lower()
    if "background" in name or name in {"alternate-background-color", "selection-background-color"}:
        return "background"
    if "border" in name or "outline" in name:
        return "border"
    if name in {"color", "selection-color", "text-color"} or name.endswith("-color"):
        return "foreground"
    return "generic"


def _darken_light_colour(value: str, category: str, colours: ThemeColors) -> str:
    qcolour = QColor(value)
    if not qcolour.isValid():
        return value
    lightness = qcolour.lightnessF()
    if category == "background" and lightness > 0.62:
        # Keep a hint of the original status hue while moving it into a dark
        # surface range, so generated comparison gradients remain meaningful.
        hue, saturation, _, alpha = qcolour.getHslF()
        if saturation < 0.08 or hue < 0:
            return colours.surface_alt
        replacement = QColor()
        replacement.setHslF(hue, min(1.0, saturation), 0.20, alpha)
        return replacement.name(QColor.NameFormat.HexArgb if alpha < 1.0 else QColor.NameFormat.HexRgb)
    if category == "foreground" and lightness < 0.38:
        return colours.text
    if category == "border" and lightness > 0.55:
        return colours.border
    return value


def _map_css_colour(value: str, category: str, colours: ThemeColors) -> str:
    lower = value.lower()
    if lower == "white":
        return colours.selection_text if category == "foreground" else colours.input
    if lower == "black":
        return colours.text if category == "foreground" else colours.input

    rgba_match = _RGBA_RE.fullmatch(value.strip())
    if rgba_match:
        red, green, blue = (int(rgba_match.group(i)) for i in range(1, 4))
        alpha = rgba_match.group(4)
        if red >= 245 and green >= 245 and blue >= 245 and category == "background":
            return "rgba(32, 32, 32, 230)"
        if red <= 10 and green <= 10 and blue <= 10 and category == "background":
            return "rgba(0, 0, 0, 150)"
        return value

    key = lower
    background_map = {
        "#ffffff": colours.input,
        "#fff": colours.input,
        "#f8f9fa": colours.button,
        "#fafafa": colours.surface_alt,
        "#f4f6f7": colours.surface_alt,
        "#ecf0f1": colours.button,
        "#fdfbfb": colours.danger_surface,
        "#fdf3e7": colours.warning_surface,
        "#f5eef8": colours.purple_surface,
        "#e8f4f8": colours.info_surface,
        "#d5f5e3": colours.success_surface,
        "#e6edf5": colours.info_surface,
        "#ececf1": colours.surface_alt,
        "#f7f7f8": colours.surface_alt,
        "#c9f3d2": colours.success_surface,
        "#1e1e1e": colours.debug_surface,
        "#555555": "#3b3b3b",
        "#2c3e50": "#353535",
        "#34495e": "#3a3a3a",
        "#7f8c8d": "#3f3f3f",
        "#bdc3c7": colours.border,
    }
    foreground_map = {
        "#2c3e50": colours.text,
        "#34495e": colours.text,
        "#7f8c8d": colours.text_muted,
        "#95a5a6": colours.disabled,
        "#bdc3c7": colours.text_muted,
        "#dcdde1": colours.text_muted,
        "#b9ddeb": colours.accent,
        "#d4d4d4": colours.debug_text,
        "#1e1e1e": colours.text,
    }
    border_map = {
        "#bdc3c7": colours.border,
        "#dcdde1": colours.border,
        "#b9ddeb": colours.accent,
    }
    accent_map = {
        "#2980b9": colours.accent,
        "#3498db": colours.accent_hover,
        "#1f6faa": colours.accent,
        "#5b7db1": "#6f9bd0",
        "#27ae60": colours.success,
        "#8e44ad": colours.purple,
        "#e74c3c": colours.danger,
        "#c0392b": "#ff9999",
        "#e67e22": "#ffb454",
        "#d35400": "#ff9f43",
        "#f39c12": "#e4a83a",
        "#d68910": colours.warning,
        "#e57373": "#ff8b83",
    }
    if category == "background" and key in background_map:
        return background_map[key]
    if category == "foreground" and key in foreground_map:
        return foreground_map[key]
    if category == "border" and key in border_map:
        return border_map[key]
    if key in accent_map:
        return accent_map[key]
    return _darken_light_colour(value, category, colours)


def transform_stylesheet(stylesheet: str, mode=ThemeMode.LIGHT) -> str:
    """Translate colour declarations in an existing widget stylesheet."""

    if not stylesheet or _normalise_mode(mode) is ThemeMode.LIGHT:
        return stylesheet
    colours = colors_for_mode(mode)

    def replace_declaration(match):
        category = _colour_category(match.group("property"))

        def replace_token(token_match):
            return _map_css_colour(token_match.group(0), category, colours)

        value = _COLOR_TOKEN_RE.sub(replace_token, match.group("value"))
        return match.group(0).replace(match.group("value"), value)

    return _DECLARATION_RE.sub(replace_declaration, stylesheet)


def build_application_stylesheet(mode=ThemeMode.LIGHT) -> str:
    """Build the palette-backed fallback stylesheet used by all windows."""

    colours = colors_for_mode(mode)
    return f"""
        * {{
            font-family: 'Microsoft YaHei', 'Segoe UI';
            font-size: 10pt;
        }}
        QWidget {{ color: {colours.text}; }}
        QMainWindow, QDialog {{ background-color: {colours.window}; }}
        QLineEdit, QComboBox, QTextEdit, QPlainTextEdit,
        QSpinBox, QDoubleSpinBox {{
            background-color: {colours.input};
            color: {colours.text};
            border: 1px solid {colours.border};
            selection-background-color: {colours.selection};
            selection-color: {colours.selection_text};
        }}
        QComboBox QAbstractItemView, QListView, QTreeView, QTableView {{
            background-color: {colours.input};
            color: {colours.text};
            border: 1px solid {colours.border};
            selection-background-color: {colours.selection};
            selection-color: {colours.selection_text};
        }}
        QPushButton, QToolButton {{
            color: {colours.text};
            background-color: {colours.button};
            border: 1px solid {colours.border};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        QPushButton:hover, QToolButton:hover {{ border-color: {colours.accent}; }}
        QPushButton:pressed, QToolButton:pressed {{ background-color: {colours.surface_alt}; }}
        QPushButton:disabled, QToolButton:disabled {{ color: {colours.disabled}; }}
        QGroupBox {{ color: {colours.text}; }}
        QScrollArea, QAbstractScrollArea {{ border-color: {colours.border}; }}
        QHeaderView::section {{
            color: {colours.text};
            background-color: {colours.surface_alt};
            border: 1px solid {colours.border};
        }}
        QListWidget::item:selected, QTreeWidget::item:selected,
        QTableWidget::item:selected {{
            background-color: {colours.selection};
            color: {colours.selection_text};
        }}
        QProgressBar {{
            color: {colours.text};
            background-color: {colours.surface_alt};
            border: 1px solid {colours.border};
            border-radius: 3px;
            text-align: center;
        }}
        QProgressBar::chunk {{ background-color: {colours.accent}; border-radius: 2px; }}
        QToolTip {{
            color: {colours.text};
            background-color: {colours.surface_alt};
            border: 1px solid {colours.border};
        }}
        QMenu {{
            color: {colours.text};
            background-color: {colours.surface};
            border: 1px solid {colours.border};
        }}
        QMenu::item:selected {{ background-color: {colours.selection}; color: {colours.selection_text}; }}
        QCheckBox::indicator {{ width: 15px; height: 15px; }}
        QSlider::groove:horizontal {{ background: {colours.border}; height: 4px; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: {colours.accent}; width: 12px; margin: -4px 0; border-radius: 6px; }}
        QSplitter::handle {{ background-color: {colours.border}; }}
    """


def theme_color(name: str, mode=None) -> str:
    """Return a semantic colour for a widget or non-style item."""

    if mode is None:
        app = QApplication.instance()
        controller = getattr(app, _CONTROLLER_ATTRIBUTE, None) if app else None
        mode = controller.mode if controller else ThemeMode.LIGHT
    colours = colors_for_mode(mode)
    return getattr(colours, name)


def get_theme_controller(app: Optional[QApplication] = None):
    """Return the installed controller, if the application has one."""

    app = app or QApplication.instance()
    return getattr(app, _CONTROLLER_ATTRIBUTE, None) if app is not None else None


def _set_native_title_bar(window: QWidget, dark: bool) -> None:
    if (
        os.name != "nt"
        or os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}
        or not window
        or not window.isWindow()
    ):
        return
    try:
        hwnd = int(window.winId())
        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # Win11/Win10 dark title-bar attributes.
            result = dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attribute),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                break
    except (AttributeError, OSError, TypeError, ValueError):
        # Native title bars are an enhancement; Qt rendering must still work if
        # DWM is unavailable (for example in a remote session or test backend).
        return


class ThemeController(QObject):
    """Apply and monitor the Windows app theme for the current QApplication."""

    theme_changed = pyqtSignal(str)

    def __init__(self, app: QApplication, poll_interval_ms: int = 1500):
        super().__init__(app)
        self.app = app
        self.mode = ThemeMode.LIGHT
        self._applying_theme = False
        self._rewriting_styles = False
        self._styled_widgets = weakref.WeakSet()
        self._initial_style_scan_done = False
        self._timer = QTimer(self)
        self._timer.setInterval(max(500, int(poll_interval_ms)))
        self._timer.timeout.connect(self.refresh)
        app.installEventFilter(self)
        try:
            app.styleHints().colorSchemeChanged.connect(self._on_qt_scheme_changed)
        except (AttributeError, RuntimeError):
            pass

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _on_qt_scheme_changed(self, *_args) -> None:
        self.refresh()

    def apply(self, dark=None) -> ThemeMode:
        if dark is None:
            next_mode = ThemeMode.DARK if detect_dark_mode(self.app) else ThemeMode.LIGHT
        else:
            next_mode = _normalise_mode(dark)
        changed = next_mode is not self.mode
        self.mode = next_mode
        self._applying_theme = True
        try:
            self.app.setProperty("music_metadata_theme", next_mode.value)
            self.app.setPalette(_palette_for_mode(next_mode))
            self.app.setStyleSheet(build_application_stylesheet(next_mode))
        finally:
            self._applying_theme = False
        self._rewrite_all_widget_styles()
        self._refresh_native_title_bars()
        if changed:
            self.theme_changed.emit(next_mode.value)
        return next_mode

    def refresh(self) -> bool:
        detected = ThemeMode.DARK if detect_dark_mode(self.app) else ThemeMode.LIGHT
        if detected is self.mode:
            return False
        self.apply(detected)
        return True

    def eventFilter(self, watched, event):
        if self._rewriting_styles:
            return False
        if self._applying_theme:
            if isinstance(watched, QWidget) and watched.styleSheet():
                self._styled_widgets.add(watched)
            return False
        if isinstance(watched, QWidget):
            if event.type() == QEvent.Type.StyleChange:
                self._capture_and_rewrite_style(watched)
            elif event.type() == QEvent.Type.Show:
                _set_native_title_bar(watched, self.mode is ThemeMode.DARK)
        return False

    def _capture_and_rewrite_style(self, widget: QWidget) -> None:
        current = widget.styleSheet()
        if current:
            self._styled_widgets.add(widget)
        applied = widget.property(_APPLIED_STYLE_PROPERTY)
        if applied is not None and current == applied:
            return
        widget.setProperty(_BASE_STYLE_PROPERTY, current)
        transformed = transform_stylesheet(current, self.mode)
        widget.setProperty(_APPLIED_STYLE_PROPERTY, transformed)
        if transformed != current:
            self._set_style_without_capture(widget, transformed)

    def _rewrite_all_widget_styles(self) -> None:
        if not self._initial_style_scan_done:
            seen = set()
            for top_level in self.app.topLevelWidgets():
                for widget in [top_level, *top_level.findChildren(QWidget)]:
                    marker = id(widget)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    if widget.styleSheet():
                        self._styled_widgets.add(widget)
            self._initial_style_scan_done = True
        for widget in list(self._styled_widgets):
            self._rewrite_saved_style(widget)

    def _rewrite_saved_style(self, widget: QWidget) -> None:
        current = widget.styleSheet()
        base = widget.property(_BASE_STYLE_PROPERTY)
        applied = widget.property(_APPLIED_STYLE_PROPERTY)
        if base is None:
            if not current:
                return
            base = current
            widget.setProperty(_BASE_STYLE_PROPERTY, base)
        transformed = transform_stylesheet(base, self.mode)
        widget.setProperty(_APPLIED_STYLE_PROPERTY, transformed)
        if current != transformed and current != applied:
            self._set_style_without_capture(widget, transformed)
        elif current != transformed and applied == current:
            self._set_style_without_capture(widget, transformed)

    def _set_style_without_capture(self, widget: QWidget, stylesheet: str) -> None:
        self._rewriting_styles = True
        try:
            widget.setStyleSheet(stylesheet)
        finally:
            self._rewriting_styles = False

    def _refresh_native_title_bars(self) -> None:
        dark = self.mode is ThemeMode.DARK
        for window in self.app.topLevelWidgets():
            _set_native_title_bar(window, dark)


def _palette_for_mode(mode: ThemeMode) -> QPalette:
    colours = colors_for_mode(mode)
    palette = QPalette()
    role_values = {
        QPalette.ColorRole.Window: colours.window,
        QPalette.ColorRole.Base: colours.input,
        QPalette.ColorRole.AlternateBase: colours.surface_alt,
        QPalette.ColorRole.Text: colours.text,
        QPalette.ColorRole.WindowText: colours.text,
        QPalette.ColorRole.Button: colours.button,
        QPalette.ColorRole.ButtonText: colours.text,
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: colours.selection,
        QPalette.ColorRole.HighlightedText: colours.selection_text,
        QPalette.ColorRole.Link: colours.accent,
        QPalette.ColorRole.ToolTipBase: colours.surface_alt,
        QPalette.ColorRole.ToolTipText: colours.text,
        QPalette.ColorRole.PlaceholderText: colours.text_muted,
        QPalette.ColorRole.Mid: colours.border,
        QPalette.ColorRole.Dark: colours.surface_alt,
        QPalette.ColorRole.Shadow: "#000000" if mode is ThemeMode.DARK else "#808080",
    }
    for role, value in role_values.items():
        palette.setColor(role, QColor(value))
    disabled_values = {
        QPalette.ColorRole.WindowText: colours.disabled,
        QPalette.ColorRole.Text: colours.disabled,
        QPalette.ColorRole.ButtonText: colours.disabled,
        QPalette.ColorRole.PlaceholderText: colours.disabled,
    }
    for role, value in disabled_values.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(value))
    return palette


def apply_theme(
    app: Optional[QApplication] = None,
    dark=None,
    monitor: bool = True,
) -> ThemeController:
    """Install the process-wide theme controller and apply the initial mode."""

    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("apply_theme() requires a QApplication")
    controller = getattr(app, _CONTROLLER_ATTRIBUTE, None)
    if controller is None:
        controller = ThemeController(app)
        setattr(app, _CONTROLLER_ATTRIBUTE, controller)
    controller.apply(dark)
    if monitor:
        controller.start()
    return controller
