"""批次 trinkets30 — "新引擎原语解锁"复评批（作业单 2026-09-15，14 张）。

台账来源: 派发作业单给定的 14 个 id。14/14 在 `CardDB` 存在、14/14 在
`CardDB.trinket_offer_pool()` 中（运行核验——商店可提供成员; `BG32_MagicItem_892t`
是 Spellcraft 法术 token，`spellcraft_id` 数据链成员，不进商店池），且在本批之前
14/14 全部**不在** `REGISTRY`（与既有 batch_trinkets1..29 / batch_unlock_final
注册集合互不相交，运行核验）。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码; 文本无占位符的字面量
按 SOP §3 在各类 `Params:` 行显式声明并给出数据核实）; 关联卡一律走数据链
`CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6，零硬编码卡 id）;
随机一律 `game.rng`; 状态写在 hero 级 tag / source 实体属性（无 game 级 flag——
SOP §12 item 9）。

**新引擎原语逐条核对（2026-09-02，RULES §7.4.10b/§7.4.12/§7.4.13/§9.6）**
═══════════════════════════════════════════════════════════════════════
  | 原语（生产点） | 本批消费卡 | 核验结论 |
  |----------------|-----------|---------|
  | `hsrl2.game.BONUS_KEYWORD_TAGS`（模块级常量，官方 6 集）+ `game.grant_bonus_keyword` + `game.random_bonus_keyword`（`game.py` L44/L3219/L3238） | 891 / 892 / 892t | 六集定义域已收口（wiki oldid 830663）; 授予记录进 `GameTag.BONUS_KEYWORDS`，非六集 fail-loud |
  | `GameTag.PERSIST_BONUS_ONLY`（`_persist_keyword_tags` L3243 读取） | 417 | 战斗持久化**只**保留 6 集（不含 Poisonous/Cleave）——与 417 文本精确对应 |
  | `GameTag.PERSIST_COMBAT_CHANGES` + `run_combat` 的 `persist_totals` 通道（L2768-2830） | 417 | 属性增量 + 关键词态在战后重放; 单实体全量通道，本卡只需按位置写 tag 即精确 |
  | `game.add_permanent_spellcraft_rule(hero, source, predicate)`（L3118） | ~~（本批无——933 因此原语语义分歧 DEFERRED）~~ → **933 已注册（batch_trinkets37, 2026-09-14）** | 该原语只翻转 `temporary` buff; 全库"Spellcrafts are permanent"有两种实现: 同名 Dark Gift `BG36_MidGameEffect_000t62` 走 `_permanent_spellcraft_uuids`（法术卡不丢弃, L2339 读取, 无公开 API），本原语走 RULES §7.4.7a（临时 buff 永久化） |
  | `CardDef.num(4)`（NUM_5 已导出，`defs.py` L34/L70） | 431t / 920 / 923 | {2}/{4} 数值通道已通（431t num(2)=2/num(4)=1; 920 num(2)=4/num(4)=4）; 923 仍因语义缺口 DEFERRED |
  | `hero._next_trinket_kind`（`_offer_trinkets` L3459 读取并消费即清） | 818 | "Your next Trinket is a Lesser Trinket" 的 hero 级覆写读取点; `GainGold(num(0))` 走 `Hero.gold` setter |
  | `deathrattle_trigger`（`trigger_deathrattle` L2457 统一入口在效果**之后**广播） | 431t | "After you trigger a Deathrattle" 的唯一观察点; 载荷 `minion=` 带 controller → owner 隔离可判定 |
  | `spell_resolving`（per-cast，RULES §7.4.10/§7.4.12） | 920 / 923 | "cast spells" 计数域 = 每次施放（含双施/效果施法）; 不得用 `card_played` |
  | `racefx.tavern_spell_buff`（`TAVERN_SPELL_EXTRA_ATK/HEALTH` 消费点） | 920 | "your Tavern spells give an extra +X/+Y" 的唯一消费点（已全族接线） |
  | `Game.trigger_deathrattle(target, hero=)`（RULES §6.20） | 834 | "Trigger your Rylak Metalheads' Deathrattles" 的统一入口（Titus/dr_extra/计数同源） |
  | `actions.TriggerBattlecry(target)`（Brann 式 `BATTLECRY_DOUBLER`/计数/广播） | 925 | "trigger your Hackerfins' Battlecries" 的重触发原子 |
  | `ImproveBloodGems(hero, atk, health)`（`actions/bloodgem.py` L141） | 431t | 血宝石额外加成唯一入口（读取点 `_gem_values` 对手打/直施两条路径统一） |
  | `LISTENER owner=饰品` 生命周期（`grant_trinket` 接线 / `replace` 注销） | 891 / 892 / 431t / 920 | 持久监听器随饰品实体注销，跨局不残留 |

**CORRECT 9 项（注册 9 个 id = 8 张饰品 + 1 个 Spellcraft 法术 token）**
═══════════════════════════════════════════════════════════════════════
  BG32_MagicItem_417 Tarecgosa Sticker (Lesser, school=11) —
      on_bind + 每场 `start_of_combat`: 对本人棋盘**最左与最右**的龙
      （race ∈ {DRAGON, ALL}）置 `PERSIST_BONUS_ONLY` + `PERSIST_COMBAT_CHANGES`
      （"permanently keep **Bonus Keywords** and stats gained in combat"）。
      重定位语义: 上一次标记的实体先清除（跨回合位置变化不残留——旧标记
      跟随实体离开极位会让"两翼"扩张成 3 只，SOP §16c item 42 口径）。

  BG32_MagicItem_891 Finley's Helmet (Lesser, school=11) —
      on_bind 注册持久监听 `tavern_refresh_complete`（刷新窗口结束观察点，
      与监听器注册顺序无关——RULES §7.4.9）: 对本人酒馆内**当前**
      Murloc（race ∈ {MURLOC, ALL}）各 `Buff(+5/+5)` +
      `game.grant_bonus_keyword(m, random_bonus_keyword())`。

  BG32_MagicItem_892 Vibrant Bubble (Lesser, school=11) + token
      `BG32_MagicItem_892t`（Spellcraft 法术, `spellcraft_id=121139`）—
      饰品 on_bind 无额外条款（文本只有 Spellcraft）; 引擎
      `spellcraft.generate_for_hero` 扫描域含 `hero.trinkets`（RULES §6.13）
      → 每回合生成 1 张 `892t`; 法术 `needs_target=True` +
      `target_candidates` = 本人棋盘 Murloc（含 ALL）→ 授予随机 Bonus
      Keyword。

  BG35_MagicItem_431t Thornspike Pauldron (Greater, school=12) —
      on_bind 注册 `deathrattle_trigger`（`minion.controller is 本人`，
      效果**之后**广播）→ 累计增量 + `ImproveBloodGems(hero, num(2), num(4))`;
      每场 `start_of_combat` 回退累计增量（"until next combat"——下一场
      战斗开始即失效，本场战斗内仍有效）。

  BG35_MagicItem_920 Bubble Crown (Lesser, school=11) —
      on_bind 写 source 级剩余计数 = `num(0)`; 注册 `spell_resolving`
      （per-cast，RULES §7.4.10）: 每次施放 -1; 归零（一次性）→
      `hero.TAVERN_SPELL_EXTRA_ATK/HEALTH += num(2)/num(4)`
      （消费点 `racefx.tavern_spell_buff`）。

  BG35_MagicItem_834 Rylak Portrait (Lesser, school=11) —
      on_bind `grant_trinket_related_card`（数据链 98829 → `BG26_801`）;
      每场 `start_of_combat`: 对本人棋盘每只**存活** Rylak Metalhead
      （基础 id 判定，金色 `_G` 同族）`game.trigger_deathrattle(m, hero=本人)`
      ——统一入口，Titus/`dr_extra`/`dr_first`/计数/`deathrattle_trigger`
      全部同源。

  BG35_MagicItem_818 Mysterious Orb (Lesser, school=11) —
      on_bind: `GainGold(hero, num(0))` + `hero._next_trinket_kind = "lesser"`
      （`_offer_trinkets` 读取并消费即清）。

  BG32_MagicItem_925 Hackerfin Portrait (Greater, school=12) —
      on_bind `grant_trinket_related_card`（数据链 115848 → `BG31_148`）;
      每回合 `end_of_turn`: 对本人棋盘每只存活 Hackerfin（基础 id 判定）
      执行 `TriggerBattlecry(m)`（Brann 式翻倍由 action 处理）。

**DEFERRED 4 张（不注册）——803 / 804 已迁出，留档见下。各卡的 Status /
Dependency / Implementation path 逐张见各类 docstring（禁止第三态——
SOP §6b）**
═══════════════════════════════════════════════════════════════════════
  - BG32_MagicItem_803 Macaw Portrait — "Your Monstrous Macaws **also**
    trigger your left-most Battlecry"：载荷 `BGS_078` 已注册（其本体
    Rally → 最左**亡语**）; "also"追加项由
    `MonstrousMacawScript.rally` 读 `FLAG_MACAW_EXTRA_BATTLECRY`
    （RULES §7.4.17 条件化战吼），"left-most Battlecry"资格集 =
    最左**带战吼**者（32.2 论坛复现串 `M G x B y z`）。
    Status: 已迁出 → batch_trinkets36（2026-09-13）; 原阻塞（Rally 出口
    无读取点 + 资格集口径）均已消除。

  - BG32_MagicItem_804 Selfless Portrait — "Your Selfless Heroes **also**
    trigger on Battlecry"：载荷 `BG_OG_221` 已注册（亡语 = 随机友方圣盾），
    但"also trigger on Battlecry"需把载荷的 `deathrattle` 钩子挂到战吼
    触发点（payload 无读取点）; 在饰品侧重放 = 复刻他卡私有逻辑且与其
    真实死亡路径不一致（半实现 = 第三态）。
    **补充（2026-09-13 实测）**: 即便按"打出本体即触发"实现，直增
    `battlecry` 钩子会让**无饰品时**的 Selfless Hero 被静态门禁
    `_has_battlecry_hook` 判为战吼随从（探针: `bc_first` 已用 0 → 1）
    → 误消费 War Drum `BG32_MagicItem_416` 配额、误计入
    `BG30_MagicItem_982`、并成为 Young Murk-Eye Sticker
    `BG35_MagicItem_752` 的最左/最右战吼目标（脚本侧另有同构副本）。
    需引擎协议: 脚本声明**条件化战吼**（flag 名），门禁按 flag 判定。
    Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
    条件化战吼协议——上列实测所需的"按 flag 判定"门禁已落地）;
    原阻塞: 载荷的 `deathrattle` 钩子无战吼触发点读取通道。

  - BG35_MagicItem_923 Bewitched Ribbon — 数值通道已通（num(0..4)
    全可读: 1/1/2/2），但 "give your minions +{0}/+{1} **permanently**.
    (+{2}/+{4} **while in combat!**)" 的**战斗内"永久"口径无权威**:
    `run_combat` finally 全量回滚战斗期 Buff（RULES §3.5），战斗内写的
    "permanent" buff 会被快照抹掉; 数据/卡面无字段区分，wiki 无 Notes。

  - BG35_MagicItem_812 Corrupted Tome — "Whenever you would get a Triple
    Reward, get a Triple Prize instead" 需要 (a) `_grant_triple_reward`
    的替换覆写读取点（引擎无）与 (b) Darkmoon Prize 候选表（RULES §11.4
    已退役系统，数据无 tier→prize 映射）。

  - BG35_MagicItem_820 Safety Patch — "Cast Ice Block" 依赖 Secrets 子系统
    （`TB_Bacon_Secrets_12` 无脚本、无 `hero.secrets`、无致命伤害预防钩子）。

  - BG32_MagicItem_933 Weary Portrait — "Your Weary Mages' **Spellcrafts**
    are permanent" 的**通道语义无权威**（同一句文案在库内有两种实现）:
    (a) 同名 Dark Gift `BG36_MidGameEffect_000t62` 走 `game.
    _permanent_spellcraft_uuids`（**法术卡**回合结束不丢弃; L2339 读取）;
    (b) `game.add_permanent_spellcraft_rule`（RULES §7.4.7a）只把施法目标
    的 `temporary` buff 翻永久。Weary Mage 的 Spellcraft `BG31_830t`
    Reinvigoration 经 XML 核实（enUS/deDE/zhCN 一致）**+2/+2 本就是永久**
    （只有 "Reborn until next turn" 是临时）→ (b) 对本卡**零行为差异**
    （运行探针: 施放后 `temporary=False` 无从观察），注册即第三态。
    实现路径: 先补公开 API `game.make_spellcraft_permanent(minion)`
    （封装/取代私有 `_permanent_spellcraft_uuids`）并裁定"保留法术 +
    每回合照常生成"的堆叠口径（`spellcraft.generate_for_hero` 是否去重），
    再按 (a) 注册; 若权威改为 (b) 则须让"until next turn"子句可被永久化。
    关联卡 `BG31_830` 交付条款本身无阻塞（数据链 119921 已通）。

关联卡台账（RULES §7.4.6——"Get a X" 交付正确即 CORRECT；被交付卡自身
脚本未迁移只登记、不阻塞）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（`evolution_card_id` → `db.by_dbf`） | 脚本状态 |
  |------|--------------------------------------------|-----------|
  | 834 | 98829 → `BG26_801` Rylak Metalhead | 已注册（batch_payload_minions） |
  | 925 | 115848 → `BG31_148` Hackerfin | 已注册（batch_payload_minions） |
  | 933 | 119921 → `BG31_830` Weary Mage | 已注册（batch_payload_minions）; ~~饰品本体 DEFERRED~~ → **已注册（batch_trinkets37, 2026-09-14）** |
  | 892t | `spellcraft_id=121139` → `BG32_MagicItem_892t` | 本批一并注册 |
  说明: 417 / 891 / 431t / 920 / 818 / 923 / 812 / 820 的
  `evolution_card_id` 为空（36.2.2 数据核实）。

测试: `hsrl2/tests/test_batch_trinkets30.py`（行为层: 真实
`_offer_trinkets` 购买 / 真实 `run_combat` / 真实 `refresh_tavern` /
真实 `play_spell` / 真实 `trigger_deathrattle` / owner 隔离 / 跨回合
一次性 / 落空不消耗 / 满手队列 / 池占返 / 同 seed 确定性; 结构性
台账守卫按 TEST_SOP 标 `@engine-only`）。
"""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from hsrl2.actions import Buff, GainGold, TriggerBattlecry
from hsrl2.actions.bloodgem import ImproveBloodGems
from hsrl2.entity import Buff as EntityBuff
from hsrl2.events import (DEATHRATTLE_TRIGGER, Listener,
                          TAVERN_REFRESH_COMPLETE)
