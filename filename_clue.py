"""Conservative filename evidence extraction for an editor draft."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


FILENAME_CLUE_FIELDS = ("title", "artist", "album", "track", "disc")
_AUDIO_EXTENSIONS = {".mp3", ".flac"}
_LEADING_TRACK_PATTERN = re.compile(
    r"^\s*(?P<track>\d{1,3})\s+-\s+(?P<remainder>\S.*)$"
)


class FilenameClueSource(str, Enum):
    LOCAL_RULES = "local_rules"
    DEEPSEEK = "deepseek"


@dataclass(frozen=True)
class FilenameClueResult:
    values: Mapping[str, str]
    source: FilenameClueSource


def analyze_filename_clues(filename: str) -> FilenameClueResult:
    """Return only clues that can be copied directly from a local filename."""
    basename = os.path.basename(str(filename or "")).strip()
    stem, extension = os.path.splitext(basename)
    if extension.casefold() not in _AUDIO_EXTENSIONS:
        stem = basename
    stem = stem.strip()

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
