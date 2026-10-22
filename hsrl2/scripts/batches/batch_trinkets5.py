"""批次 trinkets5 — 饰品第五批（作业单 2026-09-02）。

与 batch_trinkets1..4 的 id 集合互不相交。数值一律取自
`data/bg_trinkets.json` 的 `CardDef.num(0/1/2)`；文本无占位符的卡按
SOP §3 以文本字面量实现并在各类 `Params:` 行声明。

实现（20 个 id / 20 张饰品）:
  BG30_MagicItem_931  Lucky Tabby          — num(1) 次友方死亡: 随机野兽
  BG30_MagicItem_713  Bleeding Heart       — num(1) 次友方死亡: 随机亡灵
  BG35_MagicItem_302  Stormcoil Sticker    — num(1) 次友方死亡: 随机机械
  BG32_MagicItem_858  Explorer's Binoculars — 3 只随机 Tier 4 随从
  BG35_MagicItem_815  Magician's Top Hat   — T1/T2/T3 各 2 只随机随从
  BG32_MagicItem_304  Horn of Summoning    — 6 只**不同** Tier 1 随从
  BG36_MagicItem_220  Glowing Crystal      — SoT: 每个受控类型 +1 金
  BG32_MagicItem_864  Bird Feeder          — Avenge(2): 全体 +1/+1
  BG32_MagicItem_860  Beetle Band          — Avenge(5): 召唤 {0}/{1} 甲虫+嘲讽
  BG35_MagicItem_711  Protective Ring      — SoC: num(0) 个随机友方海盗圣盾
  BG36_MagicItem_203  Dragon Skull         — 战吼触发: 左右端随从 +num/+num
  BG32_MagicItem_862  Unholy Sanctum       — 亡语触发: 最右随从 +2/+2
  BG36_MagicItem_811  Defensive Shell      — 每回合第一个打出的随从获圣盾
  BG35_MagicItem_871  Mama Bear Sticker    — 召唤野兽: 该野兽 +num/+num
  BG32_MagicItem_893  Bluegill Flippers    — 施放酒馆法术: 手牌/战团最左 +num
  BG30_MagicItem_422  Lorewalker Scroll    — 对随从施法: 该随从 +num/+num
  BG30_MagicItem_426  Colorful Compass     — 随机 Race(num(0)) 随从; 每回合再来
  BG30_MagicItem_425  Azeroth Model Globe  — 每 num(0) 回合: +num(1) 金 + 发现 T6
  BG30_MagicItem_435  Goldenizer Supply    — 每 num(1) 回合 EoT: 得 Goldenizer
  BG35_MagicItem_814  Stuffed Coin Purse   — 升到 Tier num(0) 时 +num(1) 金

DEFERRED（本批评估后放弃；每张附具体引擎依赖）:
  - BG35_MagicItem_818 Mysterious Orb — "Your next Trinket is a Lesser
    Trinket"。依赖: `_offer_trinkets` 需要一个"下一饰品档位覆写"标记
    （`hero._trinket_early` 只提前 offer 回合，不改变档位）。
  - BG30_MagicItem_703 Mystery Cube — "Choose from 2 new Lesser Trinkets
    to replace this for free. At the start of each turn, repeat this."
    依赖: 饰品**替换**协议（移除本体 + 重新 offer + 免单）不存在。
  - BG30_MagicItem_888 Souvenir Stand — "When you buy a Greater Trinket,
    this transforms into a copy of it"。依赖: 饰品购买后置钩子（无
    trinket_bought 事件）。
  - BG36_MagicItem_215 Dragon's Eye — "Your Dragons' Battlecries trigger
    an extra time"。依赖: 种族限定战吼 doubler；引擎只有全局
    `_extra_bc_dr` 与棋盘 `BATTLECRY_DOUBLER` 光环（无种族过滤）。
  - BG30_MagicItem_439 Designer Eyepatch — "You only need 2 copies of a
    Pirate to make it Golden"。依赖: 种族限定的三连阈值；引擎
    `TRIPLE_THRESHOLD` 是 hero 级全域，无 per-race 口径。
  - BG36_MagicItem_300 Frigid Blossom / BG32_MagicItem_891 Finley's
    Helmet 等 "Bonus Keyword" 类 — 依赖: 随机 Bonus Keyword 授予子系统
    （`TAVERN_REFRESH` + 随机关键词池）未实现。
  - BG32_MagicItem_416 War Drum / BG36_MagicItem_214 等 "Battlecry/Rally
    额外触发次数" 类 — 依赖: 每回合一次的额外触发配额协议。
  - BG30_MagicItem_425/435 同族的 t/t2 升级变体由
    `CardDB.trinket_offer_pool()` 排除（id 尾 t/t2 且有同名本体），
    永不进入商店池，故不需要各自脚本。

协议: 饰品实体经 `_offer_trinkets` 购买 → `hero.trinkets`；脚本挂
`on_bind(source, game, ctx={"hero": hero})` + 事件监听；Avenge 走引擎
`avenge_threshold` 类属性（仅战斗内计数，每场重置，RULES §6.11）。
全部状态写在**闭包**或 `hero` 作用域（SOP §12 item 9——禁止 game 级）。
"""

