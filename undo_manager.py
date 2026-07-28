"""Application-level undo history and managed metadata snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping


MANAGED_FIELDS = (
    "title",
    "artist",
    "album",
    "album_artist",
    "composer",
    "track",
    "disc",
    "date",
    "genre",
    "comment",
)


@dataclass(frozen=True)
class ManagedMetadataSnapshot:
    """Exact state of every tag managed by the application."""

    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    composer: str = ""
    track: str = ""
    disc: str = ""
    date: str = ""
    genre: str = ""
    comment: str = ""
    has_cover: bool = False
    cover_data: bytes | None = None

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any]) -> "ManagedMetadataSnapshot":
        values = {
            key: str(metadata.get(key, "") or "")
            for key in MANAGED_FIELDS
        }
        cover = metadata.get("cover_data")
        cover_bytes = bytes(cover) if cover else None
        return cls(**values, has_cover=cover_bytes is not None, cover_data=cover_bytes)

    def restore_payload(self) -> dict[str, Any]:
        payload = {key: getattr(self, key) for key in MANAGED_FIELDS}
        payload["cover_data"] = self.cover_data if self.has_cover else None
        return payload

    def fingerprint(self) -> str:
        fields = {key: getattr(self, key) for key in MANAGED_FIELDS}
        encoded = json.dumps(
            fields,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(encoded)
        digest.update(b"\x01" if self.has_cover else b"\x00")
        if self.has_cover and self.cover_data is not None:
            digest.update(hashlib.sha256(self.cover_data).digest())
        return digest.hexdigest()


@dataclass(frozen=True)
class CursorState:
    position: int = 0
    selection_start: int = -1
    selection_length: int = 0


@dataclass(frozen=True)
class EditorStateSnapshot:
    """Widget-free snapshot of the current editor and result panels."""

    selected_paths: tuple[str, ...] = ()
    field_values: Mapping[str, str] = field(default_factory=dict)
    checked_fields: Mapping[str, bool] = field(default_factory=dict)
    locked_fields: Mapping[str, bool] = field(default_factory=dict)
    cursor_states: Mapping[str, CursorState] = field(default_factory=dict)
    cover_has_data: bool = False
    cover_data: bytes | None = None
    cover_is_mixed: bool = False
    cover_modified: bool = False
    result_values: Mapping[str, str] = field(default_factory=dict)
    selected_source: str = ""
    status_text: str = ""
    score_text: str = ""
    filename_clue_status_text: str = ""


@dataclass(frozen=True)
class StoredValue:
    exists: bool
    value: Any = None


@dataclass(frozen=True)
class SessionPatch:
    """Non-UI values changed by one editor action and needed for undo."""

    metadata_values: Mapping[str, Mapping[str, StoredValue]] = field(default_factory=dict)
    lock_values: Mapping[str, Mapping[str, StoredValue]] = field(default_factory=dict)
    source_preferences: Mapping[Any, StoredValue] = field(default_factory=dict)
    api_cache_values: Mapping[str, StoredValue] = field(default_factory=dict)

    def detached_copy(self) -> "SessionPatch":
        return copy.deepcopy(self)


@dataclass(frozen=True)
class EditorUndoCommand:
    description: str
    before: EditorStateSnapshot
    after: EditorStateSnapshot
    affected_paths: tuple[str, ...] = ()
    merge_key: str | None = None
    timestamp: float = field(default_factory=time.monotonic)
    session_before: SessionPatch | None = None
    session_after: SessionPatch | None = None


@dataclass(frozen=True)
class SavedFileChange:
    path: str
    before: ManagedMetadataSnapshot
    after: ManagedMetadataSnapshot


@dataclass
class SavedMetadataTransaction:
    """A save transaction whose remaining changes can be restored together."""

    description: str
    changes: dict[str, SavedFileChange]
    original_count: int
    action: str = "undo"
    restored_changes: dict[str, SavedFileChange] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        changes: Iterable[SavedFileChange],
        action: str = "undo",
    ) -> "SavedMetadataTransaction":
        change_map = {change.path: change for change in changes}
        count = len(change_map)
        label = "撤销保存" if action == "undo" else "重做保存"
        return cls(f"{label} {count} 个文件", change_map, count, action)

    @property
    def affected_paths(self) -> tuple[str, ...]:
        return tuple(self.changes)

    @property
    def is_complete(self) -> bool:
        return not self.changes

    def mark_restored(self, paths: Iterable[str]) -> None:
        for path in paths:
            change = self.changes.pop(path, None)
            if change is not None:
                self.restored_changes[path] = change
        if self.changes:
            label = "撤销保存" if self.action == "undo" else "重做保存"
            self.description = f"重试{label} {len(self.changes)} 个文件"

    def reversed(self, action: str) -> "SavedMetadataTransaction":
        return SavedMetadataTransaction.create(
            (
                SavedFileChange(
                    path=change.path,
                    before=change.after,
                    after=change.before,
                )
                for change in self.restored_changes.values()
            ),
            action=action,
        )


class UndoManager:
    """Strict LIFO history with coalescing, suspension, and memory limits."""

    def __init__(
        self,
        max_commands: int = 40,
        max_bytes: int = 128 * 1024 * 1024,
        merge_window_seconds: float = 0.55,
    ) -> None:
        self.max_commands = max_commands
        self.max_bytes = max_bytes
        self.merge_window_seconds = merge_window_seconds
        self._commands: list[EditorUndoCommand | SavedMetadataTransaction] = []
        self._redo_commands: list[EditorUndoCommand | SavedMetadataTransaction] = []
        self._recording_suspensions = 0
        self._merge_block = 0
        self._memory_bytes = 0
        self._cover_pool: dict[str, bytes] = {}

    @property
    def can_undo(self) -> bool:
        return bool(self._commands)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_commands)

    @property
    def count(self) -> int:
        return len(self._commands)

    @property
    def redo_count(self) -> int:
        return len(self._redo_commands)

    @property
    def memory_bytes(self) -> int:
        return self._memory_bytes

    @property
    def recording_suspended(self) -> bool:
        return self._recording_suspensions > 0

    @contextmanager
    def suspend_recording(self):
        self._recording_suspensions += 1
        try:
            yield
        finally:
            self._recording_suspensions -= 1

    def break_merge(self) -> None:
        self._merge_block += 1

    def clear(self) -> None:
        self._commands.clear()
        self._redo_commands.clear()
        self._cover_pool.clear()
        self._memory_bytes = 0
        self.break_merge()

    def peek(self) -> EditorUndoCommand | SavedMetadataTransaction | None:
        return self._commands[-1] if self._commands else None

    def peek_redo(self) -> EditorUndoCommand | SavedMetadataTransaction | None:
        return self._redo_commands[-1] if self._redo_commands else None

    def pop(self) -> EditorUndoCommand | SavedMetadataTransaction | None:
        if not self._commands:
            return None
        command = self._commands.pop()
        self._recalculate_memory()
        self.break_merge()
        return command

    def pop_if_same(self, command: object) -> bool:
        if self._commands and self._commands[-1] is command:
            self._commands.pop()
            self._recalculate_memory()
            self.break_merge()
            return True
        return False

    def move_undo_to_redo(
        self,
        command: object,
        replacement: EditorUndoCommand | SavedMetadataTransaction | None = None,
    ) -> bool:
        if not self._commands or self._commands[-1] is not command:
            return False
        self._commands.pop()
        self._redo_commands.append(
            self._intern_command_covers(replacement or command)
        )
        self._recalculate_memory()
        self.break_merge()
        return True

    def move_redo_to_undo(
        self,
        command: object,
        replacement: EditorUndoCommand | SavedMetadataTransaction | None = None,
    ) -> bool:
        if not self._redo_commands or self._redo_commands[-1] is not command:
            return False
        self._redo_commands.pop()
        self._commands.append(
            self._intern_command_covers(replacement or command)
        )
        self._recalculate_memory()
        self.break_merge()
        return True

    def push(self, command: EditorUndoCommand | SavedMetadataTransaction) -> None:
        if self.recording_suspended:
            return
        self._redo_commands.clear()
        command = self._intern_command_covers(command)
        if self._can_merge(command):
            previous = self._commands[-1]
            assert isinstance(previous, EditorUndoCommand)
            assert isinstance(command, EditorUndoCommand)
            self._commands[-1] = replace(
                previous,
                after=command.after,
                timestamp=command.timestamp,
            )
        else:
            self._commands.append(command)
        self._merge_block = 0
        self._enforce_limits()

    def discard_editor_commands_for_paths(self, paths: Iterable[str]) -> None:
        path_set = set(paths)
        if not path_set:
            return
        self._commands = [
            command
            for command in self._commands
            if not (
                isinstance(command, EditorUndoCommand)
                and path_set.intersection(command.affected_paths)
            )
        ]
        self._redo_commands = [
            command
            for command in self._redo_commands
            if not (
                isinstance(command, EditorUndoCommand)
                and path_set.intersection(command.affected_paths)
            )
        ]
        self._recalculate_memory()
        self.break_merge()

    def refresh_limits(self) -> None:
        """Recalculate after a pending saved transaction is partially restored."""
        self._enforce_limits()

    def intern_managed_snapshot(self, snapshot: ManagedMetadataSnapshot) -> ManagedMetadataSnapshot:
        if not snapshot.has_cover or snapshot.cover_data is None:
            return snapshot
        cover = self._intern_cover(snapshot.cover_data)
        return replace(snapshot, cover_data=cover)

    def _can_merge(self, command: object) -> bool:
        if self._merge_block or not isinstance(command, EditorUndoCommand):
            return False
        if (
            not command.merge_key
            or command.session_before is not None
            or command.session_after is not None
            or not self._commands
        ):
            return False
        previous = self._commands[-1]
        return (
            isinstance(previous, EditorUndoCommand)
            and previous.merge_key == command.merge_key
            and previous.affected_paths == command.affected_paths
            and command.timestamp - previous.timestamp <= self.merge_window_seconds
        )

    def _intern_command_covers(self, command):
        if isinstance(command, SavedMetadataTransaction):
            command.changes = {
                path: replace(
                    change,
                    before=self.intern_managed_snapshot(change.before),
                    after=self.intern_managed_snapshot(change.after),
                )
                for path, change in command.changes.items()
            }
            return command
        return replace(
            command,
            before=self._intern_editor_snapshot(command.before),
            after=self._intern_editor_snapshot(command.after),
        )

    def _intern_editor_snapshot(self, snapshot: EditorStateSnapshot) -> EditorStateSnapshot:
        if not snapshot.cover_has_data or snapshot.cover_data is None:
            return snapshot
        return replace(snapshot, cover_data=self._intern_cover(snapshot.cover_data))

    def _intern_cover(self, cover_data: bytes) -> bytes:
        digest = hashlib.sha256(cover_data).hexdigest()
        existing = self._cover_pool.get(digest)
        if existing == cover_data:
            return existing
        cover = bytes(cover_data)
        self._cover_pool[digest] = cover
        return cover

    def _enforce_limits(self) -> None:
        self._recalculate_memory()
        while (self._commands or self._redo_commands) and (
            len(self._commands) + len(self._redo_commands) > self.max_commands
            or self._memory_bytes > self.max_bytes
        ):
            if self._commands:
                self._commands.pop(0)
            else:
                self._redo_commands.pop(0)
            self._recalculate_memory()

    def _recalculate_memory(self) -> None:
        seen_bytes: set[int] = set()
        self._memory_bytes = sum(
            _estimate_size(command, seen_bytes)
            for command in (*self._commands, *self._redo_commands)
        )
        live_covers: dict[str, bytes] = {}
        _collect_covers((self._commands, self._redo_commands), live_covers)
        self._cover_pool = live_covers


def _estimate_size(value: Any, seen_bytes: set[int]) -> int:
    if value is None or isinstance(value, (bool, int, float)):
        return 16
    if isinstance(value, str):
        return 49 + len(value.encode("utf-8"))
    if isinstance(value, bytes):
        identity = id(value)
        if identity in seen_bytes:
            return 8
        seen_bytes.add(identity)
        return 33 + len(value)
    if isinstance(value, Mapping):
        return 64 + sum(
            _estimate_size(key, seen_bytes) + _estimate_size(item, seen_bytes)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        return 64 + sum(_estimate_size(item, seen_bytes) for item in value)
    if hasattr(value, "__dict__"):
        return 64 + _estimate_size(vars(value), seen_bytes)
    return 64


def _collect_covers(value: Any, covers: dict[str, bytes]) -> None:
    if isinstance(value, bytes):
        covers.setdefault(hashlib.sha256(value).hexdigest(), value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _collect_covers(key, covers)
            _collect_covers(item, covers)
        return
    if isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            _collect_covers(item, covers)
        return
    if hasattr(value, "__dict__"):
        _collect_covers(vars(value), covers)
