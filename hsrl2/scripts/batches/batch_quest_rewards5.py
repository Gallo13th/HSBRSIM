"""批次 quest_rewards5 — 任务奖励第五批: 第二英雄技能槽（作业单 2026-09-02）。

引擎原语: RULES §9.5「英雄技能槽（Hero Power Slots）」——任务奖励在
`on_bind(source, game, ctx={"hero": hero})` 中声明
`hero._second_power_id`（`game.complete_quest` → `run_script_hook(reward,
"on_bind", ctx={"hero": hero})`）。发现协议与候选池裁定完全复用异变批
`batch_anomalies4.grant_second_power_discover`（Finley "Adventure!" 同源
`_draftable_hero_power_ids`）——单一实现，避免同效果两批语义漂移。

注册 1 张
═══════════════════════════════════════════════════════════════════════
  - BG33_Reward_017 Cosmic Reward — "Discover a second Hero Power."
    绑定（任务完成）时为本英雄产生 PendingChoice(kind=
    "discover_hero_power"): 候选 = 英雄绑定技能全集排除本英雄主技能;
    3 选 1; 选中写入第二槽 + 显式接线被选技能的 on_bind（Finley 先例:
    引擎 `replace_hero_power`/第二槽协议不自动接线）。
    RULES §9.5: 每英雄只有一个第二槽——若本英雄已有第二技能（另一异变/
    奖励先授予），本次落空（不覆盖，防旧技能监听器变幽灵）。

  说明: 本卡在 `batch_quest_rewards3` 的 DEFERRED 台账中登记为"无第二
  英雄技能槽子系统"——引擎原语（commit 4167dc8, RULES §9.5）落地后
  解冻; 同批 `BG33_Reward_017` 的 DEFERRED 注记以本批为准。

DEFERRED 台账（本批无新增; 相关同族依赖见 batch_anomalies4 docstring）
═══════════════════════════════════════════════════════════════════════
  - BG27_Anomaly_822 Denathrius' Anima Reserves（异变）— 第二槽已就绪，
    但授予技能 'Whodunit?'（`BG24_HERO_100p`）因任务卡难度数值无数据
    权威而 DEFERRED（RULES §11.6）→ 保持 DEFERRED（SOP §12 第 14 条）。
  - 饰品替换/变形族（`BG35_Anomaly_007/008/002`）— 缺饰品购买事件与
    "技能槽 → 饰品实体"替换协议，见 batch_anomalies4 docstring。
"""

from __future__ import annotations

from hsrl2.scripts.batches.batch_anomalies4 import (
    grant_second_power_discover,
)


# ══════════════ BG33_Reward_017 Cosmic Reward ══════════════


class CosmicRewardScript:
    """
    Natural language: <b>Discover</b> a second Hero Power.

    Evidence: data/bg_quest_rewards.json BG33_Reward_017（无模板参数）。
    "Discover" = 真实玩家选择（非随机近似; SOP §8 Kelp Keeper 先例）;
    候选池 = 英雄绑定技能全集（`_draftable_hero_power_ids`，异变
    Cosmic Duality BG31_Anomaly_123 同协议，Finley 同源裁定）。
    "second Hero Power" 指第二技能槽（RULES §9.5）——本奖励与主技能
    替换（Finley/Sulfuras 的 `replace_hero_power`）不同，是**追加**槽位。

    Formal spec:
      1. on_bind(source, game, ctx): hero = ctx["hero"]（缺失退回
         source.controller）
      2. `grant_second_power_discover(hero, game)`: 候选排除本英雄主技能;
         `_second_power_id` 已占用 → 落空; 否则 rng.sample 3 个互异
         技能 id → PendingChoice(kind="discover_hero_power")
      3. resolve: 合法选项 → `hero._second_power_id = power_id` +
         `_wire_power_on_bind` 接线（本奖励绑定发生在 `start_game`
         之后，被动技能必须在选定时补接线）
      4. 本奖励只作用于 ctx 英雄（owner 隔离——不污染对手）

    Test: test_batch_quest_rewards5.py — 真实 `complete_quest` 路径:
      绑定后恰 1 个 discover_hero_power（owner=本英雄）; 选项 ⊆ 候选池、
      不含主技能、恰 3 个互异; 选中后 `hero_power_ids` 含第二技能且
      = 选中 id; 真的可用（选 Hollidae `BG28_HERO_801p` →
      `use_hero_power(power_id=...)` 手牌 +1 池法术）且不消耗主技能
      本回合次数; 选中 passive 技能时其 on_bind 监听器活性（Growing
      Collection → T8 greater offer）; 非法/陈旧 id → 槽不变（正对照:
      合法选择确实写入）; 对手无该奖励 → 无选择且槽为 None; 已有第二槽
      → 落空（正对照: 无槽时确有选择）

    Params: 无模板参数; choices=3（Discover 默认展示数，SOP §14 第 2 条）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = None
        if ctx is not None:
            hero = ctx.get("hero")
        if hero is None:
            hero = getattr(source, "controller", None)
        if hero is None:
            return None
        grant_second_power_discover(hero, game)
        return None


def register() -> list[str]:
    """注册任务奖励批 5（1 张: 第二英雄技能槽）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG33_Reward_017", CosmicRewardScript),
    ]
    registered = []
    for rid, cls in pairs:
        reg(rid, cls)
        registered.append(rid)
    return registered
