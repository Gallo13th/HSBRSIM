"""启发式对手 / BC 教师 —— 默认脚本对手。

策略（确定性，无外部依赖）::

    1. 打出手牌随从（含磁力吸附 / 定向战吼；按身材与位置择优）
    2. 棋盘已满且有更好的手牌随从 → 卖掉最弱的
    3. 买性价比最高的酒馆随从（(atk+health)/cost，种族协同加权）
    4. 前中期有富余金币 → 升级酒馆
    5. 黑暗赠礼 / Activate / 英雄技能（有金币就用）
    6. 刷新酒馆找更好的随从（每回合有限次）
    7. 无事可做 → None（结束招募阶段）

约束
----
- 只使用 :mod:`hsbg.env.driver` 的公开枚举/应用 API，**不**直接改棋盘；
- 返回的动作一定来自 ``driver.enumerate_actions`` 的候选集（因此必定合法）；
- 随机源只用 ``game.rng``（保复现）；除 ``game.rng`` 外无随机；
- 必须稳健：任何异常都不得导致对局崩溃（内部 try/except 兜底返回 None）。
"""

from __future__ import annotations

import collections
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag

from hsbg.env import driver
from hsbg.env.spec import ActionKind

_PLAY_MINION = ActionKind.PLAY_MINION.value
_PLAY_SPELL = ActionKind.PLAY_SPELL.value
_BUY = ActionKind.BUY.value
_SELL = ActionKind.SELL.value
_UPGRADE = ActionKind.UPGRADE.value
_REROLL = ActionKind.REROLL.value
_HERO_POWER = ActionKind.HERO_POWER.value
_ACTIVATE = ActionKind.ACTIVATE.value
_DARK_GIFT = ActionKind.USE_DARK_GIFT.value
_CHOOSE = ActionKind.CHOOSE.value


def _power(obj: Any) -> float:
    """随从综合身材（攻击略微加权，因为能换掉更多敌人）。"""
    try:
        atk = float(getattr(obj, "atk", 0) or 0)
        hp = float(getattr(obj, "health", 0) or 0)
    except Exception:                                     # noqa: BLE001
        return 0.0
    return atk * 1.1 + hp


def _is_playable_minion(game: Any, ent: Any) -> bool:
    if not isinstance(ent, Minion):
        return False
    if ent.has(GameTag.LOCKED_IN_HAND):
        return False
    d = None
    try:
        d = game.db.get(ent.card_id)
    except Exception:                                     # noqa: BLE001
        d = None
    if d is not None and getattr(d, "unplayable", False):
        return False
    return True


#: 关键词协同用的标签集合（与 spec.KEYWORDS 对齐的子集）
_KEYWORD_TAG_MAP: Tuple[Tuple[str, Any], ...] = (
    ("taunt", GameTag.TAUNT),
    ("divine_shield", GameTag.DIVINE_SHIELD),
    ("poisonous", GameTag.POISONOUS),
    ("venomous", GameTag.VENOMOUS),
    ("reborn", GameTag.REBORN),
    ("windfury", GameTag.WINDFURY),
    ("cleave", GameTag.CLEAVE),
    ("deathrattle", GameTag.DEATHRATTLE),
    ("magnetic", GameTag.MAGNETIC),
    ("rally", GameTag.RALLY),
    ("stealth", GameTag.STEALTH),
)


def _minion_keywords(m: Any) -> set:
    """随从当前关键词集合（标签订阅 + 脚本钩子，忽略异常）。"""
    out: set = set()
    for name, tag in _KEYWORD_TAG_MAP:
        try:
            if m.has(tag):
                out.add(name)
        except Exception:                                 # noqa: BLE001
            continue
    script = getattr(m, "scripts", None)
    if script is not None:
        if getattr(script, "deathrattle", None) is not None:
            out.add("deathrattle")
        if getattr(script, "battlecry", None) is not None:
            out.add("battlecry")
    return out


