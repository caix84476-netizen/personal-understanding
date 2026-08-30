# Entity and Context Card Policy (including personal relationships)

## Profile creation principle

Any entity the user explicitly mentions and that context can pin down gets a lightweight profile, even if it appears only once. This applies to people, schools, places, books, games, works, devices, objects, concepts, and living environments.

A "purely vague pronoun" means only a "he/she/that person" that neither the current message nor readable-back context can pin down. In that case, do not fabricate a person: hang the verbatim on the event's `unresolved_referent` and wait for later clarification.

## Social connections

An entity profile must retain the other people and environments that appear in shared stories. Social ties must not be deleted to keep a profile "clean". Facts are stored as canonical events/fragments; entity pages present them through references and context cards, avoiding copy drift.

## Context cards

When several entities co-occur in the same story, space, relationship, or experience, generate a `facet`. For example, a school, football, and one particular match can form a "school × football" context card; both the school profile and the football profile can jump to it.

Incidental co-occurrence never automatically becomes causation. A context card is a memory entry point, not an explanatory conclusion.

## Identity and time metadata

Identity notes, aliases, and time spans may be kept in the machine index, but must not be repeated as standalone biography paragraphs on every person page. Promote them into the body text only when identity conflicts, time conflicts, or attribution would change the answer.

## People profiles (formerly personality-policy)

A person profile is a node in the social network, not an isolated mini-biography. The other people, schools, places, objects, and environments involved in stories about the person must be retained, connected through canonical events and facets.

Identities must never be merged on the basis of a nickname, a pronoun, an identically named account, or a single vague mention. When identity cannot be confirmed, do not invent a name: keep the verbatim and the unresolved referent, and promote to a formal entity only after later confirmation.
