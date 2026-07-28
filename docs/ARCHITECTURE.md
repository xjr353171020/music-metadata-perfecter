# Architecture

This document describes the current repository, including current limitations. It is not a target architecture. Mandatory agent rules are in [`../AGENTS.md`](../AGENTS.md); investigation procedures are in [`DEBUGGING_GUIDE.md`](DEBUGGING_GUIDE.md).

## 1. System overview

The application is a Windows-oriented PyQt6 desktop metadata editor. It scans only top-level `.mp3` and `.flac` files in the configured music directory, reads and edits a fixed set of embedded tags, compares MusicBrainz and Apple Music/iTunes results, resolves storefront-specific artist presentation, downloads album art, writes tags, and keeps in-memory undo/restore history. Auxiliary workflows convert NCM files, permanently delete reviewed NCM sources, move converted audio into the main directory, delete `.lrc` files, and preview local audio.

External data sources are:

- MusicBrainz Web Service 2 (`release`, `recording`, and `artist` requests);
- Apple iTunes Search/Lookup APIs, used as the Apple Music metadata/storefront adapter;
- Cover Art Archive release artwork;
- optional DeepSeek `deepseek-chat`, used only to choose among existing Apple artist-name candidates.

The architectural style is a Qt window coordinator around extracted data, rule, service, adapter, and worker modules. The code is already modular around session state, save planning, filesystem execution, tag formats, undo data, Provider adapters, cancellation, background work, cover fetching, and reusable widgets. `main_window.py` remains centralized because it coordinates widget state, selection, caches, worker lifecycles, source choice, save/undo presentation, and local workflows. This is not an MVC/MVVM or dependency-injection architecture, and it should not be rewritten as one without a concrete need.

## 2. Application startup

Importing `config.py` immediately resolves `APP_DIR`, defines the product name in `APP_NAME` and release identifier in `APP_VERSION`, reads `settings.json` beside the source module or packaged executable, and exposes mutable module-global `APP_SETTINGS`. `main.py` then performs this path:

```text
main.py
  -> initialize versioned runtime logging
       -> runtime_logs/runtime-v<APP_VERSION>-YYYYMMDD.log
       -> transcribe stdout/stderr and uncaught exception tracebacks
  -> init_mb_api()                         # currently a no-op
  -> set Qt high-DPI environment variables
  -> QApplication(sys.argv)
  -> apply bundled application icon
  -> install global Microsoft YaHei/Segoe UI stylesheet
  -> APP_SETTINGS["MAIN_MUSIC_DIR"] or fallback
  -> MusicEditorWindow(music_dir)
       -> create AlbumSession, UndoManager, caches, request counters
       -> build UI and connect undo/event filters
  -> showMaximized()
  -> start_initial_load()
       -> QTimer.singleShot(0, load_file_list)
       -> FileLoaderWorker(music_dir)
       -> up to four stable reader partitions
       -> AudioTagger.read_tags() per top-level MP3/FLAC
       -> FileLoadProgressDialog lane per active reader thread
       -> on_load_finished(sortable, all_files_data)
       -> populate list and establish editor baseline
  -> QApplication.exec()
```

There is no command-line configuration parser, dependency bootstrap, settings schema validation, or database initialization. If the configured directory does not exist, `load_file_list()` returns without starting a loader. An additional window creates a completely new `MusicEditorWindow`, session, and runtime settings copy. Saving settings still updates the process-global persisted defaults and Provider configuration, but already-open windows keep their own workflow/music-directory values. Provider caches remain process-global.

`APP_NAME` is the single user-facing product name used by window titles, startup logs, and the machine-local shortcut. `APP_VERSION` is the single release/log version source. Each behavior-changing iteration updates that constant once; log producers consume it rather than maintaining independent versions. The `v` marker belongs to filenames and display headers, while the configured value itself is currently shaped like `2026.07.19.1`.

Application icon resources live in `assets/app_icon.png` and `assets/app_icon.ico`. `config.APP_ICON_PATH` resolves the PNG from the source tree or PyInstaller's temporary bundle directory. `main.py` applies it to the `QApplication`, while `build_release.ps1` uses the ICO for the Windows executable and embeds the PNG for runtime use.

For development without VS Code, the supported machine-local entry point is the `Music Metadata Perfecter` Windows desktop shortcut discoverable by searching `meta` in Listary. Its target is the absolute interpreter configured in `.vscode/settings.json`, its argument is the absolute repository `main.py`, and its working directory is the repository root. The shortcut is outside the repository and is not a portable configuration artifact. It does not need to change for normal iterations while those two paths remain stable. Startup through this shortcut follows the same `main.py` path and writes the same runtime log, so diagnostics do not depend on a visible console.

## 3. Module responsibility map

