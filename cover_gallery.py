# -*- coding: utf-8 -*-
"""UI for selecting a downloaded album cover."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QListWidget, QListWidgetItem, QScroller, QVBoxLayout

from theme import get_theme_controller, theme_color


_HIGH_RESOLUTION_ROLE = Qt.ItemDataRole.UserRole + 1


class CoverGalleryDialog(QDialog):
    """Present cover candidates and return the bytes of the chosen image."""

    def __init__(self, images_data, stats, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 智能封面画廊 (双击应用)")
        self.resize(800, 650)
        self.selected_data = None
        self._theme_controller = get_theme_controller(QApplication.instance())
        if self._theme_controller is not None:
            self._theme_controller.theme_changed.connect(self._on_theme_changed)

        layout = QVBoxLayout(self)
        status_text = f"🍎 Apple Music: {stats.get('am', '未知')}    |    🌍 MusicBrainz: {stats.get('mb', '未知')}"
        status_label = QLabel(status_text)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setStyleSheet("color: #2980b9; font-weight: bold; font-size: 10pt; margin-bottom: 5px;")
        layout.addWidget(status_label)

        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setIconSize(QSize(220, 220))
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setSpacing(15)
        self.list_widget.setStyleSheet(
            "QListWidget::item { padding: 10px; } "
            "QListWidget::item:hover { background-color: #ecf0f1; border-radius: 6px; }"
        )
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self.list_widget.viewport(), QScroller.ScrollerGestureType.TouchGesture)

        for item_data in images_data:
            image_data = item_data["data"]
            image = QImage.fromData(image_data)
            width, height = image.width(), image.height()
            item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), f"{item_data['source']}\n物理分辨率: {width} x {height}")
            item.setData(Qt.ItemDataRole.UserRole, image_data)
            if width >= 1000:
                item.setData(_HIGH_RESOLUTION_ROLE, True)
                item.setForeground(QColor(theme_color("success")))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)

        hint = QLabel("💡 提示: 苹果音乐通常提供无损原图，MB库则是黑胶/CD扫描图。双击你心仪的图片直接覆盖。")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #7f8c8d; font-weight: bold;")
        layout.addWidget(hint)

    def _on_theme_changed(self, _mode):
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.data(_HIGH_RESOLUTION_ROLE):
                item.setForeground(QColor(theme_color("success")))

    def on_item_double_clicked(self, item):
        self.selected_data = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
