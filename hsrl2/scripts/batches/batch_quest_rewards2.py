"""批次 quest_rewards2 — 任务奖励第二批（6 个 id / 5 张奖励 + 1 法术 token）。

本批解锁前批 `batch_quest_rewards.py` DEFERRED 台账中的"Avenge 奖励"
族——引擎自 2026-09-01 起在 `_process_single_death` 对
`hero.quest_rewards` 与 `hero.trinkets` 实体统一计数（脚本以类属性
`avenge_threshold` 声明阈值），且 `CombatScheduler.run` 每场战斗开始
时清零这些实体的 AVENGE_COUNTER（RULES §6.11 "本场战斗中死亡"）。

所有数值来源: `data/bg_quest_rewards.json` / `data/bg_cards.json`
（CardDB）。文本无 `{N}` 占位符的数值按 SOP §3 以文本字面量实现，
并在各类 `Params:` 行声明（本批 6 张卡的 CardDef.num(0..3) 全为 None，
即 data 无模板参数）。

实现（6 个 id）:
  BG27_Reward_502   Boom Squad            — Avenge(3): 对当前战斗对手
                                             最高 max_health 随从造成 10 伤害
  BG28_Reward_504   Cycle of Energy       — Avenge(3): 获取一张随机酒馆法术
  BG28_Reward_518   Stable Amalgamation   — Avenge(7): 有空间时召唤
                                             50/50 全种族 Amalgam
  BG33_Reward_004   Grim Freshener        — Avenge(2): 获得一次免费刷新
  BG27_Reward_504   Timeline Acceleration — 每回合开始获得 2 张 Accelerator
  BG27_Reward_504t  Accelerator           — 定向法术: 目标变形为恰好高
                                             一级的随机随从

引擎接线核实（SOP §14 "假接线" 排查）:
  - Avenge 计数源: game._process_single_death 的 avengers = 棋盘随从 +
    hero.trinkets + hero.quest_rewards（game.py:1600-1616），阈值读
    `other.scripts.avenge_threshold`；每场战斗清零见
    CombatScheduler.run（combat.py:72-79）
  - 当前战斗对手: `game._active_combat = (hero_a, hero_b)`（combat.py:77，
    finally 置 None——Boom Squad 目标定位）
  - 免费刷新读取点: game.refresh_tavern 非 auto 路径优先消耗
    hero.FREE_REFRESH_REMAINING（game.py:322-325）——Grim Freshener
  - 酒馆法术池: db.pool_spells() ∩ spell_pool.available > 0（Cycle of
    Energy / batch_quest_rewards._random_pool_spell 同口径）
  - 池占返: minion_pool.acquire（Accelerator 变形，P2）; token 非池卡
    不占池（BG28_Reward_518t 不在 bg_pool_minions.json，Accelerator
    为非池法术 card_type=5）

DEFERRED: 无（本批 6 个 id 全部 CORRECT）。
"""

from __future__ import annotations

from hsrl2.actions import Hit, Summon, Transform
from hsrl2.actions.discover import _pool_candidates
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag

# token / 数据链常量（CardDB 按名核实——SOP §11 教训 5: 禁止凭记忆写 id）
AMALGAM_TOKEN_ID = "BG28_Reward_518t"     # Totally Normal Horse 50/50 全种族
ACCELERATOR_ID = "BG27_Reward_504t"       # Accelerator 定向法术


def _reward_hero(source):
    """奖励实体控制者（owner 隔离锚点）。"""
    return getattr(source, "controller", None)


def _combat_opponent(game, hero):
    """当前战斗对手（game._active_combat 为 (hero_a, hero_b)）。

    非战斗 / 战斗对未建立 → None（Avenge 仅战斗内计数，engine 已守卫）。
    """
    ac = getattr(game, "_active_combat", None)
    if not ac:
        return None
    a, b = ac
    if a is hero:
        return b
    if b is hero:
        return a
    return None


def _random_pool_spell(game):
    """随机酒馆法术 card_id（db.pool_spells ∩ spell_pool 有剩余副本）。

    无候选（池空/无酒馆法术）→ None（效果落空）。口径与
    batch_quest_rewards._random_pool_spell 一致。经
    `Game.tavern_spell_candidates()` 施加存在档白名单（异变 101/102
    非存在档法术不可达）。
    """
    cands = game.tavern_spell_candidates()
    if not cands:
        return None
    return game.rng.choice(cands, label="cycle_of_energy_spell")


# ══════════════════ BG27_Reward_502 Boom Squad ══════════════════

