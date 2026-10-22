"""批次 trinkets26 — 饰品第二十六批（作业单 2026-09-14，16 张）。

台账来源: 派发作业单给定的 16 个 id（`docs/agents/TRINKET_LEDGER.md` 片
3/4/5 的交集）。16/16 在 `CardDB` 存在，16/16 在
`CardDB.trinket_offer_pool()` 中（运行核验——商店可提供成员）。本批
**注册集合**与既有 batch_trinkets1..23 互不相交（16 张在本批前均不在
`REGISTRY`；其中 823/834/920/921/922/362/373/380/841 曾在
batch_trinkets19/20/22 的 DEFERRED 台账中留档，本轮按新原语复评；
362/923 于 2026-09-18 由 `batch_trinkets31` 注册——见下行"已解冻"）。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码）；关联卡一律走
数据链 `CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6）；
随机/候选一律 `game.rng`；状态写在 hero 作用域 tag / source 实体属性 /
监听闭包（无 game 级 flag——SOP §12 item 9）。

**本轮新引擎原语复核**（作业单列出的"可能解冻"清单，逐张实测后裁决）:
  - `game.destroy_minion` + `minion_destroyed(hero=, minion=, source=,
    in_combat=)`（`hsrl2/game.py` / `hsrl2/events.py`，工作区当前 HEAD）
    → **解冻 `BG36_MagicItem_204` Plaguerunner Portrait**（"After you
    destroy a Plaguerunner outside combat, get a plain copy" 有了唯一
    观察点与施动者语义）。
  - `elemental_give_bonus(source)`（`hsrl2/actions/racefx.py`）**已有真实
    生产消费点**（`batch_deathrattle.DancingBarnstormerScript` BC/DR ×3
    与 `batch_econ_misc` 元素 give-stats 脚本各一处；`grep -rn
    "elemental_give_bonus(" hsrl2/` 命中调用而非仅定义）→
    `ELEMENTAL_EXTRA_ATK/HEALTH` 不再是"写 tag 无人读" →
    **解冻 `BG36_MagicItem_380` Amplifying Essence**。
    （旧台账 `ENGINE_BACKLOG §A10` / `batch_trinkets22`
    `AmplifyingEssenceScript` 的"零生产调用点"已过期；参考
    `batch_trinkets15.HeartOfTheForestScript` 的同构写法。）
  - `run_combat` 快照/恢复 `_magnetic_stack`（`hsrl2/game.py`
    `mag_snapshot` → finally 还原）→ **解冻 `BG36_MagicItem_841`
    Assembler Portrait**（SoC 吸附不再跨战斗无限累积）。"an Auto
    Assembler" 的池占返/副本来源按**已注册的同一文本族先例**
    `BG35_MagicItem_742` Accord-o-Tron Portrait（batch_trinkets18，
    关联卡 `BG26_147` 同样是**池随从**）裁定为"生成即吸附的实体、
    零池操作"——不再是未决问题。
  - `game.trigger_deathrattle` / `grant_combat_deathrattle` /
    `add_tier_aura` / `add_permanent_spellcraft_rule` /
    `add_tavern_entity` + `tavern_entity_added` / `cast_spell_effect`
    已逐个核对：本批 16 张中只有 `BG35_MagicItem_834` Rylak Portrait
    属 `trigger_deathrattle` 族，但其**载荷卡 `BG26_801` Rylak
    Metalhead 仍未注册**（`REGISTRY` 无 id；本批注册后 SoC 第二句
    100% 空转）→ 仍 DEFERRED（RULES §7.4.6 例外条款）。

注册 3 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG36_MagicItem_204 Plaguerunner Portrait — 数据链交付 Plaguerunner
      （池随从 T4，`grant_card_copy_to_hand` 占池）; 注册
      `minion_destroyed` 持久监听: 施动方 = 本人 ∧ `in_combat is False`
      ∧ 被摧毁者基础卡 id 为 Plaguerunner → `_plain_copy_for`（副本
      不占池、无附魔、金色源 → 金色副本，且**副本进施动方**手牌——
      被摧毁者可能是对手的 Plaguerunner）。

  BG36_MagicItem_380 Amplifying Essence — on_bind 永久
      `ELEMENTAL_EXTRA_ATK/HEALTH += num(1)/num(2)`（消费点
      `racefx.elemental_give_bonus`——元素 give-stats 统一出口）;
      `card_played` 计数本人打出的元素，每 num(0) 个"improve this"
      （增量 = 印面值 num(1)/num(2)），滚动复位（卡面 "({0} left!)"）。

  BG36_MagicItem_841 Assembler Portrait — SoC: 对本人棋盘每只存活
      Mech（race ∈ (MECH, ALL)）生成一个 Auto Assembler（数据链
      `evolution_card_id` 120025 → `BG32_172`）并
      `game.attach_magnetic` 吸附（属性/关键词并入 + 亡语栈叠）;
      生成体零池操作（Accord-o-Tron Portrait 先例）; 战斗级（
      `run_combat` 恢复 `_magnetic_stack` 与棋盘快照）。

DEFERRED 11 张（**不注册**；Status / Dependency / Implementation path
逐张见各类 docstring，禁止第三态——SOP §6b）
═══════════════════════════════════════════════════════════════════════
  - BG35_MagicItem_820 Safety Patch — "Cast Ice Block. Gain {0} Gold."
    Secrets 子系统缺失（`hero.secrets` + 致命伤害预防钩子;
    `TB_Bacon_Secrets_12` 无脚本）。
  - BG35_MagicItem_823 Timeworn Candelabra — Minor Timewarp 成员定义域
    缺失（XML 只有 `BACON_TIMEWARPED` 布尔且生成器未导出）。
  - BG35_MagicItem_834 Rylak Portrait — 载荷 `BG26_801` 未注册
    （SoC 第二句 100% 空转）。
  - BG35_MagicItem_920 Bubble Crown — `TAG_SCRIPT_DATA_NUM_5`（{4}）
    无数据通道（`CardDef.num(4)` 不存在）。
  - BG35_MagicItem_921 Cowrie Necklace — "give stats" 法术效果类别
    定义域缺失（`TAVERN_SPELL_COST_MOD` 是无条件 hero 级折扣）。
  - ~~BG35_MagicItem_922 Tide Raiser Portrait~~ **已解冻（2026-09-17，
    `batch_trinkets38` 注册）**: 原台账两条阻塞均为**过期陈述**——载荷
    `BG34_920`/`_G` 已由 `batch_payload_minions` 注册，且其亡语正是
    战斗内 `cast_spell_effect`（无条件广播 `spell_resolved`）。
  - ~~BG35_MagicItem_923 Bewitched Ribbon~~ **已解冻（2026-09-18，
    `batch_trinkets31` 注册）**: 原台账两条阻塞均为**过期陈述**——
    `CardDef.num(4)`（NUM_5 导出）已通（见 §A6b 订正），且
    "permanently" 的战斗内份量由 `Buff(persist=True)` 按来源跨战斗
    持久化精确表达（RULES §3.5 例外 4; 卡面 + 官方 S14 表双权威）。
  - BG35_MagicItem_930 Warband Whistle — "自定义内容的免费刷新"协议
    缺失（`refresh_tavern` 只能按池加权抽取整馆）。
  - BG36_MagicItem_214 Insurrectionist's Blade — 无"攻击外触发 Rally"
    协议，且被触发 Rally 的 ctx target 语义无权威（wiki 无 Notes）。
  - BG36_MagicItem_216 Eternal Portrait — "按卡家族的光环"读取点缺失
    （只有 `race_auras` / `tier_auras`）；入场即 buff 近似被 SOP §16b
    item 32 禁止。
  - BG36_MagicItem_308 Trailblazer Sticker — `CHOOSE_BOTH` 读取点只有
    棋盘随从（`Game.play_minion` / `play_spell`），饰品实体不在棋盘，
    写 hero 级 tag 无读取方（W3 空转标记）。
  - ~~BG36_MagicItem_362 Cyclist Portrait~~ **已解冻（2026-09-18，
    `batch_trinkets31` 注册）**: 同一原语 + 家族规则读取点
    `Game.add_persist_source` / `persist_source_id`（载荷
    `ShowyCyclistScript.deathrattle` 命中即标 `persist=True`）。
  - BG36_MagicItem_373 Multilayered Shield — 动态
    `TAVERN_SPELL_EXTRA` 提供者缺失（`tavern_spell_buff` 只读静态
    hero tag）。

关联卡台账（RULES §7.4.6——关联卡自身脚本状态不阻塞本批 CORRECT）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（`evolution_card_id` → `db.by_dbf`） | 脚本状态 |
  |------|--------------------------------------------|-----------|
  | BG36_MagicItem_204 | 126451 → BG34_690 Plaguerunner (T4, 池) | **已注册**
  |                     |                                          | （batch_deathrattle2.
  |                     |                                          | PlaguerunnerScript） |
  | BG36_MagicItem_841 | 120025 → BG32_172 Auto Assembler (T4, 池, | **已注册**
  |                     | Magnetic + Deathrattle)                 | （batch_magnetic.
  |                     |                                          | AutoAssemblerScript） |
  | BG36_MagicItem_380 | 无（本卡不交付卡牌）                     | — |
  其余 DEFERRED 卡的关联卡台账见各自 docstring（834 → BG26_801
  未注册; 820 → TB_Bacon_Secrets_12 无脚本）;
  纯修饰型（920/921/930/214/216/308/373/823）无关联卡交付。

接线审计读取点（W1/W2/W3 核对）
═══════════════════════════════════════════════════════════════════════
  饰品仅分发 `on_bind` / `start_of_turn` / `end_of_turn` /
  `start_of_combat`（W1 白名单）。监听事件全部有引擎生产点:
  `card_played`（`Game._run_play_effects` 随从路径 / `_finish_play_spell`
  法术路径 / 磁力吸附路径）、`minion_destroyed`
  （`Game.destroy_minion` 唯一入口）。公开 API 使用: 关联卡交付走
  `game.grant_trinket_related_card` / `game.grant_card_copy_to_hand`;
  "plain copy" 由模块内 `_plain_copy_for` 生成（与引擎
  `hsrl2.game._plain_copy_to_hand` 同语义、副本归属显式 = 施动方）;
  无 `game._x`/`hero._x` 私有标记写入（W3）。`ELEMENTAL_EXTRA_*`
  写入有生产消费点（`racefx.elemental_give_bonus`）。
"""

