# -*- coding: utf-8 -*-
import os
import sys
from config import APP_DIR, APP_ICON_PATH, APP_NAME, APP_SETTINGS, APP_VERSION
from startup_logging import configure_console_transcript

def main():
    configure_console_transcript(APP_DIR, APP_VERSION, APP_NAME)
    
    # 【修复】：彻底适配不同缩放比例 (125%, 150% 等)
    # PyQt6 默认内置并开启了高 DPI 支持。为确保在 Windows 等平台进行平滑缩放，
    # 避免非整数缩放(如 125%)时控件被意外裁剪或失真，配置全局环境变量。
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from main_window import MusicEditorWindow
    from mb_api import init_mb_api

    init_mb_api()

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(APP_ICON_PATH))
    
    # 【终极防线】：使用 StyleSheet 全局覆盖所有可能发生隐式调用的控件字体
    # 这样就算某个阴暗角落的组件获取不到 pointSize，CSS 也会强制赋予它 10pt (约 13px)
    app.setStyleSheet("* { font-family: 'Microsoft YaHei', 'Segoe UI'; font-size: 10pt; }")
    
    music_dir = APP_SETTINGS.get("MAIN_MUSIC_DIR", r"E:\CloudMusic")
    window = MusicEditorWindow(music_dir)
    window.showMaximized()
    window.start_initial_load()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
