"""批次 trinkets19 — 饰品第 19 批（台账 `docs/agents/TRINKET_LEDGER.md`
片 5/6 子集，20 张）。

本批 20 个 id 与 batch_trinkets1..18 的 id 集合互不相交；数值一律
`CardDef.num(0/1)`，金色走 `db.golden_version`，随机一律 `game.rng`
（`rng.choice` / `rng.sample`），无 `import random`。

注册 13 张饰品 + 2 张 Spellcraft 法术本体（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG35_MagicItem_821  Kaleidoscope          — Discover 一张 Tier 7 随从，
                                              并锁入手牌 num(0)=2 回合
  BG35_MagicItem_838  Double Stitch Needle  — Spellcraft（法术本体 838t）
  BG35_MagicItem_838t Double Stitch         — 定向: 友方随从属性翻倍 →
                                              收回手牌并锁定 1 回合
  BG35_MagicItem_840  Chromatic Tear        — Get num(0)=1 张随机
                                              Chromadrake; 每回合重复
  BG35_MagicItem_842  Egg of the Endtimes Portrait — Get 一张; 每 num(1)=2
                                              回合开始重复
  BG35_MagicItem_849  Cloud Serpent Horn    — Avenge(num(0)=3): 最右随从的
                                              攻击力给另一条友方龙
  BG35_MagicItem_850  Pocket Cyclone        — Cast Easterly Winds; 每回合
                                              开始再施放一次
  BG35_MagicItem_852  Lightning in a Bottle — 酒馆刷新后，最高攻随从的
                                              属性给最低攻随从
  BG35_MagicItem_861  Baller Portrait       — Get Temperature Shift; 每打出
                                              num(1)=10 张元素重复
  BG35_MagicItem_863  Avalanche Sticker     — Get Mounting Avalanche; 每卖出
                                              num(1)=4 个随从重复
  BG35_MagicItem_870  Leapfrogger Portrait  — Get a Timewarped Leapfrogger
  BG35_MagicItem_872  Ophidian Staff        — Spellcraft（法术本体 872t）
  BG35_MagicItem_872t Ophidian Staff        — 定向: 一只野兽 +2/+2 与 Reborn
  BG35_MagicItem_924  Groundbreaker Portrait — Get a Groundbreaker; 你的
                                              Groundbreaker 的增益同时给
                                              其左边随从
  BG35_MagicItem_925  Coral Spear           — 每施放 Spellcraft 法术 →
                                              Cast Might of Stormwind

DEFERRED 7 张（**不注册**；逐张给出缺失依赖与实现路径——SOP §6b 二态铁律）
═══════════════════════════════════════════════════════════════════════
  - BG35_MagicItem_820 Safety Patch — "Cast Ice Block. Gain {0}=5 Gold."
    Dependency: **Secrets 子系统缺失**。关联卡 `TB_Bacon_Secrets_12`
    Ice Block = "Secret: When your hero takes fatal damage, prevent it and
    become Immune this turn."——全仓 grep `secret` 零命中: 无 Secret 区域、
    无致命伤害预防钩子、无该法术脚本（REGISTRY 未注册）。`cast_spell_effect`
    对无脚本法术只做"创建实体 + 无 on_play"→ 该半场 100% 空转（SOP §12
    item 14「引擎机制就绪 ≠ 效果可兑现」）。金币半场（GainGold num(0)）
    已就绪但**不得单独注册**（整卡半实现 = 第三态）。
    实现路径: 引擎实现 Secret 协议（`hero.secrets` 区域 + HERO_DAMAGE_TAKEN
    前的致命伤害预防读取点）→ 注册 `TB_Bacon_Secrets_12` 脚本 → 本卡
    on_bind = `[GainGold(h, num(0)), cast_spell_effect(h, 关联卡)]`。
  - BG35_MagicItem_823 Timeworn Candelabra — "Discover a 2-Cost minion
    from the Minor Timewarp."
    Dependency: **"Minor Timewarp" 集合无数据定义域**。XML 只有
    `BACON_TIMEWARPED`(4503) 这一"时空扭曲过"布尔标记，无 Minor/Major
    之分；`tools/generate_bg_data.py` 的 TAG 表虽含 4503 但**无任何读取
    点**（bg_cards.json 零 `timewarped` 字段）。wiki 页
    （Battlegrounds/Timeworn_Candelabra_(Lesser)）无 Notes/Related cards
    段，仅 `BACON_TIMEWARP_TOOLTIP` / `DISCOVER` / Timewarp-related 标签。
    无法从权威数据确定候选集 → 禁止按卡名/档位猜测（SOP §6b 第 4 步）。
    实现路径: 生成器导出 Minor Timewarp 成员标记（如
    `BACON_TIMEWARP_TOOLTIP`(4701) 或专用 subset 字段）→ 候选 =
    `db` 中该集合 ∧ `cost == 2`（`BACON_SHOW_COST_ON_DISCOVER` 已证实按
    费用展示）→ 3 选 1 Discover。
  - BG35_MagicItem_834 Rylak Portrait — "Get a Rylak Metalhead. Start of
    Combat: Trigger your Rylak Metalheads' Deathrattles."
    Dependency: **载荷行为未就绪**（RULES §7.4.6 例外条）。关联卡
    `BG26_801` Rylak Metalhead（"Taunt. Deathrattle: Trigger the Battlecry
    of an adjacent minion."）未注册（REGISTRY 无 id）→ SoC 遍历 `hero.board`
    的 Rylak 调 `run_script_hook(m, "deathrattle")` 只会得到 None，整卡
    第二句 100% 空转。实现路径: 迁移 `BG26_801`/`BG26_801_G`（战吼重触发
    协议 `TriggerBattlecry` 已就绪）+ 引擎公开"战斗内触发指定随从亡语"
    入口（或在 SoC 内以 `run_script_hook(m, "deathrattle", ctx=...)` 结算）
    → 本卡 on_bind 交付关联卡、SoC 对每个 Rylak Metalhead 触发其亡语。
  - BG35_MagicItem_920 Bubble Crown — "Once you cast {1} spells, your
    Tavern spells give an extra +{2}/+{4}. ({0} left!)"
    Dependency: **TAG_SCRIPT_DATA_NUM_5 无数据通道**。XML
    （dbf 130898）: NUM_1=12、NUM_2=12、NUM_3=4、**NUM_5=4**；{4} 占位符
    映射 NUM_5，而 `CardDef` 只导出 NUM_1..4（`tools/generate_bg_data.py`
    L227-238）→ `num(3) is None`，硬编码违反数值纪律（SOP §16b item 25
    同款，batch_trinkets17 `ThornspikePauldronScript` 先例）。
    实现路径: 生成器导出 `script_data_num_5`（+ `CardDef.num(4)`）后，
    on_bind 注册监听"施放法术"计数达 num(1)=12 → 一次性写
    `hero.TAVERN_SPELL_EXTRA_ATK/HEALTH += (num(2), num(4))`（消费点
    `tavern_spell_buff` 已就绪）。同卡还需裁定"cast spells"口径
    （全法术 vs `TAVERN_SPELLS_CAST_THIS_GAME` 仅池法术）。
  - BG35_MagicItem_921 Cowrie Necklace — "Tavern spells that give stats
    cost (2) less."
    Dependency: **"give stats" 法术效果类别无定义域**。`TAVERN_SPELL_COST_MOD`
    （RULES §7.4.5）是 hero 级**无条件**持久折扣（Buy 路径
    game.py:538 `cost = max(0, cost - pers)`），无"仅按效果类别"的读取点；
    数据层无任何"给属性"标记（对照 XML: `BG34_444`/`BG35_951` 与不 give
    stats 的池法术标签集无差异）。按卡面文本解析法术文本属近似（SOP §6b
    禁止）——batch_trinkets8 模块 docstring 已就**同一张卡**备案同一缺口。
    实现路径: 引擎/数据层为"give stats"池法术标注类别（如生成器导出
    `gives_stats` 位）→ `buy_from_tavern` 增按类别折扣读取点（
    `hero.TAVERN_SPELL_COST_MOD_STATS`）。
  - ~~BG35_MagicItem_922 Tide Raiser Portrait~~ **已解冻（2026-09-17，
    `batch_trinkets38` 注册）**: 原台账两条阻塞均为**过期陈述**——
    (a) "战斗内施法不可观察" 不成立: `cast_spell_effect`（`game.py`
    L1488/L1493）无条件广播 `spell_resolving`/`spell_resolved`，战斗
    上下文经 `game.in_combat` 判定（`StalwartKodoScript` 既有口径）;
    (b) 载荷 `BG34_920`/`_G` 已由 `batch_payload_minions` 注册（其亡语
    正是战斗内 `cast_spell_effect`）。
  - ~~BG35_MagicItem_923 Bewitched Ribbon~~ **已解冻（2026-09-18，
    `batch_trinkets31` 注册）**: 原台账两条阻塞均为**过期陈述**——
    (a) "NUM_5 无数据通道" 已订正: `script_data_num_5` 已由生成器导出
    （`CardDef.num(4)`，见 `hsrl2/defs.py` docstring / ENGINE_BACKLOG
    §A6b 订正），实测 num(0..4)=1/1/2/None/2;
    (b) "while in combat" 的永久份量由 `Buff(persist=True)` 按来源跨
    战斗持久化精确表达（RULES §3.5 例外 4）; 时点用 `spell_resolving`
    （per-cast，含战斗内 `cast_spell_effect`），非 `card_played`。

机制口径（本批实现所依赖的既有原语）
══════════════════════════════════════════════════════════════════════
  - 关联卡数据链: `CardDef.evolution_card_id` → `CardDB.by_dbf`
    （`game.trinket_related_card` / `grant_trinket_related_card`，
    RULES §7.4.6）。池随从/池法术按池占返，池外卡零池操作，满手排队。
  - 效果施法: `game.cast_spell_effect(hero, card_id, target=None)`
    （RULES §7.4.7b）——不经手牌/不动法术池/不广播手牌事件；定向法术
    无合法目标 → 落空返回 False。**本轮新原语解锁了 batch_trinkets8 曾
    因 `game.cast_spell_by_id` 缺失而 DEFERRED 的 850/925**。
  - "After the Tavern is Refreshed" 是被动句式（对照 Frigid Blossom 的
    "you Refresh"）→ **自动与手动刷新都触发**（batch_trinkets17
    `CursedCrystalScript` 同裁定；`tavern_refresh(hero=, auto=)`）。
  - "After your first N … repeat this" 计数家族 = source 实体属性计数器，
    在 num(1) 次到达时归零并再次交付（batch_trinkets18
    `LensCaseScript` 同构）。
  - LOCKED_IN_HAND（SOP §10）: `play_minion`/`play_spell` 均拒绝打出;
    解锁用 TURN_START once 链（batch_hero_actives Maiev "After 2 turns" =
    2 tick; batch_spells_final `DiscoverOwnTierLocked` "for 1 turn" =
    1 tick）。
  - Spellcraft: 饰品实体参与每回合生成（`spellcraft.generate_for_hero`
    扫描 `hero.board + hero.trinkets + hero.quest_rewards`；`create_entity`
    依 `CardDef.spellcraft_id` 打 SPELLCRAFT tag）。脚本只在 on_bind 给
    第一张（RULES §6.13），**不得**再写 start_of_turn（防双发）。
  - Avenge: 饰品无 AVENGE tag，以类属性 `avenge_threshold` 声明；引擎对
    棋盘 + `hero.trinkets` + `hero.quest_rewards` 统一计数，**仅战斗内**、
    每场战斗清零（RULES §6.11）。
  - 属性快照: "double its stats" = `atk` / `max_health`（SOP §3）;
    "give the stats" = `Buff(target, atk=src.atk, health=src.max_health)`。

接线审计读取点（W1/W2/W3 核对）: 饰品仅定义 `on_bind` / `start_of_turn`
/ `start_of_combat` / `avenge`（W1 白名单）；两张法术本体只定义
`on_play` / `target_candidates`（spell 白名单）。监听事件名均为引擎真实
fire: `card_played`（game.py:804/908/1297）、`minion_sold`（game.py:757）、
`tavern_refresh`（game.py:494）、`spellcraft_cast`（game.py:1238）、
`turn_start`（game.py:287）。脚本侧状态只写 `source.*` 实体属性
（`_egg_n` / `_baller_n` / `_avalanche_n`），不写 game 级 flag
（SOP §12 item 9）。

关联卡台账（RULES §7.4.6——交付正确即 CORRECT，关联卡脚本状态另行跟踪）
══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链 dbf → id） | 被授予卡脚本状态 |
  |---|---|---|
  | BG35_MagicItem_820 | 58512 → TB_Bacon_Secrets_12 Ice Block | **未迁移**（Secret——整卡已 DEFERRED） |
  | BG35_MagicItem_838 | spellcraft 131315 → BG35_MagicItem_838t | **本批注册** |
  | BG35_MagicItem_840 | 无数据链（"Chromadrake" 家族） | BG34_634t..638t 五张**均未迁移**（池外 Timewarped; 本卡不依赖其行为，仅登记） |
  | BG35_MagicItem_842 | 126848 → BG34_639 Egg of the Endtimes | **未迁移**（池外随从; "Get a X" 不阻塞） |
  | BG35_MagicItem_850 | 126909 → BG34_444 Easterly Winds | 已注册（本批按其 on_play 结算） |
  | BG35_MagicItem_861 | 117670 → BG31_819 Temperature Shift | 已注册 |
  | BG35_MagicItem_863 | 122862 → BG33_899 Mounting Avalanche | 已注册 |
  | BG35_MagicItem_870 | 126513 → BG34_Giant_031 Timewarped Leapfrogger | **未迁移**（池外随从; 仅登记） |
  | BG35_MagicItem_872 | spellcraft 130909 → BG35_MagicItem_872t | **本批注册** |
  | BG35_MagicItem_922 | 126629 → BG34_920 Tide Raiser | 已注册（batch_trinkets38） |
  | BG35_MagicItem_924 | 114816 → BG31_035 Groundbreaker（+ _G） | 已注册（本批按同一公式镜像其增益） |
  | BG35_MagicItem_925 | 131152 → BG35_951 Might of Stormwind | 已注册（本批按其 on_play 结算） |
  | BG35_MagicItem_834 | 98829 → BG26_801 Rylak Metalhead | **未迁移**（整卡已 DEFERRED） |
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff, GainKeyword
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    CARD_PLAYED,
    MINION_SOLD,
    TAVERN_REFRESH,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.queue import Action
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

# ── 数据核实常量（CardDB 按名核实; SOP §11 教训 5——禁止凭记忆写 id）──

# "Chromadrake" 家族（bg_cards.json 按名核实，5 张**池外** Timewarped 随从:
# Blue/Black/Green/Bronze/Red Chromadrake——`is_pool_minion=False`，
# 交付零池操作; 金色版 BG34_63x_Gt 不在此列）。无数据链字段（840 的
# `evolution_card_id` 为 None），故按名核对后写成常量（Errgl Sticker
# `_PAPA_MRRGLTON` / Sky Pirate `BGS_061t` 同款先例）。
_CHROMADRAKE_IDS = (
    "BG34_634t", "BG34_635t", "BG34_636t", "BG34_637t", "BG34_638t",
)

# Groundbreaker 本体（CardDB 按名核实: 基础 + 金色独立卡定义; 两者的
# num(0)=3 / num(1)=1|2 是"也把属性给左边随从"的数值权威）。
_GROUNDBREAKER_IDS = ("BG31_035", "BG31_035_G")

# 种族匹配族（Amalgam ALL 视为匹配，RULES §8/§6.4 通用裁定）
_BEAST_RACES = (Race.BEAST, Race.ALL)
_DRAGON_RACES = (Race.DRAGON, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)

# Ophidian Staff 法术的印面值（"Give a Beast +2/+2 and Reborn"——XML/文本
# 无 {0}/{1} 占位符、CardDef num 全 None → 文本字面量，SOP §3 允许）
_OPHIDIAN_BONUS = 2

# 锁手牌的回合数语义: "Lock it in your hand for N turns" 用 N 个 TURN_START
# once tick（Maiev "After 2 turns"=2 tick / Search Through Time "1 turn"=
# 1 tick——batch_hero_actives、batch_spells_final 先例）。
_TURN_TICK = 1


def _hero(ctx):
    return (ctx or {}).get("hero")


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _grant_related(game, hero, source) -> bool:
    """`game.grant_trinket_related_card`（RULES §7.4.6）数据链交付。

    数据链断裂 → GameStateError（fail-loud，禁止近似——SOP §6b）。
    """
    if game.trinket_related_card(source.card_id) is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    return game.grant_trinket_related_card(hero, source.card_id)


def _schedule_unlock(game, entity, turns: int) -> None:
    """`turns` 个 TURN_START once tick 后清除 `LOCKED_IN_HAND`。

    - 链式 once 监听（owner=被锁实体——卡被移出手牌即自动注销，
      Search Through Time 同构）; 每 tick 注册下一环，最后一环清 tag
    - 条件绑定控制者（闭包默认参数防晚绑定，SOP §11 item 1）:
      对手的 turn_start 不消耗本链
    """
    def clear(g, hero=None, **kw):
        entity.clear(GameTag.LOCKED_IN_HAND)

    callback = clear
    for _ in range(max(1, int(turns)) - 1):
        inner = callback

        def step(g, hero=None, _inner=inner, _owner=entity, **kw):
            g.events.register(Listener(
                event=TURN_START, owner=_owner, once=True,
                condition=lambda hero=None, _h=_owner.controller, **kw:
                    hero is _h,
                callback=_inner))

        callback = step
    game.events.register(Listener(
        event=TURN_START, owner=entity, once=True,
        condition=lambda hero=None, _h=entity.controller, **kw: hero is _h,
        callback=callback))


# ══════════════ BG35_MagicItem_821 Kaleidoscope ══════════════


class DiscoverTier7Locked(Action):
    """Kaleidoscope: Discover 一张 Tier 7 随从并锁入手牌 num(0) 回合。

    - 候选 = `_pool_candidates(game, min_tier=7)`（显式越档——RULES/
      `_pool_candidates` 契约: 标准局 `max_tavern_tier=6`，只有显式
      `min_tier=7` 才能抽到 Tier 7; 36.2.2 池内 12 张 T7 随从）; 无候选
      → 落空（不产生 PendingChoice）
    - 预留语义与 `Discover` 一致: 选项生成即 `minion_pool.acquire` 占池、
      resolve 保留选中 / 释放其余（SOP §13 item 5）
    - resolve: `create_minion` → `LOCKED_IN_HAND` → `pending_hand_add`
      （满手排队 RULES §3.3）→ `_schedule_unlock(turns)`（num(0) 个
      TURN_START tick）
    """

    def __init__(self, hero, turns: int) -> None:
        self.hero = hero
        self.turns = int(turns)

    def do(self, game) -> None:
        cands = _pool_candidates(game, min_tier=7)
        if not cands:
            return
        k = min(3, len(cands))
        drawn = game.rng.sample(cands, k, label="kaleidoscope_options")
        options = [cid for cid in drawn if game.minion_pool.acquire(cid)]
        if not options:
            return
        hero = self.hero
        turns = self.turns

        def resolve(pick_id: str) -> None:
            if pick_id not in options:
                raise GameStateError(
                    f"Kaleidoscope: pick {pick_id} 不在提供选项中 {options}")
            for cid in options:
                if cid != pick_id:
                    game.minion_pool.release(cid, 1)
            m = game.create_minion(pick_id, controller=hero)
            m.set(GameTag.LOCKED_IN_HAND, True)
            game.pending_hand_add(hero, m)
            _schedule_unlock(game, m, turns)

        game.pending_choices.append(PendingChoice(
            hero, list(options), "discover_minion", resolve_callback=resolve))


class KaleidoscopeScript:
    """
    Natural language: [x]<b>Discover</b> a Tier 7 minion.
    Lock it in your hand for
    {0} |4 (turn, turns).

    Evidence: `data/bg_trinkets.json BG35_MagicItem_821`（lesser, cost 1,
    num(0)=2）。wiki.gg Battlegrounds/Kaleidoscope 无 Notes（只有 Wiki
    tags DISCOVER/Generate）; 多语言文本一致（ruRU "блокируете его в
    вашей руке на 2 хода" / zhCN "将其锁入你的手牌2回合"）→ "for {0}
    turns" 是**锁定回合数**，非"Discover 次数"。
    锁定 tick 口径与 batch_hero_actives Maiev（"After 2 turns" = 2 个
    TURN_START tick）、batch_spells_final `DiscoverOwnTierLocked`
    （"for 1 turn" = 1 tick）同源。

    Formal spec:
      1. on_bind: 返回 `DiscoverTier7Locked(hero, num(0))`（Action 经
         `run_script_hook` → `run_actions` 结算）
      2. Discover: 选项 = `_pool_candidates(min_tier=7)` rng.sample 3;
         无 T7 候选 → 落空（无 PendingChoice、不占池）
      3. resolve: 选中 `minion_pool.acquire`（占池 1 份）→ 实体带
         `LOCKED_IN_HAND`（`play_minion` 拒绝打出）→ 入手（满手排队）
      4. 解锁: num(0)=2 个 TURN_START tick 后清除 LOCKED_IN_HAND
         （绑定当回合不计数; 第 2 个招募阶段开始可打出）
      5. 只作用于本人（对手的 turn_start 不消耗解锁链、对手手牌不受影响）

    Test: test_batch_trinkets19.py — 绑定后出现 kind="discover_minion"
      的 PendingChoice、选项数恰 3 且每个选项 tech_level==7 / 选定后手牌
      +1 且带 LOCKED_IN_HAND、池 -1（其余选项回池）/ 锁定期间
      `play_minion` 返回 False / 第 1 个 turn_start 仍锁、第 num(0) 个
      解锁后可打出 / 对手 turn_start 不解锁（owner 隔离）/ 池内 T7 抽干
      时落空不占池

    Params: {0}=2（BG35_MagicItem_821 num(0)，锁定回合数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return DiscoverTier7Locked(h, _num(game, source.card_id, 0))


