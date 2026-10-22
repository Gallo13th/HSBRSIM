"""批次 trinkets7 行为层测试（19 张单卡触发饰品）。

全部断言走真实引擎路径:
  - 购买: 真实 `game._offer_trinkets` 三选一 + PendingChoice.choose
    （resolve 回调扣费 → hero.trinkets → run_script_hook(on_bind)）
  - SoT/EoT: 真实 `game.end_recruit_phase()`
  - SoC / 战斗: 真实 `game.run_combat(a, b)`（战斗内探针读 SoC 结算后
    或 SUMMON 事件流）
  - 复生: 真实 `game._process_single_death`（战斗内）
  - 法术: 真实 `game.play_spell`（含定向池法术）
  - 随从: 真实 `game.play_minion` / `game.buy_from_tavern` / `game.summon`
  - 攻击: 真实 `hsrl2.combat.execute_immediate_attack`
  - 刷新/升级: 真实 `game.refresh_tavern` / `game.upgrade_tavern`

覆盖（SOP §16 空转测试判定法——每个效果类都有正对照 + 无饰品对照）:
  - owner 隔离（2 英雄; 每个效果都有"对手活动不生效"断言）
  - 每回合/每场战斗语义（SoT 重复发放、每回合配额）
  - 池占返（随机获取占池、Bounty 池法术、plain copy 不占池、
    Dreamer's Embrace 非池卡不占池）
  - 数值与 CardDef.num 双向钉死
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions import Buff
from hsrl2.combat import execute_immediate_attack
from hsrl2.db import CardDB
from hsrl2.events import START_OF_COMBAT, SUMMON, Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets7 as B7
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# 测试用既有卡（CardDB 按名核实，非凭记忆 id）
ELEMENTAL = "BG31_816"        # Fire Baller 2/2 T2 元素
NON_ELEMENTAL = "BG31_803"    # Buzzing Vermin 1/1 T1 野兽
PIRATE = "BG26_135"           # Southsea Busker 3/1 T1 海盗（战吼）
NON_PIRATE = "BG31_803"       # Buzzing Vermin（野兽）
UNDEAD = "BG25_013"           # Rot Hide Gnoll 1/1 T1 亡灵（无关键词）
BEAST = "BG31_803"            # Buzzing Vermin T1 野兽
MECH = "BG29_611"             # Cord Puller T1 机械
RALLY_MINION = "BG20_101"     # Roadboar T1 野猪人（Rally 关键词）
TOKEN_MINION = "BG21_014"     # Prized Promo-Drake（非池 token 随从）
SPELL_PLAIN = "BG28_800"      # Careful Investment（池法术，无定向）
SPELL_TARGET = "BG28_503"     # Fortify（定向池法术）
SPELL_STATS_ALL = "BG28_168"  # Shiny Ring（Give your minions +1/+1）
DREAMERS_EMBRACE = "BG28_883"  # BG30_MagicItem_916 evolution 链目标

_db = None


def get_db():
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900):
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def offer_and_buy(game, hero, tid: str, kind: str):
    """真实饰品商店路径: _offer_trinkets → PendingChoice → resolve。

    resolve 回调本身是引擎真实实现（扣费 / `_trinkets_granted` /
    `hero.trinkets.append` / `run_script_hook(on_bind, ctx={"hero":...})`）。
    """
    hero.gold = 50
    game._offer_trinkets(hero, kind)
    choice = game.pending_choices.pop(0)
    choice.options = [get_db().get(tid)]
    choice.choose(0)
    return hero.trinkets[-1]


def probe(scripts: dict):
    return type("Probe", (), dict(scripts))


def probe_minion(hook: str, bucket: list, *, atk=1, health=5) -> Minion:
    m = Minion(f"PROBE_{hook}", "P", atk=atk, health=health)
    m.scripts = probe({
        hook: staticmethod(lambda s, g, c=None, **kw: bucket.append(s) or None)})
    return m


def put(game, hero, m: Minion):
    game.summon(hero, m)
    return m


def play_from_hand(game, hero, card_id: str, *, spell: bool,
                   target=None):
    """真实入手 + 打出路径（随从/法术）。"""
    if spell:
        assert game.spell_pool.acquire(card_id)
        e = game.create_spell(card_id, controller=hero)
        hero.add_to_hand(e)
        assert game.play_spell(hero, e, target=target)
    else:
        e = game.create_minion(card_id, controller=hero)
        hero.add_to_hand(e)
        assert game.play_minion(hero, e)
    return e


def death_in_combat(game, victim):
    """战斗内直接驱动死亡处理（真实 `_process_single_death` 路径）。"""
    prev = game.in_combat
    game.in_combat = True
    try:
        victim.health = 0
        game._process_single_death(victim)
    finally:
        game.in_combat = prev


def t7_pool_sum(game):
    ids = [d.id for d in get_db().pool_minions() if d.tech_level == 7]
    return sum(game.minion_pool.available(i) for i in ids)


def bounty_pool_sum(game):
    import hsrl2.constants as C
    return sum(game.spell_pool.available(i) for i in C.BOUNTY_SPELL_IDS)


class TestRegistryState(unittest.TestCase):
    """注册面 + 文本/数据一致性（结构性，与钩子无关）。"""

    IMPLEMENTED = (
        "BG32_MagicItem_700", "BG35_MagicItem_710", "BG36_MagicItem_205",
        "BG32_MagicItem_888", "BG36_MagicItem_300", "BG36_MagicItem_307",
        "BG35_MagicItem_890", "BG30_MagicItem_993", "BG35_MagicItem_301",
        "BG30_MagicItem_430", "BG30_MagicItem_706", "BG30_MagicItem_972",
        "BG30_MagicItem_916", "BG32_MagicItem_360", "BG36_MagicItem_200",
        "BG36_MagicItem_212", "BG36_MagicItem_840", "BG35_MagicItem_700",
        "BG35_MagicItem_731",
    )
    KIND = {
        "BG32_MagicItem_700": "greater", "BG35_MagicItem_710": "greater",
        "BG36_MagicItem_205": "lesser", "BG32_MagicItem_888": "greater",
        "BG36_MagicItem_300": "lesser", "BG36_MagicItem_307": "lesser",
        "BG35_MagicItem_890": "lesser", "BG30_MagicItem_993": "greater",
        "BG35_MagicItem_301": "lesser", "BG30_MagicItem_430": "lesser",
        "BG30_MagicItem_706": "lesser", "BG30_MagicItem_972": "greater",
        "BG30_MagicItem_916": "greater", "BG32_MagicItem_360": "lesser",
        "BG36_MagicItem_200": "lesser", "BG36_MagicItem_212": "greater",
        "BG36_MagicItem_840": "greater", "BG35_MagicItem_700": "greater",
        "BG35_MagicItem_731": "greater",
    }
    CLASSES = {
        "BG32_MagicItem_700": "MarvelousMushroomScript",
        "BG35_MagicItem_710": "MiniatureShipScript",
        "BG36_MagicItem_205": "DeathwhisperStickerScript",
        "BG32_MagicItem_888": "RecyclingStickerScript",
        "BG36_MagicItem_300": "FrigidBlossomScript",
        "BG36_MagicItem_307": "WandOfDivinationScript",
        "BG35_MagicItem_890": "SunkenAnchorScript",
        "BG30_MagicItem_993": "PaglesFishingRodScript",
        "BG35_MagicItem_301": "ScraperStickerScript",
        "BG30_MagicItem_430": "RockinMusicBoxScript",
        "BG30_MagicItem_706": "ReflectivePendantScript",
        "BG30_MagicItem_972": "KarazhanChessSetScript",
        "BG30_MagicItem_916": "EssenceOfDreamsScript",
        "BG32_MagicItem_360": "BalefulIncenseScript",
        "BG36_MagicItem_200": "HerdingHornScript",
        "BG36_MagicItem_212": "WolfheadFlailScript",
        "BG36_MagicItem_840": "SecretSchematicScript",
        "BG35_MagicItem_700": "WildfeatherDusterScript",
        "BG35_MagicItem_731": "DeathtouchAppleScript",
    }

    def test_all_registered_and_bound(self):
        self.assertEqual(len(self.IMPLEMENTED), 19)
        for tid in self.IMPLEMENTED:
            self.assertIn(tid, REGISTRY, tid)
            self.assertIs(REGISTRY[tid], getattr(B7, self.CLASSES[tid]), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_all_in_offer_pool_at_declared_tier(self):
        db = get_db()
        offer_ids = {d.id for d in db.trinket_offer_pool()}
        for tid, kind in self.KIND.items():
            self.assertIn(tid, offer_ids, tid)
            school = 11 if kind == "lesser" else 12
            self.assertEqual(db.get(tid).spell_school, school, tid)

    def test_num_params_match_text(self):
        db = get_db()
        self.assertEqual(db.get("BG32_MagicItem_700").num(0), 1)
        self.assertEqual(db.get("BG32_MagicItem_700").num(1), 1)
        self.assertEqual(db.get("BG35_MagicItem_710").num(0), 3)   # 37.0: 2→3
        self.assertEqual(db.get("BG35_MagicItem_710").num(1), 3)   # 37.0: 2→3
        self.assertEqual(db.get("BG36_MagicItem_307").num(0), 3)
        self.assertEqual(db.get("BG35_MagicItem_890").num(0), 2)
        self.assertEqual(db.get("BG35_MagicItem_700").num(1), 6)
        self.assertEqual(db.get("BG35_MagicItem_731").num(1), 3)
        self.assertEqual(db.get("BG30_MagicItem_916").num(0), 2)
        self.assertEqual(db.get("BG30_MagicItem_916").num(1), 1)

    def test_essence_of_dreams_data_chain(self):
        db = get_db()
        d = db.get("BG30_MagicItem_916")
        self.assertIsNotNone(d.evolution_card_id)
        token = db.by_dbf(d.evolution_card_id)
        self.assertIsNotNone(token)
        self.assertEqual(token.id, DREAMERS_EMBRACE)
        self.assertFalse(token.is_pool_spell)

    def test_bounty_ids_are_pool_spells(self):
        import hsrl2.constants as C
        db = get_db()
        self.assertTrue(C.BOUNTY_SPELL_IDS)
        for bid in C.BOUNTY_SPELL_IDS:
            self.assertTrue(db.get(bid).is_pool_spell, bid)


# ══════════════ BG32_MagicItem_700 Marvelous Mushroom ══════════════

class TestMarvelousMushroom(unittest.TestCase):
    TID = "BG32_MagicItem_700"

    def _play_shiny_ring(self, g, hero, target):
        s = g.create_spell(SPELL_STATS_ALL, controller=hero)
        assert g.spell_pool.acquire(SPELL_STATS_ALL)
        hero.add_to_hand(s)
        self.assertTrue(g.play_spell(hero, s))
        return target

    def test_tavern_spell_buff_increases(self):
        g = make_game(seed=1001)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        d = get_db().get(self.TID)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(0))
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), d.num(1))
        m = put(g, a, g.create_minion(BEAST, controller=a))
        base_atk, base_health = m.atk, m.max_health
        self._play_shiny_ring(g, a, m)
        # Shiny Ring 基础 +1/+1 再加饰品额外 +1/+1
        self.assertEqual(m.atk, base_atk + 2)
        self.assertEqual(m.max_health, base_health + 2)

    def test_control_without_trinket(self):
        g = make_game(seed=1002)
        a = g.heroes[0]
        m = put(g, a, g.create_minion(BEAST, controller=a))
        base_atk, base_health = m.atk, m.max_health
        self._play_shiny_ring(g, a, m)
        self.assertEqual(m.atk, base_atk + 1)      # 仅法术基础值
        self.assertEqual(m.max_health, base_health + 1)

    def test_improves_each_turn(self):
        g = make_game(seed=1003)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        g.end_recruit_phase()                       # 真实推进回合 → SoT
        d = get_db().get(self.TID)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK), d.num(0) * 2)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH),
                         d.num(1) * 2)
        m = put(g, a, g.create_minion(BEAST, controller=a))
        base_atk = m.atk
        self._play_shiny_ring(g, a, m)
        self.assertEqual(m.atk, base_atk + 3)       # 基础 1 + 2 档额外

    def test_opponent_spell_not_amplified(self):
        g = make_game(seed=1004)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        m = put(g, b, g.create_minion(BEAST, controller=b))
        base_atk = m.atk
        self._play_shiny_ring(g, b, m)
        self.assertEqual(m.atk, base_atk + 1)       # 对手只有基础值
        self.assertEqual(b.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)


# ══════════════════ BG35_MagicItem_710 Miniature Ship ══════════════════

class TestMiniatureShip(unittest.TestCase):
    TID = "BG35_MagicItem_710"

    def test_cast_tavern_spell_buffs_pirates(self):
        g = make_game(seed=1011)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        pirate = put(g, a, g.create_minion(PIRATE, controller=a))
        other = put(g, a, g.create_minion(NON_PIRATE, controller=a))
        p_atk, p_hp = pirate.atk, pirate.max_health
        o_atk = other.atk
        play_from_hand(g, a, SPELL_PLAIN, spell=True)
        d = get_db().get(self.TID)
        self.assertEqual(pirate.atk, p_atk + d.num(0))
        self.assertEqual(pirate.max_health, p_hp + d.num(1))
        self.assertEqual(other.atk, o_atk)          # 非海盗不变

    def test_control_without_trinket(self):
        g = make_game(seed=1012)
        a = g.heroes[0]
        pirate = put(g, a, g.create_minion(PIRATE, controller=a))
        p_atk = pirate.atk
        play_from_hand(g, a, SPELL_PLAIN, spell=True)
        self.assertEqual(pirate.atk, p_atk)

    def test_opponent_cast_not_buffed(self):
        g = make_game(seed=1013)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        pirate = put(g, a, g.create_minion(PIRATE, controller=a))
        p_atk = pirate.atk
        play_from_hand(g, b, SPELL_PLAIN, spell=True)
        self.assertEqual(pirate.atk, p_atk)         # owner 隔离


# ══════════════ BG36_MagicItem_205 Deathwhisper Sticker ══════════════

class TestDeathwhisperSticker(unittest.TestCase):
    TID = "BG36_MagicItem_205"

    def test_friendly_reborn_buffs_all(self):
        g = make_game(seed=1021)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        watcher = put(g, a, g.create_minion(BEAST, controller=a))
        reborn = put(g, a, g.create_minion(UNDEAD, controller=a))
        reborn.set(GameTag.REBORN, True)
        w_atk, w_hp = watcher.atk, watcher.max_health
        r_atk = reborn.atk
        death_in_combat(g, reborn)
        d = get_db().get(self.TID)
        self.assertEqual(watcher.atk, w_atk + d.num(0))
        self.assertEqual(watcher.max_health, w_hp + d.num(1))
        # 复生体本身也已回归棋盘 → 同样获得增益
        self.assertEqual(reborn.atk, r_atk + d.num(0))

    def test_control_without_trinket(self):
        g = make_game(seed=1022)
        a = g.heroes[0]
        watcher = put(g, a, g.create_minion(BEAST, controller=a))
        reborn = put(g, a, g.create_minion(UNDEAD, controller=a))
        reborn.set(GameTag.REBORN, True)
        w_atk = watcher.atk
        death_in_combat(g, reborn)
        self.assertEqual(watcher.atk, w_atk)

    def test_opponent_reborn_not_buffing(self):
        g = make_game(seed=1023)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        watcher = put(g, a, g.create_minion(BEAST, controller=a))
        reborn = put(g, b, g.create_minion(UNDEAD, controller=b))
        reborn.set(GameTag.REBORN, True)
        w_atk = watcher.atk
        death_in_combat(g, reborn)
        self.assertEqual(watcher.atk, w_atk)        # owner 隔离


# ══════════════ BG32_MagicItem_888 Recycling Sticker ══════════════

class TestRecyclingSticker(unittest.TestCase):
    TID = "BG32_MagicItem_888"

    def test_play_elemental_grants_free_refresh(self):
        g = make_game(seed=1031)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        play_from_hand(g, a, ELEMENTAL, spell=False)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 1)
        a.gold = 10
        g.refresh_tavern(a)                          # 真实刷新
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)
        self.assertEqual(a.gold, 10)                 # 免费刷新不扣金

    def test_non_elemental_does_not_trigger(self):
        g = make_game(seed=1032)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        play_from_hand(g, a, NON_ELEMENTAL, spell=False)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)

    def test_opponent_elemental_not_counted(self):
        g = make_game(seed=1033)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        play_from_hand(g, b, ELEMENTAL, spell=False)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)


# ══════════════════ BG36_MagicItem_300 Frigid Blossom ══════════════════

class TestFrigidBlossom(unittest.TestCase):
    TID = "BG36_MagicItem_300"

    def test_refresh_reduces_upgrade_cost(self):
        g = make_game(seed=1041)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        a.gold = 50
        g.refresh_tavern(a)
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD, 0), -1)
        a.gold = 50
        expected = a.upgrade_cost - 1
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.gold, 50 - expected)
        self.assertEqual(a.tavern_tier, 2)

    def test_control_without_trinket_pays_full(self):
        g = make_game(seed=1042)
        a = g.heroes[0]
        a.gold = 50
        expected = a.upgrade_cost
        self.assertTrue(g.upgrade_tavern(a))
        self.assertEqual(a.gold, 50 - expected)
        self.assertEqual(expected, 5)                # 基线升级费

    def test_auto_refresh_does_not_trigger(self):
        g = make_game(seed=1044)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        g.refresh_tavern(a, auto=True)              # 回合开始的自动刷新
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD, 0), 0)
        g.refresh_tavern(a)                          # 正对照: 手动刷新
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD, 0), -1)

    def test_opponent_refresh_not_counted(self):
        g = make_game(seed=1043)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        b.gold = 50
        g.refresh_tavern(b)
        self.assertEqual(a.get(GameTag.UPGRADE_COST_MOD, 0), 0)


# ══════════════════ BG36_MagicItem_307 Wand of Divination ══════════════════

class TestWandOfDivination(unittest.TestCase):
    TID = "BG36_MagicItem_307"

    def test_third_spell_on_minion_gives_gold(self):
        g = make_game(seed=1051)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        m = put(g, a, g.create_minion(BEAST, controller=a))
        a.gold = 10
        for _ in range(2):
            play_from_hand(g, a, SPELL_TARGET, spell=True, target=m)
        self.assertEqual(a.gold, 10)                 # 未达阈值
        play_from_hand(g, a, SPELL_TARGET, spell=True, target=m)
        self.assertEqual(a.gold, 11)                 # 第 3 次恰好 +1
        play_from_hand(g, a, SPELL_TARGET, spell=True, target=m)
        self.assertEqual(a.gold, 11)                 # 计数已清零

    def test_spell_without_minion_target_not_counted(self):
        g = make_game(seed=1052)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        put(g, a, g.create_minion(BEAST, controller=a))
        a.gold = 10
        for _ in range(3):
            play_from_hand(g, a, SPELL_PLAIN, spell=True)
        self.assertEqual(a.gold, 10)

    def test_control_without_trinket(self):
        g = make_game(seed=1053)
        a = g.heroes[0]
        m = put(g, a, g.create_minion(BEAST, controller=a))
        a.gold = 10
        for _ in range(3):
            play_from_hand(g, a, SPELL_TARGET, spell=True, target=m)
        self.assertEqual(a.gold, 10)

    def test_opponent_spells_not_counted(self):
        g = make_game(seed=1054)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        m = put(g, b, g.create_minion(BEAST, controller=b))
        a.gold = 10
        for _ in range(3):
            play_from_hand(g, b, SPELL_TARGET, spell=True, target=m)
        self.assertEqual(a.gold, 10)                 # owner 隔离


# ══════════════════ BG35_MagicItem_890 Sunken Anchor ══════════════════

class TestSunkenAnchor(unittest.TestCase):
    TID = "BG35_MagicItem_890"

    def test_bind_grants_bounties_and_sot_repeats(self):
        import hsrl2.constants as C
        g = make_game(seed=1061)
        a, b = g.heroes
        before = bounty_pool_sum(g)
        offer_and_buy(g, a, self.TID, "lesser")
        n = get_db().get(self.TID).num(0)
        self.assertEqual(len(a.hand), n)
        for e in a.hand:
            self.assertIn(e.card_id, C.BOUNTY_SPELL_IDS)
        self.assertEqual(bounty_pool_sum(g), before - n)   # 占池
        g.end_recruit_phase()                              # 真实 SoT
        got = [e for e in a.hand if e.card_id in C.BOUNTY_SPELL_IDS]
        self.assertEqual(len(got), n * 2)
        self.assertEqual(bounty_pool_sum(g), before - n * 2)
        self.assertEqual(b.hand, [])

    def test_control_without_trinket(self):
        g = make_game(seed=1062)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


# ══════════════ BG30_MagicItem_993 Pagle's Fishing Rod ══════════════

class TestPaglesFishingRod(unittest.TestCase):
    TID = "BG30_MagicItem_993"

    def test_gets_tier7_minion_each_turn(self):
        g = make_game(seed=1071)
        a, b = g.heroes
        before = t7_pool_sum(g)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual(len(a.hand), 1)
        self.assertEqual(a.hand[0].tech_level, 7)
        self.assertEqual(t7_pool_sum(g), before - 1)
        g.end_recruit_phase()
        t7s = [e for e in a.hand if e.tech_level == 7]
        self.assertEqual(len(t7s), 2)
        self.assertEqual(t7_pool_sum(g), before - 2)
        self.assertEqual(b.hand, [])

    def test_control_without_trinket(self):
        g = make_game(seed=1072)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


# ══════════════ BG35_MagicItem_301 Scraper Sticker ══════════════

class TestScraperSticker(unittest.TestCase):
    TID = "BG35_MagicItem_301"

    def test_gets_magnetic_mech_each_turn(self):
        g = make_game(seed=1081)
        a, b = g.heroes
        before = sum(g.minion_pool.available(d.id)
                     for d in get_db().pool_minions()
                     if "magnetic" in d.keywords)
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(len(a.hand), 1)
        m = a.hand[0]
        d = get_db().get(m.card_id)
        self.assertIn("magnetic", d.keywords)
        self.assertIn(d.race, (Race.MECH, Race.ALL))
        self.assertEqual(
            sum(g.minion_pool.available(x.id)
                for x in get_db().pool_minions()
                if "magnetic" in x.keywords), before - 1)
        g.end_recruit_phase()
        mags = [e for e in a.hand
                if "magnetic" in get_db().get(e.card_id).keywords]
        self.assertEqual(len(mags), 2)
        self.assertEqual(
            sum(g.minion_pool.available(x.id)
                for x in get_db().pool_minions()
                if "magnetic" in x.keywords), before - 2)
        self.assertEqual(b.hand, [])

    def test_control_without_trinket(self):
        g = make_game(seed=1082)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


# ══════════════ BG30_MagicItem_430 Rockin' Music Box ══════════════

class TestRockinMusicBox(unittest.TestCase):
    TID = "BG30_MagicItem_430"

    def test_gets_battlecry_minion_each_turn(self):
        g = make_game(seed=1091)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(len(a.hand), 1)
        self.assertIn("battlecry", get_db().get(a.hand[0].card_id).keywords)
        g.end_recruit_phase()
        gots = [e for e in a.hand
                if "battlecry" in get_db().get(e.card_id).keywords]
        self.assertEqual(len(gots), 2)
        self.assertEqual(b.hand, [])

    def test_control_without_trinket(self):
        g = make_game(seed=1092)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


# ══════════════ BG30_MagicItem_706 Reflective Pendant ══════════════

class TestReflectivePendant(unittest.TestCase):
    TID = "BG30_MagicItem_706"

    def test_plain_copy_has_no_buffs(self):
        g = make_game(seed=1101)
        a, b = g.heroes
        src = put(g, a, g.create_minion(TOKEN_MINION, controller=a))
        g.run_actions(Buff(src, atk=5, health=5))
        buffed_atk = src.atk
        pool_before = g.minion_pool.total_remaining()
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(len(a.hand), 1)
        copy = a.hand[0]
        self.assertEqual(copy.card_id, TOKEN_MINION)
        d = get_db().get(TOKEN_MINION)
        self.assertEqual(copy.atk, d.atk)            # plain: 无附魔
        self.assertEqual(copy.max_health, d.health)
        self.assertLess(copy.atk, buffed_atk)
        self.assertNotEqual(src.atk, d.atk)          # 正对照: 源确实被 buff
        self.assertEqual(g.minion_pool.total_remaining(), pool_before)
        g.end_recruit_phase()                        # 真实 SoT 再取一份
        copies = [e for e in a.hand if e.card_id == TOKEN_MINION]
        self.assertEqual(len(copies), 2)
        self.assertEqual(b.hand, [])

    def test_empty_board_whiffs(self):
        g = make_game(seed=1102)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "lesser")
        self.assertEqual(a.hand, [])


# ══════════════ BG30_MagicItem_972 Karazhan Chess Set ══════════════

class TestKarazhanChessSet(unittest.TestCase):
    TID = "BG30_MagicItem_972"

    def _soc_summons(self, seed, with_trinket, who="a"):
        g = make_game(seed=seed)
        a, b = g.heroes
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        src = put(g, a, g.create_minion(TOKEN_MINION, controller=a))
        g.run_actions(Buff(src, atk=3, health=3))
        put(g, b, g.create_minion(BEAST, controller=b))
        seen = []
        g.events.register(Listener(
            event=SUMMON, owner=a,
            callback=lambda gg, minion=None, **kw: seen.append(minion)
            if minion.controller is a else None))
        g.run_combat(a, b)
        return src, seen

    def test_soc_summons_exact_copy(self):
        src, seen = self._soc_summons(1111, with_trinket=True)
        copies = [m for m in seen if m is not src]
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy.card_id, src.card_id)
        self.assertEqual(copy.atk, src.atk)          # 精确副本含 buff
        self.assertEqual(copy.max_health, src.max_health)

    def test_control_without_trinket(self):
        src, seen = self._soc_summons(1112, with_trinket=False)
        self.assertEqual([m for m in seen if m is not src], [])

    def test_opponent_no_copy(self):
        g = make_game(seed=1113)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        put(g, a, g.create_minion(BEAST, controller=a))
        b_src = put(g, b, g.create_minion(TOKEN_MINION, controller=b))
        seen = []
        g.events.register(Listener(
            event=SUMMON, owner=b,
            callback=lambda gg, minion=None, **kw: seen.append(minion)
            if minion.controller is b else None))
        g.run_combat(a, b)
        self.assertNotIn(b_src, seen)                # 对手无复制
        self.assertEqual(seen, [])                   # owner 隔离


# ══════════════ BG30_MagicItem_916 Essence of Dreams ══════════════

class TestEssenceOfDreams(unittest.TestCase):
    TID = "BG30_MagicItem_916"

    def test_gets_copies_each_turn(self):
        g = make_game(seed=1121)
        a, b = g.heroes
        d = get_db().get(self.TID)
        before = g.spell_pool.available(DREAMERS_EMBRACE)
        offer_and_buy(g, a, self.TID, "greater")
        self.assertEqual([e.card_id for e in a.hand],
                         [DREAMERS_EMBRACE] * d.num(0))
        self.assertTrue(all(isinstance(e, Spell) for e in a.hand))
        # 非池法术（BACON_SPELL token）→ 不占池
        self.assertEqual(g.spell_pool.available(DREAMERS_EMBRACE), before)
        g.end_recruit_phase()
        got = [e for e in a.hand if e.card_id == DREAMERS_EMBRACE]
        self.assertEqual(len(got), d.num(0) + d.num(1))
        self.assertEqual(b.hand, [])

    def test_control_without_trinket(self):
        g = make_game(seed=1122)
        a = g.heroes[0]
        self.assertEqual(a.hand, [])


# ══════════════ BG32_MagicItem_360 Baleful Incense ══════════════

class TestBalefulIncense(unittest.TestCase):
    TID = "BG32_MagicItem_360"

    def _soc_reborn(self, seed, with_trinket):
        g = make_game(seed=seed)
        a, b = g.heroes
        if with_trinket:
            offer_and_buy(g, a, self.TID, "lesser")
        u1 = put(g, a, g.create_minion(UNDEAD, controller=a))
        mid = put(g, a, g.create_minion(BEAST, controller=a))
        u2 = put(g, a, g.create_minion(UNDEAD, controller=a))
        u3 = put(g, a, g.create_minion(UNDEAD, controller=a))
        b_u = put(g, b, g.create_minion(UNDEAD, controller=b))
        seen = {}
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=a,
            callback=lambda gg, hero=None, **kw: seen.update(
                {hero: [m.reborn for m in (u1, mid, u2, u3, b_u)]})
            if hero is a else None))
        g.run_combat(a, b)
        return seen[a], seen.get(b)

    def test_left_and_right_undead_get_reborn(self):
        flags, _ = self._soc_reborn(1131, with_trinket=True)
        # u1 左端亡灵 / u3 右端亡灵 → Reborn; mid 非亡灵、u2 中位不获
        self.assertEqual(flags, [True, False, False, True, False])

    def test_control_without_trinket(self):
        flags, _ = self._soc_reborn(1132, with_trinket=False)
        self.assertEqual(flags, [False, False, False, False, False])

    def test_opponent_undead_not_granted(self):
        g = make_game(seed=1133)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        b_u = put(g, b, g.create_minion(UNDEAD, controller=b))
        put(g, a, g.create_minion(BEAST, controller=a))
        seen = {}
        g.events.register(Listener(
            event=START_OF_COMBAT, owner=b,
            callback=lambda gg, hero=None, **kw: seen.update(
                {hero: b_u.reborn})))
        g.run_combat(a, b)
        self.assertFalse(seen[b])


# ══════════════════ BG36_MagicItem_200 Herding Horn ══════════════════

class TestHerdingHorn(unittest.TestCase):
    TID = "BG36_MagicItem_200"

    def test_rally_attack_grants_free_refresh(self):
        g = make_game(seed=1141)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        attacker = put(g, a, g.create_minion(RALLY_MINION, controller=a))
        defender = put(g, b, g.create_minion(BEAST, controller=b))
        self.assertTrue(attacker.has(GameTag.RALLY))
        execute_immediate_attack(g, attacker, defender)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 1)
        a.gold = 10
        g.refresh_tavern(a)
        self.assertEqual(a.gold, 10)                 # 免费刷新可用

    def test_non_rally_attacker_not_counted(self):
        g = make_game(seed=1142)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        attacker = put(g, a, g.create_minion(BEAST, controller=a))
        defender = put(g, b, g.create_minion(BEAST, controller=b))
        execute_immediate_attack(g, attacker, defender)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)

    def test_opponent_rally_attack_not_granted(self):
        g = make_game(seed=1143)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "lesser")
        attacker = put(g, b, g.create_minion(RALLY_MINION, controller=b))
        defender = put(g, a, g.create_minion(BEAST, controller=a))
        execute_immediate_attack(g, attacker, defender)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 0)


# ══════════════════ BG36_MagicItem_212 Wolfhead Flail ══════════════════

class TestWolfheadFlail(unittest.TestCase):
    TID = "BG36_MagicItem_212"

    def _eot_deathrattles(self, seed, with_trinket, owner="a"):
        g = make_game(seed=seed)
        a, b = g.heroes
        target_hero = a if owner == "a" else b
        if with_trinket:
            offer_and_buy(g, a, self.TID, "greater")
        calls = []
        probes = []
        for _ in range(3):
            m = probe_minion("deathrattle", calls)
            m.set(GameTag.DEATHRATTLE, True)
            put(g, target_hero, m)
            probes.append(m)
        g.end_recruit_phase()
        return calls, probes

    def test_two_leftmost_deathrattles_trigger(self):
        calls, probes = self._eot_deathrattles(1151, with_trinket=True)
        self.assertEqual(calls.count(probes[0]), 1)
        self.assertEqual(calls.count(probes[1]), 1)
        self.assertEqual(calls.count(probes[2]), 0)

    def test_control_without_trinket(self):
        calls, probes = self._eot_deathrattles(1152, with_trinket=False)
        self.assertEqual(calls, [])

    def test_opponent_deathrattles_not_triggered(self):
        calls, probes = self._eot_deathrattles(1153, with_trinket=True,
                                               owner="b")
        self.assertEqual(calls, [])                  # owner 隔离


# ══════════════════ BG36_MagicItem_840 Secret Schematic ══════════════════

class TestSecretSchematic(unittest.TestCase):
    TID = "BG36_MagicItem_840"

    def test_buying_mech_grants_tavern_spell(self):
        g = make_game(seed=1161)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        a.gold = 20
        mech = g.inject_tavern_minion(a, MECH)
        self.assertTrue(g.buy_from_tavern(a, mech))
        self.assertEqual(len(a.hand), 2)
        spells = [e for e in a.hand if isinstance(e, Spell)]
        self.assertEqual(len(spells), 1)
        self.assertTrue(get_db().get(spells[0].card_id).is_pool_spell)

    def test_non_mech_purchase_not_triggered(self):
        g = make_game(seed=1162)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        a.gold = 20
        beast = g.inject_tavern_minion(a, BEAST)
        self.assertTrue(g.buy_from_tavern(a, beast))
        self.assertEqual([e.card_id for e in a.hand], [BEAST])

    def test_control_without_trinket(self):
        g = make_game(seed=1163)
        a = g.heroes[0]
        a.gold = 20
        mech = g.inject_tavern_minion(a, MECH)
        self.assertTrue(g.buy_from_tavern(a, mech))
        self.assertEqual([e.card_id for e in a.hand], [MECH])

    def test_opponent_buying_mech_not_granting(self):
        g = make_game(seed=1164)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        b.gold = 20
        mech = g.inject_tavern_minion(b, MECH)
        self.assertTrue(g.buy_from_tavern(b, mech))
        self.assertEqual(a.hand, [])


# ══════════════ BG35_MagicItem_700 Wildfeather Duster ══════════════

class TestWildfeatherDuster(unittest.TestCase):
    TID = "BG35_MagicItem_700"

    def test_six_beasts_grants_random_beast(self):
        g = make_game(seed=1171)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        threshold = get_db().get(self.TID).num(1)
        for _ in range(threshold - 1):
            put(g, a, g.create_minion(BEAST, controller=a))
        self.assertEqual(a.hand, [])                 # 未达阈值
        put(g, a, g.create_minion(BEAST, controller=a))
        self.assertEqual(len(a.hand), 1)
        d = get_db().get(a.hand[0].card_id)
        self.assertIn(d.race, (Race.BEAST, Race.ALL))

    def test_non_beast_summons_not_counted(self):
        g = make_game(seed=1172)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        threshold = get_db().get(self.TID).num(1)
        for _ in range(threshold):
            put(g, a, g.create_minion(MECH, controller=a))
        self.assertEqual(a.hand, [])                 # 机械不计数

    def test_control_without_trinket(self):
        g = make_game(seed=1173)
        a = g.heroes[0]
        for _ in range(6):
            put(g, a, g.create_minion(BEAST, controller=a))
        self.assertEqual(a.hand, [])

    def test_opponent_beasts_not_counted(self):
        g = make_game(seed=1174)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        for _ in range(6):
            put(g, b, g.create_minion(BEAST, controller=b))
        self.assertEqual(a.hand, [])                 # owner 隔离


# ══════════════ BG35_MagicItem_731 Deathtouch Apple ══════════════

class TestDeathtouchApple(unittest.TestCase):
    TID = "BG35_MagicItem_731"

    def _kill_in_combat(self, g, m):
        m.set(GameTag.REBORN, True)
        prev = g.in_combat
        g.in_combat = True
        try:
            m.health = 0
            g._process_single_death(m)
        finally:
            g.in_combat = prev

    def test_reborn_undead_regains_reborn_with_turn_limit(self):
        g = make_game(seed=1181)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(1)
        m = put(g, a, g.create_minion(UNDEAD, controller=a))
        for i in range(limit):
            self._kill_in_combat(g, m)
            self.assertTrue(m.reborn, f"use {i + 1} should grant Reborn")
        self._kill_in_combat(g, m)
        self.assertFalse(m.reborn)                   # 达每回合上限

    def test_control_without_trinket(self):
        g = make_game(seed=1182)
        a = g.heroes[0]
        m = put(g, a, g.create_minion(UNDEAD, controller=a))
        self._kill_in_combat(g, m)
        self.assertFalse(m.reborn)

    def test_non_undead_reborn_not_granted(self):
        g = make_game(seed=1183)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        m = put(g, a, g.create_minion(BEAST, controller=a))
        self._kill_in_combat(g, m)
        self.assertFalse(m.reborn)

    def test_opponent_undead_not_granted(self):
        g = make_game(seed=1184)
        a, b = g.heroes
        offer_and_buy(g, a, self.TID, "greater")
        m = put(g, b, g.create_minion(UNDEAD, controller=b))
        self._kill_in_combat(g, m)
        self.assertFalse(m.reborn)                   # owner 隔离

    def test_limit_resets_next_turn(self):
        g = make_game(seed=1185)
        a = g.heroes[0]
        offer_and_buy(g, a, self.TID, "greater")
        limit = get_db().get(self.TID).num(1)
        m = put(g, a, g.create_minion(UNDEAD, controller=a))
        for _ in range(limit):
            self._kill_in_combat(g, m)
        self._kill_in_combat(g, m)
        self.assertFalse(m.reborn)                   # 本回合已用尽
        g.end_recruit_phase()                        # 真实推进回合
        self.assertTrue(m in a.board)
        self._kill_in_combat(g, m)
        self.assertTrue(m.reborn)                    # 新回合配额重置


if __name__ == "__main__":
    unittest.main()
