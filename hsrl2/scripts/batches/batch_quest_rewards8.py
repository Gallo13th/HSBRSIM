"""批次 quest_rewards8 — Essence of Zerus + 载荷 Shifter Zerus（作业单 2026-09-18 第四十九轮）。

**权威序（项目所有者 2026-09-18 裁定）**: wiki 详细说明 > 卡面自然语言理解。
本批的 wiki 说明是**详细且逐条**的（比此前台账假设的"缺权威"更强），故
两张卡均可精确实现，不构成近似。

台账来源: `batch_hero_rewards_final.py` 文末 DEFERRED 台账第 3 条
（`BG24_Reward_362` Essence of Zerus —— "At the end of your turn, get a
Shifter Zerus which transforms into random minions."）。此前 DEFERRED 理由
为「授予物 `BGS_029` 缺"手牌每回合变形"脚本; "a random minion" 的 tier 口径
亦无权威」。2026-09-18 逐条核实后**两条均不成立**。

**引擎原语逐条核对（2026-09-18）**
═══════════════════════════════════════════════════════════════════════
  | 需求 | 现成原语 / 生产点 | 本批消费卡 |
  |------|-------------------|-----------|
  | EoT 授予白板 token 进手牌 | `Game.grant_card_copy_to_hand`（非池 token
    零池操作；满手 → `pending_hand_add` 等待队列） | 362 |
  | 手牌实体卡面替换 + 保留附魔 | **无现成 Action**——`Transform`
    （`actions/stats.py`）只支持**棋盘**（`target not in controller.board`
    直接抛）。手牌变形在脚本层实现（同 `Hero.add_to_hand` 直接改 zone 的
    既有口径; 不新增引擎原语，因为机制是"每次附魔事件"级的卡脚本行为） | BGS_029 |
  | 每回合开始触发（按**持有者**回合） | `TURN_START` 事件（`hero=` kwarg，
    `game._begin_recruit_for` 每英雄一次） | BGS_029 |
  | 随机随从选择 | `game.rng.choice` + `db.pool_minions()` **+ 显式追加
    `BGS_029` 自身**（引擎既有 "random minion" 口径; `BGS_029`
    `is_pool_minion=False`，不在 `pool_minions()` 内——2026-09-18
    对抗审查修复：旧实现漏加自身，与 wiki "including Shifter Zerus"
    不符） | BGS_029 |

**wiki 证据（逐条逐字）**
═══════════════════════════════════════════════════════════════════════
  1. `https://hearthstone.wiki.gg/wiki/Battlegrounds/Essence_of_Zerus`
     oldid=805429: "At the end of your turn, get a Shifter Zerus which
     transforms into random minions."；页 tags `derived_relatedCardDbfIds
     =57742`（= `BGS_029` 的 dbfId）→ **载荷就是 BGS_029**。
  2. `https://hearthstone.wiki.gg/wiki/Battlegrounds/Shifter_Zerus`
     oldid=891260: "Card id: `BGS_029`" / "Each turn this is in your hand,
     transform it into a random minion. **It keeps enchantments.**"；
     Golden (`TB_BaconUps_095`, dbfId 60233): "...transform it into a
     random **golden** minion. It keeps enchantments."；Tavern Tier 3；
     "This minion is currently not available in games."
  3. **变形池（权威）**: `https://hearthstone.wiki.gg/wiki/Battlegrounds`
     oldid=902245: "**Shifter Zerus can transform into any Battlegrounds
     minion, including Shifter Zerus. It doesn't pull from the shared
     pool.**" → 池 = 任意 BG 随从（含自身）、**不占共享池**、**无 Tavern
     Tier 限制**（这直接消解旧台账"tier 口径无权威"的顾虑）。
  4. **时机（权威）**: `https://hearthstone.wiki.gg/wiki/Shifter_Zerus`
     oldid=810477（构造版同卡 Notes）: "Even though the card text reads
     'Each turn', Shifter Zerus transforms **only at the start of the
     possessing player's turn**." / "Advanced: Shifter Zerus's
     transformation is a trigger in the **Start of Turn Phase**." →
     引擎 `TURN_START`（按持有者回合、招募期开始）为对应时点。
  5. **保留附魔（权威）**: `https://hearthstone.wiki.gg/wiki/Patch_27.6.0.187190`
     oldid=868288: "[Battlegrounds] Shifter Zerus will now **carry over
     enchantments** when it transforms in hand (meaning, if it gets buffs
     while it's in your hand, they won't be erased when it transformed)."
  6. `BG24_Reward_362` 自身页 `https://hearthstone.wiki.gg/wiki/Battlegrounds
     /Essence_of_Zerus` oldid=805429 Patch: "34.2.0.231720 (2025-12-02):
     Now reads: '...get a Shifter Zerus...' (previously: '...get a
     'Shifter Zerus'...')"。无 Notes 段（机制说明在 1–5）。

**残留未明示项（不阻塞，记录在案）**: wiki 未明示 `random` 是否**均匀
分布**（本实现用引擎既有 `rng.choice` 等权——与全仓其它 "random minion"
同口径，Malygos 先例）; 未明示"每次变形几张"（按 BGS_029 文本 = 每回合
1 张）。

**CORRECT 2 项（注册 2 个 id）**
═══════════════════════════════════════════════════════════════════════
  BG24_Reward_362 Essence of Zerus（任务奖励）— `on_bind` 注册
      `TURN_END owner=hero` 监听 → 每个自己的回合结束
      `grant_card_copy_to_hand(hero, BGS_029)`（白板、非金、零池记账;
      满手 → 等待队列）。
  BGS_029 Shifter Zerus（**非池** token 随从）— `on_bind` 注册
      `TURN_START owner=hero` 监听 → 在自己回合开始时**若仍在手牌**，
      替换为随机 BG 随从（保留 `_buffs`、保持手牌位次、`zone=HAND`、
      同一 controller）。金色 Zerus → 随机**金色**随从
      （`golden=target.is_golden`）。无合法候选（空池）→ 落空（不变形、
      不抛错）。

测试: `hsrl2/tests/test_batch_quest_rewards8.py`（真实 `complete_quest`
→ 真实 `end_recruit_phase`/EoT → 手牌出现 Zerus → 真实 `turn_start` →
卡面替换 + 附魔保留 + 手牌位次/数量; **自身变形可发生**——候选含
`BGS_029`，用受控 RNG 选中自身走真实变形路径断言结果仍为 `BGS_029`;
**不占池**负对照——变形前后 `minion_pool.total_remaining()` 不变; 负对照:
不在手牌不变形、对手回合不变形、对手获得不触发本人 EoT; 变异: 去掉保留
附魔 / 去掉手牌判定 / 去掉自身候选必须失败）。
"""

