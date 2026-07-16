# Repository Agent Instructions

## Communication language

> All explanations, plans, progress updates, debugging conclusions, change summaries, test results, warnings, and responses addressed to the user must be written in Simplified Chinese, unless the user explicitly requests another language.

This includes plans, architecture explanations, debugging analysis, implementation summaries, verification reports, unresolved issues, and final responses. Keep code, Python identifiers, filenames, API names, commands, metadata fields, and technical symbols in English. Preserve existing Chinese UI text and follow the comment style of each production file.

## Python interpreter

1. Do not assume that `python`, `python3`, `pip`, `pytest`, or related executables on `PATH` belong to this project.
2. Read `.vscode/settings.json` before the first Python command of every new task. Recognize `python.defaultInterpreterPath`, legacy `python.pythonPath`, and equivalent workspace-relative settings; resolve `${workspaceFolder}` before use.
3. Use the absolute interpreter path configured there for every Python execution.
4. Invoke tools through that interpreter, for example:

   ```text
   "<configured-python-path>" -m unittest discover -v
   "<configured-python-path>" -m pip list
   "<configured-python-path>" -m pip install <package>
   "<configured-python-path>" -m compileall .
   ```

5. Prefer `"<configured-python-path>" -m <module>` to environment-specific executables such as `pytest` or `pip`.
6. Do not activate or silently use an unrelated Conda, Mamba, virtualenv, Windows Store, system, or global Python.
7. Do not modify `.vscode/settings.json`, add Mambaforge/Miniforge to the global `PATH`, or recreate the environment unless the user explicitly requests it.
8. Before installing anything, verify the configured interpreter and check whether the dependency is already installed in that environment.
9. In every user-facing test or command report, state the interpreter path used.
10. If the configured interpreter is absent, inaccessible, or unresolved, stop Python execution and report the exact problem in Simplified Chinese. Never fall back silently.

`.vscode/settings.json` is the authoritative interpreter-path source. Do not duplicate its machine-specific path in general documentation or scripts.

## Repository purpose

This is a PyQt6 desktop editor for top-level MP3 and FLAC files in a configured music directory. It reads embedded tags, supports multi-file and temporary-album editing, compares MusicBrainz and Apple Music/iTunes metadata, resolves storefront-specific artist names, retrieves artwork, writes managed tags, restores saved changes from in-memory undo transactions, previews audio, and provides synchronous NCM conversion/move/lyric-cleanup workflows.

## Read-first map

Read only the relevant path first, then follow its calls:

| Task | Minimum files |
| --- | --- |
| Startup, settings, packaged paths | `main.py`, `config.py`, `ui_components.py` |
| Main UI, selection, editor behavior | `main_window.py`, `album_session.py`, `library_widgets.py` |
| Album navigation | `album_initials.py`, `library_widgets.py`, relevant `main_window.py` list methods |
| Combined metadata search/source choice | `metadata_api.py`, `background_workers.py`, relevant `main_window.py` fetch methods |
| MusicBrainz | `mb_api.py`, `search_cancellation.py` |
| Apple Music/iTunes | `apple_music_api.py`, `artist_name_resolver.py`, `search_cancellation.py` |
| Artist localization/DeepSeek tie-breaking | `artist_name_resolver.py`, `apple_music_api.py`, `config.py` |
| Save rules and album synchronization | `save_plan.py`, `album_session.py`, `test_save_plan.py`, relevant `main_window.py` save methods |
| Filesystem tag reads/writes | `audio_tagger.py`, `metadata_save_service.py`, `test_metadata_restore.py` |
| Editor undo and saved-file restore | `undo_manager.py`, `metadata_save_service.py`, `background_workers.py`, relevant `main_window.py` undo methods |
| Threads, cancellation, stale results | `background_workers.py`, `cover_fetch_worker.py`, `search_cancellation.py`, relevant `main_window.py` request-generation methods |
| Cover retrieval/selection | `cover_fetch_worker.py`, `cover_gallery.py`, relevant `main_window.py` cover methods |
| Local conversion/move/delete/cleanup | `file_workflow.py`, `config.py`, relevant `main_window.py` workflow methods |
| Audio preview | `audio_player_widget.py` |
| Tests and tag-byte diagnostics | `test_*.py`, `.test_audio_meta_diff.py` |

