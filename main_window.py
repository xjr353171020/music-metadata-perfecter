# 文件名: main_window.py
# -*- coding: utf-8 -*-
import os
import copy
import difflib
import hashlib
import threading
import urllib.parse
import webbrowser
import re 
import tempfile 

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QListWidget, QListWidgetItem, QComboBox, QLabel, QPushButton, 
                             QMessageBox, QSplitter, QAbstractItemView, QLineEdit, QApplication, 
                             QCheckBox, QScroller, QGroupBox, QSizePolicy, QFrame, QScrollArea,
                             QProgressDialog, QDialog, QDialogButtonBox, QPlainTextEdit, QToolButton)
from PyQt6.QtGui import QPixmap, QKeySequence, QShortcut, QColor, QFontMetrics
from PyQt6.QtCore import (
    Qt, QByteArray, QBuffer, QIODevice, QTimer, QPropertyAnimation,
    QEasingCurve, QEvent, QVariantAnimation,
)

from audio_tagger import AudioTagger
from album_session import AlbumSession
from album_initials import album_initial, album_navigation_sort_key
from config import APP_NAME, APP_SETTINGS, save_settings
from filename_clue import FILENAME_CLUE_FIELDS, FilenameClueSource
from file_workflow import convert_ncm_files, delete_ncm_files, list_ncm_files, move_audio_files, clean_lrc_files
from metadata_save_service import MetadataRestoreService, MetadataSaveService
from save_plan import SavePlanRequest, build_save_plan
from ui_components import FileLoadProgressDialog, LoadingOverlay, SettingsDialog, DebugDialog
from background_workers import (
    FetchWorker,
    FileLoaderWorker,
    FilenameClueWorker,
    RestoreWorker,
    SaveWorker,
)
from cover_gallery import CoverGalleryDialog
from cover_fetch_worker import CoverFetchWorker
from audio_player_widget import AudioPlayerWidget
from library_widgets import AlbumIndexLetter, FileListOverlayContainer, TouchComboBox, TouchSafeFileList
from undo_manager import (
    CursorState,
    EditorStateSnapshot,
    EditorUndoCommand,
    ManagedMetadataSnapshot,
    SavedFileChange,
    SavedMetadataTransaction,
    SessionPatch,
    StoredValue,
    UndoManager,
)


