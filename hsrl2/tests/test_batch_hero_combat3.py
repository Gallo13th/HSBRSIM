"""批次 hero_combat3 行为层语义测试（2026-09-02 加固重写）。

覆盖 16 个脚本类 / 19 个注册键（Sneed token 金色 id 与 Naga Conquest 为
同批附加注册）: Illidan Wingmen / Onyxia Broodmother / Tamsin Fragrant
Phylactery / Teron Rapid Reanimation / Drek'Thar Frostwolf Fervor /
Vanndar Stormpike Strength / Ozumat Tentacular / Azshara's Ambition +
Naga Conquest / Bru'kan 四元素 / Sneed Pilot the Shredder + token /
Thorim Choose Your Champion / Tras'tath Void Power / Xavius Feel
Devastation / Galakrond's Greed / Inge Major Hymn / Artanis Warp Gate。

驱动协议（TEST_SOP §2/§5）:
  - 真实路径: `game.start_game()` 走英雄技能 on_bind 接线；主动技能走
    `game.use_hero_power`；战斗一律真实 `game.run_combat`；被动 SoC/Avenge
    经真实战斗内事件广播。
  - 战斗内状态（SoC buff / 立即攻击 / Avenge 召唤 / 亡语授予）以事件
    探针在**发生时**采集——战后棋盘按快照复原（RULES §3.5），战后读板
    观察不到战斗内效果。
  - 池记账断言 available 差分；数值期望一律来自 `CardDef.num()` /
    token CardDef / 脚本文本字面量常量（禁止复制字面量）。
  - 每个"落空/不触发"断言都在**同一测试方法内**配正对照（SOP §16 空转
    测试判定法）——因此本文件全部行为测试在钩子被替换为 no-op 后均失败
    （`tools/audit_vacuous_tests.py --strict`）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2 import entity
from hsrl2.db import CardDB
from hsrl2.events import (
    BEFORE_ATTACK,
    DEATHRATTLE_TRIGGER,
    GOLD_SPENT,
    MINION_BOUGHT,
    SPELL_BOUGHT,
    START_OF_COMBAT,
    SUMMON,
    TURN_START,
    Listener,
)
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches.batch_hero_combat3 import (
    ArtanisScript,
    BrukanScript,
    DrekTharScript,
    ELEMENT_IDS,
    IllidanWingmenScript,
    OnyxiaBroodmotherScript,
    PROTOSS_IDS,
    SHREDDER_ID,
    STONE_ELEMENTAL_ID,
    TENTACLE_ID,
    TrastathScript,
    VanndarScript,
    WHELP_ID,
)
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None

PLAIN_T1 = "BG33_140"      # River Skipper 1/1 无关键词（干净炮灰）
PLAIN_T2 = "BG22_202"      # Tad 2/2 无关键词
BIG_T2 = "BG21_015"        # Tarecgosa 4/4 无关键词（高血沙袋）


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(hero_a_card: str, seed: int,
              hero_b_card: str = "TEST_HERO_B") -> Game:
    """A=被测英雄（真实卡 id → hero_power_def 数据链），B=中性对手。"""
    return Game([Hero(hero_a_card, "A"), Hero(hero_b_card, "B")],
                get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero,
        buff: tuple[int, int] | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    if buff is not None:
        m.add_buff(entity.Buff(atk=buff[0], health=buff[1]))
    game.summon(hero, m)
    return m


def put_tavern(game: Game, card_id: str, hero: Hero) -> Minion:
    game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def power_num(power_id: str, idx: int) -> int:
    d = get_db().get(power_id)
    v = d.num(idx)
    assert v is not None, f"{power_id} num({idx}) 缺失"
    return v


def record(game: Game, event: str, fn) -> None:
    game.events.register(Listener(event=event, owner=None, callback=fn))


def summon_probe(game: Game, controller: Hero | None = None) -> list:
    """SUMMON 探针: 立即快照属性（战后召唤物从棋盘移除）。"""
    seen: list = []

    def cb(g, minion=None, **kw):
        if minion is None:
            return
        if controller is not None and minion.controller is not controller:
            return
        seen.append((minion.card_id, minion.atk, minion.max_health,
                     minion.taunt,
                     minion.has(GameTag.DIVINE_SHIELD),
                     minion.has(GameTag.DEATHRATTLE),
                     minion.is_golden))
    record(game, SUMMON, cb)
    return seen


class TestRegistryState(unittest.TestCase):
    """批次注册台账（结构性——与钩子实现无关，空转审计白名单）。"""

    OK_IDS = (
        "TB_BaconShop_HP_069", "BG22_HERO_305p", "BG20_HERO_282p",
        "BG25_HERO_103p", "BG22_HERO_002p", "BG22_HERO_003p",
        "BG23_HERO_201p", "BG22_HERO_007p", "BG22_HERO_007p2",
        "BG22_HERO_001p", "BG21_HERO_030p", "BG21_HERO_030t",
        "BG21_HERO_030t_G", "BG27_HERO_801p2", "BG36_HERO_101p",
        "BG36_HERO_105p", "TB_BaconShop_HP_011", "BG26_HERO_102p",
        "BG31_HERO_802p",
    )
    # 跨批次维护: BG22_HERO_004p Varden 已由 batch_hero_remaining2 实现
    # （实体级 FROZEN 就绪后），故从本批 DEFERRED 台账移出。
    DEFERRED_IDS = ("BG31_HERO_801p", "BG31_HERO_811p")
    LATER_IMPLEMENTED = ("BG22_HERO_004p",)

    def test_ok_registered(self):
        for cid in self.OK_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_deferred_not_registered(self):
        for cid in self.DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_later_implemented_are_registered(self):
        for cid in self.LATER_IMPLEMENTED:
            self.assertIn(cid, REGISTRY, cid)


# ══════════════ TB_BaconShop_HP_069 Illidan — Wingmen ══════════════


class TestIllidan(unittest.TestCase):
    """TB_BaconShop_HP_069 Wingmen — SoC: 左右端随从各 +2/+1 并立即攻击。

    观察: SoC 事件探针（在技能监听器之后触发）读取己方两端随从属性与
    敌方血量——立即攻击在 SoC 内已完成一次完整攻击（敌方血量已下降）。
    """

    POWER = "TB_BaconShop_HP_069"

    def test_soc_buffs_both_ends_and_forces_immediate_attack(self):
        game = make_game("TB_BaconShop_HERO_08", seed=101)
        a, b = game.heroes
        game.start_game()
        left = put(game, PLAIN_T1, a, buff=(2, 4))     # 3/5
        right = put(game, PLAIN_T2, a, buff=(1, 5))    # 3/7
        enemy = put(game, BIG_T2, b, buff=(0, 30))     # 4/34
        g_atk = IllidanWingmenScript._ATK_GAIN
        g_hp = IllidanWingmenScript._HP_GAIN
        exp_left = (left.atk + g_atk, left.max_health + g_hp)
        exp_right = (right.atk + g_atk, right.max_health + g_hp)
        exp_enemy_hp = (enemy.health - exp_left[0] - exp_right[0])
        seen: dict = {}

        def probe(g, hero=None, **kw):
            if hero is a:
                seen["a"] = [(m.atk, m.max_health) for m in a.board]
                seen["e"] = [m.health for m in b.board]
        record(game, START_OF_COMBAT, probe)
        game.run_combat(a, b)
        # 两端各被 buff（SoC 后立即攻击，敌方血量已扣两次攻击）
        self.assertEqual(seen.get("a"), [exp_left, exp_right])
        self.assertEqual(seen.get("e"), [exp_enemy_hp])


# ══════════════ BG22_HERO_305p Onyxia — Broodmother ══════════════


class TestOnyxia(unittest.TestCase):
    """BG22_HERO_305p Broodmother — Avenge(4): 召唤 {0}/{0} Whelp 立即攻击,
    之后每次触发 +1/+1。

    观察: 真实战斗中的 DEATH 计数 → SUMMON 探针捕获 Whelp 身份/属性、
    BEFORE_ATTACK 探针捕获 Whelp 立即攻击、`_onyxia_improve` 持久计数。
    """

    POWER = "BG22_HERO_305p"

    def _setup(self, game: Game, a: Hero, b: Hero, n_friend: int = 4):
        for _ in range(n_friend):
            put(game, PLAIN_T1, a)
        return put(game, BIG_T2, b, buff=(6, 36))     # 10/40 沙袋

    def test_avenge_four_deaths_summons_attacking_whelp(self):
        game = make_game("BG22_HERO_305", seed=102)
        a, b = game.heroes
        game.start_game()
        self._setup(game, a, b)
        base = get_db().get(WHELP_ID)
        summons = summon_probe(game, controller=a)
        attacks: list = []

        def on_attack(g, attacker=None, defender=None, **kw):
            attacks.append(attacker.card_id)
        record(game, BEFORE_ATTACK, on_attack)
        game.run_combat(a, b)
        whelps = [s for s in summons if s[0] == WHELP_ID]
        self.assertEqual([(s[1], s[2]) for s in whelps],
                         [(base.atk, base.health)])       # 恰一次，基值
        self.assertIn(WHELP_ID, attacks)                  # 立即攻击
        self.assertEqual(getattr(a, "_onyxia_improve", 0),
                         OnyxiaBroodmotherScript._IMPROVE_STEP)

    def test_improve_applies_to_later_combat_whelp(self):
        game = make_game("BG22_HERO_305", seed=103)
        a, b = game.heroes
        game.start_game()
        self._setup(game, a, b)
        game.run_combat(a, b)                             # 第一次触发
        self.assertEqual(getattr(a, "_onyxia_improve", 0),
                         OnyxiaBroodmotherScript._IMPROVE_STEP)
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        base = get_db().get(WHELP_ID)
        step = OnyxiaBroodmotherScript._IMPROVE_STEP
        first = [s for s in summons if s[0] == WHELP_ID][0]
        self.assertEqual((first[1], first[2]),
                         (base.atk + step, base.health + step))

    def test_recruit_phase_deaths_do_not_arm_avenge(self):
        """招募期死亡不计数（Avenge=战斗关键词，RULES §6.11）——正对照:
        同一配置进入真实战斗后 4 次友方死亡照常召唤 Whelp。"""
        game = make_game("BG22_HERO_305", seed=104)
        a, b = game.heroes
        game.start_game()
        summons = summon_probe(game, controller=a)
        for _ in range(4):
            m = put(game, PLAIN_T1, a)
            m.set(GameTag.HEALTH, 0)
            game.check_deaths()
        self.assertEqual([s for s in summons if s[0] == WHELP_ID], [])
        self.assertIsNone(getattr(a, "_onyxia_improve", None))
        # 正对照: 战斗内 4 次死亡 → Whelp
        self._setup(game, a, b)
        game.run_combat(a, b)
        self.assertEqual([s[0] for s in summons if s[0] == WHELP_ID],
                         [WHELP_ID])


# ══════════════ BG20_HERO_282p Tamsin — Fragrant Phylactery ══════════════


class TestTamsin(unittest.TestCase):
    """BG20_HERO_282p Fragrant Phylactery — SoC: 最低攻随从获得亡语
    "Give your other minions this minion's stats"（max_health 口径）。
    """

    POWER = "BG20_HERO_282p"

    def _setup(self, game, a, b):
        x = put(game, PLAIN_T1, a, buff=(0, 4))        # 1/5 最低攻
        y = put(game, PLAIN_T2, a, buff=(8, 8))        # 10/10
        z = put(game, PLAIN_T2, a, buff=(8, 8))        # 10/10
        e = put(game, BIG_T2, b, buff=(6, 40))         # 10/44
        return x, y, z, e

    def test_deathrattle_granted_to_lowest_attack_only(self):
        game = make_game("BG20_HERO_282", seed=105)
        a, b = game.heroes
        game.start_game()
        x, y, z, e = self._setup(game, a, b)
        seen: dict = {}

        def probe(g, hero=None, **kw):
            if hero is a:
                seen["dr"] = [m.uuid for m in a.board
                              if m.has(GameTag.DEATHRATTLE)]
        record(game, START_OF_COMBAT, probe)
        game.run_combat(a, b)
        self.assertEqual(seen.get("dr"), [x.uuid])

    def test_death_gives_stats_to_other_minions(self):
        game = make_game("BG20_HERO_282", seed=106)
        a, b = game.heroes
        game.start_game()
        x, y, z, e = self._setup(game, a, b)
        x_atk, x_hp = x.atk, x.max_health
        exp_y = (y.atk + x_atk, y.max_health + x_hp)
        exp_z = (z.atk + x_atk, z.max_health + x_hp)
        seen: dict = {}

        def on_dr(g, minion=None, **kw):
            if minion is x:
                seen["y"] = (y.atk, y.max_health)
                seen["z"] = (z.atk, z.max_health)
        record(game, DEATHRATTLE_TRIGGER, on_dr)
        game.run_combat(a, b)
        self.assertIn(x, game.combat_death_log)
        self.assertEqual(seen.get("y"), exp_y)
        self.assertEqual(seen.get("z"), exp_z)


# ══════════════ BG25_HERO_103p Teron — Rapid Reanimation ══════════════


class TestTeron(unittest.TestCase):
    """BG25_HERO_103p Rapid Reanimation — 定向选择友方随从; SoC 摧毁它,
    腾出空位时召唤精确副本（含 buff）。"""

    POWER = "BG25_HERO_103p"

    def test_targeted_protocol_records_chosen_minion(self):
        game = make_game("BG25_HERO_103", seed=107)
        a, b = game.heroes
        game.start_game()
        m = put(game, PLAIN_T2, a)
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))          # 无目标 → PendingChoice
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "hero_power_target")
        self.assertIn(m, choice.options)
        choice.choose(choice.options.index(m))
        self.assertEqual(getattr(a, "_teron_uuid", None), m.uuid)

    def test_soc_destroys_target_and_resummons_exact_copy(self):
        game = make_game("BG25_HERO_103", seed=108)
        a, b = game.heroes
        game.start_game()
        m = put(game, PLAIN_T2, a, buff=(3, 4))          # 5/6
        put(game, BIG_T2, b, buff=(1, 20))               # 5/24
        a.gold = 10
        self.assertTrue(game.use_hero_power(a, target=m))
        exp = (m.atk, m.max_health)
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        copies = [s for s in summons if s[0] == PLAIN_T2]
        self.assertEqual([(s[1], s[2]) for s in copies], [exp])
        self.assertIn(m, game.combat_death_log)          # 摧毁触发死亡

    def test_sold_target_fizzles_but_live_target_resummons(self):
        # 负例: 选择后售出 → SoC 定位失败落空
        game = make_game("BG25_HERO_103", seed=109)
        a, b = game.heroes
        game.start_game()
        m = put(game, PLAIN_T2, a, buff=(3, 4))
        put(game, BIG_T2, b, buff=(1, 20))
        a.gold = 10
        self.assertTrue(game.use_hero_power(a, target=m))
        game.sell_minion(a, m)
        gone = summon_probe(game, controller=a)
        game.run_combat(a, b)
        self.assertEqual([s for s in gone if s[0] == PLAIN_T2], [])
        # 正对照: 目标存活 → 副本回归
        game2 = make_game("BG25_HERO_103", seed=110)
        a2, b2 = game2.heroes
        game2.start_game()
        m2 = put(game2, PLAIN_T2, a2, buff=(3, 4))
        put(game2, BIG_T2, b2, buff=(1, 20))
        a2.gold = 10
        self.assertTrue(game2.use_hero_power(a2, target=m2))
        live = summon_probe(game2, controller=a2)
        game2.run_combat(a2, b2)
        self.assertEqual([(s[1], s[2]) for s in live if s[0] == PLAIN_T2],
                         [(m2.atk, m2.max_health)])


# ══════════════ BG22_HERO_002p Drek'Thar — Frostwolf Fervor ══════════════


class TestDrekThar(unittest.TestCase):
    """BG22_HERO_002p Frostwolf Fervor — Turn 7 解锁: 战斗内每腾位召唤
    最高攻随从的精确副本。"""

    POWER = "BG22_HERO_002p"

    def test_turn_gate_then_copies_fill_board_with_highest_attack(self):
        game = make_game("BG22_HERO_002", seed=111)
        a, b = game.heroes
        game.start_game()
        low = put(game, PLAIN_T1, a, buff=(1, 9))        # 2/10
        high = put(game, PLAIN_T2, a, buff=(8, 1))       # 10/3
        put(game, BIG_T2, b, buff=(0, 40))               # 4/44
        game.turn = DrekTharScript._UNLOCK_TURN - 1
        before = summon_probe(game, controller=a)
        game.run_combat(a, b)
        self.assertEqual(before, [])                     # 未解锁不召唤
        game.turn = DrekTharScript._UNLOCK_TURN
        after = summon_probe(game, controller=a)
        game.run_combat(a, b)
        copies = [s for s in after if s[0] == high.card_id]
        self.assertEqual(len(copies), C.BOARD_SIZE - 2)
        self.assertEqual({(s[1], s[2]) for s in copies},
                         {(high.atk, high.max_health)})
        self.assertNotIn(low.card_id, [s[0] for s in after])

    def test_both_drekthar_combat_terminates(self):
        """回归: 旧实现 AFTER_ATTACK 循环补位 → 双方永不终止。正断言:
        双方各补满到 7（12 个副本）+ 轮数有限。"""
        game = make_game("BG22_HERO_002", seed=112,
                         hero_b_card="BG22_HERO_003")
        a, b = game.heroes
        game.start_game()
        game.turn = DrekTharScript._UNLOCK_TURN
        for h in (a, b):
            put(game, PLAIN_T1, h, buff=(5, 5))          # 6/6 单一来源
        result = game.run_combat(a, b)
        copies = [m for m in game.combat_summon_log]
        self.assertEqual(len(copies), 2 * (C.BOARD_SIZE - 1))
        self.assertLess(result.rounds, 200)


# ══════════════ BG22_HERO_003p Vanndar — Stormpike Strength ══════════════


class TestVanndar(unittest.TestCase):
    """BG22_HERO_003p Stormpike Strength — 最高 max_health（不是最高攻）
    随从的副本填满空位。"""

    POWER = "BG22_HERO_003p"

    def test_copies_highest_max_health_minion(self):
        game = make_game("BG22_HERO_003", seed=113)
        a, b = game.heroes
        game.start_game()
        hitter = put(game, PLAIN_T2, a, buff=(8, 1))     # 10/3 高攻低血
        tank = put(game, PLAIN_T1, a, buff=(1, 19))      # 2/20 高血低攻
        put(game, BIG_T2, b, buff=(0, 40))
        game.turn = VanndarScript._UNLOCK_TURN
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        copies = [s for s in summons if s[0] == tank.card_id]
        self.assertEqual(len(copies), C.BOARD_SIZE - 2)
        self.assertEqual({(s[1], s[2]) for s in copies},
                         {(tank.atk, tank.max_health)})
        self.assertNotIn(hitter.card_id, [s[0] for s in summons])


# ══════════════ BG23_HERO_201p Ozumat — Tentacular ══════════════


class TestOzumat(unittest.TestCase):
    """BG23_HERO_201p Tentacular — SoC 空位召唤 {0}/{0} Taunt Tentacle;
    每出售一只随从后续 Tentacle +{1}/{1}。"""

    POWER = "BG23_HERO_201p"

    def test_soc_summons_exactly_one_taunt_tentacle(self):
        """官方文本 "summon **a** Tentacle"（单数）：每场战斗最多 1 只。

        2026-10-18 修正：旧实现 while-空位把棋盘填满（7 只），导致官方
        loss 轨迹被引擎算成 win（trace f5d1c647b2f449d1，BobsBuddy
        `CheckForTentacular` 亦用 `!_tokenSummoned` 每场 1 只）。
        """
        game = make_game("BG23_HERO_201", seed=114)
        a, b = game.heroes
        game.start_game()
        put(game, PLAIN_T2, a)                           # 来源（1 只在场）
        put(game, BIG_T2, b, buff=(2, 30))
        base = power_num(self.POWER, 0)
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        tents = [s for s in summons if s[0] == TENTACLE_ID]
        self.assertEqual(len(tents), 1)                  # 不是 BOARD_SIZE-1
        self.assertEqual({(s[1], s[2], s[3]) for s in tents},
                         {(base, base, True)})           # 2/2 + Taunt

    def test_ozumat_official_trace_river_skipper_loses(self):
        """官方轨迹回归：Risen Rider 3/2（Taunt+Reborn）vs River Skipper 1/1
        的 Ozumat 方 = **loss**（BobsBuddy 10000 次 loss / 官方 result=Loss）。

        修复前引擎会召唤 6-7 只 Tentacle → 记为 win（与官方相反）。
        """
        game = make_game("BG23_HERO_201", seed=1018,
                         hero_b_card="BG20_HERO_102")
        a, b = game.heroes
        game.start_game()
        put(game, PLAIN_T1, a)                       # River Skipper 1/1
        put(game, "BG25_001", b, buff=(1, 1))        # Risen Rider 3/2
        winners = []
        for _ in range(8):
            result = game.run_combat(a, b)
            winners.append("win" if result.winner is a
                           else "loss" if result.winner is b else "tie")
        self.assertEqual(set(winners), {"loss"},
                         f"官方轨迹要求 8/8 loss，实际 {winners}")

    def test_sell_count_increases_tentacle_stats(self):
        game = make_game("BG23_HERO_201", seed=115)
        a, b = game.heroes
        game.start_game()
        put(game, PLAIN_T2, a)
        put(game, BIG_T2, b, buff=(2, 30))
        step = power_num(self.POWER, 1)
        for _ in range(2):
            fodder = put(game, PLAIN_T1, a)
            game.sell_minion(a, fodder)
        base = power_num(self.POWER, 0) + 2 * step
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        tents = [s for s in summons if s[0] == TENTACLE_ID]
        self.assertEqual(len(tents), 1)
        self.assertEqual({(s[1], s[2]) for s in tents}, {(base, base)})

    def test_both_ozumat_combat_terminates(self):
        """回归: 旧实现 AFTER_ATTACK 循环补位 → 无限战斗。正断言双方各
        补 1 只 Tentacle（每场每方最多 1 只）且轮数有限。"""
        game = make_game("BG23_HERO_201", seed=116,
                         hero_b_card="BG23_HERO_201")
        a, b = game.heroes
        game.start_game()
        for h in (a, b):
            put(game, PLAIN_T2, h)
        result = game.run_combat(a, b)
        tents = [m for m in game.combat_summon_log
                 if m.card_id == TENTACLE_ID]
        self.assertEqual(len(tents), 2)                  # 1/方，不是 12
        self.assertLess(result.rounds, 200)


# ══════════════ BG22_HERO_007p Azshara + Naga Conquest ══════════════


class TestAzshara(unittest.TestCase):
    """BG22_HERO_007p Azshara's Ambition — 棋盘总攻 ≥ {1} 时替换为
    Naga Conquest（BG22_HERO_007p2，Discover a Naga，cost=1）。"""

    POWER = "BG22_HERO_007p"
    CONQUEST = "BG22_HERO_007p2"

    def test_reaches_total_attack_threshold_then_discovers_naga(self):
        game = make_game("BG22_HERO_007", seed=117)
        a, b = game.heroes
        game.start_game()
        threshold = power_num(self.POWER, 1)
        base = get_db().get(PLAIN_T2)
        m = put(game, PLAIN_T2, a,
                buff=(threshold - 1 - base.atk, 10))     # 总攻 = 阈值-1
        self.assertEqual(sum(x.atk for x in a.board if not x.dead),
                         threshold - 1)
        self.assertEqual(game.hero_power_def(a).id, self.POWER)  # 未变身
        put(game, PLAIN_T1, a, buff=(1, 0))              # 总攻 ≥ 阈值
        self.assertEqual(game.hero_power_def(a).id, self.CONQUEST)
        # 变身后技能可用: Discover a Naga（占池预留）
        a.gold = 10
        gold_before = a.gold
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "discover_minion")
        for oid in choice.options:
            self.assertIn(get_db().get(oid).race, (Race.NAGA, Race.ALL))
        pick = choice.options[0]
        avail = game.minion_pool.available(pick)
        choice.choose(0)
        conquest = get_db().get(self.CONQUEST)
        self.assertEqual(a.gold, gold_before - conquest.cost)
        self.assertIn(pick, [x.card_id for x in a.hand
                             if isinstance(x, Minion)])
        self.assertEqual(game.minion_pool.available(pick), avail)


# ══════════════ BG22_HERO_001p Bru'kan — Embrace the Elements ══════════════


class TestBrukan(unittest.TestCase):
    """BG22_HERO_001p Embrace the Elements — 选择元素（4 选 1），SoC 施放
    对应祈咒（Fire 最左攻翻倍 / Water 最右圣盾+嘲讽 / Lightning 5 敌各
    1 伤 / Earth 4 友方获召 1/1 的亡语）。"""

    POWER = "BG22_HERO_001p"

    def _select(self, game: Game, a: Hero, idx: int) -> None:
        a.gold = 10
        self.assertTrue(game.use_hero_power(a))
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "choose_element")
        self.assertEqual(choice.options, list(ELEMENT_IDS))
        choice.choose(idx)

    def test_fire_doubles_leftmost_attack_in_combat(self):
        game = make_game("BG22_HERO_001", seed=118)
        a, b = game.heroes
        game.start_game()
        left = put(game, PLAIN_T1, a, buff=(2, 5))       # 3/6
        right = put(game, PLAIN_T2, a, buff=(0, 5))      # 2/7
        put(game, BIG_T2, b, buff=(0, 30))
        self._select(game, a, 1)
        seen: dict = {}

        def probe(g, hero=None, **kw):
            if hero is a:
                seen["atk"] = [m.atk for m in a.board]
        record(game, START_OF_COMBAT, probe)
        game.run_combat(a, b)
        self.assertEqual(seen.get("atk"), [left.atk * 2, right.atk])

    def test_water_grants_divine_shield_and_taunt_to_rightmost(self):
        game = make_game("BG22_HERO_001", seed=119)
        a, b = game.heroes
        game.start_game()
        put(game, PLAIN_T1, a, buff=(2, 5))
        right = put(game, PLAIN_T2, a, buff=(0, 5))
        put(game, BIG_T2, b, buff=(0, 30))
        self._select(game, a, 2)
        seen: dict = {}

        def probe(g, hero=None, **kw):
            if hero is a:
                seen["kw"] = (right.has(GameTag.DIVINE_SHIELD),
                              right.taunt)
        record(game, START_OF_COMBAT, probe)
        game.run_combat(a, b)
        self.assertEqual(seen.get("kw"), (True, True))

    def test_lightning_hits_five_random_enemies(self):
        game = make_game("BG22_HERO_001", seed=120)
        a, b = game.heroes
        game.start_game()
        put(game, PLAIN_T1, a, buff=(1, 9))
        enemies = [put(game, PLAIN_T1, b, buff=(0, 4))
                   for _ in range(BrukanScript._LIGHTNING_COUNT)]
        exp = [e.health - BrukanScript._LIGHTNING_DAMAGE for e in enemies]
        self._select(game, a, 3)
        seen: dict = {}

        def probe(g, hero=None, **kw):
            if hero is a:
                seen["hp"] = [m.health for m in b.board]
        record(game, START_OF_COMBAT, probe)
        game.run_combat(a, b)
        self.assertEqual(seen.get("hp"), exp)

    def test_earth_grants_deathrattle_summoning_stone_elementals(self):
        game = make_game("BG22_HERO_001", seed=121)
        a, b = game.heroes
        game.start_game()
        for _ in range(BrukanScript._EARTH_COUNT):
            put(game, PLAIN_T1, a)
        put(game, BIG_T2, b, buff=(6, 40))               # 10/44 全歼友方
        self._select(game, a, 0)
        golem = get_db().get(STONE_ELEMENTAL_ID)
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        stones = [s for s in summons if s[0] == STONE_ELEMENTAL_ID]
        self.assertEqual(len(stones), BrukanScript._EARTH_COUNT)
        self.assertEqual({(s[1], s[2]) for s in stones},
                         {(golem.atk, golem.health)})

    def test_no_element_selected_whiffs_then_fire_applies(self):
        game = make_game("BG22_HERO_001", seed=122)
        a, b = game.heroes
        game.start_game()
        left = put(game, PLAIN_T1, a, buff=(2, 5))       # 3/6
        put(game, BIG_T2, b, buff=(0, 30))
        no_elem: dict = {}

        def probe(g, hero=None, **kw):
            if hero is a:
                no_elem["atk"] = left.atk
        record(game, START_OF_COMBAT, probe)
        game.run_combat(a, b)
        self.assertEqual(no_elem.get("atk"), left.atk)   # 未选择 → 落空
        self._select(game, a, 1)                          # 正对照: Fire
        fire: dict = {}

        def probe2(g, hero=None, **kw):
            if hero is a:
                fire["atk"] = left.atk
        record(game, START_OF_COMBAT, probe2)
        game.run_combat(a, b)
        self.assertEqual(fire.get("atk"), left.atk * 2)


# ══════════════ BG21_HERO_030p Sneed + token ══════════════


class TestSneed(unittest.TestCase):
    """BG21_HERO_030p Pilot the Shredder — 开局 2/1 Shredder; 其亡语
    从手牌召唤最高 max_health 随从（**移出手牌**，非复制）并给圣盾
    （金色召 2 只）。F-09: 旧实现复制留手导致无限重召，已修正。"""

    POWER = "BG21_HERO_030p"

    def test_start_of_game_summons_token_shredder(self):
        game = make_game("BG21_HERO_030", seed=123)
        a, b = game.heroes
        game.start_game()
        shredders = [m for m in a.board if m.card_id == SHREDDER_ID]
        self.assertEqual(len(shredders), 1)
        d = get_db().get(SHREDDER_ID)
        self.assertEqual((shredders[0].atk, shredders[0].max_health),
                         (d.atk, d.health))

    def test_deathrattle_summons_hand_minion_with_divine_shield(self):
        game = make_game("BG21_HERO_030", seed=124)
        a, b = game.heroes
        game.start_game()
        hand_m = game.create_minion(PLAIN_T2, controller=a)
        hand_m.add_buff(entity.Buff(atk=3, health=5))    # 5/7
        a.add_to_hand(hand_m)
        put(game, BIG_T2, b, buff=(1, 30))               # 5/34 击杀 Shredder
        base = get_db().get(PLAIN_T2)
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        copies = [s for s in summons
                  if s[0] == PLAIN_T2 and s[4] is True]
        self.assertEqual([(s[1], s[2]) for s in copies],
                         [(base.atk + 3, base.health + 5)])
        self.assertNotIn(hand_m, a.hand)                 # 移出手牌（非复制）

    def test_golden_shredder_deathrattle_summons_two_highest(self):
        game = make_game("BG21_HERO_030", seed=125)
        a, b = game.heroes
        gsh = put(game, SHREDDER_ID, a, golden=True)
        self.assertTrue(gsh.is_golden)
        small = game.create_minion(PLAIN_T1, controller=a)
        small.add_buff(entity.Buff(atk=1, health=1))
        a.add_to_hand(small)
        big = game.create_minion(BIG_T2, controller=a)
        big.add_buff(entity.Buff(atk=1, health=1))       # 5/5
        a.add_to_hand(big)
        put(game, BIG_T2, b, buff=(1, 30))
        small_def = get_db().get(PLAIN_T1)
        big_def = get_db().get(BIG_T2)
        summons = summon_probe(game, controller=a)
        game.run_combat(a, b)
        copies = [(s[1], s[2]) for s in summons if s[4] is True]  # 带圣盾
        self.assertEqual(sorted(copies),
                         sorted([(big_def.atk + 1, big_def.health + 1),
                                 (small_def.atk + 1,
                                  small_def.health + 1)]))
        self.assertNotIn(small, a.hand)
        self.assertNotIn(big, a.hand)

    def test_empty_hand_fizzles_then_hand_minion_is_summoned(self):
        # 负例: 手牌无随从 → 落空
        game = make_game("BG21_HERO_030", seed=126)
        a, b = game.heroes
        game.start_game()
        put(game, BIG_T2, b, buff=(1, 30))
        empty = summon_probe(game, controller=a)
        game.run_combat(a, b)
        self.assertEqual([s for s in empty if s[4] is True], [])
        # 正对照: 手牌有随从 → 副本带圣盾入场
        game2 = make_game("BG21_HERO_030", seed=127)
        a2, b2 = game2.heroes
        game2.start_game()
        hand_m = game2.create_minion(PLAIN_T2, controller=a2)
        a2.add_to_hand(hand_m)
        put(game2, BIG_T2, b2, buff=(1, 30))
        filled = summon_probe(game2, controller=a2)
        game2.run_combat(a2, b2)
        self.assertEqual([s[0] for s in filled
                          if s[0] == PLAIN_T2 and s[4] is True],
                         [PLAIN_T2])


# ══════════════ BG27_HERO_801p2 Thorim — Choose Your Champion ══════════════


class TestThorim(unittest.TestCase):
    """BG27_HERO_801p2 Choose Your Champion — 开局 Discover 一个 Tier 7
    随从（选项即占池预留），累计花 {0} 金后入手。"""

    POWER = "BG27_HERO_801p2"

    def test_offers_only_tier_seven_and_reserves_pool(self):
        game = make_game("BG27_HERO_801", seed=128)
        a, b = game.heroes
        pre = {d.id: game.minion_pool.available(d.id)
               for d in get_db().pool_minions() if d.tech_level == 7}
        self.assertTrue(pre)
        game.start_game()
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "discover_minion")
        self.assertEqual(len(choice.options), min(3, len(pre)))
        for cid in choice.options:
            self.assertEqual(get_db().get(cid).tech_level, 7)
            self.assertEqual(game.minion_pool.available(cid), pre[cid] - 1)
        pick = choice.options[0]
        avail = game.minion_pool.available(pick)
        choice.choose(choice.options.index(pick))
        self.assertEqual(game.minion_pool.available(pick), avail)  # 预留保留

    def test_champion_granted_after_threshold_gold_spent(self):
        game = make_game("BG27_HERO_801", seed=129)
        a, b = game.heroes
        threshold = power_num(self.POWER, 0)
        game.start_game()
        choice = game.pending_choices.pop(0)
        pick = choice.options[0]
        # 未选择 champion: 花满阈值也不发放
        game.events.fire(game, GOLD_SPENT, amount=threshold - 1, hero=a)
        self.assertNotIn(pick, [x.card_id for x in a.hand
                                if isinstance(x, Minion)])
        choice.choose(choice.options.index(pick))
        game.events.fire(game, GOLD_SPENT, amount=1, hero=a)
        self.assertIn(pick, [x.card_id for x in a.hand
                             if isinstance(x, Minion)])


# ══════════════ BG36_HERO_101p Tras'tath — Void Power ══════════════


class TestTrastath(unittest.TestCase):
    """BG36_HERO_101p Void Power — 开局 Discover 一个带 Dark Gift 的 T5
    随从（锁在手牌），Turn {0}+1 解锁。"""

    POWER = "BG36_HERO_101p"

    def test_start_of_game_tier5_with_gift_locked_until_unlock_turn(self):
        game = make_game("BG36_HERO_101", seed=130)
        a, b = game.heroes
        unlock_turn = power_num(self.POWER, 0) + 1
        game.start_game()
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "dark_gift")
        self.assertTrue(choice.options)
        for cid, gift_id in choice.options:
            self.assertEqual(get_db().get(cid).tech_level,
                             TrastathScript._TIER)
            self.assertIsNotNone(get_db().get(gift_id))
        self.assertEqual(len({g for _, g in choice.options}),
                         len(choice.options))            # gift 互不相同
        card_id, gift_id = choice.options[0]
        choice.choose(choice.options.index((card_id, gift_id)))
        hand = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual([m.card_id for m in hand], [card_id])
        m = hand[0]
        self.assertEqual(m.get(GameTag.DARK_GIFT), gift_id)
        self.assertTrue(m.has(GameTag.LOCKED_IN_HAND))
        self.assertIn((gift_id, m.uuid, game.turn, "APPLIED"),
                      game.dark_gift_audit_log)
        self.assertFalse(game.play_minion(a, m))          # 锁定期不可打出
        # 未到解锁回合仍锁定
        game.events.fire(game, TURN_START, turn=unlock_turn - 1, hero=a)
        self.assertTrue(m.has(GameTag.LOCKED_IN_HAND))
        # 解锁回合清除锁并成功打出
        game.events.fire(game, TURN_START, turn=unlock_turn, hero=a)
        self.assertFalse(m.has(GameTag.LOCKED_IN_HAND))
        self.assertTrue(game.play_minion(a, m))
        self.assertIn(m, a.board)


# ══════════════ BG36_HERO_105p Xavius — Feel Devastation ══════════════


class TestXavius(unittest.TestCase):
    """BG36_HERO_105p Feel Devastation — 每 {0}+1 回合 Discover 一个带
    Dark Gift 的随从（入手不锁定）。"""

    POWER = "BG36_HERO_105p"

    def test_periodic_dark_gift_on_multiples_of_period(self):
        game = make_game("BG36_HERO_105", seed=131)
        a, b = game.heroes
        period = power_num(self.POWER, 0) + 1
        game.start_game()
        self.assertEqual(game.pending_choices, [])
        game.turn = period - 1
        game.events.fire(game, TURN_START, turn=period - 1, hero=a)
        self.assertEqual(game.pending_choices, [])        # 未到周期不触发
        game.turn = period
        game.events.fire(game, TURN_START, turn=period, hero=a)
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "dark_gift")
        self.assertTrue(choice.options)
        card_id, gift_id = choice.options[0]
        choice.choose(choice.options.index((card_id, gift_id)))
        hand = [m for m in a.hand if isinstance(m, Minion)]
        self.assertEqual([m.card_id for m in hand], [card_id])
        m = hand[0]
        self.assertEqual(m.get(GameTag.DARK_GIFT), gift_id)
        self.assertFalse(m.has(GameTag.LOCKED_IN_HAND))   # 无锁语义
        self.assertIn((gift_id, m.uuid, game.turn, "APPLIED"),
                      game.dark_gift_audit_log)
        game.turn = 2 * period
        game.events.fire(game, TURN_START, turn=2 * period, hero=a)
        self.assertEqual(len(game.pending_choices), 1)    # 下一周期再触发


# ══════════════ TB_BaconShop_HP_011 Galakrond — Galakrond's Greed ══════════════


class TestGalakrond(unittest.TestCase):
    """TB_BaconShop_HP_011 Galakrond's Greed — 选择馆内随从，再以更高
    tier 随从替换（旧回池/新占池/槽位保留）。"""

    POWER = "TB_BaconShop_HP_011"

    def test_replace_tavern_minion_with_higher_tier(self):
        game = make_game("TB_BaconShop_HERO_02", seed=132)
        a, b = game.heroes
        game.start_game()
        a.gold = 10
        a.tavern.clear()
        # 37.0: River Skipper（BG33_140）退出池内随从；池账本单测改用
        # 池内 T1（Rot Hide Gnoll）。
        plain_t1 = "BG25_013"
        old = put_tavern(game, plain_t1, a)
        old_avail = game.minion_pool.available(plain_t1)
        self.assertTrue(game.use_hero_power(a))
        c1 = game.pending_choices.pop(0)
        self.assertEqual(c1.kind, "galakrond_tavern")
        self.assertIn(old, c1.options)
        c1.choose(c1.options.index(old))
        c2 = game.pending_choices.pop(0)
        self.assertEqual(c2.kind, "discover_minion")
        for nid in c2.options:
            self.assertGreater(get_db().get(nid).tech_level,
                               old.tech_level)
            self.assertLessEqual(get_db().get(nid).tech_level,
                                 C.TAVERN_MAX_TIER)
        new_id = c2.options[0]
        new_avail = game.minion_pool.available(new_id)
        c2.choose(c2.options.index(new_id))
        self.assertEqual([e.card_id for e in a.tavern], [new_id])
        self.assertNotIn(old, a.tavern)
        self.assertEqual(game.minion_pool.available(plain_t1), old_avail + 1)
        self.assertEqual(game.minion_pool.available(new_id), new_avail - 1)

    def test_highest_tier_minion_has_no_replacement(self):
        game = make_game("TB_BaconShop_HERO_02", seed=133)
        a, b = game.heroes
        game.start_game()
        a.gold = 10
        a.tavern.clear()
        top_id = next(d.id for d in get_db().pool_minions()
                      if d.tech_level == C.TAVERN_MAX_TIER)
        top = put_tavern(game, top_id, a)
        self.assertTrue(game.use_hero_power(a))
        c1 = game.pending_choices.pop(0)
        c1.choose(c1.options.index(top))
        self.assertEqual(game.pending_choices, [])        # 无更高 tier
        self.assertEqual([e.card_id for e in a.tavern], [top_id])
        # 正对照: 更低 tier 的馆内随从有替换
        game2 = make_game("TB_BaconShop_HERO_02", seed=134)
        a2, b2 = game2.heroes
        game2.start_game()
        a2.gold = 10
        a2.tavern.clear()
        low = put_tavern(game2, PLAIN_T1, a2)
        self.assertTrue(game2.use_hero_power(a2))
        c = game2.pending_choices.pop(0)
        c.choose(c.options.index(low))
        self.assertEqual(game2.pending_choices[0].kind, "discover_minion")


# ══════════════ BG26_HERO_102p Inge — Major Hymn ══════════════


class TestInge(unittest.TestCase):
    """BG26_HERO_102p Major Hymn — 每回合 2 次，给随从等于酒馆 tier 的
    攻击（奇数回合）或生命（偶数回合）。"""

    POWER = "BG26_HERO_102p"

    def test_twice_per_turn_alternating_attack_and_health(self):
        game = make_game("BG26_HERO_102", seed=135)
        a, b = game.heroes
        game.start_game()
        a.gold = 10
        a.set(GameTag.TAVERN_TIER, 3)
        m = put(game, PLAIN_T2, a)
        tier = a.tavern_tier
        atk0, hp0 = m.atk, m.max_health
        self.assertTrue(game.use_hero_power(a, target=m))
        self.assertEqual(m.atk, atk0 + tier)             # turn 1 → 攻击
        self.assertTrue(game.use_hero_power(a, target=m))
        self.assertEqual(m.atk, atk0 + 2 * tier)
        self.assertFalse(game.use_hero_power(a, target=m))   # 每回合上限 2
        self.assertEqual(a.gold, 10)                     # cost=0
        game.turn = 2
        a.clear(GameTag.HERO_POWER_USED_THIS_TURN)
        self.assertTrue(game.use_hero_power(a, target=m))
        self.assertEqual(m.max_health, hp0 + tier)       # turn 2 → 生命


# ══════════════ BG31_HERO_802p Artanis — Warp Gate ══════════════


class TestArtanis(unittest.TestCase):
    """BG31_HERO_802p Warp Gate — 开局从 2 个 Protoss 中选 1，购买
    {0} 张卡后入手（随从+酒馆法术混合计数，token 不占池）。"""

    POWER = "BG31_HERO_802p"

    def test_choose_two_protoss_then_grant_after_buying_cards(self):
        game = make_game("BG31_HERO_802", seed=136)
        a, b = game.heroes
        threshold = power_num(self.POWER, 0)
        game.start_game()
        choice = game.pending_choices.pop(0)
        self.assertEqual(choice.kind, "choose_protoss")
        self.assertEqual(len(choice.options), ArtanisScript._OPTION_COUNT)
        self.assertTrue(set(choice.options) <= set(PROTOSS_IDS))
        pick = choice.options[0]
        avail = game.minion_pool.available(pick)
        choice.choose(choice.options.index(pick))
        dummy = game.create_minion(PLAIN_T2, controller=a)
        for _ in range(threshold - 1):
            game.events.fire(game, MINION_BOUGHT, minion=dummy)
        self.assertNotIn(pick, [x.card_id for x in a.hand
                                if isinstance(x, Minion)])
        game.events.fire(game, SPELL_BOUGHT, hero=a)      # 第 14 张 = 法术
        self.assertIn(pick, [x.card_id for x in a.hand
                             if isinstance(x, Minion)])
        self.assertEqual(game.minion_pool.available(pick), avail)  # 非池卡


if __name__ == "__main__":
    unittest.main()