| Module | Responsibility and important API | Allowed dependencies | Prohibited responsibility | Risk |
| --- | --- | --- | --- | --- |
| `main.py` | Process entry point, runtime stream/exception logging, Qt/DPI setup, first window | `config`, `mb_api`, `main_window`, Qt | Metadata rules or I/O workflows | Low |
| `config.py` | Application path, `APP_NAME`, `APP_VERSION`, `settings.json`, `APP_SETTINGS` | stdlib | UI, Provider logic, tag writes | Medium: import-time mutable config |
| `main_window.py` | `MusicEditorWindow`; UI construction, selection/editor coordination, worker lifecycle, source choice, save/undo reporting | All feature modules and Qt | New Provider algorithms, tag encoding, save/restore rules | High |
| `album_session.py` | `AlbumSession`; loaded/selected metadata, virtual groups, locks, sync keys | stdlib only | Qt, network, filesystem mutation | Medium |
| `save_plan.py` | `SavePlanRequest`, `SaveItem`, `SavePlan`, `build_save_plan`; pure primary/dependent write rules | stdlib only | Qt, taggers, filesystem I/O | High |
| `metadata_save_service.py` | `MetadataSaveService`, `MetadataRestoreService`, result DTOs; snapshot, execute, read back, conflict-check | `audio_tagger`, `save_plan`, `undo_manager` | Widget state, Provider logic | High |
| `audio_tagger.py` | `AudioTagger`; MP3 ID3 and FLAC read/update/exact managed restore | Mutagen; optional Pillow | UI, album sync, Provider matching | High |
| `undo_manager.py` | Editor/saved snapshots, `SessionPatch`, saved transactions, LIFO undo/redo stacks and limits | stdlib only | Applying widgets or writing files | High |
| `filename_clue.py` | `analyze_filename_clues()`; conservative filename-stem parsing into a five-field `FilenameClueResult` | stdlib only | Qt, network, Provider matching, tag writes | Medium |
| `metadata_api.py` | Run both Providers, normalize cross-source scores, select a default, retain both results | Provider adapters, cancellation | UI, tag writing | High |
| `mb_api.py` | MusicBrainz release/recording/artist requests, matching, identities, caches, pacing | `requests`, `config`, cancellation | UI, Apple rules, tag writes | High |
| `apple_music_api.py` | iTunes collection/track search, storefront strategy, matching, localization calls, caches | `requests`, MB similarity helpers, resolver, cancellation | UI, tag writes | High |
| `artist_name_resolver.py` | Select an existing Apple artist variant; optional DeepSeek tie-break | `requests`, `config` | Inventing artist metadata, tag writes | High |
| `search_cancellation.py` | `SearchCancelled`, event checks, cancellable wait | stdlib | UI reporting, request identity | Low |
| `background_workers.py` | `FetchWorker`, `FilenameClueWorker`, `FileLoaderWorker`, `SaveWorker`, `RestoreWorker` and signal contracts | Qt, filename analysis, tagger, services, cancellation | Direct widget mutation | Medium |
| `cover_fetch_worker.py` | `CoverFetchWorker`; Apple/CAA artwork requests, retry, cancellation, debug stats | Qt, `requests`; delayed MB similarity import | Gallery UI, tag persistence | High |
| `cover_gallery.py` | `CoverGalleryDialog`; display candidates and return selected bytes | Qt | Network or tag writes | Low |
| `library_widgets.py` | Touch-safe list/combo/index widgets and smooth scrolling | Qt | Metadata/session rules | Low |
| `ui_components.py` | Loading, settings, versioned raw-debug/export dialogs | Qt, `config` | Provider matching or save rules | Medium: writes debug logs/settings |
| `audio_player_widget.py` | `AudioPlayerWidget`; Qt playback and Mutagen duration read | Qt Multimedia, Mutagen | Metadata mutation | Low |
| `album_initials.py` | Cross-script album initial/sort key | optional `pypinyin`, `pykakasi` | UI/session mutation | Low |
| `file_workflow.py` | NCM converter resolution/execution, NCM deletion, audio move, `.lrc` cleanup | stdlib, bundled executable | User confirmation or UI messages | High: destructive operations |
| `test_*.py` | `unittest` coverage for state, save/restore, UI, cancellation, Apple behavior | production modules, mocks, Qt, optional `ffmpeg` | Production behavior | Low |
| `.test_audio_meta_diff.py` | Standalone MP3/FLAC container/tag byte-diff diagnostic | stdlib | Production mutation | Low |

No active circular import was found. A few imports are deliberately local: `FetchWorker.run()` imports `metadata_api`, `CoverFetchWorker.run()` imports MB similarity, and `TouchSafeFileList` lazily imports `QScroller`. Moving these to module scope can alter import/startup behavior even though no verified cycle currently requires them.

## 4. UI architecture

`MusicEditorWindow` builds three main areas: workflow actions, a library pane, and local/result metadata panels. It owns Qt objects, event handling, progress dialogs, selection, keyboard shortcuts, request generations, per-window caches, and service factories used by tests. It converts UI state to plain requests and converts plain worker results back to widgets.

Widget-local/presentation state includes:

- editable combo values, checkboxes, lock buttons, cursor/selection positions;
- result-panel line edits and selected Provider button;
- filename-clue action availability and its compact source/no-result text;
- list/header items, hidden search rows, scroll animation, and status markers;
- `current_cover_data`, mixed/modified flags, overlay/progress state;
- audio-player media state.

State that belongs outside widgets includes loaded metadata, virtual groups, lock records, save rules, Provider matching, tag format logic, managed snapshots, filesystem restore, and cancellation checkpoints. These are already extracted and must not be reintroduced into widgets.

Reusable components are deliberately narrow:

- `library_widgets.py`: touch/wheel/list/index behavior only;
- `cover_gallery.py`: choose one downloaded byte payload;
- `audio_player_widget.py`: preview only;
- `ui_components.py`: loading, settings, and raw-debug dialogs;
- `album_initials.py`: deterministic navigation labels.

Remaining coupling in `main_window.py` is real rather than merely line-count related: editor widgets mirror session metadata; source preferences depend on album identity; save completion updates session, list, undo, and navigation; cover search can chain from metadata search; and undo re-applies both widget and selected session patches. Any extraction must preserve one state owner and these signal boundaries.

## 5. Session and editor state

