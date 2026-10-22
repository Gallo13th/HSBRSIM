"""批次 quests — 酒馆战棋任务卡 20 注册项（2026-09-18 第四十九轮）。

**权威序（项目所有者 2026-09-18 直接裁定，取代此前"无权威可依"的
DEFERRED 判定）**

1. hearthstone.wiki.gg 有详细说明处 → **wiki 权威**（记录 URL + oldid +
   逐字引文）。
2. wiki 无详细说明处 → 卡面文字的自然语言解读（把解读与边界写进本
   文件的类 docstring）。
3. 铁律不变: 禁止"注册但空转"、禁止静默第三态、卡面明确处禁止简化
   实现、真实路径测试 + 变异敏感负对照、三段式 docstring、文档只记录
   现实（本政策本身只能作为"项目所有者裁定"记录，不得用来洗白别的
   近似）。

**目标值权威（逐卡核实 2026-09-18）**

页面 `https://hearthstone.wiki.gg/wiki/Battlegrounds/Quest`（oldid
916067）的 "Baseline requirements for all Quests" 段给出基线值，但该列表
**陈旧**（如 hub 写 Crack the Case 15 / Cry for Help 3 / Dust for Prints
22 / Pressure 35 / Unlikely Duo "Play 5"，而各卡页 Patch changes 的当前值
分别是 9 / 4 / 23 / 28 / "Buy 4"）→ **以各卡页 "Patch changes" 的当前值
为权威**（下表），并与 `hsdata/CardDefs.xml` 的 `QUEST_PROGRESS_TOTAL`
（enumID 535）逐张一致：

| id | 名称 | 目标值 | 卡页 oldid | 当前值来源（逐字） |
|----|------|--------|-----------|-------------------|
| `BG24_Quest_112` | Track the Footprints | 8 | 885653 | "New baseline requirement: 8 (previously: 9)" |
| `BG24_Quest_114` | Assemble a Lineup | 16 | 904752 | "baseline requirement: 16 (previously: 17)" |
| `BG24_Quest_120` | Unmask the Culprit | 3 | 866634 | 卡页**无** baseline 行（仅 "Added." / "Removed"）→ 自然语言解读 + tag 值 |
| `BG24_Quest_123` | Find the Murder Weapon | 14 | 805529 | "baseline requirement: 14 (previously: 15)" |
| `BG24_Quest_124` | Reenact the Murder | 17 | 885660 | "New baseline requirement: 17 (previously: 18)" |
| `BG24_Quest_125` | Sort It All Out | 4 | 891593 | 卡页无 baseline 行 → 自然语言解读 + tag 值 |
| `BG24_Quest_126` | Follow the Money | 27 | 885654 | "New baseline requirement: 27 (previously: 30)" |
| `BG24_Quest_151` | Unlikely Duo | 4 | 885662 | "New baseline requirement: 4 (previously: 5)" |
| `BG24_Quest_311` | Cry for Help | 4 | 921080 | "baseline requirement: 4 (previously: 3)" |
| `BG24_Quest_313` | Invite the Guests | 6 | 885659 | "baseline requirement: 6 (previously: 7)" |
| `BG24_Quest_314` | Dust for Prints | 23 | 885655 | "New baseline requirement: 23 (previously: 22)" |
| `BG24_Quest_318` | Witness Protection | 7 | 888017 | "New baseline requirement: 7 (previously: 8)" |
| `BG24_Quest_320` | Exhume the Bones | 6 | 885664 | "New baseline requirement: 6 (previously: 7)" |
| `BG24_Quest_328` | Close the Case | 1（数据值; 未注册） | 805512 | **DEFERRED**——卡数据 `quest_progress_total=1`（tag 535）; 真正阻塞 = "Win the game." 胜义无权威（见文末） |
| `BG24_Quest_351` | Hire an Investigator | 3 | 885665 | 卡页无 baseline 行 → 自然语言解读 + tag 值 |
| `BG24_Quest_352` | Crack the Case | 9 | 885656 | "New baseline requirement: 9 (previously: 10)" |
| `BG27_Quest_800` | Burn the Evidence | 6 | 904024 | "New baseline requirement: 6 (previously: 7)" |
| `BG27_Quest_801` | Pressure the Authorities | 28 | 885658 | "baseline requirement: 28 (previously: 32)" |
| `BG27_Quest_802` | Round Up the Suspects | 17 | 892002 | "baseline requirement: 17 (previously: 18)" |
| `BG28_Quest_500` | Fill the Cauldron | 11 | 805528 | "baseline requirement: 11 (previously: 12)" |

**关于"四因子缩放"（旧阻塞）**: 旧 DEFERRED 判定依据社区拆包公式
「难度 = 基础值 × 任务种族修正 × 奖励基础值 × 奖励种族修正 × 护甲等级」
（RULES §11.6 旧文）。wiki 的用词是 **"baseline requirement"**——它是
**基线**（可因英雄或奖励强度上下浮动），即缩放后的运行时值而以基线为
中心。项目所有者裁定: wiki 明文给出的 baseline 即本模拟器的目标值，
不再要求四因子表（该表 XML 与 wiki 均无）。**已实现的近似边界**:
每局只按基线判定，不模拟 ±修正 → 记录在案（`QUEST_DEFERRED_SPEC.md`
§3），不得再被当作"未实现的简化"另行判罚。

**进度口径**: 机制留在引擎（`Game.advance_quest_progress` /
`set_quest_progress` 是唯一写入点），脚本只声明
「监听哪个事件 + 目标值 + 判定」。每个脚本注册**一个**事件监听器
（`_wire`），回调内用 `_matches` 做持有者隔离。

**DEFERRED 台账（1 张）**
═══════════════════════════════════════════════════════════════════════
  `BG24_Quest_328` Close the Case — "Win the game."。
  **阻塞点 = 胜义无权威，不是缺目标值**: 卡数据携带
  `quest_progress_total=1`（`data/bg_cards.json` / CardDefs tag 535，
  2026-09-18 实测），故"无 baseline/无 target"的说法**为假**; wiki 卡页
  （oldid 805512）只有 "Patch 24.2.0: Added."（无 baseline 行）只说明
  wiki 未给出可用数值，不说明数据无值。真正无法消歧的是 "Win the game"
  指**第 1 名 / 前 4 名 / 单场战斗胜利**三者中的哪一个——自然语言解读
  无法选定（该卡 `QUEST` tag 缺失、从未入池）。二态铁律下保持 DEFERRED
  （不是近似实现，也不是"无进度脚本"）。
  两张公告 token（`BG24_Quest_Bob` / `BG33_Anomaly_008_Quest`）由
  `Game.quest_defs()` 显式排除（注册=空转第三态）。

**已知近似（记录在案）**
═══════════════════════════════════════════════════════════════════════
  1. `BG24_Quest_125` Sort It All Out: 文本 "Order your minions from
     lowest to highest Attack for {0} combats"——判定 = 每场战斗
     `start_of_combat` 时本人存活棋盘按攻击力**非递减**（平局允许）。
     边界: <2 随从视为平凡成立（"order your minions" 无可排序对象）;
     只按战前面板攻击力（光环实时值），不检查手牌/酒馆。wiki 页
     （oldid 891593）无 Notes。
  2. `BG24_Quest_151` Unlikely Duo: 两族 = 卡数据 `TAG_SCRIPT_DATA_NUM_1
     =14 (MURLOC)` / `NUM_2=20 (BEAST)`（**不是**每局随机——卡页 own
     tags 即定值; hub 的 "random minion type" 是模板占位符未渲染的
     显示产物）。计数**合并**在一个阈值上（文本只有一个 `{0}`）。
  3. `BG24_Quest_123` Find the Murder Weapon: 见类 docstring（计数
     粒度 = 每次**永久**附魔事件 1 次）。
  4. `BG27_Quest_801` Pressure the Authorities: 阈值式，达 28 即完成
     （不写成 28 次事件）。

测试: `hsrl2/tests/test_batch_quests.py`（真实路径 + 负对照 + 变异）。
"""

