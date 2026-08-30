#!/usr/bin/env python3
"""Register the personal-understanding local MCP server across AI clients.

Usage:
  python scripts/install_mcp.py                # detect local clients and show status
  python scripts/install_mcp.py --auto         # register/update every detected client
  python scripts/install_mcp.py --client zcode # handle only the given client

Supported: zcode (~/.zcode/cli/config.json), codex (~/.codex/config.toml),
claude-code (~/.claude.json), cursor (~/.cursor/mcp.json),
generic (~/.agents/mcp.json, a cross-tool compatibility slot).

Idempotent: a no-op when already registered with a matching path; rerun after
the skill directory moves to self-heal the path. Every write backs up the
target config as <config>.bak-personal-understanding first.
"""
from __future__ import annotations

from cli_runtime import configure_utf8_stdio
configure_utf8_stdio()

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = Path(__file__).resolve().parent / "mcp_server.py"
SERVER_NAME = "personal-understanding"
HOME = Path.home()


def server_command() -> tuple[str, list[str]]:
    python = Path(sys.executable)
    if not python.exists():  # python may be uninstalled after registration; fall back to the py launcher
        return "py", ["-3", str(SERVER)]
    return str(python), [str(SERVER)]


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.bak-personal-understanding-{stamp}")
    shutil.copy2(path, target)
    return target


def backup_then_write(path: Path, content: str) -> str:
    if path.exists():
        backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {path} (previous file backed up as *.bak-personal-understanding)"


def detect_zcode() -> Path | None:
    path = HOME / ".zcode" / "cli" / "config.json"
    return path if path.exists() else None


