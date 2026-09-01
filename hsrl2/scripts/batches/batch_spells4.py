"""批次 spells4 — 池法术 13 张（作业单 2026-08-21，Choose One 密集）。

覆盖 12 张 OK + 1 张 DEFERRED:
  OK: BG31_881 Time Management / BG31_886 Forest's Bounty /
      BG31_889 Sharing is Caring / BG31_890 Boundless Potential /
      BG31_896 Hallowed Ritual / BG32_815 Shifting Tide /
      BG33_101 A New Sprout / BG33_811 Healthy Bounty /
      BG33_812 Hostile Bounty / BG33_813 Selfish Bounty /
      BG33_814 Friendly Bounty / BG33_815 Wealthy Bounty
  DEFERRED: BG31_892 Fandral's Fortune（both_options 打出路径引擎缺口）

共性裁定:
  - **法术 Choose One 协议（本批自建）**: play_spell 无 choose_options
    分流（仅 play_minion 有，game.py:387）→ on_play 手动 append
    PendingChoice(kind="choose_one", options=[key,...])，resolve 按
    key 分支执行（SOP 经验库 PendingChoice 建模先例）。分支 Buff 数值
    各自独立取 num。
  - **酒馆法术 buff 出口**: 对随从的增益一律经
    actions.racefx.tavern_spell_buff 构造（"Your Tavern spells give an
    extra +X" 修饰叠加，racefx 模块契约）。
  - **法术 SoC（Sharing is Caring）**: 施放即注册持久
    START_OF_COMBAT 事件监听（owner=施放者英雄，condition=hero is
    施放者）。combat.py _start_of_combat_phase 对每个参战英雄恰好
    fire 一次 (hero=)（第 4 步英雄技能段）→ 天然 once-per-combat，
    无需 once/flag 防重（Upper Hand 同款语义的事件契约版）。战斗内
    plain Buff 战后快照恢复回滚 → 每场战斗重触发 = 官方"持久法术"
    语义。对手定位经 game._active_combat（combat.py 已暴露）。
  - **数据核实**: 13 张均无金色卡定义（bg_cards.json 无 *_G 池法术
    条目; 文本 '@' 后金色段为 CardDefs 遗留，BG 池法术无金色版），
    仅注册基础 id。
  - **BG33_811/812 "four friendly minions" 目标裁定**: 文本无
    "random" 无 "Choose"——采 v1 先例（hsrl/cards/spells/scripts.py
    HealthyBountyScript: rng.sample 随机 4）。
  - **BG33_814 "most common type" 裁定**: v1 FriendlyBountyScript
    先例——统计棋盘种族（排除 NONE/ALL）、并列取板序首个
    （max+插入序）; 无任何有类型随从 → 不限族 GetRandomMinion。

引擎缺口（报告主线）:
  1. play_spell 不支持 choose_options 声明协议（play_minion 有）——
     本批以手动 PendingChoice 自建，主线接线后可迁移。
  2. Discover Action 只覆盖随从（resolve 固定 create_minion）——
     "Discover a Tavern spell" 需法术版发现，本批自建
     DiscoverTavernSpellOfTier（批内 Action，batch_deathrattle
     自定义 Action 先例）。
  3. both_options 声明协议未实现（game.py:386 仅注释承诺）——
     Fandral's Fortune / Thorned Trailblazer BG31_327 共同依赖。
"""

from __future__ import annotations

from hsrl2.actions import Buff, Discover, GainGold, GetRandomMinion, ScheduleNextTurn
from hsrl2.actions.racefx import tavern_spell_buff
from hsrl2.events import START_OF_COMBAT, Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.queue import Action
from hsrl2.tags import Race

_NAGA_RACES = (Race.NAGA, Race.ALL)      # ALL 视为所有种族 (RULES §6.18)


