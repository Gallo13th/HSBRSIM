"""批次 remaining1 语义测试（作业单 2026-09-16，1 注册项）。

覆盖: `EBG_Spell_037` Unmasked Identity — "**Discover** a new Hero
Power."（T5 池法术）

驱动协议: 真实 `game.spell_pool.acquire` → `create_spell` → 入手 →
`game.play_spell`（与对局同一路径）; 选择经真实
`PendingChoice.choose`（kind="discover_hero_power"，Finley 同协议）;
数值/候选期望一律来自引擎权威（`_draftable_hero_power_ids` /
`CardDef`），不硬编码候选 id。

DEFERRED 台账守卫（结构性, `@engine-only`）: 本批 docstring 列出的
逐类别复核结果（3 张 Duos 池法术 / 5 张纯关键词池随从 / 15 英雄技能 /
30 饰品 / 37 异变 / 4 任务奖励 / 21 任务维持 DEFERRED）在
`TestRegistryState` 内抽样固定。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_hero_remaining import (
    _draftable_hero_power_ids,
)
from hsrl2.tags import CardType, GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

CARD = "EBG_Spell_037"
# 本批选中用于验证 on_bind 真实接线的技能: Patchwerk "All minions have
# double Health" 的 on_bind 直接改 HERO 生命（TEST_SOP §4: 期望从
# CardDef/引擎状态计算）
_PATCHWERK = "TB_BaconShop_HP_035"
# 施放前的"当前技能"（Millhouse——主动/被动均与 Patchwerk 不同族）
_CURRENT = "TB_BaconShop_HP_054"
# seed 54: 候选含 Patchwerk（rng.sample 按 seed 确定性; 注意本卡
# 会消耗一次共享 RNG 抽取，故其后同局抽取序列会前移）
_PATCHWERK_SEED = 54


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 7, current: str | None = None,
              heroes: int = 2) -> Game:
    hs = [Hero(f"TEST_H_{i}", chr(ord("A") + i)) for i in range(heroes)]
    game = Game(hs, get_db(), seed=seed)
    if current is not None:
        game.replace_hero_power(game.heroes[0], current)
    return game


def cast(game: Game, hero: Hero, card_id: str = CARD):
    """真实施放一张池法术（占池 → 入手 → play_spell）。"""
    assert game.spell_pool.acquire(card_id), "pool copy unavailable"
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    ok = game.play_spell(hero, s)
    assert ok, "play_spell rejected"
    return s


def discovers(game: Game):
    return [c for c in game.pending_choices
            if c.kind == "discover_hero_power"]


def current_power_id(game: Game, hero: Hero) -> str | None:
    d = game.hero_power_def(hero)
    return d.id if d is not None else None


class TestRegistryState(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 卡定义 / DEFERRED 台账 / Duos 范围。

    与脚本钩子无关（钩子 no-op 后仍通过属预期）。
    """

    def test_card_registered(self):
        self.assertIn(CARD, REGISTRY)
        from hsrl2.scripts.batches.batch_remaining1 import (
            UnmaskedIdentityScript,
        )
        self.assertIs(REGISTRY[CARD], UnmaskedIdentityScript)

    def test_card_definition_is_t5_pool_spell(self):
        d = get_db().get(CARD)
        self.assertIsNotNone(d)
        self.assertEqual(d.card_type, CardType.BACON_SPELL)
        self.assertTrue(d.is_pool_spell)
        self.assertEqual(d.tech_level, 5)
        # 无金色定义（batch_spells_final 已核；本批复核）
        self.assertIsNone(get_db().get(CARD + "_G"))
        # 无模板参数——脚本不得读 num()
        self.assertEqual([d.num(i) for i in range(5)], [None] * 5)

    def test_duos_pool_spells_stay_out_of_scope(self):
        """teammate/Pass 三张 = Duos 机制（SOP 范围外），维持未注册。"""
        for cid in ("BG31_242", "BG31_243", "BG31_244"):
            self.assertNotIn(cid, REGISTRY, cid)

    def test_pure_keyword_pool_minions_stay_unregistered(self):
        """纯关键词卡由数据通道生效，注册空脚本 = 第三态。"""
        for cid in ("BG25_001", "BGS_119", "BGS_131", "BG_BOT_911",
                    "BG_DEEP_015", "BG26_175"):
            self.assertNotIn(cid, REGISTRY, cid)

    def test_engine_blocked_hero_powers_stay_deferred(self):
        """无来源卡 Triple Reward 档位 / rebind / 子系统阻塞项维持未注册。"""
        for cid in ("BG20_HERO_242p", "BG33_HERO_001p_ALT",
                    "BG20_HERO_202p", "BG31_HERO_801p", "TB_BaconShop_HP_101"):
            self.assertNotIn(cid, REGISTRY, cid)

    def test_no_number_portraits_stay_deferred(self):
        """约束 1 点名: "also give Attack/Health" 无数字 → 维持 DEFERRED。

        2026-09-19 更新: 868 / 987 / 283 已由 batch_trinkets31 按 owner
        权威序解冻（wiki 页无 Notes → 卡面天然语言: "also give X" 增量 =
        同句既有量）并注册 → 移出本守卫; 仅 `BG35_MagicItem_921`
        Cowrie Necklace 仍 DEFERRED（阻塞为"Tavern spells that give
        stats"子集折扣读取点，与"无数字"无关）。
        """
        for cid in ("BG35_MagicItem_921",):
            self.assertNotIn(cid, REGISTRY, cid)