| State | Owner | Lifetime/mutability | Classification and consumers |
| --- | --- | --- | --- |
| `AlbumSession.all_files_data[path]` | `AlbumSession` | Per window/directory; replaced after load, save, restore | Authoritative in-memory metadata view; list, editor, album identity, save plan |
| `selected_files_data[path]` | `AlbumSession` | Rebuilt on selection | Derived/mirrored selection view, usually referencing current loaded dicts; editor comparison and save request |
| `virtual_album_map` / `virtual_album_anchors` | `AlbumSession` | Per directory | Authoritative session-only grouping and stable sorting anchor |
| `locks_data[path][field]` | `AlbumSession` | Per directory | Authoritative lock records; mirrored by visible lock buttons |
| `album_sync_keys` | `AlbumSession` | Per session; defaults to album, album artist, date, genre | Save-plan configuration; preserved by `reset_for_file_load()` |
| `last_selected_album` | `AlbumSession` | Selection lifetime | Derived marker for auto-clearing manually supplied IDs |
| `inputs` / `checkboxes` | Window widgets | Current selection/edit | Authoritative pending unsaved text and elected fields |
| visible lock buttons | Window widgets | Current selection | Mirror of the first selected path; toggling applies to all selected paths |
| `_editor_baseline` | Window | Replaced after selection/action | Mirrored last captured widget snapshot used to form undo commands |
| `_selection_metadata_baseline` | Window | Replaced after selection/save/restore | Text/cover baseline used to warn before abandoning unsaved metadata edits |
| `current_cover_data` | Window | Current selection/edit | Pending cover bytes or `None`; paired with `_cover_is_mixed` and `cover_modified_in_batch` |
| `mb_inputs`, `available_source_results`, `_current_metadata_source` | Window | Current Provider result | Displayed candidate and source map; result-level source selection |
| filename-clue status text and request identity | Window | Current selection/request | Presentation-only source text is captured in editor undo; result values themselves live only in `inputs` |
| `api_cache[path]` | Window | Until directory reload | Cached normalized Provider result, raw logs, and display strings |
| `album_source_preferences[key]` | Window | Until directory reload | Preferred source per virtual/physical album identity |
| `_physical_album_key_cache`, `_cover_fingerprint_cache` | Window | Invalidated on known metadata updates | Derived album/cover identity acceleration |
| `_track_item_cache`, `_header_item_cache` | Window | Directory/list lifetime | Derived Qt object identity, not metadata truth |
| request generations/active IDs/cancelled-ID sets | Window | Per window/process run | Async identity and stale-completion protection |
| `UndoManager` history | Window | Until directory reload/window close | Authoritative in-memory editor/save undo and redo stacks; a new command clears redo |
| MB/Apple/resolver caches | Provider modules | Python process lifetime | Process-global network/decision cache shared by windows |

Parallel-source risks:

- `selected_files_data` is rebuilt on selection and explicitly refreshed for successful save/restore read-back affecting the current selection.
- Widget edits are intentionally not copied into `all_files_data` until a successful write, except the existing lock-propagation path, which updates synchronized in-memory fields immediately.
- `api_cache` is per file and is not generally invalidated by a metadata save; source preference uses album plus cover identity and may change when those fields change.
- Files changed outside the application make `all_files_data` stale until reload/read-back. Saved restore detects managed-field divergence only when undo is attempted.

## 6. Complete metadata lifecycle

| Stage | Owner | Input -> output / transformation | Error, cancellation, and source of truth |
| --- | --- | --- | --- |
| Local scan | `FileLoaderWorker` | configured directory -> top-level MP3/FLAC paths -> up to four round-robin reader partitions | One `ThreadPoolExecutor` task owns each active partition; per-file exceptions are swallowed; no cancellation/generation; filesystem is source |
| Tag read | `AudioTagger.read_tags()` | ID3/Vorbis/Picture tags -> normalized metadata dict | Returns empty defaults and prints format read errors; file is source |
| Loaded state | `on_load_finished()` / `AlbumSession` | worker dict -> `all_files_data`, sortable list | UI thread; in-memory dict becomes current window truth |
| Selection | `MusicEditorWindow` | selected paths -> `selected_files_data`, mixed/single combo values, cover state | Reads file directly only if path absent from loaded state; selection view is derived |
| Search request | `do_fetch()` | first selected path plus visible title/artist/album/track/disc and optional IDs -> `FetchWorker` arguments | UI validates required title/track clues; first selected item supplies local debug metadata |
| MusicBrainz | `mb_api.search_mb()` | local clues/MBID -> normalized MB dict, raw records | Cooperative cancellation; 10 s requests, paced waits; release track titles override shared recording titles, and artist credits use the application multi-value separator |
| Apple | `apple_music_api.search_apple_music()` | clues, MB artist identities, optional collection ID -> normalized Apple dict | Cooperative cancellation; 12 s requests; no live retry in this adapter |
| Cross-source comparison | `metadata_api.search_metadata()` | successful source dicts -> one default dict plus `source_results` | Direct IDs override fuzzy choice; textual tie prefers MB; failure only if both fail |
| Artist presentation | Apple adapter + resolver | Apple storefront variants + MB identities -> one existing artist/album-artist pair | Optional DeepSeek tie-break is a selector; its 15 s request lacks cancellation input |
| Result display | window `_fill_mb_panel()` | selected normalized dict -> read-only fields and comparison styling | UI thread; Provider result remains a proposal, not local truth |
| User choice/edit | window | source button/field apply/manual combo edit/checkbox/lock/cover -> pending widget state | Editor undo snapshots changes; locked fields reject Provider application |
| Save request | `_execute_save()` | widgets/session -> `SavePlanRequest` | `<preserve>` values are omitted; `<blank>` becomes empty string; no filesystem access |
| Save planning | `build_save_plan()` | request -> immutable `SavePlan` of primary/sync items | Pure; no cancellation; request/session state is source |
| Save execution | `SaveWorker` + `MetadataSaveService` | plan -> before snapshots, writes, read-back `SaveResult` | Per-item failures continue; dependencies require primary success; no rollback/cancel |
| Tag mutation | `AudioTagger.update_tags()` | partial metadata payload -> MP3/FLAC managed tags | Tagger owns encoding and cover replacement; file becomes persistent truth |
| In-memory refresh | `_finish_save()` | successful read-back -> `all_files_data`, current selection mirror, list status/header | Album rename headers update in place and retain their current-session order; failed/skipped paths keep previous values |
| Saved undo record | `_finish_save()` / `UndoManager` | before/after successful snapshots -> one `SavedMetadataTransaction` | In-memory only; successful paths' editor commands are discarded first |
| Restore/redo | `RestoreWorker` + `MetadataRestoreService` | saved changes or their reversed snapshots -> conflict-checked exact managed restore -> read-back | Current fingerprint must equal recorded `after`; partial operations remain retryable in their current undo/redo stack |

MusicBrainz and Apple run sequentially inside one fetch worker. A successful search never writes local tags automatically. Source switching selects a complete normalized result, after which the user may apply individual fields or all eligible fields.

### Versioned diagnostics

The application produces three diagnostic log families tied to the same `APP_VERSION`:

