<div align="center">

# Personal Understanding

**An agent memory system with verbatim trace-back — it mimics how a human brain associates, fans out, converges, and reasons backward.**

[中文](README.md) · [What it is](#what-it-is) · [Feature map](#feature-map) · [Quick start](#quick-start) · [Design](#design)

[![PyPI](https://img.shields.io/pypi/v/personal-understanding)](https://pypi.org/project/personal-understanding/)
[![Python](https://img.shields.io/pypi/pyversions/personal-understanding)](https://pypi.org/project/personal-understanding/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/caix84476-netizen/personal-understanding?style=social)](https://github.com/caix84476-netizen/personal-understanding/stargazers)

</div>

`agent memory` `personal memory` `AI memory system` `MCP server` `local-first` `verbatim capture` `verbatim trace-back` `associative retrieval` `Personalized PageRank` `timeline memory` `auditable memory` `anti-hallucination memory` `personal knowledge management` `LLM agent memory` `claude skill` `codex skill`

---

## What it is

A personal memory system for AI assistants: plug it into clients like Claude, Codex, or Pi, and it remembers *you as a person* across sessions.

The mainstream approach — summarize or embed every sentence first, then throw the original away — is reversed here: **your exact words are saved first, untouched; understanding is only a derivation from them**. Derivations can be recomputed and corrected when wrong, while the original words stay in place for auditing — that's the "verbatim trace-back." As for "associates, fans out, converges, reasons backward": those are the four brain-like ways it finds things when it recalls, covered one by one in the [feature map](#feature-map) below.

## Life of a message

```text
your message → ① preflight: is this personal? (pure tech questions skip, never touch the archive)
            → ② verbatim capture: full message on disk byte-for-byte + SHA-256, immutable
            → ③ derive: events, entities, context cards, follow-ups; model guesses go to a separate hypothesis layer
            → ④ closure: every capture explicitly closed; no closure, no "it's remembered"
            → ⑤ later recall: survey the map → probe the fan-out → deep-read the verbatim, plus an association channel
```

Mechanics of ①–④: [docs/how-it-works.md](docs/how-it-works.md) sections 1–3; ⑤ in sections 4–8.

## Feature map

Four groups: capture, organize, recall, maintain. Each line carries a one-sentence "why"; details are all linked.

### Capture: when things come in

- **Two-tier gate** — personal content goes the full pipeline; pure tech, "what to eat," one-off purchases never touch the archive. The model backstops classifier misses — over-capture beats under-capture. (Why: a missed capture is a permanently lost verbatim; [mechanics](docs/how-it-works.md))
- **Immutable verbatim capture** — the full message lands byte-for-byte with SHA-256, timestamp, session tag; corrections append, never overwrite; attachments keep originals, OCR is only a derivation. (Why: summary-first makes the original unauditable; [mechanics](docs/how-it-works.md))
- **Derivation closure + hard gate** — saving the words isn't "updated": records must be derived and the capture explicitly closed; orphan captures can't pass the pre-answer session_check. (Why: "trust me, I saved it" failed in real life — the [2.5.0 duplicate-record incident](docs/why-it-works.md); [mechanics](docs/how-it-works.md))
- **Footprint discipline** — game-strategy, currently-reading/watching turns: targeted dedup first, exactly one light record, close gracefully on nothing-new. (Why: keeps one-off consultations from piling into archive noise; [mechanics](docs/how-it-works.md))

### Organize: how the archive is shaped

- **Timeline spine** — every record carries happened-date/precision/basis/phase/before-after neighbors; the recorded day can never impersonate the happened day. (Why: "you're currently in phase X" requires checking dates before telling stories; [policy](references/timeline-and-followup-policy.md))
- **Entity profiles + context cards** — nine entity types (people, schools, places, works, games, concepts…) plus "school × football" cross-cards; facts stored once, cards are projections. (Why: mutable state written into entity bodies becomes never-updated zombie info; [policy](references/entity-and-context-policy.md))
- **Five fact layers** — your verbatim / your evaluations / your explanations / model hypotheses / unconfirmable, always kept apart; model guesses stay `candidate`, need ≥2 pieces of evidence, and are never promoted. (Why: keeps the AI from filing its own speculation as your fact; [policy](references/causal-hypothesis-policy.md))
- **Follow-ups** — "let's see in a few days" open loops are archived with due dates, and proactively asked about with full context when due. (Why: silence is not an answer; changing the subject is not resolution; [policy](references/timeline-and-followup-policy.md))

### Recall: how it remembers

- **survey → probe → deep, three progressive layers** — a 48K compact routing map orients first, then fan-out along entities/contexts/time neighbors, then verbatim verification; every step budget-capped, the archive is never dumped whole into the model. (Why: dumping the whole archive drowns the model in irrelevant memory; [mechanics](docs/how-it-works.md))
- **Association channel (divergence)** — Personalized PageRank diffuses across the archive graph and surfaces zero-surface-overlap candidates that genuinely relate ("impact feel" → "Witcher 3 horseback handling"); a candidate pool, not a conclusion — the model cites only what holds. (Why: "out of books, give me one to chew on" once died in all three lexical channels — the [2.6.0 incident](docs/why-it-works.md); [mechanics](docs/how-it-works.md))
- **Convergent reading (detective board)** — "what should I do" splits into emotion/interests/people threads probed separately, then stitched; answers layered as archive facts / pattern observations / model inference. (Why: broad questions can't be served by a single query; [mechanics](docs/how-it-works.md))
- **Reverse cold-recall** — when keywords are gone, fan out from any person/place/time clue, walk time neighbors, browse time windows for the user to claim; declaring "not found" is forbidden. (Why: "not found" in a memory system is a lie — it means *not yet found*, not *doesn't exist*; [mechanics](docs/how-it-works.md))

### Maintain: how the archive takes care of itself

- **Feedback loop** — recorded only on explicit correction/confirmation, with the user's exact words as evidence; silence and topic changes are not signals. (Why: stops the model from grading its own homework; [policy](references/review-and-feedback-loops.md))
- **Quarterly salience review** — imported weights unconfirmed for 180+ days drop to 0: retained, retrievable, out of the active map, never deleted. (Why: the archive only grows; weights drift; [policy](references/review-and-feedback-loops.md))
- **Semantic review + three-state validation** — periodic scans for "summary posing as verbatim," "hypothesis quietly promoted," "misattribution"; structural validation reports clean/warnings/failed. ([mechanics](docs/how-it-works.md))
- **Snapshot backups + scoped restore** — a snapshot is cut only after "ran fine for 7 days and validation passed"; restore comes in code/data/all scopes, dry-run by default. (Why: this archive really lost data once; [policy](references/maintenance-and-durability.md))
- **Visual audit dashboard** — a pure local static page where you can click through the full chain: event → entity → context → verbatim. ([mechanics](docs/how-it-works.md))

## Quick start

Hand your agent this one command (adjust the path to your client's skills folder):

```bash
git clone https://github.com/caix84476-netizen/personal-understanding.git \
    ~/.claude/skills/personal-understanding && \
cd ~/.claude/skills/personal-understanding && \
python scripts/init_archive.py && \
python scripts/install_mcp.py --auto
```

Restart your client — the `personal_*` tools go live, and you just talk: "I've been feeling…", "remember that…", "why do I keep…" — it picks up on its own. Step-by-step manual guide (with verification checklist, upgrade, uninstall): [docs/install.md](docs/install.md).

Requires Python 3.10+, stdlib only, zero pip deps, Windows / macOS / Linux. You can also `pip install personal-understanding` for the server side, but the full brain (`SKILL.md` + audit dashboard) is best via the clone above.

## Design

Why verbatim-first, why the hard gate, why honesty beats recall rate, and what every version fixed: [docs/why-it-works.md](docs/why-it-works.md). One-line summary: **it's not a designed framework — it's a daily-driven archive hardened by a dozen rounds of real incidents** — the classifier once locked "I feel suffocated" out of the archive, dateless records were once silently buried by time decay, and whole-sentence colloquial queries were once topped by fake slices. Every fix has its scene in the [CHANGELOG](CHANGELOG.md).

The retrieval and tokenization layers stand on prior work ([per-item adoption/rejection with measured results](docs/why-it-works.md)): **SYNAPSE** (ACL 2026 Findings, spreading-activation gating), **HippoRAG** (NeurIPS 2024, PPR seed weighting), **Generative Agents** (Stanford, time decay), **Qiao & Sun** (ACL Y09-2003, self-trained lexicons), **jieba** (MIT, Chinese segmentation).

## Project layout

```text
personal-understanding/
├── SKILL.md                 # per-turn contract: gates, verbatim, closure, three-layer retrieval
├── docs/                    # how-it-works (mechanics) · why-it-works (rationale) · install
├── references/              # 14 field-level policy files (capture/retrieval/timeline/entities/…)
├── scripts/                 # the whole implementation, Python stdlib only
│   ├── mcp_server.py        # MCP server (11 personal_* tools)
│   ├── preflight_context.py · capture_user_update.py · finalize_capture.py · session_check.py
│   ├── catalog_context.py · retrieve_v2.py   # survey / probe / deep
│   ├── ppr.py · lexicon.py                   # association channel / token hygiene
│   └── validate_memory.py · review_v2.py · salience_review.py · backup_archive.py
├── dashboard/               # visual audit panel (pure local static page)
├── templates/branches/      # six life-domain branch templates
├── resources/lexicon/       # jieba lexicon (vendored, MIT)
├── tests/                   # 180+ regression tests + acceptance suites
└── VERSION / CHANGELOG.md   # version + battle-tested repair log
```

## Your data stays yours

Everything runs locally, inside this folder. No telemetry, no cloud calls, no third-party embedding services. The shipped `.gitignore` blocks `memory/`, `sources/`, and `backups/` — you can version-control this directory and never accidentally commit your private archive.

## License

[MIT](LICENSE) © 2026 caix84476-netizen
