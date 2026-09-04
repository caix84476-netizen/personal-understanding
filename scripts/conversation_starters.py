"""Guided starters: suggest what the user might want to tell the archive next.

Reads the archive's own state — sparse domains, open follow-ups, stale current
state, recent activity — and returns a few concrete, warm starter questions.
Intended for users who do not know what to share, and for freshly initialized
archives that need a first entry point.

Output is JSON. Ranking: due follow-ups first (with their context), then the
emptiest domains, then a stale-current-state nudge. Suggestions come only from
real gaps in the archive — never invented psychology. All prompts are Chinese
(2.5.0 §6.7): the whole skill works in the user's language, so an English starter
template would read as noise when the model speaks it out loud.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOMAIN_QUESTIONS = {
    "domain.education-career": "学校或工作里，有没有哪件事让你重新看了自己一眼？",
    "domain.family-home": "你从小待的那个家里，有没有哪条规矩、习惯或氛围，到今天还在你身上？",
    "domain.health-life": "这周你的精力、睡眠、压力，实际是个什么状态？",
    "domain.learning-interests": "最近有没有在学什么、玩什么，是你想再往深里挖的？",
    "domain.relationships": "最近谁给你留下了点印象？当时怎么个情况？",
    "domain.self-collaboration": "你干活、做计划的时候——不管是跟 AI 还是自己来——什么样的帮忙方式对你真正管用？",
}

GENERIC_OPENERS = [
    "最近有没有哪个瞬间，不管大小，你隐约觉得它挺能说明你是谁的？",
    "眼下有在纠结的决定吗？在这儿聊明白，以后翻回来就能接着想。",
    "有没有哪个人塑造了你，你想留一个真实发生过的那段事？",
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
            "question": f"之前你留了个口子：“{item['question']}”——后来怎么样了？",
            "domain": "follow-up",
            "reason": "你自己开的一条待回访；按时收口档案才不失真",
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
            question = f"「{label}」这一面，有什么事或记忆值得记一笔？"
        reason = (
            "这个领域还没有记录——开个第一线正好"
            if counts.get(domain, 0) == 0
            else f"目前这儿只有 {counts[domain]} 条记录"
        )
        starters.append({"question": question, "domain": domain, "reason": reason})

    if len(starters) < limit and total <= 3:
        for opener in GENERIC_OPENERS:
            if len(starters) >= limit:
                break
            starters.append({"question": opener, "domain": "any", "reason": "档案刚起步——任何一段真实的事都是好种子"})

    gap_days = last_capture_days()
    return {
        "starters": starters[:limit],
        "archive": {
            "records": total,
            "domains": branch_domains(),
            "open_followups": len(open_followups()),
            "days_since_last_capture": gap_days,
        },
        "usage": "用你自己的话、自然暖心地挑一条问，只问一条；用户答完后原样捕获消息，走正常的派生+回答流程。不要把整个清单倒出来连环追问。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest what the user might want to tell the archive next.")
    parser.add_argument("--limit", type=int, default=3, help="how many starters to return (default 3)")
    args = parser.parse_args()
    print(json.dumps(build_starters(max(1, args.limit)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