| Log family | Filename | Creation and contents |
| --- | --- | --- |
| Runtime | `runtime_logs/runtime-v<version>-YYYYMMDD.log` | Created/appended during startup; contains transcribed stdout/stderr and uncaught exception tracebacks for that version and day |
| Metadata search export | `metadata-search-v<version>-YYYYMMDD-HHMMSS.log` | Explicit export from the metadata debug dialog; contains the displayed search records and a version header |
| Cover search export | `cover-search-v<version>-YYYYMMDD-HHMMSS.log` | Explicit export from the cover debug dialog; contains the displayed cover-search records and a version header |

Runtime logs live under `runtime_logs/` at the application directory. Search logs are user-selected exports and may live elsewhere. Search debugging data remains owned by Provider/worker results and the dialog only renders and exports it; adding a version marker does not move matching or acquisition logic into the UI.

Logs are diagnostic artifacts, not application state, caches, undo history, or test fixtures. They may contain file paths and metadata even though secrets and binary payloads are excluded, so they must not be committed. For active debugging, keep the current version and, when comparison is useful, the immediately preceding version. Once the current version has captured the reproduction, older-version and legacy unversioned logs can be deleted without affecting application behavior.

## 7. Metadata field semantics

The normalized managed shape contains these text fields plus binary cover state:

`title`, `artist`, `album`, `album_artist`, `composer`, `track`, `disc`, `date`, `genre`, `comment`, `cover_data`.

### MP3

| Normal field | ID3 handling |
| --- | --- |
| `title` | `TIT2` |
| `artist` | all `TPE1` text values |
| `album` | `TALB` |
| `album_artist` | all `TPE2` values |
| `composer` | all `TCOM` values |
| `track` / `disc` | `TRCK` / `TPOS`, retained as strings |
| `date` | read `TDRC`, fallback `TYER`; write `TDRC` and remove legacy `TYER`, `TDAT`, `TORY` |
| `genre` | all `TCON` values |
| `comment` | all `COMM` plus `TXXX` entries whose description contains `163 key`; write replaces all `COMM` and those `163 key` entries |
| `cover_data` | first `APIC` on read; writes replace all `APIC` frames |

### FLAC

Text uses Vorbis fields `title`, `artist`, `album`, `albumartist`, `composer`, `tracknumber`, `discnumber`, `date`, and `genre`. Date falls back to `year`; writing `date` removes `year`. Comments combine `comment`, `description`, and keys containing `163 key`; writing removes those managed comment forms and writes values to `description`. The first FLAC picture is read; cover writes clear all pictures and add one front-cover `Picture`.

The application-level multi-value separator is the literal two-backslash string `\\`. MP3 frames and FLAC value lists are joined to this string on read and split on write for artist, album artist, composer, and genre. Track/disc values are not reformatted for writing; Provider matching uses the first numeric substring, and list sorting uses the portion before `/` only when it is entirely numeric.

MusicBrainz artist credits discard Provider joinphrases such as `feat.`, `Remixed by`, `&`, or punctuation and join all non-empty credit names with the same application-level multi-value separator.

An exact `VA` after removing dots/spaces is normalized to `Various Artists` during tag reading and MusicBrainz input preparation. This normalization is not a general artist canonicalizer.

Cover MIME is inferred as PNG only from the PNG signature; every other payload is treated as JPEG. Optional Pillow fills FLAC picture dimensions, but absence of Pillow does not block saving. Normal updates touch only supplied managed fields. Exact restore supplies every managed field and explicit cover state. Existing real MP3/FLAC tests verify that representative unrelated custom tags survive restore.

No format other than MP3 and FLAC is supported by scan/tag/write/restore code.

## 8. External metadata architecture

### MusicBrainz

`search_mb()` accepts fuzzy clues or an explicit release/recording MBID. A direct recording request uses `/recording/{id}?inc=releases+artist-credits+work-rels+artist-rels`; it takes the first returned release. A direct release ID skips release search but still selects a track from that release.

Normal matching is three-stage:

1. Search `/release` with tiered Lucene terms derived from album and lead artist. Rank release text as album 75% and artist 25%; accept at least 0.25.
2. If no release is found, search `/recording` by title/artist and choose a linked release using album 60% and artist 40%.
3. Fetch `/release/{id}?inc=recordings+artist-credits`, score tracks as title 75% and artist 25%, then add 2.0 for an exact numeric track match and 0.5 for an exact numeric disc match. Unless `only_album` or direct release mode applies, reject below 0.35. Fetch the chosen recording detail for final title/artist, composer relations, and date fallback.

Artist identities come from `/artist/{id}?inc=aliases`, producing MBID, canonical name, country, aliases, locale, and primary flags. Requests use 10 s timeouts and a cancellable 1 s wait before MusicBrainz calls. There is no general retry loop. Raw JSON/status records are accumulated for the debug dialog.

Module caches cover release search keys, release tracklists by release ID, recording details by recording ID, and artist identity by artist MBID. `no_cache=True` bypasses reads but successful calls still populate caches.

### Apple Music/iTunes

The adapter uses `https://itunes.apple.com/search` and `/lookup`:

1. Search albums with a query normally composed from album and artist. Search artist home-country storefronts from MusicBrainz identity evidence, then US and CN, stopping when a storefront contains a collection baseline of at least 0.90.
2. Deduplicate collection IDs and inspect at most the four best collections. Lookup collection tracks across storefront fallbacks; CN can fall back to HK/US, and HK/TW can fall through HK/CN/US.
3. Score a song as title 50%, album 30%, lead artist 20%; without title, album is 70% and artist 30%. Matching track/disc add 0.08/0.04 and the result is capped at 1.0. A direct collection ID plus numeric local track requires exact track/disc for a score of 1.0.
4. Reject below 0.40 except in `only_album` mode. For album-level metadata, prefer the lookup response's collection record over redundant fields embedded in a track; this applies to both matching and the normalized album name. Prefer collection release date over track release date and truncate to ten characters.
5. If a sibling storefront supplied a missing tracklist, look up the selected track ID in the preferred storefront. Then resolve artist presentation with available MB identity evidence.

Album search, collection lookup, and track lookup each have process-global caches keyed by query/ID plus country. Requests have 12 s timeouts and no adapter-level retry. The exact matched collection's artwork URL/storefront is included for the cover workflow.

### Combined selection

