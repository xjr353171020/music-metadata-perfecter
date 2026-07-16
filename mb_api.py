# -*- coding: utf-8 -*-
import requests
import urllib.parse
import time
import difflib
import re
import json
from config import APP_SETTINGS
from search_cancellation import cancellable_wait, check_cancelled

MB_BASE_URL = "https://musicbrainz.org/ws/2"
# MB_USER_AGENT = "MusicMetaAutoTagger/2.0 ( https://github.com/ )"
MB_USER_AGENT = "xjr353171020@126.com"

_release_search_cache = {}
_release_tracklist_cache = {}
_recording_detail_cache = {}
_artist_identity_cache = {}

def init_mb_api(*args, **kwargs):
    pass

def safe_int(val):
    """【新增核心防御】正则表达式提取数字，完美解决 '05' != '5' 和 '05/15' != '5' 的致命问题"""
    if not val: return None
    match = re.search(r'\d+', str(val))
    return int(match.group()) if match else None

def clean_string(s):
    if not s: return ""
    s = re.sub(r'[^\w\s]', ' ', str(s))
    return re.sub(r'\s+', ' ', s).strip().lower()

def calculate_similarity(a, b):
    if not a or not b: return 0.0
    clean_a = clean_string(a)
    clean_b = clean_string(b)
    if not clean_a and not clean_b:
        return difflib.SequenceMatcher(None, str(a).lower().strip(), str(b).lower().strip()).ratio()
    return difflib.SequenceMatcher(None, clean_a, clean_b).ratio()

def get_lucene_words(text, is_artist=False):
    if not text: return [], []
    
    if is_artist:
        text = re.split(r'[,&/]|\\\\', text)[0] 
        text = re.split(r'(?i)\s+feat\.?\s+', text)[0]
        text = re.split(r'(?i)\s+ft\.?\s+', text)[0]
        main_part = text
        sub_part = ""
    else:
        if '-' in text or '—' in text:
            parts = re.split(r'[-—]', text, 1)
            main_part = parts[0]
            sub_part = parts[1]
        elif '(' in text or '[' in text:
            main_part = re.sub(r'[\(\[].*?[\)\]]', ' ', text)
            sub_match = re.search(r'[\(\[](.*?)[\)\]]', text)
            sub_part = sub_match.group(1) if sub_match else ""
        else:
            main_part = text
            sub_part = ""
            
    if not main_part.strip(): main_part = text

    def extract_clean_words(s):
        s = re.sub(r'[^\w\s]', ' ', s)
        stop_words = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'for', 'with', 'by', 'to'}
        words = [w for w in s.split() if w.lower() not in stop_words and len(w) > 0]
        return words
        
    return extract_clean_words(main_part), extract_clean_words(sub_part)

def parse_artist_credit(artist_credit):
    if not artist_credit: return ""
    names = []
    for ac in artist_credit:
        name = ac.get("name", "").strip()
        if name: names.append(name)
    return "\\\\".join(names)


def get_artist_identities(artist_credit, raw_json_list, cancel_event=None):
    """Fetch canonical MusicBrainz artist evidence for name localization."""
    identities = []
    for credit in artist_credit or []:
        check_cancelled(cancel_event)
        artist = credit.get("artist", {})
        artist_id = artist.get("id", "")
        if not artist_id:
            continue
        if artist_id not in _artist_identity_cache:
            identity = {
                "mbid": artist_id,
                "name": artist.get("name", "") or credit.get("name", ""),
                "country": artist.get("country", ""),
                "aliases": [],
            }
            try:
                cancellable_wait(cancel_event, 1.0)
                check_cancelled(cancel_event)
                response = requests.get(
                    f"{MB_BASE_URL}/artist/{artist_id}?inc=aliases&fmt=json",
                    headers=get_headers(),
                    timeout=10,
                )
                check_cancelled(cancel_event)
                if response.status_code == 200:
                    data = response.json()
                    identity["name"] = data.get("name", identity["name"])
                    identity["country"] = data.get("country", identity["country"])
                    identity["aliases"] = [
                        {"name": alias.get("name", ""), "locale": alias.get("locale", ""), "primary": bool(alias.get("primary"))}
                        for alias in data.get("aliases", [])
                        if alias.get("name")
                    ]
            except requests.RequestException:
                pass
            _artist_identity_cache[artist_id] = identity
        identities.append(_artist_identity_cache[artist_id])

    if identities:
        raw_json_list.append(("🌍 MusicBrainz 艺人身份佐证", json.dumps(identities, indent=4, ensure_ascii=False)))
    return identities

