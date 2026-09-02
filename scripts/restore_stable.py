#!/usr/bin/env python3
"""从 backups/personal-understanding-stable.zip 选择性恢复本体。

背景：稳定压缩包同时包含代码与个人数据（memory/、sources/）。"本体改坏了"
多数时候只坏代码；全量解压覆盖会把快照日之后新增的个人记忆一并抹掉。
因此恢复必须分档：

- --scope code  只恢复代码与文档（SKILL.md、scripts、references 等），
                不触碰 memory/ 与 sources/；这是默认档，对应"skill 被改坏"。
- --scope data  只恢复 memory/ 与 sources/；对应"档案数据被改坏"。
                注意：快照日之后新增的捕获不在包内，先抢救再恢复。
- --scope all   全量恢复，等价于旧文档的"解压覆盖"，仅当目录整体损坏时使用。

安全机制：
1. 恢复前校验压缩包 sha256 与 manifest 是否一致，不一致直接拒绝；
2. 默认 dry-run，只报告将发生什么；--apply 才真正写盘；
3. --apply 时先把将被覆盖的现有文件快照到
   backups/pre-restore-<时间戳>/（保留相对路径），恢复本身也可逆；
4. 恢复完成后自动运行 rebuild_views.py 与 validate_memory.py 并汇报状态。

用法：
  python scripts/restore_stable.py                     # dry-run，scope=code
  python scripts/restore_stable.py --scope data        # dry-run，仅数据
  python scripts/restore_stable.py --apply --scope code
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    from cli_runtime import configure_utf8_stdio; configure_utf8_stdio()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "backups"
STABLE_ZIP = BACKUPS / "personal-understanding-stable.zip"
STABLE_MANIFEST = BACKUPS / "personal-understanding-stable.json"
DATA_PREFIXES = ("memory/", "sources/")
SCOPE_HELP = "code=仅代码与文档（默认）；data=仅 memory/ 与 sources/；all=全量"


def verify_zip() -> None:
    if not STABLE_ZIP.exists() or not STABLE_MANIFEST.exists():
        sys.exit(f"缺少压缩包或清单：{STABLE_ZIP.name} / {STABLE_MANIFEST.name}")
    expected = json.loads(STABLE_MANIFEST.read_text(encoding="utf-8")).get("sha256")
    actual = hashlib.sha256(STABLE_ZIP.read_bytes()).hexdigest()
    if expected and actual != expected:
        sys.exit(f"sha256 不匹配（manifest={expected}，实际={actual}），拒绝恢复。")
    with zipfile.ZipFile(STABLE_ZIP) as zf:
        bad = zf.testzip()
        if bad:
            sys.exit(f"压缩包成员损坏：{bad}，拒绝恢复。")


def scope_members(scope: str) -> list[str]:
    with zipfile.ZipFile(STABLE_ZIP) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    if scope == "all":
        return names
    if scope == "data":
        return [n for n in names if n.startswith(DATA_PREFIXES)]
    return [n for n in names if not n.startswith(DATA_PREFIXES)]


def plan(members: list[str]) -> tuple[list[str], list[str], list[str]]:
    """返回（将被覆盖、将新增、本地多出但不会被删除的文件）。"""
    overwrite, add, local_only = [], [], []
    zipset = set(members)
    for name in members:
        (overwrite if (ROOT / name).exists() else add).append(name)
    zip_dirs = {n.split("/")[0] for n in zipset}
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_dir() or rel.startswith("backups") or rel.startswith("logs"):
            continue
        top = rel.split("/")[0]
        if top in zip_dirs and rel not in zipset and not any(rel.startswith(x) for x in DATA_PREFIXES):
            local_only.append(rel)
    return overwrite, add, sorted(local_only)


def snapshot_before_apply(members: list[str]) -> Path | None:
    targets = [m for m in members if (ROOT / m).exists()]
    if not targets:
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS / f"pre-restore-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in targets:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    return dest


def apply(members: list[str]) -> None:
    dest = snapshot_before_apply(members)
    with zipfile.ZipFile(STABLE_ZIP) as zf:
        for name in members:
            target = ROOT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    print(f"已恢复 {len(members)} 个文件。")
    if dest:
        print(f"覆盖前的旧文件已快照到：{dest.relative_to(ROOT)}")


def post_check() -> None:
    for script, args in (("rebuild_views.py", []), ("validate_memory.py", ["--json"])):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        tail = (proc.stdout or proc.stderr).strip().splitlines()
        print(f"[{script}] rc={proc.returncode}" + (f" | {tail[-1][:120]}" if tail else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scope", choices=("code", "data", "all"), default="code", help=SCOPE_HELP)
    ap.add_argument("--apply", action="store_true", help="真正写盘；缺省为 dry-run")
    args = ap.parse_args()

    verify_zip()
    members = scope_members(args.scope)
    overwrite, add, local_only = plan(members)
    print(f"scope={args.scope}：将写入 {len(members)} 个文件"
          f"（覆盖 {len(overwrite)}，新增 {len(add)}）。")
    if local_only:
        print(f"注意：本地有 {len(local_only)} 个压缩包里没有的同目录文件，恢复不会删除它们"
              f"（示例：{local_only[:3]}）。")
    if args.scope != "code":
        print("警告：该档位会把 memory/sources 回退到压缩包快照日；快照日之后新增的捕获将不可在本目录找回。")
    if not args.apply:
        print("dry-run：未写入任何文件。确认无误后加 --apply 执行。")
        return
    apply(members)
    post_check()


if __name__ == "__main__":
    main()
