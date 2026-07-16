# Model Handoff

This is a compact continuity contract for switching coding models. Mandatory repository rules are in [`../AGENTS.md`](../AGENTS.md); load the relevant data flow from [`ARCHITECTURE.md`](ARCHITECTURE.md) before changing code.

## 1. Current architectural status

The repository is a functioning personal PyQt6 desktop application with recent, partial structural extraction from a large window coordinator. It is not a clean-slate layered framework, and it should not be converted into one casually.

Verified separations:

- `AlbumSession` owns loaded/selected metadata, virtual groups, locks, and sync configuration without Qt/filesystem dependencies.
- `save_plan.py` calculates primary and dependent writes without mutation.
- `metadata_save_service.py` executes plans and restores managed snapshots without widget dependencies.
- `AudioTagger` encapsulates MP3/FLAC tag interpretation and mutation.
- `undo_manager.py` represents editor snapshots, session patches, managed snapshots, saved transactions, and history limits separately from Qt application.
- MusicBrainz, Apple Music/iTunes, combined source comparison, and artist-name selection have distinct modules.
- cooperative search cancellation is shared through `search_cancellation.py`.
- directory scan, metadata fetch, save, restore, and cover download have dedicated workers.
- cover gallery, library/touch widgets, dialogs, album initials, and audio preview are extracted reusable UI units.
- `config.APP_NAME` is the single product name used by window titles, startup logs, and the `Music Metadata Perfecter` desktop shortcut. `config.APP_VERSION` is the single release/log identifier; runtime, metadata-search, and cover-search logs use it consistently.
- `main.py` captures stdout/stderr and uncaught exception tracebacks in a versioned daily runtime log, including when launched from the machine-local desktop/Listary shortcut.

Incomplete separations that must be understood rather than hidden:

- `MusicEditorWindow` still owns workflow coordination, widget/session mirrors, Provider-result caches, source preference, request identity, save/undo presentation, cover state, and local workflow calls.
- local conversion/move/delete/cleanup remains synchronous on the UI thread.
- per-window and process-global caches have different lifetimes and no unified invalidation contract.
- there is no automatic save rollback, durable undo journal, save dry-run, or reproducible packaging configuration.

The current automated suite is standard-library `unittest`. At this handoff's creation, the configured interpreter ran 60 discovered tests successfully, including temporary real MP3/FLAC restore tests using `ffmpeg`. External network behavior is mocked.

## 2. Stable areas

### Plain session boundary

`album_session.py` is small, Qt-free, tested, and has explicit virtual-group/lock operations. Safe changes are local state operations that preserve ownership and reset semantics. Do not make it read files or widgets.

### Save plan boundary

`save_plan.py` is the correct owner for album membership, lock, checkbox, configured sync field, cover propagation, and dependency rules. Safe changes use additional plain request data and deterministic tests. Do not add taggers or UI callbacks.

### Filesystem service/tagger boundary

`metadata_save_service.py` owns execution/snapshot/read-back results; `audio_tagger.py` owns format details. Preserve this split. Safe service changes are format-agnostic result/order behavior; safe tagger changes are verified MP3/FLAC mappings.

### Undo data boundary

`undo_manager.py` is widget-free and tested for LIFO, merging, memory limits, cover interning, partial saved-transaction retry, and fingerprints. Extend snapshots only when a real reversible state is missing.

### Provider adapters

`mb_api.py` and `apple_music_api.py` return a common metadata shape, while `metadata_api.py` performs comparable whole-source selection. Provider-specific search changes should stay in their adapter; cross-source changes belong only in the combiner.

### Worker signal boundary

Workers accept plain inputs, run off-thread, and emit plain outputs. Services remain Qt-free. Preserve signal argument contracts and identity-safe cleanup.

### Focused UI components

`library_widgets.py`, `cover_gallery.py`, `audio_player_widget.py`, `album_initials.py`, and dialogs are appropriately narrow. Styling/interaction fixes can usually remain local if they do not change metadata behavior.

### Version and diagnostics boundary

`config.APP_VERSION` is authoritative. A behavior-changing iteration bumps only this value; log filenames and headers derive from it. Do not add a second version constant to `main.py`, dialogs, workers, or Provider adapters.

