---
name: personal-understanding
version: 2.2.0
description: Use when the user talks about their own experiences, states, feelings, family, friends, school, or decisions; asks to remember, correct, or recall something about themselves; or asks "why am I like this?". The user's exact words are always saved first as an immutable verbatim capture, then retrieval proceeds progressively — timeline survey → entity/context probe → verbatim deep — like human recall: gist first, verification later. Works in English by default and mirrors the user's language.
---

# Personal Understanding v2.0

This is a **local, traceable, verbatim-first, timeline-driven personal cognition archive**. It stores experiences, relationships, states, and rules, and lets the model:

- recall an experience first;
- then branch outward along time, people, places, school, objects, works, games, concepts, and living environment;
- return to the user's exact words at the time;
- keep facts, feelings, user interpretations, model speculation, and open questions strictly separated;
- check whether any follow-up items are due;
- raise contradictions with evidence and context instead of out of nowhere.

The legacy `memory/records/` layout is kept as a compatibility layer. The v2 derivation trunk lives in `memory/v2/`, and immutable conversation verbatims live in `sources/conversation/`.

## Scope gate: do not archive technical work

Before invoking this skill, classify the request. If it is primarily technical — including configuration, debugging, code, model/provider setup, MCP, plugins, repositories, or project maintenance — and the answer will not materially change because of the user's experiences, preferences, values, current state, or prior decisions, skip this skill entirely. Do not run a survey, capture the message, create a derived record, or store an audit copy for that request.

Use this skill only when the request contains personal material, the user explicitly asks to remember or archive it, or personal context would materially change the recommendation, tradeoff, warning, or action order. A request to maintain this skill's boundaries is not itself personal material; update the skill rules without archiving the maintenance conversation.

Global conversation style, coding-language preferences, tool preferences, and planning/interview behavior belong in the host client's instruction file, not in this personal archive. This skill must not capture or derive those client-configuration decisions as personal facts.

## Highest priority: verbatim fidelity

**Whenever the user adds content that belongs in the Personal Understanding skill — in any form, in any scenario — the complete user message must be saved verbatim, character for character, before any summarizing, event splitting, person extraction, relationship judgment, or causal interpretation.**

The execution order is fixed:

```text
user verbatim / raw attachments
  ↓ saved first, never overwritten
verbatim fragment
  ↓
events, entities, context cards, states, follow-ups, hypotheses
  ↓
retrieval and answers
```

Mandatory:

1. Save the complete user message for text input — not just the sentences the model considers important;
2. Keep original attachments for images, audio, and files; OCR, transcription, and summaries are all derived content;
3. Every verbatim carries a `utf8_sha256`, capture time, session identifier, and source path;
4. Once a verbatim capture exists it must never be silently overwritten; corrections only add new captures and relations;
5. No model summary may ever pose as the user's verbatim; legacy records that only have summaries must be marked `summary_only`;
6. If a verbatim capture fails, report the failure — never pretend it "was saved";
7. First create a same-turn receipt with `scripts/preflight_context.py <full-message> --turn-id <turn-id>` or MCP `personal_preflight_turn`; then capture with `scripts/capture_user_update.py --turn-id <turn-id>` or MCP `personal_capture_user_turn`. A text capture's SHA256 must match the receipt's full message;
8. When writing derived records with `personal_add_record`, content the user just supplied must carry `capture_id` or `verbatim_refs`; bare `current-conversation` source attributions are forbidden.

### Derivation closure: a successful capture is not a finished update

A successful `capture` only means the raw material was not lost. It enters `pending` in `memory/derivation-ledger.json` and still must be split semantically, linked, and closed.

Before every answer, every personal-material capture from the current turn must be in one of these states:

- all necessary events, entities, states, preferences, rules, contexts, or candidate hypotheses have been created and the capture was closed with `scripts/finalize_capture.py --disposition derived` or MCP tool `personal_finalize_capture`;
- after dedup and semantic checks, there is genuinely nothing new — close with `no-derivation-needed` and a concrete reason.

