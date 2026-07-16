"""In-memory state for one music metadata editing session."""

from __future__ import annotations

from typing import Any, Iterable


class AlbumSession:
    """Own mutable editor state without UI or filesystem dependencies."""

    DEFAULT_ALBUM_SYNC_KEYS = ["album", "album_artist", "date", "genre"]

    def __init__(self) -> None:
        self.all_files_data: dict[str, dict[str, Any]] = {}
        self.selected_files_data: dict[str, dict[str, Any]] = {}
        self.virtual_album_map: dict[str, int] = {}
        self.virtual_album_anchors: dict[int, str] = {}
        self.next_group_id = 1
        self.recycled_groups: list[int] = []
        self.locks_data: dict[str, dict[str, bool]] = {}
        self.album_sync_keys = list(self.DEFAULT_ALBUM_SYNC_KEYS)
        self.last_selected_album: str | None = None

    def reset(self) -> None:
        """Clear all session state."""
        self.all_files_data = {}
        self.selected_files_data = {}
        self.album_sync_keys = list(self.DEFAULT_ALBUM_SYNC_KEYS)
        self._reset_directory_state()

    def reset_for_file_load(self) -> None:
        """Clear data tied to the previous directory before an async file load."""
        self.all_files_data = {}
        self.selected_files_data = {}
        self._reset_directory_state()

    def export_state(self) -> dict[str, Any]:
        """Return the current session context for consumers of plain data.

        The returned dictionary is a lightweight view of this session.  Its
        values intentionally reference the session's live state so callers do
        not create a parallel source of truth.
        """
        return {
            "all_files_data": self.all_files_data,
            "selected_files_data": self.selected_files_data,
            "virtual_album_map": self.virtual_album_map,
            "virtual_album_anchors": self.virtual_album_anchors,
            "next_group_id": self.next_group_id,
            "recycled_groups": self.recycled_groups,
            "locks_data": self.locks_data,
            "album_sync_keys": self.album_sync_keys,
            "last_selected_album": self.last_selected_album,
        }

    def _reset_directory_state(self) -> None:
        self.virtual_album_map = {}
        self.virtual_album_anchors = {}
        self.next_group_id = 1
        self.recycled_groups = []
        self.locks_data = {}
        self.last_selected_album = None

    def create_virtual_album(self, paths: Iterable[str]) -> int:
        """Create a virtual album from paths, moving them from old groups if needed."""
        paths = tuple(dict.fromkeys(paths))
        if not paths:
            raise ValueError("A virtual album requires at least one path.")

        group_id = self._allocate_group_id()
        affected_groups = {self.virtual_album_map.get(path) for path in paths}
        for path in paths:
            self.virtual_album_map[path] = group_id
        self.virtual_album_anchors[group_id] = paths[0]
        self._repair_group_anchors(affected_groups - {None, group_id})
        self.cleanup_recycled_groups()
        return group_id

    def add_to_virtual_album(self, group_id: int, paths: Iterable[str]) -> None:
        """Add paths to an existing virtual album and repair any source anchors."""
        if group_id not in self.virtual_album_anchors:
            raise ValueError(f"Unknown virtual album group: {group_id}")

        paths = tuple(dict.fromkeys(paths))
        affected_groups = {self.virtual_album_map.get(path) for path in paths}
        for path in paths:
            self.virtual_album_map[path] = group_id
        self._repair_group_anchors(affected_groups - {None, group_id})
        self.cleanup_recycled_groups()

    def remove_virtual_album(self, group_id: int) -> list[str]:
        """Remove a virtual album and return the paths that belonged to it."""
        paths = [
            path
            for path, mapped_group in self.virtual_album_map.items()
            if mapped_group == group_id
        ]
        for path in paths:
            del self.virtual_album_map[path]
        self.virtual_album_anchors.pop(group_id, None)
        self.cleanup_recycled_groups()
        return paths

    def selected_virtual_album_group(self, paths: Iterable[str]) -> int | None:
        """Return the shared virtual group only when every path belongs to it."""
        paths = tuple(paths)
        if not paths:
            return None
        group_id = self.virtual_album_map.get(paths[0])
        if group_id is None:
            return None
        return group_id if all(self.virtual_album_map.get(path) == group_id for path in paths) else None

    def cleanup_recycled_groups(self) -> None:
        """Discard stale anchors and make every inactive allocated ID reusable."""
        active_groups = set(self.virtual_album_map.values())
        for group_id in list(self.virtual_album_anchors):
            if group_id not in active_groups:
                self.virtual_album_anchors.pop(group_id, None)
        for group_id in range(1, self.next_group_id):
            if group_id not in active_groups and group_id not in self.recycled_groups:
                self.recycled_groups.append(group_id)
        self.recycled_groups.sort()

    def set_lock(self, path: str, key: str, is_locked: bool) -> None:
        """Store a field lock for a file."""
        self.locks_data.setdefault(path, {})[key] = is_locked

    def is_locked(self, path: str, key: str) -> bool:
        """Return whether a field is locked for a file."""
        return self.locks_data.get(path, {}).get(key, False)

    def _allocate_group_id(self) -> int:
        if self.recycled_groups:
            return self.recycled_groups.pop(0)
        group_id = self.next_group_id
        self.next_group_id += 1
        return group_id

    def _repair_group_anchors(self, group_ids: Iterable[int]) -> None:
        for group_id in group_ids:
            remaining_paths = [
                path
                for path, mapped_group in self.virtual_album_map.items()
                if mapped_group == group_id
            ]
            if remaining_paths and self.virtual_album_anchors.get(group_id) not in remaining_paths:
                self.virtual_album_anchors[group_id] = remaining_paths[0]
