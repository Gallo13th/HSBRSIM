"""批次 stats_gained — "Whenever a [friendly] X gains Attack" 家族
（2026-09-20; 引擎原语 `stats_gained` 落地轮）。

台账来源: `docs/agents/ENGINE_BACKLOG.md` §E（16 实体 = 8 基础 + 8 金色
的决策证据包）。本轮在该包基础上按项目所有者**权威序**（wiki 详细说明 >
卡面自然语言解读）完成触发域裁定并落地原语，逐卡判定如下。

═══════════════════════════════════════════════════════════════════════
  引擎原语（本轮新增，生产点唯一）
═══════════════════════════════════════════════════════════════════════
  `Entity.add_buff`（`entity.py`）在附魔入 `_buffs`、HEALTH 同步**之后**
  广播 `stats_gained(minion=, atk=, health=, permanent=, source=,
  source_id=)`（`hsrl2/events.py` 常量 `STATS_GAINED`）。逐字段语义与
  逐路径触发域裁定写在 `Entity.add_buff` 的 docstring（本批不再重复）;
  摘要:

  | §E2 路径 | 是否算"获得攻击力" | 理由 |
  |---|---|---|
  | #1 `add_buff` / #2 附魔 Action / #3 持久酒馆 buff 入馆 / #13 Dark Gift | **计入** | 附魔真正施加于实体 = 属性上升的唯一真实"获得"时刻 |
  | #4 `copy_buffs_to`（副本）/ #5 三连 `_combine` / #6 战斗快照复原重放 | **排除** | 复制/复原，不构成"获得"; 经 `suppress_stats_gained()` / `_restore_no_gain` 抑制（否则三连/战后各重复触发） |
  | #7 磁力相加 / #8 `SetStats` 覆盖 / #9 脚本直写 `BASE_ATK` / #10 `Transform` buff 整体转移 / #11 计算式光环 / #12 `atk` 动态钩子 / #14 血宝石移转直插 / #15 治疗 | **不计** | **不经** `add_buff` → 无"获得时刻"; 且多为覆盖/读时计算/位置搬移（非"增加"） |

  `source` 载荷 = 触发本次附魔的**来源实体**（`ActionQueue.resolve` 把队首
  Action 的 `source` 写入 `game._action_source` → 附魔携带）; 来源不可判定
  时为 None。BG21_018「from other sources」/ BG31_820「another friendly
  Pirate」/ BG26_966「a different friendly Dragon」的排除依据即此。

═══════════════════════════════════════════════════════════════════════
  本批注册 12 实体（6 卡 × 基础/金色）
═══════════════════════════════════════════════════════════════════════
  | id | 文本要点 | 数值 | 权威 |
  |---|---|---|---|
  | BG21_013 / `_G` Whelp Smuggler | friendly **Dragon** gains Attack → give it +N Health | num(0)=1/2 | 卡页 revid=907222（`?action=raw` 全文仅 Card template、**无 Notes/正文**）+ 自然语言 |
  | BG21_018 / `_G` Defiant Shipwright | this gains Attack **from other sources** → gain +num(1) Health（金 "twice"） | num(1)=1（基础/金色同值——金文本靠 "twice"） | 卡页 revid=800837（无 Notes）+ 自然语言; 金文本 Patch 34.6.0.235290 revid=904455 Dev Note |
  | BG25_027 / `_G` Hunter of Gatherers | this gains Attack → give your minions +N Health（**含自身**） | 字面量 2/4（num 全 None） | **官方 Blizzard 31.4.2 patch notes + wiki 卡页 revid=884903 + 本地 CardDefs 36.2.2（14 语言）三者一致 = "your minions"（无 "other"）**; 见下"**BG25_027 权威复核**" |
  | BG26_966 / `_G` Stormbringer | **a different** friendly Dragon gains Attack → this **also gains it**（金 twice） | 数值 = 事件增量（无 num） | 卡页 revid=804846（无 Notes）+ 自然语言; 金 "twice" = Patch 26.2.0.174258 上线口径 |
  | BG31_820 / `_G` Spacefarer | **another** friendly Pirate gains Attack → gain +N Health | 字面量 2/4 | 卡页 revid=830430（无 Notes）+ 自然语言 |
  | BG34_Giant_064 / `_G` Timewarped Whelp Smuggler | friendly **minion** gains Attack → give it +N Health | num(1)=3/6 | 卡页 revid=883775（无 Notes）+ Patch 34.4.2.234747 revid=901476（"+2 → +3"）+ 自然语言 |

  **BG25_027 权威复核（2026-09-20 对抗验证纠错——取代旧"数据陈旧"结论）**:
  上一轮（`f0426d5`）把本卡实现为 "give your **other** minions"（排除
  自身），理由是"本地数据陈旧"。该诊断**不成立**，权威证据如下:
    1. **官方 Blizzard 31.4.2 patch notes**（
       https://hearthstone.blizzard.com/en-us/news/24173976/31-4-2-patch-notes）
       逐字: "Hunter of Gatherers * Old: [Tier 4] 3/6. Whenever this gains
       Attack, give your minions +1 Health. * **New: [Tier 5] 3/5.
       Whenever this gains Attack, give your minions +2 Health.**"
       —— **无 "other"**。
    2. **wiki 卡页 `Battlegrounds/Hunter of Gatherers` revid=884903**
       （pageid=80454；wikitext 仅 `{{Card template v2}}`，正文由 dbfId
       95293 拉取）渲染: Regular "Whenever this gains Attack, give your
       minions +2 Health." / Golden "…give your minions +4 Health.";
       其 Patch changes 段同引 31.4.2.216149 "give your minions +2
       Health"（**无 "other"**）。
    3. **本地 `data/bg_cards.json`**（源自 `hsdata/CardDefs.xml`，build
       **249896 = 36.2.2，晚于 31.4.2**）: "Whenever this gains Attack,
       give your minions +2 Health."; CardDefs 全 **14 语言**（enUS/
       deDE/esES/esMX/frFR/itIT/jaJP/koKR/plPL/ptBR/ruRU/thTH/zhCN/
       zhTW）**均无 "other"**。
    4. **唯一反证**: wiki patch 文章 `Patch 31.4.2.216149` **revid=892585**
       写 "give your **other** minions +2 Health" —— 与官方原文、卡页、
       全部数据均矛盾，判定为**该 wiki 文章的孤立笔误（outlier）**。
       被否决的旧读法 "other"（排除自身）即源自此孤立行; 已纠正为
       "your minions"（**含自身**）。数值不变（2/4）。

  **wiki 金色文本 vs 本地数据（本轮记录，实现一律取数据）**: 三张卡的
  wiki 金色 infobox 文本与本地 `bg_cards.json` 不一致，实现取**本地数据**
  （CardDefs = 游戏内权威快照），显式记录以免静默:
    - `BG21_018_G` Defiant Shipwright: wiki 金色 "Whenever this gains
      Attack, gain +2 Health."（**丢 "from other sources"**、且写作一次
      +2）vs 本地数据 "Whenever this gains Attack **from other sources**,
      gain +{1} Health **twice**."（num(1)=1）。实现取数据: 保留
      "from other sources" 排除 + 两次独立 +1（"twice" 与金文本一致;
      对抗验证 2026-09-20）。
    - `BG34_Giant_064_G` Timewarped Whelp Smuggler: wiki 金色 "give it
      **+2** Health." vs 本地数据同文模板 `{1}` 且 `script_data_num_2`
      = **6**（卡页 fullTags 亦为 6）。实现取数据: 金色 = 一次 +6
      （`num(1)`=6）。
    - `BG34_111_G` Sepulchral Sergeant: wiki 金色 "Give your **minions**
      +4 Health."（**丢 "other"**、旧文本残留）vs 本地数据 "Give your
      **other** minions +{0} Health."（num(0)=4）。该卡 DEFERRED
      （不注册），裁定文本取数据 = "other"。

═══════════════════════════════════════════════════════════════════════
  DEFERRED 2 实体（不注册，理由随类 docstring）
═══════════════════════════════════════════════════════════════════════
  - `BG34_111` / `_G` Sepulchral Sergeant — "Improves permanently after
    this gains Attack!" 的**增量数值无权威**（XML 无 num 参数、wiki 卡页
    revid=883820 无 Notes）→ 无法精确实现（禁近似）。
  - `TB_BaconShop_HERO_52_Buddy` / `_G` Sinestra — Buddy 子系统整体未
    实现（ENGINE_BACKLOG #24）; 且需要"战斗内"边界（ENGINE_BACKLOG §E
    的 D8）。

**接线生命周期（本批统一，边界显式记录）**: 监听器在 `on_summon` 注册
（`Game.summon` 是招募/召唤的统一入口; 战斗开始时 `run_combat` 的
`events_snapshot` 已含该监听器 → 战后恢复保留，跨场有效）。**未接线
`on_transform`**: Transform 出的新实体由引擎重跑 `on_transform` 重接线
（RULES §6.21），本批不实现该钩子 → 变身后的新实体不再监听（边界，
非"no-op"——原实体路径完整）。另: **战斗中召唤**出的本族随从（战吼/亡语
召唤）其监听器落在战斗快照之外 → 战后随快照丢弃（既有引擎语义，
ENGINE_BACKLOG #30/#31/#32 的"战斗作用域注册"）。

**Register** 经 `batches/__init__` 自动发现执行。
"""

