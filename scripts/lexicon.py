#!/usr/bin/env python3
"""Query-slice lexicon: vendored jieba dictionary + archive self-trained proper nouns.

Role boundary (2.6.0, SKILL §检索流程): the lexicon is a *recall janitor*, not a
judge. It only deletes OOV cross-word slices (郎我/卡了) and stray ASCII single
chars ("3" from 巫师3 matching dates inside record ids) from the QUERY side, so
inflated-IDF junk slices stop qualifying irrelevant records. It never filters the
archive side, never ranks anything, and every filter has a fall-back: when a
query has no lexicon-known content term at all, the unfiltered set is used —
宁滥勿漏 still wins wherever the lexicon is uncertain.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEXICON_DIR = ROOT / "resources" / "lexicon"
JIEBA_DICT = LEXICON_DIR / "jieba-dict.txt"
ENTITIES_JSONL = ROOT / "memory" / "v2" / "entities.jsonl"
RECORDS_DIR = ROOT / "memory" / "records"
V2_DIR = ROOT / "memory" / "v2"
ARCHIVE_LEXICON = V2_DIR / "archive-lexicon.json"
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


@lru_cache(maxsize=1)
def load_jieba_dict() -> frozenset[str]:
    """Vendored jieba dict.txt (MIT, fxsjy/jieba) — 349k entries, loaded once per process."""
    if not JIEBA_DICT.exists():
        return frozenset()
    words: set[str] = set()
    with JIEBA_DICT.open(encoding="utf-8") as handle:
        for line in handle:
            word = line.split(" ", 1)[0].strip().casefold()
            if word:
                words.add(word)
    return frozenset(words)


def build_archive_terms(min_df: int = 2, max_chars_per_record: int = 6000) -> frozenset[str]:
    """Self-trained archive lexicon: entity labels/aliases (authoritative, always in)
    plus every 2-4 char CJK slice occurring in >= min_df distinct record/v2 texts.

    This is the archive self-training the user asked for (5.6b): 弦一郎/艾迪芬奇/
    晕3D-style proper nouns that no general dictionary knows become lexicon words
    because the archive itself repeats them, while cross-word accident slices
    (郎我/卡了) stay out at df=1. O(n) over ~1MB of text; persisted by
    rebuild_views into archive-lexicon.json so retrieval never pays it live.
    """
    from collections import Counter

    df: Counter[str] = Counter()

    def feed(text: str) -> None:
        if not text:
            return
        for run in CJK_RUN.findall(text.casefold()):
            seen: set[str] = set()
            for size in (2, 3, 4):
                for index in range(len(run) - size + 1):
                    piece = run[index : index + size]
                    if piece not in seen:
                        seen.add(piece)
                        df[piece] += 1

    try:
        for jsonl in V2_DIR.glob("*.jsonl"):
            if jsonl.name in {"archive-lexicon.json", "feedback.jsonl"}:
                continue
            for line in jsonl.read_text(encoding="utf-8").splitlines()[:2000]:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                feed(" ".join(str(row.get(k, "")) for k in ("title", "summary", "label", "notes")))
    except OSError:
        pass
    try:
        for path in RECORDS_DIR.glob("*.md"):
            feed(path.read_text(encoding="utf-8")[:max_chars_per_record])
    except OSError:
        pass

    terms = {word for word, count in df.items() if count >= min_df}
    try:
        for line in (ENTITIES_JSONL.read_text(encoding="utf-8").splitlines() if ENTITIES_JSONL.exists() else []):
            if not line.strip():
                continue
            row = json.loads(line)
            for value in (row.get("label"), *(row.get("aliases") or [])):
                value = str(value).strip()
                if 1 < len(value) <= 12:
                    terms.add(value.casefold())
    except (OSError, json.JSONDecodeError):
        pass
    return frozenset(terms)


def _signature() -> tuple:
    """Cheap change signal for the archive (records count + newest mtimes)."""
    try:
        rec_stat = [(p.stat().st_mtime_ns, p.stat().st_size) for p in RECORDS_DIR.glob("*.md")]
        v2_stat = [(p.stat().st_mtime_ns, p.stat().st_size) for p in V2_DIR.glob("*.jsonl")]
        return (len(rec_stat), sum(m for m, _ in rec_stat), len(v2_stat), sum(m for m, _ in v2_stat))
    except OSError:
        return ()


_CORPUS_CACHE: tuple[tuple, frozenset[str]] | None = None


def load_archive_terms() -> frozenset[str]:
    """Archive lexicon with an mtime-checked cache; falls back to a live build
    when no persisted copy exists yet (first run before rebuild_views)."""
    global _CORPUS_CACHE
    sig = _signature()
    if _CORPUS_CACHE and _CORPUS_CACHE[0] == sig:
        return _CORPUS_CACHE[1]
    if ARCHIVE_LEXICON.exists():
        try:
            terms = frozenset(json.loads(ARCHIVE_LEXICON.read_text(encoding="utf-8")))
            _CORPUS_CACHE = (sig, terms)
            return terms
        except (OSError, json.JSONDecodeError):
            pass
    terms = build_archive_terms()
    _CORPUS_CACHE = (sig, terms)
    return terms


def persist_archive_terms() -> int:
    """Rebuild and persist the archive lexicon (called by rebuild_views)."""
    terms = build_archive_terms()
    from storage import atomic_write_text

    atomic_write_text(ARCHIVE_LEXICON, json.dumps(sorted(terms), ensure_ascii=False))
    _CORPUS_CACHE = None  # force re-read of the persisted copy
    return len(terms)


def known(term: str) -> bool:
    """True when the term is a dictionary word or an archive proper noun."""
    if term in load_archive_terms():
        return True
    return term in load_jieba_dict()


def is_mixed(term: str) -> bool:
    """True for a glued CJK+Latin term (巫师3/晕3D): adjacent in the query itself,
    so a record-side substring hit requires the same adjacency — no false hits."""
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in term)
    has_latin = any(ch.isascii() and ch.isalnum() for ch in term)
    return has_cjk and has_latin


def filter_query_terms(terms: list[str]) -> tuple[list[str], list[str]]:
    """Query-side hygiene with a strict no-deletion contract for CJK slices.

    2.6.0 revision: OOV slices are NOT deleted. The first cut deleted them, and the
    smoke test immediately regressed T02 — 弦一郎 appears in the archive only once,
    so no DF threshold can separate it from accident slices like 郎我. Deletion also
    cannot be repaired by the fall-back once it blinds the one decisive term. So the
    lexicon's only deletion here is stray ASCII single chars ('3' out of 巫师3 —
    inside ids/dates they match everything; measured top1 junk qualifier on
    2026-09-05). OOV slices keep their recall but are DEMOTED in term_weights
    (×0.4) so they can neither anchor nor dominate ranking; a sole hit still wins
    because ranking is relative. Mixed CJK/Latin glued terms (巫师3/晕3D) are kept
    unfiltered: they only form where the characters are adjacent in the query, so a
    record-side substring hit requires the same adjacency — no false hits possible.
    FALL-BACK kept as belt-and-braces: with no content-bearing term left, return
    the original list.
    """
    dropped: list[str] = []
    kept: list[str] = []
    ascii_single: list[str] = []
    for term in terms:
        if term.isascii():
            if len(term) == 1:
                ascii_single.append(term)
            else:
                kept.append(term)
            continue
        kept.append(term)  # CJK slices are never deleted; OOV demotion lives in weights
    content_kept = [t for t in kept if len(t) >= 2]
    if not content_kept:
        return list(terms), []
    if ascii_single:
        dropped.extend(ascii_single)
    return kept, dropped


def mixed_run_terms(query: str) -> list[str]:
    """Glue adjacent CJK/Latin runs into mixed proper-noun terms (巫师3, QQ空间, 晕3D).

    CJK/ASCII boundary splitting loses the strongest anchor a query can carry:
    巫师3 becomes 巫师+3 and the record that literally contains 巫师3 loses its
    sharpest signal. The glued form is an extra term, not a replacement — the
    unglued parts stay so partial matches still work.
    """
    tokens = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[\u4e00-\u9fff]+|[a-z0-9_]+", query.casefold())]
    glued: list[str] = []
    for (tok_a, _, end_a), (tok_b, start_b, _) in zip(tokens, tokens[1:]):
        if end_a != start_b:
            continue  # separated by punctuation/space — not one written word
        a_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in tok_a)
        b_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in tok_b)
        if a_cjk != b_cjk:
            combined = tok_a + tok_b
            if len(combined) <= 8:
                glued.append(combined)
    return glued
