"""磁力批次语义测试（作业单 2026-08-21，8 张磁力/机械池随从 + 金色）。

覆盖 batch_magnetic.py 全部注册卡: BG26_146 Lullabot / BG26_147
Accord-o-Tron / BG26_149 Polarizing Beatboxer / BG29_503 Clunker Junker /
BG31_177 Mechagnome Interpreter / BG32_172 Auto Assembler /
BG36_851 Spark Snapper（DEFERRED）/ BG36_853 Glambot（DEFERRED）。

磁力吸附路径统一 game.play_minion(hero, mag, magnetic_target=host)
驱动（作业单要求）; EoT/SoT 合并效果经 game.run_script_hook(host,
"end_of_turn"/"start_of_turn") 驱动（引擎 _end_of_turn_for/
_begin_recruit_for 对棋盘随从的同款调用）。数值断言一律从 CardDef
num()/atk/health 计算; 无模板参数的卡用文本字面量并注明。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 数据缺口自举（同 batch_deathrattle Handless Forsaken REBORN 先例）:
# bg_cards.json 金色条目不导出 keywords（magnetic/deathrattle 标志缺失，
# batch_magnetic 模块 docstring G3）——金色磁力随从走 play_minion 吸附
# 路径前手工置 MAGNETIC tag
def bootstrap_golden_magnetic(m: Minion) -> Minion:
    if m.is_golden and not m.has(GameTag.MAGNETIC):
        m.set(GameTag.MAGNETIC, True)
    return m

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_hero(name: str = "Hero") -> Hero:
    return Hero(f"TEST_HERO_{name}", name)


def make_game(seed: int = 42, heroes: list | None = None) -> Game:
    if heroes is None:
        heroes = [make_hero("A"), make_hero("B")]
    return Game(heroes, get_db(), seed=seed)


def put(game: Game, card_id: str, hero: Hero, position: int | None = None,
        golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m, position)
    return m


def to_hand(game: Game, card_id: str, hero: Hero, golden: bool = False,
            controller: Hero | None = None) -> Minion:
    m = game.create_minion(card_id, controller=controller or hero,
                           golden=golden)
    hero.hand.append(m)
    return m


def kill(game: Game, m: Minion) -> None:
    m.take_damage(999)
    game.check_deaths()


def mech_host(game: Game, hero: Hero) -> Minion:
    """通用机械宿主: 测试实体 Mech（BG_TTN_401 已有动态属性脚本——
    3/3 token 相邻计数会叠加，不再惰性）。"""
    m = Minion("TEST_MECH_HOST", "Host", atk=3, health=4, race=Race.MECH)
    game.summon(hero, m)
    return m


class TestRegistry(unittest.TestCase):
    def test_all_16_ids_registered(self):
        for cid in ("BG26_146", "BG26_146_G", "BG26_147", "BG26_147_G",
                    "BG26_149", "BG26_149_G", "BG29_503", "BG29_503_G",
                    "BG31_177", "BG31_177_G", "BG32_172", "BG32_172_G",
                    "BG36_851", "BG36_851_G", "BG36_853", "BG36_853_G"):
            self.assertIn(cid, REGISTRY)


class TestLullabotBG26_146(unittest.TestCase):
    """BG26_146 — Magnetic + EoT gain +1 Health（金色 +2）。"""

    def test_magnetic_attach_then_eot_buff(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        host = mech_host(game, a)
        d = get_db().get("BG26_146")
        base_atk, base_hp = host.atk, host.max_health
        mag = to_hand(game, "BG26_146", a)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        # 吸附并入: 攻/血 += def 2/2
        self.assertEqual(host.atk, base_atk + d.atk)
        self.assertEqual(host.max_health, base_hp + d.health)
        self.assertEqual(host.health, base_hp + d.health)
        # 宿主 EoT → 合并触发 Lullabot EoT（+1 文本字面量）
        game.run_script_hook(host, "end_of_turn")
        self.assertEqual(host.atk, base_atk + d.atk)
        self.assertEqual(host.max_health, base_hp + d.health + 1)
        self.assertEqual(host.health, base_hp + d.health + 1)

    def test_normal_play_path_buffs_self(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        bot = put(game, "BG26_146", a)
        game.run_script_hook(bot, "end_of_turn")
        d = get_db().get("BG26_146")
        self.assertEqual(bot.max_health, d.health + 1)

    def test_golden_attach_eot_plus2(self):
        game = make_game(seed=1)
        a = game.heroes[0]
        host = mech_host(game, a)
        base_hp = host.max_health
        gd = get_db().get("BG26_146_G")
        mag = bootstrap_golden_magnetic(to_hand(game, "BG26_146", a, golden=True))
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        self.assertEqual(host.max_health, base_hp + gd.health)
        game.run_script_hook(host, "end_of_turn")
        self.assertEqual(host.max_health, base_hp + gd.health + 2)  # 金色 "+2"


class TestAccordOTronBG26_147(unittest.TestCase):
    """BG26_147 — Magnetic + SoT gain 1 Gold（金色 2）。"""

    def test_magnetic_attach_then_sot_gold(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        host = mech_host(game, a)
        a.gold = 10
        mag = to_hand(game, "BG26_147", a)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        game.run_script_hook(host, "start_of_turn")
        self.assertEqual(a.gold, 11)   # "gain 1 Gold" 文本字面量

    def test_normal_play_path_sot_gold(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        bot = put(game, "BG26_147", a)
        a.gold = 10
        game.run_script_hook(bot, "start_of_turn")
        self.assertEqual(a.gold, 11)

    def test_golden_attach_sot_plus2_gold(self):
        game = make_game(seed=2)
        a = game.heroes[0]
        host = mech_host(game, a)
        a.gold = 10
        mag = bootstrap_golden_magnetic(to_hand(game, "BG26_147", a, golden=True))
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        game.run_script_hook(host, "start_of_turn")
        self.assertEqual(a.gold, 12)   # 金色 "gain 2 Gold"


class TestPolarizingBeatboxerBG26_149(unittest.TestCase):
    """BG26_149 — Whenever you Magnetize to a different minion, it also
    Magnetizes to this（金色 twice）。"""

    def test_magnetize_to_other_copies_to_beatboxer(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        bb = put(game, "BG26_149", a)
        host = mech_host(game, a)
        d = get_db().get("BG26_146")
        bb_atk, bb_hp = bb.atk, bb.max_health
        pool_before = game.minion_pool.available("BG26_146")
        mag = to_hand(game, "BG26_146", a)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        # 副本并入 Beatboxer: +BG26_146 def 2/2
        self.assertEqual(bb.atk, bb_atk + d.atk)
        self.assertEqual(bb.max_health, bb_hp + d.health)
        # 副本为生成语义: 不占池
        self.assertEqual(game.minion_pool.available("BG26_146"), pool_before)
        # 吸附的 Lullabot 副本 EoT 合并在 Beatboxer 上生效
        game.run_script_hook(bb, "end_of_turn")
        self.assertEqual(bb.max_health, bb_hp + d.health + 1)

    def test_magnetize_to_beatboxer_itself_no_extra_copy(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        bb = put(game, "BG26_149", a)
        d = get_db().get("BG26_146")
        bb_atk, bb_hp = bb.atk, bb.max_health
        mag = to_hand(game, "BG26_146", a)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=bb))
        self.assertEqual(bb.atk, bb_atk + d.atk)          # 仅本体并入
        self.assertEqual(bb.max_health, bb_hp + d.health)

    def test_enemy_magnetize_does_not_trigger(self):
        game = make_game(seed=3)
        a, b = game.heroes
        bb = put(game, "BG26_149", a)
        host_b = mech_host(game, b)
        bb_atk, bb_hp = bb.atk, bb.max_health
        mag = to_hand(game, "BG26_146", b, controller=b)
        self.assertTrue(game.play_minion(b, mag, magnetic_target=host_b))
        self.assertEqual(bb.atk, bb_atk)                  # "you" 过滤
        self.assertEqual(bb.max_health, bb_hp)

    def test_golden_copies_twice(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        bb = put(game, "BG26_149", a, golden=True)
        host = mech_host(game, a)
        d = get_db().get("BG26_146")
        bb_atk, bb_hp = bb.atk, bb.max_health
        mag = to_hand(game, "BG26_146", a)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        self.assertEqual(bb.atk, bb_atk + 2 * d.atk)      # 两个副本
        self.assertEqual(bb.max_health, bb_hp + 2 * d.health)

    def test_golden_magnetic_copy_is_golden(self):
        game = make_game(seed=3)
        a = game.heroes[0]
        bb = put(game, "BG26_149", a)
        host = mech_host(game, a)
        gd = get_db().get("BG26_146_G")
        bb_atk, bb_hp = bb.atk, bb.max_health
        mag = bootstrap_golden_magnetic(to_hand(game, "BG26_146", a, golden=True))
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        # 金色附件 → 金色副本（金色卡定义属性并入）
        self.assertEqual(bb.atk, bb_atk + gd.atk)
        self.assertEqual(bb.max_health, bb_hp + gd.health)
        game.run_script_hook(bb, "end_of_turn")
        self.assertEqual(bb.max_health, bb_hp + gd.health + 2)  # 金色 EoT +2


class TestClunkerJunkerBG29_503(unittest.TestCase):
    """BG29_503 — BC: Choose a friendly Mech. Discover a Mech to
    Magnetize to it（金色 Discover 2 Mechs）。"""

    def test_discover_magnetic_mech_and_attach(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        a.set(GameTag.TAVERN_TIER, 6)
        host = mech_host(game, a)
        base_atk, base_hp = host.atk, host.max_health
        cj = to_hand(game, "BG29_503", a)
        self.assertTrue(game.play_minion(a, cj, target=host))
        pcs = [pc for pc in game.pending_choices
               if pc.kind == "discover_minion"]
        self.assertEqual(len(pcs), 1)
        pc = pcs[0]
        self.assertLessEqual(len(pc.options), 3)   # RULES §6.18 三选一
        for oid in pc.options:                      # 选项全为 Magnetic Mech
            od = get_db().get(oid)
            self.assertIn("magnetic", od.keywords)
            self.assertIn(od.race, (Race.MECH, Race.ALL))
        pick = pc.options[0]
        pd_ = get_db().get(pick)
        avail_before = game.minion_pool.available(pick)
        pc.choose(0)
        # 选中卡吸附到目标1: 属性并入 + 池占用 -1
        self.assertEqual(host.atk, base_atk + pd_.atk)
        self.assertEqual(host.max_health, base_hp + pd_.health)
        self.assertEqual(game.minion_pool.available(pick), avail_before - 1)
        game.pending_choices.remove(pc)

    def test_golden_discovers_two_mechs(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        host = mech_host(game, a)
        base_atk = host.atk
        cj = to_hand(game, "BG29_503", a, golden=True)
        self.assertTrue(game.play_minion(a, cj, target=host))
        pcs = [pc for pc in game.pending_choices
               if pc.kind == "discover_minion"]
        self.assertEqual(len(pcs), 2)               # 引擎金色战吼×2
        attach_atk = 0
        for pc in pcs:
            pd_ = get_db().get(pc.options[0])
            attach_atk += pd_.atk
            pc.choose(0)
            game.pending_choices.remove(pc)
        self.assertEqual(host.atk, base_atk + attach_atk)

    def test_target_candidates_mech_only(self):
        game = make_game(seed=4)
        a = game.heroes[0]
        beast = next(d for d in get_db().pool_minions()
                     if d.race == Race.BEAST)
        put(game, beast.id, a)
        mech = mech_host(game, a)
        cj = put(game, "BG29_503", a)
        cands = cj.scripts.target_candidates(cj, game)
        self.assertIn(mech, cands)
        self.assertNotIn(beast.id, [m.card_id for m in cands])
        self.assertIn(cj, cands)   # 自身入场在战吼前——合法目标


class TestMechagnomeInterpreterBG31_177(unittest.TestCase):
    """BG31_177 — Whenever you play or Magnetize a Mech, give it
    +{0}/+{1}（num 3/1; 金色 6/2）。"""

    def test_play_mech_buffs_it(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        put(game, "BG31_177", a)
        d = get_db().get("BG31_177")
        played = to_hand(game, "BG_TTN_401", a)
        self.assertTrue(game.play_minion(a, played))
        self.assertEqual(played.atk, 3 + d.num(0))
        self.assertEqual(played.max_health, 4 + d.num(1))

    def test_magnetize_path_buffs_host_once(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        put(game, "BG31_177", a)
        d = get_db().get("BG31_177")
        ld = get_db().get("BG26_146")
        host = mech_host(game, a)
        mag = to_hand(game, "BG26_146", a)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        # 吸附 +2/+2，Interpreter buff 恰一份 +3/+1（card_played 分支跳过
        # REMOVED 实体，仅 magnetized 分支生效）
        self.assertEqual(host.atk, 3 + ld.atk + d.num(0))
        self.assertEqual(host.max_health, 4 + ld.health + d.num(1))

    def test_play_non_mech_not_buffed(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        put(game, "BG31_177", a)
        beast = next(d for d in get_db().pool_minions()
                     if d.race == Race.BEAST)
        played = to_hand(game, beast.id, a)
        bd = get_db().get(beast.id)
        self.assertTrue(game.play_minion(a, played))
        self.assertEqual(played.atk, bd.atk)
        self.assertEqual(played.max_health, bd.health)

    def test_playing_interpreter_itself_gets_buff(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        interp = to_hand(game, "BG31_177", a)
        self.assertTrue(game.play_minion(a, interp))
        d = get_db().get("BG31_177")
        self.assertEqual(interp.atk, d.atk + d.num(0))
        self.assertEqual(interp.max_health, d.health + d.num(1))

    def test_golden_nums(self):
        game = make_game(seed=5)
        a = game.heroes[0]
        put(game, "BG31_177", a, golden=True)
        gd = get_db().get("BG31_177_G")
        played = to_hand(game, "BG_TTN_401", a)
        self.assertTrue(game.play_minion(a, played))
        self.assertEqual(played.atk, 3 + gd.num(0))
        self.assertEqual(played.max_health, 4 + gd.num(1))


class TestAutoAssemblerBG32_172(unittest.TestCase):
    """BG32_172 — Magnetic + DR Summon an Ancestral Automaton
    （金色 Golden Ancestral Automaton）。"""

    def test_attach_host_death_summons_token(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        host = mech_host(game, a)
        pos = a.board.index(host)
        mag = to_hand(game, "BG32_172", a)
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        kill(game, host)
        token = a.board[pos]
        td = get_db().get("BG_TTN_401")
        self.assertEqual(token.card_id, "BG_TTN_401")
        self.assertEqual(token.atk, td.atk)
        self.assertEqual(token.max_health, td.health)

    def test_normal_play_death_summons_token(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        asm = put(game, "BG32_172", a)
        kill(game, asm)
        self.assertTrue(any(m.card_id == "BG_TTN_401" for m in a.board))

    def test_golden_summons_golden_automaton(self):
        game = make_game(seed=6)
        a = game.heroes[0]
        host = mech_host(game, a)
        mag = bootstrap_golden_magnetic(to_hand(game, "BG32_172", a, golden=True))
        self.assertTrue(game.play_minion(a, mag, magnetic_target=host))
        kill(game, host)
        token = next(m for m in a.board
                     if m.card_id == "BG_TTN_401_G")
        gd = get_db().get("BG_TTN_401_G")
        self.assertTrue(token.is_golden)
        self.assertEqual(token.atk, gd.atk)
        self.assertEqual(token.max_health, gd.health)


class TestDeferredCards(unittest.TestCase):
    """BG36_851 Spark Snapper / BG36_853 Glambot — 已解冻（2026-08-21，
    引擎 G1 实体属性并入 + G2 card_played target kwarg）: 实现移册
    batch_consume.py（语义测试见 test_batch_consume.py）。此处保留
    最小行为断言。"""

    def test_spark_snapper_now_magnetizes_satellite(self):
        # 解冻后: 打出 Mech → 吸附 num(1)/num(1) Satellite（batch_consume）
        game = make_game(seed=7)
        a = game.heroes[0]
        put(game, "BG36_851", a)
        played = to_hand(game, "BG_TTN_401", a)
        self.assertTrue(game.play_minion(a, played))
        d = get_db().get("BG_TTN_401")
        step = get_db().get("BG36_851").num(1)
        self.assertEqual(played.atk, d.atk + step)
        self.assertEqual(played.max_health, d.health + step)

    def test_glambot_playing_minion_still_noop(self):
        # Glambot 触发条件是"法术施放于 Mech"——打出 Mech 不触发（负例）
        game = make_game(seed=7)
        a = game.heroes[0]
        put(game, "BG36_853", a)
        played = to_hand(game, "BG_TTN_401", a)
        self.assertTrue(game.play_minion(a, played))
        d = get_db().get("BG_TTN_401")
        self.assertEqual(played.atk, d.atk)
        self.assertEqual(played.max_health, d.health)


if __name__ == "__main__":
    unittest.main()
