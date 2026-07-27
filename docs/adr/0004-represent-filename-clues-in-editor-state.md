# Represent filename clue drafts in editor state

An accepted filename clue draft populates the existing editor fields as an undoable pending edit instead of creating a second metadata store or a parallel set of search fields. The UI must continue to identify those values as unverified filename-derived clues, and accepting the draft must not automatically start Provider search or save the file; the user retains both actions explicitly.
