"""缩放教师（DAgger 式）：把「∞ 金币 + tier6 施法缩放脚本」变成可查询策略。

来源：`scripts/engine_ceiling_probe.py --mode spell`（`runs/ceiling_probe/REPORT.md`
§2：同引擎 + 施法缩放脚本在 ∞ 金币下 t12 p50 1843 / p90 6003）。本模块把那段
脚本策略抽成**纯函数**：输入引擎 `Game.view(seat)` 的 JSON（board/hand/gold/tier/
shop/pending/mask），输出一个**确定性、必合法**的动作。用途：

1. **离线标注**：`scripts/scaling_teacher.py` 在 learner rollout 的状态上查询教师，
   写 `data/scaling_teacher/labels.jsonl`；
2. **在线 DAgger**：训练采集（`collect_ppo_lockstep`）在「高金币/缩放窗口」
   （``gold >= 10 and tier >= 4``）把教师动作写进 record，PPO 侧用
   ``teacher_bc_coef * CE(π_θ, a_teacher)`` 做辅助 BC（默认系数 0 = 零影响）。

动作布局与引擎一致（见 `rust/crates/hsbg-engine/src/actions.rs`）：

    EndTurn 0 / Refresh 1 / Freeze 2 / Upgrade 3 / HeroPower 4..5 / DarkGift 6 /
    Cancel 7 / Buy 8..15 / Sell 16..22 / Activate 23..29 / Choose 30..45 /
    Play 46..125 (hand 10 × pos 8) / Magnetize 126..195 / Move 196..244

设计约束：
- **只读 view**：不依赖 Game 句柄、不消耗随机数、不修改状态；同状态 -> 同动作。
- **必合法**：所有动作先过 `mask`；若首选不可用，按优先级回退到第一个合法动作，
  因此非法率恒为 0（`scripts/scaling_teacher.py` 会统计并在 >0 时报错）。
- 缩放优先级：手牌法术先打；买法术（酒馆永久 buff/吞食引擎）；买「cast a spell
  on this」缩放随从；买/换身材；三连；升 tier；刷新；英雄技能；结束回合。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --- 动作布局 -----------------------------------------------------------------
A_END = 0
A_REFRESH = 1
A_UPGRADE = 3
A_HERO_POWER = 4
A_CANCEL = 7
A_BUY = 8
A_SELL = 16
A_CHOOSE = 30
A_PLAY = 46
N_CHOICE = 16
N_POS = 8
N_BOARD = 7

#: 缩放窗口门槛（题面：gold>=10 且 tier>=4）
WINDOW_GOLD = 10
WINDOW_TIER = 4


def _text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("text") or item.get("text_zh") or "").lower()


def _is_spell_synergy(item: Any) -> bool:
    """「whenever you cast a spell on this」类缩放随从。"""
    t = _text(item)
    return ("cast a spell on this" in t
            or "对其施放法术" in t
            or "施放法术" in t and "获得" in t)


def _is_consume(item: Any) -> bool:
    """吞食酒馆随从的缩放引擎（Felboar / 恶魔吞食）。"""
    t = _text(item)
    return ("consume" in t or "吞食" in t or "吞噬" in t)


def _is_minion(item: Any) -> bool:
    return isinstance(item, dict) and str(item.get("type") or "") == "minion"


def _stats(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    return int(item.get("atk") or 0) + int(item.get("hp") or 0)


def _price(item: Any) -> int:
    for k in ("price", "cost"):
        v = item.get(k)
        if isinstance(v, int) and v >= 0:
            return int(v)
    return 3


def in_scaling_window(gold: Any, tier: Any) -> bool:
    """在线 DAgger 的窗口判定（题面：gold≥10 且 tier≥4）。"""
    try:
        return int(gold or 0) >= WINDOW_GOLD and int(tier or 0) >= WINDOW_TIER
    except (TypeError, ValueError):
        return False


class ScalingTeacher:
    """确定性施法缩放教师；``act_view`` 是唯一入口。"""

    name = "scaling_teacher"

    def __init__(self, *, window_gold: int = WINDOW_GOLD,
                 window_tier: int = WINDOW_TIER, refresh_cap: int = 40):
        self.window_gold = int(window_gold)
        self.window_tier = int(window_tier)
        self.refresh_cap = max(0, int(refresh_cap))

    # -- 公开入口 ---------------------------------------------------------
    def act_view(self, view: Dict[str, Any],
                 mask: Optional[Sequence[Any]] = None) -> int:
        """输入 `Game.view(seat)` JSON，返回合法动作下标（确定性）。"""
        v = view if isinstance(view, dict) else {}
        m = v.get("mask") if mask is None else mask
        me = v.get("me") or {}
        if not isinstance(me, dict):
            me = {}
        a = self._choose(v, me, m)
        return self._ensure_legal(a, m)

    def act(self, game: Any, seat: int = 0) -> int:
        """便捷入口：从 Game 取 view 并返回动作（不修改 game 状态）。"""
        return self.act_view(json.loads(game.view(int(seat))))

    # -- 规则 -------------------------------------------------------------
    def _choose(self, v: Dict[str, Any], me: Dict[str, Any],
                m: Sequence[Any]) -> int:
        pend = me.get("pending")
        if pend:
            return self._pending(v, me, m, pend)
        if str(v.get("phase") or "recruit") != "recruit" or me.get("ended_turn"):
            return A_END
        return self._recruit(v, me, m)

    def _pending(self, v: Dict[str, Any], me: Dict[str, Any],
                 m: Sequence[Any], pend: Dict[str, Any]) -> int:
        legal = [i for i in range(N_CHOICE) if self._legal(m, A_CHOOSE + i)]
        if not legal:
            return A_CHOOSE
        kind = str(pend.get("kind") or "")
        opts = pend.get("options") or []
        if kind == "target":
            board = me.get("board") or []
            want = None
            for mm in board:
                if _is_spell_synergy(mm):
                    want = mm.get("eid")
                    break
            if want is not None:
                for i in legal:
                    if i < len(opts) and opts[i] == want:
                        return A_CHOOSE + i
            if board:
                best = max(range(len(board)), key=lambda i: _stats(board[i]))
                eid = board[best].get("eid")
                for i in legal:
                    if i < len(opts) and opts[i] == eid:
                        return A_CHOOSE + i
            return A_CHOOSE + legal[0]
        if kind == "hero":
            best: Optional[Tuple[Tuple[int, int, int], int]] = None
            for i in legal:
                if i >= len(opts) or not isinstance(opts[i], dict):
                    continue
                hp = opts[i].get("hero_power") or {}
                txt = _text(hp)
                sc = (3 if "+" in txt else 0) + (1 if "stats" in txt else 0)
                key = (sc - int(hp.get("cost") or 0),
                       -int(opts[i].get("armor") or 0), -i)
                if best is None or key > best[0]:
                    best = (key, i)
            return A_CHOOSE + (best[1] if best is not None else legal[0])
        if kind in ("discover", "choose_one"):
            best = None
            for i in legal:
                if i >= len(opts) or not isinstance(opts[i], dict):
                    continue
                o = opts[i]
                sc = _stats(o) if _is_minion(o) else 0
                # 缩放关键词优先（发现/三选一里优先吞食/施法缩放）
                if _is_spell_synergy(o) or _is_consume(o):
                    sc += 50
                key = (sc, -i)
                if best is None or key > best[0]:
                    best = (key, i)
            return A_CHOOSE + (best[1] if best is not None else legal[0])
        if kind == "trinket":
            gold = int(me.get("gold") or 0)
            for i in legal:
                if i < len(opts) and isinstance(opts[i], dict) \
                        and int(opts[i].get("cost") or 0) <= gold:
                    return A_CHOOSE + i
            return A_CHOOSE + legal[0]
        return A_CHOOSE + legal[0]

    def _recruit(self, v: Dict[str, Any], me: Dict[str, Any],
                 m: Sequence[Any]) -> int:
        gold = int(me.get("gold") or 0)
        board: List[Dict[str, Any]] = list(me.get("board") or [])
        hand: List[Dict[str, Any]] = list(me.get("hand") or [])
        shop: List[Dict[str, Any]] = list(me.get("shop") or [])
        tier = int(me.get("tier") or 1)

        # 1) 手牌法术：全部施放（pending 阶段会优先选缩放随从作为目标）
        for h, it in enumerate(hand[:10]):
            if not _is_minion(it) and self._legal(m, A_PLAY + h * N_POS):
                return A_PLAY + h * N_POS

        buys = [i for i in range(8)
                if i < len(shop) and self._legal(m, A_BUY + i)]
        owned_synergy = any(_is_spell_synergy(x) for x in board)
        owned_consume = any(_is_consume(x) for x in board)

        # 2) 缩放引擎：优先买法术（酒馆永久 buff / 吞食）与「施法缩放」随从
        spells = [i for i in buys if not _is_minion(shop[i])]
        if spells:
            i = min(spells, key=lambda k: (_price(shop[k]), k))
            if gold >= _price(shop[i]):
                return A_BUY + i
        synergy = [i for i in buys if _is_spell_synergy(shop[i])]
        if synergy and not owned_synergy:
            i = max(synergy, key=lambda k: (_stats(shop[k]), -k))
            if gold >= _price(shop[i]) and len(board) < N_BOARD:
                return A_BUY + i
        consume = [i for i in buys if _is_consume(shop[i])]
        if consume and not owned_consume:
            i = max(consume, key=lambda k: (_stats(shop[k]), -k))
            if gold >= _price(shop[i]) and len(board) < N_BOARD:
                return A_BUY + i

        worst_i = (min(range(len(board)), key=lambda k: _stats(board[k]))
                   if board else None)
        worst_s = _stats(board[worst_i]) if worst_i is not None else -1

        # 3) 手牌随从：有空位就下；满场只换「明显更强」
        best_hand = None
        for h, it in enumerate(hand[:10]):
            if _is_minion(it):
                s = _stats(it)
                if best_hand is None or s > best_hand[0]:
                    best_hand = (s, h)
        if best_hand is not None:
            s, h = best_hand
            if len(board) < N_BOARD:
                pos = len(board)
                if self._legal(m, A_PLAY + h * N_POS + pos):
                    return A_PLAY + h * N_POS + pos
            elif worst_i is not None and s > worst_s + max(5, worst_s // 5):
                if self._legal(m, A_SELL + worst_i):
                    return A_SELL + worst_i

        # 4) 三连：买会凑成三个的同名随从（金色化放大永久 buff）
        from collections import Counter
        owned = Counter(str(x.get("id")) for x in board)
        owned.update(str(it.get("id")) for it in hand if _is_minion(it))
        triples = [i for i in buys
                   if _is_minion(shop[i])
                   and owned.get(str(shop[i].get("id")), 0) >= 2]
        if triples:
            i = max(triples, key=lambda k: (_stats(shop[k]), -k))
            if gold >= _price(shop[i]):
                return A_BUY + i

        # 5) 买随从：身材 + tier；满场只换明显更强
        cands = [i for i in buys if _is_minion(shop[i])]
        if cands:
            i = max(cands, key=lambda k: (_stats(shop[k])
                                          + int(shop[k].get("tier") or 0), -k))
            s = shop[i]
            if gold >= _price(s):
                if len(board) < N_BOARD:
                    return A_BUY + i
                if worst_i is not None and _stats(s) > worst_s + max(5, worst_s // 5):
                    if self._legal(m, A_SELL + worst_i):
                        return A_SELL + worst_i

        # 6) 升 tier（tier<6 且负担得起；留 3 金）
        price = int(me.get("upgrade_price") or 99)
        if tier < 6 and self._legal(m, A_UPGRADE) \
                and gold >= price and (price <= 3 or gold - price >= 3):
            return A_UPGRADE

        # 7) 刷新（缩放流更积极：每次刷新多一张酒馆法术）
        refresh_price = int(me.get("refresh_price") or 1)
        if self._legal(m, A_REFRESH) and gold >= refresh_price + 2:
            return A_REFRESH

        # 8) 英雄技能（有就用）
        for slot in range(2):
            if self._legal(m, A_HERO_POWER + slot) and gold >= 1:
                return A_HERO_POWER + slot
        return A_END

    # -- 工具 -------------------------------------------------------------
    @staticmethod
    def _legal(mask: Optional[Sequence[Any]], a: int) -> bool:
        if a < 0:
            return False
        if mask is None:
            return True
        return 0 <= a < len(mask) and bool(mask[a])

    def _ensure_legal(self, a: int, mask: Optional[Sequence[Any]]) -> int:
        """首选动作不可用时按优先级回退（EndTurn -> Refresh -> 第一个合法动作）。"""
        if self._legal(mask, a):
            return int(a)
        if mask is None:
            return A_END
        for cand in (A_END, A_REFRESH):
            if self._legal(mask, cand):
                return int(cand)
        for i, ok in enumerate(mask):
            if bool(ok):
                return int(i)
        return A_END


__all__ = [
    "ScalingTeacher", "in_scaling_window", "A_END", "A_REFRESH", "A_UPGRADE",
    "A_HERO_POWER", "A_BUY", "A_SELL", "A_CHOOSE", "A_PLAY", "N_POS", "N_BOARD",
    "WINDOW_GOLD", "WINDOW_TIER",
]