from __future__ import annotations

from hsrl2.actions import Buff
from hsrl2.events import STATS_GAINED, Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone


# ══════════════ 共用判定（4 卡共享） ══════════════


def _friendly(holder, minion) -> bool:
    """`minion` 是否为 `holder` 控制的**棋盘上**的友方随从。

    "friendly"/"your" = 同一控制者 **且 `zone is Zone.PLAY`**（RULES
    §7.4.2）。卡面 "friendly [X]"/"your minions" 在战棋触发语境下 =
    己方**棋盘**随从; 酒馆（`Zone.TAVERN`）随从属于 Bob、手牌
    （`Zone.HAND`）不是棋盘随从——上游事件若来自这两区（如 `TavernBuff`
    给酒馆随从加攻），本族监听器不应触发（2026-09-20 对抗验证:
    `_friendly` 旧实现只查 `controller`，一只**酒馆**龙被 `TavernBuff`
    加攻即触发棋盘上的 Whelp Smuggler 并给酒馆随从加生命 = 错误）。

    `controller` 为 None（无主）→ 不计。**边界记录**: `batch_quests.
    _friendly`（同款控制器判定）**未**加 `Zone.PLAY`——其事件域（任务
    计分事件）的实体已由各事件生产点限定在棋盘/明确域内，本轮不改动
    以避免超范围行为变更（共享助手分歧已在此显式记录）。
    """
    if not isinstance(minion, Minion) or holder is None:
        return False
    ctrl = minion.controller
    return (ctrl is not None and ctrl is holder
            and minion.zone == Zone.PLAY)


