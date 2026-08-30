#!/usr/bin/env python3
"""Open the local personal-understanding archive viewer.

The viewer reads the current Skill directory directly. It never writes records,
sources, indexes, or generated views.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import webbrowser
from collections import defaultdict
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from catalog_utils import ROOT, load_branches, load_records, parse_frontmatter, source_ref_matches, split_ids
from v2_archive import load_v2, v2_audit

DASHBOARD = ROOT / "dashboard"
OTHER_ID = "domain.unclassified"
OTHER_LABEL = "Other / Unclassified"
RELATION_FIELDS = ("parent_ids", "related_ids", "supports", "contradicts", "supersedes")
ROOT_ROLES = {
    "memory": "Personal records, branches, and generated indexes",
    "sources": "Raw chats, text, images, and OCR",
    "references": "Retrieval, correction, and review rules",
    "scripts": "Read, maintenance, and validation tools",
    "migrations": "Structure migration notes",
    "agents": "Collaborating agent notes",
    "dashboard": "Current visualization UI",
    "tests": "Structure and behavior tests",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def clean_text(text: str, limit: int | None = None) -> str:
    value = " ".join(text.split())
    return value if not limit or len(value) <= limit else value[: limit - 1].rstrip() + "…"


def list_value(meta: dict[str, str], field: str) -> list[str]:
    return split_ids(meta.get(field))


def title_for(meta: dict[str, str], body: str) -> str:
    aliases = list_value(meta, "aliases")
    if aliases:
        return aliases[0]
    text = clean_text(body)
    if not text:
        return meta.get("id", "Untitled record")
    sentence = re.split(r"[。！？]", text, maxsplit=1)[0].strip()
    return sentence[:28] + ("…" if len(sentence) > 28 else "")


def all_source_files() -> list[Path]:
    base = ROOT / "sources"
    return sorted(path for path in base.rglob("*") if path.is_file() and not ("sources" in path.parts and "conversation" in path.parts and path.suffix.lower() == ".json"))


def source_type(path: Path) -> str:
    value = rel(path)
    if value.startswith("sources/conversation/"):
        return "User verbatim"
    if value.startswith("sources/external/"):
        return "External conversation"
    if value.startswith("sources/images/"):
        return "Image"
    if value.startswith("sources/ocr/"):
        return "OCR"
    if value.startswith("sources/markdown/"):
        return "Text"
    return "Source note"


def source_group(path: Path) -> str:
    name = path.name.casefold()
    if "deepseek" in name:
        return "DeepSeek chat"
    if "conversation" in path.parts or str(path).replace("\\", "/").find("sources/conversation/") >= 0:
        return "User verbatim capture"
    return source_type(path)


def source_display_title(path: Path) -> str:
    name = path.name
    lowered = name.casefold()
    if "deepseek" in lowered:
        match = re.search(r"(20\d{2})[-_.](\d{2})[-_.](\d{2})t(\d{2})[-_.](\d{2})[-_.](\d{2})", lowered)
        if match:
            year, month, day, hour, minute, second = match.groups()
            return f"DeepSeek chat · {year}.{month}.{day} {hour}:{minute}:{second}"
        return "DeepSeek chat"
    return path.stem


def source_date(path: Path) -> str:
    match = re.search(r"(20\d{2})[-_.年](\d{1,2})[-_.月](\d{1,2})", path.name)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def tree(path_value: str = "") -> dict:
    base = (ROOT / path_value).resolve()
    try:
        base.relative_to(ROOT.resolve())
    except ValueError:
        return {"error": "Path not allowed"}
    if not base.exists() or not base.is_dir():
        return {"error": "Directory not found"}
    items = []
    for child in sorted(base.iterdir(), key=lambda item: (item.is_file(), item.name.casefold())):
        if child.name.startswith("__pycache__") or child.name == ".codex-write-probe.tmp":
            continue
        items.append({
            "name": child.name,
            "path": rel(child),
            "kind": "folder" if child.is_dir() else "file",
            "extension": child.suffix.lower(),
            "size": child.stat().st_size if child.is_file() else None,
        })
    return {"path": rel(base) if base != ROOT else "", "items": items}


def expand_refs(record_id: str, raw_by_id: dict[str, dict], seen: set[str] | None = None) -> set[str]:
    seen = seen or set()
    if record_id in seen or record_id not in raw_by_id:
        return set()
    seen.add(record_id)
    meta = raw_by_id[record_id]["meta"]
    refs = set(list_value(meta, "source_refs"))
    for ref in list(refs):
        if ref in raw_by_id:
            refs.update(expand_refs(ref, raw_by_id, seen))
    return refs


def source_matches_ref(reference: str, relative: str) -> bool:
    if source_ref_matches(reference, relative):
        return True
    ref = reference.replace("\\", "/").strip().casefold()
    path = relative.casefold()
    name = Path(relative).name.casefold()
    stem = Path(relative).stem.casefold()
    return ref == path or ref == name or ref == stem or ref.endswith("/" + name)


def snapshot() -> dict:
    raw_rows = load_records()
    raw_by_id = {row["meta"].get("id"): row for row in raw_rows if row["meta"].get("id")}
    inverse_replacements: dict[str, list[str]] = defaultdict(list)
    for record_id, row in raw_by_id.items():
        meta = row["meta"]
        for old_id in list_value(meta, "supersedes") + list_value(meta, "superseded_by"):
            if old_id in raw_by_id:
                inverse_replacements[old_id].append(record_id)

    records: list[dict] = []
    for record_id, row in raw_by_id.items():
        meta, body = row["meta"], row["body"]
        role = meta.get("record_role") or "personal_memory"
        domains = [item for item in list_value(meta, "domain") if item.startswith("domain.")]
        domains += [item for item in list_value(meta, "parent_ids") if item.startswith("domain.")]
        domains = list(dict.fromkeys(domains)) or [OTHER_ID]
        relations = {field: list_value(meta, field) for field in RELATION_FIELDS}
        records.append({
            "id": record_id,
            "title": title_for(meta, body),
            "summary": clean_text(body, 620),
            "body": body,
            "kind": meta.get("kind", "unknown"),
            "status": meta.get("status", "unknown"),
            "role": role,
            "is_source_material": role == "source_material",
            "confidence": meta.get("confidence", ""),
            "sensitivity": meta.get("sensitivity", ""),
            "domains": domains,
            "date": meta.get("valid_from") or meta.get("last_confirmed") or "",
            "valid_from": meta.get("valid_from", ""),
            "last_confirmed": meta.get("last_confirmed", ""),
            "applies_when": meta.get("applies_when", ""),
            "aliases": list_value(meta, "aliases"),
            "source_refs": sorted(expand_refs(record_id, raw_by_id)),
            "relations": relations,
            "replaced_by": list(dict.fromkeys(inverse_replacements.get(record_id, []))),
            "record_path": rel(row["path"]),
        })
    record_by_id = {record["id"]: record for record in records}

    branches = []
    for row in load_branches():
        meta, body = row["meta"], row["body"]
        branch_id = meta.get("id")
        if not branch_id:
            continue
        heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), branch_id)
        branches.append({"id": branch_id, "label": heading, "priority": int(meta.get("priority", "0") or 0)})
    branches.sort(key=lambda item: (-item["priority"], item["id"]))
    branches.append({"id": OTHER_ID, "label": OTHER_LABEL, "priority": 0})
    known_domains = {branch["id"] for branch in branches}
    for branch in branches:
        assigned = [record for record in records if branch["id"] in record["domains"]]
        branch["counts"] = {
            "current": sum(record["status"] == "current" for record in assigned),
            "all": len(assigned),
            "events": sum(record["kind"] in {"event", "decision"} and not record["is_source_material"] for record in assigned),
        }

    source_rows = []
    for path in all_source_files():
        relative = rel(path)
        linked = [record["id"] for record in records if any(source_matches_ref(ref, relative) for ref in record["source_refs"])]
        warnings = []
        typ = source_type(path)
        if typ == "User verbatim":
            warnings.append("User verbatim is immutable; derived summaries cannot replace this source.")
        if typ in {"Image", "OCR"}:
            warnings.append("For exact quotes, check the original image; OCR may be wrong.")
        if typ == "External conversation":
            warnings.append("AI analysis inside a chat does not automatically equal user fact.")
        source_rows.append({
            "id": "source." + re.sub(r"[^a-z0-9._-]+", "-", relative.casefold()).strip("-"),
            "path": relative,
            "title": source_display_title(path),
            "filename": path.name,
            "type": typ,
            "group": source_group(path),
            "date": source_date(path),
            "record_ids": linked,
            "warnings": warnings,
            "size": path.stat().st_size,
        })

    edges, seen = [], set()
    for record in records:
        for domain in record["domains"]:
            if domain in known_domains:
                key = (domain, record["id"], "membership")
                if key not in seen:
                    edges.append({"source": domain, "target": record["id"], "type": "membership"}); seen.add(key)
        for relation, targets in record["relations"].items():
            for target in targets:
                if target in record_by_id:
                    key = (record["id"], target, relation)
                    if key not in seen:
                        edges.append({"source": record["id"], "target": target, "type": relation}); seen.add(key)

    personal_events = [record for record in records if not record["is_source_material"] and record["kind"] in {"event", "decision", "state"}]
    personal_events.sort(key=lambda item: (item["date"], item["id"]), reverse=True)
    domain_link_counts: dict[tuple[str, str], int] = defaultdict(int)
    domain_link_examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    for edge in edges:
        if edge["type"] == "membership":
            continue
        left, right = record_by_id.get(edge["source"]), record_by_id.get(edge["target"])
        if not left or not right:
            continue
        for first in left["domains"]:
            for second in right["domains"]:
                if first == second or first not in known_domains or second not in known_domains:
                    continue
                key = tuple(sorted((first, second)))
                domain_link_counts[key] += 1
                for candidate in (left["id"], right["id"]):
                    if candidate not in domain_link_examples[key] and not record_by_id[candidate]["is_source_material"]:
                        domain_link_examples[key].append(candidate)
    domain_links = [
        {"source": first, "target": second, "weight": weight, "example_ids": domain_link_examples[(first, second)][:3]}
        for (first, second), weight in domain_link_counts.items()
    ]
    missing_refs = sorted({ref for record in records for ref in record["source_refs"] if ref.startswith("sources/") and not any(source_matches_ref(ref, source["path"]) for source in source_rows)})
    v2 = load_v2()
    v2["audit"] = v2_audit()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": {
            "records": len(records), "current": sum(record["status"] == "current" for record in records),
            "sources": len(source_rows), "unclassified": sum(OTHER_ID in record["domains"] for record in records),
            "source_material": sum(record["is_source_material"] for record in records),
            "uncertain": sum(record["status"] == "uncertain" for record in records),
            "superseded": sum(record["status"] == "superseded" for record in records),
        },
        "branches": branches, "records": records, "sources": source_rows, "edges": edges, "domain_links": domain_links,
        "recent": personal_events[:30], "missing_source_refs": missing_refs,
        "root_structure": [{"name": name, "role": role, "files": sum(1 for child in (ROOT / name).rglob("*") if child.is_file()) if (ROOT / name).exists() else 0} for name, role in ROOT_ROLES.items()],
        "v2": v2,
    }


def inside_root(relative: str) -> Path | None:
    candidate = (ROOT / relative).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD), **kwargs)

    def json(self, value: object, status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/snapshot":
            self.json(snapshot()); return
        if parsed.path == "/api/tree":
            relative = parse_qs(parsed.query).get("path", [""])[0]
            payload = tree(relative)
            self.json(payload, 404 if "error" in payload else 200); return
        if parsed.path == "/api/file":
            relative = parse_qs(parsed.query).get("path", [""])[0]
            path = inside_root(relative)
            if not path:
                self.json({"error": "Path not allowed"}, 403); return
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                self.json({"path": relative, "binary": True, "content": "This is a binary file; view the original under sources/."}); return
            self.json({"path": relative, "binary": False, "content": content}); return
        if parsed.path in {"", "/"}:
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PERSONAL_UNDERSTANDING_PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Personal understanding: {url}")
    if not args.no_browser:
        threading.Timer(.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