# ══════════════ BG35_MagicItem_838 Double Stitch Needle（Spellcraft） ══════════════


class DoubleStitchNeedleScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Choose a
    friendly minion. Double
    its stats and lock it in your
    hand for 1 turn.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_838`（greater, cost 1,
    `spellcraft_id=131315 → BG35_MagicItem_838t`）。RULES §6.13: 饰品实体
    参与每回合 Spellcraft 生成（`spellcraft.generate_for_hero` 扫描
    `hero.trinkets`；`create_entity` 依 `spellcraft_id` 打 SPELLCRAFT
    tag）。

    Formal spec:
      1. on_bind: 获得时立即给第一张 Spellcraft 法术
         （`grant_spellcraft_spell(source, game)`——RULES §6.13 "获得法术
         塑造时立即获得第一张"; 饰品版先例 batch_trinkets2 Harvested
         Pearl / batch_trinkets18 Jailer Sticker）。**每回合**再次生成由
         **引擎**负责，脚本不得再写 start_of_turn（否则同回合双发）
      2. 实效由法术本体 `DoubleStitchSpellScript`（BG35_MagicItem_838t）
         完成: 定向一只友方随从 → 属性翻倍 → 收回手牌并锁定 1 回合
      3. 该法术是临时 Spellcraft 法术（未使用则回合结束丢弃），引擎处理

    Test: test_batch_trinkets19.py — 绑定后手牌恰 +1 张
      `BG35_MagicItem_838t` 且带 SPELLCRAFT tag / 脚本类**未**定义
      start_of_turn（防双发）/ 下一招募阶段 `generate_for_hero` 恰再
      生成 1 张 / 对手手牌不受影响

    Params: 无模板参数（法术 id 经 `CardDef.spellcraft_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)
        return None


