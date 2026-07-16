# -*- coding: utf-8 -*-
import os
import re
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TCOM, TRCK, TPOS, TDRC, TCON, APIC, COMM, TXXX
from mutagen.flac import FLAC, Picture


MANAGED_TAG_FIELDS = (
    "title", "artist", "album", "album_artist", "composer",
    "track", "disc", "date", "genre", "comment",
)

try:
    from PIL import Image
    import io
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class AudioTagger:
    def __init__(self, file_path):
        self.file_path = file_path

    def _normalize_va(self, val):
        if not val: return ""
        if re.sub(r'[\.\s]', '', val).upper() == 'VA':
            return "Various Artists"
        return val

    def _get_id3_multi(self, tags, key):
        frames = tags.getall(key)
        if not frames:
            return ""
        values = []
        for frame in frames:
            if hasattr(frame, 'text'):
                for text in frame.text:
                    val = self._normalize_va(str(text).strip())
                    if val:
                        values.append(val)
        return "\\\\".join(values)

    def read_tags(self):
        data = {"title": "", "artist": "", "album": "", "album_artist": "", 
                "composer": "", "track": "", "disc": "", "date": "", 
                "genre": "", "comment": "", "cover_data": None}
        ext = os.path.splitext(self.file_path)[1].lower()
        
        if ext == ".mp3":
            try:
                audio = MP3(self.file_path, ID3=ID3)
                if audio.tags:
                    t = audio.tags
                    data["title"] = str(t.getall("TIT2")[0].text[0]) if t.getall("TIT2") else ""
                    data["artist"] = self._get_id3_multi(t, "TPE1")
                    data["album"] = self._normalize_va(str(t.getall("TALB")[0].text[0]) if t.getall("TALB") else "")
                    data["album_artist"] = self._get_id3_multi(t, "TPE2")
                    data["composer"] = self._get_id3_multi(t, "TCOM")
                    data["genre"] = self._get_id3_multi(t, "TCON")
                    data["track"] = str(t.getall("TRCK")[0].text[0]) if t.getall("TRCK") else ""
                    data["disc"] = str(t.getall("TPOS")[0].text[0]) if t.getall("TPOS") else ""
                    
                    # 【日期读取防御】：优先读取 v2.4 规范的 TDRC，找不到则降级尝试读取 v2.3 的 TYER
                    if t.getall("TDRC"):
                        data["date"] = str(t.getall("TDRC")[0].text[0])
                    elif t.getall("TYER"):
                        data["date"] = str(t.getall("TYER")[0].text[0])
                    else:
                        data["date"] = ""
                    
                    comments = []
                    for comm in t.getall("COMM"):
                        if hasattr(comm, 'text'): comments.extend(comm.text)
                    for txxx in t.getall("TXXX"):
                        if '163 key' in txxx.desc.lower():
                            comments.append(f"{txxx.desc}: {txxx.text[0]}")
                    data["comment"] = "\\\\".join([str(c) for c in comments if c])
                    
                    apic_frames = t.getall("APIC")
                    if apic_frames:
                        data["cover_data"] = apic_frames[0].data
            except Exception as e:
                print(f"读取 MP3 失败: {e}")
                
        elif ext == ".flac":
            try:
                audio = FLAC(self.file_path)
                data["title"] = audio.get("title", [""])[0]
                data["album"] = self._normalize_va(audio.get("album", [""])[0])
                data["artist"] = "\\\\".join([self._normalize_va(str(x).strip()) for x in audio.get("artist", []) if str(x).strip()])
                data["album_artist"] = "\\\\".join([self._normalize_va(str(x).strip()) for x in audio.get("albumartist", []) if str(x).strip()])
                data["composer"] = "\\\\".join([self._normalize_va(str(x).strip()) for x in audio.get("composer", []) if str(x).strip()])
                data["genre"] = "\\\\".join([self._normalize_va(str(x).strip()) for x in audio.get("genre", []) if str(x).strip()])
                data["track"] = audio.get("tracknumber", [""])[0]
                data["disc"] = audio.get("discnumber", [""])[0]
                
                # 【日期读取防御】：优先读标准 DATE，若被非常规工具写为 YEAR 也可兼容
                data["date"] = audio.get("date", [""])[0] or audio.get("year", [""])[0]
                
                comments = []
                comments.extend(audio.get("comment", []))
                comments.extend(audio.get("description", []))
                for k, v in audio.items():
                    if '163 key' in k.lower():
                        comments.extend(v)
                data["comment"] = "\\\\".join([str(c) for c in comments if c])
                
                if audio.pictures:
                    data["cover_data"] = audio.pictures[0].data
            except Exception as e:
                print(f"读取 FLAC 失败: {e}")
                
        return data

    def read_managed_tags(self):
        """Read a reversible snapshot and surface format/read failures."""
        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".mp3":
            MP3(self.file_path, ID3=ID3)
        elif ext == ".flac":
            FLAC(self.file_path)
        else:
            raise ValueError(f"Unsupported audio format: {ext}")
        return self.read_tags()

    def update_tags(self, new_data):
        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".mp3":
            self._update_mp3(new_data)
        elif ext == ".flac":
            self._update_flac(new_data)

    def restore_managed_tags(self, snapshot):
        """Replace every managed field while preserving unrelated tags."""
        if hasattr(snapshot, "restore_payload"):
            payload = snapshot.restore_payload()
        else:
            payload = dict(snapshot)
            if "has_cover" in payload:
                payload["cover_data"] = (
                    payload.get("cover_data") if payload["has_cover"] else None
                )

        missing = [key for key in MANAGED_TAG_FIELDS if key not in payload]
        if missing or "cover_data" not in payload:
            raise ValueError(
                "Managed restore requires all fields and an explicit cover state: "
                + ", ".join(missing or ["cover_data"])
            )

        exact_payload = {
            key: str(payload.get(key, "") or "")
            for key in MANAGED_TAG_FIELDS
        }
        exact_payload["cover_data"] = payload.get("cover_data")
        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".mp3":
            self._update_mp3(exact_payload)
        elif ext == ".flac":
            self._update_flac(exact_payload, raise_errors=True)
        else:
            raise ValueError(f"Unsupported audio format: {ext}")

    replace_managed_tags = restore_managed_tags

    def _update_mp3(self, new_data):
        try:
            audio = MP3(self.file_path, ID3=ID3)
        except Exception:
            audio = MP3(self.file_path)
            audio.add_tags()
            
        if audio.tags is None: audio.add_tags()
        t = audio.tags

        key_map = {
            "title": (TIT2, "TIT2"), "artist": (TPE1, "TPE1"),
            "album": (TALB, "TALB"), "album_artist": (TPE2, "TPE2"),
            "composer": (TCOM, "TCOM"), "track": (TRCK, "TRCK"),
            "disc": (TPOS, "TPOS"), "date": (TDRC, "TDRC"),
            "genre": (TCON, "TCON")
        }

        for key, (frame_class, frame_key) in key_map.items():
            if key in new_data:
                val = str(new_data[key])
                t.delall(frame_key)
                
                # 【MP3 日期写入防御】：为了完美兼容包含日期的 ISO 标准，并防止幽灵标签重影
                # 当写入 ID3v2.4 的 TDRC 时，必须主动铲除 ID3v2.3 遗留下来的 TYER(年)、TDAT(日) 和 TORY(原发行年份)
                if key == "date":
                    t.delall("TYER")
                    t.delall("TDAT")
                    t.delall("TORY")
                    
                if val:
                    if key in ["artist", "album_artist", "composer", "genre"]:
                        values = [v.strip() for v in val.split("\\\\") if v.strip()]
                        t.add(frame_class(encoding=3, text=values))
                    else:
                        t.add(frame_class(encoding=3, text=[val]))
                        
        if "comment" in new_data:
            val = str(new_data["comment"])
            t.delall("COMM")
            for txxx in t.getall("TXXX"):
                if '163 key' in txxx.desc.lower():
                    t.delall(f"TXXX:{txxx.desc}")
            if val:
                values = [v.strip() for v in val.split("\\\\") if v.strip()]
                for v in values:
                    t.add(COMM(encoding=3, lang='eng', desc='', text=[v]))

        if "cover_data" in new_data:
            t.delall("APIC")
            if new_data["cover_data"]:
                mime = "image/png" if new_data["cover_data"][:4] == b'\x89PNG' else "image/jpeg"
                t.add(APIC(
                    encoding=3, mime=mime, type=3, desc="Cover", data=new_data["cover_data"]
                ))
        audio.save()

    def _update_flac(self, new_data, raise_errors=False):
        try:
            audio = FLAC(self.file_path)
        except Exception as e:
            if raise_errors:
                raise
            print(f"打开 FLAC 失败: {e}")
            return
        
        key_map = {
            "title": "title", "artist": "artist", "album": "album",
            "album_artist": "albumartist", "composer": "composer",
            "track": "tracknumber", "disc": "discnumber", 
            "date": "date", "genre": "genre"
        }

        for key, flac_key in key_map.items():
            if key in new_data:
                val = str(new_data[key])
                
                # 【FLAC 日期写入防御】：为了防止有些流氓转换工具将标签写入非标准的 'year'，在更新 date 时进行顺手清理
                if key == "date" and "year" in audio:
                    del audio["year"]
                    
                if val:
                    if key in ["artist", "album_artist", "composer", "genre"]:
                        audio[flac_key] = [v.strip() for v in val.split("\\\\") if v.strip()]
                    else:
                        audio[flac_key] = [val]
                else:
                    if flac_key in audio:
                        del audio[flac_key]

        if "comment" in new_data:
            val = str(new_data["comment"])
            if "comment" in audio: del audio["comment"]
            if "description" in audio: del audio["description"]
            keys_to_delete = [k for k in audio.keys() if '163 key' in k.lower()]
            for k in keys_to_delete:
                del audio[k]
            if val:
                audio["description"] = [v.strip() for v in val.split("\\\\") if v.strip()]

        if "cover_data" in new_data:
            audio.clear_pictures()
            if new_data["cover_data"]:
                pic = Picture()
                pic.type = 3
                pic.mime = "image/png" if new_data["cover_data"][:4] == b'\x89PNG' else "image/jpeg"
                pic.desc = "Cover"
                pic.data = new_data["cover_data"]
                
                if HAS_PIL:
                    try:
                        img = Image.open(io.BytesIO(pic.data))
                        pic.width = img.width
                        pic.height = img.height
                        pic.depth = 24
                    except Exception:
                        pass
                audio.add_picture(pic)
        audio.save()