Hard constraints:

1. Never claim a capture "has been recorded", "has been merged in", or end the reply while a current-turn capture is still `pending`;
2. `derived` requires at least one verifiable bidirectional capture→record link;
3. One message containing several independent events, people, date corrections, preferences, or states must be split and judged item by item — a single vague summary card does not count;
4. Standalone confirmations, corrections, and context additions may attach to the same derived record, but each capture is still finalized individually;
5. Images, audio, and files follow the same closure as text; attachments use `scripts/capture_attachment.py` to keep originals and register hashes;
6. An exact duplicate attachment may reuse the stored original, but this capture is still registered and closed with a concrete dedup reason;
7. `scripts/validate_memory.py --require-closed-captures` must block orphaned captures, untracked captures, and unfinished derivations from entering the completed state;
8. Event dates, source-material writing dates, recall dates, and the date of this ingestion must be kept apart — never pass off the ingestion day as the day something happened.

## Fact hierarchy

All content is handled at one of these levels:

1. **User verbatim facts**: first-person experiences, states, feelings, preferences, corrections, and rules the user explicitly stated;
2. **User evaluations of material**: the user saying an analysis is wrong, that someone is not a certain account, that a plan was consultation only, etc.;
3. **The user's own interpretations**: the user's explanations of causes, meaning, relationships, and the future; these stay user opinions and never auto-promote to objective fact;
4. **Model candidate interpretations**: patterns or causal hypotheses the model proposes from multiple records — these live only in the hypothesis layer;
5. **Unconfirmed content**: keep the source and the gap; never fill in from imagination.

What the user just said outranks the existing archive. Old facts are never silently erased; new content establishes `supersedes`, `contradicts`, or correction chains.

## One memory-weight axis

What an entry *is* and how much future understanding depends on it are different things — and there must not be two competing "importance" standards.

- `entry_kind`: event, state, decision, fact, etc. — what it is;
- `salience`: how much future understanding of the user depends on it, on a single 0–3 axis:
  - `3 pivotal`: changes long-term understanding, multiple domains, or life direction;
  - `2 key`: clearly changes one life thread, a current decision, or a relationship's course;
  - `1 supporting`: provides background, connections, or counterexamples;
  - `0 passing`: appears only as a name or detail.

"pivotal / key / supporting / passing" are display labels on this one scale — there is no second "core / important / background event" classification. When migrating legacy records, weights may only be marked `imported heuristic`, never disguised as user-assigned.

## The timeline spine

The timeline is the archive's first backbone — but it must not force a life into a biography.

Each timeline entry keeps, where possible:

- `date_start`, `date_end`;
- `date_precision`: day, month, year, approximate, relative order, unknown;
- `date_basis`: when it happened, when recalled, when the source was written, or model inference;
- `phase`: childhood, middle school, high school, college transition, etc.;
- `salience`: the single memory weight;
- `entity_refs`: people, schools, places, objects, works, concepts, environments;
- `before_ids`, `after_ids`;
- fidelity markers for verbatim fragments and legacy summary fragments.

Never record the record-creation date as the event date. If a date is uncertain, write uncertain — never invent dates to make the timeline look tidy.

### How the overview is summarized

The overview uses an **events-first, experience-follows, current-state-overlaid** structure:

1. **Life trunk**: show the pivotal/key events that changed life threads first — never summarize the user in one grand narrative;
2. **Event expansion**: each event can expand into "what happened, how the user felt, how the user explained it, what impact it had";
3. **Current state**: a separate overlay of the current core, real circumstances, feeling load, decisions under tension, and the next checkpoint;
4. **Evidence entries**: every judgment links back to entities, context cards, events, and verbatims.

So this is neither "examples-first" nor "feelings-first": the timeline uses events as the skeleton, feelings and meaning are the expansion layer of events, and current state adds a short, information-dense snapshot on top.

## Entity profiles: no person is an island

Any object the user explicitly refers to and that plays some role in the current content can get a lightweight entity profile — neither skipped because it is a passerby nor padded with invented biography because material is thin.