class DoubleStitchSpellScript:
    """
    Natural language: Choose a friendly minion. Double its stats and lock
    it in your hand for 1 turn.

    Evidence: `data/bg_cards.json BG35_MagicItem_838t`（card_type=5,
    spell_school=10 Spellcraft, 无 {0}/{1} 模板参数）。**多语言文本裁定
    "it" 的所指**（SOP §6b 查证）: koKR "그 하수인의 능력치를 2배로
    증가시키고 **내 손으로 가져와** 1턴 동안 잠금 상태로 만듭니다" / ruRU
    "Оно **возвращается в руку** c удвоенными характеристиками и
    блокируется на 1 ход" / zhCN "使其属性值翻倍，并将其锁入你的手牌1个
    回合"——即目标随从（棋盘上）属性翻倍后**收回手牌**并锁定 1 回合
    （enUS 省略了 "returns to your hand"，单看英文有歧义）; wiki 卡页
    refTags 亦含 **Hand-related**。

    Formal spec:
      1. needs_target=True（"Choose a friendly minion" = 定向选择）——
         候选 = 引擎默认（施放者棋盘存活随从）
      2. on_play: 目标必须仍是本人棋盘上的存活随从（挂起期离场 → 落空，
         SOP §16 item 24）
      3. 属性翻倍 = `Buff(target, atk=target.atk, health=target.max_health)`
         （生命快照用 max_health，SOP §3）→ 净效果 atk/上限 ×2
      4. 收回手牌: `hero.board.remove` + `_update_positions` +
         `pending_hand_add`（满手排队不销毁 RULES §3.3; 实体保留全部 buff）
      5. 锁定 1 回合: `LOCKED_IN_HAND` + 1 个 TURN_START tick（与
         Search Through Time "for 1 turn" 同口径）
      6. 只作用于本人棋盘/手牌; 池不涉及（随从本已属于该玩家，非获取）

    Test: test_batch_trinkets19.py — 打出后目标离板、入手、atk/max_health
      各翻倍且带 buff / 带 LOCKED_IN_HAND 时 `play_minion` False、1 个
      turn_start 后可打出 / 对手随从不可选（target_candidates 只含本人）/
      陈旧目标（挂起期已离场）落空不抛错 / 满手时目标进等待队列

    Params: 无模板参数（"Double" 由运行时属性快照表达）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or not isinstance(target, Minion) \
                or target.dead or target not in hero.board:
            return None
        game.run_actions(Buff(target, atk=target.atk,
                              health=target.max_health))
        hero.board.remove(target)
        game._update_positions(hero)
        target.set(GameTag.LOCKED_IN_HAND, True)
        game.pending_hand_add(hero, target)
        _schedule_unlock(game, target, _TURN_TICK)
        return None


# ══════════════ BG35_MagicItem_840 Chromatic Tear ══════════════


class ChromaticTearScript:
    """
    Natural language: [x]Get a random
    <b>Chromadrake.</b>
    At the start of each turn,
    repeat this.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_840`（lesser, cost 2,
    num(0)=1, `subset_dragon`; `evolution_card_id=None`——无单卡数据链）。
    "Chromadrake" 是 5 张**池外** Timewarped 随从的家族名（bg_cards.json
    按名核实: BG34_634t..638t Blue/Black/Green/Bronze/Red Chromadrake,
    `is_pool_minion=False`）→ 交付零池操作（RULES §7.4.6 非池卡条款）。
    同名升级版 `BG35_MagicItem_840t`（Greater）文本为 "Get 2 random
    Chromadrakes. After you play {1} Battlecry minions, repeat this."——
    另一张卡，本批不涉及。

    Formal spec:
      1. on_bind: 交付 num(0)=1 张随机 Chromadrake
         （`game.rng.choice(五张)` → `grant_card_copy_to_hand`——非池卡
         零池操作 + `create_minion` + `pending_hand_add` 满手排队）
      2. start_of_turn: 每个招募阶段重复同样交付（"At the start of each
         turn, repeat this"）
      3. 每次交付独立随机（文本无 "different"，且每张触发只抽 1 张——
         重复语义只出现在多次触发之间，RULES §7.4.8 的互异口径不适用）
      4. 只进本人手牌（owner 隔离）; 池不涉及（五张均非池卡，交付不改
         变 `minion_pool.available`）

    Test: test_batch_trinkets19.py — 绑定后手牌 +num(0) 张且 card_id ∈
      五张 Chromadrake（池数不变=正对照）/ 每次 start_of_turn 恰再 +1 张
      （不双发）/ 对手手牌不受影响 / 五张卡脚本状态登记（未迁移=台账）

    Params: {0}=1（BG35_MagicItem_840 num(0)，每次交付张数）
    """

    @staticmethod
    def _grant(game, hero, count: int) -> int:
        defs = [d for d in (game.db.get(cid) for cid in _CHROMADRAKE_IDS)
                if d is not None]
        granted = 0
        for _ in range(count):
            if not defs:
                break
            d = game.rng.choice(defs, label="chromatic_tear")
            if game.grant_card_copy_to_hand(hero, d):
                granted += 1
        return granted

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        ChromaticTearScript._grant(game, h, _num(game, source.card_id, 0))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        ChromaticTearScript._grant(game, h, _num(game, source.card_id, 0))
        return None


# ══════════════ BG35_MagicItem_842 Egg of the Endtimes Portrait ══════════════


class EggOfTheEndtimesPortraitScript:
    """
    Natural language: [x]Get an Egg of the Endtimes.
    At the start of every {1} turns,
    repeat this. <i>({0} |4(turn, turns) left!)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_842`（lesser, cost 2,
    num(0)=2 num(1)=2, `evolution_card_id=126848 → BG34_639 Egg of the
    Endtimes`——池外随从）。cadence 口径与 batch_trinkets18
    `LensCaseScript`（"At the start of every {1} turns, repeat this"）
    一致: 计数达 num(1) 触发一次。

    Formal spec:
      1. on_bind: 关联卡交付 1 张（`grant_trinket_related_card`——池外
         随从零池操作 + `pending_hand_add`）; 计数 `source._egg_n = 0`
      2. start_of_turn: 计数 +1; 达 num(1)=2 → 归零并再交付 1 张
         （绑定当回合不计数; 首次重复在第 num(1) 次回合开始）
      3. 只进本人手牌; 绑定前已过的回合不追溯; 对手不受影响

    Test: test_batch_trinkets19.py — 绑定后手牌 +1 张 BG34_639（池不变）/
      第 1 个 start_of_turn 无新卡、第 num(1) 个恰 +1 张 / 再满 num(1)
      回合再发一张（滚动）/ 对手手牌不变 / `_egg_n` 周期归零

    Params: {0}=2 {1}=2（BG35_MagicItem_842 num(0)=倒计时显示 /
            num(1)=重复周期）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        source._egg_n = 0
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        every = _num(game, source.card_id, 1)
        n = getattr(source, "_egg_n", 0) + 1
        if n < every:
            source._egg_n = n
            return None
        source._egg_n = 0
        _grant_related(game, h, source)
        return None


