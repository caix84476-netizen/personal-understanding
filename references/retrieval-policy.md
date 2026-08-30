# v2 Retrieval Policy (including the activation contract and priority loading)

## Retrieval flow

```text
preflight + follow-up check
  ↓
survey: timeline spine / entities / contexts / state / hypotheses
  ↓
probe: event neighbors / entity relations / context cards / counterexamples
  ↓
deep: verbatim fragments and sources of the selected entries
```

Not everything must be read to the end, but every entry point that could change the interpretation must have a reachable card. Keywords are only seeds; events, entities, time, shared contexts, and current state determine the expansion boundary.

probe never reads verbatim full texts. deep reads only the selected fragments, preserving the `verbatim`, `summary_only`, `ocr`, and `external_material` markers. probe output carries `evidence_fidelity` fidelity counts; the retrieval decision trace is persisted under `memory/v2/traces/` (see retrieval-decision-trace.md).

Relevance is not a privacy switch: sensitive content may be read when relevant; irrelevant content is never poured into answers.

## Activation contract (formerly activation-contract)

Each turn first judges whether personal context could change the answer:

- Clearly irrelevant: skip is allowed;
- Possibly relevant: read the v2 survey;
- Clearly relevant: read the survey, then pick events/entities/facets for probe, and deep when necessary.

When the personal-understanding skill runs, first check due items in `followups` and v2 review warnings; this step only does scheduling.

The survey covers the timeline spine, current state, the entity catalog, context cards, candidate hypotheses, follow-ups, and material gaps — never verbatim full texts.

## Priority and loading (formerly priority-and-loading)

Personal context is not a private database loaded in full every turn. When the skill runs, do the scheduling check first, then read progressively along survey → probe → deep.

The survey looks first at the timeline spine, entities, contexts, current state, follow-ups, hypotheses, and review warnings. Seeds can be events, entities, facets, states, or follow-ups. Relevance is judged jointly from entities, time, shared stories, user experience, the current task, and counterexamples — never from a single keyword.

Maintenance must not interrupt urgent tasks, but due follow-ups, user corrections, source-attribution errors, and structural corruption must be reported explicitly.

## Legacy proactive-association rules (formerly legacy-proactive-cues, migration material only)

`proactive-cues.json` retains the v0.2 trigger and expansion vocabulary for regression comparison and failure analysis. Since v0.3.0 it plays no part in runtime recall: the model must first decide whether the personal skill is needed, then progressively read material from the global survey. Do not stack more trigger words into that file to fix missed detections.