from __future__ import annotations

from hsrl2.events import Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# ══════════════ 基础协议 ══════════════

# 标准随从种族池（`BG24_Quest_151` "random minion type" 的抽样域）。
# 排除 INVALID(0) 与 ALL(26)——"random minion type" 在 BG 语境里指
# 可入池的具名种族（wiki `Battlegrounds/Minion type`）。
_STANDARD_RACES = (
    Race.BEAST, Race.DEMON, Race.DRAGON, Race.ELEMENTAL, Race.MECH,
    Race.MURLOC, Race.NAGA, Race.PIRATE, Race.QUILBOAR, Race.UNDEAD,
)


class QuestScript:
    """任务脚本基类: 单事件监听 + 持有者隔离 + 目标阈值。

    Natural language: 每张任务卡 = 一个"条件事件 + 计数/达标阈值"。
    卡面 `{0}` 处即本类的 `target`（数值来源见模块 docstring 表）。

    Formal spec:
      1. `event` / `target` 是类属性（引擎 `Game.quest_target` 读
         `target`）
      2. `on_bind(source, game, ctx)` 注册**唯一**监听器 →
         `_on_event`；`ctx["hero"]` 是任务持有者
      3. `_matches(game, holder, **kw) -> bool` 持有者/条件判定
      4. `_amount(**kw) -> int` 单次事件增量（缺省 1）
      5. `_on_event` → `game.advance_quest_progress(holder, amount)`
         （唯一进度写入点；二次计分由引擎 `_quest_completed` 阻挡）

    Test: test_batch_quests.py — 每张任务真实路径推进/完成/发奖、
      对手隔离、超阈值不多发、未达阈值不完成、变异探针。

    Params: 子类定义 event/target/_matches/_amount
    """

    event: str = ""
    target: int = 0
    # 监听持有者: "quest" = 任务实体（随任务生命周期注销）; "hero" =
    # 英雄（跨战斗持久接线所需——`run_on_bind` 作用域内注册的 Hero-owned
    # 监听器才打 `survives_combat`，见 ENGINE_BACKLOG #31/#32）
    listener_owner: str = "quest"

    # ── 子类接口 ──

    @staticmethod
    def _matches(game, holder, **kw) -> bool:
        raise NotImplementedError

    @staticmethod
    def _amount(**kw) -> int:
        return 1

    # ── 接线 ──

    @classmethod
    def on_bind(cls, source, game, ctx):
        hero = (ctx or {}).get("hero")
        if hero is None:
            return None
        owner = hero if cls.listener_owner == "hero" else source
        game.events.register(Listener(
            event=cls.event, owner=owner,
            callback=cls._make_callback(hero)))
        cls._after_bind(source, game, hero)
        return None

    @classmethod
    def _after_bind(cls, source, game, hero) -> None:
        """接线后的初始化钩子（缺省 no-op；151 在此抽两族）。"""
        return None

    @classmethod
    def _make_callback(cls, hero):
        def _on_event(game, **kw):
            if not cls._matches(game, hero, **kw):
                return
            game.advance_quest_progress(hero, cls._amount(**kw))
        return _on_event