from __future__ import annotations

from hsrl2.events import TURN_END, TURN_START, Listener

REWARD_ID = "BG24_Reward_362"
ZERUS_ID = "BGS_029"


def _random_minion_id(game, golden: bool) -> str | None:
    """随机 BG 随从 id（含 Zerus 自身; 无 tier 限制; 不占共享池）。

    权威: `Battlegrounds` oldid 902245（= 该页当前修订；页面
    `Special:CiteThisPage` 实测 `id=902245`）——"can transform into any
    Battlegrounds minion, including Shifter Zerus. It doesn't pull from
    the shared pool." → 候选 = `db.pool_minions()`（池定义集，作为"任意
    BG 随从"的可实现代表）**+ `BGS_029` 自身**。`BGS_029` 的
    `is_pool_minion=False`，`db.pool_minions()` 不包含它，故必须显式
    追加——否则 "including Shifter Zerus" 落空（2026-09-18 对抗审查
    修复）。金色路径用 `db.golden_version` 换金色独立卡定义。

    池记账: 候选枚举与 `create_minion` 均**不触碰** `minion_pool`——
    本函数只读 `is_pool_minion` 标志，`_transform_in_hand` 走
    `create_minion`（零 acquire/release）。与 "It doesn't pull from the
    shared pool." 一致；负对照见
    `test_batch_quest_rewards8.py::TestHandTransform.test_transform_does_not_consume_pool`。
    """
    cands = [d for d in game.db.pool_minions()]
    self_def = game.db.get(ZERUS_ID)
    if self_def is not None and all(d.id != ZERUS_ID for d in cands):
        cands.append(self_def)
    if not cands:
        return None
    pick = game.rng.choice(cands, label="shifter_zerus_transform")
    if golden:
        gd = game.db.golden_version(pick)
        return gd.id if gd is not None else pick.id
    return pick.id


