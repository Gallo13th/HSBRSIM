"""批次 37x_combatgap 行为层测试（7 张当前池内 combat 卡 + 金色）。

覆盖（全部走真实引擎路径）:
  - 攻击触发: 真实 `CombatScheduler._execute_attack`（`after_attack`
    广播、同时双向伤害/圣盾/剧毒语义）
  - 亡语: 真实 `game.destroy_minion` → `check_deaths` →
    `trigger_deathrattle`（含 `game.trigger_deathrattle` 直调路径）
  - Avenge: 真实战斗内友方死亡计数（`game.in_combat` + `_active_combat`
    + `_process_single_death` 的 Avenge 步骤）
  - SoC: 真实 `game.run_script_hook(entity, "start_of_combat")`
    （`CombatScheduler._start_of_combat_phase` 同款分发）+ 真实
    `game.run_combat` 整场战斗
  - 打出触发: 真实 `game.play_minion`（`card_played` 广播）
  - 战斗快照复原: 真实 `game.run_combat` 的 persist 通道 /
    `Minion.snapshot_state/restore_state`
  - 池记账: 真实 `game.minion_pool.available/total_remaining`

每张卡都有**正对照**（钩子换 no-op 后测试必失败）与**负对照**
（敌方 / 非目标 / 非元素 / 招募期无战斗对 / 无候选落空）。

DEFERRED 台账: 本批 0 DEFERRED（14 个 id 全部注册）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import LoseKeyword
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.events import AFTER_ATTACK
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_37x_combatgap as B
from hsrl2.tags import CardType, GameTag, Race, Zone

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 37, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m, position)
    return m


def dummy(hero: Hero, name: str = "Dummy", atk: int = 0,
          health: int = 100, race: Race | None = None) -> Minion:
    """合成随从（真实卡定义之外的白板，用于构造战斗场景）。"""
    m = Minion(f"TEST_{name}", name, atk=atk, health=health)
    m.game = hero.game
    m.controller = hero
    m.zone = Zone.PLAY
    if race is not None:
        m.set(GameTag.RACE, race)
    hero.board.append(m)
    hero.game._update_positions(hero)
    return m


def hand_minion(game: Game, hero: Hero, card_id: str,
                golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert hero.add_to_hand(m)
    return m


def enter_combat(game: Game, a: Hero, b: Hero) -> None:
    game.in_combat = True
    game._active_combat = (a, b)


def leave_combat(game: Game) -> None:
    game.in_combat = False
    game._active_combat = None


def kill(game: Game, m: Minion) -> None:
    """战斗内杀死一个随从（真实死亡链 + Avenge 计数）。"""
    m.health = 0
    game._process_single_death(m)


# ══════════════════════════════════════════════════════════════════════
# 结构性: 注册表 / 数据链 / DEFERRED 台账
# ══════════════════════════════════════════════════════════════════════


class TestRegistryAndCardDefs(unittest.TestCase):
    """@engine-only 结构性: 注册表 / 金色独立 CardDef / num 纪律。"""

    def test_registered_all_ids(self):
        expected = [
            B.DE_VOLITIONIST, B.DE_VOLITIONIST_G,
            B.LICHLING_HOARDER, B.LICHLING_HOARDER_G,
            B.HOPEBRINGER, B.HOPEBRINGER_G,
            B.NADINA, B.NADINA_G,
            B.GHASTCOILER, B.GHASTCOILER_G,
            B.ULTRAVIOLET, B.ULTRAVIOLET_G,
            B.EUDORA, B.EUDORA_G,
        ]
        self.assertEqual(len(expected), 14)
        for cid in expected:
            self.assertIn(cid, REGISTRY, cid)

    def test_pool_and_golden_defs(self):
        db = get_db()
        for cid in (B.DE_VOLITIONIST, B.LICHLING_HOARDER, B.HOPEBRINGER,
                    B.NADINA, B.GHASTCOILER, B.ULTRAVIOLET, B.EUDORA):
            d = db.get(cid)
            self.assertIsNotNone(d, cid)
            self.assertTrue(d.is_pool_minion, cid)
        for cid in (B.DE_VOLITIONIST_G, B.LICHLING_HOARDER_G,
                    B.HOPEBRINGER_G, B.ULTRAVIOLET_G, B.EUDORA_G):
            self.assertTrue(db.get(cid).is_golden_def, cid)
        self.assertTrue(db.get(B.NADINA_G).is_golden_def)
        self.assertTrue(db.get(B.GHASTCOILER_G).is_golden_def)

    def test_template_numbers(self):
        db = get_db()
        d = db.get(B.HOPEBRINGER)
        self.assertEqual((d.num(0), d.num(1)), (4, 3))
        gd = db.get(B.HOPEBRINGER_G)
        self.assertEqual((gd.num(0), gd.num(1)), (8, 6))
        u = db.get(B.ULTRAVIOLET)
        self.assertEqual((u.num(0), u.num(1)), (3, 3))
        ug = db.get(B.ULTRAVIOLET_G)
        self.assertEqual((ug.num(0), ug.num(1)), (6, 6))
        self.assertEqual(db.get(B.GHASTCOILER).num(0), 2)
        self.assertEqual(db.get(B.GHASTCOILER_G).num(0), 4)
        self.assertEqual((db.get(B.EUDORA).num(0),
                          db.get(B.EUDORA).num(1)), (6, 6))
        self.assertEqual(db.get(B.LICHLING_HOARDER).avenge_target, 3)
        self.assertEqual(db.get(B.LICHLING_HOARDER_G).avenge_target, 3)

    def test_no_deferred_ledger(self):
        """本批 7/7 全部实现，无 DEFERRED 类需要登记。"""
        self.assertFalse(hasattr(B, "DEFERRED_CARDS"))

    def test_scripts_class_mapping(self):
        self.assertIs(REGISTRY[B.DE_VOLITIONIST], B.DeVolitionistScript)
        self.assertIs(REGISTRY[B.DE_VOLITIONIST_G],
                      B.DeVolitionistGoldenScript)
        self.assertIs(REGISTRY[B.LICHLING_HOARDER_G],
                      B.LichlingHoarderGoldenScript)
        self.assertIs(REGISTRY[B.NADINA_G], B.NadinaGoldenScript)
        self.assertIs(REGISTRY[B.EUDORA_G], B.ShipMasterEudoraGoldenScript)


# ══════════════════════════════════════════════════════════════════════
# BG36_102 De-volition-ist
# ══════════════════════════════════════════════════════════════════════


class TestDeVolitionist(unittest.TestCase):
    """BG36_102 — 攻击后对最高**当前生命**敌方随从造成等同攻击的伤害。"""

    def test_after_attack_hits_highest_current_health(self):
        game = make_game(seed=1)
        a, b = game.heroes
        devo = put(game, B.DE_VOLITIONIST, a)          # 4/8
        e_low = dummy(b, "Low", 0, 10)                  # 当前 10
        e_high = dummy(b, "High", 0, 40)                # 当前 40
        enter_combat(game, a, b)
        CombatScheduler(game, a, b)._execute_attack(devo, e_low)
        # 攻击本体伤害 4 → e_low 6; 触发对最高当前生命 e_high 造成 4
        self.assertEqual(e_low.health, 6)
        self.assertEqual(e_high.health, 36)

    def test_uses_current_health_not_max_health(self):
        game = make_game(seed=2)
        a, b = game.heroes
        devo = put(game, B.DE_VOLITIONIST, a)
        e_low = dummy(b, "LowMax", 0, 40)
        e_low.set(GameTag.HEALTH, 3)                    # 当前 3 / 上限 40
        e_high = dummy(b, "HighMax", 0, 10)             # 当前 10 / 上限 10
        enter_combat(game, a, b)
        CombatScheduler(game, a, b)._execute_attack(devo, e_high)
        # e_high 10-4=6; 最高当前生命 = e_high(6) > e_low(3) → 再受 4
        self.assertEqual(e_high.health, 2)
        self.assertEqual(e_low.health, 3)

    def test_golden_deals_double_attack(self):
        game = make_game(seed=3)
        a, b = game.heroes
        devo = put(game, B.DE_VOLITIONIST, a, golden=True)   # 8/16
        target = dummy(b, "Tank", 0, 100)
        enter_combat(game, a, b)
        CombatScheduler(game, a, b)._execute_attack(devo, target)
        self.assertEqual(target.health, 100 - 8 - 16)

    def test_as_defender_does_not_trigger(self):
        game = make_game(seed=4)
        a, b = game.heroes
        devo = put(game, B.DE_VOLITIONIST, a)
        attacker = dummy(b, "Att", 1, 100)
        bystander = dummy(b, "By", 0, 100)
        enter_combat(game, a, b)
        CombatScheduler(game, a, b)._execute_attack(attacker, devo)
        # 敌方攻击者攻击 De-volition-ist：本卡是防守方 → 不触发
        self.assertEqual(bystander.health, 100)
        # 攻击者只承受 Devo 的反击 4（双向伤害）——没有 after-attack 追加伤害
        self.assertEqual(attacker.health, 96)

    def test_no_enemy_no_crash(self):
        game = make_game(seed=5)
        a, b = game.heroes
        devo = put(game, B.DE_VOLITIONIST, a)
        enter_combat(game, a, b)
        game.events.fire(game, AFTER_ATTACK, attacker=devo, defender=None)
        self.assertFalse(devo.dead)

    def test_recruit_phase_attack_no_opponent(self):
        """招募期没有 `_active_combat` → after_attack 落空不崩。"""
        game = make_game(seed=6)
        a = game.heroes[0]
        devo = put(game, B.DE_VOLITIONIST, a)
        game.events.fire(game, AFTER_ATTACK, attacker=devo, defender=None)
        self.assertEqual((devo.atk, devo.health), (4, 8))


# ══════════════════════════════════════════════════════════════════════
# BG36_848 Lichling Hoarder
# ══════════════════════════════════════════════════════════════════════


class TestLichlingHoarder(unittest.TestCase):
    """BG36_848 — Avenge (3): 入手战前战团中一个随从的 plain copy。"""

    def _prepare(self, game, golden=False):
        a, b = game.heroes
        lich = put(game, B.LICHLING_HOARDER, a, golden=golden)
        a.last_combat_board = [lich]
        enter_combat(game, a, b)
        return a, b, lich

    def test_avenge_three_deaths_gets_plain_copy(self):
        game = make_game(seed=10)
        a, b, lich = self._prepare(game)
        victims = [dummy(a, f"V{i}", 1, 5) for i in range(3)]
        for v in victims:
            kill(game, v)
        self.assertEqual(len(a.hand), 1)
        copy = a.hand[0]
        self.assertEqual(copy.card_id, B.LICHLING_HOARDER)
        d = get_db().get(B.LICHLING_HOARDER)
        self.assertEqual((copy.atk, copy.health), (d.atk, d.health))
        self.assertFalse(copy.is_golden)

    def test_two_deaths_no_trigger(self):
        game = make_game(seed=11)
        a, b, lich = self._prepare(game)
        for i in range(2):
            kill(game, dummy(a, f"V{i}", 1, 5))
        self.assertEqual(a.hand, [])

    def test_golden_gets_two_copies(self):
        game = make_game(seed=12)
        a, b, lich = self._prepare(game, golden=True)
        for i in range(3):
            kill(game, dummy(a, f"V{i}", 1, 5))
        self.assertEqual(len(a.hand), 2)
        self.assertEqual([m.card_id for m in a.hand],
                         [B.LICHLING_HOARDER] * 2)
        for m in a.hand:
            self.assertFalse(m.is_golden)

    def test_recruit_phase_deaths_do_not_count(self):
        game = make_game(seed=13)
        a, b = game.heroes
        lich = put(game, B.LICHLING_HOARDER, a)
        a.last_combat_board = [lich]
        # 招募期（in_combat=False）友方死亡不累计 Avenge（RULES §6.11）
        for i in range(4):
            m = dummy(a, f"V{i}", 1, 5)
            m.health = 0
            game._process_single_death(m)
        self.assertEqual(a.hand, [])

    def test_soc_fallback_snapshot_without_last_combat_board(self):
        """裸 run_combat（无 end_recruit_phase）→ SoC 兜底快照。"""
        game = make_game(seed=14)
        a, b = game.heroes
        lich = put(game, B.LICHLING_HOARDER, a)
        other = dummy(a, "Other", 1, 50)
        a.last_combat_board = []
        game.run_script_hook(lich, "start_of_combat")
        enter_combat(game, a, b)
        for i in range(3):
            kill(game, dummy(a, f"V{i}", 1, 5))
        self.assertEqual(len(a.hand), 1)
        self.assertIn(a.hand[0].card_id,
                      (B.LICHLING_HOARDER, other.card_id))

    def test_plain_copy_strips_buffs(self):
        game = make_game(seed=15)
        a, b, lich = self._prepare(game)
        from hsrl2.entity import Buff
        lich.add_buff(Buff(atk=5, health=5))
        for i in range(3):
            kill(game, dummy(a, f"V{i}", 1, 5))
        copy = a.hand[0]
        d = get_db().get(B.LICHLING_HOARDER)
        self.assertEqual((copy.atk, copy.health), (d.atk, d.health))

    def test_full_hand_goes_to_pending_queue(self):
        game = make_game(seed=16)
        a, b, lich = self._prepare(game)
        while not a.hand_full():
            a.add_to_hand(game.create_minion(B.GHASTCOILER, controller=a))
        for i in range(3):
            kill(game, dummy(a, f"V{i}", 1, 5))
        self.assertEqual(len(a.hand), 10)      # 满手不变
        self.assertEqual(len(game.pending_hand_queue), 1)
        self.assertEqual(game.pending_hand_queue[0][1].card_id,
                         B.LICHLING_HOARDER)


# ══════════════════════════════════════════════════════════════════════
# BG36_364 Hopebringer
# ══════════════════════════════════════════════════════════════════════


class TestHopebringer(unittest.TestCase):
    """BG36_364 — SoC 全板 +4/+3; 友方失去圣盾后永久改善。"""

    def test_soc_buffs_all_friendly_including_self(self):
        game = make_game(seed=20)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a)              # 4/3
        ally = dummy(a, "Ally", 1, 20)
        game.run_script_hook(h, "start_of_combat")
        self.assertEqual((h.atk, h.health), (4 + 4, 3 + 3))
        self.assertEqual((ally.atk, ally.health), (1 + 4, 20 + 3))

    def test_friendly_ds_loss_improves_next_soc(self):
        game = make_game(seed=21)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a)
        ally = dummy(a, "Ally", 1, 30)
        ally.set(GameTag.DIVINE_SHIELD, True)
        game.run_actions(LoseKeyword(ally, GameTag.DIVINE_SHIELD))
        self.assertEqual(getattr(h, "_hopebringer_improves", 0), 1)
        game.run_script_hook(h, "start_of_combat")
        self.assertEqual((h.atk, h.health), (4 + 8, 3 + 6))
        self.assertEqual((ally.atk, ally.health), (1 + 8, 30 + 6))

    def test_enemy_ds_loss_does_not_improve(self):
        game = make_game(seed=22)
        a, b = game.heroes
        h = put(game, B.HOPEBRINGER, a)
        enemy = dummy(b, "Enemy", 1, 20)
        enemy.set(GameTag.DIVINE_SHIELD, True)
        game.run_actions(LoseKeyword(enemy, GameTag.DIVINE_SHIELD))
        self.assertEqual(getattr(h, "_hopebringer_improves", 0), 0)
        game.run_script_hook(h, "start_of_combat")
        self.assertEqual((h.atk, h.health), (4 + 4, 3 + 3))

    def test_non_ds_keyword_loss_does_not_improve(self):
        game = make_game(seed=23)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a)
        ally = dummy(a, "Ally", 1, 20)
        ally.set(GameTag.TAUNT, True)
        game.run_actions(LoseKeyword(ally, GameTag.TAUNT))
        self.assertEqual(getattr(h, "_hopebringer_improves", 0), 0)

    def test_improve_survives_snapshot_restore(self):
        game = make_game(seed=24)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a)
        ally = dummy(a, "Ally", 1, 20)
        ally.set(GameTag.DIVINE_SHIELD, True)
        game.run_actions(LoseKeyword(ally, GameTag.DIVINE_SHIELD))
        snap = h.snapshot_state()
        h.restore_state(snap)
        self.assertEqual(getattr(h, "_hopebringer_improves", 0), 1)

    def test_two_improvements_scale_by_printed_value(self):
        """离线轨迹交叉验证公式: 每次改善 = 印面值（base×(1+count)）。"""
        game = make_game(seed=241)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a)
        ally = dummy(a, "Ally", 1, 40)
        for _ in range(2):
            ally.set(GameTag.DIVINE_SHIELD, True)
            game.run_actions(LoseKeyword(ally, GameTag.DIVINE_SHIELD))
        self.assertEqual(getattr(h, "_hopebringer_improves", 0), 2)
        game.run_script_hook(h, "start_of_combat")
        self.assertEqual((h.atk, h.health), (4 + 12, 3 + 9))

    def test_injected_dynamic_improve_count(self):
        """动态通道 `ScriptDataNum3`（官方轨迹重建注入）作为 Improve 初值。

        无注入时行为不变（上文各测试）；注入 2 次 → mult=3。
        """
        game = make_game(seed=242)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a)
        game.set_entity_script_data(h, {3: 2})
        game.run_script_hook(h, "start_of_combat")
        self.assertEqual((h.atk, h.health), (4 + 12, 3 + 9))

    def test_injected_dynamic_count_combines_with_own_increments(self):
        game = make_game(seed=243)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a)
        game.set_entity_script_data(h, {3: 1})
        ally = dummy(a, "Ally", 1, 40)
        ally.set(GameTag.DIVINE_SHIELD, True)
        game.run_actions(LoseKeyword(ally, GameTag.DIVINE_SHIELD))
        game.run_script_hook(h, "start_of_combat")
        # mult = 1（基础）+ 1（注入）+ 1（本场改善）= 3
        self.assertEqual((h.atk, h.health), (4 + 12, 3 + 9))

    def test_golden_values_and_improve(self):
        game = make_game(seed=25)
        a = game.heroes[0]
        h = put(game, B.HOPEBRINGER, a, golden=True)   # 8/6
        ally = dummy(a, "Ally", 1, 30)
        ally.set(GameTag.DIVINE_SHIELD, True)
        game.run_actions(LoseKeyword(ally, GameTag.DIVINE_SHIELD))
        game.run_script_hook(h, "start_of_combat")
        self.assertEqual((h.atk, h.health), (8 + 16, 6 + 12))
        self.assertEqual((ally.atk, ally.health), (1 + 16, 30 + 12))

    def test_real_combat_ds_loss_counts(self):
        """真实 run_combat: 友方龙破盾且 Hopebringer 存活 → 计数 +1。"""
        game = make_game(seed=26)
        a, b = game.heroes
        h = put(game, B.HOPEBRINGER, a)
        dragon = dummy(a, "DS", 2, 40, Race.DRAGON)
        dragon.set(GameTag.DIVINE_SHIELD, True)
        dummy(b, "B1", 1, 100)
        dummy(b, "B2", 1, 100)
        game.run_combat(a, b)
        self.assertEqual(getattr(h, "_hopebringer_improves", 0), 1)
        self.assertIn(h, a.board)


# ══════════════════════════════════════════════════════════════════════
# BGS_040 Nadina the Red
# ══════════════════════════════════════════════════════════════════════


class TestNadina(unittest.TestCase):
    """BGS_040 — 亡语给 3 / 金色 6 条友方龙圣盾。"""

    def _dragons(self, game, hero, n):
        return [dummy(hero, f"DR{i}", 1, 20, Race.DRAGON) for i in range(n)]

    def test_deathrattle_gives_three_dragons_ds(self):
        game = make_game(seed=30)
        a = game.heroes[0]
        nadina = put(game, B.NADINA, a)
        dragons = self._dragons(game, a, 5)
        non_dragon = dummy(a, "Beast", 1, 20, Race.BEAST)
        game.destroy_minion(nadina)
        shielded = [m for m in dragons if m.has(GameTag.DIVINE_SHIELD)]
        self.assertEqual(len(shielded), 3)
        self.assertFalse(non_dragon.has(GameTag.DIVINE_SHIELD))
        self.assertNotIn(nadina, a.board)

    def test_fewer_than_three_dragons_all_get_ds(self):
        game = make_game(seed=31)
        a = game.heroes[0]
        nadina = put(game, B.NADINA, a)
        dragons = self._dragons(game, a, 2)
        game.destroy_minion(nadina)
        self.assertTrue(all(m.has(GameTag.DIVINE_SHIELD) for m in dragons))

    def test_golden_six_dragons(self):
        game = make_game(seed=32)
        a = game.heroes[0]
        nadina = put(game, B.NADINA, a, golden=True)
        dragons = self._dragons(game, a, 7)
        game.destroy_minion(nadina)
        self.assertEqual(
            sum(1 for m in dragons if m.has(GameTag.DIVINE_SHIELD)), 6)

    def test_no_dragons_no_crash(self):
        game = make_game(seed=33)
        a = game.heroes[0]
        nadina = put(game, B.NADINA, a)
        dummy(a, "Beast", 1, 20, Race.BEAST)
        game.destroy_minion(nadina)
        self.assertNotIn(nadina, a.board)

    def test_all_type_minion_counts_as_dragon(self):
        """ALL 类型随从的身份集合含 DRAGON（has_race 集合语义）。"""
        game = make_game(seed=34)
        a = game.heroes[0]
        nadina = put(game, B.NADINA, a)
        amalgam = dummy(a, "Amalgam", 1, 20, Race.ALL)
        game.destroy_minion(nadina)
        self.assertTrue(amalgam.has(GameTag.DIVINE_SHIELD))


# ══════════════════════════════════════════════════════════════════════
# BGS_008 Ghastcoiler
# ══════════════════════════════════════════════════════════════════════


class TestGhastcoiler(unittest.TestCase):
    """BGS_008 — 亡语从池内召唤 2 / 金色 4 只随机亡语随从。"""

    def _deathrattle_ids(self):
        return {d.id for d in get_db().pool_minions()
                if "deathrattle" in d.keywords}

    def test_summons_two_from_pool(self):
        game = make_game(seed=40)
        a, b = game.heroes
        gh = put(game, B.GHASTCOILER, a)
        before = game.minion_pool.total_remaining()
        enter_combat(game, a, b)        # 战斗内死亡不回池（招募期死亡会回池）
        game.destroy_minion(gh)
        self.assertNotIn(gh, a.board)
        self.assertEqual(len(a.board), 2)
        allowed = self._deathrattle_ids()
        for m in a.board:
            self.assertIn(m.card_id, allowed)
            self.assertIn("deathrattle", get_db().get(m.card_id).keywords)
        # 池记账: 召唤取走 2 份
        self.assertEqual(game.minion_pool.total_remaining(), before - 2)

    def test_golden_summons_four(self):
        game = make_game(seed=41)
        a, b = game.heroes
        gh = put(game, B.GHASTCOILER, a, golden=True)
        before = game.minion_pool.total_remaining()
        enter_combat(game, a, b)
        game.destroy_minion(gh)
        self.assertEqual(len(a.board), 4)
        self.assertEqual(game.minion_pool.total_remaining(), before - 4)

    def test_no_candidates_no_crash(self):
        game = make_game(seed=42)
        a = game.heroes[0]
        gh = put(game, B.GHASTCOILER, a)
        old = game.max_tavern_tier
        game.max_tavern_tier = 0      # 所有候选 tech_level >=1 → 无候选
        try:
            game.destroy_minion(gh)
        finally:
            game.max_tavern_tier = old
        self.assertEqual(a.board, [])

    def test_recruit_phase_death_also_summons(self):
        game = make_game(seed=43)
        a = game.heroes[0]
        gh = put(game, B.GHASTCOILER, a)
        game.destroy_minion(gh)      # 招募期死亡（亡语不分阶段）
        self.assertEqual(len(a.board), 2)

    def test_trigger_deathrattle_direct_path(self):
        """引擎 "Trigger a Deathrattle" 统一入口同样生效。"""
        game = make_game(seed=44)
        a, b = game.heroes
        gh = put(game, B.GHASTCOILER, a)
        a.board.remove(gh)               # 直调入口: 本体已离场
        before = game.minion_pool.total_remaining()
        game.trigger_deathrattle(gh, hero=a)
        self.assertEqual(len(a.board), 2)
        self.assertEqual(game.minion_pool.total_remaining(), before - 2)


# ══════════════════════════════════════════════════════════════════════
# BG31_810 Ultraviolet Ascendant
# ══════════════════════════════════════════════════════════════════════


class TestUltravioletAscendant(unittest.TestCase):
    """BG31_810 — SoC 其他元素 +3/+3; 打出元素后永久改善。"""

    def _elemental_card_id(self):
        for d in get_db().pool_minions():
            if Race.ELEMENTAL in d.races and REGISTRY.get(d.id) is None:
                return d.id
        return None

    def test_soc_buffs_other_elementals_only(self):
        game = make_game(seed=50)
        a = game.heroes[0]
        u = put(game, B.ULTRAVIOLET, a)                 # 6/6
        el = dummy(a, "El", 1, 20, Race.ELEMENTAL)
        non_el = dummy(a, "Beast", 1, 20, Race.BEAST)
        game.run_script_hook(u, "start_of_combat")
        self.assertEqual((u.atk, u.health), (6, 6))     # "other" → 自身不加
        self.assertEqual((el.atk, el.health), (1 + 3, 20 + 3))
        self.assertEqual((non_el.atk, non_el.health), (1, 20))

    def test_play_elemental_improves_next_soc(self):
        game = make_game(seed=51)
        a = game.heroes[0]
        u = put(game, B.ULTRAVIOLET, a)
        el = dummy(a, "El", 1, 20, Race.ELEMENTAL)
        cid = self._elemental_card_id()
        self.assertIsNotNone(cid)
        played = hand_minion(game, a, cid)
        self.assertTrue(game.play_minion(a, played))
        self.assertEqual(getattr(u, "_ultraviolet_improves", 0), 1)
        game.run_script_hook(u, "start_of_combat")
        self.assertEqual((el.atk, el.health), (1 + 6, 20 + 6))

    def test_play_non_elemental_no_improve(self):
        game = make_game(seed=52)
        a = game.heroes[0]
        u = put(game, B.ULTRAVIOLET, a)
        beast = None
        for d in get_db().pool_minions():
            if Race.BEAST in d.races and Race.ELEMENTAL not in d.races:
                beast = d
                break
        played = hand_minion(game, a, beast.id)
        self.assertTrue(game.play_minion(a, played))
        self.assertEqual(getattr(u, "_ultraviolet_improves", 0), 0)

    def test_enemy_play_elemental_no_improve(self):
        game = make_game(seed=53)
        a, b = game.heroes
        u = put(game, B.ULTRAVIOLET, a)
        cid = self._elemental_card_id()
        played = hand_minion(game, b, cid)
        self.assertTrue(game.play_minion(b, played))
        self.assertEqual(getattr(u, "_ultraviolet_improves", 0), 0)

    def test_golden_values(self):
        game = make_game(seed=54)
        a = game.heroes[0]
        u = put(game, B.ULTRAVIOLET, a, golden=True)    # 12/12
        el = dummy(a, "El", 1, 50, Race.ELEMENTAL)
        cid = self._elemental_card_id()
        played = hand_minion(game, a, cid)
        self.assertTrue(game.play_minion(a, played))
        game.run_script_hook(u, "start_of_combat")
        self.assertEqual((el.atk, el.health), (1 + 12, 50 + 12))

    def test_improve_survives_snapshot_restore(self):
        game = make_game(seed=55)
        a = game.heroes[0]
        u = put(game, B.ULTRAVIOLET, a)
        cid = self._elemental_card_id()
        played = hand_minion(game, a, cid)
        self.assertTrue(game.play_minion(a, played))
        snap = u.snapshot_state()
        u.restore_state(snap)
        self.assertEqual(getattr(u, "_ultraviolet_improves", 0), 1)

    def test_two_improvements_scale_by_printed_value(self):
        """两元素 → count=2 → SoC +3×3/+3×3（官方轨迹 ScriptDataNum 交叉验证）。"""
        game = make_game(seed=551)
        a = game.heroes[0]
        u = put(game, B.ULTRAVIOLET, a)
        el = dummy(a, "El", 1, 40, Race.ELEMENTAL)
        cid = self._elemental_card_id()
        for _ in range(2):
            played = hand_minion(game, a, cid)
            self.assertTrue(game.play_minion(a, played))
        self.assertEqual(getattr(u, "_ultraviolet_improves", 0), 2)
        game.run_script_hook(u, "start_of_combat")
        self.assertEqual((el.atk, el.health), (1 + 9, 40 + 9))

    def test_injected_dynamic_improve_count(self):
        """注入 `ScriptDataNum3=2`（轨迹重建）→ mult=3；无注入行为不变。"""
        game = make_game(seed=552)
        a = game.heroes[0]
        u = put(game, B.ULTRAVIOLET, a)
        el = dummy(a, "El", 1, 40, Race.ELEMENTAL)
        game.set_entity_script_data(u, {3: 2})
        game.run_script_hook(u, "start_of_combat")
        self.assertEqual((el.atk, el.health), (1 + 9, 40 + 9))

    def test_played_ascendant_itself_counts_as_elemental(self):
        """Ascendant 从手牌打出时 `card_played` 已广播 → 自身也是元素。

        边界: 官方 wiki 无 Notes; 自然语言 "after you play an Elemental"
        含自身（事件在入场后广播，同 Groundbreaker 家族口径）。已在
        模块 docstring 记录该解读。
        """
        game = make_game(seed=56)
        a = game.heroes[0]
        u = hand_minion(game, a, B.ULTRAVIOLET)
        self.assertTrue(game.play_minion(a, u))
        self.assertEqual(getattr(u, "_ultraviolet_improves", 0), 1)

    def test_two_ascendants_buff_each_other(self):
        game = make_game(seed=57)
        a = game.heroes[0]
        u1 = put(game, B.ULTRAVIOLET, a)
        u2 = put(game, B.ULTRAVIOLET, a)
        game.run_script_hook(u1, "start_of_combat")
        # u1 的 SoC 只 buff "other" → u2；u1 自身不变
        self.assertEqual((u1.atk, u1.health), (6, 6))
        self.assertEqual((u2.atk, u2.health), (6 + 3, 6 + 3))


# ══════════════════════════════════════════════════════════════════════
# BG33_828 Ship Master Eudora
# ══════════════════════════════════════════════════════════════════════


class TestShipMasterEudora(unittest.TestCase):
    """BG33_828 — 亡语全板 +6/+6; 金色随从永久保留。"""

    def test_deathrattle_buffs_all_friendly(self):
        game = make_game(seed=60)
        a, b = game.heroes
        eudora = put(game, B.EUDORA, a)
        m1 = dummy(a, "M1", 1, 20)
        m2 = dummy(a, "M2", 1, 20)
        enemy = dummy(b, "Enemy", 1, 20)
        enter_combat(game, a, b)
        game.trigger_deathrattle(eudora, hero=a)
        self.assertEqual((m1.atk, m1.health), (1 + 6, 20 + 6))
        self.assertEqual((m2.atk, m2.health), (1 + 6, 20 + 6))
        self.assertEqual((enemy.atk, enemy.health), (1, 20))

    def test_golden_target_persist_normal_not(self):
        game = make_game(seed=61)
        a, b = game.heroes
        eudora = put(game, B.EUDORA, a)
        gold = put(game, B.ULTRAVIOLET, a, golden=True)
        norm = dummy(a, "Norm", 1, 20)
        enter_combat(game, a, b)
        game.trigger_deathrattle(eudora, hero=a)
        self.assertEqual((gold.atk, gold.health), (12 + 6, 12 + 6))
        self.assertTrue(any(b.persist for b in gold.buffs))
        self.assertFalse(any(b.persist for b in norm.buffs))
        self.assertEqual((norm.atk, norm.health), (1 + 6, 20 + 6))

    def test_golden_eudora_twice(self):
        game = make_game(seed=62)
        a, b = game.heroes
        eudora = put(game, B.EUDORA, a, golden=True)
        gold = put(game, B.ULTRAVIOLET, a, golden=True)   # 12/12
        norm = dummy(a, "Norm", 1, 20)
        enter_combat(game, a, b)
        game.trigger_deathrattle(eudora, hero=a)
        self.assertEqual((gold.atk, gold.health), (12 + 12, 12 + 12))
        self.assertEqual(sum(b.persist for b in gold.buffs), 2)
        self.assertEqual((norm.atk, norm.health), (1 + 12, 20 + 12))
        self.assertFalse(any(b.persist for b in norm.buffs))

    def test_empty_board_no_crash(self):
        game = make_game(seed=63)
        a, b = game.heroes
        eudora = put(game, B.EUDORA, a)
        a.board.remove(eudora)          # 真实死亡: 亡语结算时本体已离场
        enter_combat(game, a, b)
        game.trigger_deathrattle(eudora, hero=a)
        self.assertEqual(a.board, [])

    def test_persist_across_real_combat(self):
        """真实 run_combat: Eudora 战死 → 金色随从保留 +6/+6、普通随从回滚。"""
        game = make_game(seed=64)
        a, b = game.heroes
        eudora = put(game, B.EUDORA, a)                  # 8/3
        gold = put(game, B.ULTRAVIOLET, a, golden=True)  # 12/12
        norm = dummy(a, "Norm", 1, 40)
        dummy(b, "Big", 40, 200)                         # 一击必杀 Eudora
        game.run_combat(a, b)
        # 战斗结束棋盘复原: 金色随从 persist 通道保留 +6/+6
        self.assertEqual((gold.atk, gold.health), (12 + 6, 12 + 6))
        # 非金色目标的战斗内 buff 回滚
        self.assertEqual((norm.atk, norm.health), (1, 40))


if __name__ == "__main__":
    unittest.main()
