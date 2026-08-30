#!/usr/bin/env python3
"""Validate v2 structure, provenance, relations, and migration debt."""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()
import argparse, json, re
from pathlib import Path
from source_audit import audit_records
from v2_archive import v2_audit
from derivation_ledger import audit_ledger

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SKILL_FIELDS = {"name", "description", "version"}
REQUIRED_RECORD_FIELDS = {"id", "kind", "status", "confidence", "sensitivity", "source_refs"}
VALID_KINDS = {"fact", "state", "event", "preference", "rule", "heuristic", "value", "decision", "model", "entity"}
VALID_STATUS = {"current", "superseded", "uncertain", "archived", "deleted"}
ROUTING_KINDS = {"state", "decision", "model", "value", "heuristic", "rule", "preference"}


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines(); result = {}
    if not lines or lines[0].strip() != "---": return result
    for line in lines[1:]:
        if line.strip() == "---": break
        if ":" in line:
            key, value = line.split(":", 1); result[key.strip()] = value.strip()
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--strict", action="store_true"); ap.add_argument("--json", action="store_true"); ap.add_argument("--require-closed-captures", action="store_true", help="fail when there are pending/untracked captures"); args = ap.parse_args()
    errors: list[str] = []; warnings: list[str] = []
    meta = frontmatter(ROOT / "SKILL.md")
    missing = REQUIRED_SKILL_FIELDS - meta.keys()
    if missing: errors.append(f"SKILL.md missing frontmatter: {sorted(missing)}")
    if meta.get("name") != "personal-understanding": errors.append("SKILL.md name must be personal-understanding")
    if meta.get("version") != "2.1.0": errors.append("SKILL.md version must be 2.1.0")
    version_file = ROOT / "VERSION"
    if not version_file.exists() or version_file.read_text(encoding="utf-8").strip() != "2.1.0": errors.append("VERSION must be 2.1.0")
    branches_dir = ROOT / "memory" / "branches"; branch_ids: set[str] = set()
    if not branches_dir.is_dir(): errors.append("missing directory: memory/branches")
    else:
        for branch_path in sorted(branches_dir.glob("*.md")):
            if branch_path.name == "index.md": continue
            branch_data = frontmatter(branch_path); branch_id = branch_data.get("id", "")
            if not branch_id.startswith("domain."): errors.append(f"{branch_path.name}: branch id must start with domain.")
            branch_ids.add(branch_id)
    ids: dict[str, Path] = {}; records = sorted((ROOT / "memory" / "records").glob("*.md")); legacy_verbatim_debt: list[str] = []
    for path in records:
        data = frontmatter(path); missing = REQUIRED_RECORD_FIELDS - data.keys()
        if missing: errors.append(f"{path.name} missing fields: {sorted(missing)}")
        record_id = data.get("id", "")
        if record_id in ids: errors.append(f"duplicate record id {record_id}: {ids[record_id].name} and {path.name}")
        ids[record_id] = path
        if data.get("kind") not in VALID_KINDS: errors.append(f"{path.name}: invalid kind {data.get('kind')}")
        if data.get("status") not in VALID_STATUS: errors.append(f"{path.name}: invalid status {data.get('status')}")
        if data.get("domain") and data.get("domain") not in branch_ids: errors.append(f"{path.name}: unknown domain {data.get('domain')}")
        if data.get("status") == "current" and data.get("kind") in ROUTING_KINDS and not data.get("domain"): errors.append(f"{path.name}: current routing record requires a domain")
        if data.get("kind") == "model" and data.get("status") == "current" and not data.get("supports"): warnings.append(f"{path.name}: current model has no explicit supports evidence")
        if not re.match(r"^[a-z0-9][a-z0-9._-]+$", record_id): errors.append(f"{path.name}: invalid id {record_id!r}")
        if "current-conversation" in re.split(r"[;,]", data.get("source_refs", "")) and not data.get("verbatim_refs"):
            legacy_verbatim_debt.append(data.get("id", path.name))
    if legacy_verbatim_debt:
        warnings.append(f"legacy current-conversation without verbatim capture: {len(legacy_verbatim_debt)} record(s); the old summaries are kept as summary_only and the verbatim text cannot be conjured back.")
    for issue in audit_records(): warnings.append(f"{issue['id']}: unresolved source_refs {', '.join(issue['unresolved_refs'])}")
    known_ids = set(ids) | branch_ids; directional: dict[str, set[str]] = {record_id: set() for record_id in ids}
    for path in records:
        data = frontmatter(path)
        for relation_field in ("parent_ids", "related_ids", "supports", "contradicts", "supersedes"):
            for related_id in re.split(r"[;,]", data.get(relation_field, "")):
                related_id = related_id.strip()
                if not related_id or related_id.lower() in {"none", "null"}: continue
                if related_id not in known_ids: warnings.append(f"{path.name}: unresolved {relation_field} reference {related_id}")
                elif related_id in ids and relation_field in {"parent_ids", "supersedes"}: directional[data.get("id", "")].add(related_id)
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(record_id: str, path: list[str]) -> None:
        if record_id in visiting: errors.append("relation cycle detected: " + " -> ".join(path + [record_id])); return
        if record_id in visited: return
        visiting.add(record_id)
        for target in directional.get(record_id, set()): visit(target, path + [record_id])
        visiting.remove(record_id); visited.add(record_id)
    for record_id in directional: visit(record_id, [])
    for required in ["references", "memory", "memory/branches", "memory/v2", "sources", "sources/conversation", "scripts", "migrations"]:
        if not (ROOT / required).is_dir(): errors.append(f"missing directory: {required}")
    v2 = v2_audit(strict=False)
    for item in v2.get("errors", []): errors.append("v2: " + json.dumps(item, ensure_ascii=False))
    for item in v2.get("warnings", []): warnings.append("v2: " + json.dumps(item, ensure_ascii=False))
    derivation = audit_ledger(ROOT)
    for item in derivation.get("errors", []): errors.append("derivation: " + json.dumps(item, ensure_ascii=False))
    closure_codes = {"capture-pending-derivation", "capture-untracked"}
    for item in derivation.get("warnings", []):
        rendered = "derivation: " + json.dumps(item, ensure_ascii=False)
        if args.require_closed_captures and item.get("code") in closure_codes:
            errors.append(rendered)
        else:
            warnings.append(rendered)
    warnings = list(dict.fromkeys(warnings)); errors = list(dict.fromkeys(errors))
    status = "failed" if errors else ("warnings" if warnings else "clean")
    result = {"version": "2.1.0", "status": status, "records": len(records), "unique_ids": len(ids), "errors": errors, "warnings": warnings, "v2": v2, "derivation": derivation}
    if args.json: print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if errors: print("Validation failed")
        elif warnings: print(f"Validation finished: structure usable, but {len(warnings)} warning(s) present")
        else: print(f"Validation passed: {len(records)} records, {len(ids)} unique IDs")
        if errors: print("\n".join(f"- {x}" for x in errors))
        if warnings: print("Warnings\n" + "\n".join(f"- {x}" for x in warnings[:80]))
    if errors: return 1
    if args.strict and warnings: return 2
    return 0


if __name__ == "__main__": raise SystemExit(main())
