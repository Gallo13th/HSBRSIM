"""批次 quest_rewards4 — 任务奖励第四批（5 张 "Get a copy of '{0}'" 族）。

数据来源: `data/bg_quest_rewards.json` / `data/bg_cards.json`（CardDB）。
本批全部消费**新数据链** `CardDef.reward_dbf_id`（生成器导出的 XML
Tag2673 `BACON_CARD_DBID_REWARD`）——"Get a copy of '{0}'" 的 `{0}`
是**卡**不是数值: 奖励文本在客户端由该 tag 的 dbf id 解析成卡名
（所有 locale 的 {0} 均为卡名占位; wiki 卡片页把未解析的 {0} 显示为
'another card'，hu 站显示为空——两处都证明 {0} 是运行时填入的卡引用）。
一律 `game.db.by_dbf(def.reward_dbf_id)` 运行时解析，**禁止硬编码 id**。

实现（5 张奖励）:
  BG24_Reward_130   Ghastly Mask      — 获取 {0}=BGS_009 Lightfang
                      Enforcer 的一张副本 + `eot_extra += 1`
  BG27_Reward_802   Gilnean War Horn  — 获取 {0}=BGS_043 Murozond 的副本
                      + `bc_times += 1`（单独声明 = 全部己方战吼）
  BG27_Reward_803   Turbulent Tombs   — 获取 {0}=BG25_009 Eternal
                      Summoner 的副本 + `dr_extra += 1`
  BG33_Reward_021   Rallying Cry      — 获取 {0}=BG33_240 Charmwing 的副本
                      + `rally_extra += 1`
  BG28_Reward_510   Secret Culprit    — 获取 {0}=BG27_518 Moira
                      Bronzebeard（Tier 7）的副本

卡 id 勘误（2026-09-02 数据核实）: 作业单里的 "BG28_Reward_021 Rallying
Cry" / "BG24_Reward_510 Secret Culprit" 在 data 中不存在; 按名字查
`bg_quest_rewards.json` 得真实 id = **BG33_Reward_021** / **BG28_Reward_510**
（SOP §11 教训 5: 一律按名字查 CardDB 取 id，禁止凭记忆写 id）。

Secret Culprit 读法（主线已裁定）: 文本 "Get a copy of '{0}' from
Tier 7." 中 `{0}` 由 tag 2673=103502 解析为 **BG27_518 Moira
Bronzebeard**（tech_level=7、`is_pool_minion=False`——被轮换出标准池的
T7 奖励专属随从）。"from Tier 7" 是该卡**档位描述**，不是"随机 T7 池
抽取": 5 张奖励的 `{0}` 都是固定卡（XML 全库仅这 5 个实体带 tag 2673，
各自对应一张具体随从），且 Moira 本就是 T7。故与其余 4 张同构——
授予 `by_dbf(reward_dbf_id)` 的副本，**不**改写 `game.max_tavern_tier`、
**不**从 T7 池抽样（那样会丢弃 {0} 的信息）。副本语义 = "Get a copy"
默认: **白板副本**（非金色、不复制附魔——SOP §3 动词核对表;
Murozond 自身文本亦用 "plain copy" 表达同族语义）。

引擎接线核实（SOP §14 "假接线" 排查）:
  - `on_bind` 分发: `game.complete_quest` → `run_script_hook(reward,
    "on_bind", ctx={"hero": hero})`（game.py:2359-2368）
  - `extra_triggers` 消费点均为真实生产路径（RULES §6.20）:
    `eot_extra` → `end_recruit_phase`（game.py:1830）;
    `bc_times` → `_finish_play_minion`（game.py:714-726）;
    `dr_extra` → `_process_single_death`（game.py:1704-1707）;
    `rally_extra` → `game.run_rally`（game.py:1945-1949）
  - `by_dbf` 二次映射: `CardDB.load` 注册 `dbf_id → CardDef`
    （db.py:96-108; 同 dbf 重复注册保留首个定义）
  - 池记账: `minion_pool.acquire` 是"获取随从"的唯一闸门
    （SOP §3 / RULES §2.3-2.4）; 非池卡（token / 池外轮换卡）
    `release` 亦 no-op → 零池操作

DEFERRED（3 张本轮复核仍缺原语，不注册——二态铁律）:
  BG24_Reward_719 The Golden Hammer — Spellcraft 法术 "Make a friendly
    minion Golden **until next turn**" 需要**临时金色**原语: 引擎无
    GOLDEN_UNTIL/temporary 金色 tag，也无金色卡定义回滚点
    （`clear_temporary_buffs` 只处理附魔，不还原 CARD_ID/BASE_ATK/
    BASE_HEALTH/scripts）。Dependency: 临时金色 tag + 回合回滚点。
  BG24_Reward_113 Ritual Dagger — "After a friendly Deathrattle minion
    dies, give it +5/+5 permanently." 死亡时点实体已 zone=GRAVEYARD，
    且战斗期增益默认被战后快照回滚; 引擎只有实体级
    `PERSIST_COMBAT_CHANGES/PERSIST_DOUBLE`（会保留该随从全部战斗期
    变化且须战前设置）与 `_permanence_pending`（仅法术结算窗口内的
    temporary buff），**无逐 Buff 的永久标记**。Dependency: 逐 Buff
    持久化标记（死亡实体可观测）。
  BG28_Reward_500 Beyond the Mirage — "Tavern spells cost (1) less."
    需要**常驻**酒馆法术折扣钩子; 引擎只有一次性
    `NEXT_SPELL_COST_REDUCTION`（`buy_from_tavern` 成交即清零,
    game.py:513-531）。Dependency: 常驻 hero 级酒馆法术折扣 tag +
    购买路径读取。
"""