def _queue_choose_one(game, hero, options, resolve):
    """法术 Choose One: 手动入队 PendingChoice(kind="choose_one")。

    options: ((key, label), ...)；resolve(key) 分支执行（数值在分支
    内经 game.db.get(source.card_id).num() 取回）。
    """
    game.pending_choices.append(PendingChoice(
        hero, [k for k, _ in options], "choose_one",
        resolve_callback=resolve))


# ═══════════════ 批内自定义 Action ═══════════════


class GiveBoardBuffNextTurn(Action):
    """延迟到 hero 下一招募阶段开始的全体随从 buff。

    与 ScheduleNextTurn 组合（game.deferred_actions 在
    _begin_recruit_for 金币重置后执行 = "At the start of your next
    turn"）。目标在**执行时**求值——"your minions" 指下回合开始的
    当前棋盘（施放后新买入的随从同样获益，已卖出/死亡的不获益），
    故不可在施放时快照 Buff 列表。times = 应用次数（"twice"）。
    """

    def __init__(self, hero, spell_id: str, times: int = 1):
        self.hero = hero
        self.spell_id = spell_id
        self.times = times

    def do(self, game) -> None:
        d = game.db.get(self.spell_id)
        atk, health = d.num(0), d.num(1)
        for _ in range(self.times):
            for m in self.hero.living_minions():
                game.run_actions(tavern_spell_buff(m, atk, health))


class DiscoverTavernSpellOfTier(Action):
    """发现一张指定 tier 的酒馆法术（占 spell_pool，RULES §2.3 同构）。

    - 候选 = db.pool_spells() 中 tech_level == tier 且 spell_pool 仍有
      剩余（每张 1 份，RULES §3.6.1）; 无候选 → 落空（真实游戏行为）
    - count=3 官方发现张数; 候选不足全给
    - resolve(pick_id): spell_pool.acquire → create_spell →
      pending_hand_add（满手排队 RULES §3.3）; 异常上抛不吞
    """

    def __init__(self, hero, tier: int, count: int = 3,
                 kind: str = "discover_tavern_spell"):
        self.hero = hero
        self.tier = tier
        self.count = count
        self.kind = kind

    def do(self, game) -> None:
        cands = [d.id for d in game.db.pool_spells()
                 if d.tech_level == self.tier
                 and game.spell_pool.available(d.id) > 0]
        if not cands:
            return
        k = min(self.count, len(cands))
        options = game.rng.sample(cands, k, label="discover_spell_options")
        hero = self.hero

        def resolve(pick_id: str) -> None:
            if not game.spell_pool.acquire(pick_id):
                raise GameStateError(
                    f"DiscoverTavernSpell: pick {pick_id} no longer "
                    f"available in spell pool")
            s = game.create_spell(pick_id, controller=hero)
            game.pending_hand_add(hero, s)

        game.pending_choices.append(PendingChoice(
            hero, options, self.kind, resolve_callback=resolve))


# ════════════════ BG31_881 Time Management ════════════════


