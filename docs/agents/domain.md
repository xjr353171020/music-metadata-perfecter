# Domain Docs

How the engineering skills consume this repository's domain documentation.

## Before exploring, read these

- `CONTEXT.md` at the repository root
- `CONTEXT-MAP.md`, if present, and each context relevant to the task
- Applicable ADRs under `docs/adr/`

If these files do not exist, proceed silently. The `domain-modeling` skill creates them lazily when terminology or decisions are actually resolved.

## Layout

This is a single-context repository:

```text
/
├── CONTEXT.md
└── docs/
    └── adr/
```

## Use the glossary's vocabulary

Use canonical terms defined in `CONTEXT.md` in issue titles, proposals, hypotheses, and test names. Avoid synonyms that the glossary explicitly rejects.

If a needed concept is absent, reconsider whether it belongs to the domain language or note the gap for `domain-modeling`.

## Flag ADR conflicts

Explicitly surface proposed work that contradicts an existing ADR instead of silently overriding it.
