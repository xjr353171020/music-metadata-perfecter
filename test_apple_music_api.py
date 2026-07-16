# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from apple_music_api import _resolve_artist_localization, search_apple_music


class AppleMusicSearchTests(unittest.TestCase):
    def test_cn_search_relocalizes_hk_track_without_us_tracklist_sweep(self):
        collection_id = 1763742878
        us_collection = {
            "wrapperType": "collection", "collectionId": collection_id,
            "collectionName": "八方来财", "artistName": "SKAI ISYOURGOD",
        }
        cn_collection = {
            "wrapperType": "collection", "collectionId": collection_id,
            "collectionName": "八方来财", "artistName": "揽佬SKAI ISYOURGOD",
            "releaseDate": "2024-08-20T07:00:00Z",
        }
        hk_collection = {
            **cn_collection,
            "collectionName": "八方來財", "artistName": "攬佬SKAI ISYOURGOD",
        }
        hk_song = {
            "wrapperType": "track", "kind": "song",
            "collectionId": collection_id, "trackId": 1763742879,
            "trackName": "八方來財", "collectionName": "八方來財",
            "artistName": "攬佬SKAI ISYOURGOD", "trackNumber": 1,
            "discNumber": 1,
        }
        cn_song = {
            **hk_song,
            "trackName": "八方来财", "collectionName": "八方来财",
            "artistName": "揽佬SKAI ISYOURGOD",
        }

        def search_side_effect(query, country, *args, **kwargs):
            collection = cn_collection if country == "cn" else us_collection
            return {"resultCount": 1, "results": [collection]}

        def collection_lookup_side_effect(collection_id_arg, country, *args, **kwargs):
            self.assertEqual(collection_id_arg, collection_id)
            if country == "cn":
                return {"resultCount": 1, "results": [cn_collection]}
            if country == "hk":
                return {"resultCount": 2, "results": [hk_collection, hk_song]}
            self.fail("A decisive CN result must not trigger a US track-list lookup")

        def track_lookup_side_effect(track_id, country, *args, **kwargs):
            self.assertEqual((track_id, country), (1763742879, "cn"))
            return {"resultCount": 1, "results": [cn_song]}

        identities = [{"name": "攬佬SKAI ISYOURGOD", "country": "CN", "aliases": []}]
        with patch("apple_music_api._search_collections", side_effect=search_side_effect) as search, patch(
            "apple_music_api._lookup_collection", side_effect=collection_lookup_side_effect
        ) as collection_lookup, patch(
            "apple_music_api._lookup_track", side_effect=track_lookup_side_effect
        ) as track_lookup:
            success, data, _, _ = search_apple_music(
                "八方来财", "揽佬SKAI ISYOURGOD", "八方来财", "1", "",
                no_cache=True, artist_identities=identities,
            )

        self.assertTrue(success)
        self.assertEqual(data["title"], "八方来财")
        self.assertEqual(data["artist"], "揽佬SKAI ISYOURGOD")
        self.assertEqual(data["album"], "八方来财")
        self.assertEqual(data["apple_storefront"], "cn")
        self.assertEqual([call.args[1] for call in search.call_args_list], ["cn"])
        self.assertEqual([call.args[1] for call in collection_lookup.call_args_list], ["cn", "hk"])
        self.assertEqual(track_lookup.call_count, 1)

    def test_artist_localization_includes_matched_and_home_storefront(self):
        song = {"trackId": 892687724, "artistName": "劉德華"}
        collection = {"artistName": "劉德華", "_search_country": "hk"}
        identities = [{
            "name": "劉德華",
            "country": "HK",
            "aliases": [
                {"name": "Andy Lau", "locale": "en", "primary": True},
                {"name": "刘德华", "locale": "zh_Hans_CN", "primary": True},
            ],
        }]
        names = {"us": "Andy Lau", "cn": "刘德华", "hk": "劉德華"}

        def lookup_side_effect(track_id, country, *args, **kwargs):
            artist = names.get(country)
            if not artist:
                return {"resultCount": 0, "results": []}
            return {"resultCount": 1, "results": [{
                "wrapperType": "track", "kind": "song",
                "artistName": artist, "collectionArtistName": artist,
            }]}

        with patch("apple_music_api._lookup_track", side_effect=lookup_side_effect) as lookup:
            artist, album_artist = _resolve_artist_localization(
                song, collection, True, [], identities, "Andy Lau"
            )

        self.assertEqual((artist, album_artist), ("劉德華", "劉德華"))
        lookup.assert_not_called()

    def test_direct_collection_id_falls_back_to_hong_kong_for_tracks(self):
        collection = {
            "wrapperType": "collection",
            "collectionId": 892687697,
            "collectionName": "Album",
            "artistName": "Artist",
            "releaseDate": "1997-01-01T00:00:00Z",
        }
        song = {
            "wrapperType": "track",
            "kind": "song",
            "trackId": 123,
            "trackName": "Target",
            "artistName": "Artist",
            "collectionName": "Album",
            "trackNumber": 2,
            "discNumber": 1,
        }

        def lookup_side_effect(collection_id, country, *args, **kwargs):
            self.assertEqual(collection_id, "892687697")
            if country == "hk":
                return {"resultCount": 2, "results": [collection, song]}
            return {"resultCount": 1, "results": [collection]}

        with patch("apple_music_api._lookup_collection", side_effect=lookup_side_effect) as lookup, patch(
            "apple_music_api._resolve_artist_localization", return_value=("Artist", "Artist")
        ):
            success, data, _, _ = search_apple_music(
                "Target", "Artist", "Album", "2", "1",
                collection_id_override="892687697",
            )

        self.assertTrue(success)
        self.assertEqual(data["metadata_source"], "Apple Music")
        self.assertEqual(data["title"], "Target")
        self.assertTrue(data["is_direct_apple_collection_id"])
        self.assertEqual([call.args[1] for call in lookup.call_args_list], ["us", "cn", "hk"])

    def test_collection_record_album_name_overrides_track_embedded_name(self):
        collection = {
            "wrapperType": "collection",
            "collectionId": 651455891,
            "collectionName": "陳奕迅 國語精選",
            "artistName": "Eason Chan",
            "releaseDate": "2013-05-22T07:00:00Z",
        }
        song = {
            "wrapperType": "track",
            "kind": "song",
            "collectionId": 651455891,
            "trackId": 651456031,
            "trackName": "你的背包",
            "artistName": "Eason Chan",
            "collectionName": "Eason Chan Mandarin Collection",
            "trackNumber": 5,
            "discNumber": 1,
        }

        with patch(
            "apple_music_api._lookup_collection",
            return_value={"resultCount": 2, "results": [collection, song]},
        ), patch(
            "apple_music_api._resolve_artist_localization",
            return_value=("陳奕迅", "陳奕迅"),
        ):
            success, data, _, _ = search_apple_music(
                "你的背包", "陳奕迅", "陳奕迅 國語精選", "5", "1",
                collection_id_override="651455891",
            )

        self.assertTrue(success)
        self.assertEqual(data["album"], "陳奕迅 國語精選")


if __name__ == "__main__":
    unittest.main()
