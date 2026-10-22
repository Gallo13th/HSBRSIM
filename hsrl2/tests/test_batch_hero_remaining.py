"""批次 hero_remaining 语义测试（作业单 2026-09-02，6 注册项）。

覆盖: TB_BaconShop_HP_057 Adventure!（Finley）/ BG22_HERO_000p_Alt Lock
and Load（Tavish）/ BG24_HERO_100p Whodunit?（Denathrius）/
BG30_HERO_304p Fantastic Treasure（Marin）/ BG32_HERO_002p Growing
Collection（Buttons）/ TB_BaconShop_HP_102 Three Wishes（Zephrys）。

驱动协议: ``game.replace_hero_power(hero, power_id)`` +
``game.start_game()``（与真实对局同一 on_bind 接线路径）; 主动/定向技能
走 ``game.use_hero_power`` + ``PendingChoice.choose`` 真实结算; 数值期望
一律 ``db.get(power_id).num(N)`` 权威。DEFERRED 15 项断言不注册
（见 batch_hero_remaining.py 头台账）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2 import entity as E
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_hero_remaining import (
    _draftable_hero_power_ids,
)
from hsrl2.tags import CardType, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(power_id: str | None = None, seed: int = 7,
              heroes: int = 2) -> Game:
    hs = [Hero(f"TEST_H_{i}", chr(ord("A") + i)) for i in range(heroes)]
    game = Game(hs, get_db(), seed=seed)
    if power_id is not None:
        game.replace_hero_power(game.heroes[0], power_id)
    game.start_game()
    return game


def choices_of(game: Game, kind: str):
    return [c for c in game.pending_choices if c.kind == kind]


def put_in_tavern(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def run_soc(game: Game, a: Hero, b: Hero) -> None:
    """执行真实 SoC 阶段（CombatScheduler._start_of_combat_phase）。"""
    game.in_combat = True
    game._active_combat = (a, b)
    try:
        CombatScheduler(game, a, b)._start_of_combat_phase()
    finally:
        game._active_combat = None


class TestRegistryState(unittest.TestCase):
    # 跨批次维护约定: 后续批次实现了本批 DEFERRED 的技能时，把 id 从
    # DEFERRED_IDS 移到 OK_IDS（该卡不再处于二态中的 DEFERRED 态）。
    OK_IDS = (
        "TB_BaconShop_HP_057", "BG22_HERO_000p_Alt",
        "BG30_HERO_304p", "BG32_HERO_002p", "TB_BaconShop_HP_102",
    )
    DEFERRED_IDS = (
        "BG20_HERO_202p", "BG20_HERO_242p", "BG20_HERO_283p",
        "BG21_HERO_000p", "BG22_HERO_000p",
        "BG24_HERO_100p",   # 任务载荷 0/17 DEFERRED → 效果空转（对抗审计）
        "BG25_HERO_100p", "BG31_HERO_801p", "BG31_HERO_811p",
        "BG33_HERO_001p_ALT", "BG34_HERO_000p", "BG34_HERO_004p",
        "BG35_HERO_001p", "TB_BaconShop_HP_020", "TB_BaconShop_HP_101",
        "TB_BaconShop_HP_106",
    )
    # 曾在本批 DEFERRED、后由 batch_hero_remaining2 实现的技能
    LATER_IMPLEMENTED = ("BG22_HERO_004p",)   # Varden（实体级 FROZEN 就绪后）

    def test_ok_registered(self):
        for cid in self.OK_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_deferred_not_registered(self):
        for cid in self.DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_later_implemented_are_registered(self):
        """曾被本批 DEFERRED、后由后续批次实现的技能必须真的在册
        （跨批次台账不漂移）。"""
        for cid in self.LATER_IMPLEMENTED:
            self.assertIn(cid, REGISTRY, cid)


class TestAdventureFinley(unittest.TestCase):
    """TB_BaconShop_HP_057 — 开局 3 选 1 Discover 一个英雄技能并替换。"""

    POWER = "TB_BaconShop_HP_057"

    def test_start_of_game_offers_three_draftable_powers(self):
        game = make_game(self.POWER, seed=3)
        a, b = game.heroes
        offers = choices_of(game, "discover_hero_power")
        self.assertEqual(len(offers), 1)
        choice = offers[0]
        self.assertIs(choice.owner, a)
        # 3 个互异候选，全在可选中英雄技能池内，且不含本技能自身
        pool = _draftable_hero_power_ids(game)
        self.assertEqual(len(choice.options), 3)
        self.assertEqual(len(set(choice.options)), 3)
        self.assertNotIn(self.POWER, choice.options)
        for pid in choice.options:
            self.assertIn(pid, pool)
            self.assertEqual(game.db.get(pid).card_type, CardType.HERO_POWER)
        # owner 隔离: 对手无该 PendingChoice
        self.assertEqual([c for c in offers if c.owner is b], [])

    def test_choose_patchwerk_replaces_and_wires_on_bind(self):
        # seed 54: 候选含 Patchwerk（TB_BaconShop_HP_035）——D2 过滤候选池
        # 后重新标定（原 seed 3 已不含它）
        game = make_game(self.POWER, seed=54)
        a, b = game.heroes
        choice = choices_of(game, "discover_hero_power")[0]
        # 候选池已过滤为已注册技能（D2）→ 按 id 定位 Patchwerk 而非
        # 依赖固定 seed 的选项位置
        self.assertIn("TB_BaconShop_HP_035", choice.options)
        idx = choice.options.index("TB_BaconShop_HP_035")
        self.assertEqual(a.health, C.HERO_BASE_HEALTH)
        choice.choose(idx)
        # 替换生效（hero_power_def 读 _active_power_id）
        self.assertEqual(game.hero_power_def(a).id, "TB_BaconShop_HP_035")
        # 被选技能 on_bind 已显式接线: Patchwerk "30 extra Health"
        self.assertEqual(a.health, C.HERO_BASE_HEALTH + 30)
        # 对手未被替换（TEST_H_1 无绑定技能）
        self.assertIsNone(game.hero_power_def(b))

    def test_pool_excludes_token_and_unscripted_powers(self):
        """候选池 = 已绑定英雄的**已实现**英雄技能。

        2026-09-02 对抗审查 D2: 未注册脚本的技能选中即"槽位就绪但技能
        永久不可用"（实测 57% 局至少给出 1 个空转选项）→ 池过滤为
        REGISTRY 在册者（原断言"恰好 116"编码了未过滤的旧池）。
        """
        game = make_game(self.POWER, seed=3)
        pool = _draftable_hero_power_ids(game)
        self.assertGreater(len(pool), 90)
        for pid in pool:
            self.assertIsNotNone(REGISTRY.get(pid), pid)
        for token in ("TB_BaconShop_HP_087t", "TB_BaconShop_HP_036t"):
            self.assertNotIn(token, pool)


class TestLockAndLoadTavish(unittest.TestCase):
    """BG22_HERO_000p_Alt — 移除酒馆随从; 下场战斗有空位时召唤并射击。"""

    POWER = "BG22_HERO_000p_Alt"

    def _use_on(self, game: Game, hero: Hero, target: Minion) -> None:
        self.assertTrue(game.use_hero_power(hero))
        choice = choices_of(game, "hero_power_target")[-1]
        self.assertIs(choice.owner, hero)
        choice.choose(choice.options.index(target))

    def test_remove_tavern_minion_restores_pool(self):
        game = make_game(self.POWER, seed=11)
        a, b = game.heroes
        a.gold = 10
        tm = put_in_tavern(game, a, "BG33_886")
        avail_before = game.minion_pool.available("BG33_886")
        self.assertTrue(game.use_hero_power(a))
        choice = choices_of(game, "hero_power_target")[0]
        self.assertIn(tm, choice.options)
        choice.choose(choice.options.index(tm))
        # 离开酒馆、zone=REMOVED、存储槽位设置、池副本回补 1 份
        self.assertNotIn(tm, a.tavern)
        self.assertEqual(tm.zone, Zone.REMOVED)
        self.assertIs(getattr(a, "_lock_and_load_stored", None), tm)
        self.assertEqual(game.minion_pool.available("BG33_886"),
                         avail_before + 1)
        self.assertEqual(a.gold, 10)   # cost=0

    def test_start_of_combat_summons_and_fires_at_enemy(self):
        game = make_game(self.POWER, seed=11)
        a, b = game.heroes
        a.gold = 10
        tm = put_in_tavern(game, a, "BG23_000")     # Mini-Myrmidon 1/4
        tm.add_buff(E.Buff(atk=10))                 # 11/4
        self._use_on(game, a, tm)
        enemy = game.create_minion("BG23_004", controller=b)   # 2/3
        game.summon(b, enemy)
        run_soc(game, a, b)
        # 存储槽清空; 实体已召唤入己方棋盘
        self.assertIsNone(getattr(a, "_lock_and_load_stored", None))
        self.assertIn(tm, a.board)
        self.assertEqual(tm.zone, Zone.PLAY)
        # 目标为敌方唯一存活随从 → 吃 11 点（2/3 死亡）
        self.assertTrue(enemy.dead)
        self.assertEqual(enemy.health, 0)
        # 反伤: 存储随从 4 血 - 2 = 2
        self.assertEqual(tm.health, 2)

    def test_no_space_defers_to_next_combat(self):
        game = make_game(self.POWER, seed=12)
        a, b = game.heroes
        a.gold = 10
        tm = put_in_tavern(game, a, "BG23_000")
        self._use_on(game, a, tm)
        for _ in range(C.BOARD_SIZE):
            game.summon(a, game.create_minion("BG23_004", controller=a))
        enemy = game.create_minion("BG23_004", controller=b)
        game.summon(b, enemy)
        run_soc(game, a, b)
        # 无空位 → 槽保留、未召唤、敌方无伤
        self.assertIs(getattr(a, "_lock_and_load_stored", None), tm)
        self.assertNotIn(tm, a.board)
        self.assertEqual(len(a.board), C.BOARD_SIZE)
        self.assertFalse(enemy.dead)

    def test_opponent_soc_does_not_fire_tavish_store(self):
        game = make_game(self.POWER, seed=14)
        a, b = game.heroes
        a.gold = 10
        tm = put_in_tavern(game, a, "BG23_000")
        self._use_on(game, a, tm)
        enemy = game.create_minion("BG23_004", controller=b)
        game.summon(b, enemy)
        game.events.fire(game, "start_of_combat", hero=b)
        self.assertIs(getattr(a, "_lock_and_load_stored", None), tm)
        self.assertEqual(a.board, [])


class TestWhodunitDenathriusDeferred(unittest.TestCase):
    """BG24_HERO_100p — DEFERRED（2026-09-01 对抗审计；2026-09-18 更新）。

    机制（开局二选一任务 + complete_quest 发奖）本身正确，但本卡**未接线**。

    2026-09-18 第四十九轮订正: 旧 DEFERRED 理由「任务卡 0/17 注册 → 选到的
    任务永不推进/完成」**已随任务族落地失效**——`BG24_Quest_*` 现全部注册
    （`batch_quests`，目标值权威 = 各卡 wiki 页 baseline requirement，见
    `docs/agents/QUEST_DEFERRED_SPEC.md`）。本卡当前的真实缺口 = **接线**
    （`on_bind` 选两任务 + 第 4 回合 offer 抑制），不是权威数据缺口。
    另: 现有 `WhodunitScript` 的候选池写死 `BG24_Quest_*` 前缀，会把已
    DEFERRED 的 `BG24_Quest_328` 与公告 token `BG24_Quest_Bob` 一并发出
    → 接线时必须改用 `game.quest_offer_pool()`。详见
    `batch_hero_remaining.py` 的类 docstring（本次未注册，属独立卡片工作项）。
    """

    POWER = "BG24_HERO_100p"

    def test_unregistered(self):
        self.assertNotIn(self.POWER, REGISTRY)

    def test_quest_payload_now_progresses(self):
        """2026-09-18 订正: 任务载荷**已可推进/完成**（旧前提失效的证明）。

        旧测试 `test_dependency_still_holds` 断言「BG24 任务卡 REGISTRY 为
        空」，已过期（见 `test_batch_quests.py::TestRegistryAndAuthority`）。
        本测试锁住**新**前提: 抽一个已注册任务 → 真实事件能推进并完成，
        因此本英雄技能的机制（选择 + 发奖）不再被任务侧数据阻塞。
        """
        from hsrl2.tests.test_batch_quests import attach, make_game
        quests = [k for k in REGISTRY if k.startswith("BG24_Quest_")]
        # 17 = 15 任务卡 + `BG24_Quest_328`（DEFERRED）+ `BG24_Quest_Bob`
        # （公告 token）→ 15 张注册
        self.assertEqual(len(quests), 15)
        self.assertNotIn("BG24_Quest_328", REGISTRY)
        self.assertNotIn("BG24_Quest_Bob", REGISTRY)
        g = make_game()
        a = g.heroes[0]
        attach(g, a, "BG24_Quest_126")
        a.gold = 50
        g.spend_gold(a, 27)
        self.assertTrue(a._quest_completed)
        self.assertEqual(len(a.quest_rewards), 1)

    def test_quest_base_progress_is_a_real_data_field(self):
        """数据权威核实（RULES §11.6）: 任务**基础值**确实在 CardDefs 里
        （QUEST_PROGRESS_TOTAL，17/17 张）——DEFERRED 的理由是奖励侧
        基础值/修正表缺失，不是"任务数值完全没有数据"。本测试锁住该
        事实，防止过时注记回流。"""
        import re
        from pathlib import Path as _P
        xml = (_P(__file__).resolve().parent.parent.parent
               / "hsdata" / "CardDefs.xml")
        text = xml.read_text(encoding="utf-8")
        ents = re.findall(
            r'<Entity CardID="(BG24_Quest_[^"]+)"[^>]*>(.*?)</Entity>',
            text, re.S)
        self.assertEqual(len(ents), 17)
        with_total = 0
        for cid, body in ents:
            m = re.search(r'name="QUEST_PROGRESS_TOTAL" type="Int" '
                          r'value="(\d+)"', body)
            if m:
                with_total += 1
                self.assertGreater(int(m.group(1)), 0, cid)
        self.assertEqual(with_total, 17)     # 任务基础值 17/17 可得
        # 奖励侧基础值不可得: 66 张奖励里只有极少数带该 tag
        rew = re.findall(
            r'<Entity CardID="(BG24_Reward_[^"]+)"[^>]*>(.*?)</Entity>',
            text, re.S)
        rew_with = sum(1 for _, b in rew
                       if 'name="QUEST_PROGRESS_TOTAL"' in b)
        self.assertLessEqual(rew_with, 3)    # 不足以构成奖励难度数据源


class TestFantasticTreasureMarin(unittest.TestCase):
    """BG30_HERO_304p — 第 num(0)+1 回合提供 Lesser 饰品商店。"""

    POWER = "BG30_HERO_304p"

    def test_lesser_trinket_on_configured_turn(self):
        game = make_game(self.POWER, seed=5)
        a, b = game.heroes
        trigger = game.db.get(self.POWER).num(0) + 1
        self.assertEqual(trigger, 5)
        game.pending_choices.clear()
        for turn in range(2, trigger + 1):
            game.turn = turn
            game._begin_recruit_for(a)
            game._begin_recruit_for(b)
        offers = choices_of(game, "trinket_offer")
        self.assertEqual([c.owner for c in offers], [a])
        choice = offers[0]
        self.assertEqual(len(choice.options), C.TRINKET_CHOICES + 1)
        self.assertIsNone(choice.options[-1])          # 放弃哨兵
        for d in choice.options[:-1]:
            self.assertEqual(d.card_type, CardType.BACON_TRINKET)
            self.assertEqual(d.spell_school, 11)   # "Lesser Trinket"
        self.assertIn((a, "lesser"), game._trinket_offered)
        # 真实购买路径: 选一张付得起 → 入 hero.trinkets
        a.gold = C.GOLD_HOLD_CAP
        cheap = min(range(len(choice.options) - 1),
                    key=lambda i: choice.options[i].cost or 0)
        choice.choose(cheap)
        self.assertEqual([t.card_id for t in a.trinkets],
                         [choice.options[cheap].id])

    def test_standard_t6_lesser_not_duplicated(self):
        game = make_game(self.POWER, seed=5)
        a, b = game.heroes
        trigger = game.db.get(self.POWER).num(0) + 1
        for turn in range(2, trigger + 1):
            game.turn = turn
            game._begin_recruit_for(a)
        game.pending_choices.clear()
        game.turn = 6
        game._begin_recruit_for(a)
        game._begin_recruit_for(b)
        offers = choices_of(game, "trinket_offer")
        # Marin（T5 已 lesser）不再发; 对手照常 T6 lesser
        self.assertEqual([c.owner for c in offers], [b])


class TestGrowingCollectionButtons(unittest.TestCase):
    """BG32_HERO_002p — 第 num(0)+1 回合提供 Greater 饰品商店。"""

    POWER = "BG32_HERO_002p"

    def test_greater_trinket_on_configured_turn(self):
        game = make_game(self.POWER, seed=6)
        a, b = game.heroes
        trigger = game.db.get(self.POWER).num(0) + 1
        self.assertEqual(trigger, 8)
        for turn in range(2, trigger):
            game.turn = turn
            game._begin_recruit_for(a)
            game._begin_recruit_for(b)
        game.pending_choices.clear()
        game.turn = trigger
        game._begin_recruit_for(a)
        game._begin_recruit_for(b)
        offers = choices_of(game, "trinket_offer")
        self.assertEqual([c.owner for c in offers], [a])
        self.assertEqual(len(offers[0].options), C.TRINKET_CHOICES + 1)
        for d in offers[0].options[:-1]:
            self.assertEqual(d.spell_school, 12)   # "Greater Trinket"
        self.assertIn((a, "greater"), game._trinket_offered)
        self.assertIn((b, "lesser"), game._trinket_offered)   # 对手 T6
        self.assertNotIn((b, "greater"), game._trinket_offered)

    def test_standard_t9_greater_not_duplicated(self):
        game = make_game(self.POWER, seed=6)
        a, b = game.heroes
        trigger = game.db.get(self.POWER).num(0) + 1
        for turn in range(2, trigger + 1):
            game.turn = turn
            game._begin_recruit_for(a)
        game.pending_choices.clear()
        game.turn = 9
        game._begin_recruit_for(a)
        game._begin_recruit_for(b)
        offers = choices_of(game, "trinket_offer")
        self.assertEqual([c.owner for c in offers], [b])


class TestThreeWishesZephrys(unittest.TestCase):
    """TB_BaconShop_HP_102 — 两张同名 → 池中找第三张（每局 num(0) 次）。"""

    POWER = "TB_BaconShop_HP_102"

    def _wish_minions(self, game: Game, n: int = 3):
        out = []
        for d in game.db.pool_minions():
            if game.minion_pool.available(d.id) > 0 \
                    and game.db.golden_version(d) is not None:
                out.append(d.id)
            if len(out) >= n:
                break
        return out

    def _give_pair(self, game: Game, hero: Hero, card_id: str) -> None:
        for _ in range(2):
            m = game.create_minion(card_id, controller=hero)
            m.zone = Zone.HAND
            hero.hand.append(m)

    def test_finds_third_copy_and_makes_golden(self):
        game = make_game(self.POWER, seed=13)
        a, b = game.heroes
        wishes = game.db.get(self.POWER).num(0)
        self.assertEqual(a._three_wishes_left, wishes)
        self.assertEqual(wishes, 3)
        cid = self._wish_minions(game, 1)[0]
        self._give_pair(game, a, cid)
        av_before = game.minion_pool.available(cid)
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))
        # 第三份从池中获取（占池 1 份）→ 计数 -1 → 扣 3 金
        self.assertEqual(game.minion_pool.available(cid), av_before - 1)
        self.assertEqual(a._three_wishes_left, wishes - 1)
        self.assertEqual(a.gold, 10 - game.db.get(self.POWER).cost)
        # 第三份入手即三连 → 手牌为金色本体，普通副本全部消失
        golden_id = game.db.golden_version(game.db.get(cid)).id
        self.assertEqual([m.card_id for m in a.hand], [golden_id])
        self.assertTrue(a.hand[0].is_golden)
        # 对手无变化
        self.assertEqual(b.hand, [])

    def test_no_pair_unavailable_and_no_gold_spent(self):
        game = make_game(self.POWER, seed=13)
        a, b = game.heroes
        cid = self._wish_minions(game, 1)[0]
        single = game.create_minion(cid, controller=a)
        single.zone = Zone.HAND
        a.hand.append(single)
        a.gold = 10
        avail_before = game.minion_pool.available(cid)
        self.assertFalse(game.use_hero_power(a))     # 仅 1 份 → 不可用
        self.assertEqual(a.gold, 10)
        self.assertEqual(game.minion_pool.available(cid), avail_before)

    def test_three_uses_then_unavailable(self):
        game = make_game(self.POWER, seed=13)
        a, b = game.heroes
        wishes = game.db.get(self.POWER).num(0)
        cids = self._wish_minions(game, wishes)
        self.assertEqual(len(cids), wishes)
        cost = game.db.get(self.POWER).cost
        for i, cid in enumerate(cids):
            self._give_pair(game, a, cid)
            if i:
                # 引擎默认每回合 1 次 → 真实回合推进清除使用计数
                game.turn += 1
                game._begin_recruit_for(a)
            a.gold = 10
            self.assertTrue(game.use_hero_power(a))
            self.assertEqual(a.gold, 10 - cost)
            self.assertEqual(a._three_wishes_left, wishes - 1 - i)
        self.assertEqual(a._three_wishes_left, 0)
        # 第 4 次: 计数归零 → 拒绝（即使仍有配对也不可用、不扣金）
        game.turn += 1
        game._begin_recruit_for(a)
        self._give_pair(game, a, cids[0])
        a.gold = 10
        self.assertFalse(game.use_hero_power(a))
        self.assertEqual(a.gold, 10)


if __name__ == "__main__":
    unittest.main()
