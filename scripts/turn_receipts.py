#!/usr/bin/env python3
"""Persistent, content-first preflight receipts for personal turns."""
from __future__ import annotations
import hashlib, json, re, uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from storage import atomic_write_text, mutation_lock

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
EXPLICIT = ("记住", "归档", "存下来", "个人理解", "我的档案", "我为什么会", "我怎么会这样")
MARKERS = ("经历", "发生", "以前", "后来", "当时", "最近", "今天", "昨天", "玩到", "看完", "遇到", "感觉", "感到", "觉得", "害怕", "恶心", "难过", "开心", "焦虑", "生气", "委屈", "思考", "喜欢", "讨厌", "偏好", "决定", "选择", "拒绝", "后悔", "朋友", "家人", "同学", "老师", "学校", "工作", "身体", "恋爱", "父母", "自己", "室友", "吵架", "分手", "痘痘", "好丧", "很丧", "挺丧", "emo", "低落")
# STRONG_MARKERS fire without a first-person pronoun (2.5.0 §8): Chinese routinely
# drops the subject ("最近状态不太好", "下巴冒痘了挺烦"), and the old first-AND-marker
# rule missed exactly the抒情感慨/状态更新 turns the two-tier design most wants.
# Membership criterion: an affect/self-state word a real technical or FAQ turn
# would essentially never contain. Deliberately conservative — 崩溃/压力-style words
# that double as tech jargon stay OUT (a missed low-signal turn is recoverable via
# the tier=full declaration + §8.1 upgrade path; a tech turn forced into capture is
# churn the user feels every session).
STRONG_MARKERS = ("难过", "焦虑", "委屈", "害怕", "后悔", "失眠", "烦躁", "心烦", "压抑", "孤独", "自卑", "难受", "心情", "情绪", "想哭", "哭了", "烦", "emo", "低落", "郁闷", "崩溃", "疲惫", "很丧", "好丧", "有点丧", "挺丧", "丧得", "堵得慌", "心里堵", "憋屈", "心里闷", "心累", "好累啊", "撑不住", "尴尬", "难为情", "社死", "丢人", "羞耻", "不是滋味", "诸事不顺")  # 词表法已到头的诚实边界见 SKILL 低信号节  # 低信号情感第二补充批：g03 实测"心里堵得慌"漏判后加；心累依赖 TECHNICAL 否决（写代码写得心累=技术轮）  # 丧 须多字形态："丧尸"是游戏名词（实测误触发足迹轮）
TECHNICAL = ("python", "javascript", "typescript", "代码", "配置", "报错", "bug", "mcp", "插件", "仓库", "git", "接口", "数据库", "部署")

def now_iso() -> str: return datetime.now().astimezone().isoformat(timespec="seconds")
def receipt_dir(root: Path = DEFAULT_ROOT) -> Path: return root / "memory" / "turn-receipts"
def receipt_path(turn_id: str, root: Path = DEFAULT_ROOT) -> Path: return receipt_dir(root) / f"{turn_id}.json"

VALID_TIERS = ("auto", "full", "light", "skip")

def classify_personal_turn(text: str, tier: str = "auto") -> dict[str, Any]:
    """Task form never wins over personal content: 润色 personal experience still captures.

    tier 是模型对两档调用逻辑的显式声明，只在内容分类之外生效：
    - full：完整档——内容分类漏判时的兜底，也是活动足迹轮次的入口（派生受 SKILL.md
      "足迹纪律"约束：恰好一条微型记录，查重零新增可 no-derivation 收场）。
    - skip：模型判定为跳过档，即使关键词误命中也不建 receipt 要求；被压制的内容分类
      检出会留痕在 reasons_suppressed，供事后审计（护栏：内容已检出个人材料的轮次不应声明 skip）。
    - auto：不声明，纯内容分类。
    - light：已废弃（2.4.0 两档制并入 full），枚举仅为兼容旧调用保留，传入按 full 处理。
    """
    if tier not in VALID_TIERS: raise ValueError(f"tier 不合法：{tier}；必须是 {'/'.join(VALID_TIERS)}")
    if tier == "light":
        # 2026-09-03 两档制改革：轻量档并入完整档。tier=light 枚举仅为兼容保留，
        # 声明一律按 full 处理（活动足迹轮次受 SKILL.md"足迹纪律"派生约束，不再有独立档位）。
        tier = "full"
    compact = " ".join(text.split()); reasons: list[str] = []
    if any(x in compact for x in EXPLICIT): reasons.append("explicit-memory-or-self-understanding-request")
    first = bool(re.search(r"我|本人|自己|咱们?", compact))
    if first and any(x in compact for x in MARKERS): reasons.append("first-person-experience-or-state")
    # STRONG_MARKERS fire without a first-person pronoun (2.5.0 §8): Chinese routinely
    # drops the subject ("最近状态不太好"、"下巴冒痘了挺烦"), and the old first-AND-marker
    # rule systematically missed 抒情感慨/状态更新 turns the two-tier design most wants.
    # Technical-context guard: a STRONG hit is vetoed when the turn also carries a
    # TECHNICAL token, so "这个 bug 让我很崩溃" stays technical.
    elif not first and any(x in compact for x in STRONG_MARKERS) and not any(x in compact.casefold() for x in TECHNICAL):
        reasons.append("affective-or-state-without-subject")
    if re.search(r"我.{0,12}(为什么|怎么会|是不是).{0,18}(这样|的人|性格|状态)", compact): reasons.append("self-explanation-request")
    required = bool(reasons) or tier == "full"
    suppressed: list[str] = []
    if tier == "skip":
        suppressed = reasons
        reasons = []; required = False
    if required:
        signal = "personal"
    else:
        signal = "technical" if any(x in compact.casefold() for x in TECHNICAL) else "non-personal"
    return {"requires_personal_understanding": required, "signal": signal, "tier": tier, "reasons": reasons or ["no-personal-material-detected"], "reasons_suppressed": suppressed, "required_actions": ["capture", "derive-or-close", "session-check"] if required else []}

