"""人类观测的**准完整状态**解析与注入（board + hand + 可推断 counters）。

背景：训练对手长期只用 ``Game.inject_board``（board-only，见
``docs/HUMAN_BOARD_OPPONENT.md`` / ``docs/PRESSURE_AUDIT.md``）。审计证明 board-only 会
系统性丢掉金色身份（引擎侧其实由 ``_G`` 卡 id 保留）、**被授予的关键词位**、attachments、
scripts 与手牌，使训练压力被低估（同帧 +5.1pp / 真实管线 +6.7pp 败率差）。

本模块把 ``data/real_library/obs/observations/*.jsonl`` 里**真实可见**的字段补全成
「准完整状态」，并把它注入到引擎的目标座位。**只做 Python 侧封装**，Rust 核心零改动：

- 复用 ``Game.apply_turn_snapshots``（EOT 完整 Player 注入，白名单替换 + EID 重映射 +
  逐座位事务）；
- 复用 ``Game.inject_board`` 作为最底层/默认保真度（逐位等价现状）；
- 注入后可选把 ``ended_turn`` 复位（``reset_ended=True``），让被注入座位**照常行动**，
  与现有 board-only 训练管线的「注入后 bot 继续打」语义一致（见 docs 的语义对照表）。

数据可得性（实测 2026-10-31，13,120 行 / 376 文件 / 67,386 个战团随从）：

========================  ==================================================  ========
字段                       来源                                                 状态
========================  ==================================================  ========
board (card/atk/hp)        ``board[].card_id/attack/health``                    可得
golden                    ``card_id`` 以 ``_G`` 结尾 或 tag 12 (PREMIUM)        可得
关键词位 (kw)              ``board[].tags`` 的数字 tag（见 ``TAG_TO_KW``）       可得（经验证）
圣盾层数 (shield_max)      tag 194 的值（1 或 3）                               可得
tavern tier               ``heroes[0].tags["1377"]``（按回合单调 1→6）          可得（经验证）
hand                      ``known_hand``（仅 ``perspective=self`` 帧可信）      可得 / 部分
gold                      无字段                                                **不可得**
每随从 script counter      无可靠 tag（``counter``/``gems``/``avenge``）           **不可得**
attachments / 亡语脚本      无字段（只有可见关键词位）                             **不可得**
player counters / 英雄技能  ``apply_turn_snapshots`` 白名单保留目标座位原值          **不可得**
shop / 共享池差量          无字段                                                **不可得**
========================  ==================================================  ========

``TAG_TO_KW`` 的经验依据（不是猜的）：用 ``final_boards.jsonl`` 的**具名 tag** 与
``cards.json`` 的印刷关键词交叉验证，对全部 67k 战团随从计算 precision/recall：

===========  ==================  ==========  =================================
tag          语义                 recall      说明
===========  ==================  ==========  =================================
190/3614     TAUNT               0.998       印刷嘲讽全覆盖
194/3617     DIVINE_SHIELD       0.994       tag 值 3 = 圣盾 3 层（Toreth）
189/3622     WINDFURY            1.000
1085/3621    REBORN              0.955
2853         VENOMOUS            1.000
363/3620     POISONOUS           1.000
849          MAGNETIC            1.000
191/3619     STEALTH             0.994
===========  ==================  ==========  =================================

precision 低于 1 的原因是**被授予**的关键词（例如 Bubble Gunner 的战吼随机给关键词、
Bile Spitter 的 Rally 给毒），这正是我们要补的 hidden counters；因此这里按
「tag 非零 = 该关键词存在」取值，并把「不是印刷关键词」的位单独记进 ``bonus_kw``。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

#: 观测数字 tag -> 引擎关键词名（经验映射，见模块 docstring 的 recall 表）。
TAG_TO_KW: Dict[int, str] = {
    190: "TAUNT", 3614: "TAUNT",
    194: "DIVINE_SHIELD", 3617: "DIVINE_SHIELD",
    189: "WINDFURY", 3622: "WINDFURY",
    1085: "REBORN", 3621: "REBORN",
    2853: "VENOMOUS",
    363: "POISONOUS", 3620: "POISONOUS",
    849: "MAGNETIC",
    191: "STEALTH", 3619: "STEALTH",
}

#: 与 Rust ``types.rs::Kw`` 逐位一致（bit0 TAUNT … bit11 IMMUNE_ATTACKING）。
KW_BITS: Dict[str, int] = {
    "TAUNT": 1 << 0,
    "DIVINE_SHIELD": 1 << 1,
    "WINDFURY": 1 << 2,
    "REBORN": 1 << 3,
    "VENOMOUS": 1 << 4,
    "POISONOUS": 1 << 5,
    "STEALTH": 1 << 6,
    "MAGNETIC": 1 << 7,
    "MEGA_WINDFURY": 1 << 8,
    "CLEAVE": 1 << 9,
    "IMMUNE": 1 << 10,
    "IMMUNE_ATTACKING": 1 << 11,
}
KW_NAMES: Tuple[str, ...] = tuple(KW_BITS)

#: 本模块能注入的字段（白名单）；其它一律 ``unavailable``，绝不编造。
FIELDS_INJECTABLE: Tuple[str, ...] = (
    "board", "golden", "keywords", "shield_max", "tavern_tier", "hand",
)
#: **玩家级**（Player 上）的字段：``apply_turn_snapshots`` 白名单**保留目标座位原值**，
#: 因此需要一步 Python 侧 overlay（仍在同一个 ``set_player_from_json`` 往返里完成）。
#: 这些字段全部是「卡 id + int」的**自包含**结构（不含 EntityId 引用），可安全搬运。
#: ``combat`` 组只含「战斗开始触发」的玩家级效果（trinkets/quests/rewards/secrets/
#: effects/stats）——它们是战斗数值的真实来源；``hero``/``powers`` 会改变后续回合的
#: 主动玩法（bot 会去用不属于自己的英雄技能），默认**不**搬。
PLAYER_COMBAT_FIELDS: Tuple[str, ...] = (
    "trinkets", "quests", "rewards", "secrets", "levels", "effects", "counters",
    "stats", "tier7",
)
PLAYER_ACTIVE_FIELDS: Tuple[str, ...] = ("hero", "powers")
PLAYER_OVERLAY_MODES: Tuple[str, ...] = ("none", "combat", "all")

#: 明确不可得（写进 payload 的 availability，训练 meta 里逐字段计数）。
FIELDS_UNAVAILABLE: Tuple[str, ...] = (
    "gold", "counter", "gems", "attachments", "deathrattle_scripts",
    "player_counters", "hero_power_uses", "shop", "pool_delta",
)

SCHEMA = "hsbg.human_state_quasi_full"
SCHEMA_VERSION = 1

DEFAULT_CARDS = os.path.join(ROOT, "rust", "crates", "hsbg-engine", "data", "cards.json")

#: 观测 stage：只有「招募结束、战斗前」的帧才是 EOT 帧（另一类是第一刀之后）。
EOT_STAGE = "recruitment_end_at_phase_switch"


# ════════════════════════════════════════════════════════════════════════
# 卡表（卡 id 字符串 -> 引擎 int cid + 印刷关键词）
# ════════════════════════════════════════════════════════════════════════

_META: Optional[Dict[str, Dict[str, Any]]] = None


def _kw_bits_from_names(names: Iterable[Any]) -> int:
    bits = 0
    for n in names or ():
        bits |= int(KW_BITS.get(str(n).strip().upper(), 0))
    return bits


def load_card_meta(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """读 ``cards.json`` → ``{card_id: {cid, kind, tier, kw_bits, atk, hp, normal, golden}}``。

    下标即 Rust ``CardId``（与 ``scripts/import_real_library.py`` 同一约定，绝不重排）。
    """
    global _META
    if _META is not None and (path is None or path == DEFAULT_CARDS):
        return _META
    raw = json.loads(open(path or DEFAULT_CARDS, "r", encoding="utf-8").read())
    cards = raw.get("cards") if isinstance(raw, dict) else raw
    out: Dict[str, Dict[str, Any]] = {}
    for i, c in enumerate(cards or ()):
        if not isinstance(c, dict) or not isinstance(c.get("id"), str):
            continue
        out[c["id"]] = {
            "cid": int(i),
            "kind": str(c.get("kind") or ""),
            "tier": int(c.get("tier") or 0),
            "atk": int(c.get("atk") or 0),
            "hp": int(c.get("hp") or 0),
            "kw_bits": _kw_bits_from_names(c.get("keywords") or ()),
            "normal": c.get("normal") or "",
            "golden": c.get("golden") or "",
            "name": c.get("name") or "",
        }
    if path is None or path == DEFAULT_CARDS:
        _META = out
    return out


def is_golden_card_id(card_id: str, meta: Dict[str, Dict[str, Any]]) -> bool:
    """金色判定：``_G`` 后缀，或卡表 ``normal`` 非空（该卡本身就是金色变体）。"""
    if not isinstance(card_id, str):
        return False
    if card_id.endswith("_G"):
        return True
    return bool((meta.get(card_id) or {}).get("normal"))


# ════════════════════════════════════════════════════════════════════════
# 观测行 -> 准完整 payload
# ════════════════════════════════════════════════════════════════════════


def _tags_of(obj: Any) -> Dict[int, Any]:
    raw = (obj or {}).get("tags") if isinstance(obj, dict) else None
    out: Dict[int, Any] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[int(k)] = v
            except (TypeError, ValueError):
                continue
    return out


def _kw_from_tags(tags: Dict[int, Any]) -> int:
    bits = 0
    for tag, name in TAG_TO_KW.items():
        try:
            v = int(tags.get(tag) or 0)
        except (TypeError, ValueError):
            v = 0
        if v != 0:
            bits |= int(KW_BITS[name])
    return bits


def _int_or(v: Any, default: Optional[int] = None) -> Optional[int]:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    return default


def availability_defaults() -> Dict[str, str]:
    """每个字段的可用性标签（``observed`` / ``derived`` / ``unavailable``）。"""
    av: Dict[str, str] = {f: "observed" for f in FIELDS_INJECTABLE}
    av.update({f: "unavailable" for f in FIELDS_UNAVAILABLE})
    av["hero"] = "observed_not_injected"
    return av


def parse_observation(row: Any, meta: Optional[Dict[str, Dict[str, Any]]] = None,
                      *, eot_only: bool = True, max_board: int = 7
                      ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """一行观测 -> ``(payload | None, 失败原因)``。

    只接受 ``stage == recruitment_end_at_phase_switch`` 的 EOT 帧（``eot_only=False`` 放宽，
    用于统计）；board 里任何一张卡映射不到卡表 / 不是随从则**整行丢弃**（fail-closed）。
    ``hand`` 只在 ``perspective == self`` 且 ``unknown_hand_count == 0`` 时可信。
    """
    m = meta if meta is not None else load_card_meta()
    reasons: List[str] = []
    if not isinstance(row, dict):
        return None, ["not_object"]
    if eot_only and str(row.get("stage") or "") != EOT_STAGE:
        reasons.append("stage")
        return None, reasons + ["drop"]
    turn = _int_or(row.get("turn"))
    if turn is None or turn <= 0:
        reasons.append("bad_turn")
        turn = 0
    raw_board = row.get("board")
    if not isinstance(raw_board, list) or not raw_board:
        reasons.append("empty_board")
        return None, reasons + ["drop"]
    if len(raw_board) > int(max_board):
        return None, reasons + ["board_too_large"]

    board: List[Dict[str, Any]] = []
    for i, mm in enumerate(raw_board):
        if not isinstance(mm, dict):
            return None, reasons + ["bad_minion"]
        cid_s = mm.get("card_id")
        info = m.get(str(cid_s) or "")
        if info is None or info.get("kind") != "minion":
            return None, reasons + [f"unmapped_minion:{cid_s}"]
        atk = _int_or(mm.get("attack"))
        hp = _int_or(mm.get("health"))
        if atk is None or hp is None:
            return None, reasons + ["incomplete_stats"]
        if int(atk) < 0 or int(hp) <= 0:
            return None, reasons + ["bad_stats"]
        tags = _tags_of(mm)
        printed = int(info.get("kw_bits") or 0)
        observed = _kw_from_tags(tags)
        golden = (bool(str(cid_s).endswith("_G"))
                  or int(tags.get(12) or 0) != 0
                  or bool(info.get("normal")))
        sh = int(tags.get(194) or 0)
        board.append({
            "card": int(info["cid"]),
            "card_id": str(cid_s),
            "atk": int(atk), "hp": int(hp),
            "position": int(_int_or(mm.get("position"), i + 1) or (i + 1)),
            "golden": bool(golden),
            # 观测关键词位 = 印刷 ∪ 被授予（客户端对两者都给 tag）。
            "kw": int(observed | printed),
            "bonus_kw": int(observed & ~printed),
            "shield_max": int(sh if sh in (1, 3) else (3 if sh > 3 else 1)),
        })

    # tavern tier：hero 实体 tag 1377（经验证：按回合中位 1→6 单调）。
    tier: Optional[int] = None
    persp = str(row.get("perspective") or "")
    heroes = row.get("heroes")
    hero_card_id = None
    if isinstance(heroes, list) and heroes and isinstance(heroes[0], dict):
        hero_card_id = heroes[0].get("card_id")
        t = _int_or(_tags_of(heroes[0]).get(1377))
        if t is not None and 1 <= int(t) <= 7:
            tier = int(t)

    # hand：仅 self 视角可信（对手视角的 known_hand 只是已揭示的子集）。
    hand: Optional[List[Dict[str, Any]]] = None
    hand_available = False
    if persp == "self" and int(_int_or(row.get("unknown_hand_count"), 0) or 0) == 0:
        raw_hand = row.get("known_hand")
        if isinstance(raw_hand, list):
            hand_available = True
            hand = []
            for it in raw_hand:
                if not isinstance(it, dict):
                    hand, hand_available = None, False
                    break
                cid_s = it.get("card_id")
                info = m.get(str(cid_s) or "")
                if info is None:
                    hand, hand_available = None, False
                    break
                tags = _tags_of(it)
                kind = str(info.get("kind") or "")
                if kind == "minion":
                    atk = _int_or(tags.get(47), int(info.get("atk") or 1)) or 1
                    hp = _int_or(tags.get(45), int(info.get("hp") or 1)) or 1
                    hand.append({"card": int(info["cid"]), "card_id": str(cid_s),
                                 "kind": "minion", "atk": int(atk), "hp": int(hp),
                                 "golden": bool(str(cid_s).endswith("_G")
                                                or int(tags.get(12) or 0) != 0
                                                or bool(info.get("normal"))),
                                 "kw": int(_kw_from_tags(tags) | int(info.get("kw_bits") or 0))})
                elif kind in ("spell", "tavern_spell"):
                    hand.append({"card": int(info["cid"]), "card_id": str(cid_s),
                                 "kind": "spell"})
                else:
                    hand, hand_available = None, False
                    break

    av = availability_defaults()
    av["tavern_tier"] = "observed" if tier is not None else "derived_from_turn"
    av["hand"] = "observed" if hand_available else "unavailable"

    payload = {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
        "turn": int(turn),
        "game_id": str(row.get("game_id") or ""),
        "split": str(row.get("split") or ""),
        "stage": str(row.get("stage") or ""),
        "perspective": persp,
        "controller": _int_or(row.get("controller")),
        "build_number": _int_or(row.get("build_number")),
        "hero_card_id": hero_card_id,
        "board": board,
        "board_flat": [[int(b["card"]), int(b["atk"]), int(b["hp"])] for b in board],
        "hand": hand,
        "hand_available": bool(hand_available),
        "tier": tier,
        "gold": None,
        "availability": av,
        "source": "human_obs_quasi_full",
    }
    return payload, reasons


# ════════════════════════════════════════════════════════════════════════
# 引擎帧构造
# ════════════════════════════════════════════════════════════════════════

_TPL_GAME: Any = None
_TPL_CACHE: Dict[int, Dict[str, Any]] = {}


def _template_game():
    """一个停在 turn1 recruit 的临时局（只为让引擎产出**权威**的随从 JSON 模板）。"""
    global _TPL_GAME
    if _TPL_GAME is not None:
        return _TPL_GAME
    import hsbg_engine as E

    g = E.Game(seed=1)
    for _ in range(8):        # 8 个座位各选一个英雄 -> 进入 turn1 recruit
        p = next((i for i in range(8) if g.needs_action(i)), None)
        if p is None:
            break
        g.bot_play(int(p))
    _TPL_GAME = g
    return g


def minion_template(cid: int) -> Optional[Dict[str, Any]]:
    """取``cid``的权威随从 JSON（引擎 ``Minion::new`` 的序列化结果；含 races/tier/kw）。"""
    cid = int(cid)
    hit = _TPL_CACHE.get(cid)
    if hit is not None:
        return hit
    try:
        g = _template_game()
        rep = g.inject_board(0, [(cid, 1, 1)], None)
        if not bool(rep.get("applied")):
            return None
        pj = json.loads(g.player_json(0))
        b = pj.get("board") or []
        if not b:
            return None
        tpl = b[0]
        _TPL_CACHE[cid] = tpl
        return tpl
    except BaseException:  # noqa: BLE001 - 模板失败 -> 调用方退化为合成 JSON
        return None


def _default_minion(eid: int, card: int) -> Dict[str, Any]:
    """兜底：与 Rust ``Minion`` serde 结构逐字段一致（模板不可用时使用）。"""
    return {
        "eid": int(eid), "card": int(card), "atk": 1, "hp": 1, "max_hp": 1,
        "kw": 0, "bonus_kw": 0, "shield_hits": 0, "shield_max": 1,
        "races": 0, "tier": 1, "golden": False, "attached": [],
        "attachment_data": [], "pool_copies": 0, "triple_reward": False,
        "counter": 0, "gift_data": 0, "first_play_reward_used": False,
        "pbonus_atk": 0, "pbonus_hp": 0, "temp_atk": 0, "temp_hp": 0,
        "tavern_temp_atk": 0, "tavern_temp_hp": 0, "temp_kw": 0,
        "activations": 0, "destroyed": False, "attacked": False, "killed_by": 0,
        "peak_atk": 1, "peak_hp": 1, "combat_only": False, "gems": 0,
        "gem_atk": 0, "gem_hp": 0, "avenge": 0, "attacks": 0, "doomed_turn": 0,
        "cycle": 0, "cycle_turn": 0, "gained_dr": [],
    }


def _minion_json(entry: Dict[str, Any], eid: int, *, with_counters: bool
                 ) -> Dict[str, Any]:
    """payload 的一条 board 项 -> 引擎 ``Minion`` JSON。

    ``with_counters=False`` 时只保留 B0（board-only）等价的信息：卡 id + atk/hp
    （引擎自带的印刷关键词/races/tier 由模板给出，与 ``inject_board`` 完全一致）。
    """
    if with_counters and isinstance(entry.get("json"), dict):
        # 可信 EOT 帧：整条随从 JSON 照抄（counter/attached/gems 全保留），只重置
        # 与「上一场战斗」相关的瞬时字段与 EID。
        out = json.loads(json.dumps(entry["json"]))
        out["eid"] = int(eid)
        out["killed_by"] = 0
        out["destroyed"] = False
        out["attacked"] = False
        out["combat_only"] = False
        out["pool_copies"] = 0
        out.pop("pool_parts", None)
        out["hp"] = int(out.get("hp") or 1)
        out["max_hp"] = max(int(out.get("max_hp") or out["hp"]), out["hp"])
        out["atk"] = int(out.get("atk") or 0)
        return out
    tpl = minion_template(int(entry["card"]))
    base = json.loads(json.dumps(tpl)) if tpl else _default_minion(eid, int(entry["card"]))
    atk = int(entry.get("atk", base.get("atk", 1)))
    hp = int(entry.get("hp", base.get("hp", 1)))
    base.update({
        "eid": int(eid), "card": int(entry["card"]),
        "atk": atk, "hp": hp, "max_hp": max(hp, int(entry.get("max_hp", hp))),
        "pool_copies": 0, "killed_by": 0, "destroyed": False, "attacked": False,
        "combat_only": False, "peak_atk": atk, "peak_hp": hp,
    })
    base.pop("pool_parts", None)
    if with_counters:
        base["kw"] = int(entry.get("kw", base.get("kw", 0)))
        base["bonus_kw"] = int(entry.get("bonus_kw", 0))
        base["golden"] = bool(entry.get("golden", base.get("golden", False)))
        base["triple_reward"] = bool(base["golden"])
        if int(base["kw"]) & int(KW_BITS["DIVINE_SHIELD"]):
            sm = int(entry.get("shield_max") or 1)
            base["shield_max"] = int(sm) if sm in (1, 3) else 1
            base["shield_hits"] = int(base["shield_max"])
        else:
            base["shield_hits"] = 0
            base["shield_max"] = 1
    return base


def _hand_json(payload: Dict[str, Any], first_eid: int
               ) -> Tuple[List[Dict[str, Any]], int]:
    """payload 的 hand -> 引擎 ``HandCard`` JSON 列表（hid 连续分配）。"""
    out: List[Dict[str, Any]] = []
    nid = int(first_eid)
    for it in payload.get("hand") or ():
        nid += 1
        if str(it.get("kind") or "") == "minion":
            mj = _minion_json({"card": int(it["card"]), "atk": int(it.get("atk") or 1),
                               "hp": int(it.get("hp") or 1),
                               "golden": bool(it.get("golden")),
                               "kw": int(it.get("kw") or 0)},
                              nid, with_counters=True)
            out.append({"hid": nid, "item": {"Minion": mj}, "locked": 0,
                        "link": 0, "group": 0, "group_left": 0,
                        "temporary": False, "src": 0, "combined": False,
                        "held": False, "held_gold": 0})
        else:
            out.append({"hid": nid, "item": {"Spell": {"card": int(it["card"]), "data": 0}},
                        "locked": 0, "link": 0, "group": 0, "group_left": 0,
                        "temporary": False, "src": 0, "combined": False,
                        "held": False, "held_gold": 0})
    return out, nid


# ════════════════════════════════════════════════════════════════════════
# 注入（Python 侧封装；不改 Rust）
# ════════════════════════════════════════════════════════════════════════

#: 保真度档位（与训练 ``--human-board-fidelity`` 一致）。
FIDELITY_MODES = ("board", "hand", "full")


def inject_quasi_state(game: Any, seat: int, payload: Dict[str, Any],
                       fidelity: str = "full", *,
                       reset_ended: bool = True,
                       tier_fn: Optional[Any] = None,
                       player_overlay: str = "combat") -> Dict[str, Any]:
    """把一个准完整 payload 注入 ``game`` 的 ``seat``。

    - ``fidelity="board"``：完全走 ``Game.inject_board``（**与现状逐位等价**）；
    - ``fidelity="hand"``：board（印刷信息）+ 手牌；tier/gold 保持目标座位原值；
    - ``fidelity="full"``：board + 可推断 counters（关键词位/金身/圣盾层数）+ 手牌 + tier。

    ``player_overlay``：``apply_turn_snapshots`` 会保留目标座位的**玩家级**字段
    （trinkets/quests/rewards/secrets/effects/stats/counters）。若 payload 带了
    ``"player"`` 段，可在同一次写回里 overlay：``"none"`` 不搬 / ``"combat"``（默认）
    只搬「战斗开始触发」组（这是战斗数值的真实来源）/ ``"all"`` 连 hero+powers 一起搬
    （会改变后续回合的主动玩法，训练里不建议）。

    返回 dict：``applied`` / ``reason`` / ``mode`` / ``hand_applied`` /
    ``counters_applied`` / ``unavailable_fields`` / ``pool_balance_ok`` / ``overlay``。
    """
    fid = str(fidelity or "full").strip().lower()
    if fid not in FIDELITY_MODES:
        return {"applied": False, "reason": f"bad_fidelity({fidelity})", "mode": fid,
                "hand_applied": False, "counters_applied": False,
                "unavailable_fields": [], "pool_balance_ok": True}
    seat = int(seat)
    board = payload.get("board") or []
    av = payload.get("availability") or {}
    unavailable = sorted(k for k, v in av.items() if str(v).startswith("unavailable"))
    tier = payload.get("tier")
    if tier is None and tier_fn is not None:
        try:
            tier = int(tier_fn(int(payload.get("turn") or 1)))
        except BaseException:  # noqa: BLE001
            tier = None

    # ── board-only：复用现成引擎路径（保持逐位等价 + RNG/池语义不变） ──
    if fid == "board":
        flat = payload.get("board_flat") or [[int(b["card"]), int(b["atk"]), int(b["hp"])]
                                             for b in board]
        rep = game.inject_board(seat, [list(x) for x in flat],
                                int(tier) if tier is not None else None)
        return {"applied": bool(rep.get("applied")), "reason": str(rep.get("reason")),
                "mode": "board", "hand_applied": False, "counters_applied": False,
                "unavailable_fields": unavailable,
                "pool_balance_ok": bool(rep.get("pool_balance_ok", True))}

    # ── hand / full：以**目标座位当前状态**为帧骨架（保证引擎侧合法） ──
    try:
        frame = json.loads(game.player_json(seat))
    except BaseException as exc:  # noqa: BLE001
        return {"applied": False, "reason": f"player_json:{exc!r}"[:160], "mode": fid,
                "hand_applied": False, "counters_applied": False,
                "unavailable_fields": unavailable, "pool_balance_ok": True}
    used = {int(m.get("eid", 0)) for m in (frame.get("board") or [])}
    used |= {int(h.get("hid", 0)) for h in (frame.get("hand") or [])}
    used |= {int(s.get("sid", 0)) for s in (frame.get("shop") or [])}
    nid = max(used | {50000}) + 1

    with_counters = (fid == "full")
    new_board: List[Dict[str, Any]] = []
    for b in board:
        new_board.append(_minion_json(b, nid, with_counters=with_counters))
        nid += 1
    frame["board"] = new_board
    hand_applied = False
    if payload.get("hand_available") and payload.get("hand") is not None:
        hj, nid = _hand_json(payload, nid)
        frame["hand"] = hj
        hand_applied = True
        unavailable = [f for f in unavailable if f != "hand"]
    if with_counters and tier is not None:
        frame["tier"] = int(tier)
    gold = payload.get("gold")
    if with_counters and gold is not None:
        frame["gold"] = int(gold)
        unavailable = [f for f in unavailable if f != "gold"]
    try:
        rep = game.apply_turn_snapshots([[seat, json.dumps(frame)]], None)
    except BaseException as exc:  # noqa: BLE001
        return {"applied": False, "reason": f"apply_exc:{exc!r}"[:160], "mode": fid,
                "hand_applied": False, "counters_applied": False,
                "unavailable_fields": unavailable, "pool_balance_ok": True}
    if not int(rep.get("applied", 0)):
        rej = rep.get("rejected") or [[seat, "unknown"]]
        return {"applied": False, "reason": str(rej[0][1])[:160], "mode": fid,
                "hand_applied": False, "counters_applied": False,
                "unavailable_fields": unavailable,
                "pool_balance_ok": bool(rep.get("pool_balance_ok", True))}
    # ``apply_turn_snapshots`` 语义是「整场面 = 回合末」→ ended_turn=true。训练管线要的是
    # 「注入后该座位照常行动」（与 board-only 现状一致），因此把 ended 位复位。整帧是从
    # 本座位刚读出来的，set_player_from_json 的往返是逐字段恒等的，只改 ended_turn。
    # 玩家级 overlay 也在**同一次**写回里做（省一次 JSON 往返）。
    ov_mode = str(player_overlay or "none").strip().lower()
    if ov_mode not in PLAYER_OVERLAY_MODES:
        ov_mode = "combat"
    ov_src = payload.get("player") if isinstance(payload.get("player"), dict) else None
    ov_in: Dict[str, Any] = {}
    if ov_src and ov_mode != "none":
        for k in PLAYER_COMBAT_FIELDS:
            if k in ov_src:
                ov_in[k] = ov_src[k]
        if ov_mode == "all":
            for k in PLAYER_ACTIVE_FIELDS:
                if k in ov_src:
                    ov_in[k] = ov_src[k]
    ended = not bool(game.needs_action(seat))
    if ov_in or (reset_ended and ended):
        try:
            pj = json.loads(game.player_json(seat))
            pj.update(ov_in)
            if reset_ended and ended:
                pj["ended_turn"] = False
            game.set_player_from_json(seat, json.dumps(pj), True, False)
        except BaseException as exc:  # noqa: BLE001
            return {"applied": False, "reason": f"writeback:{exc!r}"[:160], "mode": fid,
                    "hand_applied": False, "counters_applied": False,
                    "unavailable_fields": unavailable,
                    "pool_balance_ok": bool(rep.get("pool_balance_ok", True))}
    return {
        "applied": True, "reason": "ok", "mode": fid,
        "hand_applied": bool(hand_applied),
        "counters_applied": bool(with_counters),
        "unavailable_fields": unavailable,
        "pool_balance_ok": bool(rep.get("pool_balance_ok", True)),
        "applied_seats": int(rep.get("applied", 0)),
        "overlay": sorted(ov_in),
    }


__all__ = [
    "EOT_STAGE", "FIDELITY_MODES", "FIELDS_INJECTABLE", "FIELDS_UNAVAILABLE",
    "KW_BITS", "KW_NAMES", "PLAYER_ACTIVE_FIELDS", "PLAYER_COMBAT_FIELDS",
    "PLAYER_OVERLAY_MODES", "SCHEMA", "SCHEMA_VERSION", "TAG_TO_KW",
    "availability_defaults", "inject_quasi_state", "is_golden_card_id",
    "load_card_meta", "minion_template", "parse_observation",
]