# ══════════════ BG21_013 / _G Whelp Smuggler ══════════════


# ── 记录订正（第四轮 stats_gained 对抗验证, 2026-09-20） ──
# 1. 上文三处"wiki 金色文本 vs 本地数据"的记录**已撤回**: 引用的是**历史
#    页面文本**; 当前 wiki 金色卡页与本地数据**一致**——
#    [Defiant_Shipwright_(golden)](https://hearthstone.wiki.gg/wiki/Battlegrounds/Defiant_Shipwright_(golden))
#    oldid=800838 "…gain +1 Health twice",
#    [Timewarped_Whelp_Smuggler_(golden)](https://hearthstone.wiki.gg/wiki/Battlegrounds/Timewarped_Whelp_Smuggler_(golden))
#    oldid=883170 "give it +6 Health",
#    [Sepulchral_Sergeant_(golden)](https://hearthstone.wiki.gg/wiki/Battlegrounds/Sepulchral_Sergeant_(golden))
#    oldid=882855 "Give your other minions +4 Health"。
#    金色卡页须用 `…_(golden)` URL: 裸 id 形式 `…_G` 的**标题不存在**（既不重定向到基础页也不渲染金色文本; 对抗验证实测）,
#    其 "Golden" 标签渲染的是**过时**文本（oldid 本身正确）。
#    实现取本地数据的选择未被推翻, 但"wiki 与数据冲突"的表述不成立。
# 2. 语言数订正: CardDefs build 249896 共 **14 个语系**（上文误记 13）。
# 3. `ActionQueue` 逐动作来源重置的补充披露: 既有**已注册卡的可观测结果**
#    不变, 但**嵌套监听授予**中 stats_gained 的 `source` 载荷会变化
#    （例如 Whelp 授予的 buff 现为 source=None 而非触发动作的来源）——
#    全量套件未覆盖该链路, 故不宜表述为"无任何行为变化"。