from __future__ import annotations

from hsrl2.actions import (
    Buff,
    Discover,
    GainGold,
    GainKeyword,
    GetRandomMinion,
)
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    BATTLECRY_TRIGGER,
    CARD_PLAYED,
    DEATH,
    DEATHRATTLE_TRIGGER,
    SUMMON,
    TAVERN_SPELL_CAST,
    TURN_END,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race, Zone

# 全部标准种族（All 型随从即每个类型——batch_trinkets3._ALL_MINION_RACES
# / batch_spells3 Misplaced Tea Set 同源）
_ALL_MINION_RACES = tuple(
    r for r in Race if r not in (Race.INVALID, Race.NONE, Race.ALL)
)

_BEAST_RACES = (Race.BEAST, Race.ALL)
_PIRATE_RACES = (Race.PIRATE, Race.ALL)

# Beetle Band 的召唤物: CardDB 按名 "Beetle" 核实，唯一 Beetle token
# （BG28_603t 2/2 Beast，card_type 4; 与 trinket num(0/1)=2/2 一致，
# 一致性由测试守护）
BEETLE_TOKEN = "BG28_603t"


def _hero(ctx):
    return ctx.get("hero") if ctx else None


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _controlled_races(hero) -> tuple:
    """本人棋盘"控制的不同类型"（标准种族顺序，去重）。

    race == ALL 的随从按官方 All 型规则视为**每个**标准种族
    （batch_trinkets3._controlled_types 同款裁定）；race == NONE 不计。
    """
    present = set()
    for m in hero.board:
        if m.dead:
            continue
        # 类型身份集合（AC-3）: ALL → 全 10 族; NONE → 空集;
        # 双类型贡献两个类型; 家族类型改写（Portrait）同样计入。
        present.update(m.races)
    return tuple(r for r in _ALL_MINION_RACES if r in present)


def _living(hero):
    return [m for m in hero.board if not m.dead]


def _acquire_to_hand(game, hero, card_id: str) -> bool:
    """指定随从占池入手（池空返 False——效果落空）。"""
    if not game.minion_pool.acquire(card_id):
        return False
    m = game.create_minion(card_id, controller=hero)
    if m is None:
        return False
    game.pending_hand_add(hero, m)
    return True


def _death_counter(source, game, hero, threshold: int, race):
    """注册"每 num(1) 次友方死亡 → GetRandomMinion(race)"监听器。

    计数跨回合累积（文本无 "this turn"）；状态存于脚本闭包（随饰品实体
    存活）。招募期与战斗内死亡都计入（文本无阶段限定）。
    """
    progress = [0]

    def on_death(g, minion=None, **kw):
        if minion is None or minion.controller is not hero:
            return
        progress[0] += 1
        if progress[0] < threshold:
            return
        progress[0] = 0
        g.run_actions(GetRandomMinion(hero, race=race))

    game.events.register(Listener(event=DEATH, owner=source,
                                  callback=on_death))
    return None


# ══════════════════ BG30_MagicItem_931 Lucky Tabby ══════════════════

