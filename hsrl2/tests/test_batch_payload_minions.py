"""批次 payload_minions 行为层测试（13 张池外载荷随从 + 2 法术塑造法术）。

全部断言走真实引擎路径:
  - 死亡: 真实 `game._process_single_death`（亡语/Titus/复生顺序）与
    `Hit` → `check_deaths`（Avenge 计数）
  - 战斗: 真实 `CombatScheduler._execute_attack`（Rally 在伤害前）
  - 回合: 真实 `game.run_script_hook(m, "end_of_turn")`（= end_recruit_phase
    的分发路径）与真实 `game.end_recruit_phase` / `_begin_recruit_for`
  - 施放: 真实 `game.play_spell`（池法术 acquire → 施放自动 release）与
    `game.cast_spell_effect`（效果施法）
  - 酒馆: 真实 `game.inject_tavern_minion`（持久酒馆 Buff 读取点）

覆盖口径（SOP §16 空转判定法——**每个行为测试方法都含正效果断言**，
hook 被替换为 no-op 后必然失败）: 正/负对照同方法、owner 隔离（2 英雄）、
跨回合/一次性、落空、池占返（非池卡零池操作 + 酒馆吞噬回池配平）、
满手 `pending_hand_queue`、Avenge 仅战斗内计数、同 seed 确定性。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.actions import Buff, Hit
from hsrl2.combat import CombatScheduler
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 本批 id（CardDB 按名核实——禁止凭记忆写 id） ──
IMPULSIVE = "BG21_006"
IMPULSIVE_G = "BG21_006_G"
FALSE_IMPLICATOR = "BG29_140"
FALSE_IMPLICATOR_G = "BG29_140_G"
FELEMENTAL = "BG25_041"
FELEMENTAL_G = "BG25_041_G"
HACKERFIN = "BG31_148"
HACKERFIN_G = "BG31_148_G"
WEARY_MAGE = "BG31_830"
WEARY_MAGE_G = "BG31_830_G"
REINVIGORATION = "BG31_830t"
REINVIGORATION_G = "BG31_830_Gt"
VINESPEAKER = "BG35_437"
VINESPEAKER_G = "BG35_437_G"
RYLAK = "BG26_801"
RYLAK_G = "BG26_801_G"
TIDE_RAISER = "BG34_920"
TIDE_RAISER_G = "BG34_920_G"
MACAW = "BGS_078"
MACAW_G = "TB_BaconUps_135"
SELFLESS_HERO = "BG_OG_221"
SELFLESS_HERO_G = "TB_BaconUps_014"
NALAA = "BG28_551"
NALAA_G = "BG28_551_G"
BRISTLEBACH = "BG26_157"
BRISTLEBACH_G = "BG26_157_G"
LIGHTFANG = "BGS_009"
LIGHTFANG_G = "TB_BaconUps_082"

_ALL_BATCH_IDS = (
    IMPULSIVE, IMPULSIVE_G, FALSE_IMPLICATOR, FALSE_IMPLICATOR_G,
    FELEMENTAL, FELEMENTAL_G, HACKERFIN, HACKERFIN_G,
    WEARY_MAGE, WEARY_MAGE_G, REINVIGORATION, REINVIGORATION_G,
    VINESPEAKER, VINESPEAKER_G, RYLAK, RYLAK_G, TIDE_RAISER, TIDE_RAISER_G,
    MACAW, MACAW_G, SELFLESS_HERO, SELFLESS_HERO_G, NALAA, NALAA_G,
    BRISTLEBACH, BRISTLEBACH_G, LIGHTFANG, LIGHTFANG_G,
)

# ── 测试用既有卡（CardDB 按名核实） ──
BUZZING_VERMIN = "BG31_803"      # 1/1 T1 野兽 Taunt+Deathrattle（亡语驱动）
DEEP_SEA_ANGLER = "BG23_004"     # 2/3 T3 纳迦（非池注册卡——定向目标）
TITUS = "BG25_354"               # 5/5 T5 亡语翻倍光环（真实卡）
ARMOR_STASH = "BG28_500"         # 池法术 T5 "Set your Armor to 5"（无目标）
SHIFTING_TIDE = "BG32_815"       # 池法术 T4（效果施法不改池）
BLOOD_GEM = "BG20_GEM"           # 非池法术（不广播 tavern_spell_cast）

TITUS_IDS = (TITUS, "BG25_354_G")

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 770) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def put(game: Game, hero: Hero, card_id: str, position: int | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m, position)
    return m


def make_minion(name: str, atk: int, health: int,
                race: Race = Race.NONE) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health, race=race)


def summon_plain(game: Game, hero: Hero, m: Minion,
                 position: int | None = None) -> Minion:
    assert game.summon(hero, m, position)
    return m


def to_hand(game: Game, hero: Hero, card_id: str,
            golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    hero.hand.append(m)
    m.zone = Zone.HAND
    return m


def tavern_put(game: Game, hero: Hero, card_id: str) -> Minion:
    """从池占 1 份后放入酒馆（池占返配平可断言）。"""
    assert game.minion_pool.acquire(card_id)
    m = game.create_minion(card_id, controller=hero)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def clear_tavern(hero: Hero) -> None:
    for e in list(hero.tavern):
        e.zone = Zone.REMOVED
    hero.tavern.clear()


def slay(game: Game, m: Minion) -> None:
    """真实死亡路径（亡语/Titus/复生/Avenge）。"""
    m.health = 0
    game._process_single_death(m)


def hit_kill(game: Game, victim: Minion, in_combat: bool) -> None:
    """Hit 致死 → check_deaths（Avenge 计数需战斗上下文）。"""
    prev = game.in_combat
    game.in_combat = in_combat
    try:
        game.run_actions(Hit(victim, victim.health))
    finally:
        game.in_combat = prev


def pool_copies(card_id: str) -> int:
    d = get_db().get(card_id)
    tier = min(max(d.tech_level, 1), 7)
    return C.POOL_COPIES_BY_TIER[tier]


def play_pool_spell(game: Game, hero: Hero, card_id: str, target=None) -> bool:
    assert game.spell_pool.acquire(card_id)
    s = game.create_spell(card_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    return game.play_spell(hero, s, target=target)


def decisions(game: Game, label: str) -> list:
    return [d for d in game.rng.decisions if d[0] == label]


# ── 测试探针脚本（挂在手工随从上——不经 REGISTRY，不受空转审计突变） ──


class _BattlecryProbe:
    """战吼: 自身 +1 Attack（可观测增量）。"""

    @staticmethod
    def battlecry(source, game, ctx):
        return Buff(source, atk=1)


class _DeathrattleProbe:
    """亡语: 自身 +1 Attack（macaw/触发亡语驱动）。"""

    @staticmethod
    def deathrattle(source, game, ctx):
        return Buff(source, atk=1)


class _DoublerProbe:
    """亡语翻倍光环（Titus 等价探针——引擎棋盘扫描 tag）。"""

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.DEATHRATTLE_DOUBLER, True)
        return None


def probe_battlecry(game: Game, hero: Hero, name: str,
                    atk: int = 1, health: int = 1) -> Minion:
    m = make_minion(name, atk, health)
    m.scripts = _BattlecryProbe
    return summon_plain(game, hero, m)


def probe_deathrattle(game: Game, hero: Hero, name: str,
                      atk: int = 1, health: int = 1) -> Minion:
    m = make_minion(name, atk, health)
    m.scripts = _DeathrattleProbe
    return summon_plain(game, hero, m)


def probe_doubler(game: Game, hero: Hero, name: str = "DOUBLER") -> Minion:
    m = make_minion(name, 1, 1)
    m.scripts = _DoublerProbe
    return summon_plain(game, hero, m)


class TestRegistryAndCardDefs(unittest.TestCase):
    """结构性守卫: 注册面 / 金色数据链 / 非池前提 / Bonus Keyword 域。"""

    def test_all_batch_ids_registered(self):
        missing = [cid for cid in _ALL_BATCH_IDS if cid not in REGISTRY]
        self.assertEqual(missing, [])

    def test_golden_ids_match_db_data_chain(self):
        db = get_db()
        pairs = [
            (IMPULSIVE, IMPULSIVE_G), (FALSE_IMPLICATOR, FALSE_IMPLICATOR_G),
            (FELEMENTAL, FELEMENTAL_G), (HACKERFIN, HACKERFIN_G),
            (WEARY_MAGE, WEARY_MAGE_G), (VINESPEAKER, VINESPEAKER_G),
            (RYLAK, RYLAK_G), (TIDE_RAISER, TIDE_RAISER_G),
            (NALAA, NALAA_G), (BRISTLEBACH, BRISTLEBACH_G),
        ]
        for base, expected_golden in pairs:
            g = db.golden_version(db.get(base))
            self.assertIsNotNone(g, base)
            self.assertEqual(g.id, expected_golden, base)
        # 无 triple_upgrade 链、按名核实的金色 id
        self.assertEqual(db.get(MACAW).triple_upgrade_id,
                         db.get(MACAW_G).dbf_id)
        self.assertEqual(db.get(SELFLESS_HERO).triple_upgrade_id,
                         db.get(SELFLESS_HERO_G).dbf_id)
        self.assertEqual(db.get(LIGHTFANG).triple_upgrade_id,
                         db.get(LIGHTFANG_G).dbf_id)

    def test_all_payload_cards_are_out_of_pool(self):
        """本批前提: 池外载荷（37.0 起 Hackerfin 回归池内，见下）。"""
        db = get_db()
        for cid in (IMPULSIVE, FALSE_IMPLICATOR, FELEMENTAL,
                    WEARY_MAGE, VINESPEAKER, RYLAK, TIDE_RAISER, MACAW,
                    SELFLESS_HERO, NALAA, BRISTLEBACH, LIGHTFANG):
            self.assertFalse(db.get(cid).is_pool_minion, cid)
            self.assertFalse(db.get(cid).is_pool_spell, cid)

    def test_weary_mage_spellcraft_data_chain_carddef(self):
        db = get_db()
        base = db.get(WEARY_MAGE)
        golden = db.get(WEARY_MAGE_G)
        self.assertEqual(db.by_dbf(base.spellcraft_id).id, REINVIGORATION)
        self.assertEqual(db.by_dbf(golden.spellcraft_id).id, REINVIGORATION_G)

    def test_bristlebach_avenge_threshold_from_carddef(self):
        db = get_db()
        self.assertEqual(db.get(BRISTLEBACH).avenge_target, 2)
        self.assertEqual(db.get(BRISTLEBACH_G).avenge_target, 2)

    def test_bonus_keyword_domain_data_drift_guard(self):
        """Bonus Keyword 官方 6 集（wiki: Battlegrounds/Bonus_Keyword）。"""
        from hsrl2.scripts.batches.batch_payload_minions import (
            _BONUS_KEYWORD_TAGS)
        self.assertEqual(set(_BONUS_KEYWORD_TAGS), {
            GameTag.DIVINE_SHIELD, GameTag.REBORN, GameTag.STEALTH,
            GameTag.TAUNT, GameTag.VENOMOUS, GameTag.WINDFURY})


class TestImpulsiveTrickster(unittest.TestCase):
    """BG21_006 — 亡语: 把本体 max Health 给一个随机友方（金色 twice）。"""

    def test_deathrattle_gives_max_health_to_random_ally(self):
        game = make_game(seed=1)
        a, b = game.heroes
        trickster = put(game, a, IMPULSIVE)
        Buff(trickster, health=3).do(game)          # max_health 5+3=8
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        enemy = summon_plain(game, b, make_minion("ENEMY", 2, 2))
        self.assertEqual(ally.max_health, 2)        # 死亡前无变化
        slay(game, trickster)
        self.assertEqual(ally.max_health, 2 + 8)    # 正效果
        self.assertEqual(ally.atk, 2)               # 只给 Health
        self.assertEqual(enemy.max_health, 2)       # owner 隔离
        self.assertEqual(game.minion_pool.available(IMPULSIVE), 0)  # 非池

    def test_no_other_friendly_ally_fizzles(self):
        game = make_game(seed=2)
        a, b = game.heroes
        trickster = put(game, a, IMPULSIVE)
        enemy = summon_plain(game, b, make_minion("ENEMY", 2, 2))
        slay(game, trickster)                       # 落空不崩
        self.assertEqual(enemy.max_health, 2)
        # 正对照: 同一方法内补一个友方 → 效果发生
        trickster2 = put(game, a, IMPULSIVE)
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        slay(game, trickster2)
        self.assertEqual(ally.max_health, 2 + trickster2.max_health)

    def test_golden_applies_twice(self):
        game = make_game(seed=3)
        a, _b = game.heroes
        golden = put(game, a, IMPULSIVE, golden=True)
        self.assertEqual(golden.card_id, IMPULSIVE_G)
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        amount = golden.max_health
        slay(game, golden)
        self.assertEqual(ally.max_health, 2 + 2 * amount)

    def test_titus_doubles_deathrattle(self):
        game = make_game(seed=4)
        a, _b = game.heroes
        titus = put(game, a, TITUS)
        t_hp0 = titus.max_health
        trickster = put(game, a, IMPULSIVE)
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        amount = trickster.max_health
        slay(game, trickster)
        # Titus 翻倍 → 亡语钩子触发 2 次（两次目标各自随机）
        self.assertEqual(
            len(decisions(game, "impulsive_trickster_target")), 2)
        total = (titus.max_health - t_hp0) + (ally.max_health - 2)
        self.assertEqual(total, 2 * amount)

    def test_same_seed_determinism(self):
        picks = []
        for _ in range(2):
            game = make_game(seed=55)
            a, _b = game.heroes
            trickster = put(game, a, IMPULSIVE)
            for name in ("A1", "A2", "A3"):
                summon_plain(game, a, make_minion(name, 1, 1))
            slay(game, trickster)
            got = [m.name for m in a.board if m.max_health > 1]
            self.assertEqual(len(got), 1)           # 正效果确实发生
            picks.append(got[0])
        self.assertEqual(picks[0], picks[1])


class TestFalseImplicator(unittest.TestCase):
    """BG29_140 — EoT: 吞噬酒馆随机随从获得属性（金色 double）。"""

    def test_end_of_turn_consumes_tavern_minion(self):
        game = make_game(seed=11)
        a, b = game.heroes
        clear_tavern(a)
        clear_tavern(b)
        impl = put(game, a, FALSE_IMPLICATOR)
        victim = tavern_put(game, a, BUZZING_VERMIN)
        before_pool = game.minion_pool.available(BUZZING_VERMIN)
        atk0, hp0 = impl.atk, impl.max_health
        game.run_script_hook(impl, "end_of_turn")
        self.assertNotIn(victim, a.tavern)          # 受害者消失
        self.assertEqual(impl.atk, atk0 + 1)        # 正效果: 获得属性
        self.assertEqual(impl.max_health, hp0 + 1)
        self.assertEqual(game.minion_pool.available(BUZZING_VERMIN),
                         before_pool + 1)           # 酒馆来源回池（配平）

    def test_empty_tavern_fizzles_then_positive(self):
        game = make_game(seed=12)
        a, _b = game.heroes
        clear_tavern(a)
        impl = put(game, a, FALSE_IMPLICATOR)
        atk0, hp0 = impl.atk, impl.max_health
        game.run_script_hook(impl, "end_of_turn")   # 空馆落空
        self.assertEqual((impl.atk, impl.max_health), (atk0, hp0))
        tavern_put(game, a, BUZZING_VERMIN)         # 正对照
        game.run_script_hook(impl, "end_of_turn")
        self.assertEqual(impl.atk, atk0 + 1)

    def test_golden_gains_double_stats(self):
        game = make_game(seed=13)
        a, _b = game.heroes
        clear_tavern(a)
        impl = put(game, a, FALSE_IMPLICATOR, golden=True)
        tavern_put(game, a, BUZZING_VERMIN)
        atk0, hp0 = impl.atk, impl.max_health
        game.run_script_hook(impl, "end_of_turn")
        self.assertEqual(impl.atk, atk0 + 2 * 1)
        self.assertEqual(impl.max_health, hp0 + 2 * 1)

    def _run_false_implicator(self, seed):
        """单次重放: 返回 (选择, 对手酒馆 id 列表)，并断言正效果/隔离。"""
        game = make_game(seed=seed)
        a, b = game.heroes
        clear_tavern(a)
        clear_tavern(b)
        impl = put(game, a, FALSE_IMPLICATOR)
        tavern_put(game, a, BUZZING_VERMIN)
        b_victim = tavern_put(game, b, BUZZING_VERMIN)
        game.run_script_hook(impl, "end_of_turn")
        self.assertIn(b_victim, b.tavern)       # 对手酒馆不受影响
        self.assertEqual(impl.atk, 2)           # 正效果: 1+1
        picks = decisions(game, "false_implicator_victim")
        self.assertEqual(len(picks), 1)
        # repr 含随机 uuid（每次建实体不同）→ 归一化后只剩卡身份
        stable = re.sub(r"\([0-9a-f]{8,}\)", "", picks[0][1])
        return (stable, tuple(c.card_id for c in b.tavern),
                b_victim.card_id)

    def test_owner_isolation_and_determinism(self):
        """对手酒馆隔离 + **同 seed 独立重放**确定性。
        （2026-09-13 修正: 旧版 `for seed in (21, 21)` 复用循环变量、并以
        `picks[0] == picks[0]` 自比较——"确定性"零验证。）"""
        first = self._run_false_implicator(21)
        self.assertTrue(first[0])               # 确有选择记录
        self.assertEqual(first, self._run_false_implicator(21))
        self.assertIn(first[2], first[1])       # 对手酒馆快照含受害者


class TestFelemental(unittest.TestCase):
    """BG25_041 — 战吼: 馆内随从 +{0}/+{1} this game（金色 twice）。"""

    def test_battlecry_buffs_current_and_future_tavern(self):
        game = make_game(seed=31)
        a, b = game.heroes
        clear_tavern(a)
        clear_tavern(b)
        d = get_db().get(FELEMENTAL)
        cur = tavern_put(game, a, BUZZING_VERMIN)
        b_cur = tavern_put(game, b, BUZZING_VERMIN)
        fele = to_hand(game, a, FELEMENTAL)
        self.assertTrue(game.play_minion(a, fele))
        self.assertEqual(cur.atk, 1 + d.num(0))     # 当前馆内（正效果）
        self.assertEqual(cur.max_health, 1 + d.num(1))
        self.assertEqual(b_cur.atk, 1)              # owner 隔离
        # 持久面: 之后注入的随从同样获得（"this game"）
        future = game.inject_tavern_minion(a, BUZZING_VERMIN)
        self.assertEqual(future.atk, 1 + d.num(0))
        self.assertEqual(future.max_health, 1 + d.num(1))
        b_future = game.inject_tavern_minion(b, BUZZING_VERMIN)
        self.assertEqual(b_future.atk, 1)

    def test_empty_tavern_registers_persistent_face(self):
        game = make_game(seed=32)
        a, _b = game.heroes
        clear_tavern(a)
        d = get_db().get(FELEMENTAL)
        self.assertTrue(game.play_minion(a, to_hand(game, a, FELEMENTAL)))
        later = game.inject_tavern_minion(a, BUZZING_VERMIN)
        self.assertEqual(later.atk, 1 + d.num(0))   # 空馆也登记持久面

    def test_golden_triggers_twice_total(self):
        game = make_game(seed=33)
        a, _b = game.heroes
        clear_tavern(a)
        d = get_db().get(FELEMENTAL)
        cur = tavern_put(game, a, BUZZING_VERMIN)
        self.assertTrue(game.play_minion(
            a, to_hand(game, a, FELEMENTAL, golden=True)))
        self.assertEqual(cur.atk, 1 + 2 * d.num(0))
        self.assertEqual(cur.max_health, 1 + 2 * d.num(1))


class TestHackerfin(unittest.TestCase):
    """BG31_148 — 战吼: 其他友方 +{0}/+{1}，每个不同 Bonus Keyword 提升。"""

    def _play(self, game, hero, golden=False):
        h = to_hand(game, hero, HACKERFIN, golden=golden)
        self.assertTrue(game.play_minion(hero, h))

    def test_improved_by_each_different_bonus_keyword(self):
        d = get_db().get(HACKERFIN)
        # 场景 1: 两个 Taunt（同一关键词）→ 只计 1 个 "different"
        game = make_game(seed=41)
        a, _b = game.heroes
        t1 = summon_plain(game, a, make_minion("T1", 1, 1))
        t1.set(GameTag.TAUNT, True)
        t2 = summon_plain(game, a, make_minion("T2", 1, 1))
        t2.set(GameTag.TAUNT, True)
        self._play(game, a)
        self.assertEqual(t1.atk, 1 + d.num(0) * 2)      # 1+1
        self.assertEqual(t2.max_health, 1 + d.num(1) * 2)
        # 场景 2: Taunt + Divine Shield → 2 个不同 → 增量 ×3
        game2 = make_game(seed=42)
        a2, _b2 = game2.heroes
        u1 = summon_plain(game2, a2, make_minion("U1", 1, 1))
        u1.set(GameTag.TAUNT, True)
        u2 = summon_plain(game2, a2, make_minion("U2", 1, 1))
        u2.set(GameTag.DIVINE_SHIELD, True)
        self._play(game2, a2)
        self.assertEqual(u1.atk, 1 + d.num(0) * 3)
        self.assertEqual(u2.atk, 1 + d.num(0) * 3)

    def test_non_bonus_keyword_does_not_improve_and_self_excluded(self):
        d = get_db().get(HACKERFIN)
        game = make_game(seed=43)
        a, _b = game.heroes
        poison = summon_plain(game, a, make_minion("P", 1, 1))
        poison.set(GameTag.POISONOUS, True)     # 非 Bonus Keyword
        self._play(game, a)
        self.assertEqual(poison.atk, 1 + d.num(0))      # 仅基础增量
        hack = [m for m in a.board if m.card_id == HACKERFIN][0]
        self.assertEqual(hack.atk, d.atk)               # "other minions" 不含自身

    def test_owner_isolation(self):
        d = get_db().get(HACKERFIN)
        game = make_game(seed=44)
        a, b = game.heroes
        mine = summon_plain(game, a, make_minion("MINE", 1, 1))
        theirs = summon_plain(game, b, make_minion("THEIRS", 1, 1))
        self._play(game, a)
        self.assertEqual(mine.atk, 1 + d.num(0))
        self.assertEqual(theirs.atk, 1)                 # 对手不受影响

    def test_golden_total_double(self):
        d = get_db().get(HACKERFIN)                     # 基础 1/2 → 总 2/4
        game = make_game(seed=45)
        a, _b = game.heroes
        ally = summon_plain(game, a, make_minion("ALLY", 1, 1))
        self._play(game, a, golden=True)
        self.assertEqual(ally.atk, 1 + 2 * d.num(0))
        self.assertEqual(ally.max_health, 1 + 2 * d.num(1))


class TestWearyMage(unittest.TestCase):
    """BG31_830 — Spellcraft: +2/+2; 纳迦另获 Reborn until next turn。"""

    def test_grants_spellcraft_spell_and_naga_reborn_until_next_turn(self):
        game = make_game(seed=51)
        a, _b = game.heroes
        put(game, a, WEARY_MAGE)
        spells = [c for c in a.hand if c.card_id == REINVIGORATION]
        self.assertEqual(len(spells), 1)                # 打出即得第一张
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))
        naga = summon_plain(game, a, make_minion(
            "NAGA", 2, 2, race=Race.NAGA))
        beast = summon_plain(game, a, make_minion(
            "BEAST", 2, 2, race=Race.BEAST))
        self.assertTrue(game.play_spell(a, spells[0], target=naga))
        self.assertEqual((naga.atk, naga.max_health), (4, 4))   # +2/+2
        self.assertTrue(naga.has(GameTag.REBORN))               # 纳迦专属
        self.assertEqual((beast.atk, beast.max_health), (2, 2))  # 未命中
        self.assertFalse(beast.has(GameTag.REBORN))
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertFalse(naga.has(GameTag.REBORN))              # 到期清除

    def test_non_naga_gets_stats_without_reborn(self):
        game = make_game(seed=52)
        a, _b = game.heroes
        put(game, a, WEARY_MAGE)
        spell = [c for c in a.hand if c.card_id == REINVIGORATION][0]
        beast = summon_plain(game, a, make_minion(
            "BEAST", 2, 2, race=Race.BEAST))
        self.assertTrue(game.play_spell(a, spell, target=beast))
        self.assertEqual((beast.atk, beast.max_health), (4, 4))
        self.assertFalse(beast.has(GameTag.REBORN))

    def test_native_reborn_naga_not_cleared_by_expiry(self):
        game = make_game(seed=53)
        a, _b = game.heroes
        put(game, a, WEARY_MAGE)
        spell = [c for c in a.hand if c.card_id == REINVIGORATION][0]
        naga = summon_plain(game, a, make_minion(
            "NAGA", 2, 2, race=Race.NAGA))
        naga.set(GameTag.REBORN, True)                  # 原生 Reborn
        self.assertTrue(game.play_spell(a, spell, target=naga))
        self.assertEqual(naga.atk, 4)                   # 正效果仍生效
        game.events.fire(game, "turn_start", turn=2, hero=a)
        self.assertTrue(naga.has(GameTag.REBORN))       # 不被误清

    def test_golden_spell_gives_four(self):
        game = make_game(seed=54)
        a, _b = game.heroes
        put(game, a, WEARY_MAGE, golden=True)
        spells = [c for c in a.hand if c.card_id == REINVIGORATION_G]
        self.assertEqual(len(spells), 1)                # 金色法术数据链
        beast = summon_plain(game, a, make_minion(
            "BEAST", 2, 2, race=Race.BEAST))
        self.assertTrue(game.play_spell(a, spells[0], target=beast))
        self.assertEqual((beast.atk, beast.max_health), (6, 6))

    def test_recruit_phase_regenerates_spell(self):
        game = make_game(seed=56)
        a, _b = game.heroes
        put(game, a, WEARY_MAGE)
        spell = [c for c in a.hand if c.card_id == REINVIGORATION][0]
        game.play_spell(a, spell, target=summon_plain(
            game, a, make_minion("NAGA", 2, 2, race=Race.NAGA)))
        self.assertEqual(
            len([c for c in a.hand if c.card_id == REINVIGORATION]), 0)
        game._begin_recruit_for(a)                      # 下回合开始生成
        self.assertEqual(
            len([c for c in a.hand if c.card_id == REINVIGORATION]), 1)

    def test_full_hand_queues_spellcraft_spell(self):
        game = make_game(seed=57)
        a, _b = game.heroes
        while not a.hand_full():
            a.add_to_hand(game.create_spell(ARMOR_STASH, controller=a))
        put(game, a, WEARY_MAGE)                        # on_summon 授予
        queued = [(h, e) for h, e in game.pending_hand_queue
                  if e.card_id == REINVIGORATION]
        self.assertEqual(len(queued), 1)                # 排队不销毁
        self.assertEqual(
            len([c for c in a.hand if c.card_id == REINVIGORATION]), 0)
        for _ in range(2):                              # 腾出 2 个位
            a.hand.pop().zone = Zone.REMOVED
        game._begin_recruit_for(a)                      # 真实交付路径
        self.assertEqual(
            len([c for c in a.hand if c.card_id == REINVIGORATION]), 2)
        self.assertEqual(
            [e for _h, e in game.pending_hand_queue
             if e.card_id == REINVIGORATION], [])


class TestVinespeaker(unittest.TestCase):
    """BG35_437 — 友方亡语随从死亡 → 血宝石永久 +{0} Attack。"""

    def test_friendly_deathrattle_death_improves_gems(self):
        game = make_game(seed=61)
        a, _b = game.heroes
        vines = put(game, a, VINESPEAKER)
        plain = summon_plain(game, a, make_minion("PLAIN", 1, 1))
        slay(game, plain)                       # 非亡语随从死亡 → 不触发
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 0)
        dr = put(game, a, BUZZING_VERMIN)       # 亡语随从（正效果）
        slay(game, dr)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 2)
        # 功能面: 之后的血宝石实际 +3 Attack（基础 num(0)=1 + 额外 2）
        from hsrl2.actions.bloodgem import PlayBloodGems
        gem = get_db().get(BLOOD_GEM)
        PlayBloodGems(vines, 1).do(game)
        self.assertEqual(vines.atk, 5 + gem.num(0) + 2)
        self.assertEqual(vines.max_health, 6 + gem.num(1))

    def test_enemy_deathrattle_death_does_not_improve(self):
        game = make_game(seed=62)
        a, b = game.heroes
        put(game, a, VINESPEAKER)
        enemy_dr = put(game, b, BUZZING_VERMIN)
        slay(game, enemy_dr)                    # 对手亡语随从 → 不触发
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 0)
        ally_dr = put(game, a, BUZZING_VERMIN)  # 正对照: 友方触发
        slay(game, ally_dr)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 2)
        self.assertEqual(b.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 0)

    def test_golden_num_four(self):
        game = make_game(seed=63)
        a, _b = game.heroes
        put(game, a, VINESPEAKER, golden=True)
        slay(game, put(game, a, BUZZING_VERMIN))
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 4)

    def test_combat_death_improves_and_persists(self):
        game = make_game(seed=64)
        a, b = game.heroes
        # 死者在 Vinespeaker 之前（攻序左→右）且会被对手 2 攻反杀
        put(game, a, BUZZING_VERMIN)
        put(game, a, VINESPEAKER)
        summon_plain(game, b, make_minion("ENEMY", 2, 2))
        game.run_combat(a, b, alive_count=2)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 2)  # 战斗内也计
        # 跨战斗持久（hero 级 tag 不随棋盘快照回滚）——精确值: 第二次
        # 战斗再 +2（旧版 `>= 2` 在"完全不累计"时也会通过，零验证）
        game.run_combat(a, b, alive_count=2)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 4)


class TestRylakMetalhead(unittest.TestCase):
    """BG26_801 — 亡语: 触发一个相邻随从的战吼（金色复数）。"""

    def test_deathrattle_triggers_adjacent_battlecry(self):
        game = make_game(seed=71)
        a, _b = game.heroes
        rylak = put(game, a, RYLAK)             # 板位 0
        bc = probe_battlecry(game, a, "BC")     # 唯一相邻（确定性）
        plain = summon_plain(game, a, make_minion("PLAIN", 1, 1))
        slay(game, rylak)
        self.assertEqual(bc.atk, 1 + 1)         # 正效果: 相邻战吼触发
        self.assertEqual(plain.atk, 1)          # 无战吼的友方不受影响

    def test_base_triggers_exactly_one_random_adjacent(self):
        game = make_game(seed=72)
        a, _b = game.heroes
        left = probe_battlecry(game, a, "L")
        rylak = put(game, a, RYLAK)
        right = probe_battlecry(game, a, "R")
        slay(game, rylak)
        gains = (left.atk - 1) + (right.atk - 1)
        self.assertEqual(gains, 1)              # 单数 "an adjacent minion"
        self.assertEqual(len(decisions(game, "rylak_adjacent")), 1)

    def test_no_adjacent_fizzles_then_positive(self):
        game = make_game(seed=73)
        a, _b = game.heroes
        rylak = put(game, a, RYLAK)
        slay(game, rylak)                       # 无相邻 → 落空不崩
        self.assertEqual(len(decisions(game, "rylak_adjacent")), 0)
        rylak2 = put(game, a, RYLAK)
        bc = probe_battlecry(game, a, "BC")
        slay(game, rylak2)
        self.assertEqual(bc.atk, 2)             # 正对照

    def test_golden_triggers_both_adjacent(self):
        game = make_game(seed=74)
        a, _b = game.heroes
        left = probe_battlecry(game, a, "L")
        rylak = put(game, a, RYLAK, golden=True)
        right = probe_battlecry(game, a, "R")
        slay(game, rylak)
        self.assertEqual(left.atk, 2)
        self.assertEqual(right.atk, 2)

    def test_titus_doubles_trigger(self):
        game = make_game(seed=75)
        a, _b = game.heroes
        rylak = put(game, a, RYLAK)             # 板位 0
        bc = probe_battlecry(game, a, "BC")     # 唯一相邻（确定性）
        probe_doubler(game, a)                  # 亡语翻倍光环
        slay(game, rylak)
        self.assertEqual(bc.atk, 1 + 2)         # 亡语翻倍 → 战吼 2 次

    def test_triggered_while_alive_uses_real_neighbors(self):
        """"Trigger a Deathrattle" 路径: 本体存活 → 实际板位 ±1。"""
        game = make_game(seed=77)
        a, _b = game.heroes
        left = probe_battlecry(game, a, "L")
        rylak = put(game, a, RYLAK)
        right = probe_battlecry(game, a, "R")
        game.trigger_deathrattle(rylak, hero=a)     # 存活触发（position 缺省 0）
        gains = (left.atk - 1) + (right.atk - 1)
        self.assertEqual(gains, 1)                  # 仍是"单数随机一只"
        self.assertEqual(len(decisions(game, "rylak_adjacent")), 1)

    def test_owner_isolation(self):
        game = make_game(seed=76)
        a, b = game.heroes
        mine = probe_battlecry(game, a, "MINE")
        rylak = put(game, a, RYLAK)
        theirs = probe_battlecry(game, b, "THEIRS")
        slay(game, rylak)
        self.assertEqual(mine.atk, 2)           # 己方相邻触发
        self.assertEqual(theirs.atk, 1)         # 敌方不受影响


class TestTideRaiser(unittest.TestCase):
    """BG34_920 — 亡语: 对一个相邻随从施放 Shifting Tide（金色复数）。"""

    def test_deathrattle_casts_shifting_tide_on_adjacent(self):
        game = make_game(seed=81)
        a, _b = game.heroes
        raiser = put(game, a, TIDE_RAISER)
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        pool_before = game.spell_pool.available(SHIFTING_TIDE)
        slay(game, raiser)
        self.assertEqual(ally.atk, 2 + 2)       # 非纳迦: 2×(1/1)
        self.assertEqual(ally.max_health, 2 + 2)
        self.assertEqual(game.spell_pool.available(SHIFTING_TIDE),
                         pool_before)           # 效果施法不动法术池

    def test_naga_target_repeats(self):
        game = make_game(seed=82)
        a, _b = game.heroes
        raiser = put(game, a, TIDE_RAISER)
        naga = summon_plain(game, a, make_minion(
            "NAGA", 2, 2, race=Race.NAGA))
        slay(game, raiser)
        self.assertEqual(naga.atk, 2 + 4)       # 纳迦: "repeat this" → 4×
        self.assertEqual(naga.max_health, 2 + 4)

    def test_no_adjacent_fizzles_then_positive(self):
        game = make_game(seed=83)
        a, _b = game.heroes
        raiser = put(game, a, TIDE_RAISER)
        slay(game, raiser)                      # 无相邻落空
        self.assertEqual(len(decisions(game, "tide_raiser_adjacent")), 0)
        raiser2 = put(game, a, TIDE_RAISER)
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        slay(game, raiser2)
        self.assertEqual(ally.atk, 4)           # 正对照

    def test_golden_casts_on_both_adjacents(self):
        game = make_game(seed=84)
        a, _b = game.heroes
        left = summon_plain(game, a, make_minion("L", 2, 2))
        raiser = put(game, a, TIDE_RAISER, golden=True)
        right = summon_plain(game, a, make_minion("R", 2, 2))
        slay(game, raiser)
        self.assertEqual(left.atk, 4)
        self.assertEqual(right.atk, 4)

    def test_triggered_while_alive_uses_real_neighbors(self):
        """"Trigger a Deathrattle" 路径: 本体存活 → 施放给实际相邻。"""
        game = make_game(seed=86)
        a, _b = game.heroes
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        raiser = put(game, a, TIDE_RAISER)
        game.trigger_deathrattle(raiser, hero=a)    # 存活触发（缺省 position 0）
        self.assertEqual(ally.atk, 2 + 2)

    def test_owner_isolation(self):
        game = make_game(seed=85)
        a, b = game.heroes
        raiser = put(game, a, TIDE_RAISER)
        mine = summon_plain(game, a, make_minion("MINE", 2, 2))
        theirs = summon_plain(game, b, make_minion("THEIRS", 2, 2))
        slay(game, raiser)
        self.assertEqual(mine.atk, 4)           # 己方相邻
        self.assertEqual(theirs.atk, 2)         # 敌方不受影响


class TestMonstrousMacaw(unittest.TestCase):
    """BGS_078 — Rally: 触发最左友方亡语（排除自身; 金色两次）。"""

    def _attack(self, game, attacker, defender):
        CombatScheduler(game, attacker.controller,
                        defender.controller)._execute_attack(attacker,
                                                             defender)

    def test_rally_triggers_leftmost_deathrattle_only(self):
        game = make_game(seed=91)
        a, b = game.heroes
        enemy = summon_plain(game, b, make_minion("ENEMY", 0, 20))
        dr_left = probe_deathrattle(game, a, "DR_L")
        macaw = put(game, a, MACAW)             # 左起第 2 位
        dr_right = probe_deathrattle(game, a, "DR_R")
        self._attack(game, macaw, enemy)
        self.assertEqual(dr_left.atk, 1 + 1)    # 最左亡语被触发（正效果）
        self.assertEqual(dr_right.atk, 1)       # 非最左不触发

    def test_no_deathrattle_fizzles_then_positive(self):
        game = make_game(seed=92)
        a, b = game.heroes
        enemy = summon_plain(game, b, make_minion("ENEMY", 0, 20))
        macaw = put(game, a, MACAW)
        self._attack(game, macaw, enemy)        # 无亡语 → 落空
        self.assertEqual(macaw.atk, 5)
        dr = probe_deathrattle(game, a, "DR")   # 正对照
        self._attack(game, macaw, enemy)
        self.assertEqual(dr.atk, 2)

    def test_golden_triggers_twice(self):
        game = make_game(seed=93)
        a, b = game.heroes
        enemy = summon_plain(game, b, make_minion("ENEMY", 0, 20))
        dr = probe_deathrattle(game, a, "DR")
        macaw = put(game, a, MACAW, golden=True)
        self._attack(game, macaw, enemy)
        self.assertEqual(dr.atk, 1 + 2)

    def test_titus_doubles_triggered_deathrattle(self):
        game = make_game(seed=94)
        a, b = game.heroes
        enemy = summon_plain(game, b, make_minion("ENEMY", 0, 20))
        put(game, a, TITUS)
        dr = probe_deathrattle(game, a, "DR")
        macaw = put(game, a, MACAW)
        self._attack(game, macaw, enemy)
        self.assertEqual(dr.atk, 1 + 2)         # 统一入口 → Titus 生效

    def test_owner_isolation(self):
        game = make_game(seed=95)
        a, b = game.heroes
        enemy = summon_plain(game, b, make_minion("ENEMY", 0, 20))
        mine = probe_deathrattle(game, a, "MINE")
        theirs = probe_deathrattle(game, b, "THEIRS")
        macaw = put(game, a, MACAW)
        self._attack(game, macaw, enemy)
        self.assertEqual(mine.atk, 2)           # 己方最左亡语
        self.assertEqual(theirs.atk, 1)         # 敌方亡语不触发


class TestSelflessHero(unittest.TestCase):
    """BG_OG_221 — 亡语: 随机友方获得圣盾（金色 2 只）。"""

    def test_deathrattle_grants_divine_shield(self):
        game = make_game(seed=101)
        a, _b = game.heroes
        hero = put(game, a, SELFLESS_HERO)
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        self.assertFalse(ally.has(GameTag.DIVINE_SHIELD))   # 死亡前无
        slay(game, hero)
        self.assertTrue(ally.has(GameTag.DIVINE_SHIELD))    # 正效果

    def test_no_friendly_ally_fizzles_then_positive(self):
        game = make_game(seed=102)
        a, _b = game.heroes
        hero = put(game, a, SELFLESS_HERO)
        slay(game, hero)                        # 落空不崩
        self.assertEqual(
            len(decisions(game, "selfless_hero_targets")), 0)
        hero2 = put(game, a, SELFLESS_HERO)     # 正对照
        ally = summon_plain(game, a, make_minion("ALLY", 2, 2))
        slay(game, hero2)
        self.assertTrue(ally.has(GameTag.DIVINE_SHIELD))

    def test_golden_grants_two_distinct_allies(self):
        game = make_game(seed=103)
        a, _b = game.heroes
        hero = put(game, a, SELFLESS_HERO, golden=True)
        a1 = summon_plain(game, a, make_minion("A1", 2, 2))
        a2 = summon_plain(game, a, make_minion("A2", 2, 2))
        slay(game, hero)
        self.assertTrue(a1.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(a2.has(GameTag.DIVINE_SHIELD))
        picks = decisions(game, "selfless_hero_targets")
        self.assertEqual(len(picks), 1)         # 单次互异采样 2 只

    def test_titus_triggers_again(self):
        game = make_game(seed=104)
        a, _b = game.heroes
        probe_doubler(game, a)
        hero = put(game, a, SELFLESS_HERO)
        summon_plain(game, a, make_minion("ALLY", 2, 2))
        slay(game, hero)
        picks = decisions(game, "selfless_hero_targets")
        self.assertEqual(len(picks), 2)         # 亡语触发 2 次

    def test_owner_isolation(self):
        game = make_game(seed=105)
        a, b = game.heroes
        hero = put(game, a, SELFLESS_HERO)
        mine = summon_plain(game, a, make_minion("MINE", 2, 2))
        theirs = summon_plain(game, b, make_minion("THEIRS", 2, 2))
        slay(game, hero)
        self.assertTrue(mine.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(theirs.has(GameTag.DIVINE_SHIELD))


class TestNalaaTheRedeemer(unittest.TestCase):
    """BG28_551 — 每当施放酒馆法术: 每类型一个随机友方 +{0}/+{1}。"""

    def test_tavern_spell_buffs_one_minion_of_each_type(self):
        game = make_game(seed=111)
        a, _b = game.heroes
        put(game, a, NALAA)
        d = get_db().get(NALAA)
        beast = summon_plain(game, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        mech = summon_plain(game, a, make_minion(
            "MECH", 1, 1, race=Race.MECH))
        none = summon_plain(game, a, make_minion("NONE", 1, 1))
        self.assertTrue(play_pool_spell(game, a, ARMOR_STASH))
        self.assertEqual(beast.atk, 1 + d.num(0))       # 正效果
        self.assertEqual(beast.max_health, 1 + d.num(1))
        self.assertEqual(mech.atk, 1 + d.num(0))
        self.assertEqual(none.atk, 1)                   # 无类型不被选中
        self.assertEqual(none.max_health, 1)

    def test_owner_isolation(self):
        game = make_game(seed=112)
        a, b = game.heroes
        put(game, a, NALAA)
        beast = summon_plain(game, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        self.assertTrue(play_pool_spell(game, b, ARMOR_STASH))
        self.assertEqual(beast.atk, 1)                  # 对手施放不触发
        self.assertTrue(play_pool_spell(game, a, ARMOR_STASH))  # 正对照
        self.assertEqual(beast.atk, 1 + get_db().get(NALAA).num(0))

    def test_non_tavern_spell_does_not_trigger(self):
        game = make_game(seed=113)
        a, _b = game.heroes
        put(game, a, NALAA)
        beast = summon_plain(game, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        self.assertTrue(play_pool_spell(game, a, ARMOR_STASH))
        n_tavern = len(decisions(game, "nalaa_target"))
        self.assertGreater(n_tavern, 0)                 # 酒馆法术触发
        # 血宝石（非池法术）不广播 tavern_spell_cast → 不再触发
        self.assertFalse(game.spell_pool.acquire(BLOOD_GEM))  # 非池法术不可预约
        s = game.create_spell(BLOOD_GEM, controller=a)
        a.hand.append(s)
        s.zone = Zone.HAND
        self.assertTrue(game.play_spell(a, s, target=beast))
        self.assertEqual(len(decisions(game, "nalaa_target")), n_tavern)

    def test_golden_nums_eight_six(self):
        game = make_game(seed=114)
        a, _b = game.heroes
        put(game, a, NALAA, golden=True)
        d = get_db().get(NALAA_G)
        beast = summon_plain(game, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        self.assertTrue(play_pool_spell(game, a, ARMOR_STASH))
        self.assertEqual(beast.atk, 1 + d.num(0))
        self.assertEqual(beast.max_health, 1 + d.num(1))

    def test_all_type_minion_can_be_picked_per_race(self):
        game = make_game(seed=115)
        a, _b = game.heroes
        put(game, a, NALAA)
        amalgam = summon_plain(game, a, make_minion(
            "AMALGAM", 1, 1, race=Race.ALL))
        self.assertTrue(play_pool_spell(game, a, ARMOR_STASH))
        d = get_db().get(NALAA)
        picks = decisions(game, "nalaa_target")
        self.assertEqual(len(picks), 10)        # 10 标准种族各一次
        self.assertEqual(amalgam.atk, 1 + 10 * d.num(0))

    def test_same_seed_determinism(self):
        results = []
        for _ in range(2):
            game = make_game(seed=116)
            a, _b = game.heroes
            put(game, a, NALAA)
            beasts = [summon_plain(game, a, make_minion(n, 1, 1,
                                                        race=Race.BEAST))
                      for n in ("B1", "B2")]
            mech = summon_plain(game, a, make_minion(
                "M1", 1, 1, race=Race.MECH))
            self.assertTrue(play_pool_spell(game, a, ARMOR_STASH))
            # 确定性: 各随从的最终增量（与 uuid 无关）
            results.append(sorted((m.atk for m in beasts + [mech])))
        self.assertEqual(results[0], results[1])
        d = get_db().get(NALAA)
        self.assertEqual(results[0], sorted([1, 1 + d.num(0), 1 + d.num(0)]))


class TestBristlebach(unittest.TestCase):
    """BG26_157 — Avenge(2): 对所有 Quilboar 施放 2 颗血宝石（金色 4）。"""

    def test_avenge_counts_only_in_combat(self):
        game = make_game(seed=121)
        a, _b = game.heroes
        br = put(game, a, BRISTLEBACH)
        quil = summon_plain(game, a, make_minion(
            "QUIL", 1, 1, race=Race.QUILBOAR))
        # 招募期: 2 次友方死亡不计数
        hit_kill(game, summon_plain(game, a, make_minion("S1", 1, 1)),
                 in_combat=False)
        hit_kill(game, summon_plain(game, a, make_minion("S2", 1, 1)),
                 in_combat=False)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        # 战斗内: 第 1 次不达标、第 2 次达标触发（正效果）
        hit_kill(game, summon_plain(game, a, make_minion("S3", 1, 1)),
                 in_combat=True)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        hit_kill(game, summon_plain(game, a, make_minion("S4", 1, 1)),
                 in_combat=True)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 2)
        self.assertEqual(quil.atk, 1 + 2)       # 2 颗 vanilla 宝石
        self.assertEqual(quil.max_health, 1 + 2)

    def test_avenge_skips_non_quilboar_and_enemy(self):
        game = make_game(seed=122)
        a, b = game.heroes
        put(game, a, BRISTLEBACH)
        quil = summon_plain(game, a, make_minion(
            "QUIL", 1, 1, race=Race.QUILBOAR))
        beast = summon_plain(game, a, make_minion(
            "BEAST", 1, 1, race=Race.BEAST))
        enemy_quil = summon_plain(game, b, make_minion(
            "EQUIL", 1, 1, race=Race.QUILBOAR))
        hit_kill(game, summon_plain(game, a, make_minion("S1", 1, 1)),
                 in_combat=True)
        hit_kill(game, summon_plain(game, a, make_minion("S2", 1, 1)),
                 in_combat=True)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 2)
        self.assertEqual(beast.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        self.assertEqual(enemy_quil.get(GameTag.GEMS_PLAYED_ON, 0), 0)

    def test_golden_plays_four_gems(self):
        game = make_game(seed=123)
        a, _b = game.heroes
        put(game, a, BRISTLEBACH, golden=True)
        quil = summon_plain(game, a, make_minion(
            "QUIL", 1, 1, race=Race.QUILBOAR))
        for i in range(2):
            hit_kill(game, summon_plain(
                game, a, make_minion(f"S{i}", 1, 1)), in_combat=True)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 4)
        self.assertEqual(quil.atk, 1 + 4)

    def test_counter_resets_between_combats(self):
        game = make_game(seed=124)
        a, _b = game.heroes
        br = put(game, a, BRISTLEBACH)
        quil = summon_plain(game, a, make_minion(
            "QUIL", 1, 1, race=Race.QUILBOAR))
        # 第 1 场: 1 次死亡（不达标）→ 未触发
        hit_kill(game, summon_plain(game, a, make_minion("S0", 1, 1)),
                 in_combat=True)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        # 新一场开始: 计数清零（Avenge 不跨战斗累积）
        br.reset_for_combat()
        hit_kill(game, summon_plain(game, a, make_minion("S1", 1, 1)),
                 in_combat=True)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 0)
        # 正对照: 本场第 2 次死亡 → 达标触发
        hit_kill(game, summon_plain(game, a, make_minion("S2", 1, 1)),
                 in_combat=True)
        self.assertEqual(quil.get(GameTag.GEMS_PLAYED_ON, 0), 2)


class TestLightfangEnforcer(unittest.TestCase):
    """BGS_009 — EoT: 每类型一个随机友方 +4/+4（金色 +8/+8）。"""

    def test_end_of_turn_buffs_one_per_type(self):
        game = make_game(seed=131)
        a, _b = game.heroes
        lf = put(game, a, LIGHTFANG)
        b1 = summon_plain(game, a, make_minion(
            "B1", 1, 1, race=Race.BEAST))
        b2 = summon_plain(game, a, make_minion(
            "B2", 1, 1, race=Race.BEAST))
        mech = summon_plain(game, a, make_minion(
            "M1", 1, 1, race=Race.MECH))
        none = summon_plain(game, a, make_minion("N", 1, 1))
        game.run_script_hook(lf, "end_of_turn")
        self.assertEqual(mech.atk, 1 + 4)       # 正效果
        self.assertEqual(mech.max_health, 1 + 4)
        self.assertEqual((b1.atk - 1) + (b2.atk - 1), 4)  # 同族只 buff 一只
        self.assertEqual(none.atk, 1)           # 无类型不被选中
        self.assertEqual(lf.atk, 8)             # 自身无类型

    def test_repeated_end_of_turn_accumulates(self):
        game = make_game(seed=132)
        a, _b = game.heroes
        lf = put(game, a, LIGHTFANG)
        mech = summon_plain(game, a, make_minion(
            "M", 1, 1, race=Race.MECH))
        game.run_script_hook(lf, "end_of_turn")
        game.run_script_hook(lf, "end_of_turn")     # 每回合 EoT
        self.assertEqual(mech.atk, 1 + 8)
        self.assertEqual(mech.max_health, 1 + 8)

    def test_golden_eight_eight(self):
        game = make_game(seed=133)
        a, _b = game.heroes
        lf = put(game, a, LIGHTFANG, golden=True)
        mech = summon_plain(game, a, make_minion(
            "M", 1, 1, race=Race.MECH))
        game.run_script_hook(lf, "end_of_turn")
        self.assertEqual(mech.atk, 1 + 8)
        self.assertEqual(mech.max_health, 1 + 8)

    def test_owner_isolation(self):
        game = make_game(seed=134)
        a, b = game.heroes
        lf = put(game, a, LIGHTFANG)
        mine = summon_plain(game, a, make_minion(
            "MINE", 1, 1, race=Race.MECH))
        theirs = summon_plain(game, b, make_minion(
            "THEIRS", 1, 1, race=Race.MECH))
        game.run_script_hook(lf, "end_of_turn")
        self.assertEqual(mine.atk, 5)
        self.assertEqual(theirs.atk, 1)         # 对手不受影响

    def test_real_end_recruit_phase_applies_buff(self):
        game = make_game(seed=135)
        a, _b = game.heroes
        put(game, a, LIGHTFANG)
        mech = summon_plain(game, a, make_minion(
            "M", 1, 1, race=Race.MECH))
        game.end_recruit_phase()                # 真实 EoT → 战斗 → 下回合
        self.assertEqual(mech.atk, 1 + 4)       # 招募期 buff 跨战斗保留
        self.assertEqual(mech.max_health, 1 + 4)

    def test_same_seed_determinism(self):
        chosen = []
        for _ in range(2):
            game = make_game(seed=136)
            a, _b = game.heroes
            lf = put(game, a, LIGHTFANG)
            beasts = [summon_plain(game, a, make_minion(n, 1, 1,
                                                        race=Race.BEAST))
                      for n in ("B1", "B2")]
            game.run_script_hook(lf, "end_of_turn")
            # 确定性: 同族两只中恰好一只获 +4/+4（与 uuid 无关）
            chosen.append(sorted(m.atk for m in beasts))
        self.assertEqual(chosen[0], chosen[1])
        self.assertEqual(chosen[0], [1, 1 + 4])


if __name__ == "__main__":
    unittest.main()


# ══════════════════ BG29_873 / BG29_877 Felblood（2026-09-19 注册） ══════

SLIMY_FELBLOOD = "BG29_873"
SLIMY_FELBLOOD_G = "BG29_873_G"
FIERY_FELBLOOD = "BG29_877"
FIERY_FELBLOOD_G = "BG29_877_G"


class TestFelbloodPayloads(unittest.TestCase):
    """Felblood 载荷本体（869 Felblood Portrait 交付/改写的行为）。

    无饰品时：Slimy 战吼只给酒馆 +2 血 / Fiery 亡语只给酒馆 +2 攻
    （"this game" = 持久面，当前 + 未来入馆随从都获得）。
    """

    def _play(self, game, hero, card_id, golden=False):
        m = to_hand(game, hero, card_id, golden=golden)
        assert game.play_minion(hero, m)
        return m

    def _tavern(self, game, hero):
        m = game.create_minion(DEEP_SEA_ANGLER, controller=hero)
        assert game.add_tavern_entity(hero, m)
        return m

    def test_registered(self):
        for cid in (SLIMY_FELBLOOD, SLIMY_FELBLOOD_G,
                    FIERY_FELBLOOD, FIERY_FELBLOOD_G):
            self.assertIn(cid, REGISTRY, cid)

    def test_slimy_battlecry_buffs_current_and_future_tavern(self):
        g = make_game(seed=8731)
        a, b = g.heroes
        cur = self._tavern(g, a)
        foe = self._tavern(g, b)
        self._play(g, a, SLIMY_FELBLOOD)
        self.assertEqual((cur.atk, cur.max_health), (2, 5))    # +2 health
        self.assertEqual((foe.atk, foe.max_health), (2, 3))    # owner 隔离
        fut = self._tavern(g, a)                                # 未来入馆
        self.assertEqual((fut.atk, fut.max_health), (2, 5))

    def test_slimy_golden_four_health(self):
        g = make_game(seed=8732)
        a = g.heroes[0]
        cur = self._tavern(g, a)
        self._play(g, a, SLIMY_FELBLOOD, golden=True)
        self.assertEqual((cur.atk, cur.max_health), (2, 7))    # +4 health

    def test_fiery_deathrattle_buffs_tavern_attack(self):
        g = make_game(seed=8733)
        a, b = g.heroes
        cur = self._tavern(g, a)
        foe = self._tavern(g, b)
        f = put(g, a, FIERY_FELBLOOD)
        slay(g, f)
        self.assertEqual((cur.atk, cur.max_health), (4, 3))    # +2 attack
        self.assertEqual((foe.atk, foe.max_health), (2, 3))
        fut = self._tavern(g, a)
        self.assertEqual((fut.atk, fut.max_health), (4, 3))

    def test_fiery_golden_four_attack(self):
        g = make_game(seed=8734)
        a = g.heroes[0]
        cur = self._tavern(g, a)
        f = put(g, a, FIERY_FELBLOOD, golden=True)
        slay(g, f)
        self.assertEqual((cur.atk, cur.max_health), (6, 3))    # +4 attack
