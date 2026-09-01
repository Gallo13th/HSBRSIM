"""批次 hero_passives2 语义测试（作业单 2026-08-23，15 项注册）。

覆盖 12 被动技能 + Sulfuras 替换目标 + 2 香蕉 token 支撑脚本;
DEFERRED 台账 12 项断言未注册（二态铁律）。

驱动协议: 测试显式调 ``REGISTRY[power.id].on_bind(hero, game)``（
start_game 接线的人工等价物）; 数值断言一律 CardDef.num()/db 属性
计算（TEST_SOP §4）; 事件驱动用引擎真实路径（buy_from_tavern /
play_minion / sell_minion / refresh_tavern / _process_eliminations），
无引擎入口的事件（turn_start/turn_end/summon-in-combat）以字面量
fire（与引擎 fire 点同参）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

import hsrl2.constants as C
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import GameTag, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(hero_ids: tuple[str, ...] = ("TB_BaconShop_HERO_52",
                                           "TB_BaconShop_HERO_34"),
              seed: int = 7) -> Game:
    heroes = [Hero(hid, hid) for hid in hero_ids]
    return Game(heroes, get_db(), seed=seed)


def bind(game: Game, hero: Hero, power_id: str | None = None):
    power = game.hero_power_def(hero)
    assert power is not None, f"hero {hero.card_id} has no power def"
    key = power_id or power.id
    script = REGISTRY[key]
    script.on_bind(hero, game)
    return script


def put(game: Game, card_id: str, hero: Hero, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.summon(hero, m)
    return m


def make_minion(name: str, atk: int, health: int) -> Minion:
    return Minion(f"TEST_{name}", name, atk=atk, health=health)


def buy_minion(game: Game, hero: Hero, card_id: str | None = None) -> bool:
    """真实购买路径: 构造随从入馆后 buy_from_tavern（fire minion_bought）。"""
    if card_id is None:
        m = make_minion(f"BUY{len(hero.hand)}", 1, 1)
    else:
        m = game.create_minion(card_id, controller=hero)
    m.controller = hero
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return game.buy_from_tavern(hero, m)


def buy_spell(game: Game, hero: Hero, card_id: str = "BG28_810") -> bool:
    """真实法术购买路径（fire spell_bought; Tavern Coin 池法术）。"""
    s = game.create_spell(card_id, controller=hero)
    s.zone = Zone.TAVERN
    hero.tavern.append(s)
    return game.buy_from_tavern(hero, s)


def play(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    hero.add_to_hand(m)
    assert game.play_minion(hero, m)
    return m


class TestRegistryState(unittest.TestCase):
    """批次注册面: 15 项 OK; DEFERRED 台账 12 项不注册。"""

    OK_IDS = (
        "TB_BaconShop_HP_087", "TB_BaconShop_HP_087t", "BG20_HERO_102p",
        "BG28_HERO_800p", "BG24_HERO_204p", "TB_BaconShop_HP_038",
        "BG20_HERO_280p5", "BG26_HERO_104p", "TB_BaconShop_HP_088",
        "TB_BaconShop_HP_107", "TB_BaconShop_HP_042", "TB_BaconShop_HP_080",
        "TB_BaconShop_HP_085t",
    )
    TOKEN_IDS = ("BG_EX1_014t", "BG_TB_006")
    DEFERRED_IDS = (
        "BG21_HERO_000p", "BG35_HERO_001p",
        "TB_BaconShop_HP_057", "BG20_HERO_202p", "BG33_HERO_001p_ALT",
        "BG20_HERO_242p", "BG22_HERO_004p",
    )

    def test_ok_registered_and_passive(self):
        for cid in self.OK_IDS:
            self.assertIn(cid, REGISTRY)
            self.assertTrue(getattr(REGISTRY[cid], "passive", False),
                            cid)
            self.assertTrue(hasattr(REGISTRY[cid], "on_bind"), cid)
        for cid in self.TOKEN_IDS:   # 香蕉 token 为法术脚本（非被动）
            self.assertIn(cid, REGISTRY)

    def test_token_scripts_not_passive_flagged(self):
        # 香蕉 token 是法术脚本（needs_target），无 passive 语义要求
        for cid in ("BG_EX1_014t", "BG_TB_006"):
            self.assertTrue(getattr(REGISTRY[cid], "needs_target", False))

    def test_deferred_not_registered(self):
        for cid in self.DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)


class TestRagnaros(unittest.TestCase):
    """TB_BaconShop_HP_087 — 买 12 张（随从+法术混合）得 Sulfuras。"""

    HERO = "TB_BaconShop_HERO_11"
    THRESHOLD = 12   # db.num(0)（36.2; wiki BUY,INSECT! 同值）

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        game.heroes[0].gold = 99
        return game, game.heroes[0]

    def test_threshold_from_db(self):
        d = get_db().get("TB_BaconShop_HP_087")
        self.assertEqual(d.num(0), self.THRESHOLD)

    def test_replace_after_12_cards(self):
        game, rag = self.make()
        for i in range(self.THRESHOLD - 1):
            if i % 2 == 0:
                self.assertTrue(buy_minion(game, rag))
            else:
                self.assertTrue(buy_spell(game, rag))
            if len(rag.hand) > 8:
                rag.hand.clear()
            self.assertEqual(game.hero_power_def(rag).id,
                             "TB_BaconShop_HP_087")
        self.assertTrue(buy_spell(game, rag))
        self.assertEqual(game.hero_power_def(rag).id,
                         "TB_BaconShop_HP_087t")
        # 替换后 Sulfuras 即刻接线: 同回合 turn_end 生效
        a = make_minion("L", 1, 1)
        b = make_minion("M", 1, 1)
        c = make_minion("R", 1, 1)
        for m in (a, b, c):
            game.summon(rag, m)
        game.events.fire(game, "turn_end", turn=1)
        self.assertEqual((a.atk, a.health), (9, 9))
        self.assertEqual((b.atk, b.health), (1, 1))
        self.assertEqual((c.atk, c.health), (9, 9))

    def test_replacement_is_passive(self):
        game, rag = self.make()
        self.assertFalse(game.use_hero_power(rag))


class TestSulfuras(unittest.TestCase):
    """TB_BaconShop_HP_087t — EoT 左右最右 +8/+8（+8/+8 文本字面量）。"""

    def test_ends_buffed_single_minion_once(self):
        game = make_game(("TB_BaconShop_HERO_11", "TB_BaconShop_HERO_52"))
        rag = game.heroes[0]
        bind(game, rag, "TB_BaconShop_HP_087t")
        solo = make_minion("SOLO", 2, 3)
        game.summon(rag, solo)
        game.events.fire(game, "turn_end", turn=1)
        # 单随从 = 左右同一实体 → 去重单次 +8/+8
        self.assertEqual((solo.atk, solo.health), (10, 11))

    def test_three_minion_board(self):
        game = make_game(("TB_BaconShop_HERO_11", "TB_BaconShop_HERO_52"))
        rag = game.heroes[0]
        bind(game, rag, "TB_BaconShop_HP_087t")
        left = make_minion("L", 1, 1)
        mid = make_minion("M", 5, 5)
        right = make_minion("R", 2, 2)
        for m in (left, mid, right):
            game.summon(rag, m)
        game.events.fire(game, "turn_end", turn=1)
        self.assertEqual((left.atk, left.health), (9, 9))
        self.assertEqual((mid.atk, mid.health), (5, 5))
        self.assertEqual((right.atk, right.health), (10, 10))

    def test_empty_board_safe_and_repeat_per_turn(self):
        game = make_game(("TB_BaconShop_HERO_11", "TB_BaconShop_HERO_52"))
        rag = game.heroes[0]
        bind(game, rag, "TB_BaconShop_HP_087t")
        game.events.fire(game, "turn_end", turn=1)   # 空板不抛
        m = make_minion("M", 1, 1)
        game.summon(rag, m)
        game.events.fire(game, "turn_end", turn=2)
        game.events.fire(game, "turn_end", turn=3)
        self.assertEqual((m.atk, m.health), (17, 17))   # 每回合各一次


class TestOverlordSaurfang(unittest.TestCase):
    """BG20_HERO_102p — 馆内随从 +1/+1 光环, 每 3 买递进。"""

    HERO = "BG20_HERO_102"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        game.heroes[0].gold = 99
        return game, game.heroes[0]

    @staticmethod
    def _def_atk_hp(game, m):
        d = game.db.get(m.card_id)
        return d.atk, d.health

    def test_params_from_db(self):
        d = get_db().get("BG20_HERO_102p")
        self.assertEqual((d.num(0), d.num(1)), (3, 1))

    def test_tavern_aura_on_refresh_and_improve(self):
        game, sf = self.make()
        game.refresh_tavern(sf, auto=True)
        tavern_ms = [e for e in sf.tavern
                     if isinstance(e, Minion) and game.db.get(e.card_id)]
        self.assertTrue(tavern_ms)
        for m in tavern_ms:
            da, dh = self._def_atk_hp(game, m)
            self.assertEqual((m.atk, m.health), (da + 1, dh + 1))
        # 买 2 只: 不改善
        for _ in range(2):
            self.assertTrue(buy_minion(game, sf))
            if len(sf.hand) > 8:
                sf.hand.clear()
        for m in tavern_ms:
            da, dh = self._def_atk_hp(game, m)
            self.assertEqual((m.atk, m.health), (da + 1, dh + 1))
        # 第 3 只（馆内真实随从）: 其余馆内随从即时再 +1/+1（增量）
        in_tavern = [e for e in sf.tavern
                     if isinstance(e, Minion) and e not in sf.hand]
        self.assertTrue(in_tavern)
        bought = in_tavern[0]
        game.buy_from_tavern(sf, bought)
        for m in [x for x in in_tavern if x is not bought]:
            da, dh = self._def_atk_hp(game, m)
            self.assertEqual((m.atk, m.health), (da + 2, dh + 2))
        da, dh = self._def_atk_hp(game, bought)
        self.assertEqual((bought.atk, bought.health), (da + 1, dh + 1))
        # 下次刷新: 新入馆随从共 +2/+2（初始 + 改善两条 TavernBuff 叠加）
        game.refresh_tavern(sf, auto=True)
        newcomers = [e for e in sf.tavern
                     if isinstance(e, Minion) and game.db.get(e.card_id)]
        self.assertTrue(newcomers)
        for e in newcomers:
            da, dh = self._def_atk_hp(game, e)
            self.assertEqual((e.atk, e.health), (da + 2, dh + 2))

    def test_opponent_buys_do_not_count(self):
        game, sf = self.make()
        opp = game.heroes[1]
        opp.gold = 99
        for _ in range(3):
            self.assertTrue(buy_minion(game, opp))
        game.refresh_tavern(sf, auto=True)
        for e in sf.tavern:
            if isinstance(e, Minion) and game.db.get(e.card_id):
                da, dh = self._def_atk_hp(game, e)
                self.assertEqual((e.atk, e.health), (da + 1, dh + 1))


class TestTaethelan(unittest.TestCase):
    """BG28_HERO_800p — 每第 3 个酒馆法术免费。"""

    HERO = "BG28_HERO_800"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        game.heroes[0].gold = 99
        return game, game.heroes[0]

    def test_params(self):
        self.assertEqual(get_db().get("BG28_HERO_800p").num(0), 2)

    def test_every_third_spell_free(self):
        game, tt = self.make()
        cost = game.db.get("BG28_810").cost
        g0 = tt.gold
        buy_spell(game, tt); self.assertEqual(tt.gold, g0 - cost)
        buy_spell(game, tt); self.assertEqual(tt.gold, g0 - 2 * cost)
        buy_spell(game, tt); self.assertEqual(tt.gold, g0 - 2 * cost)  # 免费
        buy_spell(game, tt); self.assertEqual(tt.gold, g0 - 3 * cost)
        buy_spell(game, tt); self.assertEqual(tt.gold, g0 - 4 * cost)
        buy_spell(game, tt); self.assertEqual(tt.gold, g0 - 4 * cost)  # 免费

    def test_window_persists_across_turns(self):
        game, tt = self.make()
        cost = game.db.get("BG28_810").cost
        g0 = tt.gold
        buy_spell(game, tt)
        buy_spell(game, tt)
        self.assertEqual(tt.gold, g0 - 2 * cost)
        # 过回合（第 2 次购买后的免费额度留存）
        game.events.fire(game, "turn_start", turn=2, hero=tt)
        buy_spell(game, tt)
        self.assertEqual(tt.gold, g0 - 2 * cost)

    def test_opponent_spell_buys_do_not_count(self):
        game, tt = self.make()
        opp = game.heroes[1]
        opp.gold = 99
        cost = game.db.get("BG28_810").cost
        for _ in range(3):
            buy_spell(game, opp)
        self.assertEqual(opp.gold, 99 - 3 * cost)   # 对手无折扣


class TestEnhanceO(unittest.TestCase):
    """BG24_HERO_204p — 每次刷新 2 次独立随机 Bonus Keyword。"""

    HERO = "BG24_HERO_204"
    _OFFICIAL_SIX = {
        GameTag.DIVINE_SHIELD, GameTag.REBORN, GameTag.STEALTH,
        GameTag.TAUNT, GameTag.VENOMOUS, GameTag.WINDFURY,
    }

    def test_two_grants_per_refresh_in_official_pool(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        eo = game.heroes[0]
        bind(game, eo)
        seen: list = []

        def spy(g, minion=None, tag=None, **kw):
            seen.append((minion, tag))

        from hsrl2.events import Listener
        game.events.register(Listener(
            event="keyword_gained", owner=eo, callback=spy))
        game.refresh_tavern(eo, auto=True)
        self.assertEqual(len(seen), 2)
        tavern_ids = {id(e) for e in eo.tavern}
        for minion, tag in seen:
            self.assertIn(id(minion), tavern_ids)
            self.assertIn(tag, self._OFFICIAL_SIX)

    def test_opponent_refresh_no_grant(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        eo = game.heroes[0]
        bind(game, eo)
        seen: list = []

        def spy(g, minion=None, tag=None, **kw):
            seen.append((minion, tag))

        from hsrl2.events import Listener
        game.events.register(Listener(
            event="keyword_gained", owner=eo, callback=spy))
        game.refresh_tavern(game.heroes[1], auto=True)
        self.assertEqual(seen, [])


class TestKingMukla(unittest.TestCase):
    """TB_BaconShop_HP_038 — 回合开始自身 2 根香蕉 + 他人各 1 根（33% Big）。"""

    HERO = "TB_BaconShop_HERO_38"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0]

    def test_distribution(self):
        game, mk = self.make()
        partner = game.heroes[1]
        game.events.fire(game, "turn_start", turn=1, hero=mk)
        self.assertEqual(len(mk.hand), 2)
        self.assertEqual(len(partner.hand), 1)
        valid = {"BG_EX1_014t", "BG_TB_006"}
        for e in mk.hand + partner.hand:
            self.assertIn(e.card_id, valid)
        labels = [l for l, _ in game.rng.decisions
                  if l == "mukla_big_banana"]
        self.assertEqual(len(labels), 3)   # 3 根各独立 33% 判定走 game.rng

    def test_bananas_play_closure(self):
        game, mk = self.make()
        target = make_minion("T", 3, 3)
        game.summon(mk, target)
        # Bananas: 定向 +1/+1（db 文本权威）
        s = game.create_spell("BG_EX1_014t", controller=mk)
        mk.add_to_hand(s)
        self.assertTrue(game.play_spell(mk, s))
        self.assertEqual(len(game.pending_choices), 1)
        game.pending_choices[-1].choose(0)
        self.assertEqual((target.atk, target.health), (4, 4))
        # Big Banana: 定向 +2/+2
        big = game.create_spell("BG_TB_006", controller=mk)
        mk.add_to_hand(big)
        self.assertTrue(game.play_spell(mk, big))
        game.pending_choices[-1].choose(0)
        self.assertEqual((target.atk, target.health), (6, 6))


class TestKurtrus(unittest.TestCase):
    """BG20_HERO_280p5 — 每回合首 3 买之一 plain 副本，每回合一次。"""

    HERO = "BG20_HERO_280"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        game.heroes[0].gold = 99
        return game, game.heroes[0]

    def test_plain_copy_at_third_buy_once_per_turn(self):
        game, kt = self.make()
        ids = ("BG23_000", "BG25_013", "BG25_001")
        for i, cid in enumerate(ids[:2]):
            self.assertTrue(buy_minion(game, kt, cid))
            self.assertEqual(len(kt.hand), i + 1)
        self.assertTrue(buy_minion(game, kt, ids[2]))
        self.assertEqual(len(kt.hand), 4)   # 3 购 + 1 副本
        copies = kt.hand[3:]
        self.assertEqual(len(copies), 1)
        self.assertIn(copies[0].card_id, ids)
        # plain: 副本数值=卡面（无 buff）
        d = get_db().get(copies[0].card_id)
        self.assertEqual((copies[0].atk, copies[0].health),
                         (d.atk, d.health))
        # 同回合再买 3 只（新 id 集）: once per turn 不再触发
        ids2 = ("BG33_140", "BG32_330", "BG26_146")
        for cid in ids2:
            self.assertTrue(buy_minion(game, kt, cid))
        n2 = len([m for m in kt.hand if m.card_id in ids2])
        self.assertEqual(n2, 3)   # 恰 3 购、无副本
        # 下一回合窗口复位: 再触发（清手防满手排队干扰计数）
        kt.hand.clear()
        game.events.fire(game, "turn_start", turn=2, hero=kt)
        ids3 = ("BG31_816", "BG27_005", "BG26_810")
        for cid in ids3:
            self.assertTrue(buy_minion(game, kt, cid))
        n3 = len([m for m in kt.hand if m.card_id in ids3])
        self.assertEqual(n3, 4)   # 3 购 + 1 副本


class TestRockMasterVoone(unittest.TestCase):
    """BG26_HERO_104p — 每 3 回合结束复制手牌最左卡。"""

    HERO = "BG26_HERO_104"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0]

    def test_period_and_leftmost_copy(self):
        game, vo = self.make()
        m = game.create_minion("BG33_140", controller=vo)
        s = game.create_spell("BG28_810", controller=vo)
        self.assertTrue(vo.add_to_hand(m))
        self.assertTrue(vo.add_to_hand(s))
        game.events.fire(game, "turn_end", turn=2)
        self.assertEqual(len(vo.hand), 2)   # 非周期回合无动作
        game.events.fire(game, "turn_end", turn=3)
        self.assertEqual(len(vo.hand), 3)
        self.assertEqual(vo.hand[-1].card_id, "BG33_140")   # 最左（随从）
        # 最左为法术时复制法术
        vo.hand.clear()
        s2 = game.create_spell("BG28_810", controller=vo)
        vo.add_to_hand(s2)
        game.events.fire(game, "turn_end", turn=6)
        ids = [e.card_id for e in vo.hand]
        self.assertEqual(ids, ["BG28_810", "BG28_810"])

    def test_empty_hand_safe(self):
        game, vo = self.make()
        game.events.fire(game, "turn_end", turn=3)
        self.assertEqual(vo.hand, [])


class TestChenvaala(unittest.TestCase):
    """TB_BaconShop_HP_088 — 每 3 元素打出升级费 -3。"""

    HERO = "TB_BaconShop_HERO_78"
    ELEM = "BG31_816"   # Fire Baller（元素 18, 无战吼/无脚本）

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        game.heroes[0].set(GameTag.UPGRADE_COST, 7)
        return game, game.heroes[0]

    def test_reduce_every_three_elementals(self):
        game, ch = self.make()
        play(game, ch, self.ELEM)
        play(game, ch, self.ELEM)
        self.assertEqual(ch.upgrade_cost, 7)
        play(game, ch, self.ELEM)
        self.assertEqual(ch.upgrade_cost, 4)   # 7 - 3
        play(game, ch, self.ELEM)
        play(game, ch, self.ELEM)
        play(game, ch, self.ELEM)
        self.assertEqual(ch.upgrade_cost, 1)   # 4 - 3
        # 非元素不计
        play(game, ch, "BG33_140")
        self.assertEqual(ch.upgrade_cost, 1)

    def test_upgrade_resets_to_schedule(self):
        game, ch = self.make()
        for _ in range(3):
            play(game, ch, self.ELEM)
        self.assertEqual(ch.upgrade_cost, 4)
        ch.gold = 20
        self.assertTrue(game.upgrade_tavern(ch))
        self.assertEqual(ch.tavern_tier, 2)
        # 升级后重置为下一档标准费（减费不跨档携带）
        self.assertEqual(ch.upgrade_cost,
                         C.BASE_UPGRADE_COSTS.get(3, 11))


class TestGreybough(unittest.TestCase):
    """TB_BaconShop_HP_107 — 战斗中召唤的随从 +1/+2 + 嘲讽。"""

    HERO = "TB_BaconShop_HERO_95"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0]

    def test_combat_summon_buffed(self):
        game, gb = self.make()
        game.in_combat = True
        m = put(game, "BG33_140", gb)   # 1/1
        self.assertEqual((m.atk, m.health), (2, 3))
        self.assertTrue(m.taunt)
        game.in_combat = False

    def test_recruit_summon_not_buffed(self):
        game, gb = self.make()
        m = put(game, "BG33_140", gb)
        self.assertEqual((m.atk, m.health), (1, 1))
        self.assertFalse(m.taunt)

    def test_enemy_combat_summon_not_buffed(self):
        game, gb = self.make()
        game.in_combat = True
        opp = game.heroes[1]
        m = put(game, "BG33_140", opp)
        self.assertEqual((m.atk, m.health), (1, 1))
        game.in_combat = False


class TestDancinDeryl(unittest.TestCase):
    """TB_BaconShop_HP_042 — 打出戴帽 +1/+1, 卖出随机传承。"""

    HERO = "TB_BaconShop_HERO_36"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0]

    def test_hat_on_play_and_pass_on_sell(self):
        game, de = self.make()
        other = put(game, "BG25_001", de)      # 2/1 taunt/reborn
        d0 = (other.atk, other.health)
        hatted = play(game, de, "BG33_140")    # 1/1 -> 2/2 (帽)
        self.assertEqual((hatted.atk, hatted.health), (2, 2))
        self.assertTrue(game.sell_minion(de, hatted))
        # 帽子传给唯一其他随从
        self.assertEqual((other.atk, other.health),
                         (d0[0] + 1, d0[1] + 1))
        # 传承后再卖出继续传递（链式）
        third = put(game, "BG33_140", de)
        self.assertTrue(game.sell_minion(de, other))
        self.assertEqual((third.atk, third.health), (2, 2))

    def test_hat_lost_when_sold_alone(self):
        game, de = self.make()
        hatted = play(game, de, "BG33_140")
        self.assertEqual((hatted.atk, hatted.health), (2, 2))
        self.assertTrue(game.sell_minion(de, hatted))
        self.assertEqual(de.board, [])

    def test_opponent_play_not_hatted(self):
        game, de = self.make()
        opp = game.heroes[1]
        m = play(game, opp, "BG33_140")
        self.assertEqual((m.atk, m.health), (1, 1))


class TestMrBigglesworth(unittest.TestCase):
    """TB_BaconShop_HP_080 — 他英雄阵亡后 Discover 其板随从（保附魔）。"""

    HERO = "TB_BaconShop_HERO_70"

    def make(self, n_victims: int = 1):
        ids = [self.HERO, "TB_BaconShop_HERO_52", "TB_BaconShop_HERO_34"]
        game = make_game(tuple(ids[:1 + n_victims]))
        bind(game, game.heroes[0])
        return game, game.heroes[0], game.heroes[1:]

    def test_discover_copy_keeps_enchantments(self):
        game, kt, victims = self.make()
        v = victims[0]
        plain = put(game, "BG33_140", v)               # 1/1
        buffed = put(game, "BG33_140", v)
        from hsrl2 import entity
        buffed.add_buff(entity.Buff(atk=3, health=3))  # -> 4/4
        extra1 = put(game, "BG25_001", v)
        extra2 = put(game, "BG25_013", v)
        v.health = 0
        game._process_eliminations()
        self.assertEqual(len(game.pending_choices), 1)
        pc = game.pending_choices[-1]
        self.assertEqual(len(pc.options), 3)   # 4 板 → Discover 样 3
        pick = pc.options[0]
        pc.choose(0)
        self.assertEqual(len(kt.hand), 1)
        got = kt.hand[0]
        self.assertEqual(got.card_id, pick.card_id)
        self.assertEqual(got.is_golden, pick.is_golden)
        self.assertEqual((got.atk, got.health),
                         (pick.atk, pick.health))   # 附魔保持
        self.assertEqual(got.zone, Zone.HAND)

    def test_golden_source_yields_golden_copy(self):
        game, kt, victims = self.make()
        v = victims[0]
        gdef = get_db().golden_version(get_db().get("BG33_140"))
        self.assertIsNotNone(gdef)
        put(game, "BG33_140", v, golden=True)
        v.health = 0
        game._process_eliminations()
        game.pending_choices[-1].choose(0)
        got = kt.hand[0]
        self.assertTrue(got.is_golden)
        self.assertEqual(got.card_id, gdef.id)

    def test_empty_warband_no_choice(self):
        game, kt, victims = self.make()
        victims[0].health = 0
        game._process_eliminations()
        self.assertEqual(game.pending_choices, [])

    def test_multiple_eliminations_queue_choices(self):
        game, kt, victims = self.make(n_victims=2)
        for v in victims:
            put(game, "BG33_140", v)
            v.health = 0
        game._process_eliminations()
        self.assertEqual(len(game.pending_choices), 2)


class TestRakanishu(unittest.TestCase):
    """TB_BaconShop_HP_085t — 酒馆法术增幅 +1/+1, 每 3 回合递进。"""

    HERO = "TB_BaconShop_HERO_75"

    def make(self):
        game = make_game((self.HERO, "TB_BaconShop_HERO_52"))
        bind(game, game.heroes[0])
        return game, game.heroes[0]

    def test_params(self):
        d = get_db().get("TB_BaconShop_HP_085t")
        self.assertEqual((d.num(0), d.num(1)), (3, 1))

    def test_improve_every_three_turns(self):
        game, rk = self.make()
        self.assertEqual(rk.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 1)
        self.assertEqual(rk.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 1)
        game.events.fire(game, "turn_start", turn=1, hero=rk)
        game.events.fire(game, "turn_start", turn=2, hero=rk)
        self.assertEqual(rk.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 1)
        game.events.fire(game, "turn_start", turn=3, hero=rk)
        self.assertEqual(rk.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 2)
        self.assertEqual(rk.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH), 2)
        game.events.fire(game, "turn_start", turn=6, hero=rk)
        self.assertEqual(rk.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 3)

    def test_tavern_spell_buff_applies_extra(self):
        game, rk = self.make()
        game.events.fire(game, "turn_start", turn=3, hero=rk)   # extra=2
        m = make_minion("T", 1, 1)
        game.summon(rk, m)
        act = tavern_spell_buff(m, 2, 2)   # base +2/+2 法术出口
        self.assertEqual((act.atk, act.health), (4, 4))

    def test_opponent_turn_no_improve(self):
        game, rk = self.make()
        opp = game.heroes[1]
        game.events.fire(game, "turn_start", turn=3, hero=opp)
        self.assertEqual(rk.get(GameTag.TAVERN_SPELL_EXTRA_ATK), 1)


if __name__ == "__main__":
    unittest.main()
