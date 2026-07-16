# -*- coding: utf-8 -*-
"""Apple Music/iTunes Search API adapter for metadata lookup.

The Search API's ``entity=album`` response contains only collection data.  A
second lookup with ``entity=song`` is therefore required before it can be
compared fairly with MusicBrainz's track-level result.
"""
import json
import re
import urllib.parse

import requests

from artist_name_resolver import select_artist_variant
from mb_api import calculate_similarity, safe_int
from search_cancellation import check_cancelled


ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
_album_search_cache = {}
_album_lookup_cache = {}
_track_lookup_cache = {}
_DECISIVE_MATCH_SCORE = 0.90


def _artist_home_countries(artist_identities):
    countries = (
        str(identity.get("country", "")).strip().lower()
        for identity in artist_identities or []
    )
    return tuple(
        dict.fromkeys(
            country for country in countries
            if len(country) == 2 and country.isalpha() and country != "xw"
        )
    )


def _collection_lookup_countries(collection):
    """Return unique storefronts that can expose a collection's track list."""
    source_country = str(collection.get("_search_country", "")).strip().lower()
    if source_country == "cn":
        countries = ("cn", "hk", "us")
    elif source_country in {"hk", "tw"}:
        countries = (source_country, "hk", "cn", "us")
    else:
        countries = (source_country, "us", "cn", "hk")
    return tuple(dict.fromkeys(country for country in countries if country))


def _artist_lookup_countries(collection, artist_identities):
    """Prefer the artist's home storefront and avoid unrelated locale probes."""
    home_countries = _artist_home_countries(artist_identities)
    source_country = str(collection.get("_search_country", "")).strip().lower()
    countries = (*home_countries, source_country, "us")
    return tuple(
        dict.fromkeys(
            country for country in countries
            if len(country) == 2 and country.isalpha()
        )
    )


def _normalise_artist(value):
    """Keep the primary artist, matching the MusicBrainz search convention."""
    if not value:
        return ""
    return re.split(r"\s*(?:,|&|/|\\\\|\band\b)\s*", str(value), maxsplit=1, flags=re.IGNORECASE)[0].strip()


def _collection_baseline(album, artist, collection):
    score = (calculate_similarity(album, collection.get("collectionName", "")) if album else 1.0) * 0.75
    score += (
        calculate_similarity(_normalise_artist(artist), _normalise_artist(collection.get("artistName", "")))
        if artist else 1.0
    ) * 0.25
    return score


def _album_search_countries(artist_identities):
    return tuple(dict.fromkeys((*_artist_home_countries(artist_identities), "us", "cn")))


def _format_artist_credit(value):
    """Use the same ID3v2 multi-value separator as the MusicBrainz adapter."""
    if not value:
        return ""
    # Apple separates a list of artists as "A, B, C & D".  The commas are
    # separators in this API field, not part of a person-name sort format.
    artists = re.split(r"\s*(?:,|\band\b|&)\s*", str(value), flags=re.IGNORECASE)
    return "\\\\".join(artist.strip() for artist in artists if artist.strip())


def _authoritative_collection_name(song, collection):
    """Prefer the lookup's album record over a track's redundant album field."""
    return collection.get("collectionName", "") or song.get("collectionName", "")


def _request_json(url, params, cancel_event=None):
    check_cancelled(cancel_event)
    response = requests.get(
        url,
        params=params,
        headers={"Accept": "application/json", "User-Agent": "MusicMetaAutoTagger/6.0"},
        timeout=12,
    )
    check_cancelled(cancel_event)
    response.raise_for_status()
    return response.json(), response.url


def _search_collections(query, country, no_cache, raw_json_list, cancel_event=None):
    check_cancelled(cancel_event)
    key = (query.casefold(), country)
    if not no_cache and key in _album_search_cache:
        data, url = _album_search_cache[key]
        raw_json_list.append((f"🍎 Apple Music 专辑搜索缓存 [{country.upper()}]", json.dumps(data, indent=4, ensure_ascii=False)))
        return data

    data, url = _request_json(ITUNES_SEARCH_URL, {
        "term": query, "entity": "album", "country": country, "limit": 8,
    }, cancel_event)
    raw_json_list.append((f"🍎 Apple Music 专辑搜索 [{country.upper()}]", f"检索内容: {query}\n请求地址: {url}\n\n" + json.dumps(data, indent=4, ensure_ascii=False)))
    _album_search_cache[key] = (data, url)
    return data