from hsrl2.game import BONUS_KEYWORD_TAGS, GameStateError
from hsrl2.queue import Action
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.minion import Minion

# ── 卡 id（CardDB 按名核实——禁止凭记忆写 id） ──
TARECGOSA_STICKER = "BG32_MagicItem_417"
FINLEYS_HELMET = "BG32_MagicItem_891"
VIBRANT_BUBBLE = "BG32_MagicItem_892"
VIBRANT_BUBBLE_SPELL = "BG32_MagicItem_892t"
THORNSPIKE_PAULDRON = "BG35_MagicItem_431t"
BUBBLE_CROWN = "BG35_MagicItem_920"
RYLAK_PORTRAIT = "BG35_MagicItem_834"
MYSTERIOUS_ORB = "BG35_MagicItem_818"
WEARY_PORTRAIT = "BG32_MagicItem_933"
HACKERFIN_PORTRAIT = "BG32_MagicItem_925"
MACAW_PORTRAIT = "BG32_MagicItem_803"
SELFLESS_PORTRAIT = "BG32_MagicItem_804"
BEWITCHED_RIBBON = "BG35_MagicItem_923"
CORRUPTED_TOME = "BG35_MagicItem_812"
SAFETY_PATCH = "BG35_MagicItem_820"

# 关联卡（数据链身份; 运行核验 `evolution_card_id`）
RYLAK = "BG26_801"          # 98829 → BG26_801
HACKERFIN = "BG31_148"      # 115848 → BG31_148
WEARY_MAGE = "BG31_830"     # 119921 → BG31_830