class TimeManagementScript:
    """
    Natural language: [x]<b>Choose One -</b> Give your
    minions +{0}/+{1}; or At the
    start of your next turn, give
    your minions +{0}/+{1} twice.

    Formal spec:
      1. on_play: 入队 choose_one PendingChoice（"now"/"later"）
      2. "now": 每个存活友方随从立即经 tavern_spell_buff 获得
         +num(0)/+num(1)
      3. "later": ScheduleNextTurn + GiveBoardBuffNextTurn——下一
         招募阶段开始（_begin_recruit_for，金币重置后）对当时全部
         存活友方随从施加 times=2 次 +num(0)/+num(1)（目标延迟
         求值，见该 Action docstring）
      4. 空棋盘: "now" 落空 / "later" 延迟落空（真实游戏行为）

    Test: test_batch_spells4.py — now 分支全体 +num(0)/num(1);
    later 分支当回合无变化、end_recruit_phase 后下回合全体
    +2×num(0)/num(1) 且后买入随从同样获益

    Params: {0}=2 {1}=2（times=2 为 "twice" 文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)

        def resolve(key):
            if key == "now":
                game.run_actions([tavern_spell_buff(m, d.num(0), d.num(1))
                                  for m in hero.living_minions()])
            elif key == "later":
                game.run_actions(ScheduleNextTurn(
                    hero, GiveBoardBuffNextTurn(
                        hero, source.card_id, times=2)))

        _queue_choose_one(
            game, hero,
            (("now", "Give your minions +{0}/+{1}"),
             ("later", "At the start of your next turn, twice")),
            resolve)
        return None


# ════════════════ BG31_886 Forest's Bounty ════════════════


class ForestsBountyScript:
    """
    Natural language: <b>Choose One</b> - Give a
    minion +{0}/+{1} twice; or Give your minions +{2}/{3}.

    Formal spec:
      1. needs_target=True（"Give a minion" 定向——play_spell 的
         spell_target PendingChoice 分流，无候选时 target=None
         落空但法术照常消耗）
      2. on_play（ctx["target"] 已定）: 入队 choose_one
         PendingChoice（"single"/"all"）
      3. "single": target 获得 2 次独立 tavern_spell_buff
         (+num(0)/+num(1))——"twice" = 两次独立施加（TAVERN_SPELL_
         EXTRA 修饰按次叠加）; target=None → 落空
      4. "all": 每个存活友方随从 tavern_spell_buff(+num(2)/+num(3))

    Test: test_batch_spells4.py — single 分支目标 2×num(0)/num(1);
    all 分支全体 +num(2)/num(3); 目标选择与分支选择两级
    PendingChoice 流; 空棋盘施放 single 落空

    Params: {0}=6 {1}=6 {2}=2 {3}=2（times=2 为 "twice" 文本字面量）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        target = (ctx or {}).get("target")
        d = game.db.get(source.card_id)

        def resolve(key):
            if key == "single":
                if target is None:
                    return
                game.run_actions(
                    [tavern_spell_buff(target, d.num(0), d.num(1))
                     for _ in range(2)])
            elif key == "all":
                game.run_actions(
                    [tavern_spell_buff(m, d.num(2), d.num(3))
                     for m in hero.living_minions()])

        _queue_choose_one(
            game, hero,
            (("single", "Give a minion +{0}/+{1} twice"),
             ("all", "Give your minions +{2}/{3}")),
            resolve)
        return None


# ════════════════ BG31_889 Sharing is Caring ════════════════


class SharingIsCaringScript:
    """
    Natural language: <b>Start of Combat:</b> Your left-most minion
    gains stats equal to the nearest enemy minion's.

    Formal spec:
      1. on_play: 注册持久监听器 Listener(START_OF_COMBAT,
         owner=施放者英雄, condition=hero is 施放者)——combat.py 对
         每个参战英雄恰好 fire 一次 (hero=)（第 4 步），即施放者
         每场战斗恰好触发一次（Upper Hand 同款持久法术 SoC 的
         事件契约实现; 无需 once/flag 防重）
      2. 触发: 经 game._active_combat 定位对手; 我方最左存活随从
         （board 顺序首个非 dead）获得 Buff(+对手最左存活随从的
         atk, +其 max_health)——"gains stats equal to" = 增量等于
         对方属性（SOP §3 属性快照: 生命用 max_health; 战斗开始时
         current==max）。"nearest enemy minion" = 对位最左（BG 棋盘
         镜像位，v1/官方图示常规）
      3. 战斗内 plain Buff，战后快照恢复回滚 → 每场重新触发（官方
         持久法术语义）; 任一棋盘为空 → 落空
      4. SoC 时序注: 事件在双方 minion SoC（第 3 步）与英雄技能段
         之间 fire，敌方数值为其当时值——引擎 a/b 顺序内禀，与全部
         SoC 脚本一致

    Test: test_batch_spells4.py — 手动 fire start_of_combat（设
    _active_combat）验证最左获得对位属性 / 对手空盘落空 / 完整
    end_recruit_phase 战斗后回滚且每场重触发

    Params: 无数值参数
    """

    @staticmethod
    def on_play(source, game, ctx):
        caster = source.controller
        if caster is None:
            return None

        def on_soc(g, hero=None, **kw):
            combat = g._active_combat
            if combat is None:
                return
            if combat[0] is caster:
                opp = combat[1]
            elif combat[1] is caster:
                opp = combat[0]
            else:
                return
            mine = caster.living_minions()
            foes = opp.living_minions()
            if not mine or not foes:
                return
            left, nearest = mine[0], foes[0]
            g.run_actions(Buff(left, atk=nearest.atk,
                               health=nearest.max_health))

        game.events.register(Listener(
            event=START_OF_COMBAT,
            owner=caster,
            condition=lambda hero=None, **kw: hero is caster,
            callback=on_soc,
        ))
        return None