`metadata_api.py` recalculates comparable source quality using title 50%, artist 20%, and album 30%, reweighting when an expected field is absent. Each textual comparison is 85% normalized MB-style similarity plus 15% literal case-folded similarity. Artist comparison permits the local lead artist to match one collaborator component.

Track/disc bonuses are intentionally excluded from cross-source quality. A direct MBID or direct Apple collection ID receives normalized quality 1.0. If both direct overrides are supplied and MusicBrainz succeeds, the explicit MBID takes precedence. Otherwise explicit Apple wins when successful; fuzzy ties prefer MusicBrainz because it provides relationship and Cover Art Archive evidence.

Selection is result-level, not an automatic field-by-field merge. The UI retains both normalized dictionaries in `source_results`, permits explicit source switching, and permits later per-field application.

## 9. Artist-name resolution

Apple can return different official display names for one track ID across storefronts. MusicBrainz supplies identity evidence: canonical names, country, aliases, locale, and primary flags. `select_artist_variant()` deduplicates existing Apple candidates by artist/album-artist and applies this order when uniquely decisive:

1. artist home-country storefront;
2. MusicBrainz canonical-name match;
3. Japanese JP-storefront writing backed by local/MB Japanese evidence;
4. any MusicBrainz identity/alias match;
5. a sole readable Latin/Japanese candidate;
6. tie-breaker.

The tie-breaker checks an in-memory decision cache, then optionally calls DeepSeek using `DEEPSEEK_API_KEY` from the environment or `APP_SETTINGS`. The model receives local artist text, MusicBrainz identities, and the finite candidate list. Its response is only a country code; code maps that back to an existing candidate. Therefore it is not allowed or able through the normal path to create a new name. If unavailable or invalid, deterministic storefront priority is used.

Privacy/security rules:

- never log or expose the API key;
- remember that candidate names and MusicBrainz identity evidence are sent to DeepSeek;
- do not add file paths, local tags unrelated to identity, or secrets to that payload;
- `settings.json` stores the key as plaintext and must not be committed or pasted into reports.

The decision-cache key currently contains candidate country/name pairs but not identity evidence or local artist. It lasts for the process. The DeepSeek request has a 15 s timeout and does not accept the search cancellation event, so cancellation may be delayed at this stage.

## 10. Save architecture

```text
editor widgets + AlbumSession
  -> SavePlanRequest
  -> build_save_plan()
  -> SavePlan(primary SaveItem(s), optional dependent sync SaveItem(s))
  -> SaveWorker
  -> MetadataSaveService.execute()
       -> capture every unique path's managed before-state
       -> enforce depends_on success
       -> AudioTagger.update_tags(payload)
       -> read managed tags back
  -> SaveResult
  -> MusicEditorWindow updates all_files_data/list/status
  -> SavedMetadataTransaction(before, after) for successful paths
```

The UI owns sentinel interpretation and field election. Checked fields are recorded separately from actual `field_updates`: `<preserve>` produces no direct update, while `<blank>` produces an empty string. Automatic Provider application respects locks and, on multi-selection, does not apply `title`, `artist`, `track`, or `disc`. A user's explicit current-file write is not blocked by a lock.

Every selected path gets a primary item. Only a single selected primary can produce dependent synchronization:

- a virtual reference syncs only within the same virtual group;
- a physical reference syncs only ungrouped paths with the same non-empty trimmed album and equal cover fingerprint;
- album can be propagated when non-empty and target-unlocked;
- other fields are restricted to configured `album_sync_keys`, checked state, non-`None` value, and target lock;
- a non-empty reference cover can be propagated; primary cover removal is representable when the cover is explicitly marked modified and is `None`, but the current UI exposes no dedicated remove-cover command;
- each sync item depends on successful completion of the reference primary.

`MetadataSaveService` captures all unique before-states before the first mutation. Snapshot-capture failure marks that path failed. Other item failures do not stop later independent items. A dependent item whose dependency failed is skipped; it is not written and is not currently reported as a failed item. Progress is emitted before dependency evaluation. There is no transaction-wide filesystem rollback.

Responsibility placement:

- UI input validation/sentinel handling: `MusicEditorWindow`;
- album/write business rules: `save_plan.py`;
- mutation ordering, snapshots, read-back, partial result: `metadata_save_service.py`;
- format-specific validation/encoding: `audio_tagger.py`;
- progress/dialog/errors/in-memory refresh: `MusicEditorWindow` through `SaveWorker` signals;
- later user-requested restore: `MetadataRestoreService` and undo transaction, not save execution.

There is no preview/dry-run UI. `SavePlan` is inspectable plain data in tests/debugging, but building it does not itself provide a user-facing preview.

## 11. Undo and restore architecture

Two different mechanisms share one LIFO `UndoManager`:

### Unsaved editor undo

`EditorStateSnapshot` contains selected paths, current field text, checkbox/lock state, cursor selections, cover/mixed/modified state, result-panel values, selected source, and status/score text. `SessionPatch` optionally stores previous metadata/locks or source-preference/API-cache entries. Continuous typing in the same field/path can merge within 0.55 seconds. Applying undo suspends recording so restoration does not create a new command.

The undo and redo stacks share limits of 40 commands and 128 MiB. Cover byte payloads are SHA-256 interned to reduce duplicate memory. Undo moves a command to redo, redo moves it back to undo, and a new command clears redo. Virtual-album grouping, skip markers, settings, and local file workflows are not represented as editor undo commands.

### Saved-file restore

Before/after managed metadata is represented by immutable `ManagedMetadataSnapshot`, including empty fields and explicit cover state. Successful writes are grouped into one `SavedMetadataTransaction`. Before pushing it, editor commands affecting successful paths are discarded, so the next Ctrl+Z restores the saved files rather than only changing stale widgets.

`MetadataRestoreService` reads current managed metadata and compares its fingerprint to the transaction's recorded `after` snapshot. A mismatch is an external-change conflict and is not overwritten. A matching file is restored through `AudioTagger.restore_managed_tags()`, read back, and verified against `before`. Unmanaged tags are outside the fingerprint and are preserved by the format-specific managed restore.