# 种族资格集（融合怪 Race.ALL 视为属于全部类型——RULES §8/§6.19 既有口径）
_DRAGON_RACES = (Race.DRAGON, Race.ALL)
_MURLOC_RACES = (Race.MURLOC, Race.ALL)

# 文本字面量（无模板参数; 数据核实见各类 Params 区）
_FINLEY_ATK = 5
_FINLEY_HEALTH = 5

# rng 审计标签（全仓约定: 每次随机带可读 label）
_RANDOM_KEYWORD_LABEL = "random_bonus_keyword"
# "spell_resolving" 尚无 events.py 常量（全仓既有脚本一律用字面量——
# batch_trinkets13/14/15/16/19 先例）; 生产点 game._finish_play_spell /
# cast_spell_effect
SPELL_RESOLVING = "spell_resolving"


def _hero(ctx):
    """on_bind ctx → 饰品持有英雄（引擎 grant_trinket 传 ctx={"hero": h}）。"""
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef 模板参数（缺失 → fail-loud，SOP §3）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _base_card_id(entity) -> Optional[str]:
    """实体的**基础**卡 id（金色 → TRIPLE_BASE_CARD_ID，缺省 card_id）。

    家族判定一律用它（SOP §16b item 17: 金色化实体不得用 card_id 直判）。
    """
    if entity is None:
        return None
    base = entity.get(GameTag.TRIPLE_BASE_CARD_ID, None)
    return base or getattr(entity, "card_id", None)


def _living(hero) -> List["Minion"]:
    return [m for m in hero.board if not m.dead]


def _matches_base(entity, base_id: str) -> bool:
    """实体是否属于 base_id 家族（金色经 TRIPLE_BASE_CARD_ID 回落）。"""
    return _base_card_id(entity) == base_id


def _grant_random_bonus_keyword(game, entity) -> None:
    """给实体授予一枚随机 **Bonus Keyword**（官方 6 集，`game.rng` 均匀）。

    统一出口: 走 `game.rng.choice` + `game.grant_bonus_keyword`
    （后者 fail-loud 校验六集成员并记录 `GameTag.BONUS_KEYWORDS`、
    广播 `bonus_keyword_granted`）。
    """
    tag = game.rng.choice(list(BONUS_KEYWORD_TAGS),
                          label=_RANDOM_KEYWORD_LABEL)
    game.grant_bonus_keyword(entity, tag)


# ══════════════ BG32_MagicItem_417 Tarecgosa Sticker ══════════════