def _friendly(holder, entity) -> bool:
    return entity is not None and getattr(entity, "controller", None) is holder


# ══════════════ BG24_Quest_112 Track the Footprints ══════════════


class TrackTheFootprintsScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Have the Tavern <b>Refreshed</b>
    {0} times.

    Evidence: `data/bg_cards.json` BG24_Quest_112（`quest_progress_total`
    =8）; wiki `Battlegrounds/Track_the_Footprints` oldid=885653
    "New baseline requirement: 8 (previously: 9)" —— 数值 = 8。
    卡页无 Notes（自动/手动刷新是否同计无明文）→ 自然语言解读: 文本是
    "Have the Tavern Refreshed"，引擎 `Game.refresh_tavern(hero, auto=)`
    的手动与回合开始自动刷新**同一生产点**、同一事件
    （`tavern_refresh`），故二者同计（"Tavern Refreshed" 不区分来源）。

    Formal spec:
      1. 监听 `tavern_refresh(hero=, auto=)`（`game.py:483/605` 两处
         生产点: 回合开始自动 / 玩家付费刷新）
      2. `_matches`: 事件 `hero` 是任务持有者（对手刷新不计）
      3. 每次 +1；达 8 → `complete_quest` 发奖并停止计分

    Test: test_batch_quests.py::TestQuest112 — 真实 `refresh_tavern`
      手动/自动各计 1; 对手刷新不计（负对照）; 8 次恰好完成并只发一次奖;
      第 9 次不再计分（变异: target 改 7 必须失败）

    Params: target=8（wiki baseline，见模块表）
    """

    event = "tavern_refresh"
    target = 8

    @staticmethod
    def _matches(game, holder, hero=None, auto=None, **kw):
        return hero is holder


# ══════════════ BG24_Quest_114 Assemble a Lineup ══════════════


class AssembleALineupScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Summon {0} minions.

    Evidence: wiki `Battlegrounds/Assemble_a_Lineup` oldid=904752
    "baseline requirement: 16 (previously: 17)" —— 数值 = 16。

    Formal spec:
      1. 监听 `summon(minion=)`（`game.py:1277` 唯一生产点，覆盖
         `play_minion` / 战吼召唤 / 亡语召唤 / 三连金色置场）
      2. `_matches`: `minion.controller is holder`
      3. 每次 +1；达 16 完成

    Test: test_batch_quests.py::TestQuest114 — 真实 `play_minion` 召唤
      计数; 对手召唤不计（负对照）; 16 次完成（变异: 去掉 controller
      判定必须失败）

    Params: target=16（wiki baseline）
    """

    event = "summon"
    target = 16

    @staticmethod
    def _matches(game, holder, minion=None, **kw):
        return _friendly(holder, minion)


# ══════════════ BG24_Quest_120 Unmask the Culprit ══════════════


class UnmaskTheCulpritScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Lose or tie {0} combats.

    Evidence: wiki `Battlegrounds/Unmask_the_Culprit` oldid=866634 只有
    "Patch 24.2.0: Added." / "Removed from the pool"——**无 baseline 行**。
    → 自然语言解读 + 数据值: 卡数据 `quest_progress_total`=3（CardDefs
    tag 535）。文本 "Lose or tie {0} combats" 的自然语言解读 = 在
    {0} 场战斗中**未获胜**（败或平）。数值 3 取自数据（与 hub 页
    旧列表不冲突）。

    Formal spec:
      1. 监听 `combat_end(hero_a=, hero_b=, result=)`（`game.py:2501`
         真实配对; `run_ghost_combat` 同事件）
      2. `_matches`: 持有者是 `hero_a`/`hero_b` 之一 ∧
         `holder._last_combat_result in {"loss", "draw"}`
         （引擎在 `run_combat` 战后写入该字段）
      3. 每场 +1；达 3 完成

    Test: test_batch_quests.py::TestQuest120 — 真实 `run_combat` 败局
      计入、胜局不计（负对照: 同一 hook 在 win 下必须不推进）; 对手败局
      不计入本人（owner 隔离）; 3 场完成

    Params: target=3（自然语言解读 + CardDefs tag 535; wiki 卡页无 baseline）
    """

    event = "combat_end"
    target = 3

    @staticmethod
    def _matches(game, holder, hero_a=None, hero_b=None, result=None,
                 **kw):
        if holder is not hero_a and holder is not hero_b:
            return False
        return getattr(holder, "_last_combat_result", None) in ("loss",
                                                                "draw")


# ══════════════ BG24_Quest_123 Find the Murder Weapon ══════════════


class FindTheMurderWeaponScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Increase a friendly minion's stats
    {0} times.

    Evidence: wiki `Battlegrounds/Find_the_Murder_Weapon` oldid=805529
    "baseline requirement: 14 (previously: 15)" —— 数值 = 14。卡页无
    Notes（计数粒度/临时 buff 无明文）→ 自然语言解读与边界:

      - 计数粒度 = 每次**附魔事件** 1 次（一次 `+2/+2` 记 1 次，不按
        点数拆分）——文本是 "Increase ... {0} **times**"，"times" 数
        的是"次数"不是点数。
      - 只计**永久**（非 `temporary`）附魔（RULES §3.5: 战斗期 buff
        战后消失，不构成"增加属性"的持久事实）。
      - 事件源 = `buff_applied(target=, buff=)`（`Entity.add_buff` 尾
        广播，`entity.py`）。**已记录在案的边界**: `copy_buffs_to`
        （副本/三连合成）与战斗快照重放也经 `add_buff` → 会一并计入；
        引擎当前无"获得"语义事件（ENGINE_BACKLOG §E 的触发域裁定
        仍开放）。此处按卡面自然语言取"附魔事件"为口径，不引入新的
        引擎事件（该原语一旦落地应迁移到它）。
      - `temporary=True` 的附魔不计。

    Formal spec:
      1. 监听 `buff_applied(target=, buff=)`
      2. `_matches`: `target.controller is holder` ∧ `not buff.temporary`
      3. 每次 +1（不按 atk/health 点数）; 达 14 完成

    Test: test_batch_quests.py::TestQuest123 — 真实 `add_buff`（经
      真实 `Buff` action / 真实法术）永久附魔计数; 临时附魔不计
      （负对照）; 对手随从附魔不计（owner 隔离）; 一次 +2/+2 只记 1
      （变异: `_amount` 改成按点数必须失败）

    Params: target=14（wiki baseline）
    """

    event = "buff_applied"
    target = 14

    @staticmethod
    def _matches(game, holder, target=None, buff=None, **kw):
        if not _friendly(holder, target):
            return False
        return not getattr(buff, "temporary", False)


