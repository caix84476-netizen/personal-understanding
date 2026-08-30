#!/usr/bin/env python3
"""Personal-understanding backup: working archive (preview) + archived snapshot (stable).

Model (as defined by the user on 2026-08-29):
- Working archive: the living archive, improving all the time;
- Archived snapshot (fixed filename, overwrites the old zip, no accumulating
  snapshots): the "known-good" rollback point. The criterion is not "content
  unchanged" but "works fine in use": when more than refresh_after_days days
  (default 7) have passed since the last packaging and structural validation
  passes (the certification test), the current working archive is zipped into
  a new snapshot; if the working archive has not changed at all, no re-zipping
  (saves bandwidth).
- Cloud (a WebDAV cloud drive via rclone): each run incrementally pushes
  "working archive + archived snapshot" (overwrite update), no resident daemon;
  skipped when rclone_remote is not configured;
- USB mirror is off by default (manual copying); with usb_mirror=true the
  backup also incrementally updates the working archive to a removable drive.

This script only writes backups/ itself and never touches archive content such
as memory/ or sources/.
"""
from __future__ import annotations
from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import string
import subprocess
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BACKUPS = ROOT / "backups"
CONFIG = ROOT / "memory" / "backup-config.json"
STATE = ROOT / "memory" / "backup-state.json"
BACKUP_DUE_DAYS = 7
STABLE_ZIP = "personal-understanding-stable.zip"
STABLE_MANIFEST = "personal-understanding-stable.json"
PREVIOUS_ZIP = "personal-understanding-previous.zip"
PREVIOUS_MANIFEST = "personal-understanding-previous.json"
DRIVE_REMOVABLE = 2  # GetDriveTypeW: DRIVE_REMOVABLE

INCLUDE_DIRS = ("memory", "sources", "references", "scripts", "migrations", "dashboard", "agents", "tests")
INCLUDE_FILES = ("SKILL.md", "VERSION", "CHANGELOG.md", "open-dashboard.cmd", "register-mcp.cmd", "README.md")