For cross-module work, read the matching sections in `docs/ARCHITECTURE.md` and `docs/DEBUGGING_GUIDE.md` before editing.

## Architectural boundaries

- `main_window.py` owns Qt rendering, user interaction, orchestration, widget snapshots, request identity, and presentation of progress/errors. Do not add Provider algorithms, tag mutation, restore logic, or save-plan business rules there.
- `AlbumSession` owns mutable directory/editor context: loaded metadata, current selection data, virtual-album membership/anchors, field locks, album-sync keys, and last selected album.
- `metadata_api.py` combines normalized Provider results and chooses a whole-source default. `mb_api.py` and `apple_music_api.py` own Provider-specific acquisition and matching.
- `artist_name_resolver.py` selects among artist variants already returned by Apple storefronts, using MusicBrainz identity evidence and an optional DeepSeek tie-breaker. It must not invent metadata.
- `save_plan.py` owns the pure conversion from `SavePlanRequest` to primary and dependent `SaveItem` objects. It must remain free of Qt and filesystem writes.
- `metadata_save_service.py` executes an already-built plan, captures before/after managed metadata, and performs conflict-checked restoration. It must remain free of widget state.
- `audio_tagger.py` is the only layer that interprets and mutates MP3 ID3/FLAC tags.
- `undo_manager.py` owns widget-free editor snapshots, managed metadata snapshots, saved transactions, LIFO history, merging, and memory limits. The window applies snapshots and reports results.
- `background_workers.py` moves Provider search, directory scanning, save, and restore work off the UI thread. `cover_fetch_worker.py` owns asynchronous cover-network work. Workers emit data; they never mutate widgets.
- `search_cancellation.py` defines cooperative cancellation checkpoints. Request IDs/generations in `MusicEditorWindow` separately reject stale completions.
- `cover_gallery.py` selects downloaded cover bytes; cover acquisition remains in `cover_fetch_worker.py`, and cover persistence remains in the save pipeline.
- `file_workflow.py` owns NCM conversion and local move/delete/cleanup primitives. The window owns confirmation and messages. These helpers are currently called synchronously.
- Reusable Qt-only behavior belongs in `ui_components.py`, `library_widgets.py`, `cover_gallery.py`, and `audio_player_widget.py`.

Do not move Provider matching, artist resolution, save planning, tag writes, restore conflict checks, cancellation checks, or worker execution back into `main_window.py`.

## Core invariants

1. `AlbumSession.all_files_data` is the window's authoritative in-memory view after load/save/restore; audio files remain the persistent source and may be changed externally.
2. `selected_files_data` and editor widgets are selection-scoped mirrors. Synchronize them at established selection/save/restore boundaries; do not create another metadata store.
3. UI code builds `SavePlanRequest`; `build_save_plan` decides writes; `MetadataSaveService` and `AudioTagger` perform filesystem mutation. Do not bypass this path.
4. Save planning must stay separate from mutation. There is no save dry-run and no automatic rollback of a partially successful plan.
5. A single-file primary write may trigger dependent album synchronization. Physical albums require equal non-empty album names and equal cover fingerprints; virtual albums use explicit group membership. Multi-file primary saves do not create dependent sync items.
6. Locks prevent Provider application and dependent synchronization. A lock does not block an explicitly checked direct write to the currently selected primary file; this is tested behavior.
7. Dependent synchronized fields are limited by `album_sync_keys`, checkbox state, and target locks. Track-specific fields are protected from automatic Provider application during multi-selection.
8. Cover state is separate from text fields. `cover_modified_in_batch` controls primary cover writes; `None` can mean no cover, while `_cover_is_mixed` means selected files disagree. Never collapse those states.
9. Managed restore snapshots contain all ten managed text fields plus explicit cover presence/data. Restore compares the current managed fingerprint with the recorded post-save fingerprint before writing.
10. Editor undo and saved-file restore are different operations. Editor undo changes widgets/session patches; a `SavedMetadataTransaction` invokes background filesystem restoration.
11. Saved undo history is in memory only, strict LIFO, and retryable after partial restore. Do not claim persistence across application restarts.
12. Workers never update widgets directly. Qt signals/callbacks deliver results to the UI thread.
13. Cooperative cancellation and stale-result rejection are separate protections. Preserve both cancellation events/checkpoints and request-generation comparisons.
14. Cancelled searches are reported as cancellation, not ordinary Provider failure. Old request completions must not update the current UI.
15. MP3/FLAC multi-values use the literal `\\` application separator. Keep normalization rules centralized in the existing Provider/tag adapters; do not add competing UI-only normalization.
16. Unmanaged tags must survive managed save/restore behavior. Existing real-file tests verify this for representative MP3 and FLAC tags.
17. Provider API keys and other secrets must never enter logs, tests, screenshots, commits, or user-facing output. `settings.json` may contain a plaintext DeepSeek key.
18. Directory reload clears per-window session, undo, API result, source-preference, and list caches. Module-level Provider caches live for the Python process and have no general invalidation API.

