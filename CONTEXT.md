# Music Metadata Repair

This context covers user-guided repair and completion of embedded metadata for local audio tracks that have at least one usable identity clue.

## Language

**Identity clue**:
Information sufficient to search for or disambiguate a track's identity, whether already embedded or supplied by the user.
_Avoid_: Metadata, hint

**Untagged track**:
A local audio track with none of the managed metadata fields populated. It can still have an identity clue outside its embedded tags.
_Avoid_: Unknown track, unidentified track

**Unidentified track**:
A local audio track with no reliable identity clue available from embedded data, its filename, or user knowledge.
_Avoid_: Untagged track

**Metadata repair**:
The user-guided correction or completion of embedded track metadata using identity clues and candidate metadata.
_Avoid_: Automatic identification, blind tagging

**Candidate metadata**:
A proposed set of values from an external reference source that is not authoritative until the user accepts it.
_Avoid_: Source of truth, detected metadata