class WhelpSmugglerScript:
    """
    Natural language: Whenever a friendly **Dragon** gains Attack,
    give it +1 Health.（金色 +2）

    Authority: wiki 卡页 `Battlegrounds/Whelp_Smuggler` revid=907222
    （`?action=raw` 全文仅 `{{Card template v2}}`——**无 Notes、无正文**，
    故"哪些路径算获得攻击力"无 wiki 明文）→ 按卡面自然语言解读;
    触发域裁定见本模块 docstring 与 `Entity.add_buff` docstring。
    数值 = `num(0)`（基础 1 / 金色 2; 本地数据与卡页 dbfId=72072 一致）。
    观察者 = 打出的这只 Whelp Smuggler 本体（非"家族光环"）。

    Formal spec:
      1. `on_summon` 注册 `stats_gained` 监听（owner=source → 离场自动
         注销; 幂等 `_sg_wired` 防 `on_transform` 重入双注册）
      2. 触发条件: `atk > 0` ∧ `_friendly(holder, minion)` ∧
         `minion.has_race(DRAGON)`（"friendly **Dragon**"；类型身份集合
         读取——双类型随从与家族类型改写（825 Smuggler Portrait）均命中，
         ALL = Amalgam 经 `race_set` 展开为全 10 族同样命中）
      3. 效果: `Buff(minion, health=num(0), source=source)`——**给获得
         攻击力的那只随从**加生命（文本 "give **it**"）
      4. 仅生命增益 → `atk == 0` → 不再触发本事件（无递归）

    Test: test_batch_stats_gained.py::TestWhelpSmuggler — 真实
      `play_minion` + 真实 `Buff` 作用于龙触发; 非龙不触发（负对照）;
      仅得生命不触发（负对照）; 对手的龙不触发; 三连不重复触发;
      金色给 +2（num 自然体现）; 变异探针 4 项

    Params: {0}=1（金色 2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        if getattr(source, "_sg_wired", False):
            return None
        source._sg_wired = True
        amount = game.db.get(source.card_id).num(0)
        owner = source

        def on_gain(g, minion=None, atk=0, health=0, source=None, **kw):
            if atk <= 0 or not _friendly(owner.controller, minion):
                return
            # 类型身份集合（AC-3）——825 Smuggler Portrait 使本家族
            # （Whelp Smuggler）成为 Dragon，"friendly **Dragon**" 应按
            # 身份命中（含 ALL 展开）。
            if not minion.has_race(Race.DRAGON):
                return
            g.run_actions(Buff(minion, health=amount))

        game.events.register(Listener(
            event=STATS_GAINED, owner=source, callback=on_gain))
        return None


# ══════════════ BG21_018 / _G Defiant Shipwright ══════════════


class DefiantShipwrightScript:
    """
    Natural language: [x]Whenever this gains Attack **from other
    sources**, gain +1 Health.@[x]...gain +0/+1.（金色: "...gain +1
    Health **twice**."）

    Authority: 卡页 `Battlegrounds/Defiant_Shipwright` revid=800837
    （无 Notes/正文）→ 自然语言解读。金色 "twice" 的官方口径见
    Patch 34.6.0.235290 revid=904455 Dev Note: "The Golden versions of
    all Pirates that give stats have been changed to trigger the regular
    effect **twice**, rather than doubling the buff."（= 金文本
    "gain +{1} Health twice"，非 +2 一次）。

    数值 = `num(1)`（基础 1 / 金色 1——金文本靠 "twice"; 注意本卡模板
    参数是 **{1}**（`num(1)`）不是 `num(0)`——`{0}` 只出现在升级段
    `+{0}/+{1}` 的攻击位）。本卡不在酒馆池（`is_pool_minion=False`），
    当前仅作"每当……获得攻击力"原语的真实消费点。

    **wiki 金色文本 vs 数据（显式记录）**: wiki 卡页 revid=800837 的
    金色 infobox 文本是 "Whenever this gains Attack, gain +2 Health."
    （**丢 "from other sources"**、且写作一次 +2），而本地 `bg_cards.json`
    的金色文本是 "…**from other sources**, gain +{1} Health **twice**."
    （`num(1)`=1）。**实现取本地数据**: 保留 "from other sources" 排除 +
    两次独立 +1（金文本 "twice" 语义; 与卡片模板参数一致）。

    "from other sources" 的读法（与 rejected 替代）: 取得攻击力的
    **来源实体不是本体**。来源由 `stats_gained.source` 给出
    （`ActionQueue.resolve` 的 `game._action_source`）:
      - 本体自己的增益（自战吼 / 自亡语 / 自身效果经 `Buff` Action）
        → `source is 本体` → **不计**
      - 他者（法术 / 队友随从 / 饰品 / 英雄技能 / 血宝石效果）
        → `source` 是他实体 → **计**
      - **来源不可判定（`source is None`）→ 计**（"from other sources"
        的排除项只排除"自身"这一确定情形; 把 None 当自身会漏触发，
        把 None 当"非自身"是唯一不臆造来源的读法）
      - **rejected 替代**: (a) "自身脚本直接写的增益"当作 other
        （无法区分、且卡面说的是来源不是通道）; (b) 把来源不可判定当
        "非 other"（会静默吞掉真实触发）; (c) 按 `buff.source_id` 是否
        等于本体卡 id 判定（同卡多只时误判）。

    Formal spec:
      1. `on_summon` 注册 `stats_gained`（owner=source）
      2. 触发条件: `atk > 0` ∧ `minion is source` ∧
         (事件 `source` 不是本体)
      3. 效果: 基础 `Buff(source, health=num(1))` 一次; 金色注册
         `times=2` 两次独立 `Buff`（"twice" 语义 = 两次触发，
         与 `batch_rally2.HeroicUnderdogGoldenScript` 等 "twice" 同构）
      4. 仅生命增益不触发本事件（`atk == 0`）→ 无递归

    Test: test_batch_stats_gained.py::TestDefiantShipwright — 真实
      `game.run_actions(Buff(...))` 无来源触发; 带 `source=本体` **不**
      触发（负对照，"from other sources"）; 带 `source=他者` 触发;
      仅生命不触发; 金色两次; 变异探针 4 项

    Params: {1}=1（基础/金色同值; 金色靠 twice）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        if getattr(source, "_sg_wired", False):
            return None
        source._sg_wired = True
        amount = game.db.get(source.card_id).num(1)
        times = 2 if source.is_golden else 1
        owner = source

        def on_gain(g, minion=None, atk=0, health=0, source=None, **kw):
            me = owner
            if atk <= 0 or minion is not me:
                return
            if source is me:
                return              # "from other sources" 排除自身
            for _ in range(times):
                g.run_actions(Buff(me, health=amount))

        game.events.register(Listener(
            event=STATS_GAINED, owner=source, callback=on_gain))
        return None