The supported diagnostic families are `runtime_logs/runtime-v<version>-YYYYMMDD.log`, `metadata-search-v<version>-<timestamp>.log`, and `cover-search-v<version>-<timestamp>.log`. Runtime capture belongs to process startup; Provider/cover raw records remain owned by their existing adapters/workers and are only formatted/exported by the debug dialog. Versioning must not move search logic into UI code or allow secrets into logs.

The desktop shortcut is machine-local: it targets the interpreter from `.vscode/settings.json`, passes the absolute `main.py`, and uses the repository as its working directory. Never copy a machine-specific interpreter path into repository documentation or scripts. Recreate the shortcut only if the interpreter or repository path changes.

When diagnosing an iteration, use the current version and at most the immediately preceding version for comparison. Once the current version has captured the issue, older and legacy unversioned logs may be removed; logs are not application state and must not be committed.

## 3. High-risk areas

### `main_window.py`

Load selection handling, editor snapshots, request lifecycle, save completion, and undo completion before modifying shared state. A fix often needs one local change, but it must account for `_editor_baseline`, cache invalidation, signal cleanup, and list/session refresh. Size alone does not justify splitting it.

### Metadata source comparison

Load `metadata_api.py`, both Provider output shapes, source-switch UI/cache logic, and relevant tests. Internal Provider scores are intentionally different from normalized cross-source quality; do not compare them directly.

### MusicBrainz matching

Load Lucene query construction, release/fallback selection, track numeric bonuses, recording detail, identity lookup, pacing, cache keys, and cancellation. A numeric track match must not become cross-source textual certainty.

### Apple storefront and artist resolution

Load country ordering, collection/track lookup fallbacks, relocalization, `artist_name_resolver.py`, and mocked tests. DeepSeek is only a selector among existing candidates; its key is secret and its request lacks cooperative cancellation.

### Album synchronization

Load `AlbumSession`, physical/virtual album identity helpers, `SavePlanRequest`, `_build_album_sync_items()`, locks, checkboxes, cover state, and save tests. Single selection and multi-selection intentionally differ.

### Save/restore and partial failure

Load plan, services, worker signals, `_finish_save()`, managed snapshots, and restore completion. There is no automatic rollback. Dependency-skipped items are not currently failures. Only successful writes belong to the saved transaction.

### Undo transactions

Load both editor snapshot application and filesystem restore. Preserve strict LIFO, recording suspension, editor-command discard on save, fingerprint conflict checks, partial retry, selection/cursor restoration, and cover interning.

### Cancellation and stale results

Load worker cancel methods, Provider checkpoints, both generation counters, active/cancelled IDs, completion early returns, and cleanup. Cancellation and stale-completion rejection are separate mechanisms. Loader/save/restore do not have the same contract.

### Cover state

Load selection-derived mixed state, modified flag, exact Apple artwork reuse, CAA lookup, gallery selection, save-plan cover flags, and snapshot fingerprints. `None`, mixed, unchanged, and explicit absence are not interchangeable.

### Local file workflow/configuration

Load `file_workflow.py`, UI confirmation sites, `config.py`, and packaged path branches. Move/delete/cleanup are destructive and not undoable; settings can contain a plaintext secret.

## 4. Model task classification

### Small and suitable for a lower-cost model

- isolated UI text/style changes within one existing component;
- album-index or touch-widget boundary fix with an existing failing test;
- adding secret-safe diagnostics to one owner;
- adding a deterministic unit test for an already-understood rule;
- type annotations or documentation that do not change runtime behavior;
- a local boundary condition with an existing reproduction and one source of truth.

Even small tasks must follow the interpreter and Simplified Chinese communication rules.

### Medium and requiring architecture review

- changing one metadata field from Provider through save/read-back;
- changing `SavePlan` membership, lock, checkbox, cover, or dependency behavior;
- changing virtual/physical album synchronization;
- adding a managed metadata field;
- changing one Provider scoring/storefront rule;
- changing source-preference/cache invalidation;
- changing a worker signal or cancellation checkpoint;
- extending editor snapshots/session patches or managed restore semantics;
- moving one local workflow to a worker while preserving confirmations.