def zcode_status(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "config unparseable"
    entry = (data.get("mcp") or {}).get("servers", {}).get(SERVER_NAME)
    return describe_entry(entry)


def register_zcode(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"skipped: config.json unparseable ({exc})"
    command, args = server_command()
    servers = data.setdefault("mcp", {}).setdefault("servers", {})
    servers[SERVER_NAME] = {"command": command, "args": args, "env": {"PYTHONUTF8": "1"}}
    return backup_then_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def detect_codex() -> Path | None:
    path = HOME / ".codex" / "config.toml"
    return path if path.exists() else None


def codex_section_pattern() -> re.Pattern:
    # From the [mcp_servers.<name>] header to the next line-start [ header or
    # end of file; a [^\[] approach would truncate at the args array.
    return re.compile(rf"(?ms)^\[mcp_servers\.{re.escape(SERVER_NAME)}\]\s*$.*?(?=^\[|\Z)")


def codex_status(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "config unreadable"
    match = codex_section_pattern().search(text)
    if not match:
        return "not registered"
    if str(SERVER) in match.group(0):
        return "registered, path matches"
    return "registered, but the path is stale (rerun to self-heal)"


def register_codex(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    command, args = server_command()
    block = (
        f"[mcp_servers.{SERVER_NAME}]\n"
        + f"command = '{command}'\n"
        + "args = [" + ", ".join(f"'{arg}'" for arg in args) + "]\n"
        + "startup_timeout_sec = 120\n"
    )
    pattern = codex_section_pattern()
    if pattern.search(text):
        # block contains Windows paths (\U would be read as a regex escape);
        # a lambda sidesteps that
        new_text = pattern.sub(lambda _match: block, text)
        action = "updated existing registration"
    else:
        new_text = text.rstrip("\n") + "\n\n" + block
        action = "added new registration"
    return action + "; " + backup_then_write(path, new_text)


def detect_json_mcp(path: Path, key_path: tuple[str, ...]) -> Path | None:
    if not path.exists():
        return None
    return path


def json_status(path: Path, key_path: tuple[str, ...]) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "config unparseable"
    for key in key_path:
        data = data.get(key) if isinstance(data, dict) else None
    return describe_entry(data)


def json_register(path: Path, key_path: tuple[str, ...], top_level_key: str) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"skipped: {path.name} unparseable ({exc})"
    command, args = server_command()
    node = data
    for key in key_path[:-1]:
        node = node.setdefault(key, {})
    servers = node.setdefault(key_path[-1], {})
    servers[SERVER_NAME] = {"command": command, "args": args, "env": {"PYTHONUTF8": "1"}}
    return backup_then_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def describe_entry(entry: object) -> str:
    if not isinstance(entry, dict):
        return "not registered"
    args = [str(item) for item in (entry.get("args") or [])]
    if any(Path(arg) == SERVER for arg in args):
        return "registered, path matches"
    return "registered, but the path is stale (rerun to self-heal)"


APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))


def json_client(config_path: Path, key_path: tuple[str, ...], label: str) -> dict:
    """Most MCP clients share the mcpServers JSON structure: appears only when the config file is detected; auto-registers."""
    return {
        "detect": lambda: config_path if config_path.exists() else None,
        "status": lambda path: json_status(path, key_path),
        "register": lambda path: json_register(path, key_path, key_path[-1]),
        "label": label,
    }


CLIENTS = {
    "zcode": {
        "detect": detect_zcode,
        "status": zcode_status,
        "register": register_zcode,
    },
    "codex": {
        "detect": detect_codex,
        "status": codex_status,
        "register": register_codex,
    },
    "claude-code": {
        "detect": lambda: detect_json_mcp(HOME / ".claude.json", ("mcpServers",)),
        "status": lambda path: json_status(path, ("mcpServers",)),
        "register": lambda path: json_register(path, ("mcpServers",), "mcpServers"),
    },
    "cursor": {
        "detect": lambda: detect_json_mcp(HOME / ".cursor" / "mcp.json", ("mcpServers",)),
        "status": lambda path: json_status(path, ("mcpServers",)),
        "register": lambda path: json_register(path, ("mcpServers",), "mcpServers"),
    },
    # Everything below is a variant of the same de-facto mcpServers JSON
    # standard; any future client that follows this structure only needs its
    # config path added to this list — no new registration logic required.
    "claude-desktop": json_client(APPDATA / "Claude" / "claude_desktop_config.json", ("mcpServers",), "Claude Desktop"),
    "vscode": json_client(APPDATA / "Code" / "User" / "mcp.json", ("servers",), "VS Code (native MCP, 1.99+)"),
    "vscode-insiders": json_client(APPDATA / "Code - Insiders" / "User" / "mcp.json", ("servers",), "VS Code Insiders"),
    "windsurf": json_client(HOME / ".codeium" / "windsurf" / "mcp_config.json", ("mcpServers",), "Windsurf"),
    "cline": json_client(APPDATA / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json", ("mcpServers",), "Cline"),
    "trae": json_client(HOME / ".trae" / "mcp.json", ("mcpServers",), "Trae"),
    "generic": {
        "detect": lambda: detect_json_mcp(HOME / ".agents" / "mcp.json", ("mcpServers",)),
        "status": lambda path: json_status(path, ("mcpServers",)),
        "register": lambda path: json_register(path, ("mcpServers",), "mcpServers"),
    },
}


def universal_block() -> dict:
    command, args = server_command()
    return {"mcpServers": {SERVER_NAME: {"command": command, "args": args, "env": {"PYTHONUTF8": "1"}}}}


def export_universal(out_dir: Path) -> list[str]:
    """Generate universal config snippets that work with any MCP client: for a new client, paste once manually."""
    out_dir.mkdir(parents=True, exist_ok=True)
    block = universal_block()
    json_path = out_dir / "mcpServers.json"
    json_path.write_text(json.dumps(block, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entry = block["mcpServers"][SERVER_NAME]
    toml = (
        f"[mcp_servers.{SERVER_NAME}]\n"
        + f"command = '{entry['command']}'\n"
        + "args = [" + ", ".join(f"'{a}'" for a in entry["args"]) + "]\n"
        + "startup_timeout_sec = 120\n"
    )
    guide = f"""# Universal MCP config snippets (personal-understanding)

MCP is a cross-vendor protocol; most clients use the same JSON for MCP config (key name mcpServers).
For a new client this installer does not cover yet:

1. Open the corresponding JSON file: {json_path}
2. Copy the whole `{SERVER_NAME}` entry into the mcpServers object of that client's config file
   (if the client uses the `servers` key name, put the entry under servers; the entry content is unchanged);
3. Restart the client session; success means personal_* tools appear in the tool list.

Entry content (generated {datetime.now():%Y-%m-%d}, pointing at the current skill location):

```json
{json.dumps(entry, ensure_ascii=False, indent=2)}
```

TOML-style clients (e.g. Codex's config.toml):

```toml
{toml}```

Common config file locations per client (Windows):
- ZCode: ~/.zcode/cli/config.json → mcp.servers
- Codex: ~/.codex/config.toml → [mcp_servers.*]
- Claude Code: ~/.claude.json → mcpServers
- Claude Desktop: %APPDATA%\\Claude\\claude_desktop_config.json → mcpServers
- VS Code: %APPDATA%\\Code\\User\\mcp.json → servers
- Cursor: ~/.cursor/mcp.json → mcpServers
- Windsurf: ~/.codeium/windsurf/mcp_config.json → mcpServers
- Cline: %APPDATA%\\Code\\User\\globalStorage\\saoudrizwan.claude-dev\\settings\\cline_mcp_settings.json
- Cross-tool compatibility slot: ~/.agents/mcp.json → mcpServers

Note: the paths are bound to this machine and this directory; after copying the skill elsewhere,
regenerate the snippets at the new location once (run
`python scripts/install_mcp.py --export-dir <dir>`), or rerun --auto.
"""
    guide_path = out_dir / "HOW-TO-ADD.md"
    guide_path.write_text(guide, encoding="utf-8")
    return [str(json_path), str(guide_path)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=sorted(CLIENTS), help="handle only the given client")
    parser.add_argument("--auto", action="store_true", help="register/update every client with a detected config")
    parser.add_argument("--export-dir", default="", help="write universal config snippets to the given directory (for new clients not covered by the installer, to paste manually)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.export_dir:
        written = export_universal(Path(args.export_dir))
        print("Universal MCP config snippets generated:")
        for item in written:
            print(f"- {item}")
        return 0

    targets = [args.client] if args.client else sorted(CLIENTS)
    report = {}
    for name in targets:
        client = CLIENTS[name]
        path = client["detect"]()
        if path is None:
            report[name] = {"config": "not detected (not installed or not initialized)", "status": "-", "action": "skipped"}
            continue
        status = client["status"](path)
        if args.auto:
            if status == "registered, path matches":
                action = "no-op (already consistent, nothing written)"
            else:
                action = client["register"](path)
            report[name] = {"config": str(path), "status": status, "action": action}
        else:
            report[name] = {"config": str(path), "status": status, "action": "(pass --auto to write)"}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"personal-understanding local MCP registrar (server: {SERVER})")
    for name, item in report.items():
        print(f"- {name}: {item['status']}; {item['config']}; {item['action']}")
    if not args.auto:
        print("Tip: pass --auto to register/update; restart the client session afterward for changes to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