# ════════════════ BG31_890 Boundless Potential ════════════════


class BoundlessPotentialScript:
    """
    Natural language: [x]<b><b>Choose One - </b>Discover</b> a
    minion of your Tier; or a
    Tavern spell of your Tier.

    Formal spec:
      1. on_play: 入队 choose_one PendingChoice（"minion"/"spell"）
      2. "minion": Discover(hero, min_tier=max_tier=hero.tavern_tier
         （施放时酒馆等级）)——池感知三选一，选中占 minion_pool
      3. "spell": DiscoverTavernSpellOfTier(hero, tavern_tier)——
         法术版发现（引擎 Discover 只覆盖随从，批内自建）:
         候选 = pool_spells 中 tech_level==tier 且 spell_pool 有
         剩余，三选一，选中 spell_pool.acquire 占池 +
         create_spell 进手牌
      4. tier=1（初始）时法术分支候选含全部 T1 池法术; 无候选分支
         落空（真实游戏行为）

    Test: test_batch_spells4.py — minion 分支发现项全部 == 英雄
    tier 且选中入手占池; spell 分支发现项全部 tech_level==tier
    且选中法术入手、spell_pool 扣减

    Params: 无数值参数（tier 取 hero.tavern_tier 运行时值）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None

        def resolve(key):
            tier = hero.tavern_tier
            if key == "minion":
                game.run_actions(Discover(hero, min_tier=tier,
                                          max_tier=tier))
            elif key == "spell":
                game.run_actions(DiscoverTavernSpellOfTier(hero, tier))

        _queue_choose_one(
            game, hero,
            (("minion", "Discover a minion of your Tier"),
             ("spell", "Discover a Tavern spell of your Tier")),
            resolve)
        return None


# ════════════════ BG31_892 Fandral's Fortune ════════════════


class FandralsFortuneScript:
    """
    Natural language: <b>Discover</b> a <b>Choose One</b> card. It has
    both effects combined.

    Status: DEFERRED — requires both_options 打出路径

    Dependency: "It has both effects combined" 需要被发现的 Choose One
    卡在**后续打出**时双分支全发——game.py:386 注释承诺的
    "脚本层声明 both_options 处理" 未实现（play_minion/play_spell
    均只走单 key 分流），Thorned Trailblazer（BG31_327，
    "One Choose One card each turn has both effects combined"）同样
    依赖且未注册。无标记机制（hero 属性/tag）可复用——grep 确认
    both_options 全仓仅此一处注释。近似的"发现后二选一照旧"是
    简化实现，禁止。候选集（Discover 部分）可复用 batch_rally2 的
    CHOOSE_ONE_MINION_IDS ∪ CHOOSE_ONE_SPELL_IDS（漂移守护已备）。

    Params: 无数值参数
    """

    @staticmethod
    def on_play(source, game, ctx):
        return None


# ════════════════ BG31_896 Hallowed Ritual ════════════════


class HallowedRitualScript:
    """
    Natural language: <b>Discover</b> a Tier 7 minion.

    Formal spec:
      1. on_play: Discover(hero, min_tier=7, max_tier=7)——T7 池
         存在（data 12 张 T7 池随从已核实），池感知三选一
      2. 无候选（T7 全被购空）→ 落空（真实游戏行为）

    Test: test_batch_spells4.py — 发现项全部 tech_level==7 且
    选中入手占池

    Params: 无模板参数（tier=7 为文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return Discover(hero, min_tier=7, max_tier=7)