class BoomSquadScript:
    """
    Natural language: <b>Avenge (3):</b> Deal 10 damage to the
    highest-Health enemy minion.

    Formal spec:
      1. avenge_threshold = 3 = 文本 "Avenge (3)" 字面量（CardDef 无模板
         参数——data 仅标 avenge=true；enemy 侧最高血量选择见 §3）
      2. 对手定位: game._active_combat = (hero_a, hero_b)（combat.py:77
         CombatScheduler.run 设置、finally 置 None）→ 取本奖励控制者
         之外的一方; 无战斗对 → 落空（Avenge 引擎守卫: 非战斗不计数）
      3. 候选 = 对手棋盘存活随从（文本无嘲讽/潜行限制——damage 类效果
         不受嘲讽约束）; 选键 = **当前** HEALTH（英文 "highest-Health"
         的 HS 术语口径 = 当前生命; "maximum Health" 才会写 maximum。
         多语言佐证: deDE "höchsten Leben" / jaJP "最も体力が高い" /
         koKR "생명력이 가장 높은" 均指当前生命。2026-09-02 对抗审查
         证伪: 旧实现用 max_health → 战斗中敌方"上限高但已被打残"的
         随从被优先选中）; 并列 game.rng.choice 随机
      4. 效果 = Hit(target, 10)——法术式伤害实例（圣盾照常抵消、
         不触发剧毒），经 run_script_hook → run_actions 入队结算
      5. 只作用于当前战斗对手（owner 隔离: 本人棋盘/对手奖励互不越界）

    Test: test_batch_quest_rewards2.py — 真实 run_combat 内第 3 次友方
      死亡后敌方最高当前生命随从恰好 -10（damage 事件探针）/
      "上限高但残血"不优先 / 第 2 次不触发 / 触发后 AVENGE_COUNTER
      清零 / 敌方无随从落空 / 对手奖励不烧本方

    Params: avenge_threshold=3 damage=10（文本字面量
            "Avenge (3): Deal 10 damage"）
    """

    avenge_threshold = 3   # 文本字面量（CardDef 无模板参数）

    @staticmethod
    def avenge(source, game, ctx):
        hero = _reward_hero(source)
        if hero is None:
            return None
        opponent = _combat_opponent(game, hero)
        if opponent is None:
            return None
        cands = [m for m in opponent.board if not m.dead]
        if not cands:
            return None
        top = max(m.health for m in cands)
        tied = [m for m in cands if m.health == top]
        target = game.rng.choice(tied, label="boom_squad_target")
        return Hit(target, 10)


# ══════════════════ BG28_Reward_504 Cycle of Energy ══════════════════

class CycleOfEnergyScript:
    """
    Natural language: <b>Avenge (3):</b> Get a random Tavern spell.

    Formal spec:
      1. avenge_threshold = 3 = 文本 "Avenge (3)" 字面量（CardDef 无模板
         参数——data 仅标 avenge=true）
      2. avenge: 随机酒馆法术 = db.pool_spells() ∩ spell_pool.available
         > 0（_random_pool_spell）; 无候选 → 落空
      3. "Get" = 进手牌: spell_pool.acquire 占池（P2）+ create_spell +
         game.pending_hand_add（满手排队等待，RULES §3.3——禁止直接
         append）
      4. acquire 失败（本函数内刚校验过 available>0，理论不可达）→
         GameStateError fail-loud，不静默吞掉池记账
      5. 只进本奖励控制者手牌（owner 隔离）

    Test: test_batch_quest_rewards2.py — 第 3 次友方死亡后手牌新增 1 张
      池法术且 spell_pool 可用数 -1 / 第 2 次不触发 / 计数清零 /
      对手手牌与其池记账不变

    Params: avenge_threshold=3（文本字面量 "Avenge (3)"）
    """

    avenge_threshold = 3   # 文本字面量（CardDef 无模板参数）

    @staticmethod
    def avenge(source, game, ctx):
        hero = _reward_hero(source)
        if hero is None:
            return None
        cid = _random_pool_spell(game)
        if cid is None:
            return None
        if not game.spell_pool.acquire(cid):
            raise GameStateError(
                f"Cycle of Energy: acquire failed for {cid}")
        spell = game.create_spell(cid, controller=hero)
        if spell is None:
            game.spell_pool.release(cid)
            return None
        game.pending_hand_add(hero, spell)
        return None


# ══════════════════ BG28_Reward_518 Stable Amalgamation ══════════════════