Entity types are not limited to people:

- `person`: people, relatives, friends, classmates;
- `group`: class, team, community;
- `school_or_organization`: schools, universities, institutions;
- `place`: cities, homes, courts, workplaces;
- `object`: computers, headphones, football boots, equipment;
- `book_or_work`: books, novels, works, articles;
- `game_or_media`: games, videos, music, account content;
- `concept`: concepts, values, ideals, systems;
- `environment`: family environment, school atmosphere, living conditions, institutional environment.

### Handling vague pronouns

A "bare vague pronoun" means:

- the user only said "he/she/that person";
- neither the current message nor readable context can identify who;
- and there is not enough information for a stable name or role.

In that case, do not invent a fake person and do not write "unconfirmed entity" junk nodes the model cannot use: hang that verbatim on the event's `unresolved_referent`, keep the original text, and fold it into the formal profile once the user later clarifies who it is.

Whenever identity IS clear from context, create a short profile even from a single sentence. A passerby profile with a few sentences is not waste.

### Profile content and redundancy

Entity profiles never hand-copy a duplicate biography. Instead:

- **Facts live in exactly one place**: verbatims and events are the canonical source;
- **Entity pages are projections**: they display all related stories and verbatim entry points;
- **Context cards are cross entries**: they show an entity's shared stories within a specific relationship/place/phase;
- **Cross connections are never deleted**: a person's profile must keep its links to other people, schools, places, and environments;
- `identity_note`, time spans, etc. are retrieval metadata that stay out of the profile body unless they affect understanding.

A person's profile may talk about the people around them, because social relations are part of who that person is. Connections stay; the same fact returns to the same canonical fragment through links and context cards.

## Context cards: solving the "school × football" problem

Beyond entity profiles there are `facet` / `context cards`:

```text
school entity
football entity
school × football context card
```

The school profile jumps to this card, the football profile jumps to the same card. The card holds their shared events, people, places, objects, and verbatim entry points — never a fabricated "school football story" copy.

Context card boundaries form around shared stories:

- co-occurring in the same event;
- an explicit relation or spatial connection;
- a shared user experience or decision;
- helping explain the current question.

Coincidental co-occurrence is never auto-written as causation — but cross-domain cards are not deleted either. Relevance is decided by events, time, entities, and user experience together.

## Current state

Current state is never a vague one-liner and never a full biography. Default five blocks:

1. **Personal core**: values, boundaries, and decision tendencies still in effect;
2. **Real circumstances**: life facts and resources currently in play;
3. **Experience load**: emotions, energy, bodily feelings, and stress the user actually expressed;
4. **Open tensions**: unresolved decisions, conflicts, counterexamples, uncertainties;
5. **Next checkpoint**: follow-ups, deadlines, places needing new evidence.

Each block gets 1–3 high-density entries with expandable key examples and verbatims — never core-only, never everything crammed onto the front page.

## Follow-ups and proactive check-ins

Questions the model raised, the user's "let's see in a few days", the other side not having replied, pending decisions, items to confirm — all must enter `memory/v2/followups.jsonl` with at least:

- the original question or pending item;
- concrete context;
- creation date;
- `due_at` or an explicit `due_rule`;
- current status;
- source;
- last-checked time;
- resolution or follow-up record.

Every time the skill runs, first check follow-ups that are due or near due (default 3-day window). When due, ask proactively — but always with context:

```text
On <date> you mentioned: …
At the time we expected: …
It's check-in time now.
How did it turn out?
```

If the current message contradicts the archive, list both conflicting facts, dates, sources, and the delta before asking — never pop a context-free question.

## Guided starters: when the user doesn't know what to tell

Some users freeze in front of an empty archive. When the user asks what to share ("what should I tell you?"), seems unsure how to begin, or the archive is freshly initialized, run `python scripts/conversation_starters.py` (JSON output) and pick **one** starter — ranked by due follow-ups first, then the emptiest domain — and ask it warmly, in your own words.

