"""批次 hero_remaining — 剩余无脚本英雄技能审计批（作业单 2026-09-02）。

作业范围: 36.2.2 数据中 `bg_heroes.json` 绑定但 REGISTRY 无脚本的 21 个
英雄技能（逐一用作业单探针列表核对）。铁律: **CORRECT 或 DEFERRED，没有
第三态**（SOP §6b）——候选集/奖励档位/冻结粒度无权威证据的一律不注册。

协议（沿用 hero_passives / hero_actives / hero_econ3 批）:
  - 被动/自动技能: ``passive = True`` + ``on_bind(hero, game)``
    （Game.start_game 对每个英雄按其当前技能调 on_bind）
  - 主动技能: ``hero_power(hero, game, ctx)``；``needs_target`` /
    ``target_candidates`` / ``available(hero, game)`` 由
    game.use_hero_power/_finish_hero_power 读取
  - "Discover/选择" 一律 ``game.pending_choices.append(PendingChoice(...))``
    （自动化层 choice_policy 决策; 不接 UI）
  - 技能替换: ``game.replace_hero_power(hero, power_id)``（单槽
    ``hero._active_power_id``）; 引擎**不**自动接线被替换技能的 on_bind
    → 脚本显式调用（Jaraxxus/Nether Portal 先例）
  - 数值一律 ``CardDef.num(N)``；无占位符的文本字面量在各类 Params 区注明

实现 5（CORRECT）:
  TB_BaconShop_HP_057 Adventure!（Finley）— 开局 Discover 一个英雄技能并替换
  BG22_HERO_000p_Alt Lock and Load（Tavish）— 定向移除酒馆随从; 下场战斗
      有空位时召唤并强制攻击随机敌方随从
  BG30_HERO_304p Fantastic Treasure（Marin）— 第 num(0)+1 回合选购 Lesser 饰品
  BG32_HERO_002p Growing Collection（Buttons）— 第 num(0)+1 回合选购 Greater 饰品
  TB_BaconShop_HP_102 Three Wishes（Zephrys）— 凑满第三份同名随从（每局 num(0) 次）

DEFERRED 16（作业单 21 项中余下的全部; 不注册; 依赖逐条列出——宁缺毋错;
另附台账备注 1: BG22_HERO_000p Deadeye 已非任何英雄的绑定技能，
不计入 21）:
  BG24_HERO_100p Whodunit?（Denathrius）"At the start of the game, choose
      one of two Quests"——机制（开局二选一任务 + complete_quest 发奖）已
      实现并通过对抗审计验证。**2026-09-18 第四十九轮订正**: 旧理由
      「任务卡 17 张全部 DEFERRED → 任务永不推进/无人调用
      complete_quest → 技能空转」**已失效**——19 张任务已注册
      （`batch_quests`; 目标值权威 = 各卡 wiki 页 "baseline requirement"，
      见 `docs/agents/QUEST_DEFERRED_SPEC.md`）。当前缺口 = **接线工作项**:
      下方 `WhodunitScript.on_bind` 的候选池写死 `BG24_Quest_*` 前缀，
      会把已 DEFERRED 的 `BG24_Quest_328` 与公告 token `BG24_Quest_Bob`
      一并发出 → 接线须改用 `game.quest_offer_pool()`。Dependency: 接线
      （class 保留，机制已在类 docstring 记档）。
  BG20_HERO_202p Power of the Storm（Nguyen）"At the start of every turn,
      choose from 2 new Hero Powers"——候选集缺口同 Finley（已由本批
      数据链解决），但**每回合轮换的注销语义**缺引擎协议: 引擎无
      unbind（被替换被动技能的 on_bind 监听器/英雄 tag 常驻——Millhouse
      费用覆写、Patchwerk 血量、Curator 随从在换走后仍生效）。Dependency:
      主线需 hero 级技能 rebind/unbind 协议（监听器随技能身份注销 +
      hero tag 回滚），否则每次轮换都产生残留被动 = 第三态。
  BG20_HERO_242p Natural Balance（Guff）"After you buy 20 Tiers' worth of
      cards, get a Triple Reward"（num(0)=20; 购买 tier 累加面可实现）
      / BG33_HERO_001p_ALT Heroic Inspiration（Loh）"After {1} friendly
      minions attack, get a Triple Reward"（num(0)=num(1)=15; after_attack
      计数面可实现）——**奖励档位规则**无权威: 常规三连奖励档 = 被三连
      卡 tier+1（RULES §10.3; 引擎 _grant_triple_reward(hero, golden)
      锚定金色实体），英雄技能授予场景**无来源卡**; wiki Triple Reward
      token 文本 "Discover a minion from Tier @" 未给规则，patch notes
      无（2026-09-02 查证 Loh/Heroic Inspiration/Triple Reward 三页）。
      Dependency: 主线给"无来源 Triple Reward"的档位裁定 + 脱锚原语
      （_grant_triple_reward 现签名要求 golden Minion）。
  BG22_HERO_004p Twice as Nice（Varden）"After the Tavern is Refreshed,
      copy its highest-Tier minion and Freeze them both"——复制面可实现，
      但**随从级冻结**缺引擎粒度: 冻结恒读 hero FROZEN tag（整馆保留,
      refresh_tavern game.py:339-353; tags FROZEN 注释"整馆由 player
      级 tag 表达"），无 minion 级冻结读取点 → 整馆冻结 = 多冻结其余
      展示项（近似实现, 禁止）。Dependency: minion 级 freeze tag + 
      refresh_tavern 保留集合读取。
  BG35_HERO_001p King of Duality（Genn）"On Turn 4, Discover two Hero
      Powers to replace this"——"Discover two" 的语义二择一（二选一）
      与"获得第二英雄技能"（34.2 官方 Timewarped Power "second Hero
      Power" 概念）**均无公开证据**（2026-09-17 复核 wiki
      `Battlegrounds/King_of_Duality` oldid 904461: 仅 mechanics 行
      "Discover, Replace Hero Power" + `DISCOVER=1`/`num(0)=3`，无 Notes、
      无 Patch 说明）。**原注"技能替换协议仅单槽"已陈旧**——引擎现同时
      具备 `replace_hero_power`（主槽 `_active_power_id`）与
      `set_second_hero_power`/`hero._second_power_id` 第二槽
      （RULES §9.5; batch_anomalies4/5、batch_quest_rewards5 已在用），
      故两种读法**都有落点**、缺口纯在语义权威。且第 4 回合换入"At the
      start of the game"类技能时 on_bind 接线时点无官方裁定。
      Dependency: 官方语义证据（二择一 vs 第二技能）。
  BG20_HERO_283p Dungar's Gryphon "Choose a new flightpath. Complete it
      to get a bonus!"——flightpath 子系统（路线/进度/奖励）无数据权威
      （CardDB 内 "Flightpath" 零命中）。Dependency: flightpath 卡池与
      进度协议。
  BG21_HERO_000p Conviction（Cariel）"Give {2} random friendly minions
      +{0}/+{1}. Passive: After each combat, choose an improvement"——
      主动面可实现（num=1/1/1），但被动面"choose an improvement"的
      改进选项集为客户端硬编码（wiki Cariel Roame / HSReplay 无枚举;
      2026-08-23 hero_passives2 批查证）→ 部分实现 = 第三态，整体 DEFER。
  BG22_HERO_000p Deadeye（Tavish 旧技能）"Take aim! Start of Combat: Deal
      {1} damage to your target"——瞄准选择器（多回合目标记忆 + 战斗
      目标解析）无引擎协议; 且该技能已非任何英雄的绑定技能。DEFER。
  BG25_HERO_100p Build-An-Undead（Putricide）"Craft a custom Undead"
      （num(0)=3 次）——多步部件选择/缝合 UI（种族+关键词+属性选择链）
      无引擎建模。Dependency: 合成选择链协议。
  BG31_HERO_801p Lift Off（Raynor）"Start the game with a 2/2
      Battlecruiser. Whenever the Tavern is Refreshed, add a Battlecruiser
      Upgrade to it"——token 存在（BG31_HERO_801pt 2/2, 数据核实），
      但 10 张 Battlecruiser Upgrade（BG31_HERO_801pta..j, card_type 42）
      全部无脚本且含 Yamato/Rally/Deathrattle 赋予关键词等叠加语义 →
      非"完全可表达"（作业单条件不满足）。Dependency: 升级卡脚本批。
  BG31_HERO_811p Spawning Pool（Kerrigan）"Unlock Tier 2 Zerg. Costs (1)
      less each turn. Passive: Start the game with a 2/2 Larva"——
      "Unlock Tier 2 Zerg"（Zerg 分级解锁）+ Larva 每回合变形选择
      （BG31_HERO_811t "choose a Zerg minion to morph into"）子系统
      未建。Dependency: Zerg morph 协议。
  BG34_HERO_000p Alternate Timeline / BG34_HERO_004p Warped Conflux——
      Timewarp（Chronum/Timewarped Tavern 商店）子系统无引擎实现
      （BG34_BlackMarket_Skip 等 356 张卡无脚本）。Dependency: Timewarp
      子系统。
  TB_BaconShop_HP_020 Prestidigitation（Akazamzarak）——Secret 子系统
      （BG 无 Secret 区/触发协议）。Dependency: Secret 区与触发。
  TB_BaconShop_HP_101 Come One, Come All!（Silas）——Darkmoon Ticket
      token + 馆内计数 + 集 3 发现子系统（CardDB 内 "Ticket" 仅 buddy
      卡）。Dependency: Ticket token 与酒馆注入协议。
  TB_BaconShop_HP_106 Prize Wall（Tickatus）——Darkmoon Prize 子系统
      （CardDB 内 "Darkmoon Prize" 零卡池定义）。Dependency: Prize 卡池。

引擎需求汇总（报告主线）:
  1. hero 级技能 rebind/unbind（Nguyen 每回合轮换——残留被动注销）
  2. 无来源 Triple Reward 的档位裁定 + 脱锚授予原语（Loh/Guff）
  3. minion 级 freeze（Varden "Freeze them both"）
  4. Battlecruiser Upgrade 卡脚本（Lift Off）/ Zerg morph（Spawning Pool）
  5. Timewarp / Secret / Ticket / Darkmoon Prize 子系统
  6. 多技能槽协议（Genn "Discover two Hero Powers" 若为第二技能语义）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.combat import execute_immediate_attack
from hsrl2.events import START_OF_COMBAT, TURN_START, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.scripts import REGISTRY
from hsrl2.tags import CardType, GameTag, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

_ADVENTURE_POWER = "TB_BaconShop_HP_057"
_LOCK_AND_LOAD_POWER = "BG22_HERO_000p_Alt"
_WHODUNIT_POWER = "BG24_HERO_100p"
_FANTASTIC_TREASURE_POWER = "BG30_HERO_304p"
_GROWING_COLLECTION_POWER = "BG32_HERO_002p"
_THREE_WISHES_POWER = "TB_BaconShop_HP_102"


def _power_def(game: "Game", power_id: str):
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    return d


def _draftable_hero_power_ids(game: "Game", exclude=()) -> list:
    """可选中英雄绑定的英雄技能 id 集合（Discover a Hero Power 候选池）。

    数据链: CardDB 载入 bg_heroes.json 的全部 HERO 定义；CardDB.load 把
    raw["hero_power_dbf"]（XML Tag380）二次映射为 ``hero_power_id``。
    仅这些技能属于官方英雄技能池——token 技能（Sulfuras
    TB_BaconShop_HP_087t / Nether Portal TB_BaconShop_HP_036t / Rat King
    变体）不绑定英雄，排除。返回排序列表（rng.sample 输入稳定）。

    证据: hearthstone.wiki.gg/wiki/Battlegrounds/Power_of_the_Storm 的
    "Cards banned from Power of the Storm" 池只剔除 Conviction /
    Power of the Storm / Sharpen Blades 三项——证明基础池 = 英雄技能全集
    而非某个另行维护的子集（2026-09-02 查证）。
    """
    out: list = []
    seen: set = set()
    exclude = set(exclude)
    for d in game.db._by_id.values():
        pid = getattr(d, "hero_power_id", None)
        if d.card_type != CardType.HERO or pid is None or pid in seen:
            continue
        seen.add(pid)
        if pid in exclude or game.db.get(pid) is None:
            continue
        # 未迁移技能（REGISTRY 无脚本）→ 选中即"槽位就绪但技能空转"
        # （2026-09-02 对抗审查 D2: 抽样 200 局有 57% 局至少给出 1 个
        # 空转选项，按首个选项策略约 13% 局选中即永久不可用）。
        # Discover a Hero Power 的候选池 = **已实现**英雄技能。
        if REGISTRY.get(pid) is None:
            continue
        out.append(pid)
    return sorted(out)


def _wire_power_on_bind(game: "Game", hero: "Hero", power_id: str) -> None:
    """替换英雄技能后显式接线被选技能的 on_bind（引擎协议不自动调）。"""
    from hsrl2.scripts import REGISTRY
    script = REGISTRY.get(power_id)
    fn = getattr(script, "on_bind", None) if script is not None else None
    if fn is not None:
        fn(hero, game)


# ═══════════════ TB_BaconShop_HP_057 Sir Finley — Adventure! ═══════════════

class AdventureScript:
    """
    Natural language: [x]At the start of the game, <b>Discover</b> a Hero
    Power.

    Formal spec:
      1. on_bind（= start_game 接线点）: 候选池 =
         `_draftable_hero_power_ids(game, exclude={本技能})`（116 个可
         选中英雄技能; 剔除当前技能——官方 Discover 不提供正持有的
         技能，wiki Power of the Storm banned pool 同样剔除自身）。
      2. rng.sample 取 count 个不同候选 → PendingChoice(kind=
         "discover_hero_power") 入队（options = 技能 card_id 字符串;
         自动化层 choice_policy 决策，不接 UI）。
      3. resolve(power_id): game.replace_hero_power 覆写单槽
         hero._active_power_id + `_wire_power_on_bind` 显式接线被选
         技能的 on_bind（开局时点调用与 "At the start of the game"
         语义一致——Patchwerk 血量 / Curator 随从等开局效果生效）。
      4. passive=True: 不可点击（use_hero_power 对被动恒 False）；
         选择完成后 hero_power_def 读 _active_power_id → 本技能离场。
      5. 被选技能若是另一个"Discover a Hero Power"（Genn 的 King of
         Duality）不递归处理——其 on_bind 只注册 TURN_START 监听，
         不立即选择（非开局时点不会立刻结算）。

    Test: test_batch_hero_remaining.py — 开局恰 1 个 discover_hero_power
    PendingChoice（3 个互异候选、不含本技能、全在候选池内）; seed=3
    下选 Patchwerk（TB_BaconShop_HP_035）→ 替换生效且 on_bind 接线
    （health 30 → 2×30）; 对手无该 PendingChoice（owner 隔离）。

    Params: count=3（Discover 默认展示数——文本无占位符）
            候选池证据: wiki.gg/wiki/Battlegrounds/Power_of_the_Storm
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        pool = _draftable_hero_power_ids(game, exclude=(_ADVENTURE_POWER,))
        if not pool:
            return
        options = game.rng.sample(pool, min(3, len(pool)),
                                  label="adventure_hero_power")

        def resolve(power_id):
            game.replace_hero_power(hero, power_id)
            _wire_power_on_bind(game, hero, power_id)

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_hero_power", resolve_callback=resolve))