def _transform_in_hand(game, minion, hero) -> bool:
    """手牌内卡面替换（保留附魔/位次/控制者）。返回 True = 已变形。

    与棋盘 `Transform`（`actions/stats.py`）的区别只在于**区域**: 手牌
    无板位概念，故原地替换 `hero.hand[idx]`；`_buffs` 整体转移（不复制
    引用之外的任何共享状态——`Transform` 同款），HEALTH 按新卡定义重算
    并 clamp 到新上限（不因变形治疗）。
    """
    from hsrl2.tags import GameTag, Zone
    # 调用方（`on_sot`）已保证 `minion in hero.hand`——此处不再重复判定
    # （用 `hero.hand.index` 兜底: 不在手牌会抛 ValueError，属 fail-loud
    # 的调用方契约违反，不是被吞掉的静默第三态）。
    new_id = _random_minion_id(game, minion.is_golden)
    if new_id is None:
        return False
    new = game.create_minion(new_id, controller=hero,
                             golden=minion.is_golden)
    if new is None:
        return False
    new._buffs = list(minion._buffs)
    new.set(GameTag.HEALTH, min(new.max_health, max(1, minion.health)))
    idx = hero.hand.index(minion)
    new.zone = Zone.HAND
    hero.hand[idx] = new
    minion.zone = Zone.REMOVED
    game.events.unregister_owner(minion)
    game.events.fire(game, "transform", old=minion, new=new)
    game.run_script_hook(new, "on_transform", ctx={"old": minion})
    return True


# ══════════════ BG24_Reward_362 Essence of Zerus ══════════════