Restore runs in `RestoreWorker`. Successful paths update `all_files_data`, are removed from the transaction, and can restore selection to the first success. Failed/conflicting paths remain in the same top transaction for retry. History is not persisted to disk; application exit or directory reload loses it. There is no durable journal, crash recovery, or automatic rollback after save failure.

## 12. Threading and asynchronous execution

| Worker | Input | Output signals | Cancellation/stale handling |
| --- | --- | --- | --- |
| `FileLoaderWorker` | directory | progress `(current,total,filename)`, finished `(sortable,data)` | No cancellation or request generation |
| `FetchWorker` | local clues, IDs, local metadata, request ID/event | progress text; finished `(success,data,raw,msg,path,id,cancelled)` | Event + `requestInterruption`; Provider checkpoints; window ID rejection |
| `FilenameClueWorker` | one basename, target path, request ID/event | finished `(result,path,id,cancelled)` | Plain Qt-free result; window rechecks request ID, path, current blanks, and locks |
| `CoverFetchWorker` | artist, album, release/artwork identity, request ID/event | progress text; finished `(images,stats,raw,id,cancelled)` | Event + interruption; retry waits are cancelable; window ID rejection |
| `SaveWorker` | immutable `SavePlan`, service | item progress, result/failure | No cancellation; close is blocked while running |
| `RestoreWorker` | transaction changes, service | item progress, result/failure | No cancellation; close is blocked while running |

All workers are `QThread` subclasses. They own plain inputs and emit plain results; they do not access widgets. `MetadataSaveService` and `MetadataRestoreService` are Qt-free and report progress through callbacks that workers convert to signals. UI updates happen in connected window slots.

Metadata/cover cancellation sets a `threading.Event`, calls `requestInterruption()`, marks the active request ID as cancelled, and disables search controls until completion. Provider code checks the event before/after network calls and inside loops; MB pacing and cover retry waits are event-aware. A blocking HTTP call can only observe cancellation after it returns or times out. The DeepSeek tie-break request has no cancellation argument.

Stale-result prevention is separate: `_metadata_search_generation` and `_cover_search_generation` monotonically assign IDs; completion slots return immediately unless the ID equals the active ID. Cancelled IDs also prevent a cancellation race from being displayed as failure. Metadata and cover searches have separate generations and cancelled-ID sets. Progress signals do not carry IDs, so their safety depends on only one same-kind worker being active and cancelled fetch progress being suppressed.

MusicBrainz and Apple metadata acquisition are sequential within one worker, not parallel. Auxiliary NCM conversion, audio moves, lyric deletion, settings writes, debug-log export, and temporary cover-file writes still execute synchronously on the UI thread.

Filename clue analysis is a separate explicit single-track action. The current Qt-free entry performs only deterministic local parsing; the window writes accepted non-empty values into blank, unlocked editor fields through one `_record_editor_mutation()` command. It preserves checkbox state and does not invoke Provider search, `SavePlan`, or tag writes.

Worker cleanup connects `QThread.finished` to a slot that calls `deleteLater()` and clears the stored worker only if identities match. Closing during a search requests cancellation and ignores that close event; closing during save/restore is simply ignored until completion.

## 13. Cover-art workflow

```text
normalized metadata result
  -> MusicBrainz release_id and/or Apple artwork URL/storefront
  -> CoverFetchWorker
       -> exact Apple artwork reuse, else fuzzy iTunes cover search
       -> first front image from Cover Art Archive release
       -> retry selected transient HTTP statuses
  -> raw byte candidates + per-source stats/debug records
  -> CoverGalleryDialog decodes thumbnails with QImage
  -> selected bytes
  -> current_cover_data + cover_modified_in_batch
  -> SavePlan cover flags
  -> AudioTagger APIC/FLAC picture replacement
```

When metadata already matched an Apple collection, its artwork URL is preferred and fuzzy Apple cover search is skipped. The URL's `100x100bb` segment is changed to `10000x10000bb`. Otherwise the worker searches US, GB, JP, and CN using album/artist variants, scores album 75% and artist 25%, stops at 0.75, and accepts at least 0.25.

Cover Art Archive uses the MusicBrainz release ID and downloads the first image marked `front`. The common request helper retries up to four times for 429/500/502/503/504 and request exceptions, with incremental cancelable waits and 10/15 s request timeouts.

The worker does not transform or explicitly validate downloaded image bytes. The gallery's `QImage.fromData()` supplies display dimensions and implicit decode feedback, but invalid bytes are not rejected by a dedicated validation layer. Clipboard images are re-encoded as PNG when alpha is present, otherwise high-quality JPEG. Saved bytes remain separate from Provider text metadata.

Selection cover states are:

- all selected covers byte-equal: `current_cover_data` holds that value and `_cover_is_mixed=False`;
- selected covers differ: `current_cover_data=None`, `_cover_is_mixed=True`;
- user pasted/chose a cover: bytes set, mixed cleared, `cover_modified_in_batch=True`;
- unchanged selection: `cover_modified_in_batch=False`, so primary save does not rewrite cover.

Cover changes are editor-undoable, and saved cover state participates in filesystem restore fingerprints. There is no durable cover cache; only exact Apple artwork identity retained in `api_cache` can avoid a fuzzy lookup.

## 14. Local file workflow

`file_workflow.py` verifies these behaviors:

- `convert_ncm_files()` runs the bundled `Ncm...exe` once per top-level `.ncm` file with `subprocess.run(check=True)`. It preserves source NCM files. In development the executable is resolved beside the module; in a frozen PyInstaller process it is resolved under `sys._MEIPASS`.
- `delete_ncm_files()` permanently deletes the exact reviewed list. `MusicEditorWindow.confirm_delete_ncm()` displays a modal file list and explicit destructive confirmation first. This operation is not undoable.
- `move_audio_files()` moves top-level MP3/FLAC files from the download directory to the main directory, creates the target, and avoids overwrites with ` (n)` suffixes. The current UI invokes it without a confirmation dialog. Moving is destructive to source paths and not undoable.
- `clean_lrc_files()` permanently deletes top-level `.lrc` files in both configured directories. The current UI invokes it without confirmation and it is not undoable.
- `SettingsDialog` edits download directory, music directory, and DeepSeek key. `save_settings()` writes UTF-8 JSON next to the source application or packaged executable. Changing the main directory triggers a reload.

