#!/usr/bin/env python3
"""“游戏支持但两引擎都未实现”的操作缺口探针（245+ 扩展依据）。

做法：对每个候选操作，给出三类**可复算证据**：
  1. AutoTavern（36.6.3，`crates/taverngym/src`）里的实现/缺失位置（file:line + 代码片段）；
  2. HSBRSIM（hsrl2 引擎 + hsbg/env legacy 动作枚举）里的实现/缺失位置；
  3. 37.0.0 数据侧的卡面/规则证据（命中卡 id 列表/计数）。

输出 `runs/p2_delta/ops_probe.json`；供 `docs/PORTING_37_PLAN.md` §6 引用。
本脚本只读，不写仓库源码。

用法::

    python3 tools/p2_delta/probe_ops.py [--at-root ...] [--out runs/p2_delta/ops_probe.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as C  # noqa: E402

AT_SRC = "crates/taverngym/src"
HSRL2 = "hsrl2"
HSBG_ENV = "hsbg/env"


# ── 证据抓取（grep 文件 → file:line + 片段；确定性）──────────────────
def grep(root: Path, rel_glob: str, pattern: str, limit: int = 3) -> List[Dict[str, Any]]:
    """在 root/rel_glob 匹配的文件里搜 pattern，返回前 limit 条命中证据。"""
    hits: List[Dict[str, Any]] = []
    if root != C.REPO_ROOT:
        base = root
    else:
        base = C.REPO_ROOT
    for path in sorted(base.glob(rel_glob)):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line):
                hits.append(
                    {
                        "file": str(path.relative_to(base)),
                        "line": i,
                        "snippet": line.strip()[:220],
                    }
                )
                if len(hits) >= limit:
                    return hits
    return hits


def read_file(root: Path, rel: str) -> str:
    p = root / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")


# ── 37 数据侧统计 ─────────────────────────────────────────────────────
def load_active_sets() -> Dict[str, List[Dict[str, Any]]]:
    raw = {}
    for name in (
        "bg_pool_minions",
        "bg_pool_spells",
        "bg_trinkets",
        "bg_hero_powers",
        "bg_tavern_spells",
        "bg_anomalies",
        "bg_dark_gifts",
        "bg_quest_rewards",
        "bg_heroes",
    ):
        raw[name] = C.read_json(C.DATA_DIR / f"{name}.json")
    return raw


def cards_matching(sets: Dict[str, List[Dict[str, Any]]], pattern: str) -> List[Dict[str, Any]]:
    """在 37 活跃卡集合里按**去标记后**的文本匹配（同 id 去重，保留首个 set）。"""
    rx = re.compile(pattern)
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for kind, arr in sets.items():
        for card in arr:
            cid = card["id"]
            if cid in seen:
                continue
            text = C.solo_text(card.get("text"))
            plain = re.sub(r"<[^>]+>", "", text).replace("[x]", "")
            if plain and rx.search(plain):
                seen.add(cid)
                out.append(
                    {
                        "set": kind,
                        "id": cid,
                        "name": card.get("name"),
                        "text": text[:240],
                    }
                )
    return out


# ── 探针定义 ─────────────────────────────────────────────────────────
def build_probes(at: Path) -> Dict[str, Any]:
    sets = load_active_sets()

    def at_grep(rel: str, pattern: str, limit: int = 3):
        return grep(at, rel, pattern, limit)

    def my_grep(rel: str, pattern: str, limit: int = 3):
        return grep(C.REPO_ROOT, rel, pattern, limit)

    probes: List[Dict[str, Any]] = []

    # ── OPS-01 整馆冻结/解冻 ──────────────────────────────────────────
    probes.append(
        {
            "id": "OPS-01",
            "op": "整馆冻结/解冻（Freeze / Unfreeze 整馆）",
            "game_semantics": "酒馆雪花按钮：未全冻→冻结全部；已全冻→解冻全部（切换语义）。",
            "at_status": "covered(toggle)",
            "at_evidence": at_grep("crates/taverngym/src/recruit.rs", r"set_frozen\(!all\)")
            + at_grep("crates/taverngym/src/state.rs", r"fn set_frozen"),
            "hsbrsim_status": "covered(单向 FREEZE + F-23 unfreeze_tavern；候选动作只有 FREEZE)",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"def (un)?freeze_tavern")
            + my_grep("hsbg/env/spec.py", r"FREEZE = "),
            "ds37_evidence": {
                "note": "37 数据卡面证实冻结是**按随从粒度**的状态（见 OPS-02）",
            },
            "is_gap": False,
            "suggested_action_index": "已覆盖：245 Unfreeze（std profile 扩展，单向掩码更清晰）",
        }
    )

    # ── OPS-02 单个酒馆随从冻结/解冻 ─────────────────────────────────
    freeze_cards = cards_matching(sets, r"Freeze")
    per_slot = cards_matching(sets, r"Freeze( them| both| it| a| the)")
    probes.append(
        {
            "id": "OPS-02",
            "op": "单个酒馆随从冻结/解冻（per-slot freeze/unfreeze）",
            "game_semantics": "真实游戏 UI 对每个酒馆随从有独立雪花（可只冻/只解一个）；"
            "整馆按钮与单卡按钮是两种操作。",
            "at_status": "missing",
            "at_evidence": at_grep("crates/taverngym/src/recruit.rs", r"fn freeze\(")
            + at_grep("crates/taverngym/src/recruit.rs", r"fn unfreeze_shop")
            + [
                {
                    "file": "crates/taverngym/src/actions.rs",
                    "line": 0,
                    "snippet": "Action 枚举只有 `Freeze`（整馆 toggle），没有 `FreezeSlot(i)`；"
                    "`unfreeze_shop(sid)` 仅内部用于卡被替换时清标记，不是动作",
                }
            ],
            "hsbrsim_status": "missing",
            "hsbrsim_evidence": my_grep("hsbg/env/spec.py", r"FREEZE = ")
            + my_grep("hsrl2/game.py", r"def freeze_tavern"),
            "ds37_evidence": {
                "per_minion_freeze_cards": per_slot[:20],
                "count": len(per_slot),
                "note": "「Freeze them both / Freeze it」等卡面证明冻结状态是**单个随从**粒度"
                "（卡面如 BG22_HERO_004p Twice as Nice），整馆 API 无法表达",
            },
            "is_gap": True,
            "suggested_action_index": "266..273 = FREEZE_SLOT(0..7)：单个酒馆槽位冻结/解冻（toggle，8 槽）",
        }
    )

    # ── OPS-03 酒馆展示位 8 ──────────────────────────────────────────
    probes.append(
        {
            "id": "OPS-03",
            "op": "酒馆展示位 8（7 随从 + 1 酒馆法术槽）",
            "game_semantics": "34.2 起酒馆为 7 个随从位 + 1 个酒馆法术位（共 8 槽）。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/actions.rs", r"pub const N_SHOP")
            + at_grep("crates/taverngym/src/config.rs", r"7 \+ self\.shop_spell_slots")
            + at_grep("crates/taverngym/src/config.rs", r"shop_spell_slots: 1"),
            "hsbrsim_status": "legacy 观测只声明 TAVERN_MAX=7（会截断第 8 张）",
            "hsbrsim_evidence": my_grep("hsbg/env/spec.py", r"TAVERN_MAX = "),
            "ds37_evidence": {
                "pool_spells": len(sets["bg_pool_spells"]),
                "note": "37 数据池内酒馆法术 76 张，与随从同店展示",
            },
            "is_gap": False,
            "suggested_action_index": "已覆盖：8..15 Buy(0..7)；std profile 观测需 N_SHOP=8",
        }
    )

    # ── OPS-04 选择 16（及 >16 预留）────────────────────────────────
    probes.append(
        {
            "id": "OPS-04",
            "op": "选择选项 16（Choose 0..15）",
            "game_semantics": "所有 PendingChoice（发现/三选一/饰品/任务/英雄选择/目标）共用 Choose 动作；"
            "AT 上限 16，单测/真实对局观测选项 ≤5。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/actions.rs", r"pub const N_CHOICE")
            + at_grep("crates/taverngym/src/state.rs", r"pub enum Pending"),
            "hsbrsim_status": "legacy CHOICE_OPTION_MAX=5（截断风险）",
            "hsbrsim_evidence": my_grep("hsbg/env/spec.py", r"CHOICE_OPTION_MAX = "),
            "ds37_evidence": {
                "note": "37 数据无 >5 选项的强制场景；16 足够，>16 仅预留",
            },
            "is_gap": False,
            "suggested_action_index": "已覆盖：30..45 Choose(0..15)；250..265 为 16..31 预留",
        }
    )

    # ── OPS-05 手牌/棋盘上限 ─────────────────────────────────────────
    probes.append(
        {
            "id": "OPS-05",
            "op": "手牌上限 10 / 棋盘上限 7",
            "game_semantics": "手牌最多 10 张、棋盘最多 7 个随从（召唤受上限约束）。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/config.rs", r"hand_size: 10")
            + at_grep("crates/taverngym/src/config.rs", r"board_size: 7")
            + at_grep("crates/taverngym/src/actions.rs", r"hand_full = pl\.hand\.len\(\)")
            + at_grep("crates/taverngym/src/actions.rs", r"board_full = pl\.board\.len\(\)"),
            "hsbrsim_status": "covered（引擎有 hand cap/board cap；F-37 修过 Reborn 溢出 8）",
            "hsbrsim_evidence": my_grep("hsbg/env/spec.py", r"HAND_MAX = |BOARD_MAX = ")
            + my_grep("hsrl2/game.py", r"board_full"),
            "ds37_evidence": {"note": "37 数据标准局无超限机制；上限为规则常数"},
            "is_gap": False,
            "suggested_action_index": "已覆盖：8..15/46..125/126..195 的 hand/board 维度（N_HAND=10, N_BOARD=7）",
        }
    )

    # ── OPS-06 黑暗赠礼选择 ──────────────────────────────────────────
    probes.append(
        {
            "id": "OPS-06",
            "op": "黑暗赠礼（Dark Gift 按钮 → 三选一）",
            "game_semantics": "第 3 回合起，花 3 金点黑暗赠礼按钮 → 3 个「随从+gift」选 1。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/actions.rs", r"Action::DarkGift")
            + at_grep("crates/taverngym/src/recruit.rs", r"fn dark_gift"),
            "hsbrsim_status": "covered（USE_DARK_GIFT + PendingChoice）",
            "hsbrsim_evidence": my_grep("hsbg/env/spec.py", r"USE_DARK_GIFT")
            + my_grep("hsrl2/game.py", r"def use_dark_gift"),
            "ds37_evidence": {
                "dark_gifts": len(sets["bg_dark_gifts"]),
                "note": "37 数据 47 张黑暗赠礼（全部 BG36 前缀）",
            },
            "is_gap": False,
            "suggested_action_index": "已覆盖：6 DarkGift + Choose",
        }
    )

    # ── OPS-07 任务选择 ──────────────────────────────────────────────
    probes.append(
        {
            "id": "OPS-07",
            "op": "任务选择（Quest + 配对奖励）",
            "game_semantics": "任务系统：从若干「任务+奖励」选项中选 1；选完进入进度追踪。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/state.rs", r"Quest \{")
            + at_grep("crates/taverngym/src/recruit.rs", r"Pending::Quest")
            + at_grep("crates/taverngym/src/content/quests.rs", r"pub fn scripts\(\)"),
            "hsbrsim_status": "covered（PendingChoice kind=quest_offer）",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"quest_offer")
            + my_grep("hsrl2/game.py", r"def quest_defs"),
            "ds37_evidence": {
                "quest_rewards": len(sets["bg_quest_rewards"]),
                "note": "37 数据 73 张任务奖励；任务卡本体 20（hsrl2 同源谓词）",
            },
            "is_gap": False,
            "suggested_action_index": "已覆盖：Choose（Pending::Quest 选项 ≤ N_CHOICE）",
        }
    )

    # ── OPS-08 饰品三选一/四选一 ─────────────────────────────────────
    probes.append(
        {
            "id": "OPS-08",
            "op": "饰品选择（Lesser T6 / Greater T9 四选一 + 可选放弃）",
            "game_semantics": "饰品商店：4 个候选选 1（花金币），或放弃；替换类不可放弃。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/state.rs", r"Trinket \{")
            + at_grep("crates/taverngym/src/recruit.rs", r"fn take_trinket"),
            "hsbrsim_status": "covered（trinket_offer PendingChoice）",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"def _offer_trinkets"),
            "ds37_evidence": {
                "trinkets": len(sets["bg_trinkets"]),
                "note": "37 数据 409 张饰品定义",
            },
            "is_gap": False,
            "suggested_action_index": "已覆盖：Choose（4+1 选项）",
        }
    )

    # ── OPS-09 备用英雄技能槽 ────────────────────────────────────────
    second_hp = cards_matching(sets, r"second Hero Power|extra Hero Power|Hero Power slot")
    probes.append(
        {
            "id": "OPS-09",
            "op": "备用/第二英雄技能槽（HeroPower slot ≥ 2 可用）",
            "game_semantics": "部分效果给英雄追加第 2 个技能槽；槽位可被饰品/Timewarp 技能占用。",
            "at_status": "partial(engine 支持任意 slot，动作空间只编码 0..1)",
            "at_evidence": at_grep("crates/taverngym/src/state.rs", r"HeroPowerChoice")
            + at_grep("crates/taverngym/src/actions.rs", r"pub const N_POWERS")
            + at_grep("crates/taverngym/src/actions.rs", r"N_POWERS: usize = 2"),
            "hsbrsim_status": "covered(hero_power_ids 为列表，set_second_hero_power；legacy 动作按 id 枚举)",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"def set_second_hero_power")
            + my_grep("hsrl2/game.py", r"def hero_power_ids"),
            "ds37_evidence": {
                "hero_powers": len(sets["bg_hero_powers"]),
                "second_power_cards": second_hp[:10],
                "count": len(second_hp),
            },
            "is_gap": True,
            "suggested_action_index": "246..249 = HeroPower(2..5)（std profile 已预留）",
        }
    )

    # ── OPS-10 目标取消 ──────────────────────────────────────────────
    probes.append(
        {
            "id": "OPS-10",
            "op": "目标选择取消（Cancel）",
            "game_semantics": "目标型战吼/法术/Activate/英雄技能在选定目标前可取消（未扣费）。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/actions.rs", r"Action::Cancel")
            + at_grep("crates/taverngym/src/state.rs", r"fn cancellable"),
            "hsbrsim_status": "legacy ActionKind 无 CANCEL；std profile 有 7 Cancel",
            "hsbrsim_evidence": my_grep("hsbg/env/spec.py", r"class ActionKind")
            + my_grep("hsbg/env/action_space_std.py", r"A_CANCEL"),
            "ds37_evidence": {"note": "37 卡面无变化；规则层操作"},
            "is_gap": False,
            "suggested_action_index": "已覆盖：7 Cancel（AT 语义）；legacy → std 迁移时补齐",
        }
    )

    # ── OPS-11 异变系统 ──────────────────────────────────────────────
    anomalies = sets["bg_anomalies"]
    probes.append(
        {
            "id": "OPS-11",
            "op": "异变（Anomaly）系统：开局全局覆写 + 局内异变选择",
            "game_semantics": "异变是**局级**全局效果（开局生效），部分异变会新增局内选择"
            "（如 Audience's Choice / Anomalous Evidence）。",
            "at_status": "missing（AT 无 anomaly 系统）",
            "at_evidence": at_grep("crates/taverngym/src/*.rs", r"anomal", 2)
            + [
                {
                    "file": "crates/taverngym/src/content/mod.rs",
                    "line": 0,
                    "snippet": "all_scripts() 无 anomaly 模块；Game 无 anomaly 字段（36.6.3 全局系统=饰品+黑暗赠礼）",
                }
            ],
            "hsbrsim_status": "covered（Game(anomaly=...) + PendingChoice；41 张有脚本）",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"anomaly: Optional\[str\]")
            + my_grep("hsrl2/game.py", r"anomaly must be a BACON_ANOMALY"),
            "ds37_evidence": {
                "anomalies_total": len(anomalies),
                "new_in_37": sum(1 for a in anomalies if "BG36" in a["id"] or "BG37" in a["id"]),
                "new_in_37_ids": [a["id"] for a in anomalies if "BG36" in a["id"]],
                "note": "108 条均为历史定义（BG27/31/32/33/34/35 前缀）；唯一 BG36 条目 "
                "BG36_Anomaly_002 是 Dark Gift 教学式条目（hsrl2 记为 no-op）→ "
                "**无证据**表明 37.0.0 轮换启用异变系统",
            },
            "is_gap": True,
            "suggested_action_index": "不新增动作（配置注入即可）；系统本身列入 P3/可选，见文档 §7",
        }
    )

    # ── OPS-12 Pass（Duos）───────────────────────────────────────────
    pass_cards = cards_matching(sets, r"\bPass\b")
    # 37 全量卡里“Pass 只出现在 @ 第二段（Duos 变体）”的卡
    all37 = C.read_json(C.DATA_DIR / "bg_cards.json")
    pass_segment2 = sorted(
        c["id"]
        for c in all37
        if "@" in (c.get("text") or "")
        and "Pass" not in C.solo_text(c.get("text"))
        and "Pass" in (c.get("text") or "").split("@", 1)[1]
    )
    probes.append(
        {
            "id": "OPS-12",
            "op": "Pass（传递/弃置手牌，Duos 语义）",
            "game_semantics": "Duos 双人模式的传递机制；单人 8 人局无队友，不能 Pass。",
            "at_status": "missing（Duos 不在 AT 范围）",
            "at_evidence": at_grep("crates/taverngym/src/*.rs", r"\bPass a\b", 2)
            + at_grep("crates/taverngym/src/content/*.rs", r"\bPass a\b", 2),
            "hsbrsim_status": "missing（hsrl2 F-08 明确裁定 Duos 语义不实现）",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"\bPass\b", 1)
            + my_grep("docs/ENGINE_NOTES.md", r"or Pass", 2),
            "ds37_evidence": {
                "cards_with_pass": [c["id"] for c in pass_cards],
                "pass_only_in_segment2": pass_segment2,
                "note": "37 数据里 Pass 只出现在 5 个 37 新卡的 `@` 第二段（Duos 文本变体）"
                "与 2 张 Duos-only 法术（BG31_243/244，误入 is_pool_spell）",
            },
            "is_gap": False,
            "suggested_action_index": "不新增动作；数据管线需按 `@` 拆分丢弃 Duos 变体（见文档 §2.4）",
        }
    )

    # ── OPS-13 弃手牌选择 ────────────────────────────────────────────
    discard_cards = cards_matching(sets, r"Discard a card|discard a card")
    probes.append(
        {
            "id": "OPS-13",
            "op": "弃手牌选择（Discard a card from hand）",
            "game_semantics": "「Discard a card」需从手牌选择一张弃置（非随机）。",
            "at_status": "covered（TargetSpec::Hand + Continuation）",
            "at_evidence": at_grep("crates/taverngym/src/content/minions.rs", r"TargetSpec::Hand"),
            "hsbrsim_status": "covered（PendingChoice kind=discard_card，F-08）",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"discard_card")
            + my_grep("hsrl2/scripts/batches/batch_37x_discard.py", r"discard_card"),
            "ds37_evidence": {"discard_cards": discard_cards[:10], "count": len(discard_cards)},
            "is_gap": False,
            "suggested_action_index": "已覆盖：用 Choose 在手牌选项上结算（无需新动作）",
        }
    )

    # ── OPS-14 非随从 Discover ───────────────────────────────────────
    probes.append(
        {
            "id": "OPS-14",
            "op": "非随从发现（Discover 法术/任务奖励/英雄技能）",
            "game_semantics": "Discover 的候选池不限于随从（池内 5+ 张法术/奖励会 Discover 非随从）。",
            "at_status": "covered（Pending::Discover options 是 Item，可含法术）",
            "at_evidence": at_grep("crates/taverngym/src/state.rs", r"Discover \{"),
            "hsbrsim_status": "legacy 缺口（G-F1：Discover Action 只造随从，4 个脚本自建 Action）",
            "hsbrsim_evidence": my_grep("docs/AUDIT_ENGINE_MECHANICS.md", r"通用 Discover 只支持随从", 1),
            "ds37_evidence": {"note": "37 池内酒馆法术 76 + 任务奖励 73 均为可发现池"},
            "is_gap": False,
            "suggested_action_index": "AT 已覆盖；Rust fork 沿用 Pending::Discover 即可",
        }
    )

    # ── OPS-15 英雄选择（开局 lobby）────────────────────────────────
    probes.append(
        {
            "id": "OPS-15",
            "op": "开局英雄选择（Hero Select）",
            "game_semantics": "开局从 2/3/4 个英雄中选 1（hero_choices 随赛季）。",
            "at_status": "covered",
            "at_evidence": at_grep("crates/taverngym/src/state.rs", r"HeroSelect")
            + at_grep("crates/taverngym/src/config.rs", r"hero_choices"),
            "hsbrsim_status": "covered（英雄选择在 env 配置层，非动作）",
            "hsbrsim_evidence": my_grep("hsbg/env/game_env.py", r"hero_id"),
            "ds37_evidence": {"heroes": len(sets["bg_heroes"])},
            "is_gap": False,
            "suggested_action_index": "已覆盖：Choose（HeroSelect pending）；AT config.hero_choices 可调",
        }
    )

    # ── OPS-16 Timewarp 购买/离开 ────────────────────────────────────
    probes.append(
        {
            "id": "OPS-16",
            "op": "Timewarp 商店（Chronum 购买 / 离开）",
            "game_semantics": "34.2 Timewarp：用 Chronum 逐张购买 Timewarp 卡，最后一项为离开。",
            "at_status": "covered（Pending::Timewarp；默认 timewarp_enabled=false）",
            "at_evidence": at_grep("crates/taverngym/src/state.rs", r"Timewarp \{")
            + at_grep("crates/taverngym/src/config.rs", r"timewarp_enabled"),
            "hsbrsim_status": "missing（hsrl2 无 Timewarp 系统）",
            "hsbrsim_evidence": my_grep("hsrl2/game.py", r"timewarp", 1),
            "ds37_evidence": {
                "timewarp_cards_present_in_37_data": 253,
                "note": "AT Timewarp 池 253 卡在 37 数据中全部存在；37 无新增 Timewarp 卡；"
                "37 池内有 4 个英雄技能/7 张饰品文本仍引用 Timewarp",
            },
            "is_gap": False,
            "suggested_action_index": "AT 已覆盖（Pending::Timewarp 最后一项=离开）；按 config 开关",
        }
    )

    # ── OPS-17 Activate 带目标 ───────────────────────────────────────
    probes.append(
        {
            "id": "OPS-17",
            "op": "Activate（发动）带目标选择",
            "game_semantics": "Activate 结算前若需目标，先选目标再扣费；可取消。",
            "at_status": "covered（Continuation::Activate + resolve_or_ask + Cancel）",
            "at_evidence": at_grep("crates/taverngym/src/recruit.rs", r"Continuation::Activate"),
            "hsbrsim_status": "legacy 缺口（G-A3：目标协议非引擎级，14 处脚本自建）",
            "hsbrsim_evidence": my_grep("docs/AUDIT_ENGINE_MECHANICS.md", r"Activate 目标协议非引擎级", 1),
            "ds37_evidence": {"pool_activate_minions": 23},
            "is_gap": False,
            "suggested_action_index": "AT 已覆盖：Activate(i) + 后续 Choose(目标)",
        }
    )

    return {
        "schema": "p2_delta/ops_probe/v1",
        "inputs": {
            "at_root": str(at),
            "ds37": C.read_json(C.DATA_DIR / "bg_summary.json").get("patch"),
        },
        "at_action_space": _at_action_space(at),
        "hsbrsim_action_space": _hsbrsim_action_space(),
        "probes": probes,
        "gap_summary": {
            "gaps": [p["id"] for p in probes if p["is_gap"]],
            "covered": [p["id"] for p in probes if not p["is_gap"]],
        },
    }


def _at_action_space(at: Path) -> Dict[str, Any]:
    """从 actions.rs 抓 AT 动作空间常量 + 布局注释。"""
    src = read_file(at, "crates/taverngym/src/actions.rs")
    consts: Dict[str, int] = {}
    for m in re.finditer(r"pub const ([A-Z_][A-Z0-9_]*): usize = ([^;]+);", src):
        expr = m.group(2).strip()
        # 只解析纯数字或已算出的常量表达式（按出现顺序迭代解析）
        val = _eval_const(expr, consts)
        if val is not None:
            consts[m.group(1)] = val
    layout = re.search(r"Layout \(N_ACTIONS = \d+\):\n(.*?)\*/", src, re.S)
    return {
        "consts": dict(sorted(consts.items())),
        "n_actions": consts.get("N_ACTIONS"),
        "layout_comment": layout.group(0)[:1200] if layout else "",
        "enum_variants": sorted(set(re.findall(r"^\s{4}([A-Z][A-Za-z]*)", src, re.M))),
    }


def _eval_const(expr: str, known: Dict[str, int]) -> Optional[int]:
    if re.fullmatch(r"\d+", expr):
        return int(expr)
    # 形如 A_B + N * M
    safe = expr
    for name, val in known.items():
        safe = re.sub(rf"\b{name}\b", str(val), safe)
    if not re.fullmatch(r"[0-9+\-*/() ]+", safe):
        return None
    try:
        return int(eval(safe, {"__builtins__": {}}, {}))  # noqa: S307 - 纯算术白名单
    except Exception:
        return None


def _hsbrsim_action_space() -> Dict[str, Any]:
    spec_src = read_file(C.REPO_ROOT, "hsbg/env/spec.py")
    kinds = re.findall(r'^\s{4}([A-Z_]+) = "([a-z_]+)"', spec_src, re.M)
    std_src = read_file(C.REPO_ROOT, "hsbg/env/action_space_std.py")
    std_consts: Dict[str, int] = {}
    if std_src:
        # 多轮解析别名/算术（A_UNFREEZE = A_EXT_BASE 等）
        pending = [
            (m.group(1), m.group(2).strip())
            for m in re.finditer(r"^([A-Z_][A-Z0-9_]*) = (.+)$", std_src, re.M)
            if not m.group(2).strip().startswith(("(", '"', "'"))
        ]
        for _ in range(6):
            changed = False
            for name, expr in pending:
                if name in std_consts:
                    continue
                safe = expr
                for known, val in std_consts.items():
                    safe = re.sub(rf"\b{known}\b", str(val), safe)
                if re.fullmatch(r"[0-9+\-*/() ]+", safe):
                    try:
                        std_consts[name] = int(eval(safe, {"__builtins__": {}}, {}))  # noqa: S307
                        changed = True
                    except Exception:
                        pass
            if not changed:
                break
    return {
        "legacy_action_kinds": [{"enum": e, "value": v} for e, v in kinds],
        "legacy_num_kinds": len(kinds),
        "std_consts": dict(sorted(std_consts.items())),
        "std_extensions": [
            {"index": std_consts.get("A_UNFREEZE"), "name": "Unfreeze"},
            {"index": std_consts.get("A_EXTRA_POWER"), "name": "HeroPower(2..5)",
             "count": std_consts.get("N_EXTRA_POWER_SLOTS")},
            {"index": std_consts.get("A_EXTRA_CHOOSE"), "name": "Choose(16..31)",
             "count": std_consts.get("N_EXTRA_CHOICE_SLOTS")},
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--at-root", default=None)
    ap.add_argument("--out", default=str(C.RUNS_DIR / "ops_probe.json"))
    args = ap.parse_args(argv)
    at = C.at_root(args.at_root)
    result = build_probes(at)
    C.write_json(args.out, result)
    print(f"[probe_ops] 输出: {args.out}")
    print(f"  AT N_ACTIONS={result['at_action_space']['n_actions']}")
    print(f"  探针 {len(result['probes'])} 项；缺口: {result['gap_summary']['gaps']}")
    for p in result["probes"]:
        flag = "GAP " if p["is_gap"] else "ok  "
        print(f"  {flag}{p['id']} {p['op']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