from __future__ import annotations

from typing import List, Optional

from hsrl2.events import CARD_PLAYED, MINION_DESTROYED, Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# ── 本批卡 id（CardDB 按名核实，禁止凭记忆写） ──
PLAGUERUNNER_PORTRAIT = "BG36_MagicItem_204"   # Plaguerunner Portrait (G)
AMPLIFYING_ESSENCE = "BG36_MagicItem_380"      # Amplifying Essence (G)
ASSEMBLER_PORTRAIT = "BG36_MagicItem_841"      # Assembler Portrait (G)
# DEFERRED（不注册；台账守卫见测试）
SAFETY_PATCH = "BG35_MagicItem_820"
TIMEWORN_CANDELABRA = "BG35_MagicItem_823"
RYLAK_PORTRAIT = "BG35_MagicItem_834"
BUBBLE_CROWN = "BG35_MagicItem_920"
COWRIE_NECKLACE = "BG35_MagicItem_921"
TIDE_RAISER_PORTRAIT = "BG35_MagicItem_922"
BEWITCHED_RIBBON = "BG35_MagicItem_923"
WARBAND_WHISTLE = "BG35_MagicItem_930"
INSURRECTIONISTS_BLADE = "BG36_MagicItem_214"
ETERNAL_PORTRAIT = "BG36_MagicItem_216"
TRAILBLAZER_STICKER = "BG36_MagicItem_308"
CYCLIST_PORTRAIT = "BG36_MagicItem_362"
MULTILAYERED_SHIELD = "BG36_MagicItem_373"

