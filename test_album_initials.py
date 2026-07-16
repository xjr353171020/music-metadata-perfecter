# -*- coding: utf-8 -*-
import unittest

from album_initials import album_initial


class AlbumInitialTests(unittest.TestCase):
    def test_empty_album_uses_miscellaneous_index(self):
        self.assertEqual(album_initial(""), "#")

    def test_english_album_uses_first_letter(self):
        self.assertEqual(album_initial("Abbey Road"), "A")

    def test_chinese_album_uses_pinyin_initial(self):
        self.assertEqual(album_initial("周杰伦"), "Z")

    def test_japanese_album_uses_kana_initial(self):
        self.assertEqual(album_initial("さくら"), "S")

    def test_korean_album_uses_hangul_initial(self):
        self.assertEqual(album_initial("가나다"), "G")
