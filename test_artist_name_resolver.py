# -*- coding: utf-8 -*-
import unittest

from artist_name_resolver import select_artist_variant


class ArtistNameResolverTests(unittest.TestCase):
    def test_home_country_official_name_precedes_musicbrainz_canonical_name(self):
        variants = [
            {"country": "us", "artist": "Official Name", "album_artist": "Official Name"},
            {"country": "jp", "artist": "公式別名", "album_artist": "公式別名"},
        ]
        identities = [{
            "name": "Official Name",
            "country": "JP",
            "aliases": [{"name": "公式別名", "locale": "ja", "primary": True}],
        }]

        selected = select_artist_variant(variants, [], identities)

        self.assertEqual(selected["artist"], "公式別名")

    def test_home_country_name_is_used_when_canonical_name_is_unavailable(self):
        variants = [
            {"country": "us", "artist": "International Alias", "album_artist": "International Alias"},
            {"country": "hk", "artist": "國籍語言名", "album_artist": "國籍語言名"},
        ]
        identities = [{
            "name": "Unavailable Official Name",
            "country": "HK",
            "aliases": [
                {"name": "International Alias", "locale": "en", "primary": True},
                {"name": "國籍語言名", "locale": "zh", "primary": True},
            ],
        }]

        selected = select_artist_variant(variants, [], identities)

        self.assertEqual(selected["artist"], "國籍語言名")


if __name__ == "__main__":
    unittest.main()
