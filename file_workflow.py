# -*- coding: utf-8 -*-
import os
import sys
import glob
import shutil
import subprocess

def get_bundled_exe_path():
    """
    智能获取 Ncm拖一拖.exe 的路径。
    如果是打包环境，它会被解压到 sys._MEIPASS 临时目录中；
    如果是开发环境，它就在当前脚本同级目录。
    """
    if getattr(sys, 'frozen', False):
        # 运行在 PyInstaller 打包后的环境中
        base_path = sys._MEIPASS
    else:
        # 运行在普通 Python 开发环境中
        base_path = os.path.dirname(os.path.abspath(__file__))
        
    return os.path.join(base_path, "Ncm拖一拖.exe")

def convert_ncm_files(ncm_dir):
    ncm_files = list_ncm_files(ncm_dir)
    if not ncm_files: 
        return False, "未找到需要转换的 .ncm 文件。"

    # 获取内嵌（或同级）的转换工具路径
    converter_exe = get_bundled_exe_path()

    if not os.path.exists(converter_exe):
        return False, f"严重错误：未找到内置转换工具！\n预期路径: {converter_exe}\n请确认打包时已将 Ncm拖一拖.exe 包含在内。"

    success_count = 0
    for ncm_file in ncm_files:
        try: 
            # Keep the source NCM until the user explicitly reviews and deletes it.
            subprocess.run([converter_exe, ncm_file], check=True)
            success_count += 1
        except Exception as e: 
            print(f"转换失败 [{os.path.basename(ncm_file)}]: {e}")
            
    return True, f"解密完成！共成功解密 {success_count} 个 NCM 文件，原始 NCM 已保留。"


def list_ncm_files(ncm_dir):
    if not ncm_dir or not os.path.isdir(ncm_dir):
        return []
    return sorted(glob.glob(os.path.join(ncm_dir, "*.ncm")), key=lambda path: os.path.basename(path).casefold())


def delete_ncm_files(ncm_files):
    deleted_count = 0
    failed_files = []
    for ncm_file in ncm_files:
        try:
            if os.path.exists(ncm_file):
                os.remove(ncm_file)
                deleted_count += 1
        except OSError as exc:
            failed_files.append(f"{os.path.basename(ncm_file)}: {exc}")

    if failed_files:
        return False, f"已删除 {deleted_count} 个 NCM 文件，{len(failed_files)} 个删除失败。\n" + "\n".join(failed_files)
    return True, f"已删除 {deleted_count} 个 NCM 文件。"

def get_unique_path(target_dir, file_name):
    base, ext = os.path.splitext(file_name)
    counter = 1
    new_name = file_name
    target_path = os.path.join(target_dir, new_name)
    while os.path.exists(target_path):
        new_name = f"{base} ({counter}){ext}"
        target_path = os.path.join(target_dir, new_name)
        counter += 1
    return target_path

def move_audio_files(source_dir, target_dir):
    if not os.path.exists(target_dir): 
        os.makedirs(target_dir)
        
    audio_files = []
    for ext in ("*.flac", "*.mp3"):
        audio_files.extend(glob.glob(os.path.join(source_dir, ext)))
        
    if not audio_files:
        return False, "下载目录中没有找到可以移动的音频文件。"
        
    moved_count = 0
    for file_path in audio_files:
        try: 
            shutil.move(file_path, get_unique_path(target_dir, os.path.basename(file_path)))
            moved_count += 1
        except Exception as e: 
            print(f"移动失败 [{os.path.basename(file_path)}]: {e}")
            
    return True, f"移动完成！共移动了 {moved_count} 个文件至主曲库。"

def clean_lrc_files(directories):
    deleted_count = 0
    for d in directories:
        if os.path.exists(d):
            lrc_files = glob.glob(os.path.join(d, "*.lrc"))
            for lrc in lrc_files:
                try:
                    os.remove(lrc)
                    deleted_count += 1
                except Exception as e:
                    print(f"删除歌词失败 [{os.path.basename(lrc)}]: {e}")
                    
    return True, f"歌词扫描完毕！共清理了 {deleted_count} 个无用的 .lrc 文件。"
