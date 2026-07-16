"""Pure business rules for converting editor state into tag write operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Mapping, Sequence


Metadata = dict[str, Any]


@dataclass(frozen=True)
class SaveItem:
    """One file write, optionally dependent on a previous successful write."""

    path: str
    metadata: Mapping[str, Any]
    cover_data: bytes | None = None
    write_cover: bool = False
    kind: str = "primary"
    depends_on: str | None = None


@dataclass(frozen=True)
class SavePlan:
    items: tuple[SaveItem, ...] = ()


@dataclass(frozen=True)
class SavePlanRequest:
    """Plain editor state required to build a save plan.

    ``field_updates`` contains only the fields the user elected to write.
    ``checked_fields`` is retained separately because album synchronization
    follows checkbox state, including values that did not change on the source.
    """

    selected_paths: Sequence[str]
    field_updates: Mapping[str, Any]
    checked_fields: frozenset[str]
    cover_modified: bool
    cover_data: bytes | None
    all_files_data: Mapping[str, Mapping[str, Any]]
    selected_files_data: Mapping[str, Mapping[str, Any]]
    locks_data: Mapping[str, Mapping[str, bool]]
    album_sync_keys: Sequence[str]
    virtual_album_map: Mapping[str, Any]
    track_paths: Sequence[str]


def build_save_plan(request: SavePlanRequest) -> SavePlan:
    """Build all direct and dependent tag writes without touching the filesystem."""
    primary_items = tuple(
        SaveItem(
            path=path,
            metadata=dict(request.field_updates),
            cover_data=request.cover_data,
            write_cover=request.cover_modified,
        )
        for path in request.selected_paths
    )

    if len(request.selected_paths) != 1:
        return SavePlan(primary_items)

    reference_path = request.selected_paths[0]
    sync_items = _build_album_sync_items(request, reference_path)
    return SavePlan(primary_items + tuple(sync_items))


def _build_album_sync_items(request: SavePlanRequest, reference_path: str) -> list[SaveItem]:
    reference_original = request.selected_files_data.get(
        reference_path, request.all_files_data.get(reference_path, {})
    )
    reference_final = dict(request.all_files_data.get(reference_path, reference_original))
    reference_final.update(request.field_updates)
    if request.cover_modified:
        reference_final["cover_data"] = request.cover_data

    reference_group = request.virtual_album_map.get(reference_path)
    new_album = str(reference_final.get("album", "")).strip()
    new_cover = reference_final.get("cover_data")
    sync_keys = tuple(key for key in request.album_sync_keys if key != "album")
    items: list[SaveItem] = []

    for other_path in request.track_paths:
        if other_path == reference_path or not _is_same_album(
            request, reference_path, other_path, reference_original, reference_group
        ):
            continue

        other_data = request.all_files_data.get(other_path, {})
        other_locks = request.locks_data.get(other_path, {})
        needs_sync = False

        if new_album and other_data.get("album", "") != new_album and not other_locks.get("album", False):
            needs_sync = True

        for key in sync_keys:
            new_value = reference_final.get(key)
            if (
                key in request.checked_fields
                and not other_locks.get(key, False)
                and new_value is not None
                and other_data.get(key) != new_value
            ):
                needs_sync = True

        if new_cover and other_data.get("cover_data") != new_cover:
            needs_sync = True

        if not needs_sync:
            continue

        metadata: Metadata = {}
        if new_album and not other_locks.get("album", False):
            metadata["album"] = new_album
        for key in sync_keys:
            new_value = reference_final.get(key)
            if key in request.checked_fields and not other_locks.get(key, False) and new_value is not None:
                metadata[key] = new_value

        items.append(
            SaveItem(
                path=other_path,
                metadata=metadata,
                cover_data=new_cover if new_cover else None,
                write_cover=bool(new_cover),
                kind="sync",
                depends_on=reference_path,
            )
        )

    return items


def _is_same_album(
    request: SavePlanRequest,
    reference_path: str,
    candidate_path: str,
    reference_data: Mapping[str, Any],
    reference_group: Any,
) -> bool:
    if reference_group is not None:
        return request.virtual_album_map.get(candidate_path) == reference_group
    if candidate_path in request.virtual_album_map:
        return False

    candidate_data = request.all_files_data.get(candidate_path, {})
    reference_album = str(reference_data.get("album", "")).strip()
    return (
        bool(reference_album)
        and reference_album == str(candidate_data.get("album", "")).strip()
        and _cover_fingerprint(reference_data.get("cover_data"))
        == _cover_fingerprint(candidate_data.get("cover_data"))
    )


def _cover_fingerprint(cover_data: bytes | None) -> str:
    if not cover_data:
        return "no-cover"
    return sha256(cover_data).hexdigest()