# ══════════════ BG24_Quest_124 Reenact the Murder ══════════════


class ReenactTheMurderScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Have {0} friendly minions die.

    Evidence: wiki `Battlegrounds/Reenact_the_Murder` oldid=885660
    "New baseline requirement: 17 (previously: 18)" —— 数值 = 17。

    Formal spec:
      1. 监听 `death(minion=)`（`game.py:_process_death_inner` 在**离场
         之前**广播，招募期与战斗期同一生产点）
      2. `_matches`: `minion.controller is holder`
      3. 每个友方随从死亡 +1；达 17 完成

    Test: test_batch_quests.py::TestQuest124 — 真实战斗致死友方随从计
      数; 对手随从死亡不计（负对照）; 17 个完成

    Params: target=17（wiki baseline）
    """

    event = "death"
    target = 17

    @staticmethod
    def _matches(game, holder, minion=None, **kw):
        return _friendly(holder, minion)


# ══════════════ BG24_Quest_125 Sort It All Out ══════════════


class SortItAllOutScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Order your minions from lowest to
    highest Attack for {0} combats.

    Evidence: wiki `Battlegrounds/Sort_It_All_Out` oldid=891593 只有
    "Patch 24.2.0: Added." / "Removed from the pool"——**无 baseline 行**
    也**无 Notes**。→ 自然语言解读 + 数据值 `quest_progress_total`=4。

    自然语言解读与边界（已记录在案）:
      - 检查时点 = 每场战斗**开始时**（`start_of_combat`，攻击结算前）
        的本人棋盘。
      - "from lowest to highest Attack" = 攻击力**非递减**
        （平局允许——文本未写 "strictly"）。
      - 存活随从 < 2 时视为平凡成立（无可排序对象）。
      - 只按战前棋盘攻击力（含实时光环值）判定; 不看手牌/酒馆。
      - 计数 = 每满足一场战斗 +1（不是每次重排 +1）。

    Formal spec:
      1. 监听 `start_of_combat(hero=)`（`combat.py:155` 每英雄一次，
         先攻判定前）
      2. `_matches`: `hero is holder` ∧ 棋盘攻击力非递减
      3. 满足一场 +1；达 4 完成

    Test: test_batch_quests.py::TestQuest125 — 真实 `run_combat` 下
      升序棋盘计入、乱序棋盘不计（负对照）; 对手乱序不影响本人;
      4 场完成

    Params: target=4（自然语言解读 + CardDefs tag 535; wiki 卡页无 baseline）
    """

    event = "start_of_combat"
    target = 4

    @staticmethod
    def _matches(game, holder, hero=None, **kw):
        if hero is not holder:
            return False
        atks = [m.atk for m in holder.board if not m.dead]
        if len(atks) < 2:
            return True
        return all(a <= b for a, b in zip(atks, atks[1:]))


# ══════════════ BG24_Quest_126 Follow the Money ══════════════


class FollowTheMoneyScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Spend {0} Gold.

    Evidence: wiki `Battlegrounds/Follow_the_Money` oldid=885654
    "New baseline requirement: 27 (previously: 30)" —— 数值 = 27。
    另 quotes: "2023-06-30: Fixed a bug where the 'Follow the Money'
    quest updated in combat."（→ 只计招募期花费，引擎 `spend_gold`
    只在招募期被调用，战斗内无金币消耗，天然满足）。

    Formal spec:
      1. 监听 `gold_spent(amount=, hero=)`（`game.py:1640` 唯一生产点）
      2. `_matches`: `hero is holder`
      3. 进度 += `amount`（不是每次 +1）; 达 27 完成

    Test: test_batch_quests.py::TestQuest126 — 真实 `spend_gold` 按金
      额累加（买 3 金随从 → +3）; 对手花费不计（负对照）; 恰好 27 完成;
      变异: `_amount` 改 1 必须失败

    Params: target=27（wiki baseline）
    """

    event = "gold_spent"
    target = 27

    @staticmethod
    def _matches(game, holder, hero=None, amount=0, **kw):
        return hero is holder

    @staticmethod
    def _amount(amount=0, **kw):
        return int(amount)


# ══════════════ BG24_Quest_151 Unlikely Duo ══════════════


class UnlikelyDuoScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Buy {0} {2} or {3}.

    Evidence:
      - 数值: wiki `Battlegrounds/Unlikely_Duo` oldid=885662
        "New baseline requirement: 4 (previously: 5)" —— 数值 = 4。
      - 动词: 同页 "Now reads: 'Quest: Buy {0} {2} or {3}.' (previously:
        'Quest: Play {0} {2} or {3}.')"（Patch 33.4.2.228373,
        2025-09-17）—— **"Buy" 为当前文本**，故计购买而非打出。
      - `{2}`/`{3}`: 卡数据 `TAG_SCRIPT_DATA_NUM_1=14 (MURLOC)` /
        `NUM_2=20 (BEAST)`——**由卡数据确定的两族**（非每局随机: 卡页
        own tags 给出 14/20，页面的 "Races in art: Beast Murloc" 与
        "Beast art/Murloc art" 分类佐证; hub 页 "Play 5 random minion
        type or random minion type" 是 {{2}}/{{3}} 未渲染的显示产物，
        且 hub 列表整体陈旧——见模块 docstring 权威说明）。

    自然语言解读与边界（已记录在案）:
      - 两族 = 卡数据 `num(0)`/`num(1)`（MURLOC=14 / BEAST=20），
        不再用 RNG 抽样（数据权威 > hub 陈旧渲染）。
      - 计数**合并**在一个阈值上（文本只有一个 `{0}`）。
      - `Race.ALL`（One-Amalgam 族）对两种族均合格。
      - "Buy" = 引擎 `minion_bought(minion=)` 生产点（`buy_from_tavern`），
        不含战吼/亡语召唤出的随从。

    Formal spec:
      1. `_after_bind`: 从 CardDef 读 `num(0)`/`num(1)`（Race 值）存到
         任务实体 `_quest_races`——缺参数则退化为 `_STANDARD_RACES`
         抽样（数据缺口兜底，不静默空转）
      2. 监听 `minion_bought(minion=)`
      3. `_matches`: `minion.controller is holder` ∧
         (`minion.race in races` ∨ `minion.race is Race.ALL`)
      4. 每次 +1；达 4 完成

    Test: test_batch_quests.py::TestQuest151 — 真实 `buy_from_tavern`
      购买两族之一计数、购买第三族不计（负对照）; `Race.ALL` 计数;
      对手购买不计; `_quest_races` = 卡数据两族（MURLOC/BEAST）

    Params: target=4（wiki baseline）; races=CardDef num(0)/num(1)
            （MURLOC/BEAST）
    """

    event = "minion_bought"
    target = 4

    @staticmethod
    def _after_bind(source, game, hero):
        d = game.db.get(source.card_id)
        r1 = d.num(0) if d is not None else None
        r2 = d.num(1) if d is not None else None
        try:
            picked = [Race(int(r1)), Race(int(r2))]
        except (TypeError, ValueError):
            picked = list(game.rng.sample(list(_STANDARD_RACES), 2,
                                          label="unlikely_duo_races"))
        source._quest_races = frozenset(picked)

    @staticmethod
    def _matches(game, holder, minion=None, **kw):
        if not _friendly(holder, minion):
            return False
        races = getattr(holder.quest, "_quest_races", frozenset())
        race = getattr(minion, "race", None)
        return race is Race.ALL or race in races


# ══════════════ BG24_Quest_311 Cry for Help ══════════════


class CryForHelpScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Play {0} <b>Battlecry</b> minions.

    Evidence: wiki `Battlegrounds/Cry_for_Help` oldid=921080
    "baseline requirement: 4 (previously: 3)" —— 数值 = 4。卡页无 Notes
    （触发式战吼是否计无明文）→ 自然语言解读: 文本是 "**Play** {0}
    Battlecry minions" → 只计**打出**随从（`card_played` 生产点），
    "Trigger a Battlecry" 类效果不打出随从故不计。

    Formal spec:
      1. 监听 `card_played(card=)`（`game.py:1090` 随从打出唯一生产点；
         法术打出在同名事件但 `card` 非随从）
      2. `_matches`: `card` 是随从 ∧ `controller is holder` ∧ Battlecry
         关键词（`card.has(GameTag.BATTLECRY)`）
      3. 每次 +1；达 4 完成

    Test: test_batch_quests.py::TestQuest311 — 真实 `play_minion` 战吼
      随从计数; 无战吼随从不计（负对照）; 对手打出不计; 4 个完成

    Params: target=4（wiki baseline）
    """

    event = "card_played"
    target = 4

    @staticmethod
    def _matches(game, holder, card=None, **kw):
        if not _friendly(holder, card):
            return False
        if not isinstance(card, Minion):
            return False
        return card.has(GameTag.BATTLECRY)


# ══════════════ BG24_Quest_313 Invite the Guests ══════════════


class InviteTheGuestsScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Buy {0} minions.

    Evidence: wiki `Battlegrounds/Invite_the_Guests` oldid=885659
    "baseline requirement: 6 (previously: 7)" —— 数值 = 6。
    同页 Notes 段（hub）: "the '{0}' can be a 7, changing it to 'Buy 7
    minions'." —— 印证 `{0}` 是可变的 baseline。

    Formal spec:
      1. 监听 `minion_bought(minion=)`（`game.py:782` 酒馆购买唯一生产点）
      2. `_matches`: `minion.controller is holder`
      3. 每次 +1；达 6 完成

    Test: test_batch_quests.py::TestQuest313 — 真实 `buy_from_tavern`
      计数; 对手购买不计（负对照）; 6 次完成

    Params: target=6（wiki baseline）
    """

    event = "minion_bought"
    target = 6

    @staticmethod
    def _matches(game, holder, minion=None, **kw):
        return _friendly(holder, minion)