# ══════════════ BG25_027 / _G Hunter of Gatherers ══════════════


class HunterOfGatherersScript:
    """
    Natural language: Whenever this gains Attack, give your minions
    +2 Health.（金色 +4）

    Authority: **官方 Blizzard 31.4.2 patch notes**（
    https://hearthstone.blizzard.com/en-us/news/24173976/31-4-2-patch-notes）
    "New: [Tier 5] 3/5. Whenever this gains Attack, give your minions
    +2 Health."（**无 "other"**）; wiki 卡页
    `Battlegrounds/Hunter_of_Gatherers` revid=884903（pageid=80454，
    正文由 dbfId 95293 拉取）Regular "…give your minions +2 Health." /
    Golden "…give your minions +4 Health."，Patch changes 段同引无
    "other"; 本地 `hsdata/CardDefs.xml`（build 249896 = 36.2.2）enUS
    "give your minions +2 Health"，14 语言全无 "other"。**唯一反证**:
    wiki patch 文章 `Patch 31.4.2.216149` revid=892585 写 "your
    **other** minions"（孤立笔误）——上一轮据其实现 "other"（排除自身）
    即本卡缺陷，已按上述三条一致证据纠正。

    读法与 rejected 替代: "your minions" = 己方**棋盘上全部存活随从**
    （**含本体自身**——本体刚获得攻击力，文本未写 "other"）。
    **rejected**: (a) "other"（排除自身）——否决: 仅一条 wiki patch
    文章支持，与官方原文 + 卡页 + 全部本地数据矛盾; (b) 排除本体以免
    自增益递归——否决: 本效果只加生命（`atk == 0`），不触发本事件，
    无需靠排除自身防递归。

    Formal spec:
      1. `on_summon` 注册 `stats_gained`（owner=source）
      2. 触发条件: `atk > 0` ∧ `minion is source`（"this gains Attack"）
      3. 效果: 对 `holder.board` 上**全部存活随从（含本体）**各
         `Buff(m, health=amount)`（"your minions"）
      4. 仅生命增益不触发（`atk == 0`）→ 无递归

    Test: test_batch_stats_gained.py::TestHunterOfGatherers — 真实
      `play_minion` 后自身获得攻击触发全场（**含自身** +2）; 只给自己
      +生命不触发; 对手棋盘不受影响; 金色 +4; 变异探针

    Params: 字面量 2（金色 4; data 无脚本参数）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        if getattr(source, "_sg_wired", False):
            return None
        source._sg_wired = True
        amount = 4 if source.is_golden else 2
        owner = source

        def on_gain(g, minion=None, atk=0, health=0, source=None, **kw):
            holder = owner.controller
            if atk <= 0 or minion is not owner or holder is None:
                return
            targets = [m for m in list(holder.board) if not m.dead]
            if not targets:
                return
            g.run_actions([Buff(m, health=amount) for m in targets])

        game.events.register(Listener(
            event=STATS_GAINED, owner=source, callback=on_gain))
        return None


# ══════════════ BG26_966 / _G Stormbringer ══════════════


class StormbringerScript:
    """
    Natural language: After a different friendly Dragon gains Attack,
    this also gains it.（金色 "...this also gains it **twice**."）

    Authority: 卡页 `Battlegrounds/Stormbringer` revid=804846
    （`?action=raw` 仅 Card template、无 Notes）→ 自然语言; 金文本
    "twice" 为 Patch 26.2.0.174258 上线口径（该期 patch 文本即含
    "this also gains it" / 金色 twice）。本地数据无模板参数 → 数值必须
    由**事件增量**给出（`stats_gained.atk`——ENGINE_BACKLOG §E D3 的
    数值载荷需求）。

    "a different friendly Dragon" 三条件:
      - "friendly" = 同控制者
      - "Dragon" = `minion.has_race(DRAGON)`（类型身份集合：双类型 /
        家族类型改写命中；ALL 经 `race_set` 展开为全 10 族）
      - "**different**" = 不是本体（`minion is not 本体`）

    Formal spec:
      1. `on_summon` 注册 `stats_gained`（owner=source）
      2. 触发条件: `atk > 0` ∧ `_friendly(holder, minion)` ∧
         `minion is not source` ∧ `minion.has_race(DRAGON)`
      3. 效果: `Buff(source, atk=atk)` **N 次**（"also gains **it**" =
         获得**同样的攻击增量**; 基础 1 次 / 金色 2 次 = 金文本 "twice"）
      4. 本效果只加攻击 → 会给**其它** Stormbringer 制造新事件
         （多个 Stormbringer 相互追加——官方"also gains it"的自然结果，
         有限收敛: 每次增加量按来源增量，不回指自身）

    Test: test_batch_stats_gained.py::TestStormbringer — 真实路径下另一只
      友方龙 +3 攻击 → 本体 +3 攻击（数值拷贝）; 本体自己获得攻击**不**
      触发（"different"）; 非龙不触发; 对手的龙不触发; 金色 +3 两次
      （= +6）; 变异探针（增量改成固定 1 必须失败）。
      类型身份读取点（F2）: test_engine_primitives.py::
      test_stormbringer_counts_dualtype_and_portrait_dragons — 双类型
      `BG27_005`（PIRATE+DRAGON）与 Smuggler Portrait 家族 Whelp 均触发，
      基础单类型龙为对照。

    Params: 无模板参数（数值来自事件载荷）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        if getattr(source, "_sg_wired", False):
            return None
        source._sg_wired = True
        times = 2 if source.is_golden else 1
        owner = source

        def on_gain(g, minion=None, atk=0, health=0, source=None, **kw):
            me = owner
            if atk <= 0 or minion is me:
                return
            if not minion.has_race(Race.DRAGON):
                return
            if not _friendly(owner.controller, minion):
                return
            for _ in range(times):
                g.run_actions(Buff(owner, atk=atk))

        game.events.register(Listener(
            event=STATS_GAINED, owner=source, callback=on_gain))
        return None