class TarecgosaStickerScript:
    """
    Natural language: [x]Your left and right-most
    Dragons permanently keep
    <b>Bonus Keyword</b>s and stats
    gained in combat.

    Evidence: `data/bg_trinkets.json BG32_MagicItem_417`（lesser, cost 4,
    `spell_school=11`; `evolution_card_id` 空、num(0..4) 全 None）。
    Bonus Keyword 定义域 = 官方 6 集（RULES §9.6 / wiki.gg
    `Battlegrounds/Bonus_Keyword` oldid 830663）: Divine Shield / Reborn /
    Stealth / Taunt / Venomous / Windfury——引擎 `game.BONUS_KEYWORD_TAGS`。
    持久化通道 = `GameTag.PERSIST_COMBAT_CHANGES`（`run_combat`
    `persist_totals` 捕获属性总量 + 关键词态，战后重放）+
    `GameTag.PERSIST_BONUS_ONLY`（`_persist_keyword_tags` 只保留 6 集，
    不含 Poisonous/Cleave——与文本"keep **Bonus Keyword**s"精确对应）。

    Formal spec:
      1. on_bind: 清除 source 上次标记（绑定即建标记表），标记本人棋盘
         当前的**最左与最右龙**（race ∈ {DRAGON, ALL}——融合怪属龙）
      2. 标记 = `PERSIST_BONUS_ONLY=True` + `PERSIST_COMBAT_CHANGES=True`
         （两 tag 均由引擎读取——无脚本私有标记，W3 无空转）
      3. 每场 `start_of_combat` **重定位**: 先清除上次标记的实体，再标记
         当场的最左/最右龙（同 tag 幂等）——位置变化的回合标记跟随，
         不会让旧标记停留在非极位实体上（SOP §16c item 42 口径:
         无官方 Notes 支持的"跨回合扩张"即近似实现）
      4. 只有 1 只龙 → 它同时是最左与最右（只标记一次）
      5. 棋盘无龙 → 该场无标记（落空不报错）
      6. 只作用于本人棋盘（对手龙不被标记——owner 隔离）

    Test: test_batch_trinkets30.py — 绑定后最左/最右龙带
      `PERSIST_BONUS_ONLY`+`PERSIST_COMBAT_CHANGES`、中间龙不带 /
      真实 `run_combat`: 战内授予的 Taunt（Bonus Keyword）与 +atk
      保留、战内授予的 Poisonous（非 6 集）被清除（**正对照**: 未标记
      的龙两者都不保留）/ 位置变化后旧标记被清除、新极位被标记 /
      单龙双端 / 无龙落空 / 对手龙无标记 / 同 seed 两次结果一致

    Params: 无模板参数（CardDef.num(0..4) 全 None——"left and
            right-most" 是文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None
        source._tarecgosa_written = {}
        TarecgosaStickerScript._retarget(source, hero)

        def on_combat_restored(g, hero_a=None, hero_b=None, **kw):
            # 战后收敛: `run_combat` finally 的 `restore_state` 会把已撤销的
            # 标记复活 → 棋盘复原后立刻再 sweep 一次（2026-09-02 BUG-2;
            # 必须用 `combat_restored`——`combat_end` 只在 end_recruit_phase
            # 广播，直调 run_combat 的路径收不到）
            if hero in (hero_a, hero_b):
                TarecgosaStickerScript._retarget(source, hero)

        game.events.register(Listener(event="combat_restored", owner=source,
                                      callback=on_combat_restored))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        TarecgosaStickerScript._retarget(source, hero)
        return None

    @staticmethod
    def _retarget(source, hero) -> None:
        """**全板 sweep** → 标记当前最左/最右龙（幂等 + 位置跟随）。

        2026-09-02 对抗验证 BUG-2 修复:
        - `PERSIST_BONUS_ONLY` 是本人私有标记 → **棋盘上所有非极位龙一律清**
          （旧实现只清 `_tarecgosa_marked` 里的实体，而 `run_combat` 的
          `restore_state(snapshots[m])` 会把开战快照整份还原 → 已撤销的旧
          标记"复活"并让中间龙永久多持久化）
        - `PERSIST_COMBAT_CHANGES` 与 Dark Gift: Tarecgosa's Blessing / 金色
          Persistent Poet **共用通道** → 只清**本人写入且写入前不存在**的
          那些（`_tarecgosa_written[uuid] is False` 记账，跨 sweep 保留以便
          清掉被快照复活的标记）；他源写入（写入前已为 True）不动
        - **`combat_restored` 事件**也跑一次: 快照还原发生在 `run_combat`
          finally，SoC 的清理会被复活，故棋盘复原后立刻再收敛一次
        """
        written = dict(getattr(source, "_tarecgosa_written", {}) or {})
        dragons = [m for m in _living(hero) if m.race in _DRAGON_RACES]
        edges = []
        if dragons:
            edges = ([dragons[0]] if dragons[0] is dragons[-1]
                     else [dragons[0], dragons[-1]])
        edge_uuids = {m.uuid for m in edges}
        for m in list(hero.board):
            if m.uuid in edge_uuids:
                continue
            if m.has(GameTag.PERSIST_BONUS_ONLY):
                m.clear(GameTag.PERSIST_BONUS_ONLY)
            if written.get(m.uuid) is False \
                    and m.has(GameTag.PERSIST_COMBAT_CHANGES):
                m.clear(GameTag.PERSIST_COMBAT_CHANGES)
        for m in edges:
            if m.uuid not in written:
                written[m.uuid] = m.has(GameTag.PERSIST_COMBAT_CHANGES)
            m.set(GameTag.PERSIST_BONUS_ONLY, True)
            m.set(GameTag.PERSIST_COMBAT_CHANGES, True)
        source._tarecgosa_written = written

# ══════════════ BG32_MagicItem_891 Finley's Helmet ══════════════


class FinleysHelmetScript:
    """
    Natural language: [x]After the Tavern is
    <b>Refreshed</b>, give Murlocs
    in it +5/+5 and a random
    <b>Bonus Keyword</b>.

    Evidence: `data/bg_trinkets.json BG32_MagicItem_891`（lesser, cost 2,
    `spell_school=11`, `num(0..4)` 全 None——"+5/+5" 是**卡面字面量**，
    数据核实无模板占位符，按 SOP §3 在 Params 声明）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `tavern_refresh_complete`
         （hero=, auto=）——引擎在 `tavern_refresh` 的**全部监听器跑完后**
         广播（RULES §7.4.9），因此覆盖刷新窗口内入馆的实体且与监听器
         注册顺序无关
      2. "After the Tavern is Refreshed" 是被动句式（对照 Frigid Blossom 的
         "you Refresh"）→ **自动与手动刷新都算**（`auto` 不参与过滤）
      3. 每次刷新对本人酒馆内**每个** Murloc（race ∈ {MURLOC, ALL}）:
         `Buff(atk=5, health=5)`（永久、实体级——买入后带走，文本无
         "this turn"）+ `game.grant_bonus_keyword(m, game.random_bonus_keyword())`
         （6 集均匀随机，走 `game.rng`; 授予记录进 `GameTag.BONUS_KEYWORDS`）
      4. 绑定当回合**不**追溯当前酒馆（触发时机是"刷新之后"，绑定本身
         不是刷新）; 下一次刷新起生效
      5. 只作用于本人酒馆（hero 作用域监听过滤——对手刷新不 buff 本人，
         本人刷新不 buff 对手）
      6. 馆内无 Murloc → 该次刷新无副作用（落空不报错）

    Test: test_batch_trinkets30.py — 绑定后真实 `refresh_tavern` 注入
      Murloc → 恰 +5/+5 且获得**一枚** 6 集 Bonus Keyword
      （`BONUS_KEYWORDS` 记录 + 对应关键词 tag 置位）/ 同批非 Murloc
      不受影响（负对照）/ 自动刷新（auto=True）同样触发 / 未刷新时
      馆内 Murloc 无变化（触发时机正对照）/ 对手刷新不 buff 本人酒馆、
      本人刷新不 buff 对手（owner 隔离）/ 绑定后立即购买 Murloc 跨回合
      保留 buff 与关键词 / 同 seed 两局关键词序列一致

    Params: 无模板参数（"+5/+5" 为卡面字面量 `_FINLEY_ATK`/`_FINLEY_HEALTH`，
            36.2.2 数据无 {0}/{1} 占位符——运行核验 num(0..4) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_refresh_complete(g, hero=None, **kw):
            if hero is not source.controller:
                return
            targets = [e for e in source.controller.tavern
                       if getattr(e, "race", None) in _MURLOC_RACES]
            for e in targets:
                # 永久实体级附魔（买入后带走; 文本无 "this turn"）
                e.add_buff(EntityBuff(atk=_FINLEY_ATK,
                                      health=_FINLEY_HEALTH))
                _grant_random_bonus_keyword(g, e)

        game.events.register(Listener(
            event=TAVERN_REFRESH_COMPLETE, owner=source,
            callback=on_refresh_complete))
        return None


# ══════════════ BG32_MagicItem_892 Vibrant Bubble（+ Spellcraft 法术）══════════════


class VibrantBubbleScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Give a
    Murloc a random
    <b>Bonus Keyword</b>.

    Evidence: `data/bg_trinkets.json BG32_MagicItem_892`（lesser, cost 3,
    `spell_school=11`, `spellcraft_id=121139` → `BG32_MagicItem_892t`）。
    饰品版 Spellcraft 生成点 = `spellcraft.generate_for_hero`（扫描域
    含 `hero.trinkets`，RULES §6.13）; SPELLCRAFT tag 由 `create_entity`
    依 `CardDef.spellcraft_id` 数据驱动置位。

    Formal spec:
      1. on_bind: 文本**无** "Get a X" 子句（`evolution_card_id` 空）→
         不授予任何卡; 效果全部由 Spellcraft 法术本体承担
      2. 每回合开始由引擎生成 1 张 `BG32_MagicItem_892t` 入手（临时法术;
         未使用则回合结束丢弃——RULES §6.13）
      3. 实效见 `VibrantBubbleSpellScript`

    Test: test_batch_trinkets30.py — 绑定后真实 `_begin_recruit_for`
      生成恰好 1 张带 SPELLCRAFT tag 的 `BG32_MagicItem_892t` 入手 /
      无饰品对照不生成 / 未使用的法术在 `end_recruit_phase` 被丢弃

    Params: 无模板参数（效果量由法术脚本与随机关键词决定）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class VibrantBubbleSpellScript:
    """
    Natural language: [x]Give a Murloc a random
    <b>Bonus Keyword</b>.

    Evidence: `data/bg_cards.json BG32_MagicItem_892t`（card_type=5 法术,
    `spell_school=10`; num(0..4) 全 None）。Bonus Keyword 定义域 =
    官方 6 集（RULES §9.6）。

    Formal spec:
      1. needs_target=True（"Give a Murloc" 定向 → 引擎经
         `spell_target` 产生 PendingChoice 分流; 候选由
         `target_candidates` 给定）
      2. target_candidates = 本人棋盘上**存活**的 Murloc
         （race ∈ {MURLOC, ALL}——融合怪属鱼人）; 空候选 → 引擎落空
         （法术照常消耗，不抛错中断回合——SOP §16 item 15 口径）
      3. on_play: `game.grant_bonus_keyword(target, game.random_bonus_keyword())`
         ——6 集均匀随机（`game.rng`），授予记录进 `GameTag.BONUS_KEYWORDS`
         并广播 `bonus_keyword_granted`
      4. 只作用于本人棋盘（候选集限定本人——owner 隔离）

    Test: test_batch_trinkets30.py — 真实 `play_spell` 定向后目标获得
      **恰好一枚** 6 集关键词（tag 置位 + `BONUS_KEYWORDS` 记录）/
      候选集只含本人 Murloc（非鱼人/对手鱼人不可选）/ 空板时无可选目标
      （`len(options) == 0` → 落空）/ 同 seed 两局关键词序列一致

    Params: 无模板参数（关键词为随机，非数值）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in _living(hero) if m.race in _MURLOC_RACES]

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None or getattr(target, "dead", False):
            return None
        return GrantRandomBonusKeyword(target)


class GrantRandomBonusKeyword(Action):
    """施法 Action: 给目标授予一枚随机 Bonus Keyword（`game.rng` 6 集）。

    与 `GainKeyword` 同族的原子，但经 `game.grant_bonus_keyword` 记录
    `GameTag.BONUS_KEYWORDS`（"gains its Bonus Keywords" 类效果的数据源）
    并广播 `bonus_keyword_granted`。
    """

    def __init__(self, target) -> None:
        self.target = target

    def do(self, game: "Game") -> None:
        _grant_random_bonus_keyword(game, self.target)


# ══════════════ BG35_MagicItem_431t Thornspike Pauldron ══════════════


class ThornspikePauldronScript:
    """
    Natural language: [x]After you trigger a
    <b>Deathrattle</b>, your
    <b>Blood Gems</b> give an extra
    +{2}/+{4} until next combat.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_431t`（greater,
    cost 1, `spell_school=12`; `num(2)=2`、`num(4)=1`——NUM_5 已导出）。
    "until next combat" 的时点由官方 bug 报告佐证
    （us.forums.blizzard.com/en/hearthstone/t/160488: 本场战斗内仍生效、
    下一场战斗开始失效）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `deathrattle_trigger`
         （minion=）——`game.trigger_deathrattle` 与真实死亡路径都在
         **亡语效果结算之后**广播，恰是 "**After** you trigger a
         Deathrattle" 的时点（计数/广播同源，RULES §6.20）
      2. 条件 `minion.controller is 本人`（"you trigger" = 己方亡语;
         对手亡语不触发——owner 隔离）
      3. 触发: `ImproveBloodGems(hero, num(2), num(4))` 立即结算并
         **累计**记入 `source._pauldron_bonus`（同一回合多次亡语可叠加，
         文本无"一次"限定）
      4. 每场 `start_of_combat`（战斗开始）: 回退累计增量
         （`ImproveBloodGems(hero, -atk, -health)`）并清零累计——
         "until next combat" = 下一场战斗开始即失效
      5. 效果只改 hero 级 `BLOOD_GEM_BONUS_ATK/HEALTH`（读取点
         `actions/bloodgem._gem_values`——手牌打出与 `PlayBloodGems`
         两条路径统一生效）
      6. 绑定后未触发过亡语 → 无任何数值变化（落空不消耗）

    Test: test_batch_trinkets30.py — 真实 `_process_single_death` 触发
      己方亡语后血宝石面值恰 +num(2)/+num(4)（`_gem_values` 探针）/
      同回合第二次亡语再叠加 / 真实 `run_combat` 后开战前增量已回退
      （**正对照**: 战斗前快照确实 +/战后为 0）/ 对手亡语不触发 /
      绑定后未触发亡语时面值不变 / 两份副本各叠加一次（实例私有状态
      不串号——模式 35）

    Params: {2}=num(2)=2 {4}=num(4)=1（NUM_5 导出后的 `CardDef.num(4)`）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None
        atk = _num(game, source.card_id, 2)
        health = _num(game, source.card_id, 4)
        source._pauldron_atk = 0
        source._pauldron_health = 0

        def on_deathrattle(g, minion=None, **kw):
            if minion is None or minion.controller is not source.controller:
                return
            source._pauldron_atk += atk
            source._pauldron_health += health
            g.run_actions(ImproveBloodGems(source.controller, atk, health))

        game.events.register(Listener(event=DEATHRATTLE_TRIGGER,
                                      owner=source, callback=on_deathrattle))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        """下一场战斗开始: 回退上次累计的"until next combat"增量。"""
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        atk = getattr(source, "_pauldron_atk", 0)
        health = getattr(source, "_pauldron_health", 0)
        source._pauldron_atk = 0
        source._pauldron_health = 0
        if atk or health:
            game.run_actions(ImproveBloodGems(hero, -atk, -health))
        return None


# ══════════════ BG35_MagicItem_920 Bubble Crown ══════════════


class BubbleCrownScript:
    """
    Natural language: [x]Once you cast {1} spells,
    your Tavern spells give
    an extra +{2}/+{4}. <i>({0} left!)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_920`（lesser,
    `spell_school=11`; `num(0)=12`、`num(1)=12`、`num(2)=4`、
    `num(4)=4`——{4} = NUM_5，已由 `CardDef.num(4)` 导出）。
    文本第二段 `@...<i>(Done!)</i>` 是完成后替换文案（数据同实体双段）。
    消费点 = `racefx.tavern_spell_buff`（`TAVERN_SPELL_EXTRA_ATK/HEALTH`
    ——所有 give-stats 酒馆法术统一经该出口，RULES §7.4.13）。

    Formal spec:
      1. on_bind: 剩余计数 = `num(0)`（12）写在 source 实体属性上
         （实例私有——两份副本各自计数，模式 35）
      2. 注册持久监听器 `spell_resolving`（**per-cast**，RULES
         §7.4.10/§7.4.12——不得用每次只广播一次的 `card_played`）:
         每次施放（含双施/效果施法）计数 -1
      3. 计数归零的**那一次**施放（一次性——完成后不再重复结算）:
         `hero.TAVERN_SPELL_EXTRA_ATK += num(2)`、
         `hero.TAVERN_SPELL_EXTRA_HEALTH += num(4)`，并置完成标志
      4. 只对本人施法计数（`spell.controller is 本人`——对手施法不推进）
      5. 计数从**绑定时刻**开始（源商店展示的 "({0} left!)" 即 num(0)=12;
         绑定前施放的历史法术不计入——"Once you cast" 的窗口起于获得）
      6. 达成后本卡不再有任何效果（无过期、无回退——文本"Done!"）

    Test: test_batch_trinkets30.py — 绑定后连续 `spell_resolving` 到
      num(0)-1 次时 `TAVERN_SPELL_EXTRA_*` 仍为 0（正对照: 未完成时
      无加成）/ 第 num(0) 次后恰为 num(2)/num(4) / 再施放一次不重复
      加成（一次性）/ 真实 `play_spell`（池法术 give-stats）结算数值
      含额外加成 / 对手施法不推进本人计数 / 两份副本各自独立计数

    Params: {0}=num(0)=12 {1}=num(1)=12 {2}=num(2)=4 {4}=num(4)=4
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None
        source._bubble_crown_left = _num(game, source.card_id, 0)
        source._bubble_crown_done = False
        atk = _num(game, source.card_id, 2)
        health = _num(game, source.card_id, 4)

        def on_resolving(g, spell=None, **kw):
            if spell is None or spell.controller is not source.controller:
                return
            if getattr(source, "_bubble_crown_done", False):
                return
            left = getattr(source, "_bubble_crown_left", 0) - 1
            source._bubble_crown_left = left
            if left > 0:
                return
            source._bubble_crown_done = True
            source.controller.set(
                GameTag.TAVERN_SPELL_EXTRA_ATK,
                source.controller.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0)
                + atk)
            source.controller.set(
                GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                source.controller.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
                + health)

        game.events.register(Listener(event=SPELL_RESOLVING, owner=source,
                                      callback=on_resolving))
        return None