# ══════════════ BG24_Quest_314 Dust for Prints ══════════════


class DustForPrintsScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Add {0} cards to your hand.

    Evidence: wiki `Battlegrounds/Dust_for_Prints` oldid=885655
    "New baseline requirement: 23 (previously: 22)" —— 数值 = 23。

    Formal spec:
      1. 监听 `card_gained(hero=, card=)`（`Hero.add_to_hand` 唯一入口，
         `hero.py:282` —— 覆盖购买入手/生成/Discover/等待队列交付）
      2. `_matches`: `hero is holder`（不需要 card 的 controller 判定；
         入手的牌可能是 token）
      3. 每次 +1；达 23 完成

    Test: test_batch_quests.py::TestQuest314 — 真实 `add_to_hand` 计数;
      对手入手不计（负对照）; 23 张完成; 变异: 去掉 hero 判定必须失败

    Params: target=23（wiki baseline）
    """

    event = "card_gained"
    target = 23

    @staticmethod
    def _matches(game, holder, hero=None, card=None, **kw):
        return hero is holder


# ══════════════ BG24_Quest_318 Witness Protection ══════════════


class WitnessProtectionScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Have a friendly <b>Taunt</b> minion
    attacked {0} times.

    Evidence: wiki `Battlegrounds/Witness_Protection` oldid=888017
    "New baseline requirement: 7 (previously: 8)" —— 数值 = 7。

    Formal spec:
      1. 监听 `after_attacked(defender=)`（`combat.py:346` 每次敌方随从
         攻击结算后广播; 伤害与死亡结算之后）
      2. `_matches`: `defender.controller is holder` ∧
         `defender.has(GameTag.TAUNT)`——"被攻击的嘲讽随从"（嘲讽已死
         仍计本次: 事件在伤害后广播且 `controller` 保留）
      3. 每次 +1；达 7 完成

    Test: test_batch_quests.py::TestQuest318 — 真实战斗中被攻击的嘲讽
      计数; 非嘲讽被攻击不计（负对照）; 对手嘲讽被攻击不计;
      7 次完成

    Params: target=7（wiki baseline）
    """

    event = "after_attacked"
    target = 7

    @staticmethod
    def _matches(game, holder, defender=None, **kw):
        if not _friendly(holder, defender):
            return False
        return defender.has(GameTag.TAUNT)


# ══════════════ BG24_Quest_320 Exhume the Bones ══════════════


class ExhumeTheBonesScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Trigger {0} friendly
    <b>Deathrattles</b>.

    Evidence: wiki `Battlegrounds/Exhume_the_Bones` oldid=885664
    "New baseline requirement: 6 (previously: 7)" —— 数值 = 6。卡页无
    Notes → 自然语言解读: "Trigger {0} friendly Deathrattles" 计的是
    **亡语触发次数**，同一次死亡触发多个亡语各计 1（引擎
    `deathrattle_trigger` 按每个亡语独立广播，`game.py:2730`）。

    Formal spec:
      1. 监听 `deathrattle_trigger(minion=)`
      2. `_matches`: `minion.controller is holder`
      3. 每次 +1；达 6 完成

    Test: test_batch_quests.py::TestQuest320 — 真实亡语随从死亡触发
      计数; 对手亡语不计（负对照）; 6 次完成

    Params: target=6（wiki baseline）
    """

    event = "deathrattle_trigger"
    target = 6

    @staticmethod
    def _matches(game, holder, minion=None, **kw):
        return _friendly(holder, minion)


# ══════════════ BG24_Quest_351 Hire an Investigator ══════════════


class HireAnInvestigatorScript(QuestScript):
    """
    Natural language: <b>Quest:</b> End your turn with unspent Gold
    {0} times.

    Evidence: wiki `Battlegrounds/Hire_an_Investigator` oldid=885665
    只有 "2024-02-16: Now harder to complete." / "Added." / "Removed
    from the pool"——**无 baseline 行**，也无 Notes。→ 自然语言解读 +
    数据值: `quest_progress_total`=3。解读: 每个**自己**的回合结束时
    若金币 > 0 则 +1（"unspent Gold" = 结束时仍有余额）。

    Formal spec:
      1. 监听 `turn_end(turn=)`（`end_recruit_phase` 开头广播，
         在 EoT 效果与战斗之前 → 读到的是招募期结束余额; 引擎金币在
         **下一个** `_begin_recruit_for` 才重置）
      2. `_matches`: 持有者存活 ∧ `holder.gold > 0`
      3. 每次 +1；达 3 完成

    Test: test_batch_quests.py::TestQuest351 — 真实 `end_recruit_phase`
      下留金币的回合计入、花光金币的回合不计（负对照）; 3 个回合完成

    Params: target=3（自然语言解读 + CardDefs tag 535; wiki 卡页无 baseline）
    """

    event = "turn_end"
    target = 3

    @staticmethod
    def _matches(game, holder, turn=None, **kw):
        return holder.is_alive and holder.gold > 0


# ══════════════ BG24_Quest_352 Crack the Case ══════════════


class CrackTheCaseScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Have friendly minions attack {0}
    times.

    Evidence: wiki `Battlegrounds/Crack_the_Case` oldid=885656
    "New baseline requirement: 9 (previously: 10)" —— 数值 = 9。

    Formal spec:
      1. 监听 `after_attack(attacker=, defender=)`（`combat.py:342`
         每次攻击结算后; 招募期 `recruit_phase_attack` 同名事件也广播）
      2. `_matches`: `attacker.controller is holder`
      3. 每次 +1；达 9 完成

    Test: test_batch_quests.py::TestQuest352 — 真实战斗攻击计数; 对手
      攻击不计（负对照）; 9 次完成

    Params: target=9（wiki baseline）
    """

    event = "after_attack"
    target = 9

    @staticmethod
    def _matches(game, holder, attacker=None, defender=None, **kw):
        return _friendly(holder, attacker)