def read_receipt(turn_id: str, root: Path = DEFAULT_ROOT) -> dict[str, Any] | None:
    try:
        data = json.loads(receipt_path(turn_id, root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError): return None

def _write(receipt: dict[str, Any], root: Path) -> None:
    atomic_write_text(receipt_path(str(receipt["turn_id"]), root), json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")

def create_receipt(text: str, *, turn_id: str | None = None, conversation_id: str | None = None, tier: str = "auto", root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    turn_id = turn_id or f"turn.{uuid.uuid4().hex}"
    if not ID_RE.fullmatch(turn_id): raise ValueError("turn_id 不合法")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with mutation_lock(root):
        old = read_receipt(turn_id, root)
        if old:
            if old.get("message_sha256") != digest: raise ValueError("同一 turn_id 不能对应不同用户消息")
            # §8.1: a re-declared tier must not be silently dropped. Upgrading a
            # turn the content classifier missed (auto→non-personal, then the model
            # declares full) must take effect on the SAME turn id — a model that
            # instead invents a fresh turn id leaks duplicate receipts. Downgrades
            # stay refused: suppressing already-detected personal material with
            # skip is the guardrail the receipt trail exists to catch.
            decision = classify_personal_turn(text, tier=tier)
            if bool(decision["requires_personal_understanding"]) == bool(old.get("requires_personal_understanding")):
                return old
            if not decision["requires_personal_understanding"]:
                raise ValueError("同一 turn 已有需要捕获的 receipt，拒绝降级为 skip/非个人；压制行为应发生在 preflight 之前")
            receipt = {**old, **decision, "capture_status": "required", "closure_status": "required",
                       "tier_upgraded_at": now_iso(), "tier_upgraded_from": old.get("tier")}
            _write(receipt, root); return receipt
        decision = classify_personal_turn(text, tier=tier)
        receipt = {"schema_version": "1.1.1", "turn_id": turn_id, "created_at": now_iso(), "conversation_id": conversation_id or None, "message_sha256": digest, **decision, "capture_id": None, "capture_ids": [], "capture_status": "required" if decision["requires_personal_understanding"] else "not-required", "closure_status": "required" if decision["requires_personal_understanding"] else "not-required"}
        _write(receipt, root); return receipt

def mark_captured(turn_id: str, capture_id: str, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    with mutation_lock(root):
        receipt = read_receipt(turn_id, root)
        if not receipt: raise ValueError("turn receipt 不存在；必须先运行 preflight")
        if not receipt.get("requires_personal_understanding"): raise ValueError("本 turn 不应写入个人档案")
        # 一个 turn 可绑定多个 immutable capture（正文 + N 个附件是同一轮对话的常态）。
        ids = list(receipt.get("capture_ids") or [])
        first = receipt.get("capture_id")
        if first and first not in ids:
            ids.insert(0, first)
        if capture_id not in ids:
            ids.append(capture_id)
        receipt.update({"capture_id": ids[0], "capture_ids": ids, "capture_status": "captured", "closure_status": "pending", "captured_at": now_iso()})
        _write(receipt, root); return receipt

def mark_closed_for_capture(capture_id: str, status: str, root: Path = DEFAULT_ROOT) -> None:
    with mutation_lock(root):
        for path in receipt_dir(root).glob("*.json"):
            receipt = read_receipt(path.stem, root)
            ids = set(receipt.get("capture_ids") or []) | {receipt.get("capture_id")}
            if receipt and capture_id in ids:
                receipt.update({"closure_status": status, "closed_at": now_iso()}); _write(receipt, root)

def audit_turn(turn_id: str, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    receipt = read_receipt(turn_id, root)
    if not receipt: return {"pass": False, "code": "turn-receipt-missing", "turn_id": turn_id}
    if not receipt.get("requires_personal_understanding"): return {"pass": True, "turn_id": turn_id, "receipt": receipt}
    if not receipt.get("capture_id") or receipt.get("capture_status") != "captured": return {"pass": False, "code": "required-turn-not-captured", "turn_id": turn_id, "receipt": receipt}
    if receipt.get("closure_status") not in {"derived", "no-derivation-needed"}: return {"pass": False, "code": "required-turn-not-closed", "turn_id": turn_id, "receipt": receipt}
    # 2026-09-03 两档制改革：已移除 light-tier-requires-derived-record 门禁。
    # 轻量档已并入完整档；查重零新增时以 no-derivation-needed 收尾（reason 须写明命中的既有记录）是合法闭环。
    return {"pass": True, "turn_id": turn_id, "receipt": receipt}