## Change protocol

For every code change:

1. Read the relevant architecture/debugging sections and tests.
2. Identify the owning layer and all mirrored/derived consumers.
3. Trace the affected value from its source through its final consumer.
4. Reproduce the issue with exact workflow and input metadata.
5. Add or update a deterministic regression test when the existing `unittest` infrastructure permits.
6. Fix the earliest incorrect state or transformation, not the final visible symptom.
7. Run targeted tests with the configured interpreter.
8. Run the broader relevant suite; use the full suite for shared state, save, undo, worker, or Provider-contract changes.
9. Report unresolved uncertainty, skipped checks, external-service limitations, and any documentation impact in Simplified Chinese.

## Refactoring rules

- Do not refactor unrelated code while fixing a bug.
- Do not introduce an abstraction without demonstrated duplication, coupling, or extension need.
- Prefer explicit data flow over hidden Qt/framework behavior.
- Preserve public and internal contracts unless the task explicitly changes them.
- Do not leave duplicate old/new execution paths or temporary adapters without a removal condition.
- Do not move business logic into widgets.
- Do not bypass `SavePlan`, save/restore services, `UndoManager`, cancellation helpers, request generations, or workers.
- Do not add MVC, MVVM, service containers, repositories, presenters, controllers, or dependency-injection machinery solely for theoretical purity.
- Update `docs/ARCHITECTURE.md` and `docs/MODEL_HANDOFF.md` after meaningful structural changes.
- Keep behavior changes and refactoring separate when practical.

## Special rule for `main_window.py`

`main_window.py` is a large coordination and UI module. Its size alone is not a reason to split it, and small bug fixes must not trigger an architectural rewrite.

Before extracting anything, establish:

- the exact responsibility being moved;
- the authoritative state owner before and after;
- dependency direction;
- the signal/callback boundary;
- regression risks;
- tests or a concrete verification method;
- whether the extraction removes real duplication or coupling.

Do not automatically decompose it into controllers, managers, presenters, or services. Any extraction must avoid creating a second source of truth.

## Testing and verification

The automated suite uses standard-library `unittest`; no `pytest` configuration is present. Run from the repository root:

```text
"<configured-python-path>" -m unittest discover -v
```

Examples of targeted, existing test modules:

```text
"<configured-python-path>" -m unittest test_save_plan -v
"<configured-python-path>" -m unittest test_metadata_restore -v
"<configured-python-path>" -m unittest test_application_undo_and_cancel -v
```

`test_metadata_restore.py` requires `ffmpeg` on `PATH` and skips its real-file class when unavailable. At documentation creation, the configured interpreter ran all 60 discovered tests successfully, including the `ffmpeg` cases. Network tests mock external calls; the suite does not validate live MusicBrainz, Apple, Cover Art Archive, or DeepSeek behavior.

For metadata-byte investigation, `.test_audio_meta_diff.py` is an existing standalone diagnostic script; see `docs/DEBUGGING_GUIDE.md`. It is not part of `unittest` discovery. No verified packaging command or project-level lint/type-check command exists in the repository.

When a UI/network change cannot be automated, launch with:

```text
"<configured-python-path>" main.py
```

Then manually verify only the affected workflow: top-level MP3/FLAC loading, selection/mixed values, source switching, cancellation, cover selection, save/read-back/undo, or confirmed local file operations. Do not make live API calls or destructive file operations unless required by the task and authorized by the user.

## Definition of done

A task is not complete until the Simplified Chinese report states:

- files changed;
- behavior changed;
- behavior intentionally preserved;
- tests/checks run and the configured interpreter path;
- failures, skipped checks, and limitations;
- documentation updated or why no documentation update was needed.