- Never dump the whole list as an interrogation; offer one prompt, let them answer, and capture the verbatim like any other turn;
- suggestions must come from the archive's real gaps (an empty domain, an open loop, a stale current state) — never invented psychology;
- after they answer, resume the normal flow: capture → derive → answer.

## Hard gate before answering (cannot be skipped)

Whenever the current user message contains personal experience, state, feelings, self-evaluation, relationships, decisions, corrections, long-term preferences, or asks "why am I like this", the **complete current user message** must be saved as a new immutable capture — successfully — before any survey, probe, deep read, derived record, causal analysis, or answer. A previous turn's capture, an old summary, `current-conversation`, or model memory is never a substitute.

The execution order is fixed:

```text
content-first preflight receipt → capture bound to receipt (read-back verified)
→ survey/probe/deep → derived records/hypotheses → finalize
→ session_check --turn-id → answer / claim update
```

The receipt is an auditable fact, not an advisory prompt: when `requires_personal_understanding=true`, capture, finalization, and `session_check --turn-id` are all mandatory and fail closed. If capture fails, stop all personal-understanding analysis and report the failure explicitly; never answer first and backfill later. If capture succeeds but no derived record exists yet, the answer must clearly distinguish "verbatim saved" from "not yet written into experience/state cards" — never present a raw capture as a fully updated archive.

This gate applies to messages that explicitly mention the personal archive, the skill, memory, verbatims, or "remember" — and equally to personal experiences, states, feelings, relationships, preferences, or decisions supplied through a rewrite, edit, translation, summary, or image-review request. Task form never overrides personal material. Pure technical work, configuration, debugging, project maintenance, and maintenance of this skill's rules do not create receipts, captures, or derived records.

### The low-signal fast path

Low-information messages which are also content-classified as personal (for example, "kind of lost" or "hard to say") are bound by two contracts at once: answers must feel natural (see the low-signal response contract), yet the gate still demands capture. A bare "ugh" does not enter the archive by itself. To keep chat from turning into a retrieval ceremony, low-signal personal turns run in this order:

1. **Capture immediately, no deferral** — verbatim fidelity has no exceptions;
2. **Reads degrade**: skip the full survey; pick the single most likely entry from the due follow-ups and current-state snapshot in the preflight output; at most one small probe if truly necessary;
3. **Answer first**: open like a familiar person would (one or two details, then stop), with tool calls capped at capture + at most one light read;
4. **Close the loop after answering**: finalize (derive or `no-derivation-needed`) within the same turn and run session_check; if the user follows up with substantive content, escalate to the full flow.

The fast path relaxes the timing of reads and derivation — never the verbatim capture or the closure itself.

### Read entry points and MCP

Prefer the MCP tools (`personal_catalog`, `personal_retrieve`, `personal_session_check`, …) for reads and writes; they carry read-preflight capture validation. If no `personal_*` tools exist in the current session, this client has not registered the local MCP service: run `python scripts/install_mcp.py --auto` (idempotent, safe to repeat), then ask the user to restart the session; until registered, the CLI scripts perform the same work.

## Retrieval: never read everything

v2 retrieval is neither "stuff the whole archive into the model" nor keyword search. It is three layers of divergence:

### survey: the global map

Read the compact catalog only — never full verbatims:

- timeline spine;
- current state;
- entity catalog;
- context card catalog;
- follow-ups;
- hypothesis catalog;
- material gaps and review warnings.

survey is a compact routing map without the full legacy record list; use `catalog_context.py --view routing --query <message>` to expand legacy catalogs per domain, or `--view full` for the complete catalog.

### probe: diverge from entries

The model picks one or more entries:

- events;
- entities;
- context cards;
- current state;
- follow-ups;
- candidate hypotheses.

Then read those derived cards and expand:

- time neighbors before/after an event;
- the event's people, places, schools, objects, works, concepts, environments;
- context cards where those entities co-occur;
- supports / contradicts / alternatives / supersedes relations.

