"""Conservative filename evidence extraction for an editor draft."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import requests

from config import DEEPSEEK_CHAT_URL
from search_cancellation import check_cancelled


FILENAME_CLUE_FIELDS = ("title", "artist", "album", "track", "disc")
_AUDIO_EXTENSIONS = {".mp3", ".flac"}
_DEEPSEEK_TIMEOUT_SECONDS = 15
_LEADING_TRACK_PATTERN = re.compile(
    r"^\s*(?P<track>\d{1,3})\s+-\s+(?P<remainder>\S.*)$"
)
_DEEPSEEK_SYSTEM_PROMPT = """\
你只负责拆分一个 Windows 音乐文件名主体中明确存在的线索。
只返回一个 JSON 对象，且必须恰好包含以下五个字符串键：
{"title":"","artist":"","album":"","track":"","disc":""}
没有明确线索的字段返回空字符串。不得联网搜索、猜测、翻译、修正、
补全或生成文件名中不存在的字符和事实。数字必须保持文件名中的原始写法。"""


class FilenameClueSource(str, Enum):
    LOCAL_RULES = "local_rules"
    DEEPSEEK = "deepseek"


@dataclass(frozen=True)
class FilenameClueResult:
    values: Mapping[str, str]
    source: FilenameClueSource


def analyze_filename_clues(
    filename: str,
    *,
    api_key: str = "",
    transport=None,
    cancel_event=None,
) -> FilenameClueResult:
    """Analyze one filename, falling back atomically to deterministic rules."""
    stem = _filename_stem(filename)
    check_cancelled(cancel_event)
    api_key = str(api_key or "").strip()
    if api_key:
        request = transport or _request_deepseek
        payload = _deepseek_payload(stem)
        try:
            response_data = request(
                payload=payload,
                api_key=api_key,
                timeout=_DEEPSEEK_TIMEOUT_SECONDS,
            )
            check_cancelled(cancel_event)
            deepseek_values = _validated_deepseek_values(response_data, stem)
            if deepseek_values is not None:
                return FilenameClueResult(
                    deepseek_values,
                    FilenameClueSource.DEEPSEEK,
                )
        except Exception:
            check_cancelled(cancel_event)

    check_cancelled(cancel_event)
    return _analyze_with_local_rules(stem)


def _filename_stem(filename: str) -> str:
    basename = os.path.basename(str(filename or "")).strip()
    stem, extension = os.path.splitext(basename)
    if extension.casefold() not in _AUDIO_EXTENSIONS:
        stem = basename
    return stem.strip()


def _deepseek_payload(stem: str) -> dict:
    return {
        "model": "deepseek-chat",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _DEEPSEEK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps({"filename": stem}, ensure_ascii=False),
            },
        ],
    }


def _request_deepseek(*, payload, api_key, timeout):
    response = requests.post(
        DEEPSEEK_CHAT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _validated_deepseek_values(response_data, stem):
    try:
        content = response_data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            return None
        values = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if type(values) is not dict or set(values) != set(FILENAME_CLUE_FIELDS):
        return None

    validated = {}
    for field in FILENAME_CLUE_FIELDS:
        value = values[field]
        if type(value) is not str:
            return None
        value = value.strip()
        if value and not _value_is_traceable(field, value, stem):
            return None
        validated[field] = value
    return validated


def _value_is_traceable(field, value, stem):
    if field in ("track", "disc"):
        if not re.fullmatch(r"\d{1,3}", value):
            return False
        number = int(value)
        if number < 1 or number > 999:
            return False
        return bool(re.search(rf"(?<!\d){re.escape(value)}(?!\d)", stem))
    return value in stem


def _analyze_with_local_rules(stem: str) -> FilenameClueResult:
    """Return only clues that can be copied directly from a local filename."""

    values = {field: "" for field in FILENAME_CLUE_FIELDS}
    if not stem:
        return FilenameClueResult(values, FilenameClueSource.LOCAL_RULES)

    remainder = stem
    track_match = _LEADING_TRACK_PATTERN.fullmatch(stem)
    if track_match:
        values["track"] = track_match.group("track")
        remainder = track_match.group("remainder").strip()

    parts = remainder.split(" - ")
    if len(parts) == 2 and all(part.strip() for part in parts):
        values["artist"] = parts[0].strip()
        values["title"] = parts[1].strip()
    elif len(parts) == 1:
        values["title"] = remainder
    else:
        values["title"] = stem

    return FilenameClueResult(values, FilenameClueSource.LOCAL_RULES)
