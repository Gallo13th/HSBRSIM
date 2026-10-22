"""批次 trinkets31 行为层测试（41 张复评: 8 CORRECT + 19 DEFERRED + 14 迁出,
2026-09-19 复核；原始快照 2026-09-15 = 1 + 29 + 11）。

覆盖 `hsrl2/scripts/batches/batch_trinkets31.py` 的注册项
`BG32_MagicItem_830` Felemental Portrait（+ 2026-09-18 解冻的
Bewitched Ribbon / Cyclist Portrait + 2026-09-19 解冻的 A 组 5 张:
Rewinder / Balladist / Czarina / Implicator / Felblood Portrait）:
数据链交付 / 家族 give 的额外持久酒馆 Buff（当前 + 未来入馆）/ "also
give X" 的同句增量 / 吞噬最高生命策略 / owner 隔离 / 绑定前不追溯 /
金色逐次触发 / 非家族战吼落空 / 空酒馆落空 / 满手排队 / 同 seed 确定性;
以及 19 张 DEFERRED 的结构性台账守卫（零钩子、未注册、在商店池）。

全部行为断言走真实引擎路径: `game.grant_trinket`（on_bind 接线）、
`game.play_minion`（真实战吼广播）、真实 `play_spell`（酒馆法术）、
真实 `hero.take_damage` / `game._process_single_death`（亡语）、真实
`game.add_tavern_entity` / `game.refresh_tavern`（持久酒馆 Buff 应用点
`game.py`）、`game.create_minion` / `game.summon`。结构性守卫类标
`@engine-only`。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2 import constants as C
from hsrl2.db import CardDB
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.scripts import REGISTRY
from hsrl2.scripts.batches import batch_trinkets31 as B31
from hsrl2.minion import Minion
from hsrl2.tags import CardType, GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BATCH_FILE = (Path(__file__).resolve().parent.parent
              / "scripts" / "batches" / "batch_trinkets31.py")

# ── 测试用卡（CardDB 按名核实——禁止凭记忆写 id） ──
PORTRAIT = "BG32_MagicItem_830"       # Felemental Portrait（本批 CORRECT）
BEWITCHED_RIBBON = "BG35_MagicItem_923"   # Bewitched Ribbon（2026-09-18 解冻）
CYCLIST_PORTRAIT = "BG36_MagicItem_362"   # Cyclist Portrait（2026-09-18 解冻）
FELEMENTAL = "BG25_041"               # 关联卡（数据链 evolution_card_id）
FELEMENTAL_GOLDEN = "BG25_041_G"      # 金色独立卡定义
TAVERN_MINION = "BG23_004"            # Deep-Sea Angler 2/3 T3 纳迦（池）
BATTLECRY_OTHER = "BG31_330"          # Ominous Seer（池; 非家族）
NON_NAGA = "BG22_202"                 # Tad 2/2 T2 鱼人（池; 非家族非纳迦）
SHOWY_CYCLIST = "BG31_925"            # 362 载荷（4/2 T5 纳迦; 亡语给纳迦）
TIDE_RAISER = "BG34_920"              # 923 战斗内施法源（死亡亡语施法）
TARECGOSA = "BG21_015"                # 4/4 龙; 自带 PERSIST_COMBAT_CHANGES
SHINY_RING = "BG28_168"               # 池法术 "Give your minions +1/+1"
HAND_FILLER = "BG28_168"              # 满手占位（非池法术，同上卡）

# 基准数值（CardDB 运行核实）: 载荷 give = +2/+1; 饰品 extra = +2/+2
BASE_ATK, BASE_HEALTH = 2, 1
EXTRA_ATK, EXTRA_HEALTH = 2, 2

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 931) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def heroes(g: Game):
    return g.heroes[0], g.heroes[1]


def bind(game: Game, hero: Hero, tid: str = PORTRAIT):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put_tavern(game: Game, hero: Hero, card_id: str = TAVERN_MINION):
    """把随从放进英雄酒馆（走 add_tavern_entity——持久 Buff 的应用点）。"""
    m = game.create_minion(card_id, controller=hero)
    assert game.add_tavern_entity(hero, m)
    return m


def put_board(game: Game, hero: Hero, card_id: str = TAVERN_MINION):
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m)
    return m


def play(game: Game, hero: Hero, card_id: str, golden: bool = False):
    """创建随从进手牌并真实打出（触发战吼广播）。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.pending_hand_add(hero, m)
    ok = game.play_minion(hero, m)
    assert ok, f"{card_id} 打出失败"
    return m


def buffs(hero: Hero):
    """hero.tavern_buffs（延迟初始化 → 缺省空表）的 (atk, health) 快照。"""
    return [(b.atk, b.health) for b in getattr(hero, "tavern_buffs", []) or []]


def hand_ids(hero: Hero):
    return [e.card_id for e in hero.hand]


# ══════════════ BG32_MagicItem_830 行为层 ══════════════