# ══════════════ BG31_820 / _G Spacefarer ══════════════


class SpacefarerScript:
    """
    Natural language: Whenever **another** friendly Pirate gains Attack,
    gain +2 Health.（金色 +4）

    Authority: 卡页 `Battlegrounds/Spacefarer` revid=830430
    （`?action=raw` 仅 Card template、无 Notes）→ 自然语言。数值 =
    文本字面量 2/4（data num 全 None）。

    "another friendly Pirate":
      - "another" = 不是本体（`minion is not 本体`）
      - "friendly" = 同控制者
      - "Pirate" = `minion.has_race(PIRATE)`（类型身份集合；ALL 经
        `race_set` 展开为全 10 族——与 `_aura_atk` 同口径。本卡文本是
        "another friendly **Pirate**"，非"of type"，双类型随从按 wiki
        `Multi-type minion` revid 855346 "benefit from the effects of
        both types" 命中）

    Formal spec:
      1. `on_summon` 注册 `stats_gained`（owner=source）
      2. 触发条件: `atk > 0` ∧ `minion is not source` ∧
         `_friendly(holder, minion)` ∧ `minion.has_race(PIRATE)`
      3. 效果: `Buff(source, health=amount)`——本体**自己**加生命
         （"gain +2 Health"）
      4. 仅生命增益不触发本事件 → 无递归

    Test: test_batch_stats_gained.py::TestSpacefarer — 真实路径下另一只
      友方海盗 +攻触发; 本体自己 +攻不触发（"another"）; 非海盗不触发;
      对手海盗不触发; 金色 +4; 变异探针（去掉 another 过滤必须失败）

    Params: 字面量 2（金色 4; data 无脚本参数）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        if getattr(source, "_sg_wired", False):
            return None
        source._sg_wired = True
        amount = 4 if source.is_golden else 2
        owner = source

        def on_gain(g, minion=None, atk=0, health=0, source=None, **kw):
            if atk <= 0 or minion is owner:
                return
            if not minion.has_race(Race.PIRATE):
                return
            if not _friendly(owner.controller, minion):
                return
            g.run_actions(Buff(owner, health=amount))

        game.events.register(Listener(
            event=STATS_GAINED, owner=source, callback=on_gain))
        return None


# ══════════════ BG34_Giant_064 / _G Timewarped Whelp Smuggler ══════


class TimewarpedWhelpSmugglerScript:
    """
    Natural language: [x]Whenever a friendly **minion** gains Attack,
    give it +{1} Health.（金色同文、`num(1)`=6）

    Authority: 卡页 `Battlegrounds/Timewarped_Whelp_Smuggler` revid=883775
    （`?action=raw` 仅 Card template + 派生图、无 Notes）; 数值取
    Patch 34.4.2.234747 revid=901476: "{{bl|Timewarped Whelp Smuggler}}
    * Old: Whenever a friendly minion gains Attack, give it +2 Health.
    * New: ... give it **+3** Health." → `num(1)`=3（基础）/6（金色，
    数据核实）。局部数据与卡页 dbfId=126754 一致。

    **wiki 金色文本 vs 数据（显式记录）**: wiki 卡页金色 infobox 文本是
    "Whenever a friendly minion gains Attack, give it **+2** Health."
    （旧文残留），而本地 `bg_cards.json` 金色文本与基础同文（`{1}`）且
    `script_data_num_2` = **6**（卡页 fullTags 亦为 `TAG_SCRIPT_DATA_NUM_2=6`）。
    **实现取本地数据**: 金色 = 一次 `num(1)`=6（非 +2）。

    与 `BG21_013` 的差异: 种族过滤 = **任意友方随从**（无类型限制），
    数值模板位是 `{1}`（`num(1)`）。

    Formal spec:
      1. `on_summon` 注册 `stats_gained`（owner=source）
      2. 触发条件: `atk > 0` ∧ `_friendly(holder, minion)`（无类型过滤）
      3. 效果: `Buff(minion, health=num(1))`——"give **it**"
      4. 仅生命增益不触发（`atk == 0`）→ 无递归

    Test: test_batch_stats_gained.py::TestTimewarpedWhelpSmuggler — 真实
      路径下无类型/任意类型友方随从获得攻击触发; 仅生命不触发; 对手随从
      不触发; 金色 num(1)=6（数据自然体现）; 变异探针

    Params: {1}=3（金色 6）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        if getattr(source, "_sg_wired", False):
            return None
        source._sg_wired = True
        amount = game.db.get(source.card_id).num(1)
        owner = source

        def on_gain(g, minion=None, atk=0, health=0, source=None, **kw):
            if atk <= 0 or not _friendly(owner.controller, minion):
                return
            g.run_actions(Buff(minion, health=amount))

        game.events.register(Listener(
            event=STATS_GAINED, owner=source, callback=on_gain))
        return None


