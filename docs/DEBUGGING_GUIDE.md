# Debugging Guide

Use this guide with [`../AGENTS.md`](../AGENTS.md) and the owning workflow in [`ARCHITECTURE.md`](ARCHITECTURE.md). The central rule is to find the first incorrect state, not the last visible symptom.

## 1. Mandatory debugging sequence

1. Reproduce the issue with the exact user workflow: directory load, selection shape, search mode/IDs, source choice, field application, save variant, or undo action.
2. Record the relevant input metadata without exposing secrets or unnecessary private paths.
3. Identify the authoritative owner at each stage; do not treat a widget, cache, or list item as persistent truth.
4. Trace the value through every owning layer.
5. Locate the first point where the value differs from the expected value.
6. Classify the defect as one of:
   - local tag reading (`AudioTagger`);
   - Provider acquisition (`mb_api.py` / `apple_music_api.py`);
   - Provider matching or combined source comparison;
   - artist-name resolution;
   - result-panel/editor UI state;
   - album/virtual-album synchronization;
   - save-plan construction;
   - tag writing/read-back;
   - editor undo or saved-file restore;
   - worker cancellation or stale-result handling;
   - cover handling;
   - local file conversion/move/delete/cleanup.
7. Add a minimal deterministic regression test or reproduction when possible.
8. Fix the owning layer, preserving adjacent contracts.
9. Verify downstream display, plan, write, read-back, and undo behavior as relevant.
10. Run targeted tests, then the broader relevant suite with the interpreter discovered from `.vscode/settings.json`.

### Select logs by application version

Before reading a diagnostic log, read `config.APP_VERSION` and match it against the version in the filename and file header. The three supported families are:

```text
runtime_logs/runtime-v<version>-YYYYMMDD.log
metadata-search-v<version>-YYYYMMDD-HHMMSS.log
cover-search-v<version>-YYYYMMDD-HHMMSS.log
```

Use current-version logs for the reproduction under investigation. Use only the immediately preceding version when a before/after comparison is needed. Do not diagnose new code from an older or unversioned log merely because its timestamp is recent.

After the current version has reproduced the workflow and produced usable logs, older-version logs may be deleted. This includes old files under `runtime_logs/`, old metadata/cover exports, and legacy exports without a version marker. Keep the previous version only while it supplies useful comparison evidence. Close the application before deleting a runtime log that may still be open, and never delete source files, tests, or user audio as part of log cleanup.

For every behavior-changing iteration, update only `config.APP_VERSION`; do not hand-edit version strings in log writers, filenames, or documentation examples. A version bump separates new diagnostics from evidence produced by older code.

## 2. Root-cause rule

**Do not patch the final writer, display widget, or output formatting merely because that is where an incorrect value becomes visible. Find where the value first becomes wrong.**

### Example: wrong `album_artist`

Bad approach:

- force a preferred string inside `AudioTagger`;
- special-case one Provider inside the final writer;
- overwrite the file again after `MetadataSaveService` returns.

Correct trace:

```text
AudioTagger.read_tags()
  -> AlbumSession selected/all data
  -> mb_api / apple_music_api normalized candidate
  -> artist_name_resolver (Apple presentation only)
  -> metadata_api whole-source choice
  -> result panel and user source/field application
  -> checkbox and lock state
  -> SavePlanRequest.field_updates
  -> primary/sync SaveItem.metadata
  -> AudioTagger write and read-back
```

Fix the first incorrect transformation. Remember that a target lock blocks dependent synchronization but does not block a checked direct primary write.

### Example: old search result replaces a new result

Bad approach:

- add a delay;
- globally ignore a signal;
- disable searching permanently.

Correct trace:

- record `_metadata_search_generation` or `_cover_search_generation`;
- record `_active_*_search_id` and the worker's `request_id`;
- inspect the cancellation event and cancelled-ID set;
- confirm the completion slot rejects a mismatched ID before changing overlay, result data, caches, or status;
- distinguish a cancelled completion from an ordinary Provider failure.

### Example: one album save changes unrelated tracks

Bad approach:

- remove all dependent writes;
- add a filename check in `AudioTagger`.

Correct trace:

- record selected paths and whether selection count is one;
- inspect `virtual_album_map` and anchors;
- for physical albums, compare the original non-empty album and cover fingerprints;
- inspect target locks, `album_sync_keys`, and checked fields;
- inspect the exact `SavePlanRequest` and every `SaveItem.depends_on`;
- fix membership or planning in `save_plan.py` or the earlier session identity owner.