def load_backup_config() -> dict:
    if not CONFIG.exists():
        return {}
    try:
        value = json.loads(CONFIG.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def snapshot_paths(source_root: Path = ROOT) -> list[Path]:
    paths: list[Path] = []
    for name in INCLUDE_DIRS:
        base = source_root / name
        if not base.is_dir():
            continue
        paths.extend(path for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    for name in INCLUDE_FILES:
        path = source_root / name
        if path.is_file():
            paths.append(path)
    return sorted(set(paths))


def archive_fingerprint(source_root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for path in snapshot_paths(source_root):
        digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def stable_zip_path() -> Path:
    return BACKUPS / STABLE_ZIP


def backup_age_days() -> int | None:
    """Days since the last stable-snapshot certification; None if never certified."""
    stable = stable_zip_path()
    if not stable.exists():
        return None
    newest = datetime.fromtimestamp(stable.stat().st_mtime)
    return (datetime.now() - newest).days


def _days_since(value: str | None, today: date) -> int | None:
    if not value:
        return None
    try:
        return (today - date.fromisoformat(str(value)[:10])).days
    except ValueError:
        return None


def should_promote(state: dict, fingerprint: str, today: date, config: dict) -> tuple[bool, str]:
    """Snapshot refresh decision: promote a new version once the window elapses (passing validation is a hard gate); skip when the working archive is unchanged."""
    refresh_after = int(config.get("refresh_after_days", 7))
    if not stable_zip_path().exists():
        return True, "no-zip-yet"
    if state.get("body_fingerprint") == fingerprint:
        return False, "body-unchanged-zip-already-current"
    promoted_age = _days_since(state.get("promoted_at"), today)
    if promoted_age is None:
        return True, "no-promotion-record"
    if promoted_age >= refresh_after:
        return True, f"zip-{promoted_age}-days-old"
    return False, "waiting-refresh-window"


def validation_gate() -> tuple[bool, str]:
    """Certification test: promoting a stable snapshot requires structural validation to not be failed."""
    proc = subprocess.run([sys.executable, str(SCRIPTS / "validate_memory.py"), "--json"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, f"validate output not parseable: {(proc.stderr or proc.stdout)[:150]}"
    if data.get("status") == "failed":
        return False, f"validate failed: {len(data.get('errors', []))} errors, not promoting"
    return True, data.get("status", "unknown")


def promote_stable(source_root: Path = ROOT, backups_dir: Path | None = None) -> dict:
    """Certify the current working archive as the new archived snapshot; the previous snapshot is kept for one generation (previous), capped at two files."""
    backups = backups_dir or BACKUPS
    ok, gate = validation_gate()
    if not ok:
        return {"promoted": False, "reason": gate}
    paths = snapshot_paths(source_root)
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / STABLE_ZIP
    previous = backups / PREVIOUS_ZIP
    if target.exists():
        # Keep the previous snapshot for one generation: the copy that is always
        # one version behind the working archive
        shutil.copy2(target, previous)
        if (backups / STABLE_MANIFEST).exists():
            shutil.copy2(backups / STABLE_MANIFEST, backups / PREVIOUS_MANIFEST)
    digests: dict[str, str] = {}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            arcname = path.relative_to(source_root).as_posix()
            data = path.read_bytes()
            digests[arcname] = hashlib.sha256(data).hexdigest()
            zf.writestr(arcname, data)
    manifest = {
        "promoted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": len(paths),
        "total_bytes": sum(p.stat().st_size for p in paths),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "member_count": len(digests),
    }
    write_text_atomic(backups / STABLE_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"promoted": True, "reason": "validated-and-promoted", "zip": target.name, "files": len(paths), "sha256": manifest["sha256"], "previous_kept": previous.exists()}


def verify_stable() -> tuple[bool, str]:
    stable = stable_zip_path()
    if not stable.exists():
        return False, "no stable zip"
    manifest_path = BACKUPS / STABLE_MANIFEST
    if not manifest_path.exists():
        return False, "no stable manifest"
    try:
        expected = json.loads(manifest_path.read_text(encoding="utf-8")).get("sha256")
    except (OSError, json.JSONDecodeError):
        return False, "manifest unreadable"
    actual = hashlib.sha256(stable.read_bytes()).hexdigest()
    return (actual == expected), ("sha256-match" if actual == expected else "sha256-mismatch")


def removable_drives() -> list[Path]:
    found = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not os.path.exists(root):
            continue
        if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_REMOVABLE:
            found.append(Path(root))
    return found


def mirror_target(override: str = "", config: dict | None = None) -> Path | None:
    """Optional full-archive mirror location: --also-to > backup-config.json > environment variable > USB drive."""
    config = config if config is not None else load_backup_config()
    value = str(override or "").strip()
    if not value:
        value = str(config.get("mirror_to") or "")
    if not value:
        value = os.environ.get("PERSONAL_BACKUP_MIRROR", "")
    if value.strip():
        return Path(value.strip())
    if config.get("usb_mirror"):
        wanted = str(config.get("usb_volume_label") or "").strip().casefold()
        for drive in removable_drives():
            if not wanted:
                return drive
            volume = ctypes.create_unicode_buffer(64)
            if ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(str(drive)), volume, 64, None, None, None, None, 0) and volume.value.strip().casefold() == wanted:
                return drive
    return None


def mirror_body(target: Path, source_root: Path = ROOT) -> dict:
    """Incrementally mirror the full archive to target (copy only changed files; delete files that no longer exist in the source)."""
    dest_root = target / "personal-understanding-archive"
    copied = skipped = 0
    for src in snapshot_paths(source_root):
        rel = src.relative_to(source_root)
        dst = dest_root / rel
        try:
            same = dst.exists() and dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime == src.stat().st_mtime
        except OSError:
            same = False
        if same:
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    removed_stale = 0
    for dst in list(dest_root.rglob("*")):
        if dst.is_file():
            rel = dst.relative_to(dest_root)
            if not (source_root / rel).exists():
                dst.unlink()
                removed_stale += 1
    return {"target": str(dest_root), "copied": copied, "unchanged": skipped, "removed_stale": removed_stale}


def rclone_executable(config: dict) -> str | None:
    configured = str(config.get("rclone_path") or "").strip()
    if configured and Path(configured).exists():
        return configured
    return shutil.which("rclone")


def rclone_push(remote: str, config: dict) -> str:
    """Push the archived snapshot (stable + previous) to the cloud as an
    overwrite update, no accumulating history.

    Pushes only the few files under backups/ instead of the whole working
    archive directory: a WebDAV cloud drive (via rclone) rate-limits WebDAV
    request frequency and hundreds of small files would hit that limit; the
    zip itself is a complete copy of the working archive, so recovery =
    download + unzip.
    """
    exe = rclone_executable(config)
    if not exe:
        return "skipped: rclone not found"
    if not stable_zip_path().exists():
        return "skipped: archived snapshot does not exist yet"
    try:
        proc = subprocess.run(
            [exe, "copy", str(BACKUPS), f"{remote}:personal-understanding-archive/backups", "--transfers", "4"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
        )
    except subprocess.TimeoutExpired:
        return "push timed out (900s); the next backup run will resume automatically once the network recovers"
    if proc.returncode == 0:
        return f"archived snapshot pushed to {remote}:personal-understanding-archive/backups (overwrite update)"
    return f"push failed ({proc.returncode}): {(proc.stderr or proc.stdout).strip()[:200]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--also-to", default="", help="temporarily override the full-archive mirror directory (takes priority over config)")
    ap.add_argument("--verify", action="store_true", help="verify the SHA256 of the existing stable snapshot (no packaging, no push)")
    ap.add_argument("--force-promote", action="store_true", help="skip the refresh-window decision and certify the current working archive as the new stable snapshot immediately")
    args = ap.parse_args()

    if args.verify:
        ok, detail = verify_stable()
        print(json.dumps({"verify": ok, "detail": detail}, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    today = date.today()
    config = load_backup_config()
    fingerprint = archive_fingerprint()
    state = load_state()

    due, reason = should_promote(state, fingerprint, today, config)
    if args.force_promote:
        due, reason = True, "forced"
    if reason == "body-unchanged-zip-already-current":
        promoted_note = "working archive unchanged; archived snapshot is already current — skipping re-packaging and upload"
    elif due:
        result = promote_stable()
        state["promoted_at"] = today.isoformat()
        state["body_fingerprint"] = fingerprint
        state["last_promotion_reason"] = reason
        state["last_promotion_result"] = result
        if result.get("promoted"):
            promoted_note = f"certification test passed; archived snapshot updated to the current working archive ({result['files']} files)"
        else:
            promoted_note = f"certification test failed; archived snapshot kept at the previous version: {result.get('reason')}"
    else:
        promoted_note = f"archived snapshot still within its refresh window ({reason}); the working archive keeps running as the preview"
    state["checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_text_atomic(STATE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    mirror = mirror_target(args.also_to, config)
    mirror_result = None
    mirror_error = None
    if mirror is not None:
        try:
            mirror_result = mirror_body(mirror)
        except OSError as exc:
            mirror_error = str(exc)

    rclone_remote = str(config.get("rclone_remote") or "").strip()
    rclone_status = rclone_push(rclone_remote, config) if rclone_remote else "rclone_remote not configured"
    stable = stable_zip_path()
    print(json.dumps({
        "status": "ok",
        "stable": promoted_note,
        "stable_age_days": backup_age_days(),
        "verified_stable": verify_stable()[0],
        "mirror": mirror_result,
        "mirror_error": mirror_error,
        "rclone": rclone_status,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
