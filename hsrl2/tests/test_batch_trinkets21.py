"""批次 trinkets21 行为层测试（2 张注册饰品, 作业单 2026-09-12）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）;
    副本条款用 `duplicate=True`（RULES §7.4.3）
  - 施放: 真实 `game.cast_spell_effect`（RULES §7.4.7b——效果施法）;
    以实例级 spy 包装该公开入口记录 (hero, card_id, 返回值),
    再用真实施放断言效果落地（不动池 / 不计费 / 不入手牌）
  - 回合: 真实 `game.end_recruit_phase`（下回合 SoT 钩子重复）
  - 候选口径: 真实 `db.pool_spells()` 的 `tech_level <= hero.tavern_tier`
    只读枚举（**不**用 `SpellPool.draw_tavern`——会真实抽池）

覆盖（SOP §16 空转测试判定法）: 每个行为测试至少含一条**正效果**断言
（负对照与正对照同方法内），owner 隔离（2 英雄），跨回合语义，
无候选/无合法目标落空且不消耗资源，RNG 确定性（同 seed 序列可复现），
副本条款（两份副本各结算一次），CardDef.num 双向钉死。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 本批 id（CardDB 按名核实——禁止凭记忆写 id）
LAVISH_CAPE = "BG32_MagicItem_286"
WAR_DRUM = "BG32_MagicItem_416"

# 测试用既有卡（按名核实; 选无 on_summon 干扰的简单随从）
MURLOC = "BG22_202"        # Tad（race=MURLOC，仅 on_sell）
BEAST = "BG25_806"         # Sly Raptor（race=BEAST，仅 deathrattle）
UNDEAD = "BG25_013"        # Rot Hide Gnoll（race=UNDEAD，无钩子）
UNDEAD_B = "BG25_008"      # Eternal Knight（race=UNDEAD，无钩子）
AMALGAM = "BG27_080"       # Motley Phalanx（race=ALL）
TYPELESS_A = "BG24_715"    # Patient Scout（race=NONE）
TYPELESS_B = "BG25_016"    # Sin'dorei Straight Shot（race=NONE）

# 单候选注入用既有池法术（按名核实）
BANANA = "BG28_897"        # Tavern Dish Banana 定向 +{0}/+{1}
BUTCHERING = "BG28_604"    # Butchering 定向"友方 Undead"（无 Undead → 落空）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str = LAVISH_CAPE):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def spy_casts(game: Game) -> list:
    """包装公开入口 `Game.cast_spell_effect` 记录每次施放。

    返回 [(hero, card_id, result), ...]——`result` 为真实入口返回值
    （True=已结算 / False=落空）。只做观测，不改语义。
    """
    calls: list = []
    orig = game.cast_spell_effect

    def wrapper(hero, card_id, target=None):
        result = orig(hero, card_id, target)
        calls.append((hero, card_id, result))
        return result

    game.cast_spell_effect = wrapper
    return calls


def pool_spell_ids() -> list:
    return [d.id for d in get_db().pool_spells()]


def spell_pool_snapshot(game: Game, ids=None) -> dict:
    ids = ids if ids is not None else pool_spell_ids()
    return {i: game.spell_pool.available(i) for i in ids}


def total_atk(hero: Hero) -> int:
    return sum(m.atk for m in hero.board)


def total_max_health(hero: Hero) -> int:
    return sum(m.max_health for m in hero.board)


# ══════════════ BG32_MagicItem_286 Lavish Cape ══════════════


class TestLavishCapeCasting(unittest.TestCase):
    """每个不同友方随从类型各施放 1 个随机酒馆法术; on_bind + 每回合重复。"""

    def test_bind_casts_one_per_distinct_type(self):
        g = make_game(3001)
        a, b = g.heroes
        put(g, a, MURLOC)
        put(g, a, BEAST)
        put(g, a, UNDEAD)
        calls = spy_casts(g)
        bind(g, a)
        self.assertEqual(len(calls), 3)                    # 3 种类型 → 3 次
        ids = set(pool_spell_ids())
        for hero, cid, result in calls:
            self.assertIs(hero, a)                         # 只作用于本人
            self.assertIn(cid, ids, cid)                   # 池法术候选
            self.assertLessEqual(get_db().get(cid).tech_level,
                                 a.tavern_tier)
            self.assertTrue(result)

    def test_same_race_counts_once(self):
        g = make_game(3002)
        a, b = g.heroes
        put(g, a, UNDEAD)
        put(g, a, UNDEAD_B)
        calls = spy_casts(g)
        bind(g, a)
        self.assertEqual(len(calls), 1)                    # 同族去重

    def test_typeless_minions_count_as_one_type(self):
        """Race.NONE 计入为一种（同文本先例 BG34_272 裁定，见脚本 docstring）。"""
        g = make_game(3003)
        a, b = g.heroes
        put(g, a, TYPELESS_A)
        put(g, a, TYPELESS_B)
        calls = spy_casts(g)
        bind(g, a)
        self.assertEqual(len(calls), 1)                    # 两无类型 → 1 种
        # 正对照: 无类型 + 野兽 = 2 种
        g2 = make_game(3003)
        a2, b2 = g2.heroes
        put(g2, a2, TYPELESS_A)
        put(g2, a2, BEAST)
        calls2 = spy_casts(g2)
        bind(g2, a2)
        self.assertEqual(len(calls2), 2)

    def test_amalgam_counts_as_one_type(self):
        """Race.ALL 计为一种（一只随从只有一个 race tag）。"""
        g = make_game(3004)
        a, b = g.heroes
        put(g, a, AMALGAM)
        calls = spy_casts(g)
        bind(g, a)
        self.assertEqual(len(calls), 1)
        # 正对照: Amalgam + 野兽 = 2 种
        g2 = make_game(3004)
        a2, b2 = g2.heroes
        put(g2, a2, AMALGAM)
        put(g2, a2, BEAST)
        calls2 = spy_casts(g2)
        bind(g2, a2)
        self.assertEqual(len(calls2), 2)

    def test_candidates_capped_at_tavern_tier(self):
        g = make_game(3005)
        a, b = g.heroes
        put(g, a, MURLOC)
        put(g, a, BEAST)
        a.set(GameTag.TAVERN_TIER, 3)
        calls = spy_casts(g)
        bind(g, a)
        self.assertEqual(len(calls), 2)
        for _, cid, _ in calls:
            self.assertLessEqual(get_db().get(cid).tech_level, 3, cid)

    def test_start_of_turn_repeats(self):
        g = make_game(3006)
        a, b = g.heroes
        put(g, a, MURLOC)
        put(g, a, BEAST)
        calls = spy_casts(g)
        t = bind(g, a)
        self.assertEqual(len(calls), 2)                    # on_bind 首次
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(calls), 4)                    # 每回合重复
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(calls), 6)

    def test_real_turn_advance_repeats(self):
        """真实 `end_recruit_phase`（下回合 SoT）→ 再施放一次。"""
        g = make_game(3007)
        a, b = g.heroes
        t = bind(g, a)                                     # 空板 → 0 次
        put(g, a, MURLOC)
        put(g, a, UNDEAD)
        calls = spy_casts(g)
        seen = {}

        def on_ts(g_, turn=None, hero=None, **kw):
            if hero is a:
                seen.setdefault("turn", turn)

        g.events.register(Listener(event="turn_start", owner=t,
                                   callback=on_ts))
        g.end_recruit_phase()
        self.assertGreaterEqual(seen.get("turn", 0), 2)     # 确实换了回合
        self.assertEqual(len(calls), 2)                     # 2 种类型 → 2 次
        self.assertTrue(all(h is a for h, _, _ in calls))

    def test_opponent_board_not_counted_and_untouched(self):
        g = make_game(3008)
        a, b = g.heroes
        bm = [put(g, b, MURLOC), put(g, b, BEAST), put(g, b, UNDEAD)]
        put(g, a, MURLOC)                                  # 只有 1 种
        a.set(GameTag.TAVERN_TIER, 1)
        gold_b, hand_b = b.gold, list(b.hand)
        calls = spy_casts(g)
        bind(g, a)
        self.assertEqual(len(calls), 1)                    # 对手 3 种不计入
        self.assertIs(calls[0][0], a)
        self.assertEqual([m.card_id for m in b.board],
                         [MURLOC, BEAST, UNDEAD])           # 对手棋盘不变
        self.assertTrue(all(m in b.board for m in bm))
        self.assertEqual(b.gold, gold_b)
        self.assertEqual(list(b.hand), hand_b)

    def test_empty_board_whiffs_then_positive_control(self):
        g = make_game(3009)
        a, b = g.heroes
        t = bind(g, a)
        gold0, hand0 = a.gold, len(a.hand)
        calls = spy_casts(g)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(calls), 0)                    # 空板落空
        self.assertEqual((a.gold, len(a.hand)), (gold0, hand0))
        put(g, a, MURLOC)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(calls), 1)                    # 正对照

    def test_no_candidates_whiffs_without_cost(self):
        """酒馆等级 0 → 无 tier 合法候选: 0 次施放且不消耗任何资源。"""
        g = make_game(3010)
        a, b = g.heroes
        put(g, a, MURLOC)
        a.set(GameTag.TAVERN_TIER, 0)
        gold0, hand0 = a.gold, len(a.hand)
        pool0 = spell_pool_snapshot(g)
        calls = spy_casts(g)
        t = bind(g, a)
        self.assertEqual(len(calls), 0)                    # 无候选
        self.assertEqual(a.gold, gold0)                    # 不计费
        self.assertEqual(len(a.hand), hand0)               # 不入手牌
        self.assertEqual(spell_pool_snapshot(g), pool0)    # 不动法术池
        a.set(GameTag.TAVERN_TIER, 1)
        g.run_script_hook(t, "start_of_turn")
        self.assertEqual(len(calls), 1)                    # 正对照

    def test_rng_sequence_deterministic_with_seed(self):
        def seq(seed):
            g = make_game(seed)
            a, b = g.heroes
            put(g, a, MURLOC)
            put(g, a, BEAST)
            put(g, a, UNDEAD)
            calls = spy_casts(g)
            bind(g, a)
            return [c[1] for c in calls]

        s1, s2 = seq(4242), seq(4242)
        self.assertEqual(len(s1), 3)                       # 非空（防空转假通过）
        self.assertEqual(s1, s2)                           # 同 seed 可复现

    def test_two_copies_each_cast(self):
        """副本条款: 两份副本各自 on_bind 结算（实例无私有状态, 不去重）。"""
        g = make_game(3012)
        a, b = g.heroes
        put(g, a, MURLOC)
        put(g, a, BEAST)
        calls = spy_casts(g)
        bind(g, a)
        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(g.grant_trinket(a, LAVISH_CAPE, duplicate=True))
        self.assertEqual(len(a.trinkets), 2)
        self.assertEqual(len(calls), 4)                    # 第二份各再施放一次


class TestLavishCapeCastEffects(unittest.TestCase):
    """候选注入单张已知法术 → 断言真实施放效果（不动池 / 不计费 / 落空）。"""

    def _patched(self, spell_id):
        return patch.object(get_db(), "pool_spells",
                            return_value=[get_db().get(spell_id)])

    def test_cast_effect_lands_buff(self):
        g = make_game(3013)
        a, b = g.heroes
        put(g, a, MURLOC)
        put(g, a, BEAST)
        d = get_db().get(BANANA)
        atk0, hp0 = total_atk(a), total_max_health(a)
        with self._patched(BANANA):
            calls = spy_casts(g)
            bind(g, a)
        self.assertEqual(len(calls), 2)                    # 2 种类型 → 2 次施放
        self.assertTrue(all(r for _, _, r in calls))
        self.assertEqual(total_atk(a) - atk0, 2 * d.num(0))
        self.assertEqual(total_max_health(a) - hp0, 2 * d.num(1))

    def test_cast_does_not_touch_pool_or_gold_or_hand(self):
        g = make_game(3014)
        a, b = g.heroes
        put(g, a, MURLOC)
        put(g, a, BEAST)
        ids = pool_spell_ids()
        pool0 = spell_pool_snapshot(g, ids)
        gold0, hand0 = a.gold, len(a.hand)
        atk0 = total_atk(a)
        with self._patched(BANANA):
            calls = spy_casts(g)
            bind(g, a)
            pool1 = spell_pool_snapshot(g, ids)
        self.assertEqual(len(calls), 2)
        self.assertEqual(pool0, pool1)                     # 不动法术池
        self.assertEqual(a.gold, gold0)                    # 效果施法不计费
        self.assertEqual(len(a.hand), hand0)               # 不入手牌
        self.assertGreater(total_atk(a), atk0)             # 正对照: 效果真落地

    def test_targeted_spell_without_legal_target_whiffs(self):
        """定向法术无合法目标（无 Undead）→ 该次落空且无副作用。"""
        g = make_game(3015)
        a, b = g.heroes
        m = put(g, a, MURLOC)                              # 非 Undead
        a.set(GameTag.TAVERN_TIER, 6)                      # Butchering 为 T5
        gold0, hand0 = a.gold, len(a.hand)
        pool0 = spell_pool_snapshot(g)
        with self._patched(BUTCHERING):
            calls = spy_casts(g)
            bind(g, a)
        self.assertEqual(len(calls), 1)                    # 1 种类型 → 1 次尝试
        self.assertFalse(calls[0][2])                      # 落空
        self.assertFalse(m.dead)
        self.assertIn(m, a.board)
        self.assertEqual(a.gold, gold0)                    # 不消耗资源
        self.assertEqual(len(a.hand), hand0)
        self.assertEqual(spell_pool_snapshot(g), pool0)

    def test_targeted_spell_with_legal_target_resolves(self):
        """正对照: 有合法目标（Undead）→ 同一定向法术真正结算。"""
        g = make_game(3016)
        a, b = g.heroes
        u = put(g, a, UNDEAD)
        a.set(GameTag.TAVERN_TIER, 6)                      # Butchering 为 T5
        with self._patched(BUTCHERING):
            calls = spy_casts(g)
            bind(g, a)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][2])                       # 已结算
        self.assertTrue(u.dead or u not in a.board)        # 目标被摧毁
        self.assertEqual(len(a.board), 0)


# ══════════════ BG32_MagicItem_416 War Drum ══════════════

# 战吼结算计数探针（测试自带, 不属于本批脚本类——空转审计不会替换它）
_BC_HITS: list = []


class _BcProbe:
    @staticmethod
    def battlecry(source, game, ctx):
        _BC_HITS.append(source.card_id)


class TestWarDrum(unittest.TestCase):
    """每回合首个战吼额外触发 num(1)=2 次（共 3 次结算）; 每回合重复。"""

    TID = WAR_DRUM

    def _play_battlecry(self, g: Game, hero: Hero) -> int:
        """打出一张带战吼的探针随从, 返回本次战吼的结算次数。"""
        _BC_HITS.clear()
        m = Minion("TEST_BC", "B", atk=1, health=1)
        m.set(GameTag.BATTLECRY, True)
        m.scripts = _BcProbe
        hero.add_to_hand(m)
        g.play_minion(hero, m)
        return len(_BC_HITS)

    def test_bind_declares_two_dimension_quota(self):
        g = make_game(3201)
        a, b = g.heroes
        d = get_db().get(WAR_DRUM)
        bind(g, a, WAR_DRUM)
        self.assertEqual(a.extra_triggers["bc_first"], d.num(0))
        self.assertEqual(a.extra_triggers["bc_first_times"], d.num(1))
        self.assertNotIn("bc_first", b.extra_triggers)          # owner 隔离
        self.assertNotIn("bc_first_times", b.extra_triggers)
        # 无饰品对照: 两 key 均不声明
        g2 = make_game(3201)
        self.assertNotIn("bc_first", g2.heroes[0].extra_triggers)

    def test_first_battlecry_three_and_second_once(self):
        g = make_game(3202)
        a, b = g.heroes
        bind(g, a, WAR_DRUM)
        self.assertEqual(self._play_battlecry(g, a), 3)         # 1 + 2
        self.assertEqual(self._play_battlecry(g, a), 1)         # 额度已用完

    def test_without_trinket_control(self):
        g = make_game(3203)
        a, b = g.heroes
        self.assertEqual(self._play_battlecry(g, a), 1)         # 无饰品基线
        g2 = make_game(3203)
        a2, b2 = g2.heroes
        bind(g2, a2, WAR_DRUM)
        self.assertEqual(self._play_battlecry(g2, a2), 3)       # 正对照

    def test_next_turn_first_battlecry_three_again(self):
        g = make_game(3204)
        a, b = g.heroes
        bind(g, a, WAR_DRUM)
        self.assertEqual(self._play_battlecry(g, a), 3)
        g._begin_recruit_for(a)                                 # 换回合（重置已用）
        self.assertEqual(a.extra_trigger_used.get("bc_first"), 0)
        self.assertEqual(self._play_battlecry(g, a), 3)         # 又是 3 次

    def test_real_turn_advance_repeats(self):
        """真实 `end_recruit_phase` → 下回合首个战吼仍 3 次。"""
        g = make_game(3208)
        a, b = g.heroes
        bind(g, a, WAR_DRUM)
        self.assertEqual(self._play_battlecry(g, a), 3)
        g.end_recruit_phase()
        self.assertGreaterEqual(g.turn, 2)
        self.assertEqual(self._play_battlecry(g, a), 3)

    def test_stacks_with_bc_times_without_overwrite(self):
        g = make_game(3205)
        a, b = g.heroes
        a.extra_triggers["bc_times"] = 1                        # Gilnean 类来源
        bind(g, a, WAR_DRUM)
        self.assertEqual(a.extra_triggers.get("bc_times"), 1)   # 不被覆盖
        self.assertEqual(self._play_battlecry(g, a), 4)         # 1+1+2
        self.assertEqual(self._play_battlecry(g, a), 2)         # 1+1

    def test_start_of_turn_rewrites_clobbered_quota(self):
        g = make_game(3206)
        a, b = g.heroes
        t = bind(g, a, WAR_DRUM)
        d = get_db().get(WAR_DRUM)
        a.extra_triggers["bc_first"] = 99                       # 外部改写
        a.extra_triggers["bc_first_times"] = 7
        g.run_script_hook(t, "start_of_turn")                   # 覆写式恢复
        self.assertEqual(a.extra_triggers["bc_first"], d.num(0))
        self.assertEqual(a.extra_triggers["bc_first_times"], d.num(1))

    def test_opponent_quota_isolation(self):
        g = make_game(3207)
        a, b = g.heroes
        bind(g, a, WAR_DRUM)
        self.assertEqual(self._play_battlecry(g, b), 1)         # 对手不享受
        self.assertEqual(self._play_battlecry(g, a), 3)         # 正对照


# ══════════════ 注册表 / 台账守卫 ══════════════


class TestRegistryLedger(unittest.TestCase):
    """注册表、台账与引擎数据/文本证据（结构性——与钩子无关）。
    @engine-only
    """

    def test_implemented_registered(self):
        self.assertIn(LAVISH_CAPE, REGISTRY)
        self.assertEqual(REGISTRY[LAVISH_CAPE].__name__, "LavishCapeScript")
        self.assertIn(WAR_DRUM, REGISTRY)
        self.assertEqual(REGISTRY[WAR_DRUM].__name__, "WarDrumScript")

    def test_offer_pool_membership(self):
        pool = {d.id for d in get_db().trinket_offer_pool()}
        self.assertIn(LAVISH_CAPE, pool)
        self.assertIn(WAR_DRUM, pool)

    def test_lavish_cape_has_no_template_params(self):
        d = get_db().get(LAVISH_CAPE)
        self.assertTrue(all(d.num(i) is None for i in range(4)))

    def test_lavish_cape_card_text_matches_xml(self):
        d = get_db().get(LAVISH_CAPE)
        self.assertIn("Cast a random Tavern spell", d.text)
        self.assertIn("each different friendly minion type", d.text)

    def test_war_drum_card_text_matches_xml_and_params(self):
        """数据权威: "One Battlecry each turn triggers two extra times"
        （本批订正 RULES §6.20 / 兄弟批次 docstring 的误引文本）。"""
        d = get_db().get(WAR_DRUM)
        self.assertIn("two extra times", d.text)
        self.assertNotIn("first", d.text.lower())
        self.assertEqual(d.num(0), 1)                      # "One Battlecry" / {0}
        self.assertEqual(d.num(1), 2)                      # "two extra times"


if __name__ == "__main__":
    unittest.main()
