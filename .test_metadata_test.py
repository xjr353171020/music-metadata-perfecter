import os
from mutagen.id3 import ID3, TPE1, TIT2, ID3NoHeaderError
from mutagen.flac import FLAC

def test_multi_artist_mp3(file_path, artist_list):
    print(f"--- 测试 MP3 ---")
    try:
        audio = ID3(file_path)
    except ID3NoHeaderError:
        audio = ID3()
    
    # 写入标题，encoding=3 代表使用 UTF-8 编码
    audio.add(TIT2(encoding=3, text=["测试多艺术家 MP3"]))
    
    # 【核心验证点】：在 TPE1 (艺术家) 帧中，直接传入包含多个字符串的列表
    audio.add(TPE1(encoding=3, text=artist_list))
    
    # 【核心验证点】：强制保存为 ID3v2.4 版本。
    # ID3v2.4 是对多值标签支持最好的版本，现代播放器（如 foobar2000）完美兼容，
    # 它会自动用 Null 字符 (\x00) 将你传入的列表分隔开，避免使用“/”造成的名称冲突。
    audio.save(file_path, v2_version=4)
    print(f"✅ MP3 写入成功。已写入: {artist_list}\n")


def test_multi_artist_flac(file_path, artist_list):
    print(f"--- 测试 FLAC ---")
    audio = FLAC(file_path)
    
    audio["title"] = ["测试多艺术家 FLAC"]
    
    # FLAC 的 Vorbis Comment 原生支持给同一个键赋一个列表
    # 它会在底层自动生成多个 ARTIST 标签
    audio["artist"] = artist_list
    
    audio.save()
    print(f"✅ FLAC 写入成功。已写入: {artist_list}\n")


if __name__ == "__main__":
    # ==========================================
    # 请把下面这两个路径改成你的“小白鼠”测试文件路径！
    # ==========================================
    test_mp3_path = r"Wendy Carlos,Al Bowlly - It's All Forgotten Now.mp3" 
    test_flac_path = r"seatrus,kuro,Halv - Quattro Elements Dimiourgia.flac"
    
    # 模拟我们从未来 UI 界面获取到的字符串，并用我们商量好的 "\\" 分割
    input_string = "Wendy Carlos\\\\Al Bowlly"
    
    # 将字符串分割为真实的 Python 列表: ['Wendy Carlos', 'Al Bowlly']
    artist_list = input_string.split("\\\\")
    print(f"准备写入的艺术家列表: {artist_list}\n")
    
    # 执行写入
    if os.path.exists(test_mp3_path):
        test_multi_artist_mp3(test_mp3_path, artist_list)
    else:
        print(f"❌ 找不到 MP3 测试文件: {test_mp3_path}")
        
    if os.path.exists(test_flac_path):
        test_multi_artist_flac(test_flac_path, artist_list)
    else:
        print(f"❌ 找不到 FLAC 测试文件: {test_flac_path}")

    print("🎉 测试执行完毕！")