# ══════════════ BG35_MagicItem_849 Cloud Serpent Horn ══════════════


class CloudSerpentHornScript:
    """
    Natural language: [x]<b>Avenge ({0}):</b> Give the
    Attack of your right-most
    minion to another
    friendly Dragon.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_849`（greater, cost 3,
    num(0)=3, `avenge_target=3`, `subset_dragon`）。多语言一致（zhCN "使
    另一条友方的龙获得你最右边的随从的攻击力" / deDE "einem **anderen**
    befreundeten Drachen"）→ 目标是"除最右者之外的另一条友方龙"。
    "another friendly Dragon" 无 "Choose"/无 wiki [Targeted] → 随机
    （SOP §9 目标语义裁决库: "a different friendly X" 随机先例）。

    Formal spec:
      1. Avenge 阈值 = num(0)=3 = 类属性 `avenge_threshold`（饰品实体无
         AVENGE tag，引擎对 `hero.trinkets` 统一计数、**仅战斗内**、每场
         清零——RULES §6.11）; 类属性无法在 import 期读 CardDef，测试钉死
         `CloudSerpentHornScript.avenge_threshold == num(0)`
      2. avenge: 最右存活随从 = `_living(hero)[-1]`; 候选 = 本人棋盘存活
         龙（race ∈ (DRAGON, ALL)）**且不是最右者实体**; 无候选 / 空板
         → 落空（不产生 Action）
      3. 最右者攻击力 ≤ 0 → 无值可给，落空（不产生空 Buff）
      4. 目标 = `game.rng.choice(候选)`; 增益 = `Buff(target,
         atk=最右者.atk)`——**只给攻击力**（文本无 Health）; "Give"
         = 永久增益（非 temporary）
      5. 只作用于本人（对手死亡不计数、对手龙不获得属性）

    Test: test_batch_trinkets19.py — 战斗内 num(0)-1 次友方死亡不触发、
      第 num(0) 次恰触发（正对照）/ 另一条龙 +最右者攻击力且最右者自身
      不变、无龙时落空（不抛错）/ 最右者若是唯一龙 → 无"另一条"落空 /
      招募期死亡不计数（阶段守卫）/ 对手龙不受影响 / Avenge 计数每场
      清零（真实 run_combat 两次）

    Params: {0}=3（BG35_MagicItem_849 num(0)，即 Avenge 阈值）
    """

    avenge_threshold = 3   # == CardDef.num(0)（测试钉死）

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = _living(h)
        if not living:
            return None
        right = living[-1]
        if right.atk <= 0:
            return None
        cands = [m for m in living
                 if m is not right and m.race in _DRAGON_RACES]
        if not cands:
            return None
        target = game.rng.choice(cands, label="cloud_serpent_horn")
        return Buff(target, atk=right.atk)


