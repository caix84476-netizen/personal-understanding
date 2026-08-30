"""Guided starters: suggest what the user might want to tell the archive next.

Reads the archive's own state — sparse domains, open follow-ups, stale current
state, recent activity — and returns a few concrete, warm starter questions.
Intended for users who do not know what to share, and for freshly initialized
archives that need a first entry point.

Output is JSON. Ranking: due follow-ups first (with their context), then the
emptiest domains, then a stale-current-state nudge. Suggestions come only from
real gaps in the archive — never invented psychology.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOMAIN_QUESTIONS = {
    "domain.education-career": "What's one moment from school or work that changed how you see yourself?",
    "domain.family-home": "What's a rule, habit, or atmosphere from the place you grew up that still shows up in your life?",
    "domain.health-life": "How have your energy, sleep, and stress actually been this week?",
    "domain.learning-interests": "What's something you've been learning or playing with lately that you'd love to go deeper on?",
    "domain.relationships": "Who's someone who left an impression on you recently — and what happened?",
    "domain.self-collaboration": "When you work and plan — with AI or alone — what style of help actually works for you?",
}

GENERIC_OPENERS = [
    "What's a recent moment — big or tiny — that you suspect says something about who you are?",
    "Is there a decision you're weighing right now? Talking it out here means future-you can pick up the thread.",
    "Who's a person that shaped you, and what's one story with them you'd want remembered the way it actually happened?",
]

FRONTMATTER_RE = re.compile(r"^---\s*$", re.MULTILINE)


def split_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def domain_counts() -> tuple[dict[str, int], int]:
    counts: dict[str, int] = {}
    total = 0
    records = ROOT / "memory" / "records"
    if records.exists():
        for path in records.glob("*.md"):
            meta = split_frontmatter(path)
            if meta.get("status", "current") != "current":
                continue
            total += 1
            for domain in re.split(r"[;,]", meta.get("domain", "")):
                domain = domain.strip()
                if domain:
                    counts[domain] = counts.get(domain, 0) + 1
    return counts, total


def branch_domains() -> list[str]:
    branches = ROOT / "memory" / "branches"
    ids = []
    if branches.exists():
        for path in sorted(branches.glob("*.md")):
            if path.name == "index.md":
                continue
            meta = split_frontmatter(path)
            branch_id = meta.get("id", "")
            if branch_id.startswith("domain."):
                ids.append(branch_id)
    return ids


def open_followups() -> list[dict[str, str]]:
    path = ROOT / "memory" / "v2" / "followups.jsonl"
    items: list[dict[str, str]] = []
    if not path.exists():
        return items
    today = date.today()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = str(row.get("status", "")).lower()
        if status in {"resolved", "answered", "declined", "closed"}:
            continue
        due = str(row.get("due_at") or "")
        due_date = None
        if due:
            try:
                due_date = datetime.strptime(due[:10], "%Y-%m-%d").date()
            except ValueError:
                due_date = None
        if due_date and due_date > today + timedelta(days=3):
            continue
        question = str(row.get("prompt") or row.get("question") or "").strip()
        if question:
            items.append({"question": question, "due_at": due})
    return items


def last_capture_days() -> int | None:
    conv = ROOT / "sources" / "conversation"
    if not conv.exists():
        return None
    stamps = [p.stat().st_mtime for p in conv.glob("*.txt")]
    if not stamps:
        return None
    latest = datetime.fromtimestamp(max(stamps)).date()
    return (date.today() - latest).days


def build_starters(limit: int) -> dict:
    counts, total = domain_counts()
    starters: list[dict[str, str]] = []

    for item in open_followups()[:1]:
        starters.append({
            "question": f"Earlier you left this open: “{item['question']}” — how did it turn out?",
            "domain": "follow-up",
            "reason": "an open loop you created; checking back keeps the archive honest",
        })

    empty_domains = [d for d in branch_domains() if counts.get(d, 0) == 0]
    thin_domains = sorted(branch_domains(), key=lambda d: counts.get(d, 0))
    ordered = empty_domains + [d for d in thin_domains if counts.get(d, 0) > 0 and d not in empty_domains]
    for domain in ordered:
        if len(starters) >= limit:
            break
        question = DOMAIN_QUESTIONS.get(domain)
        if not question:
            label = domain.removeprefix("domain.").replace("-", " ")
            question = f"What's a story or memory that fits your {label} side?"
        reason = (
            "this domain has no records yet — a good first thread"
            if counts.get(domain, 0) == 0
            else f"only {counts[domain]} record(s) here so far"
        )
        starters.append({"question": question, "domain": domain, "reason": reason})

    if len(starters) < limit and total <= 3:
        for opener in GENERIC_OPENERS:
            if len(starters) >= limit:
                break
            starters.append({"question": opener, "domain": "any", "reason": "fresh archive — any true story is a good seed"})

    gap_days = last_capture_days()
    return {
        "starters": starters[:limit],
        "archive": {
            "records": total,
            "domains": branch_domains(),
            "open_followups": len(open_followups()),
            "days_since_last_capture": gap_days,
        },
        "usage": "Ask ONE starter warmly in your own words; after the user answers, capture the message verbatim and follow the normal derive-and-answer flow. Never dump the whole list as an interrogation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest what the user might want to tell the archive next.")
    parser.add_argument("--limit", type=int, default=3, help="how many starters to return (default 3)")
    args = parser.parse_args()
    print(json.dumps(build_starters(max(1, args.limit)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
