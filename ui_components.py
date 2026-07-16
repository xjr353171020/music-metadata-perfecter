# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLineEdit, QFormLayout, QTextEdit, 
                             QFileDialog, QLabel, QMessageBox, QListWidget,
                             QListWidgetItem, QScroller, QSplitter, QStackedWidget)
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt, QTimer

from config import APP_SETTINGS, APP_VERSION


def build_debug_log_filename(log_prefix, now=None):
    timestamp = now or datetime.now()
    return f"{log_prefix}-v{APP_VERSION}-{timestamp:%Y%m%d-%H%M%S}.log"


def format_debug_log(json_list, log_prefix):
    sections = []
    for index, (title, content) in enumerate(json_list or [], start=1):
        sections.append(f"{'=' * 24} [{index}] {title} {'=' * 24}\n{content}")
    body = "\n\n".join(sections) or "暂无 API 返回数据。\n"
    return f"App version: {APP_VERSION}\nLog type: {log_prefix}\n\n{body}"

class LoadingOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.angle = 0
        self.timer = QTimer(self)
        self.timeout_signal = self.timer.timeout
        self.timeout_signal.connect(self.rotate)
        self.hide()

    def rotate(self):
        self.angle = (self.angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)
        for i in range(12):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 255 - (i * 20)))
            painter.drawEllipse(-6, -25, 12, 12)
            painter.rotate(30)

    def start(self):
        self.show(); self.raise_(); self.timer.start(50)

    def stop(self):
        self.timer.stop(); self.hide()

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ 设置工作目录")
        self.resize(550, 195)
        layout = QFormLayout(self)
        self.ncm_input = QLineEdit(APP_SETTINGS.get("VIP_DOWNLOAD_DIR", ""))
        btn_ncm = QPushButton("浏览...")
        btn_ncm.clicked.connect(lambda: self.browse_dir(self.ncm_input))
        row1 = QHBoxLayout(); row1.addWidget(self.ncm_input); row1.addWidget(btn_ncm)
        layout.addRow("NCM 下载目录:", row1)
        self.main_input = QLineEdit(APP_SETTINGS.get("MAIN_MUSIC_DIR", ""))
        btn_main = QPushButton("浏览...")
        btn_main.clicked.connect(lambda: self.browse_dir(self.main_input))
        row2 = QHBoxLayout(); row2.addWidget(self.main_input); row2.addWidget(btn_main)
        layout.addRow("主曲库目录:", row2)
        self.deepseek_key_input = QLineEdit(APP_SETTINGS.get("DEEPSEEK_API_KEY", ""))
        self.deepseek_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.deepseek_key_input.setPlaceholderText("可留空；也可使用环境变量 DEEPSEEK_API_KEY")
        layout.addRow("DeepSeek API Key:", self.deepseek_key_input)
        btn_save = QPushButton("💾 保存设置")
        btn_save.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 8px;")
        btn_save.clicked.connect(self.accept)
        layout.addRow("", btn_save)

    def browse_dir(self, line_edit):
        dir_path = QFileDialog.getExistingDirectory(self, "选择目录", line_edit.text())
        if dir_path: line_edit.setText(os.path.normpath(dir_path))

class DebugDialog(QDialog):
    def __init__(self, json_list, parent=None, log_prefix="metadata-search"):
        super().__init__(parent)
        self.json_list = json_list or []
        self.log_prefix = log_prefix
        self.setWindowTitle("🐞 元数据 API 原始返回数据分析追踪")
        self.resize(1000, 680)
        layout = QVBoxLayout(self)
        
        # Use a normal list, not west-positioned QTabWidget tabs: Qt rotates
        # west tab captions.  This behaves like a chat sidebar and is resized
        # with the splitter handle.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.sidebar = QListWidget()
        self.sidebar.setMinimumWidth(150)
        self.sidebar.setMaximumWidth(420)
        self.sidebar.setStyleSheet("""
            QListWidget { background: #f7f7f8; border: 0; padding: 6px; }
            QListWidget::item { min-height: 34px; padding: 6px 8px; border-radius: 5px; }
            QListWidget::item:selected { background: #e6edf5; color: #1f6faa; font-weight: bold; }
            QListWidget::item:hover { background: #ececf1; }
        """)
        self.sidebar.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        QScroller.grabGesture(self.sidebar.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self.pages = QStackedWidget()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 780])
        if not self.json_list:
            self.sidebar.addItem(QListWidgetItem("无数据"))
            self.pages.addWidget(QLabel("暂无数据。请先执行一次 API 搜索。"))
        else:
            for title, content in self.json_list:
                text_edit = QTextEdit()
                text_edit.setReadOnly(True)
                text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
                text_edit.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas, Courier New, monospace; font-size: 13px;")
                text_edit.setPlainText(content)
                QScroller.grabGesture(text_edit.viewport(), QScroller.ScrollerGestureType.TouchGesture)
                self.sidebar.addItem(QListWidgetItem(title))
                self.pages.addWidget(text_edit)
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
                
        layout.addWidget(splitter)

        btn_export = QPushButton("导出本次检索日志…")
        btn_export.setStyleSheet("padding: 7px 14px; font-weight: bold;")
        btn_export.clicked.connect(self.export_log)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(btn_export)
        layout.addLayout(footer)

    def export_log(self):
        """Save every displayed raw response in a portable UTF-8 text log."""
        default_name = build_debug_log_filename(self.log_prefix)
        dialog_title = (
            "导出专辑封面检索日志"
            if self.log_prefix == "cover-search"
            else "导出元数据检索日志"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, dialog_title, os.path.join(os.getcwd(), default_name),
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(format_debug_log(self.json_list, self.log_prefix))
            QMessageBox.information(self, "导出完成", f"日志已保存到：\n{path}")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入日志：\n{exc}")