# ══════════════ BG35_MagicItem_834 Rylak Portrait ══════════════


class RylakPortraitScript:
    """
    Natural language: [x]Get a Rylak Metalhead.
    <b>Start of Combat:</b> Trigger
    your Rylak Metalheads'
    <b>Deathrattles</b>.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_834`（lesser, cost 4,
    `spell_school=11`, `evolution_card_id=98829` → `db.by_dbf` =
    `BG26_801` Rylak Metalhead，已由 batch_payload_minions 注册;
    金色 `BG26_801_G` 同族）。"Get a Rylak Metalhead" 无模板参数 →
    交付 **1** 张（文本字面量，`num(0..4)` 全 None）。

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(hero, source.card_id)`
         ——数据链解析 + 白板副本经 `pending_hand_add` 入手（满手排队;
         池外卡零池操作——RULES §7.4.6）
      2. 每场 `start_of_combat`: 对本人棋盘每只**存活** Rylak Metalhead
         （基础 id 判定，金色经 `TRIPLE_BASE_CARD_ID` 回落）
         `game.trigger_deathrattle(m, hero=本人)`——统一亡语入口
         （Titus `DEATHRATTLE_DOUBLER` 倍率、`dr_extra`/`dr_first` 配额、
         `COUNTER_DEATHRATTLES` 计数、`deathrattle_trigger` 广播全部
         同源，RULES §6.20）
      3. 亡语效果 = 载荷脚本本体（触发随机相邻随从的战吼）——交付物
         行为正确即 CORRECT（RULES §7.4.6）
      4. 棋盘无 Rylak → 落空不报错
      5. 只对本人随从（对手 Rylak 不触发——owner 隔离）

    Test: test_batch_trinkets30.py — 绑定后入手 1 张 `BG26_801`（满手
      进 `pending_hand_queue` 而非丢弃）/ 真实 `run_combat`: SoC 时
      己方 Rylak 的亡语触发（相邻随从战吼生效，探针 = 相邻随从属性
      变化）/ 无 Rylak 时无副作用 / 对手 Rylak 不被触发（owner 隔离）/
      金色 Rylak 同样被触发 / 同 seed 两次战斗结果一致

    Params: 无模板参数（"Get a Rylak Metalhead" = 1 张，文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None
        game.grant_trinket_related_card(hero, source.card_id)
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        for m in list(_living(hero)):
            if _matches_base(m, RYLAK):
                game.trigger_deathrattle(m, hero=hero)
        return None


# ══════════════ BG35_MagicItem_818 Mysterious Orb ══════════════


class MysteriousOrbScript:
    """
    Natural language: [x]Gain {0} Gold.
    Your next <b>Trinket</b> is a
    Lesser <b>Trinket</b>.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_818`（lesser,
    `spell_school=11`, `num(0)=10`）。读取点 = `_offer_trinkets`
    （`game.py` L3459: `hero._next_trinket_kind` 覆写档位并**消费即清**，
    RULES §7.4.13）。

    Formal spec:
      1. on_bind: `GainGold(hero, num(0))`——走 `Hero.gold` setter
         （99 上限截断、广播 `gold_gained`，RULES §7.4.13）
      2. 同次: `hero._next_trinket_kind = "lesser"`——**本人**下一次
         饰品商店档位被覆写为 Lesser（消费即清，不影响对手）
      3. 若本人已有其它覆写值 → 覆盖（文本"Your next Trinket"是单值语义，
         两份副本不叠加——Orb 的档位覆写本质是单槽状态）

    Test: test_batch_trinkets30.py — 绑定后金币恰 +num(0) / 覆写后
      `_offer_trinkets(hero, "greater")` 实际给出 Lesser 池成员
      （正对照: 无覆写时 greater 给出 Greater）/ 覆写被消费后
      `hero._next_trinket_kind is None` 且下一次恢复 greater / 对手
      英雄的覆写不受影响（owner 隔离）/ 金币上限截断（99 上限下
      实际增量小于 num(0)）

    Params: {0}=num(0)=10
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None
        amount = _num(game, source.card_id, 0)
        hero._next_trinket_kind = "lesser"
        return GainGold(hero, amount)


# ══════════════ BG32_MagicItem_933 Weary Portrait ══════════════


class WearyPortraitScript:
    """
    Natural language: [x]Get a Weary Mage. Your
    Weary Mages' <b>Spellcrafts</b>
    are permanent.

    ~~阻塞卡: BG32_MagicItem_933 Weary Portrait —— DEFERRED（不注册）。~~

    Status: **已迁出** — 本类为历史 DEFERRED 骨架，**不再引用**；
    实际实现见 `batch_trinkets37.WearyPortraitScript`（2026-09-14:
    载荷已注册 + `ReinvigorationScript` 加 `permanent_spellcraft` 关键词
    分支 + 引擎施放期回写）。保留仅为台账可追溯（不声明任何引擎钩子）。

    Evidence（数据侧，已逐条核实）:
      - `data/bg_trinkets.json BG32_MagicItem_933`（lesser, cost 5,
        `spell_school=11`）: `evolution_card_id=119921` → `db.by_dbf` =
        `BG31_830` Weary Mage（已由 batch_payload_minions 注册）;
        `BG31_830.spellcraft_id=120896` → `BG31_830t` Reinvigoration;
        金色 `BG31_830_G` → 120897 `BG31_830_Gt`。
      - `hsdata/CardDefs.xml BG31_830t`（enUS/deDE/zhCN 三语一致）:
        "Give a minion **+2/+2**. If it's a Naga, also give it Reborn
        *until next turn*." —— **属性条款本就是永久**，只有 Reborn 是
        临时（`BG31_830te` 附魔 "Reinvigorated +{0}/+{1}" 无 this-turn
        标记）。

    Dependency: 缺权威——同一句文案在库内有两种互斥实现。
      (a) **法术卡保留**: 同名 Dark Gift `BG36_MidGameEffect_000t62`
          "This minion's **Spellcrafts** are permanent"（同一措辞——
          单随从版）在引擎侧 = `game._permanent_spellcraft_uuids.add(uuid)`
          （game.py `_gift_sunken_persistence`），读取点
          `end_recruit_phase` L2339: 该来源生成的 Spellcraft 法术回合结束
          **不丢弃**。该集合是私有属性，**无公开 API**，也无"保留法术 +
          每回合照常生成是否去重"的裁定（`spellcraft.generate_for_hero`
          不去重 → 手牌随回合线性增长）。
      (b) **临时 buff 永久化**: `game.add_permanent_spellcraft_rule`
          （RULES §7.4.7a，Thaumaturgist Portrait `BG32_MagicItem_920`
          所用通道）只把该次施放目标的 `temporary` buff 翻永久。
          Reinvigoration 的 +2/+2 **本就永久**（见上），运行探针确认
          注册该规则后唯一可观察量（`spell.permanent_spellcraft=True`）
          对**行为**零差异（无 temporary buff 可翻转；Reborn 的
          "until next turn" 由 `BG31_830t` 载荷自己的 TURN_START 过期
          监听清除，不读 `permanent_spellcraft`）→ 注册即"注册但 no-op"
          第三态（SOP §12 item 2/14）。

    Implementation path: 解锁条件，按优先级——
      1. 若权威为 (a): 新增公开入口
         `game.make_spellcraft_permanent(minion)`（封装/取代私有
         `_permanent_spellcraft_uuids`，与 Sunken Persistence Dark Gift
         共用），并先裁定 `generate_for_hero` 对"手牌已持有该来源
         Spellcraft"是否跳过（否则每回合 +1 张的堆叠上限无权威）。
      2. 若权威为 (b): 需让 "until next turn" 子句可被永久化——在
         `permanent_spellcraft` 命中时抑制 `BG31_830t` 载荷注册的
         Reborn 过期监听（跨批改动 payload 脚本，须主线裁定）。
      3. 关联卡交付条款 `grant_trinket_related_card`（数据链 119921）
         本身无阻塞——解锁后即可直接接线。

    Test: test_batch_trinkets30.py — 结构性台账守卫（不注册 / 类无引擎
      钩子 / docstring 含 Status·Dependency·Implementation path）;
      数据侧断言: `evolution_card_id` 数据链 == BG31_830、其
      `spellcraft_id` == BG31_830t、`BG31_830t` 卡面无 "until next turn"
      属性条款（即 (b) 通道为空转）——作为阻塞证据的**可执行回归**。

    Params: 无模板参数（"Get a Weary Mage" = 1 张，文本字面量）
    """


# ══════════════ BG32_MagicItem_925 Hackerfin Portrait ══════════════


class HackerfinPortraitScript:
    """
    Natural language: Get a Hackerfin. At the end of each turn, trigger
    your Hackerfins' <b>Battlecries</b>.

    Evidence: `data/bg_trinkets.json BG32_MagicItem_925`（greater, cost 5,
    `spell_school=12`, `evolution_card_id=115848` → `db.by_dbf` =
    `BG31_148` Hackerfin，已由 batch_payload_minions 注册; 金色
    `BG31_148_G` 同族，其战吼由 `_per_trigger_def` 回落基础 CardDef +
    引擎 2 次触发体现）。重触发原子 = `actions.TriggerBattlecry`
    （Brann 式 `BATTLECRY_DOUBLER` 翻倍 / `COUNTER_BATTLECRIES` 计数 /
    `battlecry_trigger` 广播——与 Rylak 本体亡语同款先例）。

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(hero, source.card_id)`
         ——数据链解析 Hackerfin（池外卡零池操作; 满手排队）
      2. 每回合 `end_of_turn`（引擎对 `hero.trinkets` 逐个派发，
         RULES §7.4 §EoT 顺序含饰品）: 对本人棋盘每只**存活** Hackerfin
         （基础 id 判定，金色回落）执行 `TriggerBattlecry(m)`
         ——重触发其战吼（"Give your other minions +{0}/{1}，每个不同的
         Bonus Keyword 提升一次"），走完整战吼计数/广播/翻倍协议
      3. 棋盘无 Hackerfin → 落空不报错
      4. 只对本人随从（对手 Hackerfin 不触发——owner 隔离）

    Test: test_batch_trinkets30.py — 绑定后入手 1 张 `BG31_148`（满手进
      等待队列）/ 真实 `end_recruit_phase`: 己方其它随从获得战吼增量
      （探针 = 属性差，期望值由载荷 num(0)/num(1) 与棋盘不同 Bonus
      Keyword 数计算）/ 无 Hackerfin 时无副作用 / 对手 Hackerfin 不
      触发（owner 隔离）/ 金色 Hackerfin 战吼按 2× 总额结算 /
      `COUNTER_BATTLECRIES` 递增（重触发计入）/ 同 seed 结果一致

    Params: 无模板参数（"Get a Hackerfin" = 1 张，文本字面量；战吼数值
            在载荷脚本内由 `BG31_148.num(0)/num(1)` 提供）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None
        game.grant_trinket_related_card(hero, source.card_id)
        return None

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        triggers = [TriggerBattlecry(m) for m in list(_living(hero))
                    if _matches_base(m, HACKERFIN)]
        if triggers:
            return triggers
        return None