class LuckyTabbyScript:
    """
    Natural language: After {1} friendly minions die, get a random Beast.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: DEATH（minion=）——
         `minion.controller is 本人`; 计数 += 1
      2. 计数达阈值 num(1)=7 时清零并 GetRandomMinion(hero, race=BEAST)
         ——池感知（占池 RULES §2.3 + 满手排队 RULES §3.3）;
         文本 {1} 是阈值、{0} 是剩余显示值（同源 7）
      3. 计数跨回合累积（文本无 "this turn"）; 状态存于脚本闭包
      4. 只进本人手牌（对手死亡不计数）

    Test: test_batch_trinkets5.py — 第 threshold-1 次死亡不发放 / 第
      threshold 次恰好 1 只随机野兽入手且池 -1 / 对手死亡不计数 /
      阈值 == CardDef.num(1)

    Params: {0}=7 {1}=7（BG30_MagicItem_931 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return _death_counter(source, game, h,
                              _num(game, source.card_id, 1), Race.BEAST)


# ══════════════════ BG30_MagicItem_713 Bleeding Heart ══════════════════

class BleedingHeartScript:
    """
    Natural language: After {1} friendly minions die, get a random Undead.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册 DEATH 监听（owner=饰品）; `minion.controller is
         本人` 才计数
      2. 达阈值 num(1)=8 → 清零 + GetRandomMinion(hero, race=UNDEAD)
         （占池 + 满手排队）
      3. 跨回合累积; 只进本人手牌

    Test: test_batch_trinkets5.py — 阈值取自 num(1) / 达标入手 1 只亡灵
      且池 -1 / 对手死亡不计 / 计数清零后再满一轮再发

    Params: {0}=8 {1}=8（BG30_MagicItem_713 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return _death_counter(source, game, h,
                              _num(game, source.card_id, 1), Race.UNDEAD)


# ══════════════════ BG35_MagicItem_302 Stormcoil Sticker ══════════════════

class StormcoilStickerScript:
    """
    Natural language: After {1} friendly minions die, get a random Mech.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册 DEATH 监听（owner=饰品）; `minion.controller is
         本人` 才计数
      2. 达阈值 num(1)=8 → 清零 + GetRandomMinion(hero, race=MECH)
         （占池 + 满手排队）
      3. 跨回合累积; 只进本人手牌

    Test: test_batch_trinkets5.py — 阈值取自 num(1) / 达标入手 1 只机械
      且池 -1 / 对手死亡不计

    Params: {0}=8 {1}=8（BG35_MagicItem_302 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return _death_counter(source, game, h,
                              _num(game, source.card_id, 1), Race.MECH)


# ═══════════════ BG32_MagicItem_858 Explorer's Binoculars ═══════════════

class ExplorersBinocularsScript:
    """
    Natural language: Get three random Tier 4 minions.

    Formal spec:
      1. on_bind: 3 次 GetRandomMinion(hero, min_tier=4, max_tier=4)——
         每次独立从池中仍有副本的 Tier 4 随从随机取一只（RULES §2.4）;
         "three random" 无 "different" 措辞 → 允许重复（池有余量时）
      2. 占池（RULES §2.3）+ 满手排队（RULES §3.3）; 池耗尽 → 该次落空
      3. 只进本人手牌

    Test: test_batch_trinkets5.py — 恰好 3 只入手且每只 tech_level==4 /
      Tier 4 池总量 -3 / 对手手牌为空

    Params: count=3 tier=4（文本字面量 "three random Tier 4"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return [GetRandomMinion(h, min_tier=4, max_tier=4)
                for _ in range(3)]


# ══════════════════ BG35_MagicItem_815 Magician's Top Hat ══════════════

class MagiciansTopHatScript:
    """
    Natural language: Get two minions each from Tiers 1, 2, and 3.

    Formal spec:
      1. on_bind: 对 tier ∈ (1, 2, 3) 各 2 次
         GetRandomMinion(hero, min_tier=tier, max_tier=tier)——
         6 次独立池抽取（"two minions each" 无 "different" 措辞）
      2. 占池 + 满手排队; 某 tier 池耗尽则该次落空（不跨 tier 补偿）
      3. 只进本人手牌

    Test: test_batch_trinkets5.py — 恰好 6 只入手且 T1/T2/T3 各 2 只
      （按 tech_level 分组）/ 三个 tier 池各 -2 / 对手手牌为空

    Params: count=2（文本字面量 "two minions each"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return [GetRandomMinion(h, min_tier=t, max_tier=t)
                for t in (1, 2, 3) for _ in range(2)]


# ══════════════════ BG32_MagicItem_304 Horn of Summoning ══════════════════

class HornOfSummoningScript:
    """
    Natural language: [x]Get six different Tier 1 minions.

    Formal spec:
      1. on_bind: 候选 = 池中仍有副本（RULES §2.4）的 Tier 1 随从
         card_id 去重集合; 取 min(6, |候选|) 个**互不相同**的 id
         （game.rng.sample——"different" 措辞要求不同随从）
      2. 每个 id `minion_pool.acquire` 占池（RULES §2.3）→
         create_minion → pending_hand_add（满手排队 RULES §3.3）
      3. 候选不足 6 个时只给实际数量; 只进本人手牌

    Test: test_batch_trinkets5.py — 恰好 6 只入手、6 个 card_id 互不相同
      且均为 Tier 1 / 每个 id 池 -1 / 对手手牌为空

    Params: count=6 tier=1（文本字面量 "six different Tier 1"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        cands = _pool_candidates(game, None, 1, 1)
        if not cands:
            return None
        k = min(6, len(cands))
        picks = game.rng.sample(cands, k, label="horn_of_summoning")
        for cid in picks:
            _acquire_to_hand(game, h, cid)
        return None