### Example: restore overwrites or refuses a file

Bad approach:

- bypass fingerprint comparison;
- write the `before` dict directly from the window.

Correct trace:

- distinguish editor undo from `SavedMetadataTransaction` restore;
- compare current managed fingerprint to the recorded `after` fingerprint;
- inspect external changes to any managed text field or cover;
- inspect exact restore payload and post-restore read-back;
- preserve unmanaged tags and partial-retry transaction semantics.

## 3. Metadata debugging checklist

For every affected text field, capture this chain in a test or notes:

| Checkpoint | Value to record |
| --- | --- |
| Local file | raw frame/Vorbis value and format |
| Tag adapter | normalized `AudioTagger.read_tags()` value |
| Loaded state | `all_files_data[path][field]` |
| Selected state | `selected_files_data[path][field]` |
| MusicBrainz | normalized candidate and internal score/evidence |
| Apple | normalized candidate, storefront, collection/track IDs and score |
| Combined selection | `metadata_source`, `source_quality_score`, `source_results` |
| Result panel | displayed proposal |
| Editor | current combo text after manual/source application |
| Election | checkbox state |
| Protection | visible lock and `locks_data[path][field]` |
| Planning | `field_updates`, `checked_fields`, primary/sync item value |
| Persistence | tagger payload and service read-back |
| In-memory refresh | new `all_files_data[path][field]` |
| Restore | `before`, `after`, current fingerprint, restored read-back |

For `cover_data`, record hashes and state flags rather than dumping bytes:

- local first APIC/FLAC-picture SHA-256 and presence;
- whether selected covers are equal or mixed;
- `current_cover_data` presence/hash;
- `_cover_is_mixed`;
- `cover_modified_in_batch`;
- Provider artwork URL/source/storefront/release ID;
- selected gallery/clipboard image decode dimensions;
- primary and sync `write_cover`, payload presence/hash;
- before/after/restore snapshot `has_cover` and hash.

Do not equate `current_cover_data is None` with explicit removal when `_cover_is_mixed` is true or `cover_modified_in_batch` is false.

## 4. Provider debugging

### Collect evidence

Use the existing metadata/cover debug dialogs and exported UTF-8 logs. They already retain local normalized metadata (without cover bytes), request descriptions/URLs, raw JSON, source scores, artist identities, localization decisions, and final selections. Metadata exports use `metadata-search-v<version>-<timestamp>.log`; cover exports use `cover-search-v<version>-<timestamp>.log`; both include the application version in the header. Confirm that marker matches `config.APP_VERSION` before treating the data as current. Do not add secrets to these records.

For MusicBrainz, inspect:

- generated Lucene main/sub words and search mode;
- release search query tier and whether `_release_search_cache` hit;
- album 75% / artist 25% release score and 0.25 threshold;
- fallback recording release choice;
- release MBID and tracklist cache hit;
- local numeric track/disc after `safe_int()`;
- track title/artist score plus numeric bonuses;
- recording detail, composer relations, date fallback, and artist identities;
- each 1 s cancellable pacing wait, 10 s request, status/error, and cancellation checkpoint.

For Apple, inspect:

- exact query and `_album_search_countries()` order;
- collection baseline and whether 0.90 stopped later storefront searches;
- collection deduplication/top-four ranking;
- `_collection_lookup_countries()` order and missing-tracklist fallback;
- per-song title/album/lead-artist score and numeric additions;
- direct collection track/disc exact-match behavior;
- collection release date versus track release date;
- selected storefront, any track relocalization, and artist candidate list;
- album/collection/track cache keys, 12 s network errors, and cancellation checkpoints.

For combined selection, inspect both `engine_match_score` and `source_quality_score`. The latter deliberately excludes track/disc bonuses. Verify title 50%, artist 20%, album 30%, exact-presentation contribution, direct-ID precedence, and MusicBrainz tie-breaking.

For artist-name issues, record home-country evidence, canonical/alias matches, Japanese evidence, every existing Apple candidate, and the rule/DeepSeek decision. DeepSeek must return only a candidate country and code must map it to an existing candidate. Its cache key does not include identity evidence, and its request is not cooperatively cancellable.

### Cache diagnosis

Reproduce once with normal caching and once with the UI's `no_cache` option or direct `no_cache=True` test call. `no_cache` bypasses Provider cache reads but successful calls still repopulate caches. Per-window `api_cache` is a separate layer and is skipped by selection loading when the no-cache checkbox is active.

Do not log:

- `DEEPSEEK_API_KEY` or request authorization headers;
- complete `settings.json`;
- full private file paths unless path identity is the defect;
- binary cover/audio data;
- unnecessary personal metadata.

Automated tests should mock network calls. Use a live request only when the task requires it and the user has authorized the external call.

### Shortcut/runtime failures

When `Music Metadata Perfecter` is launched from the desktop/Listary shortcut and no console is visible:

1. Confirm the shortcut target is the absolute interpreter currently configured by `.vscode/settings.json`.
2. Confirm its argument is the absolute repository `main.py` and its working directory is the repository root.
3. Open the current day's `runtime_logs/runtime-v<APP_VERSION>-YYYYMMDD.log`.
4. Check the startup/version header, then the final stdout/stderr lines and any uncaught exception traceback.
5. Re-run with the same configured interpreter from a terminal only when interactive console behavior is needed.

Do not replace the shortcut target with an arbitrary `python`, `python3`, system interpreter, or unrelated environment. The shortcut is machine-local and is not expected to be committed. A normal application iteration requires only an `APP_VERSION` bump, not shortcut recreation, unless the interpreter or repository path changed.

## 5. Save debugging

Before executing a save, inspect the plain plan. In a regression test, construct or capture `SavePlanRequest` and assert the complete item list.

Checklist:

1. Confirm the selected path list and whether it is single- or multi-selection.
2. Record widget values and translate `<preserve>`/`<blank>` exactly as `_execute_save()` does.
3. Confirm `field_updates` includes only checked, non-preserved fields.
4. Confirm `checked_fields` separately includes checked fields even when their values are omitted.
5. Record `cover_modified` and cover presence/hash.
6. Confirm primary items contain only intended updates.
7. For each sync item, record physical/virtual album membership.
8. Check `album_sync_keys`, target locks, and checkbox state.
9. Check `kind` and `depends_on`; every dependent sync should reference the primary path.
10. Confirm target cover propagation is intentional and non-empty.
11. Before execution, confirm every unique path can produce a managed snapshot.
12. During execution, distinguish snapshot-capture failure, write failure, dependency skip, and read-back failure.
13. Inspect `success_files`, `failed_files`, `successful_items`, `failed_items`, `before_metadata`, and `saved_metadata` separately.
14. Read tags back through `read_managed_tags()` after writing.
15. Verify `all_files_data`, sortable/list status, and cache invalidation only changed for successes.
16. Verify the saved undo transaction contains every and only successful path.

Important current behavior:

- failures do not roll back earlier successes;
- later independent files continue;
- a failed primary prevents its dependent item from writing;
- a dependency-skipped item is currently not reported as failed;
- progress is emitted before dependency evaluation;
- save/restore workers are not cancellable.

Use the existing targeted suite:

```text
"<configured-python-path>" -m unittest test_save_plan -v
"<configured-python-path>" -m unittest test_metadata_restore -v
"<configured-python-path>" -m unittest test_main_window_interactions -v
```

## 6. Undo and restore debugging

First classify the command returned by `undo_manager.peek()`.

### `EditorUndoCommand`

Inspect:

- `before` and `after` selected paths;
- field, checkbox, visible lock, cursor, cover/mixed/modified, result/source/status values;
- merge key, affected paths, timestamp, and whether a focus/selection change broke merging;
- optional `SessionPatch` for metadata/locks or source preference/API cache;
- whether undo recording was suspended while applying the snapshot;
- whether `_editor_baseline` was recaptured after application.

Editor undo does not restore audio files. It also does not currently cover virtual-album grouping, skip markers, settings, or local file operations.

### `SavedMetadataTransaction`

Inspect:

- transaction ordering and whether newer editor commands were intentionally discarded for saved paths;
- `before` and `after` fields, `has_cover`, cover hash, and fingerprints;
- current managed read-back before restore;
- fingerprint mismatch caused by an external managed-field or cover change;
- `restore_managed_tags()` exact payload;
- post-restore fingerprint and unmanaged-tag preservation;
- success removal from `transaction.changes`;
- conflict/failure retention for retry;
- selection/list/session refresh after successes.

A change to an unmanaged custom tag is outside the managed fingerprint and should be preserved rather than treated as a conflict. History is per window and is cleared by directory reload/exit.

## 7. Async debugging

For UI blocking, first determine whether work is supposed to be asynchronous. Directory scanning, metadata search, cover fetch, save, and restore have workers. NCM conversion, audio move, `.lrc` deletion, settings/debug writes, and temporary cover opening currently run on the UI thread.

Worker checklist:

