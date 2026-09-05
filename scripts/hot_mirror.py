#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hot-mirror watchdog for the personal-understanding real body.

After the 2026-09-02 08:37 mass-deletion incident (whole skill tree wiped in
under a second by an unidentified client skill-reconciliation process), this
watchdog keeps a second-by-second local mirror of the whole skills tree and
auto-restores it if a mass deletion is ever detected again. Worst-case loss
window drops from "until next backup" to one mirror interval (15 min).

Modes:
  --loop       daemon mode (run via pythonw at logon, Startup VBS)
  --once       single mirror cycle (guard runs first)
  --selftest   sandbox test with dummy data; never touches real paths
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PU = "personal-understanding"
# Defaults derive from the user profile so the script ships without
# machine-specific literals; every path is overridable via env.
SRC = Path(os.environ.get("PU_SKILLS_DIR", str(Path.home() / ".codex" / "skills")))
DST = Path(os.environ.get("PU_HOT_MIRROR_DIR", str(Path.home() / ".pu-hot-mirror")))
LOG = Path(os.environ.get("PU_HOT_MIRROR_LOG", str(SRC / PU / "backups" / "hot-mirror.log")))
EXCLUDES = [".git", "__pycache__", "backups", "logs", ".pytest_cache", "node_modules"]
PU = "personal-understanding"
STATE_DIRS = ["memory", "sources"]
MIN_BASELINE = 300          # mirror must hold at least this many state files to be trusted
COLLAPSE_RATIO = 0.6        # live < 60% of mirror => mass deletion
MAX_MIRROR_AGE_H = 48       # never restore from a stale mirror
INTERVAL_S = 900


def log(msg: str, log_path: Path = LOG) -> None:
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def count_state_files(src: Path) -> int:
    n = 0
    for sd in STATE_DIRS:
        base = src / PU / sd
        if base.exists():
            for _, _, files in os.walk(base):
                n += len(files)
    return n


def robocopy_mir(src: Path, dst: Path) -> int:
    cmd = ["robocopy", str(src), str(dst), "/MIR", "/R:1", "/W:1",
           "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
    for ex in EXCLUDES:
        cmd += ["/XD", ex]
    proc = subprocess.run(cmd, capture_output=True)  # robocopy prints GBK; only exit code matters
    return proc.returncode  # 0-7 ok, >=8 failure


def read_manifest(dst: Path) -> dict | None:
    p = dst / "hot-mirror-manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_manifest(dst: Path, live: int) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "hot-mirror-manifest.json").write_text(json.dumps({
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "live_state_files": live,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def cycle(src: Path, dst: Path, log_path: Path) -> str:
    if not src.exists():
        log("INCIDENT: source tree missing entirely; restoring from mirror", log_path)
        rc = robocopy_mir(dst, src)
        log(f"restore-from-missing rc={rc}", log_path)
        return "restored-missing"

    live = count_state_files(src)
    man = read_manifest(dst)
    mirror_count = man.get("live_state_files", 0) if man else 0
    mirror_age_h = 1e9
    if man:
        try:
            t = datetime.fromisoformat(man["time"])
            mirror_age_h = (datetime.now(tz=t.tzinfo) - t).total_seconds() / 3600
        except Exception:
            pass

    trusted = mirror_count >= MIN_BASELINE and mirror_age_h <= MAX_MIRROR_AGE_H
    if trusted and live < mirror_count * COLLAPSE_RATIO:
        log(f"INCIDENT: mass deletion suspected (live={live}, mirror={mirror_count}); auto-restoring", log_path)
        rc = robocopy_mir(dst, src)
        restored = count_state_files(src)
        log(f"auto-restore rc={rc}, state files after restore={restored}", log_path)
        alert = dst.parent / "pu-watchdog-ALERT.txt"
        try:
            alert.write_text(
                f"{datetime.now().astimezone().isoformat(timespec='seconds')} watchdog auto-restored "
                f"skills tree from hot mirror (live={live} -> {restored}). See {log_path}\n", encoding="utf-8")
        except Exception:
            pass
        live = restored
        action = "auto-restored"
    else:
        action = "mirrored"

    rc = robocopy_mir(src, dst)
    if rc >= 8:
        log(f"ERROR: mirror robocopy failed rc={rc}", log_path)
        return "error"
    write_manifest(dst, live)
    log(f"{action}: state_files={live} rc={rc}", log_path)
    return action


def selftest() -> int:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="pu-wd-test-"))
    src, dst = tmp / "src", tmp / "dst"
    tlog = tmp / "test.log"
    rec = src / PU / "memory" / "records"
    sou = src / PU / "sources"
    rec.mkdir(parents=True)
    sou.mkdir(parents=True)
    (src / PU / "SKILL.md").write_text("test skill", encoding="utf-8")
    (src / "grill-me").mkdir()
    (src / "grill-me" / "SKILL.md").write_text("grill", encoding="utf-8")
    for i in range(400):
        (rec / f"record-{i:04d}.md").write_text(f"---\nid: r{i}\n---\nbody {i}", encoding="utf-8")
        (sou / f"source-{i:04d}.txt").write_text(f"source {i}", encoding="utf-8")

    # 1) first cycle mirrors
    cycle(src, dst, tlog)
    m1 = read_manifest(dst)
    assert m1 and m1["live_state_files"] == 800, f"mirror failed: {m1}"
    # 2) idempotent second cycle
    assert cycle(src, dst, tlog) == "mirrored"
    # 3) simulated mass deletion -> auto restore
    for f in sorted(rec.glob("*.md"))[:350]:
        f.unlink()
    for f in sorted(sou.glob("*.txt"))[:350]:
        f.unlink()
    action = cycle(src, dst, tlog)
    after = count_state_files(src)
    assert action == "auto-restored", f"guard did not trigger: {action}"
    assert after == 800, f"restore incomplete: {after}"
    assert (src / "grill-me" / "SKILL.md").exists()
    assert (dst.parent / "pu-watchdog-ALERT.txt").exists()
    logtxt = tlog.read_text(encoding="utf-8")
    assert "INCIDENT: mass deletion suspected" in logtxt
    shutil.rmtree(tmp, ignore_errors=True)
    print("SELFTEST PASS: mirror + idempotent cycle + mass-deletion auto-restore all verified")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.loop:
        log("watchdog loop started")
        while True:
            try:
                cycle(SRC, DST, LOG)
            except Exception as e:
                log(f"cycle error: {e}", LOG)
            time.sleep(INTERVAL_S)
    if args.once:
        cycle(SRC, DST, LOG)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