# ═══════════════ BG22_HERO_000p_Alt Tavish — Lock and Load ═══════════════

class LockAndLoadScript:
    """
    Natural language: [x]Remove a minion in the Tavern. When you have space
    next combat, fire it at a random enemy minion.

    Formal spec:
      1. 定向（wiki 卡片页 Wiki tags 含 [Targeted]; needs_target=True）:
         候选 = hero.tavern 中全部 Minion（"a minion in the Tavern"）。
      2. 移除（wiki Wiki tags "Remove from game"）: 馆内实体移出展示区
         （zone=REMOVED + unregister_owner——非死亡，不触发 death/
         亡语/复仇）; 池记账按 refresh_tavern 对未购馆内实体的回池路径
         `minion_pool.release(base_id, 1)`（base_id 取 TRIPLE_BASE_CARD_ID
         ——金色化展示项; RULES §2.3 池守恒，否则每次使用永久收缩池）。
         实体存入 hero._lock_and_load_stored 单槽（重复使用覆盖旧槽，
         旧实体已回池，丢弃无泄漏）。
      3. 战斗触发: on_bind 注册持久 START_OF_COMBAT 监听（owner=hero）。
         条件: 绑定英雄（hero is _owner）、槽非空、己方棋盘有空位
         （board_full() False——"When you have space"）、
         game._active_combat 定位敌方且敌方有存活随从。**无空位时槽
         保留**（文本 "next combat"：顺延到有空位的那场战斗）。
      4. 触发动作（wiki Wiki tags "Summon" + "Force attack"）:
         game.summon 存储实体入己方棋盘（战斗召唤物不入池;
         战后随 board_before 快照复原消失）→ rng.choice 随机敌方存活
         随从 → `combat.execute_immediate_attack`（完整单次攻击语义:
         Rally/同时双向伤害/顺劈/剧毒/AFTER_ATTACK）。槽清空，
         每场战斗至多一次; XML 权威 START_OF_COMBAT=1（SOP §13.3:
         不以文本措辞发明触发时机）。

    Test: test_batch_hero_remaining.py — 定向移除（离馆 + 池回补 +
    无 death 事件）; SoC 有空位时召唤并对唯一敌方随从完成攻击（敌方
    死亡、存储实体在己方棋盘）; 满板时槽保留且不召唤; 敌方 SoC
    （hero=对手）不触发。

    Params: 无模板参数（无数值; 触发时机/目标域由 CardDefs XML 标签权威）
    """

    needs_target = True

    @staticmethod
    def target_candidates(hero: "Hero", game: "Game"):
        return [e for e in hero.tavern if isinstance(e, Minion)]

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.tavern:
            raise GameStateError("Lock and Load: target not in tavern")
        hero.tavern.remove(target)
        target.zone = Zone.REMOVED
        game.events.unregister_owner(target)
        base_id = target.get(GameTag.TRIPLE_BASE_CARD_ID, None) \
            or target.card_id
        game.minion_pool.release(base_id, 1)
        hero._lock_and_load_stored = target
        return None

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_soc(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            stored = getattr(_owner, "_lock_and_load_stored", None)
            if stored is None:
                return
            pair = getattr(g, "_active_combat", None)
            if pair is None:
                return
            enemy = pair[1] if pair[0] is _owner else pair[0]
            targets = [m for m in enemy.board if not m.dead]
            if not targets:
                return
            if _owner.board_full():
                return   # 无空位 → 槽保留到下一场战斗
            _owner._lock_and_load_stored = None
            g.summon(_owner, stored)
            target = g.rng.choice(targets, label="lock_and_load_fire")
            execute_immediate_attack(g, stored, target)

        game.events.register(Listener(
            event=START_OF_COMBAT, owner=hero, callback=on_soc))


# ═══════════════ BG24_HERO_100p Sire Denathrius — Whodunit? ═══════════════

class WhodunitScript:
    """
    Natural language: At the start of the game, choose one of two
    <b>Quests</b>.

    Status: DEFERRED — **接线未落地**（2026-09-18 第四十九轮订正）。
    Dependency: 旧理由「任务卡 `BG24_Quest_*` 全部 DEFERRED → 选到的任务
      永不推进、`complete_quest` 无人调用 → 技能空转」**已随任务族落地
      失效**（2026-09-18: 19 张任务注册于 `batch_quests`；目标值权威 =
      各卡 wiki 页 "baseline requirement"，见
      `docs/agents/QUEST_DEFERRED_SPEC.md`）。当前缺口是**接线工作项**
      （非权威/数据缺口）:
        (a) 下方 `on_bind` 的候选池写死 `BG24_Quest_*` 前缀 → 会把已
            DEFERRED 的 `BG24_Quest_328`（"Win the game." 胜义无权威）与
            公告 token `BG24_Quest_Bob` 一并发出（后者注册即空转第三态）
            → 接线时必须改用 `game.quest_offer_pool()`（池门禁 =
            `quest_defs() ∩ REGISTRY`）。
        (b) 本卡与第 4 回合标准 offer 的互斥已由 `game._quest_offered`
            实现，但需真实路径测试锁定（对手/同英雄两个 offer 不得重复）。
      本次（第四十九轮）未注册本卡——属独立卡片工作项，避免在任务批里
      夹带未经对抗验证的英雄技能接线。

    Formal spec（机制，暂不注册）:
      1. on_bind（= start_game）: 任务候选 = `game.quest_offer_pool()`
         （**接线时改**）; 奖励候选 = 全部 BG24_Reward_*。rng.sample 取
         2 个不同任务，各配一张 rng.choice 随机奖励 ——引擎既有裁定
         （game._offer_quests: 官方配对规则未公布 → 等权随机配对,
         Malygos 先例）。
      2. PendingChoice(kind="quest_offer") 入队（options = (quest_id,
         reward_id) 二元组; 复用引擎任务选择协议与 kind）。
      3. resolve((qid, rid)): create_entity(任务) → hero.quest、
         hero._quest_progress=0、hero._quest_completed=False、**先**暂存
         hero._quest_reward_id = rid、再任务 on_bind 接线（阈值式任务
         可能当场达标 → `complete_quest` 必须能立刻发奖;
         `_offer_quests.resolve` 同款顺序）。
      4. 第 4 回合的标准任务 offer 抑制: game._quest_offered.add(hero)
         ——一处英雄同时只有一个任务（引擎 _begin_recruit_for 读取该
         集合，game.py:260）。
      5. 本技能 passive=True（纯开局选择）。

    Test: test_batch_hero_remaining.py — 断言未注册 + **新前提**（任务
    载荷已可推进/完成，旧"REGISTRY 为空"断言已删除并给出证明）。
    接线后改为行为断言并重新注册。

    Params: count=2（"one of two Quests"——文本字面量，CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        quests = [d.id for d in game.db._by_id.values()
                  if d.id.startswith("BG24_Quest_")]
        rewards = [d.id for d in game.db._by_id.values()
                   if d.id.startswith("BG24_Reward_")]
        if not quests or not rewards:
            return
        pairs = [(q, game.rng.choice(rewards, label="whodunit_reward_pair"))
                 for q in game.rng.sample(
                     quests, min(2, len(quests)), label="whodunit_quest")]
        # 已有任务 → 不再接受第 4 回合的标准任务 offer（一个英雄一个任务）
        game._quest_offered.add(hero)

        def resolve(pair):
            qid, rid = pair
            quest_entity = game.create_entity(qid, controller=hero)
            hero.quest = quest_entity
            hero._quest_progress = 0
            game.run_on_bind(quest_entity, ctx={"hero": hero})
            hero._quest_reward_id = rid

        game.pending_choices.append(PendingChoice(
            hero, pairs, "quest_offer", resolve_callback=resolve))


# ═══════════════ 饰品提前档（Marin / Buttons）═══════════════

def _register_trinket_offer(hero: "Hero", game: "Game",
                            power_id: str, kind: str) -> None:
    """第 num(0)+1 回合提供指定档位饰品商店（Marin/Buttons 提前档）。

    "{0} turns left!" 显示 = 当前回合 1 时的剩余回合数 → 触发回合 =
    num(0)+1（Marin num(0)=4 → T5; Buttons num(0)=7 → T8）。
    once + condition 监听（EventBus 仅在 condition 通过时消费）。
    触发时记账 game._trinket_offered.add((hero, kind))——引擎标准档
    （RULES §7.4.1 T6 lesser / T9 greater）据此跳过，避免二次发放
    （game.py:270-275 读取点）。
    """
    trigger_turn = _power_def(game, power_id).num(0) + 1

    def on_turn_start(g, hero=None, turn=None, _owner=hero, _kind=kind, **kw):
        if hero is not _owner or turn != trigger_turn:
            return
        if (_owner, _kind) in g._trinket_offered:
            return
        g._trinket_offered.add((_owner, _kind))
        g._offer_trinkets(_owner, _kind)

    game.events.register(Listener(
        event=TURN_START, owner=hero, once=True,
        condition=lambda hero=None, turn=None, _owner=hero,
        _t=trigger_turn, **kw: hero is _owner and turn == _t,
        callback=on_turn_start))


class FantasticTreasureScript:
    """
    Natural Language: [x]On Turn 5, choose a Lesser <b>Trinket</b> to buy.
    <i>({0} |4(turn, turns) left!)</i>

    Formal spec:
      1. on_bind 注册 TURN_START once 监听（owner=hero）; 触发回合 =
         num(0)+1 = 5（{0}=4 为第 1 回合起算的倒计时显示）。
      2. 触发: game._trinket_offered.add((hero, "lesser")) →
         game._offer_trinkets(hero, "lesser")——引擎饰品商店协议
         （3 选 1 + 放弃; 类型关联展示; 跨局不重复; RULES §7.4）。
      3. 记账使引擎标准 T6 lesser 档跳过（同一 (hero, kind) 单次）。
      4. passive=True: 不可点击（自动触发）。

    Test: test_batch_hero_remaining.py — 第 5 回合恰 1 个 trinket_offer
    PendingChoice（kind 档位 lesser; options 全为 BACON_TRINKET + 放弃
    哨兵）; 第 6 回合不重复发放; 对手第 6 回合照常 lesser（owner 隔离）。

    Params: {0}=4（script_data_num_1; 触发回合 = {0}+1 = 5）
            choices=3（引擎 TRINKET_CHOICES——本轮给定，非本卡数值）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        _register_trinket_offer(hero, game, _FANTASTIC_TREASURE_POWER,
                                "lesser")


class GrowingCollectionScript:
    """
    Natural Language: [x]On Turn 8, choose a Greater <b>Trinket</b> to buy.
    <i>({0} |4(turn, turns) left!)</i>

    Formal spec:
      1. on_bind 注册 TURN_START once 监听（owner=hero）; 触发回合 =
         num(0)+1 = 8（{0}=7 倒计时）。
      2. 触发: 记账 (hero, "greater") → game._offer_trinkets(hero,
         "greater")（引擎饰品商店协议, RULES §7.4）。
      3. 记账使引擎标准 T9 greater 档跳过; 标准 T6 lesser 不受影响
         （键按 (hero, kind) 粒度——2026-09-01 审计修复语义）。
      4. passive=True。

    Test: test_batch_hero_remaining.py — 第 8 回合恰 1 个 trinket_offer
    （greater 档）; 第 6 回合 lesser 与第 9 回合 greater 均不重复;
    对手第 9 回合照常 greater。

    Params: {0}=7（script_data_num_1; 触发回合 = {0}+1 = 8）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        _register_trinket_offer(hero, game, _GROWING_COLLECTION_POWER,
                                "greater")


# ═══════════════ TB_BaconShop_HP_102 Zephrys — Three Wishes ═══════════════

def _three_wishes_pairs(hero: "Hero", game: "Game") -> list:
    """手牌+棋盘中 ≥2 张同名非金色随从且池中仍有副本的 card_id。"""
    counts: dict = {}
    for m in list(hero.hand) + list(hero.board):
        if isinstance(m, Minion) and not m.is_golden:
            counts[m.card_id] = counts.get(m.card_id, 0) + 1
    return sorted(cid for cid, n in counts.items()
                  if n >= 2 and game.minion_pool.available(cid) > 0)


class ThreeWishesScript:
    """
    Natural language: [x]If you have two copies of a minion, find the third.
    <i>(@ |4(Wish, Wishes) left!)</i>

    Formal spec:
      1. 次数: on_bind 读 num(0)=3 初始化 hero._three_wishes_left
         （"3 Wishes left!"）。引擎 uses_per_game 是静态类属性、无法读
         CardDef → 脚本自持计数; available() 在计数归零或无合法配对时
         返回 False（use_hero_power 拒绝且不扣 3 金）。
      2. 合法配对 = 手牌+棋盘存在 ≥2 张同名非金色随从且池中该 id
         available>0。第三份来自共享池（"find the third"; 池耗尽则不
         可用——RULES §2.4 无副本不可获取）。
      3. hero_power: rng.choice 随机一个配对（wiki Wiki tags 含
         [Random]）→ minion_pool.acquire（占池）→ create_minion →
         pending_hand_add（满手排队 P6）→ 计数 -1。第三份入手触发引擎
         三连检查（pending_hand_add → check_for_triple）→ 合成金色 +
         标准三连奖励 = "找到第三张" 的完整官方结果。
      4. cost=3（CardDef.cost）; 每回合 1 次由引擎处理。

    Test: test_batch_hero_remaining.py — 2 份同名 → 使用后第三份入手并
    立即合成金色（池 available 恰 -1、计数 -1、金恰 -3）; 仅 1 份时
    available False（不扣金）; 3 次用尽后第 4 次 False。

    Params: {0}=3（Wishes=script_data_num_1; wiki 页 TAG_SCRIPT_DATA_NUM_1=3）
    """

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        hero._three_wishes_left = _power_def(game, _THREE_WISHES_POWER).num(0)

    @staticmethod
    def available(hero: "Hero", game: "Game") -> bool:
        if getattr(hero, "_three_wishes_left", 0) <= 0:
            return False
        return bool(_three_wishes_pairs(hero, game))

    @staticmethod
    def hero_power(hero: "Hero", game: "Game", ctx):
        cands = _three_wishes_pairs(hero, game)
        if not cands:
            return None
        cid = game.rng.choice(cands, label="three_wishes")
        if not game.minion_pool.acquire(cid):
            raise GameStateError(
                f"Three Wishes: pool acquire failed for {cid}")
        game.pending_hand_add(hero, game.create_minion(cid, controller=hero))
        hero._three_wishes_left -= 1
        return None


def register() -> list[str]:
    """注册本批 5 个 CORRECT 技能（技能 card_id; DEFERRED 16 项不注册）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for power_id, script in (
        (_ADVENTURE_POWER, AdventureScript),
        (_LOCK_AND_LOAD_POWER, LockAndLoadScript),
        # (_WHODUNIT_POWER, WhodunitScript) — DEFERRED: 任务卡 0/17
        # REGISTRY（任务进度 = 基础值 × 种族修正 × 奖励基础值 × 奖励
        # 种族修正 × 护甲等级，其中仅任务基础值有 CardDefs 权威——奖励
        # 基础值 1/66、修正表全缺，见 RULES §11.6）→ 选到的任务永不
        # 推进/完成，真实对局中技能效果为空转（2026-09-01 对抗审计撤注册）
        (_FANTASTIC_TREASURE_POWER, FantasticTreasureScript),
        (_GROWING_COLLECTION_POWER, GrowingCollectionScript),
        (_THREE_WISHES_POWER, ThreeWishesScript),
    ):
        reg(power_id, script)
        registered.append(power_id)
    return registered