These helpers currently run synchronously under a wait cursor, so large operations can block the UI. Return success generally means the workflow ran, not that every individual conversion/move succeeded; individual failures are printed and counts can be lower than discovered files.

`config.py` checks `sys.frozen` and uses the executable directory for packaged settings. `build_release.ps1` is the reproducible Windows packaging entry point: it requires an explicit Python interpreter, reads `config.APP_VERSION`, builds a one-file/no-console PyInstaller executable with the NCM converter embedded, creates a ZIP containing the EXE and license notices, and writes SHA-256 checksums. Generated `build/`, `dist/`, and `.spec` files remain ignored.

## 15. Caches and identity

| Cache/identity | Key | Lifetime/invalidation | Stale-data risk |
| --- | --- | --- | --- |
| MB release search | normalized album/sub/artist word tuples + mode | Process; bypass read with `no_cache`; no clear API | Provider data and heuristics can outlive edits/windows |
| MB release tracklist | release MBID | Process | Remote release changes not observed |
| MB recording detail | recording MBID | Process | Remote relationship changes not observed |
| MB artist identity | artist MBID | Process | Country/alias changes not observed |
| Apple album search | case-folded query + country | Process | Remote/storefront changes not observed |
| Apple collection lookup | collection ID + country | Process | Tracklist/storefront changes not observed |
| Apple track lookup | track ID + country | Process | Localized name changes not observed |
| Resolver decision | candidate country/artist/album-artist tuples | Process; only DeepSeek success cached | Key omits local/MB identity evidence |
| `api_cache` | absolute file path | Per window; cleared on directory load | Saved/manual metadata can leave cached proposal based on old clues |
| source preference | virtual group, physical `(album,cover hash)`, or file path | Per window; cleared on load; undo patchable | Album/cover changes alter identity; old key can remain |
| physical album key | path + observed album/cover object identity | Per window; explicit invalidation on known metadata changes | External edits are invisible until reload |
| cover fingerprint | byte-object identity | Per window; globally cleared on known metadata changes | Memory growth bounded only by session/reset |
| list items/headers | path/header identity | Per directory/list rebuild | Must not be treated as metadata truth |
| metadata/cover request ID | monotonic per-window generation | Window lifetime | Guards completion, not module caches |

`no_cache` prevents reading per-Provider caches but successful calls still write them. Directory reload clears window caches but not module caches. Most cache writes follow request cancellation checks; no transactional cache invalidation contract exists.

## 16. Architectural invariants

1. Persistent metadata mutation flows through `SavePlan` -> save service -> `AudioTagger`.
2. Planning remains pure and independent of Qt/filesystem state.
3. Filesystem services remain independent of widgets and report plain result objects.
4. `AudioTagger` alone maps normalized fields to MP3/FLAC tags.
5. `AlbumSession` remains free of Qt, network, and filesystem dependencies.
6. Physical album identity is non-empty album text plus cover fingerprint; virtual album identity is explicit group membership.
7. Multi-selection does not generate dependent album-sync writes.
8. Locks affect Provider application and dependent writes, not an explicit direct primary write.
9. Track-specific fields are not automatically applied from one Provider result to multiple selected tracks.
10. Cover mixed/absent/modified states remain distinct.
11. Before-state is captured before any item in a plan is mutated.
12. Dependent writes require their primary path to have succeeded.
13. Partial save success is retained; no automatic rollback is implied.
14. Saved restore requires current managed state to equal recorded post-save state.
15. Restore replaces every managed field and explicit cover state while preserving unrelated tags.
16. Editor undo never performs filesystem restoration; saved transactions always do.
17. Worker threads never mutate widgets directly.
18. Cooperative cancellation does not replace request-generation stale-result checks.
19. A cancelled completion is not shown as an ordinary Provider failure.
20. Provider source choice is whole-result choice; field application remains explicit.
21. DeepSeek may select only an existing candidate and secrets never enter debug logs.
22. Directory reload resets per-window state/history; saved undo is not durable.

## 17. Known risks and technical debt

### Risk: dense window coordination

**Where:** `main_window.py`, `MusicEditorWindow`

**Why it exists:** One window coordinates several state mirrors and Qt lifecycles.

**Failure mode:** A local change can omit cache invalidation, undo baseline, control state, or worker cleanup.

**Safe modification strategy:** Trace one workflow end to end; extract only a proven responsibility with one owner and explicit signals.

**Verification:** Relevant UI tests plus full suite; manually exercise the exact selection/search/save/undo path.

### Risk: mirrored editor/session state

**Where:** `all_files_data`, `selected_files_data`, widgets, `_editor_baseline`, `api_cache`

**Why it exists:** Unsaved UI edits and loaded/persisted metadata have different lifetimes.

**Failure mode:** Display, planning, album identity, or undo can consume an older mirror.

**Safe modification strategy:** Fix the earliest synchronization boundary and avoid another cache/store.

**Verification:** Compare local, selected, widget, plan, written, read-back, and restored values.

### Risk: album synchronization identity

**Where:** `save_plan.py`, physical/virtual album helpers in `main_window.py`

**Why it exists:** Physical grouping uses album plus cover; temporary grouping overrides physical identity.

**Failure mode:** Unrelated files receive dependent writes, or intended siblings are missed.

**Safe modification strategy:** Preserve virtual membership, ungrouped exclusion, cover fingerprint, checkbox, sync-key, and lock rules together.

**Verification:** Extend `test_save_plan.py` with physical, virtual, locked, cover, and dependency cases.

### Risk: partial save without rollback

**Where:** `metadata_save_service.py`, `_finish_save()`

**Why it exists:** Each file is independently mutable and failures do not stop later independent writes.

**Failure mode:** Some files are changed while others fail; dependency-skipped files are not listed as failed.

**Safe modification strategy:** Do not add implicit rollback in UI code. Change result semantics/service behavior only with explicit tests and UX decisions.

**Verification:** Inject capture/write/read-back/dependency failures and inspect saved transaction membership.

### Risk: undo consistency is memory-only

**Where:** `undo_manager.py`, save/restore completion in `main_window.py`

