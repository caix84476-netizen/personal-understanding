# -*- coding: utf-8 -*-
"""Compact view of retrieve_v2 probe/deep output for human (model) grading.
Mechanical extraction only: prints ranked ids + scores, never judges."""
import json, subprocess, sys, pathlib
sys.path.insert(0, "scripts")

def run(args):
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("STDERR:", r.stderr[:500]); sys.exit(1)
    return json.loads(r.stdout)

def main():
    cap = sys.argv[1]; query = sys.argv[2]; level = sys.argv[3] if len(sys.argv) > 3 else "probe"
    extra = sys.argv[4:]
    d = run(["scripts/retrieve_v2.py", "--query", query, "--level", level, "--capture-id", cap, "--format", "json"] + extra)
    tl = d.get("timeline") or []
    print(f"== timeline ({len(tl)}) ==")
    for i, e in enumerate(tl):
        fid = e.get("evidence_fidelity") or {}
        print(f"{i+1}. {e.get('record_id') or e.get('id')} | s{e.get('salience')} | {e.get('score') if e.get('score') is not None else ''} | fid={fid.get('verbatim','?')}v/{fid.get('summary_only','?')}s | {(e.get('title') or e.get('summary') or '')[:60]}")
    ent = d.get("entities") or []
    print(f"== entities ({len(ent)}) ==")
    for i, e in enumerate(ent):
        print(f"{i+1}. {e.get('record_id') or e.get('id')} | {(e.get('title') or e.get('label') or '')[:40]}")
    kn = d.get("knowledge") or []
    print(f"== knowledge ({len(kn)}) ==")
    for i, k in enumerate(kn):
        print(f"{i+1}. {k.get('record_id') or k.get('id')} | {(k.get('title') or k.get('summary') or '')[:60]}")
    fc = d.get("facets") or d.get("contexts") or []
    print(f"== facets ({len(fc)}) ==")
    for i, f in enumerate(fc[:12]):
        print(f"{i+1}. {f.get('id')} | {(f.get('title') or f.get('summary') or '')[:50]}")
    fr = d.get("fragments") or []
    print(f"== fragments ({len(fr)}) ==")
    for i, f in enumerate(fr[:8]):
        t = (f.get('text') or f.get('content') or '')
        print(f"{i+1}. {f.get('id')} | fidelity={f.get('fidelity','')} | {t[:80]}")
    if level == "deep":
        for i, f in enumerate(fr):
            t = (f.get('text') or f.get('content') or '')
            print(f"--- deep frag {i+1} {f.get('id')} ---")
            print(t[:600])

main()
