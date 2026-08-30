# 2026-08-19: restore visibility, separate source material from current understanding

## Reason

The archive owner confirmed that `private` / `highly-private` are not hiding conditions: the local skill directory is under the owner's own control, so privacy records should stay visible and readable by relevance. The owner also pointed out that chat logs with an external AI assistant are source material and must not be marked `archived` merely because of the nature of their source.

## Changes

- Restored the 17 formerly `archived` records to `current`.
- Privacy and relationship records marked `record_role: personal_memory`.
- `source.note.*` records corresponding to external AI discussions marked `record_role: source_material`.
- Raw sources, record bodies, and historical relations were preserved; nothing was deleted.
- The dashboard presents "source material" and "confirmed personal facts" separately, but both remain visible and traceable.

## Boundary

AI analysis contained in source material still cannot automatically count as a fact about the owner; this is a source-tier distinction, not hiding. Records genuinely replaced by newer facts keep `superseded`, and the UI shows their replacement.
