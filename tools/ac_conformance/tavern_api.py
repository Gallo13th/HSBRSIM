"""AutoTavern（taverngym 1.0.0 / 36.6.3）侧构造与驱动。

只调用公开 Python API：
`Game(seed, config_json)` / `Game.step` / `Game.view` / `Game.debug` /
`Game.bot_play` / `Game.placements` / `Game.combat_preview`（debug 命令）。

约定（见 docs/CONFORMANCE_AUTOTAVERN.md §3）：
* 8 个座位在英雄选择后统一 pin 成 Patchwerk（纯被动英雄，唯一效果是
  开局 +30 血），清空棋盘/手牌；玩家 stats/effects/quests/trinkets 全 0
  （实测，见 `probe_clean_state`），因此战斗观察不受英雄起始效果污染；
* 合成随从用“白板卡 + edit_minion 覆写 atk/hp/keywords”构造：卡面
  tier 由所选白板决定（伤害公式里 token tier 计入），所以 hsrl2 侧
  dummy 的 `tech_level` 必须取同一个值，见 `BODY_BY_TIER`；
* 战斗用 `combat_preview`：`details=true` 给 n 个独立 trial 的胜负与
  实际扣血（含伤害上限/护甲路径）；`details=false, n=1` 给 trial 0 的
  replay frames（首攻方/攻击次数/事件日志从 frames 解析）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

import taverngym

HERO = "TB_BaconShop_HERO_34"  # Patchwerk：被动，仅开局 +30 Health

#: 各 tier 的“白板”宿主卡（AutoTavern 36.6.3 目录里 scripted=false、
#: 无关键词、无文本；race 对纯机制场景无影响）。tier 会进入伤害公式
#: （胜方伤害 = 酒馆等级 + 存活随从 tier 之和），故必须与 hsrl2 侧
#: dummy 的 tech_level 一致。
BODY_BY_TIER: Dict[int, str] = {
    1: "AV_113t3t2",   # Snake 2/2 BEAST
    2: "BG29_100_G",   # Zilliax: Assembled 6/8 MECHANICAL
    3: "BG_CS2_200",   # Boulderfist Ogre 6/7（无种族）
    5: "BG26_173",     # [BGTEMPLATE] VFX Dummy 1/8 UNDEAD
}

#: taverngym 关键词名（types.rs Kw::NAMES）
KW_NAMES = ("TAUNT", "DIVINE_SHIELD", "WINDFURY", "REBORN", "VENOMOUS",
            "POISONOUS", "STEALTH", "MAGNETIC", "MEGA_WINDFURY", "CLEAVE")


def _dbg(g, **cmd) -> Any:
    return json.loads(g.debug(json.dumps(cmd)))


def recruit_game(seed: int, config: Optional[Dict[str, Any]] = None):
    """建一局并推进到第 1 回合招募阶段；所有座位 pin 成 Patchwerk。"""
    g = taverngym.Game(seed, json.dumps(config or {}))
    for p in range(g.num_players):
        g.step(p, json.loads(g.view(p))["actions"]["CHOOSE"])
    for p in range(g.num_players):
        for _ in range(8):
            v = json.loads(g.view(p))
            if v["me"]["pending"] is None:
                break
            g.step(p, v["actions"]["CHOOSE"])
    for p in range(g.num_players):
        _dbg(g, cmd="set_hero", p=p, hero=HERO)
        _dbg(g, cmd="clear_zone", p=p, zone="board")
        _dbg(g, cmd="clear_zone", p=p, zone="hand")
    return g


def probe_clean_state(g) -> Dict[str, Any]:
    """记录英雄 pin 之后玩家级状态（用于证明无污染）。"""
    v = json.loads(g.view(0))
    me = v["me"]
    return {
        "hero": me["hero"]["id"] if me.get("hero") else None,
        "powers": [p["id"] for p in me.get("hero_powers") or []],
        "effects": len(me.get("effects") or []),
        "quests": len(me.get("quests") or []),
        "trinkets": len(me.get("trinkets") or []),
        "nonzero_stats": {k: x for k, x in (me.get("stats") or {}).items()
                          if x not in (0, False, None, [], "")},
    }


def add_synthetic(g, p: int, units: Sequence[Dict[str, Any]]) -> None:
    """在座位 p 棋盘末尾添加合成随从。

    unit = {"atk", "hp", "kws": [...], "tier": 1}
    """
    for i, u in enumerate(units):
        tier = int(u.get("tier", 1))
        card = BODY_BY_TIER[tier]
        _dbg(g, cmd="add_minion", p=p, zone="board", card=card,
             atk=int(u["atk"]), hp=int(u["hp"]))
        _dbg(g, cmd="edit_minion", p=p, zone="board", index=i,
             atk=int(u["atk"]), hp=int(u["hp"]),
             keywords=list(u.get("kws") or ()))


def add_cards(g, p: int, cards: Sequence[str], golden: Sequence[bool] = ()) -> None:
    """在座位 p 棋盘末尾添加真实卡牌（不覆写属性/关键词）。"""
    from_idx = 0
    for i, cid in enumerate(cards):
        golden_i = bool(golden[i]) if i < len(golden) else False
        _dbg(g, cmd="add_minion", p=p, zone="board", card=cid, golden=golden_i)
        from_idx += 1


def _set_players(g, turn: int, tier_a: int, tier_b: int) -> None:
    _dbg(g, cmd="set_turn", turn=int(turn))
    for p, tier in ((0, tier_a), (1, tier_b)):
        _dbg(g, cmd="set_player", p=p, health=100, armor=0, tier=int(tier),
             gold=99)


def build_duel(seed: int, a_units, b_units, *, turn: int = 1,
               tier_a: int = 1, tier_b: int = 1, card_a=(), card_b=(),
               golden_a=(), golden_b=()):
    g = recruit_game(seed)
    _set_players(g, turn, tier_a, tier_b)
    if card_a:
        add_cards(g, 0, card_a, golden_a)
    if a_units:
        add_synthetic(g, 0, a_units)
    if card_b:
        add_cards(g, 1, card_b, golden_b)
    if b_units:
        add_synthetic(g, 1, b_units)
    return g


# ══════════════════════════════════════════════════════════════════════
# 战斗观察
# ══════════════════════════════════════════════════════════════════════

_ATTACK_RE = re.compile(r"p(\d)'s .*? attacks ")
_DEATH_RE = re.compile(r"p(\d)'s (.+) dies")


def combat_trials(g, n: int) -> Dict[str, Any]:
    """n 个独立 trial 的胜负/扣血（含真实伤害上限路径）。"""
    r = _dbg(g, cmd="combat_preview", a=0, b=1, n=int(n), details=True)
    trials = r["trials"]
    wins = {"a": 0, "b": 0, "tie": 0}
    dmg_by_winner: Dict[str, List[int]] = {"a": [], "b": []}
    truncated = 0
    for t in trials:
        w = t["winner"]
        if w == 0:
            wins["a"] += 1
            dmg_by_winner["a"].append(int(t["damage_dealt"]))
        elif w == 1:
            wins["b"] += 1
            dmg_by_winner["b"].append(int(t["damage_taken"]))
        else:
            wins["tie"] += 1
        truncated += 1 if t.get("truncated") else 0
    return {
        "n": len(trials),
        "wins": wins,
        "damage_by_winner": dmg_by_winner,
        "truncated": truncated,
        "after_start": r.get("after_start"),
    }


def combat_sample(g) -> Dict[str, Any]:
    """trial 0 的 replay frames（胜负/原始伤害/首攻方/攻击事件）。"""
    r = _dbg(g, cmd="combat_preview", a=0, b=1, n=1)
    s = r["sample"]
    frames = s["frames"]
    logs: List[str] = []
    for f in frames:
        logs.extend(f.get("log") or [])
    first_attacker = None
    for line in logs:
        m = _ATTACK_RE.search(line)
        if m:
            first_attacker = "a" if int(m.group(1)) == 0 else "b"
            break
    n_attacks = sum(len(f.get("attacks") or []) for f in frames)
    deaths = [m.group(2) for m in (_DEATH_RE.search(l) for l in logs) if m]
    return {
        "winner": {0: "a", 1: "b", 2: "tie"}[int(s["winner"])],
        "uncapped_damage": int(s["damage"]),
        "first_attacker": first_attacker,
        "n_attacks": n_attacks,
        "frame_count": len(frames),
        "deaths": deaths,
        "log": logs,
        "truncated": bool(s.get("truncated")),
    }


def build_full_board(seed: int, a_units, b_units, **kw):
    return build_duel(seed, a_units, b_units, **kw)


def run_bot_game(seed: int) -> Dict[str, Any]:
    """整局 bot 对局（每个座位用内置启发式 bot 驱动）。"""
    g = taverngym.Game(seed, json.dumps({}))
    for p in range(g.num_players):
        g.step(p, json.loads(g.view(p))["actions"]["CHOOSE"])
    for _ in range(5000):
        if g.is_over():
            break
        progressed = False
        for p in range(g.num_players):
            if g.needs_action(p):
                g.bot_play(p)
                progressed = True
        if not progressed and not g.is_over():
            break
    placements = list(g.placements())
    return {
        "over": bool(g.is_over()),
        "turn": int(g.turn),
        "placements": placements,
        "truncated_combats": int(g.truncated_combats),
        "turn_limit_end": bool(g.turn_limit_end),
    }


# ══════════════════════════════════════════════════════════════════════
# 招募经济探针
# ══════════════════════════════════════════════════════════════════════

def _view(g, p: int = 0) -> Dict[str, Any]:
    return json.loads(g.view(p))


def _resolve_pending(g, p: int) -> None:
    for _ in range(16):
        v = _view(g, p)
        if v["me"]["pending"] is None:
            return
        g.step(p, v["actions"]["CHOOSE"])


def _end_all_turns(g) -> None:
    end = _view(g)["actions"]["END"]
    for p in range(g.num_players):
        _resolve_pending(g, p)
        if g.needs_action(p):
            g.step(p, end)


def economy_probe(seed: int = 7) -> Dict[str, Any]:
    cfg = json.loads(taverngym.default_config_json())

    # ── 金币曲线（单独一局，避免探测动作污染回合推进） ──
    g = recruit_game(seed)
    gold_progression = [int(_view(g)["me"]["gold"])]
    for _ in range(4):
        _end_all_turns(g)
        _resolve_pending(g, 0)
        gold_progression.append(int(_view(g)["me"]["gold"]))

    res: Dict[str, Any] = {
        "gold_progression": gold_progression,
        "start_gold": int(cfg["start_gold"]),
        "gold_increment": int(cfg["gold_increment"]),
        "gold_refill_cap": int(cfg["gold_refill_cap"]),
        "buy_cost": int(cfg["buy_cost"]),
        "sell_value": int(cfg["sell_value"]),
        "refresh_cost": int(cfg["refresh_cost"]),
        "board_size": int(cfg["board_size"]),
        "hand_size": int(cfg["hand_size"]),
        "max_regular_tier": int(cfg["max_regular_tier"]),
        "triple_copies": int(cfg["triple_copies"]),
        "damage_cap_until_alive": int(cfg["damage_cap_until_alive"]),
        "pool_copies_by_tier": list(cfg["pool_copies_by_tier"]),
        "spell_copies_by_tier": list(cfg["spell_copies_by_tier"]),
        "shop_minion_slots": list(cfg["shop_minion_slots"]),
        "shop_spell_slots": int(cfg["shop_spell_slots"]),
        "upgrade_costs": list(cfg["upgrade_costs"]),
        "upgrade_discount_per_turn": int(cfg["upgrade_discount_per_turn"]),
        "damage_caps": [[int(t), int(c)] for t, c in cfg["damage_caps"]],
    }

    # ── 酒馆内容 / 买卖 / 升级（turn1 全新一局，无任务/饰品干扰） ──
    g = recruit_game(seed)
    shop = {}
    for tier in range(1, 7):
        _dbg(g, cmd="set_player", p=0, tier=tier, gold=99)
        _dbg(g, cmd="refresh_shop", p=0)
        entries = _view(g)["me"]["shop"]
        minions = sum(1 for e in entries if "base_hp" in e)
        spells = sum(1 for e in entries if "base_hp" not in e)
        shop[str(tier)] = {"minions": minions, "spells": spells}
    res["shop_by_tier"] = shop

    _dbg(g, cmd="set_player", p=0, tier=1, gold=99)
    _dbg(g, cmd="refresh_shop", p=0)
    v = _view(g)
    res["minion_price"] = int(v["me"]["minion_price"])
    res["refresh_price"] = int(v["me"]["refresh_price"])
    buy_idx = next((i for i, e in enumerate(v["me"]["shop"])
                    if "base_hp" in e and v["mask"][8 + i]), None)
    if buy_idx is None:
        res.update(buy_ok=None, buy_gold_delta=None,
                   sell_ok=None, sell_gold_delta=None)
    else:
        gold0 = int(v["me"]["gold"])
        g.step(0, 8 + buy_idx)               # A_BUY + shop 槽
        v = _view(g)
        res["buy_ok"] = True
        res["buy_gold_delta"] = int(v["me"]["gold"]) - gold0
        hand_idx = next((i for i, e in enumerate(v["me"]["hand"])
                         if "base_hp" in e), None)
        if hand_idx is not None:
            g.step(0, 46 + hand_idx * 8)     # A_PLAY + hand*N_POS + pos0
            v = _view(g)
            gold1 = int(v["me"]["gold"])
            if v["me"]["board"]:
                g.step(0, 16)               # A_SELL + board 0
                v = _view(g)
                res["sell_ok"] = True
                res["sell_gold_delta"] = int(v["me"]["gold"]) - gold1
            else:
                res.update(sell_ok=None, sell_gold_delta=None)
        else:
            res.update(sell_ok=None, sell_gold_delta=None)

    up = {}
    for target in range(2, 7):
        _dbg(g, cmd="set_player", p=0, tier=target - 1, gold=99,
             upgrade_cost=int(cfg["upgrade_costs"][target - 2]))
        v = _view(g)
        cost = int(v["me"]["upgrade_price"])
        gold0 = int(v["me"]["gold"])
        if v["mask"][3]:                     # A_UPGRADE
            g.step(0, 3)
            v = _view(g)
            up[str(target)] = {
                "cost": cost,
                "ok": True,
                "gold_after": gold0 - int(v["me"]["gold"]),
                "tier_after": int(v["me"]["tier"]),
            }
        else:
            up[str(target)] = {"cost": cost, "ok": False,
                               "gold_after": 0,
                               "tier_after": int(v["me"]["tier"])}
    res["upgrade_by_tier"] = up
    res["var"] = None
    return res
