# Maintenance, Cleanup, Backup, and Evolution Policy

## v2 maintenance policy (formerly maintenance-policy)

Maintenance has four outcomes:

- clean: no problems;
- warnings: structure usable but with migration debt, date gaps, pending follow-ups, or evidence gaps;
- failed: structure / hash / relations / schema corrupted;
- semantic-review-required: the model must compare verbatim, events, entities, and explanations item by item.

`validate_memory.py` handles machine structure; `review_v2.py --deep` handles review bundles and semantic risk. Without a verbatim capture, review can only report that it cannot verify — it must never fill in the gap.

User-stated facts, current state, corrections, and collaboration rules are archived directly; model causal speculation goes into a candidate hypothesis; old versions are retained and never silently overwritten.

Deep review is triggered when an important-update threshold is reached, when a correction / attribution error / structure change / verbatim-capture failure occurs, when a follow-up comes due, or when an important decision is near. The `maintenance` reminder in preflight / session_check output (backup age, etc.) is per-turn visible maintenance state; when the backup is overdue, run the backup after the current task finishes and before ending.

## v2 cleanup policy (formerly cleanup-policy)

Verbatim captures, attachments, sources, and history are not deletable by default. Cleanup prefers reversible cooling, down-weighting, and historical marking.

Permanent deletion requires the user to explicitly name the specific capture, source, or record. Before deleting, report the path, rationale, impact, and recovery possibility.

`summary_only` is neither deletion nor current fact; it is readable-back migration debt.

## Backup and disaster-recovery policy (formerly backup-policy)

The archive is non-regenerable personal memory; `memory/records/` contains a record of a real data-loss incident (2026-08-08). "Undeletable" only protects the archive from accidental deletion — not from disk failure, accidental reformatting, or sync conflicts.

**Backup model (user-defined, 2026-08-29: working archive and archived snapshot)**:

- **Working archive** = the preview version, the live copy that keeps evolving;
- **Archived snapshot** (`backups/personal-understanding-stable.zip`, overwritten under a fixed name; the previous generation is kept as `previous.zip`; capped at two files) = the stable rollback point, **always one version behind the working archive**. Refresh conditions: more than `refresh_after_days` days since the last one (default 7, i.e., "sync once it has run fine for a week or two") **and** structural validation passes (treat it as an acceptance test; a failed validation never refreshes). If the working archive has not changed by a single character, skip — no redundant repacking and uploading;
- **Cloud (a WebDAV cloud drive, synced via rclone)**: every backup run pushes the archived snapshots (stable version + previous version) to the cloud — overwrite in place, no accumulating snapshots, no resident background process. Only the snapshots are pushed, never the working-archive directory: the drive's free tier rate-limits WebDAV request frequency, and a few hundred small files can trigger 503 rate limiting. The snapshot itself is a complete copy of the working archive, so recovery = download + extract. A 503 is temporary rate limiting; it clears itself in about half an hour and the next backup run resumes automatically;
- **USB drive**: automatic mirroring is off by default; the user copies manually (taking the whole working-archive folder is enough).
- Recommended cadence: after every important update batch, before every migration, and at least once a week. preflight / session_check reports the archived-snapshot age; once overdue (default 7 days) a backup is due. As long as the archive has been updated, the reminder always appears with activation and the model executes it automatically.
- Recovery = download/obtain the archived snapshot → extract over the skill directory → `rebuild_views.py` + `validate_memory.py`.
- Disaster-recovery tiers: working archive → cloud archived snapshot (off-site, guards against disk-level or same-room disasters) → local previous-generation snapshot (guards against "the new version has bad data") → user-managed USB-drive snapshot.

## v2 evolution policy (formerly evolution-policy)

v2 uses compatible migration: old records are not deleted, old summaries are never disguised as verbatim, and all new content goes through the verbatim-capture chain.

A version change must update all of the following together:

- SKILL.md and VERSION;
- the record schema;
- the catalog, retrieval, write, validation, and review scripts;
- the dashboard;
- tests and migration notes.

Upgrading only part of the functionality creates dual-track semantics and counts as a migration failure.