# ════════════════ BG32_815 Shifting Tide ════════════════


class ShiftingTideScript:
    """
    Natural language: [x]Give a minion +{0}/+{1}
    twice. If it's a Naga,
    repeat this.

    Formal spec:
      1. needs_target=True（"Give a minion" 定向，spell_target
         PendingChoice 分流）
      2. on_play: target 获得 times 次独立 tavern_spell_buff
         (+num(0)/+num(1))——基础 times=2（"twice"）
      3. "If it's a Naga, repeat this": target.race ∈ (NAGA, ALL)
         （Amalgam 视为所有种族，RULES §6.18）→ times=4（整套重复
         一次，v1 Shifting Tide 先例: loops = 4 if is_naga else 2）
      4. target=None（无候选棋盘）→ 落空

    Test: test_batch_spells4.py — 非 Naga 目标 2×num、Naga/ALL
    目标 4×num

    Params: {0}=1 {1}=1（times 2/4 为 "twice"/"repeat" 文本语义
    字面量）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        d = game.db.get(source.card_id)
        times = 4 if target.race in _NAGA_RACES else 2
        return [tavern_spell_buff(target, d.num(0), d.num(1))
                for _ in range(times)]


# ════════════════ BG33_101 A New Sprout ════════════════


class ANewSproutScript:
    """
    Natural language: <b>Discover</b> a Tier 1 minion.

    Formal spec:
      1. on_play: Discover(hero, min_tier=1, max_tier=1)——池感知
         三选一（T1 池 22 张已核实）
      2. 无候选 → 落空

    Test: test_batch_spells4.py — 发现项全部 tech_level==1 且选中
    入手占池

    Params: 无模板参数（tier=1 为文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return Discover(hero, min_tier=1, max_tier=1)


# ════════════════ BG33_811 Healthy Bounty ════════════════


class HealthyBountyScript:
    """
    Natural language: Give four friendly minions +{1} Health.
    （'@' 后金色段 "Give four friendly minions +{0}/{1}." 为
    CardDefs 遗留——BG 池法术无金色卡定义，data 已核实。）

    Formal spec:
      1. on_play: 存活友方随从中随机 4 个（不足 4 全取; 目标裁定
         v1 先例: 无 "random"/"Choose" 词，hsrl/cards/spells/
         scripts.py HealthyBountyScript rng.sample）各获得
         tavern_spell_buff(+0 攻/+num(1) 生命)
      2. 基础版文本只引用 {1}（无 {0}）——攻击加成不存在，num(0)
         缺失不回落
      3. 空棋盘 → 落空

    Test: test_batch_spells4.py — 5 随从恰 4 个 +num(1) 生命、攻击
    不变; 空棋盘落空

    Params: {1}=4（count=4 为 "four" 文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        targets = game.rng.sample(living, min(4, len(living)),
                                  label="healthy_bounty_targets")
        d = game.db.get(source.card_id)
        return [tavern_spell_buff(m, 0, d.num(1)) for m in targets]


# ════════════════ BG33_812 Hostile Bounty ════════════════


class HostileBountyScript:
    """
    Natural language: Give four friendly minions +{0} Attack.
    （'@' 后金色段同上——无金色卡定义。）

    Formal spec:
      1. on_play: 存活友方随从中随机 4 个（裁定同 Healthy Bounty，
         v1 先例）各获得 tavern_spell_buff(+num(0) 攻/+0 生命)
      2. 基础版文本只引用 {0}——生命加成不存在
      3. 空棋盘 → 落空

    Test: test_batch_spells4.py — 4 随从 +num(0) 攻击、生命不变

    Params: {0}=4（count=4 为 "four" 文本字面量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        targets = game.rng.sample(living, min(4, len(living)),
                                  label="hostile_bounty_targets")
        d = game.db.get(source.card_id)
        return [tavern_spell_buff(m, d.num(0), 0) for m in targets]