# ══════════════ 未注册（DEFERRED；台账见各类 docstring）══════════════


class MacawPortraitScript:
    """
    Natural language: Get a Monstrous Macaw. Your Monstrous Macaws also
    trigger your left-most <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets36（2026-09-13，RULES §7.4.17 条件化
    战吼第二消费者）; 原阻塞: requires 载荷"also"读取通道 + "left-most"
    口径权威

    Dependency:
      1. 载荷 `BGS_078` Monstrous Macaw（金色 `TB_BaconUps_135`）**已注册**
         （batch_payload_minions; 本体 Rally → `game.trigger_deathrattle`
         触发最左**亡语**）; 本卡的 "also trigger your left-most
         **Battlecry**" 由 `MonstrousMacawScript.rally` 读
         `FLAG_MACAW_EXTRA_BATTLECRY` 追加（RULES §7.4.17）。
      2. 原阻塞（2026-09-13 消除）: Rally 出口无读取点、`rally` 不广播
         独立事件。条件化战吼协议以"§7.4.16 家族开关 + 载荷消费点"
         落地，无需在饰品侧重放而复刻他卡私有逻辑。
      3. 原阻塞（2026-09-13 消除）: "left-most **Battlecry**" 的资格集
         由 32.2 官方论坛复现串（2025-05-15）棋盘 `M G x B y z` 裁定
         = 最左**带战吼**者（跳过中间的非战吼 x），与载荷本体
         "left-most Deathrattle" 同构。
    Implementation path: `MonstrousMacawScript.rally` 读
      `FLAG_MACAW_EXTRA_BATTLECRY` 并对最左带战吼者执行
      `TriggerBattlecry`（已落地，见 batch_trinkets36）。

    Params: 无模板参数（CardDef.num(0..4) 全 None）
    """