from __future__ import annotations

from hsrl2.tags import CardType

# ── 额外触发配额 key（RULES §6.20 契约字符串）──
EOT_EXTRA = "eot_extra"
BC_TIMES = "bc_times"
DR_EXTRA = "dr_extra"
RALLY_EXTRA = "rally_extra"


def register() -> list[str]:
    """注册任务奖励批 4（5 张 "Get a copy of '{0}'" 族）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG24_Reward_130", GhastlyMaskScript),
        ("BG27_Reward_802", GilneanWarHornScript),
        ("BG27_Reward_803", TurbulentTombsScript),
        ("BG33_Reward_021", RallyingCryScript),
        ("BG28_Reward_510", SecretCulpritScript),
    ]
    registered = []
    for rid, cls in pairs:
        reg(rid, cls)
        registered.append(rid)
    return registered


# ══════════════════ 共享效果体 ══════════════════

def _reward_target(game, source):
    """`{0}` 指向的卡定义（XML Tag2673 → dbf → CardDef）。

    数据链断裂（无 tag / db 无该 dbf）→ None（不近似实现）。
    """
    d = game.db.get(source.card_id)
    if d is None or d.reward_dbf_id is None:
        return None
    return game.db.by_dbf(d.reward_dbf_id)


def _grant_reward_copy(game, hero, source):
    """授予 `{0}` 的一张白板副本进手牌（满手排队 RULES §3.3）。

    池记账（RULES §2.3/§2.4 + SOP §3）:
      - `{0}` 是池随从 → 必须先 `minion_pool.acquire` 占池（与
        Discover/GetRandomMinion 同口径）; 池中无副本 → 本次获取落空
        （RULES §2.4 "池中无副本的随从不可被任何玩家获取"）
      - 非池卡（token / 被轮换出池的奖励专属卡，如 Lightfang/Murozond/
        Charmwing/Moira）→ **零池操作**（release 亦 no-op）
    副本为**白板**（create_minion golden=False 默认）: 文本无"金色"、
    无"保留附魔"，且授予源不是已有实体 → 不复制任何 buff（SOP §3）。
    返回 True=已入手 / False=落空或仅入等待队列。
    """
    target = _reward_target(game, source)
    if target is None or target.card_type != CardType.MINION:
        return False
    if target.is_pool_minion:
        if not game.minion_pool.acquire(target.id):
            return False          # 池耗尽 → 获取落空（RULES §2.4）
    copy = game.create_minion(target.id, controller=hero)
    if copy is None:
        return False
    return game.pending_hand_add(hero, copy)


def _bind(source, game, ctx, extra_key=None):
    """on_bind 公共体: 授予 `{0}` 副本（+ 可选额外触发配额）。"""
    hero = ctx.get("hero") if ctx else getattr(source, "controller", None)
    if hero is None:
        return None
    _grant_reward_copy(game, hero, source)
    if extra_key is not None:
        # 永久额度（脚本侧只写额度; 引擎消费"已用次数"，RULES §6.20）
        hero.extra_triggers[extra_key] = hero.extra_trigger(extra_key) + 1
    return None


# ══════════════════ BG24_Reward_130 Ghastly Mask ══════════════════

class GhastlyMaskScript:
    """
    Natural language: Get a copy of '{0}'. Your end of turn effects
    trigger an extra time.

    Formal spec:
      1. on_bind（获得奖励时一次性结算，文本无时机子句）:
         a. 获取 `{0}` 的一张白板副本进手牌; `{0}` =
            `db.by_dbf(def.reward_dbf_id)`（本卡 dbf 59707 =
            BGS_009 Lightfang Enforcer, tech_level=5,
            is_pool_minion=False → 零池操作）
         b. `hero.extra_triggers["eot_extra"] += 1`——永久额度;
            引擎在 `end_recruit_phase` 按
            `1 + extra_trigger("eot_extra")` 次触发**每个**己方 EoT
            效果（随从/饰品/任务奖励，RULES §6.20，与 Drakkari 叠加）
      2. 只写本奖励控制者的 hero 状态（owner 隔离——对手 eot_extra 不变）
      3. 重复获得同奖励 → 额度累加（文本无"唯一"限定）

    Test: test_batch_quest_rewards4.py — 真实 `complete_quest` 后手牌
      恰为该卡的白板副本（card_id/golden=False/无附魔）; 零池操作;
      真实 `end_recruit_phase` 下棋盘探针 EoT 钩子被调用 **2** 次
      （基线 1 + 配额 1）; 对手探针仍 1 次（owner 隔离）

    Params: 无数值模板参数（{0} 是卡引用，经 reward_dbf_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return _bind(source, game, ctx, extra_key=EOT_EXTRA)


