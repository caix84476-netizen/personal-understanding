"""Shared command-line runtime behavior for the Skill."""
from __future__ import annotations

import sys


def configure_utf8_stdio() -> None:
    """Make JSON and Chinese text stable across Windows console code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass


class CliReadGateError(Exception):
    """Raised when a CLI read is not cleared to run (mirrors the MCP capture gate)."""


def declare_maintenance_read(argv: list[str]) -> list[str]:
    """Automatic key for non-conversational callers (2.5.0 §6.5).

    Internal maintenance tools (review passes, dashboards, test drivers) must
    never hand-assemble --maintenance and risk forgetting it: they append this
    single argument to the child argv right after the script name. Reads that go
    through require_cli_capture with the flag set are audited maintenance reads.
    """
    argv = list(argv)
    for index, item in enumerate(argv):
        if item.endswith(("retrieve_v2.py", "catalog_context.py")):
            return argv[: index + 1] + ["--maintenance"] + argv[index + 1 :]
    return argv + ["--maintenance"]


def require_cli_capture(capture_id: str, *, maintenance: bool, root) -> str:
    """Align the CLI read gate with the MCP one (2.5.0 §6.5).

    Interactive reads go through MCP, which already refuses to read until the
    current turn's verbatim capture exists. The CLI had no such check, so the
    "capture-before-read" discipline only held on the front door. Now the CLI
    enforces it too, with one deliberate escape valve so maintenance/CI/tests
    — which have no user turn to capture — keep working:

    - ``--maintenance`` is the "key". It marks a non-conversational read (a
      rebuild audit, a review pass, a test) and skips the capture requirement.
      This is the automatic-key the internal tools reach for; there is nothing
      to forget because the wrapper passes it for them.
    - a real ``--capture-id`` must exist in the ledger; a made-up one is refused
      the same way MCP refuses it (closes the "CLI can't tell a bogus capture"
      hole, and MCP now forwards the id it already validated upstream).

    Deliberately a soft contract, not a fail-closed coercion of model behavior
    (hard constraint #1): a conversational turn reading the archive *should*
    have captured first, and the gate makes the honest path the easy path, but
    a maintainer can always read with an explicit, audited ``--maintenance``.
    """
    from pathlib import Path
    if maintenance:
        return "maintenance"
    capture_id = str(capture_id or "").strip()
    if not capture_id:
        raise CliReadGateError(
            "拒绝读取：CLI 读取须先完成本轮原话捕获并提供 --capture-id（与 MCP 一致）；"
            "无对话轮次的维护/测试/审计读取请显式声明 --maintenance。"
        )
    from derivation_ledger import discover_captures
    if capture_id not in discover_captures(Path(root)):
        raise CliReadGateError(f"拒绝读取：capture_id 不存在：{capture_id}。先保存原话或附件，或声明 --maintenance。")
    return "captured"