# ══════════════ DEFERRED（不注册） ══════════════


class SepulchralSergeantScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Give your other minions
    +{0} Health. <i>(Improves permanently after this gains Attack!)</i>

    Status: **DEFERRED** — "Improves permanently after this gains Attack!"
    的**增量数值无权威**（禁近似实现）。

    Authority 与缺口:
      - 卡页 `Battlegrounds/Sepulchral_Sergeant` revid=883820
        （`?action=raw` 仅 Card template——**无 Notes**，未说明每次获得
        攻击力提升多少）;
      - 本地数据 = `script_data_num_1`=2（基础）/4（金色）——只钉死
        **亡语基础值** `num(0)`，无任何"提升量"参数（`num(1..4)` 全
        None）; CardDefs 无 `TAG_SCRIPT_DATA_NUM_*` 承载提升量;
      - Patch 34.2.2.233025 revid=884356 只改文本（"your minions" →
        "your **other** minions"），未给提升量;
      - 文本自身不明: 每次 +1? +2（= 基础值）? 按获得量?
      - 亡语本体（`num(0)` + "other"）本身可实现，但整卡注册会引入
        "注册但提升条款 no-op"的第三态（铁律禁止）→ 整卡 DEFERRED。
      - **wiki 金色文本 vs 数据（显式记录）**: 卡页 revid=883820 的金色
        infobox 文本 "Give your **minions** +4 Health."（旧文残留，丢
        "other"）vs 本地数据 "Give your **other** minions +{0} Health."
        （`num(0)`=4）。本卡未注册，若未来解冻则文本取**本地数据**
        （"other"）。

    Dependency: 提升增量的权威数值（wiki Notes 或 CardDefs 参数）。
    Implementation path: 拿到数值后 `deathrattle` 钩子给
      `holder.board` 除自身外存活随从 `Buff(health=counter)`，并注册
      `stats_gained`（`minion is source` ∧ `atk > 0`）使
      `counter += 增量`（永久、跨场; 仅生命加成不触发 → 无递归）。

    Test: 不注册（DEFERRED）——无行为测试; 台账守卫见
      test_batch_stats_gained.py::TestDeferred

    Params: {0}=2（金色 4）; 提升量 = **无参数**（阻塞项）
    """


class SinestraScript:
    """
    Natural language: Whenever a friendly minion gains Attack **during
    combat**, give it +1 Health **permanently**.（金色 +2）

    Status: **DEFERRED** — Buddy 子系统整体未实现。

    Authority 与缺口:
      - 卡页 `Battlegrounds/Sinestra` revid=907187（`?action=raw` 仅
        Card template——无 Notes）; 上线口径见 Patch 29.6.0.201108
        "{{bl|Deathwing}} – {{bl|Sinestra}} [Tier 4, Dragon] * 2/6.
        Whenever a friendly minion gains Attack during combat, give it
        +1 Health permanently."（与本地数据一致）;
      - `TB_BaconShop_HERO_52_Buddy` 是**英雄伙伴（Buddy）**: 伙伴按钮 /
        进度 / 三份获取 / 金色伙伴整套子系统未实现（ENGINE_BACKLOG
        #24）——即使效果本体可实现，该实体也**无法在游戏中被取得**
        （注册 = 不可达的第三态）;
      - 第二重缺口（ENGINE_BACKLOG §E D8）: "**during combat**" 边界
        ——战斗内 `add_buff` 会广播 `stats_gained`（`game.in_combat`
        可判），但 "permanently"（跨战斗保留）在 Buddy 语境下还需
        `Buff(persist=True)` 通道的 Buddy 侧确认。

    Dependency: Buddy 子系统（获取/进度/金色）; 之后按 `game.in_combat`
      过滤 `stats_gained` + `Buff(health=1, persist=True)`。
    Implementation path: 见上。**不注册**（引擎不可达 + 前置系统缺失）。

    Test: 不注册（DEFERRED）——台账守卫见
      test_batch_stats_gained.py::TestDeferred

    Params: 无模板参数（+1/+2 为文本字面量）
    """


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG21_013", WhelpSmugglerScript)
    _add("BG21_013_G", WhelpSmugglerScript)       # 金色 num(0)=2 自然体现
    _add("BG21_018", DefiantShipwrightScript)     # num(1)=1
    _add("BG21_018_G", DefiantShipwrightScript)   # 金色 "twice" = times=2
    _add("BG25_027", HunterOfGatherersScript)     # 字面量 +2
    _add("BG25_027_G", HunterOfGatherersScript)   # 金色字面量 +4
    _add("BG26_966", StormbringerScript)          # 数值来自事件增量
    _add("BG26_966_G", StormbringerScript)        # 金色 "twice"
    _add("BG31_820", SpacefarerScript)            # 字面量 +2
    _add("BG31_820_G", SpacefarerScript)          # 金色字面量 +4
    _add("BG34_Giant_064", TimewarpedWhelpSmugglerScript)    # num(1)=3
    _add("BG34_Giant_064_G", TimewarpedWhelpSmugglerScript)  # 金色 6
    return registered