# ══════════════ BG35_MagicItem_850 Pocket Cyclone ══════════════


class PocketCycloneScript:
    """
    Natural language: Cast Easterly Winds.
    At the start of each turn, cast it again.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_850`（lesser, cost 3,
    `evolution_card_id=126909 → BG34_444 Easterly Winds`——**已注册**的池
    法术，on_play 注册持久 `tavern_refresh` 监听）。batch_trinkets8 曾因
    `game.cast_spell_by_id` 缺失把本卡列入 DEFERRED; 本轮引擎新增
    `game.cast_spell_effect`（RULES §7.4.7b）后**解冻**。

    Formal spec:
      1. on_bind: `cast_spell_effect(hero, 关联卡)`——效果施法（不经手牌/
         不耗金币/不动法术池/不广播手牌事件）; EasterlyWinds 的 on_play
         以 `source.controller` 为锚注册持久刷新监听 → 该次施放成为
         一份"本局持续"效果
      2. start_of_turn: 再施放一次（"At the start of each turn, cast it
         again"）——每次施放都是**独立**的一份持续效果（监听逐份叠加，
         与官方"每次施放各注册一份"一致）
      3. 关联卡无定向需求 → 无目标落空问题; 数据链断裂 → fail-loud
      4. 只作用于本人酒馆（EasterlyWinds 回调按 `hero is` 过滤）

    Test: test_batch_trinkets19.py — 绑定后本人酒馆刷新使馆内随从
      +num(0)/num(1)（正对照: 无饰品不变）/ 每次 start_of_turn 后再注册
      一份（同一回合两次刷新各 +1 次，验证逐份叠加）/ 对手刷新不触发
      本人效果 / 未绑定英雄刷新无加成

    Params: 无模板参数（法术 id 经 `CardDef.evolution_card_id` 数据链;
            数值由 BG34_444 的 num(0)/num(1) 决定）
    """

    @staticmethod
    def _cast(source, game) -> bool:
        h = source.controller
        if h is None:
            return False
        rd = game.trinket_related_card(source.card_id)
        if rd is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        return game.cast_spell_effect(h, rd.id)

    @staticmethod
    def on_bind(source, game, ctx):
        PocketCycloneScript._cast(source, game)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        PocketCycloneScript._cast(source, game)
        return None


# ══════════════ BG35_MagicItem_852 Lightning in a Bottle ══════════════


