"""批次 remaining2 — 载荷随从（作业单 2026-09-16 第二轮清尾）。

范围: 逐类别复扫后，未注册且**权威完整**的卡只剩"载荷随从"一族
（池外 token/交付物，`is_pool_minion=False`——引擎数据通道不覆盖它们，
因为它们的钩子/条件面需要脚本）。本批只迁**卡面 + 数据完全确定**的 4 张,
不触碰任何需要裁定口径的饰品（二态铁律，SOP §6b）。

编号说明: `batch_remaining1`（2026-09-16，EBG_Spell_037）已做完整类别
扫描；本批是同一作业单下的第二批，范围收敛到载荷随从。

注册 4 张（CORRECT；注册键 = 卡 id，金色独立卡定义）
═══════════════════════════════════════════════════════════════════════
  BG_BOT_606 Kaboom Bot（T2 2/2 机械）
      "<b>Deathrattle:</b> Deal {0}_damage to a random enemy minion."
      `num(0)=4`（CardDefs TAG_SCRIPT_DATA_NUM_1；缺失 → fail-loud）。
      金色 `TB_BaconUps_028`（4/4）文本 "...to a random enemy minion,
      twice." = 同一亡语结算 2 次伤害实例（`_times=2`；Impulsive
      Trickster 金色 `_applications=2` 先例）。
      与该卡数据链归属: `BG30_MagicItem_803` Kaboom Bot Portrait
      （`evolution_card_id=96766` → 本卡，本批核验）。该饰品**已迁出
      DEFERRED**（2026-09-18，`batch_trinkets39`：家族伤害加成读取点 =
      RULES §7.4.16 `family_flags` + 载荷侧 `FLAG_KABOOM_DR_BONUS`；
      金色逐实例口径见 `KaboomBotScript` docstring §6–8）。

  BG29_801 Silver Goose（T2 2/3 野兽）
      "Whenever this takes damage, summon a 2/2 Fledgling with
      <b>Taunt</b>."
      金色 `BG29_801_G`（4/6）文本 "...summon a **4/4** Fledgling with
      Taunt."。召唤物 = 数据链 token `BG29_801t`（2/2 Taunt，dbf
      108715）/ 金色 `BG29_801_Gt`（4/4 Taunt，dbf 108716）——属性与
      Taunt 全在 token CardDef 上（CardDefs.xml 权威），脚本零硬编码数值。
      与该卡数据链归属: `BG30_MagicItem_777` Goose Portrait
      （`evolution_card_id=107865` → 本卡），该饰品已由
      batch_goose_lucky_egg 注册（2026-09-17，见文末台账）。

实现依据（可离线核验）
═══════════════════════════════════════════════════════════════════════
  - 伤害事件 `DAMAGE ("damage", minion=, amount=, source=)` 覆盖全部
    伤害路径（攻击主/反击/顺劈/招募期攻击/`Hit`）——SOP §9 /
    `batch_misc.VeryHungryWinterfinnerScript`（同款 "Whenever this
    takes damage" 监听协议: `owner=source` + `condition minion is
    source` + `amount` 为 0 不计）。
  - 敌方定位 `game._active_combat`（`combat.CombatScheduler.run` 在
    SoC 前设 `(a, b)`、finally 清 None）——复用
    `batch_hero_remaining2._combat_opponent`（同协议唯一实现）。
  - 召唤走 `actions.Summon`（`create_minion`，token 不占池——SOP §3 P2;
    `BG29_801t/_Gt` 运行核验 `is_pool_minion=False`）。
  - 伤害走 `actions.Hit`（圣盾/剧毒口径由引擎保证; 逐实例 `Hit.do`
    内含 `check_deaths`，故"twice"的第二实例在第一个实例的死亡波次
    **之后**重新选取存活目标——数量不足即落空，非近似）。

DEFERRED 台账（本批复核维持；只记与载荷相关的两条，其余见
`batch_remaining1` / `batch_trinkets31` 的分类台账）
═══════════════════════════════════════════════════════════════════════
  - `BG30_MagicItem_803` Kaboom Bot Portrait — ✅ **已迁出**（2026-09-18，
    batch_trinkets39）: "Get a Kaboom Bot. Your Kaboom Bots' Deathrattles
    deal 10 extra damage."
    载荷面（`BG_BOT_606`/`TB_BaconUps_028`）随本批关闭; 饰品本体由
    batch_trinkets39 注册。两条原残余阻塞均已消除:
      (a) "卡家族亡语伤害加成"读取点 → RULES §7.4.16 家族行为开关通道
          （`Game.add_family_flag` / `family_flag`，Bristlebach 先例），
          载荷 `KaboomBotScript.deathrattle` 经 `FLAG_KABOOM_DR_BONUS`
          把逐实例 +`KABOOM_EXTRA_DAMAGE`(=10) 传给 `KaboomBlast`。
      (b) 金色"twice"下 +10 的口径 → owner 权威序: wiki 页
          `Battlegrounds/Kaboom_Bot_Portrait`（oldid=921183）**无 Notes
          段**（2026-09-16 复核）→ 取卡面天然语言**逐实例**读法
          （14+14=28）; 否决"总额 +10 一次"（18 无法在两条独立伤害
          实例间分配，文本无 "split" 字样）。完整推导与边界见
          `KaboomBotScript` docstring §6–8。
  - `BG30_MagicItem_777` Goose Portrait — ✅ **已迁出**（2026-09-17，
    batch_goose_lucky_egg）: "Get a Silver Goose. After you summon 3
    Silver Fledglings, get a Lucky Egg. <i>({0} left!)</i>"
    载荷面（`BG29_801`/`BG29_801_G`）随本批关闭; 次生载荷
    `BG30_104`/`BG30_104_G` Lucky Egg 由 batch_goose_lucky_egg 注册
    （"transform into" = 引擎 `Transform` + 池化发现金色 T3/T4），
    饰品本体同批注册（计数阈值 `num(0)=3` + Fledgling token 家族）。
    不再有残余阻塞（原"口径无先例"记载已按 §6.21 + wiki Transform
    Notes + `Discover(golden=True)` 先例裁定而失效）。

测试: `hsrl2/tests/test_batch_remaining2.py`（行为层: 真实
`_process_single_death` / 真实 `run_combat`（战斗内 `_active_combat`
定位敌方 + 战斗内探针）/ `Hit` → `check_deaths` / owner 隔离 /
无战斗落空 / 池零操作 / 同 seed 确定性; 结构性: 注册表 / 金色数据链 /
token 非池 / num 纪律）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2.actions import Hit, Summon
from hsrl2.events import DAMAGE, Listener
from hsrl2.queue import Action
from hsrl2.scripts.batches.batch_hero_remaining2 import _combat_opponent

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.minion import Minion

# ── 卡 id（CardDB 按名核实，禁止凭记忆写） ──
KABOOM = "BG_BOT_606"                # Kaboom Bot（2/2, num(0)=4, dbf 96766）
KABOOM_G = "TB_BaconUps_028"         # 金色（4/4, num(0)=4, dbf 58369）

#: 家族亡语伤害加成开关（RULES §7.4.16 家族行为开关通道）——由
#: `BG30_MagicItem_803` Kaboom Bot Portrait 写入 `hero.family_flags`
#: （batch_trinkets39）。常量定义在**载荷侧**（唯一消费点），饰品侧
#: import 同一常量（Bristlebach `FLAG_SCOPE_ALL_FRIENDLY` 同构）。
FLAG_KABOOM_DR_BONUS = "kaboom_deathrattle_damage_bonus"

#: 文本字面量（`BG30_MagicItem_803` CardDef `num(0..4)` 全 None——SOP §3
#: 允许并在此声明）: "deal 10 extra damage" = 每个亡语伤害**实例** +10。
KABOOM_EXTRA_DAMAGE = 10

SILVER_GOOSE = "BG29_801"            # Silver Goose（2/3, dbf 107865）
SILVER_GOOSE_G = "BG29_801_G"        # 金色（4/6, dbf 107887）
FLEDGLING = "BG29_801t"              # Silver Fledgling 2/2 Taunt（dbf 108715）
FLEDGLING_G = "BG29_801_Gt"          # Silver Fledgling 4/4 Taunt（dbf 108716）


# ══════════════════ BG_BOT_606 / TB_BaconUps_028 Kaboom Bot ══════════════════


class KaboomBlast(Action):
    """`times` 次"对一个随机敌方随从造成 num(0) 伤害"（每次独立选取）。

    - 敌方 = `_combat_opponent(game, 本卡控制者)`（`game._active_combat`;
      结算期外/招募期 → None → 整体落空——真实游戏中此刻无敌方棋盘）
    - 逐实例重选: `Hit.do` 内含 `check_deaths`，上一实例的死亡波次已结算,
      故第二实例只在**当时仍存活**的敌方随从中选取; 无存活者 → 落空
      （"twice" 的两个伤害实例不再有合法目标即空转，非重复打尸体）
    - 伤害不传 `source`（KILLER tag 不写）——与既有"对随机敌方随从造成
      伤害"实现同口径（`batch_hero_remaining2.DieInsectsScript` /
      `FireTheCannonsScript`），不新增无权威的击杀归因
    - `bonus` = 家族亡语伤害加成（`BG30_MagicItem_803` Kaboom Bot
      Portrait "deal 10 extra damage"）。**逐实例**加到 `num(0)` 上
      （每实例 4+10=14；金色两次实例各自 14）——见
      `KaboomBotScript.deathrattle` 的读法与边界记录。默认 0 =
      无饰品时行为与旧实现逐位一致。
    """

    def __init__(self, source: "Minion", times: int, bonus: int = 0) -> None:
        self.source = source
        self.times = times
        self.bonus = bonus

    def do(self, game: "Game") -> None:
        opponent = _combat_opponent(game, self.source.controller)
        if opponent is None:
            return
        d = game.db.get(self.source.card_id)
        for _ in range(self.times):
            living = [m for m in opponent.board if not m.dead]
            if not living:
                return
            target = game.rng.choice(living, label="kaboom_bot_target")
            Hit(target, d.num(0) + self.bonus).do(game)


class KaboomBotScript:
    """
    Natural language: <b>Deathrattle:</b> Deal {0}_damage to a random
    enemy minion.

    Formal spec:
      1. deathrattle（真实死亡路径 `_process_single_death` 或
         "Trigger a Deathrattle" 统一入口）: 返回 `KaboomBlast(source,
         _times, bonus)`——伤害数额 `num(0)`（基础 = 4，CardDef 权威;
         缺失 fail-loud），目标 = 战斗对手棋盘中存活随从的 `rng.choice`
      2. 结算期外（`game._active_combat is None`，如招募期被消灭）→
         落空（无敌方棋盘，零状态变更）
      3. 敌方无存活随从 → 落空
      4. 本卡为池外 token（`is_pool_minion=False`）→ 生死均零池操作
      5. Taunt 等关键词由 CardDef 映射（数据权威; 本卡仅 Deathrattle）
      6. **家族亡语伤害加成读取点**（RULES §7.4.16 家族行为开关通道）:
         `KaboomBotPortraitScript`（`BG30_MagicItem_803`，batch_trinkets39）
         经 `game.add_family_flag(hero, 基础卡 id, FLAG_KABOOM_DR_BONUS,
         source=饰品)` 登记规则; 本钩子经
         `game.family_flag(hero, source.card_id, FLAG_KABOOM_DR_BONUS)`
         读取——命中则 `bonus = KABOOM_EXTRA_DAMAGE`（= 饰品文本字面量
         "10 extra damage"; 饰品 CardDef `num(0..4)` 全 None），
         未命中则 `bonus = 0`（**无饰品时逐位等于旧行为**）。
         金色 `TB_BaconUps_028` 按基础卡 id 归一命中（`_base_card_id`）。
      7. **"10 extra damage" 的天然语言读法（逐实例）与其边界**:
         - 读法: 饰品句 "Your Kaboom Bots' <b>Deathrattles</b> deal 10
           extra damage." 修饰的是 **Deathrattle 的伤害量**; 载荷把该
           伤害写作 "Deal {0}_damage"（`num(0)`=4），"twice" 只是对同一
           伤害事件的重复。故"一个 Deathrattle 伤害实例" = 一次
           "Deal num(0) damage"，加成逐实例施加: 基础 4+10=14; 金色两个
           实例各自 14 → **14 + 14 = 28**。
         - 被否决的替代读法（**总额 +10 一次**，金色 = 4+4+10 = 18）:
           18 无法在"两个各自独立选取目标、各打一个数额"的实例之间
           分配（10 是奇数，且两张卡文本均无 "split"/"divided evenly"
           字样）——总额读法必须凭空发明一条"奇数加成如何拆分"的规则，
           而逐实例读法不需要任何新规则。故按 owner 权威序（wiki 无
           Notes → 卡面天然语言）取逐实例读法。
         - 边界: 加成只作用于本条"造成伤害的亡语"（本族基础 + 金色，
           基础卡 id 归一）; 不影响其它亡语/其它伤害来源; 只作用于
           **本英雄**的 Kaboom Bot（`family_flag` 的 owner 隔离）。
      8. 权威记录: `BG30_MagicItem_803` 卡面 + hearthstone.wiki.gg/
         Battlegrounds/Kaboom_Bot_Portrait（oldid=921183，2026-09-16
         复核: Availability/Related cards/Gallery/Patch changes/
         External links，**无 Notes 段** → wiki 对金色逐实例口径沉默）;
         载荷页 Battlegrounds/Kaboom_Bot（oldid=803543）确认金色文本
         "Deal 4 damage to a random enemy minion, **twice**" 与
         `num(0)=4`。

    Test: test_batch_remaining2.py — 真实 `run_combat` 内亡语命中敌方
    随从恰 num(0)（战斗内探针）/ 招募期死亡落空 / 敌方空盘落空 /
    己方随从不受影响 / 金色恰 2 个实例 / 同 seed 确定性;
    test_batch_trinkets39.py — 无饰品 4 / 有饰品 14 / 金色有饰品
    [14, 14] / 对手饰品不影响我方 / 非家族随从不受影响

    Params: {0}=4（TAG_SCRIPT_DATA_NUM_1; num(1..4) 全 None）
    """

    _times = 1

    @staticmethod
    def deathrattle(source: "Minion", game: "Game", ctx) -> Optional[Action]:
        bonus = 0
        hero = source.controller
        if hero is not None and game.family_flag(
                hero, source.card_id, FLAG_KABOOM_DR_BONUS):
            bonus = KABOOM_EXTRA_DAMAGE
        return KaboomBlast(source, source.scripts._times, bonus)


class KaboomBotGoldenScript(KaboomBotScript):
    """
    Natural language: <b>Deathrattle:</b> Deal {0}_damage to a random
    enemy minion, twice.

    Formal spec: 同基础版，`_times = 2`——同一亡语结算两个**独立**
    伤害实例（每次重新 `rng.choice` 存活敌方; 先结算死亡波次）。
    金色 CardDef `TB_BaconUps_028` 的 `num(0)` 同为 4（数据核实）。
    家族加成（`FLAG_KABOOM_DR_BONUS`）**逐实例**生效（基础版 §7）:
    两个实例各自 `num(0)+10 = 14`，合计 28。

    Test: test_batch_remaining2.py — 金色在敌方存活 ≥1 时造成 2 个
    伤害实例（探针记录恰 2 次 num(0)）/ 仅 1 只且第一实例致死后第二
    实例落空; test_batch_trinkets39.py — 金色 + 饰品 = [14, 14]

    Params: {0}=4（金色 CardDef 同值; "twice" = `_times=2`）
    """

    _times = 2


# ══════════════════ BG29_801 / BG29_801_G Silver Goose ══════════════════


class SilverGooseScript:
    """
    Natural language: [x]Whenever this takes damage, summon a 2/2
    Fledgling with <b>Taunt</b>.

    Formal spec:
      1. on_summon 注册持久监听器（`owner=source` → 随从离场/死亡自动
         注销，SOP §5）: 事件 `DAMAGE`（引擎全覆盖路径），
         `condition: minion is source`（"this takes damage"）;
         `amount == 0` 不计（圣盾抵消 —— VeryHungryWinterfinner
         同口径）
      2. 回调: `Summon(控制者, _fledgling)`——token 经 `create_minion`
         创建（**不占池**; `BG29_801t` 运行核验 `is_pool_minion=False`），
         位置 = 最右（`Summon(position=None)` 默认）
      3. 数值/属性全在 token CardDef: 基础 2/2 + Taunt
         （`BG29_801t`, dbf 108715）; 脚本零硬编码
      4. 致死伤害同样触发（伤害实例先于死亡处理——受伤即召唤, 本体随后
         进入死亡波次）; 满场由 `game.summon` 的 MINION_OVERFLOW 处理
      5. 只作用于本人（监听器 owner 绑本实体; 对手的 Goose 不触发我方）

    Test: test_batch_remaining2.py — 真实 `Hit` 后棋盘出现
    `BG29_801t`（2/2 Taunt）/ 与其他友方受伤无关 / 对手 Goose 受伤
    不给我方召唤 / `amount=0` 不召唤 / 致死伤害仍召唤 / 两次伤害
    两只 Fledgling / 池零变化 / 同 seed 确定性

    Params: 无模板参数（召唤物属性 = token CardDef: 2/2 Taunt）
    """

    _fledgling = FLEDGLING

    @staticmethod
    def on_summon(source: "Minion", game: "Game", ctx) -> None:
        def on_damage(g, minion=None, amount=None, **kw):
            if minion is not source or not amount:
                return
            hero = source.controller
            if hero is None:
                return
            g.run_actions(Summon(hero, source.scripts._fledgling))

        game.events.register(Listener(
            event=DAMAGE, owner=source,
            condition=lambda minion=None, **kw: minion is source,
            callback=on_damage))
        return None


class SilverGooseGoldenScript(SilverGooseScript):
    """
    Natural language: [x]Whenever this takes damage, summon a 4/4
    Fledgling with <b>Taunt</b>.

    Formal spec: 同基础版，召唤物 = 金色 token `BG29_801_Gt`
    （CardDef 4/4 + Taunt, dbf 108716）——属性差异由 token 数据体现，
    脚本无分支。

    Test: test_batch_remaining2.py — 金色受伤召唤 `BG29_801_Gt`
    （4/4 Taunt）

    Params: 无模板参数（召唤物属性 = 金色 token CardDef: 4/4 Taunt）
    """

    _fledgling = FLEDGLING_G


# ══════════════════ 注册 ══════════════════

_SCRIPTS = {
    KABOOM: KaboomBotScript,
    KABOOM_G: KaboomBotGoldenScript,
    SILVER_GOOSE: SilverGooseScript,
    SILVER_GOOSE_G: SilverGooseGoldenScript,
}

CORRECT_IDS = (KABOOM, KABOOM_G, SILVER_GOOSE, SILVER_GOOSE_G)


def register() -> list[str]:
    """注册 4 张载荷随从（DEFERRED 台账见模块 docstring——不注册）。"""
    from hsrl2.scripts.registry import register as reg

    for cid, cls in _SCRIPTS.items():
        reg(cid, cls)
    return list(_SCRIPTS)