# =========================================================================
# 主界面构建与逻辑
# =========================================================================
class MusicEditorWindow(QMainWindow):
    def __init__(self, fallback_dir, window_settings=None):
        super().__init__()
        
        self.music_dir = fallback_dir
        self.window_settings = copy.deepcopy(window_settings or APP_SETTINGS)
        self.window_settings["MAIN_MUSIC_DIR"] = fallback_dir
        self.additional_windows = {}
        self.album_session = AlbumSession()
        self.current_cover_data = None
        self.cover_modified_in_batch = False
        self._cover_is_mixed = False
        self.undo_manager = UndoManager()
        self._save_in_progress = False
        self._undo_in_progress = False
        self._blocked_key_releases = set()
        self._field_flash_animations = {}
        self._cover_fingerprint_cache = {}
        self._physical_album_key_cache = {}
        self._track_item_cache = {}
        self._header_item_cache = {}
        self._session_modified_album_paths = set()
        self._save_service_factory = MetadataSaveService
        self._restore_service_factory = MetadataRestoreService
        self._local_search_active = False
        self._search_selection_before_filter = set()
        self._search_hidden_paths = set()
        self._search_hidden_headers = set()
        self._editor_baseline = None
        self._loaded_selection_paths = ()
        self._selection_metadata_baseline = None
        self._selection_prompt_suppressed = False
        self._restoring_rejected_selection = False
        self._current_metadata_source = ""
        self._metadata_search_generation = 0
        self._active_metadata_search_id = None
        self._cancelled_metadata_search_ids = set()
        self._cover_search_generation = 0
        self._active_cover_search_id = None
        self._cancelled_cover_search_ids = set()
        self._filename_clue_generation = 0
        self._active_filename_clue_request_id = None
        self._active_filename_clue_path = ""
        self._cancelled_filename_clue_request_ids = set()
        self._search_buttons = []
        
        self.api_cache = {}
        self.album_source_preferences = {}
        self.last_fetch_success = False
        self.last_api_raw_json_list = [] 
        self.last_cover_raw_json_list = [] 
        self.field_configs = [
            ("title", "标题 (Title)", True),
            ("artist", "艺术家 (Artist)", True),
            ("album", "专辑 (Album)", True),
            ("album_artist", "专辑艺术家 (Album Art.)", True),
            ("composer", "作曲家 (Comp.)", False), 
            ("track", "音轨号 (Track)", True),
            ("disc", "碟号 (Disc)", True),
            ("date", "发布日期 (Date)", True), 
            ("genre", "流派 (Genre)", False),
            ("comment", "注释 (Comment)", True)
        ]
        
        self.cb_style_normal = """
            QComboBox { padding: 6px 0px 6px 10px; font-size: 10pt; border: 1px solid #bdc3c7; border-radius: 4px; background-color: #ffffff; }
            QComboBox:hover { border: 1px solid #3498db; }
            QComboBox::drop-down { width: 28px; border: none; border-left: 1px solid #dcdde1; }
            QComboBox::down-arrow { image: none; }
            QComboBox QAbstractItemView { border: 1px solid #bdc3c7; selection-background-color: #3498db; outline: none; font-size: 10pt; }
            QComboBox QLineEdit { font-size: 10pt; }
        """
        self.cb_style_locked = """
            QComboBox { padding: 6px 0px 6px 10px; font-size: 10pt; border: 1px solid #3498db; border-radius: 4px; background-color: #e8f4f8; }
            QComboBox::drop-down { width: 28px; border: none; border-left: 1px solid #b9ddeb; }
            QComboBox::down-arrow { image: none; }
            QComboBox QAbstractItemView { border: 1px solid #3498db; selection-background-color: #2980b9; outline: none; font-size: 10pt; }
            QComboBox QLineEdit { font-size: 10pt; }
        """
        
        self.checkboxes = {}
        self.inputs = {}
        self.lock_btns = {}  
        self.mb_inputs = {} 
        self.mb_apply_btns = {} 
        self.mb_labels = {}
        
        self.init_ui()
        self._search_restore_timer = QTimer(self)
        self._search_restore_timer.setSingleShot(True)
        self._search_restore_timer.setInterval(40)
        self._search_restore_timer.timeout.connect(self.restore_full_list)
        self._connect_undo_capture()
        self._refresh_filename_clue_action()
        self._editor_baseline = self._capture_editor_state()
        QApplication.instance().installEventFilter(self)
        self._initial_load_scheduled = False
        
        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        self.paste_shortcut.activated.connect(self.paste_cover_from_clipboard)

    def start_initial_load(self):
        if self._initial_load_scheduled:
            return
        self._initial_load_scheduled = True
        QTimer.singleShot(0, self.load_file_list)

    def set_workflow_expanded(self, expanded):
        self.btn_workflow_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.workflow_animation.stop()
        self._workflow_target_expanded = expanded

        if expanded:
            self.workflow_content.show()
            start_height = self.workflow_content.height()
            target_height = self.workflow_content.sizeHint().height()
        else:
            if not self.workflow_content.isVisible():
                return
            start_height = self.workflow_content.height()
            target_height = 0

        self.workflow_content.setMaximumHeight(start_height)
        self.workflow_animation.setStartValue(start_height)
        self.workflow_animation.setEndValue(target_height)
        self.workflow_animation.start()

    def _finish_workflow_animation(self):
        if self._workflow_target_expanded:
            # Let normal layouts handle later window/font size changes.
            self.workflow_content.setMaximumHeight(16777215)
        else:
            self.workflow_content.hide()

    def init_ui(self):
        self.setWindowTitle(APP_NAME)
        
        screen_geo = QApplication.primaryScreen().availableGeometry()
        w = min(1600, int(screen_geo.width() * 0.85))
        h = min(900, int(screen_geo.height() * 0.85))
        self.resize(w, h)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        h_layout = QHBoxLayout(main_widget)
        h_layout.setContentsMargins(15, 15, 15, 15)
        h_layout.setSpacing(15)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        h_layout.addWidget(splitter)

        splitter.addWidget(self._build_library_panel())
        splitter.addWidget(self._build_editor_panels())

        self.overlay = LoadingOverlay(self)

    def _build_workflow_section(self):
        workflow_section = QWidget()
        workflow_section_layout = QVBoxLayout(workflow_section)
        workflow_section_layout.setContentsMargins(0, 0, 0, 0)
        workflow_section_layout.setSpacing(4)
        self.btn_workflow_toggle = QToolButton()
        self.btn_workflow_toggle.setText("文件与工作流")
        self.btn_workflow_toggle.setCheckable(True)
        self.btn_workflow_toggle.setChecked(False)
        self.btn_workflow_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.btn_workflow_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_workflow_toggle.setFixedHeight(30)
        self.btn_workflow_toggle.setStyleSheet("QToolButton { text-align: left; padding: 5px 8px; font-size: 10pt; font-weight: bold; border: 1px solid #bdc3c7; border-radius: 4px; background-color: #f8f9fa; }")
        workflow_section_layout.addWidget(self.btn_workflow_toggle)

        self.workflow_content = QWidget()
        tools_layout = QVBoxLayout(self.workflow_content)
        tools_layout.setContentsMargins(6, 4, 6, 4)
        tools_layout.setSpacing(10) 
        
        workflow_btn_style = "padding: 10px; font-size: 10pt; font-weight: bold; border-radius: 4px; border: 1px solid #bdc3c7; background-color: #f8f9fa;"
        btn_settings = QPushButton("⚙️ 设置工作目录"); btn_settings.setStyleSheet(workflow_btn_style); btn_settings.clicked.connect(self.open_settings)
        self.btn_reload_library = QPushButton("🔄 重新读取音乐目录"); self.btn_reload_library.setStyleSheet(workflow_btn_style); self.btn_reload_library.clicked.connect(self.load_file_list)
        btn_convert = QPushButton("🔄 1. 解密 NCM"); btn_convert.setStyleSheet(workflow_btn_style); btn_convert.clicked.connect(self.run_convert)
        btn_move = QPushButton("🚚 2. 移动至曲库"); btn_move.setStyleSheet(workflow_btn_style); btn_move.clicked.connect(self.run_move)
        btn_delete_ncm = QPushButton("🗑️ 删除 NCM"); btn_delete_ncm.setStyleSheet("padding: 10px; font-weight: bold; border-radius: 4px; border: 1px solid #e74c3c; background-color: #fdfbfb; color: #c0392b;"); btn_delete_ncm.clicked.connect(self.confirm_delete_ncm)
        btn_new_window = QPushButton("🗗 新开编辑窗口"); btn_new_window.setStyleSheet(workflow_btn_style); btn_new_window.setToolTip("打开独立编辑窗口，可切换目录后复制元数据"); btn_new_window.clicked.connect(self.open_additional_window)
        btn_clean_lrc = QPushButton("🧹 3. 清理所有 LRC"); btn_clean_lrc.setStyleSheet("padding: 10px; font-weight: bold; border-radius: 4px; border: 1px solid #e74c3c; background-color: #fdfbfb; color: #c0392b;")
        btn_clean_lrc.clicked.connect(self.run_clean_lrc)
        
        ops_layout = QHBoxLayout(); ops_layout.addWidget(btn_convert); ops_layout.addWidget(btn_move)
        secondary_ops_layout = QHBoxLayout(); secondary_ops_layout.addWidget(btn_new_window); secondary_ops_layout.addWidget(btn_delete_ncm)
        tools_layout.addWidget(btn_settings); tools_layout.addWidget(self.btn_reload_library); tools_layout.addLayout(ops_layout); tools_layout.addLayout(secondary_ops_layout); tools_layout.addWidget(btn_clean_lrc)
        workflow_section_layout.addWidget(self.workflow_content)
        self.workflow_animation = QPropertyAnimation(self.workflow_content, b"maximumHeight", self)
        self.workflow_animation.setDuration(160)
        self.workflow_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.workflow_animation.finished.connect(self._finish_workflow_animation)
        self._workflow_target_expanded = False
        self.workflow_content.setMaximumHeight(0)
        self.workflow_content.hide()
        self.btn_workflow_toggle.toggled.connect(self.set_workflow_expanded)
        return workflow_section

    def _build_library_panel(self):
        left_widget = QWidget()
        left_widget.setMinimumWidth(280)
        left_widget.setMaximumWidth(400)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        
        workflow_section = self._build_workflow_section()
        left_layout.addWidget(workflow_section)
        search_bar_layout = QHBoxLayout()
        search_bar_layout.setContentsMargins(0, 0, 0, 0)
        
        self.search_combo = TouchComboBox()
        self.search_combo.addItem("标题", "title")
        self.search_combo.addItem("艺术家", "artist")
        self.search_combo.addItem("专辑", "album")
        self.search_combo.setStyleSheet("QComboBox { padding: 4px 26px 4px 6px; font-size: 9pt; border: 1px solid #bdc3c7; border-radius: 4px; font-weight: bold; } QComboBox::drop-down { width: 26px; border: none; border-left: 1px solid #dcdde1; } QComboBox::down-arrow { image: none; }")
        self.search_combo.setFixedHeight(28)
        self._enable_touch_scrolling(self.search_combo.view())
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("在此检索本地单曲 (Enter 过滤)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("padding: 4px; font-size: 9pt; border: 1px solid #bdc3c7; border-radius: 4px;")
        self.search_input.setFixedHeight(28)
        
        self.search_input.returnPressed.connect(self.perform_local_search)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        
        search_bar_layout.addWidget(self.search_combo)
        search_bar_layout.addWidget(self.search_input, stretch=1)
        
        self.btn_group_album = QPushButton("🗜️ 编为临时专辑 / 撤销")
        self.btn_group_album.setStyleSheet("background-color: #f39c12; color: white; padding: 8px; font-size: 10pt; font-weight: bold; border-radius: 4px;")
        self.btn_group_album.clicked.connect(self.toggle_virtual_album_group)
        self.btn_find_incomplete = QPushButton("🔎 缺失首曲")
        self.btn_find_incomplete.setStyleSheet("background-color: #2980b9; color: white; padding: 8px; font-size: 10pt; font-weight: bold; border-radius: 4px;")
        self.btn_find_incomplete.setToolTip("定位当前列表中首个缺少必要元数据的曲目")
        self.btn_find_incomplete.clicked.connect(self.locate_first_incomplete_track)

        self.audio_player = AudioPlayerWidget()
        left_layout.addWidget(self.audio_player)
        album_action_layout = QHBoxLayout()
        album_action_layout.setContentsMargins(0, 0, 0, 0)
        album_action_layout.setSpacing(8)
        album_action_layout.addWidget(self.btn_group_album, stretch=2)
        album_action_layout.addWidget(self.btn_find_incomplete, stretch=1)
        left_layout.addLayout(album_action_layout)
        left_layout.addLayout(search_bar_layout)

        self.file_list = TouchSafeFileList()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.file_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.file_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.file_list.verticalScrollBar().setSingleStep(12)
        self.file_list.setViewportMargins(24, 0, 0, 0)
        self.file_list.setStyleSheet("QListWidget { border: 1px solid #bdc3c7; border-radius: 4px; padding: 5px; font-size: 10pt; }")
        self._enable_touch_scrolling(self.file_list)
        
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        self.file_list.itemClicked.connect(self.on_list_item_clicked)
        
        self.file_list_container = FileListOverlayContainer()
        file_list_layout = QVBoxLayout(self.file_list_container)
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        file_list_layout.setSpacing(0)
        file_list_layout.addWidget(self.file_list)
        self._create_album_index()
        left_layout.addWidget(self.file_list_container, stretch=1) 
        return left_widget

    def _build_editor_panels(self):
        forms_container = QWidget()
        forms_h_layout = QHBoxLayout(forms_container)
        forms_h_layout.setContentsMargins(15, 0, 0, 0)
        forms_h_layout.setSpacing(15)
        
        groupbox_style = "QGroupBox { font-weight: bold; color: #2980b9; border: 1px solid #bdc3c7; border-radius: 6px; margin-top: 10px; font-size: 10pt; } QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 5px; }"
        scroll_style = "QScrollArea { border: none; background: transparent; } QWidget#scroll_content { background: transparent; }"

        local_form_widget = self._build_local_editor_panel(groupbox_style, scroll_style)
        forms_h_layout.addWidget(local_form_widget, stretch=4)

        mb_form_widget = self._build_metadata_result_panel(groupbox_style, scroll_style)
        forms_h_layout.addWidget(mb_form_widget, stretch=5)
        return forms_container

    def _build_local_editor_panel(self, groupbox_style, scroll_style):
        local_form_widget = QGroupBox("💿 本地曲目元数据编辑")
        local_form_widget.setStyleSheet(groupbox_style)
        
        v_layout_local = QVBoxLayout(local_form_widget)
        v_layout_local.setContentsMargins(15, 10, 15, 15) 
        v_layout_local.setSpacing(10)
        
        middle_scroll = QScrollArea()
        middle_scroll.setWidgetResizable(True)
        middle_scroll.setStyleSheet(scroll_style)
        self._enable_touch_scrolling(middle_scroll)
        
        middle_content = QWidget()
        middle_content.setObjectName("scroll_content")
        middle_scroll_layout = QVBoxLayout(middle_content)
        middle_scroll_layout.setContentsMargins(0, 0, 0, 0)
        middle_scroll_layout.setSpacing(14) 
        
        # =========================================================
        # 精确到像素级的 UI 对齐设计：锁定顶部区域 185px 高度
        # =========================================================
        middle_scroll_layout.addWidget(self._build_cover_section())
        middle_scroll_layout.addWidget(self._build_filename_clue_row())
        middle_scroll_layout.addLayout(self._build_metadata_field_editor())
        middle_scroll_layout.addStretch()

        middle_scroll.setWidget(middle_content)
        v_layout_local.addWidget(middle_scroll)

        # 中间底部锁定 172px 强迫症高度
        v_layout_local.addWidget(self._build_editor_action_bar())
        return local_form_widget

    def _build_cover_section(self):
        cover_container = QWidget()
        cover_container.setFixedHeight(185) # 强锁定整体高度，保证起跑线一致
        cover_main_layout = QVBoxLayout(cover_container)
        cover_main_layout.setContentsMargins(0, 0, 0, 0)
        cover_main_layout.setSpacing(5)
        
        top_aligned_layout = QHBoxLayout()
        top_aligned_layout.setContentsMargins(0, 0, 0, 0)
        top_aligned_layout.setSpacing(10)
        
        self.cover_label = QLabel("无封面\n(支持 Ctrl+V)")
        self.cover_label.setFixedSize(160, 160) 
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 2px dashed #bdc3c7; background: #fafafa; color: #7f8c8d; font-weight: bold; border-radius: 4px;")
        self.cover_label.setToolTip("点击查看高清大图")
        self.cover_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover_label.mousePressEvent = self.open_current_cover
        
        top_aligned_layout.addWidget(self.cover_label)
        
        cover_mid_widget = QWidget()
        cover_mid_widget.setFixedHeight(160)
        cover_mid_layout = QVBoxLayout(cover_mid_widget)
        cover_mid_layout.setContentsMargins(0, 0, 0, 0)
        cover_mid_layout.setSpacing(10)
        
        cover_btn_style = "padding: 5px; font-size: 9pt; font-weight: bold; border: 1px solid #bdc3c7; border-radius: 4px; background-color: #f8f9fa;"
        
        row_paste_copy_widget = QWidget()
        row_paste_copy = QHBoxLayout(row_paste_copy_widget)
        row_paste_copy.setContentsMargins(0, 0, 0, 0)
        row_paste_copy.setSpacing(6)
        
        btn_paste = QPushButton("📋 粘贴封面")
        btn_paste.clicked.connect(self.paste_cover_from_clipboard)
        btn_paste.setStyleSheet(cover_btn_style)
        btn_paste.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        btn_paste.setMinimumWidth(50)
        
        btn_copy = QPushButton("💾 复制封面")
        btn_copy.clicked.connect(self.copy_cover_to_clipboard)
        btn_copy.setStyleSheet(cover_btn_style)
        btn_copy.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        btn_copy.setMinimumWidth(50)
        
        row_paste_copy.addWidget(btn_paste)
        row_paste_copy.addWidget(btn_copy)
        cover_mid_layout.addWidget(row_paste_copy_widget, stretch=1)
        
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)
        
        am_mb_layout = QVBoxLayout()
        am_mb_layout.setContentsMargins(0, 0, 0, 0)
        am_mb_layout.setSpacing(6)
        
        btn_am = QPushButton("🍎 搜 Apple Music")
        btn_am.clicked.connect(self.search_apple_music)
        btn_am.setStyleSheet(cover_btn_style)
        btn_am.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        btn_am.setMinimumWidth(50)
        
        btn_mb = QPushButton("🌍 搜 MB (网页)")
        btn_mb.clicked.connect(self.search_mb_album)
        btn_mb.setStyleSheet(cover_btn_style)
        btn_mb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        btn_mb.setMinimumWidth(50)
        
        am_mb_layout.addWidget(btn_am)
        am_mb_layout.addWidget(btn_mb)
        
        search_layout.addLayout(am_mb_layout, stretch=1)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet("color: #bdc3c7;")
        search_layout.addWidget(line)
        
        btn_both = QPushButton("同\n开")
        btn_both.setFixedWidth(24)
        btn_both.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        btn_both.setStyleSheet("font-size: 8pt; font-weight: bold; border: 1px solid #bdc3c7; border-radius: 4px; background-color: #ecf0f1; color: #2c3e50;")
        btn_both.clicked.connect(self.search_both)
        search_layout.addWidget(btn_both)
        
        cover_mid_layout.addSpacing(6)
        cover_mid_layout.addWidget(search_widget, stretch=2)
        top_aligned_layout.addWidget(cover_mid_widget, stretch=5)
        
        cover_right_widget = QWidget()
        cover_right_widget.setFixedHeight(160)
        cover_right_btn_layout = QHBoxLayout(cover_right_widget)
        cover_right_btn_layout.setContentsMargins(0, 0, 0, 0)
        cover_right_btn_layout.setSpacing(4)
        
        btn_auto_cover = QPushButton("🌐 智能自动搜图\n(双引擎画廊)")
        btn_auto_cover.clicked.connect(self.run_cover_fetch)
        btn_auto_cover.setStyleSheet("padding: 4px; font-size: 9pt; font-weight: bold; border: 1px solid #8e44ad; border-radius: 4px; background-color: #f5eef8; color: #8e44ad;")
        btn_auto_cover.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        btn_auto_cover.setMinimumWidth(60) 
        self._search_buttons.append(btn_auto_cover)
        
        self.btn_cover_debug = QPushButton("🐞\n调\n试")
        self.btn_cover_debug.clicked.connect(self.show_cover_debug)
        self.btn_cover_debug.setStyleSheet("padding: 2px; font-size: 8pt; font-weight: bold; border: 1px solid #e67e22; border-radius: 4px; background-color: #fdf3e7; color: #d35400;")
        self.btn_cover_debug.setFixedSize(28, 160)
        
        cover_right_btn_layout.addWidget(btn_auto_cover, stretch=1)
        cover_right_btn_layout.addWidget(self.btn_cover_debug)
        
        top_aligned_layout.addWidget(cover_right_widget, stretch=3)
        cover_main_layout.addLayout(top_aligned_layout)
        
        res_layout = QHBoxLayout()
        res_layout.setContentsMargins(0, 0, 0, 0)
        self.resolution_label = QLabel("分辨率: -")
        self.resolution_label.setFixedSize(160, 20) # 强制给文本框高度，完成数学计算
        self.resolution_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.resolution_label.setStyleSheet("color: #7f8c8d; font-size: 8pt;")
        res_layout.addWidget(self.resolution_label)
        res_layout.addStretch() 
        cover_main_layout.addLayout(res_layout)
        
        return cover_container

    def _build_filename_clue_row(self):
        container = QWidget()
        container.setFixedHeight(34)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_filename_clue = QPushButton("从文件名提取线索")
        self.btn_filename_clue.setFixedHeight(30)
        self.btn_filename_clue.setStyleSheet(
            "QPushButton { padding: 4px 10px; font-size: 9pt; font-weight: bold; "
            "border: 1px solid #bdc3c7; border-radius: 4px; "
            "background-color: #f8f9fa; color: #2c3e50; } "
            "QPushButton:disabled { color: #95a5a6; background-color: #f4f6f7; }"
        )
        self.btn_filename_clue.clicked.connect(self.start_filename_clue_analysis)
        layout.addWidget(self.btn_filename_clue)

        self.filename_clue_status_label = QLabel("")
        self.filename_clue_status_label.setFixedHeight(30)
        self.filename_clue_status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self.filename_clue_status_label, stretch=1)
        return container

    def _build_metadata_field_editor(self):
        local_form_layout = QVBoxLayout()
        local_form_layout.setSpacing(12)
        
        for key, label_text, default_checked in self.field_configs:
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            
            left_col = QWidget()
            left_col.setMinimumWidth(160) 
            left_col.setMaximumWidth(200)
            left_col_layout = QHBoxLayout(left_col)
            left_col_layout.setContentsMargins(0, 0, 0, 0)
            left_col_layout.setSpacing(4)
            
            btn_lock = QPushButton("🔓")
            btn_lock.setFixedSize(26, 26)
            btn_lock.setStyleSheet("QPushButton { border: none; background: transparent; font-size: 12pt; }")
            btn_lock.setCheckable(True)
            btn_lock.toggled.connect(lambda checked, k=key: self.toggle_lock(k, checked))
            self.lock_btns[key] = btn_lock
            
            chk = QCheckBox(label_text)
            chk.setChecked(default_checked)
            chk.setStyleSheet("font-size: 10pt; font-weight: bold; color: #2c3e50;")
            self.checkboxes[key] = chk
            
            left_col_layout.addWidget(btn_lock)
            left_col_layout.addWidget(chk)
            left_col_layout.addStretch()
            row_layout.addWidget(left_col)
            
            cb = TouchComboBox()
            cb.setEditable(True)
            cb.setCompleter(None)
            cb.lineEdit().setClearButtonEnabled(True)
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(5)
            cb.setStyleSheet(self.cb_style_normal)
            cb.setFixedHeight(32) 
            self._enable_touch_scrolling(cb.view())
            self.inputs[key] = cb
            
            input_container = QHBoxLayout()
            input_container.setContentsMargins(0, 0, 0, 0)
            input_container.addWidget(cb, stretch=1)
            
            if key in ["artist", "album"]:
                cb.setPlaceholderText("用 \\\\ 分隔" if key=="artist" else "")
            elif key in ["album_artist", "composer"]:
                cb.setPlaceholderText("多位人员请用 \\\\ 分隔")
            elif key == "genre":
                warn = QLabel("(不推荐勾选)")
                warn.setStyleSheet("color: #e74c3c; font-size: 8pt; margin-left: 5px;")
                input_container.addWidget(warn)
                
            row_layout.addLayout(input_container, stretch=1)
            
            right_col = QWidget()
            right_col.setFixedWidth(70)
            right_col_layout = QHBoxLayout(right_col)
            right_col_layout.setContentsMargins(0, 0, 0, 0)
            if key in ["artist", "album"]:
                c_btn = QPushButton("搜 MB")
                c_btn.setFixedSize(70, 32)
                c_btn.setStyleSheet("padding: 4px; font-weight: bold; border-radius: 4px; border: 1px solid #bdc3c7; background-color: #ecf0f1; font-size: 9pt;")
                cb_callback = self.search_mb_artist if key=="artist" else self.search_mb_album
                c_btn.clicked.connect(cb_callback)
                right_col_layout.addWidget(c_btn)
            row_layout.addWidget(right_col)
            
            local_form_layout.addLayout(row_layout)
            
        mbid_row = QHBoxLayout()
        mbid_row.setContentsMargins(0, 0, 0, 0)
        mbid_row.setSpacing(8)
        lbl_mbid = QLabel("🎯 指定 MBID")
        lbl_mbid.setFixedWidth(170)
        lbl_mbid.setStyleSheet("color: #8e44ad; font-weight: bold; font-size: 10pt; padding-left: 35px;")
        mbid_row.addWidget(lbl_mbid)
        
        self.input_mbid = QLineEdit()
        self.input_mbid.setPlaceholderText("粘贴网址或ID强制抓取 (如: 8b0afd0f-c578-...)")
        self.input_mbid.setStyleSheet("padding: 6px; font-size: 10pt; border: 1px solid #bdc3c7; border-radius: 4px;")
        self.input_mbid.setFixedHeight(32)
        self.input_mbid.setClearButtonEnabled(True)
        mbid_row.addWidget(self.input_mbid, stretch=1)
        
        self.btn_paste_mbid = QPushButton("📋 粘贴")
        self.btn_paste_mbid.setFixedSize(70, 32)
        self.btn_paste_mbid.setStyleSheet("padding: 4px; font-weight: bold; border-radius: 4px; border: 1px solid #bdc3c7; background-color: #ecf0f1; font-size: 9pt;")
        self.btn_paste_mbid.clicked.connect(self.paste_mbid)
        
        mbid_right = QWidget()
        mbid_right.setFixedWidth(70)
        mbid_right_layout = QHBoxLayout(mbid_right)
        mbid_right_layout.setContentsMargins(0, 0, 0, 0)
        mbid_right_layout.addWidget(self.btn_paste_mbid)
        mbid_row.addWidget(mbid_right)

        local_form_layout.addLayout(mbid_row)

        apple_id_row = QHBoxLayout()
        apple_id_row.setContentsMargins(0, 0, 0, 0)
        apple_id_row.setSpacing(8)
        lbl_apple_id = QLabel("🍎 指定 Apple 专辑 ID")
        lbl_apple_id.setFixedWidth(170)
        lbl_apple_id.setStyleSheet("color: #c0392b; font-weight: bold; font-size: 10pt; padding-left: 35px;")
        apple_id_row.addWidget(lbl_apple_id)

        self.input_apple_collection_id = QLineEdit()
        self.input_apple_collection_id.setPlaceholderText("粘贴专辑网址或数字 ID (如: .../album/.../1486746625)")
        self.input_apple_collection_id.setStyleSheet("padding: 6px; font-size: 10pt; border: 1px solid #bdc3c7; border-radius: 4px;")
        self.input_apple_collection_id.setFixedHeight(32)
        self.input_apple_collection_id.setClearButtonEnabled(True)
        self.input_apple_collection_id.editingFinished.connect(self.normalize_apple_collection_id_input)
        apple_id_row.addWidget(self.input_apple_collection_id, stretch=1)

        btn_paste_apple_id = QPushButton("📋 粘贴")
        btn_paste_apple_id.setFixedSize(70, 32)
        btn_paste_apple_id.setStyleSheet("padding: 4px; font-weight: bold; border-radius: 4px; border: 1px solid #bdc3c7; background-color: #ecf0f1; font-size: 9pt;")
        btn_paste_apple_id.clicked.connect(self.paste_apple_collection_id)
        apple_id_right = QWidget()
        apple_id_right.setFixedWidth(70)
        apple_id_right_layout = QHBoxLayout(apple_id_right)
        apple_id_right_layout.setContentsMargins(0, 0, 0, 0)
        apple_id_right_layout.addWidget(btn_paste_apple_id)
        apple_id_row.addWidget(apple_id_right)
        local_form_layout.addLayout(apple_id_row)
        
        mbid_opt_row = QHBoxLayout()
        mbid_opt_row.setContentsMargins(0, 0, 0, 0)
        mbid_opt_row.setSpacing(8)
        mbid_opt_row.addSpacing(178) 
        
        self.chk_auto_clear_mbid = QCheckBox("切换至新专辑时自动清除指定 ID")
        self.chk_auto_clear_mbid.setChecked(True)
        self.chk_auto_clear_mbid.setFixedHeight(20)
        self.chk_auto_clear_mbid.setStyleSheet("font-size: 9pt; font-weight: bold; color: #7f8c8d;")
        mbid_opt_row.addWidget(self.chk_auto_clear_mbid)
        mbid_opt_row.addStretch()
        
        local_form_layout.addLayout(mbid_opt_row)
        
        return local_form_layout

    def _build_editor_action_bar(self):
        bottom_container = QWidget()
        bottom_container.setFixedHeight(172)
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(12, 12, 12, 12) 
        bottom_layout.setSpacing(12) 
        bottom_container.setStyleSheet("background-color: #f4f6f7; border-radius: 6px; border: 1px solid #dcdde1;")
        
        top_fetch_row = QHBoxLayout()
        self.btn_fetch_auto = QPushButton("🤖 API 智能提取对比 | Shift+Enter")
        self.btn_fetch_auto.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; font-size: 11pt; padding: 0 12px; border-radius: 4px;")
        self.btn_fetch_auto.setFixedHeight(46)
        self.btn_fetch_auto.clicked.connect(lambda: self.do_fetch("auto"))
        self._search_buttons.append(self.btn_fetch_auto)
        top_fetch_row.addWidget(self.btn_fetch_auto, stretch=1)
        
        self.chk_no_cache = QCheckBox("🔴 禁用缓存 (强制网络请求)")
        self.chk_no_cache.setStyleSheet("font-size: 9pt; font-weight: bold; color: #c0392b; margin-left: 10px;")
        self.chk_no_cache.setToolTip("选中后，将无视本地内存缓存，对该歌曲执行全新的、彻底的网络请求。")
        top_fetch_row.addWidget(self.chk_no_cache)
        
        bottom_layout.addLayout(top_fetch_row)

        sub_api_layout = QHBoxLayout()
        sub_api_layout.setSpacing(10)
        for txt, mode in [("🔍 搜: 专辑", "only_album"), ("🔍 搜: 标题+专辑", "album"), ("🔍 搜: 标题", "title")]:
            b = QPushButton(txt)
            b.setStyleSheet("padding: 0 8px; border-radius: 4px; border: 1px solid #bdc3c7; background-color: #ecf0f1; font-size: 9pt; font-weight: bold;")
            b.setFixedHeight(36)
            b.clicked.connect(lambda chk, m=mode: self.do_fetch(m))
            self._search_buttons.append(b)
            sub_api_layout.addWidget(b)
            
        self.btn_api_debug = QPushButton("🐞 元数据调试流")
        self.btn_api_debug.setStyleSheet("padding: 0 8px; border-radius: 4px; border: 1px solid #e67e22; background-color: #fdf3e7; color: #d35400; font-size: 9pt; font-weight: bold;")
        self.btn_api_debug.setFixedHeight(36)
        self.btn_api_debug.clicked.connect(self.show_api_debug)
        sub_api_layout.addWidget(self.btn_api_debug)
        bottom_layout.addLayout(sub_api_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.btn_skip = QPushButton("⏭️ 跳过 | Ctrl+Enter")
        self.btn_skip.clicked.connect(self.skip_current_files)
        self.btn_skip.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 0 12px; font-size: 10pt; border-radius: 4px;")
        self.btn_skip.setFixedHeight(42)

        self.btn_save_apply = QPushButton("💾 应用勾选数据并保存 | Enter")
        self.btn_save_apply.clicked.connect(self.save_current_files)
        self.btn_save_apply.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 0 12px; font-size: 10pt; border-radius: 4px;")
        self.btn_save_apply.setFixedHeight(42)

        self.btn_save_only = QPushButton("📌 仅保存左侧并停留")
        self.btn_save_only.clicked.connect(self.save_left_only_and_stay)
        self.btn_save_only.setStyleSheet("background-color: #8e44ad; color: white; font-weight: bold; padding: 0 12px; font-size: 10pt; border-radius: 4px;")
        self.btn_save_only.setFixedHeight(42)

        btn_layout.addWidget(self.btn_skip)
        btn_layout.addWidget(self.btn_save_apply)
        btn_layout.addWidget(self.btn_save_only)
        bottom_layout.addLayout(btn_layout)
        
        return bottom_container

    def _build_metadata_result_panel(self, groupbox_style, scroll_style):
        mb_form_widget = QGroupBox("🔍 多信息源提取结果对比 (只读)")
        mb_form_widget.setStyleSheet(groupbox_style)
        v_layout_mb = QVBoxLayout(mb_form_widget)
        v_layout_mb.setContentsMargins(15, 10, 15, 15) 
        
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setStyleSheet(scroll_style)
        self._enable_touch_scrolling(right_scroll)
        self.metadata_result_scroll = right_scroll
        
        right_content = QWidget()
        right_content.setObjectName("scroll_content")
        right_scroll_layout = QVBoxLayout(right_content)
        right_scroll_layout.setContentsMargins(0, 0, 0, 0)
        right_scroll_layout.setSpacing(14)
        
        # 强制顶盖对齐中间封面 185px 高度
        status_container = QWidget()
        status_container.setFixedHeight(185)
        status_layout = QVBoxLayout(status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.mb_status_label = QLabel("等待提取...")
        self.mb_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mb_status_label.setWordWrap(True)
        self.mb_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.mb_status_label.setMinimumWidth(0)
        self.mb_status_label.setStyleSheet("color: #7f8c8d; font-size: 12pt; font-weight: bold; padding: 5px;")
        self.mb_score_label = QLabel("")
        self.mb_score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mb_score_label.setWordWrap(True)
        self.mb_score_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.mb_score_label.setMinimumWidth(0)
        self.mb_score_label.setStyleSheet("color: #8e44ad; font-size: 10pt; font-weight: bold;")

        source_buttons = QHBoxLayout()
        source_buttons.setSpacing(8)
        self.btn_use_mb_source = QPushButton("采用 MusicBrainz")
        self.btn_use_apple_source = QPushButton("采用 Apple Music")
        for button, color in ((self.btn_use_mb_source, "#5b7db1"), (self.btn_use_apple_source, "#555555")):
            button.setEnabled(False)
            button.setFixedHeight(30)
            button.setStyleSheet(f"QPushButton {{ padding: 4px 8px; font-size: 9pt; font-weight: bold; color: white; background: {color}; border-radius: 4px; }} QPushButton:disabled {{ background: #bdc3c7; }}")
            source_buttons.addWidget(button)
        self.btn_use_mb_source.clicked.connect(lambda: self.select_metadata_source("MusicBrainz"))
        self.btn_use_apple_source.clicked.connect(lambda: self.select_metadata_source("Apple Music"))

        status_layout.addStretch()
        status_layout.addWidget(self.mb_status_label)
        status_layout.addWidget(self.mb_score_label)
        status_layout.addLayout(source_buttons)
        status_layout.addStretch()
        right_scroll_layout.addWidget(status_container)
        
        # 【修正】统一右侧布局行间距为 12，消除瀑布流错位偏差
        mb_inner_layout = QVBoxLayout()
        mb_inner_layout.setSpacing(12) 
        
        for key, label_text, _ in self.field_configs:
            r_row = QHBoxLayout()
            r_row.setContentsMargins(0, 0, 0, 0)
            r_row.setSpacing(8)
            
            lbl = QLabel(label_text)
            lbl.setFixedWidth(170)
            lbl.setStyleSheet("font-size: 10pt; font-weight: bold; color: #2c3e50; padding-left: 10px;")
            r_row.addWidget(lbl)
            self.mb_labels[key] = lbl 
            
            le = QLineEdit()
            le.setReadOnly(True)
            le.setCursorPosition(0)
            le.setFixedHeight(32)
            le.setStyleSheet("QLineEdit { background-color: #ecf0f1; color: #34495e; padding: 6px; font-size: 10pt; border: 1px solid #dcdde1; border-radius: 4px; }")
            self.mb_inputs[key] = le
            
            le_container = QHBoxLayout()
            le_container.setContentsMargins(0, 0, 0, 0)
            le_container.addWidget(le, stretch=1)
                
            r_row.addLayout(le_container, stretch=1)
            
            r_btn = QPushButton("⬅️ 应用")
            r_btn.setFixedSize(70, 32)
            r_btn.setStyleSheet("padding: 4px; font-weight: bold; background-color: #3498db; color: white; border-radius: 4px; font-size: 10pt;")
            r_btn.clicked.connect(lambda checked, k=key: self.apply_mb_field(k))
            self.mb_apply_btns[key] = r_btn
            r_row.addWidget(r_btn)
            
            mb_inner_layout.addLayout(r_row)
            
        right_scroll_layout.addLayout(mb_inner_layout)
        
        # Account for both explicit ID rows and the auto-clear option on the left.
        align_spacer = QWidget()
        align_spacer.setFixedHeight(212)
        right_scroll_layout.addWidget(align_spacer)
        
        right_scroll_layout.addStretch()
        
        right_scroll.setWidget(right_content)
        v_layout_mb.addWidget(right_scroll)
        
        # 右侧底部锁定 70px 强迫症高度
        right_bottom_container = QWidget()
        right_bottom_container.setFixedHeight(70)
        right_bottom_layout = QVBoxLayout(right_bottom_container)
        right_bottom_layout.setContentsMargins(12, 12, 12, 12) 
        right_bottom_layout.setSpacing(12)
        
        btn_apply_all = QPushButton("⬅️ 全部应用 (覆盖左侧未锁定的项)")
        btn_apply_all.setStyleSheet("background-color: #34495e; color: white; font-weight: bold; padding: 12px; font-size: 11pt; border-radius: 6px;")
        btn_apply_all.setFixedHeight(46)
        btn_apply_all.clicked.connect(self.apply_all_mb_fields)
        right_bottom_layout.addWidget(btn_apply_all)
        
        v_layout_mb.addWidget(right_bottom_container)

        return mb_form_widget

    @staticmethod
    def _enable_touch_scrolling(scroll_area):
        if hasattr(scroll_area, "setVerticalScrollMode"):
            scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        else:
            scroll_area.verticalScrollBar().setSingleStep(12)
            scroll_area.horizontalScrollBar().setSingleStep(12)
        QScroller.grabGesture(scroll_area.viewport(), QScroller.ScrollerGestureType.TouchGesture)

    def on_list_item_clicked(self, item):
        if item.data(Qt.ItemDataRole.UserRole + 2) == "header":
            header_id = item.data(Qt.ItemDataRole.UserRole + 3)
            modifiers = QApplication.keyboardModifiers()
            
            self.file_list.blockSignals(True)
            if not (modifiers & Qt.KeyboardModifier.ControlModifier):
                self.file_list.clearSelection()
                
            for i in range(self.file_list.count()):
                child = self.file_list.item(i)
                if (
                    child.data(Qt.ItemDataRole.UserRole + 2) == "track"
                    and not child.isHidden()
                    and child.data(Qt.ItemDataRole.UserRole + 3) == header_id
                ):
                    child.setSelected(True)
                    
            item.setSelected(False) 
            
            self.file_list.blockSignals(False)
            self.on_file_selected() 

    def on_search_text_changed(self, text):
        if not text.strip():
            self._search_restore_timer.start()
        else:
            self._search_restore_timer.stop()

    def _create_album_index(self):
        self.album_index_targets = {}
        self.album_index_hover_timer = QTimer(self)
        self.album_index_hover_timer.setSingleShot(True)
        self.album_index_hover_timer.timeout.connect(self._scroll_to_pending_album_initial)
        self._pending_album_index_letter = ""
        self.album_index = QWidget(self.file_list_container)
        self.album_index.setObjectName("album_index")
        self.album_index.setFixedWidth(22)
        self.album_index.setStyleSheet(
            "QWidget#album_index { background-color: rgba(255, 255, 255, 218); "
            "border-right: 1px solid #dcdde1; }"
        )
        index_layout = QVBoxLayout(self.album_index)
        index_layout.setContentsMargins(0, 0, 0, 0)
        index_layout.setSpacing(0)
        self.album_index_letters = {}
        for letter in "#ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            index_letter = AlbumIndexLetter(letter, self.album_index)
            index_letter.hovered.connect(self.schedule_album_index_scroll)
            index_letter.hover_left.connect(self.cancel_album_index_scroll)
            index_layout.addWidget(index_letter, stretch=1)
            self.album_index_letters[letter] = index_letter

        self.file_list_container.resized.connect(self._position_album_index)
        self.album_index.hide()

    def _position_album_index(self):
        if not hasattr(self, "album_index") or getattr(self, "_is_positioning_album_index", False):
            return
        self._is_positioning_album_index = True
        try:
            viewport_rect = self.file_list.viewport().geometry()
            list_rect = self.file_list.geometry()
            self.album_index.setGeometry(
                list_rect.x() + self.file_list.frameWidth() + 1,
                list_rect.y() + viewport_rect.y(),
                self.album_index.width(),
                viewport_rect.height(),
            )
        finally:
            self._is_positioning_album_index = False

    def _update_album_index(self):
        if not hasattr(self, "album_index_letters"):
            return
        for letter, index_letter in self.album_index_letters.items():
            index_letter.set_available(letter in self.album_index_targets)
        self.album_index.setVisible(bool(self.album_index_targets))
        self._position_album_index()
        QTimer.singleShot(0, self._position_album_index)

    def scroll_to_album_initial(self, letter):
        target = self.album_index_targets.get(letter)
        if target:
            self.file_list.smooth_scroll_to_item(target, QAbstractItemView.ScrollHint.PositionAtTop)

    def schedule_album_index_scroll(self, letter):
        self._pending_album_index_letter = letter
        self.album_index_hover_timer.start(180)

    def cancel_album_index_scroll(self, letter):
        if self._pending_album_index_letter == letter:
            self.album_index_hover_timer.stop()
            self._pending_album_index_letter = ""

    def _scroll_to_pending_album_initial(self):
        letter = self._pending_album_index_letter
        self._pending_album_index_letter = ""
        if letter:
            self.scroll_to_album_initial(letter)

    def perform_local_search(self):
        self._search_restore_timer.stop()
        query = self.search_input.text().strip().lower()
        if not query:
            self.restore_full_list()
            return

        if not self._local_search_active:
            self._search_selection_before_filter = self._selected_track_paths()
            self._local_search_active = True
        search_type = self.search_combo.currentData()
        visible_paths = set()
        for item_data, f_path in getattr(self, "full_sortable_list", []):
            data = self.album_session.all_files_data.get(f_path, {})
            val = str(data.get(search_type, "")).lower()
            if query in val:
                visible_paths.add(f_path)
        self._set_search_visibility(visible_paths)
        self.on_file_selected()

    def restore_full_list(self):
        self._search_restore_timer.stop()
        if not hasattr(self, "full_sortable_list") or not self._local_search_active:
            return
        self._restore_search_visibility()
        selected_paths = self._search_selection_before_filter
        self.file_list.blockSignals(True)
        try:
            self.file_list.clearSelection()
            current = None
            for path in selected_paths:
                item = self._track_item_cache.get(path)
                if item and self.file_list.row(item) >= 0:
                    item.setSelected(True)
                    current = current or item
            if current:
                self.file_list.setCurrentItem(current)
        finally:
            self.file_list.blockSignals(False)
        self._local_search_active = False
        self._search_selection_before_filter = set()
        if current:
            self.file_list.smooth_scroll_to_item(current, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.on_file_selected()

    def _restore_search_visibility(self):
        """Unhide only items hidden by the active filter."""
        self.file_list.blockSignals(True)
        self.file_list.setUpdatesEnabled(False)
        try:
            for path in self._search_hidden_paths:
                item = self._track_item_cache.get(path)
                if item and self.file_list.row(item) >= 0:
                    item.setHidden(False)
            for header_id in self._search_hidden_headers:
                item = self._header_item_cache.get(header_id)
                if item and self.file_list.row(item) >= 0:
                    item.setHidden(False)
            self._search_hidden_paths = set()
            self._search_hidden_headers = set()
            self.album_index_targets = {}
            for item in self._header_item_cache.values():
                if self.file_list.row(item) < 0 or item.isHidden():
                    continue
                initial = album_initial(item.data(Qt.ItemDataRole.UserRole + 5))
                if initial and initial not in self.album_index_targets:
                    self.album_index_targets[initial] = item
        finally:
            self.file_list.setUpdatesEnabled(True)
            self.file_list.blockSignals(False)
        self._update_album_index()

    def populate_file_list(self, data_list):
        self._rebuild_file_list(data_list)

    def _rebuild_file_list(self, data_list):
        """Reorder reusable list items while suppressing intermediate paints."""
        selected_paths = self._selected_track_paths()
        current_item = self.file_list.currentItem()
        current_path = self._item_path(current_item) if current_item else None
        self.file_list.cancel_smooth_scroll()
        self.file_list.blockSignals(True)
        self.file_list.setUpdatesEnabled(False)
        try:
            while self.file_list.count():
                self.file_list.takeItem(0)
            self.album_index_targets = {}

            group_sort_keys = {}

            def group_sort_key(group_id):
                if group_id not in group_sort_keys:
                    anchor_path = self.album_session.virtual_album_anchors.get(group_id)
                    anchor_album, anchor_cover = self._physical_album_key(anchor_path)
                    group_sort_keys[group_id] = (
                        *album_navigation_sort_key(anchor_album),
                        anchor_cover,
                    )
                return group_sort_keys[group_id]

            sorted_data_list = sorted(data_list, key=self._effective_sort_key(group_sort_key))
            current_header_id = None
            for item_data, f_path in sorted_data_list:
                group_id = self.album_session.virtual_album_map.get(f_path)
                orig_album = str(item_data[0]).strip()
                current_album = str(
                    self.album_session.all_files_data.get(f_path, {}).get("album", "")
                ).strip()
                if group_id:
                    display_album = f"临时编组 💽{group_id}"
                    header_id = f"virtual_{group_id}"
                    anchor_path = self.album_session.virtual_album_anchors.get(group_id)
                    index_album_name = self.album_session.all_files_data.get(anchor_path, {}).get("album", "") or orig_album
                else:
                    display_album = current_album or orig_album or "未知专辑"
                    album_sort_key, cover_sort_key = self._physical_album_key(f_path)
                    header_id = f"album_{album_sort_key}_{cover_sort_key}"
                    index_album_name = current_album or orig_album

                if header_id != current_header_id:
                    current_header_id = header_id
                    header_item = self._header_item(
                        header_id,
                        display_album,
                        index_album_name,
                        mark_modified=f_path in self._session_modified_album_paths,
                    )
                    self.file_list.addItem(header_item)
                    initial = album_initial(index_album_name)
                    if initial and initial not in self.album_index_targets:
                        self.album_index_targets[initial] = header_item

                item = self._track_item(f_path)
                item.setData(Qt.ItemDataRole.UserRole + 3, header_id)
                self.file_list.addItem(item)

            self._restore_list_selection(selected_paths, current_path)
            self.update_list_display()
        finally:
            self.file_list.setUpdatesEnabled(True)
            self.file_list.blockSignals(False)
        if self.search_input.text().strip():
            self._set_search_visibility(self._matching_search_paths())
        else:
            self._update_album_index()

    def _effective_sort_key(self, group_sort_key):
        def get_effective_sort_key(item_tuple):
            item_data, f_path = item_tuple
            group_id = self.album_session.virtual_album_map.get(f_path)
            album_sort_key, cover_sort_key = self._physical_album_key(f_path)
            stable_album_sort_key = (
                item_data[0]
                if f_path in self._session_modified_album_paths
                else album_sort_key
            )
            album_initial_rank, album_name_sort_key = album_navigation_sort_key(
                stable_album_sort_key
            )
            if group_id:
                anchor_initial_rank, anchor_name_sort_key, anchor_cover = group_sort_key(group_id)
                return (
                    anchor_initial_rank,
                    anchor_name_sort_key,
                    anchor_cover or cover_sort_key,
                    1,
                    group_id,
                    item_data[1],
                    item_data[2],
                    os.path.basename(f_path),
                )
            return (
                album_initial_rank,
                album_name_sort_key,
                cover_sort_key,
                0,
                0,
                item_data[1],
                item_data[2],
                os.path.basename(f_path),
            )
        return get_effective_sort_key

    def _header_item(
        self, header_id, display_album, index_album_name, mark_modified=False
    ):
        item = self._header_item_cache.get(header_id)
        if item is None:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            item.setForeground(QColor("#7f8c8d"))
            item.setBackground(QColor("#f4f6f7"))
            font = item.font()
            font.setPointSize(9)
            font.setBold(True)
            item.setFont(font)
            item.setData(Qt.ItemDataRole.UserRole + 2, "header")
            self._header_item_cache[header_id] = item
        item.setText(f"💿 {display_album}")
        item.setData(Qt.ItemDataRole.UserRole + 3, header_id)
        item.setData(Qt.ItemDataRole.UserRole + 5, index_album_name)
        item.setData(Qt.ItemDataRole.UserRole + 6, mark_modified)
        item.setForeground(QColor("#8e44ad" if mark_modified else "#7f8c8d"))
        item.setToolTip(
            "专辑名称已修改；本次会话保持原列表位置。"
            if mark_modified else ""
        )
        return item

    def _track_item(self, path):
        item = self._track_item_cache.get(path)
        if item is None:
            base_name = os.path.basename(path)
            item = QListWidgetItem(f"   {base_name}")
            item.setData(Qt.ItemDataRole.UserRole, base_name)
            item.setData(Qt.ItemDataRole.UserRole + 2, "track")
            item.setData(Qt.ItemDataRole.UserRole + 4, path)
            item.setToolTip(base_name)
            self._track_item_cache[path] = item
        return item

    def _item_path(self, item):
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole + 4) or os.path.join(
            self.music_dir, self.get_real_filename(item)
        )

    def _selected_track_paths(self):
        return {
            self._item_path(item)
            for item in self.file_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole + 2) == "track"
        }

    def _restore_list_selection(self, selected_paths, current_path):
        current_item = None
        for path, item in self._track_item_cache.items():
            if self.file_list.row(item) < 0:
                continue
            item.setSelected(path in selected_paths)
            if path == current_path:
                current_item = item
        if current_item:
            self.file_list.setCurrentItem(current_item)

    def _matching_search_paths(self):
        query = self.search_input.text().strip().lower()
        if not query:
            return set(self.album_session.all_files_data)
        search_type = self.search_combo.currentData()
        return {
            path for _, path in getattr(self, "full_sortable_list", [])
            if query in str(self.album_session.all_files_data.get(path, {}).get(search_type, "")).lower()
        }

    def _set_search_visibility(self, visible_paths):
        selected_visible_paths = {
            path for path in self._selected_track_paths() if path in visible_paths
        }
        current_item = self.file_list.currentItem()
        current_path = self._item_path(current_item) if current_item else None
        self.file_list.blockSignals(True)
        self.file_list.setUpdatesEnabled(False)
        try:
            self.file_list.clearSelection()
            headers_with_tracks = set()
            for path, item in self._track_item_cache.items():
                is_visible = path in visible_paths and self.file_list.row(item) >= 0
                item.setHidden(not is_visible)
                if self.file_list.row(item) >= 0 and not is_visible:
                    self._search_hidden_paths.add(path)
                else:
                    self._search_hidden_paths.discard(path)
                if is_visible:
                    headers_with_tracks.add(item.data(Qt.ItemDataRole.UserRole + 3))
            self.album_index_targets = {}
            for header_id, item in self._header_item_cache.items():
                is_visible = header_id in headers_with_tracks and self.file_list.row(item) >= 0
                item.setHidden(not is_visible)
                if self.file_list.row(item) >= 0 and not is_visible:
                    self._search_hidden_headers.add(header_id)
                else:
                    self._search_hidden_headers.discard(header_id)
                if is_visible:
                    initial = album_initial(item.data(Qt.ItemDataRole.UserRole + 5))
                    if initial and initial not in self.album_index_targets:
                        self.album_index_targets[initial] = item
            for path in selected_visible_paths:
                item = self._track_item_cache.get(path)
                if item and not item.isHidden():
                    item.setSelected(True)
            if current_path in selected_visible_paths:
                self.file_list.setCurrentItem(self._track_item_cache[current_path])
            elif current_item and current_item.isHidden():
                self.file_list.setCurrentItem(None)
        finally:
            self.file_list.setUpdatesEnabled(True)
            self.file_list.blockSignals(False)
        self._update_album_index()

    def refresh_list_items(self):
        self._rebuild_file_list(getattr(self, "full_sortable_list", []))
        self.on_file_selected()

    def show_cover_debug(self):
        if not hasattr(self, 'last_cover_raw_json_list') or not self.last_cover_raw_json_list:
            QMessageBox.information(self, "提示", "暂无封面抓取记录。请先点击执行一次【智能自动搜图】！")
            return
            
        dlg = DebugDialog(
            self.last_cover_raw_json_list, self, log_prefix="cover-search"
        )
        dlg.setWindowTitle("🐞 智能封面画廊 (Apple Music / MusicBrainz) API 通讯底层追踪")
        dlg.exec()
        
    def show_api_debug(self):
        dlg = DebugDialog(self.last_api_raw_json_list, self)
        dlg.exec()

    def run_cover_fetch(self):
        if (
            self._save_in_progress
            or self._undo_in_progress
            or self.is_metadata_search_running()
            or self.is_cover_search_running()
            or self.is_filename_clue_analysis_running()
        ):
            return
        items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        if not items: return
        path = os.path.join(self.music_dir, self.get_real_filename(items[0]))
        
        artist = self.inputs["artist"].currentText().split("\\\\")[0].strip()
        album = self.inputs["album"].currentText().strip()
        
        if album in ["", "<保留>", "<留白>"]:
            QMessageBox.warning(self, "缺少线索", "请先在左侧确保【专辑】和【艺术家】名称已被提取，再进行智能搜图！")
            return
            
        release_id = ""
        apple_cover_data = {}
        if path in self.api_cache:
            api_data = self.api_cache[path].get("api_data", {})
            source_results = api_data.get("source_results", {})
            release_id = source_results.get("MusicBrainz", {}).get("release_id", "") or api_data.get("release_id", "")
            apple_cover_data = source_results.get("Apple Music", {})
            if not apple_cover_data and api_data.get("metadata_source") == "Apple Music":
                apple_cover_data = api_data
            
        if not release_id:
            self.mb_status_label.setText("⏳ 正在自动补全专辑 MBID 前置信息...")
            self.pending_cover_fetch = True 
            self.do_fetch("auto", is_auto=True) 
        else:
            self._start_cover_fetch_worker(artist, album, release_id, apple_cover_data)

    def _start_cover_fetch_worker(self, artist, album, release_id, apple_cover_data=None):
        if self.is_cover_search_running():
            return
        self.overlay.start()
        self.mb_status_label.setText("🚀 正在全网检索并下载极清封面资源...")
        apple_cover_data = apple_cover_data or {}
        self._cover_search_generation += 1
        request_id = self._cover_search_generation
        self._active_cover_search_id = request_id
        self.cover_worker = CoverFetchWorker(
            artist,
            album,
            release_id,
            apple_cover_data.get("apple_artwork_url", ""),
            apple_cover_data.get("apple_storefront", ""),
            request_id=request_id,
            cancel_event=threading.Event(),
        )
        self.cover_worker.progress_sig.connect(self.update_fetch_progress)
        self.cover_worker.finished_sig.connect(self.on_cover_fetch_finished)
        self.cover_worker.finished.connect(self._cleanup_cover_worker)
        self.cover_worker.start()
        
    def on_cover_fetch_finished(self, results, stats, raw_json_list, request_id, cancelled):
        if request_id != self._active_cover_search_id:
            self._cancelled_cover_search_ids.discard(request_id)
            return
        was_cancelled = request_id in self._cancelled_cover_search_ids
        if request_id == self._active_cover_search_id:
            self._active_cover_search_id = None
        self._cancelled_cover_search_ids.discard(request_id)
        if cancelled or was_cancelled:
            self.pending_cover_fetch = False
            for button in self._search_buttons:
                button.setEnabled(True)
            self.mb_status_label.setText("封面搜索已取消")
            self.mb_status_label.setStyleSheet("color: #7f8c8d; font-size: 12pt; font-weight: bold; padding: 5px;")
            return
        self.last_cover_raw_json_list = raw_json_list 
        
        if getattr(self, "pending_cover_fetch", False): 
            self.pending_cover_fetch = False
            
        if not results:
            self.mb_status_label.setText("❌ 未能找到任何封面。")
            msg = f"🍎 Apple Music: {stats.get('am', '未知')}\n🌍 MusicBrainz: {stats.get('mb', '未知')}"
            QMessageBox.information(self, "搜图失败", f"未能找到适用结果。\n\n引擎详情:\n{msg}")
            return
            
        self.mb_status_label.setText(f"✅ 成功命中 {len(results)} 张封面！")
        dlg = CoverGalleryDialog(results, stats, self)
        if dlg.exec():
            if dlg.selected_data:
                def apply_gallery_cover():
                    self.current_cover_data = dlg.selected_data
                    self._cover_is_mixed = False
                    self.update_cover_display(multiple_different=False)
                    self.cover_modified_in_batch = True
                self._record_editor_mutation("撤销画廊封面修改", apply_gallery_cover)

    def _cleanup_cover_worker(self):
        worker = self.sender()
        if worker:
            worker.deleteLater()
        if getattr(self, "cover_worker", None) is worker:
            self.cover_worker = None
            if not self.is_metadata_search_running():
                self.overlay.stop()

    def open_current_cover(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.current_cover_data:
            try:
                ext = ".png" if self.current_cover_data[:4] == b'\x89PNG' else ".jpg"
                temp_dir = tempfile.gettempdir()
                temp_path = os.path.join(temp_dir, f"music_meta_tagger_temp_cover{ext}")
                
                with open(temp_path, "wb") as f:
                    f.write(self.current_cover_data)
                
                if os.name == 'nt':
                    os.startfile(temp_path)
                else:
                    import subprocess
                    subprocess.call(('open', temp_path))
            except Exception as e:
                print(f"打开封面失败: {e}")

    def paste_mbid(self):
        text = QApplication.clipboard().text().strip()
        if not text: return
        match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', text, re.IGNORECASE)
        if match: self.input_mbid.setText(match.group(1).lower())
        else: self.input_mbid.setText(text)

    @staticmethod
    def _extract_apple_collection_id(text):
        text = str(text or "").strip()
        if text.isdigit():
            return text
        match = re.search(r"music\.apple\.com/[^/]+/album/(?:[^/?#]+/)?(\d+)", text, re.IGNORECASE)
        return match.group(1) if match else ""

    def paste_apple_collection_id(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        collection_id = self._extract_apple_collection_id(text)
        self.input_apple_collection_id.setText(collection_id or text)

    def normalize_apple_collection_id_input(self):
        collection_id = self._extract_apple_collection_id(self.input_apple_collection_id.text())
        if collection_id:
            self.input_apple_collection_id.setText(collection_id)

    def resizeEvent(self, event):
        if hasattr(self, 'overlay'): self.overlay.resize(self.centralWidget().size())
        super().resizeEvent(event)
        if getattr(self, "progress_dialog", None) and self.progress_dialog.isVisible():
            QTimer.singleShot(0, self._center_loading_progress_dialog)

    def copy_cover_to_clipboard(self):
        if self.current_cover_data:
            pixmap = QPixmap()
            pixmap.loadFromData(self.current_cover_data)
            QApplication.clipboard().setPixmap(pixmap)

    def paste_cover_from_clipboard(self):
        mime_data = QApplication.clipboard().mimeData()
        if mime_data.hasImage():
            image = QApplication.clipboard().image()
            ba = QByteArray()
            buffer = QBuffer(ba)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if image.hasAlphaChannel():
                image.save(buffer, "PNG")
            else:
                image.save(buffer, "JPEG", quality=100) 
                
            cover_data = ba.data()
            def apply_pasted_cover():
                self.current_cover_data = cover_data
                self._cover_is_mixed = False
                self.update_cover_display(multiple_different=False)
                self.cover_modified_in_batch = True
            self._record_editor_mutation("撤销封面粘贴", apply_pasted_cover)

    def update_cover_display(self, multiple_different=False):
        if multiple_different:
            self.cover_label.setText("多个不同封面\n(支持 Ctrl+V 覆盖)")
            self.resolution_label.setText("分辨率: -")
            return

        if self.current_cover_data:
            pixmap = QPixmap()
            pixmap.loadFromData(self.current_cover_data)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    160, 160,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.cover_label.setPixmap(scaled_pixmap)
                self.resolution_label.setText(f"分辨率: {pixmap.width()}x{pixmap.height()}")
            else:
                self.cover_label.setText("封面读取失败\n(支持 Ctrl+V)")
                self.resolution_label.setText("分辨率: -")
        else:
            self.cover_label.setText("无封面\n(支持 Ctrl+V)")
            self.resolution_label.setText("分辨率: -")

    def locate_first_incomplete_track(self):
        required_fields = ("title", "artist", "album", "album_artist", "track", "disc", "date")
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole + 2) != "track":
                continue
            path = os.path.join(self.music_dir, self.get_real_filename(item))
            metadata = self.album_session.all_files_data.get(path, {})
            if any(not str(metadata.get(field, "") or "").strip() for field in required_fields):
                self.file_list.blockSignals(True)
                self.file_list.clearSelection()
                item.setSelected(True)
                self.file_list.setCurrentItem(item)
                self.file_list.blockSignals(False)
                self.file_list.smooth_scroll_to_item(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                self.on_file_selected()
                return

        QMessageBox.information(self, "信息完整", "当前列表中的曲目均已填写必要元数据。")

    def toggle_virtual_album_group(self):
        items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        if not items: return
        
        paths = [os.path.join(self.music_dir, self.get_real_filename(item)) for item in items]
        
        first_group = self.album_session.selected_virtual_album_group(paths)

        if first_group is not None:
            self.album_session.remove_virtual_album(first_group)
            self.setWindowTitle(f"{APP_NAME} - [已彻底撤销虚拟编组 💽{first_group}]")
        else:
            new_group_id = self.album_session.create_virtual_album(paths)
            self.setWindowTitle(f"{APP_NAME} - [已将 {len(paths)} 首歌编为虚拟专辑 💽{new_group_id}]")
            
        self.refresh_list_items()

    def update_list_display(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 2) == "header":
                continue
                
            base_name = item.data(Qt.ItemDataRole.UserRole)
            if not base_name: continue
            
            display_name = base_name
            status = item.data(Qt.ItemDataRole.UserRole + 1)
            if status == "done": display_name = f"✅ {display_name}"
            elif status == "skip": display_name = f"⏭️ {display_name}"
            elif status == "sync": display_name = f"🔗 {display_name}"
            
            item.setText(f"   {display_name}")

    def toggle_lock(self, key, is_locked):
        should_record = (
            not self.undo_manager.recording_suspended
            and not self._undo_in_progress
            and self._editor_baseline is not None
        )
        before = self._editor_baseline if should_record else None
        session_before = self._capture_lock_session_patch(key) if should_record else None
        btn = self.lock_btns[key]
        if is_locked:
            btn.setText("🔒")
            self.inputs[key].setStyleSheet(self.cb_style_locked)
            if key in self.mb_apply_btns:
                self.mb_apply_btns[key].setEnabled(False)
                self.mb_apply_btns[key].setStyleSheet("padding: 4px; font-weight: bold; background-color: #bdc3c7; color: white; border-radius: 4px; font-size: 10pt;")
        else:
            btn.setText("🔓")
            self.inputs[key].setStyleSheet(self.cb_style_normal)
            if key in self.mb_apply_btns:
                self.mb_apply_btns[key].setEnabled(True)
                self.mb_apply_btns[key].setStyleSheet("padding: 4px; font-weight: bold; background-color: #3498db; color: white; border-radius: 4px; font-size: 10pt;")

        items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        if not items:
            self._refresh_filename_clue_action()
            return
        for item in items:
            path = os.path.join(self.music_dir, self.get_real_filename(item))
            self.album_session.set_lock(path, key, is_locked)
            
        if is_locked and key in self.album_session.album_sync_keys and len(items) == 1:
            ref_path = os.path.join(self.music_dir, self.get_real_filename(items[0]))
            ref_group = self.album_session.virtual_album_map.get(ref_path)
            sync_val = self.inputs[key].currentText()
            
            for i in range(self.file_list.count()):
                o_item = self.file_list.item(i)
                if o_item.data(Qt.ItemDataRole.UserRole + 2) != "track": continue
                o_path = os.path.join(self.music_dir, self.get_real_filename(o_item))
                
                is_same = False
                if ref_group and self.album_session.virtual_album_map.get(o_path) == ref_group:
                    is_same = True
                elif not ref_group and o_path not in self.album_session.virtual_album_map and self._is_same_physical_album(ref_path, o_path):
                    is_same = True
                    
                if is_same:
                    self.album_session.set_lock(o_path, key, True)
                    if sync_val not in ["<保留>", "<留白>"]:
                        self.album_session.all_files_data[o_path][key] = sync_val
                        self._invalidate_metadata_caches([o_path])

        if should_record:
            after = self._capture_editor_state()
            self.undo_manager.push(EditorUndoCommand(
                description=f"撤销{key}锁定修改",
                before=before,
                after=after,
                affected_paths=before.selected_paths,
                session_before=session_before,
                session_after=self._capture_lock_session_patch(key),
            ))
            self._editor_baseline = after
        self._refresh_filename_clue_action()

    def load_locks_for_selection(self, paths):
        if not paths: return
        p0 = paths[0]
        for key in self.inputs.keys():
            is_locked = self.album_session.is_locked(p0, key)
            btn = self.lock_btns[key]
            btn.blockSignals(True)
            btn.setChecked(is_locked)
            btn.setText("🔒" if is_locked else "🔓")
            btn.blockSignals(False)
            
            if is_locked:
                self.inputs[key].setStyleSheet(self.cb_style_locked)
            else:
                self.inputs[key].setStyleSheet(self.cb_style_normal)
                
            if key in self.mb_apply_btns:
                self.mb_apply_btns[key].setEnabled(not is_locked)
                if is_locked: self.mb_apply_btns[key].setStyleSheet("padding: 4px; font-weight: bold; background-color: #bdc3c7; color: white; border-radius: 4px; font-size: 10pt;")
                else: self.mb_apply_btns[key].setStyleSheet("padding: 4px; font-weight: bold; background-color: #3498db; color: white; border-radius: 4px; font-size: 10pt;")
        self._refresh_filename_clue_action()

    def apply_mb_field(self, key):
        if self.lock_btns[key].isChecked(): return
        val = self.mb_inputs[key].text()
        if val:
            self._record_editor_mutation(
                f"撤销应用{key}",
                lambda: self.update_combo_text(self.inputs[key], val),
            )

    def apply_all_mb_fields(self):
        def apply_all():
            items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
            protected_fields = {"title", "artist", "track", "disc"}
            for key, le in self.mb_inputs.items():
                if self.lock_btns[key].isChecked(): continue
                # A metadata query describes one track.  When an album is selected,
                # keep values that inherently differ between tracks intact.
                if len(items) > 1 and key in protected_fields:
                    continue
                val = le.text()
                if val: self.update_combo_text(self.inputs[key], val)
        self._record_editor_mutation("撤销全部应用", apply_all)

    def clear_mb_fields(self):
        self.last_fetch_success = False
        self.mb_status_label.setText("等待提取...")
        self.mb_score_label.setText("")
        if hasattr(self, "btn_use_mb_source"):
            self._set_available_sources({}, "")
        self._current_metadata_source = ""
        self.mb_status_label.setStyleSheet("color: #7f8c8d; font-size: 12pt; font-weight: bold; padding: 5px;")
        for le in self.mb_inputs.values():
            le.clear()
            self._reset_result_field_style(le)
            
        self.mb_labels["disc"].setText("碟号 (Disc)")
        self.mb_labels["disc"].setStyleSheet("font-size: 10pt; font-weight: bold; color: #2c3e50; padding-left: 10px;")

    def open_settings(self):
        dlg = SettingsDialog(self, self.window_settings)
        if dlg.exec():
            self.window_settings["VIP_DOWNLOAD_DIR"] = dlg.ncm_input.text()
            self.window_settings["MAIN_MUSIC_DIR"] = dlg.main_input.text()
            self.window_settings["DEEPSEEK_API_KEY"] = dlg.deepseek_key_input.text()
            APP_SETTINGS.update(self.window_settings)
            save_settings(APP_SETTINGS)
            if self.music_dir != self.window_settings["MAIN_MUSIC_DIR"]:
                self.music_dir = self.window_settings["MAIN_MUSIC_DIR"]
                self.load_file_list()

    def run_convert(self):
        self.setCursor(Qt.CursorShape.WaitCursor)
        success, msg = convert_ncm_files(self.window_settings.get("VIP_DOWNLOAD_DIR", ""))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if success: QMessageBox.information(self, "转换完毕", msg)
        else: QMessageBox.warning(self, "转换警告", msg)

    def confirm_delete_ncm(self):
        ncm_files = list_ncm_files(self.window_settings.get("VIP_DOWNLOAD_DIR", ""))
        if not ncm_files:
            QMessageBox.information(self, "没有可删除文件", "下载目录中没有 .ncm 文件。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("确认删除 NCM")
        dialog.setModal(True)
        dialog.resize(680, 460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        warning_label = QLabel(f"将永久删除以下 {len(ncm_files)} 个 NCM 文件。此操作不可撤销：")
        warning_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        layout.addWidget(warning_label)

        file_preview = QPlainTextEdit()
        file_preview.setReadOnly(True)
        file_preview.setPlainText("\n".join(ncm_files))
        file_preview.setStyleSheet("font-family: 'Consolas', 'Microsoft YaHei'; font-size: 9pt;")
        layout.addWidget(file_preview, stretch=1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        delete_button = button_box.addButton("永久删除", QDialogButtonBox.ButtonRole.DestructiveRole)
        delete_button.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 6px 16px;")
        delete_button.clicked.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        self._center_dialog_on_window(dialog)
        QTimer.singleShot(0, lambda: self._center_dialog_on_window(dialog))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        success, msg = delete_ncm_files(ncm_files)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if success:
            QMessageBox.information(self, "删除完成", msg)
        else:
            QMessageBox.warning(self, "删除不完整", msg)

    def _center_dialog_on_window(self, dialog):
        parent_frame = self.frameGeometry()
        dialog_frame = dialog.frameGeometry()
        dialog.move(
            parent_frame.x() + (parent_frame.width() - dialog_frame.width()) // 2,
            parent_frame.y() + (parent_frame.height() - dialog_frame.height()) // 2,
        )

    def open_additional_window(self):
        new_window = MusicEditorWindow(self.music_dir, self.window_settings)
        window_id = id(new_window)
        self.additional_windows[window_id] = new_window
        new_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        new_window.destroyed.connect(lambda *_args, key=window_id: self.additional_windows.pop(key, None))
        new_window.showMaximized()
        new_window.start_initial_load()

    def run_move(self):
        self.setCursor(Qt.CursorShape.WaitCursor)
        success, msg = move_audio_files(
            self.window_settings.get("VIP_DOWNLOAD_DIR", ""),
            self.window_settings.get("MAIN_MUSIC_DIR", ""),
        )
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if success: self.load_file_list(); QMessageBox.information(self, "移动完毕", msg)
        else: QMessageBox.warning(self, "移动警告", msg)

    def run_clean_lrc(self):
        self.setCursor(Qt.CursorShape.WaitCursor)
        dirs_to_clean = [
            self.window_settings.get("VIP_DOWNLOAD_DIR", ""),
            self.window_settings.get("MAIN_MUSIC_DIR", ""),
        ]
        success, msg = clean_lrc_files(dirs_to_clean)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        QMessageBox.information(self, "清理完毕", msg)

    def _connect_undo_capture(self):
        for key, combo in self.inputs.items():
            combo.currentTextChanged.connect(self._refresh_filename_clue_action)
            combo.lineEdit().textEdited.connect(
                lambda _text, field=key: self._record_user_editor_change(
                    f"撤销{field}编辑", f"field:{field}"
                )
            )
            combo.activated.connect(
                lambda _index, field=key: self._record_user_editor_change(
                    f"撤销{field}选项修改"
                )
            )
            self.checkboxes[key].clicked.connect(
                lambda _checked, field=key: self._record_user_editor_change(
                    f"撤销{field}勾选修改"
                )
            )

    def _capture_editor_state(self):
        paths = tuple(
            self._item_path(item)
            for item in self.file_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole + 2) == "track"
        )
        cursor_states = {}
        for key, combo in self.inputs.items():
            line_edit = combo.lineEdit()
            start = line_edit.selectionStart()
            cursor_states[key] = CursorState(
                line_edit.cursorPosition(),
                start,
                len(line_edit.selectedText()) if start >= 0 else 0,
            )
        cover = bytes(self.current_cover_data) if self.current_cover_data else None
        return EditorStateSnapshot(
            selected_paths=paths,
            field_values={key: combo.currentText() for key, combo in self.inputs.items()},
            checked_fields={key: box.isChecked() for key, box in self.checkboxes.items()},
            locked_fields={key: button.isChecked() for key, button in self.lock_btns.items()},
            cursor_states=cursor_states,
            cover_has_data=cover is not None,
            cover_data=cover,
            cover_is_mixed=self._cover_is_mixed,
            cover_modified=self.cover_modified_in_batch,
            result_values={key: line_edit.text() for key, line_edit in self.mb_inputs.items()},
            selected_source=self._current_metadata_source,
            status_text=self.mb_status_label.text(),
            score_text=self.mb_score_label.text(),
            filename_clue_status_text=self.filename_clue_status_label.text(),
        )

    def _record_user_editor_change(self, description, merge_key=None):
        if self.undo_manager.recording_suspended or self._undo_in_progress:
            return
        after = self._capture_editor_state()
        before = self._editor_baseline
        if before is None or before.selected_paths != after.selected_paths:
            self._editor_baseline = after
            return
        if before == after:
            return
        effective_merge_key = None
        if merge_key:
            effective_merge_key = f"{merge_key}:{'|'.join(after.selected_paths)}"
        self.undo_manager.push(EditorUndoCommand(
            description=description,
            before=before,
            after=after,
            affected_paths=after.selected_paths,
            merge_key=effective_merge_key,
        ))
        self._editor_baseline = after

    def _record_editor_mutation(self, description, mutator, session_before=None):
        before = self._capture_editor_state()
        with self.undo_manager.suspend_recording():
            mutator()
        after = self._capture_editor_state()
        if before != after or session_before is not None:
            self.undo_manager.push(EditorUndoCommand(
                description=description,
                before=before,
                after=after,
                affected_paths=before.selected_paths or after.selected_paths,
                session_before=session_before.detached_copy() if session_before else None,
            ))
        self._editor_baseline = after

    @staticmethod
    def _stored_value(mapping, key):
        return StoredValue(key in mapping, copy.deepcopy(mapping.get(key)))

    def _capture_lock_session_patch(self, key):
        paths = set(self.album_session.all_files_data) | set(self.album_session.locks_data)
        return SessionPatch(
            metadata_values={
                path: {key: self._stored_value(data, key)}
                for path, data in self.album_session.all_files_data.items()
            },
            lock_values={
                path: {key: self._stored_value(self.album_session.locks_data.get(path, {}), key)}
                for path in paths
            },
        )

    def _capture_source_session_patch(self):
        path = getattr(self, "current_api_file_path", "")
        preference_key = self._album_source_key(path) if path else None
        preferences = {}
        if preference_key is not None:
            preferences[preference_key] = self._stored_value(
                self.album_source_preferences, preference_key
            )
        cache_values = {}
        if path:
            cache_values[path] = self._stored_value(self.api_cache, path)
        return SessionPatch(
            source_preferences=preferences,
            api_cache_values=cache_values,
        )

    def _restore_session_patch(self, patch):
        if patch is None:
            return
        for path, fields in patch.metadata_values.items():
            data = self.album_session.all_files_data.setdefault(path, {})
            for key, stored in fields.items():
                if stored.exists:
                    data[key] = copy.deepcopy(stored.value)
                else:
                    data.pop(key, None)
        for path, fields in patch.lock_values.items():
            locks = self.album_session.locks_data.setdefault(path, {})
            for key, stored in fields.items():
                if stored.exists:
                    locks[key] = copy.deepcopy(stored.value)
                else:
                    locks.pop(key, None)
            if not locks:
                self.album_session.locks_data.pop(path, None)
        for key, stored in patch.source_preferences.items():
            if stored.exists:
                self.album_source_preferences[key] = copy.deepcopy(stored.value)
            else:
                self.album_source_preferences.pop(key, None)
        for path, stored in patch.api_cache_values.items():
            if stored.exists:
                self.api_cache[path] = copy.deepcopy(stored.value)
            else:
                self.api_cache.pop(path, None)
        self._invalidate_metadata_caches(patch.metadata_values)

    def _apply_lock_visual(self, key, is_locked):
        button = self.lock_btns[key]
        button.setText("🔒" if is_locked else "🔓")
        self.inputs[key].setStyleSheet(
            self.cb_style_locked if is_locked else self.cb_style_normal
        )
        if key in self.mb_apply_btns:
            self.mb_apply_btns[key].setEnabled(not is_locked)

    def _select_paths_for_undo(self, paths):
        available = [
            self._track_item_cache[path]
            for path in paths
            if path in self._track_item_cache
            and self.file_list.row(self._track_item_cache[path]) >= 0
        ]
        if not available:
            return
        self.file_list.blockSignals(True)
        self._selection_prompt_suppressed = True
        try:
            self.file_list.clearSelection()
            for item in available:
                item.setSelected(True)
            self.file_list.setCurrentItem(available[0])
        finally:
            self.file_list.blockSignals(False)
        try:
            self.on_file_selected()
        finally:
            self._selection_prompt_suppressed = False
        self.file_list.smooth_scroll_to_item(
            available[0], QAbstractItemView.ScrollHint.PositionAtCenter
        )

    def _apply_editor_state(self, command, redo=False):
        snapshot = command.after if redo else command.before
        session_patch = command.session_after if redo else command.session_before
        with self.undo_manager.suspend_recording():
            self._restore_session_patch(session_patch)
            if snapshot.selected_paths:
                self._select_paths_for_undo(snapshot.selected_paths)
            for key, value in snapshot.field_values.items():
                self.update_combo_text(self.inputs[key], value)
            for key, checked in snapshot.checked_fields.items():
                self.checkboxes[key].setChecked(checked)
            for key, locked in snapshot.locked_fields.items():
                button = self.lock_btns[key]
                button.blockSignals(True)
                button.setChecked(locked)
                button.blockSignals(False)
                self._apply_lock_visual(key, locked)
            self.current_cover_data = (
                snapshot.cover_data if snapshot.cover_has_data else None
            )
            self._cover_is_mixed = snapshot.cover_is_mixed
            self.cover_modified_in_batch = snapshot.cover_modified
            self.update_cover_display(snapshot.cover_is_mixed)
            for key, value in snapshot.result_values.items():
                self.mb_inputs[key].setText(value)
            self._current_metadata_source = snapshot.selected_source
            self._set_available_sources(
                getattr(self, "available_source_results", {}),
                snapshot.selected_source,
            )
            self.mb_status_label.setText(snapshot.status_text)
            self.mb_score_label.setText(snapshot.score_text)
            self._set_filename_clue_status(snapshot.filename_clue_status_text)
            for key, cursor in snapshot.cursor_states.items():
                line_edit = self.inputs[key].lineEdit()
                line_edit.setCursorPosition(
                    max(0, min(cursor.position, len(line_edit.text())))
                )
                if cursor.selection_start >= 0 and cursor.selection_length:
                    line_edit.setSelection(
                        cursor.selection_start, cursor.selection_length
                    )
        self._editor_baseline = self._capture_editor_state()

    def perform_undo(self):
        if self._save_in_progress or self._undo_in_progress:
            return
        if self.is_filename_clue_analysis_running():
            self.cancel_active_search()
            return
        command = self.undo_manager.peek()
        if command is None:
            return
        if self.is_metadata_search_running() or self.is_cover_search_running():
            self.cancel_active_search()
        if isinstance(command, SavedMetadataTransaction):
            self._start_saved_transaction_restore(command, redo=False)
            return
        if isinstance(command, EditorUndoCommand):
            if self.undo_manager.move_undo_to_redo(command):
                self._apply_editor_state(command, redo=False)

    def perform_redo(self):
        if self._save_in_progress or self._undo_in_progress:
            return
        if self.is_filename_clue_analysis_running():
            self.cancel_active_search()
            return
        command = self.undo_manager.peek_redo()
        if command is None:
            return
        if self.is_metadata_search_running() or self.is_cover_search_running():
            self.cancel_active_search()
        if isinstance(command, SavedMetadataTransaction):
            self._start_saved_transaction_restore(command, redo=True)
            return
        if isinstance(command, EditorUndoCommand):
            if self.undo_manager.move_redo_to_undo(command):
                self._apply_editor_state(command, redo=True)

    def _start_saved_transaction_restore(self, transaction, redo=False):
        if not transaction.changes:
            return
        self._undo_in_progress = True
        self._undo_transaction = transaction
        self._undo_is_redo = redo
        self._set_save_controls_enabled(False)
        action_text = "重做保存" if redo else "撤销保存"
        self.save_progress_dialog = QProgressDialog(
            f"正在准备{action_text}...", None, 0, len(transaction.changes), self
        )
        self.save_progress_dialog.setWindowTitle(f"正在{action_text}")
        self.save_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.save_progress_dialog.setWindowFlag(
            Qt.WindowType.WindowCloseButtonHint, False
        )
        self.save_progress_dialog.setCancelButton(None)
        self.save_progress_dialog.setMinimumDuration(0)
        self.save_progress_dialog.setAutoClose(False)
        self.save_progress_dialog.setAutoReset(False)
        self.save_progress_dialog.setValue(0)
        self.save_progress_dialog.show()
        self._center_dialog_on_window(self.save_progress_dialog)
        self.restore_worker = RestoreWorker(
            transaction.changes,
            service=self._restore_service_factory(),
            parent=self,
        )
        self.restore_worker.progress_sig.connect(self._update_save_progress)
        self.restore_worker.finished_sig.connect(self._finish_saved_transaction_undo)
        self.restore_worker.failed_sig.connect(self._handle_restore_worker_failure)
        self.restore_worker.finished.connect(self._cleanup_restore_worker)
        self.restore_worker.start()

    def _handle_restore_worker_failure(self, error):
        self._finish_saved_transaction_undo(None, error)

    def _close_operation_progress_dialog(self):
        dialog = getattr(self, "save_progress_dialog", None)
        if not dialog:
            return
        dialog.close()
        QTimer.singleShot(
            100,
            lambda target=dialog: self._dispose_operation_progress_dialog(target),
        )

    def _dispose_operation_progress_dialog(self, dialog):
        if getattr(self, "save_progress_dialog", None) is dialog:
            self.save_progress_dialog = None
        dialog.deleteLater()

    def _finish_saved_transaction_undo(self, result, worker_error=""):
        transaction = getattr(self, "_undo_transaction", None)
        is_redo = getattr(self, "_undo_is_redo", False)
        try:
            self._close_operation_progress_dialog()
            if result is None:
                action_text = "重做保存" if is_redo else "撤销保存"
                QMessageBox.warning(
                    self,
                    f"{action_text}失败",
                    worker_error or f"{action_text}任务意外终止。",
                )
                return

            for path, metadata in result.restored_metadata.items():
                self.album_session.all_files_data[path] = metadata
                item = self._track_item_cache.get(path)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole + 1, None)
            restored_paths = list(result.success_files)
            restored_album_paths = {
                path
                for path in restored_paths
                if transaction is not None
                and path in transaction.changes
                and transaction.changes[path].before.album
                != transaction.changes[path].after.album
            }
            self._sync_selected_metadata_after_write(result.restored_metadata)
            self._invalidate_metadata_caches(restored_paths)
            self._refresh_sortable_metadata(preserve_album_order=True)
            if is_redo:
                self._session_modified_album_paths.update(restored_album_paths)
            else:
                self._session_modified_album_paths.difference_update(
                    restored_album_paths
                )
            if transaction is not None:
                transaction.mark_restored(restored_paths)
                if transaction.is_complete:
                    replacement = transaction.reversed(
                        "undo" if is_redo else "redo"
                    )
                    if is_redo:
                        self.undo_manager.move_redo_to_undo(
                            transaction, replacement
                        )
                    else:
                        self.undo_manager.move_undo_to_redo(
                            transaction, replacement
                        )
                else:
                    self.undo_manager.refresh_limits()
            self.refresh_list_items()
            self._refresh_saved_album_headers(
                restored_album_paths, mark_modified=is_redo
            )
            if restored_paths:
                self._select_paths_for_undo([restored_paths[0]])

            details = []
            for path in result.conflict_files:
                details.append(f"外部修改冲突: {os.path.basename(path)}")
            for path in result.failed_files:
                details.append(
                    f"恢复失败: {os.path.basename(path)}: {result.errors.get(path, '')}"
                )
            if details:
                action_text = "重做保存" if is_redo else "撤销保存"
                self.mb_status_label.setText(
                    f"{action_text}未完成，仍有 {len(details)} 个文件可重试"
                )
                QMessageBox.warning(self, f"{action_text}未完成", "\n".join(details))
            else:
                self.mb_status_label.setText(
                    f"已{'重做' if is_redo else '撤销'}保存 {len(restored_paths)} 个文件"
                )
        finally:
            self._undo_in_progress = False
            self._set_save_controls_enabled(True)
            self._undo_transaction = None
            self._undo_is_redo = False
            self._editor_baseline = self._capture_editor_state()
            self._selection_metadata_baseline = self._capture_selection_metadata_state()

    def _cleanup_restore_worker(self):
        worker = self.sender()
        if worker:
            worker.deleteLater()
        if getattr(self, "restore_worker", None) is worker:
            self.restore_worker = None

    def update_combo_text(self, cb, text):
        cb.setCurrentText(text)
        if cb.lineEdit(): 
            cb.lineEdit().setCursorPosition(0)
            cb.lineEdit().setToolTip(text) 

    def _set_filename_clue_status(self, text):
        self.filename_clue_status_label.setText(text)
        color = "#d68910" if text == "未从文件名提取到可填线索" else "#7f8c8d"
        self.filename_clue_status_label.setStyleSheet(
            f"color: {color}; font-size: 9pt;"
        )

    def _filename_clue_target_path(self):
        paths = self._selected_track_paths()
        if len(paths) != 1:
            return ""
        return next(iter(paths))

    def _eligible_filename_clue_fields(self):
        path = self._filename_clue_target_path()
        if not path:
            return ()
        identity_values = [
            self.inputs[key].currentText().strip()
            for key in ("title", "artist", "album")
        ]
        if all(identity_values):
            return ()
        return tuple(
            key
            for key in FILENAME_CLUE_FIELDS
            if not self.inputs[key].currentText().strip()
            and not self.lock_btns[key].isChecked()
        )

    def _refresh_filename_clue_action(self, *_args):
        if not hasattr(self, "btn_filename_clue"):
            return
        busy = (
            self._save_in_progress
            or self._undo_in_progress
            or self.is_metadata_search_running()
            or self.is_cover_search_running()
            or self.is_filename_clue_analysis_running()
        )
        self.btn_filename_clue.setEnabled(
            not busy and bool(self._eligible_filename_clue_fields())
        )

    def is_filename_clue_analysis_running(self):
        worker = getattr(self, "filename_clue_worker", None)
        return bool(worker and worker.isRunning())

    def start_filename_clue_analysis(self):
        eligible_fields = self._eligible_filename_clue_fields()
        target_path = self._filename_clue_target_path()
        if (
            not target_path
            or not eligible_fields
            or self._save_in_progress
            or self._undo_in_progress
            or self.is_metadata_search_running()
            or self.is_cover_search_running()
            or self.is_filename_clue_analysis_running()
        ):
            self._refresh_filename_clue_action()
            return

        self._filename_clue_generation += 1
        request_id = self._filename_clue_generation
        self._active_filename_clue_request_id = request_id
        self._active_filename_clue_path = target_path
        self.overlay.start()
        self.btn_filename_clue.setEnabled(False)
        self._set_save_controls_enabled(False)
        api_key = (
            os.environ.get("DEEPSEEK_API_KEY", "").strip()
            or str(self.window_settings.get("DEEPSEEK_API_KEY", "") or "").strip()
        )
        self.filename_clue_worker = FilenameClueWorker(
            os.path.basename(target_path),
            target_path,
            api_key=api_key,
            request_id=request_id,
            cancel_event=threading.Event(),
            parent=self,
        )
        self.filename_clue_worker.finished_sig.connect(
            self.on_filename_clue_analysis_finished
        )
        self.filename_clue_worker.finished.connect(
            self._cleanup_filename_clue_worker
        )
        self.filename_clue_worker.start()

    def on_filename_clue_analysis_finished(
        self,
        result,
        target_path,
        request_id,
        cancelled,
    ):
        if request_id != self._active_filename_clue_request_id:
            self._cancelled_filename_clue_request_ids.discard(request_id)
            return
        was_cancelled = request_id in self._cancelled_filename_clue_request_ids
        self._cancelled_filename_clue_request_ids.discard(request_id)
        self._active_filename_clue_request_id = None
        active_path = self._active_filename_clue_path
        self._active_filename_clue_path = ""
        if (
            cancelled
            or was_cancelled
            or result is None
            or target_path != active_path
            or target_path != self._filename_clue_target_path()
        ):
            return

        updates = {
            key: str(result.values.get(key, "") or "").strip()
            for key in FILENAME_CLUE_FIELDS
            if str(result.values.get(key, "") or "").strip()
            and not self.inputs[key].currentText().strip()
            and not self.lock_btns[key].isChecked()
        }
        if not updates:
            self._set_filename_clue_status("未从文件名提取到可填线索")
            self._editor_baseline = self._capture_editor_state()
            return

        status_text = (
            "DeepSeek解析"
            if result.source == FilenameClueSource.DEEPSEEK
            else "本地规则解析"
        )

        def apply_filename_clues():
            for key, value in updates.items():
                self.update_combo_text(self.inputs[key], value)
            self._set_filename_clue_status(status_text)

        self._record_editor_mutation(
            "撤销文件名线索解析",
            apply_filename_clues,
        )
        self._refresh_filename_clue_action()

    def _cleanup_filename_clue_worker(self):
        worker = self.sender()
        if worker:
            worker.deleteLater()
        if getattr(self, "filename_clue_worker", None) is worker:
            self.filename_clue_worker = None
            if (
                not self.is_metadata_search_running()
                and not self.is_cover_search_running()
            ):
                self.overlay.stop()
            self._set_save_controls_enabled(True)
            self._refresh_filename_clue_action()

    def keyPressEvent(self, event):
        focus = QApplication.focusWidget()
        if (
            self._save_in_progress
            or self._undo_in_progress
            or self.is_filename_clue_analysis_running()
        ):
            event.accept()
            return
        if not isinstance(focus, QLineEdit):
            modifiers = QApplication.keyboardModifiers()
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers == Qt.KeyboardModifier.ShiftModifier:
                if self.file_list.selectedItems(): self.do_fetch("auto")
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers == Qt.KeyboardModifier.ControlModifier:
                if self.file_list.selectedItems(): self.skip_current_files()
            elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers == Qt.KeyboardModifier.NoModifier:
                self._blocked_key_releases.add(event.key())
                if self.file_list.selectedItems(): self.save_current_files()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        belongs_to_this_window = watched is self or (
            isinstance(watched, QWidget) and self.isAncestorOf(watched)
        )
        if belongs_to_this_window and event.type() in (
            QEvent.Type.ShortcutOverride,
            QEvent.Type.KeyPress,
        ):
            key = getattr(event, "key", lambda: None)()
            modifiers = getattr(event, "modifiers", lambda: Qt.KeyboardModifier.NoModifier)()
            focus = QApplication.focusWidget()
            native_history_widgets = (
                self.input_mbid,
                self.input_apple_collection_id,
            )
            if (
                focus in native_history_widgets
                and modifiers == Qt.KeyboardModifier.ControlModifier
                and key in (Qt.Key.Key_Z, Qt.Key.Key_Y)
            ):
                return super().eventFilter(watched, event)
            if (
                key == Qt.Key.Key_Z
                and modifiers == Qt.KeyboardModifier.ControlModifier
            ):
                event.accept()
                if event.type() == QEvent.Type.KeyPress:
                    self.perform_undo()
                return True
            if (
                key == Qt.Key.Key_Y
                and modifiers == Qt.KeyboardModifier.ControlModifier
            ):
                event.accept()
                if event.type() == QEvent.Type.KeyPress:
                    self.perform_redo()
                return True
            if key == Qt.Key.Key_Escape and event.type() == QEvent.Type.KeyPress:
                if self.cancel_active_search():
                    event.accept()
                    return True
        if (
            self._save_in_progress
            or self._undo_in_progress
            or self.is_filename_clue_analysis_running()
        ) and belongs_to_this_window and event.type() in (
            QEvent.Type.ShortcutOverride,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
        ):
            key = getattr(event, "key", lambda: None)()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.type() == QEvent.Type.KeyRelease:
                    self._blocked_key_releases.discard(key)
                else:
                    self._blocked_key_releases.add(key)
            event.accept()
            return True
        if belongs_to_this_window and event.type() == QEvent.Type.KeyRelease:
            key = getattr(event, "key", lambda: None)()
            if key in self._blocked_key_releases:
                self._blocked_key_releases.discard(key)
                event.accept()
                return True
        if belongs_to_this_window and event.type() == QEvent.Type.KeyPress:
            key = getattr(event, "key", lambda: None)()
            if key in self._blocked_key_releases:
                event.accept()
                return True
            focus = QApplication.focusWidget()
            metadata_enter_widgets = (
                *self.inputs.values(),
                *(combo.lineEdit() for combo in self.inputs.values()),
                self.input_mbid,
                self.input_apple_collection_id,
                *self.mb_inputs.values(),
            )
            if (
                (watched in metadata_enter_widgets or focus in metadata_enter_widgets)
                and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            ):
                modifiers = getattr(
                    event, "modifiers", lambda: Qt.KeyboardModifier.NoModifier
                )()
                if modifiers == Qt.KeyboardModifier.ShiftModifier:
                    if self.file_list.selectedItems():
                        self.do_fetch("auto")
                elif modifiers == Qt.KeyboardModifier.ControlModifier:
                    if self.file_list.selectedItems():
                        self.skip_current_files()
                elif modifiers == Qt.KeyboardModifier.NoModifier:
                    self._blocked_key_releases.add(key)
                    if self.file_list.selectedItems():
                        self.save_current_files()
                else:
                    return super().eventFilter(watched, event)
                event.accept()
                return True
        if belongs_to_this_window and event.type() == QEvent.Type.FocusOut:
            if watched in [combo.lineEdit() for combo in self.inputs.values()]:
                self.undo_manager.break_merge()
        return super().eventFilter(watched, event)

    def is_metadata_search_running(self):
        return bool(getattr(self, "worker", None) and self.worker.isRunning())

    def is_cover_search_running(self):
        return bool(getattr(self, "cover_worker", None) and self.cover_worker.isRunning())

    def cancel_active_search(self):
        if self.is_metadata_search_running():
            request_id = self._active_metadata_search_id
            if request_id is not None:
                self._cancelled_metadata_search_ids.add(request_id)
            self.pending_cover_fetch = False
            self.worker.cancel()
            for button in self._search_buttons:
                button.setEnabled(False)
            self.mb_status_label.setText("正在取消元数据搜索...")
            self.mb_status_label.setStyleSheet("color: #e67e22; font-size: 12pt; font-weight: bold; padding: 5px;")
            return True
        if self.is_cover_search_running():
            request_id = self._active_cover_search_id
            if request_id is not None:
                self._cancelled_cover_search_ids.add(request_id)
            self.cover_worker.cancel()
            for button in self._search_buttons:
                button.setEnabled(False)
            self.mb_status_label.setText("正在取消封面搜索...")
            self.mb_status_label.setStyleSheet("color: #e67e22; font-size: 12pt; font-weight: bold; padding: 5px;")
            return True
        if self.is_filename_clue_analysis_running():
            request_id = self._active_filename_clue_request_id
            if request_id is not None:
                self._cancelled_filename_clue_request_ids.add(request_id)
            self.filename_clue_worker.cancel()
            self.btn_filename_clue.setEnabled(False)
            return True
        return False

    def search_mb_artist(self):
        artist = self.inputs["artist"].currentText().split("\\\\")[0].strip()
        if not artist or artist in ["<保留>", "<留白>"]: return
        webbrowser.open(f"https://musicbrainz.org/search?query={urllib.parse.quote(artist)}&type=artist&method=indexed")

    def search_mb_album(self):
        album = self.inputs["album"].currentText().strip()
        if not album or album in ["<保留>", "<留白>"]: return
        webbrowser.open(f"https://musicbrainz.org/search?query={urllib.parse.quote(album)}&type=release&method=indexed")

    def search_apple_music(self):
        album, title = self.inputs["album"].currentText().strip(), self.inputs["title"].currentText().strip()
        if album in ["<保留>", "<留白>"]: album = ""
        if title in ["<保留>", "<留白>"]: title = ""
        q = album if album else title
        if q: webbrowser.open(f"https://music.apple.com/cn/search?term={urllib.parse.quote(q)}")
        
    def search_both(self):
        self.search_apple_music()
        self.search_mb_album()

    def load_file_list(self):
        self.undo_manager.clear()
        self._editor_baseline = None
        self._loaded_selection_paths = ()
        self._selection_metadata_baseline = None
        self._search_restore_timer.stop()
        self._search_hidden_paths = set()
        self._search_hidden_headers = set()
        self.file_list.clear()
        self._track_item_cache = {}
        self._header_item_cache = {}
        self._session_modified_album_paths = set()
        self._cover_fingerprint_cache = {}
        self._physical_album_key_cache = {}
        self.album_session.reset_for_file_load()
        self.api_cache = {} 
        self.album_source_preferences = {}
        
        if not os.path.exists(self.music_dir): return
        
        self.progress_dialog = FileLoadProgressDialog(self)
        self.progress_dialog.show()
        self._center_loading_progress_dialog()
        # The platform may apply its own first-show placement after show().
        QTimer.singleShot(0, self._center_loading_progress_dialog)
        QTimer.singleShot(100, self._center_loading_progress_dialog)
        
        self.loader_worker = FileLoaderWorker(self.music_dir)
        self.loader_worker.configured_sig.connect(self.configure_load_workers)
        self.loader_worker.progress_sig.connect(self.update_load_progress)
        self.loader_worker.finished_sig.connect(self.on_load_finished)
        self.loader_worker.start()

    def _center_loading_progress_dialog(self):
        dialog = getattr(self, "progress_dialog", None)
        if not dialog or not dialog.isVisible():
            return
        parent_frame = self.frameGeometry()
        dialog_frame = dialog.frameGeometry()
        dialog.move(
            parent_frame.x() + (parent_frame.width() - dialog_frame.width()) // 2,
            parent_frame.y() + (parent_frame.height() - dialog_frame.height()) // 2,
        )

    def configure_load_workers(self, worker_count):
        self.progress_dialog.configure_worker_count(worker_count)
        self._center_loading_progress_dialog()

    def update_load_progress(
        self, slot, current, lane_total, completed, total, filename
    ):
        self.progress_dialog.update_thread_progress(
            slot, current, lane_total, completed, total, filename
        )

    def on_load_finished(self, sortable, all_files_data):
        self.album_session.all_files_data = all_files_data
        self.full_sortable_list = sortable
        self.populate_file_list(sortable)
        self._editor_baseline = self._capture_editor_state()
        
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.accept()

    def get_real_filename(self, item):
        return item.data(Qt.ItemDataRole.UserRole)

    @staticmethod
    def _cover_fingerprint(cover_data):
        if not cover_data:
            return "no-cover"
        return hashlib.sha256(cover_data).hexdigest()

    def _cached_cover_fingerprint(self, cover_data):
        if not cover_data:
            return "no-cover"
        cache_key = id(cover_data)
        cached = self._cover_fingerprint_cache.get(cache_key)
        if cached and cached[0] is cover_data:
            return cached[1]
        fingerprint = self._cover_fingerprint(cover_data)
        self._cover_fingerprint_cache[cache_key] = (cover_data, fingerprint)
        return fingerprint

    def _physical_album_key(self, path, metadata=None):
        if metadata is not None:
            return (
                str(metadata.get("album", "")).strip().casefold(),
                self._cached_cover_fingerprint(metadata.get("cover_data")),
            )

        metadata = self.album_session.all_files_data.get(
            path, self.album_session.selected_files_data.get(path, {})
        )
        album = str(metadata.get("album", "")).strip().casefold()
        cover_data = metadata.get("cover_data")
        cached = self._physical_album_key_cache.get(path)
        if cached and cached[0] == album and cached[1] is cover_data:
            return cached[2]
        result = (album, self._cached_cover_fingerprint(cover_data))
        self._physical_album_key_cache[path] = (album, cover_data, result)
        return result

    def _invalidate_metadata_caches(self, paths):
        self._cover_fingerprint_cache.clear()
        for path in paths:
            self._physical_album_key_cache.pop(path, None)

    def _refresh_sortable_metadata(self, preserve_album_order=False):
        if not hasattr(self, "full_sortable_list"):
            return

        def tag_number(value):
            number = str(value).split("/", 1)[0]
            return int(number) if number.isdigit() else 0

        refreshed = []
        for old_sort_data, path in self.full_sortable_list:
            data = self.album_session.all_files_data.get(path, {})
            album_sort_value = (
                old_sort_data[0]
                if preserve_album_order
                else data.get("album", "")
            )
            refreshed.append((
                (
                    album_sort_value,
                    tag_number(data.get("disc", "")),
                    tag_number(data.get("track", "")),
                    os.path.basename(path),
                ),
                path,
            ))
        self.full_sortable_list = refreshed

    def _refresh_saved_album_headers(self, paths, mark_modified=True):
        if mark_modified:
            self._session_modified_album_paths.update(paths)
        else:
            self._session_modified_album_paths.difference_update(paths)
        header_ids = {
            item.data(Qt.ItemDataRole.UserRole + 3)
            for path in paths
            for item in (self._track_item_cache.get(path),)
            if item is not None and self.file_list.row(item) >= 0
        }
        for header_id in header_ids:
            if not str(header_id).startswith("album_"):
                continue
            albums = {
                str(self.album_session.all_files_data.get(path, {}).get("album", "")).strip()
                for path, item in self._track_item_cache.items()
                if self.file_list.row(item) >= 0
                and item.data(Qt.ItemDataRole.UserRole + 3) == header_id
            }
            albums.discard("")
            if len(albums) != 1:
                continue
            album = next(iter(albums))
            header = self._header_item_cache.get(header_id)
            if header is None:
                continue
            header.setText(f"💿 {album}")
            header.setData(Qt.ItemDataRole.UserRole + 5, album)
            header.setData(Qt.ItemDataRole.UserRole + 6, mark_modified)
            header.setForeground(QColor("#8e44ad" if mark_modified else "#7f8c8d"))
            header.setToolTip(
                "专辑名称已修改；本次会话保持原列表位置。"
                if mark_modified else ""
            )

    def _sync_selected_metadata_after_write(self, metadata_by_path):
        for path, metadata in metadata_by_path.items():
            if path in self.album_session.selected_files_data:
                self.album_session.selected_files_data[path] = metadata
        selected_albums = {
            str(self.album_session.all_files_data.get(path, {}).get("album", "")).strip()
            for path in self._loaded_selection_paths
            if path in self.album_session.all_files_data
        }
        if len(selected_albums) == 1:
            self.album_session.last_selected_album = next(iter(selected_albums))

    def _album_source_key(self, path):
        group_id = self.album_session.virtual_album_map.get(path)
        if group_id is not None:
            return ("virtual", group_id)
        album, cover_fingerprint = self._physical_album_key(path)
        return ("album", album, cover_fingerprint) if album else ("file", path)

    def _is_same_physical_album(self, reference_path, candidate_path, reference_data=None):
        reference_data = reference_data or self.album_session.all_files_data.get(reference_path, {})
        candidate_data = self.album_session.all_files_data.get(candidate_path, {})
        reference_album = str(reference_data.get("album", "")).strip()
        return (
            bool(reference_album)
            and reference_album == str(candidate_data.get("album", "")).strip()
            and self._cover_fingerprint(reference_data.get("cover_data"))
            == self._cover_fingerprint(candidate_data.get("cover_data"))
        )

    def _apply_album_source_preference(self, path, api_data, establish_default=False):
        source_results = api_data.get("source_results", {})
        if not source_results:
            return api_data

        album_key = self._album_source_key(path)
        preferred_source = self.album_source_preferences.get(album_key)
        if preferred_source not in source_results:
            preferred_source = api_data.get("metadata_source", "")
            if establish_default and preferred_source in source_results:
                self.album_source_preferences[album_key] = preferred_source

        preferred_data = source_results.get(preferred_source)
        if not preferred_data:
            return api_data

        selected = dict(preferred_data)
        selected["source_results"] = source_results
        selected["source_comparison"] = api_data.get("source_comparison", "")
        return selected

    def on_file_selected(self):
        new_paths = tuple(
            self._item_path(item)
            for item in self.file_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole + 2) == "track"
        )
        selection_changed = set(new_paths) != set(self._loaded_selection_paths)
        if (
            selection_changed
            and self._loaded_selection_paths
            and not self._selection_prompt_suppressed
            and not self._restoring_rejected_selection
            and self._has_unsaved_metadata_changes()
        ):
            answer = QMessageBox.question(
                self,
                "存在未保存的修改",
                "当前选择的元数据尚未保存。是否仍要切换到其他文件？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._restore_rejected_selection()
                return
        elif not selection_changed and self._has_unsaved_metadata_changes():
            return

        with self.undo_manager.suspend_recording():
            self._on_file_selected_without_undo()
        self._loaded_selection_paths = new_paths
        self._selection_metadata_baseline = self._capture_selection_metadata_state()
        self.undo_manager.break_merge()
        self._editor_baseline = self._capture_editor_state()

    def _capture_selection_metadata_state(self):
        cover = bytes(self.current_cover_data) if self.current_cover_data else None
        return (
            tuple((key, combo.currentText()) for key, combo in self.inputs.items()),
            cover,
            self._cover_is_mixed,
            self.cover_modified_in_batch,
        )

    def _has_unsaved_metadata_changes(self):
        if self._selection_metadata_baseline is None:
            return False
        return self._capture_selection_metadata_state() != self._selection_metadata_baseline

    def _restore_rejected_selection(self):
        self._restoring_rejected_selection = True
        self.file_list.blockSignals(True)
        try:
            self.file_list.clearSelection()
            current = None
            for path in self._loaded_selection_paths:
                item = self._track_item_cache.get(path)
                if item and self.file_list.row(item) >= 0:
                    item.setSelected(True)
                    current = current or item
            if current:
                self.file_list.setCurrentItem(current)
        finally:
            self.file_list.blockSignals(False)
            self._restoring_rejected_selection = False

    def _on_file_selected_without_undo(self):
        self._set_filename_clue_status("")
        items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        if not items: 
            self.clear_mb_fields()
            self.album_session.selected_files_data = {}
            for key, cb in self.inputs.items(): cb.clear()
            self.current_cover_data = None
            self._cover_is_mixed = False
            self.update_cover_display(False)
            self._refresh_filename_clue_action()
            return
            
        self.clear_mb_fields() 
        self.album_session.selected_files_data = {}
        paths = []
        for item in items:
            path = os.path.join(self.music_dir, self.get_real_filename(item))
            paths.append(path)
            if path in self.album_session.all_files_data:
                metadata = self.album_session.all_files_data[path]
            else:
                metadata = AudioTagger(path).read_tags()
            self.album_session.selected_files_data[path] = metadata

        self.audio_player.load_track(paths[0])
            
        albums = list(set([self.album_session.selected_files_data[p].get("album", "").strip() for p in self.album_session.selected_files_data]))
        current_album = albums[0] if len(albums) == 1 else "<Multiple>"
        
        if hasattr(self, 'chk_auto_clear_mbid') and self.chk_auto_clear_mbid.isChecked():
            if self.album_session.last_selected_album is not None and current_album != self.album_session.last_selected_album:
                self.input_mbid.clear()
                self.input_apple_collection_id.clear()
                
        self.album_session.last_selected_album = current_album

        for key, cb in self.inputs.items():
            cb.clear()
            values = list(set([self.album_session.selected_files_data[p].get(key, "") for p in self.album_session.selected_files_data]))
            if len(values) == 1: 
                cb.addItems([values[0], "<留白>"])
                self.update_combo_text(cb, values[0])
            else:
                cb.addItems(["<保留>", "<留白>"])
                for v in values:
                    if v: cb.addItem(v)
                self.update_combo_text(cb, "<保留>")

            if key == "comment":
                has_163 = any("163 key" in str(v).lower() for v in values if v)
                if has_163:
                    self.update_combo_text(cb, "<留白>")
                    self.mb_status_label.setText("💩 侦测到网易云 163key 污染，已为您默认选中清除！")
                    self.mb_status_label.setStyleSheet("color: #e74c3c; font-size: 12pt; font-weight: bold; padding: 5px;")

        self.load_locks_for_selection(paths)

        covers = [self.album_session.selected_files_data[p].get("cover_data") for p in self.album_session.selected_files_data]
        if all(c == covers[0] for c in covers):
            self.current_cover_data = covers[0]
            self._cover_is_mixed = False
            self.update_cover_display(multiple_different=False)
        else:
            self.current_cover_data = None
            self._cover_is_mixed = True
            self.update_cover_display(multiple_different=True)

        self.cover_modified_in_batch = False
        self._refresh_filename_clue_action()

        if len(paths) == 1 and paths[0] in self.api_cache and not self.chk_no_cache.isChecked():
            cache_obj = self.api_cache[paths[0]]
            api_data = self._apply_album_source_preference(paths[0], cache_obj["api_data"])
            self.last_fetch_success = True
            self.mb_status_label.setText(cache_obj["status_text"])
            self.mb_status_label.setStyleSheet("color: #27ae60; font-size: 12pt; font-weight: bold; padding: 5px;")
            self.mb_score_label.setText(cache_obj["score_text"])
            self.last_api_raw_json_list = cache_obj["raw_json_list"]
            self._fill_mb_panel(api_data)
            self.current_api_file_path = paths[0]
            self._set_available_sources(
                api_data.get("source_results", {}),
                api_data.get("metadata_source", "")
            )

    def do_fetch(self, mode, is_auto=False):
        if (
            self._save_in_progress
            or self._undo_in_progress
            or self.is_metadata_search_running()
            or self.is_filename_clue_analysis_running()
        ):
            return
        self.is_auto_fetch = is_auto 
        items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        if not items: return
        if len(items) > 1 and not is_auto:
            if QMessageBox.question(self, "警告", "多选模式下检索会给所有曲目赋相同数据，是否继续？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No: return

        title = self.inputs["title"].currentText().strip()
        artist = self.inputs["artist"].currentText().split("\\\\")[0].strip()
        album = self.inputs["album"].currentText().strip()
        local_track = self.inputs["track"].currentText().strip()
        local_disc = self.inputs["disc"].currentText().strip()
        mbid_override = self.input_mbid.text().strip()
        apple_collection_id_override = self._extract_apple_collection_id(self.input_apple_collection_id.text())
        no_cache = self.chk_no_cache.isChecked()

        if self.input_apple_collection_id.text().strip() and not apple_collection_id_override:
            if not is_auto:
                QMessageBox.warning(self, "Apple Music ID 无效", "请输入数字专辑 ID，或完整的 Apple Music 专辑网址。")
            return
        
        target_path = os.path.join(self.music_dir, self.get_real_filename(items[0]))
        
        if not mbid_override and not apple_collection_id_override and title in ["", "<保留>", "<留白>"]: 
            if not is_auto: QMessageBox.warning(self, "提示", "未指定 MBID 或 Apple 专辑 ID 时，必须填写【标题】！")
            return
        if apple_collection_id_override and title in ["", "<保留>", "<留白>"] and not re.search(r"\d+", local_track):
            if not is_auto:
                QMessageBox.warning(self, "缺少曲目线索", "指定 Apple 专辑 ID 时，请至少填写【标题】或【音轨号】以定位专辑内曲目。")
            return
            
        self.overlay.start()
        self.mb_score_label.setText("")
        self.mb_status_label.setStyleSheet("color: #e67e22; font-size: 12pt; font-weight: bold; padding: 5px;")
        
        local_metadata = {
            key: value
            for key, value in self.album_session.selected_files_data.get(target_path, {}).items()
            if key != "cover_data"
        }
        self._metadata_search_generation += 1
        request_id = self._metadata_search_generation
        self._active_metadata_search_id = request_id
        self.worker = FetchWorker(
            title, artist, album, local_track, local_disc, mbid_override, apple_collection_id_override,
            mode, target_path, no_cache, local_metadata,
            request_id=request_id,
            cancel_event=threading.Event(),
        )
        self.worker.progress_sig.connect(self.update_fetch_progress)
        self.worker.finished_sig.connect(self.on_fetch_finished)
        self.worker.finished.connect(self._cleanup_metadata_worker)
        self.worker.start()

    def update_fetch_progress(self, text):
        self.mb_status_label.setText(text)

    def on_fetch_finished(self, success, api_data, raw_json_list, msg, file_path, request_id, cancelled):
        if request_id != self._active_metadata_search_id:
            self._cancelled_metadata_search_ids.discard(request_id)
            return
        was_cancelled = request_id in self._cancelled_metadata_search_ids
        if request_id == self._active_metadata_search_id:
            self._active_metadata_search_id = None
        self._cancelled_metadata_search_ids.discard(request_id)
        if cancelled or was_cancelled:
            self.pending_cover_fetch = False
            for button in self._search_buttons:
                button.setEnabled(True)
            self.mb_status_label.setText("元数据搜索已取消")
            self.mb_status_label.setStyleSheet("color: #7f8c8d; font-size: 12pt; font-weight: bold; padding: 5px;")
            return
        self.last_api_raw_json_list = raw_json_list
        
        if success:
            self.last_fetch_success = True
            api_data = self._apply_album_source_preference(file_path, api_data, establish_default=True)
            source = api_data.get("metadata_source", "信息源")
            status_text = f"✅ 已采用 {source}（Enter 应用）"
            self.mb_status_label.setText(status_text)
            self.mb_status_label.setStyleSheet("color: #27ae60; font-size: 12pt; font-weight: bold; padding: 5px;")
            
            score = api_data.get("match_score", 0.0)
            score_text = ""
            if api_data.get("is_direct_mbid"): score_text = "Match Confidence: 100% (Direct MBID)"
            elif api_data.get("is_direct_apple_collection_id"): score_text = "Match Confidence: 100% (Direct Apple Collection ID)"
            elif score > 0.0: score_text = f"Match Confidence: {int(score * 100)}%"
            else: score_text = "Album Match Confidence: N/A"
            if api_data.get("source_comparison"):
                score_text += f"  |  {api_data['source_comparison']}"
            self.mb_score_label.setText(score_text)
                 
            self._fill_mb_panel(api_data)
            self._set_available_sources(api_data.get("source_results", {}), api_data.get("metadata_source", ""))
            
            self.api_cache[file_path] = {
                "api_data": api_data,
                "raw_json_list": raw_json_list,
                "status_text": status_text,
                "score_text": score_text
            }
            self.current_api_file_path = file_path
            
        else:
            self.last_fetch_success = False
            self._set_available_sources({}, "")
            self.mb_status_label.setText(f"❌ {msg}")
            self.mb_score_label.setText("")
            self.mb_status_label.setStyleSheet("color: #e74c3c; font-size: 12pt; font-weight: bold; padding: 5px;")
            if not getattr(self, "is_auto_fetch", False):
                QMessageBox.information(self, "检索失败", msg)
                
        if getattr(self, "pending_cover_fetch", False):
            self.pending_cover_fetch = False
            if success:
                artist = self.inputs["artist"].currentText().split("\\\\")[0].strip()
                album = self.inputs["album"].currentText().strip()
                source_results = api_data.get("source_results", {})
                release_id = source_results.get("MusicBrainz", {}).get("release_id", "") or api_data.get("release_id", "")
                apple_cover_data = source_results.get("Apple Music", {})
                if not apple_cover_data and api_data.get("metadata_source") == "Apple Music":
                    apple_cover_data = api_data
                self._start_cover_fetch_worker(artist, album, release_id, apple_cover_data)
            else:
                QMessageBox.warning(self, "前置检索中断", f"未能补全该专辑的 MBID，无法向 MusicBrainz 官方库查询。\n你仍可尝试搜图，但将只有 Apple Music 可用。")

    def _cleanup_metadata_worker(self):
        worker = self.sender()
        if worker:
            worker.deleteLater()
        if getattr(self, "worker", None) is worker:
            self.worker = None
            if not self.is_cover_search_running():
                self.overlay.stop()

    def _set_available_sources(self, source_results, selected_source):
        self.available_source_results = source_results or {}
        self._current_metadata_source = selected_source or ""
        self.btn_use_mb_source.setEnabled("MusicBrainz" in self.available_source_results)
        self.btn_use_apple_source.setEnabled("Apple Music" in self.available_source_results)
        for button, source in ((self.btn_use_mb_source, "MusicBrainz"), (self.btn_use_apple_source, "Apple Music")):
            button.setText(("✓ " if source == selected_source else "采用 ") + source)

    def select_metadata_source(self, source):
        data = getattr(self, "available_source_results", {}).get(source)
        if not data or self._undo_in_progress or self.is_metadata_search_running():
            return
        editor_before = self._capture_editor_state()
        session_before = self._capture_source_session_patch()
        # Preserve the complete source map, because the user may switch back.
        selected = dict(data)
        selected["source_results"] = self.available_source_results
        selected["source_comparison"] = "；".join(
            f"{name} {result.get('source_quality_score', result.get('match_score', 0.0)):.0%}"
            for name, result in self.available_source_results.items()
        )
        self._fill_mb_panel(selected)
        self._current_metadata_source = source
        self._set_available_sources(self.available_source_results, source)
        self.album_source_preferences[self._album_source_key(self.current_api_file_path)] = source
        self.mb_status_label.setText(f"✅ 已采用 {source}")
        self.mb_status_label.setStyleSheet("color: #27ae60; font-size: 12pt; font-weight: bold; padding: 5px;")
        self.mb_score_label.setText(f"Match Confidence: {selected.get('match_score', 0.0):.0%}  |  {selected['source_comparison']}")
        cache_obj = self.api_cache.get(getattr(self, "current_api_file_path", ""))
        if cache_obj is not None:
            cache_obj["api_data"] = selected
            cache_obj["status_text"] = self.mb_status_label.text()
            cache_obj["score_text"] = self.mb_score_label.text()
        editor_after = self._capture_editor_state()
        self.undo_manager.push(EditorUndoCommand(
            description="撤销元数据来源切换",
            before=editor_before,
            after=editor_after,
            affected_paths=editor_before.selected_paths,
            session_before=session_before.detached_copy(),
            session_after=self._capture_source_session_patch().detached_copy(),
        ))
        self._editor_baseline = editor_after

    def _fill_mb_panel(self, d):
        for key, line_edit in self.mb_inputs.items():
            value = str(d.get(key, "") or "")
            line_edit.setText(value)
            if key in d:
                self._apply_result_comparison_style(key, value)
            else:
                self._reset_result_field_style(line_edit)
                line_edit.setToolTip("")
        
        if d.get("medium_count", 1) > 1:
            self.mb_labels["disc"].setText(f"碟号 (Disc)  [共{d['medium_count']}碟]")
            self.mb_labels["disc"].setStyleSheet("font-size: 10pt; font-weight: bold; color: #d35400; padding-left: 10px;")
        else:
            self.mb_labels["disc"].setText("碟号 (Disc)")
            self.mb_labels["disc"].setStyleSheet("font-size: 10pt; font-weight: bold; color: #2c3e50; padding-left: 10px;")
                
        for le in self.mb_inputs.values():
            le.setCursorPosition(0)

    def _apply_result_comparison_style(self, key, new_value):
        line_edit = self.mb_inputs[key]
        local_values = [
            str(data.get(key, "") or "")
            for data in self.album_session.selected_files_data.values()
        ]
        base_style = "color: #34495e; padding: 6px; font-size: 10pt; border-radius: 4px;"
        if not local_values:
            self._reset_result_field_style(line_edit)
            line_edit.setToolTip(new_value)
            return

        ratios = [difflib.SequenceMatcher(None, value, new_value).ratio() for value in local_values]
        is_exact = all(value == new_value for value in local_values)
        similarity = sum(ratios) / len(ratios)
        if is_exact:
            line_edit.setStyleSheet(f"QLineEdit {{ background-color: #d5f5e3; {base_style} border: 1px solid #27ae60; }}")
            line_edit.setToolTip(f"本地信息完全一致\n本地: {local_values[0]}")
            return

        difference = 1.0 - similarity
        green = round(244 - 92 * difference)
        blue = round(242 - 92 * difference)
        background = f"#ff{green:02x}{blue:02x}"
        line_edit.setStyleSheet(f"QLineEdit {{ background-color: {background}; {base_style} border: 1px solid #e57373; }}")
        local_text = local_values[0] if len(set(local_values)) == 1 else "多首歌曲的本地值不同"
        line_edit.setToolTip(f"本地: {local_text}\n字符相似度: {similarity:.0%}")

    @staticmethod
    def _reset_result_field_style(line_edit):
        line_edit.setStyleSheet(
            "QLineEdit { background-color: #ecf0f1; color: #34495e; padding: 6px; "
            "font-size: 10pt; border: 1px solid #dcdde1; border-radius: 4px; }"
        )

    def advance_to_next_item(self, current_items, auto_search=False):
        if not current_items: return
        current_tracks = [item for item in current_items if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        if not current_tracks:
            return
        anchor_item = self.file_list.currentItem()
        if anchor_item not in current_tracks:
            anchor_item = max(current_tracks, key=self.file_list.row)
        anchor_y = self.file_list.visualItemRect(anchor_item).top()
        highest_row = max(self.file_list.row(item) for item in current_tracks)
        next_row = highest_row + 1
        
        while next_row < self.file_list.count():
            item = self.file_list.item(next_row)
            if item.data(Qt.ItemDataRole.UserRole + 2) == "track":
                self._selection_prompt_suppressed = True
                self.file_list.blockSignals(True)
                try:
                    self.file_list.clearSelection()
                    item.setSelected(True)
                    self.file_list.setCurrentItem(item)
                finally:
                    self.file_list.blockSignals(False)
                try:
                    self.on_file_selected()
                finally:
                    self._selection_prompt_suppressed = False
                QTimer.singleShot(0, lambda target=item, y=anchor_y: self._align_item_to_viewport_y(target, y))
                if auto_search:
                    QTimer.singleShot(250, lambda: self.do_fetch("auto", is_auto=True))
                return
            next_row += 1

    def _align_item_to_viewport_y(self, item, target_y):
        if self.file_list.row(item) < 0:
            return
        current_y = self.file_list.visualItemRect(item).top()
        self.file_list.smooth_scroll_by(current_y - target_y)

    def closeEvent(self, event):
        if (
            (getattr(self, "save_worker", None) and self.save_worker.isRunning())
            or (getattr(self, "restore_worker", None) and self.restore_worker.isRunning())
        ):
            event.ignore()
            return
        if (
            self.is_metadata_search_running()
            or self.is_cover_search_running()
            or self.is_filename_clue_analysis_running()
        ):
            self.cancel_active_search()
            event.ignore()
            return
        super().closeEvent(event)

    def skip_current_files(self):
        if (
            self._save_in_progress
            or self._undo_in_progress
            or self.is_metadata_search_running()
            or self.is_filename_clue_analysis_running()
        ):
            return
        items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        for item in items:
            base = self.get_real_filename(item)
            item.setData(Qt.ItemDataRole.UserRole + 1, "skip")
        self.update_list_display()
        self.advance_to_next_item(items, auto_search=False)

    def save_current_files(self):
        if self._save_in_progress or self._undo_in_progress:
            return
        self._execute_save(apply_mb=True)

    def save_only_current_files(self):
        if self._save_in_progress or self._undo_in_progress:
            return
        self._execute_save(apply_mb=False)

    def save_left_only_and_stay(self):
        if self._save_in_progress or self._undo_in_progress:
            return
        self._execute_save(apply_mb=False, advance=False)

    def _execute_save(self, apply_mb=True, advance=True):
        if (
            self._save_in_progress
            or self._undo_in_progress
            or self.is_metadata_search_running()
            or self.is_filename_clue_analysis_running()
        ):
            return
        items = [item for item in self.file_list.selectedItems() if item.data(Qt.ItemDataRole.UserRole + 2) == "track"]
        if not items:
            return
        
        protected_fields = {"title", "artist", "track", "disc"}
        if apply_mb and self.last_fetch_success:
            for key, cb in self.inputs.items():
                if self.checkboxes[key].isChecked() and not self.lock_btns[key].isChecked():
                    if len(items) > 1 and key in protected_fields:
                        continue
                    mb_val = self.mb_inputs[key].text()
                    if mb_val: self.update_combo_text(cb, mb_val)

        field_updates = {}
        checked_fields = set()
        for key, cb in self.inputs.items():
            if not self.checkboxes[key].isChecked():
                continue
            checked_fields.add(key)
            ui_val = cb.currentText()
            if ui_val == "<保留>":
                continue
            field_updates[key] = "" if ui_val == "<留白>" else ui_val

        selected_paths = [os.path.join(self.music_dir, self.get_real_filename(item)) for item in items]
        track_items = [
            self.file_list.item(index)
            for index in range(self.file_list.count())
            if self.file_list.item(index).data(Qt.ItemDataRole.UserRole + 2) == "track"
        ]
        track_items_by_path = {
            os.path.join(self.music_dir, self.get_real_filename(item)): item
            for item in track_items
        }
        session_state = self.album_session.export_state()
        plan = build_save_plan(SavePlanRequest(
            selected_paths=selected_paths,
            field_updates=field_updates,
            checked_fields=frozenset(checked_fields),
            cover_modified=self.cover_modified_in_batch,
            cover_data=self.current_cover_data,
            all_files_data=session_state["all_files_data"],
            selected_files_data=session_state["selected_files_data"],
            locks_data=session_state["locks_data"],
            album_sync_keys=session_state["album_sync_keys"],
            virtual_album_map=session_state["virtual_album_map"],
            track_paths=list(track_items_by_path),
        ))
        if not plan.items:
            return
        self._save_in_progress = True
        self._save_context = {
            "plan": plan,
            "items": items,
            "track_items_by_path": track_items_by_path,
            "advance": advance,
            "field_updates": field_updates,
            "selected_paths": tuple(selected_paths),
        }
        self._set_save_controls_enabled(False)
        self.save_progress_dialog = QProgressDialog("正在准备保存...", None, 0, len(plan.items), self)
        self.save_progress_dialog.setWindowTitle("正在保存元数据")
        self.save_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.save_progress_dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.save_progress_dialog.setCancelButton(None)
        self.save_progress_dialog.setMinimumDuration(0)
        self.save_progress_dialog.setAutoClose(False)
        self.save_progress_dialog.setAutoReset(False)
        self.save_progress_dialog.setValue(0)
        self.save_progress_dialog.show()
        self._center_dialog_on_window(self.save_progress_dialog)
        self.save_worker = SaveWorker(
            plan,
            service=self._save_service_factory(),
            parent=self,
        )
        self.save_worker.progress_sig.connect(self._update_save_progress)
        self.save_worker.finished_sig.connect(self._finish_save)
        self.save_worker.failed_sig.connect(self._handle_save_worker_failure)
        self.save_worker.finished.connect(self._cleanup_save_worker)
        self.save_worker.start()

    def _set_save_controls_enabled(self, enabled):
        for button in (self.btn_skip, self.btn_save_apply, self.btn_save_only):
            button.setEnabled(enabled)
        search_enabled = enabled and not (
            self.is_metadata_search_running()
            or self.is_cover_search_running()
            or self.is_filename_clue_analysis_running()
        )
        for button in self._search_buttons:
            button.setEnabled(search_enabled)

    def _update_save_progress(self, current, total, filename, kind):
        dialog = getattr(self, "save_progress_dialog", None)
        if not dialog:
            return
        operation = "专辑同步" if kind == "sync" else "直接保存"
        if kind == "restore":
            operation = (
                "重做保存"
                if getattr(self, "_undo_is_redo", False)
                else "撤销保存"
            )
        dialog.setMaximum(max(1, total))
        dialog.setValue(current - 1)
        label = dialog.fontMetrics().elidedText(filename, Qt.TextElideMode.ElideMiddle, 380)
        dialog.setLabelText(f"正在{operation} ({current}/{total}):\n{label}")

    def _handle_save_worker_failure(self, error):
        self._finish_save(None, error)

    def _finish_save(self, result, worker_error=""):
        context = getattr(self, "_save_context", {})
        plan = context.get("plan")
        try:
            self._close_operation_progress_dialog()
            if result is None:
                QMessageBox.warning(self, "保存失败", worker_error or "保存任务意外终止。")
                return
            for path, metadata in result.saved_metadata.items():
                self.album_session.all_files_data[path] = metadata
            self._sync_selected_metadata_after_write(result.saved_metadata)
            self._invalidate_metadata_caches(result.saved_metadata)
            self._refresh_sortable_metadata(preserve_album_order=True)
            changed_album_paths = {
                item.path
                for item in result.successful_items
                if "album" in item.metadata
            }
            self._refresh_saved_album_headers(
                changed_album_paths, mark_modified=True
            )

            saved_paths = {item.path for item in result.successful_items if item.kind == "primary"}
            track_items_by_path = context["track_items_by_path"]
            for item in result.successful_items:
                if item.kind == "primary":
                    track_items_by_path[item.path].setData(Qt.ItemDataRole.UserRole + 1, "done")
                elif item.kind == "sync":
                    track_items_by_path[item.path].setData(Qt.ItemDataRole.UserRole + 1, "sync")

            cleaned_163key = any(
                "163 key" in str(self.album_session.selected_files_data.get(item.path, {}).get("comment", "")).lower()
                and item.metadata.get("comment") == ""
                for item in plan.items
                if item.kind == "primary"
            )
            failed_files = [
                f"{os.path.basename(path)}: {result.errors[path]}"
                for path in result.failed_files
            ]

            self.update_list_display()
            self.setWindowTitle(APP_NAME)

            if cleaned_163key:
                self.mb_status_label.setText("✨ 网易云 163key 专属垃圾已被彻底清理！")
                self.mb_status_label.setStyleSheet("color: #27ae60; font-size: 12pt; font-weight: bold; padding: 5px;")

            if failed_files:
                self.mb_status_label.setText(f"⚠️ 已保存 {len(saved_paths)} 首，{len(failed_files)} 首失败")
                self.mb_status_label.setStyleSheet("color: #e67e22; font-size: 12pt; font-weight: bold; padding: 5px;")
                QMessageBox.warning(self, "部分文件未保存", "\n".join(failed_files))

            successful_primary_items = [
                item for item in result.successful_items if item.kind == "primary"
            ]
            self._flash_saved_fields(successful_primary_items)

            successful_changes = []
            for item in result.successful_items:
                before_metadata = result.before_metadata.get(item.path)
                after_metadata = result.saved_metadata.get(item.path)
                if before_metadata is None or after_metadata is None:
                    continue
                successful_changes.append(SavedFileChange(
                    path=item.path,
                    before=ManagedMetadataSnapshot.from_metadata(before_metadata),
                    after=ManagedMetadataSnapshot.from_metadata(after_metadata),
                ))
            if successful_changes:
                successful_paths = [change.path for change in successful_changes]
                self.undo_manager.discard_editor_commands_for_paths(successful_paths)
                self.undo_manager.push(
                    SavedMetadataTransaction.create(successful_changes)
                )

            if set(context.get("selected_paths", ())).issubset(result.saved_metadata):
                self.cover_modified_in_batch = False
                self._selection_metadata_baseline = self._capture_selection_metadata_state()
                self._editor_baseline = self._capture_editor_state()

            if context["advance"] and saved_paths:
                self.advance_to_next_item(context["items"], auto_search=True)
        finally:
            self._save_in_progress = False
            self._set_save_controls_enabled(True)
            self._save_context = {}

    def _cleanup_save_worker(self):
        worker = self.sender()
        if worker:
            worker.deleteLater()
        if getattr(self, "save_worker", None) is worker:
            self.save_worker = None

    def _flash_saved_fields(self, successful_primary_items):
        if not successful_primary_items:
            return
        fields = set()
        for item in successful_primary_items:
            fields.update(item.metadata)
        for key in fields:
            widget = self.inputs.get(key)
            if widget:
                self._flash_field(widget)

    def _flash_field(self, widget):
        old_animation = self._field_flash_animations.pop(widget, None)
        if old_animation:
            old_animation.stop()
            old_animation.deleteLater()
        key = next((name for name, value in self.inputs.items() if value is widget), None)
        if key is None:
            return
        is_locked = self.lock_btns[key].isChecked()
        base_style = self.cb_style_locked if is_locked else self.cb_style_normal
        animation = QVariantAnimation(widget)
        animation.setStartValue(QColor("#c9f3d2"))
        animation.setEndValue(QColor("#e8f4f8") if is_locked else QColor("#ffffff"))
        animation.setDuration(520)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def update(color, target=widget):
            target.setStyleSheet(f"{base_style}\nQComboBox {{ background-color: {color.name()}; }}")

        def finish(target=widget, anim=animation):
            current_key = next((name for name, value in self.inputs.items() if value is target), None)
            target.setStyleSheet(
                self.cb_style_locked if current_key and self.lock_btns[current_key].isChecked()
                else self.cb_style_normal
            )
            self._field_flash_animations.pop(target, None)
            anim.deleteLater()

        animation.valueChanged.connect(update)
        animation.finished.connect(finish)
        self._field_flash_animations[widget] = animation
        animation.start()
