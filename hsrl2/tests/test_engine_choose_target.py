"""引擎机制 P0 回归：饰品 offer 注册闸 / Choose One×needs_target 两阶段 /
法术实体 CHOOSE_BOTH / 旧 Choose One 脚本双效。

对应 `docs/AUDIT_ENGINE_MECHANICS.md`：
  - G-R1  饰品商店 offer 池按 `REGISTRY` 过滤（41/357 无脚本不得提供）
  - G-C1  `choose_options` × `needs_target` 两阶段状态机（抉择 → 目标 → 结算）
  - G-C2  旧 Choose One 脚本 `choose="both"` 不再静默零效果
  - G-C3  法术实体自带 `CHOOSE_BOTH` tag 被引擎读取

说明：旧脚本（BG27_084 Sprightly Scarab / BG30_123 Fearless Foodie）的
`needs_target`/`both` 迁移由 task-3（card-script-builder）在
`hsrl2/scripts/batches/batch_misc.py` 落地；本文件的实卡回归用
`skipUnless(...needs_target)` 占位，脚本落地后自动转为执行，引擎合成脚本
测试不依赖脚本迁移。验收: `python -m pytest hsrl2/tests -q` 全绿。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str) -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, n: int = 2) -> Game:
    heroes = [make_hero(chr(ord("A") + i)) for i in range(n)]
    import hsrl2.scripts  # noqa: F401  注册脚本
    return Game(heroes, get_db(), seed=seed)


def put_in_hand(game, hero, card_id: str, *, golden: bool = False):
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def summon(game, hero, card_id: str):
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def take_choice(game, index: int = 0):
    """按契约：先 pop 再 choose（引擎 choose 不出队）。"""
    choice = game.pending_choices.pop(0)
    choice.choose(index)
    return choice


def pick_pool_minion(*, race: Race = None, not_race=(), golden_ready=False):
    db = get_db()
    for d in db.pool_minions():
        if d.is_golden_def:
            continue
        if race is not None and d.race != race:
            continue
        if d.race in not_race:
            continue
        if golden_ready and db.golden_version(d) is None:
            continue
        return d
    raise AssertionError("no matching pool minion")


def _scarab_supports_combo() -> bool:
    """旧脚本迁移状态探测（task-3 落地 needs_target 后启用实卡组合测试）。"""
    script = REGISTRY.get("BG27_084")
    return bool(script is not None and getattr(script, "needs_target", False))


# ══════════════════ G-R1: 饰品 offer 注册闸 ══════════════════


class TestTrinketOfferRegistryGate(unittest.TestCase):
    def _narrow_offer_pool(self, game, defs):
        """收窄本局商店候选池（实例影子方法；Cleanup 恢复，避免污染
        共享 CardDB 单例——本文件其余用例依赖真实候选池）。"""
        game.db.trinket_offer_pool = lambda: list(defs)
        self.addCleanup(
            lambda: game.db.__dict__.pop("trinket_offer_pool", None))

    def test_real_offer_options_all_have_scripts(self):
        """真实商店候选（4+None）全部有 REGISTRY 脚本。"""
        game = make_game(seed=11)
        hero = game.heroes[0]
        hero.gold = 10
        game._offer_trinkets(hero, "lesser")
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices[0]
        self.assertEqual(choice.kind, "trinket_offer")
        self.assertEqual(len(choice.options), 5)          # 4 选 1 + 放弃
        self.assertIsNone(choice.options[-1])
        for d in choice.options[:-1]:
            self.assertIsNotNone(
                REGISTRY.get(d.id), f"无脚本饰品被提供: {d.id}")

    def test_unscripted_trinket_never_offered(self):
        """收窄候选池为「1 无脚本 + 1 有脚本」：无脚本项不得出现。"""
        db = get_db()
        unscripted = next(
            d for d in db.trinket_offer_pool() if REGISTRY.get(d.id) is None)
        school = unscripted.spell_school
        scripted = next(
            d for d in db.trinket_offer_pool()
            if REGISTRY.get(d.id) is not None and d.spell_school == school)

        game = make_game(seed=12)
        hero = game.heroes[0]
        # 本局候选池收窄（实例影子方法，Cleanup 恢复共享 CardDB）
        self._narrow_offer_pool(game, [unscripted, scripted])
        hero.gold = 10
        kind = "lesser" if school == 11 else "greater"
        game._offer_trinkets(hero, kind)

        choice = game.pending_choices[0]
        offered = [getattr(d, "id", None)
                   for d in choice.options if d is not None]
        self.assertNotIn(unscripted.id, offered)
        self.assertIn(scripted.id, offered)
        self.assertTrue(all(REGISTRY.get(cid) is not None for cid in offered))

    def test_empty_pool_after_gate_is_harmless(self):
        """只剩无脚本候选 → 不产生选择窗（不 panic、不扣金）。"""
        db = get_db()
        unscripted = next(
            d for d in db.trinket_offer_pool() if REGISTRY.get(d.id) is None)
        game = make_game(seed=13)
        hero = game.heroes[0]
        self._narrow_offer_pool(game, [unscripted])
        hero.gold = 10
        kind = "lesser" if unscripted.spell_school == 11 else "greater"
        before = len(game.pending_choices)
        game._offer_trinkets(hero, kind)
        self.assertEqual(len(game.pending_choices), before)
        self.assertEqual(hero.gold, 10)


# ══════════════════ G-C1: 引擎两阶段状态机（合成脚本） ══════════════════


class _ComboMinionScript:
    """合成随从脚本: choose_options + needs_target。"""

    choose_options = [("a", "A"), ("b", "B")]
    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        return [m for m in source.controller.board if not m.dead]

    @staticmethod
    def battlecry(source, game, ctx):
        source.seen.append(dict(ctx or {}))
        return None


class _ChooseOnlyMinionScript:
    choose_options = [("a", "A"), ("b", "B")]

    @staticmethod
    def battlecry(source, game, ctx):
        source.seen.append(dict(ctx or {}))
        return None


class _NoCandidateComboScript(_ComboMinionScript):
    @staticmethod
    def target_candidates(source, game):
        return []


class TestChooseOneTargetEngine(unittest.TestCase):
    def _combo_minion(self, game, hero, script=_ComboMinionScript,
                      *, golden=False):
        d = pick_pool_minion(golden_ready=golden)
        m = put_in_hand(game, hero, d.id, golden=golden)
        m.scripts = script
        m.seen = []
        return m

    def test_stage_order_choose_then_target(self):
        game = make_game(seed=21)
        hero = game.heroes[0]
        target = summon(game, hero, pick_pool_minion().id)
        m = self._combo_minion(game, hero)

        self.assertTrue(game.play_minion(hero, m))
        self.assertEqual(len(game.pending_choices), 1)
        self.assertEqual(game.pending_choices[0].kind, "choose_one")

        take_choice(game, 1)                               # 选 "b"
        self.assertEqual(len(game.pending_choices), 1)
        target_choice = game.pending_choices[0]
        self.assertEqual(target_choice.kind, "battlecry_target")
        self.assertIn(target, target_choice.options)
        take_choice(game, target_choice.options.index(target))

        self.assertFalse(game.pending_choices)
        self.assertEqual(len(m.seen), 1)
        self.assertEqual(m.seen[0].get("choose"), "b")
        self.assertIs(m.seen[0].get("target"), target)

    def test_explicit_target_skips_target_stage(self):
        game = make_game(seed=22)
        hero = game.heroes[0]
        target = summon(game, hero, pick_pool_minion().id)
        m = self._combo_minion(game, hero)

        self.assertTrue(game.play_minion(hero, m, target=target))
        self.assertEqual(game.pending_choices[0].kind, "choose_one")
        take_choice(game, 0)
        self.assertFalse(game.pending_choices)
        self.assertEqual(len(m.seen), 1)
        self.assertIs(m.seen[0].get("target"), target)

    def test_invalid_explicit_target_fizzles_battlecry(self):
        game = make_game(seed=23)
        hero = game.heroes[0]
        # 目标不在候选域（对面英雄的随从）
        enemy = game.heroes[1]
        foreign = summon(game, enemy, pick_pool_minion().id)
        m = self._combo_minion(game, hero)

        self.assertTrue(game.play_minion(hero, m, target=foreign))
        take_choice(game, 0)
        self.assertFalse(game.pending_choices)
        # 随从已入场、战吼落空（无目标窗、ctx 不含 target）
        self.assertIn(m, hero.board)
        self.assertEqual(len(m.seen), 1)
        self.assertNotIn("target", m.seen[0])

    def test_no_candidates_fizzles_without_target_window(self):
        game = make_game(seed=24)
        hero = game.heroes[0]
        m = self._combo_minion(game, hero, _NoCandidateComboScript)
        self.assertTrue(game.play_minion(hero, m))
        take_choice(game, 0)
        self.assertFalse(game.pending_choices)
        self.assertIn(m, hero.board)
        self.assertEqual(len(m.seen), 1)
        self.assertNotIn("target", m.seen[0])

    def test_golden_single_target_for_two_triggers(self):
        game = make_game(seed=25)
        hero = game.heroes[0]
        target = summon(game, hero, pick_pool_minion().id)
        m = self._combo_minion(game, hero, golden=True)
        self.assertTrue(m.is_golden)

        self.assertTrue(game.play_minion(hero, m))
        self.assertEqual(game.pending_choices[0].kind, "choose_one")
        take_choice(game, 0)
        self.assertEqual(game.pending_choices[0].kind, "battlecry_target")
        take_choice(game, 0)

        self.assertFalse(game.pending_choices)
        self.assertEqual(len(m.seen), 2)                   # 金色触发 2 次
        for ctx in m.seen:
            self.assertIs(ctx.get("target"), target)        # 同一目标

    def test_choose_both_skips_choose_stage(self):
        game = make_game(seed=26)
        hero = game.heroes[0]
        hero.set(GameTag.CHOOSE_BOTH, True)
        m = self._combo_minion(game, hero, _ChooseOnlyMinionScript)
        self.assertTrue(game.play_minion(hero, m))
        self.assertFalse(game.pending_choices)
        self.assertEqual(len(m.seen), 1)
        self.assertEqual(m.seen[0].get("choose"), "both")

    def test_choose_both_still_requires_target_stage(self):
        game = make_game(seed=27)
        hero = game.heroes[0]
        hero.set(GameTag.CHOOSE_BOTH, True)
        target = summon(game, hero, pick_pool_minion().id)
        m = self._combo_minion(game, hero)
        self.assertTrue(game.play_minion(hero, m))
        self.assertEqual(len(game.pending_choices), 1)
        self.assertEqual(game.pending_choices[0].kind, "battlecry_target")
        take_choice(game, 0)
        self.assertEqual(m.seen[0].get("choose"), "both")
        self.assertIs(m.seen[0].get("target"), target)


# ══════════════════ 法术路径（合成脚本） ══════════════════


class _ComboSpellScript:
    """合成法术脚本: choose_options + needs_target（真实卡暂无此组合）。"""

    choose_options = [("a", "A"), ("b", "B")]
    needs_target = True

    @staticmethod
    def target_candidates(spell, game):
        return [m for m in spell.controller.board if not m.dead]

    @staticmethod
    def on_play(spell, game, ctx):
        spell.seen_ctx = dict(ctx or {})
        return None


class _ChooseOnlySpellScript:
    choose_options = [("a", "A"), ("b", "B")]

    @staticmethod
    def on_play(spell, game, ctx):
        spell.seen_ctx = dict(ctx or {})
        return None


class TestSpellChooseOneCombo(unittest.TestCase):
    def _spell(self, game, hero, script):
        db = get_db()
        d = next(x for x in db.pool_spells() if not x.is_golden_def)
        spell = game.create_spell(d.id, controller=hero)
        spell.scripts = script
        hero.hand.append(spell)
        spell.zone = Zone.HAND
        return spell

    def test_choose_then_target_two_phase(self):
        game = make_game(seed=31)
        hero = game.heroes[0]
        target = summon(game, hero, pick_pool_minion().id)
        spell = self._spell(game, hero, _ComboSpellScript)

        self.assertTrue(game.play_spell(hero, spell))
        self.assertEqual(game.pending_choices[0].kind, "choose_one")
        take_choice(game, 1)                               # 选 "b"
        self.assertEqual(game.pending_choices[0].kind, "spell_target")
        take_choice(game, game.pending_choices[0].options.index(target))
        self.assertFalse(game.pending_choices)
        self.assertEqual(spell.seen_ctx.get("choose"), "b")
        self.assertIs(spell.seen_ctx.get("target"), target)

    def test_entity_choose_both_tag(self):
        """G-C3: 法术**实体**自带 CHOOSE_BOTH → 跳过抉择、直接双效。"""
        game = make_game(seed=32)
        hero = game.heroes[0]
        spell = self._spell(game, hero, _ChooseOnlySpellScript)
        spell.set(GameTag.CHOOSE_BOTH, True)

        self.assertTrue(game.play_spell(hero, spell))
        self.assertFalse(game.pending_choices)
        self.assertEqual(spell.seen_ctx.get("choose"), "both")

    def test_entity_choose_both_with_target(self):
        """实体 CHOOSE_BOTH + needs_target：跳过抉择但仍挂目标窗。"""
        game = make_game(seed=33)
        hero = game.heroes[0]
        target = summon(game, hero, pick_pool_minion().id)
        spell = self._spell(game, hero, _ComboSpellScript)
        spell.set(GameTag.CHOOSE_BOTH, True)

        self.assertTrue(game.play_spell(hero, spell))
        self.assertEqual(game.pending_choices[0].kind, "spell_target")
        take_choice(game, 0)
        self.assertFalse(game.pending_choices)
        self.assertEqual(spell.seen_ctx.get("choose"), "both")
        self.assertIs(spell.seen_ctx.get("target"), target)

    def test_board_aura_choose_both_still_works(self):
        """既有路径回归：棋盘随从 CHOOSE_BOTH 光环（Thorned Trailblazer）。"""
        game = make_game(seed=34)
        hero = game.heroes[0]
        aura = summon(game, hero, pick_pool_minion().id)
        aura.set(GameTag.CHOOSE_BOTH, True)
        spell = self._spell(game, hero, _ChooseOnlySpellScript)

        self.assertTrue(game.play_spell(hero, spell))
        self.assertFalse(game.pending_choices)
        self.assertEqual(spell.seen_ctx.get("choose"), "both")


# ══════════════════ 实卡回归（脚本迁移后自动启用） ══════════════════


class TestRealSprightlyScarabContract(unittest.TestCase):
    """BG27_084 Sprightly Scarab：选项/目标/显式目标在旧脚本下也成立；
    金色同目标与 CHOOSE_BOTH 双效在脚本迁移（needs_target）后启用。"""

    SCARAB = "BG27_084"

    def _setup(self, *, golden=False):
        game = make_game(seed=51)
        hero = game.heroes[0]
        beast = summon(game, hero, pick_pool_minion(race=Race.BEAST).id)
        other = summon(game, hero,
                       pick_pool_minion(not_race=(Race.BEAST, Race.ALL)).id)
        scarab = put_in_hand(game, hero, self.SCARAB, golden=golden)
        return game, hero, beast, other, scarab

    def test_stage_order_choose_then_target(self):
        game, hero, beast, other, scarab = self._setup()
        base = get_db().get(self.SCARAB)
        atk0, max_hp0 = beast.atk, beast.max_health
        self.assertTrue(game.play_minion(hero, scarab))
        self.assertEqual(game.pending_choices[0].kind, "choose_one")
        take_choice(game, game.pending_choices[0].options.index("reborn"))
        self.assertEqual(game.pending_choices[0].kind, "battlecry_target")
        target_choice = game.pending_choices[0]
        self.assertIn(beast, target_choice.options)
        self.assertNotIn(other, target_choice.options)
        take_choice(game, target_choice.options.index(beast))
        self.assertFalse(game.pending_choices)
        self.assertEqual(beast.atk, atk0 + base.num(0))
        self.assertEqual(beast.max_health, max_hp0 + base.num(1))
        self.assertTrue(beast.has(GameTag.REBORN))

    def test_explicit_target_skips_target_stage(self):
        game, hero, beast, _other, scarab = self._setup()
        base = get_db().get(self.SCARAB)
        atk0 = beast.atk
        self.assertTrue(game.play_minion(hero, scarab, target=beast))
        self.assertEqual(game.pending_choices[0].kind, "choose_one")
        take_choice(game, 0)                               # reborn
        self.assertFalse(game.pending_choices)
        self.assertEqual(beast.atk, atk0 + base.num(0))
        self.assertTrue(beast.has(GameTag.REBORN))

    @unittest.skipUnless(
        _scarab_supports_combo(),
        "BG27_084 needs_target 迁移由 task-3(card-script-builder) 落地后启用")
    def test_golden_uses_one_target_for_two_triggers(self):
        game, hero, beast, _other, scarab = self._setup(golden=True)
        base = get_db().get(self.SCARAB)
        atk0, max_hp0 = beast.atk, beast.max_health
        self.assertTrue(game.play_minion(hero, scarab))
        take_choice(game, game.pending_choices[0].options.index("reborn"))
        self.assertEqual(game.pending_choices[0].kind, "battlecry_target")
        take_choice(game, game.pending_choices[0].options.index(beast))
        self.assertFalse(game.pending_choices)
        # 金色: 目标只选一次，战吼触发 2 次（同目标）= 金色总额 2/2
        self.assertEqual(beast.atk, atk0 + 2 * base.num(0))
        self.assertEqual(beast.max_health, max_hp0 + 2 * base.num(1))
        self.assertTrue(beast.has(GameTag.REBORN))

    @unittest.skipUnless(
        _scarab_supports_combo(),
        "BG27_084 choose='both' 分支由 task-3(card-script-builder) 落地后启用")
    def test_both_applies_all_branches(self):
        game, hero, beast, _other, scarab = self._setup()
        hero.set(GameTag.CHOOSE_BOTH, True)
        base = get_db().get(self.SCARAB)
        atk0, max_hp0 = beast.atk, beast.max_health
        self.assertTrue(game.play_minion(hero, scarab))
        # both 跳过抉择阶段 → 直接目标阶段
        self.assertEqual(game.pending_choices[0].kind, "battlecry_target")
        take_choice(game, game.pending_choices[0].options.index(beast))
        self.assertFalse(game.pending_choices)
        self.assertEqual(beast.atk, atk0 + base.num(0) + base.num(2))
        self.assertEqual(beast.max_health, max_hp0 + base.num(1))
        self.assertTrue(beast.has(GameTag.REBORN))
        self.assertTrue(beast.has(GameTag.WINDFURY))


class TestRandomTrinketGrantRegistryGate(unittest.TestCase):
    """G-R1 补口（task-6）: ``grant_random_trinket`` 同样过 REGISTRY 闸。"""

    def _narrow(self, game, defs):
        game.db.trinket_offer_pool = lambda: list(defs)
        self.addCleanup(
            lambda: game.db.__dict__.pop("trinket_offer_pool", None))

    def test_unscripted_pick_replaced_by_registered(self):
        db = get_db()
        unscripted = next(
            d for d in db.trinket_offer_pool() if REGISTRY.get(d.id) is None)
        school = unscripted.spell_school
        scripted = next(
            d for d in db.trinket_offer_pool()
            if REGISTRY.get(d.id) is not None and d.spell_school == school)
        game = make_game(seed=61)
        hero = game.heroes[0]
        self._narrow(game, [unscripted, scripted])
        kind = "lesser" if school == 11 else "greater"

        entity = game.grant_random_trinket(hero, kind=kind)
        self.assertIsNotNone(entity)
        self.assertIsNotNone(REGISTRY.get(entity.card_id))
        self.assertEqual(entity.card_id, scripted.id)
        self.assertIn(scripted.id, hero.trinkets_granted)

    def test_only_unscripted_pool_whiffs(self):
        db = get_db()
        unscripted = next(
            d for d in db.trinket_offer_pool() if REGISTRY.get(d.id) is None)
        game = make_game(seed=62)
        hero = game.heroes[0]
        self._narrow(game, [unscripted])
        kind = "lesser" if unscripted.spell_school == 11 else "greater"

        self.assertIsNone(game.grant_random_trinket(hero, kind=kind))
        self.assertEqual(list(hero.trinkets), [])
        self.assertEqual(list(hero.trinkets_granted), [])

    def test_real_pool_grants_only_registered(self):
        game = make_game(seed=63)
        hero = game.heroes[0]
        granted = 0
        for _ in range(30):
            entity = game.grant_random_trinket(hero, kind="lesser")
            if entity is None:
                break
            self.assertIsNotNone(
                REGISTRY.get(entity.card_id),
                f"无脚本饰品被随机授予: {entity.card_id}")
            granted += 1
        self.assertGreater(granted, 0)

    def test_kind_filter_preserved(self):
        db = get_db()
        lesser = next(d for d in db.trinket_offer_pool()
                      if REGISTRY.get(d.id) is not None
                      and d.spell_school == 11)
        greater = next(d for d in db.trinket_offer_pool()
                       if REGISTRY.get(d.id) is not None
                       and d.spell_school == 12)
        game = make_game(seed=64)
        hero = game.heroes[0]
        self._narrow(game, [lesser, greater])

        entity = game.grant_random_trinket(hero, kind="lesser")
        self.assertIsNotNone(entity)
        self.assertEqual(db.get(entity.card_id).spell_school, 11)


if __name__ == "__main__":
    unittest.main()
