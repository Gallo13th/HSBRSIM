"""批次 unlock_final 行为层测试（10 注册饰品 + 1 Spellcraft token + 3
DEFERRED 台账守卫，作业单 2026-09-15）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）
  - 关联卡交付: `game.grant_card_copy_to_hand`（金色独立卡定义 + 池记账 +
    满手入队，RULES §7.4.6）
  - 刷新: 真实 `game.refresh_tavern`（含 `keywords=` / `copies_of_warband`）
    / 真实 `game.end_recruit_phase`（EoT + 跨回合 + 回合末清扫）
  - 战斗: 真实 `game.run_combat`（907/732 的 `last_minion_died` 通道**必须**
    在真实战斗内验证——`_combat_dead_snaps` + `_fire_last_minion_died`
    只在 `in_combat` 且棋盘清空时广播）; SoC 后棋盘用 `start_of_combat`
    事件探针读取（引擎在 SoC 钩子全部结算后广播）
  - 吞噬: 真实 `ConsumeMinion` Action（`from_tavern` / `consumer` /
    `stats_atk/health` 载荷生产点）
  - 血宝石: 真实 `PlayBloodGems`（BLOOD_GEM_BONUS_* 的唯一消费点）
  - 战吼刷新: 真实 `game.buy_from_tavern`（条件报价读取点）

覆盖（SOP §16 空转测试判定法 + 作业单测试矩阵）:
  - 每个行为测试**同一方法内**同时含正效果与负/正对照（无纯负面断言
    方法——`audit_vacuous_tests --strict` 要求 0 行为性存活者）;
  - owner 隔离（对手棋盘/对手酒馆/对手亡语/对手吞噬/对手选择，
    且同方法内含本人正效果）;
  - 跨回合 / 一次性（907/732 `last_minion_died` 每场一次; 755 规则回合末
    清除且每回合恰再生成 1 张）;
  - 落空不消耗（907 无 Demon 死亡、732 空板、755 无战吼随从、
    902 法术池耗尽）;
  - 池占返配平（216 交付 1 份 + `GILDED_NOT_TRIPLED` 出售回 1 份;
    930 白板副本零池操作——全池快照比对; 902 获得法术占池 1 份;
    433 非池卡零池操作）;
  - 满手队列（902 满手 → `pending_hand_queue`）;
  - 同 seed 确定性（每张卡一条）;
  - 禁止弱断言: 一律 `assertEqual` 钉死 id / 数值 / 实体身份 / 控制者。

作业单测试矩阵中**不适用**的条目（本批效果域决定）:
  - `len(options) == N`（Discover 选项数）: 本批 10 张注册饰品均不产生
    `Discover`/`PendingChoice`（902 是 `game.rng.choice` 随机获取，无选项
    集）。308 的覆盖是**反向**的——它让 Choose One 不再产生选择框，
    已在 `TestTrailblazerSticker` 逐项验证;
  - 双施（`SPELL_DOUBLER` / `spell_first`）: 本批无"额外施放"效果;
  - Titus / 亡语翻倍: 本批不产生亡语（433 只**观察**友方亡语死亡，
    其自身不产生亡语），故不适用。
  上述三条已在模块 docstring 留档，而非以空转测试冒充覆盖。

DEFERRED 守卫（3 张不注册——二态铁律 SOP §6b）:
  - `test_deferred_classes_have_no_engine_hooks` 逐类断言**零引擎钩子**
    （防"注册但 no-op"或"未注册却带钩子"的第三态）;
  - `test_deferred_docstrings_document_status_dependency_path` 断言每类
    docstring 含 Status / Dependency / Implementation path 三行台账。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.consume import ConsumeMinion
from hsrl2.db import CardDB
from hsrl2.entity import Buff as Enchant
from hsrl2.events import Listener
from hsrl2.game import Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 本批 13 张（CardDB 按名核实——禁止凭记忆写） ──
ETERNAL_PORTRAIT = "BG36_MagicItem_216"
S_THARA_STICKER = "BG32_MagicItem_907"
SOUL_FERMENTER = "BG35_MagicItem_732"
WARBAND_WHISTLE = "BG35_MagicItem_930"
INSURRECTIONISTS_BLADE = "BG36_MagicItem_214"
TRAILBLAZER_STICKER = "BG36_MagicItem_308"
STATUE_OF_HIREERK = "BG32_MagicItem_902"
ELECTRODE_ATTRACTOR = "BG35_MagicItem_743"
CHILLMERE_MOSAIC = "BG35_MagicItem_755"
VINESPEAKER_PORTRAIT = "BG35_MagicItem_433"
CHILLMERE_SPELL = "BG35_MagicItem_755t"          # Spellcraft token

CORRECT_TRINKETS = [
    ETERNAL_PORTRAIT, S_THARA_STICKER, SOUL_FERMENTER, WARBAND_WHISTLE,
    INSURRECTIONISTS_BLADE, TRAILBLAZER_STICKER, STATUE_OF_HIREERK,
    ELECTRODE_ATTRACTOR, CHILLMERE_MOSAIC, VINESPEAKER_PORTRAIT,
]
CORRECT_IDS = CORRECT_TRINKETS + [CHILLMERE_SPELL]

FLAMING_PORTRAIT = "BG35_MagicItem_156"
DESIGNER_EYEPATCH = "BG30_MagicItem_439"
MARINE_SIGNET = "BG30_MagicItem_711"
# FLAMING_PORTRAIT（156）/ DESIGNER_EYEPATCH（439）已由 `batch_misc_final`
# 注册（2026-09-02：`minion_triggered` 与 `hero.triple_threshold_race`
# 原语落地）→ 从本批 DEFERRED 台账迁出（保留历史记录）。
MIGRATED_IDS = [FLAMING_PORTRAIT, DESIGNER_EYEPATCH]
DEFERRED_IDS = [MARINE_SIGNET]

ALL_TRINKET_IDS = CORRECT_TRINKETS + DEFERRED_IDS + MIGRATED_IDS   # 恰好 13 张
DEFERRED_CLASSES = ["FlamingPortraitScript", "DesignerEyepatchScript",
                    "MarineSignetScript"]

# 引擎分发的钩子名（audit_script_wiring.ENGINE_HOOKS——DEFERRED 类必须零）
ENGINE_HOOK_NAMES = (
    "battlecry", "deathrattle", "start_of_combat", "avenge", "rally",
    "start_of_turn", "end_of_turn", "on_sell", "on_summon", "on_play",
    "activate", "atk", "health", "on_enter_hand", "on_bind",
)

# ── 测试用卡（CardDB 数据核实 36.2.2，均无亡语/复生意外关键词） ──
GEM = "BG20_GEM"                  # 血宝石 token（填充手牌用）
UNDEAD_T1 = "BG25_013"            # Rot Hide Gnoll 1/4 Undead（无关键词）
ETERNAL_KNIGHT = "BG25_008"       # Eternal Knight 4/2 Undead（池 T2）
ETERNAL_KNIGHT_G = "BG25_008_G"   # 金色独立卡定义
DEMON_T2 = "BG26_174"             # Demon 4/1（无关键词）
DEMON_BC = "BG23_357"             # Mind Muck Demon 3/2（战吼）
DEATHRATTLE_T1 = "BG28_300"       # Harmless Bonehead 1/1 Undead（亡语脚本）
MAGNETIC_MECH = "BG26_146"        # Mech 2/2 magnetic（池 T1）
BATTLECRY_T1 = "BG20_100"         # 战吼 2/1（池 T1）
CHOOSE_ONE_MINER = "BG31_320"     # Crater Miner（Choose One 随从）
GEM_DAY = "BG31_893"              # Gem Day（Choose One 法术）
VINESPEAKER = "BG35_437"          # Vinespeaker 5/6（非池 T5）
VINESPEAKER_G = "BG35_437_G"      # 金色独立卡定义 10/12

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 900) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str):
    e = game.grant_trinket(hero, tid)
    assert e is not None, f"{tid} 未授予"
    return e


def put(game: Game, hero: Hero, card_id: str, atk: int | None = None,
        hp: int | None = None) -> Minion:
    m = game.create_minion(card_id, controller=hero)
    if atk is not None:
        m.set(GameTag.BASE_ATK, atk)
    if hp is not None:
        m.set(GameTag.BASE_HEALTH, hp)
    if atk is not None or hp is not None:
        m.set(GameTag.HEALTH, m.get(GameTag.BASE_HEALTH))
    assert game.summon(hero, m)
    return m


def put_golden(game: Game, hero: Hero, card_id: str) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=True)
    assert game.summon(hero, m)
    return m


def to_tavern(game: Game, hero: Hero, m: Minion) -> Minion:
    if m in hero.board:
        hero.board.remove(m)
    m.zone = Zone.TAVERN
    hero.tavern.append(m)
    return m


def make_tavern_food(game: Game, hero: Hero, n: int) -> list:
    out = []
    for _ in range(n):
        m = game.create_minion(UNDEAD_T1, controller=hero)
        out.append(to_tavern(game, hero, m))
    return out


def fill_hand(game: Game, hero: Hero) -> None:
    while not hero.hand_full():
        assert hero.add_to_hand(game.create_minion(UNDEAD_T1,
                                                   controller=hero))


def num_of(card_id: str, i: int):
    return get_db().get(card_id).num(i)


def pool_snapshot(game: Game) -> dict:
    return {d.id: game.minion_pool.available(d.id)
            for d in game.db.pool_minions()}


def spell_pool_snapshot(game: Game) -> dict:
    return {d.id: game.spell_pool.available(d.id)
            for d in game.db.pool_spells()}


def minion_tavern_ids(hero: Hero) -> list:
    return [e.card_id for e in hero.tavern if isinstance(e, Minion)]


def summon_watch(game: Game, hero: Hero) -> list:
    seen: list = []
    game.events.register(Listener(
        event="summon", owner=hero,
        callback=lambda g, **kw: seen.append(kw["minion"])))
    return seen


def destroy_watch(game: Game, hero: Hero) -> list:
    seen: list = []
    game.events.register(Listener(
        event="minion_destroyed", owner=hero,
        callback=lambda g, **kw: seen.append(kw["minion"])))
    return seen


def soc_board_watch(game: Game, watched: Hero) -> dict:
    """`start_of_combat` 探针——SoC 钩子全部结算后的本人棋盘。"""
    snap: dict = {}

    def cb(g, hero=None, **kw):
        if hero is watched:
            snap["board"] = [m.card_id for m in watched.board]

    game.events.register(Listener(event="start_of_combat", owner=watched,
                                  callback=cb))
    return snap


class _RallyProbe:
    """记录 Rally 触发的探针脚本（真实 `trigger_friendly_rallies` 调用）。"""

    log: list = []

    @staticmethod
    def rally(source, game, ctx=None):
        _RallyProbe.log.append(source.uuid)
        return None


def rally_minion(game: Game, hero: Hero) -> Minion:
    m = game.create_minion(UNDEAD_T1, controller=hero)
    m.scripts = _RallyProbe
    assert game.summon(hero, m)
    return m


# ══════════════ 注册表 / DEFERRED 台账（结构性——与钩子无关） ══════════════


class TestBatchUnlockFinalLedger(unittest.TestCase):
    """结构性: 注册表 / CardDef / DEFERRED 台账一致性（与脚本钩子无关）。"""

    def test_all_ids_registered_or_deferred(self):
        """13 张恰好二分为 10 CORRECT + 3 DEFERRED，另加 1 个 token。"""
        self.assertEqual(len(ALL_TRINKET_IDS), 13)
        self.assertEqual(len(set(ALL_TRINKET_IDS)), 13)
        self.assertEqual(len(CORRECT_TRINKETS), 10)
        self.assertEqual(len(DEFERRED_IDS), 1)          # 439/156 已迁出
        self.assertEqual(len(MIGRATED_IDS), 2)
        self.assertEqual(set(CORRECT_TRINKETS) & set(DEFERRED_IDS), set())
        self.assertEqual(len(CORRECT_IDS), 11)      # + Spellcraft token

    def test_registered_ids_are_bound_and_carddef_present(self):
        db = get_db()
        for tid in CORRECT_IDS:
            self.assertIn(tid, REGISTRY, f"{tid} 未注册")
            self.assertIsNotNone(db.get(tid), f"{tid} 卡定义缺失")

    def test_deferred_ids_unregistered_with_carddef(self):
        db = get_db()
        for tid in DEFERRED_IDS:
            self.assertIsNotNone(db.get(tid), f"{tid} 卡定义缺失")
            self.assertNotIn(tid, REGISTRY, f"{tid} 仍被注册（DEFERRED）")
        for lone in (CHILLMERE_SPELL,):
            self.assertIsNotNone(db.get(lone))

    def test_deferred_classes_have_no_engine_hooks(self):
        """DEFERRED 类**零钩子**——防"未注册却带失效钩子"的第三态。"""
        from hsrl2.scripts.batches import batch_unlock_final as B
        for name in DEFERRED_CLASSES:
            cls = getattr(B, name)
            hooks = [h for h in ENGINE_HOOK_NAMES if h in vars(cls)]
            self.assertEqual(hooks, [], f"{name} 携带引擎钩子 {hooks}")

    def test_carddef_num_matches_text_params(self):
        """数值权威双向钉死（文本占位符 → CardDef.num）+ 数据链 id。"""
        self.assertEqual([num_of(ETERNAL_PORTRAIT, i) for i in range(2)],
                         [4, 2])
        self.assertEqual(num_of(STATUE_OF_HIREERK, 0), 2)
        self.assertEqual([num_of(MARINE_SIGNET, i) for i in range(2)],
                         [4, 1])
        for tid in (S_THARA_STICKER, SOUL_FERMENTER, WARBAND_WHISTLE,
                    INSURRECTIONISTS_BLADE, TRAILBLAZER_STICKER,
                    ELECTRODE_ATTRACTOR, CHILLMERE_MOSAIC,
                    VINESPEAKER_PORTRAIT, FLAMING_PORTRAIT,
                    DESIGNER_EYEPATCH):
            self.assertEqual([num_of(tid, i) for i in range(4)],
                             [None, None, None, None], tid)
        db = get_db()
        self.assertEqual(db.by_dbf(db.get(ETERNAL_PORTRAIT)
                                   .evolution_card_id).id, ETERNAL_KNIGHT_G)
        self.assertEqual(db.by_dbf(db.get(VINESPEAKER_PORTRAIT)
                                   .evolution_card_id).id, VINESPEAKER)
        self.assertEqual(db.by_dbf(db.get(FLAMING_PORTRAIT)
                                   .evolution_card_id).id, "BG34_500")
        self.assertEqual(db.by_dbf(db.get(CHILLMERE_MOSAIC)
                                   .spellcraft_id).id, CHILLMERE_SPELL)
        # 金色独立卡定义存在（禁止"数值×2"近似）
        self.assertEqual(db.golden_version(db.get(ETERNAL_KNIGHT)).id,
                         ETERNAL_KNIGHT_G)
        self.assertEqual(db.golden_version(db.get(VINESPEAKER)).id,
                         VINESPEAKER_G)

    def test_all_ids_in_offer_pool_membership(self):
        offer = {d.id for d in get_db().trinket_offer_pool()}
        for tid in ALL_TRINKET_IDS:
            self.assertIn(tid, offer, f"{tid} 不在商店提供池")
        self.assertNotIn(CHILLMERE_SPELL, offer)      # token 非商店成员

    def test_deferred_docstrings_document_status_dependency_path(self):
        """每张 DEFERRED 台账三行齐全（Status / Dependency / path）。"""
        from hsrl2.scripts.batches import batch_unlock_final as B
        low = B.__doc__ or ""
        for tid in DEFERRED_IDS:
            self.assertIn(tid, low)
        for name in DEFERRED_CLASSES:
            doc = getattr(B, name).__doc__ or ""
            self.assertIn("Status: DEFERRED", doc, name)
            self.assertIn("Dependency:", doc, name)
            self.assertIn("Implementation path:", doc, name)


# ══════════════ BG36_MagicItem_216 Eternal Portrait ══════════════


class TestEternalPortrait(unittest.TestCase):
    """216 — Get a Golden Eternal Knight; friendly Undead deaths buff
    your Eternal Knights +4/+2 this game（任意区域）。"""

    def test_bind_grants_golden_eternal_knight_with_pool_balance(self):
        g = make_game(seed=310)
        a, b = g.heroes
        pool_before = g.minion_pool.available(ETERNAL_KNIGHT)
        bind(g, a, ETERNAL_PORTRAIT)
        ks = [m for m in a.hand if m.card_id == ETERNAL_KNIGHT_G]
        self.assertEqual(len(ks), 1)
        ek = ks[0]
        self.assertTrue(ek.is_golden)
        self.assertTrue(ek.has(GameTag.GILDED_NOT_TRIPLED))
        self.assertEqual(ek.get(GameTag.TRIPLE_BASE_CARD_ID),
                         ETERNAL_KNIGHT)
        # 池记账: 占 1 份基础副本（金色独立定义按基础 id 扣池）
        self.assertEqual(g.minion_pool.available(ETERNAL_KNIGHT),
                         pool_before - 1)
        # 负对照: 对手手牌无交付
        self.assertEqual([m for m in b.hand
                          if m.card_id == ETERNAL_KNIGHT_G], [])
        # GILDED_NOT_TRIPLED: 打出后出售恰好回 1 份（不是 3 份）
        self.assertTrue(g.play_minion(a, ek))
        assert g.sell_minion(a, ek)
        self.assertEqual(g.minion_pool.available(ETERNAL_KNIGHT),
                         pool_before)

    def test_friendly_undead_deaths_buff_family_wherever(self):
        g = make_game(seed=311)
        a, b = g.heroes
        bind(g, a, ETERNAL_PORTRAIT)
        ek = put(g, a, ETERNAL_KNIGHT)
        hand_ek = [m for m in a.hand if m.card_id == ETERNAL_KNIGHT_G][0]
        enemy_ek = put(g, b, ETERNAL_KNIGHT)
        base = (ek.atk, ek.max_health)
        hand_base = (hand_ek.atk, hand_ek.max_health)
        enemy_base = (enemy_ek.atk, enemy_ek.max_health)
        non_undead = put(g, a, DEMON_T2)
        u1 = put(g, a, UNDEAD_T1)
        u2 = put(g, a, UNDEAD_T1)

        u1.health = 0
        g.check_deaths()
        self.assertEqual((ek.atk, ek.max_health),
                         (base[0] + 4, base[1] + 2))
        # "wherever this is": 手牌中的家族实体同享（光环实时读取）
        self.assertEqual((hand_ek.atk, hand_ek.max_health),
                         (hand_base[0] + 4, hand_base[1] + 2))
        # 负对照 1: 非 Undead 死亡不计
        non_undead.health = 0
        g.check_deaths()
        self.assertEqual((ek.atk, ek.max_health),
                         (base[0] + 4, base[1] + 2))
        # 负对照 2: 对手 Undead 死亡不计（owner 隔离）
        enemy_u = put(g, b, UNDEAD_T1)
        enemy_u.health = 0
        g.check_deaths()
        self.assertEqual((ek.atk, ek.max_health),
                         (base[0] + 4, base[1] + 2))
        self.assertEqual((enemy_ek.atk, enemy_ek.max_health), enemy_base)
        # 正效果 2: 第二只友方 Undead → 累计 +8/+4（增量式）
        u2.health = 0
        g.check_deaths()
        self.assertEqual((ek.atk, ek.max_health),
                         (base[0] + 8, base[1] + 4))

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=312)
            a, _b = g.heroes
            bind(g, a, ETERNAL_PORTRAIT)
            ek = put(g, a, ETERNAL_KNIGHT)
            u = put(g, a, UNDEAD_T1)
            u.health = 0
            g.check_deaths()
            results.append((ek.atk, ek.max_health,
                            sorted(m.card_id for m in a.hand)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], num_of(ETERNAL_KNIGHT, 0) + 4)
        self.assertEqual(results[0][1], num_of(ETERNAL_KNIGHT, 1) + 2)


# ══════════════ BG32_MagicItem_907 S'Thara Sticker ══════════════


class TestSTharaSticker(unittest.TestCase):
    """907 — After your last minion dies each combat, summon your first
    Demon that died with its maximum stats（真实 run_combat 验证）。"""

    def test_last_minion_died_summons_first_demon_with_death_stats(self):
        g = make_game(seed=320)
        a, b = g.heroes
        bind(g, a, S_THARA_STICKER)
        demon = put(g, a, DEMON_T2)
        demon.add_buff(Enchant(atk=2, health=2))     # 死亡瞬间 6/3
        put(g, a, UNDEAD_T1)
        put(g, b, DEMON_T2, atk=50, hp=50)
        seen = summon_watch(g, a)
        g.run_combat(a, b)
        mine = [m for m in seen
                if m.controller is a and m.card_id == DEMON_T2]
        self.assertEqual(len(mine), 1)
        d_demon = get_db().get(DEMON_T2)
        self.assertEqual((mine[0].atk, mine[0].max_health),
                         (d_demon.atk + 2, d_demon.health + 2))
        # 交叉核对引擎死亡快照（独立于脚本的状态源）
        snaps = a._combat_dead_snaps
        first_demon = next(s for s in snaps if s["race"] in (Race.DEMON,
                                                            Race.ALL))
        self.assertEqual((first_demon["atk"], first_demon["max_health"]),
                         (d_demon.atk + 2, d_demon.health + 2))
        self.assertEqual(first_demon["race"], demon.race)

    def test_aura_not_double_counted(self):
        """对抗验证 MAJOR（2026-09-13）: `_live_light_snapshot` 不得烘入
        光环——重召后实时光环重算，最终属性 == 死亡瞬间属性。"""
        from hsrl2.actions.racefx import ApplyRaceAura
        g = make_game(seed=325)
        a, b = g.heroes
        bind(g, a, S_THARA_STICKER)
        g.run_actions([ApplyRaceAura(a, Race.DEMON, 3, 3)])
        d = get_db().get(DEMON_T2)
        demon = put(g, a, DEMON_T2)
        put(g, a, UNDEAD_T1)
        put(g, b, DEMON_T2, atk=50, hp=50)
        self.assertEqual((demon.atk, demon.max_health),
                         (d.atk + 3, d.health + 3))     # 光环生效
        seen = summon_watch(g, a)
        g.run_combat(a, b)
        mine = [m for m in seen
                if m.controller is a and m.card_id == DEMON_T2]
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0].atk, mine[0].max_health),
                         (d.atk + 3, d.health + 3),
                         "光环双计（快照烘入光环后又重算一次）")

    def test_no_demon_snapshot_fizzles_without_summon(self):
        """正对照（有 Demon → 召唤）与落空（无 Demon → 不召唤）同方法。"""
        g = make_game(seed=321)
        a, b = g.heroes
        bind(g, a, S_THARA_STICKER)
        put(g, a, UNDEAD_T1)
        put(g, b, DEMON_T2, atk=50, hp=50)
        seen = summon_watch(g, a)
        g.run_combat(a, b)
        self.assertTrue(a._combat_dead_snaps)         # 事件条件确实满足
        self.assertEqual([m for m in seen if m.controller is a], [])
        # 正对照: 同 seed 加一只 Demon → 召唤发生
        g2 = make_game(seed=321)
        a2, b2 = g2.heroes
        bind(g2, a2, S_THARA_STICKER)
        put(g2, a2, UNDEAD_T1)
        put(g2, a2, DEMON_T2)
        put(g2, b2, DEMON_T2, atk=50, hp=50)
        seen2 = summon_watch(g2, a2)
        g2.run_combat(a2, b2)
        self.assertEqual([m.card_id for m in seen2 if m.controller is a2],
                         [DEMON_T2])

    def test_opponent_last_minion_died_does_not_summon_for_holder(self):
        """owner 隔离: 双方都绑 → 只有棋盘清空的一方召唤。"""
        g = make_game(seed=322)
        a, b = g.heroes
        bind(g, a, S_THARA_STICKER)
        bind(g, b, S_THARA_STICKER)
        put(g, a, DEMON_T2, atk=50, hp=50)            # a 存活
        put(g, b, DEMON_T2)                           # b 的 Demon 死亡
        seen = summon_watch(g, a)
        g.run_combat(a, b)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].card_id, DEMON_T2)
        self.assertIs(seen[0].controller, b)                  # 不是 a
        self.assertIsNot(seen[0].controller, a)

    def test_recruit_phase_death_does_not_trigger(self):
        """正对照（战斗内 → 召唤）与非战斗（招募期死亡 → 不召唤）同方法。"""
        g = make_game(seed=323)
        a, b = g.heroes
        bind(g, a, S_THARA_STICKER)
        demon = put(g, a, DEMON_T2)
        seen = summon_watch(g, a)
        demon.health = 0
        g.check_deaths()                              # in_combat=False
        self.assertEqual([m for m in seen if m.controller is a], [])
        # 正对照: 同 seed 走真实战斗 → 召唤
        g2 = make_game(seed=323)
        a2, b2 = g2.heroes
        bind(g2, a2, S_THARA_STICKER)
        put(g2, a2, DEMON_T2)
        put(g2, b2, DEMON_T2, atk=50, hp=50)
        seen2 = summon_watch(g2, a2)
        g2.run_combat(a2, b2)
        self.assertEqual([m.card_id for m in seen2 if m.controller is a2],
                         [DEMON_T2])

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=324)
            a, b = g.heroes
            bind(g, a, S_THARA_STICKER)
            put(g, a, DEMON_T2)
            put(g, a, UNDEAD_T1)
            put(g, b, DEMON_T2, atk=50, hp=50)
            seen = summon_watch(g, a)
            g.run_combat(a, b)
            results.append([(m.card_id, m.atk, m.max_health)
                            for m in seen if m.controller is a])
        self.assertEqual(results[0], results[1])
        d_demon = get_db().get(DEMON_T2)
        self.assertEqual(results[0],
                         [(DEMON_T2, d_demon.atk, d_demon.health)])


# ══════════════ BG35_MagicItem_732 Soul Fermenter ══════════════


class TestSoulFermenter(unittest.TestCase):
    """732 — Start of Combat: destroy your 3 left-most minions; after your
    last minion dies, resummon them（真实 run_combat 验证）。"""

    def test_soc_destroys_three_leftmost_and_resummons_them(self):
        g = make_game(seed=330)
        a, b = g.heroes
        bind(g, a, SOUL_FERMENTER)
        d1 = put(g, a, UNDEAD_T1)
        d1.add_buff(Enchant(atk=2, health=2))          # 3/6
        d1.set(GameTag.TAUNT, True)
        put(g, a, MAGNETIC_MECH)                       # 2/2
        put(g, a, BATTLECRY_T1)                        # 2/1
        put(g, a, DEMON_T2, atk=5, hp=5)               # 第 4 只（保留）
        put(g, b, DEMON_T2, atk=50, hp=50)
        soc = soc_board_watch(g, a)
        destroyed = destroy_watch(g, a)
        summons = summon_watch(g, a)
        g.run_combat(a, b)
        # SoC 后: 最左 3 只已摧毁，第 4 只仍在
        self.assertEqual(soc["board"], [DEMON_T2])
        mine = [m.card_id for m in destroyed if m.controller is a]
        self.assertEqual(mine[:3], [UNDEAD_T1, MAGNETIC_MECH,
                                    BATTLECRY_T1])
        # owner 隔离: 对手随从未被本饰品摧毁
        self.assertEqual([m for m in destroyed if m.controller is b], [])
        # 最后随从死亡后按快照顺序 resummon
        res = [m for m in summons if m.controller is a]
        self.assertEqual([m.card_id for m in res],
                         [UNDEAD_T1, MAGNETIC_MECH, BATTLECRY_T1])
        self.assertEqual((res[0].atk, res[0].max_health), (3, 6))
        self.assertTrue(res[0].has(GameTag.TAUNT))     # 关键词复原
        self.assertEqual((res[1].atk, res[1].max_health), (2, 2))

    def test_board_of_exactly_three_resummons_during_soc(self):
        g = make_game(seed=331)
        a, b = g.heroes
        bind(g, a, SOUL_FERMENTER)
        put(g, a, UNDEAD_T1)
        put(g, a, MAGNETIC_MECH)
        put(g, a, BATTLECRY_T1)
        put(g, b, DEMON_T2, atk=50, hp=50)
        summons = summon_watch(g, a)
        g.run_combat(a, b)
        res = [m.card_id for m in summons if m.controller is a]
        self.assertEqual(res, [UNDEAD_T1, MAGNETIC_MECH, BATTLECRY_T1])

    def test_board_of_two_only_destroys_two(self):
        g = make_game(seed=332)
        a, b = g.heroes
        bind(g, a, SOUL_FERMENTER)
        put(g, a, UNDEAD_T1)
        put(g, a, MAGNETIC_MECH)
        put(g, b, DEMON_T2, atk=50, hp=50)
        destroyed = destroy_watch(g, a)
        summons = summon_watch(g, a)
        g.run_combat(a, b)
        self.assertEqual([m.card_id for m in destroyed
                          if m.controller is a],
                         [UNDEAD_T1, MAGNETIC_MECH])
        self.assertEqual([m.card_id for m in summons
                          if m.controller is a],
                         [UNDEAD_T1, MAGNETIC_MECH])

    def test_empty_board_fizzles_without_side_effects(self):
        """正对照（有板 → 摧毁+resummon）与空板（零副作用）同方法。"""
        g = make_game(seed=333)
        a, b = g.heroes
        bind(g, a, SOUL_FERMENTER)
        put(g, b, DEMON_T2, atk=50, hp=50)
        destroyed = destroy_watch(g, a)
        summons = summon_watch(g, a)
        g.run_combat(a, b)
        self.assertEqual(destroyed, [])
        self.assertEqual(summons, [])
        # 正对照: 同 seed + 一只随从 → 摧毁并 resummon
        g2 = make_game(seed=333)
        a2, b2 = g2.heroes
        bind(g2, a2, SOUL_FERMENTER)
        put(g2, a2, UNDEAD_T1)
        put(g2, b2, DEMON_T2, atk=50, hp=50)
        s2 = summon_watch(g2, a2)
        g2.run_combat(a2, b2)
        self.assertEqual([m.card_id for m in s2 if m.controller is a2],
                         [UNDEAD_T1])

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=334)
            a, b = g.heroes
            bind(g, a, SOUL_FERMENTER)
            put(g, a, UNDEAD_T1)
            put(g, a, MAGNETIC_MECH)
            put(g, a, BATTLECRY_T1)
            put(g, a, DEMON_T2, atk=5, hp=5)
            put(g, b, DEMON_T2, atk=50, hp=50)
            summons = summon_watch(g, a)
            g.run_combat(a, b)
            results.append([(m.card_id, m.atk, m.max_health)
                            for m in summons if m.controller is a])
        self.assertEqual(results[0], results[1])
        self.assertEqual([r[0] for r in results[0]],
                         [UNDEAD_T1, MAGNETIC_MECH, BATTLECRY_T1])


# ══════════════ BG35_MagicItem_930 Warband Whistle ══════════════


class TestWarbandWhistle(unittest.TestCase):
    """930 — Gain a free Refresh that contains plain copies of minions in
    your warband（白板副本 + 零池操作 + 不扣金币）。"""

    def test_free_refresh_does_not_consume_player_free_refresh(self):
        """BUG-4 回归: 引擎赠送的"免费刷新"不得吞玩家自有免费次数。"""
        g = make_game(seed=341)
        a, b = g.heroes
        put(g, a, UNDEAD_T1)
        a.set(GameTag.FREE_REFRESH_REMAINING, 2)
        bind(g, a, WARBAND_WHISTLE)
        self.assertEqual(a.get(GameTag.FREE_REFRESH_REMAINING, 0), 2)

    def test_refresh_contains_plain_copies_of_warband_zero_pool(self):
        g = make_game(seed=340)
        a, b = g.heroes
        m1 = put(g, a, UNDEAD_T1)
        m2 = put(g, a, MAGNETIC_MECH)
        m2.add_buff(Enchant(atk=3, health=3))          # 战团有 buff，副本须白板
        gold_before = a.gold
        initial = [e for e in a.tavern if isinstance(e, Minion)]
        b_tavern_before = list(b.tavern)
        pool_before = pool_snapshot(g)
        bind(g, a, WARBAND_WHISTLE)
        self.assertEqual(minion_tavern_ids(a),
                         [m1.card_id, m2.card_id])
        self.assertEqual([(e.atk, e.max_health) for e in a.tavern],
                         [(1, 4), (2, 2)])             # 白板（不带 buff）
        self.assertEqual(a.gold, gold_before)          # free=True
        # 零池操作: 池变化**只**来自旧馆内容回池（副本本身不占池/不回池）
        expected = dict(pool_before)
        for e in initial:
            bid = e.get(GameTag.TRIPLE_BASE_CARD_ID, None) or e.card_id
            expected[bid] = expected[bid] + 1
        self.assertEqual(pool_snapshot(g), expected)
        # 负对照: 对手酒馆原样未动
        self.assertEqual(b.tavern, b_tavern_before)
        # 正对照: 空板 → 空馆（同方法内）
        g2 = make_game(seed=340)
        a2, _b2 = g2.heroes
        bind(g2, a2, WARBAND_WHISTLE)
        self.assertEqual(minion_tavern_ids(a2), [])

    def test_golden_warband_minion_yields_plain_copy(self):
        g = make_game(seed=341)
        a, _b = g.heroes
        golden = put_golden(g, a, ETERNAL_KNIGHT_G)
        self.assertTrue(golden.is_golden)
        bind(g, a, WARBAND_WHISTLE)
        self.assertEqual(minion_tavern_ids(a), [ETERNAL_KNIGHT])
        copy = a.tavern[0]
        self.assertFalse(copy.is_golden)
        self.assertEqual((copy.atk, copy.max_health),
                         (num_of(ETERNAL_KNIGHT, 0),
                          num_of(ETERNAL_KNIGHT, 1)))

    def test_opponent_tavern_untouched(self):
        g = make_game(seed=342)
        a, b = g.heroes
        put(g, a, UNDEAD_T1)
        put(g, b, MAGNETIC_MECH)
        b_tavern_before = list(b.tavern)
        bind(g, a, WARBAND_WHISTLE)
        self.assertEqual(minion_tavern_ids(a), [UNDEAD_T1])   # 本人正效果
        self.assertEqual(b.tavern, b_tavern_before)           # owner 隔离
        self.assertEqual([e.card_id for e in b.tavern],
                         [e.card_id for e in b_tavern_before])

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=343)
            a, _b = g.heroes
            put(g, a, UNDEAD_T1)
            put(g, a, MAGNETIC_MECH)
            bind(g, a, WARBAND_WHISTLE)
            results.append([(e.card_id, e.atk, e.max_health)
                            for e in a.tavern])
        self.assertEqual(results[0], results[1])
        self.assertEqual([r[0] for r in results[0]],
                         [UNDEAD_T1, MAGNETIC_MECH])


# ══════════════ BG36_MagicItem_214 Insurrectionist's Blade ══════════════


class TestInsurrectionistsBlade(unittest.TestCase):
    """214 — At the end of your turn, trigger all friendly Rallies。"""

    def setUp(self):
        _RallyProbe.log = []

    def test_eot_triggers_all_friendly_rallies(self):
        """真实 `end_recruit_phase` EoT 派发 + 无饰品负对照。"""
        g = make_game(seed=350)
        a, b = g.heroes
        r1 = rally_minion(g, a)
        r2 = rally_minion(g, a)
        bind(g, a, INSURRECTIONISTS_BLADE)
        g.end_recruit_phase()
        self.assertEqual(sorted(_RallyProbe.log), sorted([r1.uuid, r2.uuid]))
        # 负对照: 同 seed 不绑 → EoT 不触发任何 Rally
        _RallyProbe.log = []
        g2 = make_game(seed=350)
        a2, _b2 = g2.heroes
        r3 = rally_minion(g2, a2)
        g2.end_recruit_phase()
        self.assertEqual(_RallyProbe.log, [])
        self.assertIsNotNone(r3)

    def test_opponent_rally_not_triggered(self):
        g = make_game(seed=351)
        a, b = g.heroes
        mine = rally_minion(g, a)
        theirs = rally_minion(g, b)
        bind(g, a, INSURRECTIONISTS_BLADE)
        trinket = [t for t in a.trinkets
                   if t.card_id == INSURRECTIONISTS_BLADE][0]
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(_RallyProbe.log, [mine.uuid])       # 本人正效果
        self.assertNotIn(theirs.uuid, _RallyProbe.log)       # owner 隔离

    def test_rally_extra_quota_doubles_trigger(self):
        g = make_game(seed=352)
        a, _b = g.heroes
        r1 = rally_minion(g, a)
        bind(g, a, INSURRECTIONISTS_BLADE)
        trinket = a.trinkets[0]
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(_RallyProbe.log, [r1.uuid])
        a.extra_triggers["rally_extra"] = 1
        _RallyProbe.log = []
        g.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(_RallyProbe.log, [r1.uuid, r1.uuid])

    def test_no_friendly_rally_is_noop_then_triggers(self):
        g = make_game(seed=353)
        a, _b = g.heroes
        bind(g, a, INSURRECTIONISTS_BLADE)
        trinket = a.trinkets[0]
        g.run_script_hook(trinket, "end_of_turn")     # 无 Rally → 空转不抛错
        self.assertEqual(_RallyProbe.log, [])
        r = rally_minion(g, a)
        g.run_script_hook(trinket, "end_of_turn")     # 正效果
        self.assertEqual(_RallyProbe.log, [r.uuid])

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            _RallyProbe.log = []
            g = make_game(seed=354)
            a, _b = g.heroes
            r1 = rally_minion(g, a)
            r2 = rally_minion(g, a)
            bind(g, a, INSURRECTIONISTS_BLADE)
            g.run_script_hook(a.trinkets[0], "end_of_turn")
            results.append(
                (sorted(_RallyProbe.log) == sorted([r1.uuid, r2.uuid]),
                 len(_RallyProbe.log)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], (True, 2))


# ══════════════ BG36_MagicItem_308 Trailblazer Sticker ══════════════


class TestTrailblazerSticker(unittest.TestCase):
    """308 — Your Choose One cards have both effects combined。"""

    def test_choose_one_minion_gets_both_effects(self):
        g = make_game(seed=360)
        a, b = g.heroes
        bind(g, a, TRAILBLAZER_STICKER)
        self.assertTrue(a.get(GameTag.CHOOSE_BOTH, False))
        m = g.create_minion(CHOOSE_ONE_MINER, controller=a)
        assert a.add_to_hand(m)
        self.assertTrue(g.play_minion(a, m))
        self.assertEqual(g.pending_choices, [])              # 不产生选择
        self.assertEqual(len([c for c in a.hand
                              if c.card_id == GEM]), num_of(
                                 CHOOSE_ONE_MINER, 0))
        self.assertEqual(len([c for c in a.hand
                              if c.card_id == GEM_DAY]), 1)
        # 负对照: 同 seed 不绑 → 产生 Choose One 选择且无效果
        g2 = make_game(seed=360)
        a2, _b2 = g2.heroes
        m2 = g2.create_minion(CHOOSE_ONE_MINER, controller=a2)
        assert a2.add_to_hand(m2)
        g2.play_minion(a2, m2)
        self.assertEqual(len(g2.pending_choices), 1)
        self.assertEqual(g2.pending_choices[0].kind, "choose_one")
        self.assertEqual([c for c in a2.hand if c.card_id == GEM], [])

    def test_choose_one_spell_gets_both_effects(self):
        g = make_game(seed=361)
        a, _b = g.heroes
        bind(g, a, TRAILBLAZER_STICKER)
        s = self._give_spell(g, a, GEM_DAY)
        self.assertTrue(g.play_spell(a, s))
        self.assertEqual(g.pending_choices, [])
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 1)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 1)
        # 负对照: 同 seed 不绑 → 选择框 + 未结算
        g2 = make_game(seed=361)
        a2, _b2 = g2.heroes
        s2 = self._give_spell(g2, a2, GEM_DAY)
        self.assertTrue(g2.play_spell(a2, s2))
        self.assertEqual(len(g2.pending_choices), 1)
        self.assertEqual(a2.get(GameTag.BLOOD_GEM_BONUS_ATK, 0), 0)

    def test_opponent_choose_one_unaffected(self):
        g = make_game(seed=362)
        a, b = g.heroes
        bind(g, a, TRAILBLAZER_STICKER)
        mine = g.create_minion(CHOOSE_ONE_MINER, controller=a)
        assert a.add_to_hand(mine)
        g.play_minion(a, mine)
        self.assertEqual(g.pending_choices, [])              # 本人正效果
        theirs = g.create_minion(CHOOSE_ONE_MINER, controller=b)
        assert b.add_to_hand(theirs)
        g.play_minion(b, theirs)
        self.assertEqual(len(g.pending_choices), 1)          # owner 隔离
        self.assertIs(g.pending_choices[0].owner, b)

    def test_newly_gained_choose_one_also_affected(self):
        g = make_game(seed=363)
        a, _b = g.heroes
        bind(g, a, TRAILBLAZER_STICKER)
        later = g.create_minion(CHOOSE_ONE_MINER, controller=a)  # 绑定后获得
        assert a.add_to_hand(later)
        g.play_minion(a, later)
        self.assertEqual(g.pending_choices, [])
        self.assertEqual(len([c for c in a.hand
                              if c.card_id == GEM_DAY]), 1)

    @staticmethod
    def _give_spell(game, hero, card_id) -> Spell:
        s = game.create_spell(card_id, controller=hero)
        s.scripts = REGISTRY.get(card_id)
        assert hero.add_to_hand(s)
        return s

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=364)
            a, _b = g.heroes
            bind(g, a, TRAILBLAZER_STICKER)
            m = g.create_minion(CHOOSE_ONE_MINER, controller=a)
            assert a.add_to_hand(m)
            g.play_minion(a, m)
            results.append(sorted(c.card_id for c in a.hand))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0].count(GEM_DAY), 1)


# ══════════════ BG32_MagicItem_902 Statue of Hir'eek ══════════════


class TestStatueOfHireek(unittest.TestCase):
    """902 — After 2 minions in the Tavern are consumed, get a random
    Tavern spell. ({0} left!)。"""

    def test_two_tavern_consumes_grant_spell_and_reset(self):
        g = make_game(seed=370)
        a, _b = g.heroes
        t = bind(g, a, STATUE_OF_HIREERK)
        demon = put(g, a, DEMON_T2)
        v1, v2 = make_tavern_food(g, a, 2)
        hand_before = list(a.hand)
        pool_before = spell_pool_snapshot(g)
        ConsumeMinion(demon, v1).do(g)
        self.assertEqual(t._hireek_left, 1)                  # 1 只不计
        self.assertEqual([c for c in a.hand if isinstance(c, Spell)], [])
        ConsumeMinion(demon, v2).do(g)
        self.assertEqual(t._hireek_left, num_of(STATUE_OF_HIREERK, 0))
        new = [c for c in a.hand
               if isinstance(c, Spell) and c not in hand_before]
        self.assertEqual(len(new), 1)
        self.assertLessEqual(get_db().get(new[0].card_id).tech_level,
                             a.tavern_tier)
        pool_after = spell_pool_snapshot(g)
        self.assertEqual(pool_after[new[0].card_id],
                         pool_before[new[0].card_id] - 1)    # 占池 1 份

    def test_non_tavern_consume_not_counted(self):
        g = make_game(seed=371)
        a, _b = g.heroes
        t = bind(g, a, STATUE_OF_HIREERK)
        demon = put(g, a, DEMON_T2)
        board_food = put(g, a, UNDEAD_T1)                    # 棋盘来源
        ConsumeMinion(demon, board_food).do(g)
        self.assertEqual(t._hireek_left, num_of(STATUE_OF_HIREERK, 0))
        self.assertEqual([c for c in a.hand if isinstance(c, Spell)], [])
        # 正对照: 2 只酒馆来源 → 得法术
        v1, v2 = make_tavern_food(g, a, 2)
        ConsumeMinion(demon, v1).do(g)
        ConsumeMinion(demon, v2).do(g)
        self.assertEqual(len([c for c in a.hand if isinstance(c, Spell)]), 1)

    def test_opponent_tavern_consume_not_counted(self):
        g = make_game(seed=372)
        a, b = g.heroes
        t = bind(g, a, STATUE_OF_HIREERK)
        enemy_demon = put(g, b, DEMON_T2)
        enemy_food = make_tavern_food(g, b, 2)
        ConsumeMinion(enemy_demon, enemy_food[0]).do(g)
        ConsumeMinion(enemy_demon, enemy_food[1]).do(g)
        self.assertEqual(t._hireek_left, num_of(STATUE_OF_HIREERK, 0))
        self.assertEqual([c for c in a.hand if isinstance(c, Spell)], [])
        # 正对照: 本人的酒馆吞噬 → 得法术
        demon = put(g, a, DEMON_T2)
        v1, v2 = make_tavern_food(g, a, 2)
        ConsumeMinion(demon, v1).do(g)
        ConsumeMinion(demon, v2).do(g)
        self.assertEqual(len([c for c in a.hand if isinstance(c, Spell)]), 1)

    def test_pool_exhausted_fizzles_but_resets(self):
        g = make_game(seed=373)
        a, _b = g.heroes
        t = bind(g, a, STATUE_OF_HIREERK)
        demon = put(g, a, DEMON_T2)
        v1, v2 = make_tavern_food(g, a, 2)
        ConsumeMinion(demon, v1).do(g)
        ConsumeMinion(demon, v2).do(g)
        self.assertEqual(len([c for c in a.hand if isinstance(c, Spell)]), 1)
        # 耗尽法术池 → 落空但计数复位
        for d in g.db.pool_spells():
            for _ in range(g.spell_pool.available(d.id)):
                assert g.spell_pool.acquire(d.id)
        hand_now = len([c for c in a.hand if isinstance(c, Spell)])
        v3, v4 = make_tavern_food(g, a, 2)
        ConsumeMinion(demon, v3).do(g)
        ConsumeMinion(demon, v4).do(g)
        self.assertEqual(len([c for c in a.hand if isinstance(c, Spell)]),
                         hand_now)
        self.assertEqual(t._hireek_left, num_of(STATUE_OF_HIREERK, 0))

    def test_full_hand_queues_spell(self):
        g = make_game(seed=374)
        a, _b = g.heroes
        bind(g, a, STATUE_OF_HIREERK)
        demon = put(g, a, DEMON_T2)
        v1, v2 = make_tavern_food(g, a, 2)
        ConsumeMinion(demon, v1).do(g)
        ConsumeMinion(demon, v2).do(g)                       # 正效果: 入手
        self.assertEqual(len([c for c in a.hand if isinstance(c, Spell)]), 1)
        granted = [c for c in a.hand if isinstance(c, Spell)][0]
        a.hand.remove(granted)
        fill_hand(g, a)
        q_before = len(g.pending_hand_queue)
        v3, v4 = make_tavern_food(g, a, 2)
        ConsumeMinion(demon, v3).do(g)
        ConsumeMinion(demon, v4).do(g)
        self.assertEqual(len(g.pending_hand_queue), q_before + 1)
        self.assertIs(g.pending_hand_queue[-1][0], a)

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=375)
            a, _b = g.heroes
            bind(g, a, STATUE_OF_HIREERK)
            demon = put(g, a, DEMON_T2)
            v1, v2 = make_tavern_food(g, a, 2)
            ConsumeMinion(demon, v1).do(g)
            ConsumeMinion(demon, v2).do(g)
            results.append(sorted(c.card_id for c in a.hand
                                  if isinstance(c, Spell)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(results[0]), 1)


# ══════════════ BG35_MagicItem_743 Electrode Attractor ══════════════


class TestElectrodeAttractor(unittest.TestCase):
    """743 — Magnetic Mechs cost (2); the Tavern offers an extra Magnetic
    whenever it is Refreshed。"""

    def test_magnetic_mech_costs_two_others_full_price(self):
        g = make_game(seed=380)
        a, _b = g.heroes
        bind(g, a, ELECTRODE_ATTRACTOR)
        g.minion_pool.acquire(MAGNETIC_MECH)
        mag = g.create_minion(MAGNETIC_MECH, controller=a)
        mag.zone = Zone.TAVERN
        a.tavern.append(mag)
        plain = g.create_minion(BATTLECRY_T1, controller=a)  # 非磁力
        plain.zone = Zone.TAVERN
        a.tavern.append(plain)
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, mag))
        self.assertEqual(a.gold, 8)                          # 3 → 2
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, plain))
        self.assertEqual(a.gold, 7)                          # 原价 3
        # 负对照: 同 seed 不绑 → 磁力机械原价 3
        g2 = make_game(seed=380)
        a2, _b2 = g2.heroes
        g2.minion_pool.acquire(MAGNETIC_MECH)
        mag2 = g2.create_minion(MAGNETIC_MECH, controller=a2)
        mag2.zone = Zone.TAVERN
        a2.tavern.append(mag2)
        a2.gold = 10
        self.assertTrue(g2.buy_from_tavern(a2, mag2))
        self.assertEqual(a2.gold, 7)

    def test_refresh_offers_extra_magnetic_slot(self):
        g = make_game(seed=381)
        a, _b = g.heroes
        bind(g, a, ELECTRODE_ATTRACTOR)
        g.refresh_tavern(a, free=True)
        mags = [e for e in a.tavern
                if isinstance(e, Minion) and e.has(GameTag.MAGNETIC)]
        self.assertEqual(len(mags), 1)                       # 恰多 1 个展示位
        # 负对照: 同 seed 不绑 → 主轴完全相同的馆少 1 个磁力位
        g2 = make_game(seed=381)
        a2, _b2 = g2.heroes
        g2.refresh_tavern(a2, free=True)
        mags2 = [e for e in a2.tavern
                 if isinstance(e, Minion) and e.has(GameTag.MAGNETIC)]
        self.assertEqual(len(a.tavern), len(a2.tavern) + 1)
        self.assertEqual(len(mags2), 0)
        self.assertEqual(len(mags), len(mags2) + 1)

    def test_opponent_tavern_and_cost_unaffected(self):
        g = make_game(seed=382)
        a, b = g.heroes
        bind(g, a, ELECTRODE_ATTRACTOR)
        # owner 隔离: 规则只挂在本人（hero 级），对手无任何规则
        self.assertEqual(len(a._tavern_extra_keyword), 1)
        self.assertEqual(len(a._tavern_cost_rules), 1)
        self.assertEqual(b._tavern_extra_keyword, [])
        self.assertEqual(b._tavern_cost_rules, [])
        g.refresh_tavern(a, free=True)
        mags = [e for e in a.tavern
                if isinstance(e, Minion) and e.has(GameTag.MAGNETIC)]
        self.assertTrue(mags)                                 # 本人正效果
        # 对手购买磁力机械 → 原价 3（折扣不越界到对手）
        g.minion_pool.acquire(MAGNETIC_MECH)
        mag = g.create_minion(MAGNETIC_MECH, controller=b)
        mag.zone = Zone.TAVERN
        b.tavern.append(mag)
        b.gold = 10
        self.assertTrue(g.buy_from_tavern(b, mag))
        self.assertEqual(b.gold, 7)
        # 正对照: 本人同价购买 → 2 金
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, mags[0]))
        self.assertEqual(a.gold, 8)

    def test_trinket_removal_disables_both_effects(self):
        g = make_game(seed=383)
        a, _b = g.heroes
        t = bind(g, a, ELECTRODE_ATTRACTOR)
        g.minion_pool.acquire(MAGNETIC_MECH)
        mag = g.create_minion(MAGNETIC_MECH, controller=a)
        mag.zone = Zone.TAVERN
        a.tavern.append(mag)
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, mag))           # 正效果: 折扣
        self.assertEqual(a.gold, 8)
        a.trinkets.remove(t)
        g.minion_pool.acquire(MAGNETIC_MECH)
        mag2 = g.create_minion(MAGNETIC_MECH, controller=a)
        mag2.zone = Zone.TAVERN
        a.tavern.append(mag2)
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, mag2))
        self.assertEqual(a.gold, 7)                          # 移除后失效
        g.refresh_tavern(a, free=True)
        self.assertEqual([e for e in a.tavern
                          if isinstance(e, Minion)
                          and e.has(GameTag.MAGNETIC)], [])

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=384)
            a, _b = g.heroes
            bind(g, a, ELECTRODE_ATTRACTOR)
            g.refresh_tavern(a, free=True)
            results.append([(e.card_id, e.get(GameTag.MAGNETIC, False))
                            for e in a.tavern])
        self.assertEqual(results[0], results[1])
        self.assertEqual(len([r for r in results[0] if r[1]]), 1)


# ══════════════ BG35_MagicItem_755 Chillmere Mosaic ══════════════


class TestChillmereMosaic(unittest.TestCase):
    def test_cost_rule_uses_stable_identity(self):
        """BUG-1 回归: 1 费规则只作用于**本次刷新**抽到的战吼随从。

        旧实现用 `id(entity)` → 同回合再次刷新时旧实体回池释放、CPython
        复用地址 → 新抽随从白拿 1 费。
        """
        g = make_game(seed=7551)
        a, b = g.heroes
        a.gold = 30
        a.set(GameTag.TAVERN_TIER, 4)
        t = bind(g, a, CHILLMERE_MOSAIC)
        spell = next(x for x in a.hand
                     if x.card_id == CHILLMERE_SPELL)
        g.play_spell(a, spell)                     # 第 1 次刷新（战吼族）
        first = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(first)
        g.refresh_tavern(a, free=True)             # 第 2 次刷新（普通族）
        second = [e for e in a.tavern if isinstance(e, Minion)]
        rules = list(getattr(a, "_tavern_cost_rules", []))
        self.assertTrue(rules)
        pred = rules[0][1]
        for m in second:
            self.assertFalse(pred(m),
                             f"非本次刷新的随从命中 1 费规则: {m.card_id}")

    """755 (+ token 755t) — Spellcraft: Refresh the Tavern with Battlecry
    minions. They cost (1)。"""

    def test_bind_grants_spellcraft_spell(self):
        g = make_game(seed=390)
        a, b = g.heroes
        t = bind(g, a, CHILLMERE_MOSAIC)
        spells = [c for c in a.hand if c.card_id == CHILLMERE_SPELL]
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))
        self.assertEqual(spells[0].spellcraft_source_uuid, t.uuid)
        self.assertEqual([c for c in b.hand
                          if c.card_id == CHILLMERE_SPELL], [])

    def test_play_refreshes_with_battlecry_and_cost_one(self):
        g = make_game(seed=391)
        a, _b = g.heroes
        bind(g, a, CHILLMERE_MOSAIC)
        spell = [c for c in a.hand if c.card_id == CHILLMERE_SPELL][0]
        self.assertTrue(g.play_spell(a, spell))
        tavern_minions = [e for e in a.tavern if isinstance(e, Minion)]
        self.assertTrue(tavern_minions)
        self.assertTrue(all(e.has(GameTag.BATTLECRY)
                            for e in tavern_minions))
        self.assertEqual(len(a._tavern_cost_rules), 1)
        target = tavern_minions[0]
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, target))
        self.assertEqual(a.gold, 9)                          # "They cost (1)"
        # 负对照: 同 seed 不绑/不施放 → 原价（3 金）
        g2 = make_game(seed=391)
        a2, _b2 = g2.heroes
        m2 = g2.create_minion(BATTLECRY_T1, controller=a2)
        m2.zone = Zone.TAVERN
        a2.tavern.append(m2)
        a2.gold = 10
        self.assertTrue(g2.buy_from_tavern(a2, m2))
        self.assertEqual(a2.gold, 7)

    def test_cost_rule_cleared_at_turn_end(self):
        g = make_game(seed=392)
        a, _b = g.heroes
        bind(g, a, CHILLMERE_MOSAIC)
        spell = [c for c in a.hand if c.card_id == CHILLMERE_SPELL][0]
        g.play_spell(a, spell)
        self.assertEqual(len(a._tavern_cost_rules), 1)
        g.end_recruit_phase()                                # 真实回合末
        self.assertEqual(a._tavern_cost_rules, [])
        self.assertEqual(g.turn, 2)
        # 新回合的随机馆：手工刷出战吼随从，须按原价
        g.refresh_tavern(a, free=True, keywords={"battlecry"})
        battlecry = [e for e in a.tavern
                     if isinstance(e, Minion) and e.has(GameTag.BATTLECRY)]
        self.assertTrue(battlecry)
        a.gold = 10
        self.assertTrue(g.buy_from_tavern(a, battlecry[0]))
        self.assertEqual(a.gold, 7)                          # 规则未越界

    def test_regenerates_once_each_turn(self):
        g = make_game(seed=393)
        a, _b = g.heroes
        bind(g, a, CHILLMERE_MOSAIC)
        self.assertEqual(len([c for c in a.hand
                              if c.card_id == CHILLMERE_SPELL]), 1)
        g.end_recruit_phase()
        self.assertEqual(len([c for c in a.hand
                              if c.card_id == CHILLMERE_SPELL]), 1)  # 不双发
        self.assertEqual(len(a._tavern_cost_rules), 0)

    def test_opponent_tavern_unaffected(self):
        g = make_game(seed=394)
        a, b = g.heroes
        bind(g, a, CHILLMERE_MOSAIC)
        g.refresh_tavern(b, free=True)
        b_before = [e.card_id for e in b.tavern]
        spell = [c for c in a.hand if c.card_id == CHILLMERE_SPELL][0]
        g.play_spell(a, spell)
        self.assertTrue(all(e.has(GameTag.BATTLECRY)
                            for e in a.tavern if isinstance(e, Minion)))
        self.assertEqual([e.card_id for e in b.tavern], b_before)
        self.assertEqual(len(b._tavern_cost_rules), 0)

    def test_no_battlecry_minions_no_error(self):
        g = make_game(seed=395)
        a, _b = g.heroes
        bind(g, a, CHILLMERE_MOSAIC)
        spells = [c for c in a.hand if c.card_id == CHILLMERE_SPELL]
        a.set(GameTag.TAVERN_OFFER_MOD, -99)                 # 展示 0 个随从
        self.assertTrue(g.play_spell(a, spells[0]))
        self.assertEqual([e for e in a.tavern if isinstance(e, Minion)], [])
        self.assertEqual(a._tavern_cost_rules, [])
        # 正对照: 解除覆写后再施放一张 → 战吼馆 + 规则 1 条
        a.clear(GameTag.TAVERN_OFFER_MOD)
        s2 = g.create_spell(CHILLMERE_SPELL, controller=a)
        s2.scripts = REGISTRY.get(CHILLMERE_SPELL)
        assert a.add_to_hand(s2)
        self.assertTrue(g.play_spell(a, s2))
        self.assertTrue(all(e.has(GameTag.BATTLECRY)
                            for e in a.tavern if isinstance(e, Minion)))
        self.assertEqual(len(a._tavern_cost_rules), 1)

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=396)
            a, _b = g.heroes
            bind(g, a, CHILLMERE_MOSAIC)
            spell = [c for c in a.hand if c.card_id == CHILLMERE_SPELL][0]
            g.play_spell(a, spell)
            results.append([e.card_id for e in a.tavern
                            if isinstance(e, Minion)])
        self.assertEqual(results[0], results[1])
        self.assertTrue(results[0])


# ══════════════ BG35_MagicItem_433 Vinespeaker Portrait ══════════════


class TestVinespeakerPortrait(unittest.TestCase):
    """433 — Get a Vinespeaker; your Vinespeakers also improve the Health
    given by your Blood Gems。"""

    def test_bind_grants_vinespeaker_zero_pool(self):
        g = make_game(seed=400)
        a, b = g.heroes
        pool_before = pool_snapshot(g)
        bind(g, a, VINESPEAKER_PORTRAIT)
        vs = [m for m in a.hand if m.card_id == VINESPEAKER]
        self.assertEqual(len(vs), 1)
        self.assertEqual([m for m in b.hand if m.card_id == VINESPEAKER], [])
        self.assertEqual(pool_snapshot(g), pool_before)   # 非池卡零池操作

    def test_deathrattle_death_improves_gem_health_production_point(self):
        g = make_game(seed=401)
        a, _b = g.heroes
        bind(g, a, VINESPEAKER_PORTRAIT)
        put(g, a, VINESPEAKER)
        target = put(g, a, UNDEAD_T1)
        dr = put(g, a, DEATHRATTLE_T1)
        dr.health = 0
        g.check_deaths()
        n = num_of(VINESPEAKER, 0)
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), n)
        # 生产消费点: 真实 PlayBloodGems 实际多给 n 点生命
        before = (target.atk, target.max_health)
        PlayBloodGems(target, 1).do(g)
        gem_atk = num_of(GEM, 0)
        gem_hp = num_of(GEM, 1)
        self.assertEqual(target.max_health, before[1] + gem_hp + n)
        self.assertEqual(target.atk, before[0] + gem_atk + n)

    def test_two_vinespeakers_and_golden_amount(self):
        g = make_game(seed=402)
        a, _b = g.heroes
        bind(g, a, VINESPEAKER_PORTRAIT)
        put(g, a, VINESPEAKER)
        put(g, a, VINESPEAKER)
        put_golden(g, a, VINESPEAKER_G)
        n = num_of(VINESPEAKER, 0)
        ng = num_of(VINESPEAKER_G, 0)
        dr = put(g, a, DEATHRATTLE_T1)
        dr.health = 0
        g.check_deaths()
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0),
                         2 * n + ng)
        # 交叉核对: 三只 Vinespeaker 本体各触发一次 Attack 改进
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0),
                         2 * n + ng)

    def test_non_deathrattle_death_not_counted(self):
        g = make_game(seed=403)
        a, _b = g.heroes
        bind(g, a, VINESPEAKER_PORTRAIT)
        put(g, a, VINESPEAKER)
        plain = put(g, a, UNDEAD_T1)                          # 无亡语
        plain.health = 0
        g.check_deaths()
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 0)
        # 正效果: 亡语随从死亡 → +num(0)
        dr = put(g, a, DEATHRATTLE_T1)
        dr.health = 0
        g.check_deaths()
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0),
                         num_of(VINESPEAKER, 0))

    def test_opponent_deathrattle_death_not_counted(self):
        g = make_game(seed=404)
        a, b = g.heroes
        bind(g, a, VINESPEAKER_PORTRAIT)
        put(g, a, VINESPEAKER)
        enemy_dr = put(g, b, DEATHRATTLE_T1)
        enemy_dr.health = 0
        g.check_deaths()
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 0)
        mine_dr = put(g, a, DEATHRATTLE_T1)
        mine_dr.health = 0
        g.check_deaths()
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0),
                         num_of(VINESPEAKER, 0))

    def test_no_vinespeaker_on_board_not_counted(self):
        g = make_game(seed=405)
        a, _b = g.heroes
        bind(g, a, VINESPEAKER_PORTRAIT)
        dr = put(g, a, DEATHRATTLE_T1)                        # 板上无 Vinespeaker
        dr.health = 0
        g.check_deaths()
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0), 0)
        put(g, a, VINESPEAKER)                                # 正效果
        dr2 = put(g, a, DEATHRATTLE_T1)
        dr2.health = 0
        g.check_deaths()
        self.assertEqual(a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0),
                         num_of(VINESPEAKER, 0))

    def test_same_seed_reproducible(self):
        results = []
        for _ in range(2):
            g = make_game(seed=406)
            a, _b = g.heroes
            bind(g, a, VINESPEAKER_PORTRAIT)
            put(g, a, VINESPEAKER)
            dr = put(g, a, DEATHRATTLE_T1)
            dr.health = 0
            g.check_deaths()
            results.append((a.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0),
                            a.get(GameTag.BLOOD_GEM_BONUS_ATK, 0)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], num_of(VINESPEAKER, 0))


if __name__ == "__main__":
    unittest.main()