class TestFelementalPortrait(unittest.TestCase):
    """Felemental Portrait: 家族 give 的额外持久酒馆 Buff。"""

    def test_bind_delivers_felemental_card(self):
        """on_bind 经数据链交付恰好 1 只 BG25_041（只进本人手牌）。"""
        g = make_game()
        a, b = heroes(g)
        self.assertEqual(hand_ids(a).count(FELEMENTAL), 0)
        bind(g, a)
        self.assertEqual(hand_ids(a).count(FELEMENTAL), 1)
        self.assertEqual(hand_ids(b).count(FELEMENTAL), 0)
        self.assertEqual([t.card_id for t in a.trinkets].count(PORTRAIT), 1)
        # 数据链零硬编码: evolution_card_id → by_dbf 解析出 BG25_041
        d = get_db().get(PORTRAIT)
        self.assertEqual(get_db().by_dbf(d.evolution_card_id).id, FELEMENTAL)

    def test_extra_applies_to_current_tavern(self):
        """绑定后打出 Felemental: 酒馆既有随从恰 +4/+3（正效果 + 对照）。"""
        # 正: 有饰品 → 基准 +2/+1 + extra +2/+2
        g = make_game()
        a, _ = heroes(g)
        m = put_tavern(g, a)
        self.assertEqual((m.atk, m.health), (2, 3))
        bind(g, a)
        play(g, a, FELEMENTAL)
        self.assertEqual((m.atk, m.health),
                         (2 + BASE_ATK + EXTRA_ATK,
                          3 + BASE_HEALTH + EXTRA_HEALTH))
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        # 负对照: 同 setup 不绑饰品 → 只有基准 +2/+1
        g2 = make_game()
        a2, _ = heroes(g2)
        m2 = put_tavern(g2, a2)
        play(g2, a2, FELEMENTAL)
        self.assertEqual((m2.atk, m2.health),
                         (2 + BASE_ATK, 3 + BASE_HEALTH))
        self.assertEqual(buffs(a2), [(BASE_ATK, BASE_HEALTH)])

    def test_only_tavern_not_board(self):
        """正/负同方法: 酒馆随从吃 extra，本人棋盘随从不受影响。"""
        g = make_game()
        a, _ = heroes(g)
        tavern = put_tavern(g, a)
        board = put_board(g, a)
        board_stats = (board.atk, board.health)
        bind(g, a)
        play(g, a, FELEMENTAL)
        self.assertEqual((tavern.atk, tavern.health), (6, 6))
        self.assertEqual((board.atk, board.health), board_stats)

    def test_extra_persists_to_future_tavern_entries(self):
        """绑定 + 空酒馆打出后，新入馆随从经持久面拿到基准 + extra。"""
        g = make_game()
        a, _ = heroes(g)
        a.tavern.clear()
        self.assertEqual(a.tavern, [])
        bind(g, a)
        play(g, a, FELEMENTAL)
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        fresh = put_tavern(g, a)
        self.assertEqual((fresh.atk, fresh.health),
                         (2 + BASE_ATK + EXTRA_ATK,
                          3 + BASE_HEALTH + EXTRA_HEALTH))

    def test_refresh_applies_both_persistent_buffs(self):
        """真实 refresh_tavern 后，酒馆内每只随从都带两份额外/基准增益。"""
        g = make_game()
        a, _ = heroes(g)
        bind(g, a)
        play(g, a, FELEMENTAL)
        g.refresh_tavern(a)
        self.assertTrue(a.tavern)
        checked = 0
        for e in a.tavern:
            d = get_db().get(e.card_id)
            if d is None or d.card_type != CardType.MINION:
                continue
            checked += 1
            self.assertEqual(e.atk - d.atk, BASE_ATK + EXTRA_ATK, e.card_id)
            self.assertEqual(e.health - d.health,
                             BASE_HEALTH + EXTRA_HEALTH, e.card_id)
        self.assertGreater(checked, 0)

    def test_pre_bind_felemental_not_retroactive(self):
        """绑定前打出的 Felemental 不追溯; 绑定后的才吃 extra。"""
        g = make_game()
        a, _ = heroes(g)
        m = put_tavern(g, a)
        play(g, a, FELEMENTAL)                      # 绑定前
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH)])
        self.assertEqual((m.atk, m.health), (4, 4))
        bind(g, a)
        play(g, a, FELEMENTAL)                      # 绑定后
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        self.assertEqual((m.atk, m.health),
                         (2 + 2 * BASE_ATK + EXTRA_ATK,
                          3 + 2 * BASE_HEALTH + EXTRA_HEALTH))

    def test_golden_felemental_extra_per_trigger(self):
        """金色 Felemental 每次触发各计一次 → extra ×2（正 + 负对照）。"""
        g = make_game()
        a, _ = heroes(g)
        m = put_tavern(g, a)
        bind(g, a)
        play(g, a, FELEMENTAL_GOLDEN, golden=True)
        self.assertEqual(buffs(a),
                         [(BASE_ATK, BASE_HEALTH), (EXTRA_ATK, EXTRA_HEALTH),
                          (BASE_ATK, BASE_HEALTH), (EXTRA_ATK, EXTRA_HEALTH)])
        self.assertEqual((m.atk, m.health),
                         (2 + 2 * BASE_ATK + 2 * EXTRA_ATK,
                          3 + 2 * BASE_HEALTH + 2 * EXTRA_HEALTH))
        # 负对照: 同一金色卡、无饰品 → 只有两次基准
        g2 = make_game()
        a2, _ = heroes(g2)
        m2 = put_tavern(g2, a2)
        play(g2, a2, FELEMENTAL_GOLDEN, golden=True)
        self.assertEqual(buffs(a2), [(BASE_ATK, BASE_HEALTH),
                                     (BASE_ATK, BASE_HEALTH)])
        self.assertEqual((m2.atk, m2.health),
                         (2 + 2 * BASE_ATK, 3 + 2 * BASE_HEALTH))

    def test_owner_isolation(self):
        """本人饰品只统计本人战吼: 对手打出不触发; 本人打出仍生效（正对照）。"""
        g = make_game()
        a, b = heroes(g)
        ma = put_tavern(g, a)
        mb = put_tavern(g, b)
        bind(g, a)
        play(g, b, FELEMENTAL)                      # 对手的战吼
        self.assertEqual(buffs(a), [])              # 本人零增益
        self.assertEqual((ma.atk, ma.health), (2, 3))
        self.assertEqual(buffs(b), [(BASE_ATK, BASE_HEALTH)])
        self.assertEqual((mb.atk, mb.health), (4, 4))   # 对手只有自己的基准
        # 正对照: 本人打出自己的 Felemental → extra 只加到本人酒馆
        play(g, a, FELEMENTAL)
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        self.assertEqual((ma.atk, ma.health), (6, 6))
        self.assertEqual(buffs(b), [(BASE_ATK, BASE_HEALTH)])
        self.assertEqual((mb.atk, mb.health), (4, 4))   # 对手不受影响

    def test_non_felemental_battlecry_does_not_trigger(self):
        """非家族战吼不触发 extra; 家族战吼仍生效（同 setup 正对照）。"""
        g = make_game()
        a, _ = heroes(g)
        m = put_tavern(g, a)
        bind(g, a)
        play(g, a, BATTLECRY_OTHER)
        self.assertEqual(buffs(a), [])
        self.assertEqual((m.atk, m.health), (2, 3))
        # 正对照: 同一绑定下换成家族战吼 → 基准 + extra 都落地
        play(g, a, FELEMENTAL)
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        self.assertEqual((m.atk, m.health), (6, 6))

    def test_second_felemental_stacks_extra(self):
        """同一局内第二只 Felemental 仍吃 extra（非一次性/每回合限制）。"""
        g = make_game()
        a, _ = heroes(g)
        m = put_tavern(g, a)
        bind(g, a)
        play(g, a, FELEMENTAL)
        play(g, a, FELEMENTAL)
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH),
                                    (BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        self.assertEqual((m.atk, m.health), (10, 9))

    def test_full_hand_queues_delivered_card(self):
        """满手时交付走等待队列（不丢失），且交付的关联卡可正常打出。"""
        g = make_game()
        a, _ = heroes(g)
        a.hand.extend(g.create_spell(HAND_FILLER, controller=a)
                      for _ in range(C.HAND_SIZE))
        self.assertEqual(len(a.hand), C.HAND_SIZE)
        bind(g, a)
        self.assertNotIn(FELEMENTAL, hand_ids(a))
        self.assertIn(FELEMENTAL,
                      [e.card_id for h, e in g.pending_hand_queue if h is a])
        # 腾出手牌位 → 等待队列交付，且 extra 监听已接线（正效果）
        a.hand.pop()
        entry = next((h, e) for h, e in g.pending_hand_queue
                     if h is a and e.card_id == FELEMENTAL)
        g.pending_hand_queue.remove(entry)
        self.assertTrue(g.pending_hand_add(a, entry[1]))
        self.assertIn(FELEMENTAL, hand_ids(a))
        m = put_tavern(g, a)
        self.assertTrue(g.play_minion(a, entry[1]))
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        self.assertEqual((m.atk, m.health), (6, 6))

    def test_same_seed_determinism(self):
        """同 seed 同序列 → 酒馆 Buff 面完全一致（无 random 依赖）。"""
        def run():
            g = make_game(seed=4242)
            a, _ = heroes(g)
            put_tavern(g, a)
            bind(g, a)
            play(g, a, FELEMENTAL)
            play(g, a, FELEMENTAL_GOLDEN, golden=True)
            return buffs(a)

        self.assertEqual(run(), run())
        self.assertEqual(run(), [(BASE_ATK, BASE_HEALTH),
                                 (EXTRA_ATK, EXTRA_HEALTH),
                                 (BASE_ATK, BASE_HEALTH),
                                 (EXTRA_ATK, EXTRA_HEALTH),
                                 (BASE_ATK, BASE_HEALTH),
                                 (EXTRA_ATK, EXTRA_HEALTH)])

    def test_no_battlecry_no_extra(self):
        """不打出 Felemental → 零酒馆 Buff（落空不消费）; 随后打出则生效。"""
        g = make_game()
        a, _ = heroes(g)
        m = put_tavern(g, a)
        bind(g, a)
        self.assertEqual(buffs(a), [])
        self.assertEqual((m.atk, m.health), (2, 3))
        # 正对照: 同一绑定下打出 Felemental → 基准 + extra 都落地
        play(g, a, FELEMENTAL)
        self.assertEqual(buffs(a), [(BASE_ATK, BASE_HEALTH),
                                    (EXTRA_ATK, EXTRA_HEALTH)])
        self.assertEqual((m.atk, m.health), (6, 6))

    def test_engine_family_base_id_golden_fallback(self):
        """金色家族身份按 TRIPLE_BASE_CARD_ID 回落（结构 + 行为）。"""
        g = make_game()
        a, _ = heroes(g)
        gold = g.create_minion(FELEMENTAL_GOLDEN, controller=a, golden=True)
        self.assertEqual(gold.get(GameTag.TRIPLE_BASE_CARD_ID), FELEMENTAL)
        self.assertEqual(B31._family_base_id(gold), FELEMENTAL)
        self.assertEqual(B31._family_base_id(
            g.create_minion(FELEMENTAL, controller=a)), FELEMENTAL)
        self.assertEqual(B31._family_base_id(
            g.create_minion(BATTLECRY_OTHER, controller=a)), BATTLECRY_OTHER)


# ══════════════ 注册表 / DEFERRED 台账（结构性） ══════════════


class TestBatch31Ledger(unittest.TestCase):
    """@engine-only — 注册表 / 商店池 / 参数 / 19 张 DEFERRED 台账守卫。

    结构性断言：钩子 no-op 后仍应通过（登记为引擎数据通道检查）。
    """

    def test_portrait_registered(self):
        self.assertIn(PORTRAIT, REGISTRY)
        self.assertIs(REGISTRY[PORTRAIT], B31.FelementalPortraitScript)
        self.assertTrue(hasattr(REGISTRY[PORTRAIT], "on_bind"))
        # 2026-09-18 解冻的两张（persist 原语 + 家族规则读取点）
        self.assertIs(REGISTRY["BG35_MagicItem_923"],
                      B31.BewitchedRibbonScript)
        self.assertIs(REGISTRY["BG36_MagicItem_362"],
                      B31.CyclistPortraitScript)
        self.assertTrue(hasattr(B31.BewitchedRibbonScript, "on_bind"))
        self.assertTrue(hasattr(B31.CyclistPortraitScript, "on_bind"))
        # 2026-09-19 解冻的 A 组 5 张（owner 权威序 → 卡面天然语言 +
        # §7.4.16 family_flags / hero.consume_policies）
        for tid, cls in ((B31.REWINDER_PORTRAIT, B31.RewinderPortraitScript),
                         (B31.BALLADIST_PORTRAIT,
                          B31.BalladistPortraitScript),
                         (B31.CZARINA_PORTRAIT, B31.CzarinaPortraitScript),
                         (B31.IMPLICATOR_PORTRAIT,
                          B31.ImplicatorPortraitScript),
                         (B31.FELBLOOD_PORTRAIT,
                          B31.FelbloodPortraitScript)):
            self.assertIs(REGISTRY[tid], cls)
            self.assertTrue(hasattr(cls, "on_bind"))
        # 824 的吞噬策略 / 987 的每回合交付各有一个额外的真实钩子
        self.assertTrue(hasattr(B31.ImplicatorPortraitScript, "on_bind"))
        self.assertTrue(hasattr(B31.BalladistPortraitScript, "start_of_turn"))
        import inspect as _inspect
        src = _inspect.getsource(B31.register)
        self.assertIn("BEWITCHED_RIBBON", src)
        self.assertIn("CYCLIST_PORTRAIT", src)
        for cname in ("REWINDER_PORTRAIT", "BALLADIST_PORTRAIT",
                      "CZARINA_PORTRAIT", "IMPLICATOR_PORTRAIT",
                      "FELBLOOD_PORTRAIT"):
            self.assertIn(cname, src)

    def test_deferred_not_registered_and_valid(self):
        db = get_db()
        for cid in B31._DEFERRED_IDS:
            self.assertNotIn(cid, REGISTRY, cid)
            self.assertIsNotNone(db.get(cid), cid)

    def test_deferred_batch_scope_partition(self):
        """作业范围 = 41 张，8 CORRECT + 19 DEFERRED + 14 迁出。"""
        # 440 / 804 / 822 已由 batch_trinkets32、821t2 已由 batch_misc_final
        # 注册 → 迁出本批 DEFERRED 台账（2026-09-02）
        # 828 / 944 已由 batch_trinkets33 注册（2026-09-13）→ 迁出
        # 274 已由 batch_trinkets34 注册（2026-09-13，§7.4.16 行为开关）→ 迁出
        # 804 已由 batch_trinkets35 注册（2026-09-13，§7.4.17 条件化战吼）→ 迁出
        # 803 已由 batch_trinkets36 注册（2026-09-13，§7.4.17 条件化战吼
        # 第二消费者）→ 迁出
        # 777 已由 batch_goose_lucky_egg 注册（2026-09-17，Transform +
        # 金色 T3/T4 池化发现）→ 迁出
        # 922 已由 batch_trinkets38 注册（2026-09-17，战斗内
        # `cast_spell_effect` 的 `spell_resolved` 消费）→ 迁出
        # 923 / 362 已由本批注册（2026-09-18，`Buff(persist=True)` 按来源
        # 跨战斗持久化 + `Game.add_persist_source`）→ 移出 DEFERRED 台账
        # 803（Kaboom Bot）/ 820（Impulsive）已由 batch_trinkets39 注册
        # （2026-09-18，§7.4.16 家族行为开关: 亡语伤害加成 +10 / 目标集合
        # 改为相邻 + 6/6 覆盖式交付）→ 迁出
        # 868 / 987 / 283 / 824 / 869 已由本批注册（2026-09-19，A 组 5 张:
        # owner 权威序——wiki 页均无 Notes → 卡面天然语言; "also give X"
        # 增量 = 同句既有量; 824 = hero.consume_policies 吞噬策略读取点）
        # → 移出 DEFERRED 台账
        # 418 / 825 / 971 / 179 已由 batch_family_races 注册（2026-09-21，
        # RACES 家族类型身份改写）→ 19 降为 15。
        self.assertEqual(len(B31._DEFERRED_IDS), 15)
        self.assertEqual(len(set(B31._DEFERRED_IDS)), 15)
        scope = (set(B31._DEFERRED_IDS)
                 | {PORTRAIT, BEWITCHED_RIBBON, CYCLIST_PORTRAIT,
                    "BG30_MagicItem_418", "BG30_MagicItem_825",
                    "BG30_MagicItem_971", "BG32_MagicItem_179"}
                 | {"BG30_MagicItem_440", "BG30_MagicItem_804",
                    "BG30_MagicItem_822", "BG30_MagicItem_821t2",
                    "BG30_MagicItem_828", "BG30_MagicItem_944",
                    "BG32_MagicItem_274", "BG32_MagicItem_804",
                    "BG32_MagicItem_803", "BG30_MagicItem_777",
                    "BG32_MagicItem_933", "BG35_MagicItem_922",
                    "BG30_MagicItem_803", "BG32_MagicItem_820",
                    "BG30_MagicItem_868", "BG30_MagicItem_987",
                    "BG32_MagicItem_283", "BG32_MagicItem_824",
                    "BG30_MagicItem_869"})
        self.assertEqual(len(scope), 41)
        self.assertNotIn(PORTRAIT, B31._DEFERRED_IDS)
        # 38 张全部在商店本体池（spell_school 11/12）
        pool = {d.id: d for d in get_db().trinket_offer_pool()}
        for cid in scope:
            self.assertIn(cid, pool, cid)
            self.assertIn(pool[cid].spell_school, (11, 12), cid)

    def test_deferred_ledger_documents_every_id(self):
        """台账完整性: 模块 docstring 必须逐张记档（防静默遗漏）。"""
        text = BATCH_FILE.read_text(encoding="utf-8")
        for cid in (set(B31._DEFERRED_IDS)
                    | {PORTRAIT, BEWITCHED_RIBBON, CYCLIST_PORTRAIT,
                       "BG30_MagicItem_868", "BG30_MagicItem_987",
                       "BG32_MagicItem_283", "BG32_MagicItem_824",
                       "BG30_MagicItem_869"}):
            self.assertIn(cid, text, f"{cid} 未在 batch_trinkets31 记档")

    def test_deferred_classes_have_no_hooks(self):
        """DEFERRED 类不得携带任何引擎钩子（否则是隐性第三态）。"""
        hook_names = {"on_bind", "start_of_turn", "end_of_turn",
                      "start_of_combat", "avenge", "battlecry",
                      "deathrattle", "rally", "activate", "hero_power",
                      "on_sell", "on_summon", "on_play", "atk", "health"}
        with_hooks = set()
        for name, obj in vars(B31).items():
            if not isinstance(obj, type) or obj.__module__ != B31.__name__:
                continue
            if any(hasattr(obj, hook) for hook in hook_names):
                with_hooks.add(name)
        self.assertEqual(with_hooks, {"FelementalPortraitScript",
                                      "BewitchedRibbonScript",
                                      "CyclistPortraitScript",
                                      "RewinderPortraitScript",
                                      "BalladistPortraitScript",
                                      "CzarinaPortraitScript",
                                      "ImplicatorPortraitScript",
                                      "FelbloodPortraitScript"})

    def test_carddef_num_params_pinned_to_text(self):
        db = get_db()
        d = db.get(PORTRAIT)
        self.assertEqual((d.num(0), d.num(1)),
                         (EXTRA_ATK, EXTRA_HEALTH))
        # 载荷基准（"give an extra" 的增量来源口径）
        fel = db.get(FELEMENTAL)
        self.assertEqual((fel.num(0), fel.num(1)),
                         (BASE_ATK, BASE_HEALTH))

    def test_related_card_definition_data_chain(self):
        db = get_db()
        d = db.get(PORTRAIT)
        self.assertIsNotNone(d.evolution_card_id)
        related = db.by_dbf(d.evolution_card_id)
        self.assertIsNotNone(related)
        self.assertEqual(related.id, FELEMENTAL)
        self.assertIsNotNone(db.golden_version(related))
        self.assertEqual(db.golden_version(related).id, FELEMENTAL_GOLDEN)


if __name__ == "__main__":
    unittest.main()

# ══════════════ BG35_MagicItem_923 Bewitched Ribbon 行为层 ══════════════


class TestBewitchedRibbon(unittest.TestCase):
    """Bewitched Ribbon: 每次施法给本人全部随从 +N/+N（战斗内更大且持久）。"""

    def _board(self, g, hero, ids=(TAVERN_MINION,)):
        return [put_board(g, hero, cid) for cid in ids]

    def test_recruit_cast_buffs_all_friendly_minions(self):
        """真实 play_spell: 全部己方存活随从各 +num(0)/+num(1)（对照无饰品）。"""
        g = make_game(seed=923)
        a, b = heroes(g)
        m = put_board(g, a, TAVERN_MINION)      # 2/3 Naga
        other = put_board(g, a, NON_NAGA)
        foe = put_board(g, b, TAVERN_MINION)
        bind(g, a, BEWITCHED_RIBBON)
        sp = g.create_spell(SHINY_RING, controller=a)
        a.hand.append(sp)
        sp.zone = Zone.HAND
        self.assertTrue(g.play_spell(a, sp))
        # 酒馆法术本体 +1/+1 + 饰品 +num(0)/+num(1)=1/1 → 合计 +2/+2
        self.assertEqual((m.atk, m.max_health), (4, 5))
        self.assertEqual((other.atk, other.max_health), (4, 4))
        # 对手棋盘不受影响
        self.assertEqual((foe.atk, foe.max_health), (2, 3))
        # 负对照: 同 setup 不绑饰品 → 只有法术本体 +1/+1
        g2 = make_game(seed=923)
        a2, _ = heroes(g2)
        m2 = put_board(g2, a2, TAVERN_MINION)
        sp2 = g2.create_spell(SHINY_RING, controller=a2)
        a2.hand.append(sp2)
        sp2.zone = Zone.HAND
        self.assertTrue(g2.play_spell(a2, sp2))
        self.assertEqual((m2.atk, m2.max_health), (3, 4))

    def test_recruit_buff_marked_persist_with_source_id(self):
        """招募期授予即 `persist=True` + `source_id` = 饰品 id（审计身份）。"""
        g = make_game(seed=924)
        a, _ = heroes(g)
        m = put_board(g, a, TAVERN_MINION)
        bind(g, a, BEWITCHED_RIBBON)
        sp = g.create_spell(SHINY_RING, controller=a)
        a.hand.append(sp)
        sp.zone = Zone.HAND
        g.play_spell(a, sp)
        ribbon_buffs = [x for x in m._buffs
                        if x.source_id == BEWITCHED_RIBBON]
        self.assertEqual([(x.atk, x.health) for x in ribbon_buffs], [(1, 1)])
        self.assertTrue(ribbon_buffs[0].persist)

    def test_combat_cast_uses_combat_amount_and_survives(self):
        """真实 run_combat 内 `cast_spell_effect`（Tide Raiser 亡语）:
        本次授予 = num(2)/num(4)（2/2）且跨战斗保留; 对照无饰品 = 回滚。"""
        def run(seed, with_ribbon):
            g = make_game(seed=seed)
            a, b = heroes(g)
            if with_ribbon:
                bind(g, a, BEWITCHED_RIBBON)
            tide = put_board(g, a, TIDE_RAISER)
            watch = put_board(g, a, TAVERN_MINION)
            g.summon(b, Minion("TEST_BIG", "BIG", atk=10, health=200))
            g.run_combat(a, b)
            return g, tide, watch

        g, tide, watch = run(925, True)
        # 战后棋盘复原会把死者放回（`dead=False`）——用战斗死亡快照证明
        # 亡语确实在**战斗内**触发（`hero._combat_dead_snaps`）
        self.assertIn(TIDE_RAISER,
                      [s["card_id"] for s in g.heroes[0]._combat_dead_snaps])
        self.assertEqual((watch.atk, watch.max_health), (2 + 2, 3 + 2))
        self.assertEqual([(x.atk, x.health) for x in watch._buffs
                          if x.persist], [(2, 2)])
        g2, tide2, watch2 = run(925, False)
        self.assertIn(TIDE_RAISER,
                      [s["card_id"] for s in g2.heroes[0]._combat_dead_snaps])
        self.assertEqual((watch2.atk, watch2.max_health), (2, 3))
        self.assertEqual([x for x in watch2._buffs if x.persist], [])

    def test_combat_other_buffs_still_roll_back(self):
        """同一场战斗内非持久战内增益仍回滚（证明只重放 persist 附魔）。"""
        g = make_game(seed=926)
        a, b = heroes(g)
        bind(g, a, BEWITCHED_RIBBON)
        tide = put_board(g, a, TIDE_RAISER)
        watch = put_board(g, a, TAVERN_MINION)
        g.summon(b, Minion("TEST_BIG2", "BIG2", atk=10, health=200))

        def nonpersist(src, game, ctx):
            from hsrl2.actions.stats import Buff as BuffAction
            return [BuffAction(x, atk=9, health=9)
                    for x in list(src.controller.board)]

        watch.scripts = type("S", (), {
            "start_of_combat": staticmethod(nonpersist)})
        g.run_combat(a, b)
        # 持久 +2/+2 保留; 非持久 +9/+9 回滚
        self.assertEqual((watch.atk, watch.max_health), (2 + 2, 3 + 2))
        self.assertEqual([(x.atk, x.health) for x in watch._buffs],
                         [(2, 2)])

    def test_persist_channel_and_entity_persist_no_double_count(self):
        """交叉回归（2026-09-18 实测缺陷）: 同一实体既带
        `PERSIST_COMBAT_CHANGES`（例外 1，单实体全量）又吃到本饰品的
        `persist` 附魔（例外 4）时，两份增量各计一次——不得双计。
        棋盘 [Tide Raiser, Tarecgosa]: 亡语施放 Shifting Tide 给相邻
        Tarecgosa +2/+2（例外 1，Tarecgosa 自身 tag）+ 饰品给全部
        +2/+2（例外 4）→ 战后 Tarecgosa = 4/4 + 2/2 + 2/2 = 8/8。"""
        def run(seed, with_ribbon):
            g = make_game(seed=seed)
            a, b = heroes(g)
            if with_ribbon:
                bind(g, a, BEWITCHED_RIBBON)
            put_board(g, a, TIDE_RAISER)
            tar = put_board(g, a, TARECGOSA)
            self.assertTrue(tar.has(GameTag.PERSIST_COMBAT_CHANGES))
            g.summon(b, Minion("TEST_BIG6", "BIG6", atk=10, health=200))
            g.run_combat(a, b)
            return g, tar

        g, tar = run(930, True)
        self.assertEqual((tar.atk, tar.max_health), (4 + 2 + 2, 4 + 2 + 2))
        plain = [x for x in tar._buffs if not x.persist]
        kept = [x for x in tar._buffs if x.persist]
        self.assertEqual([(x.atk, x.health) for x in plain], [(2, 2)])
        self.assertEqual([(x.atk, x.health) for x in kept], [(2, 2)])
        self.assertEqual([x.source_id for x in kept], [BEWITCHED_RIBBON])
        # 对照（无饰品）: 只有例外 1 的 Shifting Tide +2/+2
        g2, tar2 = run(930, False)
        self.assertEqual((tar2.atk, tar2.max_health), (4 + 2, 4 + 2))
        self.assertEqual([x for x in tar2._buffs if x.persist], [])

    def test_opponent_cast_does_not_trigger(self):
        """owner 隔离: 对手施放法术不触发本人饰品。"""
        g = make_game(seed=927)
        a, b = heroes(g)
        mine = put_board(g, a, TAVERN_MINION)
        bind(g, a, BEWITCHED_RIBBON)
        sp = g.create_spell(SHINY_RING, controller=b)
        b.hand.append(sp)
        sp.zone = Zone.HAND
        self.assertTrue(g.play_spell(b, sp))
        self.assertEqual((mine.atk, mine.max_health), (2, 3))

    def test_empty_board_cast_no_error(self):
        """空板落空不报错; 之后入场随从不再追溯。"""
        g = make_game(seed=928)
        a, _ = heroes(g)
        bind(g, a, BEWITCHED_RIBBON)
        sp = g.create_spell(SHINY_RING, controller=a)
        a.hand.append(sp)
        sp.zone = Zone.HAND
        self.assertTrue(g.play_spell(a, sp))
        m = put_board(g, a, TAVERN_MINION)
        self.assertEqual((m.atk, m.max_health), (2, 3))

    def test_num_values_match_card_text(self):
        """数值权威: num(0..4) = 1/1/2/None/2（文本 {0}{1}{2}{4}）。"""
        d = get_db().get(BEWITCHED_RIBBON)
        self.assertEqual(tuple(d.num(i) for i in range(5)),
                         (1, 1, 2, None, 2))


# ══════════════ BG36_MagicItem_362 Cyclist Portrait 行为层 ══════════════


class TestCyclistPortrait(unittest.TestCase):
    """Cyclist Portrait: Showy Cyclist 亡语给的属性跨战斗保留。"""

    def test_bind_delivers_showy_cyclist(self):
        """on_bind 经数据链交付恰好 1 张 BG31_925（只进本人手牌）。"""
        g = make_game(seed=362)
        a, b = heroes(g)
        self.assertEqual(hand_ids(a).count(SHOWY_CYCLIST), 0)
        bind(g, a, CYCLIST_PORTRAIT)
        self.assertEqual(hand_ids(a).count(SHOWY_CYCLIST), 1)
        self.assertEqual(hand_ids(b).count(SHOWY_CYCLIST), 0)
        d = get_db().get(CYCLIST_PORTRAIT)
        self.assertEqual(get_db().by_dbf(d.evolution_card_id).id,
                         SHOWY_CYCLIST)

    def test_rule_matches_family_including_golden(self):
        """家族规则命中基础 + 金色 + 对手隔离。"""
        g = make_game(seed=363)
        a, b = heroes(g)
        bind(g, a, CYCLIST_PORTRAIT)
        base = g.create_minion(SHOWY_CYCLIST, controller=a)
        gold = g.create_minion(SHOWY_CYCLIST, controller=a, golden=True)
        other = g.create_minion(NON_NAGA, controller=a)
        foe = g.create_minion(SHOWY_CYCLIST, controller=b)
        self.assertEqual(gold.get(GameTag.TRIPLE_BASE_CARD_ID), SHOWY_CYCLIST)
        # 金色独立卡定义按名核实（SOP: 禁止凭记忆写 id）
        self.assertEqual(get_db().golden_version(
            get_db().get(SHOWY_CYCLIST)).id, B31.SHOWY_CYCLIST_GOLDEN)
        self.assertTrue(g.minion_persist_source(a, base))
        self.assertTrue(g.minion_persist_source(a, gold))
        self.assertFalse(g.minion_persist_source(a, other))
        self.assertFalse(g.minion_persist_source(b, foe))
        self.assertEqual(g.persist_source_id(a, base), CYCLIST_PORTRAIT)
        self.assertEqual(g.persist_source_id(a, other), "")

    def test_combat_deathrattle_stats_survive(self):
        """真实 run_combat: 死亡 Showy Cyclist 的亡语增量跨战斗保留。"""
        def run(seed, with_portrait):
            g = make_game(seed=seed)
            a, b = heroes(g)
            if with_portrait:
                bind(g, a, CYCLIST_PORTRAIT)
            cyc = put_board(g, a, SHOWY_CYCLIST)      # 4/2 Naga
            naga = put_board(g, a, TAVERN_MINION)     # 2/3 Naga
            g.summon(b, Minion("TEST_BIG3", "BIG3", atk=10, health=200))
            g.run_combat(a, b)
            return g, cyc, naga

        g, cyc, naga = run(364, True)
        # 战斗死亡快照证明亡语在战斗内触发（战后复原点会清 DEAD）
        self.assertIn(SHOWY_CYCLIST,
                      [s["card_id"] for s in g.heroes[0]._combat_dead_snaps])
        # Showy Cyclist num(1)/num(3)=2/1（0 施法）→ +2/+1 保留
        self.assertEqual((naga.atk, naga.max_health), (4, 4))
        self.assertEqual([(x.atk, x.health) for x in naga._buffs
                          if x.persist], [(2, 1)])
        self.assertEqual([x.source_id for x in naga._buffs if x.persist],
                         [CYCLIST_PORTRAIT])
        g2, cyc2, naga2 = run(364, False)
        self.assertIn(SHOWY_CYCLIST,
                      [s["card_id"] for s in g2.heroes[0]._combat_dead_snaps])
        self.assertEqual((naga2.atk, naga2.max_health), (2, 3))
        self.assertEqual([x for x in naga2._buffs if x.persist], [])

    def test_only_showy_cyclist_source_persists(self):
        """负对照: 非 Showy Cyclist 的亡语增量仍随战斗回滚。"""
        g = make_game(seed=365)
        a, b = heroes(g)
        bind(g, a, CYCLIST_PORTRAIT)
        watch = put_board(g, a, TAVERN_MINION)

        def dr(src, game, ctx):
            from hsrl2.actions.stats import Buff as BuffAction
            return BuffAction(watch, atk=6, health=6)

        watch.scripts = type("S", (), {"deathrattle": staticmethod(dr)})
        g.summon(b, Minion("TEST_BIG4", "BIG4", atk=10, health=200))
        g.run_combat(a, b)
        self.assertIn(TAVERN_MINION,
                      [s["card_id"] for s in g.heroes[0]._combat_dead_snaps])
        self.assertEqual((watch.atk, watch.max_health), (2, 3))
        self.assertEqual([x for x in watch._buffs if x.persist], [])

    def test_rule_inactive_after_trinket_leaves(self):
        """饰品离场（替换注销）后家族规则失效 → 亡语增量回滚。"""
        g = make_game(seed=366)
        a, b = heroes(g)
        e = bind(g, a, CYCLIST_PORTRAIT)
        cyc = put_board(g, a, SHOWY_CYCLIST)
        naga = put_board(g, a, TAVERN_MINION)
        a.trinkets.remove(e)
        self.assertFalse(g.minion_persist_source(a, cyc))
        g.summon(b, Minion("TEST_BIG5", "BIG5", atk=10, health=200))
        g.run_combat(a, b)
        self.assertIn(SHOWY_CYCLIST,
                      [s["card_id"] for s in a._combat_dead_snaps])
        self.assertEqual((naga.atk, naga.max_health), (2, 3))

    def test_copied_cyclist_deathrattle_on_other_minion_not_persisted(self):
        """已备案边界（非静默近似）+ 来源过滤负对照: 把 Showy Cyclist 的
        亡语**复制到非家族随从**时，家族按卡 id 匹配 → 该次增量**不**持久
        （"Your Showy Cyclists' Deathrattles" 的卡身份口径; 复制语义无权威，
        见 362 docstring W-notes）。去掉引擎 id 过滤（M2 突变）后，
        `persist_source_id` 会误命中该非家族随从 → 本测试失败。"""
        g = make_game(seed=369)
        a, b = heroes(g)
        bind(g, a, CYCLIST_PORTRAIT)
        impostor = put_board(g, a, TAVERN_MINION)     # 非 Showy Cyclist
        # 复制来的同一亡语（脚本实体 = 真实载荷类）
        from hsrl2.scripts.batches.batch_deathrattle import ShowyCyclistScript
        impostor.scripts = ShowyCyclistScript
        self.assertFalse(g.minion_persist_source(a, impostor))
        self.assertEqual(g.persist_source_id(a, impostor), "")
        g.summon(b, Minion("TEST_BIG9", "BIG9", atk=10, health=200))
        g.run_combat(a, b)
        # 战斗死亡快照证明亡语确实触发过
        self.assertIn(TAVERN_MINION,
                      [s["card_id"] for s in a._combat_dead_snaps])
        # 但增量随战斗回滚（非家族 → 不持久）
        self.assertEqual((impostor.atk, impostor.max_health), (2, 3))
        self.assertEqual([x for x in impostor._buffs if x.persist], [])

    def test_non_combat_deathrattle_still_permanent(self):
        """正对照: 战斗外同一亡语照常永久（饰品不改变非战斗路径）。"""
        g = make_game(seed=367)
        a, _ = heroes(g)
        bind(g, a, CYCLIST_PORTRAIT)
        cyc = put_board(g, a, SHOWY_CYCLIST)
        naga = put_board(g, a, TAVERN_MINION)
        cyc.set(GameTag.HEALTH, 0)
        g.check_deaths()
        self.assertEqual((naga.atk, naga.max_health), (4, 4))

    def test_persist_source_api_validation(self):
        """W3: 写点校验 fail-loud（None hero / None source / 空集合）。"""
        from hsrl2.game import GameStateError
        g = make_game(seed=368)
        a, _ = heroes(g)
        e = bind(g, a, CYCLIST_PORTRAIT)
        with self.assertRaises(GameStateError):
            g.add_persist_source(None, e, {SHOWY_CYCLIST})
        with self.assertRaises(GameStateError):
            g.add_persist_source(a, None, {SHOWY_CYCLIST})
        with self.assertRaises(GameStateError):
            g.add_persist_source(a, e, set())
        # 重复登记合并集合（不产生重复条目）
        before = len(a.persist_sources)
        g.add_persist_source(a, e, {SHOWY_CYCLIST})
        self.assertEqual(len(a.persist_sources), before)

    def test_num_values_match_card_text(self):
        """362 无模板参数（数值由载荷 CardDef 提供）。"""
        d = get_db().get(CYCLIST_PORTRAIT)
        self.assertEqual(tuple(d.num(i) for i in range(5)),
                         (None, None, None, None, None))


# ══════════════════════════════════════════════════════════════════════
# 2026-09-19 解冻 A 组 5 张的行为层（真实路径 + 负对照 + 变异敏感）
# ══════════════════════════════════════════════════════════════════════

REWINDER_PORTRAIT = "BG30_MagicItem_868"
BALLADIST_PORTRAIT = "BG30_MagicItem_987"
CZARINA_PORTRAIT = "BG32_MagicItem_283"
IMPLICATOR_PORTRAIT = "BG32_MagicItem_824"
FELBLOOD_PORTRAIT = "BG30_MagicItem_869"
CHARGING_CZARINA = "BG28_741"
LOVESICK_BALLADIST = "BG26_814"
SOUL_REWINDER = "BG26_174"
WRATH_WEAVER = "BGS_004"
FALSE_IMPLICATOR = "BG29_140"
SLIMY_FELBLOOD = "BG29_873"
FIERY_FELBLOOD = "BG29_877"
URZUL = "BG21_004"                    # Insatiable Ur'zul（恶魔吞噬路径）


def _plain(name, atk, health, **kw):
    return Minion(f"TEST_{name}", name, atk=atk, health=health, **kw)


def cast_tavern_spell(game, hero, spell_id="BG28_805"):
    """真实施放一张未注册脚本的池法术（驱动 TAVERN_SPELL_CAST）。"""
    assert game.spell_pool.acquire(spell_id)
    s = game.create_spell(spell_id, controller=hero)
    hero.hand.append(s)
    s.zone = Zone.HAND
    assert game.play_spell(hero, s)
    return s


def play_battlecry(game, hero, card_id, target, golden=False):
    """真实打出战吼随从并在 PendingChoice 中选 target。"""
    m = game.create_minion(card_id, controller=hero, golden=golden)
    game.pending_hand_add(hero, m)
    assert game.play_minion(hero, m)
    if game.pending_choices:
        pc = game.pending_choices.pop(0)
        pc.choose(pc.options.index(target))
    return m


def slay(game, m):
    """真实死亡路径（亡语/Titus/复生/Avenge）。"""
    m.health = 0
    game._process_single_death(m)


def clear_tavern(hero):
    """清空酒馆（测试用: 只保留用例自建的候选）。

    `start_game()` 会从池中抽 4 张默认随从入馆（Rot Hide Gnoll 等），
    会稀释"最高生命"断言的候选域——消费策略断言前必须清空。
    """
    for e in list(hero.tavern):
        e.zone = Zone.REMOVED
    hero.tavern.clear()


class TestRewinderPortrait(unittest.TestCase):
    """868: "Your Soul Rewinders also gain Attack"（增量 = 同句 Health 额）。"""

    def test_bind_delivers_soul_rewinder_and_wrath_weaver(self):
        g = make_game(seed=3101)
        a, b = heroes(g)
        self.assertEqual(hand_ids(a).count(SOUL_REWINDER), 0)
        self.assertEqual(hand_ids(a).count(WRATH_WEAVER), 0)
        bind(g, a, REWINDER_PORTRAIT)
        self.assertEqual(hand_ids(a).count(SOUL_REWINDER), 1)
        self.assertEqual(hand_ids(a).count(WRATH_WEAVER), 1)
        self.assertEqual(hand_ids(b).count(SOUL_REWINDER), 0)
        self.assertEqual(hand_ids(b).count(WRATH_WEAVER), 0)

    def test_damage_grants_attack_and_health(self):
        # 37.0: Soul Rewinder 官方文本 "+{2} Health"（num(2)=2；36.2.2 +1）
        d = get_db().get(SOUL_REWINDER)
        gain = d.num(2)
        # 正: 有饰品 → +gain 攻且 +gain 血（"also gain Attack" = 同句 Health 额）
        g = make_game(seed=3102)
        a, _ = heroes(g)
        bind(g, a, REWINDER_PORTRAIT)
        r = put_board(g, a, SOUL_REWINDER)
        a.take_damage(5)
        self.assertEqual((r.atk, r.max_health),
                         (d.atk + gain, d.health + gain))
        # 负对照: 同 setup 不绑 → 只有 +gain 血（atk 不变）
        g2 = make_game(seed=3102)
        a2, _ = heroes(g2)
        r2 = put_board(g2, a2, SOUL_REWINDER)
        a2.take_damage(5)
        self.assertEqual((r2.atk, r2.max_health), (d.atk, d.health + gain))

    def test_golden_mirrors_golden_gain(self):
        g = make_game(seed=3103)
        a, _ = heroes(g)
        d = get_db().get(SOUL_REWINDER)
        dg = get_db().get(SOUL_REWINDER + "_G")
        gain = d.num(2)
        gain_g = dg.num(2)
        bind(g, a, REWINDER_PORTRAIT)
        r = put_board(g, a, SOUL_REWINDER)
        r2 = g.create_minion(SOUL_REWINDER, controller=a, golden=True)
        g.summon(a, r2)
        a.take_damage(5)
        self.assertEqual((r.atk, r.max_health),
                         (d.atk + gain, d.health + gain))
        self.assertEqual((r2.atk, r2.max_health),
                         (dg.atk + gain_g, dg.health + gain_g))

    def test_opponent_trinket_does_not_buff_my_rewinder(self):
        g = make_game(seed=3104)
        a, b = heroes(g)
        d = get_db().get(SOUL_REWINDER)
        bind(g, b, REWINDER_PORTRAIT)          # 对手持有饰品
        r = put_board(g, a, SOUL_REWINDER)
        a.take_damage(5)
        self.assertEqual((r.atk, r.max_health), (d.atk, d.health + d.num(2)))

    def test_rule_lapses_after_trinket_leaves(self):
        g = make_game(seed=3105)
        a, _ = heroes(g)
        d = get_db().get(SOUL_REWINDER)
        e = bind(g, a, REWINDER_PORTRAIT)
        r = put_board(g, a, SOUL_REWINDER)
        a.trinkets.remove(e)                    # 饰品被替换/移除
        a.take_damage(5)
        self.assertEqual((r.atk, r.max_health), (d.atk, d.health + d.num(2)))

    def test_num_params_absent(self):
        d = get_db().get(REWINDER_PORTRAIT)
        self.assertEqual(tuple(d.num(i) for i in range(5)),
                         (None, None, None, None, None))
        self.assertEqual(get_db().by_dbf(d.evolution_card_id).id, SOUL_REWINDER)


class TestBalladistPortrait(unittest.TestCase):
    """987: "also give Attack"（增量 = num(1)+GOLD_SPENT）+ 每回合再得 1 张。"""

    def _pirate(self, g, a, name="P"):
        m = _plain(name, 3, 3, race=Race.PIRATE)
        g.summon(a, m)
        return m

    def test_bind_delivers_lovesick_balladist(self):
        g = make_game(seed=3201)
        a, b = heroes(g)
        bind(g, a, BALLADIST_PORTRAIT)
        self.assertEqual(hand_ids(a).count(LOVESICK_BALLADIST), 1)
        self.assertEqual(hand_ids(b).count(LOVESICK_BALLADIST), 0)

    def _health_gain(self) -> int:
        """Lovesick Balladist 战吼 Health 增量（37.0: num(1)=2；36.2.2 为 1）。"""
        return get_db().get(LOVESICK_BALLADIST).num(1)

    def test_battlecry_grants_attack_and_health(self):
        gain = self._health_gain()
        # 正: 有饰品 → +gain 攻且 +gain 血（0 支出）
        g = make_game(seed=3202)
        a, _ = heroes(g)
        bind(g, a, BALLADIST_PORTRAIT)
        p = self._pirate(g, a)
        play_battlecry(g, a, LOVESICK_BALLADIST, p)
        self.assertEqual((p.atk, p.max_health), (3 + gain, 3 + gain))
        # 负对照: 无饰品 → 只有 +gain 血
        g2 = make_game(seed=3202)
        a2, _ = heroes(g2)
        p2 = self._pirate(g2, a2)
        play_battlecry(g2, a2, LOVESICK_BALLADIST, p2)
        self.assertEqual((p2.atk, p2.max_health), (3, 3 + gain))

    def test_improved_by_gold_spent_scales_both_stats(self):
        gain = self._health_gain()
        g = make_game(seed=3203)
        a, _ = heroes(g)
        bind(g, a, BALLADIST_PORTRAIT)
        p = self._pirate(g, a)
        a.gold = 10
        g.spend_gold(a, 3)
        play_battlecry(g, a, LOVESICK_BALLADIST, p)
        step = gain + 3                    # num(1) + 已花费金币
        self.assertEqual((p.atk, p.max_health), (3 + step, 3 + step))

    def test_golden_twice_same_target(self):
        gain = self._health_gain()
        g = make_game(seed=3204)
        a, _ = heroes(g)
        bind(g, a, BALLADIST_PORTRAIT)
        p = self._pirate(g, a)
        a.gold = 10
        g.spend_gold(a, 2)
        play_battlecry(g, a, LOVESICK_BALLADIST, p, golden=True)
        # 2 次触发 × 每次 (num(1)+2)
        step = 2 * (gain + 2)
        self.assertEqual((p.atk, p.max_health), (3 + step, 3 + step))

    def test_non_pirate_not_in_candidates(self):
        g = make_game(seed=3205)
        a, _ = heroes(g)
        bind(g, a, BALLADIST_PORTRAIT)
        beast = _plain("Z", 3, 3, race=Race.BEAST)
        g.summon(a, beast)
        m = g.create_minion(LOVESICK_BALLADIST, controller=a)
        g.pending_hand_add(a, m)
        g.play_minion(a, m)
        pc = g.pending_choices.pop(0)
        self.assertNotIn(beast, pc.options)
        pc.choose(0)

    def test_start_of_turn_grants_another(self):
        g = make_game(seed=3206)
        a, b = heroes(g)
        e = bind(g, a, BALLADIST_PORTRAIT)
        self.assertEqual(hand_ids(a).count(LOVESICK_BALLADIST), 1)
        B31.BalladistPortraitScript.start_of_turn(e, g, {"hero": a})
        self.assertEqual(hand_ids(a).count(LOVESICK_BALLADIST), 2)
        self.assertEqual(hand_ids(b).count(LOVESICK_BALLADIST), 0)

    def test_opponent_battlecry_not_buffed(self):
        g = make_game(seed=3207)
        a, b = heroes(g)
        bind(g, a, BALLADIST_PORTRAIT)          # 饰品在 A
        p = self._pirate(g, b, "PB")            # B 的 Pirate
        play_battlecry(g, b, LOVESICK_BALLADIST, p)
        self.assertEqual((p.atk, p.max_health), (3, 3 + self._health_gain()))


class TestCzarinaPortrait(unittest.TestCase):
    """283: "also give Health"（增量 = 同句 num(0) Attack 额）。"""

    def test_bind_delivers_charging_czarina(self):
        g = make_game(seed=3301)
        a, b = heroes(g)
        bind(g, a, CZARINA_PORTRAIT)
        self.assertEqual(hand_ids(a).count(CHARGING_CZARINA), 1)
        self.assertEqual(hand_ids(b).count(CHARGING_CZARINA), 0)

    def test_cast_grants_attack_and_health_to_divine_shield(self):
        # 正: 有饰品 → 圣盾随从 +4/+4
        g = make_game(seed=3302)
        a, _ = heroes(g)
        bind(g, a, CZARINA_PORTRAIT)
        cz = put_board(g, a, CHARGING_CZARINA)      # 自带圣盾
        plain = put_board(g, a, TAVERN_MINION)      # 无圣盾
        cast_tavern_spell(g, a)
        self.assertEqual((cz.atk, cz.max_health), (8, 5))   # 4+4 / 1+4
        self.assertEqual((plain.atk, plain.max_health), (2, 3))
        # 负对照: 无饰品 → 只 +4 攻
        g2 = make_game(seed=3302)
        a2, _ = heroes(g2)
        cz2 = put_board(g2, a2, CHARGING_CZARINA)
        cast_tavern_spell(g2, a2)
        self.assertEqual((cz2.atk, cz2.max_health), (8, 1))

    def test_golden_eight_eight(self):
        g = make_game(seed=3303)
        a, _ = heroes(g)
        bind(g, a, CZARINA_PORTRAIT)
        cz = g.create_minion(CHARGING_CZARINA, controller=a, golden=True)
        g.summon(a, cz)
        cast_tavern_spell(g, a)
        self.assertEqual((cz.atk, cz.max_health), (16, 10))   # 8+8 / 2+8

    def test_needs_live_czarina_per_instance(self):
        """每只 Czarina 各自触发（per-instance 缩放）。"""
        g = make_game(seed=3304)
        a, _ = heroes(g)
        bind(g, a, CZARINA_PORTRAIT)
        cz = put_board(g, a, CHARGING_CZARINA)
        cast_tavern_spell(g, a)
        self.assertEqual((cz.atk, cz.max_health), (8, 5))
        # 第二只 Czarina 入场后再次施放 → 两只监听各对**全部**圣盾随从
        # 触发一次: cz 再 +8/+8；cz2（新入场）被两只各 +4/+4
        cz2 = put_board(g, a, CHARGING_CZARINA)
        cast_tavern_spell(g, a)
        self.assertEqual((cz.atk, cz.max_health), (16, 13))
        self.assertEqual((cz2.atk, cz2.max_health), (12, 9))

    def test_enemy_cast_no_trigger(self):
        g = make_game(seed=3305)
        a, b = heroes(g)
        bind(g, a, CZARINA_PORTRAIT)
        cz = put_board(g, a, CHARGING_CZARINA)
        cast_tavern_spell(g, b)                  # 对手施放
        self.assertEqual((cz.atk, cz.max_health), (4, 1))

    def test_opponent_trinket_does_not_help_my_czarina(self):
        g = make_game(seed=3306)
        a, b = heroes(g)
        bind(g, b, CZARINA_PORTRAIT)
        cz = put_board(g, a, CHARGING_CZARINA)
        cast_tavern_spell(g, a)
        self.assertEqual((cz.atk, cz.max_health), (8, 1))

    def test_num_params_absent(self):
        d = get_db().get(CZARINA_PORTRAIT)
        self.assertEqual(tuple(d.num(i) for i in range(5)),
                         (None, None, None, None, None))
        self.assertEqual(get_db().by_dbf(d.evolution_card_id).id,
                         CHARGING_CZARINA)


class TestImplicatorPortrait(unittest.TestCase):
    """824: "Your Demons always consume the highest-Health minion in the
    Tavern" + "Get 2 False Implicators"。"""

    def _tavern_pair(self, g, a, hi_health=9, lo_health=2):
        clear_tavern(a)
        lo = _plain("LO", 1, lo_health)
        hi = _plain("HI", 1, hi_health)
        g.add_tavern_entity(a, lo)
        g.add_tavern_entity(a, hi)
        return lo, hi

    def test_bind_delivers_exactly_two(self):
        g = make_game(seed=3401)
        a, b = heroes(g)
        bind(g, a, IMPLICATOR_PORTRAIT)
        self.assertEqual(hand_ids(a).count(FALSE_IMPLICATOR), 2)
        self.assertEqual(hand_ids(b).count(FALSE_IMPLICATOR), 0)

    def test_eot_consumes_highest_health(self):
        g = make_game(seed=3402)
        a, _ = heroes(g)
        bind(g, a, IMPLICATOR_PORTRAIT)
        imp = put_board(g, a, FALSE_IMPLICATOR)
        lo, hi = self._tavern_pair(g, a)
        g.run_script_hook(imp, "end_of_turn")
        self.assertNotIn(hi, a.tavern)
        self.assertIn(lo, a.tavern)
        self.assertEqual((imp.atk, imp.max_health), (2, 10))  # 1+1 / 1+9

    def test_without_trinket_selection_is_random(self):
        """负对照: 同 setup 不绑 → 随机（多 seed 下两种结果都出现）。"""
        outcomes = set()
        for seed in range(1, 41):
            g = make_game(seed=seed)
            a, _ = heroes(g)
            imp = put_board(g, a, FALSE_IMPLICATOR)
            lo, hi = self._tavern_pair(g, a, hi_health=9, lo_health=2)
            g.run_script_hook(imp, "end_of_turn")
            outcomes.add("hi" if hi not in a.tavern else "lo")
        self.assertEqual(outcomes, {"hi", "lo"})

    def test_with_trinket_always_highest_across_seeds(self):
        for seed in range(1, 41):
            g = make_game(seed=seed)
            a, _ = heroes(g)
            bind(g, a, IMPLICATOR_PORTRAIT)
            imp = put_board(g, a, FALSE_IMPLICATOR)
            lo, hi = self._tavern_pair(g, a, hi_health=9, lo_health=2)
            g.run_script_hook(imp, "end_of_turn")
            self.assertNotIn(hi, a.tavern, seed)
            self.assertIn(lo, a.tavern, seed)

    def test_tie_break_uses_rng_and_is_seed_deterministic(self):
        victims = []
        for _ in range(2):
            g = make_game(seed=3403)
            a, _ = heroes(g)
            bind(g, a, IMPLICATOR_PORTRAIT)
            imp = put_board(g, a, FALSE_IMPLICATOR)
            x = _plain("X", 1, 7)
            y = _plain("Y", 1, 7)
            g.add_tavern_entity(a, x)
            g.add_tavern_entity(a, y)
            g.run_script_hook(imp, "end_of_turn")
            victims.append(
                "x" if x not in a.tavern else ("y" if y not in a.tavern
                                               else "none"))
        self.assertEqual(victims[0], victims[1])
        self.assertIn(victims[0], ("x", "y"))

    def test_generic_demon_consume_path_reads_policy(self):
        """种族范围证明: 非 False Implicator 家族的恶魔同样命中策略。"""
        from hsrl2.actions.consume import ConsumeRandomTavernMinion
        g = make_game(seed=3404)
        a, _ = heroes(g)
        bind(g, a, IMPLICATOR_PORTRAIT)
        demon = put_board(g, a, URZUL)
        lo, hi = self._tavern_pair(g, a, hi_health=8, lo_health=1)
        ConsumeRandomTavernMinion(demon).do(g)
        self.assertNotIn(hi, a.tavern)
        self.assertIn(lo, a.tavern)

    def test_golden_jailer_activate_path_reads_policy(self):
        """消费方 2: `BG36_503_G` 金色 Soulkeeping Jailer activate。

        （金色分支自实现 `rng.choice`——2026-09-19 起统一走
        `Game.pick_consume_victim`; 20 seed 循环证明该站点也吃策略，
        变异回 `rng.choice` 必然失败。）
        """
        from hsrl2.scripts.batches.batch_activate import (
            SoulkeepingJailerGoldenScript)
        for seed in range(1, 21):
            g = make_game(seed=seed)
            a, _ = heroes(g)
            bind(g, a, IMPLICATOR_PORTRAIT)
            jailer = put_board(g, a, "BG36_503_G")   # 本身是恶魔（唯一恶魔）
            lo, hi = self._tavern_pair(g, a, hi_health=9, lo_health=2)
            SoulkeepingJailerGoldenScript.activate(jailer, g, {})
            self.assertNotIn(hi, a.tavern, seed)
            self.assertIn(lo, a.tavern, seed)

    def test_methodical_madness_consume_path_reads_policy(self):
        """消费方 3: `BG36_880` Methodical Madness 的
        `ConsumeRandomTavernWithKeywords`（2 次独立吞噬）。"""
        from hsrl2.scripts.batches.batch_spells_final import (
            ConsumeRandomTavernWithKeywords)
        for seed in range(1, 21):
            g = make_game(seed=seed)
            a, _ = heroes(g)
            bind(g, a, IMPLICATOR_PORTRAIT)
            demon = put_board(g, a, URZUL)
            lo, hi = self._tavern_pair(g, a, hi_health=8, lo_health=1)
            ConsumeRandomTavernWithKeywords(demon).do(g)
            self.assertNotIn(hi, a.tavern, seed)
            self.assertIn(lo, a.tavern, seed)

    def test_r309_quest_reward_consume_path_reads_policy(self):
        """消费方 4: `BG24_Reward_309` R309（左右端随从吞噬）——
        消费者是恶魔时命中策略（非恶魔仍随机，见 race-filter 负对照）。"""
        from hsrl2.scripts.batches.batch_quest_rewards import R309
        for seed in range(1, 21):
            g = make_game(seed=seed)
            a, _ = heroes(g)
            bind(g, a, IMPLICATOR_PORTRAIT)
            reward = g.create_entity("BG24_Reward_309", controller=a)
            a.quest_rewards.append(reward)
            g.run_script_hook(reward, "on_bind", ctx={"hero": a})
            put_board(g, a, URZUL)                 # 唯一（左=右端）恶魔
            lo, hi = self._tavern_pair(g, a, hi_health=8, lo_health=1)
            g.events.fire(g, "turn_end", turn=g.turn)
            self.assertNotIn(hi, a.tavern, seed)
            self.assertIn(lo, a.tavern, seed)

    def test_race_filter_non_demon_consumer_ignores_policy(self):
        """卡面范围 "Your **Demons**": 非恶魔吞噬者不吃策略（仍随机）。

        变异探针: 去掉 `pick_consume_victim` 的 `consumer.race in
        (DEMON, ALL)` 过滤 → 本测试 40 seed 全吞最高生命 → 失败。
        """
        from hsrl2.actions.consume import ConsumeRandomTavernMinion
        beast_card = "BG31_803"          # Buzzing Vermin 1/1 T1 野兽（池）
        outcomes = set()
        for seed in range(1, 41):
            g = make_game(seed=seed)
            a, _ = heroes(g)
            bind(g, a, IMPLICATOR_PORTRAIT)
            beast = put_board(g, a, beast_card)
            self.assertNotIn(beast.race, (Race.DEMON, Race.ALL))
            lo, hi = self._tavern_pair(g, a, hi_health=9, lo_health=2)
            ConsumeRandomTavernMinion(beast).do(g)
            outcomes.add("hi" if hi not in a.tavern else "lo")
        self.assertEqual(outcomes, {"hi", "lo"})

    def test_rule_lapses_after_trinket_leaves(self):
        g = make_game(seed=3405)
        a, _ = heroes(g)
        e = bind(g, a, IMPLICATOR_PORTRAIT)
        imp = put_board(g, a, FALSE_IMPLICATOR)
        lo, hi = self._tavern_pair(g, a)
        a.trinkets.remove(e)
        g.run_script_hook(imp, "end_of_turn")
        # 策略失效 → 随机；只断言两候选之一被吞（状态一致）
        self.assertEqual(
            (hi in a.tavern) + (lo in a.tavern), 1)

    def test_opponent_policy_isolation(self):
        g = make_game(seed=3406)
        a, b = heroes(g)
        bind(g, b, IMPLICATOR_PORTRAIT)         # 对手持有饰品
        imp = put_board(g, a, FALSE_IMPLICATOR)
        lo, hi = self._tavern_pair(g, a)
        g.run_script_hook(imp, "end_of_turn")
        self.assertEqual((hi in a.tavern) + (lo in a.tavern), 1)
        # B 的恶魔才吃策略（A 不吃）——用 A 的多次结果证明仍随机
        outcomes = set()
        for seed in range(1, 21):
            gg = make_game(seed=seed)
            aa, bb = heroes(gg)
            bind(gg, bb, IMPLICATOR_PORTRAIT)
            ii = put_board(gg, aa, FALSE_IMPLICATOR)
            l2, h2 = self._tavern_pair(gg, aa, hi_health=9, lo_health=2)
            gg.run_script_hook(ii, "end_of_turn")
            outcomes.add("hi" if h2 not in aa.tavern else "lo")
        self.assertEqual(outcomes, {"hi", "lo"})

    def test_consume_policy_api_validation(self):
        from hsrl2.game import GameStateError
        g = make_game(seed=3407)
        a, _ = heroes(g)
        with self.assertRaises(GameStateError):
            g.add_consume_policy(None, "highest_health")
        with self.assertRaises(GameStateError):
            g.add_consume_policy(a, "")
        with self.assertRaises(GameStateError):
            g.consume_policy(None)


class TestFelbloodPortrait(unittest.TestCase):
    """869: "Your Fiery and Slimy Felbloods give Attack and Health"。"""

    def test_bind_delivers_slimy_felblood(self):
        g = make_game(seed=3501)
        a, b = heroes(g)
        bind(g, a, FELBLOOD_PORTRAIT)
        self.assertEqual(hand_ids(a).count(SLIMY_FELBLOOD), 1)
        self.assertEqual(hand_ids(b).count(SLIMY_FELBLOOD), 0)

    def test_slimy_battlecry_gives_both_stats(self):
        # 正: 有饰品 → 馆内 +2/+2
        g = make_game(seed=3502)
        a, _ = heroes(g)
        bind(g, a, FELBLOOD_PORTRAIT)
        t = put_tavern(g, a)
        play(g, a, SLIMY_FELBLOOD)
        self.assertEqual((t.atk, t.max_health), (4, 5))
        # 负对照: 无饰品 → 只 +2 血
        g2 = make_game(seed=3502)
        a2, _ = heroes(g2)
        t2 = put_tavern(g2, a2)
        play(g2, a2, SLIMY_FELBLOOD)
        self.assertEqual((t2.atk, t2.max_health), (2, 5))

    def test_golden_slimy_four_four(self):
        g = make_game(seed=3503)
        a, _ = heroes(g)
        bind(g, a, FELBLOOD_PORTRAIT)
        t = put_tavern(g, a)
        play(g, a, SLIMY_FELBLOOD, golden=True)
        self.assertEqual((t.atk, t.max_health), (6, 7))   # +4/+4

    def test_fiery_deathrattle_gives_both_stats(self):
        # 正: 有饰品 → 真实死亡路径 +2/+2
        g = make_game(seed=3504)
        a, _ = heroes(g)
        bind(g, a, FELBLOOD_PORTRAIT)
        t = put_tavern(g, a)
        f = put_board(g, a, FIERY_FELBLOOD)
        slay(g, f)
        self.assertEqual((t.atk, t.max_health), (4, 5))
        # 负对照: 无饰品 → 只 +2 攻
        g2 = make_game(seed=3504)
        a2, _ = heroes(g2)
        t2 = put_tavern(g2, a2)
        f2 = put_board(g2, a2, FIERY_FELBLOOD)
        slay(g2, f2)
        self.assertEqual((t2.atk, t2.max_health), (4, 3))

    def test_golden_fiery_four_four(self):
        g = make_game(seed=3505)
        a, _ = heroes(g)
        bind(g, a, FELBLOOD_PORTRAIT)
        t = put_tavern(g, a)
        f = g.create_minion(FIERY_FELBLOOD, controller=a, golden=True)
        g.summon(a, f)
        slay(g, f)
        self.assertEqual((t.atk, t.max_health), (6, 7))   # +4/+4

    def test_opponent_tavern_unaffected(self):
        g = make_game(seed=3506)
        a, b = heroes(g)
        bind(g, a, FELBLOOD_PORTRAIT)
        tb = put_tavern(g, b)             # 对手酒馆
        play(g, a, SLIMY_FELBLOOD)
        self.assertEqual((tb.atk, tb.max_health), (2, 3))

    def test_both_families_flagged(self):
        """开关必须同时覆盖 Slimy（BG29_873）与 Fiery（BG29_877）两家族。"""
        g = make_game(seed=3507)
        a, _ = heroes(g)
        bind(g, a, FELBLOOD_PORTRAIT)
        self.assertTrue(g.family_flag(a, SLIMY_FELBLOOD, "felblood_give_attack_and_health"))
        self.assertTrue(g.family_flag(a, FIERY_FELBLOOD, "felblood_give_attack_and_health"))
        self.assertTrue(g.family_flag(a, FIERY_FELBLOOD + "_G",
                                      "felblood_give_attack_and_health"))