# ════════════════ BG33_813 Selfish Bounty ════════════════


class SelfishBountyScript:
    """
    Natural language: Give your left-most minion +{0}/+{1}.

    Formal spec:
      1. on_play: 最左存活随从（board 顺序首个非 dead）获得
         tavern_spell_buff(+num(0)/+num(1))——目标固定无需选择，
         不声明 needs_target（v1 先例 board[0]）
      2. 空棋盘 → 落空

    Test: test_batch_spells4.py — 仅最左 +num(0)/num(1)，其余不变

    Params: {0}=6 {1}=6
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        living = hero.living_minions()
        if not living:
            return None
        d = game.db.get(source.card_id)
        return tavern_spell_buff(living[0], d.num(0), d.num(1))


# ════════════════ BG33_814 Friendly Bounty ════════════════


class FriendlyBountyScript:
    """
    Natural language: Get a random minion of your most common type.

    Formal spec:
      1. on_play: 统计存活友方随从种族（排除 NONE/ALL——Amalgam 不
         计入任何单族计数，v1 先例）; 众数族 R → GetRandomMinion
         (hero, race=R)（池感知: race 匹配 R 或 ALL、占池、满手
         排队）
      2. 并列: v1 先例 max(counts) 取板序插入序首个（确定性，
         无随机 tie-break 官方证据）
      3. 棋盘无任何有类型随从 → GetRandomMinion(hero) 不限族
         （v1 先例）
      4. 无候选（池空）→ Action 内部落空

    Test: test_batch_spells4.py — 2 Beast+1 Murloc 棋盘入手 Beast
    （或 ALL）且占池; 空棋盘入手不限族随从

    Params: 无数值参数
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        counts: dict = {}
        for m in hero.living_minions():
            r = m.race
            if r in (Race.NONE, Race.ALL):
                continue
            counts[r] = counts.get(r, 0) + 1
        if not counts:
            return GetRandomMinion(hero)
        most_common = max(counts, key=counts.get)
        return GetRandomMinion(hero, race=most_common)


# ════════════════ BG33_815 Wealthy Bounty ════════════════


class WealthyBountyScript:
    """
    Natural language: Gain 2 Gold.

    Formal spec:
      1. on_play: GainGold(hero, amount=2)——hero.gold setter 执行
         99 持有上限（RULES §1.4）
      2. 文本无占位符、CardDef 无模板参数 → 字面量 2

    Test: test_batch_spells4.py — 金币 +2（含 99 上限封顶路径）

    Params: amount=2（文本字面量——无模板参数）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GainGold(hero, amount=2)


# ══════════════════ 注册 ══════════════════

# （无金色 id——池法术无金色卡定义，见模块 docstring 数据核实）
_REGISTRATIONS = [
    ("BG31_881", TimeManagementScript),
    ("BG31_886", ForestsBountyScript),
    ("BG31_889", SharingIsCaringScript),
    ("BG31_890", BoundlessPotentialScript),
    ("BG31_896", HallowedRitualScript),
    ("BG32_815", ShiftingTideScript),
    ("BG33_101", ANewSproutScript),
    ("BG33_811", HealthyBountyScript),
    ("BG33_812", HostileBountyScript),
    ("BG33_813", SelfishBountyScript),
    ("BG33_814", FriendlyBountyScript),
    ("BG33_815", WealthyBountyScript),
]
# DEFERRED 未注册: BG31_892 Fandral's Fortune（both_options 打出
# 路径引擎缺口，与 BG31_327 Thorned Trailblazer 同依赖）


def register() -> list[str]:
    """注册本批次全部脚本，返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []
    for card_id, script_cls in _REGISTRATIONS:
        _register(card_id, script_cls)
        registered.append(card_id)
    return registered
