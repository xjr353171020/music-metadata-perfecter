# Represent filename clue drafts in editor state

An accepted filename clue draft populates the existing editor fields as an undoable pending edit instead of creating a second metadata store or a parallel set of search fields. The UI must continue to identify those values as unverified filename-derived clues, and accepting the draft must not automatically start Provider search or save the file; the user retains both actions explicitly.

Applying one filename clue draft is one atomic editor command even when it fills several fields. Undo restores every affected field and the draft-source presentation together; redo reapplies the already validated draft without calling DeepSeek again.

Filename analysis may fill an eligible empty editor field even when that field's save checkbox is clear, because the draft can still be used for review and Provider search. It must preserve every checkbox state: checkboxes express the user's save intent, which clue extraction is not authorized to change.

The compact `DeepSeek解析` or `本地规则解析` indicator is visible only while the filename clue draft's title, artist, album, track, and disc values remain untouched by the user. Typing, choosing another value, or applying Provider data to any of those fields transitions the state to an ordinary editor draft and hides the indicator; undoing that change restores both the filename clue draft and its indicator.

After saving, the indicator clears only when every remaining extracted value was written successfully and read back as loaded metadata. It remains visible when the target write fails or when an unchecked extracted field still differs from loaded metadata.

The explicit `从文件名提取线索` action appears in a compact row between the cover area and metadata fields, separate from Provider search controls. A successful action shows `DeepSeek解析` or `本地规则解析`; a completed action with no applicable clue shows the non-modal amber text `未从文件名提取到可填线索` and creates no undo command.

Provider search consumes the current editor draft, including unsaved title, first artist, album, track, and disc edits. Provider candidate coloring compares against that same editor draft rather than loaded metadata.

Each metadata field reserves a fixed position for a non-interactive amber dot. The dot indicates that saving the currently checked editor value would change loaded metadata; in a multi-selection it lights when at least one selected track would change, while `<保留>` never lights it. Hovering shows the loaded value, or `多个不同值` for a mixed selection. Continuous field borders are not used for this state because they conflict with lock, hover, and candidate-comparison styling.
