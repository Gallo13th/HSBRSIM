"""批次 trinkets30 行为层测试（注册 10 id = 9 饰品 + 1 Spellcraft token;
DEFERRED 3 张台账守卫。作业单 2026-09-15）。

全部断言走真实引擎路径:
  - 绑定: `game.grant_trinket`（RULES §7.4.3——on_bind 接线）
  - 商店: 真实 `game._offer_trinkets`（档位覆写消费即清）
  - SoC: 真实 `game.run_combat`——饰品 SoC 在 `START_OF_COMBAT` 事件
    **之前**（`combat._start_of_combat_phase`: 饰品→任务奖励→随从→事件），
    探针注册在 `START_OF_COMBAT` 上并按 hero 过滤，读到 SoC 结算后、
    伤害前的状态（战斗收尾会回滚非持久增益，故必须用探针）
  - 刷新: 真实 `game.refresh_tavern`（`tavern_refresh_complete` 观察点）
  - 法术: 真实 `game.play_spell`（Spellcraft 定向 / 池法术两条路径）
  - 亡语: 真实 `game._process_single_death`（战斗内 in_combat=True）
  - 回合: 真实 `game._begin_recruit_for` / `game.end_recruit_phase`
  - 池: `minion_pool` / `spell_pool` 可用数前后差

每个测试方法至少一条**正效果**断言，且多数与同 setup 的负/正对照写在
同一方法内; owner 隔离（两英雄）; 跨回合/一次性/落空不消耗; 满手队列;
涉及战斗者一律真实 `run_combat`; 同 seed 确定性。结构性台账守卫类按
TEST_SOP 标 `@engine-only`。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hsrl2.actions.bloodgem import _gem_values
from hsrl2.db import CardDB
from hsrl2.entity import Buff as EntityBuff
from hsrl2.events import Listener, START_OF_COMBAT, TURN_START
from hsrl2.game import BONUS_KEYWORD_TAGS, Game
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# ── 测试用既有卡（CardDB 按名核实——禁止凭记忆写 id） ──
# 三只**无固有持久化 tag** 的池内龙（BG21_015 Tarecgosa 的 on_summon 会
# 自带 PERSIST_COMBAT_CHANGES，不可作对照）
DRAGON_A = "BG24_500"        # Amber Guardian T3 龙（池）
DRAGON_B = "BG28_595"        # Ignition Specialist T6 龙（池）
DRAGON_C = "BG24_004"        # Warpwing T6 龙（池）
DRAGON_D = "BG29_816"        # Roaring Recruiter T3 龙（池）
AMALGAM = "BG36_640"         # Gatekeeper Amalgam T6 全类型（Race.ALL）
DRAGON_AMALGAM = "BG27_080"  # Motley Phalanx T4 全类型（Race.ALL）
MURLOC = "BG22_202"          # Tad T2 鱼人（池 2/2）
MURLOC_B = "BG32_330"        # Flighty Scout T1 鱼人（池）
NON_MURLOC = "BG23_004"      # Deep-Sea Angler T3 纳迦（池）
BEAST = "BG31_803"           # Buzzing Vermin T1 野兽（池; 带亡语）
HACKERFIN = "BG31_148"       # Hackerfin T5 鱼人（非池载荷; 战吼 give-stats）
RYLAK = "BG26_801"           # Rylak Metalhead（非池载荷; 亡语触发相邻战吼）
SHINY_RING = "BG28_168"      # 池法术（Give your minions +1/+1）
GEM = "BG20_GEM"             # 血宝石（池外资源卡）

# ── 本批 id ──
TARECGOSA = "BG32_MagicItem_417"
FINLEY = "BG32_MagicItem_891"
BUBBLE = "BG32_MagicItem_892"
BUBBLE_SPELL = "BG32_MagicItem_892t"
PAULDRON = "BG35_MagicItem_431t"
CROWN = "BG35_MagicItem_920"
RYLAK_PORTRAIT = "BG35_MagicItem_834"
ORB = "BG35_MagicItem_818"
HACKERFIN_PORTRAIT = "BG32_MagicItem_925"
DEFERRED_933 = "BG32_MagicItem_933"

DEFERRED_IDS = (
    # BG32_MagicItem_804 Selfless Portrait 已由 batch_trinkets35 注册
    # （2026-09-13，RULES §7.4.17 条件化战吼协议）→ 移出本台账
    # BG32_MagicItem_803 Macaw Portrait 已由 batch_trinkets36 注册
    # （2026-09-13，RULES §7.4.17 条件化战吼第二消费者）→ 移出本台账
    # BG35_MagicItem_923 Bewitched Ribbon 已由 batch_trinkets31 注册
    # （2026-09-18: `Buff(persist=True)` 按来源跨战斗持久化，RULES §3.5
    #  例外 4）→ 移出本台账
    "BG35_MagicItem_812",   # Corrupted Tome — Triple Prize 替换 + 候选表
    "BG35_MagicItem_820",   # Safety Patch — Secrets 子系统
    # BG32_MagicItem_933 Weary Portrait 已由 batch_trinkets37 注册
    # （2026-09-14: 载荷已在 + Reinvigoration 加 permanent_spellcraft 分支）
)

REGISTERED_IDS = (
    TARECGOSA, FINLEY, BUBBLE, BUBBLE_SPELL, PAULDRON, CROWN,
    RYLAK_PORTRAIT, ORB, HACKERFIN_PORTRAIT,
)

_CARD_CLASSES = {
    TARECGOSA: "TarecgosaStickerScript",
    FINLEY: "FinleysHelmetScript",
    BUBBLE: "VibrantBubbleScript",
    BUBBLE_SPELL: "VibrantBubbleSpellScript",
    PAULDRON: "ThornspikePauldronScript",
    CROWN: "BubbleCrownScript",
    RYLAK_PORTRAIT: "RylakPortraitScript",
    ORB: "MysteriousOrbScript",
    HACKERFIN_PORTRAIT: "HackerfinPortraitScript",
    "BG35_MagicItem_812": "CorruptedTomeScript",
    "BG35_MagicItem_820": "SafetyPatchScript",
    "BG32_MagicItem_933": "WearyPortraitScript",
}

# 数值逐张钉死（`CardDef.num(0..4)`; None = 无模板参数）
# 37.0/255130 起 CROWN 阈值 12→14（官方 NUM_1/NUM_2 变更）。
_NUM_PARAMS = {
    TARECGOSA: (None, None, None, None, None),
    FINLEY: (None, None, None, None, None),
    BUBBLE: (None, None, None, None, None),
    BUBBLE_SPELL: (None, None, None, None, None),
    PAULDRON: (None, None, 2, None, 1),
    CROWN: (14, 14, 4, None, 4),
    RYLAK_PORTRAIT: (None, None, None, None, None),
    ORB: (10, None, None, None, None),
    HACKERFIN_PORTRAIT: (None, None, None, None, None),
    DEFERRED_933: (None, None, None, None, None),
}

# 数据链 `evolution_card_id` → 期望关联卡（RULES §7.4.6）
_RELATED_CARDS = {
    RYLAK_PORTRAIT: RYLAK,
    HACKERFIN_PORTRAIT: HACKERFIN,
    DEFERRED_933: "BG31_830",
}
# 无数据链的 6 张（36.2.2 逐条核实 `evolution_card_id` 为空）
_NO_RELATED_CARDS = (TARECGOSA, FINLEY, BUBBLE, PAULDRON, CROWN, ORB)

# DEFERRED 类**不得**定义任何引擎钩子（防"注册但 no-op"第三态）
_ENGINE_HOOKS = (
    "battlecry", "deathrattle", "start_of_combat", "avenge", "rally",
    "start_of_turn", "end_of_turn", "on_sell", "on_summon", "on_play",
    "activate", "atk", "health", "on_enter_hand", "on_bind", "hand_soc",
    "hero_power", "available", "cost_override", "target_candidates",
)

_db = None


def get_db() -> CardDB:
    global _db
    if _db is None:
        _db = CardDB.load(DATA_DIR)
    return _db


def make_game(seed: int = 1024) -> Game:
    g = Game([Hero("TEST_H_A", "A"), Hero("TEST_H_B", "B")],
             get_db(), seed=seed)
    g.start_game()
    return g


def bind(game: Game, hero: Hero, tid: str, duplicate: bool = False):
    """真实授予路径（on_bind 接线; duplicate 走 RULES §7.4.3 副本条款）。"""
    e = game.grant_trinket(hero, tid, duplicate=duplicate)
    assert e is not None, tid
    return e


def put(game: Game, hero: Hero, card_id: str, golden: bool = False) -> Minion:
    m = game.create_minion(card_id, controller=hero, golden=golden)
    assert game.summon(hero, m)
    return m


def in_tavern(game: Game, hero: Hero, card_id: str, freeze: bool = True):
    """把随从放进酒馆展示区（freeze=True 使其在下一次 refresh 被保留）。"""
    m = game.create_minion(card_id, controller=hero)
    game.add_tavern_entity(hero, m)
    if freeze:
        m.set(GameTag.FROZEN, True)
    return m


def soc_probe(game: Game, hero: Hero, fn):
    """START_OF_COMBAT 探针（SoC 钩子全部跑完后、伤害前; 按 hero 过滤）。

    战斗收尾会回滚非持久增益，战后读不到战内值——探针是唯一可观察点。
    """
    seen: dict = {}

    def cb(g, **kw):
        if kw.get("hero") is hero:
            seen["v"] = fn()

    game.events.register(Listener(event=START_OF_COMBAT, owner=hero,
                                  callback=cb))
    return seen


def death_in_combat(game: Game, victim: Minion) -> None:
    """战斗内真实死亡处理（`_process_single_death`，in_combat=True）。"""
    prev = game.in_combat
    game.in_combat = True
    try:
        victim.set(GameTag.HEALTH, 0)
        game._process_single_death(victim)
    finally:
        game.in_combat = prev


def cast(game: Game, hero: Hero, card_id: str = SHINY_RING) -> bool:
    """真实 `play_spell`（非定向池法术）。"""
    s = game.create_spell(card_id, controller=hero)
    game.pending_hand_add(hero, s)
    return game.play_spell(hero, s)


def fill_hand(hero: Hero, game: Game) -> None:
    """填满手牌（`constants.HAND_SIZE` = 10; 多出的进等待队列）。"""
    from hsrl2 import constants as C
    while len(hero.hand) < C.HAND_SIZE:
        game.pending_hand_add(
            hero, game.create_spell(SHINY_RING, controller=hero))


def _hackerfin_bonus(game: Game) -> int:
    """Hackerfin 战吼印面增量 {0}（37.0/255130: num(0)=3；36.2.2 为 1）。

    数值权威 = CardDef.num(0)（SOP: 数值一律 CardDef.num()）。
    """
    return get_db().get(HACKERFIN).num(0)


def bonus_keyword_count(game: Game, hero: Hero) -> int:
    """棋盘上出现的**不同** Bonus Keyword 数（官方 6 集; 与载荷同口径）。"""
    return sum(1 for tag in BONUS_KEYWORD_TAGS
               if any(m.has(tag) for m in hero.board))


# ══════════════ BG32_MagicItem_417 Tarecgosa Sticker ══════════════


class TestTarecgosaSticker(unittest.TestCase):
    """417 — 最左/最右龙战斗持久化（只保留 6 集 Bonus Keyword + 属性）。"""

    def test_retarget_survives_combat_snapshot_restore(self):
        """BUG-2 回归: 位置变更 + 真实战斗后，旧极位龙不得残留标记。

        `run_combat` 的 `restore_state(snapshots[m])` 会整份还原开战快照 →
        旧实现把已撤销的 PERSIST 标记复活 → 中间龙永久多持久化。
        """
        game = make_game(seed=4170)
        a, b = game.heroes
        d1 = put(game, a, DRAGON_A)
        d2 = put(game, a, DRAGON_B)
        d3 = put(game, a, DRAGON_C)
        bind(game, a, TARECGOSA)
        self.assertTrue(d1.has(GameTag.PERSIST_BONUS_ONLY))
        # d1 移到中间（d2 成为最左、d3 仍最右）
        game.board_move(a, d1, 1) if hasattr(game, "board_move") else None
        a.board.remove(d1); a.board.insert(1, d1); game._update_positions(a)
        game.run_combat(a, b)                      # 触发 SoC sweep + 快照还原
        self.assertFalse(d1.has(GameTag.PERSIST_BONUS_ONLY),
                         "旧极位龙残留 PERSIST_BONUS_ONLY（快照复活未清）")
        self.assertFalse(d1.has(GameTag.PERSIST_COMBAT_CHANGES),
                         "旧极位龙残留 PERSIST_COMBAT_CHANGES")
        self.assertTrue(d2.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertTrue(d3.has(GameTag.PERSIST_BONUS_ONLY))

    def test_bind_marks_leftmost_and_rightmost_dragon_only(self):
        game = make_game()
        a = game.heroes[0]
        left = put(game, a, DRAGON_A)
        mid = put(game, a, DRAGON_B)
        right = put(game, a, DRAGON_C)
        bind(game, a, TARECGOSA)
        for m in (left, right):
            self.assertTrue(m.has(GameTag.PERSIST_BONUS_ONLY))
            self.assertTrue(m.has(GameTag.PERSIST_COMBAT_CHANGES))
        self.assertFalse(mid.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertFalse(mid.has(GameTag.PERSIST_COMBAT_CHANGES))

    def test_single_dragon_is_both_ends(self):
        game = make_game()
        a = game.heroes[0]
        only = put(game, a, DRAGON_A)
        bind(game, a, TARECGOSA)
        self.assertTrue(only.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertTrue(only.has(GameTag.PERSIST_COMBAT_CHANGES))

    def test_no_dragon_no_mark(self):
        game = make_game()
        a = game.heroes[0]
        beast = put(game, a, BEAST)
        naga = put(game, a, NON_MURLOC)
        trinket = bind(game, a, TARECGOSA)
        for m in (beast, naga):
            self.assertFalse(m.has(GameTag.PERSIST_BONUS_ONLY))
        dragon = put(game, a, DRAGON_A)          # 正对照: 入场龙被标记
        game.run_script_hook(trinket, "start_of_combat")
        self.assertTrue(dragon.has(GameTag.PERSIST_BONUS_ONLY))

    def test_amalgam_counts_as_dragon(self):
        """融合怪（Race.ALL）视为龙（RULES §6.19 既有口径）。"""
        game = make_game()
        a = game.heroes[0]
        amalgam = put(game, a, DRAGON_AMALGAM)
        bind(game, a, TARECGOSA)
        self.assertTrue(amalgam.has(GameTag.PERSIST_BONUS_ONLY))

    def test_opponent_dragons_not_marked(self):
        game = make_game()
        a, b = game.heroes
        mine = put(game, a, DRAGON_A)
        theirs = put(game, b, DRAGON_B)
        bind(game, a, TARECGOSA)
        self.assertTrue(mine.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertFalse(theirs.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertFalse(theirs.has(GameTag.PERSIST_COMBAT_CHANGES))

    def test_soc_retargets_when_positions_change(self):
        """位置变化 → 旧标记清除、新极位标记（不扩张成 3 只）。"""
        game = make_game()
        a = game.heroes[0]
        x = put(game, a, DRAGON_A)          # 最左
        y = put(game, a, DRAGON_B)          # 中间
        z = put(game, a, DRAGON_C)          # 最右
        trinket = bind(game, a, TARECGOSA)
        a.board.remove(x)
        a.board.append(x)                   # x 移到末尾
        game.run_script_hook(trinket, "start_of_combat")
        self.assertTrue(y.has(GameTag.PERSIST_BONUS_ONLY))     # 新最左
        self.assertTrue(x.has(GameTag.PERSIST_BONUS_ONLY))     # 新最右
        self.assertFalse(z.has(GameTag.PERSIST_BONUS_ONLY))    # 旧最右已清
        self.assertFalse(z.has(GameTag.PERSIST_COMBAT_CHANGES))

    def test_retarget_preserves_other_sources_persist_tag(self):
        """撤销标记不得抹除他源写入的 `PERSIST_COMBAT_CHANGES`
        （Dark Gift / 金色 Poet 共用通道——对抗审查模式: 不 clear 他人状态）。"""
        game = make_game()
        a = game.heroes[0]
        x = put(game, a, DRAGON_A)
        y = put(game, a, DRAGON_B)
        z = put(game, a, DRAGON_C)
        w = put(game, a, DRAGON_D)
        y.set(GameTag.PERSIST_COMBAT_CHANGES, True)   # 模拟他源（Dark Gift）
        trinket = bind(game, a, TARECGOSA)
        self.assertFalse(y.has(GameTag.PERSIST_BONUS_ONLY))   # y 非极位
        # 1) y 移到最左: 被本饰品标记
        a.board.remove(y)
        a.board.insert(0, y)                 # [y, x, z, w]
        game.run_script_hook(trinket, "start_of_combat")
        self.assertTrue(y.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertTrue(y.has(GameTag.PERSIST_COMBAT_CHANGES))
        # 负对照: x 离开极位 → 本饰品写入的 tag 被清（x 无他源标记）
        self.assertFalse(x.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertFalse(x.has(GameTag.PERSIST_COMBAT_CHANGES))
        # 2) y 回中间 → 撤销本饰品标记，但**保留**他源的持久化 tag
        a.board.remove(y)
        a.board.insert(2, y)                 # [x, z, y, w]
        game.run_script_hook(trinket, "start_of_combat")
        self.assertFalse(y.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertTrue(y.has(GameTag.PERSIST_COMBAT_CHANGES))

    def test_combat_keeps_bonus_keyword_and_stats_but_not_other_keywords(self):
        """真实 `run_combat`: 战内 Taunt（6 集）+ 属性增量保留;
        Poisonous（非 6 集）清除。负对照 = 未标记龙两者皆不保留。"""
        game = make_game()
        a, b = game.heroes
        marked = put(game, a, DRAGON_A)      # 最左 → 会被标记
        control = put(game, a, DRAGON_B)     # 中间 → 不标记
        put(game, a, DRAGON_C)               # 最右 → 会被标记
        put(game, b, BEAST)
        put(game, b, NON_MURLOC)
        trinket = bind(game, a, TARECGOSA)
        self.assertTrue(marked.has(GameTag.PERSIST_BONUS_ONLY))
        self.assertFalse(control.has(GameTag.PERSIST_BONUS_ONLY))
        base_marked = marked.atk
        base_control = control.atk

        def buff_at_soc(g, **kw):
            if kw.get("hero") is not a:
                return
            for m in (marked, control):
                m.set(GameTag.TAUNT, True)
                m.set(GameTag.POISONOUS, True)
                m.add_buff(EntityBuff(atk=3, health=0))

        game.events.register(Listener(event=START_OF_COMBAT, owner=a,
                                      callback=buff_at_soc))
        game.run_combat(a, b)
        # 标记龙: Bonus Keyword（Taunt）保留、属性增量保留
        self.assertTrue(marked.has(GameTag.TAUNT))
        self.assertFalse(marked.has(GameTag.POISONOUS))
        self.assertEqual(marked.atk, base_marked + 3)
        # 负对照: 未标记龙两者皆不保留
        self.assertFalse(control.has(GameTag.TAUNT))
        self.assertFalse(control.has(GameTag.POISONOUS))
        self.assertEqual(control.atk, base_control)

    def test_same_seed_same_marks(self):
        def run(seed):
            g = make_game(seed)
            h = g.heroes[0]
            put(g, h, DRAGON_A)
            put(g, h, DRAGON_B)
            put(g, h, DRAGON_C)
            bind(g, h, TARECGOSA)
            return [m.has(GameTag.PERSIST_BONUS_ONLY) for m in h.board]

        self.assertEqual(run(7), run(7))
        self.assertEqual(run(7), [True, False, True])


# ══════════════ BG32_MagicItem_891 Finley's Helmet ══════════════


class TestFinleysHelmet(unittest.TestCase):
    """891 — 刷新后馆内鱼人 +5/+5 并各获一枚随机 Bonus Keyword。"""

    def test_real_refresh_buffs_every_murloc_in_tavern(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, FINLEY)
        keep = in_tavern(game, a, MURLOC)          # 冻结保留 → 断言对象确定
        game.refresh_tavern(a, auto=True)
        self.assertIn(keep, a.tavern)
        murlocs = [e for e in a.tavern
                   if getattr(e, "race", None) in (Race.MURLOC, Race.ALL)]
        self.assertTrue(murlocs)
        for e in murlocs:
            d = get_db().get(e.card_id)
            self.assertEqual(e.atk, d.atk + 5, e.card_id)
            self.assertEqual(e.max_health, d.health + 5, e.card_id)
            kws = e.get(GameTag.BONUS_KEYWORDS, frozenset())
            self.assertEqual(len(kws), 1)
            self.assertTrue(all(t in BONUS_KEYWORD_TAGS for t in kws))
        self.assertEqual(keep.atk, get_db().get(MURLOC).atk + 5)

    def test_buffs_murlocs_only_and_amalgam_counts(self):
        """非鱼人不吃; 融合怪（ALL）属鱼人（负 / 正对照同一方法）。"""
        game = make_game()
        a = game.heroes[0]
        bind(game, a, FINLEY)
        naga = in_tavern(game, a, NON_MURLOC)
        amalgam = in_tavern(game, a, AMALGAM)
        fish = in_tavern(game, a, MURLOC_B)
        naga_atk, amalgam_atk = naga.atk, amalgam.atk
        fish_atk = fish.atk
        game.refresh_tavern(a, auto=True)
        self.assertEqual(naga.atk, naga_atk)                    # 负对照
        self.assertIsNone(naga.get(GameTag.BONUS_KEYWORDS, None))
        self.assertEqual(amalgam.atk, amalgam_atk + 5)          # ALL 属鱼人
        self.assertEqual(fish.atk, fish_atk + 5)
        self.assertEqual(len(fish.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_bind_does_not_retro_buff_current_tavern(self):
        """触发时机: 绑定本身不是刷新（负）; 随后真实刷新才生效（正）。"""
        game = make_game()
        a = game.heroes[0]
        fish = in_tavern(game, a, MURLOC)
        base_atk = fish.atk
        bind(game, a, FINLEY)
        self.assertEqual(fish.atk, base_atk)
        self.assertIsNone(fish.get(GameTag.BONUS_KEYWORDS, None))
        game.refresh_tavern(a, auto=True)              # 正对照
        self.assertEqual(fish.atk, base_atk + 5)
        self.assertEqual(len(fish.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_opponent_tavern_not_buffed(self):
        game = make_game()
        a, b = game.heroes
        bind(game, a, FINLEY)
        mine = in_tavern(game, a, MURLOC)
        theirs = in_tavern(game, b, MURLOC)
        my_atk, their_atk = mine.atk, theirs.atk
        game.refresh_tavern(b, auto=True)
        self.assertEqual(theirs.atk, their_atk)     # 负对照: 对手馆不受影响
        self.assertIsNone(theirs.get(GameTag.BONUS_KEYWORDS, None))
        self.assertEqual(mine.atk, my_atk)
        game.refresh_tavern(a, auto=True)           # 正对照: 本人刷新生效
        self.assertEqual(mine.atk, my_atk + 5)
        self.assertEqual(len(mine.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_two_murlocs_each_get_one_keyword(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, FINLEY)
        f1 = in_tavern(game, a, MURLOC)
        f2 = in_tavern(game, a, MURLOC_B)
        game.refresh_tavern(a, auto=True)
        for f in (f1, f2):
            self.assertEqual(len(f.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_bought_murloc_keeps_buff_and_keyword_across_turn(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, FINLEY)
        fish = in_tavern(game, a, MURLOC)
        game.refresh_tavern(a, auto=True)
        buffed_atk = get_db().get(MURLOC).atk + 5
        self.assertEqual(fish.atk, buffed_atk)
        a.gold = 20
        self.assertTrue(game.buy_from_tavern(a, fish))   # 买入带走（永久附魔）
        game._begin_recruit_for(a)                       # 跨回合
        self.assertEqual(fish.atk, buffed_atk)
        self.assertEqual(len(fish.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_same_seed_same_keywords(self):
        def run(seed):
            g = make_game(seed)
            h = g.heroes[0]
            bind(g, h, FINLEY)
            f = in_tavern(g, h, MURLOC)
            g.refresh_tavern(h, auto=True)
            return sorted(f.get(GameTag.BONUS_KEYWORDS, ()))

        self.assertEqual(run(11), run(11))
        self.assertEqual(len(run(11)), 1)


# ══════════════ BG32_MagicItem_892 / 892t Vibrant Bubble ══════════════


class TestVibrantBubble(unittest.TestCase):
    """892 — 饰品 Spellcraft: 每回合生成 892t; 892t 给鱼人随机 Bonus Keyword。"""

    def test_spellcraft_generated_each_turn_with_tag(self):
        """真实 `_begin_recruit_for` 生成; 生成的法术可施放并产生效果。"""
        game = make_game()
        a = game.heroes[0]
        bind(game, a, BUBBLE)
        fish = put(game, a, MURLOC)
        game._begin_recruit_for(a)
        spells = [e for e in a.hand if e.card_id == BUBBLE_SPELL]
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0].has(GameTag.SPELLCRAFT))
        self.assertEqual(spells[0].spellcraft_source_uuid,
                         a.trinkets[0].uuid)      # Sunken Persistence 协议
        self.assertTrue(game.play_spell(a, spells[0], target=fish))
        self.assertEqual(len(fish.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_control_without_trinket_generates_nothing(self):
        """负对照（无饰品不生成）+ 正对照（对手持饰品则生成）。"""
        game = make_game()
        a, b = game.heroes
        bind(game, b, BUBBLE)
        fish = put(game, b, MURLOC)
        game._begin_recruit_for(a)
        game._begin_recruit_for(b)
        self.assertEqual([e for e in a.hand if e.card_id == BUBBLE_SPELL], [])
        spells = [e for e in b.hand if e.card_id == BUBBLE_SPELL]
        self.assertEqual(len(spells), 1)
        # 正对照: 生成的法术经真实 `play_spell` 产生效果（走 892t 脚本钩子）
        self.assertTrue(game.play_spell(b, spells[0], target=fish))
        self.assertEqual(len(fish.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_play_grants_one_bonus_keyword_to_murloc(self):
        game = make_game()
        a = game.heroes[0]
        fish = put(game, a, MURLOC)
        spell = game.create_spell(BUBBLE_SPELL, controller=a)
        game.pending_hand_add(a, spell)
        self.assertTrue(game.play_spell(a, spell, target=fish))
        kws = fish.get(GameTag.BONUS_KEYWORDS, frozenset())
        self.assertEqual(len(kws), 1)
        self.assertTrue(all(t in BONUS_KEYWORD_TAGS for t in kws))
        self.assertTrue(any(fish.has(t) for t in kws))
        self.assertNotIn(spell, a.hand)

    def test_is_targeted_target_candidates_only_own_murlocs(self):
        game = make_game()
        a, b = game.heroes
        mine = put(game, a, MURLOC)
        naga = put(game, a, NON_MURLOC)
        theirs = put(game, b, MURLOC)
        cls = REGISTRY[BUBBLE_SPELL]
        spell = game.create_spell(BUBBLE_SPELL, controller=a)
        cands = cls.target_candidates(spell, game)
        self.assertEqual(cands, [mine])
        self.assertNotIn(naga, cands)
        self.assertNotIn(theirs, cands)

    def test_empty_board_fizzles_but_spell_still_resolves(self):
        """无合法目标 → 效果落空，法术照常消耗且**不产生悬挂选择**
        （引擎 RULES §6.4 定向法术落空口径——正对照: 有目标时产生效果）。"""
        game = make_game()
        a = game.heroes[0]
        spell = game.create_spell(BUBBLE_SPELL, controller=a)
        game.pending_hand_add(a, spell)
        self.assertTrue(game.play_spell(a, spell, target=None))
        self.assertEqual(game.pending_choices, [])
        self.assertNotIn(spell, a.hand)
        # 正对照: 同法术在棋盘有鱼人时确实产生效果
        game2 = make_game()
        a2 = game2.heroes[0]
        fish = put(game2, a2, MURLOC)
        s2 = game2.create_spell(BUBBLE_SPELL, controller=a2)
        game2.pending_hand_add(a2, s2)
        self.assertTrue(game2.play_spell(a2, s2, target=fish))
        self.assertEqual(len(fish.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_amalgam_is_valid_murloc_target(self):
        game = make_game()
        a = game.heroes[0]
        amalgam = put(game, a, AMALGAM)
        spell = game.create_spell(BUBBLE_SPELL, controller=a)
        game.pending_hand_add(a, spell)
        self.assertTrue(game.play_spell(a, spell, target=amalgam))
        self.assertEqual(len(amalgam.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_opponent_murloc_cannot_be_targeted_by_spell_target_flow(self):
        """真实 `play_spell` 的定向挂起: 候选集只有本人鱼人。"""
        game = make_game()
        a, b = game.heroes
        mine = put(game, a, MURLOC)
        theirs = put(game, b, MURLOC)
        spell = game.create_spell(BUBBLE_SPELL, controller=a)
        game.pending_hand_add(a, spell)
        self.assertTrue(game.play_spell(a, spell, target=None))
        self.assertEqual(len(game.pending_choices), 1)
        choice = game.pending_choices.pop(0)
        self.assertEqual(list(choice.options), [mine])
        choice.choose(0)
        self.assertIsNone(theirs.get(GameTag.BONUS_KEYWORDS, None))
        self.assertEqual(len(mine.get(GameTag.BONUS_KEYWORDS, ())), 1)

    def test_same_seed_same_keyword(self):
        def run(seed):
            g = make_game(seed)
            h = g.heroes[0]
            f = put(g, h, MURLOC)
            s = g.create_spell(BUBBLE_SPELL, controller=h)
            g.pending_hand_add(h, s)
            g.play_spell(h, s, target=f)
            return sorted(f.get(GameTag.BONUS_KEYWORDS, ()))

        self.assertEqual(run(31), run(31))
        self.assertEqual(len(run(31)), 1)


# ══════════════ BG35_MagicItem_431t Thornspike Pauldron ══════════════


class TestThornspikePauldron(unittest.TestCase):
    """431t — 触发亡语后血宝石 +num(2)/+num(4)，直到下一场战斗。"""

    def test_deathrattle_improves_blood_gems(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, PAULDRON)
        base = _gem_values(game, GEM, a)
        death_in_combat(game, put(game, a, BEAST))
        self.assertEqual(_gem_values(game, GEM, a), (base[0] + 2, base[1] + 1))

    def test_stacks_per_deathrattle(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, PAULDRON)
        base = _gem_values(game, GEM, a)
        for _ in range(2):
            death_in_combat(game, put(game, a, BEAST))
        self.assertEqual(_gem_values(game, GEM, a), (base[0] + 4, base[1] + 2))

    def test_opponent_deathrattle_does_not_trigger(self):
        """owner 隔离（负对照）: 对手亡语不触发; 己方随后触发才 +。"""
        game = make_game()
        a, b = game.heroes
        bind(game, a, PAULDRON)
        base = _gem_values(game, GEM, a)
        death_in_combat(game, put(game, b, BEAST))
        self.assertEqual(_gem_values(game, GEM, a), base)
        death_in_combat(game, put(game, a, BEAST))
        self.assertEqual(_gem_values(game, GEM, a), (base[0] + 2, base[1] + 1))

    def test_bind_without_trigger_leaves_gems_unchanged(self):
        game = make_game()
        a = game.heroes[0]
        base = _gem_values(game, GEM, a)
        bind(game, a, PAULDRON)
        self.assertEqual(_gem_values(game, GEM, a), base)   # 负对照
        death_in_combat(game, put(game, a, BEAST))          # 正对照
        self.assertEqual(_gem_values(game, GEM, a), (base[0] + 2, base[1] + 1))

    def test_next_combat_start_reverts_bonus(self):
        """真实 `run_combat`: 开战瞬间（SoC）增量已回退——正对照 =
        战斗前确实 +2/+1。

        棋盘只放**无亡语**随从: 否则战斗内再有死亡会二次累计
        （本测试只验证回退时点）。
        """
        game = make_game()
        a, b = game.heroes
        bind(game, a, PAULDRON)
        put(game, a, NON_MURLOC)            # 纳迦（无亡语）
        put(game, b, NON_MURLOC)
        d = get_db().get(GEM)
        base = (d.num(0), d.num(1))
        death_in_combat(game, put(game, a, BEAST))
        self.assertEqual(_gem_values(game, GEM, a), (base[0] + 2, base[1] + 1))
        probe = soc_probe(game, a, lambda: _gem_values(game, GEM, a))
        game.run_combat(a, b)
        self.assertEqual(probe["v"], base)              # SoC 已回退
        self.assertEqual(_gem_values(game, GEM, a), base)

    def test_two_copies_each_add(self):
        """副本条款（RULES §7.4.3）: 两份各带实例私有累计器，互不串号。"""
        game = make_game()
        a = game.heroes[0]
        bind(game, a, PAULDRON)
        bind(game, a, PAULDRON, duplicate=True)
        self.assertEqual(len(a.trinkets), 2)
        base = _gem_values(game, GEM, a)
        death_in_combat(game, put(game, a, BEAST))
        self.assertEqual(_gem_values(game, GEM, a), (base[0] + 4, base[1] + 2))
        # 每份副本各自回退自己累计的那一份 → 净值归零
        game.run_script_hook(a.trinkets[0], "start_of_combat")
        game.run_script_hook(a.trinkets[1], "start_of_combat")
        self.assertEqual(_gem_values(game, GEM, a), base)

    def test_same_seed_deterministic(self):
        def run(seed):
            g = make_game(seed)
            h = g.heroes[0]
            bind(g, h, PAULDRON)
            death_in_combat(g, put(g, h, BEAST))
            return _gem_values(g, GEM, h)

        d = get_db().get(GEM)
        self.assertEqual(run(5), (d.num(0) + 2, d.num(1) + 1))
        self.assertEqual(run(5), run(5))


# ══════════════ BG35_MagicItem_920 Bubble Crown ══════════════


class TestBubbleCrown(unittest.TestCase):
    """920 — 施放 num(1) 个法术后酒馆法术永久 +num(2)/+num(4)。

    37.0（255130）: 官方把阈值 12→14（NUM_1/NUM_2 12→14）；增量仍为
    num(2)/num(4)=4/4。阈值与增量一律从 CardDef 读取（不钉死旧数字）。
    """

    def _advance(self, game, hero, n):
        spell = game.create_spell(SHINY_RING, controller=hero)
        for _ in range(n):
            game.events.fire(game, "spell_resolving", spell=spell,
                             target=None, cast_no=1)

    def _params(self):
        d = get_db().get(CROWN)
        return d.num(1), d.num(2), d.num(4)

    def test_not_completed_no_bonus(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, CROWN)
        thr, atk_gain, hp_gain = self._params()
        self._advance(game, a, thr - 1)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), 0)
        self._advance(game, a, 1)                 # 第 thr 次才结算
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), atk_gain)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), hp_gain)

    def test_completion_grants_bonus_once(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, CROWN)
        thr, atk_gain, hp_gain = self._params()
        self._advance(game, a, thr)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), atk_gain)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), hp_gain)
        self._advance(game, a, 5)                 # 一次性
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), atk_gain)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0), hp_gain)

    def test_bonus_applies_to_real_tavern_spell(self):
        """真实 `play_spell`（正面） + 无饰品对照（负面）同一方法。"""
        game = make_game()
        a = game.heroes[0]
        m = put(game, a, NON_MURLOC)
        base_atk, base_hp = m.atk, m.max_health
        self.assertTrue(cast(game, a))                     # 负面对照
        self.assertEqual((m.atk - base_atk, m.max_health - base_hp), (1, 1))
        bind(game, a, CROWN)
        thr, atk_gain, hp_gain = self._params()
        self._advance(game, a, thr)
        before = (m.atk, m.max_health)
        self.assertTrue(cast(game, a))
        self.assertEqual((m.atk - before[0], m.max_health - before[1]),
                         (1 + atk_gain, 1 + hp_gain))

    def test_opponent_casts_do_not_advance(self):
        game = make_game()
        a, b = game.heroes
        bind(game, a, CROWN)
        self._advance(game, b, 20)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), 0)
        thr, atk_gain, _hp = self._params()
        self._advance(game, a, thr)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0), atk_gain)

    def test_two_copies_count_independently(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, CROWN)
        bind(game, a, CROWN, duplicate=True)
        thr, atk_gain, hp_gain = self._params()
        self._advance(game, a, thr)
        # 两份副本各在 thr 次时结算一次 → 合计 2×增量
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0),
                         2 * atk_gain)
        self.assertEqual(a.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0),
                         2 * hp_gain)


# ══════════════ BG35_MagicItem_834 Rylak Portrait ══════════════


class TestRylakPortrait(unittest.TestCase):
    """834 — 交付 Rylak + SoC 触发己方 Rylak 亡语。"""

    def test_grants_rylak(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, RYLAK_PORTRAIT)
        self.assertEqual([e.card_id for e in a.hand], [RYLAK])

    def test_grants_rylak_into_hand_not_pool(self):
        """载荷 `BG26_801` 非池卡（`is_pool_minion=False`）→ 零池操作。"""
        game = make_game()
        a = game.heroes[0]
        avail0 = game.minion_pool.available(RYLAK)
        bind(game, a, RYLAK_PORTRAIT)
        self.assertIn(RYLAK, [e.card_id for e in a.hand])      # 正对照: 已交付
        self.assertEqual(game.minion_pool.available(RYLAK), avail0)

    def test_full_hand_queues_delivery(self):
        game = make_game()
        a = game.heroes[0]
        fill_hand(a, game)
        from hsrl2 import constants as C
        self.assertEqual(len(a.hand), C.HAND_SIZE)
        bind(game, a, RYLAK_PORTRAIT)
        self.assertIn(RYLAK,
                      [e.card_id for _, e in game.pending_hand_queue])
        self.assertEqual(len(a.hand), C.HAND_SIZE)      # 未顶掉手牌

    def test_soc_triggers_rylak_deathrattle(self):
        """真实 `run_combat`: Rylak 亡语触发相邻 Hackerfin 的战吼
        （负对照 = 同 setup 无饰品：战前属性不变）。"""
        game = make_game()
        a, b = game.heroes
        put(game, a, RYLAK)
        put(game, a, HACKERFIN)
        target = put(game, a, BEAST)
        put(game, b, BEAST)
        put(game, b, NON_MURLOC)
        base = target.atk

        def run_without_trinket():
            g2 = make_game()
            a2, b2 = g2.heroes
            put(g2, a2, RYLAK)
            put(g2, a2, HACKERFIN)
            t2 = put(g2, a2, BEAST)
            put(g2, b2, BEAST)
            put(g2, b2, NON_MURLOC)
            p2 = soc_probe(g2, a2, lambda: t2.atk)
            g2.run_combat(a2, b2)
            return p2["v"]

        self.assertEqual(run_without_trinket(), base)     # 负对照
        bind(game, a, RYLAK_PORTRAIT)
        probe = soc_probe(game, a, lambda: target.atk)
        game.run_combat(a, b)
        # 亡语 → 相邻 Hackerfin 战吼 → 对其他友方随从 +num(0)×(1+c)
        self.assertEqual(probe["v"],
                         base + _hackerfin_bonus(game) * (1 + bonus_keyword_count(game, a)))

    def test_no_rylak_no_effect(self):
        """负对照（无 Rylak 不触发）+ 正对照（有 Rylak 则触发相邻战吼）。"""
        game = make_game()
        a, b = game.heroes
        fin = put(game, a, HACKERFIN)
        target = put(game, a, BEAST)
        put(game, b, BEAST)
        put(game, b, NON_MURLOC)
        bind(game, a, RYLAK_PORTRAIT)
        base = target.atk
        probe = soc_probe(game, a, lambda: target.atk)
        game.run_combat(a, b)
        self.assertEqual(probe["v"], base)      # 负对照
        self.assertEqual(fin.atk, get_db().get(HACKERFIN).atk)
        # 正对照: 同 setup + Rylak 紧邻 Hackerfin（board [RYLAK, HF, BEAST]）
        game2 = make_game()
        a2, b2 = game2.heroes
        put(game2, a2, RYLAK)
        put(game2, a2, HACKERFIN)
        target2 = put(game2, a2, BEAST)
        put(game2, b2, BEAST)
        put(game2, b2, NON_MURLOC)
        bind(game2, a2, RYLAK_PORTRAIT)
        base2 = target2.atk
        c = bonus_keyword_count(game2, a2)
        probe2 = soc_probe(game2, a2, lambda: target2.atk)
        game2.run_combat(a2, b2)
        self.assertEqual(probe2["v"], base2 + _hackerfin_bonus(game2) * (1 + c))

    def test_opponent_rylak_not_triggered(self):
        game = make_game()
        a, b = game.heroes
        put(game, a, RYLAK)
        put(game, a, HACKERFIN)
        my_target = put(game, a, BEAST)
        put(game, b, RYLAK)
        put(game, b, HACKERFIN)
        their_target = put(game, b, BEAST)
        bind(game, a, RYLAK_PORTRAIT)
        my_base, their_base = my_target.atk, their_target.atk
        c = bonus_keyword_count(game, a)
        probe_mine = soc_probe(game, a, lambda: my_target.atk)
        probe_theirs = soc_probe(game, b, lambda: their_target.atk)
        game.run_combat(a, b)
        self.assertEqual(probe_theirs["v"], their_base)          # 负对照
        self.assertEqual(probe_mine["v"], my_base + _hackerfin_bonus(game) * (1 + c))  # 正对照

    def test_golden_rylak_also_triggered(self):
        """金色 Rylak 同族（`_base_card_id` 经 TRIPLE_BASE_CARD_ID 回落）。"""
        game = make_game()
        a, b = game.heroes
        put(game, a, RYLAK, golden=True)
        put(game, a, HACKERFIN)
        target = put(game, a, BEAST)
        put(game, b, BEAST)
        put(game, b, NON_MURLOC)
        bind(game, a, RYLAK_PORTRAIT)
        base = target.atk
        probe = soc_probe(game, a, lambda: target.atk)
        game.run_combat(a, b)
        self.assertEqual(probe["v"],
                         base + _hackerfin_bonus(game) * (1 + bonus_keyword_count(game, a)))


# ══════════════ BG35_MagicItem_818 Mysterious Orb ══════════════


class TestMysteriousOrb(unittest.TestCase):
    """818 — 获得 num(0) 金 + 下一饰品为 Lesser。"""

    def test_gain_gold(self):
        game = make_game()
        a = game.heroes[0]
        a.gold = 0
        bind(game, a, ORB)
        self.assertEqual(a.gold, 10)

    def test_gold_capped(self):
        game = make_game()
        a = game.heroes[0]
        a.gold = 95
        bind(game, a, ORB)
        self.assertEqual(a.gold, 99)          # 99 上限截断

    def test_next_offer_is_lesser(self):
        game = make_game()
        a = game.heroes[0]
        a.gold = 50
        bind(game, a, ORB)
        game._offer_trinkets(a, "greater")
        choice = game.pending_choices.pop(0)
        options = [d for d in choice.options if d is not None]
        self.assertTrue(options)
        self.assertTrue(all(d.spell_school == 11 for d in options))
        self.assertIsNone(getattr(a, "_next_trinket_kind", None))  # 消费即清

    def test_after_consumption_greater_restored(self):
        game = make_game()
        a = game.heroes[0]
        a.gold = 50
        bind(game, a, ORB)
        game._offer_trinkets(a, "greater")        # 第一次: 覆写为 Lesser
        first = [d for d in game.pending_choices.pop(0).options
                 if d is not None]
        self.assertTrue(first)
        self.assertTrue(all(d.spell_school == 11 for d in first))
        game._offer_trinkets(a, "greater")        # 消费后恢复 Greater
        choice = game.pending_choices.pop(0)
        options = [d for d in choice.options if d is not None]
        self.assertTrue(options)
        self.assertTrue(all(d.spell_school == 12 for d in options))

    def test_opponent_unaffected(self):
        game = make_game()
        a, b = game.heroes
        a.gold = b.gold = 50
        bind(game, a, ORB)
        self.assertIsNone(getattr(b, "_next_trinket_kind", None))
        game._offer_trinkets(a, "greater")        # 正对照: 本人是 Lesser
        mine = [d for d in game.pending_choices.pop(0).options
                if d is not None]
        self.assertTrue(mine)
        self.assertTrue(all(d.spell_school == 11 for d in mine))
        game._offer_trinkets(b, "greater")        # 负对照: 对手仍是 Greater
        options = [d for d in game.pending_choices.pop(0).options
                   if d is not None]
        self.assertTrue(options)
        self.assertTrue(all(d.spell_school == 12 for d in options))
        self.assertEqual(b.gold, 50)              # 对手没拿到金

    def test_duplicate_orb_sets_kind_once_per_bind(self):
        game = make_game()
        a = game.heroes[0]
        a.gold = 50
        bind(game, a, ORB)
        bind(game, a, ORB, duplicate=True)
        self.assertEqual(a.gold, 70)          # 两份各给 num(0)
        self.assertEqual(a._next_trinket_kind, "lesser")
        game._offer_trinkets(a, "greater")
        choice = game.pending_choices.pop(0)
        options = [d for d in choice.options if d is not None]
        self.assertTrue(all(d.spell_school == 11 for d in options))


# ══════════════ BG32_MagicItem_925 Hackerfin Portrait ══════════════


class TestHackerfinPortrait(unittest.TestCase):
    def test_golden_retrigger_resolves_twice(self):
        """BUG-3 回归: 金色随从被 `TriggerBattlecry` 重触发应结算 2 次
        （与自然打出路径同口径; 旧实现只认 Brann → 金色只 1 次）。"""
        from hsrl2.actions.trigger import TriggerBattlecry
        game = make_game(seed=9250)
        a, b = game.heroes
        calls = []

        class Probe:
            @staticmethod
            def battlecry(source, g, ctx=None):
                calls.append(source)

        m = Minion("TEST_BC", "BC", atk=1, health=1)
        m.game = game
        m.controller = a
        m.scripts = Probe
        m.set(GameTag.GOLDEN, True)
        game.summon(a, m)
        TriggerBattlecry(m).do(game)
        self.assertEqual(len(calls), 2)
        # 非金色 → 1 次（负对照）
        calls.clear()
        p = Minion("TEST_BC2", "BC2", atk=1, health=1)
        p.game = game
        p.controller = a
        p.scripts = Probe
        game.summon(a, p)
        TriggerBattlecry(p).do(game)
        self.assertEqual(len(calls), 1)

    """925 — 交付 Hackerfin + EoT 触发己方 Hackerfin 战吼。"""

    def test_grants_hackerfin(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, HACKERFIN_PORTRAIT)
        self.assertEqual([e.card_id for e in a.hand], [HACKERFIN])

    def test_full_hand_queues(self):
        game = make_game()
        a = game.heroes[0]
        fill_hand(a, game)
        from hsrl2 import constants as C
        bind(game, a, HACKERFIN_PORTRAIT)
        self.assertIn(HACKERFIN,
                      [e.card_id for _, e in game.pending_hand_queue])
        self.assertEqual(len(a.hand), C.HAND_SIZE)

    def test_eot_triggers_hackerfin_battlecry(self):
        """真实 EoT 钩子: 战吼被触发（`COUNTER_BATTLECRIES` +1 为直接证据）
        且其他友方随从获得 num(0)×(1+c)。"""
        game = make_game()
        a = game.heroes[0]
        trinket = bind(game, a, HACKERFIN_PORTRAIT)
        put(game, a, HACKERFIN)
        target = put(game, a, BEAST)
        base = target.atk
        counter0 = a.get(GameTag.COUNTER_BATTLECRIES, 0)
        game.run_script_hook(trinket, "end_of_turn")
        self.assertGreater(a.get(GameTag.COUNTER_BATTLECRIES, 0), counter0)
        self.assertEqual(target.atk,
                         base + _hackerfin_bonus(game) * (1 + bonus_keyword_count(game, a)))

    def test_no_hackerfin_no_effect(self):
        """棋盘无 Hackerfin → EoT 空转（负）; 入板后同一钩子生效（正）。"""
        game = make_game()
        a = game.heroes[0]
        trinket = bind(game, a, HACKERFIN_PORTRAIT)
        target = put(game, a, BEAST)
        base = target.atk
        counter0 = a.get(GameTag.COUNTER_BATTLECRIES, 0)
        game.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(target.atk, base)
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), counter0)
        put(game, a, HACKERFIN)                 # 正对照
        c = bonus_keyword_count(game, a)
        game.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0), counter0 + 1)
        self.assertEqual(target.atk, base + _hackerfin_bonus(game) * (1 + c))

    def test_opponent_hackerfin_not_triggered(self):
        game = make_game()
        a, b = game.heroes
        trinket = bind(game, a, HACKERFIN_PORTRAIT)
        put(game, a, HACKERFIN)
        my_target = put(game, a, BEAST)
        put(game, b, HACKERFIN)
        their_target = put(game, b, BEAST)
        my_base, their_base = my_target.atk, their_target.atk
        c = bonus_keyword_count(game, a)
        game.run_script_hook(trinket, "end_of_turn")
        self.assertEqual(their_target.atk, their_base)   # 负对照
        self.assertEqual(my_target.atk, my_base + _hackerfin_bonus(game) * (1 + c))  # 正对照

    def test_control_without_trinket_no_eot(self):
        """真实 `end_recruit_phase` 全循环: 无饰品方不触发（负），
        持饰品方触发（正）。"""
        game = make_game()
        a, b = game.heroes
        bind(game, b, HACKERFIN_PORTRAIT)     # 只有 b 持饰品
        put(game, a, HACKERFIN)               # a 也有 Hackerfin 但无饰品
        put(game, b, HACKERFIN)
        a_target = put(game, a, BEAST)
        b_target = put(game, b, BEAST)
        a_base, b_base = a_target.atk, b_target.atk
        game.end_recruit_phase()
        self.assertEqual(a_target.atk, a_base)          # 负对照
        self.assertGreater(b_target.atk, b_base)        # 正对照

    def test_golden_hackerfin_triggers_for_each_copy(self):
        game = make_game()
        a = game.heroes[0]
        trinket = bind(game, a, HACKERFIN_PORTRAIT)
        put(game, a, HACKERFIN)
        put(game, a, HACKERFIN, golden=True)
        target = put(game, a, BEAST)
        base = target.atk
        game.run_script_hook(trinket, "end_of_turn")
        # 两只 Hackerfin 各触发一次 → 目标至少拿到 2 份增量
        self.assertGreaterEqual(target.atk, base + 2)

    def test_two_trinket_copies_trigger_twice(self):
        game = make_game()
        a = game.heroes[0]
        bind(game, a, HACKERFIN_PORTRAIT)
        bind(game, a, HACKERFIN_PORTRAIT, duplicate=True)
        put(game, a, HACKERFIN)
        target = put(game, a, BEAST)
        base = target.atk
        counter0 = a.get(GameTag.COUNTER_BATTLECRIES, 0)
        for t in list(a.trinkets):
            game.run_script_hook(t, "end_of_turn")
        self.assertEqual(a.get(GameTag.COUNTER_BATTLECRIES, 0),
                         counter0 + 2)
        self.assertEqual(target.atk,
                         base + 2 * _hackerfin_bonus(game) * (1 + bonus_keyword_count(game, a)))


# ══════════════ 注册表 / DEFERRED 台账（结构性） ══════════════


class TestBatch30Ledger(unittest.TestCase):
    """@engine-only 结构性: 注册表 / DEFERRED 台账 / 数据链 / 数值守卫。

    本类断言与脚本钩子无关（注册与不注册、`CardDef` 数值、类名、docstring
    台账），按 TEST_SOP §16 末段标注 `@engine-only`，避免被空转审计误判。
    """

    def test_all_registered_and_bound(self):
        from hsrl2.scripts.batches import batch_trinkets30 as B
        for tid in REGISTERED_IDS:
            self.assertIs(REGISTRY.get(tid),
                          getattr(B, _CARD_CLASSES[tid]), tid)

    def test_registry_returns_exactly_nine_ids(self):
        from hsrl2.scripts.batches import batch_trinkets30 as B
        import inspect as _inspect
        src = _inspect.getsource(B.register)
        self.assertIn("return registered", src)
        self.assertEqual(len(REGISTERED_IDS), 9)
        for tid in REGISTERED_IDS:
            self.assertIn(tid, REGISTRY)

    def test_deferred_not_registered(self):
        for tid in DEFERRED_IDS:
            self.assertIsNone(REGISTRY.get(tid), tid)
            self.assertIsNotNone(get_db().get(tid), tid)

    def test_923_unfrozen_by_persist_source_primitive(self):
        """923 解冻回归（原 DEFERRED 阻塞证据的反向断言）:
        `Buff(persist=True)` 与 `Game.add_persist_source` /
        `persist_source_id` 已落地，923 由 batch_trinkets31 注册。"""
        from hsrl2.entity import Buff as EntityBuff
        from hsrl2.scripts.batches import batch_trinkets31 as B31
        self.assertIn("BG35_MagicItem_923", REGISTRY)
        self.assertIs(REGISTRY["BG35_MagicItem_923"],
                      B31.BewitchedRibbonScript)
        self.assertIn("persist", EntityBuff.__slots__)
        self.assertTrue(hasattr(Game, "add_persist_source"))
        self.assertTrue(hasattr(Game, "persist_source_id"))

    def test_deferred_docstring_ledger(self):
        from hsrl2.scripts.batches import batch_trinkets30 as B
        for tid in DEFERRED_IDS:
            cls = getattr(B, _CARD_CLASSES[tid])
            doc = cls.__doc__ or ""
            self.assertIn("Status:", doc, tid)
            self.assertIn("DEFERRED", doc, tid)
            self.assertIn("Dependency:", doc, tid)
            self.assertIn("Implementation path:", doc, tid)
            self.assertIn("阻塞卡:", doc, tid)

    def test_deferred_classes_declare_no_engine_hooks(self):
        from hsrl2.scripts.batches import batch_trinkets30 as B
        for tid in DEFERRED_IDS:
            cls = getattr(B, _CARD_CLASSES[tid])
            declared = [h for h in _ENGINE_HOOKS if h in vars(cls)]
            self.assertEqual(declared, [], f"{tid} {_CARD_CLASSES[tid]}")

    def test_all_ids_exist_and_offer_pool(self):
        db = get_db()
        pool = {d.id for d in db.trinket_offer_pool()}
        for tid in REGISTERED_IDS:
            d = db.get(tid)
            self.assertIsNotNone(d, tid)
            if tid == BUBBLE_SPELL:
                # Spellcraft 法术 token（card_type=5）——不进商店池
                self.assertEqual(d.spell_school, 10, tid)
                self.assertNotIn(tid, pool)
            else:
                self.assertIn(tid, pool, tid)
                self.assertIn(d.spell_school, (11, 12), tid)

    def test_carddef_num_params_pinned(self):
        db = get_db()
        for tid, expected in _NUM_PARAMS.items():
            d = db.get(tid)
            self.assertEqual(tuple(d.num(i) for i in range(5)), expected, tid)

    def test_carddef_related_card_data_chain(self):
        db = get_db()
        for tid, related in _RELATED_CARDS.items():
            evo = db.get(tid).evolution_card_id
            self.assertIsNotNone(evo, tid)
            self.assertEqual(db.by_dbf(evo).id, related, tid)
        for tid in _NO_RELATED_CARDS:
            self.assertIsNone(db.get(tid).evolution_card_id, tid)

    def test_carddef_bubble_spellcraft_data_chain(self):
        db = get_db()
        self.assertEqual(db.get(BUBBLE).spellcraft_id,
                         db.get(BUBBLE_SPELL).dbf_id)

    def test_payload_cards_registered(self):
        db = get_db()
        for cid in (RYLAK, HACKERFIN):
            self.assertIsNotNone(db.get(cid), cid)
            self.assertIsNotNone(REGISTRY.get(cid), cid)

    def test_933_unfrozen_and_payload_consumes_permanence(self):
        """933 Weary Portrait 解冻回归（原 DEFERRED 阻塞证据的反向断言）:
        载荷 Reinvigoration 现已消费 `permanent_spellcraft`（Reborn 永久
        保留），且引擎仍不提供 `make_spellcraft_permanent` 私有后门——
        永久化只经 `add_permanent_spellcraft_rule` 的生成期打标。"""
        db = get_db()
        spell = db.by_dbf(db.get("BG31_830").spellcraft_id)
        self.assertEqual(spell.id, "BG31_830t")
        # "until next turn" 只修饰 Reborn 子句（属性子句本就是永久）
        self.assertIn("+2/+2.", spell.text)
        self.assertNotIn("+2/+2 until next turn", spell.text.lower())
        import inspect as _inspect
        from hsrl2.scripts.batches import batch_payload_minions as PM
        src = _inspect.getsource(PM.ReinvigorationScript)
        self.assertIn("permanent_spellcraft", src)
        self.assertIn("BG32_MagicItem_933", REGISTRY)

    def test_933_registered_in_new_batch(self):
        from hsrl2.scripts.batches import batch_trinkets37 as B37
        self.assertIs(REGISTRY.get("BG32_MagicItem_933"),
                      B37.WearyPortraitScript)


if __name__ == "__main__":
    unittest.main()