These tasks require the relevant architecture section and targeted plus broader tests.

### Large and requiring the strongest available reasoning model

- splitting or replacing major responsibilities in `main_window.py`;
- changing the source-of-truth or widget/session synchronization model;
- redesigning save execution, rollback, durable restore, or transaction semantics;
- introducing a Provider abstraction beyond the current two hard-coded sources;
- changing threading/worker ownership or enabling overlapping operations;
- replacing request-generation/cancellation architecture;
- jointly changing MB matching, Apple storefront selection, artist resolution, and cross-source scoring;
- adding a new audio format across read/write/restore/scan/move;
- broad cross-module refactoring or packaging/environment reconstruction.

Large tasks need an explicit ownership/data-flow proposal, tests, compatibility/removal plan, and updated documentation. They must not begin as opportunistic cleanup.

## 5. Required handoff packet after a large change

Leave all of the following in repository documentation, commit/PR notes, or a durable handoff file rather than conversation only:

- concise change summary;
- architectural boundaries before and after;
- changed invariants;
- affected end-to-end data flow;
- behavior intentionally preserved and compatibility behavior;
- removed old paths;
- remaining temporary paths/adapters and removal condition;
- tests added and why they cover the risk;
- exact commands and configured interpreter used;
- known failures, skipped checks, and external limitations;
- rollback point or Git commit;
- architecture/debug/handoff documentation updated.

## 6. Rules for strong models

A stronger model must not:

- over-abstract a personal desktop application;
- add patterns solely for theoretical purity;
- split a large module without a verified ownership improvement;
- move code only to reduce line count;
- leave dual old/new execution paths or undocumented adapters;
- create a second metadata/session/cache truth;
- alter behavior during a behavior-preserving refactor;
- rely on conversation-only architecture reasoning;
- weaken save, undo, cancellation, stale-ID, or secret-handling guarantees to simplify code.

A stronger model must convert reasoning into explicit code boundaries, focused tests, documented invariants, removed obsolete paths, and small reviewable commits when commits are in scope.

## 7. Rules for smaller models

A smaller model must:

- read `AGENTS.md` and the relevant `ARCHITECTURE.md` section;
- read the complete affected data flow, not only the failing file;
- identify authoritative, mirrored, cached, and derived state;
- avoid architecture changes unless the task requires one;
- add a failing deterministic reproduction before broad edits when possible;
- make the smallest root-cause fix at the owning layer;
- preserve service/plan/tagger, undo/restore, worker, cancellation, and stale-result boundaries;
- stop and escalate when ownership is unclear, multiple state systems disagree, or a behavioral contract must be chosen.

It must never patch `AudioTagger` merely to correct a Provider/UI error or patch a widget merely to hide an incorrect plan/write.

## 8. Bug-task handoff template

```text
Project goal:

Relevant architecture:

Current bug:

Exact reproduction:

Expected behavior:

Actual behavior:

Earliest known incorrect state:

Likely owning layer:

Relevant files:

Recent related changes:

Constraints:

Required tests:

Do not modify:

Unresolved uncertainty:
```

## 9. Refactor handoff template

```text
Refactor objective:

Behavior that must remain unchanged:

Current architecture:

Target architecture:

Reason the change is necessary:

Modules changed:

State ownership before:

State ownership after:

Data flow before:

Data flow after:

Compatibility path:

Temporary adapters:

Removal condition:

Tests added:

Tests run:

Known limitations:

Documentation updated:
```

## 10. Current handoff summary

Read `AGENTS.md` first, then the relevant architecture/debugging section and owning tests. Do not bypass `AlbumSession`, `SavePlan`, save/restore services, `AudioTagger`, `UndoManager`, workers, cooperative cancellation, or request-generation checks. Treat `main_window.py`, album synchronization, Provider heuristics/storefront localization, partial save/restore, async identity, and cover flags as high-context areas. Treat `config.APP_VERSION` as the sole iteration/log version, use only current/previous-version logs for active debugging, and clean older logs after current evidence exists. Address the user in Simplified Chinese unless they explicitly request another language. When unsure, trace the value to its first incorrect state and escalate rather than creating a second path or patching the final symptom.