def parse_date(date_str):
    if not date_str: return ""
    # 【修复】：移除强制 [:4] 截断，保留 MusicBrainz 返回的完整精度 (YYYY 或 YYYY-MM-DD)
    return str(date_str).strip()

def get_headers():
    return {
        "User-Agent": APP_SETTINGS.get("USER_AGENT", MB_USER_AGENT),
        "Accept": "application/json"
    }

def fetch_recording_by_mbid(mbid, progress_callback=None, cancel_event=None):
    check_cancelled(cancel_event)
    if progress_callback: progress_callback(f"🎯 触发强制单曲模式，正在提取...")
    raw_json_list = []
    try:
        url = f"{MB_BASE_URL}/recording/{mbid}?inc=releases+artist-credits+work-rels+artist-rels&fmt=json"
        check_cancelled(cancel_event)
        resp = requests.get(url, headers=get_headers(), timeout=10)
        check_cancelled(cancel_event)
        if resp.status_code != 200: return False, {}, [], f"MBID 检索失败，HTTP {resp.status_code}"
        
        data = resp.json()
        raw_json_list.append((f"强制获取 MBID Recording: {mbid}", json.dumps(data, indent=4, ensure_ascii=False)))
        
        composers = []
        for rel in data.get("relations", []):
            if rel.get("type") == "composer":
                c_name = rel.get("artist", {}).get("name", "").strip()
                if c_name: composers.append(c_name)
        
        releases = data.get("releases", [])
        rel = releases[0] if releases else {}
        
        api_data = {
            "title": data.get("title", ""),
            "artist": parse_artist_credit(data.get("artist-credit", [])),
            "album": rel.get("title", ""),
            "album_artist": parse_artist_credit(rel.get("artist-credit", [])),
            "date": parse_date(rel.get("date", "")) or parse_date(data.get("first-release-date", "")),
            "track": "", "disc": "", "medium_count": 1,
            "composer": "\\\\".join(composers),
            "is_direct_mbid": True, "match_score": 1.0,
            "release_id": rel.get("id", ""), # 【新增】：供主程序的 Cover Art Archive 搜图使用
            "artist_identities": get_artist_identities(
                data.get("artist-credit", []), raw_json_list, cancel_event
            ),
        }
        return True, api_data, raw_json_list, "通过 MBID 获取成功"
    except Exception as e:
        return False, {}, raw_json_list, f"MBID 解析异常: {str(e)}"