# ══════════════════ BG36_MagicItem_220 Glowing Crystal ══════════════════

class GlowingCrystalScript:
    """
    Natural language: At the start of your turn, gain 1 Gold for each
    different friendly minion type.

    Formal spec:
      1. start_of_turn（饰品 SoT 钩子）: types = 本人棋盘存活随从的不同
         类型数（`_controlled_races`——All 型贡献全部标准种族，
         无类型不计）
      2. GainGold(hero, len(types))——"1 Gold for each"（文本字面量 1）;
         空棋盘/全无类型 → 0 金，落空
      3. 只作用于本人（hero 作用域），对手金币不变

    Test: test_batch_trinkets5.py — 鱼人+亡灵棋盘 → +2 金 / 无类型棋盘
      → 0 金 / All 型随从 → +10 金 / 对手金币不变

    Params: gold_per_type=1（文本字面量 "1 Gold for each"）
    """

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        n = len(_controlled_races(h))
        if n <= 0:
            return None
        return GainGold(h, n)


# ══════════════════ BG32_MagicItem_864 Bird Feeder ══════════════════

class BirdFeederScript:
    """
    Natural language: <b>Avenge (2):</b> Give your minions +1/+1.

    Formal spec:
      1. avenge_threshold = 2（文本 "Avenge (2)" 字面量——CardDef 无
         num 参数; 与数据一致性由测试守护）
      2. avenge: 本人棋盘每个存活随从获得 Buff(atk=1, health=1)
         永久增益（战斗期增益战后由 run_combat 快照回滚）
      3. 仅战斗内计数（引擎 Avenge 阶段守卫，RULES §6.11）; 每场清零

    Test: test_batch_trinkets5.py — 战斗内 2 次友方死亡后全体 +1/+1 /
      1 次死亡不触发 / 招募期死亡不触发 / 对手随从不变

    Params: atk=1 health=1（文本字面量 "+1/+1"）
    """

    avenge_threshold = 2

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        out = [Buff(m, atk=1, health=1) for m in _living(h)]
        return out or None


# ══════════════════ BG32_MagicItem_860 Beetle Band ══════════════════

class BeetleBandScript:
    """
    Natural language: [x]<b>Avenge (5):</b> Summon a {0}/{1} Beetle.
    Give it <b>Taunt</b>.

    Formal spec:
      1. avenge_threshold = 5（文本 "Avenge (5)" 字面量）
      2. avenge: 召唤 Beetle token（`BG28_603t`——CardDB 按名核实唯一
         Beetle; 2/2 Beast，与 num(0)=2/num(1)=2 一致，测试守护），
         并在入场前打 TAUNT（"Give it Taunt"）; 满场由 game.summon
         走 MINION_OVERFLOW 丢弃（引擎统一语义）
      3. 仅战斗内计数，每场清零（RULES §6.11）

    Test: test_batch_trinkets5.py — 战斗内 5 次友方死亡后棋盘出现 1 只
      Beetle 且带 TAUNT / 4 次不触发 / token 基础属性 == num(0)/num(1)

    Params: {0}=2 {1}=2（BG32_MagicItem_860 num(0/1)，与 Beetle token
              CardDef 属性一致）
    """

    avenge_threshold = 5

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        m = game.create_minion(BEETLE_TOKEN, controller=h)
        if m is None:
            return None
        m.set(GameTag.TAUNT, True)
        game.summon(h, m, None)
        return None


