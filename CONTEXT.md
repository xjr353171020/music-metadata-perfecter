# Music Metadata Repair

This context covers user-guided repair and completion of embedded metadata for local audio tracks that have at least one usable identity clue.

## Language

**Identity clue**:
Information sufficient to search for or disambiguate a track's identity, whether already embedded or supplied by the user.
_Avoid_: Metadata, hint

**Filename clue draft**:
An unverified, structured interpretation of identity clues present in a filename. It may separate or rearrange filename evidence but adds no absent facts and remains weaker evidence than non-empty loaded metadata. Once the user changes any title, artist, album, track, or disc value after extraction, the result becomes an ordinary editor draft rather than a filename clue draft. It also ceases to be a draft after all remaining extracted values are successfully saved and read back as loaded metadata.
_Avoid_: Candidate metadata, generated metadata, identified track

**Untagged track**:
A local audio track with none of the managed metadata fields populated. It can still have an identity clue outside its embedded tags.
_Avoid_: Unknown track, unidentified track

**Unidentified track**:
A local audio track with no reliable identity clue available from embedded data, its filename, or user knowledge.
_Avoid_: Untagged track

**Metadata repair**:
The user-guided correction or completion of embedded track metadata using identity clues and candidate metadata.
_Avoid_: Automatic identification, blind tagging

**Loaded metadata**:
The embedded metadata most recently read from a local track. It is the persisted baseline against which unsaved edits can be distinguished.
_Avoid_: Original information, editor draft

**Editor draft**:
The current mutable metadata values presented for review, search, and eventual saving. It can differ from loaded metadata and is not persisted until the user saves it.
_Avoid_: Original information, loaded metadata

**Candidate metadata**:
A proposed set of values from an external reference source that is not authoritative until the user accepts it.
_Avoid_: Source of truth, detected metadata
