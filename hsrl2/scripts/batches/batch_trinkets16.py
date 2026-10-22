"""批次 trinkets16 — 饰品第十六批（作业单 2026-09-12，台账片 4/5）。

与 batch_trinkets1..15 的 id 集合互不相交；全部 id 都在
`CardDB.trinket_offer_pool()` 中（20/20 已运行核验）。数值一律
`CardDef.num(0/1/2)`（`CardDef` 无参数而文本含字面量的 +N 类增量按
SOP §3 在各类 `Params:` 行声明为文本权威）; 关联卡一律走数据链
`CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6，零硬编码
卡 id）; 随机一律 `game.rng`；全部状态写在 hero 作用域 / source 实体
属性 / 监听闭包（无 game 级 flag——SOP §12 item 9）。

实现（13 个 id / 13 张饰品）:
  BG32_MagicItem_890  Cliffdiver Sticker     — EoT: 最左随从
                                               +num(0)/+num(1)，按本回合
                                               已触发战吼次数递增
  BG32_MagicItem_894  Blessing Portrait      — Get Natural Blessing;
                                               每回合再来一张; 本人的
                                               Natural Blessing 同时作用于
                                               手牌随从
  BG32_MagicItem_901  Gold-plated Compass    — 下一次购买的 {0}=纳迦
                                               金色化 + 5 次免费刷新
  BG32_MagicItem_904  Hogwash Basin          — SoC: 对全部己方随从各
                                               施放 3 颗鲜血宝石
  BG32_MagicItem_906  Artanis Sticker        — Get a copy of '{0}'
                                               （Mothership，token）
  BG32_MagicItem_922  Charming Panpipes      — EoT: 最左随从
                                               +num(0)/+num(0); 每次施放
                                               **法术**递增（步长待权威）
  BG32_MagicItem_926  Morgl Portrait         — Get a Tide Oracle Morgl
  BG32_MagicItem_931  Azsharan Statuette     — Get num(0) random
                                               Spellcraft spells; 每回合
                                               再来 num(0) 张
  BG32_MagicItem_932  Vash'jir Anemone       — SoC: 己方纳迦
                                               +improved(num(1)) Health
  BG32_MagicItem_934  Dazzling Dagger        — 己方随从 +improved(num(1))
                                               Attack（`ApplyRaceAura
                                               (Race.ALL)` 光环）
  BG32_MagicItem_944  Empowerment Portrait   — Get an Azerite Empowerment;
                                               每回合再来一张
  BG32_MagicItem_950  Gritty Portrait        — Get a Gritty Headhunter
                                               that gives a Marauder's
                                               Contract; 每回合重复
  BG32_MagicItem_951  Gold Pendant           — 随机己方 Tier ≤ num(0)
                                               随从金色化; 每回合重复

DEFERRED（本批逐张评估后放弃；每张附具体依赖 + 实现路径，禁止近似）:
  - BG32_MagicItem_891 Finley's Helmet / BG32_MagicItem_892 Vibrant
    Bubble — "a random **Bonus Keyword**"。"Bonus Keyword" 的**定义域**
    在 CardDefs.xml 无任何数据字段（无 tag、文本无枚举），且需要"逐实体
    记录被授予的 bonus 关键词"新机制；RULES §9.6（2026-09-02 主线裁定）
    已将这 4 张（本两张 + BG32_MagicItem_417 Tarecgosa Sticker +
    BG36_MagicItem_801 Consuming Claw）钉死为 DEFERRED。本批复核维持:
    36.2.2 数据核实 `BG32_MagicItem_891` / `_892` 的 `num(0..3)` 全为
    None（文本 "+5/+5" 是字面量，Bonus Keyword 无参数字段），
    `spell_school` 均为 11（Lesser）。Dependency: (1) 官方/patch notes
    佐证 `BONUS_KEYWORD_SET`; (2) 新 tag `BONUS_KEYWORDS_GRANTED`（list）
    逐实体记录; (3) 授予走 `GainKeyword` 并追加该 tag。
  - BG32_MagicItem_902 Statue of Hir'eek — "After 2 minions **in the
    Tavern** are consumed, get a random Tavern spell"。
    `minion_consumed` 事件（actions/consume.py:120 fire）载荷只有
    `(demon=, minion=)` 且**在受害实体 zone 已被置 REMOVED 之后**广播
    （consume.py 步骤 2→3）——无来源区域字段，"酒馆中吞噬"与棋盘/手牌
    吞噬无法区分。Dependency: 事件携带 `zone=` 或 `from_tavern=True`
    （batch_trinkets8 台账同条目，本批复核仍缺失）。
  - BG32_MagicItem_907 S'Thara Sticker — "After your last minion dies
    each combat, summon your first Demon that died with its maximum
    stats"。三处缺口: (a) 触发时机是"**最后**一个随从死亡"，引擎只有
    逐次 DEATH 事件，且 `._death_processing` 重入保护窗口内查询
    "本场死亡日志最后一项"与"己方仍有存活随从"无官方顺序权威;
    (b) `game.combat_death_log` 条目只记录实体（无死亡顺序索引与
    "首个恶魔"筛选口径的文档化字段）; (c) 召唤物要恢复"**maximum
    stats**"（属性快照），战斗内召唤路径的 max_health 快照未定义。
    Dependency: 战斗内"最后随从死亡"触发点 + 本场按序 death log 的
    公开读取 API + 战斗内召唤 max-stats 快照。
  - BG32_MagicItem_920 Thaumaturgist Portrait — "Get a Thaumaturgist.
    Your Thaumaturgists' **Spellcrafts** are permanent"。
    已由 `batch_trinkets23` 注册（`add_permanent_spellcraft_rule` 已落地）。
    Dependency（历史）: **载荷未就绪**
    （RULES §7.4.6 **例外**条 / SOP §12 item 14）: 关联卡 `BG31_924`
    已有脚本（batch_misc.ThaumaturgistScript + `BG31_924t`
    ThaumaturgySpellScript，36.2.2 REGISTRY 核实），但其法术塑造法术
    的 +num(1)/+num(1) 是 `temporary=True`（下一招募阶段过期）——
    "permanent" 要求把该次施放的临时 buff 转为永久。引擎的永久化拦截
    `game._permanence_pending`（game.py:1202-1208）**只在
    `_finish_play_spell` 的 spell_resolving 窗口内被消费**，而本饰品是
    被动实体、无法在自己的钩子里消费该窗口; `_permanent_spellcraft_
    uuids` 只豁免**法术实体**的回合末丢弃（不改变 buff 的 temporary
    标志），语义不是"Spellcraft 效果永久"。
    Dependency: 引擎级"某控制者的随从施放的 Spellcraft 法术永久化"
    协议（例: `hero.permanent_spellcraft_uuids` + `_finish_play_spell`
    消费点），或 `_permanence_pending` 对被动监听器开放。
  - BG32_MagicItem_925 Hackerfin Portrait — "Get a Hackerfin. At the
    end of each turn, trigger your Hackerfins' Battlecries"。第二条
    条款**依赖被授予卡的行为**: 关联卡 `BG31_148` Hackerfin 在
    REGISTRY 中**无脚本**（36.2.2 核实）→ 它的 `battlecry` 钩子不存在，
    `TriggerBattlecry` 每回合空转。RULES §7.4.6 例外条: 本卡效果依赖 X
    的行为（X 的迁移状态属那张卡的台账，但此处 X 的效果缺失使本饰品
    整体空转）→ 整卡 DEFERRED（同 batch_trinkets12 Glowscale Portrait
    先例）。Dependency: 先迁 `BG31_148`（Battlecry: Give your other
    minions +num(0)/+num(1)，按 warband 中不同 Bonus Keyword 递增）。
  - ~~BG32_MagicItem_933 Weary Portrait~~ — **已解冻（2026-09-14 第二十三轮，
    `batch_trinkets37`）**。原"双重阻塞"两条均消除: (a) `BG31_830` +
    `BG31_830t`（+金色）已由 `batch_payload_minions` 注册; (b) 永久化
    协议已由 `batch_trinkets23`（`_920`）落地。**残余口径差异（本轮
    修正）**: Reinvigoration 的临时项是 **Reborn 关键词**（+2/+2 本就
    无期限），`_920` 的通用通道只翻转 temporary **buff** → 本轮给
    `ReinvigorationScript.on_play` 加 `permanent_spellcraft` 分支（不注册
    Reborn 过期监听），权威 34.0 官方 bugfix "retains Reborn from Weary
    Mage's Reinvigoration Spellcraft"。

**关联卡台账**（RULES §7.4.6 —— 交付正确即 CORRECT，关联卡自身脚本
未迁移不阻塞；下表登记被授予卡当前的迁移状态供主线跟踪）:
  | 饰品 | 关联卡（数据链 dbf → id） | 被授予卡脚本状态 |
  |---|---|---|
  | BG32_MagicItem_894 | 104472 → BG28_845 Natural Blessing (T4 池法术) | 已注册（NaturalBlessingScript） |
  | BG32_MagicItem_906 | 119960 → BG31_HERO_802pt7 Mothership (token) | 未注册（不影响交付） |
  | BG32_MagicItem_926 | 103047 → BG27_513 Tide Oracle Morgl (T7, 非池) | 未注册（不影响交付） |
  | BG32_MagicItem_944 | 109232 → BG28_169 Azerite Empowerment (T6 池法术) | 已注册（AzeriteEmpowermentScript） |
  | BG32_MagicItem_950 | 115900 → BG31_891 Marauder's Contract (法术) → **反向解析** BG31_822 Gritty Headhunter | Gritty Headhunter 未注册（不影响交付） |
  | BG32_MagicItem_925 | 115848 → BG31_148 Hackerfin | **未注册 → 整卡 DEFERRED**（§7.4.6 例外） |
  | BG32_MagicItem_920 | 115563 → BG31_924 Thaumaturgist | 随从已注册，法术塑造法术的"永久"协议已落地 → 已注册（batch_trinkets23） |
  | BG32_MagicItem_933 | 119921 → BG31_830 Weary Mage | 随从 + 法术均已注册 → **已注册（batch_trinkets37）** |
  注: `BG32_MagicItem_894` 的 "also affect minions in hand" 与
  `BG32_MagicItem_950` 的 "Get a Gritty Headhunter **that gives a
  Marauder's Contract**" 都不依赖被授予卡的脚本（前者自行实现手牌
  分支，后者只要求把文本写进交付物的卡面——交付物是随从不是法术）。

协议: 饰品实体经 `_offer_trinkets` 购买 / `grant_trinket` 授予 →
`hero.trinkets`；脚本只挂 `on_bind` / `start_of_turn` /
`end_of_turn` / `start_of_combat`（接线审计 W1 白名单）。事件名均为
引擎真实 fire: `turn_start`（_begin_recruit_for，逐英雄带 hero= 载荷）/
`battlecry_trigger` / `tavern_spell_cast` / `spell_resolving` /
`minion_bought`。AURA 记档:
  - `BG32_MagicItem_934` Dazzling Dagger: "Your minions **have** +X
    Attack" 是 AURA（wiki tags `AURA`/`3407=0`）→ 直接用引擎原语
    `ApplyRaceAura(hero, Race.ALL, atk, 0)`（`Entity._aura_atk` 对
    `Race.ALL` 命中全部己方随从含无类型；Feral Talisman 同款）。
    on_bind 一次性补齐"基准 1 档 + 本局已达档位"层数，此后每次跨档
    再叠一层 → 已在场与未来随从同步抬升（旧版"一次性 Buff + SUMMON
    监听"不抬升已在场随从，已废弃）。残余差异仅"饰品被 replace/移除
    时已叠层不回收"（`race_auras` 无移除协议; 招募期无此路径）。
  - `BG32_MagicItem_894` Blessing Portrait: "Your Natural Blessings
    also affect minions in hand" 是 AURA（wiki tags `AURA`/`4701=1`）
    → 以 `spell_resolving`（每 cast 一次、在主 on_play **之前** fire）
    的常驻监听实现手牌分支；棋盘分支仍由 NaturalBlessingScript 本体
    产生，零重复施加（SOP §12 item 2: 不复制他脚本私有记账、不重放
    效果体）。
  - `BG32_MagicItem_901` Gold-plated Compass: 购买路径金色化无引擎
    原语（`Transform` 只支持棋盘目标; 无 `PENDING_GOLDEN` tag）→
    本地 `_goldenize_hand` 复用 Golden Touch 的酒馆版语义（换金色卡
    定义、buff 并集、`GILDED_NOT_TRIPLED` 回池 1 份），已金色目标
    不消耗（wiki Patch 32.4.0 bugfix: "Fixed a bug where Gold-plated
    Compass's effect was consumed if you bought a minion that was
    already Golden"）。
  - `BG32_MagicItem_950` Gritty Portrait: **数据链反指**。饰品
    `evolution_card_id`（dbf 115900）经 `db.by_dbf` 命中的是
    `BG31_891` Marauder's Contract（法术），而非卡面点名的 Gritty
    Headhunter（`BG31_822`）。两卡互指（`BG31_822.evolution_card_id`
    也 = 115900）→ 本类以**反向解析**（枚举 `evolution_card_id ==
    115900` 的 MINION 定义）定位交付物，零硬编码 id; 解析失败
    fail-loud。**建议主线**把饰品 `BG32_MagicItem_950` 的
    `evolution_card_id` 修正为 115597（详见报告"跨文件台账"）。
"""

