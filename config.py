# -*- coding: utf-8 -*-
import os
import sys
import json

# 【新增打包路径处理魔法】
def get_application_path():
    """获取程序运行时的当前真实目录（兼容 PyInstaller 打包模式）"""
    if getattr(sys, 'frozen', False):
        # 如果是打包后的 exe 运行，返回 exe 所在的目录
        return os.path.dirname(sys.executable)
    else:
        # 如果是 python 脚本运行，返回当前脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))


def get_bundled_resource_path(*parts):
    """Resolve a read-only resource in source and PyInstaller builds."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, *parts)

# 现在的路径全基于真实运行目录计算
APP_DIR = get_application_path()
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
APP_ICON_PATH = get_bundled_resource_path("assets", "app_icon.png")

DEFAULT_SETTINGS = {
    "VIP_DOWNLOAD_DIR": r"E:\CloudMusic\VipSongsDownload",
    "MAIN_MUSIC_DIR": r"E:\CloudMusic",
    "DEEPSEEK_API_KEY": ""
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

APP_SETTINGS = load_settings()

APP_NAME = "Music Metadata Perfecter"
APP_VERSION = "2026.07.29.4"
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
USER_AGENT_APP = "MyMusicOrganizer"
USER_AGENT_VERSION = "6.0"
USER_AGENT_CONTACT = "xjr353171020@126.com"