# ── 关联卡 id（数据链 `evolution_card_id` → `CardDB.by_dbf`；仅用于
#    标识判定与测试断言，脚本运行时一律经 `trinket_related_card` 解析） ──
PLAGUERUNNER = "BG34_690"       # 池随从 T4（dbf 126451）
AUTO_ASSEMBLER = "BG32_172"     # 池随从 T4（dbf 120025）

# 匹配族（Amalgam 视为全种族，RULES §6.18/§8）
_MECH_RACES = (Race.MECH, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)


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
    """实体的**基础**卡 id（金色 → TRIPLE_BASE_CARD_ID，缺省 card_id）。"""
    if entity is None:
        return None
    base = entity.get(GameTag.TRIPLE_BASE_CARD_ID, None)
    return base or entity.card_id


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _plain_copy_for(game, hero, source_minion) -> bool:
    """给 **hero**（而非死者的控制者）一份 plain copy。

    与引擎 `hsrl2.game._plain_copy_to_hand` 同语义（无附魔、金色源 →
    金色副本、`pending_hand_add` 满手排队、**不占池**——RULES §2.3
    "效果生成的副本不占池"），但副本**归属显式指定**：Plaguerunner
    Portrait 的文本是 "After **you** destroy a Plaguerunner … **you**
    get a plain copy"——被摧毁者可能是**对手的** Plaguerunner（Destroy
    类效果可指向敌方），副本必须进**施动方**手牌而不是死者的控制者
    （引擎 helper 取 `m.controller`，在敌方目标场景会发错人）。
    返回 True = 副本已产生（含入等待队列）。
    """
    if source_minion is None:
        return False
    if source_minion.is_golden:
        base_id = (source_minion.get(GameTag.TRIPLE_BASE_CARD_ID, None)
                   or source_minion.card_id)
        copy = game.create_minion(base_id, controller=hero, golden=True)
    else:
        copy = game.create_minion(source_minion.card_id, controller=hero)
    if copy is None:
        return False
    game.pending_hand_add(hero, copy)
    return True


# ══════════════ BG36_MagicItem_204 Plaguerunner Portrait ══════════════


