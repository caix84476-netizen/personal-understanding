# Retrieval Decision Trace

Keep the following internal structure on every invocation of the personal skill:

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

## Persistence (since v2.1.0)

The trace is no longer just a convention but a machine fact: on every run, `retrieve_v2.py` appends the trace of that retrieval (phase, queries, time windows, selected/stopped IDs, capture association) to `memory/v2/traces/trace-YYYYMM.jsonl`. Use `--capture-id` to associate the current turn's capture, or `--no-trace` to disable writing for a single run. Trace files are run logs; they do not participate in validation or derivation.

Use: when retrieval misses, mis-attributes, over-reads, or the user corrects something, replay the trace to locate the problem stage. `review_v2 --deep` and `review_skill` can, on demand, correlate high-frequency queries with frequently corrected memories. Traces are not shown to the user by default.


## v0.6 context extensions

The decision trace must distinguish: seeds the user stated explicitly, relation-expansion candidates, cross-domain anchors, behavioral evidence, counterexamples/conflicts, historical changes, and stop candidates. `seed IDs` are not a relevance boundary; every candidate needs its relation path, level, keep/exclude/promote decision, and the reason.
