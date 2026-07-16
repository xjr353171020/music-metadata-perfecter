# -*- coding: utf-8 -*-
"""Locale-aware initial letters for album-index navigation."""

import unicodedata

try:
    from pypinyin import Style as PinyinStyle, lazy_pinyin
except ImportError:
    PinyinStyle = None
    lazy_pinyin = None

try:
    from pykakasi import kakasi
except ImportError:
    kakasi = None


CHINESE_INITIAL_RANGES = (
    (1601, "A"), (1637, "B"), (1833, "C"), (2078, "D"),
    (2274, "E"), (2302, "F"), (2433, "G"), (2594, "H"),
    (2787, "J"), (3106, "K"), (3212, "L"), (3472, "M"),
    (3635, "N"), (3722, "O"), (3730, "P"), (3858, "Q"),
    (4027, "R"), (4086, "S"), (4390, "T"), (4558, "W"),
    (4684, "X"), (4925, "Y"), (5249, "Z"),
)
KANA_INITIALS = {
    "A": "あぁ", "I": "いぃゐ", "U": "うぅ", "E": "えぇゑ", "O": "おぉを",
    "B": "ばびぶべぼ", "C": "ち", "D": "だでど", "F": "ふ",
    "G": "がぎぐげご", "H": "はひへほ", "J": "じぢ", "K": "かきくけこゕゖ",
    "M": "まみむめも", "N": "なにぬねのん", "P": "ぱぴぷぺぽ",
    "R": "らりるれろ", "S": "さしすせそ", "T": "たつてとっ",
    "V": "ゔ", "W": "わゎ", "Y": "やゃゆゅよょ", "Z": "ざずぜぞづ",
}
HANGUL_INITIALS = (
    "G", "K", "N", "D", "T", "R", "M", "B", "P", "S",
    "S", "", "J", "J", "C", "K", "T", "P", "H",
)
HANGUL_VOWEL_INITIALS = (
    "A", "A", "Y", "Y", "E", "E", "Y", "Y", "O", "W",
    "W", "O", "Y", "U", "W", "W", "W", "Y", "E", "U", "I",
)
JAPANESE_CONVERTER = kakasi() if kakasi else None


def album_initial(album_name):
    album_name = str(album_name or "").strip()
    if not album_name:
        return "#"
    first_source_char = album_name[0]
    first_char = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", first_source_char))[0]
    if first_char.isascii() and first_char.isalpha():
        return first_char.upper()
    if is_kana(first_source_char) or (is_han(first_source_char) and contains_kana(album_name)):
        japanese_initial = get_japanese_initial(album_name)
        if japanese_initial:
            return japanese_initial
    kana_initial = get_kana_initial(first_source_char)
    if kana_initial:
        return kana_initial
    if is_han(first_source_char):
        chinese_initial = get_chinese_initial(first_source_char)
        if chinese_initial:
            return chinese_initial
    hangul_initial = get_hangul_initial(first_source_char)
    return hangul_initial or "#"


def album_navigation_sort_key(album_name):
    initial = album_initial(album_name)
    initial_rank = 0 if initial == "#" else ord(initial) - ord("A") + 1
    return initial_rank, str(album_name or "").casefold()


def is_han(char):
    return "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"


def is_kana(char):
    return "\u3040" <= char <= "\u309f" or "\u30a0" <= char <= "\u30ff"


def contains_kana(text):
    return any(is_kana(char) for char in text)


def get_japanese_initial(text):
    if not JAPANESE_CONVERTER:
        return ""
    for token in JAPANESE_CONVERTER.convert(text):
        reading = token.get("hepburn", "")
        if reading and reading[0].isascii() and reading[0].isalpha():
            return reading[0].upper()
    return ""


def get_kana_initial(char):
    code_point = ord(char)
    if 0x30A1 <= code_point <= 0x30F6:
        char = chr(code_point - 0x60)
    elif char == "ヵ":
        char = "か"
    elif char == "ヶ":
        char = "け"
    for initial, kana_group in KANA_INITIALS.items():
        if char in kana_group:
            return initial
    return ""


def get_chinese_initial(char):
    if lazy_pinyin and PinyinStyle:
        readings = lazy_pinyin(char, style=PinyinStyle.NORMAL, errors=lambda _: "")
        if readings and readings[0] and readings[0][0].isascii() and readings[0][0].isalpha():
            return readings[0][0].upper()
    try:
        gbk_bytes = char.encode("gbk")
    except UnicodeEncodeError:
        return ""
    if len(gbk_bytes) != 2:
        return ""
    gbk_code = (gbk_bytes[0] - 160) * 100 + gbk_bytes[1] - 160
    if not (CHINESE_INITIAL_RANGES[0][0] <= gbk_code < 5600):
        return ""
    for threshold, initial in reversed(CHINESE_INITIAL_RANGES):
        if gbk_code >= threshold:
            return initial
    return ""


def get_hangul_initial(char):
    syllable_index = ord(char) - 0xAC00
    if not 0 <= syllable_index < 11172:
        return ""
    consonant_index = syllable_index // 588
    consonant_initial = HANGUL_INITIALS[consonant_index]
    if consonant_initial:
        return consonant_initial
    vowel_index = (syllable_index % 588) // 28
    return HANGUL_VOWEL_INITIALS[vowel_index]