class PlaguerunnerPortraitScript:
    """
    Natural language: [x]Get a Plaguerunner. After you destroy a
    Plaguerunner outside combat, get a plain copy.

    Formal spec:
      1. on_bind: 数据链交付关联卡——`game.trinket_related_card(本饰品)`
         的 `evolution_card_id`(126451) → `BG34_690` Plaguerunner（池
         随从 T4）→ `game.grant_trinket_related_card(hero, 本饰品)`：
         占池 1 份，池中无副本 → **本次获取**落空（RULES
         §2.3/§2.4/§7.4.6）; 白板副本、满手入等待队列（RULES §3.3）。
         交付失败**不**影响第二条款：无论如何都注册监听（"Get a X" 的
         落空只作用于本次交付，不是整卡门槛）。
      2. 注册 `minion_destroyed` 持久监听（owner=饰品; 引擎
         `Game.destroy_minion` **唯一**广播点，载荷 hero=/minion=/
         source=/in_combat=）:
           a) 施动方过滤 `hero is 本人`（"**you** destroy"——对手摧毁
              不触发）
           b) 战斗外过滤 `in_combat is False`（"outside combat"——
              战斗内摧毁由 `run_combat` 路径处理，本入口只覆盖招募期
              效果摧毁）
           c) 身份过滤: 被摧毁者 `_base_card_id` == `BG34_690`
              （金色 `BG34_690_G` 亦属 Plaguerunner 家族——RULES §2.3
              金色=独立 def 但同名）
      3. 触发: `_plain_copy_for(game, hero, minion)`——plain copy 进
         **施动方**手牌（文本 "**you** get a plain copy"）: 无附魔
         （plain）、金色源 → 金色副本（`TRIPLE_BASE_CARD_ID` +
         `golden=True`）、**不占池**（RULES §2.3 "效果生成的副本不
         占池"）、满手入等待队列。语义与引擎
         `game._plain_copy_to_hand` 一致，但副本归属显式 = 施动方
         （被摧毁者可能是**对手的** Plaguerunner——引擎 helper 取
         `m.controller` 会发错人；本地 helper 见模块内 docstring）。
      4. 触发窗口在死亡链**之后**（`destroy_minion` 先 `check_deaths`
         再广播）——此时 `minion.card_id`/`is_golden` 仍可读，副本按
         死者身份生成。
      5. 只作用于本人（施动方）; 副本条款: 两份副本各注册监听 → 每次
         摧毁各得一份 plain copy。

    Test: test_batch_trinkets26.py — 绑定后手牌出现 Plaguerunner（池
      -1，数据链）; 招募期 `destroy_minion(本人, Plaguerunner)` → 手牌
      再 +1 张（属性 = 基础 CardDef，无附魔）且被摧毁者确实离场 /
      **池守恒**（摧毁回池 1 份、副本不占池）; 正对照: 无饰品时同操作
      手牌不变 / 摧毁**非** Plaguerunner 不触发 / `in_combat=True` 时
      不触发 / 对手施动（hero=对手）不触发 / **本人摧毁对手的
      Plaguerunner → 副本进本人手牌（不进对手手牌）** / 金色
      Plaguerunner 被摧毁 → 金色 plain copy（独立卡定义，非数值×2）/
      两份副本各给一份 / 真实 `end_recruit_phase` 招募回合内摧毁同样
      触发（跨回合持久）

    Params: 无模板参数（BG36_MagicItem_204 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # 第一条款: 数据链交付关联卡（池随从 → 占池; 池空落空由入口处理）
        game.grant_trinket_related_card(h, source.card_id)

        def cond(hero=None, in_combat=None, **kw):
            return hero is h and not in_combat

        def on_destroyed(g, minion=None, **kw):
            if minion is None:
                return
            if _base_card_id(minion) != PLAGUERUNNER:
                return
            _plain_copy_for(g, h, minion)

        game.events.register(Listener(event=MINION_DESTROYED, owner=source,
                                      callback=on_destroyed, condition=cond))
        return None


# ══════════════ BG36_MagicItem_380 Amplifying Essence ══════════════


class AmplifyingEssenceScript:
    """
    Natural language: [x]Your Elementals give an extra +{1}/+{2}. After
    you play {0} Elementals, improve this. <i>({0} left!)</i>

    Evidence: wiki.gg `Battlegrounds/Amplifying_Essence`（Greater,
    cost 4, dbfId 133719, Elemental-related / Ongoing effect /
    Summoning-related）无 Notes 反证; 印面值 +1/+1 与 num(1)=num(2)=1
    一致。**消费点已就绪**: `hsrl2.actions.racefx.elemental_give_bonus`
    有真实生产调用点（`batch_deathrattle.DancingBarnstormerScript`
    BC/DR 三处 + `batch_econ_misc` 元素 give-stats 一处）——旧台账
    "写 tag 无人读"（ENGINE_BACKLOG §A10 / batch_trinkets22）已过期。

    Formal spec:
      1. on_bind: 本人 `ELEMENTAL_EXTRA_ATK += num(1)` /
         `ELEMENTAL_EXTRA_HEALTH += num(2)`（hero 作用域 tag，SOP §12
         item 9）。消费点 = `racefx.elemental_give_bonus(source)`:
         所有"元素 give-stats"效果在构造 Buff 时读取该 tag，且**仅当
         给予者本身是 ELEMENTAL/ALL** 才叠加（非元素给予者不吃加成——
         Champion of Sargeras 族）。
      2. on_bind 注册 `card_played` 持久监听（owner=饰品）: `card` 为
         **本人** Minion 且 `race ∈ (ELEMENTAL, ALL)` → 计数 +1;
         达 num(0) → 计数清零并**再**叠加同额 num(1)/num(2)
         （"improve this" 增量 = 印面值; 同族已验收先例
         `batch_trinkets15.HeartOfTheForestScript` "After you cast 5
         Tavern spells, improve this"——本卡 XML 隐藏
         TAG_SCRIPT_DATA_NUM_4/5=1/1 与 num(1)/num(2) 相等但未导出，
         故运行时以 num(1)/num(2) 为权威）。
         **事件选择**: 用 `card_played`（play 域，RULES §7.4.10——
         "After you play N Elementals" 的计数域）而非引擎 2026-09-02
         新增的 `elemental_played`：后者由 `_run_play_effects` 单点
         广播（不含 `play_minion` 的磁力吸附打出路径），而磁力吸附同样
         是"打出"（`play_minion` 在该路径 fire `card_played`）。两者对
         常规打出等价; 本卡不消费 `COUNTER_ELEMENTALS_PLAYED`（那是
         "this game 累计"语义，无滚动复位）。
      3. 滚动计数（卡面 "({0} left!)" 每次改善复位）、跨回合累积
         （文本无 "this turn"）；计数存于监听闭包（饰品离场即注销）。
      4. 只作用于本人: 对手打元素不计数、对手的 `ELEMENTAL_EXTRA_*`
         不变; 非随从 / 非元素（含 NONE）不计入（不消耗计数——落空不
         消耗）。
      5. 副本条款: 两份副本各有独立 on_bind + 监听 → 基准与每次改善
         各叠加两份。

    Test: test_batch_trinkets26.py — 绑定后 tag == num(1)/num(2) 且
      对手 tag 为 0 / 真实打出元素后 `Dancing Barnstormer` 的战吼
      give-stats 数额 = 其 num(0)+num(1)（元素给予者吃加成; 正对照:
      无饰品时 = num(0)）/ **非元素**给予者（Champion of Sargeras）
      同样场景**不吃**加成（= 其 num(0)）/ 打 num(0)-1 个元素 tag
      不变、第 num(0) 个 → 再 +num(1)/num(2)（滚动: 再满 num(0) 个
      再提升）/ 中间插入非元素不消耗计数 / 对手打元素本人 tag 不变
      （owner 隔离）/ 两份副本叠加 / 真实 `end_recruit_phase` 后监听
      仍在（跨回合持久）

    Params: {0}=num(0)=5 {1}=num(1)=1 {2}=num(2)=1（BG36_MagicItem_380）
    """

    @staticmethod
    def _improve(hero, game, source) -> None:
        hero.set(GameTag.ELEMENTAL_EXTRA_ATK,
                 hero.get(GameTag.ELEMENTAL_EXTRA_ATK, 0)
                 + _num(game, source.card_id, 1))
        hero.set(GameTag.ELEMENTAL_EXTRA_HEALTH,
                 hero.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0)
                 + _num(game, source.card_id, 2))

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        AmplifyingEssenceScript._improve(h, game, source)
        state = {"n": 0}

        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not h:
                return
            if card.race not in _ELEMENTAL_RACES:
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            AmplifyingEssenceScript._improve(h, g, source)

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════ BG36_MagicItem_841 Assembler Portrait ══════════════


class AssemblerPortraitScript:
    """
    Natural language: [x]<b>Start of Combat:</b> <b>Magnetize</b> an
    Auto Assembler to all your Mechs.

    Evidence: wiki.gg `Battlegrounds/Assembler_Portrait`（Greater,
    cost 3, dbfId 133069; Wiki tags `START_OF_COMBAT` + `MAGNETIC`,
    Related cards "Generates BG32_172 Auto Assembler"）无 Notes 反证。

    Formal spec:
      1. `start_of_combat`（饰品 SoC 钩子; 引擎分发顺序 饰品→奖励→
         随从→手牌，`combat.py::_start_of_combat_phase`）: 目标 = 本人
         棋盘**存活** Mech（race ∈ (MECH, ALL)——Amalgam 视为机械，
         RULES §6.18），按左→右顺序; 无 Mech → 落空（不创建实体、不
         消耗任何资源）。
      2. 每只目标: `game.create_minion(关联卡 id)`（数据链
         `evolution_card_id` 120025 → `BG32_172` Auto Assembler，T4
         Magnetic + Deathrattle）→ `game.attach_magnetic(hero, 生成体,
         host)`——按实体当前属性并入攻/生命、关键词并入（MAGNETIC/
         DEATHRATTLE 等）、亡语**栈叠**（宿主死亡时按吸附顺序触发;
         `game.run_script_hook` 的磁力合并契约），并广播 `magnetized`
         （RULES §6.14）。
      3. **池记账 = 零池操作**: 文本是 "Magnetize **an** Auto
         Assembler"（生成一个直接吸附的实体），不是 "Get"（入手占池）。
         同一文本族已验收先例: `BG35_MagicItem_742` Accord-o-Tron
         Portrait "At the end of each turn, Magnetize an Accord-o-Tron
         to your left- and right-most Mechs"（batch_trinkets18; 其关联
         卡 `BG26_147` 同样是**池随从**，裁定零池操作），以及
         `batch_consume._make_satellite` "Magnetize a Satellite"。
         故多只 Mech 也不会耗尽随从池。
      4. **战斗级**: `run_combat` 在快照时记录 `_magnetic_stack` 并在
         finally 还原，宿主属性亦随棋盘快照回滚（RULES §3.5 战斗变化
         不延续）→ 每场战斗各自重新吸附，亡语栈不跨战斗累积。
      5. 只作用于本人棋盘（对手 Mech 不变）; 副本条款: 两份副本各注册
         SoC → 每只 Mech 每次吸附两份。

    Test: test_batch_trinkets26.py — 真实 `run_combat` 内探针（
      `start_of_combat` 事件在 SoC 钩子后广播）: 本人 2 只 Mech 各
      +Auto Assembler 攻/生命、`_magnetic_stack` 各 +1、亡语栈并入
      （宿主 `DEATHRATTLE` tag 置位）; 非 Mech 随从与**对手** Mech 不变
      / 同一 setup 无饰品（正对照）全无变化 / 战斗结束 `_magnetic_stack`
      复原且宿主属性回滚（战斗级）/ 连续两场战斗各吸附一次（不累积）/
      随从池 Auto Assembler 余量不变（零池操作）/ 空 Mech 棋盘落空 /
      真实 `end_recruit_phase` 触发 SoC / 两份副本 → 每次吸附两份

    Params: 无模板参数（BG36_MagicItem_841 num(0..3) 全 None; 生成体
            属性来自 BG32_172 CardDef）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        mechs = [m for m in _living(h) if m.race in _MECH_RACES]
        if not mechs:
            return None
        rel = game.trinket_related_card(source.card_id)
        if rel is None:
            return None
        for host in mechs:
            asm = game.create_minion(rel.id, controller=h)
            if asm is None:
                continue
            game.attach_magnetic(h, asm, host)
        return None