# ══════════════════ BG35_MagicItem_711 Protective Ring ══════════════════

class ProtectiveRingScript:
    """
    Natural language: <b>Start of Combat:</b> Give {0} random friendly
    Pirates <b>Divine Shield</b>.

    Formal spec:
      1. start_of_combat: 候选 = 本人棋盘存活、race ∈ (PIRATE, ALL) 的
         随从（Amalgam 规则）; 随机抽 min(num(0), n) 个**不重复**
         （game.rng.sample——"N random friendly Pirates" 为 N 个不同
         随从）; 不足则给全部
      2. 每个目标 GainKeyword(DIVINE_SHIELD)（战斗期授予，战后快照回滚
         RULES §3.5）; 无海盗 → 落空
      3. 只作用于本人棋盘（对手不变）

    Test: test_batch_trinkets5.py — 恰好 num(0) 个海盗获圣盾、非海盗与
      第 num(0)+1 个海盗不获 / 海盗不足时全部获 / 对手不变

    Params: {0}=4（BG35_MagicItem_711 num(0)）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        cands = [m for m in _living(h) if m.race in _PIRATE_RACES]
        if not cands:
            return None
        k = min(_num(game, source.card_id, 0), len(cands))
        picks = (list(cands) if k == len(cands)
                 else game.rng.sample(cands, k, label="protective_ring"))
        return [GainKeyword(m, GameTag.DIVINE_SHIELD) for m in picks]


# ══════════════════ BG36_MagicItem_203 Dragon Skull ══════════════════

class DragonSkullScript:
    """
    Natural language: [x]Whenever you trigger a <b>Battlecry</b>, give
    your left- and right-most minions +{0}/+{1}.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: BATTLECRY_TRIGGER
         （minion=）——引擎对自然打出与重触发都广播; 过滤
         `minion.controller is 本人`（对手战吼不触发）
      2. 每次触发: 本人棋盘存活随从的最左（索引 0）与最右（-1）各获
         Buff(atk=num(0), health=num(1)) 永久增益; 仅 1 个随从时只给
         一次（去重）; 空棋盘 → 落空
      3. 战斗内战吼的增益由战后快照回滚（RULES §3.5）

    Test: test_batch_trinkets5.py — 真实打出一个战吼随从 → 左右端
      +num/+num、中间不变 / 对手战吼不触发 / 空棋盘落空 / 单随从恰好
      一次

    Params: {0}=5 {1}=5（BG36_MagicItem_203 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_bc(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            living = _living(h)
            if not living:
                return
            targets = [living[0]]
            if living[-1] is not living[0]:
                targets.append(living[-1])
            atk = _num(g, source.card_id, 0)
            health = _num(g, source.card_id, 1)
            g.run_actions([Buff(m, atk=atk, health=health)
                           for m in targets])

        game.events.register(Listener(event=BATTLECRY_TRIGGER,
                                      owner=source, callback=on_bc))
        return None


# ══════════════════ BG32_MagicItem_862 Unholy Sanctum ══════════════════

class UnholySanctumScript:
    """
    Natural language: [x]After you trigger a <b>Deathrattle</b>, give your
    right-most minion +2/+2 permanently.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: DEATHRATTLE_TRIGGER
         （minion=）——过滤 `minion.controller is 本人`（对手亡语不触发）
      2. 每次触发: 本人棋盘**最右**存活随从获得 Buff(atk=2, health=2)
         永久增益; 空棋盘 → 落空
      3. 亡语触发时死者已离场（SOP §9 官方死亡顺序），最右取处理后的
         棋盘

    Test: test_batch_trinkets5.py — 真实触发一次亡语 → 最右 +2/+2、
      其他不变 / 对手亡语不触发 / 空棋盘落空

    Params: atk=2 health=2（文本字面量 "+2/+2"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_dr(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            living = _living(h)
            if not living:
                return
            g.run_actions(Buff(living[-1], atk=2, health=2))

        game.events.register(Listener(event=DEATHRATTLE_TRIGGER,
                                      owner=source, callback=on_dr))
        return None


# ══════════════════ BG36_MagicItem_811 Defensive Shell ══════════════════

class DefensiveShellScript:
    """
    Natural language: [x]The first minion you play each turn gains
    <b>Divine Shield</b>.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: CARD_PLAYED（card=）——
         仅 `isinstance(card, Minion)` 且 `card.controller is 本人`
      2. 每招募回合（`game.turn` 变化）**第一次**打出随从时授予
         GainKeyword(DIVINE_SHIELD)，本回合后续打出的随从不授予;
         状态存于脚本闭包（含回合号）
      3. 招募期外（战斗内召唤）不触发——战斗召唤不是 "play"（引擎
         card_played 只由 play_minion/play_spell 广播）

    Test: test_batch_trinkets5.py — 同回合打出两只: 仅第一只获圣盾 /
      真实 end_recruit_phase 推进回合后，下一只重新获圣盾 /
      对手打出不触发

    Params: 无模板参数（"the first minion" 为运行时回合状态）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        state = {"turn": None}   # 已授予圣盾的回合号（None = 尚无）

        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not h:
                return
            if state["turn"] == g.turn:
                return
            state["turn"] = g.turn
            g.run_actions(GainKeyword(card, GameTag.DIVINE_SHIELD))

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG35_MagicItem_871 Mama Bear Sticker ══════════════════

class MamaBearStickerScript:
    """
    Natural language: Whenever you summon a Beast, give it +{0}/+{1}.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: SUMMON（minion=）——过滤
         `minion.controller is 本人` 且 race ∈ (BEAST, ALL)（Amalgam
         规则）
      2. 每次召唤: 该野兽获得 Buff(atk=num(0), health=num(1))——
         招募期召唤为永久增益，战斗期召唤由战后快照回滚（RULES §3.5）
      3. 非野兽/对手召唤不触发

    Test: test_batch_trinkets5.py — 召唤野兽 → +num/+num / 召唤鱼人不变 /
      对手召唤野兽不变

    Params: {0}=6 {1}=6（BG35_MagicItem_871 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_summon(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if minion.race not in _BEAST_RACES:
                return
            g.run_actions(Buff(minion, atk=_num(g, source.card_id, 0),
                               health=_num(g, source.card_id, 1)))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summon))
        return None


# ══════════════════ BG32_MagicItem_893 Bluegill Flippers ══════════════════

class BluegillFlippersScript:
    """
    Natural language: [x]Whenever you cast a Tavern spell, give the
    left-most minion in your hand and warband +{0}/+{1}.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: TAVERN_SPELL_CAST
         （spell=）——引擎只对 `is_pool_spell` 法术广播（game.py），
         正是 "Tavern spell" 语义; `spell.controller is 本人` owner 隔离
      2. 每次触发: 两个目标各自获 Buff(atk=num(0), health=num(1)) 永久
         增益:
         a) 手牌中**最左的随从**（跳过法术/非随从手牌）
         b) 棋盘上**最左的存活随从**
         任一侧无候选 → 该侧落空（不补偿）
      3. 法术双施（Balinda）按施放次数各广播一次 → 每次各 +num/+num

    Test: test_batch_trinkets5.py — 真实打出酒馆法术 → 手牌最左随从与
      棋盘最左随从各 +num/+num、手牌中更右随从与棋盘更右随从不变 /
      对手施放不触发 / 空手牌时只加棋盘侧

    Params: {0}=3 {1}=3（BG32_MagicItem_893 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            atk = _num(g, source.card_id, 0)
            health = _num(g, source.card_id, 1)
            out = []
            hand_minions = [e for e in h.hand if isinstance(e, Minion)]
            if hand_minions:
                out.append(Buff(hand_minions[0], atk=atk, health=health))
            living = _living(h)
            if living:
                out.append(Buff(living[0], atk=atk, health=health))
            if out:
                g.run_actions(out)

        game.events.register(Listener(event=TAVERN_SPELL_CAST,
                                      owner=source, callback=on_cast))
        return None