class LightningInABottleScript:
    """
    Natural language: After the Tavern is <b>Refreshed</b>, give the
    stats of its highest-Attack minion to its lowest.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_852`（lesser, cost 3,
    num 全 None, `subset_demon` + `subset_elementals`）。多语言一致
    （zhCN "使其中攻击力最低的随从**获得**其中攻击力最高的随从的属性值"
    / ruRU "существо с самой низкой атакой … получает характеристики
    существа с самой высокой атакой"）→ 是**给予**（增益），非"移转"
    （源不损失）。文本无 "another/different" → 目标就是馆内最低攻者，
    与最高攻者相同实体时按文本字面**自我加倍**（单随从酒馆亦然）。

    Formal spec:
      1. on_bind 注册持久 `tavern_refresh` 监听（owner=饰品）: 引擎在
         酒馆**填充完成后**广播（game.py:494 `tavern_refresh(hero=,
         auto=)`）。"After the Tavern is Refreshed" 是被动句式（对照
         Frigid Blossom 的 "you Refresh"）→ **自动与手动刷新都算**
         （batch_trinkets17 `CursedCrystalScript` 同裁定）
      2. 候选 = 本人 `hero.tavern` 内非死亡 `Minion`; 空馆 → 落空
      3. hi = 攻击力最高者（并列 `rng.choice`，Training Certificate
         `_pick_extreme` 先例）; lo = 攻击力最低者（同）
      4. `Buff(lo, atk=hi.atk, health=hi.max_health)`——"the stats of X"
         = 攻击力 + 属性生命上限（SOP §3）; 永久增益（购买后随实体带走）
      5. 只作用于本人酒馆（回调 `hero is 绑定者` 过滤; 防闭包晚绑定）

    Test: test_batch_trinkets19.py — 真实刷新后馆内最高攻者的 atk/
      max_health 加到最低攻者、最高攻者自身不变（正对照: 无饰品不变）/
      单随从酒馆按文本自我加倍 / 空馆落空不抛错 / 对手刷新不触发本人
      酒馆 / 并列最低攻时确定性（构造 0 攻敌人排除随机）/ 自动刷新
      （auto=True）同样触发

    Params: 无模板参数（增益 = 运行时属性快照）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_refresh(g, hero=None, _h=h, **kw):
            if hero is not _h:
                return
            minions = [e for e in _h.tavern
                       if isinstance(e, Minion) and not e.dead]
            if not minions:
                return
            hi_atk = max(m.atk for m in minions)
            lo_atk = min(m.atk for m in minions)
            hi_tied = [m for m in minions if m.atk == hi_atk]
            lo_tied = [m for m in minions if m.atk == lo_atk]
            hi = (hi_tied[0] if len(hi_tied) == 1
                  else g.rng.choice(hi_tied, label="lightning_hi"))
            lo = (lo_tied[0] if len(lo_tied) == 1
                  else g.rng.choice(lo_tied, label="lightning_lo"))
            g.run_actions(Buff(lo, atk=hi.atk, health=hi.max_health))

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=source, callback=on_refresh))
        return None


# ══════════════ BG35_MagicItem_861 Baller Portrait ══════════════


class BallerPortraitScript:
    """
    Natural language: [x]Get a Temperature Shift.
    After you play {1} Elementals,
    repeat this. <i>({0} left!)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_861`（greater, cost 6,
    num(0)=10 num(1)=10, `evolution_card_id=117670 → BG31_819 Temperature
    Shift`——已注册的池法术）。计数家族口径: 每打出 num(1) 张元素交付
    一次并复位（batch_trinkets18 `LensCaseScript` / batch_trinkets5
    `GoldenizerSupplyScript` 同构）。

    Formal spec:
      1. on_bind: 关联卡交付 1 张（池法术 → `spell_pool.acquire` 占池 1
         份，池空 → 该次落空）; 计数 `source._baller_n = 0`
      2. 注册持久 `card_played` 监听（owner=饰品）: `card` 是 Minion、
         `controller is 本人`、`race ∈ (ELEMENTAL, ALL)`（Amalgam 计入
         ——RULES §8; 引擎无 `elemental_played` fire，经 `card_played`
         判别，Nomi Sticker / batch_hero_passives2 先例）→ 计数 +1
      3. 计数达 num(1)=10 → 归零并再交付 1 张; 未达 → 只记数
      4. 只作用于本人（对手打出元素不计数）; 满手排队不销毁

    Test: test_batch_trinkets19.py — 绑定后手牌 +1 张 BG31_819 且法术池
      -1 / 打出 num(1)-1 张元素不发放、第 num(1) 张发放（正对照）且计数
      复位 / 打出非元素不计数 / 对手打出元素不计数（owner 隔离）/ 池空
      时该次交付落空（不抛错）

    Params: {0}=10 {1}=10（BG35_MagicItem_861 num(0)=倒计时显示 /
            num(1)=重复周期）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        source._baller_n = 0
        every = _num(game, source.card_id, 1)

        def on_played(g, card=None, _h=h, **kw):
            if not isinstance(card, Minion) or card.controller is not _h:
                return
            if card.race not in _ELEMENTAL_RACES:
                return
            n = getattr(source, "_baller_n", 0) + 1
            if n < every:
                source._baller_n = n
                return
            source._baller_n = 0
            _grant_related(g, _h, source)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ══════════════ BG35_MagicItem_863 Avalanche Sticker ══════════════


class AvalancheStickerScript:
    """
    Natural language: [x]Get a Mounting Avalanche.
    After you sell {1} minions,
    repeat this. <i>({0} left!)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_863`（greater, cost 1,
    num(0)=4 num(1)=4, `evolution_card_id=122862 → BG33_899 Mounting
    Avalanche`——已注册的池法术）。计数家族同 Baller Portrait /
    `LensCaseScript`。

    Formal spec:
      1. on_bind: 关联卡交付 1 张（池法术 → 占池 1 份，池空落空）;
         计数 `source._avalanche_n = 0`; 注册持久 `minion_sold` 监听
         （owner=饰品）
      2. 触发条件: 被售随从 `controller is 本人`（`minion_sold` 在实体
         移出棋盘/回池**之前** fire，controller 仍有效——batch_econ_misc2
         Twisted Wrathguard 同构）
      3. 计数达 num(1)=4 → 归零并再交付 1 张; 未达 → 只记数
      4. 只作用于本人（对手出售不计数）; 满手排队不销毁

    Test: test_batch_trinkets19.py — 绑定后手牌 +1 张 BG33_899 且法术池
      -1 / 真实 `sell_minion` num(1)-1 次不发放、第 num(1) 次发放（正
      对照）且计数复位 / 对手出售不计数（owner 隔离）/ 池空时落空

    Params: {0}=4 {1}=4（BG35_MagicItem_863 num(0)=倒计时显示 /
            num(1)=重复周期）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        source._avalanche_n = 0
        every = _num(game, source.card_id, 1)

        def on_sold(g, minion=None, _h=h, **kw):
            if minion is None or minion.controller is not _h:
                return
            n = getattr(source, "_avalanche_n", 0) + 1
            if n < every:
                source._avalanche_n = n
                return
            source._avalanche_n = 0
            _grant_related(g, _h, source)

        game.events.register(Listener(
            event=MINION_SOLD, owner=source, callback=on_sold))
        return None


# ══════════════ BG35_MagicItem_870 Leapfrogger Portrait ══════════════


class LeapfroggerPortraitScript:
    """
    Natural language: Get a Timewarped Leapfrogger.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_870`（lesser, cost 1,
    num 全 None, `evolution_card_id=126513 → BG34_Giant_031 Timewarped
    Leapfrogger`——池外 Timewarped 随从，`is_pool_minion=False`）。

    Formal spec:
      1. on_bind: 关联卡白板副本进手牌
         （`grant_trinket_related_card` → 非池卡零池操作 + `create_minion`
         + `pending_hand_add` 满手排队）。RULES §7.4.6: 本卡效果即"交付
         卡 X"，交付正确即 CORRECT; X 自身脚本未迁移（BG34_Giant_031
         未注册）只登记台账，本卡效果**不依赖**其行为
      2. 只进本人手牌（owner 隔离）

    Test: test_batch_trinkets19.py — 绑定后手牌恰 +1 张 BG34_Giant_031
      （池不变——非池卡正对照）/ 对手手牌不受影响 / 关联卡定义经数据链
      解析正确

    Params: 无模板参数（关联卡经 `CardDef.evolution_card_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        return None


# ══════════════ BG35_MagicItem_872 Ophidian Staff（Spellcraft） ══════════════


class OphidianStaffScript:
    """
    Natural language: <b>Spellcraft:</b> Give a Beast +2/+2 and <b>Reborn</b>.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_872`（lesser, cost 5,
    `spellcraft_id=130909 → BG35_MagicItem_872t`, `subset_beast`）。
    RULES §6.13: 饰品实体参与每回合 Spellcraft 生成; 脚本只在 on_bind
    给第一张，**不得**再写 start_of_turn（防双发）。

    Formal spec:
      1. on_bind: `grant_spellcraft_spell(source, game)`——立即获得第一张
         法术（RULES §6.13; Harvested Pearl / Jailer Sticker 先例）
      2. 实效由法术本体 `OphidianStaffSpellScript`（BG35_MagicItem_872t）
         完成: 定向一只友方野兽 → +2/+2 且获得 Reborn
      3. 临时 Spellcraft 法术的回合结束丢弃由引擎处理

    Test: test_batch_trinkets19.py — 绑定后手牌恰 +1 张
      `BG35_MagicItem_872t` 且带 SPELLCRAFT tag / 脚本类未定义
      start_of_turn（防双发）/ 下一招募阶段恰再生成 1 张 / 对手不受影响

    Params: 无模板参数（法术 id 经 `CardDef.spellcraft_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)
        return None


