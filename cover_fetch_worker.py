# -*- coding: utf-8 -*-
"""Background worker for Apple Music and Cover Art Archive artwork retrieval."""

import json
import re
import threading
import urllib.parse

import requests
from PyQt6.QtCore import QThread, pyqtSignal


class CoverFetchWorker(QThread):
    progress_sig = pyqtSignal(str)
    finished_sig = pyqtSignal(list, dict, list, int, bool)

    def __init__(self, artist, album, release_id, apple_artwork_url="", apple_storefront="", request_id=0, cancel_event=None):
        super().__init__()
        self.artist = artist
        self.album = album
        self.release_id = release_id
        self.apple_artwork_url = apple_artwork_url
        self.apple_storefront = apple_storefront
        self.request_id = request_id
        self.cancel_event = cancel_event or threading.Event()

    def cancel(self):
        self.cancel_event.set()
        self.requestInterruption()

    def _cancelled(self):
        return self.cancel_event.is_set() or self.isInterruptionRequested()

    def _finish_cancelled(self, results, stats, raw_json_list):
        self.finished_sig.emit(results, stats, raw_json_list, self.request_id, True)

    def _request(self, session, url, **kwargs):
        retry_statuses = {429, 500, 502, 503, 504}
        last_response = None
        for attempt in range(4):
            if self._cancelled():
                return None
            try:
                last_response = session.get(url, **kwargs)
            except requests.exceptions.RequestException:
                if attempt == 3:
                    raise
            else:
                if last_response.status_code not in retry_statuses or attempt == 3:
                    return last_response
            if self.cancel_event.wait(0.5 * (attempt + 1)):
                return None
        return last_response

    def run(self):
        from mb_api import calculate_similarity

        results = []
        stats = {"am": "未请求", "mb": "未请求"}
        raw_json_list = []
        headers = {
            "User-Agent": "MusicMetaAutoTagger/2.0 ( https://github.com/ )",
            "Accept": "application/json",
        }
        session = requests.Session()

        if self._cancelled():
            self._finish_cancelled(results, stats, raw_json_list)
            return

        self.progress_sig.emit("正在极速抓取 Apple Music 终极画质封面...")
        try:
            queries_to_try = []
            if self.album and self.artist:
                queries_to_try.append(f"{self.album} {self.artist}".strip())
            if self.album:
                queries_to_try.append(self.album.strip())
                clean_alb = re.sub(r"[^\w\u4e00-\u9fa5\u3040-\u30ff\u3400-\u4dbf]", " ", self.album)
                clean_alb = re.sub(r"\s+", " ", clean_alb).strip()
                if clean_alb and clean_alb != self.album.strip():
                    queries_to_try.append(clean_alb)
            seen = set()
            queries = [query for query in queries_to_try if not (query in seen or seen.add(query))]

            # A metadata search already gives us the exact Apple collection.
            # Prefer that cover and skip another fuzzy query entirely.
            regions = [] if self.apple_artwork_url else ["us", "gb", "jp", "cn"]
            entity_types = ["album", ""]
            best_score = 1.0 if self.apple_artwork_url else -1.0
            best_img_url = self.apple_artwork_url
            best_region = self.apple_storefront.upper()
            best_req_tag = "Metadata cache" if self.apple_artwork_url else ""
            best_collection_name = self.album if self.apple_artwork_url else ""
            found_satisfactory = bool(self.apple_artwork_url)

            for region in regions:
                if self._cancelled():
                    self._finish_cancelled(results, stats, raw_json_list)
                    return
                for query in queries:
                    if self._cancelled():
                        self._finish_cancelled(results, stats, raw_json_list)
                        return
                    for entity_type in entity_types:
                        if self._cancelled():
                            self._finish_cancelled(results, stats, raw_json_list)
                            return
                        ent_param = f"&entity={entity_type}" if entity_type else ""
                        req_tag = f"{region.upper()}|{'Album' if entity_type else 'All'}"
                        req_url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}{ent_param}&country={region}&limit=5"
                        raw_json_list.append((f"AM 请求指令 [{req_tag}]", f"检索内容: {query}\n请求地址: {req_url}"))
                        try:
                            response = self._request(session, req_url, timeout=10)
                            if self._cancelled():
                                self._finish_cancelled(results, stats, raw_json_list)
                                return
                            if response.status_code == 200:
                                data = response.json()
                                if data.get("resultCount", 0) > 0:
                                    raw_json_list.append((f"AM 返回 JSON [{req_tag}]", json.dumps(data, indent=4, ensure_ascii=False)))
                                    for item in data.get("results", []):
                                        if self._cancelled():
                                            self._finish_cancelled(results, stats, raw_json_list)
                                            return
                                        collection_name = item.get("collectionName", "")
                                        artist_name = item.get("artistName", "")
                                        image_url = item.get("artworkUrl100", "")
                                        if image_url:
                                            album_score = calculate_similarity(self.album, collection_name)
                                            artist_score = calculate_similarity(self.artist, artist_name) if self.artist else 1.0
                                            total_score = album_score * 0.75 + artist_score * 0.25
                                            if total_score > best_score:
                                                best_score = total_score
                                                best_img_url = image_url
                                                best_region = region
                                                best_req_tag = req_tag
                                                best_collection_name = collection_name
                                            if best_score >= 0.75:
                                                found_satisfactory = True
                                                break
                                else:
                                    raw_json_list.append((f"AM 数据落空 [{req_tag}]", "当前参数未命中数据。"))
                            else:
                                raw_json_list.append((f"AM 请求失败 [{req_tag}]", f"HTTP {response.status_code}\n{response.text}"))
                        except requests.exceptions.RequestException as exc:
                            raw_json_list.append((f"AM 网络异常 [{req_tag}]", str(exc)))
                        if found_satisfactory:
                            break
                    if found_satisfactory:
                        break
                if found_satisfactory:
                    break

            if best_img_url and best_score >= 0.25:
                high_res_url = best_img_url.replace("100x100bb", "10000x10000bb")
                raw_json_list.append(("AM 最终采纳与试图下载", f"匹配专辑: {best_collection_name}\n综合得分: {best_score:.2f}\n检索组合: {best_req_tag}\n升采样 URL: {high_res_url}"))
                try:
                    if self._cancelled():
                        self._finish_cancelled(results, stats, raw_json_list)
                        return
                    image_response = self._request(session, high_res_url, timeout=15)
                    if self._cancelled():
                        self._finish_cancelled(results, stats, raw_json_list)
                        return
                    if image_response.status_code == 200:
                        results.append({"source": "🍎 Apple Music", "data": image_response.content})
                        if self.apple_artwork_url:
                            stats["am"] = f"复用元数据命中封面 ({best_region or 'US'})"
                        else:
                            stats["am"] = f"命中 1 张 (得分 {best_score:.2f} | {best_region.upper()})"
                    else:
                        stats["am"] = f"图片下载失败 HTTP {image_response.status_code}"
                        raw_json_list.append(("AM 图片下载失败", f"HTTP 状态码: {image_response.status_code}"))
                except requests.exceptions.RequestException as exc:
                    stats["am"] = f"图片下载异常 ({type(exc).__name__})"
                    raw_json_list.append(("AM 图片下载异常", str(exc)))
            else:
                stats["am"] = f"未找到达标结果 (最高分 {best_score:.2f})"
                raw_json_list.append(("AM 最终放弃", f"最高得分 {best_score:.2f} 低于及格线(0.25)或无图，已安全放弃。"))
        except Exception as exc:
            stats["am"] = f"搜索异常 ({type(exc).__name__})"
            raw_json_list.append(("AM 主程序异常", str(exc)))

        if self.release_id:
            if self._cancelled():
                self._finish_cancelled(results, stats, raw_json_list)
                return
            self.progress_sig.emit("正在抓取 MusicBrainz 官方/社区封面...")
            try:
                caa_url = f"https://coverartarchive.org/release/{self.release_id}"
                raw_json_list.append(("MB/CAA 请求指令", f"目标 MBID: {self.release_id}\n请求地址: {caa_url}"))
                response = self._request(
                    session, caa_url, headers=headers, timeout=10,
                    allow_redirects=True,
                )
                if self._cancelled():
                    self._finish_cancelled(results, stats, raw_json_list)
                    return
                if response.status_code == 200:
                    data = response.json()
                    raw_json_list.append(("MB/CAA 返回 JSON", json.dumps(data, indent=4, ensure_ascii=False)))
                    found = False
                    for image in data.get("images", []):
                        if self._cancelled():
                            self._finish_cancelled(results, stats, raw_json_list)
                            return
                        if image.get("front"):
                            image_url = image.get("image")
                            if image_url:
                                raw_json_list.append(("MB/CAA 试图下载地址", image_url))
                                image_response = self._request(
                                    session, image_url, headers=headers, timeout=15,
                                    allow_redirects=True,
                                )
                                if self._cancelled():
                                    self._finish_cancelled(results, stats, raw_json_list)
                                    return
                                if image_response.status_code == 200:
                                    results.append({"source": "🌍 MusicBrainz", "data": image_response.content})
                                    stats["mb"] = "命中 1 张 (官方 Front 图)"
                                    found = True
                                    break
                                raw_json_list.append(("MB/CAA 图片下载失败", f"HTTP 状态码: {image_response.status_code}"))
                    if not found:
                        stats["mb"] = "数据存在，但未标记 Front 图"
                elif response.status_code == 404:
                    stats["mb"] = "该专辑暂无社区传图 (404)"
                    raw_json_list.append(("MB/CAA 404 追踪", f"社区暂未上传该实体专辑封面 (MBID: {self.release_id})"))
                elif response.status_code == 403:
                    stats["mb"] = "防火墙拦截访问 (403)"
                else:
                    stats["mb"] = f"请求失败 HTTP {response.status_code}"
                    raw_json_list.append(("MB/CAA 请求失败", f"HTTP {response.status_code}\n{response.text}"))
            except requests.exceptions.RequestException as exc:
                stats["mb"] = f"网络连接异常 ({type(exc).__name__})"
                raw_json_list.append(("MB/CAA 网络异常追踪", str(exc)))
        else:
            stats["mb"] = "缺少 Release MBID，跳过查询"
            raw_json_list.append(("MB/CAA 被跳过", "未能提供 Release ID，无法向 MusicBrainz 发起封面检索。"))
        self.finished_sig.emit(results, stats, raw_json_list, self.request_id, False)
