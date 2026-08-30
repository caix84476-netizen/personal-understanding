# v2 Architecture: memory spine + entity network + context projections

## canonical layers

```text
raw attachments / user verbatim (immutable)
        ↓
fragment: verbatim fragments, legacy summary fragments, source anchors
        ↓
entry: timeline entries (events / states / decisions)
        ↓
entity: people, schools, places, objects, works, games, concepts, environments
        ↓
facet: cross-entity context cards (e.g., school × football)
        ↓
current state / follow-up / causal hypothesis
```

Each fact is stored exactly once; entity pages and context cards are projections, not duplicated writing. Legacy `memory/records/*.md` remains a compatible source of facts; v2 derived structures live under `memory/v2/`.

Backward-compatibility note (formerly architecture-v0.2): the legacy `parent_ids`, `related_ids`, `supports`, `contradicts`, and `supersedes` fields remain readable but are no longer the full memory structure. They are migrated into v2's `relations.jsonl` and participate in routing through timeline entries, entity profiles, and context cards.

## v2 files

- `fragments.jsonl`: immutable verbatim and migrated summary fragments; each carries a hash and a fidelity level;
- `timeline.jsonl`: timeline entries on a single unified salience axis;
- `entities.jsonl`: entity catalog with references to stories / fragments / contexts;
- `contexts.jsonl`: entity contexts and cross-entity facets;
- `followups.jsonl`: follow-up questions and due dates;
- `hypotheses.jsonl`: candidate hypotheses;
- `relations.jsonl`: legacy archive relations and v2 context edges;
- `current-state.json`: homepage snapshot of the core, situation, experience, tensions, and next checkpoint;
- `index.json`: routing index by date, entity, record, salience, and fidelity;
- `pages/`: human-readable projected views of entities and events;
- `traces/`: retrieval decision traces (appended on every retrieve_v2 run, see retrieval-decision-trace.md);
- `manifest.json`: version, schema, migration debt, and counts.

## one salience scale

`entry_kind` describes what an entry is; `salience` describes how much future understanding depends on it. Only the levels 0, 1, 2, 3 are allowed — the old dual core/important/background scheme is no longer mixed in.

## contextual facets

Entity co-occurrence does not by itself prove causation. A facet forms only from a shared event, shared space, shared relationship, or shared experience. A facet records the entity set and the shared entries; details resolve back to the canonical fragment.

## retrieval

survey does not read full texts; it reads only the spine, entities, facets, current state, follow-ups, and the hypothesis catalog. probe reads cards and relations. deep reads the verbatim/source fragments of the selected entries. Seeds are entry points, not hard boundaries. The survey spine samples representatives per phase bucket, so early pivotal events are not pushed out of the map just because newer entries exist.
