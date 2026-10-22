"""批次 quest_rewards7 — The Golden Hammer（临时金色兑现，作业单 2026-09-15）。

台账来源: `batch_hero_rewards_final.py` 文末 DEFERRED 台账第 4 条
（`BG24_Reward_719` The Golden Hammer — "Make a friendly minion Golden
until next turn"）。此前因**临时金色原语缺失**DEFERRED，本轮引擎补齐
（`Game.make_golden_until_next_turn`，RULES §7.4.14）后注册。

**引擎原语逐条核对（2026-09-15）**
═══════════════════════════════════════════════════════════════════════
  | 原语（生产点） | 本批消费卡 | 语义 |
  |----------------|-----------|------|
  | `Game.make_golden_until_next_turn(minion)`（`game.py`）——目标换为
    金色独立卡定义（保留附魔）+ 打 `GILDED_NOT_TRIPLED`（非三连金，
    出售回池 1 份）+ 登记控制者下一个 `turn_start` 回滚为非金
    （单 tick，SOP §16 模式 16） | 719t | 已是金色 → no-op; 目标离场/
    无金色定义 → 落空 |
  | `Transform(..., force_golden=)`（`actions/stats.py`）——覆写金色
    状态（缺省继承目标）; 临时金色需要"非金 → 金"与"金 → 非金"两个
    方向 | 719t | 两个方向都保留附魔/位置 |
  | `spellcraft.grant_spellcraft_spell(source, game)`——on_bind 立即
    授予第一张法术; 之后由 `generate_for_hero` 每回合生成（引擎扫描
    `hero.quest_rewards`——奖励的 SPELLCRAFT tag 由 `create_entity`
    从 `CardDef.spellcraft_id` 数据驱动） | 719 | 与饰品 Spellcraft
    （batch_unlock_final / batch_trinkets18/20）同协议 |

**CORRECT 2 项（注册 2 个 id）**
═══════════════════════════════════════════════════════════════════════
  BG24_Reward_719 The Golden Hammer（任务奖励，`spellcraft_id=97754`）—
      on_bind → `grant_spellcraft_spell(source, game)`（立即授予 token
      法术 `BG24_Reward_719t`）; 每回合开始引擎再生成一张。
      "Spellcraft:" 的定向法术本体是 token 卡（非池 token，不占池）。

  BG24_Reward_719t The Golden Hammer（token 法术，`CardType.SPELL`）—
      `needs_target = True`（"Make a friendly minion Golden" 是
      [Targeted]——同族 wiki tags "Targeted"）; on_play:
      `game.make_golden_until_next_turn(ctx["target"])`。无候选时引擎
      落空但法术照常消耗（play_spell 既有契约）。

**DEFERRED 台账（本批无新增）**
═══════════════════════════════════════════════════════════════════════
  剩余任务奖励 4 张以 `batch_hero_rewards_final.py` 文末台账为准:
  135 Wheel of Yogg-Saron / 313 Wondrous Wisdomball / 362 Essence of
  Zerus（授予物 BGS_029 Shifter Zerus 缺手牌变形脚本）/ 555t No Place
  Like Holmes（回报数值无权威）。

测试: `hsrl2/tests/test_batch_quest_rewards7.py`（行为层: 真实
`complete_quest` → 手牌出现 token 法术 → 真实 `play_spell` 定向施放 →
金色化; 下回合开始回滚; 对手隔离; 满板/离场落空 + 正对照）
"""

from __future__ import annotations

from hsrl2.spellcraft import grant_spellcraft_spell

TOKEN_ID = "BG24_Reward_719t"


# ══════════════ BG24_Reward_719 The Golden Hammer ══════════════


class TheGoldenHammerScript:
    """
    Natural language: <b>Spellcraft:</b> Make a friendly minion Golden
    until next turn.

    Evidence: data/bg_quest_rewards.json BG24_Reward_719（`spellcraft_id`
    = 97754 → token `BG24_Reward_719t`）; XML 无模板参数。
    "Spellcraft" 协议见 RULES §6.13: 获得时立即给第一张法术，之后每个
    招募阶段开始再生成一张。

    Formal spec:
      1. on_bind(source, game, ctx): 奖励实体已由 `complete_quest` 放入
         `hero.quest_rewards`（`create_entity` 依 `spellcraft_id` 打
         SPELLCRAFT tag）
      2. 立即 `grant_spellcraft_spell(source, game)` → token 法术
         `BG24_Reward_719t` 进手牌（满手 → pending_hand_queue）
      3. 后续由 `spellcraft.generate_for_hero` 每回合生成

    Test: test_batch_quest_rewards7.py — 真实 `complete_quest` 后:
      手牌恰 1 张 token（SPELLCRAFT tag + 来源 uuid = 奖励实体）;
      下一回合开始再生成一张（正对照: 无奖励时手牌无 token）;
      对手无该奖励 → 无 token（owner 隔离）

    Params: 无模板参数; token=BG24_Reward_719t（数据链 spellcraft_id）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)
        return None


# ══════════════ BG24_Reward_719t The Golden Hammer（法术） ══════════════


class TheGoldenHammerTokenScript:
    """
    Natural language: Make a friendly minion Golden until next turn.

    Evidence: data/bg_cards.json BG24_Reward_719t（type=SPELL, 非池）;
    "Make a friendly minion Golden" 是定向效果（同族 Golden Touch /
    官方 wiki "Targeted"）——引擎 PendingChoice(kind="spell_target")。

    Formal spec:
      1. `needs_target = True` → 引擎产生 spell_target 选择
         （候选 = 本人存活棋盘随从; 无候选 → 落空但法术消耗）
      2. on_play(spell, game, {"target": t}): `game.make_golden_until_
         next_turn(t)`——t 换为金色独立卡定义（保留附魔; 打
         GILDED_NOT_TRIPLED），并在控制者下一个招募阶段开始回滚为非金
      3. 目标已离场/死亡 → 落空（不抛错）

    Test: test_batch_quest_rewards7.py — 真实 play_spell: 目标变金色
      （card_id=金色定义、属性=金色 CardDef、GILDED_NOT_TRIPLED）;
      附魔保留; 下回合开始回滚为原卡定义（附魔保留）; 空板时落空但
      法术离手（负对照 + 正对照）; 已是金色 → 不回退为二段（no-op）

    Params: 无模板参数
    """

    needs_target = True

    @staticmethod
    def on_play(spell, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        game.make_golden_until_next_turn(target)
        return None


def register() -> list[str]:
    """注册 The Golden Hammer 批（奖励 + token 法术）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG24_Reward_719", TheGoldenHammerScript),
        (TOKEN_ID, TheGoldenHammerTokenScript),
    ]
    registered = []
    for rid, cls in pairs:
        reg(rid, cls)
        registered.append(rid)
    return registered