from __future__ import annotations

from typing import List, Optional

from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.events import (
    BATTLECRY_TRIGGER,
    MINION_BOUGHT,
    TAVERN_SPELL_CAST,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

# Natural Blessing 的卡 id（数据链解析失败时的 fail-loud 由
# GameStateError 承担; 本常量仅用于 spell_resolving 的判别——
# 与 `game.trinket_related_card` 独立，避免每次施放都做 dbf 解析）
_NATURAL_BLESSING = "BG28_845"

# 含 All 型的匹配族（Amalgam 全种族，RULES §6.4 匹配裁定）
_NAGA_RACES = (Race.NAGA, Race.ALL)

# Clickdiver/Panpipes 的 "num(0)" 层级标记（文本 "@" 第二段的"improved"
# 语义——本仓统一 rung 口径: 取该列 <= 当前计数的完整分档数）
def _rungs(count: int, per: int) -> int:
    """计数 → 完整分档数（每 per 次递增 1 档；per<=0 时防御性归零）。"""
    if per <= 0:
        return 0
    return count // per


def _hero(ctx):
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _left_most(hero) -> Optional[Minion]:
    """最左存活随从（"your left-most minion"；空场/全死 → None 落空）。"""
    for m in hero.board:
        if not m.dead:
            return m
    return None


# ══════════════ BG32_MagicItem_890 Cliffdiver Sticker ══════════════


class CliffdiverStickerScript:
    """
    Natural language: [x]At the end of each turn, give
    your left-most minion +{0}/+{1}.
    <i>(Improved by each <b>Battlecry</b>
    you've triggered this turn!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）:
         - `battlecry_trigger`（minion=）——引擎在**每次**战吼触发后
           广播（game.py `_finish_play_minion` 与 `TriggerBattlecry`
           两处; 金色×2 与 Brann 加倍各计一次，与官方 "for each
           Battlecry you've triggered" 按触发次数计的口径一致）。
           条件 `minion.controller is 本人` → `source._cliffdiver_bc += 1`
         - `turn_start`（hero=, turn=）——逐英雄广播（game.py:271）;
           `hero is 本人` 时把 `source._cliffdiver_bc` 归零（"this
           turn" 语义）
      2. `end_of_turn`: 最左存活随从（`_left_most`）获得
         Buff(atk=num(0)*(1+bc), health=num(1)*(1+bc))——bc = 本回合
         已触发战吼次数; 空场 → 落空（不报错）
      3. 监听器在绑定时注册，绑定当回合已触发的战吼**不计入**
         （无历史追踪——与"每回合开始时清零"的引擎事件模型一致）
      4. 计数写在 source 实体属性（非 hero/game 级 flag——SOP §12
         item 9）; 只作用于本人棋盘
      5. **已知口径缺口（AMBIGUOUS，待引擎读取点）**: 计数闭包从
         `on_bind` 起算 → **同回合在购买本饰品之前**触发的战吼不计
         （文本 "Battlecries you've **triggered this turn**" 应为全回合）。
         引擎现有 `GameTag.COUNTER_BATTLECRIES` 是**本局**累计（单调
         递增、无每回合重置点），故"绑定时刻的本回合起点值"不可得，
         无法在 on_bind 精确回填（用绑定值当基线会漏掉本回合早段、
         用 0 会多算往期回合，二者都是近似——按 SOP §6b 不采用）。
         Dependency（引擎侧）: 在 `_begin_recruit_for`/`Hero.clear`
         把 hero 的"本回合已触发战吼数"归零、并在 `battlecry_trigger`
         广播点 +1（可复用 `COUNTER_BATTLECRIES` 的写入处）→ 脚本
         `on_bind` 读该 hero 级 tag 即得全回合精确值。

    Test: test_batch_trinkets16.py — 无战吼时 EoT 恰好
      +num(0)/+num(1) / 2 次战吼后 EoT +3×num(0)/+3×num(1)（对照:
      1 次战吼 → ×2; 正对照与负对照同方法内）/ 下一回合 turn_start
      后计数归零 → 回到 ×1 / 对手战吼不计数（正对照: 本人战吼生效）/
      空场落空不报错 / 无饰品对照不变

    Params: {0}=3 {1}=2（BG32_MagicItem_890 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._cliffdiver_bc = 0

        def on_bc(g, minion=None, _h=h, _src=source, **kw):
            if minion is None or minion.controller is not _h:
                return
            _src._cliffdiver_bc = getattr(_src, "_cliffdiver_bc", 0) + 1

        def on_turn_start(g, hero=None, **kw):
            if hero is not h:
                return
            source._cliffdiver_bc = 0

        game.events.register(Listener(event=BATTLECRY_TRIGGER, owner=source,
                                      callback=on_bc))
        game.events.register(Listener(event="turn_start", owner=source,
                                      callback=on_turn_start))
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        target = _left_most(h)
        if target is None:
            return None
        bc = getattr(source, "_cliffdiver_bc", 0)
        mult = 1 + bc
        return Buff(target, atk=_num(game, source.card_id, 0) * mult,
                    health=_num(game, source.card_id, 1) * mult)


# ══════════════ BG32_MagicItem_894 Blessing Portrait ══════════════


class BlessingPortraitScript:
    """
    Natural language: [x]Get a Natural Blessing. At the
    start of each turn, get another.
    Your Natural Blessings
    also affect minions in hand.

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(本人, 本饰品 id)`——
         数据链 `evolution_card_id`（dbf 104472）→ `db.by_dbf` →
         `BG28_845` Natural Blessing（`card_type=42 BACON_SPELL`、
         `is_pool_spell=True`（T4 池法术）→ `spell_pool.acquire` 占池，
         池空落空; 36.2.2 数据核实）
      2. `start_of_turn`: 同路径再授予 1 张（"At the start of each turn,
         get another"）
      3. on_bind 同时注册持久 `spell_resolving` 监听器（owner=饰品）:
         该事件在**每次施放**时、main on_play **之前** fire
         （`_finish_play_spell` game.py:1204，携带 spell=, target=,
         cast_no=）。条件 `spell.card_id == BG28_845` ∧
         `spell.controller is 本人` → 对**本人手牌中的随从**（Minion
         实体、与 target.race 共享类型者，含 target 自身不在手牌时的
         纯手牌集合）各施加 `tavern_spell_buff(+num(0), +num(1))`
         ——"also affect minions in hand"（wiki tags `AURA`/`4701=1`
         的等价实现; 棋盘分支仍由 NaturalBlessingScript 产生，
         本监听**不**重放棋盘效果——SOP §12 item 2）
      4. 类型匹配 `_shares_type` 与 NaturalBlessingScript 同口径
         （目标 ALL → 一切有类型; 目标 NONE → 仅无类型;
         目标 R → race ∈ (R, ALL)）; 数值读 `BG28_845` 的
         `num(0)/num(1)` 而非饰品（权威是被施放的法术）
      5. 只作用于本人（owner 隔离）; 双施（Balinda）时每 cast 各结算
         一次（cast_no 逐次，手牌随从可重复获得）

    Test: test_batch_trinkets16.py — 绑定入手 1 张 BG28_845 且法术池 -1 /
      真实 end_recruit_phase 后再 +1 / 真实 play_spell（选 Murloc 目标）
      后同类型手牌随从获得（基础 +num(0)/+num(1)）而不同类手牌不变
      （正负对照同方法）/ 对手手牌不受影响 / 无饰品对照不变 /
      池空落空

    Params: 法术侧 {0}=3 {1}=3（BG28_845 num(0/1)——权威值，饰品无参）
    """

    @staticmethod
    def _grant(game, h, source) -> bool:
        return game.grant_trinket_related_card(h, source.card_id)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        BlessingPortraitScript._grant(game, h, source)
        d = game.db.get(_NATURAL_BLESSING)
        if d is None:
            raise GameStateError(
                f"{_NATURAL_BLESSING}: Natural Blessing missing from db")
        atk = _num(game, _NATURAL_BLESSING, 0)
        health = _num(game, _NATURAL_BLESSING, 1)

        from hsrl2.actions.racefx import tavern_spell_buff
        from hsrl2.scripts.batches.batch_spells2 import _shares_type

        def on_resolving(g, spell=None, target=None, _h=h, **kw):
            if spell is None or spell.controller is not _h:
                return
            if spell.card_id != _NATURAL_BLESSING:
                return
            if not isinstance(target, Minion) or target.dead:
                return
            out = [tavern_spell_buff(m, atk, health)
                   for m in list(_h.hand)
                   if isinstance(m, Minion) and not m.dead
                   and _shares_type(m.race, target.race)]
            if out:
                g.run_actions(out)

        game.events.register(Listener(event="spell_resolving", owner=source,
                                      callback=on_resolving))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        BlessingPortraitScript._grant(game, h, source)
        return None


# ══════════════ BG32_MagicItem_901 Gold-plated Compass ══════════════


def _goldenize_hand(game, ent: Minion) -> bool:
    """手牌内实体金色化（Reno 语义; batch_spells2 `_goldenize_tavern`
    的手牌同构实现）。

    `Transform` Action 只支持棋盘目标（actions/stats.py 对非 board 抛
    GameStateError）→ 此处同构实现: 换金色卡定义（create_minion
    golden=True 补 GOLDEN + TRIPLE_BASE_CARD_ID tag）、buff 并集保留、
    原位替换 `hero.hand`、fire "transform"、不发三连奖励
    （`GILDED_NOT_TRIPLED` 回池 1 份——Reno 语义）。原实体
    `zone=REMOVED` + 注销监听器。返回 True=已金色化。
    """
    if not isinstance(ent, Minion) or ent.is_golden:
        return False
    hero = ent.controller
    if hero is None or ent not in hero.hand:
        return False
    base_def = game.db.get(ent.card_id)
    golden_def = (game.db.golden_version(base_def)
                  if base_def is not None else None)
    if golden_def is None:
        return False
    new = game.create_minion(golden_def.id, controller=hero, golden=True)
    new._buffs = list(ent._buffs)
    new.set(GameTag.HEALTH, new.max_health)
    new.set(GameTag.GILDED_NOT_TRIPLED, True)
    idx = hero.hand.index(ent)
    new.zone = Zone.HAND
    hero.hand[idx] = new
    ent.zone = Zone.REMOVED
    game.events.unregister_owner(ent)
    game.events.fire(game, "transform", old=ent, new=new)
    return True


class GoldPlatedCompassScript:
    """
    Natural language: [x]Make the next {0}
    you buy Golden.
    Gain 5 free <b>Refreshes</b>.

    Formal spec:
      1. `{0}` = num(0) = 92 = `Race.NAGA`（36.2.2 数据核实;
         zhCN 文本 "镀金罗盘" 对应 "...下一个购买的**纳迦**变金"）。
         故"下一个你购买的"限定为**纳迦随从**——非纳迦随从与法术的
         购买不消耗本效果（"the next {0} you buy" 的 {0} 是卡类限定）
      2. on_bind: `hero.FREE_REFRESH_REMAINING(1034) += 5`——文本
         "Gain 5 free Refreshes"（字面量 5，CardDef 无参数）; 消费点
         `refresh_tavern`（game.py:352 优先扣免费刷新再扣金币）
      3. on_bind 注册持久 `minion_bought` 监听器（owner=饰品;
         game.py buy_from_tavern 在入手后广播 minion=）:
         - 条件: `minion.controller is 本人` ∧ 实体仍在本人手牌 ∧
           非金色 ∧ `race ∈ (NAGA, ALL)`（Amalgam 视为纳迦，RULES §6.4）
         - 命中: `_goldenize_hand` 换金色卡定义（buff 并集保留、
           `GILDED_NOT_TRIPLED` 回池 1 份、不发三连奖励）→
           消费标记 `source._compass_armed = False`
         - 已是金色 → **不消耗**（wiki Patch 32.4.0.221908 bugfix:
           "Fixed a bug where Gold-plated Compass's effect was consumed
           if you bought a minion that was already Golden"）
         - 无金色定义（`golden_version` 缺失）→ 不消耗（落空）
      4. 绑定后三连检查: 金色替换进手牌可能使手牌凑齐 3 份 →
         调 `game.check_for_triple(本人, new)`（金色实体本身不再合成）
      5. 一次性: 标记消费后监听器保持注册但 `_compass_armed=False`，
         永不二次触发（"the next"）; 只作用于本人购买

    Test: test_batch_trinkets16.py — 绑定后 FREE_REFRESH_REMAINING == 5
      且两次 refresh_tavern 不扣金币（正对照: 免费用尽后扣金）/
      真实 buy_from_tavern 购买纳迦 → 手牌实体 is_golden 且
      GILDED_NOT_TRIPLED 且基础卡池余量不变（买的那份已回池）/
      第二次购买纳迦不再金色（一次性）/ 购买非纳迦（野兽）不消耗
      且后续购买纳迦仍金色（对照）/ 对手购买不受影响 /
      无饰品对照普通购买

    Params: 免费刷新数=5（文本字面量 "Gain 5 free Refreshes"——
            BG32_MagicItem_901 无该参数）; {0}=92（num(0)=Race.NAGA）
    """

    _FREE_REFRESHES = 5     # 文本字面量 "Gain 5 free Refreshes"

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        race = _num(game, source.card_id, 0)
        if race != int(Race.NAGA):
            raise GameStateError(
                f"{source.card_id}: num(0)={race} 不是 Race.NAGA"
                f"（{int(Race.NAGA)}）——数据链漂移，拒绝近似实现")
        h.set(GameTag.FREE_REFRESH_REMAINING,
              h.get(GameTag.FREE_REFRESH_REMAINING, 0)
              + GoldPlatedCompassScript._FREE_REFRESHES)
        source._compass_armed = True

        def on_bought(g, minion=None, _h=h, _src=source, **kw):
            if not getattr(_src, "_compass_armed", False):
                return
            if minion is None or minion.controller is not _h:
                return
            if minion not in _h.hand:
                return
            if minion.race not in _NAGA_RACES:
                return
            if _goldenize_hand(g, minion):
                _src._compass_armed = False
                if _h.hand:
                    g.check_for_triple(_h, _h.hand[-1])

        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        return None


# ══════════════ BG32_MagicItem_904 Hogwash Basin ══════════════


class HogwashBasinScript:
    """
    Natural language: <b>Start of Combat:</b> This plays 3 <b>Blood
    Gems</b> on all your minions.

    Formal spec:
      1. `start_of_combat`（饰品 SoC 钩子，引擎顺序: 饰品→任务奖励→
         随从→英雄技能; RULES §4.2）: 对**本人棋盘全部存活随从**各执行
         `PlayBloodGems(m, count=3)`——每颗宝石 = `BG20_GEM`
         `CardDef.num(0/1)` + 本人 `BLOOD_GEM_BONUS_*`（actions/
         bloodgem.py `_gem_values` 权威读取; 文本 "3 Blood Gems" 为
         字面量，CardDef 无参数），并累加 `GEMS_PLAYED_ON` + 广播
         `blood_gem_played`（与手牌打出的宝石同一记账出口）
      2. 空场 → 无目标，效果整体落空（不报错）
      3. 只作用于本人棋盘（对手随从在对手自己的 SoC 里结算）
      4. 每场战斗触发一次（引擎 SoC 阶段逐战斗调用）

    Test: test_batch_trinkets16.py — 真实 run_combat 后本人随从各
      +3×num(0)/+3×num(1) 且 GEMS_PLAYED_ON=3（数值从 BG20_GEM
      CardDef 计算）/ 对手随从不变（owner 隔离——所以此测试构造双方
      各 1 只）/ 无饰品对照不变 / 空场不报错

    Params: count=3（文本字面量 "plays 3 Blood Gems"——CardDef 无参数）
    """

    COUNT = 3

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return [PlayBloodGems(m, count=HogwashBasinScript.COUNT,
                              source=source)
                for m in _living(h)]


# ══════════════ BG32_MagicItem_906 Artanis Sticker ══════════════


class ArtanisStickerScript:
    """
    Natural language: Get a copy of '{0}'.

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(本人, 本饰品 id)`——
         数据链 `evolution_card_id`（dbf 119960）→ `db.by_dbf` →
         `BG31_HERO_802pt7` Mothership（`card_type=4 MINION`、
         `is_pool_minion=False`（token / 池外专属卡）→ 零池操作;
         36.2.2 数据核实）。文本 `{0}` 由卡名解析（无模板参数——
         `reward_dbf_id` 家族同款数据链）
      2. 白板副本进手牌（`grant_card_copy_to_hand`: 不复制附魔、
         满手走 `pending_hand_add` 排队 RULES §3.3）
      3. 数据链断裂（evolution_card_id 为 None 或 dbf 未注册）→
         静默落空（`grant_trinket_related_card` 返回 False; 不近似）

    Test: test_batch_trinkets16.py — 绑定后本人手牌恰多 1 张
      BG31_HERO_802pt7 且该卡非池（`minion_pool.available` 不变量
      前后不变）/ 对手手牌不变 / 数据链解析 == BG31_HERO_802pt7 /
      无饰品对照手牌为空

    Params: 无模板参数（CardDef num 全 None；{0} 是卡名）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════ BG32_MagicItem_922 Charming Panpipes ══════════════


class CharmingPanpipesScript:
    """
    Natural language: [x]At the end of each turn,
    give your left-most minion
    +{0}/+{0}. After you cast
    a spell, improve this.

    Formal spec:
      1. on_bind 注册持久 `spell_resolving` 监听器（owner=饰品）:
         引擎在**每次施放**时、main on_play **之前** fire
         （`_finish_play_spell` game.py，携带 spell=, target=,
         cast_no=; 效果施法路径 `cast_spell_effect` 同样广播）。
         条件 `spell.controller is 本人` → `source._panpipes_bonus += 1`
         （"After you cast a spell, improve this"——每次施放递增）。
         **不是** "酒馆法术": zhCN「在你施放一个**法术**后」/ 英文
         "a spell" 无 Tavern 限定 → 全法术域（酒馆法术 / Spellcraft /
         手牌血宝石 / 效果施法）。事件选择: `spell_resolving` 每 cast
         一次 → 双施（SPELL_DOUBLER / 金色 Balinda `BG35_883`）按施放
         次数计（旧实现用 `tavern_spell_cast` 既漏非酒馆法术、又漏
         双施的第二次）。同仓先例: 本批 `BG32_MagicItem_894` Blessing
         Portrait 的 spell_resolving 监听。
         ⚠️ **步长 AMBIGUOUS（待权威）**: 本卡 CardDef 只有 num(0)=3
         （文本 "+{0}/+{0}" 的加成基数），**无**递增步长的数据字段。
         两种读法:
           (a) **现状口径** +1/次（每次施放 improve 1 点）;
           (b) 印面值递增 = num(0)=3/次——全仓 Improve 家族按印面值递增
               （Kibble / Spark Snapper / Murky Sticker / Copper Coil;
               同批 890 Cliffdiver Sticker 的 "Improved by each
               Battlecry" 亦按印面值 num(0)/num(1) 递增）。
         因**无数据权威**（`num(1..3)` 全 None、文本无第二数值占位符、
         wiki / 36.2.2 patch notes 无 Notes）→ 按 SOP §6b 保持 (a) 并
         记档"待权威"; 若官方裁定 (b)，只需把 `_panpipes_bonus` 的
         增量由 `1` 改为 `_num(game, source.card_id, 0)`。
      2. `end_of_turn`: 最左存活随从（`_left_most`）获得
         Buff(atk=num(0)+bonus, health=num(0)+bonus)——文本
         "+{0}/+{0}"（同一个 {0}; 36.2.2 num(0)=3）；空场落空
      3. 递增是**永久**的（跨回合累积）; 绑定当回合之前的施放不计
         （文本无 "this game/turn" 回溯限定，属施放当下的 "improve"）
      4. 加成写在 source 实体属性; 只作用于本人（对手施法不递增、
         对手随从不获得）

    Test: test_batch_trinkets16.py — 无施法时 EoT 恰好
      +num(0)/+num(0) / 真实 play_spell(Shiny Ring) 后 EoT
      +（num(0)+1）两次（正对照: 无施法者为 num(0)）/ Spellcraft
      非池法术同样递增（旧实现 tavern_spell_cast 不计——证伪旧实现）/
      跨回合累积（连续两个 end_recruit_phase）/ 对手施法不递增（正对照:
      本人施法生效）/ 空场落空 / 无饰品对照不变

    Params: {0}=3（BG32_MagicItem_922 num(0)——攻防同值）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._panpipes_bonus = 0

        def on_cast(g, spell=None, _h=h, _src=source, **kw):
            if spell is None or spell.controller is not _h:
                return
            _src._panpipes_bonus = getattr(_src, "_panpipes_bonus", 0) + 1

        game.events.register(Listener(event="spell_resolving", owner=source,
                                      callback=on_cast))
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        target = _left_most(h)
        if target is None:
            return None
        value = _num(game, source.card_id, 0) \
            + getattr(source, "_panpipes_bonus", 0)
        return Buff(target, atk=value, health=value)


# ══════════════ BG32_MagicItem_926 Morgl Portrait ══════════════


class MorglPortraitScript:
    """
    Natural language: Get a Tide Oracle Morgl.

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(本人, 本饰品 id)`——
         数据链 `evolution_card_id`（dbf 103047）→ `db.by_dbf` →
         `BG27_513` Tide Oracle Morgl（T7、`is_pool_minion=False`
         （池外专属卡）→ 零池操作; 36.2.2 数据核实）
      2. 白板副本进手牌（满手排队 RULES §3.3）; 关联卡自身脚本的迁移
         状态属该卡台账（RULES §7.4.6），不阻塞本饰品

    Test: test_batch_trinkets16.py — 绑定后本人手牌恰多 1 张 BG27_513
      且 `minion_pool.available` 不变量前后不变（非池卡）/ 对手手牌
      不变 / 数据链解析 == BG27_513

    Params: 无模板参数（CardDef num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════ BG32_MagicItem_931 Azsharan Statuette ══════════════


class AzsharanStatuetteScript:
    """
    Natural language: [x]Get {0} random <b>Spellcraft</b>
    spells. At the start of
    each turn, get {0} more.

    Formal spec:
      1. 候选池 = `_spellcraft_spell_ids(game)`（batch_spells2 已验收的
         数据链口径: 池内 Spellcraft 随从的 `spellcraft_id`（dbf）
         指向的法术定义 = 全部可获取的 Spellcraft 法术; 无硬编码 id）。
         36.2.2 实测 9 张基础版（金色法术仅由金色随从生成，不入候选）
      2. on_bind: `game.rng.sample(cands, min(num(0), len))` 无放回抽
         num(0) 张**互不相同**的法术（"Get N random ... spells" 的
         互异口径——Spitescale Special `BG28_606` 同款裁定）; 每张
         `create_spell` + 置 `SPELLCRAFT` tag（回合末丢弃协议，
         `end_recruit_phase` 以该 tag 键控）+ `pending_hand_add`
         （满手排队 P6）; 非池 token → 不占 `spell_pool`
      3. `start_of_turn`: 同路径再抽 num(0) 张（"At the start of each
         turn, get {0} more"）
      4. 候选不足 num(0) → 取 min（数据缺口防御; 当前 9 张不触发）
      5. 只进本人手牌（owner 隔离; 对手不获得）

    Test: test_batch_trinkets16.py — 绑定后本人手牌恰多 num(0)=3 张
      互不相同的 BG**t 法术且全部带 SPELLCRAFT tag、法术池余量不变量
      不变（非池）/ 真实 end_recruit_phase 后再 +3（跨回合语义；同回合
      重复调用不叠加）/ 对手手牌不变 / 无饰品对照 0 张

    Params: {0}=3（BG32_MagicItem_931 num(0)）
    """

    @staticmethod
    def _grant(game, h, source) -> int:
        from hsrl2.scripts.batches.batch_spells2 import (
            _spellcraft_spell_ids)
        count = _num(game, source.card_id, 0)
        cands = _spellcraft_spell_ids(game)
        if not cands:
            return 0
        got = 0
        for sid in game.rng.sample(cands, min(count, len(cands)),
                                   label="azsharan_statuette"):
            s = game.create_spell(sid, controller=h)
            s.set(GameTag.SPELLCRAFT, True)
            game.pending_hand_add(h, s)
            got += 1
        return got

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        AzsharanStatuetteScript._grant(game, h, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        AzsharanStatuetteScript._grant(game, h, source)
        return None


# ══════════════ BG32_MagicItem_932 Vash'jir Anemone ══════════════


class VashjirAnemoneScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give
    your Naga +{1} Health.
    <i>(Improved by every 4 spells
    you've cast this game!)</i>@[x]<b>Start of Combat:</b> Give
    your Naga +{1} Health.
    <i>(Cast {2}/4 spells
    to improve!)</i>

    Formal spec:
      1. 档数 = rungs(**本局全局**施法数, num(0))——施法数直接读
         `hero.TAVERN_SPELLS_CAST_THIS_GAME`（引擎对 `is_pool_spell`
         累计的权威 tag）。文本 "Improved by every 4 spells you've cast
         **this game**"（zhCN「在本局对战中，你每施放 4 个法术都会
         提升」）是本局对战口径 → **不存绑定快照**，绑定前本局已施放的
         法术同样计入档位。同句先例（照抄其口径）: batch_deathrattle
         `BG31_925 Showy Cyclist`（`mult = 1 + casts // num(0)`）、
         batch_econ_misc `BG31_035 Groundbreaker`、batch_misc
         `BG31_924t Thaumaturgy`。`num(0)=4` / `num(1)=1` 为 36.2.2
         数据核实值。
      2. `start_of_combat`（饰品 SoC 钩子）: 增量 = num(1) * (1 + 档数)
         ——基准 1 档来自卡面 "+{1} Health" 本体（档数 0 时仍给
         num(1)，与 Dazzling Dagger 的 "+{1} Attack" 同构）
      3. 对本人棋盘全部存活纳迦（race ∈ (NAGA, ALL)，Amalgam 视为
         纳迦——RULES §6.4）各 Buff(atk=0, health=num(1)*(1+档数))——
         "Give your Naga +{1} Health" 是 **SoC 本场增益**（战后由
         `run_combat` 棋盘快照复原回滚，RULES §3.5）
      4. 无纳迦 / 档数 0 → 本次落空（不报错）; 只作用于本人棋盘

    Test: test_batch_trinkets16.py — 绑定后 3 次施法 SoC 恰好
      +num(1) Health（档数 0，无 improve）/ 补到第 4 次施法后 SoC
      给 +2×num(1)（**正对照与负对照同方法**）/ 8 次施法 → ×3 /
      **绑定前**真实施放 num(0) 个酒馆法术再绑定 → SoC 给
      +2×num(1)（本局口径，倒灌旧实现为 +1）/ 对手施法不递增
      （正对照: 本人施法递增）/ 非纳迦随从不变 / 无饰品对照不变 /
      空板不报错

    Params: {0}=4 {1}=1（BG32_MagicItem_932 num(0)/num(1)）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        per = _num(game, source.card_id, 0)
        step = _num(game, source.card_id, 1)
        casts = h.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        bonus = step * (1 + _rungs(max(0, casts), per))
        target = [m for m in _living(h) if m.race in _NAGA_RACES]
        if not target:
            return None
        return [Buff(m, atk=0, health=bonus) for m in target]


# ══════════════ BG32_MagicItem_934 Dazzling Dagger ══════════════


class DazzlingDaggerScript:
    """
    Natural language: [x]Your minions have
    +{1} Attack. <i>(Improved
    by every 4 spells you've
    cast this game!)</i>@[x]Your minions have
    +{1} Attack.
    <i>(Cast {2}/4 spells
    to improve!)</i>

    Formal spec:
      1. Wiki tags `AURA`（`3407=0`）——"Your minions **have** +X Attack"
         是持续光环（覆盖当前与未来全部己方随从）。引擎原语 =
         `ApplyRaceAura(hero, Race.ALL, atk, 0)`（`Entity._aura_atk` 对
         `Race.ALL` 光环命中**全部**己方随从（含无类型），且对当前在场
         与未来**任意入板路径**恒生效——Feral Talisman 同款语义）:
         - on_bind: 读取本局全局施法数 → 一次性补齐 `1 + 档数` 层
           `ApplyRaceAura(..., num(1), 0)`（基准 1 档 + 本局已达档位）
         - 持久 `tavern_spell_cast` 监听器（酒馆法术 = 引擎 "spells"
           口径）: 每次跨过一个档位（含一跳多档）再叠一层 num(1)
      2. 数值 = num(1) * (1 + 档数)，档数 = rungs(**本局全局**施法数,
         num(0))。施法数直接读 `hero.TAVERN_SPELLS_CAST_THIS_GAME`
         ——文本 "every 4 spells you've **cast this game**" 是本局对战
         口径 → **不存绑定快照**（绑定前本局已施放的法术不倒灌缺失;
         旧实现 `source._dagger_base` 快照是缺陷）。同句先例（照抄其
         口径）: batch_deathrattle `BG31_925 Showy Cyclist`、
         batch_econ_misc `BG31_035 Groundbreaker`。权威 = num(0)=4
         "every 4 spells"、num(1)=1 基础值。
      3. 叠层使**已在场**随从与未来随从同步抬升——修正旧实现
         "on_bind 一次性 Buff + SUMMON 监听" 的近似缺陷（实测 8 次
         施法后旧随从仍 +1，应 +3）; 现已删除一次性 Buff 与 SUMMON
         监听（光环实时读取，无需逐实体补丁）。
      4. 只作用于本人棋盘（对手随从不获得）

    Test: test_batch_trinkets16.py — 绑定后在场随从恰好
      +num(1) Attack（health/base 不变）/ 8 次**真实**施法后
      **已在场**随从与新入场随从**同为** +3×num(1)（旧实现旧随从仅
      +1——该断言即证伪旧实现）/ 绑定前已施放 8 个酒馆法术 → 绑定即
      +3×num(1)（本局口径，旧实现为 +1）/ 对手随从不变 /
      无饰品对照不变 / num 双向钉死

    Params: {0}=4 {1}=1（BG32_MagicItem_934 num(0)/num(1)）
    """

    @staticmethod
    def _rungs_now(h, game, source) -> int:
        """本局全局计数对应的**已达成档数**（不含基准 1 档）。"""
        per = _num(game, source.card_id, 0)
        casts = h.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        return _rungs(max(0, casts), per)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        step = _num(game, source.card_id, 1)
        applied = {"rungs": DazzlingDaggerScript._rungs_now(h, game, source)}

        def on_cast(g, spell=None, _h=h, **kw):
            if spell is None or spell.controller is not _h:
                return
            want = DazzlingDaggerScript._rungs_now(_h, g, source)
            # 一跳多档（双施 / 批量计数）时逐层补齐，层数 = 总档数
            while applied["rungs"] < want:
                applied["rungs"] += 1
                g.run_actions(ApplyRaceAura(
                    _h, Race.ALL, _num(g, source.card_id, 1), 0,
                    source_id=source.card_id))

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        # 基准 1 档（卡面 "+{1} Attack" 本体）+ 绑定前本局已达档位
        return [ApplyRaceAura(h, Race.ALL, step, 0,
                              source_id=source.card_id)
                for _ in range(applied["rungs"] + 1)]


# ══════════════ BG32_MagicItem_944 Empowerment Portrait ══════════════


class EmpowermentPortraitScript:
    """
    Natural language: [x]Get an Azerite
    Empowerment. At the
    start of each turn, get
    another.

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(本人, 本饰品 id)`——
         数据链 `evolution_card_id`（dbf 109232）→ `db.by_dbf` →
         `BG28_169` Azerite Empowerment（`card_type=42 BACON_SPELL`、
         T6、`is_pool_spell=True` → `spell_pool.acquire` 占池; 池空
         落空; 36.2.2 数据核实）
      2. `start_of_turn`: 同路径再授予 1 张（"At the start of each turn,
         get another"）
      3. 白板副本进手牌（满手排队）; 关联卡本体已有脚本
         （batch_spells1.AzeriteEmpowermentScript），其效果由该卡台账
         负责，本饰品只负责交付

    Test: test_batch_trinkets16.py — 绑定入手 1 张 BG28_169 且法术池
      −1（对照: 池余量单调下降）/ 真实 end_recruit_phase 后再 +1 /
      对手手牌不变 / 数据链解析 == BG28_169 / 绑定耗尽池后落空不报错

    Params: 法术侧 {0}=2 {1}=2（BG28_169 CardDef 权威; 饰品无参）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════ BG32_MagicItem_950 Gritty Portrait ══════════════


class GrittyPortraitScript:
    """
    Natural language: [x]Get a Gritty Headhunter
    that gives a Marauder's
    Contract. At the start of
    each turn, repeat this.

    Formal spec:
      1. **数据链异常与二次解析（本批发现，见报告"跨文件台账"）**:
         `BG32_MagicItem_950` 的 `evolution_card_id`（dbf 115900）经
         `db.by_dbf` 命中 `BG31_891` **Marauder's Contract**
         （`card_type=42` **法术**），而不是卡面点名的 **Gritty
         Headhunter**（`BG31_822`，dbf 115597）。两卡存在**互指链**:
         `BG31_822`（Gritty Headhunter，战吼 "Get a Marauder's
         Contract"）的 `evolution_card_id` 也 = 115900。故本类以
         **反向解析**定位交付物: 取 `game.trinket_related_card(本饰品)`
         得 dbf 115900 的卡; 若其不是随从，则在 `db._by_id` 中找
         `evolution_card_id == 该卡 dbf_id` 且 `card_type == MINION`
         的定义（Gritty Headhunter）→ 纯数据遍历，零硬编码卡 id
         （SOP §11 教训 5 的反向应用: 禁止凭记忆写 id，但允许按数据
         字段解析）。解析失败 → `GameStateError`（fail-loud，不近似）
      2. "Get a Gritty Headhunter **that gives a Marauder's Contract**"
         = 交付的随从**卡面自带**该战吼（其效果由 `BG31_822` 自身
         脚本负责——属那张卡的台账，本饰品不做第二次交付;
         RULES §7.4.6 "Get a X" 判定）。Gritty Headhunter 是
         `is_pool_minion=False`（池外专属卡）→ 零池操作
      3. `start_of_turn`: 同路径再授予 1 张（"At the start of each turn,
         repeat this"）
      4. 白板副本进手牌（满手排队）; 只进本人手牌

    Test: test_batch_trinkets16.py — 绑定入手 1 张 BG31_822（反向数据链
      解析）且 `minion_pool.available` 不变量不变（非池）/ 真实
      end_recruit_phase 后再 +1 / 对手手牌不变 / 数据链解析 ==
      BG31_822 且 card_type == MINION 且其 evolution_card_id 指回
      dbf 115900

    Params: 无模板参数（CardDef num 全 None）
    """

    @staticmethod
    def _related_minion(game, source):
        """反向数据链: 饰品关联卡（dbf 指向的法术）→ 生成该法术的随从。

        返回 CardDef（MINION）或 None。
        """
        from hsrl2.tags import CardType as _CT
        rel = game.trinket_related_card(source.card_id)
        if rel is None:
            return None
        if rel.card_type == _CT.MINION:
            return rel
        for d in game.db._by_id.values():
            if d.card_type != _CT.MINION:
                continue
            if d.evolution_card_id == rel.dbf_id:
                return d
        return None

    @staticmethod
    def _grant(game, h, source) -> bool:
        rel = GrittyPortraitScript._related_minion(game, source)
        if rel is None:
            raise GameStateError(
                f"{source.card_id}: 反向数据链未找到 'gives' 随从"
                f"（evolution 目标={getattr(game.trinket_related_card(source.card_id), 'id', None)}）")
        return game.grant_card_copy_to_hand(h, rel)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        GrittyPortraitScript._grant(game, h, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        GrittyPortraitScript._grant(game, h, source)
        return None


# ══════════════ BG32_MagicItem_951 Gold Pendant ══════════════


class GoldPendantScript:
    """
    Natural language: [x]Make a random friendly
    minion from Tier {0} or below
    Golden. At the start of
    each turn, repeat this.

    Formal spec:
      1. 候选 = 本人棋盘 Minion 中 `tech_level <= num(0)`（36.2.2
         num(0)=4，与 wiki 文本 "from Tier 4 or below" 一致）、
         非金色、且 `db.golden_version(def)` 存在（已金色不可再金色
         ——Reno 先例; 无金色定义者排除）的实体
      2. on_bind 与 `start_of_turn` 各调用一次 `_apply`:
         `game.rng.choice(候选)` 随机选定 → `_goldenize`（batch_battlecry
         的 Reno 语义: `Transform` 到金色卡定义保留 buff、
         `GILDED_NOT_TRIPLED` 回池 1 份、**不发三连奖励**、脚本按金色
         card_id 重绑）
      3. 空候选（空板 / 全为已金色或高 Tier）→ 本次落空（不报错，
         不消耗任何资源）
      4. 只作用于本人棋盘（owner 隔离）
      5. 每回合一次（SoT 钩子）; 同一回合多次调用会重复金色化不同
         目标（引擎每回合只调一次）

    Test: test_batch_trinkets16.py — 绑定后棋盘唯一 T2 随从变金
      （is_golden、TRIPLE_BASE_CARD_ID=基础 id、无三连奖励）且基础
      卡池余量不变（GILDED_NOT_TRIPLED 回池 1 份）/ Tier 5 随从
      （> num(0)）不被选中（正对照: 同时放 T2 与 T5，只有 T2 变金）/
      已金色目标不再被选 / 真实 end_recruit_phase 后再金色化一只
      （跨回合）/ 对手随从不变 / 无饰品对照不变 / 空板不报错

    Params: {0}=4（BG32_MagicItem_951 num(0)——"Tier 4 or below"）
    """

    @staticmethod
    def _apply(game, source) -> bool:
        from hsrl2.scripts.batches.batch_battlecry import _goldenize
        h = source.controller
        if h is None:
            return False
        max_tier = _num(game, source.card_id, 0)
        cands = []
        for m in _living(h):
            if m.is_golden:
                continue
            if m.has(GameTag.GILDED_NOT_TRIPLED):
                continue
            d = game.db.get(m.card_id)
            if d is None or d.tech_level > max_tier:
                continue
            if game.db.golden_version(d) is None:
                continue
            cands.append(m)
        if not cands:
            return False
        pick = game.rng.choice(cands, label="gold_pendant")
        _goldenize(game, pick)
        return True

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        GoldPendantScript._apply(game, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        if source.controller is None:
            return None
        GoldPendantScript._apply(game, source)
        return None


# ═════════════════════════ 注册 ═════════════════════════


def register() -> list[str]:
    """注册饰品第十六批 13 张（DEFERRED 台账见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_MagicItem_890", CliffdiverStickerScript),
        ("BG32_MagicItem_894", BlessingPortraitScript),
        ("BG32_MagicItem_901", GoldPlatedCompassScript),
        ("BG32_MagicItem_904", HogwashBasinScript),
        ("BG32_MagicItem_906", ArtanisStickerScript),
        ("BG32_MagicItem_922", CharmingPanpipesScript),
        ("BG32_MagicItem_926", MorglPortraitScript),
        ("BG32_MagicItem_931", AzsharanStatuetteScript),
        ("BG32_MagicItem_932", VashjirAnemoneScript),
        ("BG32_MagicItem_934", DazzlingDaggerScript),
        ("BG32_MagicItem_944", EmpowermentPortraitScript),
        ("BG32_MagicItem_950", GrittyPortraitScript),
        ("BG32_MagicItem_951", GoldPendantScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