def search_mb(title, artist, album, local_track, local_disc, mbid_override="",
              mode="auto", no_cache=False, progress_callback=None,
              cancel_event=None):
    """加入了无缓存开关与进度播报的全新核心"""
    check_cancelled(cancel_event)
    if artist and re.sub(r'[\.\s]', '', artist).upper() == 'VA': artist = "Various Artists"
    if album and re.sub(r'[\.\s]', '', album).upper() == 'VA': album = "Various Artists"

    raw_json_list = []
    force_is_direct_mbid = False
    release_id = None

    if mbid_override:
        match = re.search(r'/(release|recording)/([a-f0-9\-]{36})', mbid_override)
        if match:
            entity_type = match.group(1)
            mbid_uuid = match.group(2)
        else:
            entity_type = "release"
            mbid_uuid = mbid_override.strip()

        if len(mbid_uuid) != 36: return False, {}, raw_json_list, "MBID 长度不正确，应为36位UUID"
        if entity_type == "recording":
            return fetch_recording_by_mbid(
                mbid_uuid, progress_callback, cancel_event
            )
        if entity_type == "release":
            release_id = mbid_uuid
            force_is_direct_mbid = True
            raw_json_list.append((f"🎯 触发强制专辑 MBID 模式", f"ID: {release_id}，直接进入音轨比对流程..."))

    album_main, album_sub = get_lucene_words(album, is_artist=False)
    title_main, title_sub = get_lucene_words(title, is_artist=False)
    artist_main, _ = get_lucene_words(artist, is_artist=True)
    
    q_artist = " AND ".join(artist_main[:3]) if artist_main else ""
    q_album_base = " AND ".join(album_main[:4]) if album_main else ""
    q_album_strict = " AND ".join(album_main[:4] + album_sub[:4]) if album_sub else ""

    target_release_title = ""
    target_release_artist = ""
    target_release_date = ""

    # ==========================================
    # 【第一步】：锁定目标专辑
    # ==========================================
    if not release_id and (q_album_base or q_artist) and mode != "title":
        step1_cache_key = (tuple(album_main), tuple(album_sub), tuple(artist_main), mode)
        
        if not no_cache and step1_cache_key in _release_search_cache:
            release_id, target_release_title, target_release_artist, target_release_date = _release_search_cache[step1_cache_key]
            raw_json_list.append((f"⚡ 缓存命中 | 第一步 专辑搜索复用", "该步骤已命中缓存，光速跳过网络耗时。"))
            if progress_callback: progress_callback("⚡ [1/3] 缓存命中，已锁定专辑实体...")
        else:
            if progress_callback: progress_callback("⏳ [1/3] 正在全网检索并锁定匹配专辑...")
            queries_step1 = []
            def add_to_queue(q_alb):
                if not q_alb: return
                if q_artist:
                    queries_step1.append(f'release:({q_alb}) AND artist:({q_artist})')
                    queries_step1.append(f'release:({q_alb}) AND ({q_artist})')
                queries_step1.append(f'release:({q_alb})')

            if q_album_strict: add_to_queue(q_album_strict)
            if q_album_base: add_to_queue(q_album_base)
            if q_artist: queries_step1.append(f'artist:({q_artist})')
            
            seen = set()
            queries_step1 = [x for x in queries_step1 if not (x in seen or seen.add(x))]

            for idx, q_album in enumerate(queries_step1):
                check_cancelled(cancel_event)
                if release_id: break
                try:
                    url = f"{MB_BASE_URL}/release?query={urllib.parse.quote(q_album)}&fmt=json&limit=25"
                    cancellable_wait(cancel_event, 1.0)
                    resp = requests.get(url, headers=get_headers(), timeout=10)
                    check_cancelled(cancel_event)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_json_list.append((f"【第一步】专辑筛选 Tier {idx+1} | 语句: {q_album}", json.dumps(data, indent=4, ensure_ascii=False)))
                        
                        releases = data.get("releases", [])
                        best_rel = None
                        max_rel_score = -1.0
                        
                        for rel in releases:
                            check_cancelled(cancel_event)
                            r_title = rel.get("title", "")
                            r_artist = parse_artist_credit(rel.get("artist-credit", []))
                            score_alb = calculate_similarity(album, r_title)
                            score_art = calculate_similarity(artist, r_artist)
                            current_rel_score = score_alb * 0.75 + score_art * 0.25
                            if current_rel_score > max_rel_score:
                                max_rel_score = current_rel_score
                                best_rel = rel
                        
                        if best_rel and max_rel_score >= 0.25:
                            release_id = best_rel.get("id")
                            target_release_title = best_rel.get("title", "")
                            target_release_artist = parse_artist_credit(best_rel.get("artist-credit", []))
                            target_release_date = parse_date(best_rel.get("date", ""))
                            _release_search_cache[step1_cache_key] = (release_id, target_release_title, target_release_artist, target_release_date)
                except Exception as e:
                    print(f"Step 1 Release search error: {e}")

    # ==========================================
    # 【第一步补救】：反查
    # ==========================================
    q_title_base = " AND ".join(title_main[:4]) if title_main else ""
    q_title_strict = " AND ".join((title_main[:4] + title_sub[:4])) if title_sub else ""

    if not release_id and q_title_base:
        if progress_callback: progress_callback("⏳ [1/3 降级] 专辑未找到，正在通过曲目标题反查...")
        queries_fallback = []
        def add_to_fallback(q_tit):
            if not q_tit: return
            if q_artist:
                queries_fallback.append(f'recording:({q_tit}) AND artist:({q_artist})')
                queries_fallback.append(f'recording:({q_tit}) AND ({q_artist})')
            queries_fallback.append(f'recording:({q_tit})')
            
        if q_title_strict: add_to_fallback(q_title_strict)
        add_to_fallback(q_title_base)
        seen = set()
        queries_fallback = [x for x in queries_fallback if not (x in seen or seen.add(x))]

        for idx, q_title in enumerate(queries_fallback):
            check_cancelled(cancel_event)
            if release_id: break
            try:
                url = f"{MB_BASE_URL}/recording?query={urllib.parse.quote(q_title)}&inc=releases+artist-credits&fmt=json&limit=15"
                cancellable_wait(cancel_event, 1.0)
                resp = requests.get(url, headers=get_headers(), timeout=10)
                check_cancelled(cancel_event)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_json_list.append((f"【降级补救】反查 Tier {idx+1} | 语句: {q_title}", json.dumps(data, indent=4, ensure_ascii=False)))
                    recordings = data.get("recordings", [])
                    best_rel_cand = None
                    max_track_rel_score = -1.0
                    for rec in recordings:
                        check_cancelled(cancel_event)
                        rec_releases = rec.get("releases", [])
                        rec_artist = parse_artist_credit(rec.get("artist-credit", []))
                        score_art = calculate_similarity(artist, rec_artist)
                        for rel in rec_releases:
                            check_cancelled(cancel_event)
                            r_title = rel.get("title", "")
                            score_alb = calculate_similarity(album, r_title) if album else 1.0
                            total_cand_score = score_alb * 0.6 + score_art * 0.4
                            if total_cand_score > max_track_rel_score:
                                max_track_rel_score = total_cand_score
                                best_rel_cand = rel
                    if best_rel_cand:
                        release_id = best_rel_cand.get("id")
                        target_release_title = best_rel_cand.get("title", "")
                        target_release_artist = parse_artist_credit(best_rel_cand.get("artist-credit", []))
                        target_release_date = parse_date(best_rel_cand.get("date", ""))
            except Exception as e:
                print(f"Fallback recording search error: {e}")

    if not release_id:
        return False, {}, raw_json_list, "未能通过 MusicBrainz 锁定相关的具体专辑实体"

    # ==========================================
    # 【第二步】：调取专辑完整音轨数据链
    # ==========================================
    track_candidates = []
    release_detail = None
    
    if not no_cache and release_id in _release_tracklist_cache:
        if progress_callback: progress_callback("⚡ [2/3] 缓存命中，正在精准定位音轨...")
        release_detail = _release_tracklist_cache[release_id]
        raw_json_list.append((f"⚡ 缓存命中 | 第二步 专辑音轨复用 (ID: {release_id})", "该专辑音轨数据已缓存，光速跳过网络耗时。"))
    else:
        if progress_callback: progress_callback("⏳ [2/3] 正在拉取该专辑全碟音轨数据...")
        try:
            url = f"{MB_BASE_URL}/release/{release_id}?inc=recordings+artist-credits&fmt=json"
            cancellable_wait(cancel_event, 1.0)
            resp = requests.get(url, headers=get_headers(), timeout=10)
            check_cancelled(cancel_event)
            if resp.status_code == 200:
                release_detail = resp.json()
                raw_json_list.append(("【第二步】精确专辑官方 Tracklist 全量详情", json.dumps(release_detail, indent=4, ensure_ascii=False)))
                _release_tracklist_cache[release_id] = release_detail
            else:
                return False, {}, raw_json_list, f"获取专辑详情失败，HTTP 错误代码 {resp.status_code}"
        except Exception as e:
            return False, {}, raw_json_list, f"解析专辑音轨链时遭遇异常: {str(e)}"

    if release_detail:
        if not target_release_title: target_release_title = release_detail.get("title", "")
        if not target_release_artist: target_release_artist = parse_artist_credit(release_detail.get("artist-credit", []))
        if not target_release_date: 
            target_release_date = parse_date(release_detail.get("date", ""))
            if not target_release_date and release_detail.get("release-events"):
                target_release_date = parse_date(release_detail["release-events"][0].get("date", ""))

        media = release_detail.get("media", [])
        
        # 预先将用户传入的 track 和 disc 安全转化为整数，防止 "05" != "5"
        local_t_int = safe_int(local_track)
        local_d_int = safe_int(local_disc)

        for m in media:
            check_cancelled(cancel_event)
            disc_num = str(m.get("position", "1"))
            disc_num_int = safe_int(disc_num)
            
            tracks = m.get("tracks", [])
            for t in tracks:
                check_cancelled(cancel_event)
                t_title = t.get("title", "")
                t_num = str(t.get("number", ""))
                t_pos = str(t.get("position", ""))
                
                t_num_int = safe_int(t_num)
                t_pos_int = safe_int(t_pos)
                
                rec_obj = t.get("recording", {})
                rec_id = rec_obj.get("id", "")
                track_artist_credit = t.get("artist-credit", []) or rec_obj.get("artist-credit", [])
                t_artist = parse_artist_credit(track_artist_credit)
                
                score_t_title = calculate_similarity(title, t_title)
                score_t_artist = calculate_similarity(artist, t_artist)
                
                track_match_score = score_t_title * 0.75 + score_t_artist * 0.25
                
                # 【终极修正】：利用数字提取法进行绝对匹配！赋予其统治级的权重 2.0！
                if local_t_int is not None and (local_t_int == t_num_int or local_t_int == t_pos_int): 
                    track_match_score += 2.0  
                if local_d_int is not None and local_d_int == disc_num_int: 
                    track_match_score += 0.5  
                    
                track_candidates.append({
                    "recording_id": rec_id,
                    "track_title": t_title,
                    "track_artist": t_artist if t_artist else target_release_artist,
                    "artist_credit": track_artist_credit,
                    "track_no": t_num, "disc_no": disc_num,
                    "medium_count": len(media), "score": track_match_score,
                    "first_release_date": parse_date(rec_obj.get("first-release-date", ""))
                })

    if not track_candidates: return False, {}, raw_json_list, "该专辑下未提取到任何有效音轨"

    track_candidates.sort(key=lambda x: x["score"], reverse=True)
    best_track = track_candidates[0]
    
    if not target_release_date: target_release_date = best_track["first_release_date"]
    
    if best_track["score"] < 0.35 and mode != "only_album" and not force_is_direct_mbid:
        return False, {}, raw_json_list, f"在专辑内进行音轨匹配失败，相似度过低 (最高分: {best_track['score']:.2f})"

    recording_id = best_track["recording_id"]

    # ==========================================
    # 【第三步】：单曲终透视
    # ==========================================
    composer = ""
    final_title = best_track["track_title"]
    final_artist = best_track["track_artist"]
    final_artist_credit = best_track.get("artist_credit", [])
    recording_detail = None
    
    if recording_id:
        if not no_cache and recording_id in _recording_detail_cache:
            if progress_callback: progress_callback("⚡ [3/3] 缓存命中，光速补全单曲关系...")
            recording_detail = _recording_detail_cache[recording_id]
            raw_json_list.append((f"⚡ 缓存命中 | 第三步 单曲详情复用 (ID: {recording_id})", "该单曲详情已缓存，光速跳过网络耗时。"))
        else:
            if progress_callback: progress_callback("⏳ [3/3] 正在深度透视单曲(作曲家等)隐藏关联...")
            try:
                url = f"{MB_BASE_URL}/recording/{recording_id}?inc=work-rels+artist-credits+artist-rels&fmt=json"
                cancellable_wait(cancel_event, 1.0)
                resp = requests.get(url, headers=get_headers(), timeout=10)
                check_cancelled(cancel_event)
                if resp.status_code == 200:
                    recording_detail = resp.json()
                    raw_json_list.append(("【第三步】单曲终点站深度关系回执", json.dumps(recording_detail, indent=4, ensure_ascii=False)))
                    _recording_detail_cache[recording_id] = recording_detail
            except Exception as e:
                print(f"Step 3 Recording detail error: {e}")

        if recording_detail:
            if recording_detail.get("title"): final_title = recording_detail.get("title")
            if recording_detail.get("artist-credit"):
                final_artist_credit = recording_detail.get("artist-credit")
                final_artist = parse_artist_credit(final_artist_credit)
            if not target_release_date: target_release_date = parse_date(recording_detail.get("first-release-date", ""))
                
            composers = []
            for rel in recording_detail.get("relations", []):
                check_cancelled(cancel_event)
                if rel.get("type") == "composer":
                    c_name = rel.get("artist", {}).get("name", "").strip()
                    if c_name: composers.append(c_name)
            composer = "\\\\".join(composers)

    check_cancelled(cancel_event)
    api_data = {
        "title": final_title,
        "artist": final_artist if final_artist else target_release_artist,
        "album": target_release_title,
        "album_artist": target_release_artist,
        "date": target_release_date,
        "track": best_track["track_no"],
        "disc": best_track["disc_no"],
        "medium_count": best_track["medium_count"],
        "composer": composer,
        "is_direct_mbid": force_is_direct_mbid,
        "match_score": min(best_track["score"], 1.0),
        "release_id": release_id, # 【新增】：供主程序的 Cover Art Archive 搜图使用
        "artist_identities": get_artist_identities(
            final_artist_credit, raw_json_list, cancel_event
        ),
    }

    if progress_callback: progress_callback("✅ 元数据提取及匹配完成！")
    return True, api_data, raw_json_list, "全链路精准提取成功"

