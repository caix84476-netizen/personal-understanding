# Changelog

All notable changes to Personal Understanding are documented here.
The project is developed as a working, daily-driven archive — many entries below
were motivated by real incidents found during use, which is exactly why the
hardening exists.

## 2.2.0 — 2026-09-01 — main branch hardening

> First release published to [PyPI](https://pypi.org/project/personal-understanding/) as `personal-understanding`.

- Added content-first, immutable turn receipts so personal material cannot be skipped just because it is framed as rewriting, translation, summarization, or image review.
- Bound capture, finalization, and `session_check --turn-id` to the receipt hash and made incomplete personal turns fail closed.
- Added a shared inter-process mutation lock, atomic writes, ledger journal/repair, and locked MCP record/follow-up/hypothesis writers to prevent lost updates between Agents and MCP processes.

## 2.1.0 — 2026-08-29 (three review-and-repair rounds: correctness, product polish, loop closure)

### Correctness fixes (P0)

- **Fixed a data-corruption defect in `salience_review.apply_decay`**: line numbers returned by `_frontmatter_span` were treated as character offsets for `text[:end]` slicing, so `--apply` could write `salience: 0` into the middle of an id line and shred frontmatter (on a scratch copy, 54 records had ids truncated and validation went straight to `failed`). Closing `---` is now inserted line-wise with CRLF handled. Found the first time the decay feature was exercised against real data — the lesson: rehearse on real-shaped data before shipping.
- Unified "follow-up is due" semantics: new shared helpers `v2_archive.followup_is_due / followup_open / followup_due_day` (dates truncated to day, unified status sets) replace four divergent implementations across v2_audit, build_current_state, review_v2, and retrieve_v2.
- Fixed `followup_check.py` CLI `--horizon` defaulting to 0 and overriding the library default of 3: the "due soon" reminder window works again.
- `load_v2` / `v2_audit` now tolerate a corrupt manifest / current-state file: corruption is reported as a structured error (`manifest-corrupt`, …) instead of crashing the whole preflight / validate / retrieval chain.
- Atomic writes everywhere: `jsonl_write`, pages rebuilds, current-state / index / manifest, MCP capture meta, add_followup / add_hypothesis all write tmp-then-rename; pages rebuild writes first and cleans later to avoid half-written states.
- `build_followups` turned from a one-shot seed import into an idempotent merge: new open loops keep flowing in, and hand-edited statuses inside the JSONL are no longer clobbered.
- Removed dead code (`query_memory.py`, `transition_record.py`, `build_catalog.py`); removed a stale hardcoded historical path from `review_skill.py`; cleaned leftover `.tmp` probes.
- MCP fixes: capture meta now records `codepoint_length` and writes atomically; unknown methods return JSON-RPC `-32601`; exception handling no longer relies on `locals()`; `finalize_capture` only validates instead of triggering needless full rebuilds; subprocess timeout raised 60s → 120s.
- `review_skill.py` thresholds unified with preflight (8); preflight no longer inlines a full deep review on its lightest step — it schedules one instead.

### Product polish (P1)

- SKILL.md description rewritten to be trigger-scenario oriented, improving auto-trigger hit rate;
- **Low-signal fast path** added: on low-information turns, capture fires immediately, reads degrade, the answer comes first, and finalization completes within the same turn — resolving the tension between the "natural conversation" contract and gate ceremony;
- survey spine buckets representative entries by life phase (childhood / middle school / high school / university …), fixing recency bias from "keep only the latest 60" so early pivotal events return to the resident map;
- survey takes the light path: no more building an ~879 KB legacy catalog just for survey (measured ~3109 ms → ~230 ms);
- probe output now carries an `evidence_fidelity` count per timeline entry (verbatim vs summary debt), making "is this from the exact words or an old summary?" visible at probe level.

### Loop closure (P2)

- Retrieval decision traces persisted: `retrieve_v2.py` appends every run's trace to `memory/v2/traces/trace-YYYYMM.jsonl` (`--capture-id` links the current turn, `--no-trace` disables) — decision traces became machine facts, not documentation wishes;
- **Backup model redesigned**: working archive as the living preview; archived snapshots (two fixed files: stable + previous, always one version behind) as rollback points; a new snapshot is cut only when more than 7 days have passed **and** structural validation passes ("behaves fine" is the criterion, not "nothing changed"). Optional cloud mirror pushes snapshots on demand to any rclone remote (a WebDAV cloud drive works; no resident background process, a few files per push, friendly to rate-limited free tiers — a 503 is a temporary throttle that recovers by itself); USB auto-mirror off by default; preflight / session_check surface snapshot age and nudge when overdue;
- `session_check` output adds feedback reminders and pending-capture age details (leftover pending captures are no longer a black box);
- references consolidated from 26 files into 14 (activation merged into retrieval policy, open loops into the timeline policy, people into entities, source catalog into capture policy, interaction + low-signal + proactive cues together, conflict + correction together, review + feedback together, maintenance + durability together);
- **New `scripts/install_mcp.py`**: detects local AI clients and registers the local MCP server (idempotent; no-op when paths already match). Covers Claude desktop builds, Codex, VS Code / Insiders, Cursor, Windsurf, Cline, Trae, ZCode and generic `.agents` layouts; `--export-dir` emits a universal `mcpServers` snippet with paste instructions for any future MCP-standard client;
- New root-level `register-mcp.cmd` (double-click registration) and a user README (daily use, moving machines, backups, health checks).

### Maintenance

- VERSION / SKILL.md / validate_memory version strings synced to 2.1.0; the v2 archive schema is unchanged (manifest `version` stays 2.0.0 with a separate `skill_version`), so no data migration is needed.

## 2.0.0 — runtime hardening round (2026-08-28; schema unchanged)

No data-architecture changes, only runtime defects fixed:

- survey became a compact routing map: only the v2 timeline spine, entity catalog, shared-story facets, model/value knowledge cards, current state, and follow-ups; the full legacy list moved to `routing`/`full` views. Size dropped from ~818 KB to ~90 KB per turn;
- fixed a double-escaping regex in `update_state.py` supersede handling: after `--apply`, superseded state records are now actually marked;
- fixed open-loops.md legend lines being imported as follow-up questions; `parse_open_loops` accepts only structured `- id:` entries and skips answered/declined loops;
- follow-up "due" checks now filter by date — future due dates no longer trigger early; `check_followups` default horizon set to 3 days so "due soon" reminders actually fire;
- fixed literal `\n` leaks in `validate_memory.py` and `retrieve_v2.py` output;
- the `next checkpoints` block of current state is now populated from due/undated follow-ups instead of staying empty;
- v2 builds support `date_end` and explicit `entity_refs` in record frontmatter; entity redirects merge old aliases to avoid post-merge recall loss;
- `rebuild_views.py` clears stale pages before rebuilding (no more ghost pages);
- `preflight_context.py` budget trimming drops items one by one until under budget;
- `capture_user_update.py` gained `--stdin` so very long verbatim messages no longer hit Windows command-line length limits;
- `update_state.py` confidence enum unified with the rest of the archive (six levels);
- **New `scripts/backup_archive.py` + backup policy**: the archive previously had "never delete" protection but no disaster tolerance — and a real data-loss incident had already been recorded inside it. Now there are append-only, verifiable local backups with SHA-256 manifests.

Three structural additions (2026-08-28 review round):

- **Salience review**: `scripts/salience_review.py` + policy. The archive only grows, so imported heuristic weights drift over time; quarterly, event/fact/entity weights unconfirmed for 180+ days decay to `salience: 0` (passing level — still retrievable, never deleted).
- **The hard gate**: `scripts/session_check.py` + MCP `personal_session_check`. One command with a hard exit code fusing structural validation + derivation closure + v2 integrity; claiming "the archive is updated" requires passing it. `update_state.py` now rejects state writes whose source record does not exist.
- **The feedback loop**: `scripts/record_feedback.py` + MCP `personal_add_feedback` + policy. After any answer that relied on memory, record how it landed (helpful / missed / corrected) and which memories were used; `review_v2 --deep` aggregates frequently corrected memories and prioritizes them for review. The user's natural reaction is the rating — no formal scoring required.

Cold recall and feedback tightening (driven by review):

- after the "cold memory dead zone" risk was raised, SKILL.md gained the **cold recall ladder**: with no keywords, probe from any entity hint → walk time neighbors → browse titles in a time window via `retrieve_v2.py --window`; demoted entries stay reachable on all three paths;
- `retrieve_v2.py` gained `--window` (`2025-03` or `2025-03:2025-08`): everything inside the window returns regardless of keyword hits;
- feedback policy rewritten to "default is not to record": silence, topic changes, and short replies produce no feedback; only explicit corrections, explicit misses, and evidenced confirmations may be written, and `note` must quote the user's words as evidence. `corrected` is the only signal that drives review priority — guarding against the model grading its own homework.

## 2.0.0 — 2026-08-22 (the architecture leap)

A full architectural jump, not a timeline reskin:

- Immutable user verbatim capture chain: save the complete original words first, derive everything else after;
- New `memory/v2/`: fragments, timeline, entities, contexts/facets, followups, hypotheses, relations, current-state, and indexes;
- One 0–3 `salience` memory-weight axis across the timeline, eliminating the double core/important/background taxonomy;
- Entity profiles extended beyond people: schools, places, objects, works, games, concepts, living environments;
- Cross-entity context cards ("school × football") reachable from either side;
- Follow-up scheduling with due-date proactive questions;
- Candidate causal hypothesis layer requiring mechanism, supports, limits, alternatives, and scope;
- `validate_memory.py` upgraded to clean / warnings / failed three-state validation, with `--strict` for migration acceptance;
- `review_v2.py --deep` reporting missing verbatim, summary debt, date gaps, orphaned entities, and pending follow-ups as review risks;
- MCP write entries gained verbatim capture, follow-ups, and candidate hypotheses — and reject bare `current-conversation` writes;
- Retrieval re-centered on the v2 spine: survey → event/entity/facet probe → verbatim deep read;
- Dashboard rebuilt around overview, timeline, entities, context cards, hypotheses, follow-ups, sources, and files;
- Legacy records, sources, and indexes kept; legacy summaries honestly marked `summary_only` — lost originals are never fabricated back into existence.

## 0.6.0 and earlier

Early-history notes live in the migration backups and file history. Runtime rules are governed by 2.0.0 and later.