def _lookup_collection(collection_id, country, no_cache, raw_json_list, cancel_event=None):
    check_cancelled(cancel_event)
    key = (str(collection_id), country)
    if not no_cache and key in _album_lookup_cache:
        data, url = _album_lookup_cache[key]
        raw_json_list.append((f"🍎 Apple Music 曲目查询缓存 [{country.upper()}]", json.dumps(data, indent=4, ensure_ascii=False)))
        return data

    data, url = _request_json(ITUNES_LOOKUP_URL, {
        "id": collection_id, "entity": "song", "country": country,
    }, cancel_event)
    raw_json_list.append((f"🍎 Apple Music 专辑及曲目查询 [{country.upper()}]", f"collectionId: {collection_id}\n请求地址: {url}\n\n" + json.dumps(data, indent=4, ensure_ascii=False)))
    _album_lookup_cache[key] = (data, url)
    return data


def _lookup_track(track_id, country, no_cache, raw_json_list, cancel_event=None):
    check_cancelled(cancel_event)
    key = (str(track_id), country)
    if not no_cache and key in _track_lookup_cache:
        data, url = _track_lookup_cache[key]
        raw_json_list.append((f"🍎 Apple Music 艺术家名称候选缓存 [{country.upper()}]", json.dumps(data, indent=4, ensure_ascii=False)))
        return data

    data, url = _request_json(
        ITUNES_LOOKUP_URL,
        {"id": track_id, "country": country},
        cancel_event,
    )
    raw_json_list.append((f"🍎 Apple Music 艺术家名称候选 [{country.upper()}]", f"trackId: {track_id}\n请求地址: {url}\n\n" + json.dumps(data, indent=4, ensure_ascii=False)))
    _track_lookup_cache[key] = (data, url)
    return data


def _resolve_artist_localization(song, collection, no_cache, raw_json_list,
                                 artist_identities, local_artist, cancel_event=None):
    track_id = song.get("trackId")
    if not track_id:
        return song.get("artistName", "") or collection.get("artistName", ""), song.get("collectionArtistName", "") or collection.get("artistName", "")

    variants = []
    home_countries = _artist_home_countries(artist_identities)
    source_country = str(collection.get("_search_country", "")).strip().lower()
    source_artist = song.get("artistName", "") or collection.get("artistName", "")
    if source_country and source_artist:
        variants.append({
            "country": source_country,
            "artist": source_artist,
            "album_artist": song.get("collectionArtistName", "") or collection.get("artistName", "") or source_artist,
        })
        if not home_countries or source_country in home_countries:
            selected = select_artist_variant(
                variants, raw_json_list, artist_identities, local_artist
            )
            return selected["artist"], selected["album_artist"]

    for country in _artist_lookup_countries(collection, artist_identities):
        if country == source_country:
            continue
        check_cancelled(cancel_event)
        try:
            data = _lookup_track(
                track_id, country, no_cache, raw_json_list, cancel_event
            )
            track = next((item for item in data.get("results", []) if item.get("wrapperType") == "track" and item.get("kind") == "song"), None)
            if track:
                variants.append({
                    "country": country,
                    "artist": track.get("artistName", ""),
                    "album_artist": track.get("collectionArtistName", "") or track.get("artistName", ""),
                })
                break
        except (requests.RequestException, ValueError):
            raw_json_list.append((f"🍎 Apple Music 艺术家名称候选失败 [{country.upper()}]", f"trackId: {track_id}"))

    selected = select_artist_variant(variants, raw_json_list, artist_identities, local_artist)
    if selected:
        return selected["artist"], selected["album_artist"]
    return song.get("artistName", "") or collection.get("artistName", ""), song.get("collectionArtistName", "") or collection.get("artistName", "")


def _candidate_score(title, artist, album, local_track, local_disc, song, collection):
    song_title = song.get("trackName", "")
    song_artist = song.get("artistName", "") or collection.get("artistName", "")
    collection_name = _authoritative_collection_name(song, collection)

    title_score = calculate_similarity(title, song_title) if title else 1.0
    album_score = calculate_similarity(album, collection_name) if album else 1.0
    artist_score = calculate_similarity(_normalise_artist(artist), _normalise_artist(song_artist)) if artist else 1.0
    if title:
        score = title_score * 0.50 + album_score * 0.30 + artist_score * 0.20
    else:
        score = album_score * 0.70 + artist_score * 0.30

    # Numbers are strong evidence but do not replace a textual match.
    local_track_number, local_disc_number = safe_int(local_track), safe_int(local_disc)
    if local_track_number is not None and local_track_number == safe_int(song.get("trackNumber")):
        score += 0.08
    if local_disc_number is not None and local_disc_number == safe_int(song.get("discNumber")):
        score += 0.04
    return min(score, 1.0)