**Why it exists:** History stores rich snapshots but has no durable journal.

**Failure mode:** Exit/reload loses restore ability; external managed edits create conflicts; mirrored selection can remain stale.

**Safe modification strategy:** Preserve fingerprints, strict LIFO, partial retry, recording suspension, and successful-path filtering.

**Verification:** `test_undo_manager.py`, `test_metadata_restore.py`, application-level undo tests.

### Risk: Provider heuristics and normalization

**Where:** `mb_api.py`, `apple_music_api.py`, `metadata_api.py`, `audio_tagger.py`

**Why it exists:** Matching, presentation, and format normalization occur at different legitimate boundaries.

**Failure mode:** A scoring bonus selects an unrelated release, presentation changes unexpectedly, or two layers normalize differently.

**Safe modification strategy:** Decide whether a rule is Provider acquisition, cross-source comparison, artist selection, or tag encoding; change only that owner.

**Verification:** Deterministic mocked candidates, including conflicting exact/fuzzy and numeric-position cases.

### Risk: global cache invalidation

**Where:** MB/Apple/resolver module globals and window `api_cache`

**Why it exists:** Caches optimize a personal desktop process with no expiry layer.

**Failure mode:** Remote changes or edited local clues do not trigger a fresh decision.

**Safe modification strategy:** Preserve existing keys unless a bug proves them insufficient; add explicit invalidation tests before changing scope.

**Verification:** Run repeated searches with/without `no_cache` and assert network calls and selected data.

### Risk: cancellation gaps and stale workers

**Where:** workers, `search_cancellation.py`, window request IDs, DeepSeek call, loader

**Why it exists:** HTTP calls block until timeout; only metadata/cover completions carry generations.

**Failure mode:** Cancellation appears slow, old UI progress leaks, or overlapping directory loads overwrite state.

**Safe modification strategy:** Keep event checkpoints and generation checks separate; add identity to any newly concurrent operation.

**Verification:** Controlled delayed workers that finish out of order, cancel during waits/calls, and emit completion after a new ID.

### Risk: cover state and validation

**Where:** window cover flags, `CoverFetchWorker`, gallery, save plan, snapshots

**Why it exists:** Binary payload, mixed selection, unchanged cover, and explicit absence are distinct.

**Failure mode:** Mixed cover becomes removal, unchanged cover is rewritten, invalid bytes are saved, or restore misses cover state.

**Safe modification strategy:** Carry bytes and flags separately and add explicit decode/validation only in the cover acquisition boundary.

**Verification:** Mixed, cover-only, text-only, no-cover restore, invalid image, and dependent-cover cases.

### Risk: hidden local configuration and release inputs

**Where:** `.vscode/settings.json`, `settings.json`, `requirements*.txt`, `config.py`, `build_release.ps1`, build artifacts

**Why it exists:** The interpreter and settings are machine-local, while release packaging embeds a converter and generates artifacts beside ignored settings and logs.

**Failure mode:** Wrong Python, dependency drift, leaked API key/local metadata, omitted bundled resources, or accidental publication of settings/logs.

**Safe modification strategy:** Follow `AGENTS.md` interpreter rules, keep runtime/build manifests current, use `build_release.ps1`, and publish only its named EXE/ZIP/checksum outputs.

**Verification:** Report the exact interpreter; run `pip check` and tests; inspect the archive/ZIP; launch the packaged EXE from an isolated directory; never publish settings or logs.

### Risk: synchronous destructive local workflows

**Where:** `file_workflow.py` calls from `main_window.py`

**Why it exists:** Auxiliary operations predate worker abstractions.

**Failure mode:** UI freezes, source files move/delete without undo, and partial failure is under-reported.

**Safe modification strategy:** Preserve source-retention and confirmations; require explicit scope before changing destructive semantics or threading.

**Verification:** Temporary directories with collisions/failures and confirmation-path UI tests.

### Risk: live external behavior is untested

**Where:** all Provider and artwork integrations

**Why it exists:** Automated tests mock network calls.

**Failure mode:** Endpoint/schema/rate-limit/storefront changes break runtime despite green tests.

**Safe modification strategy:** Keep raw-debug records, bounded timeouts, and graceful fallback; avoid tests that require live services by default.

**Verification:** Authorized manual lookup with non-sensitive data plus mocked regression coverage.

## 18. Safe extension points

| Extension | Correct owner and files to review |
| --- | --- |
| New metadata Provider | Add a normalized adapter, then review `metadata_api.py`, `background_workers.py`, source controls/cache in `main_window.py`, cancellation, raw-debug format, and Provider tests. Current UI is hard-coded to two sources. |
| New metadata field | Update `audio_tagger.py` managed mappings, both managed-field lists/snapshot model in `undo_manager.py`, UI `field_configs`, Provider normalized outputs as applicable, save/restore tests, and multi-select/sync policy. |
| New audio format | Update loader glob/filter, every `AudioTagger` read/update/restore branch, file-move filters, managed restore tests, cover semantics, and packaging dependencies. |
| New matching rule | Provider-internal rule belongs in `mb_api.py` or `apple_music_api.py`; cross-source comparability belongs in `metadata_api.py`; add deterministic score/selection tests. |
| New cover source | Extend `CoverFetchWorker` result/stats/debug handling and cancellation/retry behavior; review gallery and cover tests. Do not write tags there. |
| New background operation | Add a focused worker/signal contract in `background_workers.py` or a dedicated worker module, then create/clean it in the window with close/cancel rules and stale identity if overlap is possible. |
| New editor command | Use `_record_user_editor_change()` for normal widget signals or `_record_editor_mutation()` for atomic programmatic actions; extend snapshots/session patches only for state required to reverse it. |
| New filename-clue rule | Keep evidence parsing in `filename_clue.py`, return only the fixed five-field result, and test through `analyze_filename_clues()` plus the existing window boundary. Do not turn it into a Provider or tag writer. |
| New save rule | Implement in `save_plan.py` with plain request data and tests; review service result semantics and window reporting only if the plan/result contract changes. |

Do not create an interface or registry merely to anticipate one of these extensions. Add the narrowest boundary required by an actual feature.
