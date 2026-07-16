#!/usr/bin/env python3
"""
audio-meta-diff: deep metadata diff for MP3 ID3 and FLAC metadata blocks.

Usage:
  python audio_meta_diff.py ORIGINAL TAGGED
  python audio_meta_diff.py ORIGINAL TAGGED -o report.md --json report.json

Dependencies:
  - Python 3.8+
  - Optional: Pillow for embedded image dimensions (pip install pillow)

It does not decode/re-encode audio. It reads file bytes and reports:
  MP3: ID3v2 version/flags/frames/padding, ID3v1, APIC image hashes,
       audio-frame region hash, first MPEG header.
  FLAC: metadata block order/offset/size, STREAMINFO, Vorbis comments,
        PICTURE block fields/image hashes, PADDING, audio-region hash.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from PIL import Image  # type: ignore
    import io
except Exception:  # pragma: no cover
    Image = None
    io = None

FLAC_BLOCK_NAMES = {
    0: "STREAMINFO",
    1: "PADDING",
    2: "APPLICATION",
    3: "SEEKTABLE",
    4: "VORBIS_COMMENT",
    5: "CUESHEET",
    6: "PICTURE",
}

ID3_TEXT_ENCODINGS = {
    0: "ISO-8859-1",
    1: "UTF-16",
    2: "UTF-16BE",
    3: "UTF-8",
}

ID3V2_FLAG_NAMES = {
    2: {
        0x80: "unsynchronisation",
        0x40: "compression",
    },
    3: {
        0x80: "unsynchronisation",
        0x40: "extended_header",
        0x20: "experimental_indicator",
    },
    4: {
        0x80: "unsynchronisation",
        0x40: "extended_header",
        0x20: "experimental_indicator",
        0x10: "footer_present",
    },
}

PICTURE_TYPES = {
    0: "Other",
    1: "32x32 PNG file icon",
    2: "Other file icon",
    3: "Cover (front)",
    4: "Cover (back)",
    5: "Leaflet page",
    6: "Media",
    7: "Lead artist/performer/soloist",
    8: "Artist/performer",
    9: "Conductor",
    10: "Band/Orchestra",
    11: "Composer",
    12: "Lyricist/text writer",
    13: "Recording Location",
    14: "During recording",
    15: "During performance",
    16: "Movie/video screen capture",
    17: "A bright coloured fish",
    18: "Illustration",
    19: "Band/artist logotype",
    20: "Publisher/Studio logotype",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def hash_file(path: Path, algo: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_region(path: Path, start: int, end: Optional[int], algo: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algo)
    size = path.stat().st_size
    if end is None:
        end = size
    if start < 0 or end < start or end > size:
        raise ValueError(f"invalid region {start}:{end} for {path}")
    remaining = end - start
    with path.open("rb") as f:
        f.seek(start)
        while remaining:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


def synchsafe_to_int(b: bytes) -> int:
    if len(b) != 4:
        raise ValueError("synchsafe integer must be 4 bytes")
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def flags_to_names(flags: int, mapping: Dict[int, str]) -> List[str]:
    return [name for bit, name in mapping.items() if flags & bit]


def clean_text(s: str) -> str:
    return s.replace("\x00", "")


def decode_id3_text_payload(payload: bytes) -> Dict[str, Any]:
    if not payload:
        return {"encoding_byte": None, "encoding": None, "text": "", "values": []}

    enc = payload[0]
    data = payload[1:]
    encoding_name = ID3_TEXT_ENCODINGS.get(enc, f"unknown({enc})")

    try:
        if enc == 0:
            text = data.rstrip(b"\x00").decode("latin1", "replace")
        elif enc == 3:
            text = data.rstrip(b"\x00").decode("utf-8", "replace")
        elif enc == 1:
            while data.endswith(b"\x00\x00"):
                data = data[:-2]
            if len(data) % 2:
                data = data[:-1]
            text = data.decode("utf-16", "replace")
        elif enc == 2:
            while data.endswith(b"\x00\x00"):
                data = data[:-2]
            if len(data) % 2:
                data = data[:-1]
            text = data.decode("utf-16-be", "replace")
        else:
            text = data.decode("latin1", "replace")
    except Exception as e:
        text = f"<decode error: {e}>"

    values = [v for v in text.split("\x00") if v != ""]
    return {
        "encoding_byte": enc,
        "encoding": encoding_name,
        "text": clean_text(text),
        "values": [clean_text(v) for v in values],
    }


def find_id3_text_terminator(data: bytes, enc: int) -> Tuple[int, int]:
    """Return (end_index, after_terminator_index) inside data."""
    if enc in (1, 2):
        # UTF-16 terminator is two zero bytes. Use 2-byte alignment.
        for i in range(0, max(0, len(data) - 1), 2):
            if data[i : i + 2] == b"\x00\x00":
                return i, i + 2
        return len(data), len(data)
    i = data.find(b"\x00")
    if i == -1:
        return len(data), len(data)
    return i, i + 1


def image_info(image_bytes: bytes) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "bytes": len(image_bytes),
        "sha256": sha256_bytes(image_bytes),
        "prefix_hex": image_bytes[:16].hex(),
    }
    if Image is not None and io is not None:
        try:
            img = Image.open(io.BytesIO(image_bytes))
            info.update({"format": img.format, "width": img.width, "height": img.height, "mode": img.mode})
        except Exception as e:
            info["image_parse_error"] = str(e)
    return info


def read_prefix(path: Path, n: int) -> bytes:
    with path.open("rb") as f:
        return f.read(n)


def read_region(path: Path, start: int, length: int) -> bytes:
    with path.open("rb") as f:
        f.seek(start)
        return f.read(length)


def detect_kind(path: Path) -> str:
    magic = read_prefix(path, 16)
    if magic.startswith(b"fLaC"):
        return "flac"
    if magic.startswith(b"ID3") or path.suffix.lower() == ".mp3":
        return "mp3"
    # MPEG frame sync without ID3
    if len(magic) >= 2 and magic[0] == 0xFF and (magic[1] & 0xE0) == 0xE0:
        return "mp3"
    return "unknown"


def parse_id3v1(path: Path) -> Dict[str, Any]:
    size = path.stat().st_size
    if size < 128:
        return {"exists": False}
    tail = read_region(path, size - 128, 128)
    if not tail.startswith(b"TAG"):
        return {"exists": False}

    def field(start: int, end: int) -> str:
        return tail[start:end].rstrip(b"\x00 ").decode("latin1", "replace")

    # ID3v1.1 stores track at byte 126 if byte 125 is zero.
    track = tail[126] if tail[125] == 0 else None
    comment_end = 125 if track is not None else 127
    return {
        "exists": True,
        "title": field(3, 33),
        "artist": field(33, 63),
        "album": field(63, 93),
        "year": field(93, 97),
        "comment": field(97, comment_end),
        "track": track,
        "genre_byte": tail[127],
        "raw_sha256": sha256_bytes(tail),
    }


def parse_ape_markers(path: Path) -> Dict[str, Any]:
    # Lightweight detection only. Full APE parsing is outside the critical path here.
    size = path.stat().st_size
    window = min(size, 8192)
    head = read_prefix(path, window)
    tail = read_region(path, size - window, window) if size else b""
    return {
        "header_marker_offset": head.find(b"APETAGEX"),
        "footer_marker_offset_from_file_start": (size - window + tail.rfind(b"APETAGEX")) if tail.rfind(b"APETAGEX") != -1 else -1,
    }


def parse_mpeg_header(header: bytes) -> Optional[Dict[str, Any]]:
    if len(header) < 4:
        return None
    h = int.from_bytes(header[:4], "big")
    if ((h >> 21) & 0x7FF) != 0x7FF:
        return None

    version_id = (h >> 19) & 0x03
    layer_id = (h >> 17) & 0x03
    protection_bit = (h >> 16) & 0x01
    bitrate_index = (h >> 12) & 0x0F
    sample_rate_index = (h >> 10) & 0x03
    padding_bit = (h >> 9) & 0x01
    channel_mode_id = (h >> 6) & 0x03

    versions = {0: "MPEG 2.5", 2: "MPEG 2", 3: "MPEG 1"}
    layers = {1: "Layer III", 2: "Layer II", 3: "Layer I"}
    version = versions.get(version_id, "reserved")
    layer = layers.get(layer_id, "reserved")

    bitrate_tables = {
        ("MPEG 1", "Layer I"): [None, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, None],
        ("MPEG 1", "Layer II"): [None, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, None],
        ("MPEG 1", "Layer III"): [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None],
        ("MPEG 2", "Layer I"): [None, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, None],
        ("MPEG 2", "Layer II"): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
        ("MPEG 2", "Layer III"): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
        ("MPEG 2.5", "Layer I"): [None, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, None],
        ("MPEG 2.5", "Layer II"): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
        ("MPEG 2.5", "Layer III"): [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
    }
    sample_rates = {
        "MPEG 1": [44100, 48000, 32000, None],
        "MPEG 2": [22050, 24000, 16000, None],
        "MPEG 2.5": [11025, 12000, 8000, None],
    }
    channel_modes = ["Stereo", "Joint stereo", "Dual channel", "Mono"]

    bitrate_kbps = bitrate_tables.get((version, layer), [None] * 16)[bitrate_index]
    sample_rate = sample_rates.get(version, [None] * 4)[sample_rate_index]
    frame_length = None
    if bitrate_kbps and sample_rate:
        if layer == "Layer I":
            frame_length = int((12 * bitrate_kbps * 1000 / sample_rate + padding_bit) * 4)
        elif layer == "Layer III" and version != "MPEG 1":
            frame_length = int(72 * bitrate_kbps * 1000 / sample_rate + padding_bit)
        else:
            frame_length = int(144 * bitrate_kbps * 1000 / sample_rate + padding_bit)

    return {
        "header_hex": header[:4].hex(),
        "version": version,
        "layer": layer,
        "bitrate_kbps": bitrate_kbps,
        "sample_rate": sample_rate,
        "padding": padding_bit,
        "channel_mode": channel_modes[channel_mode_id],
        "protected_by_crc": protection_bit == 0,
        "frame_length": frame_length,
    }


def parse_id3v2(path: Path) -> Dict[str, Any]:
    prefix = read_prefix(path, 10)
    if not prefix.startswith(b"ID3"):
        return {"exists": False, "total_size": 0}

    major = prefix[3]
    revision = prefix[4]
    flags = prefix[5]
    body_size = synchsafe_to_int(prefix[6:10])
    total_size = 10 + body_size
    if major == 4 and (flags & 0x10):
        total_size += 10  # ID3v2.4 footer

    body = read_region(path, 10, body_size)
    out: Dict[str, Any] = {
        "exists": True,
        "version": f"ID3v2.{major}.{revision}",
        "major": major,
        "revision": revision,
        "flags": flags,
        "flag_names": flags_to_names(flags, ID3V2_FLAG_NAMES.get(major, {})),
        "size_excluding_header": body_size,
        "total_size": total_size,
        "header_hex": prefix.hex(),
        "raw_tag_sha256": hash_region(path, 0, total_size, "sha256"),
        "extended_header": {"exists": False},
        "frames": [],
        "padding_size": 0,
        "padding_all_zero": None,
    }

    pos = 0
    if flags & 0x40:
        if major == 3 and len(body) >= 4:
            ext_size = int.from_bytes(body[0:4], "big")
            # ID3v2.3 extended header size excludes the 4 size bytes.
            ext_total = 4 + ext_size
            out["extended_header"] = {
                "exists": True,
                "offset_in_file": 10,
                "size": ext_total,
                "raw_sha256": sha256_bytes(body[:ext_total]),
            }
            pos = ext_total
        elif major == 4 and len(body) >= 4:
            ext_total = synchsafe_to_int(body[0:4])
            out["extended_header"] = {
                "exists": True,
                "offset_in_file": 10,
                "size": ext_total,
                "raw_sha256": sha256_bytes(body[:ext_total]),
            }
            pos = ext_total
        else:
            out["extended_header"] = {"exists": True, "parse_error": "unsupported/short extended header"}

    frames: List[Dict[str, Any]] = []
    while pos < len(body):
        # padding starts with zero bytes.
        if body[pos : pos + 1] == b"\x00":
            break

        if major == 2:
            if pos + 6 > len(body):
                break
            frame_id_bytes = body[pos : pos + 3]
            frame_id = frame_id_bytes.decode("latin1", "replace")
            frame_size = int.from_bytes(body[pos + 3 : pos + 6], "big")
            header_size = 6
            frame_flags = ""
        else:
            if pos + 10 > len(body):
                break
            frame_id_bytes = body[pos : pos + 4]
            frame_id = frame_id_bytes.decode("latin1", "replace")
            if not frame_id.strip("\x00"):
                break
            if major == 4:
                frame_size = synchsafe_to_int(body[pos + 4 : pos + 8])
            else:
                frame_size = int.from_bytes(body[pos + 4 : pos + 8], "big")
            header_size = 10
            frame_flags = body[pos + 8 : pos + 10].hex()

        if frame_size < 0 or pos + header_size + frame_size > len(body):
            frames.append({
                "id": frame_id,
                "offset_in_file": 10 + pos,
                "parse_error": f"invalid frame size {frame_size}",
            })
            break

        frame_start = pos
        content_start = pos + header_size
        content = body[content_start : content_start + frame_size]
        raw_frame = body[frame_start : content_start + frame_size]
        frame: Dict[str, Any] = {
            "id": frame_id,
            "offset_in_file": 10 + frame_start,
            "size": frame_size,
            "header_size": header_size,
            "flags_hex": frame_flags,
            "raw_sha256": sha256_bytes(raw_frame),
            "content_sha256": sha256_bytes(content),
        }

        if frame_id.startswith("T") and frame_id not in ("TXXX", "TXX"):
            frame.update(decode_id3_text_payload(content))
        elif frame_id in ("TXXX", "TXX") and content:
            # User text frame: encoding + description + value.
            enc = content[0]
            desc_region = content[1:]
            desc_end, after = find_id3_text_terminator(desc_region, enc)
            desc = decode_id3_text_payload(bytes([enc]) + desc_region[:desc_end])["text"]
            value = decode_id3_text_payload(bytes([enc]) + desc_region[after:])["text"]
            frame.update({
                "encoding_byte": enc,
                "encoding": ID3_TEXT_ENCODINGS.get(enc, f"unknown({enc})"),
                "description": desc,
                "text": value,
                "values": [value] if value else [],
            })
        elif frame_id in ("APIC", "PIC") and content:
            if frame_id == "APIC":
                enc = content[0]
                rest = content[1:]
                mime_end = rest.find(b"\x00")
                if mime_end == -1 or mime_end + 1 >= len(rest):
                    frame["parse_error"] = "invalid APIC frame"
                else:
                    mime = rest[:mime_end].decode("latin1", "replace")
                    picture_type = rest[mime_end + 1]
                    desc_region = rest[mime_end + 2 :]
                    desc_end, after = find_id3_text_terminator(desc_region, enc)
                    desc = decode_id3_text_payload(bytes([enc]) + desc_region[:desc_end])["text"]
                    img_bytes = desc_region[after:]
                    frame.update({
                        "encoding_byte": enc,
                        "encoding": ID3_TEXT_ENCODINGS.get(enc, f"unknown({enc})"),
                        "mime": mime,
                        "picture_type": picture_type,
                        "picture_type_name": PICTURE_TYPES.get(picture_type, "unknown"),
                        "description": desc,
                        "image": image_info(img_bytes),
                    })
            else:
                # ID3v2.2 PIC: encoding + 3-byte image format + picture type + description + data
                enc = content[0]
                image_format = content[1:4].decode("latin1", "replace") if len(content) >= 4 else ""
                picture_type = content[4] if len(content) >= 5 else None
                desc_region = content[5:]
                desc_end, after = find_id3_text_terminator(desc_region, enc)
                desc = decode_id3_text_payload(bytes([enc]) + desc_region[:desc_end])["text"]
                img_bytes = desc_region[after:]
                frame.update({
                    "encoding_byte": enc,
                    "encoding": ID3_TEXT_ENCODINGS.get(enc, f"unknown({enc})"),
                    "image_format": image_format,
                    "picture_type": picture_type,
                    "picture_type_name": PICTURE_TYPES.get(picture_type, "unknown") if picture_type is not None else None,
                    "description": desc,
                    "image": image_info(img_bytes),
                })

        frames.append(frame)
        pos = content_start + frame_size

    out["frames"] = frames
    out["padding_size"] = max(0, len(body) - pos)
    padding = body[pos:]
    out["padding_all_zero"] = padding == b"\x00" * len(padding)
    return out


def analyze_mp3(path: Path, no_audio_hash: bool = False) -> Dict[str, Any]:
    size = path.stat().st_size
    id3v2 = parse_id3v2(path)
    id3v1 = parse_id3v1(path)
    audio_start = id3v2.get("total_size", 0) if id3v2.get("exists") else 0
    audio_end = size - 128 if id3v1.get("exists") else size

    first_header = parse_mpeg_header(read_region(path, audio_start, 4)) if audio_start < size else None
    audio_hash = None if no_audio_hash else hash_region(path, audio_start, audio_end, "sha256")

    return {
        "kind": "mp3",
        "path": str(path),
        "name": path.name,
        "size": size,
        "file_sha256": hash_file(path, "sha256"),
        "file_md5": hash_file(path, "md5"),
        "id3v2": id3v2,
        "id3v1": id3v1,
        "ape_markers": parse_ape_markers(path),
        "audio_region": {
            "start": audio_start,
            "end": audio_end,
            "bytes": max(0, audio_end - audio_start),
            "sha256": audio_hash,
            "first_mpeg_header": first_header,
        },
    }


def parse_streaminfo(content: bytes) -> Dict[str, Any]:
    if len(content) != 34:
        return {"parse_error": f"STREAMINFO length should be 34, got {len(content)}"}
    min_block_size = int.from_bytes(content[0:2], "big")
    max_block_size = int.from_bytes(content[2:4], "big")
    min_frame_size = int.from_bytes(content[4:7], "big")
    max_frame_size = int.from_bytes(content[7:10], "big")
    packed = int.from_bytes(content[10:18], "big")
    sample_rate = (packed >> 44) & ((1 << 20) - 1)
    channels = ((packed >> 41) & 0x07) + 1
    bits_per_sample = ((packed >> 36) & 0x1F) + 1
    total_samples = packed & ((1 << 36) - 1)
    return {
        "min_block_size": min_block_size,
        "max_block_size": max_block_size,
        "min_frame_size": min_frame_size,
        "max_frame_size": max_frame_size,
        "sample_rate": sample_rate,
        "channels": channels,
        "bits_per_sample": bits_per_sample,
        "total_samples": total_samples,
        "duration_seconds": total_samples / sample_rate if sample_rate else None,
        "audio_md5": content[18:34].hex(),
    }


def parse_vorbis_comment(content: bytes) -> Dict[str, Any]:
    pos = 0
    out: Dict[str, Any] = {"vendor": None, "comment_count": 0, "comments": [], "parse_error": None}
    try:
        vendor_len = int.from_bytes(content[pos : pos + 4], "little")
        pos += 4
        vendor = content[pos : pos + vendor_len].decode("utf-8", "replace")
        pos += vendor_len
        count = int.from_bytes(content[pos : pos + 4], "little")
        pos += 4
        comments = []
        for _ in range(count):
            clen = int.from_bytes(content[pos : pos + 4], "little")
            pos += 4
            raw_bytes = content[pos : pos + clen]
            pos += clen
            raw = raw_bytes.decode("utf-8", "replace")
            if "=" in raw:
                key, value = raw.split("=", 1)
            else:
                key, value = raw, ""
            comments.append({"raw": raw, "key": key, "key_lower": key.lower(), "value": value, "byte_len": clen})
        out.update({
            "vendor": vendor,
            "comment_count": count,
            "comments": comments,
            "parsed_bytes": pos,
            "trailing_bytes": len(content) - pos,
        })
    except Exception as e:
        out["parse_error"] = str(e)
    return out


def parse_flac_picture(content: bytes) -> Dict[str, Any]:
    pos = 0
    out: Dict[str, Any] = {}
    try:
        picture_type = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        mime_len = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        mime = content[pos : pos + mime_len].decode("ascii", "replace")
        pos += mime_len
        desc_len = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        description = content[pos : pos + desc_len].decode("utf-8", "replace")
        pos += desc_len
        width = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        height = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        depth = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        colors = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        image_len = int.from_bytes(content[pos : pos + 4], "big")
        pos += 4
        image_bytes = content[pos : pos + image_len]
        pos += image_len
        out.update({
            "picture_type": picture_type,
            "picture_type_name": PICTURE_TYPES.get(picture_type, "unknown"),
            "mime": mime,
            "description": description,
            "declared_width": width,
            "declared_height": height,
            "declared_depth": depth,
            "declared_colors": colors,
            "image": image_info(image_bytes),
            "parsed_bytes": pos,
            "trailing_bytes": len(content) - pos,
        })
    except Exception as e:
        out["parse_error"] = str(e)
    return out


def parse_flac(path: Path, no_audio_hash: bool = False) -> Dict[str, Any]:
    size = path.stat().st_size
    if read_prefix(path, 4) != b"fLaC":
        return {"kind": "flac", "path": str(path), "parse_error": "missing fLaC marker"}

    blocks: List[Dict[str, Any]] = []
    pos = 4
    index = 0
    while pos + 4 <= size:
        header = read_region(path, pos, 4)
        block_type = header[0] & 0x7F
        is_last = bool(header[0] & 0x80)
        length = int.from_bytes(header[1:4], "big")
        content_offset = pos + 4
        content = read_region(path, content_offset, length)
        block: Dict[str, Any] = {
            "index": index,
            "type": block_type,
            "type_name": FLAC_BLOCK_NAMES.get(block_type, f"UNKNOWN_{block_type}"),
            "is_last": is_last,
            "header_offset": pos,
            "content_offset": content_offset,
            "length": length,
            "header_hex": header.hex(),
            "raw_block_sha256": hash_region(path, pos, pos + 4 + length, "sha256"),
            "content_sha256": sha256_bytes(content),
        }
        if block_type == 0:
            block["streaminfo"] = parse_streaminfo(content)
        elif block_type == 1:
            block["padding_all_zero"] = content == b"\x00" * len(content)
        elif block_type == 3:
            block["seekpoints"] = length // 18
            block["seektable_remainder_bytes"] = length % 18
        elif block_type == 4:
            block["vorbis_comment"] = parse_vorbis_comment(content)
        elif block_type == 6:
            block["picture"] = parse_flac_picture(content)
        blocks.append(block)
        pos += 4 + length
        index += 1
        if is_last:
            break

    audio_start = pos
    return {
        "kind": "flac",
        "path": str(path),
        "name": path.name,
        "size": size,
        "file_sha256": hash_file(path, "sha256"),
        "file_md5": hash_file(path, "md5"),
        "blocks": blocks,
        "audio_region": {
            "start": audio_start,
            "end": size,
            "bytes": max(0, size - audio_start),
            "sha256": None if no_audio_hash else hash_region(path, audio_start, size, "sha256"),
            "prefix_hex": read_region(path, audio_start, min(16, max(0, size - audio_start))).hex() if audio_start < size else "",
        },
    }


def analyze(path: Path, no_audio_hash: bool = False) -> Dict[str, Any]:
    kind = detect_kind(path)
    if kind == "mp3":
        return analyze_mp3(path, no_audio_hash=no_audio_hash)
    if kind == "flac":
        return parse_flac(path, no_audio_hash=no_audio_hash)
    return {
        "kind": "unknown",
        "path": str(path),
        "name": path.name,
        "size": path.stat().st_size,
        "file_sha256": hash_file(path, "sha256"),
        "file_md5": hash_file(path, "md5"),
        "parse_error": "unsupported file type; currently supports MP3 and FLAC",
    }


def text_frames(id3v2: Dict[str, Any]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for frame in id3v2.get("frames", []):
        fid = frame.get("id")
        if isinstance(fid, str) and fid.startswith("T") and "values" in frame:
            out.setdefault(fid, []).extend(frame.get("values") or [frame.get("text", "")])
    return out


def apic_frames(id3v2: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [f for f in id3v2.get("frames", []) if f.get("id") in ("APIC", "PIC")]


def flac_blocks_by_type(data: Dict[str, Any], type_name: str) -> List[Dict[str, Any]]:
    return [b for b in data.get("blocks", []) if b.get("type_name") == type_name]


def first_streaminfo(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    blocks = flac_blocks_by_type(data, "STREAMINFO")
    return blocks[0] if blocks else None


def vorbis_comments(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    comments: List[Dict[str, Any]] = []
    for block in flac_blocks_by_type(data, "VORBIS_COMMENT"):
        comments.extend(block.get("vorbis_comment", {}).get("comments", []))
    return comments


def flac_pictures(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [b.get("picture", {}) for b in flac_blocks_by_type(data, "PICTURE")]


def same(a: Any, b: Any) -> str:
    return "same" if a == b else "DIFF"


def yesno(value: bool) -> str:
    return "yes" if value else "no"


def md_table(headers: List[str], rows: Iterable[Iterable[Any]]) -> str:
    rows_list = [["" if c is None else str(c) for c in row] for row in rows]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows_list:
        out.append("| " + " | ".join(cell.replace("\n", "<br>") for cell in row) + " |")
    return "\n".join(out)


def short_hash(h: Optional[str], n: int = 16) -> str:
    if not h:
        return ""
    return h[:n]


def compare_common(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    lines = []
    lines.append("## File summary")
    lines.append(md_table(
        ["item", "original", "tagged", "status"],
        [
            ["path", a.get("path"), b.get("path"), ""],
            ["kind", a.get("kind"), b.get("kind"), same(a.get("kind"), b.get("kind"))],
            ["size", a.get("size"), b.get("size"), same(a.get("size"), b.get("size"))],
            ["file MD5", a.get("file_md5"), b.get("file_md5"), same(a.get("file_md5"), b.get("file_md5"))],
            ["file SHA-256", a.get("file_sha256"), b.get("file_sha256"), same(a.get("file_sha256"), b.get("file_sha256"))],
        ],
    ))
    lines.append("")
    return lines


def report_mp3(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    a_id3 = a.get("id3v2", {})
    b_id3 = b.get("id3v2", {})
    a_ar = a.get("audio_region", {})
    b_ar = b.get("audio_region", {})

    lines.append("## MP3 audio-region comparison")
    lines.append(md_table(
        ["item", "original", "tagged", "status"],
        [
            ["audio start offset", a_ar.get("start"), b_ar.get("start"), same(a_ar.get("start"), b_ar.get("start"))],
            ["audio end offset", a_ar.get("end"), b_ar.get("end"), same(a_ar.get("end"), b_ar.get("end"))],
            ["audio bytes", a_ar.get("bytes"), b_ar.get("bytes"), same(a_ar.get("bytes"), b_ar.get("bytes"))],
            ["audio SHA-256", a_ar.get("sha256"), b_ar.get("sha256"), same(a_ar.get("sha256"), b_ar.get("sha256"))],
            ["first MPEG header", a_ar.get("first_mpeg_header", {}).get("header_hex") if a_ar.get("first_mpeg_header") else None,
             b_ar.get("first_mpeg_header", {}).get("header_hex") if b_ar.get("first_mpeg_header") else None,
             same(a_ar.get("first_mpeg_header"), b_ar.get("first_mpeg_header"))],
        ],
    ))
    lines.append("")

    lines.append("## MP3 ID3 container comparison")
    lines.append(md_table(
        ["item", "original", "tagged", "status"],
        [
            ["ID3v2 exists", yesno(bool(a_id3.get("exists"))), yesno(bool(b_id3.get("exists"))), same(a_id3.get("exists"), b_id3.get("exists"))],
            ["ID3v2 version", a_id3.get("version"), b_id3.get("version"), same(a_id3.get("version"), b_id3.get("version"))],
            ["ID3v2 flags", ", ".join(a_id3.get("flag_names", [])) or "none", ", ".join(b_id3.get("flag_names", [])) or "none", same(a_id3.get("flags"), b_id3.get("flags"))],
            ["ID3v2 total size", a_id3.get("total_size"), b_id3.get("total_size"), same(a_id3.get("total_size"), b_id3.get("total_size"))],
            ["padding bytes", a_id3.get("padding_size"), b_id3.get("padding_size"), same(a_id3.get("padding_size"), b_id3.get("padding_size"))],
            ["ID3v1 exists", yesno(bool(a.get("id3v1", {}).get("exists"))), yesno(bool(b.get("id3v1", {}).get("exists"))), same(a.get("id3v1", {}).get("exists"), b.get("id3v1", {}).get("exists"))],
            ["ID3v2 raw tag SHA-256", a_id3.get("raw_tag_sha256"), b_id3.get("raw_tag_sha256"), same(a_id3.get("raw_tag_sha256"), b_id3.get("raw_tag_sha256"))],
        ],
    ))
    lines.append("")

    lines.append("## MP3 ID3v2 frames")
    def frame_rows(x: Dict[str, Any]) -> List[List[Any]]:
        rows = []
        for i, f in enumerate(x.get("id3v2", {}).get("frames", [])):
            value = ""
            if "text" in f:
                value = f.get("text", "")
            elif "image" in f:
                im = f.get("image", {})
                value = f"{f.get('mime','')} {im.get('bytes','')} bytes sha256={short_hash(im.get('sha256'))} desc={f.get('description','')}"
            rows.append([i, f.get("id"), f.get("offset_in_file"), f.get("size"), f.get("encoding", ""), value])
        return rows
    lines.append("### Original")
    lines.append(md_table(["#", "frame", "offset", "size", "encoding", "value/summary"], frame_rows(a)))
    lines.append("")
    lines.append("### Tagged")
    lines.append(md_table(["#", "frame", "offset", "size", "encoding", "value/summary"], frame_rows(b)))
    lines.append("")

    lines.append("## MP3 text tag exact comparison")
    a_text = text_frames(a_id3)
    b_text = text_frames(b_id3)
    keys = sorted(set(a_text) | set(b_text))
    lines.append(md_table(["frame", "original", "tagged", "status"], [[k, "; ".join(a_text.get(k, [])), "; ".join(b_text.get(k, [])), same(a_text.get(k), b_text.get(k))] for k in keys]))
    lines.append("")

    lines.append("## MP3 embedded picture comparison")
    a_apic = apic_frames(a_id3)
    b_apic = apic_frames(b_id3)
    max_len = max(len(a_apic), len(b_apic))
    rows = []
    for i in range(max_len):
        aa = a_apic[i] if i < len(a_apic) else {}
        bb = b_apic[i] if i < len(b_apic) else {}
        aa_img = aa.get("image", {})
        bb_img = bb.get("image", {})
        rows.append([
            i,
            aa.get("description"), bb.get("description"), same(aa.get("description"), bb.get("description")),
            aa_img.get("sha256"), bb_img.get("sha256"), same(aa_img.get("sha256"), bb_img.get("sha256")),
        ])
    lines.append(md_table(["#", "orig desc", "tagged desc", "desc status", "orig image SHA-256", "tagged image SHA-256", "image status"], rows))
    lines.append("")

    return lines


def report_flac(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    a_ar = a.get("audio_region", {})
    b_ar = b.get("audio_region", {})

    lines.append("## FLAC audio-region comparison")
    a_si = first_streaminfo(a)
    b_si = first_streaminfo(b)
    lines.append(md_table(
        ["item", "original", "tagged", "status"],
        [
            ["audio start offset", a_ar.get("start"), b_ar.get("start"), same(a_ar.get("start"), b_ar.get("start"))],
            ["audio bytes", a_ar.get("bytes"), b_ar.get("bytes"), same(a_ar.get("bytes"), b_ar.get("bytes"))],
            ["audio SHA-256", a_ar.get("sha256"), b_ar.get("sha256"), same(a_ar.get("sha256"), b_ar.get("sha256"))],
            ["STREAMINFO SHA-256", a_si.get("content_sha256") if a_si else None, b_si.get("content_sha256") if b_si else None, same(a_si.get("content_sha256") if a_si else None, b_si.get("content_sha256") if b_si else None)],
            ["STREAMINFO audio MD5", a_si.get("streaminfo", {}).get("audio_md5") if a_si else None, b_si.get("streaminfo", {}).get("audio_md5") if b_si else None, same(a_si.get("streaminfo", {}).get("audio_md5") if a_si else None, b_si.get("streaminfo", {}).get("audio_md5") if b_si else None)],
        ],
    ))
    lines.append("")

    lines.append("## FLAC metadata block order")
    def block_sequence(x: Dict[str, Any]) -> str:
        return " â†’ ".join(f"{blk.get('type_name')}[{blk.get('length')}]" for blk in x.get("blocks", []))
    lines.append(md_table(["item", "original", "tagged", "status"], [["block sequence", block_sequence(a), block_sequence(b), same(block_sequence(a), block_sequence(b))]]))
    lines.append("")

    def flac_block_rows(x: Dict[str, Any]) -> List[List[Any]]:
        rows = []
        for blk in x.get("blocks", []):
            extra = ""
            if blk.get("type_name") == "STREAMINFO":
                si = blk.get("streaminfo", {})
                extra = f"{si.get('sample_rate')} Hz, {si.get('bits_per_sample')}-bit, {si.get('channels')} ch, md5={si.get('audio_md5')}"
            elif blk.get("type_name") == "VORBIS_COMMENT":
                vc = blk.get("vorbis_comment", {})
                extra = f"vendor={vc.get('vendor')}; comments={vc.get('comment_count')}"
            elif blk.get("type_name") == "PICTURE":
                pic = blk.get("picture", {})
                im = pic.get("image", {})
                extra = f"{pic.get('mime')} desc={pic.get('description')!r}; declared={pic.get('declared_width')}x{pic.get('declared_height')}x{pic.get('declared_depth')}; image_sha={short_hash(im.get('sha256'))}"
            elif blk.get("type_name") == "PADDING":
                extra = f"all_zero={blk.get('padding_all_zero')}"
            rows.append([blk.get("index"), blk.get("type_name"), blk.get("header_offset"), blk.get("length"), blk.get("is_last"), extra])
        return rows

    lines.append("### Original blocks")
    lines.append(md_table(["#", "type", "offset", "length", "last", "summary"], flac_block_rows(a)))
    lines.append("")
    lines.append("### Tagged blocks")
    lines.append(md_table(["#", "type", "offset", "length", "last", "summary"], flac_block_rows(b)))
    lines.append("")

    lines.append("## FLAC Vorbis Comment exact comparison")
    a_comments = [c.get("raw", "") for c in vorbis_comments(a)]
    b_comments = [c.get("raw", "") for c in vorbis_comments(b)]
    removed = [x for x in a_comments if x not in b_comments]
    added = [x for x in b_comments if x not in a_comments]
    lines.append(md_table(
        ["category", "values"],
        [
            ["removed from original", "<br>".join(removed) if removed else "none"],
            ["added in tagged", "<br>".join(added) if added else "none"],
        ],
    ))
    lines.append("")

    lines.append("## FLAC picture comparison")
    a_pics = flac_pictures(a)
    b_pics = flac_pictures(b)
    rows = []
    max_len = max(len(a_pics), len(b_pics))
    for i in range(max_len):
        aa = a_pics[i] if i < len(a_pics) else {}
        bb = b_pics[i] if i < len(b_pics) else {}
        aa_img = aa.get("image", {})
        bb_img = bb.get("image", {})
        rows.append([
            i,
            aa.get("description"), bb.get("description"), same(aa.get("description"), bb.get("description")),
            f"{aa.get('declared_width')}x{aa.get('declared_height')}x{aa.get('declared_depth')}",
            f"{bb.get('declared_width')}x{bb.get('declared_height')}x{bb.get('declared_depth')}",
            same((aa.get("declared_width"), aa.get("declared_height"), aa.get("declared_depth")), (bb.get("declared_width"), bb.get("declared_height"), bb.get("declared_depth"))),
            aa_img.get("sha256"), bb_img.get("sha256"), same(aa_img.get("sha256"), bb_img.get("sha256")),
        ])
    lines.append(md_table(["#", "orig desc", "tagged desc", "desc status", "orig declared", "tagged declared", "declared status", "orig image SHA-256", "tagged image SHA-256", "image status"], rows))
    lines.append("")

    return lines


def make_report(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Audio metadata diff report")
    lines.append("")
    lines.extend(compare_common(a, b))

    if a.get("kind") != b.get("kind"):
        lines.append("## Result")
        lines.append(f"Different file kinds: `{a.get('kind')}` vs `{b.get('kind')}`. Format-specific comparison skipped.")
        return "\n".join(lines).rstrip() + "\n"

    if a.get("kind") == "mp3":
        lines.extend(report_mp3(a, b))
    elif a.get("kind") == "flac":
        lines.extend(report_flac(a, b))
    else:
        lines.append("## Result")
        lines.append("Unsupported file type. Currently supports MP3 and FLAC.")

    # Short machine-oriented verdict.
    lines.append("## Quick verdict")
    audio_same = a.get("audio_region", {}).get("sha256") == b.get("audio_region", {}).get("sha256")
    file_same = a.get("file_sha256") == b.get("file_sha256")
    lines.append(f"- File bytes identical: **{yesno(file_same)}**")
    lines.append(f"- Audio region identical: **{yesno(audio_same)}**")
    if audio_same and not file_same:
        lines.append("- Difference appears to be in metadata/container bytes, not decoded audio bytes.")
    elif not audio_same:
        lines.append("- Audio-region bytes differ. This may indicate audio re-encoding, trimming, added/removed trailing tags not detected, or parser boundary issues.")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deep metadata diff for MP3 ID3 and FLAC metadata blocks.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("original", type=Path, help="original file")
    parser.add_argument("tagged", type=Path, help="tagged/modified file")
    parser.add_argument("-o", "--output", type=Path, help="write Markdown report to file instead of stdout")
    parser.add_argument("--json", dest="json_output", type=Path, help="write raw parsed JSON to file")
    parser.add_argument("--json-only", action="store_true", help="print raw parsed JSON instead of Markdown")
    parser.add_argument("--no-audio-hash", action="store_true", help="skip hashing the audio region for faster large-file scans")
    args = parser.parse_args(argv)

    for p in (args.original, args.tagged):
        if not p.exists():
            print(f"error: file not found: {p}", file=sys.stderr)
            return 2
        if not p.is_file():
            print(f"error: not a file: {p}", file=sys.stderr)
            return 2

    original = analyze(args.original, no_audio_hash=args.no_audio_hash)
    tagged = analyze(args.tagged, no_audio_hash=args.no_audio_hash)
    parsed = {"original": original, "tagged": tagged}

    if args.json_output:
        args.json_output.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        text = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
    else:
        text = make_report(original, tagged)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")

    # Exit status: 0 = ran successfully. This tool reports differences; differences are not errors.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


