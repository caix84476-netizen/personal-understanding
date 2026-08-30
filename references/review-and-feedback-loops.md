# Review, Salience Review, and Feedback Loop Policy

## Review and approval boundary (formerly review-approval-policy)

Automated review may do the following on its own:

- Rebuild the v2 derived views;
- Validate hashes, IDs, relations, sources, and time fields;
- Flag clear migration problems as warnings;
- Retain old records and old summaries.

Automated review must never do the following on its own:

- Rewrite old summaries into user verbatim;
- Promote model guesses into facts;
- Merge people whose identity is unclear;
- Invent dates, experiences, motivations, or feelings;
- Delete user verbatim or sources.

When semantic judgment is needed, emit `semantic-review-required`; the model then checks item by item as long as the current task is not blocked. What the user just explicitly corrected outranks the older archive. Deep review is automatic, verbatim must be preserved, and model guesses must never be promoted.

## Salience review (formerly salience-review-policy)

The archive only grows, so salience drifts out of truth over time. Therefore:

- Every quarter (or on every deep review), run `scripts/salience_review.py`: it lists event/fact/entity records unconfirmed for more than --min-age-days (default 180 days) whose salience came from import heuristics;
- After a trial run confirms the list, apply with `--apply`: it writes only an explicit `salience: 0` (passing level) and a `salience_reviewed` date — no deletions, no content rewrites;
- Salience 0 means "retained, retrievable, but out of the active map" — not "unimportant" and not "deleted";
- Any later mention (the user brings it up again, a new event connects to it) will hit in retrieval and naturally come back into view; at that point the user can confirm raising the salience again;
- Down-weighting never reduces reachability: keyword search in `retrieve_v2.py` covers the full timeline (including passing level), and entity/context probe pulls passing-level events back together with the entity's stories; when the user cannot recall a keyword, use the "cold recall" ladder in SKILL.md (time-neighbor walking + `--window` time-window browsing);
- Records the user rated for `salience` themselves, or that already carry a `salience_reviewed` marker, are never auto-down-weighted.

## Feedback loops (formerly feedback-policy)

The archive's value is tested by "do the answers actually understand you better". But the model reading the user's natural reactions is **low-reliability inference** with self-serving bias (a tendency to read vague reactions as "nailed it"). The default action of this policy is therefore **to record nothing**:

### What counts as a signal

- `corrected`: you explicitly corrected memory the answer relied on ("No, that's not what happened", "That's not the right person"). Strongest signal, reliable.
- `missed`: you explicitly said the association missed ("It's not about that", "That's completely different from what I meant"). Reliable.
- `helpful`: you explicitly confirmed ("Yes, exactly that"), or your follow-up questions proceed on that memory as a true premise. Moderately reliable; record only with clear evidence.
- `unclear`: you explicitly said "I can't put it into words / not quite right but I can't say why". Record only in this one case; the model's own "probably fine" does not count.

### Explicitly forbidden

- **Silence, changing the subject, and short replies are not any kind of feedback** and produce no record. "No objection" is not "nailed it".
- Never record the most self-favorable of several possible readings of a conversation as `helpful`; prefer a missed record to a wrong one.
- Each record's `note` must quote one sentence of your verbatim from that moment, or a faithful paraphrase of it, as evidence; an entry without evidence must not be written.

### Use boundary

- `corrected` is the only signal that drives action: `review_v2 --deep` lists the most-corrected memories as priority check items.
- `helpful` is reference statistics only and triggers no automatic rewriting.
- Feedback is append-only and never overwritten; it influences review priority and never directly modifies any record itself.