Expansion reads only the necessary range while keeping small details reachable via cards, reducing missed recall for minor figures. Every timeline entry in probe output carries an `evidence_fidelity` count (how much verbatim vs. summary debt backs it); claims resting on summary debt must be disclosed to the user as "this part comes from an old summary, not verbatim". Each retrieval's decision trace appends to `memory/v2/traces/` — replay it when recall misses or mis-attribution happens.

### deep: verify against verbatim

Only when the answer needs exact facts, dates, attribution, contradictions, relationships, the user's original meaning, or causal explanation do we read the corresponding verbatim fragments. Legacy summaries remain summary debt — they never pose as original text in the deep stage.

### Cold recall: when there is no keyword

When the user says "I forget" or "we talked about something like this before", do not demand keywords and do not declare "nothing found". Descend the ladder:

1. probe from any person, place, object, or time clue already mentioned; diverge along entities and facets;
2. on any hit, walk `before_ids`/`after_ids` time neighbors forward and backward;
3. still nothing: browse titles in a time window with `retrieve_v2.py --window 2025-03` (or `start:end`), like flipping through an old photo album, and let the user claim candidates;
4. if even time is vague, scan pivotal entries phase by phase (childhood / middle school / high school / college).

Demoted passing-level records stay reachable on all three paths — entity, keyword, and time window. Demotion only removes them from the standing map; it never makes them unreachable.

## The causal interpretation layer

Causal interpretation is its own large undertaking — it never runs wild inside ordinary fact retrieval. A candidate hypothesis carries at least:

- `claim`: what it explains;
- `mechanism`: through what process;
- `supports`: supporting evidence;
- `contradicts`: counterexamples and limits;
- `alternatives`: competing explanations;
- `scope`: in which times, scenes, and relationships it holds;
- `confidence`: confidence level;
- `status: candidate`: candidate by default — never treated as fact.

Trigger conditions:

1. the user explicitly asks "why am I like this";
2. multiple independent experiences repeat the same condition–response–adaptation chain across time;
3. a deep review finds multiple model-dependent stories;
4. a current decision genuinely requires comparing causes.

Generation steps:

```text
candidate pattern → mechanism sketch → supporting evidence → counterexamples/limits → competing explanations → user confirms / keep observing
```

A single event never yields a stable cause. Causal hypotheses enter deep reads only when the current question needs explanation; ordinary fact questions never auto-load them.

## Privacy boundaries

The archive owner has explicitly allowed the local skill to read private / highly-private content when relevant. Sensitivity is not a reason to hide, demote, or archive.

But relevance filtering stays:

- when personal material would change the answer, sensitive content is read by relevance;
- irrelevant questions never proactively leak unrelated private material;
- verbatims, profiles, and sources are processed only inside the local skill directory;
- external chats, third-party analyses, OCR, and model analyses still never auto-count as user fact.

Relaxing privacy reading is not abolishing boundaries — otherwise you are not understanding the user better, you are dumping the archive into every answer.

## Deep review and structural validation

Structural validation no longer just prints "pass". `scripts/validate_memory.py` has three outcomes:

- `clean`: no errors, no warnings;
- `warnings`: structurally usable, but there is summary debt, source gaps, date gaps, pending follow-ups, or entity connection issues;
- `failed`: hash errors, duplicate IDs, orphaned references, relation cycles, corrupt JSONL, or unacceptable schema errors.

Strict mode `--strict` treats warnings as failures too — for migration acceptance.

`review_v2.py --deep --json` produces a semantic review package checking:

- verbatim/event consistency;
- correct attribution of people/schools/places/objects;
- shared stories wrongly deleted;
- timeline order vs. "looking back later" confusion;
- facts, feelings, user interpretations, and model hypotheses mixed into one layer;
- legacy summaries posing as verbatim;
- causal hypotheses missing supports, counterexamples, or scope;
- follow-ups due or resolved.

Deep review may output warnings and material gaps, but never invents lost verbatims back into existence. Structural cleanliness is not semantic correctness; review must come with a risk report.

## Maintenance entry points