class HeuristicPolicy:
    """贪心启发式（默认对手 + BC 教师）。"""

    name = "heuristic"

    def __init__(self, *, upgrade_turns: int = 8, max_rerolls: int = 3,
                 max_upgrades_per_turn: int = 2,
                 buy_spells: bool = True,
                 spell_gold_reserve: int = 3) -> None:
        self.upgrade_turns = int(upgrade_turns)
        self.max_rerolls = int(max_rerolls)
        self.max_upgrades_per_turn = int(max_upgrades_per_turn)
        self.buy_spells = bool(buy_spells)
        self.spell_gold_reserve = int(spell_gold_reserve)
        # id(hero) -> {turn, rerolls, upgrades}
        self._states: Dict[int, dict] = {}

    # ── 主入口 ──

    def choose(self, game: Any, hero: Any, ctx: Any = None
               ) -> Optional[driver.ActionDescriptor]:
        try:
            if hero is None or not hero.is_alive:
                return None
            st = self._state_for(game, hero)
            zones = getattr(ctx, "zones", None) if ctx is not None else None
            descriptors = driver.enumerate_actions(game, hero, zones)
            if not descriptors:
                return None
            return self._select(game, hero, st, descriptors)
        except Exception:                                 # noqa: BLE001
            # 对手策略绝不允许让对局崩溃
            return None

    def _state_for(self, game: Any, hero: Any) -> dict:
        st = self._states.get(id(hero))
        if st is None or st.get("turn") != getattr(game, "turn", 0):
            st = {"turn": getattr(game, "turn", 0),
                  "rerolls": 0, "upgrades": 0}
            self._states[id(hero)] = st
        return st

    # ── 选择逻辑 ──

    def _select(self, game: Any, hero: Any, st: dict,
                descriptors: Sequence[driver.ActionDescriptor]
                ) -> Optional[driver.ActionDescriptor]:
        by_kind: Dict[str, List[driver.ActionDescriptor]] = {}
        for d in descriptors:
            by_kind.setdefault(d.kind, []).append(d)

        plays = by_kind.get(_PLAY_MINION, [])
        spells = by_kind.get(_PLAY_SPELL, [])
        sells = by_kind.get(_SELL, [])
        buys = by_kind.get(_BUY, [])
        turn = int(getattr(game, "turn", 0))
        minion_buys = [d for d in buys if isinstance(d.src_entity, Minion)]

        # 1) 打出手牌随从（含磁力吸附 / 定向战吼）
        if plays:
            return self._best_play(game, hero, plays)
        # 2) 打出手牌法术（清手牌 → 给买随从腾手牌空间）
        if spells:
            return self._best_play(game, hero, spells)
        # 3) 升级（金币优先级：**先升级再造随从**；后手牌/棋盘堵死时
        #    升级是唯一有效的金币去处，避免"10 金常年闲置"）
        upgrades = by_kind.get(_UPGRADE, [])
        if (upgrades and st["upgrades"] < self.max_upgrades_per_turn
                and hero.tavern_tier < 6):
            d = upgrades[0]
            cost = int(d.cost)
            blocked = hero.board_full() and hero.hand_full()
            rich = hero.gold >= cost + 4
            early = turn <= self.upgrade_turns
            reserve = 0 if (blocked or rich) else 3
            if (early or rich or blocked) and hero.gold >= cost + reserve:
                st["upgrades"] += 1
                return d
        # 4) 买随从（性价比 + 种族/关键词协同；手牌有空位时）
        #    满场时只买"能顶掉场上最弱随从"的强牌，避免手牌被垃圾随从占满
        #    （手牌一满就再也买不了东西 → 金币闲置、阵容停滞）。
        if minion_buys and not hero.hand_full():
            if hero.board_full():
                weakest_power = min(_power(m) for m in hero.board)
                stronger = [d for d in minion_buys
                            if _power(d.src_entity) >= weakest_power + 1.5]
                if stronger:
                    return self._best_buy(game, hero, stronger)
            else:
                return self._best_buy(game, hero, minion_buys)
        # 5) 满场换血：卖掉最弱随从，为"打出手牌 / 买更强随从"腾位
        if hero.board_full() and sells:
            weakest = self._sell_decision(game, hero, sells, minion_buys)
            if weakest is not None:
                return weakest
        # 6) 买「简单」酒馆法术（有闲钱时；避免定向/Choose One 卡手）
        if self.buy_spells and not hero.hand_full():
            spell_buys = [d for d in buys
                          if isinstance(d.src_entity, Spell)
                          and self._simple_spell(game, d.src_entity)]
            if spell_buys:
                spell_buys.sort(key=lambda d: (d.cost, -_power(d.src_entity)))
                best = spell_buys[0]
                reserve = 1 if hero.gold >= 8 else self.spell_gold_reserve
                if hero.gold >= best.cost + reserve:
                    return best
        # 7) 黑暗赠礼（S14：3 金换带 gift 的随从；手牌满会进等待队列，跳过）
        dark = by_kind.get(_DARK_GIFT, [])
        if dark and hero.gold >= dark[0].cost and hero.board \
                and not hero.hand_full():
            return dark[0]
        # 8) Activate（一次性技能，通常正向）
        activates = by_kind.get(_ACTIVATE, [])
        if activates:
            return activates[0]
        # 9) 英雄技能（有金币就用；带目标时选价值最高的目标组合）
        powers = by_kind.get(_HERO_POWER, [])
        if powers:
            powers = [d for d in powers if hero.gold >= max(0, d.cost)]
            if powers:
                return max(powers, key=lambda d: (
                    _power(getattr(d, "tgt_entity", None)) +
                    (0.5 if getattr(d, "tgt_entity", None) is None else 0.0)))
        # 10) 刷新找更好的随从（金币利用率；手牌满时刷新无意义）
        rerolls = by_kind.get(_REROLL, [])
        if rerolls and not hero.hand_full():
            # 金币是"用掉才有价值"的资源：富余时把刷新上限放宽到足以
            # 花掉手头金币，找三连/更强随从（避免 10 金常年闲置）。
            limit = self.max_rerolls + max(0, int(hero.gold))
            if st["rerolls"] < limit and \
                    hero.gold >= max(0, rerolls[0].cost):
                st["rerolls"] += 1
                return rerolls[0]
        return None

    # ── 卖 / 打 / 买 评分 ──

    def _sell_decision(self, game: Any, hero: Any,
                       sells: Sequence[driver.ActionDescriptor],
                       minion_buys: Sequence[driver.ActionDescriptor]
                       ) -> Optional[driver.ActionDescriptor]:
        """满场时是否该卖：手牌/酒馆里有明显更强的随从才换，避免来回倒腾。"""
        weakest = min(sells, key=lambda d: _power(d.src_entity))
        w = _power(weakest.src_entity)
        margin = 1.5

        hand_minions = [e for e in hero.hand
                        if _is_playable_minion(game, e)]
        if hand_minions:
            best_hand = max(hand_minions, key=_power)
            if _power(best_hand) >= w + margin:
                return weakest
            # 高一级酒馆的随从即使身材暂时略差也值得换位（成长性）
            if (getattr(best_hand, "tech_level", 0) >=
                    getattr(weakest.src_entity, "tech_level", 0) + 2
                    and _power(best_hand) >= w):
                return weakest
        # 酒馆里有明显更强的随从：腾出场面位 + 手牌位以便买入
        if minion_buys and (not hero.hand_full() or hand_minions):
            best_buy = max(minion_buys, key=lambda d: _power(d.src_entity))
            if _power(best_buy.src_entity) >= w + margin:
                return weakest
        return None

    def _best_play(self, game: Any, hero: Any,
                   plays: Sequence[driver.ActionDescriptor]
                   ) -> driver.ActionDescriptor:
        def key(d: driver.ActionDescriptor) -> Tuple[float, int, int]:
            ent = d.src_entity
            val = _power(ent)
            if d.magnetic and d.tgt_entity is not None:
                # 吸附到最强的机械宿主
                val += _power(d.tgt_entity) * 0.5 + 0.4
            # 追加到最右优先（保持先手攻击顺序）
            pos_bonus = 1 if d.position == -1 else 0
            # 战吼有目标（通常正向）
            tgt_bonus = 1 if (d.tgt_entity is not None and not d.magnetic) else 0
            return (val, pos_bonus, tgt_bonus)

        return max(plays, key=key)

    def _best_buy(self, game: Any, hero: Any,
                  buys: Sequence[driver.ActionDescriptor]
                  ) -> driver.ActionDescriptor:
        race_counts: collections.Counter = collections.Counter()
        keyword_counts: collections.Counter = collections.Counter()
        for m in hero.board:
            for r in getattr(m, "races", ()) or ():
                race_counts[r] += 1
            for kw in _minion_keywords(m):
                keyword_counts[kw] += 1
        top_races = {r for r, _n in race_counts.most_common(3)}
        top_keywords = {k for k, _n in keyword_counts.most_common(4)}

        def score(d: driver.ActionDescriptor) -> float:
            ent = d.src_entity
            cost = max(1, int(d.cost))
            atk = float(getattr(ent, "atk", 0) or 0)
            hp = float(getattr(ent, "health", 0) or 0)
            tier = float(getattr(ent, "tech_level", 0) or 0)
            val = (atk * 1.1 + hp) / cost
            if d.cost <= 0:
                val += 2.0                       # 免费/生命购买价值极高
            val += 0.20 * tier
            # 种族协同（阵容方向）：同族权重随场上同族数量提升
            ent_races = set(getattr(ent, "races", ()) or ())
            shared = ent_races & top_races
            if shared:
                val *= 1.15 + 0.10 * max(race_counts[r] for r in shared)
            # 关键词协同（嘲讽/圣盾/剧毒/复生/亡语/磁力等）
            shared_kw = _minion_keywords(ent) & top_keywords
            if shared_kw:
                val *= 1.0 + 0.05 * min(3, len(shared_kw))
            # 空场时优先能立刻站场的随从
            if not hero.board:
                val *= 1.15
            return val

        return max(buys, key=score)

    @staticmethod
    def _simple_spell(game: Any, spell: Any) -> bool:
        """「简单法术」：无定向/无 Choose One（不会因无目标卡在手牌）。"""
        script = getattr(spell, "scripts", None)
        if script is None:
            return True
        if getattr(script, "choose_options", None):
            return False
        return not bool(getattr(script, "needs_target", False))

    # ── 供 demo / 智能体侧复用 ──

    def choose_option_index(self, obs: Any) -> int:
        """PendingChoice 阶段的选项下标（启发式）。"""
        pending = getattr(obs, "pending_choice", None)
        if pending is None:
            return 0
        kind = getattr(pending, "kind", "")
        options = getattr(pending, "options", ()) or ()
        if not options:
            return 0
        if kind in ("choose_one", "opponent", "holmes_guess") \
                or str(kind).startswith("choose_"):
            return 0
        best_i, best = 0, None
        for i, opt in enumerate(options):
            score = 0.0
            cid = getattr(opt, "card_id", "")
            if not cid:
                score = -1.0
            else:
                score = float(getattr(opt, "atk", 0) or 0) * 1.1 \
                    + float(getattr(opt, "health", 0) or 0)
                score += float(getattr(opt, "tier", 0) or 0) * 0.5
            if best is None or score > best:
                best_i, best = i, score
        return best_i


#: 默认教师实现（可后续替换为搜索/学习的策略）
TeacherPolicy = HeuristicPolicy
