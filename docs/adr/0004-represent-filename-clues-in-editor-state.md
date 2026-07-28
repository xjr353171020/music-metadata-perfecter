# Represent filename clue drafts in editor state

An accepted filename clue draft populates the existing editor fields as an undoable pending edit instead of creating a second metadata store or a parallel set of search fields. The UI must continue to identify those values as unverified filename-derived clues, and accepting the draft must not automatically start Provider search or save the file; the user retains both actions explicitly.

Applying one filename clue draft is one atomic editor command even when it fills several fields. Undo restores every affected field and the draft-source presentation together; redo reapplies the already validated draft without calling DeepSeek again.

Filename analysis may fill an eligible empty editor field even when that field's save checkbox is clear, because the draft can still be used for review and Provider search. It must preserve every checkbox state: checkboxes express the user's save intent, which clue extraction is not authorized to change.

The compact `DeepSeek解析` or `本地规则解析` indicator is visible only while the filename clue draft's title, artist, album, track, and disc values remain untouched by the user. Typing, choosing another value, or applying Provider data to any of those fields transitions the state to an ordinary editor draft and hides the indicator; undoing that change restores both the filename clue draft and its indicator.