# ══════════════════ BG30_MagicItem_422 Lorewalker Scroll ══════════════════

class LorewalkerScrollScript:
    """
    Natural language: [x]Whenever you cast a spell on a minion, give it
    +{0}/+{1}.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: CARD_PLAYED（card=,
         target=）——引擎在法术**结算后**广播且携带 target
         （game.py `card_played`）; 过滤 `isinstance(card, Spell)` 且
         `card.controller is 本人`（对手施法不触发）
      2. 目标须为 Minion 且未死亡、未离场（Transform 类法术会把旧实体
         zone=REMOVED——不得对已移除实体加 buff）→
         获 Buff(atk=num(0), health=num(1))
      3. 未定向法术（target=None）或非随从目标 → 落空

    Test: test_batch_trinkets5.py — 真实对随从施放定向池法术 → 目标
      +num/+num / 施放无目标法术不触发 / 对手施法不触发

    Params: {0}=4 {1}=4（BG30_MagicItem_422 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, target=None, **kw):
            if not isinstance(card, Spell) or card.controller is not h:
                return
            if not isinstance(target, Minion) or target.dead:
                return
            if getattr(target, "zone", None) == Zone.REMOVED:
                return
            g.run_actions(Buff(target, atk=_num(g, source.card_id, 0),
                               health=_num(g, source.card_id, 1)))

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG30_MagicItem_426 Colorful Compass ══════════════════

class ColorfulCompassScript:
    """
    Natural language: [x]Get a random {0}. At the start of each turn,
    get another.

    Formal spec:
      1. `{0}` 由 CardDef 参数给出种族枚举: num(0)=92 == Race.NAGA
         （数据核实: 文本 "Get a random Naga"）→ race = Race(num(0))，
         零硬编码
      2. on_bind: GetRandomMinion(hero, race) 一次
      3. start_of_turn（饰品 SoT 钩子）: 同款再获取一次——"At the start
         of each turn, get another" 逐回合
      4. 占池 + 满手排队; 池耗尽 → 落空; 只进本人手牌

    Test: test_batch_trinkets5.py — 绑定即入手 1 只纳迦且池 -1 / 真实
      SoT 再入手 1 只 / 对手手牌不变 / num(0) 解析为 Race.NAGA

    Params: {0}=92（BG30_MagicItem_426 num(0)，race 枚举值）
    """

    @staticmethod
    def _get(h, game, source):
        race = Race(_num(game, source.card_id, 0))
        return GetRandomMinion(h, race=race)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return ColorfulCompassScript._get(h, game, source)

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return ColorfulCompassScript._get(h, game, source)


# ══════════════════ BG30_MagicItem_425 Azeroth Model Globe ══════════════

class AzerothModelGlobeScript:
    """
    Natural language: [x]At the start of every two turns, gain {1} Gold
    and <b>Discover</b> a Tier 6 minion. <i>({0} |4(turn, turns) left!)</i>

    Formal spec:
      1. on_bind 初始化计数器 0（绑定发生在 offer 结算时——卡面显示
         "{0} turns left!" 即首次触发在第 num(0) 个后续回合开始）
      2. start_of_turn（饰品 SoT 钩子）: 计数 += 1; 未达 num(0)=2 → 无
         效果; 达阈值 → 清零, GainGold(hero, num(1)) +
         Discover(hero, min_tier=6, max_tier=6, kind="discover_minion")
         （预留语义 RULES §6.18——选项生成即占池，未选项回池）
      3. 只作用于本人（hero 作用域）

    Test: test_batch_trinkets5.py — 第 1 次 SoT 无效果 / 第 2 次 +num(1)
      金且产生 1 个 Tier 6 发现 / 发现选项池记账 / 对手金币不变

    Params: {0}=2 {1}=2（BG30_MagicItem_425 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        state = {"n": 0}
        every = _num(game, source.card_id, 0)
        gold = _num(game, source.card_id, 1)

        def on_sot(g, **kw):
            state["n"] += 1
            if state["n"] < every:
                return
            state["n"] = 0
            g.run_actions([GainGold(h, gold),
                           Discover(h, min_tier=6, max_tier=6,
                                    kind="discover_minion")])

        game.events.register(Listener(event=TURN_START, owner=source,
                                      callback=on_sot,
                                      condition=lambda hero=None, **kw:
                                      hero is h))
        return None


