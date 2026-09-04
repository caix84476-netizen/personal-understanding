# Retrieval Decision Trace

Two distinct things share the word "trace"; 2.5.0 separates them explicitly because conflating them made the contract unreadable:

## 1. Model-internal reasoning convention (not persisted)

Keep the following reasoning structure in mind on every invocation of the personal skill:

```json
{
  "activation": "skip | inspect-catalog | retrieve",
  "reason": "whether personal context could change the answer",
  "candidates": [
    {
      "id": "record-id",
      "relevance_level": "irrelevant | possible | medium | high",
      "why_relevant": "why it is relevant",
      "why_not_deeper": "why it was not read more deeply"
    }
  ],
  "scan": {
    "phase": "survey | probe | deep",
    "surveyed_current": 0,
    "history_indexed": 0,
    "selected_for_probe_or_deep": [],
    "explicit_evidence_ids": [],
    "excluded_from_auto_expansion": ""
  },
  "read": {"records": [], "support_records": [], "sources": []},
  "excluded": [{"id": "record-id", "reason": "why it was excluded"}],
  "uncertainty": {
    "missing_ids": [],
    "hypotheses": [],
    "evidence_gaps": [],
    "note": "conflicts or insufficient material"
  }
}
```

This full shape is only ever emitted as machine JSON by the DEPRECATED `retrieve_context.py` (2.0-compat; its tests lock this structure). The live v2 path does not persist it — it stays a thinking discipline for the model.

## 2. Machine trace file (persisted by retrieve_v2.py, since v2.1.0)

On every run, `retrieve_v2.py` appends a narrower decision record to `memory/v2/traces/trace-YYYYMM.jsonl` with exactly these keys: `at, capture_id, activation("retrieve"), level, query, window, scoring, survey{events,entities,facets}, selected{event_ids,entity_ids,knowledge_ids,facet_ids}, stopped{event_count,entity_count,reason}, fidelity`. Pass `--capture-id` to associate the current turn's capture; `--no-trace` disables writing for one run. Trace files are run logs; they do not participate in validation or derivation.

Use: when retrieval misses, mis-attributes, over-reads, or the user corrects something, replay the trace file to locate the problem stage (which terms were demanded, which IDs were selected, what was stopped by budget). Traces are not shown to the user by default. There is no automatic correlation between traces and feedback/corrections — inspecting the monthly trace log with the question in mind is a manual model step, not a tool behavior.

## v0.6 context extensions

The decision trace must distinguish: seeds the user stated explicitly, relation-expansion candidates, cross-domain anchors, behavioral evidence, counterexamples/conflicts, historical changes, and stop candidates. `seed IDs` are not a relevance boundary; every candidate needs its relation path, level, keep/exclude/promote decision, and the reason. (Reasoning convention from section 1.)
