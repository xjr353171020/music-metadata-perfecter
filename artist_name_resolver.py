# -*- coding: utf-8 -*-
"""Choose the most useful artist-name representation from Apple storefronts."""

import json
import os
import re

import requests

from config import APP_SETTINGS, DEEPSEEK_CHAT_URL
_decision_cache = {}


def select_artist_variant(variants, raw_json_list, artist_identities=None, local_artist=""):
    """Return one official Apple storefront variant without logging secrets.

    The artist's home storefront is authoritative for presentation.  Identity
    evidence validates fallbacks; DeepSeek is never the source of artist data.
    """
    unique = []
    seen = set()
    for variant in variants:
        artist = str(variant.get("artist", "")).strip()
        if not artist:
            continue
        key = (artist.casefold(), str(variant.get("album_artist", "")).strip().casefold())
        if key not in seen:
            unique.append(variant)
            seen.add(key)

    if not unique:
        return {}

    artist_identities = artist_identities or []
    canonical_matches = [
        variant for variant in unique
        if _matches_canonical_identity(variant["artist"], artist_identities)
    ]
    japanese_originals = [
        variant for variant in unique
        if variant.get("country") == "jp"
        and _has_japanese_writing(variant["artist"])
        and _matches_japanese_evidence(variant["artist"], artist_identities, local_artist)
    ]
    home_country_matches = [
        variant for variant in unique
        if variant.get("country", "").upper() in _artist_countries(artist_identities)
    ]
    identity_matches = [variant for variant in unique if _matches_identity(variant["artist"], artist_identities)]
    preferred = [variant for variant in unique if _is_readable_preferred(variant["artist"])]
    candidates = preferred or unique
    if len(home_country_matches) == 1:
        selected = home_country_matches[0]
        decision = "规则：采用艺人国籍店面的官方名称"
    elif len(canonical_matches) == 1:
        selected = canonical_matches[0]
        decision = "规则：国籍店面不可用，候选与 MusicBrainz 主名一致"
    elif len(japanese_originals) == 1:
        selected = japanese_originals[0]
        decision = "规则：官方主名不可用，JP 候选与本地名或 MusicBrainz 日文身份佐证一致"
    elif len(identity_matches) == 1:
        selected = identity_matches[0]
        decision = "规则：候选与 MusicBrainz 别名一致"
    elif len(candidates) == 1:
        selected = candidates[0]
        decision = "规则：唯一可读候选"
    elif len(preferred) == 1:
        selected = preferred[0]
        decision = "规则：优先拉丁字母或日文原名"
    else:
        selected, decision = _choose_tiebreaker(candidates, artist_identities, local_artist)

    raw_json_list.append(("🍎 Apple Music 艺术家名称决策", json.dumps({
        "candidates": unique,
        "local_artist": local_artist,
        "artist_identities": artist_identities,
        "selected": selected,
        "decision": decision,
    }, indent=4, ensure_ascii=False)))
    return selected


def _is_readable_preferred(name):
    has_latin = bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", name))
    has_japanese = bool(re.search(r"[\u3040-\u30ff]", name))
    return has_latin or has_japanese


def _has_japanese_writing(name):
    """A JP storefront makes shared CJK Han characters unambiguously Japanese."""
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", name))


def _matches_japanese_evidence(value, artist_identities, local_artist):
    if _matches_name(value, [local_artist]):
        return True
    return any(
        identity.get("country", "").upper() == "JP"
        and _matches_name(value, _identity_names(identity, japanese_only=True))
        for identity in artist_identities
    )


def _artist_countries(artist_identities):
    return {identity.get("country", "").upper() for identity in artist_identities if identity.get("country")}


def _matches_identity(value, artist_identities):
    return any(_matches_name(value, _identity_names(identity)) for identity in artist_identities)


def _matches_canonical_identity(value, artist_identities):
    return any(
        _matches_name(value, [identity.get("name", "")])
        for identity in artist_identities
    )


def _identity_names(identity, japanese_only=False):
    names = [identity.get("name", "")]
    for alias in identity.get("aliases", []):
        if not japanese_only or alias.get("locale") == "ja":
            names.append(alias.get("name", ""))
    return names


def _matches_name(value, evidence_names):
    candidate_parts = _split_artist_names(value)
    evidence_parts = [part for name in evidence_names for part in _split_artist_names(name)]
    return bool(set(candidate_parts) & set(evidence_parts))


def _split_artist_names(value):
    if not value:
        return []
    return [
        _normalise_name(part)
        for part in re.split(r"\\\\|\s*,\s*|\s+and\s+|\s+&\s+", str(value), flags=re.IGNORECASE)
        if _normalise_name(part)
    ]


def _normalise_name(value):
    return re.sub(r"[\s\-‐‑‒–—―・.'’]", "", str(value)).casefold()


def _choose_tiebreaker(candidates, artist_identities, local_artist):
    cache_key = tuple((item.get("country", ""), item.get("artist", ""), item.get("album_artist", "")) for item in candidates)
    if cache_key in _decision_cache:
        return _decision_cache[cache_key], "DeepSeek 决策缓存"

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or APP_SETTINGS.get("DEEPSEEK_API_KEY", "").strip()
    if api_key:
        selected = _choose_with_deepseek(candidates, artist_identities, local_artist, api_key)
        if selected:
            _decision_cache[cache_key] = selected
            return selected, "DeepSeek deepseek-chat 裁决"

    storefront_order = {"us": 0, "gb": 1, "jp": 2, "fr": 3, "de": 4, "hk": 8, "cn": 9}
    selected = min(candidates, key=lambda item: storefront_order.get(item.get("country", ""), 5))
    return selected, "规则：DeepSeek 未配置或不可用，按店面优先级选择"


def _choose_with_deepseek(candidates, artist_identities, local_artist, api_key):
    payload = {
        "model": "deepseek-chat",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "你只从给定的 Apple Music 官方候选中选择 artist 名称，不能生成新名称。优先艺人国籍店面的官方呈现；该店面不可用时，再匹配 MusicBrainz 主名和别名。不要因 JP 店面就把外国艺人改为日文化名。仅返回 JSON：{\"country\": \"候选的国家代码\"}。",
            },
            {"role": "user", "content": json.dumps({"local_artist": local_artist, "artist_identities": artist_identities, "candidates": candidates}, ensure_ascii=False)},
        ],
    }
    try:
        response = requests.post(
            DEEPSEEK_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        country = json.loads(response.json()["choices"][0]["message"]["content"]).get("country", "")
        return next((item for item in candidates if item.get("country") == country), None)
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None