# ══════════════════ BG30_MagicItem_435 Goldenizer Supply ══════════════════

class GoldenizerSupplyScript:
    """
    Natural language: At the end of every {1} turns, get a Goldenizer.
    <i>({0} |4(turn, turns) left!)</i>

    Formal spec:
      1. on_bind 初始化计数器 0（首次触发在第 num(1)=3 个回合结束）
      2. end_of_turn（饰品 EoT 钩子）: 计数 += 1; 达 num(1) → 清零并
         入手一张关联卡（`evolution_card_id` 数据链 → CardDB.by_dbf →
         `BG26_813t` The Goldenizer, 零硬编码卡 id）:
         create_spell + pending_hand_add（满手排队 RULES §3.3）;
         该关联卡 `is_pool_spell=False`（数据核实）→ 不占法术池
      3. 只进本人手牌（对手不受影响）

    Test: test_batch_trinkets5.py — 第 1/2 次 EoT 无卡 / 第 3 次 EoT
      入手 1 张 The Goldenizer 且非池法术 / 再满 3 回合再发 /
      对手手牌不变

    Params: {0}=3 {1}=3（BG30_MagicItem_435 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        every = _num(game, source.card_id, 1)
        state = {"n": 0}

        def on_eot(g, **kw):
            state["n"] += 1
            if state["n"] < every:
                return
            state["n"] = 0
            d = g.db.get(source.card_id)
            if d is None or d.evolution_card_id is None:
                raise GameStateError(
                    f"{source.card_id}: evolution_card_id broken data chain")
            token = g.db.by_dbf(d.evolution_card_id)
            if token is None:
                raise GameStateError(
                    f"{source.card_id}: evolution_card_id "
                    f"{d.evolution_card_id} not in db")
            g.pending_hand_add(h, g.create_spell(token.id, controller=h))

        game.events.register(Listener(event=TURN_END, owner=source,
                                      callback=on_eot))
        return None


# ══════════════════ BG35_MagicItem_814 Stuffed Coin Purse ══════════════════

class StuffedCoinPurseScript:
    """
    Natural language: When you reach Tier {0}, gain {1} gold.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `tavern_upgraded`
         （hero=, tier=）——引擎在 `upgrade_tavern` 成功与
         `upgrade_tavern_free` 成功时广播（game.py）
      2. 触发条件: `hero is 本人` 且 `tier >= num(0)=6` 且尚未发放
         （闭包 once 标记——"When you reach Tier 6" 是到达事件，不可
         重复发放; 也不追溯绑定前已到达的 Tier——绑定后无 "reach"
         事件则不触发）
      3. 发放 GainGold(hero, num(1)=12); 只作用于本人
      4. 只写 hero 作用域（不污染对手）

    Test: test_batch_trinkets5.py — 真实 upgrade 到 T6 前不发放 /
      真实升到 T6 恰好 +num(1) 金 / 再升级不重复 / 对手升级不触发

    Params: {0}=6 {1}=12（BG35_MagicItem_814 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        reach = _num(game, source.card_id, 0)
        gold = _num(game, source.card_id, 1)
        state = {"granted": False}

        def on_upgraded(g, hero=None, tier=0, **kw):
            if hero is not h or state["granted"] or tier < reach:
                return
            state["granted"] = True
            g.run_actions(GainGold(h, gold))

        game.events.register(Listener(event="tavern_upgraded",
                                      owner=source, callback=on_upgraded))
        return None