class StableAmalgamationScript:
    """
    Natural language: <b>Avenge (7):</b> When you have space, summon a
    50/50 Amalgam.

    Formal spec:
      1. avenge_threshold = 7 = 文本 "Avenge (7)" 字面量（CardDef 无模板
         参数——data 仅标 avenge=true）
      2. avenge: 满场守卫——hero.board_full()（7/7，C.BOARD_SIZE）为真
         → 落空（文本 "When you have space" 的条件子句；官方无"排队
         等待空位"记载，触发时无空位即不召唤）
      3. 召唤 token BG28_Reward_518t "Totally Normal Horse"（CardDef
         50/50、card_race=26=Race.ALL 全种族; 非池卡 → 不占池副本）;
         经 Summon Action（game.summon——满场二次守卫并 fire
         minion_overflow）
      4. 只召唤到本奖励控制者棋盘; 战斗中召唤物属于本场战斗
         （战后快照回滚由引擎处理）

    Test: test_batch_quest_rewards2.py — 第 7 次友方死亡后 token 入场且
      属性 = CardDef 50/50 / 第 6 次不触发 / 触发后计数清零 / 满场
      直接调用钩子不召唤 / 对手棋盘不变

    Params: avenge_threshold=7（文本字面量 "Avenge (7)"）;
            token atk=50 health=50（BG28_Reward_518t CardDef 权威——
            非本卡模板参数）
    """

    avenge_threshold = 7   # 文本字面量（CardDef 无模板参数）

    @staticmethod
    def avenge(source, game, ctx):
        hero = _reward_hero(source)
        if hero is None:
            return None
        if hero.board_full():
            return None       # "When you have space" 条件子句
        return Summon(hero, AMALGAM_TOKEN_ID)


# ══════════════════ BG33_Reward_004 Grim Freshener ══════════════════

class GrimFreshenerScript:
    """
    Natural language: <b>Avenge (2):</b> Gain a free <b>Refresh</b>.

    Formal spec:
      1. avenge_threshold = 2 = 文本 "Avenge (2)" 字面量（CardDef 无模板
         参数——data 仅标 avenge=true）
      2. avenge: hero.FREE_REFRESH_REMAINING += 1（叠加式——
         Nozdormu / batch_choose_one "Refreshes" 同口径）
      3. 消费点核实: game.refresh_tavern 非 auto 路径**优先**消耗免费
         次数（game.py:322-325，先于金币/生命）→ 本次 free Refresh
         价值 = 该次手动刷新 0 金; auto=True 的回合开始刷新跳过计费，
         免费次数留存给本回合玩家操作
      4. 只写本奖励控制者的 tag（owner 隔离）

    Test: test_batch_quest_rewards2.py — 第 2 次友方死亡后免费次数 = 1
      且下一次手动刷新金币不变、次数归 0 / 第 1 次不触发 / 计数清零 /
      免费次数耗尽后回落扣金 / 对手免费次数不变

    Params: avenge_threshold=2（文本字面量 "Avenge (2)"）
    """

    avenge_threshold = 2   # 文本字面量（CardDef 无模板参数）

    @staticmethod
    def avenge(source, game, ctx):
        hero = _reward_hero(source)
        if hero is None:
            return None
        hero.set(GameTag.FREE_REFRESH_REMAINING,
                 hero.get(GameTag.FREE_REFRESH_REMAINING, 0) + 1)
        return None


# ══════════════════ BG27_Reward_504 Timeline Acceleration ══════════════

class TimelineAccelerationScript:
    """
    Natural language: [x]At the start of each turn, get two Accelerators
    that transform a minion into one from a Tier higher.

    Formal spec:
      1. start_of_turn（game._begin_recruit_for: 饰品 → 任务奖励 →
         随从; game.py:223-228）——只在**本奖励控制者**的回合开始触发
         （"your turn" 口径; 奖励实体不存在于对手的 quest_rewards 列表）
      2. 每次触发获取 2 张 BG27_Reward_504t "Accelerator"（文本 "two"
         字面量）进手牌: create_spell + game.pending_hand_add（满手
         排队，RULES §3.3）
      3. Accelerator 为非池法术（card_type=5，不在 bg_pool_spells.json）
         → 不占池副本（SOP §3 token 语义）; 两张为独立实例（"two
         Accelerators" 非 "Get N copies" 单份语义）
      4. 每回合各触发一次（回合频率由 start_of_turn 分发保证）

    Test: test_batch_quest_rewards2.py — 一次 start_of_turn 后手牌新增
      恰好 2 张 BG27_Reward_504t / 再触发一次再 +2 / 对手手牌不变 /
      spell_pool 无记账变化（非池法术）

    Params: count=2（文本字面量 "two Accelerators"）
    """

    @staticmethod
    def start_of_turn(source, game, ctx):
        hero = _reward_hero(source)
        if hero is None:
            return None
        for _ in range(2):
            spell = game.create_spell(ACCELERATOR_ID, controller=hero)
            if spell is None:
                continue
            game.pending_hand_add(hero, spell)
        return None


