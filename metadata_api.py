# -*- coding: utf-8 -*-
"""Combine MusicBrainz and Apple Music into one metadata-search result."""
import difflib
import json
import re

from apple_music_api import search_apple_music
from mb_api import calculate_similarity, search_mb
from search_cancellation import check_cancelled


def _text_similarity(expected, actual):
    """Combine semantic matching with a small exact-presentation preference."""
    if not expected or not actual:
        return 0.0
    semantic = calculate_similarity(expected, actual)
    literal = difflib.SequenceMatcher(
        None,
        re.sub(r"\s+", " ", str(expected)).strip().casefold(),
        re.sub(r"\s+", " ", str(actual)).strip().casefold(),
    ).ratio()
    return semantic * 0.85 + literal * 0.15


def _artist_similarity(expected, actual):
    """Do not penalize a source for listing collaborators after the lead artist."""
    if not expected or not actual:
        return 0.0
    candidates = [part.strip() for part in re.split(r"\\\\|\s*,\s*|\s+and\s+|\s+&\s+", str(actual), flags=re.IGNORECASE) if part.strip()]
    return max((_text_similarity(expected, candidate) for candidate in candidates), default=0.0)


def _comparison_score(title, artist, album, data):
    """Score source outputs by their textual evidence only.

    Track/disc numbers are useful to find a track inside a release, but they
    must not turn an unrelated release into a 100% metadata match.  Keeping
    this score separate fixes ties such as ``Tonight Chopin: 19 Waltzes`` vs
    the exact Apple collection ``Chopin: 19 Waltzes``.
    """
    comparisons = (
        (title, data.get("title", ""), 0.50, _text_similarity),
        (artist, data.get("artist", ""), 0.20, _artist_similarity),
        (album, data.get("album", ""), 0.30, _text_similarity),
    )
    available = [(expected, actual, weight, scorer) for expected, actual, weight, scorer in comparisons if expected]
    if not available:
        return 0.0
    weight_total = sum(weight for _, _, weight, _ in available)
    return sum(scorer(expected, actual) * weight for expected, actual, weight, scorer in available) / weight_total


def search_metadata(title, artist, album, local_track, local_disc, mbid_override="",
                    mode="auto", no_cache=False, progress_callback=None,
                    apple_collection_id_override="", cancel_event=None):
    raw_json_list = []
    check_cancelled(cancel_event)
    if progress_callback:
        progress_callback("🌐 正在从 MusicBrainz 和 Apple Music 检索元数据…")

    mb_ok, mb_data, mb_raw, mb_msg = search_mb(
        title, artist, album, local_track, local_disc, mbid_override, mode,
        no_cache, progress_callback, cancel_event=cancel_event
    )
    check_cancelled(cancel_event)
    raw_json_list.extend((f"🌍 MusicBrainz | {name}", content) for name, content in mb_raw)

    # A manually supplied MBID is an explicit user choice; still query Apple
    # for traceability, but never let a fuzzy Apple candidate override it.
    am_ok, am_data, am_raw, am_msg = search_apple_music(
        title, artist, album, local_track, local_disc, mode, no_cache, progress_callback,
        mb_data.get("artist_identities", []) if mb_ok else [],
        apple_collection_id_override,
        cancel_event=cancel_event,
    )
    check_cancelled(cancel_event)
    raw_json_list.extend(am_raw)

    if mb_ok:
        mb_data["metadata_source"] = "MusicBrainz"
    candidates = [data for ok, data in ((mb_ok, mb_data), (am_ok, am_data)) if ok]
    if not candidates:
        return False, {}, raw_json_list, f"MusicBrainz：{mb_msg}\nApple Music：{am_msg}"

    for data in candidates:
        data["engine_match_score"] = data.get("match_score", 0.0)
        data["source_quality_score"] = 1.0 if (data.get("is_direct_mbid") or data.get("is_direct_apple_collection_id")) else _comparison_score(title, artist, album, data)
        # The UI's confidence and cross-source selection use comparable text
        # evidence, not MusicBrainz's internal track-position bonus.
        data["match_score"] = data["source_quality_score"]

    raw_json_list.append(("📊 信息源评分对照", json.dumps({
        data.get("metadata_source", "未知"): {
            "engine_match_score": round(data["engine_match_score"], 4),
            "normalized_match_score": round(data["source_quality_score"], 4),
            "title": data.get("title", ""),
            "artist": data.get("artist", ""),
            "album": data.get("album", ""),
        }
        for data in candidates
    }, indent=4, ensure_ascii=False)))

    if mbid_override and mb_ok:
        best = mb_data
    elif apple_collection_id_override and am_ok:
        best = am_data
    else:
        # On a genuine textual tie prefer MusicBrainz: it includes recording
        # relationships and a release ID for Cover Art Archive.
        best = max(candidates, key=lambda data: (data["source_quality_score"], data.get("metadata_source") == "MusicBrainz"))
    comparison = "；".join(
        f"{data.get('metadata_source', '未知')} {data['source_quality_score']:.0%}"
        for data in candidates
    )
    # Keep normalized output from every successful source so the UI can let
    # the user explicitly choose one after inspecting the comparison.
    best["source_results"] = {
        data["metadata_source"]: dict(data)
        for data in candidates
    }
    best["source_comparison"] = comparison
    return True, best, raw_json_list, f"已比较信息源：{comparison}；采纳 {best.get('metadata_source', '未知')}"