def _score_song(title, artist, album, local_track, local_disc, song, collection,
                collection_id_override):
    score = _candidate_score(
        title, artist, album, local_track, local_disc, song, collection
    )
    local_track_number = safe_int(local_track)
    if collection_id_override and local_track_number is not None:
        if local_track_number == safe_int(song.get("trackNumber")) and (
            not local_disc or safe_int(local_disc) == safe_int(song.get("discNumber"))
        ):
            return 1.0
        return 0.0
    return score


def search_apple_music(title, artist, album, local_track, local_disc,
                       mode="auto", no_cache=False, progress_callback=None, artist_identities=None,
                       collection_id_override="", cancel_event=None):
    """Return the best Apple Music track as the application's normal metadata dict.

    Artist home-country storefronts are authoritative when MusicBrainz gives
    us a country.  A sibling storefront may supply a missing track list, but
    the selected track is localized back to the authoritative storefront.
    """
    raw_json_list = []
    check_cancelled(cancel_event)
    collection_id_override = str(collection_id_override or "").strip()
    if collection_id_override and not collection_id_override.isdigit():
        return False, {}, raw_json_list, "Apple Music 专辑 ID 必须为数字或有效的专辑网址"

    query_parts = [part.strip() for part in (album, artist, title) if part and part.strip()]
    query = " ".join(query_parts[:2]) or (title or album or artist).strip()
    if not query and not collection_id_override:
        return False, {}, raw_json_list, "Apple Music 检索缺少标题、专辑或艺术家线索"

    if progress_callback:
        progress_callback("🍎 正在检索 Apple Music 专辑与曲目…")

    collections = []
    if collection_id_override:
        raw_json_list.append((
            "🍎 Apple Music 指定专辑 ID",
            f"collectionId: {collection_id_override}\n将跳过模糊专辑搜索，直接查询专辑曲目表。",
        ))
        collections.append({"collectionId": collection_id_override, "_search_country": "us"})
    else:
        try:
            # A decisive home-storefront result avoids unrelated album and
            # track-list requests in other regions.
            for country in _album_search_countries(artist_identities):
                check_cancelled(cancel_event)
                data = _search_collections(
                    query, country, no_cache, raw_json_list, cancel_event
                )
                storefront_collections = []
                for item in data.get("results", []):
                    if item.get("wrapperType") == "collection" and item.get("collectionId"):
                        item = dict(item)
                        item["_search_country"] = country
                        collections.append(item)
                        storefront_collections.append(item)
                if storefront_collections and max(
                    _collection_baseline(album, artist, item)
                    for item in storefront_collections
                ) >= _DECISIVE_MATCH_SCORE:
                    raw_json_list.append((
                        "🍎 Apple Music 专辑店铺选择",
                        f"{country.upper()} 店铺已有高置信度专辑，跳过其他店铺的模糊搜索。",
                    ))
                    break
        except (requests.RequestException, ValueError) as exc:
            return False, {}, raw_json_list, f"Apple Music 专辑搜索失败: {exc}"

    if not collections:
        return False, {}, raw_json_list, "Apple Music 未找到相关专辑"

    if collection_id_override:
        ranked_collections = collections
    else:
        # Deduplicate global IDs, then inspect only the most plausible albums.
        unique = {}
        for item in collections:
            check_cancelled(cancel_event)
            collection_id = item["collectionId"]
            baseline = _collection_baseline(album, artist, item)
            if collection_id not in unique or baseline > unique[collection_id][0]:
                unique[collection_id] = (baseline, item)

        ranked_collections = [value[1] for value in sorted(unique.values(), key=lambda value: value[0], reverse=True)[:4]]
    candidates = []
    for collection in ranked_collections:
        check_cancelled(cancel_event)
        collection_id = collection["collectionId"]
        preferred_country = collection.get("_search_country", "us")
        collection_candidates = []
        for lookup_country in _collection_lookup_countries(collection):
            check_cancelled(cancel_event)
            try:
                lookup = _lookup_collection(
                    collection_id, lookup_country, no_cache, raw_json_list,
                    cancel_event,
                )
                songs = [item for item in lookup.get("results", []) if item.get("wrapperType") == "track" and item.get("kind") == "song"]
                if not songs:
                    continue
                source_collection = next((item for item in lookup.get("results", []) if item.get("wrapperType") == "collection"), collection)
                source_collection = dict(source_collection)
                source_collection.setdefault("releaseDate", collection.get("releaseDate", ""))
                source_collection["_search_country"] = lookup_country
                storefront_candidates = [
                    (
                        _score_song(
                            title, artist, album, local_track, local_disc,
                            song, source_collection, collection_id_override,
                        ),
                        song,
                        source_collection,
                    )
                    for song in songs
                ]
                best_storefront = max(storefront_candidates, key=lambda value: value[0])

                # Some CN collections expose no track list even though each
                # individual track is localized in CN.  Locate the track in a
                # sibling storefront, then relocalize only that selected ID.
                if preferred_country and preferred_country != lookup_country:
                    track_id = best_storefront[1].get("trackId")
                    if track_id:
                        try:
                            localized_lookup = _lookup_track(
                                track_id, preferred_country, no_cache,
                                raw_json_list, cancel_event,
                            )
                            localized_song = next((
                                item for item in localized_lookup.get("results", [])
                                if item.get("wrapperType") == "track" and item.get("kind") == "song"
                            ), None)
                            if localized_song:
                                localized_collection = dict(collection)
                                localized_collection["_search_country"] = preferred_country
                                best_storefront = (
                                    _score_song(
                                        title, artist, album, local_track,
                                        local_disc, localized_song,
                                        localized_collection,
                                        collection_id_override,
                                    ),
                                    localized_song,
                                    localized_collection,
                                )
                        except (requests.RequestException, ValueError) as exc:
                            raw_json_list.append((
                                f"🍎 Apple Music 单曲本地化失败 [{track_id}/{preferred_country.upper()}]",
                                str(exc),
                            ))

                collection_candidates.append(best_storefront)
                if best_storefront[0] >= _DECISIVE_MATCH_SCORE:
                    break
            except (requests.RequestException, ValueError) as exc:
                raw_json_list.append((
                    f"🍎 Apple Music 曲目查询失败 [{collection_id}/{lookup_country.upper()}]",
                    str(exc),
                ))

        if collection_candidates:
            best_collection = max(collection_candidates, key=lambda value: value[0])
            candidates.append(best_collection)
            if best_collection[0] >= _DECISIVE_MATCH_SCORE:
                break

    if not candidates:
        return False, {}, raw_json_list, "Apple Music 未能获得候选专辑的曲目表"

    score, song, collection = max(candidates, key=lambda value: value[0])
    if score < 0.40 and mode != "only_album":
        return False, {}, raw_json_list, f"Apple Music 曲目匹配度过低 (最高分: {score:.2f})"

    artist_name, album_artist_name = _resolve_artist_localization(
        song, collection, no_cache, raw_json_list, artist_identities or [], artist,
        cancel_event,
    )
    check_cancelled(cancel_event)
    # iTunes can attach a recording's original release date to individual
    # tracks while the collection has its own album release date.  Album
    # metadata must use the collection date so every track in one matched
    # collection receives the same value.
    collection_release_date = collection.get("releaseDate", "")
    track_release_date = song.get("releaseDate", "")
    release_date = collection_release_date or track_release_date
    api_data = {
        "title": song.get("trackName", ""),
        "artist": _format_artist_credit(artist_name),
        "album": _authoritative_collection_name(song, collection),
        "album_artist": _format_artist_credit(album_artist_name),
        "date": str(release_date)[:10],
        "track": str(song.get("trackNumber", "") or ""),
        "disc": str(song.get("discNumber", "") or ""),
        "medium_count": int(song.get("discCount", 1) or 1),
        "composer": song.get("composerName", ""),
        "match_score": score,
        "metadata_source": "Apple Music",
        "is_direct_apple_collection_id": bool(collection_id_override),
        "apple_collection_id": str(collection.get("collectionId", "")),
        # Preserve the matched collection's artwork so the cover workflow can
        # download it directly instead of repeating a fuzzy Apple search.
        "apple_artwork_url": collection.get("artworkUrl100", "") or song.get("artworkUrl100", ""),
        "apple_storefront": collection.get("_search_country", "us"),
        "release_id": "",
    }
    raw_json_list.append(("🍎 Apple Music 最终采纳", json.dumps({
        "match_score": round(score, 4), "collectionId": api_data["apple_collection_id"],
        "title": api_data["title"], "artist": api_data["artist"], "album": api_data["album"],
        "collection_release_date": collection_release_date,
        "track_release_date": track_release_date,
        "applied_album_date": api_data["date"],
    }, indent=4, ensure_ascii=False)))
    return True, api_data, raw_json_list, "Apple Music 元数据提取成功"
