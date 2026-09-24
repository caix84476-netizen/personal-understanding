#!/usr/bin/env python3
"""审计派生记录里的引号片段是否真的出自用户原话。

动机（2026-09-10 事故）：模型在记录里写下"用户第一轮口述时说的是豆包"，
而用户的全部原话 capture 里从未出现"豆包"——引号内被塞进了模型自造的内容。
原话保真的最后一道防线不能只靠模型自觉，所以用这个脚本做机械核对：

  1. 扫 memory/records/*.md 正文里的每一段引号内容；
  2. 取用户侧原文语料（sources/**：capture 原文、旧材料、外部导出）；
  3. 用后缀自动机求每段引号与语料的最长公共子串，算覆盖率；
     覆盖率低 = 这句话在原文里找不到出处，需要人工复核。

只读，不改档。用法：
    python scripts/audit_quote_provenance.py
    python scripts/audit_quote_provenance.py --min-ratio 0.6 --top 40
    python scripts/audit_quote_provenance.py --only-user-cues --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "memory" / "records"
SOURCE_DIRS = ("sources",)

QUOTE_PATTERNS = (
    re.compile(r'"([^"]{4,400})"'),
    re.compile(r"'([^']{4,400})'"),
    re.compile(r"“([^”]{4,400})”"),
    re.compile(r"『([^』]{4,400})』"),
)

COLLAB_HINTS = ("模型", "AI", "skill", "Skill", "README", "提示词", "豆包", "档案", "规则")
USER_CUES = ("用户", "他", "原话", "自述", "说", "认为", "明确", "讲述", "自评")
NOISE_RE = re.compile(r"[\s，。！？、；：…—～~·「」（）()\[\]【】*#>|\-]+")


def normalize(text: str) -> str:
    return NOISE_RE.sub("", text)


class SuffixAutomaton:
    """最小后缀自动机：线性时间建图，支持 O(len(span)) 求最长公共子串。"""

    __slots__ = ("next", "link", "length", "last")

    def __init__(self, text: str) -> None:
        self.next: list[dict[str, int]] = [{}]
        self.link: list[int] = [-1]
        self.length: list[int] = [0]
        self.last = 0
        for ch in text:
            self._extend(ch)

    def _extend(self, ch: str) -> None:
        cur = len(self.length)
        self.length.append(self.length[self.last] + 1)
        self.link.append(0)
        self.next.append({})
        p = self.last
        while p != -1 and ch not in self.next[p]:
            self.next[p][ch] = cur
            p = self.link[p]
        if p == -1:
            self.link[cur] = 0
        else:
            q = self.next[p][ch]
            if self.length[p] + 1 == self.length[q]:
                self.link[cur] = q
            else:
                clone = len(self.length)
                self.length.append(self.length[p] + 1)
                self.link.append(self.link[q])
                self.next.append(dict(self.next[q]))
                while p != -1 and self.next[p].get(ch) == q:
                    self.next[p][ch] = clone
                    p = self.link[p]
                self.link[q] = self.link[cur] = clone
        self.last = cur

    def lcs_length(self, text: str) -> int:
        state = 0
        best = 0
        cur = 0
        for ch in text:
            while state and ch not in self.next[state]:
                state = self.link[state]
                cur = self.length[state]
            nxt = self.next[state].get(ch)
            if nxt is None:
                state, cur = 0, 0
                continue
            state = nxt
            cur += 1
            if cur > best:
                best = cur
        return best


def iter_source_texts() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for base in SOURCE_DIRS:
        for path in sorted((ROOT / base).rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".txt", ".md", ".json", ".jsonl", ".csv"}:
                continue
            try:
                out.append((str(path.relative_to(ROOT)), path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="只查 mtime >= YYYYMMDD 的记录")
    ap.add_argument("--min-ratio", type=float, default=0.55)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only-user-cues", action="store_true")
    ap.add_argument("--user-voice-only", action="store_true", help="只查带用户归属词、且不含协作语境的引号（最贴近'用户原话'）")
    ap.add_argument("--max-lcs", type=int, default=None, help="另报：与语料最长公共子串长度 <= 该值的片段（噪音滤波用）")
    ap.add_argument("--out", default=None, help="把结果写入 UTF-8 文件")
    args = ap.parse_args()

    sources = iter_source_texts()
    corpus = normalize("\n".join(text for _, text in sources))
    automaton = SuffixAutomaton(corpus)
    cache: dict[str, int] = {}

    findings: list[dict] = []
    scanned = 0
    for path in sorted(RECORDS.glob("*.md")):
        if args.since:
            import datetime as _dt

            if _dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d") < args.since:
                continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if args.user_voice_only:
                if not any(cue in line for cue in USER_CUES):
                    continue
                if any(hint in line for hint in COLLAB_HINTS):
                    continue
            for pattern in QUOTE_PATTERNS:
                for span in pattern.findall(line):
                    norm = normalize(span)
                    if len(norm) < 6:
                        continue
                    scanned += 1
                    if args.only_user_cues and not any(cue in line for cue in USER_CUES):
                        continue
                    hit = cache.get(norm) or automaton.lcs_length(norm)
                    cache[norm] = hit
                    ratio = hit / len(norm)
                    if ratio >= args.min_ratio:
                        continue
                    if args.max_lcs is not None and hit > args.max_lcs:
                        continue
                    findings.append(
                        {
                            "record": path.name,
                            "line": lineno,
                            "ratio": round(ratio, 3),
                            "matched_chars": hit,
                            "span_chars": len(norm),
                            "collab_context": any(hint in line for hint in COLLAB_HINTS),
                            "span": span[:160],
                        }
                    )

    findings.sort(key=lambda row: (row["ratio"], -row["span_chars"]))
    result = {
        "source_files": len(sources),
        "source_chars": len(corpus),
        "spans_scanned": scanned,
        "suspicious": len(findings),
        "min_ratio": args.min_ratio,
        "items": findings[: args.top],
    }
    if args.json:
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        lines = [
            f"语料：{len(sources)} 个来源文件 / {len(corpus)} 字；扫描引号片段 {scanned} 段",
            f"覆盖率低于 {args.min_ratio}：{len(findings)} 段（显示前 {min(args.top, len(findings))} 段）",
        ]
        for row in result["items"]:
            flag = " [协作语境]" if row["collab_context"] else ""
            lines.append(f"- {row['ratio']:.2f} ({row['matched_chars']}/{row['span_chars']}) {row['record']}:{row['line']}{flag}")
            lines.append(f"    {row['span']}")
        text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"written: {args.out} ({len(findings)} findings)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