# ══════════════ BG27_Quest_800 Burn the Evidence ══════════════


class BurnTheEvidenceScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Sell {0} minions.

    Evidence: wiki `Battlegrounds/Burn_the_Evidence` oldid=904024
    "New baseline requirement: 6 (previously: 7)" —— 数值 = 6。
    该卡已在 Patch 28.6.0 移出可选池，但同族目标值机制不变（引擎池
    口径含同族——2026-09-13 §1.2 分母订正）。

    Formal spec:
      1. 监听 `minion_sold(minion=)`（`game.py:928` 出售唯一生产点）
      2. `_matches`: `minion.controller is holder`（出售时 controller
         仍为本英雄；`sell_minion` 在事件后才改 zone/回池）
      3. 每次 +1；达 6 完成

    Test: test_batch_quests.py::TestQuest800 — 真实 `sell_minion` 计数;
      对手出售不计（负对照）; 6 次完成

    Params: target=6（wiki baseline）
    """

    event = "minion_sold"
    target = 6

    @staticmethod
    def _matches(game, holder, minion=None, **kw):
        return _friendly(holder, minion)


# ══════════════ BG27_Quest_801 Pressure the Authorities ══════════════


class PressureTheAuthoritiesScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Get your warband to {0} total
    Attack.

    Evidence: wiki `Battlegrounds/Pressure_the_Authorities` oldid=885658
    "baseline requirement: 28 (previously: 32)" —— 数值 = 28。卡数据
    `TAG_SCRIPT_DATA_NUM_1=NUM_2=28` 同值。

    **阈值式**（不是计数式）: "Get your warband to 28 total Attack" =
    warband（本人棋盘）总攻击力**达到过** 28 即完成，之后不再计分
    （引擎 `set_quest_progress` 只升不降 + `_quest_completed` 闸）。
    自然语言边界: 只算棋盘（warband），不含手牌/酒馆; 用实时 `atk`
    （含光环）。

    Formal spec:
      1. 监听 `buff_applied(target=, buff=)`（附魔是**唯一**能在不改变
         棋盘成员的情况下抬高总攻击的路径 → 需要在此重算）
      2. `summon`/`card_played` 亦触发重算（新随从入场可能直接达标）
      3. `_matches` 恒真（持有者过滤在回调内做）; 回调调
         `game.set_quest_progress(holder, total_atk)`
      4. 达 28 完成

    Test: test_batch_quests.py::TestQuest801 — 真实 buff 抬高总攻击至
      28 完成; 只抬到 27 不完成（负对照）; 对手 warband 达标不影响本人;
      变异: 阈值改 27 必须失败

    Params: target=28（wiki baseline）
    """

    event = "buff_applied"
    target = 28

    @classmethod
    def on_bind(cls, source, game, ctx):
        hero = (ctx or {}).get("hero")
        if hero is None:
            return None

        def recompute(g, _h=hero, **kw):
            if getattr(_h, "_quest_completed", False):
                return
            g.set_quest_progress(
                _h, sum(m.atk for m in _h.board if not m.dead))

        for ev in ("buff_applied", "summon", "card_played"):
            game.events.register(Listener(event=ev, owner=hero,
                                          callback=recompute))
        # 接线时先算一次：on_bind 前已有随从可能已达标
        # （`buff_applied` 的 target 也走同一入口——`_matches` 不判持有者
        # 时会把对手的附魔也算进来，故本类不使用基类回调）
        recompute(game)
        return None

    @staticmethod
    def _matches(game, holder, **kw):
        return True


# ══════════════ BG27_Quest_802 Round Up the Suspects ══════════════


class RoundUpTheSuspectsScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Destroy {0} enemy minions.

    Evidence: wiki `Battlegrounds/Round_Up_the_Suspects` oldid=892002
    "baseline requirement: 17 (previously: 18)" —— 数值 = 17。

    Formal spec:
      1. 监听 `minion_destroyed(hero=, minion=, source=, in_combat=)`
         （`game.py:3233`——"Destroy" 语义的统一生产点: 效果摧毁 +
         战斗击杀都经它）
      2. `_matches`: `minion.controller is not holder` ∧
         `minion.controller is not None`（"enemy" = 对手的随从;
         无主随从（酒馆）不计）∧ `hero is holder`
         （施动方为本人——Destroy 类效果由本人发动）
      3. 每次 +1；达 17 完成

    Test: test_batch_quests.py::TestQuest802 — 真实 `destroy` 摧毁对手
      随从计数; 摧毁自己随从不计（负对照）; 17 个完成

    Params: target=17（wiki baseline）
    """

    event = "minion_destroyed"
    target = 17

    @staticmethod
    def _matches(game, holder, hero=None, minion=None, **kw):
        if hero is not holder:
            return False
        ctrl = getattr(minion, "controller", None)
        return ctrl is not None and ctrl is not holder


# ══════════════ BG28_Quest_500 Fill the Cauldron ══════════════


class FillTheCauldronScript(QuestScript):
    """
    Natural language: <b>Quest:</b> Cast {0} spells.

    Evidence: wiki `Battlegrounds/Fill_the_Cauldron` oldid=805528
    "baseline requirement: 11 (previously: 12)" —— 数值 = 11。

    Formal spec:
      1. 监听 `spell_resolved(spell=, target=, cast_no=)`——手牌
         `play_spell` 与效果 `cast_spell_effect` **两条施放路径的唯一
         共同生产点**（`game.py:1494/1573`）。`card_played` 只覆盖手牌
         打出，故不用它（否则效果施法漏计）。
      2. `_matches`: `spell.controller is holder`
      3. 每次 +1；达 11 完成

    Test: test_batch_quests.py::TestQuest500 — 真实 `play_spell` 计数;
      对手施法不计（负对照）; 11 次完成; 变异: 监听改 `spell_bought`
      必须失败（购买法术不算"施放"）

    Params: target=11（wiki baseline）
    """

    event = "spell_resolved"
    target = 11

    @staticmethod
    def _matches(game, holder, spell=None, target=None, cast_no=None, **kw):
        return _friendly(holder, spell)


# ══════════════ 台账 / 注册 ══════════════

# DEFERRED（未注册; 理由见模块 docstring）:
#   BG24_Quest_328 Close the Case —— "Win the game."。阻塞 = **胜义无权威**
#     （第 1 名 / 前 4 / 单场战斗胜利三者无法消歧），**不是**缺目标值:
#     卡数据有 `quest_progress_total=1`（tag 535）; wiki 卡页无 baseline 行
#     只说明 wiki 未给出数值。从未入池、无 QUEST tag → 保持 DEFERRED。
# 公告 token（非任务卡本体; `Game.quest_defs()` 显式排除）:
#   BG24_Quest_Bob / BG33_Anomaly_008_Quest —— "In 3 turns, choose one of
#     three Quests!"; 语义已由 `Game._offer_quests` 实现。

_QUESTS = (
    "BG24_Quest_112", "BG24_Quest_114", "BG24_Quest_120",
    "BG24_Quest_123", "BG24_Quest_124", "BG24_Quest_125",
    "BG24_Quest_126", "BG24_Quest_151", "BG24_Quest_311",
    "BG24_Quest_313", "BG24_Quest_314", "BG24_Quest_318",
    "BG24_Quest_320", "BG24_Quest_351", "BG24_Quest_352",
    "BG27_Quest_800", "BG27_Quest_801", "BG27_Quest_802",
    "BG28_Quest_500",
)

_SCRIPTS = {
    "BG24_Quest_112": TrackTheFootprintsScript,
    "BG24_Quest_114": AssembleALineupScript,
    "BG24_Quest_120": UnmaskTheCulpritScript,
    "BG24_Quest_123": FindTheMurderWeaponScript,
    "BG24_Quest_124": ReenactTheMurderScript,
    "BG24_Quest_125": SortItAllOutScript,
    "BG24_Quest_126": FollowTheMoneyScript,
    "BG24_Quest_151": UnlikelyDuoScript,
    "BG24_Quest_311": CryForHelpScript,
    "BG24_Quest_313": InviteTheGuestsScript,
    "BG24_Quest_314": DustForPrintsScript,
    "BG24_Quest_318": WitnessProtectionScript,
    "BG24_Quest_320": ExhumeTheBonesScript,
    "BG24_Quest_351": HireAnInvestigatorScript,
    "BG24_Quest_352": CrackTheCaseScript,
    "BG27_Quest_800": BurnTheEvidenceScript,
    "BG27_Quest_801": PressureTheAuthoritiesScript,
    "BG27_Quest_802": RoundUpTheSuspectsScript,
    "BG28_Quest_500": FillTheCauldronScript,
}


def register() -> list[str]:
    """注册 19 张任务卡（DEFERRED 1 张见模块 docstring 台账）。"""
    from hsrl2.scripts.registry import register as reg

    for card_id in _QUESTS:
        reg(card_id, _SCRIPTS[card_id])
    return list(_QUESTS)