class TestUnmaskedIdentity(unittest.TestCase):
    """EBG_Spell_037 — Discover 一个"新"英雄技能并替换当前技能。"""

    def test_cast_offers_three_distinct_new_registered_powers(self):
        game = make_game(seed=7, current=_CURRENT)
        a, b = game.heroes
        cast(game, a)
        offers = discovers(game)
        self.assertEqual(len(offers), 1)
        choice = offers[0]
        self.assertIs(choice.owner, a)
        self.assertEqual(len(choice.options), 3)
        self.assertEqual(len(set(choice.options)), 3)
        # "new"——当前技能不在候选中
        self.assertNotIn(_CURRENT, choice.options)
        # 候选全部来自引擎候选池（英雄绑定 + 已注册），且为英雄技能
        pool = _draftable_hero_power_ids(game, exclude=(_CURRENT,))
        for pid in choice.options:
            self.assertIn(pid, pool)
            self.assertIn(pid, REGISTRY)
            self.assertEqual(get_db().get(pid).card_type,
                             CardType.HERO_POWER)
        # owner 隔离: 对手没有该选择
        self.assertEqual(discovers(game)[0].owner, a)
        self.assertEqual([c for c in game.pending_choices if c.owner is b],
                         [])

    def test_choose_replaces_power_and_fires_on_bind(self):
        game = make_game(seed=_PATCHWERK_SEED, current=_CURRENT)
        a, b = game.heroes
        self.assertEqual(current_power_id(game, a), _CURRENT)
        health_before = a.health
        base_health = a.get(GameTag.BASE_HEALTH)
        cast(game, a)
        choice = discovers(game)[0]
        self.assertIn(_PATCHWERK, choice.options)
        choice.choose(choice.options.index(_PATCHWERK))
        # 效果 1: 技能被替换
        self.assertEqual(current_power_id(game, a), _PATCHWERK)
        # 效果 2: 被选技能 on_bind 真的接线并生效（Patchwerk 生命翻倍）
        self.assertIn((id(a), _PATCHWERK), game._wired_powers)
        self.assertEqual(a.health, health_before * 2)
        self.assertEqual(base_health * 2, a.health)
        # 效果 3: 替换后的技能可被引擎识别（use_hero_power 走新技能定义）
        self.assertEqual(game.hero_power_ids(a)[0], _PATCHWERK)

    def test_second_cast_excludes_newly_held_power(self):
        game = make_game(seed=_PATCHWERK_SEED, current=_CURRENT)
        a = game.heroes[0]
        cast(game, a)
        first = game.pending_choices.pop(0)    # 队列化消费（非临时列表）
        self.assertEqual(first.kind, "discover_hero_power")
        first.choose(first.options.index(_PATCHWERK))
        game.spell_pool.release(CARD)          # 第二次施放占池（模拟再买）
        cast(game, a)
        second = [c for c in game.pending_choices
                  if c.kind == "discover_hero_power"].pop(0)
        self.assertNotIn(_PATCHWERK, second.options)   # 已持有 → 非 "new"

    def test_only_main_power_excluded(self):
        """只排除**当前主技能**; 第二技能槽不算"已持有"（与 Finley /
        Cosmic Reward 同口径——wiki 对第二槽无说明, 不得自创排除规则）。"""
        from hsrl2.scripts.batches.batch_hero_remaining import (
            _draftable_hero_power_ids)
        game = make_game(seed=7, current=_CURRENT)
        a = game.heroes[0]
        second = "BG32_HERO_002p"
        game.set_second_hero_power(a, second)
        self.assertEqual(a._second_power_id, second)
        pool = _draftable_hero_power_ids(game, exclude=(_CURRENT,))
        self.assertIn(second, pool)          # 第二槽技能仍在候选池
        cast(game, a)
        options = discovers(game)[0].options
        self.assertNotIn(_CURRENT, options)  # 主技能仍被排除
        self.assertEqual(len(options), 3)

    def test_illegal_resolve_is_noop(self):
        """resolve 一个不在本次选项内的技能 → 技能不变（陈旧选择防护）。"""
        game = make_game(seed=7, current=_CURRENT)
        a = game.heroes[0]
        cast(game, a)
        choice = discovers(game)[0]
        stale = next(pid for pid in _draftable_hero_power_ids(game)
                     if pid not in choice.options and pid != _CURRENT)
        choice.resolve_callback(stale)
        self.assertEqual(current_power_id(game, a), _CURRENT)
        self.assertNotIn((id(a), stale), game._wired_powers)

    def test_opponent_power_and_choices_untouched(self):
        """owner 隔离（wiki 35.4.0 bugfix 规格的一部分）。"""
        game = make_game(seed=7, current=_CURRENT)
        a, b = game.heroes
        b_before = current_power_id(game, b)
        cast(game, a)
        choice = discovers(game)[0]
        choice.choose(0)
        self.assertEqual(current_power_id(game, b), b_before)
        self.assertNotIn((id(b), choice.options[0]), game._wired_powers)
        self.assertEqual([c for c in game.pending_choices if c.owner is b],
                         [])

    def test_empty_candidate_pool_fizzles_without_choice(self):
        """候选池为空 → 落空（不建空 PendingChoice; 不改技能）。"""
        game = make_game(seed=7, current=_CURRENT)
        a = game.heroes[0]
        with mock.patch(
                "hsrl2.scripts.batches.batch_hero_remaining."
                "_draftable_hero_power_ids", return_value=[]):
            cast(game, a)
        self.assertEqual(discovers(game), [])
        self.assertEqual(current_power_id(game, a), _CURRENT)

    def test_pool_accounting_released_after_cast(self):
        """真实池记账: 施放后副本回池（Discover 类池法术统一语义）。"""
        game = make_game(seed=7, current=_CURRENT)
        a = game.heroes[0]
        avail = game.spell_pool.available(CARD)
        self.assertGreater(avail, 0)          # 可提供（T5 池法术）
        cast(game, a)
        self.assertEqual(game.spell_pool.available(CARD), avail)


if __name__ == "__main__":
    unittest.main()