# ══════════════ DEFERRED（不注册） ══════════════


class SafetyPatchScript:
    """
    Natural language: Cast Ice Block. Gain {0} Gold.

    Status: DEFERRED — requires Secrets 子系统

    Dependency:
      1. 引擎**无任何 secrets 基础设施**（`grep -rn "SECRET" hsrl2/`
         零命中: 无 `hero.secrets`、无"致命伤害预防"钩子、无秘密触发
         阶段）。关联卡 `TB_Bacon_Secrets_12` Ice Block（dbf 58512）
         `REGISTRY` 无脚本、`CardDef` 仅文本——"Cast Ice Block" 无
         可结算的行为（`cast_spell_effect` 对该 id 会因
         `card_type`/脚本缺失而空转）。
      2. "Gain {0} Gold"（num(0)=5 已就绪）单独可交付，但半实现 =
         第三态（SOP §6b 禁止）。
    Implementation path: 主线新增 Secrets 子系统（`hero.secrets` 列表
      + 秘密实体脚本协议 + 战败致命伤害前的预防窗口
      `game._secret_fatal_prevent()`），迁移 `TB_Bacon_Secrets_12`
      （"Secret: When your hero takes fatal damage, prevent it and
      become Immune this turn"）; 随后本卡 on_bind = `[GainGold(h,
      num(0)), cast_spell_effect(h, 关联卡)]`（关联卡经数据链解析）。
      阻塞卡: BG35_MagicItem_820（同族 secrets 卡全部待此原语）。
    Reference: docs/agents/ENGINE_BACKLOG.md §B7b。

    Test: 不注册（DEFERRED）——台账守卫见
      test_batch_trinkets26.py::TestRegistryLedger（确认 id 在 CardDB
      存在但不在 REGISTRY）。

    Params: {0}=num(0)=5（BG35_MagicItem_820） {0} 对应的 "Cast Ice
            Block" 载荷无脚本（见 Dependency）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TimewornCandelabraScript:
    """
    Natural language: <b>Discover</b> a 2-Cost minion from the Minor
    <b>Timewarp</b>.

    Status: DEFERRED — requires Minor Timewarp 成员定义域

    Dependency:
      1. XML 仅有 `BACON_TIMEWARPED`(4503) 单一"时空扭曲过"布尔标记，
         生成器**无读取点**（`data/bg_cards.json` 零 `timewarp` 字段，
         `grep -i timewarp` 无命中）→ 无法把"Minor Timewarp"与
         "Major Timewarp"分开，也无法确定其成员集。
      2. wiki 页 `Battlegrounds/Timeworn_Candelabra_(Lesser)` 无 Notes /
         Related cards 段（2026-09-14 复读; 仅
         `BACON_TIMEWARP_TOOLTIP` / `DISCOVER` / Timewarp-related 标签）
         → 无权威候选集（SOP §6b 第 4 步: 禁止按卡名/档位猜测）。
    Implementation path: 生成器导出 Minor Timewarp 成员标记（如
      `BACON_TIMEWARP_TOOLTIP`(4517) 或专用 subset 字段）→ 候选 =
      该集合内 `cost == 2` 的随从（`BACON_SHOW_COST_ON_DISCOVER`(3456)
      证实按费用展示）→ 3 选 1 `Discover`（引擎预留语义）。阻塞卡:
      BG35_MagicItem_823（+ BG34_Giant_605）。
    Reference: docs/agents/ENGINE_BACKLOG.md §B7c。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（"2-Cost" 为文本字面量; CardDef num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class RylakPortraitScript:
    """
    Natural language: [x]Get a Rylak Metalhead. <b>Start of Combat:</b>
    Trigger your Rylak Metalheads' <b>Deathrattles</b>.

    Status: DEFERRED — requires 载荷卡 BG26_801 迁移（RULES §7.4.6
      例外条款: 本卡第二句**依赖被授予卡的行为**）

    Dependency:
      1. `game.trigger_deathrattle`（RULES §6.20 统一入口——Titus
         `DEATHRATTLE_DOUBLER` / `dr_extra` / `dr_first` / 计数 / 事件
         全生效）**已落地**，本卡的触发协议本身不再缺失。
      2. 但关联卡 `BG26_801` Rylak Metalhead（"Taunt. Deathrattle:
         Trigger the Battlecry of an adjacent minion."，非池卡）及其
         金色 `BG26_801_G` **仍未注册**（`REGISTRY` 运行核验无 id）→
         SoC 对每个 Rylak Metalhead 调 `trigger_deathrattle` 只会走
         `run_script_hook(m, "deathrattle")` 的空钩子（0 行为），整卡
         第二句 100% 空转（注册即 no-op = 禁止的第三态，SOP §12
         item 14）。
    Implementation path: 迁移 `BG26_801`/`BG26_801_G` 的亡语
      （"Trigger the Battlecry of an adjacent minion" ——`TriggerBattlecry`
      / `BATTLECRY_TRIGGER` 协议已就绪）→ 随后本卡 on_bind 交付关联卡
      （`trinket_related_card` → 非池卡零池操作）、`start_of_combat`
      对本人棋盘每个 Rylak Metalhead（`_base_card_id` ∈ 家族）调
      `game.trigger_deathrattle(m, hero=h)`。阻塞卡: BG35_MagicItem_834。
    Reference: RULES §6.20（统一亡语入口）; batch_trinkets19
      `RylakPortraitScript` 原台账。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（关联卡经 `CardDef.evolution_card_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BubbleCrownScript:
    """
    Natural language: [x]Once you cast {1} spells, your Tavern spells
    give an extra +{2}/+{4}. <i>({0} left!)</i>

    Status: DEFERRED — requires `TAG_SCRIPT_DATA_NUM_5` 数据导出

    Dependency:
      1. 36.2.2 XML（dbf 130898）: `TAG_SCRIPT_DATA_NUM_1=12`、
         `NUM_2=12`、`NUM_3=4`、**`NUM_5=4`**（enumID 2920）——文本
         `{4}` 映射 NUM_5，而 `CardDef` 仍只导出 `NUM_1..4`
         （`tools/generate_bg_data.py` 的 TAG 表只含 TAG_SCRIPT_DATA_
         NUM_4=2919; `hsrl2/defs.py::CardDef.num` 仅支持 index 0..3）
         → `num(3) is None`，硬编码违反"数值一律 CardDef.num()"纪律
         （SOP §16b item 25; batch_trinkets17 `ThornspikePauldronScript`
         同款缺口的既有 DEFERRED）。
      2. 附带待裁定: "cast spells" 口径（全法术 vs
         `TAVERN_SPELLS_CAST_THIS_GAME` 仅池法术）——按 RULES §7.4.10
         per-cast 语义应监听 `spell_resolving`，但阈值计数是否含
         Spellcraft/血宝石无权威。
    Implementation path: 生成器导出 `script_data_num_5`（+
      `CardDef.num(4)`）→ on_bind 注册 `spell_resolving` 计数，达
      num(1)=12 时一次性写 `hero.TAVERN_SPELL_EXTRA_ATK/HEALTH +=
      (num(2), num(4))`（消费点 `racefx.tavern_spell_buff` 已就绪、
      所有 give-stats 酒馆法术已统一经该出口）。阻塞卡:
      BG35_MagicItem_920 / BG35_MagicItem_923 / BG35_MagicItem_431t。
    Reference: docs/agents/ENGINE_BACKLOG.md §A6b。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=12 {1}=num(1)=12 {2}=num(2)=4（可读）
            {4}=NUM_5=4（**当前无数据通道**）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class CowrieNecklaceScript:
    """
    Natural language: Tavern spells that give stats cost (2) less.

    Status: DEFERRED — requires "give stats" 法术效果类别定义域

    Dependency:
      1. `GameTag.TAVERN_SPELL_COST_MOD`（RULES §7.4.5）是 hero 级
         **无条件**持久折扣（`buy_from_tavern` 只按 tag 数值递减），
         没有"仅对 give-stats 法术"的分类读取点。
      2. 数据层无任何"给属性"标记: 对照 36.2.2 XML，give-stats 的池
         法术（如 `BG34_444` / `BG35_951`）与不 give-stats 的池法术
         标签集无差异（本批复核确认）→ 按卡面文本解析法术文本属近似
         （SOP §6b 禁止）。
    Implementation path: 引擎/数据层为"give stats"池法术标注类别
      （生成器导出 `gives_stats` 位，判定依据 = 法术脚本是否经
      `racefx.tavern_spell_buff` 构造 Buff）→ `buy_from_tavern` 增按
      类别折扣读取点（如 `hero.TAVERN_SPELL_COST_MOD_STATS`）→
      on_bind 写入（"cost (2) less" 为文本字面量——CardDef num 全
      None，按 SOP §3 在 Params 声明）。阻塞卡: BG35_MagicItem_921。
    Reference: docs/agents/ENGINE_BACKLOG.md §B7f; batch_trinkets8 模块
      docstring 就同一张卡的既有备案（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（"cost (2) less" 为文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# BG35_MagicItem_922 Tide Raiser Portrait 已由 batch_trinkets38 注册
# （2026-09-17: 载荷 BG34_920 已注册 + `cast_spell_effect` 无条件广播
#  `spell_resolved`，战斗上下文经 `game.in_combat`）→ 占位 DEFERRED 类删除。


# 2026-09-18: `BewitchedRibbonScript` 占位 DEFERRED 台账删除——已由 batch_trinkets31
# 注册（`Buff(persist=True)` 按来源跨战斗持久化原语，RULES §3.5 例外 4）。


class WarbandWhistleScript:
    """
    Natural language: [x]Gain a free <b>Refresh</b> that contains plain
    copies of minions in your warband.

    Status: DEFERRED — requires "自定义内容的刷新"协议

    Dependency:
      1. `Game.refresh_tavern` 只能按 `minion_pool.draw_tavern` 加权抽取
         整馆（种族/tier/展示数可限定，**内容**不可指定）;
         `hero.FREE_REFRESH_REMAINING(1034)` 只控制费用不控制内容;
         `hero._tavern_offer_override` 只覆写**数量**（RULES §7.4.8）。
         引擎已有 `add_tavern_entity` / `tavern_entity_added`
         （RULES §7.4.9）与 `tavern_refresh_complete` 观察点，但**没有**
         "本次刷新的内容 = 指定 card_id 列表"的入口。
      2. 三条语义无权威: (a) 副本是否占池（wiki Patch 35.6.0.243002
         bugfix "could be overwritten by refresh effects" 只说明它占用
         一个独立刷新槽）; (b) 同名随从是否允许重复（warband 天然可
         同名）; (c) 该刷新被再次刷新时如何回池。
    Implementation path: 引擎新增 `hero._custom_refresh:
      Optional[list[str]]`（一次性）+ `refresh_tavern` 命中时以该列表
      填充展示区（副本走 `create_minion`，按"复制体不占池"记账 RULES
      §2.3），消耗后清空; 并在 RULES §7.4 记录刷新槽优先级。随后本卡
      on_bind = `hero.FREE_REFRESH_REMAINING += 1` + 写入
      `hero._custom_refresh`。阻塞卡: BG35_MagicItem_930。
    Reference: batch_trinkets20 模块 docstring（同卡既有台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（"a free Refresh" 为文本字面量; num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class InsurrectionistsBladeScript:
    """
    Natural language: At the end of your turn, trigger all friendly
    <b>Rallies</b>.

    Status: DEFERRED — requires "攻击外触发 Rally"协议 + 被触发 Rally
      的 ctx target 权威

    Dependency:
      1. `Game.run_rally(attacker, ctx)` 只在
         `CombatScheduler._execute_attack` 与 `Game.recruit_phase_attack`
         两处被调用，ctx 恒为 `{"target": defender}`（存活 rally 脚本
         全部经 `_rally_target(ctx)` 取防御者——batch_rally /
         batch_rally2）。EoT 无防御者，官方未公布"被触发的 Rally 以谁
         为目标"（自指 / 随机敌方 / 空目标三读法都无证据）。
      2. XML 权威确认触发时机（`END_OF_TURN_TRIGGER=1` +
         `BACON_RALLY=1`），wiki 页
         `Battlegrounds/Insurrectionist's_Blade` 无 Notes 段
         （2026-09-14 复读）→ 无权威读法（SOP §6b 第 4 步）。
      3. **禁止**脚本自行调 `run_rally`（会绕过 `rally_extra` 额外触发
         配额与磁力栈合并——SOP §16b item 39 同族纪律）。
    Implementation path: (a) 先由官方/实测裁定无攻击者时 rally 的
      `target` 取值并写入 RULES §6.16; (b) 引擎新增
      `Game.trigger_friendly_rallies(hero, ctx)`（逐存活友方
      `run_rally(m, ctx)`，含 `rally_extra` 配额）→ 本卡 EoT 调用。
      阻塞卡: BG36_MagicItem_214。
    Reference: batch_trinkets20 模块 docstring（同卡既有台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG36_MagicItem_214 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class EternalPortraitScript:
    """
    Natural language: [x]Get a Golden Eternal Knight. After a friendly
    Undead dies, your Eternal Knights have +{0}/+{1} this game.

    Status: DEFERRED — requires "按卡家族的光环"读取点

    Dependency:
      1. 第一条款可交付（数据链 95262 → `BG25_008_G` 金色 Eternal
         Knight，`triple_base_id` 95261 → `BG25_008`），但第二条款
         双重阻塞。
      2. "your Eternal Knights have +{0}/+{1} this game" 是**按卡家族**
         的累积光环（对照 `BG25_008` 自身文本显式写 "(wherever this
         is)"，本卡没写）——引擎只有 `hero.race_auras`（种族维度）与
         `hero.tier_auras`（档位维度），**无**"指定卡家族"读取点;
         `Entity._aura_atk/_aura_health` 无该分支。
      3. SOP §16b item 32 明确禁止用"入场即 buff + SUMMON 监听"近似
         光环（`Transform` / 直接 `board[idx]=` 等非 summon 入板路径会
         漏），故不能按 `BG25_008` 实例逐个打 buff。
    Implementation path: 引擎新增 `game.add_card_aura(source,
      family_ids, atk, health)` → `hero.card_auras[uuid] =
      (frozenset(ids), atk, health)`，读取点并入
      `Entity._aura_atk/_aura_health`（与 `_tier_aura_active` 同构，
      source 离场即失效）; 累积值 = `hero.deaths_by_card_id` 的
      Undead 计数 × num(0)/num(1)（"this game" 跨战斗持久）。另需官方
      对作用域（仅棋盘 / 含手牌）与"金色 Eternal Knight 是否计入"的
      证据。阻塞卡: BG36_MagicItem_216。
    Reference: batch_trinkets20 模块 docstring（同卡既有台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=4 {1}=num(1)=2（BG36_MagicItem_216）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TrailblazerStickerScript:
    """
    Natural language: Your <b>Choose One</b> cards have both effects
    combined.

    Status: DEFERRED — requires 盘外 CHOOSE_BOTH 读取点

    Dependency: 引擎读取 `GameTag.CHOOSE_BOTH` 的只有**棋盘随从**两处
      ——`Game.play_minion`（`any(m.has(GameTag.CHOOSE_BOTH) for m in
      hero.board) or minion.has(...)`）与 `Game.play_spell`
      （`any(... for m in hero.board)`，本批复核 `hsrl2/game.py`
      L850/L1196 仍如此）。饰品实体在 `hero.trinkets`（非棋盘），脚本写
      `hero.set(CHOOSE_BOTH, True)` 无任何读取方（W3 空转标记）。
      注: 法术路径连"实体自带 tag"分支都没有，即使逐张给手牌 Choose
      One 卡打标也不能覆盖法术（且无法覆盖绑定后新获得的卡）。
    Implementation path: 两处 both 判定增 `or hero.get(GameTag.
      CHOOSE_BOTH, False)`（或统一抽 `Game.choose_both_active(hero)`），
      并补盘外来源（饰品/任务奖励）的引擎回归测试; 之后本卡 on_bind
      置 hero 级 CHOOSE_BOTH 即 CORRECT。阻塞卡: BG36_MagicItem_308。
    Reference: RULES §6.x Choose One; batch_trinkets20 模块 docstring
      （同卡既有台账）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: 无模板参数（BG36_MagicItem_308 num(0..3) 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# 2026-09-18: `CyclistPortraitScript` 占位 DEFERRED 台账删除——已由 batch_trinkets31
# 注册（`Buff(persist=True)` 按来源跨战斗持久化原语，RULES §3.5 例外 4）。


class MultilayeredShieldScript:
    """
    Natural language: [x]Your Tavern spells give an extra +{0}/+{1}.
    <i>(Improved by each different friendly minion type!)</i>

    Status: DEFERRED — requires 动态 `TAVERN_SPELL_EXTRA_*` 求值点

    Dependency:
      1. `TAVERN_SPELL_EXTRA_ATK/HEALTH` 是**静态** hero tag，唯一读取点
         `racefx.tavern_spell_buff(target, atk, health)` 在法术结算时
         一次性读取。本卡的额外值随**棋盘不同随从类型数**实时变化
         （入场/死亡/出售/金色化/`Transform`/战斗复原/换入），静态写入
         无法表达（写一次 → 之后不再更新 = 空转标记，SOP §16b item 32
         明令"光环用入场即 buff 近似会漏路径"）。
      2. 官方 S14 Trinket 表 / wiki 页无"每个类型"的增量口径（印面值
         +1/+2 是基准还是 1 个类型时的值），两种读法
         （`num0*(1+T)` vs `num0*T`）无权威（SOP §6b 第 4 步）。
    Implementation path: `racefx.tavern_spell_buff` 增加**动态提供者**:
      `hero.tavern_spell_extra_providers: list[(source, fn(hero)->(atk,
      health))]`，结算时逐条求值（与 `hero.race_auras` /
      `game.add_tier_aura` 的"读取时校验 source 仍在场"生命周期同构）;
      同时取得官方对 T 口径的权威。阻塞卡: BG36_MagicItem_373。
    Reference: docs/agents/ENGINE_BACKLOG.md §A9; batch_trinkets22
      `MultilayeredShieldScript` 原台账（本批复核维持）。

    Test: 不注册（DEFERRED）——同上台账守卫。

    Params: {0}=num(0)=1 {1}=num(1)=2（BG36_MagicItem_373）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册本批 3 张 CORRECT 饰品（13 张 DEFERRED 不注册）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (PLAGUERUNNER_PORTRAIT, PlaguerunnerPortraitScript),
        (AMPLIFYING_ESSENCE, AmplifyingEssenceScript),
        (ASSEMBLER_PORTRAIT, AssemblerPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