1. Identify worker class and creation site.
2. Copy all immutable/plain inputs; ensure the worker does not read widgets.
3. Verify every signal connection and exact argument order.
4. Record request/generation ID where overlapping results are possible.
5. Record `threading.Event` identity and `requestInterruption()` state.
6. Verify cancellation checks before/after requests and inside long loops/waits.
7. Remember that a blocking request can observe cancellation only after return/timeout.
8. Verify cancellation emits `cancelled=True`, not a normal failure.
9. Verify the UI completion slot rejects a stale ID before any UI/cache mutation.
10. Verify active ID and cancelled-ID cleanup for current and stale completions.
11. Verify controls/overlay are restored only for the active completion.
12. Verify `QThread.finished` invokes `deleteLater()` and identity-safe attribute clearing.
13. Verify close behavior: cancel-and-ignore for search; block for save/restore.
14. For cover requests, inspect four-attempt transient retry and cancelable backoff.
15. For loaders, note there is no cancellation or generation guard; investigate overlapping reloads explicitly.

Relevant existing tests are in `test_application_undo_and_cancel.py`. They cover cooperative fetch/cover cancellation, Escape priority, stale metadata completion, and worker-adjacent UI behavior. They do not prove live HTTP cancellation or stale loader handling.

## 8. UI-state debugging

At one breakpoint/log point, compare:

- `inputs[field].currentText()` and checkbox state;
- visible lock button and `album_session.locks_data[path]`;
- `all_files_data[path]`;
- `selected_files_data[path]` and whether it is the same dict object as loaded data;
- `_editor_baseline` and `undo_manager.peek()`;
- `mb_inputs`, `available_source_results`, `_current_metadata_source`;
- `api_cache[path]` and `album_source_preferences[_album_source_key(path)]`;
- `current_cover_data`, `_cover_is_mixed`, `cover_modified_in_batch`;
- selected paths/current list item and virtual group membership;
- physical album key and cover fingerprint cache.

Expected synchronization points:

- `on_load_finished()`: worker data becomes loaded state;
- `on_file_selected()`: selected mirror, widgets, locks, cover, and Provider cache are rebuilt;
- editor actions: widgets change first; loaded metadata normally does not;
- lock propagation: existing code may immediately update same-album in-memory synchronized values;
- `_execute_save()`: widget/session values become an immutable plan;
- `_finish_save()`: only successful read-back replaces loaded metadata;
- `_finish_saved_transaction_undo()`: only successful restore read-back replaces loaded metadata;
- directory reload: session/history/window caches reset.

Temporary divergence is expected between unsaved widgets and loaded metadata. Divergence after a successful read-back or restored selection is not expected and should be fixed at that synchronization boundary.

## 9. Reproduction fixtures

No committed audio fixture corpus exists. Current tests use in-memory taggers and generate short temporary MP3/FLAC files with `ffmpeg`. Build a small private/non-copyrighted corpus only when the task needs broader manual or integration reproduction; do not claim it is part of the repository.

Recommended cases:

- ordinary single-artist album;
- compilation/`Various Artists` album;
- multi-disc album and track values such as `05/15`;
- multiple track artists and featured artist;
- missing `album_artist`;
- conflicting MusicBrainz/Apple candidates;
- localized/Japanese storefront variants with MB country/alias evidence;
- malformed or absent track/disc numbers;
- locked synchronized fields and locked direct fields;
- mixed multi-selection values using preserve/blank choices;
- physical album split by different covers;
- virtual album containing different original album names/covers;
- cover-only and text-only updates;
- no-cover before/after restore;
- partial snapshot/write/read-back failure;
- dependent primary failure;
- cancellation during Provider wait/request and cover retry;
- stale completion after a newer request ID;
- MP3 with unrelated `TXXX` and FLAC with unrelated Vorbis fields;
- synchronous move collisions, partial conversion failure, and destructive confirmation.

For byte-level tag investigation, use the existing standalone diagnostic:

```text
"<configured-python-path>" .test_audio_meta_diff.py <original.mp3-or-flac> <tagged.mp3-or-flac> -o <report.md> --json <parsed.json>
```

It compares MP3 ID3/FLAC metadata structure, file/audio-region hashes, and can show whether only container/tag bytes changed. It reports differences but exits zero when analysis completes.

## 10. Completion report template

User-facing reports must be in Simplified Chinese and include the configured interpreter path:

```text
问题复现：
根因：
首次出错位置：
修改文件：
为什么在该层修复：
行为变化：
刻意保持不变的行为：
验证方式（含解释器路径）：
测试结果：
未解决风险：
```
