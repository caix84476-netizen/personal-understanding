# -*- coding: utf-8 -*-
"""MCP stdio round-trip test against the sandbox server. Mechanical driver; grading is human/model."""
import json, subprocess, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent

p = subprocess.Popen([sys.executable, str(ROOT/"scripts"/"mcp_server.py")],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", cwd=ROOT)

def send(obj):
    p.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n"); p.stdin.flush()

def read_msg():
    line = p.stdout.readline()
    return json.loads(line) if line.strip() else None

rid = 0
def rpc(method, params=None):
    global rid; rid += 1
    send({"jsonrpc":"2.0","id":rid,"method":method,"params":params or {}})
    while True:
        m = read_msg()
        if m is None: raise RuntimeError("server closed; stderr:\n"+p.stderr.read()[:800])
        if m.get("id") == rid: return m
        # ignore notifications

def tool(name, args):
    r = rpc("tools/call", {"name": name, "arguments": args})
    if "error" in r: return {"rpc_error": r["error"]}
    c = r["result"]["content"][0]["text"]
    try: c = json.loads(c)
    except Exception: pass
    return {"isError": r["result"].get("isError"), "content": c}

out = {}
init = rpc("initialize", {"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"audit","version":"0"}})
out["server"] = init["result"]["serverInfo"]
tools = rpc("tools/list")["result"]["tools"]
out["n_tools"] = len(tools)

MSG = "今天有点丧，但想到马上能跟室友开黑CS2就好点了"
t = tool("personal_preflight_turn", {"text": MSG, "tier": "full"})
turn = t["content"]["turn_id"]
out["preflight"] = {"turn": turn[:14], "signal": t["content"]["signal"]}

c = tool("personal_capture_user_turn", {"capture_id": turn, "turn_id": turn, "text": MSG})
out["capture"] = c["content"].get("status") if isinstance(c["content"], dict) else str(c["content"])[:80]

cat = tool("personal_catalog", {"capture_id": turn, "view": "survey", "query": "CS2 室友 开黑"})
out["catalog"] = "ok" if isinstance(cat["content"], dict) and cat["content"].get("v2") else str(cat["content"])[:120]

ret = tool("personal_retrieve", {"capture_id": turn, "query": "CS2 steam 开黑 室友", "level": "probe"})
tl = ret["content"].get("timeline", []) if isinstance(ret["content"], dict) else []
out["retrieve_top3"] = [e.get("record_id") or e.get("id") for e in tl[:3]]

ar = tool("personal_add_record", {"capture_id": turn, "id": "state.games.cs2-anticipation-mcp-202609",
    "kind": "state", "summary": "2026-09 用户期待到校后与室友开黑 CS2（未下载未购买），情绪调节用途。",
    "salience": 1, "tier": "light", "domain": "domain.learning-interests", "confidence": "high",
    "entity_refs": "entity.game.steam-library", "source_refs": f"sources/conversation/{turn}.txt",
    "verbatim_refs": f"fragment.capture.{turn}"})
out["add_record"] = str(ar["content"])[:100] + (" | isError=" + str(ar["isError"]))

hyp = tool("personal_add_hypothesis", {"id": "hyp.mcp-audit-test-20260904",
    "claim": "游戏社交预期可作为情绪调节入口（MCP 审计测试假设）",
    "mechanism": "预期与室友开黑 → 情绪改善", "supports": ["state.games.cs2-anticipation-mcp-202609"],
    "confidence": "low"})
out["add_hypothesis"] = str(hyp["content"])[:80] + (" | isError=" + str(hyp["isError"]))

fb = tool("personal_add_feedback", {"feedback_id": "fb.mcp-audit-20260904", "outcome": "unclear",
    "memory_ids": "state.games.cs2-anticipation-mcp-202609", "note": "MCP 审计测试反馈"})
out["add_feedback"] = str(fb["content"])[:80] + (" | isError=" + str(fb["isError"]))

fin = tool("personal_finalize_capture", {"capture_id": turn, "disposition": "derived", "reason": "MCP 审计轮闭环"})
out["finalize"] = str(fin["content"])[:60] + (" | isError=" + str(fin["isError"]))

ds = tool("personal_derivation_status", {})
out["derivation_status"] = str(ds["content"])[:100]

sc = tool("personal_session_check", {"turn_id": turn, "allow_warnings": True})
out["session_check"] = str(sc["content"])[:120] + (" | isError=" + str(sc["isError"]))

val = tool("personal_validate", {"strict": False})
out["validate"] = str(val["content"])[:100]

p.stdin.close(); p.terminate()
print(json.dumps(out, ensure_ascii=False, indent=1))
