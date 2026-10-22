"""批次 trinkets25 行为层测试（1 张饰品注册: BG35_MagicItem_702）。

本批 20 张中 4 张为 DEFERRED、15 张已由 `batch_unlock_final` /
`batch_trinkets30` / `batch_trinkets39` 等注册迁出
（台账见 `batch_trinkets25` 模块 docstring 与各类 docstring）——本文件只对
**唯一注册卡**写行为测试，另以结构性类守卫"注册/撤注册"二态与台账完整性。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）
  - 交付: `game.grant_card_copy_to_hand`（RULES §7.4.6; 满手
    `pending_hand_queue` 等待 RULES §3.3）
  - SoC: 真实 `game.run_combat`（`CombatScheduler._start_of_combat_phase`
    → `game.run_script_hook(trinket, "start_of_combat")`）+ 战斗内
    `start_of_combat` 探针（SoC 增益战后被战前快照复原，RULES §3.5）
  - 跨回合: 真实 `game.end_recruit_phase()`
  - 池: `minion_pool.available` / `total_remaining` 前后差

覆盖（SOP §16 空转测试判定法）: 每个行为测试**方法内**至少含一条正效果
断言（负对照/正对照同方法），owner 隔离（2 英雄），跨回合语义，满手入队，
战斗内探针 + 战后回滚，同 seed 重跑一致。**本批无** Discover / per-cast
双施 / 亡语 doubler 文本（4 张 DEFERRED 卡不注册），故无对应矩阵项。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.db import CardDB
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType, GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BATCH_FILE = (Path(__file__).resolve().parent.parent
              / "scripts" / "batches" / "batch_trinkets25.py")

# ── 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id） ──
BEAST_A = "BG31_803"      # Buzzing Vermin 1/1 T1 野兽（池; taunt+deathrattle）
BEAST_B = "BG31_809"      # Turquoise Skitterer 5/5 T5 野兽（池）
BEAST_C = "BG31_801"      # Forest Rover 1/1 T2 野兽（池）
NON_BEAST = "BG23_004"    # Deep-Sea Angler 2/3 T3 纳迦（池; 无关键词钩子）
MURLOC = "BG22_202"       # Tad 2/2 T2 鱼人（池）
AMALGAM = "BG27_080"      # Motley Phalanx 3/3 T4 全种族（池; ALL）
HAND_FILLER = "BG28_168"  # Shiny Ring（非池法术; 仅作满手占位）

# ── 本批 id ──
STEGODON = "BG35_MagicItem_702"
STEGODON_CARD = "BG33_840"        # 关联卡（唯一名解析目标; 非池 T4 野兽）

IMPLEMENTED = (STEGODON,)
DEFERRED = (
    "BG32_MagicItem_809",   # Gem Donation — "plays its Blood Gems" 无权威
    "BG32_MagicItem_823",   # Wax Imprinter — "(if possible)" 无权威
    # BG32_MagicItem_824 Implicator Portrait 已由 batch_trinkets31 注册
    # （2026-09-19——"Your Demons always consume the highest-Health minion
    # in the Tavern" = `hero.consume_policies` + `Game.pick_consume_victim`）
    # BG32_MagicItem_933 Weary Portrait 已由 batch_trinkets37 注册（2026-09-14）
    # BG32_MagicItem_820 Impulsive Portrait 已由 batch_trinkets39 注册
    # （2026-09-18——RULES §7.4.16 family_flags 目标集合改写; both/split
    # 口径按 wiki 无 Notes → 卡面天然语言裁定 = 全额逐目标）
    "BG35_MagicItem_812",   # Corrupted Tome — 三连奖励替换 + Darkmoon
)
# 已由 batch_unlock_final 注册（2026-09-15: consume 来源区域载荷 /
# last_minion_died 触发点 / add_card_aura / 关键词限定价格·展示位 /
# 战吼刷新 / death 事件血宝石生命）——迁出 DEFERRED 台账，仍计入
# 本批 20 张作业范围; BG32_MagicItem_830 由 batch_trinkets31 注册
# （家族 give 额外持久酒馆 Buff 镜像原语，2026-09-15）。
MIGRATED = (
    "BG32_MagicItem_891",   # Finley's Helmet（batch_trinkets30）
    "BG32_MagicItem_892",   # Vibrant Bubble（batch_trinkets30）
    "BG32_MagicItem_925",   # Hackerfin Portrait（batch_trinkets30）
    "BG35_MagicItem_431t",  # Thornspike Pauldron（batch_trinkets30）
    "BG35_MagicItem_156",   # Flaming Portrait（batch_misc_final，2026-09-02）
    "BG35_MagicItem_818",   # Mysterious Orb（batch_trinkets30）
    "BG32_MagicItem_902",   # Statue of Hir'eek
    "BG32_MagicItem_907",   # S'Thara Sticker
    "BG35_MagicItem_433",   # Vinespeaker Portrait
    "BG35_MagicItem_732",   # Soul Fermenter
    "BG35_MagicItem_743",   # Electrode Attractor
    "BG35_MagicItem_755",   # Chillmere Mosaic
    "BG32_MagicItem_830",   # Felemental Portrait（batch_trinkets31）
    "BG32_MagicItem_933",   # Weary Portrait（batch_trinkets37, 2026-09-14）
    "BG32_MagicItem_820",   # Impulsive Portrait（batch_trinkets39, 2026-09-18）
    # 824 Implicator Portrait 已由 batch_trinkets31 注册（2026-09-19——
    # "Your Demons always consume the highest-Health minion in the Tavern"
    # = `hero.consume_policies` + `Game.pick_consume_victim` 读取点）
    "BG32_MagicItem_824",
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 925) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str, position=None) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    assert game.summon(hero, m, position)
    return m


def soc_probe(game: Game, owner) -> dict:
    """战斗内 SoC 探针: 记录每个英雄在全部 SoC 钩子之后的 (card_id, 圣盾)。"""
    out: dict = {}

    def cb(g, hero=None, **kw):
        if hero is None:
            return
        out[hero] = [(m.card_id, m.has(GameTag.DIVINE_SHIELD))
                     for m in hero.board]

    game.events.register(Listener(event="start_of_combat", owner=owner,
                                  callback=cb))
    return out


def shield_map(entries) -> dict:
    """(card_id, has_DS) 列表 → {card_id: has_DS}（同名取首个出现值）。"""
    return {cid: has for cid, has in entries}


def hand_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.hand]


class TestStegodonPortrait(unittest.TestCase):
    """BG35_MagicItem_702 — Get a Stomping Stegodon. SoC: 最左两只野兽圣盾。"""

    def test_bind_grants_stegodon_plain_copy(self):
        g = make_game(7021)
        a, b = g.heroes
        total_before = g.minion_pool.total_remaining()
        self.assertEqual(hand_ids(a), [])                 # 负对照
        t = bind(g, a, STEGODON)
        self.assertIn(t, a.trinkets)
        # 正效果: 恰好 1 张白板 Stomping Stegodon 进本人手牌
        self.assertEqual(hand_ids(a), [STEGODON_CARD])
        copy = a.hand[0]
        self.assertFalse(copy.is_golden)
        self.assertEqual(copy.name, "Stomping Stegodon")
        self.assertFalse(copy.get(GameTag.GILDED_NOT_TRIPLED, False))
        # owner 隔离: 对手手牌不变
        self.assertEqual(hand_ids(b), [])
        # 池记账: 关联卡是池外卡（is_pool_minion=False）→ 零池操作
        self.assertEqual(g.minion_pool.available(STEGODON_CARD), 0)
        self.assertEqual(g.minion_pool.total_remaining(), total_before)

    def test_bind_is_once_per_hero(self):
        """跨局去重: 同一英雄第二次授予不再交付（一次性语义）。"""
        g = make_game(7022)
        a, _b = g.heroes
        bind(g, a, STEGODON)
        self.assertEqual(hand_ids(a), [STEGODON_CARD])
        self.assertIsNone(g.grant_trinket(a, STEGODON))   # 已持有 → 不重复
        self.assertEqual(hand_ids(a), [STEGODON_CARD])
        # 正对照: 另一英雄仍可独立获得同一饰品
        b = g.heroes[1]
        self.assertIsNotNone(g.grant_trinket(b, STEGODON))
        self.assertEqual(hand_ids(b), [STEGODON_CARD])

    def test_carddef_related_name_resolves_uniquely(self):
        """结构性: 数据链缺失时唯一名解析（CardDB 数据，非硬编码 id）。"""
        db = get_db()
        d = db.get(STEGODON)
        # 数据链缺失是本批已记档的数据层缺口
        self.assertIsNone(d.evolution_card_id)
        hits = [x for x in db._by_id.values()
                if x.card_type == CardType.MINION
                and not x.is_golden_def and x.name == "Stomping Stegodon"]
        self.assertEqual([x.id for x in hits], [STEGODON_CARD])
        self.assertFalse(hits[0].is_pool_minion)

    def test_unresolvable_related_card_whiffs_without_crash(self):
        """落空路径: 唯一名解析失败 → 不交付、不抛错（无资源消耗）。

        临时把基础关联卡定义移出 CardDB（只留同名金色定义——金色被
        `is_golden_def` 过滤，故非金命中数 0）→ 交付落空; `finally`
        还原（SOP §16c item 33 状态卫生）。
        """
        db = get_db()
        saved = db._by_id.pop(STEGODON_CARD, None)
        self.assertIsNotNone(saved)
        try:
            g = make_game(7031)
            a, _b = g.heroes
            t = bind(g, a, STEGODON)
            self.assertIn(t, a.trinkets)        # 饰品本身照常绑定
            self.assertEqual(hand_ids(a), [])   # 交付落空（不抛错）
        finally:
            db._by_id[STEGODON_CARD] = saved
        # 正对照: 数据恢复后同 setup 正常交付
        g2 = make_game(7031)
        a2, _b2 = g2.heroes
        bind(g2, a2, STEGODON)
        self.assertEqual(hand_ids(a2), [STEGODON_CARD])

    def test_full_hand_queues_and_delivers_next_turn(self):
        g = make_game(7023)
        a, _b = g.heroes
        while len(a.hand) < 10:
            a.hand.append(g.create_spell(HAND_FILLER, controller=a))
        bind(g, a, STEGODON)
        # 满手: 副本入等待队列（不销毁、必然交付 RULES §3.3）
        self.assertNotIn(STEGODON_CARD, hand_ids(a))
        queued = [e for h, e in g.pending_hand_queue
                  if h is a and e.card_id == STEGODON_CARD]
        self.assertEqual(len(queued), 1)
        # 跨回合: 腾出手牌位后等待队列在下个招募阶段交付
        a.hand.pop()
        g.end_recruit_phase()
        self.assertIn(STEGODON_CARD, hand_ids(a))
        self.assertEqual(g.pending_hand_queue, [])

    def test_soc_two_leftmost_beasts_get_divine_shield(self):
        g = make_game(7024)
        a, b = g.heroes
        put(g, a, BEAST_A)        # 野兽 #1（最左）
        put(g, a, NON_BEAST)      # 纳迦（非野兽）
        put(g, a, BEAST_B)        # 野兽 #2
        beast_c = put(g, a, BEAST_C)   # 野兽 #3（第三只，不应获得）
        opp = put(g, b, BEAST_A)
        t = bind(g, a, STEGODON)
        out = soc_probe(g, t)
        g.run_combat(a, b)
        sm = shield_map(out[a])
        self.assertTrue(sm[BEAST_A])          # 最左野兽
        self.assertTrue(sm[BEAST_B])          # 第二只野兽
        self.assertFalse(sm[NON_BEAST])       # 非野兽
        self.assertFalse(sm[BEAST_C])         # 第三只野兽
        self.assertFalse(shield_map(out[b])[BEAST_A])   # owner 隔离
        # 战后回滚（战斗期授予，RULES §3.5）
        self.assertFalse(beast_c.has(GameTag.DIVINE_SHIELD))
        for m in a.board + b.board:
            self.assertFalse(m.has(GameTag.DIVINE_SHIELD), m.card_id)

    def test_soc_single_beast_and_whiff(self):
        g = make_game(7025)
        a, _b = g.heroes
        naga = put(g, a, NON_BEAST)
        murloc = put(g, a, MURLOC)
        t = bind(g, a, STEGODON)
        # 负对照: 无野兽 → 落空（谁都不带圣盾）
        g.run_script_hook(t, "start_of_combat")
        self.assertFalse(naga.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(murloc.has(GameTag.DIVINE_SHIELD))
        # 正对照: 同 setup 加入 1 只野兽 → 该野兽恰好获圣盾
        beast = put(g, a, BEAST_C)
        g.run_script_hook(t, "start_of_combat")
        self.assertTrue(beast.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(naga.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(murloc.has(GameTag.DIVINE_SHIELD))

    def test_soc_amalgam_counts_as_beast(self):
        g = make_game(7026)
        a, _b = g.heroes
        amalgam = put(g, a, AMALGAM)   # Race.ALL
        beast = put(g, a, BEAST_C)
        naga = put(g, a, NON_BEAST)    # 第三只（非野兽）不应该获得
        t = bind(g, a, STEGODON)
        g.run_script_hook(t, "start_of_combat")
        self.assertTrue(amalgam.has(GameTag.DIVINE_SHIELD))
        self.assertTrue(beast.has(GameTag.DIVINE_SHIELD))
        self.assertFalse(naga.has(GameTag.DIVINE_SHIELD))
        self.assertIn(amalgam.race, (Race.ALL,))

    def test_owner_isolation_trinket_on_other_hero(self):
        g = make_game(7027)
        a, b = g.heroes
        put(g, a, BEAST_A)
        put(g, a, BEAST_B)
        put(g, b, BEAST_C)
        t = bind(g, b, STEGODON)          # 只有 B 持有饰品
        out = soc_probe(g, t)
        g.run_combat(a, b)
        self.assertFalse(shield_map(out[a])[BEAST_A])
        self.assertFalse(shield_map(out[a])[BEAST_B])
        self.assertTrue(shield_map(out[b])[BEAST_C])   # 正对照

    def test_soc_triggers_every_combat(self):
        """"Start of Combat" 是每场战斗（非一次性）。"""
        g = make_game(7028)
        a, b = g.heroes
        put(g, a, BEAST_A)
        put(g, a, BEAST_B)
        put(g, b, BEAST_C)
        t = bind(g, a, STEGODON)
        for _ in range(2):
            out = soc_probe(g, t)
            g.run_combat(a, b)
            sm = shield_map(out[a])
            self.assertTrue(sm[BEAST_A])
            self.assertTrue(sm[BEAST_B])

    def test_same_seed_replay_is_deterministic(self):
        def run():
            g = make_game(7029)
            a, b = g.heroes
            put(g, a, BEAST_A)
            put(g, a, BEAST_B)
            put(g, b, BEAST_C)
            t = bind(g, a, STEGODON)
            out = soc_probe(g, t)
            g.run_combat(a, b)
            return hand_ids(a), out[a], out[b]

        self.assertEqual(run(), run())
        # 正效果锚点（同 seed 两次都"空转"不得算通过）
        first = run()
        self.assertEqual(first[0], [STEGODON_CARD])
        sm = shield_map(first[1])
        self.assertTrue(sm[BEAST_A])
        self.assertTrue(sm[BEAST_B])
        self.assertFalse(shield_map(first[2])[BEAST_C])   # owner 隔离

    def test_without_trinket_control(self):
        g = make_game(7030)
        a, b = g.heroes
        put(g, a, BEAST_A)
        put(g, a, BEAST_B)
        out = soc_probe(g, a)
        g.run_combat(a, b)
        sm = shield_map(out[a])
        self.assertFalse(sm[BEAST_A])      # 负对照: 无饰品不授予
        self.assertFalse(sm[BEAST_B])
        self.assertEqual(hand_ids(a), [])
        # 正对照: 同 setup 绑定饰品后既交付又授予圣盾
        g2 = make_game(7030)
        a2, b2 = g2.heroes
        put(g2, a2, BEAST_A)
        put(g2, a2, BEAST_B)
        t2 = bind(g2, a2, STEGODON)
        out2 = soc_probe(g2, t2)
        g2.run_combat(a2, b2)
        sm2 = shield_map(out2[a2])
        self.assertTrue(sm2[BEAST_A])
        self.assertTrue(sm2[BEAST_B])
        self.assertEqual(hand_ids(a2), [STEGODON_CARD])


# ══════════════ 注册表 / DEFERRED 台账（结构性） ══════════════


class TestRegistryAndDeferredLedger(unittest.TestCase):
    """注册清单、撤注册清单与 20 张作业范围分区的结构性守卫。"""

    def test_implemented_registered(self):
        for cid in IMPLEMENTED:
            self.assertIn(cid, REGISTRY, cid)
            script = REGISTRY[cid]
            self.assertTrue(hasattr(script, "on_bind"))
            self.assertTrue(hasattr(script, "start_of_combat"))

    def test_deferred_not_registered(self):
        for cid in DEFERRED:
            self.assertNotIn(cid, REGISTRY, cid)

    def test_batch_scope_partition(self):
        """作业范围 = 20 张，1 CORRECT + 3 DEFERRED + 16 迁出，无交集/无遗漏。"""
        self.assertEqual(len(IMPLEMENTED), 1)
        self.assertEqual(len(DEFERRED), 3)
        self.assertEqual(len(MIGRATED), 16)
        scope = list(IMPLEMENTED) + list(DEFERRED) + list(MIGRATED)
        self.assertEqual(len(set(scope)), 20)

    def test_all_scope_ids_are_shop_trinkets(self):
        """20/20 均在 `CardDB.trinket_offer_pool()`（商店本体）。"""
        pool = {d.id for d in get_db().trinket_offer_pool()}
        for cid in list(IMPLEMENTED) + list(DEFERRED) + list(MIGRATED):
            self.assertIn(cid, pool, cid)

    def test_deferred_ledger_documents_every_id(self):
        """台账完整性: 模块 docstring 必须逐张记档（防静默遗漏）。"""
        text = BATCH_FILE.read_text(encoding="utf-8")
        for cid in list(IMPLEMENTED) + list(DEFERRED) + list(MIGRATED):
            self.assertIn(cid, text, f"{cid} 未在 batch_trinkets25 记档")

    def test_deferred_classes_have_no_hooks(self):
        """DEFERRED 类不得携带任何引擎钩子（否则是隐性第三态）。

        结构性: 本批模块中**唯一定义钩子**的顶层类必须是已注册的
        `StegodonPortraitScript`; 4 个 DEFERRED 类只承载台账 docstring。
        """
        from hsrl2.scripts.batches import batch_trinkets25 as B
        hook_names = {"on_bind", "start_of_turn", "end_of_turn",
                      "start_of_combat", "avenge", "battlecry",
                      "deathrattle", "rally", "activate", "hero_power"}
        with_hooks = set()
        for name, obj in vars(B).items():
            if not isinstance(obj, type) or obj.__module__ != B.__name__:
                continue
            if any(hasattr(obj, hook) for hook in hook_names):
                with_hooks.add(name)
        self.assertEqual(with_hooks, {"StegodonPortraitScript"})


if __name__ == "__main__":
    unittest.main()