class EssenceOfZerusScript:
    """
    Natural language: At the end of your turn, get a Shifter Zerus which
    transforms into random minions.

    Evidence: `data/bg_quest_rewards.json` BG24_Reward_362（card_type 40
    = BACON_QUEST_REWARD; `derived_relatedCardDbfIds=57742` → `BGS_029`）。
    wiki `Battlegrounds/Essence_of_Zerus` oldid=805429（逐字文本见模块
    docstring）; 载荷规则见 `Battlegrounds/Shifter_Zerus` oldid=891260 与
    `Battlegrounds` oldid=902245。

    Formal spec:
      1. on_bind(source, game, ctx): 奖励实体已由 `complete_quest` 放入
         `hero.quest_rewards`
      2. 注册 `TURN_END owner=hero` 监听（`end_recruit_phase` 开头广播，
         每英雄一次）→ `grant_card_copy_to_hand(hero, BGS_029)`
      3. 白板副本（不复制附魔、非金）、零池记账（`BGS_029` 非池 token;
         `grant_card_copy_to_hand` 的非池分支）; 满手 → 等待队列
      4. 无关卡/无 hero → no-op（不抛错）

    Test: test_batch_quest_rewards8.py — 真实 `complete_quest` 后:
      真实 `end_recruit_phase` → 手牌恰 1 张 `BGS_029`（零池记账）;
      第二回合再得 1 张（每回合）; 对手无奖励 → 无 Zerus（owner 隔离）;
      满手 → 等待队列（不销毁）

    Params: 无模板参数; payload=BGS_029（数据链 derived_relatedCardDbfIds）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = (ctx or {}).get("hero")
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_eot(g, _h=hero, **kw):
            g.grant_card_copy_to_hand(
                _h, g.db.get(ZERUS_ID), golden=False)

        game.events.register(Listener(event=TURN_END, owner=hero,
                                      callback=on_eot))
        return None


# ══════════════ BGS_029 Shifter Zerus ══════════════


class ShifterZerusScript:
    """
    Natural language: Each turn this is in your hand, transform it into a
    random minion. It keeps enchantments.

    Evidence: wiki `Battlegrounds/Shifter_Zerus` oldid=891260（文本 +
    "Card id: `BGS_029`"）；变形池 = "any Battlegrounds minion, including
    Shifter Zerus. It doesn't pull from the shared pool."
    （`Battlegrounds` oldid=902245）；时机 = "transforms only at the start
    of the possessing player's turn"（构造版同卡 Notes oldid=810477）；
    保留附魔 = Patch 27.6.0.187190 oldid=868288。

    Formal spec:
      1. on_enter_hand(source, game, ctx): 注册 `TURN_START owner=hero`
         监听（该英雄招募期开始）——**手牌**随从的接线钩子。`on_bind`
         是任务/奖励/饰品/英雄技能的协议（引擎不为 minion 分发，
         audit W1 会判死钩子）; `on_summon` 只在**棋盘**召唤时分发，
         而 `grant_card_copy_to_hand` 走 `create_minion` + `add_to_hand`
         （不 summon）。`Hero.add_to_hand` 对入手实体统一分发
         `on_enter_hand`（`hero.py:284`），是本卡唯一正确的接线点。
         owner 用 `hero`（**不是** source）: 该监听器必须跨战斗存活
         （owner=hero 不在战斗快照恢复的丢弃集），而 `on_enter_hand`
         不在 `run_on_bind` 的持久接线作用域内
      2. 回调: 实体仍在 `hero.hand` 才变形（不在手牌 → 落空不变形）;
         实体若已离场/被替换 → 无操作
      3. 变形 = 随机 BG 随从（**含 Zerus 自身**——候选 =
         `db.pool_minions()` + 显式追加 `BGS_029`；等权; 无 tier 限制;
         **不占共享池**）; 金色 → 随机**金色**随从
      4. **保留附魔**（`_buffs` 整体转移; HEALTH 重算为 min(原血, 新上限)）
         与手牌位次; 控制者不变
      5. 无候选（空池）→ 落空（不变形、不抛错）

    Test: test_batch_quest_rewards8.py — 真实 `turn_start`:
      手牌 Zerus 卡面变为候选集内随从（`pool_minions() ∪ {BGS_029}`）;
      **自身变形**经受控 RNG 选中 `BGS_029` 走真实路径（变异: 去掉自身
      候选必须失败）; 变形不消耗共享池（`total_remaining` 前后不变）;
      附魔保留（预置 +5/+5 后变形仍在——变异: 去掉 `_buffs` 转移必须失败）;
      手牌位次/数量不变; 不在手牌（已上场）→ 不变形（负对照）;
      对手回合 → 本人手牌不变形（owner 隔离）

    Params: 无模板参数（金色状态由实体自身 `is_golden` 决定）
    """

    @staticmethod
    def on_enter_hand(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        if getattr(source, "_zerus_wired", False):
            return None
        source._zerus_wired = True

        def on_sot(g, hero=None, turn=None, _h=hero, _src=source, **kw):
            if hero is not _h:
                return          # 只在**持有者**的回合开始变形
            if _src not in _h.hand:
                return          # 不在手牌 → 不变形
            _transform_in_hand(g, _src, _h)

        game.events.register(Listener(event=TURN_START, owner=hero,
                                      callback=on_sot))
        return None


def register() -> list[str]:
    """注册 2 张 CORRECT（奖励 362 + 载荷 BGS_029）。"""
    from hsrl2.scripts.registry import register as reg

    reg(REWARD_ID, EssenceOfZerusScript)
    reg(ZERUS_ID, ShifterZerusScript)
    return [REWARD_ID, ZERUS_ID]