# ══════════════════ BG27_Reward_504t Accelerator ══════════════════

class AcceleratorScript:
    """
    Natural language: Transform a minion into one from a Tier higher.

    Formal spec:
      1. needs_target = True（"Transform a minion"）——引擎 play_spell 产生
         PendingChoice(kind="spell_target")，候选默认 = 控制者棋盘存活
         随从（game.py:904-914）; 无候选时法术照常消耗、效果落空
      2. on_play: target.tech_level + 1 为目标档位; 上限
         game.max_tavern_tier（每局 T6，异变 Secrets of Norgannon 可
         为 7）——T6 目标在标准局变形为同档 T6
      3. 候选 = _pool_candidates(game, min_tier=new_tier, max_tier=new_tier)
         （池剩余量 / active_races 口径——batch_spells3 Robust Evolution
         同构）; 无候选 → 落空（不占池、不变形）
      4. 占池（P2）: minion_pool.acquire; 普通目标 1 份，金色目标
         min(3, 剩余) 份（三连金占 3 副本——Lockbox / Robust Evolution
         先例）; acquire 失败 → GameStateError fail-loud
      5. Transform(target, new_id, keep_buffs=True)——保留附魔与金色
         （stats.py Transform Action: 金色按 db.golden_version 新建、
         _buffs 整体转移）; 文本未声明 "keeps its stats" → 不做属性
         校正（与 Robust Evolution 的差异点）
      6. 变形后位置 = 原棋盘位（Transform Action 保证）; 旧实体
         zone=REMOVED 并注销监听器

    Test: test_batch_quest_rewards2.py — T1 目标 → T2 随机池随从且
      占池 1 份 / 附魔保留 / 金色目标 → 金色新随从且占池 3 份 /
      T6 目标 → 上限档 T6（标准局）/ 无目标候选时法术落空不变形 /
      对手棋盘不受影响

    Params: tier_step=1（"a Tier higher" = 恰好 +1——hsdata 多语言
            zhCN "高一级" / deDE "eine Stufe höher" / jaJP "グレードの
            1高い" / zhTW "高一級" 与 Robust Evolution 裁定同源）;
            上限 = game.max_tavern_tier（运行时）
    """

    needs_target = True

    _TIER_STEP = 1     # "a Tier higher" = 恰好 +1（多语言 locale 裁定）

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        hero = _reward_hero(source)
        if target is None or hero is None:
            return None
        # target not in hero.board: 第一发 Accelerator 已把该实体
        # Transform 掉（zone=REMOVED），第二发仍持有同一实体引用时
        # Transform 会 GameStateError 中断回合——对抗审查实测
        # (Timeline Acceleration 每回合给 2 张, 可对同一随从连打两张)。
        # 失活引用按落空处理（B030_804 Robust Evolution 同款 guard）
        if (not isinstance(target, Minion) or target.dead
                or target not in hero.board):
            return None
        new_tier = min(target.tech_level + AcceleratorScript._TIER_STEP,
                       game.max_tavern_tier)
        cands = _pool_candidates(game, min_tier=new_tier, max_tier=new_tier)
        if not cands:
            return None       # 目标档池空 → 落空（法术照常消耗）
        new_id = game.rng.choice(cands, label="accelerator_new_minion")

        copies = 3 if target.is_golden else 1
        got = min(copies, game.minion_pool.available(new_id))
        for _ in range(got):
            if not game.minion_pool.acquire(new_id):
                raise GameStateError(
                    f"Accelerator: acquire failed for {new_id}")
        # 池不足 3 份时只扣到 partial golden —— 必须打 GILDED_NOT_TRIPLED
        # （回池 1 份），否则"扣 1 退 3"净泄漏 2 份（对抗审查 N3）
        return Transform(target, new_id, keep_buffs=True,
                         gilded_not_tripled=bool(target.is_golden
                                                 and got < 3))


def register() -> list[str]:
    """注册任务奖励批 2（6 个 id）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG27_Reward_502", BoomSquadScript),
        ("BG28_Reward_504", CycleOfEnergyScript),
        ("BG28_Reward_518", StableAmalgamationScript),
        ("BG33_Reward_004", GrimFreshenerScript),
        ("BG27_Reward_504", TimelineAccelerationScript),
        ("BG27_Reward_504t", AcceleratorScript),
    ]
    registered = []
    for rid, cls in pairs:
        reg(rid, cls)
        registered.append(rid)
    return registered