- `scripts/capture_user_update.py`: save the complete user verbatim first (for very long messages prefer `--stdin` or `--file` to dodge command-line length limits);
- `scripts/preflight_context.py` and `scripts/turn_receipts.py`: create, read, and audit immutable turn receipts;
- `scripts/capture_attachment.py`: store or SHA256-deduplicate raw attachments and register pending captures;
- `scripts/derivation_ledger.py`: maintain capture→records state and link audits; `--repair` rebuilds the projection from immutable capture metadata and record references;
- `scripts/finalize_capture.py`: complete a derivation or record the concrete "nothing to derive" reason;
- `scripts/catalog_context.py`: v2 global survey;
- `scripts/retrieve_v2.py`: v2 probe/deep;
- `scripts/followup_check.py`: follow-up checks;
- `scripts/review_v2.py --deep`: deep structure/fidelity/semantic review package;
- `scripts/validate_memory.py`: failed/warnings/clean three-state validation;
- `scripts/session_check.py --turn-id <turn-id>`: the hard gate before answering or claiming "the archive is updated" (receipt + structure + derivation closure + v2 integrity; non-zero exit on failure);
- `scripts/salience_review.py`: quarterly salience review, demoting long-unconfirmed imported weights to passing level (see `references/review-and-feedback-loops.md`);
- `scripts/record_feedback.py`: record how answers that relied on memory landed (helpful/missed/corrected); `review_v2 --deep` aggregates frequently corrected memories (see `references/review-and-feedback-loops.md`);
- `scripts/rebuild_views.py`: rebuild legacy compatibility views and v2 derived views;
- `scripts/backup_archive.py`: SHA256-manifested local backups, auto-mirrored to a second location from `memory/backup-config.json` (see `references/maintenance-and-durability.md`; after important updates, before migrations, and at least weekly);
- `scripts/init_archive.py`: bootstrap a fresh archive skeleton (directories + generic domain branches) on a brand-new install; idempotent, run once before first use;
- `scripts/install_mcp.py`: detect AI clients on this machine and register the local MCP service (idempotent; run once after changing machines or pasting the skill into a new client);
- `scripts/mcp_server.py`: local MCP read/write entry;
- `dashboard/`: the v2 visual audit panel.

### Maintenance principles

- Finish the current task first, then non-urgent maintenance;
- but user corrections, failed verbatim captures, misattributed people, structural corruption, due follow-ups, and imminent decisions are handled immediately;
- the `maintenance` hints in preflight / session_check output are the only maintenance state to watch: when backups are overdue (`backup.due: true`), run `scripts/backup_archive.py` after the current task and before ending the session; when an answer that relied on memory drew an explicit correction/confirmation, record feedback per `references/review-and-feedback-loops.md` (never record without quotable verbatim evidence);
- permanent deletion only on the archive owner's explicit instruction;
- legacy summaries are never deleted — marked as migration debt;
- new profiles never overwrite old ones — version chains;
- all writers (CLI, MCP, ledger, and rebuilds) share an inter-process lock and commit through atomic replacement; every write fresh-reads, merges, and commits inside the lock. Never overwrite another Agent/MCP writer from a stale JSON/JSONL snapshot;
- never promote one self-assessment into a personality verdict;
- never fabricate causal edges, merge people, or fill timeline gaps to make the graph prettier.

## Visualization audit contract

The panel exists so the owner can check whether the skill follows its own rules. The front page offers status and count entries only; details live in the timeline, entity, context, source, follow-up, and diagnostics pages.

The diagnostics page must show:

- real file entries for `SKILL.md`, references, scripts, and memory/v2;
- actual counts of verbatim captures, fragments, timeline entries, entities, context cards, and retrieval levels;
- machine validation results (`clean`, `warnings`, `failed`);
- legacy summary debt, date gaps, entity merges, unresolved relations, and candidate hypothesis gaps;
- the complete chain from an event to entities, contexts, knowledge cards, time neighbors, and verbatim sources.

Every list click uses its own ID. Never bind multiple entries to one default target. Entity redirects must show old ID, canonical ID, and merge source.
