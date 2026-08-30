# Timeline Spine and Proactive Follow-Up Policy (including open loops)

## Timeline entries

Time fields must distinguish when the event happened, when the user recalled it, when the source was created, and model inference. Exact dates, date ranges, phases, and relative order are supported; unknown stays unknown.

## Follow-ups

When the user says "wait a few days", "they haven't replied yet", when the model raises an important question that goes unanswered, or when results should be checked later, write an entry to `memory/v2/followups.jsonl`. Every entry must carry the original question, context, source, and a due rule.

When the skill runs, check:

- Already due: must proactively follow up with context;
- Due soon: may be reminded at the end of the current answer;
- No date recorded: list as a material gap; never invent a date;
- Resolved: save the user's follow-up outcome; never delete the original to-do.

Follow-up questions must first restate the date, the original question, and the expectation at the time, then ask about what happened next; never ask out of nowhere "how did it go?".

## Contradictions

Contradiction checks must list: the old claim, the new claim, dates, sources, the difference, and the points needing user confirmation. Silence is not correction, and changing the subject does not mean the issue is resolved.

## Open loops (formerly open-loops-policy)

Every unanswered important question, pending reply, pending result, and agreed later check goes into `followups.jsonl`. Keep the original question and context; never treat silence as refusal.

When the skill runs, check due items. A due follow-up must carry the creation date, the original question, the background at the time, and the reason for checking. Unrelated urgent tasks may be followed up after the task completes, but never insert a bare one-liner without context.

After the user later answers explicitly, save the verbatim of that answer and close the original loop; the old loop record is retained.
