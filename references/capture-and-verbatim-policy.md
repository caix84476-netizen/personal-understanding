# Verbatim Capture and Source Catalog Policy

## Mandatory order

Whenever the user adds personal context, corrects the archive, recounts experiences, describes people, states preferences, describes their current state, or changes collaboration rules:

1. First call `capture_user_update.py` or MCP `personal_capture_user_turn`;
2. Write the full user message;
3. Read back and verify UTF-8 bytes and SHA-256;
4. Only then generate derived events, entities, contexts, states, follow-ups, and hypotheses.

## fidelity

Levels the archive actually emits today (2.5.0 — reconciled with `v2_archive.py`; the earlier draft listed five levels but only three are ever produced, and one of those three, `exact_attachment`, was undocumented):

- `verbatim`: original user text, captured byte-for-byte and hashed;
- `exact_attachment`: an attachment stored exactly as received (the prior draft folded this into "verbatim");
- `summary_only`: legacy derived summary, cannot count as verbatim.

Reserved for future capture kinds — NOT emitted by any current script, so no code path or filter may assume they exist:

- `transcription`: audio/video transcription, the attachment must be retained;
- `ocr`: text recognized from images, the image must be retained;
- `external_material`: external/third-party material, used only as source evidence.

Every summary must retain the `summary_only` marker or another derived marker. Approximate content agreement must never substitute for verbatim fidelity.

## Recovery boundary

During migration you may scan existing `sources/markdown`, `sources/external`, `sources/ocr`, and image associations, but only sources that can actually be read back may be recovered. Content of which only legacy summaries remain is registered as migration debt; original sentences must never be fabricated in reverse from them.

## Source catalog (formerly source-catalog-policy)

The source catalog covers raw chats, session captures, text, images, OCR, audio/video, and external material. Source cards serve routing only and never replace the original text.

- User verbatim captures: `verbatim`, immutable;
- Images/OCR: the original image takes priority; OCR results must be checked;
- External conversations: distinguish user statements, third-party opinions, and model analysis;
- Legacy derived records: `summary_only`; they are migration debt, not verbatim.

Every source reference must be readable back, or must explicitly state that it cannot be. Dead sources must raise a warning; an empty path must never pretend to be traceable.