# ══════════════════ BG27_Reward_802 Gilnean War Horn ══════════════════

class GilneanWarHornScript:
    """
    Natural language: Get a copy of '{0}'. Your <b>Battlecries</b>
    trigger an extra time.

    Formal spec:
      1. on_bind: a. 获取 `{0}` 的白板副本（db.by_dbf(60637) =
         BGS_043 Murozond, T5, 非池卡 → 零池操作）;
         b. `hero.extra_triggers["bc_times"] += 1`——**单独**声明
         `bc_times`（不声明 `bc_race`）= 全部己方战吼 +1 次
         （RULES §6.20; 引擎消费点 `_finish_play_minion`）
      2. 只写本奖励控制者（owner 隔离）
      3. 额度永久（无每回合重置）; 重复获得累加

    Test: test_batch_quest_rewards4.py — 真实 `complete_quest` 后手牌为
      Murozond 白板副本 / 零池操作; 随后真实 `play_minion` 打出带探针
      战吼的随从 → 探针被调用 **2** 次（基线 1 + 配额 1）; 对手打出
      同一随从仍 1 次（owner 隔离正对照）

    Params: 无数值模板参数（{0} 经 reward_dbf_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return _bind(source, game, ctx, extra_key=BC_TIMES)


# ══════════════════ BG27_Reward_803 Turbulent Tombs ══════════════════

class TurbulentTombsScript:
    """
    Natural language: Get a copy of '{0}'. Your <b>Deathrattles</b>
    trigger an extra time.

    Formal spec:
      1. on_bind: a. 获取 `{0}` 的白板副本（db.by_dbf(95263) =
         BG25_009 Eternal Summoner, T6）——本卡 **is_pool_minion=True**
         → 走 `minion_pool.acquire` 占池（RULES §2.3/§2.4）; 池耗尽
         → 该副本落空（但第二句的配额仍生效——两句独立）;
         b. `hero.extra_triggers["dr_extra"] += 1`——永久全部己方亡语
         +1 次（引擎消费点 `_process_single_death`，仅战斗内计数路径）
      2. 只写本奖励控制者（owner 隔离）
      3. 额度永久; 重复获得累加

    Test: test_batch_quest_rewards4.py — 真实 `complete_quest` 后手牌为
      Eternal Summoner 白板副本且该卡池剩余 −1（占池）; 池提前抽干时
      副本落空但 `dr_extra` 仍 =1（正对照: 池有余时确实入手）;
      战斗内 `_process_single_death` 让带探针亡语的随从调用 **2** 次;
      对手亡语仍 1 次（owner 隔离正对照）

    Params: 无数值模板参数（{0} 经 reward_dbf_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return _bind(source, game, ctx, extra_key=DR_EXTRA)