# ══════════════════ 注册 ══════════════════

def register() -> list[str]:
    """注册饰品第五批 20 张（无 DEFERRED 注册项）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_931", LuckyTabbyScript),
        ("BG30_MagicItem_713", BleedingHeartScript),
        ("BG35_MagicItem_302", StormcoilStickerScript),
        ("BG32_MagicItem_858", ExplorersBinocularsScript),
        ("BG35_MagicItem_815", MagiciansTopHatScript),
        ("BG32_MagicItem_304", HornOfSummoningScript),
        ("BG36_MagicItem_220", GlowingCrystalScript),
        ("BG32_MagicItem_864", BirdFeederScript),
        ("BG32_MagicItem_860", BeetleBandScript),
        ("BG35_MagicItem_711", ProtectiveRingScript),
        ("BG36_MagicItem_203", DragonSkullScript),
        ("BG32_MagicItem_862", UnholySanctumScript),
        ("BG36_MagicItem_811", DefensiveShellScript),
        ("BG35_MagicItem_871", MamaBearStickerScript),
        ("BG32_MagicItem_893", BluegillFlippersScript),
        ("BG30_MagicItem_422", LorewalkerScrollScript),
        ("BG30_MagicItem_426", ColorfulCompassScript),
        ("BG30_MagicItem_425", AzerothModelGlobeScript),
        ("BG30_MagicItem_435", GoldenizerSupplyScript),
        ("BG35_MagicItem_814", StuffedCoinPurseScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
