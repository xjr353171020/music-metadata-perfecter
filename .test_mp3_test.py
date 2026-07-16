from mutagen.mp3 import MP3
from mutagen.id3 import APIC

audio = MP3("Roger Waters - 430AM (Apparently They Were Travelling Abroad) (Album Version).mp3")

for key, frame in audio.tags.items():
    if isinstance(frame, APIC):
        print(key)
        print("  MIME:", frame.mime)
        print("  图片类型:", frame.type)
        print("  描述:", frame.desc)
        print("  图片大小:", len(frame.data), "bytes")
    else:
        print(key, "=>", frame.text if hasattr(frame, "text") else frame)