class OphidianStaffSpellScript:
    """
    Natural language: <b>Spellcraft:</b> Give a Beast +2/+2 and
    <b>Reborn</b>.

    Evidence: `data/bg_cards.json BG35_MagicItem_872t`（card_type=5,
    spell_school=10 Spellcraft; XML 无 TAG_SCRIPT_DATA_* → CardDef num
    全 None，文本为字面量 "+2/+2"（SOP §3: 模板参数缺失且文本无占位符时
    可字面量）。

    Formal spec:
      1. needs_target=True（"Give a Beast" = 定向选择）——
         `target_candidates` = 施放者棋盘存活**野兽**（race ∈ (BEAST,
         ALL)）; 无野兽 → 引擎无候选（法术照常消耗、无 PendingChoice）
      2. on_play: 目标必须仍是本人棋盘上存活的野兽（挂起期离场/变种族 →
         落空，SOP §16 item 24）
      3. 效果 = `[Buff(target, atk=2, health=2), GainKeyword(target,
         REBORN)]`——"Give" = 永久增益（非 temporary），关键词走
         `GainKeyword`（fire keyword_gained，keyword 生命周期由引擎管）
      4. 只作用于本人棋盘; 对手野兽不可为目标（target_candidates 只扫
         `source.controller.board`）

    Test: test_batch_trinkets19.py — 打出后目标野兽 +2/+2 且带 REBORN
      （期望值 = `_OPHIDIAN_BONUS`）/ 非野兽不在候选中（PendingChoice
      选项只含野兽）/ 无野兽时无 PendingChoice 且法术照常消耗（落空不
      消耗资源以外的东西）/ 对手野兽不受影响 / 陈旧目标落空

    Params: atk=health=2（文本字面量 "+2/+2"——CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = source.controller
        if hero is None:
            return []
        return [m for m in _living(hero) if m.race in _BEAST_RACES]

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or not isinstance(target, Minion) \
                or target.dead or target not in hero.board \
                or target.race not in _BEAST_RACES:
            return None
        return [Buff(target, atk=_OPHIDIAN_BONUS, health=_OPHIDIAN_BONUS),
                GainKeyword(target, GameTag.REBORN)]


# ══════════════ BG35_MagicItem_924 Groundbreaker Portrait ══════════════


class GroundbreakerPortraitScript:
    """
    Natural language: [x]Get a Groundbreaker.
    Your Groundbreakers also
    give stats to the minion
    to their left.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_924`（greater, cost 5,
    num 全 None, `evolution_card_id=114816 → BG31_035 Groundbreaker`——
    **已注册**的池随从 T6，基础 + 金色 `BG31_035_G` 共用
    `GroundbreakerScript`）。多语言一致（zhCN "你的碎地者还会使其左边的
    随从获得属性值" / ruRU "также дают характеристики существам слева от
    них"）→ "the stats" = Groundbreaker 本次触发**获得的**那份属性
    （+num(1)×倍率/+num(1)×倍率），"also give" = 额外再给左边随从同一份。

    Formal spec:
      1. on_bind: 关联卡交付 1 张（池随从 → `minion_pool.acquire` 占池）;
         注册持久 `card_played` 监听（owner=饰品）
      2. 触发条件与 `GroundbreakerScript` **逐字同构**（本体脚本
         batch_econ_misc 已验收）: `card` 是 Minion、`controller is
         本人`、`race ∈ (NAGA, ALL)`
      3. 对本人棋盘每个 Groundbreaker（`card_id ∈ _GROUNDBREAKER_IDS`，
         基础/金色各读自身 CardDef）:
         `mult = 1 + hero.TAVERN_SPELLS_CAST_THIS_GAME // num(0)`、
         `amount = num(1) × mult`（数值权威 = 该实体自己的 CardDef，
         金色 num(1)=2 自然体现）
      4. 左边随从 = `hero.board[index - 1]`; Groundbreaker 已在最左 /
         左侧实体已死 → 跳过该个体（不越界、不产生 Action）
      5. 每个 Groundbreaker 各自结算（多个则各给左邻一份）;
         只作用于本人棋盘（对手打 Naga / 对手 Groundbreaker 不触发）
      6. 这是"改写他卡行为"的**只读镜像**实现: 不改写本体的脚本或
         状态，只按同一公开公式（CardDef.num + hero tag + 引擎事件）
         对左邻复算一次——测试以"左邻增量 == Groundbreaker 自身增量"
         钉死两者同步（公式漂移即红）

    Test: test_batch_trinkets19.py — 真实打出 Naga 后 Groundbreaker 自身
      +num(1)×mult（本体行为正对照）且左邻获得**同量**、右邻不变 /
      Groundbreaker 在最左时无左邻（不越界、本体照常增益）/ 打出非 Naga
      不触发 / 对手打 Naga 不触发（owner 隔离）/ 金色 Groundbreaker 的
      左邻获得 num(1)=2×mult（金色数据链）/ 多次施法后 mult 递进同步

    Params: 无模板参数（增益 = Groundbreaker 自身 CardDef.num(0/1) ×
            (1 + 本局已施放酒馆法术数 // num(0))）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)

        def on_played(g, card=None, _h=h, **kw):
            if not isinstance(card, Minion) or card.controller is not _h:
                return
            if card.race not in _NAGA_RACES:
                return
            casts = _h.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
            acts = []
            for m in _living(_h):
                if m.card_id not in _GROUNDBREAKER_IDS:
                    continue
                d = g.db.get(m.card_id)
                if d is None:
                    continue
                n0, n1 = d.num(0), d.num(1)
                if n0 is None or n1 is None:
                    continue
                idx = _h.board.index(m)
                if idx == 0:
                    continue
                left = _h.board[idx - 1]
                if left.dead:
                    continue
                amount = n1 * (1 + casts // n0)
                acts.append(Buff(left, atk=amount, health=amount))
            if acts:
                g.run_actions(acts)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_played))
        return None


# ══════════════ BG35_MagicItem_925 Coral Spear ══════════════


