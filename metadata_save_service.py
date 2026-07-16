"""Filesystem execution for a previously calculated metadata save plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from audio_tagger import AudioTagger
from save_plan import SaveItem, SavePlan
from undo_manager import ManagedMetadataSnapshot, SavedFileChange


@dataclass
class SaveResult:
    success_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    saved_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    successful_items: list[SaveItem] = field(default_factory=list)
    failed_items: list[SaveItem] = field(default_factory=list)
    before_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class RestoreResult:
    success_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    conflict_files: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    restored_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)


class MetadataSaveService:
    """Execute a save plan without any dependency on Qt or editor state."""

    def __init__(self, tagger_factory: Callable[[str], Any] = AudioTagger):
        self._tagger_factory = tagger_factory

    @staticmethod
    def _read_managed(tagger):
        reader = getattr(tagger, "read_managed_tags", tagger.read_tags)
        return reader()

    def execute(
        self,
        plan: SavePlan,
        progress_callback: Callable[[int, int, SaveItem], None] | None = None,
    ) -> SaveResult:
        """Execute a plan and optionally report each attempted write.

        The callback deliberately stays framework-agnostic so this service can
        still be used by tests and non-Qt callers.
        """
        result = SaveResult()
        successful_paths: set[str] = set()
        total = len(plan.items)

        taggers: dict[str, Any] = {}
        capture_errors: dict[str, str] = {}
        for item in plan.items:
            if item.path in taggers or item.path in capture_errors:
                continue
            try:
                tagger = self._tagger_factory(item.path)
                result.before_metadata[item.path] = self._read_managed(tagger)
                taggers[item.path] = tagger
            except Exception as exc:
                capture_errors[item.path] = f"Unable to capture pre-save snapshot: {exc}"

        for current, item in enumerate(plan.items, start=1):
            if progress_callback:
                progress_callback(current, total, item)

            if item.depends_on and item.depends_on not in successful_paths:
                continue

            if item.path in capture_errors:
                result.failed_files.append(item.path)
                result.errors[item.path] = capture_errors[item.path]
                result.failed_items.append(item)
                continue

            payload = dict(item.metadata)
            if item.write_cover:
                payload["cover_data"] = item.cover_data

            try:
                tagger = taggers[item.path]
                tagger.update_tags(payload)
                result.saved_metadata[item.path] = self._read_managed(tagger)
            except Exception as exc:
                result.failed_files.append(item.path)
                result.errors[item.path] = str(exc)
                result.failed_items.append(item)
                continue

            successful_paths.add(item.path)
            result.success_files.append(item.path)
            result.successful_items.append(item)

        return result


class MetadataRestoreService:
    """Restore managed snapshots while detecting later external changes."""

    def __init__(self, tagger_factory: Callable[[str], Any] = AudioTagger):
        self._tagger_factory = tagger_factory

    @staticmethod
    def _read_managed(tagger):
        reader = getattr(tagger, "read_managed_tags", tagger.read_tags)
        return reader()

    def execute(
        self,
        changes: Mapping[str, SavedFileChange],
        progress_callback: Callable[[int, int, SavedFileChange], None] | None = None,
    ) -> RestoreResult:
        result = RestoreResult()
        pending = list(changes.values())
        total = len(pending)
        for current, change in enumerate(pending, start=1):
            if progress_callback:
                progress_callback(current, total, change)
            try:
                tagger = self._tagger_factory(change.path)
                current_snapshot = ManagedMetadataSnapshot.from_metadata(
                    self._read_managed(tagger)
                )
                if current_snapshot.fingerprint() != change.after.fingerprint():
                    result.conflict_files.append(change.path)
                    result.errors[change.path] = "File metadata changed after this save"
                    continue

                tagger.restore_managed_tags(change.before)
                restored = self._read_managed(tagger)
                restored_snapshot = ManagedMetadataSnapshot.from_metadata(restored)
                if restored_snapshot.fingerprint() != change.before.fingerprint():
                    raise OSError("Restored metadata did not match the saved snapshot")
            except Exception as exc:
                result.failed_files.append(change.path)
                result.errors[change.path] = str(exc)
                continue

            result.success_files.append(change.path)
            result.restored_metadata[change.path] = restored
        return result