# ══════════════════ BG33_Reward_021 Rallying Cry ══════════════════

class RallyingCryScript:
    """
    Natural language: Get a copy of '{0}'. Your <b>Rallies</b> trigger
    an extra time.

    Formal spec:
      1. on_bind: a. 获取 `{0}` 的白板副本（db.by_dbf(122086) =
         BG33_240 Charmwing, T6, is_pool_minion=False → 零池操作）;
         b. `hero.extra_triggers["rally_extra"] += 1`——永久额度;
         引擎在 `game.run_rally`（攻击宣告与招募期攻击两条路径）按
         `1 + extra_trigger("rally_extra")` 次触发**每个**己方 Rally
         （RULES §6.20; 与召唤时先攻无关）
      2. 只写本奖励控制者（owner 隔离）
      3. 额度永久; 重复获得累加

    Test: test_batch_quest_rewards4.py — 真实 `complete_quest` 后手牌为
      Charmwing 白板副本 / 零池操作; 真实 `run_combat`（探针随从攻击）
      下 rally 钩子调用次数为无奖励基线的 **2 倍**（配额 1）;
      对手棋盘探针不受影响（owner 隔离）

    Params: 无数值模板参数（{0} 经 reward_dbf_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return _bind(source, game, ctx, extra_key=RALLY_EXTRA)


# ══════════════════ BG28_Reward_510 Secret Culprit ══════════════════

class SecretCulpritScript:
    """
    Natural language: Get a copy of '{0}' from Tier 7.

    Formal spec:
      1. `{0}` = `db.by_dbf(def.reward_dbf_id)`（本卡 dbf 103502 =
         BG27_518 **Moira Bronzebeard**, tech_level=7,
         is_pool_minion=False——被轮换出标准池、仅本奖励可得的 T7
         奖励专属随从）。"from Tier 7" 是该卡档位描述（XML tag 2673
         在本卡上唯一取值为 Moira）; **不**改写 `game.max_tavern_tier`，
         **不**从 T7 池随机抽样（主线裁定 2026-09-02）
      2. on_bind: 获取该卡的一张**白板副本**进手牌（非金色、无附魔——
         "Get a copy" 默认语义）; 非池卡 → **零池操作**
      3. 本奖励无额外触发子句（第二句不存在）
      4. 只进本奖励控制者的手牌（owner 隔离）

    Test: test_batch_quest_rewards4.py — 真实 `complete_quest` 后手牌
      恰为 BG27_518（由 reward_dbf_id 运行时解析，测试不硬编码期望 id
      之外还断言 == db.by_dbf(def.reward_dbf_id).id）且非金色、属性
      等于 CardDef 基础值; 池记账不变; `game.max_tavern_tier` 不变
      （正对照: 授予的是 T7 卡但无需解锁 T7）; 对手手牌为空

    Params: 无数值模板参数（{0} 经 reward_dbf_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return _bind(source, game, ctx, extra_key=None)