class CoralSpearScript:
    """
    Natural language: [x]Whenever you cast a
    <b>Spellcraft</b> spell, cast
    Might of Stormwind.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_925`（greater, cost 4,
    `evolution_card_id=131152 → BG35_951 Might of Stormwind`——**已注册**
    的池法术 "Give four random friendly minions +{0}/+{1}"）。batch_trinkets8
    曾因 `game.cast_spell_by_id` 缺失把本卡列入 DEFERRED; 本轮
    `game.cast_spell_effect`（RULES §7.4.7b）落地后**解冻**。

    Formal spec:
      1. on_bind 注册持久 `spell_resolving` 监听（owner=饰品; 引擎在
         **每次施放**时广播——手牌路径 game.py `_finish_play_spell` 与
         效果施法 `cast_spell_effect` 同源），以 `spell.has(SPELLCRAFT)`
         判别"you cast a Spellcraft spell"。旧实现监听 `spellcraft_cast`
         → 该事件每次**打出**只 fire 一次（双施 SPELL_DOUBLER 下漏算）
         且 `cast_spell_effect` 不 fire 它（效果施放的 Spellcraft 永不
         触发）——2026-09-02 对抗审查证伪（与 batch15 Bloodbound
         Earrings 同款修法）
      2. 条件: `spell.controller is 绑定者`（对手施放不触发本人饰品;
         闭包默认参数防晚绑定）
      3. 触发: `cast_spell_effect(hero, 关联卡)`——效果施法（不经手牌/
         不动法术池/不广播 card_played/tavern_spell_cast）
      4. 关联卡是普通法术（无 SPELLCRAFT tag、无 needs_target）→
         直接按 `MightOfStormwind` 的 on_play 结算（随机 4 个友方随从
         +num(0)/+num(1)）; 空板 → 该次落空（不抛错）。关联卡自身不带
         SPELLCRAFT → 重入的 `spell_resolving` 被第 1 条过滤，无递归
      5. 数据链断裂 → fail-loud（不近似）

    Test: test_batch_trinkets19.py — 真实手牌施放 Spellcraft 法术
      （BG35_MagicItem_838t）后本人随机 4 个随从
      +num(0)/+num(1)（期望值取 BG35_951 CardDef; 正对照: 无饰品不变）/
      **双施（SPELL_DOUBLER）按施放次数结算两次**（旧实现只 1 次）/
      施放**非** Spellcraft 法术（池法术）不触发 / 对手施放 Spellcraft
      不触发（owner 隔离）/ 空板落空不抛错 / 无递归（一次施放只结算
      一次 Might of Stormwind）

    Params: 无模板参数（法术 id 经 `CardDef.evolution_card_id` 数据链;
            数值由 BG35_951 的 num(0)/num(1) 决定）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        rd = game.trinket_related_card(source.card_id)
        if rd is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        spell_id = rd.id

        def on_resolving(g, spell=None, _h=h, **kw):
            if spell is None or spell.controller is not _h:
                return
            if not spell.has(GameTag.SPELLCRAFT):
                return
            g.cast_spell_effect(_h, spell_id)

        game.events.register(Listener(
            event="spell_resolving", owner=source, callback=on_resolving))
        return None


# ══════════════ 未注册（DEFERRED；台账见模块 docstring） ══════════════


class SafetyPatchScript:
    """
    Natural language: Cast Ice Block.
    Gain {0} Gold.

    Status: DEFERRED — requires Secrets 子系统 + Ice Block 法术脚本

    Dependency: 关联卡 `TB_Bacon_Secrets_12` Ice Block =
    "Secret: When your hero takes fatal damage, prevent it and become
    Immune this turn."——引擎全仓无 Secret 区域/致命伤害预防钩子，且该
    法术未注册（`REGISTRY` 无 id）。`cast_spell_effect` 对无脚本法术只
    创建实体 + 无 on_play → "Cast Ice Block" 半场 100% 空转（SOP §12
    item 14）。金币半场（`GainGold(hero, num(0))`）已就绪但不得单独
    注册（整卡半实现 = 第三态，SOP §6b）。
    实现路径: 实现 Secret 协议（`hero.secrets` + `HERO_DAMAGE_TAKEN`
    前的致命伤害预防读取点）→ 注册 `TB_Bacon_Secrets_12` 脚本 →
    本卡 on_bind = `[GainGold(h, num(0)), cast_spell_effect(h, 关联卡)]`。

    Params: {0}=5（BG35_MagicItem_820 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TimewornCandelabraScript:
    """
    Natural language: <b>Discover</b> a 2-Cost minion from the Minor
    <b>Timewarp</b>.

    Status: DEFERRED — requires Minor Timewarp 集合的数据定义域

    Dependency: XML 仅有 `BACON_TIMEWARPED`(4503) 单一"时空扭曲过"布尔
    标记（`tools/generate_bg_data.py` TAG 表内含该 enumID 但**无读取
    点**，bg_cards.json 零 `timewarped` 字段），无 Minor/Major 之分;
    wiki 页（Battlegrounds/Timeworn_Candelabra_(Lesser)）无 Notes/
    Related cards 段，只有 `BACON_TIMEWARP_TOOLTIP` / `DISCOVER` /
    Timewarp-related 标签 → 候选集无权威（SOP §6b 第 4 步: 查无证据
    即 DEFERRED，禁止按卡名/档位猜测）。
    实现路径: 生成器导出 Minor Timewarp 成员标记（如
    `BACON_TIMEWARP_TOOLTIP`(4701) 或专用 subset 字段）→ 候选 =
    该集合内 `cost == 2` 的随从（`BACON_SHOW_COST_ON_DISCOVER` 证实按
    费用展示）→ 3 选 1 `Discover`。

    Params: 无模板参数（"2-Cost" 为文本字面量——CardDef num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class RylakPortraitScript:
    """
    Natural language: [x]Get a Rylak Metalhead.
    <b>Start of Combat:</b> Trigger
    your Rylak Metalheads'
    <b>Deathrattles</b>.

    Status: DEFERRED — requires BG26_801 迁移（载荷行为未就绪）

    Dependency: RULES §7.4.6 例外条——本卡第二句**依赖被授予卡的行为**。
    关联卡 `BG26_801` Rylak Metalhead（"Taunt. Deathrattle: Trigger the
    Battlecry of an adjacent minion."）及其金色 `BG26_801_G` 均未注册
    （`REGISTRY` 无 id）→ SoC 对每个 Rylak 调
    `run_script_hook(m, "deathrattle")` 只会得到 None，整卡第二句 100%
    空转（注册即 no-op = 禁止的第三态）。
    实现路径: 迁移 `BG26_801`/`BG26_801_G`（`TriggerBattlecry` 协议已
    就绪）→ 本卡 on_bind 交付关联卡，`start_of_combat` 对本人棋盘每个
    Rylak Metalhead 触发其亡语钩子（引擎若补 `trigger_deathrattle`
    公开入口则改用之）。

    Params: 无模板参数（关联卡经 `CardDef.evolution_card_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BubbleCrownScript:
    """
    Natural language: [x]Once you cast {1} spells,
    your Tavern spells give
    an extra +{2}/+{4}. <i>({0} left!)</i>

    Status: DEFERRED — requires TAG_SCRIPT_DATA_NUM_5 数据导出

    Dependency: XML（dbf 130898）: NUM_1=12、NUM_2=12、NUM_3=4、
    **NUM_5=4**; 文本 {4} 映射 NUM_5，而 `CardDef` 只导出 NUM_1..4
    （`tools/generate_bg_data.py` L227-238）→ `num(3) is None`，硬编码
    违反数值纪律（SOP §16b item 25; batch_trinkets17
    `ThornspikePauldronScript` 同款缺口）。另需裁定 "cast spells" 口径
    （全法术 vs `TAVERN_SPELLS_CAST_THIS_GAME` 仅池法术）。
    实现路径: 生成器导出 `script_data_num_5`（+ `CardDef.num(4)`）→
    on_bind 注册法术施放计数监听，达 num(1)=12 时一次性写
    `hero.TAVERN_SPELL_EXTRA_ATK/HEALTH += (num(2), num(4))`
    （消费点 `tavern_spell_buff` 已就绪）。

    Params: {0}=12 {1}=12 {2}=4（num(0..2) 可读） {4}=NUM_5（**当前
            无数据通道**）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class CowrieNecklaceScript:
    """
    Natural language: Tavern spells that give stats cost (2) less.

    Status: DEFERRED — requires "give stats" 法术效果类别定义域

    Dependency: `TAVERN_SPELL_COST_MOD`（RULES §7.4.5）是 hero 级**无
    条件**持久折扣（`buy_from_tavern` game.py:538
    `cost = max(0, cost - pers)`），无按效果类别的读取点; 数据层无任何
    "给属性"标记（对照 XML: 给属性的 `BG34_444`/`BG35_951` 与不 give
    stats 的池法术标签集无差异）。按卡面文本解析法术文本属近似
    （SOP §6b 禁止）。batch_trinkets8 模块 docstring 已就**同一张卡**
    备案同一缺口，本批复核维持。
    实现路径: 引擎/数据层为"give stats"池法术标注类别（生成器导出
    `gives_stats` 位）→ `buy_from_tavern` 增按类别折扣读取点
    （如 `hero.TAVERN_SPELL_COST_MOD_STATS`）→ on_bind 写入
    （2 为文本字面量——CardDef 无模板参数）。

    Params: 无模板参数（"cost (2) less" 为文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# BG35_MagicItem_922 Tide Raiser Portrait 已由 batch_trinkets38 注册
# （2026-09-17: `cast_spell_effect` 的 `spell_resolved` 广播 + 载荷
#  `BG34_920` 已注册）→ 占位 DEFERRED 类删除。


# 2026-09-18: `BewitchedRibbonScript` 占位 DEFERRED 台账删除——
# `BG35_MagicItem_923` 已由 batch_trinkets31 注册
# （`Buff(persist=True)` 按来源跨战斗持久化，RULES §3.5 例外 4）。


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 19 批 13 张 + Spellcraft 法术本体 2 张。

    （7 张 DEFERRED 的依赖与实现路径见模块 docstring；不注册 = 二态铁律
    的 DEFERRED 态，SOP §6b。）
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_MagicItem_821", KaleidoscopeScript),
        ("BG35_MagicItem_838", DoubleStitchNeedleScript),
        ("BG35_MagicItem_838t", DoubleStitchSpellScript),
        ("BG35_MagicItem_840", ChromaticTearScript),
        ("BG35_MagicItem_842", EggOfTheEndtimesPortraitScript),
        ("BG35_MagicItem_849", CloudSerpentHornScript),
        ("BG35_MagicItem_850", PocketCycloneScript),
        ("BG35_MagicItem_852", LightningInABottleScript),
        ("BG35_MagicItem_861", BallerPortraitScript),
        ("BG35_MagicItem_863", AvalancheStickerScript),
        ("BG35_MagicItem_870", LeapfroggerPortraitScript),
        ("BG35_MagicItem_872", OphidianStaffScript),
        ("BG35_MagicItem_872t", OphidianStaffSpellScript),
        ("BG35_MagicItem_924", GroundbreakerPortraitScript),
        ("BG35_MagicItem_925", CoralSpearScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