class SelflessPortraitScript:
    """
    Natural language: [x]Get a Selfless Hero.
    Your Selfless Heroes also
    trigger on <b>Battlecry</b>.

    Status: 已迁出 → batch_trinkets35（2026-09-13，RULES §7.4.17
    条件化战吼协议）; 原阻塞: requires 载荷"also"读取通道 + 读法权威

    Dependency:
      1. 载荷 `BG_OG_221` Selfless Hero（金色 `TB_BaconUps_014`）**已注册**
         （batch_payload_minions; 亡语 = 给随机友方随从圣盾），但
         "also trigger on **Battlecry**" 需要把该随从的 `deathrattle`
         钩子接到**战吼触发点**——payload 无读取点，且引擎无"随从被
         打出时触发其亡语"的统一入口。
      2. 单独在饰品侧重放该亡语 = 与"由 **Selfless Hero** 给出"的归属
         不符，也与其**未变的死亡路径**不一致（半实现 = 第三态，
         SOP §6b 禁止）。
      3. "also trigger on Battlecry" 的读法无权威: 战吼**结算时**触发
         自身亡语，还是战吼结算后触发? 该随从的亡语是否在死亡时仍照常
         触发（"also" 暗示叠加）? wiki 页面仅列 `BATTLECRY` tag，
         无 Notes 段落。
    Implementation path: 引擎增"战吼触发 → 随从自身附带效果"协议
      （如 `battlecry_trigger` 事件载荷已带 `minion=`，可由 payload
      监听并 `game.trigger_deathrattle(source)`）→ payload
      `SelflessHeroScript` 增 `battlecry` 出口读取 hero 级
      `selfless_extra_battlecry` 标记 → 本卡 on_bind 交付关联卡并写标记。
      阻塞卡（已消除）: BG32_MagicItem_804——2026-09-13 由
      batch_trinkets35 以 `battlecry_flag` 条件化战吼注册。

    Params: 无模板参数（CardDef.num(0..4) 全 None）
    """


# 2026-09-18: `BewitchedRibbonScript` 占位 DEFERRED 台账删除——
# `BG35_MagicItem_923` 已由 batch_trinkets31 注册（`Buff(persist=True)`
# 按来源跨战斗持久化原语，RULES §3.5 例外 4）。


class CorruptedTomeScript:
    """
    Natural language: Get a Triple Prize. Whenever you would get a Triple
    Reward, get a Triple Prize instead.

    Status: DEFERRED — requires 三连奖励替换钩子 + Darkmoon Prize 候选表

    Dependency:
      1. 替换读取点缺失: `game._grant_triple_reward`（`game.py` L1181）
         直接发放"发现 tier+1 随从"奖励，无覆写/替换协议
         （对照 `hero._next_trinket_kind` 的覆写模式——但三连奖励是
         **流程内联**发放，不是 offer）。
      2. "Triple Prize" 候选表缺失: Darkmoon Prize 是已退役的子系统
         （RULES §11.4），`data/` 无 tier→prize 映射、无卡池定义;
         关联卡 `evolution_card_id=130856` 指向的实体也未在 36.2.2 数据中
         提供可解析的奖品集。
      3. 文本核心是"**instead**"（替换而非追加）——近似为"额外给一张"
         会改变奖励总量（SOP §6b 禁止）。
    Implementation path: (a) `hero.triple_reward_override`（或
      `game.trinket_related_card` 同族的替换协议）读取点;
      (b) Darkmoon Prize 候选表恢复（数据层）+ `Discover` 协议接入;
      之后本卡 on_bind 交付 Triple Prize 并写替换标记。
      阻塞卡: BG35_MagicItem_812。

    Params: 无模板参数（"Get a Triple Prize" = 1 张，文本字面量;
            CardDef.num(0..4) 全 None）
    """


class SafetyPatchScript:
    """
    Natural language: Cast Ice Block.
    Gain {0} Gold.

    Status: DEFERRED — requires Secrets 子系统

    Dependency:
      1. "Cast Ice Block" = 施放奥秘 `TB_Bacon_Secrets_12`（数据核实
         `evolution_card_id=58512` → Ice Block）; 该卡**无脚本**、
         `hero.secrets` 容器不存在、引擎无"致命伤害预防"钩子
         （奥秘触发窗口 = 即将受到致命伤害时）。
      2. `Game.cast_spell_effect` 只处理普通法术的 `on_play`，对奥秘
         类（`card_type` 为法术但语义为"挂奥秘"）无挂载点。
      3. "Gain {0} Gold" 侧就绪（`num(0)=5`，`GainGold`）——但半实现
         = 第三态（SOP §6b 禁止）。
    Implementation path: 引擎实现 Secrets 子系统（`hero.secrets` +
      `cast_secret` + `hero_damage_taken` 前的致命伤害预防钩子 + 奥秘
      触发/消耗协议）→ 之后本卡 on_bind 挂载 Ice Block 并 `GainGold`。
      阻塞卡: BG35_MagicItem_820。
      Reference: ENGINE_BACKLOG §B7b。

    Params: {0}=num(0)=5（Gain Gold 侧; "Cast Ice Block" 无模板参数）
    """


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 30 批 8 张 + Spellcraft 法术 token 1 张（共 9 id）。

    DEFERRED 2 张（812 / 820）**不注册**（933 Weary Portrait 已由
    batch_trinkets37 注册，2026-09-14; 923 Bewitched Ribbon 已由
    batch_trinkets31 注册，2026-09-18——`Buff(persist=True)` 按来源跨
    战斗持久化原语）——逐张
    台账见各类 docstring（SOP §6b 二态铁律）。804 Selfless Portrait 已由
    batch_trinkets35、803 Macaw Portrait 已由 batch_trinkets36 注册
    （RULES §7.4.17 条件化战吼协议，2026-09-13）。
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (TARECGOSA_STICKER, TarecgosaStickerScript),
        (FINLEYS_HELMET, FinleysHelmetScript),
        (VIBRANT_BUBBLE, VibrantBubbleScript),
        (VIBRANT_BUBBLE_SPELL, VibrantBubbleSpellScript),
        (THORNSPIKE_PAULDRON, ThornspikePauldronScript),
        (BUBBLE_CROWN, BubbleCrownScript),
        (RYLAK_PORTRAIT, RylakPortraitScript),
        (MYSTERIOUS_ORB, MysteriousOrbScript),
        (HACKERFIN_PORTRAIT, HackerfinPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
