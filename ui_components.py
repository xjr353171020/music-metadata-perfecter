# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QLineEdit, QFormLayout, QTextEdit, 
                             QFileDialog, QLabel, QMessageBox, QListWidget,
                             QListWidgetItem, QProgressBar, QScrollArea, QScroller,
                             QSplitter, QStackedWidget)
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


class FileLoadProgressDialog(QDialog):
    """Display one determinate progress lane for each metadata reader thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据加载中")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setFixedSize(640, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        self.summary_label = QLabel("正在启动多线程元数据读取...")
        self.summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.summary_label)

        lane_container = QWidget()
        self.progress_grid = QGridLayout(lane_container)
        self.progress_grid.setHorizontalSpacing(10)
        self.progress_grid.setVerticalSpacing(10)
        self.progress_grid.setColumnStretch(1, 1)
        lane_scroll = QScrollArea()
        lane_scroll.setWidgetResizable(True)
        lane_scroll.setStyleSheet("QScrollArea { border: none; }")
        lane_scroll.setWidget(lane_container)
        self.progress_bars = []
        self.file_labels = []
        layout.addWidget(lane_scroll)

    def configure_worker_count(self, worker_count):
        previous_count = len(self.progress_bars)
        while len(self.progress_bars) < worker_count:
            slot = len(self.progress_bars)
            thread_label = QLabel(f"线程 {slot + 1}")
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 0)
            progress_bar.setFixedHeight(22)
            progress_bar.setMinimumWidth(320)
            progress_bar.setTextVisible(True)
            file_label = QLabel("等待任务")
            file_label.setMinimumWidth(160)

            self.progress_grid.addWidget(thread_label, slot, 0)
            self.progress_grid.addWidget(progress_bar, slot, 1)
            self.progress_grid.addWidget(file_label, slot, 2)
            self.progress_bars.append(progress_bar)
            self.file_labels.append(file_label)
        if len(self.progress_bars) > previous_count:
            self.summary_label.setText(
                f"正在启动 {worker_count} 个元数据读取线程..."
            )
            self.setFixedHeight(min(680, 110 + worker_count * 42))

    def update_thread_progress(
        self, slot, current, lane_total, completed, total, filename
    ):
        if slot < 0:
            return
        self.configure_worker_count(slot + 1)
        self.summary_label.setText(
            f"正在并行读取音频元数据：总进度 {completed}/{total}"
        )
        progress_bar = self.progress_bars[slot]
        progress_bar.setRange(0, lane_total)
        progress_bar.setValue(current)
        progress_bar.setFormat(f"{current}/{lane_total}")

        file_label = self.file_labels[slot]
        available_width = max(80, file_label.width() - 8)
        file_label.setText(
            file_label.fontMetrics().elidedText(
                filename, Qt.TextElideMode.ElideMiddle, available_width
            )
        )
        file_label.setToolTip(filename)

    def reject(self):
        pass

class SettingsDialog(QDialog):
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        settings = settings or APP_SETTINGS
        self.setWindowTitle("⚙️ 设置工作目录")
        self.resize(550, 195)
        layout = QFormLayout(self)
        self.ncm_input = QLineEdit(settings.get("VIP_DOWNLOAD_DIR", ""))
        btn_ncm = QPushButton("浏览...")
        btn_ncm.clicked.connect(lambda: self.browse_dir(self.ncm_input))
        row1 = QHBoxLayout(); row1.addWidget(self.ncm_input); row1.addWidget(btn_ncm)
        layout.addRow("NCM 下载目录:", row1)
        self.main_input = QLineEdit(settings.get("MAIN_MUSIC_DIR", ""))
        btn_main = QPushButton("浏览...")
        btn_main.clicked.connect(lambda: self.browse_dir(self.main_input))
        row2 = QHBoxLayout(); row2.addWidget(self.main_input); row2.addWidget(btn_main)
        layout.addRow("主曲库目录:", row2)
        self.deepseek_key_input = QLineEdit(settings.get("DEEPSEEK_API_KEY", ""))
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
