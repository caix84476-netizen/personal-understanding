# Acceptance scenarios

1. Adding a state record and rebuilding views must leave old event records unchanged;
2. Adding a superseding fact keeps both the old and new versions traceable;
3. Two contextualized persona models can be stored side by side;
4. Running the maintenance check is read-only and never modifies files;
5. Validation fails on duplicate IDs, missing frontmatter, invalid statuses, and missing directories;
6. Adding a topic record without editing the master outline still passes validation;
7. Explicitly provided highly-private information is stored but cannot be retrieved by unrelated tasks;
8. Speculative persona hypotheses go to the inbox and are never auto-promoted;
9. Questions the user has not answered stay in open-loops and are not treated as refusals;
10. After eight important updates, a deep review with evidence-grounded derived-record revisions runs automatically;
11. Deep review can detect person-attribution, timing, and record drift;
12. Real decision tests outrank record counts and graph density.


## v0.3 model-driven retrieval

13. Purely technical, conceptual, and tooling questions return the model activation contract first and do not read personal records directly;
14. The full catalog covers derived records, domain branches, and raw source summaries at once, without embedding raw source bodies;
15. When the model chooses summary-level reading, raw sources are not loaded; a highly relevant deep read follows only the selected records and their `supports`;
16. The default run path does not use `proactive-cues.json`, fixed trigger words, or `cue_terms`;
17. Retrieval results include candidates, exclusions, reads, and an uncertainty trace;
18. The current conversation, user corrections, time state, and source attribution outrank catalog summaries.
