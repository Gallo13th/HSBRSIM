"""Spellcraft 系统测试（RULES §6.13）——生成器 + 首批 3 张 Naga 卡。

覆盖:
  1. generate_for_hero: 棋盘 SPELLCRAFT 随从 → 每随从一张法术
     （tag + spellcraft_source_uuid）; 无 Spellcraft 随从无生成
  2. 打出/召唤立即获得第一张（on_summon → grant_spellcraft_spell）
  3. end_recruit_phase 回合末丢弃 + Sunken Persistence 永久化豁免
     （game._permanent_spellcraft_uuids 协议）
  4. 法术效果: temporary buff / 临时关键词（风怒/圣盾）在下一招募
     阶段开始过期; 自带永久关键词不误删; target=None 落空
  5. 金色随从 → 金色法术（独立卡定义 BG*_Gt）

引擎缺口注（见批次报告）:
  - create_minion 未映射 SPELLCRAFT tag（_KEYWORD_TAG_MAP 无 spellcraft
    项）→ 随从脚本 on_summon 自举
  - entity.clear_temporary_buffs 无引擎调用点 → temporary buff 过期由
    脚本层 TURN_START once 监听器实现
数值断言一律 CardDef.num()（无模板参数的卡注明字面量来源）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.constants import HAND_SIZE
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.spellcraft import generate_for_hero, grant_spellcraft_spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42) -> Game:
    return Game([make_hero("A"), make_hero("B")], get_db(), seed=seed)


def summon(game: Game, card_id: str, hero: Hero, golden: bool = False,
           **kwargs) -> Minion:
    """create_minion（含脚本绑定 + golden→金色卡定义）→ summon（含
    on_summon: Spellcraft tag 自举 + 立即给法术）。"""
    m = game.create_minion(card_id, controller=hero, golden=golden, **kwargs)
    game.summon(hero, m)
    return m


def make_minion(name: str, atk: int, health: int, **kwargs) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kwargs)


def spell_in_hand(hero: Hero) -> list:
    return [c for c in hero.hand if c.has(GameTag.SPELLCRAFT)]


def add_spell_to_hand(game: Game, hero: Hero, card_id: str):
    """直接构造手牌中的 Spellcraft 法术（不走生成路径——隔离测试用）。

    引擎缺口注: create_spell 不绑定 REGISTRY（create_minion 才绑），
    生成路径 _make_spellcraft_spell 已补绑; 本 helper 镜像该行为。
    """
    from hsrl2.scripts import REGISTRY
    s = game.create_spell(card_id, controller=hero)
    s.scripts = REGISTRY.get(card_id)
    s.set(GameTag.SPELLCRAFT, True)
    hero.add_to_hand(s)
    return s


# ══════════════════ 1. generate_for_hero ══════════════════


class TestGenerateForHero(unittest.TestCase):

    def test_no_spellcraft_minion_no_generation(self):
        game = make_game()
        a = game.heroes[0]
        m = make_minion("Plain", 3, 3)
        m.controller = a
        game.summon(a, m)          # 无脚本 → 无 tag（引擎缺口: 无映射）
        generate_for_hero(a, game)
        self.assertEqual(len(a.hand), 0)

    def test_one_minion_one_spell_with_tag_and_source(self):
        game = make_game()
        a = game.heroes[0]
        m = summon(game, "BG23_000", a)   # on_summon 已给第一张
        first = spell_in_hand(a)
        self.assertEqual(len(first), 1)
        generate_for_hero(a, game)        # 回合开始: 再给一张
        spells = spell_in_hand(a)
        self.assertEqual(len(spells), 2)
        for s in spells:
            self.assertTrue(s.has(GameTag.SPELLCRAFT))
            self.assertEqual(s.spellcraft_source_uuid, m.uuid)
            self.assertEqual(s.zone, Zone.HAND)
            self.assertEqual(s.card_id, "BG23_000t")

    def test_two_minions_two_spells(self):
        game = make_game()
        a = game.heroes[0]
        summon(game, "BG23_000", a)
        summon(game, "BG23_008", a)
        # on_summon 立即获得: 2 张（每随从第一张）
        self.assertEqual(len(spell_in_hand(a)), 2)
        generate_for_hero(a, game)
        # 回合开始再各一张 → 4 张
        self.assertEqual(len(spell_in_hand(a)), 4)

    def test_spell_id_follows_carddef_spellcraft(self):
        """生成的法术 card_id = CardDef.spellcraft_id 解析结果（数值权威）。"""
        game = make_game()
        a = game.heroes[0]
        m = summon(game, "BG23_008", a)
        d = game.db.get("BG23_008")
        expect = game.db.by_dbf(d.spellcraft_id).id
        self.assertEqual(spell_in_hand(a)[0].card_id, expect)
        self.assertEqual(spell_in_hand(a)[0].spellcraft_source_uuid, m.uuid)


# ══════════════════ 2. 打出立即获得 ══════════════════


class TestImmediateGrantOnPlay(unittest.TestCase):

    def _play_from_hand(self, game, hero, card_id, golden=False):
        m = game.create_minion(card_id, controller=hero, golden=golden)
        hero.add_to_hand(m)
        self.assertTrue(game.play_minion(hero, m))
        return m

    def test_play_naga_grants_spell_immediately(self):
        game = make_game()
        a = game.heroes[0]
        self.assertEqual(len(a.hand), 0)
        m = self._play_from_hand(game, a, "BG23_000")
        # 打出路径: 随从入手→play_minion→summon→on_summon→立即给法术
        self.assertEqual(m.zone, Zone.PLAY)
        spells = spell_in_hand(a)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0].card_id, "BG23_000t")
        self.assertEqual(spells[0].spellcraft_source_uuid, m.uuid)

    def test_full_hand_spell_queues_not_destroyed(self):
        """满手: 法术排队等待不销毁 (RULES §6.13 / P6)。"""
        game = make_game()
        a = game.heroes[0]
        for _ in range(HAND_SIZE):
            add_spell_to_hand(game, a, "BG23_008t")
        self.assertTrue(a.hand_full())
        summon(game, "BG23_000", a)
        self.assertEqual(len(a.hand), HAND_SIZE)
        self.assertEqual(len(spell_in_hand(a)), HAND_SIZE)
        queued = [e for h, e in game.pending_hand_queue if h is a]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].card_id, "BG23_000t")


# ══════════════════ 3. 回合末丢弃 / Sunken Persistence 豁免 ══════════════════


class TestEndOfRecruitDiscard(unittest.TestCase):

    def test_unused_spell_discarded_at_end_of_recruit(self):
        game = make_game()
        a, b = game.heroes
        # 棋盘干净（避免下回合再生成干扰断言）
        s = add_spell_to_hand(game, a, "BG23_000t")
        game.end_recruit_phase()
        self.assertNotIn(s, a.hand)
        self.assertEqual(s.zone, Zone.REMOVED)
        self.assertEqual(len(spell_in_hand(a)), 0)

    def test_sunken_persistence_permanent_exemption(self):
        game = make_game()
        a, b = game.heroes
        m = summon(game, "BG23_007", a)     # 立即获得法术
        a.hand.remove(spell_in_hand(a)[0])  # 清掉，单独构造豁免路径
        s = add_spell_to_hand(game, a, "BG23_007t")
        s.spellcraft_source_uuid = m.uuid
        game._permanent_spellcraft_uuids.add(m.uuid)   # Sunken Persistence
        game.end_recruit_phase()
        self.assertIn(s, a.hand)
        self.assertEqual(s.zone, Zone.HAND)
        game._permanent_spellcraft_uuids.clear()

    def test_used_spell_not_in_hand_after_next_turn(self):
        """打出后随从在场的完整回合循环: 旧法术消耗、下回合生成新法术。"""
        game = make_game()
        a, b = game.heroes
        summon(game, "BG23_000", a)
        old = spell_in_hand(a)[0]
        game.play_spell(a, old, target=a.board[0])   # 本回合用掉
        self.assertEqual(old.zone, Zone.REMOVED)
        game.end_recruit_phase()
        # 下回合开始 generate_for_hero 重新给一张（新实体）
        spells = spell_in_hand(a)
        self.assertEqual(len(spells), 1)
        self.assertNotEqual(spells[0].uuid, old.uuid)


# ══════════════════ 4. 法术效果 + temporary 过期 ══════════════════


class TestSpellEffects(unittest.TestCase):

    def test_mini_myrmidon_spell_temp_atk_buff(self):
        game = make_game()
        a = game.heroes[0]
        tm = make_minion("Target", 5, 5)
        game.summon(a, tm)
        s = add_spell_to_hand(game, a, "BG23_000t")
        d = get_db().get("BG23_000t")
        gain = d.num(0, 2)   # 文本字面量 +2（无模板参数）
        self.assertTrue(game.play_spell(a, s, target=tm))
        self.assertEqual(tm.atk, 5 + gain)
        self.assertTrue(any(b.temporary for b in tm.buffs))
        # 下一招募阶段开始过期（RULES §6.13）
        game.end_recruit_phase()
        self.assertEqual(tm.atk, 5)

    def test_mini_myrmidon_golden_spell_plus_four(self):
        game = make_game()
        a = game.heroes[0]
        tm = make_minion("Target", 1, 1)
        game.summon(a, tm)
        s = add_spell_to_hand(game, a, "BG23_000_Gt")
        d = get_db().get("BG23_000_Gt")
        self.assertTrue(game.play_spell(a, s, target=tm))
        self.assertEqual(tm.atk, 1 + d.num(0, 4))   # 金色 +4（文本字面量）

    def test_no_target_spell_is_noop(self):
        """play_spell 无 target 分流（引擎缺口）: 效果落空、法术被消耗。"""
        game = make_game()
        a = game.heroes[0]
        tm = make_minion("Target", 2, 2)
        game.summon(a, tm)
        s = add_spell_to_hand(game, a, "BG23_000t")
        self.assertTrue(game.play_spell(a, s, target=None))
        self.assertEqual(tm.atk, 2)
        self.assertEqual(tm.buffs, [])

    def test_waverider_spell_buff_and_temp_windfury_on_naga(self):
        game = make_game()
        a = game.heroes[0]
        naga = make_minion("Naga", 3, 4, race=Race.NAGA)
        game.summon(a, naga)
        s = add_spell_to_hand(game, a, "BG23_007t")
        d = get_db().get("BG23_007t")
        self.assertTrue(game.play_spell(a, s, target=naga))
        self.assertEqual(naga.atk, 3 + d.num(0))
        self.assertEqual(naga.max_health, 4 + d.num(1))
        self.assertTrue(naga.has(GameTag.WINDFURY))
        # 下一招募阶段开始: buff 与临时风怒一并过期
        game.end_recruit_phase()
        self.assertEqual(naga.atk, 3)
        self.assertEqual(naga.max_health, 4)
        self.assertFalse(naga.has(GameTag.WINDFURY))

    def test_waverider_no_windfury_on_non_naga(self):
        game = make_game()
        a = game.heroes[0]
        beast = make_minion("Beast", 3, 4, race=Race.BEAST)
        game.summon(a, beast)
        s = add_spell_to_hand(game, a, "BG23_007t")
        d = get_db().get("BG23_007t")
        self.assertTrue(game.play_spell(a, s, target=beast))
        self.assertEqual(beast.atk, 3 + d.num(0))
        self.assertFalse(beast.has(GameTag.WINDFURY))

    def test_waverider_permanent_windfury_not_removed(self):
        """自带永久风怒的目标: 临时过期不误删（施加前已持有则保留）。"""
        game = make_game()
        a = game.heroes[0]
        naga = make_minion("Naga", 3, 4, race=Race.NAGA)
        game.summon(a, naga)
        naga.set(GameTag.WINDFURY, True)
        s = add_spell_to_hand(game, a, "BG23_007t")
        self.assertTrue(game.play_spell(a, s, target=naga))
        game.end_recruit_phase()
        self.assertTrue(naga.has(GameTag.WINDFURY))

    def test_waverider_golden_spell_double_values(self):
        game = make_game()
        a = game.heroes[0]
        naga = make_minion("Naga", 1, 1, race=Race.NAGA)
        game.summon(a, naga)
        s = add_spell_to_hand(game, a, "BG23_007_Gt")
        d = get_db().get("BG23_007_Gt")
        self.assertTrue(game.play_spell(a, s, target=naga))
        self.assertEqual(naga.atk, 1 + d.num(0))     # 金色 4/4
        self.assertEqual(naga.max_health, 1 + d.num(1))

    def test_glowscale_spell_temp_divine_shield(self):
        game = make_game()
        a = game.heroes[0]
        tm = make_minion("Target", 2, 2)
        game.summon(a, tm)
        s = add_spell_to_hand(game, a, "BG23_008t")
        self.assertTrue(game.play_spell(a, s, target=tm))
        self.assertTrue(tm.has(GameTag.DIVINE_SHIELD))
        game.end_recruit_phase()
        self.assertFalse(tm.has(GameTag.DIVINE_SHIELD))

    def test_glowscale_permanent_ds_not_removed(self):
        game = make_game()
        a = game.heroes[0]
        tm = make_minion("Target", 2, 2)
        game.summon(a, tm)
        tm.set(GameTag.DIVINE_SHIELD, True)
        s = add_spell_to_hand(game, a, "BG23_008t")
        self.assertTrue(game.play_spell(a, s, target=tm))
        game.end_recruit_phase()
        self.assertTrue(tm.has(GameTag.DIVINE_SHIELD))

    def test_temp_buff_survives_combat_then_expires_next_turn(self):
        """temporary buff 跨战斗存活（快照恢复），下一招募阶段开始过期。

        引擎现状: clear_temporary_buffs 无引擎调用点——过期完全由脚本层
        TURN_START 监听器实现（本测试即其行为契约）。
        """
        game = make_game()
        a, b = game.heroes
        tm = make_minion("Target", 5, 5)
        game.summon(a, tm)
        # 对面放一个 0 攻随从避免速胜伤害波动干扰（不必要，仅稳定场景）
        wall = make_minion("Wall", 0, 10, race=Race.NONE)
        game.summon(b, wall)
        s = add_spell_to_hand(game, a, "BG23_007t")
        d = get_db().get("BG23_007t")
        self.assertTrue(game.play_spell(a, s, target=tm))
        self.assertEqual(tm.max_health, 5 + d.num(1))
        game.end_recruit_phase()     # 战斗 + 快照恢复 + 下一回合开始
        self.assertEqual(tm.atk, 5)
        self.assertEqual(tm.max_health, 5)


# ══════════════════ 5. 金色随从 → 金色法术 ══════════════════


class TestGoldenSpellcraft(unittest.TestCase):

    def test_golden_minion_generates_golden_spell(self):
        game = make_game()
        a = game.heroes[0]
        gd = get_db().get("BG23_000_G")
        expect = game.db.by_dbf(gd.spellcraft_id).id   # BG23_000_Gt
        m = game.create_minion("BG23_000", controller=a, golden=True)
        self.assertEqual(m.card_id, "BG23_000_G")      # 金色=独立卡定义
        grant_spellcraft_spell(m, game)
        spells = spell_in_hand(a)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0].card_id, expect)
        self.assertEqual(spells[0].spellcraft_source_uuid, m.uuid)

    def test_golden_play_path_and_regeneration(self):
        game = make_game()
        a = game.heroes[0]
        m = game.create_minion("BG23_007", controller=a, golden=True)
        a.add_to_hand(m)
        self.assertTrue(game.play_minion(a, m))
        spells = spell_in_hand(a)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0].card_id, "BG23_007_Gt")
        game.end_recruit_phase()
        # 下回合 generate_for_hero: 金色随从仍给金色法术
        spells = spell_in_hand(a)
        self.assertEqual(len(spells), 1)
        self.assertEqual(spells[0].card_id, "BG23_007_Gt")
        self.assertEqual(spells[0].spellcraft_source_uuid, m.uuid)

    def test_golden_glowscale_spell_effect_equal(self):
        """BG23_008_Gt 与 BG23_008t 同文（DS 无数值差异）。"""
        game = make_game()
        a = game.heroes[0]
        tm = make_minion("Target", 2, 2)
        game.summon(a, tm)
        s = add_spell_to_hand(game, a, "BG23_008_Gt")
        self.assertTrue(game.play_spell(a, s, target=tm))
        self.assertTrue(tm.has(GameTag.DIVINE_SHIELD))


if __name__ == "__main__":
    unittest.main()
