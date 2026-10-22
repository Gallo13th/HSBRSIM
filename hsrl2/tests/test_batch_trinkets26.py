"""批次 trinkets26 行为层测试（3 张注册饰品 + 9 张 DEFERRED 台账守卫,
另有 4 张已由 batch_unlock_final 注册迁出, 作业单 2026-09-14）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线; 副本条款用
    `duplicate=True`）
  - 打出/施放: 真实 `game.play_minion`（`card_played` 广播路径）
  - 元素 give-stats: 真实 `game.run_script_hook(给予者, "battlecry")`
    （另一批次的脚本类——hooks 不受本批突变影响）
  - 摧毁: 真实 `game.destroy_minion`（`minion_destroyed` 唯一广播点）
  - 战斗: 真实 `game.run_combat` / `game.end_recruit_phase`，战斗内状态用
    `start_of_combat` 事件探针读取（SoC 钩子之后广播）——避免"战后回滚
    断言"在突变下变成空转（SOP §16c 手工判定法）

覆盖（SOP §16 空转测试判定法）: 每个行为测试至少含一条**正效果**断言
（正/负对照同方法内），owner 隔离（2 英雄），跨回合（真实
`end_recruit_phase`），落空不消耗资源，池占返配平，副本条款，
`CardDef.num` 双向钉死，无弱断言（`assertEqual` 钉死数值/身份）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 本批 id（CardDB 按名核实——禁止凭记忆写）
PLAGUERUNNER_PORTRAIT = "BG36_MagicItem_204"
AMPLIFYING_ESSENCE = "BG36_MagicItem_380"
ASSEMBLER_PORTRAIT = "BG36_MagicItem_841"

DEFERRED_IDS = [
    "BG35_MagicItem_820",   # Safety Patch — Secrets 子系统
    "BG35_MagicItem_823",   # Timeworn Candelabra — Minor Timewarp 定义域
    "BG35_MagicItem_921",   # Cowrie Necklace — "give stats" 类别
    "BG36_MagicItem_373",   # Multilayered Shield — 动态 EXTRA 提供者
]
# 930/214/216/308 已由 batch_unlock_final 注册（2026-09-15:
# copies_of_warband / trigger_friendly_rallies / add_card_aura /
# hero 级 CHOOSE_BOTH）——迁出 DEFERRED 台账，仍计入本批 16 张范围
MIGRATED_IDS = [
    "BG35_MagicItem_834",   # Rylak Portrait（batch_trinkets30）
    "BG35_MagicItem_920",   # Bubble Crown（batch_trinkets30）
    "BG35_MagicItem_922",   # Tide Raiser Portrait（batch_trinkets38）
    "BG35_MagicItem_923",   # Bewitched Ribbon（batch_trinkets31, 2026-09-18）
    "BG36_MagicItem_362",   # Cyclist Portrait（batch_trinkets31, 2026-09-18）
    "BG35_MagicItem_930",   # Warband Whistle
    "BG36_MagicItem_214",   # Insurrectionist's Blade
    "BG36_MagicItem_216",   # Eternal Portrait
    "BG36_MagicItem_308",   # Trailblazer Sticker
]

CORRECT_IDS = [PLAGUERUNNER_PORTRAIT, AMPLIFYING_ESSENCE,
               ASSEMBLER_PORTRAIT]

# 关联卡 / 测试用既有卡（按名核实）
PLAGUERUNNER = "BG34_690"        # 池随从 T4 Undead（数据链 126451）
PLAGUERUNNER_G = "BG34_690_G"    # 金色独立卡定义
AUTO_ASSEMBLER = "BG32_172"      # 池随从 T4 Mech（数据链 120025）
DANCING_BARNSTORMER = "BG26_162"  # Elemental give-stats 给予者（BC）
CHAMPION_OF_SARGERAS = "BG27_016"  # **非**元素 give-stats 给予者（BC）
UTILITY_DRONE = "BG26_152"       # Mech（无磁力连锁脚本）
ACCORD_O_TRON = "BG26_147"       # Mech（无磁力连锁脚本）
BANANA_SLAMMA = "BG26_802"       # Beast（负例）
FIRE_BALLER = "BG31_816"         # Elemental（无战吼）
SNOW_BALLER = "BG31_818"         # Elemental（无战吼）
METEORITE_CRASHER = "BG31_843"   # Elemental（无战吼）
MANA_SURGE = "BG32_846"          # Elemental（无战吼）

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 2601) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def num_of(card_id: str, index: int):
    return get_db().get(card_id).num(index)


def bind(game: Game, hero: Hero, tid: str, duplicate: bool = False):
    e = game.grant_trinket(hero, tid, duplicate=duplicate)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def tavern_put(game: Game, hero: Hero, card_id: str) -> Minion:
    """把随从放进酒馆展示区（give-stats 目标）。"""
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def play_from_hand(game: Game, hero: Hero, card_id: str) -> Minion:
    """真实打出路径（`card_played` 广播 + 战吼结算）。"""
    m = game.create_minion(card_id, controller=hero)
    hero.hand.append(m)
    assert game.play_minion(hero, m)
    return m


def hand_ids(hero: Hero) -> list:
    return [c.card_id for c in hero.hand]


def records(game: Game, owner, target_hero, fn) -> list:
    """在真实战斗的 SoC 阶段后（`start_of_combat` 事件）采集状态。

    `start_of_combat` 在 `CombatScheduler._start_of_combat_phase` 的
    SoC 钩子**之后**按英雄广播——是在战斗内观察 SoC 效果的唯一探针
    （战后棋盘已回滚）。闭包默认参数绑定 `_h` 防晚绑定（SOP §12
    item 1）。
    """
    out: list = []

    def cb(g, hero=None, _h=target_hero, **kw):
        if hero is not _h:
            return
        out.append(fn(g))

    game.events.register(Listener(event="start_of_combat", owner=owner,
                                  callback=cb))
    return out


# ══════════════════ 台账守卫（结构性——与钩子无关） ══════════════════


class TestRegistryLedger(unittest.TestCase):
    """注册表 / 卡定义 / DEFERRED 台账一致性（结构性测试）。"""

    def test_registry_contains_correct_ids(self):
        for tid in CORRECT_IDS:
            self.assertIn(tid, REGISTRY, f"{tid} 未注册")
            self.assertIsNotNone(get_db().get(tid))
        # 本批 3 张 CORRECT 均应为商店可提供成员
        offer = {d.id for d in get_db().trinket_offer_pool()}
        for tid in CORRECT_IDS:
            self.assertIn(tid, offer, f"{tid} 不在商店提供池")

    def test_deferred_ids_unregistered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNotNone(get_db().get(tid), f"{tid} 定义缺失")
            self.assertNotIn(tid, REGISTRY, f"{tid} 仍被注册（DEFERRED）")
        # 本批 id 集合互斥且恰好 16 张（12 DEFERRED 迁出 5 + 3 CORRECT）
        self.assertEqual(len(CORRECT_IDS) + len(DEFERRED_IDS)
                         + len(MIGRATED_IDS), 16)
        self.assertEqual(len(DEFERRED_IDS), 4)
        self.assertEqual(len(MIGRATED_IDS), 9)
        self.assertEqual(set(CORRECT_IDS) & set(DEFERRED_IDS), set())

    def test_deferred_ids_are_offer_pool_members(self):
        offer = {d.id for d in get_db().trinket_offer_pool()}
        self.assertEqual(sorted(set(DEFERRED_IDS) - offer), [])
        self.assertEqual(sorted(set(MIGRATED_IDS) - offer), [])

    def test_carddef_num_matches_text_params(self):
        # 数值权威双向钉死（文本占位符 → CardDef.num）
        self.assertEqual([num_of(AMPLIFYING_ESSENCE, i) for i in range(3)],
                         [5, 1, 1])
        self.assertEqual([num_of("BG36_MagicItem_216", i) for i in range(2)],
                         [4, 2])
        self.assertEqual([num_of("BG36_MagicItem_373", i) for i in range(2)],
                         [1, 2])
        self.assertEqual([num_of("BG35_MagicItem_920", i) for i in range(3)],
                         [14, 14, 4])   # 37.0: 阈值 12→14
        self.assertEqual([num_of("BG35_MagicItem_923", i) for i in range(3)],
                         [1, 1, 2])
        self.assertEqual(num_of("BG35_MagicItem_820", 0), 5)
        self.assertEqual(num_of("BG35_MagicItem_922", 0), 3)
        for tid in (PLAGUERUNNER_PORTRAIT, ASSEMBLER_PORTRAIT,
                    "BG35_MagicItem_823", "BG35_MagicItem_930",
                    "BG36_MagicItem_214", "BG36_MagicItem_308",
                    "BG36_MagicItem_362", "BG35_MagicItem_834",
                    "BG35_MagicItem_921"):
            self.assertEqual([num_of(tid, i) for i in range(4)],
                             [None, None, None, None], tid)


# ══════════════════ BG36_MagicItem_204 Plaguerunner Portrait ══════════


class TestPlaguerunnerPortrait(unittest.TestCase):
    """BG36_MagicItem_204 — Get a Plaguerunner; 招募期摧毁 Plaguerunner
    得一份 plain copy。"""

    TID = PLAGUERUNNER_PORTRAIT

    def test_bind_grants_pool_copy_and_destroy_yields_plain_copy(self):
        g = make_game()
        a = g.heroes[0]
        before = g.minion_pool.available(PLAGUERUNNER)
        bind(g, a, self.TID)
        # 第一条款: 数据链交付（占池 1 份）
        self.assertEqual(hand_ids(a), [PLAGUERUNNER])
        self.assertEqual(g.minion_pool.available(PLAGUERUNNER), before - 1)

        victim = put(g, a, PLAGUERUNNER)
        victim.set(GameTag.BASE_ATK, 99)      # 附魔态：plain copy 不得复制
        victim.set(GameTag.BASE_HEALTH, 99)
        victim.set(GameTag.HEALTH, 99)
        self.assertTrue(g.destroy_minion(victim, hero=a))
        copies = [c for c in a.hand if c.card_id == PLAGUERUNNER]
        self.assertEqual(len(copies), 2)      # 交付副本 + 摧毁副本
        fresh = copies[-1]
        d = get_db().get(PLAGUERUNNER)
        # plain = 死者**附魔态**（99/99）不被复制；但死者自己的亡语在死亡
        # 链中先结算（PlaguerunnerScript "outside combat" → 全体 Undead
        # +num(1) Attack 光环，RULES §6.19）→ 副本为 基础 + num(1)
        self.assertEqual((fresh.atk, fresh.max_health),
                         (d.atk + d.num(1), d.health))
        self.assertEqual(fresh._buffs, [])

    def test_negative_control_without_trinket_gives_no_copy(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)                  # 正路径: 有饰品 → 有副本
        victim = put(g, a, PLAGUERUNNER)
        g.destroy_minion(victim, hero=a)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)

        g2 = make_game()
        a2 = g2.heroes[0]
        victim2 = put(g2, a2, PLAGUERUNNER)
        g2.destroy_minion(victim2, hero=a2)
        self.assertEqual(hand_ids(a2).count(PLAGUERUNNER), 0)   # 负对照

    def test_outside_combat_only(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        g.in_combat = True
        victim = put(g, a, PLAGUERUNNER)
        g.destroy_minion(victim, hero=a)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 1)    # 战斗内不触发
        g.in_combat = False
        victim2 = put(g, a, PLAGUERUNNER)
        g.destroy_minion(victim2, hero=a)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)    # 战斗外触发

    def test_non_plaguerunner_and_opponent_destroyer_do_not_trigger(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, self.TID)
        # 负例 1: 摧毁非 Plaguerunner
        other = put(g, a, BANANA_SLAMMA)
        g.destroy_minion(other, hero=a)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 1)
        # 负例 2: 对手（施动方）摧毁自己的 Plaguerunner
        victim = put(g, b, PLAGUERUNNER)
        g.destroy_minion(victim, hero=b)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 1)
        # 正路径: 本人摧毁 → +1
        mine = put(g, a, PLAGUERUNNER)
        g.destroy_minion(mine, hero=a)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)

    def test_enemy_plaguerunner_destroyed_by_me_copies_to_me(self):
        """被摧毁者是**对手的** Plaguerunner 时副本进施动方手牌。"""
        g = make_game()
        a, b = g.heroes
        bind(g, a, self.TID)
        enemy = put(g, b, PLAGUERUNNER)
        g.destroy_minion(enemy, hero=a)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)   # 我拿到副本
        self.assertEqual(hand_ids(b).count(PLAGUERUNNER), 0)   # 对手没有

    def test_golden_plaguerunner_yields_golden_plain_copy(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        victim = put(g, a, PLAGUERUNNER)
        victim.set(GameTag.GOLDEN, True)      # 金色源（同家族身份）
        victim.set(GameTag.TRIPLE_BASE_CARD_ID, PLAGUERUNNER)
        g.destroy_minion(victim, hero=a)
        copies = [c for c in a.hand if c.card_id == PLAGUERUNNER_G]
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].is_golden)

    def test_copy_does_not_consume_pool(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        victim = put(g, a, PLAGUERUNNER)
        avail_before = g.minion_pool.available(PLAGUERUNNER)
        g.destroy_minion(victim, hero=a)
        # 摧毁回池 1 份、plain copy 不占池 → 净 +1（副本凭空多出）
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)
        self.assertEqual(g.minion_pool.available(PLAGUERUNNER),
                         avail_before + 1)

    def test_duplicate_copies_each_grant(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        bind(g, a, self.TID, duplicate=True)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)   # 交付两份
        # 金色 Plaguerunner 被摧毁 → 两份副本各给一份**金色** plain copy
        # （金色实体不参与三连，避免手牌 base 副本误合成干扰计数）
        victim = g.create_minion(PLAGUERUNNER, controller=a, golden=True)
        self.assertEqual(victim.card_id, PLAGUERUNNER_G)
        g.summon(a, victim, 0)
        g.destroy_minion(victim, hero=a)
        gold = [c for c in a.hand
                if c.card_id == PLAGUERUNNER_G and c.is_golden]
        self.assertEqual(len(gold), 2)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)

    def test_full_hand_queues_copy_instead_of_dropping(self):
        """满手 → 副本进等待队列（RULES §3.3），不是落空/丢失。"""
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        filler = get_db().get(BANANA_SLAMMA)
        while len(a.hand) < 10:
            a.hand.append(g.create_minion(filler.id, controller=a))
        self.assertEqual(len(a.hand), 10)
        queue_before = len(g.pending_hand_queue)
        victim = put(g, a, PLAGUERUNNER)
        g.destroy_minion(victim, hero=a)
        self.assertEqual(len(g.pending_hand_queue), queue_before + 1)
        _, queued = g.pending_hand_queue[-1]
        self.assertEqual(queued.card_id, PLAGUERUNNER)

    def test_listener_survives_end_recruit_phase(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        g.end_recruit_phase()                 # 跨过完整战斗回合
        self.assertGreater(len(a.trinkets), 0)
        victim = put(g, a, PLAGUERUNNER)
        g.destroy_minion(victim, hero=a)
        self.assertEqual(hand_ids(a).count(PLAGUERUNNER), 2)


# ══════════════════ BG36_MagicItem_380 Amplifying Essence ══════════════


class TestAmplifyingEssence(unittest.TestCase):
    """BG36_MagicItem_380 — 元素 give-stats 额外 +num(1)/+num(2)，
    每 num(0) 个元素 improve 一次。"""

    TID = AMPLIFYING_ESSENCE

    def test_bind_sets_tags_and_opponent_isolated(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, self.TID)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0),
                         num_of(self.TID, 1))
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0),
                         num_of(self.TID, 2))
        self.assertEqual(b.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 0)
        self.assertEqual(b.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), 0)

    def test_elemental_giver_bonus_but_non_elemental_giver_not(self):
        giver = get_db().get(DANCING_BARNSTORMER)
        # 正路径: 元素给予者吃加成
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        target = tavern_put(g, a, DANCING_BARNSTORMER)
        barn = put(g, a, DANCING_BARNSTORMER)
        base0 = (target.atk, target.max_health)
        g.run_script_hook(barn, "battlecry")
        self.assertEqual(target.atk - base0[0],
                         giver.num(0) + num_of(self.TID, 1))
        self.assertEqual(target.max_health - base0[1],
                         giver.num(1) + num_of(self.TID, 2))
        # 负对照 1: 无饰品 → 只有基础额
        g2 = make_game()
        a2 = g2.heroes[0]
        target2 = tavern_put(g2, a2, DANCING_BARNSTORMER)
        barn2 = put(g2, a2, DANCING_BARNSTORMER)
        base = (target2.atk, target2.max_health)
        g2.run_script_hook(barn2, "battlecry")
        self.assertEqual(target2.atk - base[0], giver.num(0))
        self.assertEqual(target2.max_health - base[1], giver.num(1))
        # 负对照 2: 非元素给予者（Champion of Sargeras）不吃加成
        champ = get_db().get(CHAMPION_OF_SARGERAS)
        g3 = make_game()
        a3 = g3.heroes[0]
        bind(g3, a3, self.TID)
        target3 = tavern_put(g3, a3, DANCING_BARNSTORMER)
        ch = put(g3, a3, CHAMPION_OF_SARGERAS)
        base3 = (target3.atk, target3.max_health)
        g3.run_script_hook(ch, "battlecry")
        self.assertEqual(target3.atk - base3[0], champ.num(0))
        self.assertEqual(target3.max_health - base3[1], champ.num(1))

    def test_improve_after_threshold_elementals_rolled(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        threshold = num_of(self.TID, 0)
        step_a, step_h = num_of(self.TID, 1), num_of(self.TID, 2)
        order = [DANCING_BARNSTORMER, FIRE_BALLER, SNOW_BALLER,
                 METEORITE_CRASHER, MANA_SURGE]
        for cid in order[:threshold - 1]:
            play_from_hand(g, a, cid)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), step_a)
        play_from_hand(g, a, order[threshold - 1])
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 2 * step_a)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0), 2 * step_h)
        # 滚动: 再满 threshold 个再提升（清零复位）。棋盘上限 7 → 先清空
        # 已打出的随从（计数只由 `card_played` 驱动，与在场状态无关）
        a.board.clear()
        for cid in order[:threshold]:
            play_from_hand(g, a, cid)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 3 * step_a)

    def test_non_elemental_play_does_not_advance_counter(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        step_a = num_of(self.TID, 1)
        for cid in [DANCING_BARNSTORMER, FIRE_BALLER, SNOW_BALLER,
                    METEORITE_CRASHER]:
            play_from_hand(g, a, cid)
        play_from_hand(g, a, BANANA_SLAMMA)          # 非元素不消耗计数
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), step_a)
        play_from_hand(g, a, MANA_SURGE)             # 第 num(0) 个元素
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 2 * step_a)

    def test_opponent_elemental_play_does_not_advance(self):
        g = make_game()
        a, b = g.heroes
        bind(g, a, self.TID)
        step_a = num_of(self.TID, 1)
        for cid in [DANCING_BARNSTORMER, FIRE_BALLER, SNOW_BALLER,
                    METEORITE_CRASHER, MANA_SURGE]:
            play_from_hand(g, b, cid)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), step_a)
        self.assertEqual(b.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 0)
        # 正路径: 本人打满 threshold 个 → 提升
        for cid in [DANCING_BARNSTORMER, FIRE_BALLER, SNOW_BALLER,
                    METEORITE_CRASHER, MANA_SURGE]:
            play_from_hand(g, a, cid)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 2 * step_a)

    def test_duplicate_copies_stack(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        bind(g, a, self.TID, duplicate=True)
        step_a = num_of(self.TID, 1)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 2 * step_a)
        for cid in [DANCING_BARNSTORMER, FIRE_BALLER, SNOW_BALLER,
                    METEORITE_CRASHER, MANA_SURGE]:
            play_from_hand(g, a, cid)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 4 * step_a)

    def test_listener_survives_end_recruit_phase(self):
        g = make_game()
        a = g.heroes[0]
        bind(g, a, self.TID)
        step_a = num_of(self.TID, 1)
        g.end_recruit_phase()                        # 跨回合
        for cid in [DANCING_BARNSTORMER, FIRE_BALLER, SNOW_BALLER,
                    METEORITE_CRASHER, MANA_SURGE]:
            play_from_hand(g, a, cid)
        self.assertEqual(a.get(GameTag.ELEMENTAL_EXTRA_ATK, 0), 2 * step_a)


# ══════════════════ BG36_MagicItem_841 Assembler Portrait ══════════════


class TestAssemblerPortrait(unittest.TestCase):
    """BG36_MagicItem_841 — SoC: 把 Auto Assembler 磁力吸附到每只机械。"""

    TID = ASSEMBLER_PORTRAIT

    def _setup(self, trinket: bool = True, seed: int = 7):
        g = make_game(seed=seed)
        a, b = g.heroes
        if trinket:
            bind(g, a, self.TID)
        m1 = put(g, a, UTILITY_DRONE)
        m2 = put(g, a, ACCORD_O_TRON)
        beast = put(g, a, BANANA_SLAMMA)
        opp = put(g, b, UTILITY_DRONE)
        return g, a, b, m1, m2, beast, opp

    @staticmethod
    def _u() -> tuple[int, int]:
        """UTILITY_DRONE 基础属性（37.0 生命 6→5，禁止硬编码）。"""
        d = get_db().get(UTILITY_DRONE)
        return (d.atk, d.health)

    def test_start_of_combat_magnetizes_each_mech_only(self):
        g, a, b, m1, m2, beast, opp = self._setup(True)
        asm = get_db().get(AUTO_ASSEMBLER)
        u = self._u()

        def snap(gg):
            return {
                "m1": (m1.atk, m1.max_health,
                       len(gg._magnetic_stack.get(m1.uuid, [])),
                       m1.has(GameTag.DEATHRATTLE)),
                "m2": (m2.atk, m2.max_health,
                       len(gg._magnetic_stack.get(m2.uuid, []))),
                "beast": (beast.atk, beast.max_health,
                          len(gg._magnetic_stack.get(beast.uuid, []))),
                "opp": (opp.atk, opp.max_health,
                        len(gg._magnetic_stack.get(opp.uuid, []))),
            }

        seen = records(g, m1, a, snap)
        g.run_combat(a, b)
        self.assertEqual(len(seen), 1)
        mid = seen[0]
        self.assertEqual(mid["m1"][:3],
                         (u[0] + asm.atk, u[1] + asm.health, 1))
        self.assertTrue(mid["m1"][3])                 # 亡语并入宿主
        self.assertEqual(mid["m2"][:3],
                         (3 + asm.atk, 3 + asm.health, 1))
        self.assertEqual(mid["beast"][:3], (3, 6, 0))  # 非机械不变
        self.assertEqual(mid["opp"][:3], (u[0], u[1], 0))    # 对手不变
        # 战斗级: 战后栈复原 + 属性回滚
        self.assertEqual((m1.atk, m1.max_health), (u[0], u[1]))
        self.assertEqual(len(g._magnetic_stack.get(m1.uuid, [])), 0)
        self.assertFalse(m1.has(GameTag.DEATHRATTLE))

    def test_negative_control_without_trinket(self):
        g, a, b, m1, m2, beast, opp = self._setup(False)
        u = self._u()

        def snap(gg):
            return (m1.atk, m1.max_health,
                    len(gg._magnetic_stack.get(m1.uuid, [])),
                    m2.atk, m2.max_health,
                    len(gg._magnetic_stack.get(m2.uuid, [])))

        seen = records(g, m1, a, snap)
        g.run_combat(a, b)
        self.assertEqual(seen, [(u[0], u[1], 0, 3, 3, 0)])
        # 对照: 同 setup + 饰品 → 有吸附（同一方法内正/负对照）
        g2, a2, b2, n1, n2, _, _ = self._setup(True)
        asm = get_db().get(AUTO_ASSEMBLER)
        seen2 = records(g2, n1, a2, lambda gg: (
            n1.atk, n1.max_health,
            len(gg._magnetic_stack.get(n1.uuid, []))))
        g2.run_combat(a2, b2)
        self.assertEqual(seen2, [(u[0] + asm.atk, u[1] + asm.health, 1)])

    def test_combat_only_restored_and_not_accumulated(self):
        g, a, b, m1, m2, beast, opp = self._setup(True)
        asm = get_db().get(AUTO_ASSEMBLER)
        u = self._u()
        seen = records(g, m1, a, lambda gg: (
            m1.atk, m1.max_health,
            len(gg._magnetic_stack.get(m1.uuid, []))))
        g.run_combat(a, b)
        self.assertEqual((m1.atk, m1.max_health), (u[0], u[1]))
        self.assertEqual(len(g._magnetic_stack.get(m1.uuid, [])), 0)
        g.run_combat(a, b)
        self.assertEqual(seen,
                         [(u[0] + asm.atk, u[1] + asm.health, 1),
                          (u[0] + asm.atk, u[1] + asm.health, 1)])  # 不累积

    def test_zero_pool_operation_and_empty_mech_board_fizzles(self):
        g, a, b, m1, m2, beast, opp = self._setup(True)
        avail = g.minion_pool.available(AUTO_ASSEMBLER)
        seen = records(g, m1, a, lambda gg: len(
            gg._magnetic_stack.get(m1.uuid, [])))
        g.run_combat(a, b)
        self.assertEqual(seen, [1])                    # 正效果确实发生
        self.assertEqual(g.minion_pool.available(AUTO_ASSEMBLER), avail)
        # 无机械棋盘 → 落空（不创建实体、池不变）
        g2 = make_game(seed=8)
        a2, b2 = g2.heroes
        bind(g2, a2, self.TID)
        beast2 = put(g2, a2, BANANA_SLAMMA)
        avail2 = g2.minion_pool.available(AUTO_ASSEMBLER)
        t2 = a2.trinkets[0]
        g2.run_script_hook(t2, "start_of_combat")
        self.assertEqual(len(g2._magnetic_stack.get(beast2.uuid, [])), 0)
        self.assertEqual(g2.minion_pool.available(AUTO_ASSEMBLER), avail2)

    def test_duplicate_copies_attach_twice(self):
        g = make_game(seed=9)
        a, b = g.heroes
        bind(g, a, self.TID)
        bind(g, a, self.TID, duplicate=True)
        u = self._u()
        m1 = put(g, a, UTILITY_DRONE)
        put(g, b, UTILITY_DRONE)
        asm = get_db().get(AUTO_ASSEMBLER)
        seen = records(g, m1, a, lambda gg: (
            m1.atk, m1.max_health,
            len(gg._magnetic_stack.get(m1.uuid, []))))
        g.run_combat(a, b)
        self.assertEqual(seen,
                         [(u[0] + 2 * asm.atk, u[1] + 2 * asm.health, 2)])

    def test_engine_dispatched_via_end_recruit_phase(self):
        g, a, b, m1, m2, beast, opp = self._setup(True)
        asm = get_db().get(AUTO_ASSEMBLER)
        u = self._u()
        seen = records(g, m1, a, lambda gg: (
            m1.atk, m1.max_health,
            len(gg._magnetic_stack.get(m1.uuid, []))))
        g.end_recruit_phase()
        self.assertEqual(seen, [(u[0] + asm.atk, u[1] + asm.health, 1)])
        self.assertEqual(len(g._magnetic_stack.get(m1.uuid, [])), 0)


if __name__ == "__main__":
    unittest.main()
