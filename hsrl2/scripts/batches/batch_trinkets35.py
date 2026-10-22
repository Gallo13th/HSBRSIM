"""饰品第 35 批 —— 条件化战吼协议 + Selfless Portrait（RULES §7.4.17，2026-09-13）

本批 1 张（全部 CORRECT，商店池 Lesser 档 spell_school=11）:

  - `BG32_MagicItem_804` Selfless Portrait — "Get a Selfless Hero.
    Your Selfless Heroes **also trigger on Battlecry**."

引擎读取点（本批主线新增，RULES §7.4.17）:
  **条件化战吼**——载荷脚本以类属性 `battlecry_flag` 声明开关名
  （= §7.4.16 家族行为开关通道的 flag），引擎统一门禁
  `Game.has_battlecry(m)` / `Game.granted_battlecry(m)` 在**开关生效时**
  才把该随从算作"有战吼"。

  为什么需要专门协议（2026-09-13 实测，SOP §12 反"静默半实现"）:
  直增 `battlecry` 钩子会让**无饰品时**的 Selfless Hero 被静态门禁判为
  战吼随从 → 误消费 War Drum `BG32_MagicItem_416` 的 `bc_first` 配额
  （探针: `extra_trigger_used['bc_first']` 0 → 1）、误计入
  `BG30_MagicItem_982`（"买 2 个战吼随从"）、误入 Young Murk-Eye
  `BG35_MagicItem_752` 的最左/最右战吼目标集。故门禁必须"按开关判定"，
  而非"按钩子是否存在判定"。

权威（读法裁定依据）: 32.4 补丁说明（2025-06-02，
playhearthstone.com blog 24205006）
  "**Snicker Snacks: Fixed a bug where it couldn't trigger Selfless
  Hero's effect when it has a Battlecry from Selfless Portrait.**"
—— 官方明确: 持本饰品时 Selfless Hero **"has a Battlecry"**，且该战吼
可被"trigger a Battlecry"类效果（`BG24_Reward_107` Snicker Snacks，
本引擎已注册）正常触发。裁定为**读法 1**（打出本体时其亡语作为战吼结算;
等价表述"该家族获得战吼"，非"每次触发战吼时触发己方无私英雄"）:
  1. 官方措辞是"**it has a Battlecry**"（随从自身获得战吼），而不是
     "after you trigger a Battlecry, trigger ...";
  2. 与同批 `BG32_MagicItem_803` Macaw Portrait 同构（Portrait 给家族
     追加一次触发: Macaw 的 Rally 追加"最左战吼"; Selfless Hero 追加
     "打出时的战吼"）;
  3. 读法 2（每次战吼触发家族）会在 Brann/Macaw 链下产生"每触发一次战吼
     就给全家族圣盾"的爆炸性效果，与"Portrait 强化本家族"的定位不符。

关联卡授予: `_grant_related`（`evolution_card_id=96769` → `BG_OG_221`
数据链——零硬编码卡 id），金色 `TB_BaconUps_014` 经基础卡 id 归一同吃开关
（"Give 2 random friendly minions" 由载荷 `_targets=2` 自然体现）。

前序台账（`batch_trinkets24` / `28` / `29` / `30`，2026-09-13 复核）:
  该卡曾 DEFERRED，两条阻塞**均已消除**:
    (a) 载荷 `BG_OG_221` "未注册" → **陈旧**（`batch_payload_minions`
        早已注册亡语路径）;
    (b) "also trigger on Battlecry"缺引擎读取点 → 本批 §7.4.17 落地 +
        读法由 32.4 补丁说明裁定。
  文本无模板参数（Params: 无 `{0}/{1}`）。

协议: 饰品实体经 `_offer_trinkets` 购买 / `grant_trinket` 授予 →
`hero.trinkets`；脚本只挂 `on_bind`（接线审计 W1 白名单）。
`source` 传入饰品实体: 开关生效期校验其仍在 `hero.trinkets`
（被替换/移除 → 战吼同步消失，同 §6.19 / §7.4.15 / §7.4.16 口径）。

AMBIGUOUS 留档（记录，不据此改动）: 官方未说明该战吼是否计入
"for each Battlecry you've triggered" 类计数——本实现按"has a
Battlecry"字面计入（`COUNTER_BATTLECRIES` +1 且广播 `battlecry_trigger`，
与关键词战吼同口径），并已在该卡测试中锁定行为。
"""

from __future__ import annotations

from hsrl2.scripts.batches.batch_payload_minions import (
    FLAG_SELFLESS_BATTLECRY,
)
from hsrl2.scripts.batches.batch_trinkets33 import _grant_related

SELFLESS_PORTRAIT = "BG32_MagicItem_804"


class SelflessPortraitScript:
    """
    Natural language: [x]Get a Selfless Hero. Your Selfless Heroes also
    trigger on <b>Battlecry</b>.

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）:
         `game.trinket_related_card(本饰品 id)` 经 `evolution_card_id`
         数据链解析关联卡（BG_OG_221 Selfless Hero）; 解析失败 →
         `GameStateError`（fail-loud，SOP §6b）
      2. `game.grant_trinket_related_card(hero, 本饰品 id)` 授予 1 份
         进手牌
      3. `game.add_family_flag(hero, 关联卡 id, FLAG_SELFLESS_BATTLECRY,
         source=source)` —— 该英雄的 Selfless Hero（含金色，基础卡 id
         归一）**获得战吼**: 打出时（及被"触发战吼"效果触发时）结算其
         亡语效果（随机 k 只友方获得圣盾，k = 1 / 金色 2）
      4. **不改效果本体**: 圣盾结算仍全在载荷
         `SelflessHeroScript._give_divine_shield`（本脚本不复刻，SOP §12）
      5. owner 隔离: 开关只写本英雄; 对手 Selfless Hero 无战吼
      6. 生效期: 饰品被替换/移除 → `has_battlecry` 与效果同步失效
         （`source` 不在 `hero.trinkets` 即失效）
      7. 数值零硬编码（本饰品 CardDef 无模板参数; `_targets` 在载荷）

    Test: test_batch_trinkets35.py — 真实 `grant_trinket` 后手牌出现
    BG_OG_221 且 `has_battlecry` 为真; 真实 `play_minion` 结算战吼 →
    唯一友方（本体）获圣盾（无饰品对照组 0）; 金色 2 只各获圣盾;
    Snicker Snacks（BG24_Reward_107）EoT 触发该战吼; War Drum 配额只在
    持饰品时被消费; 饰品移除后失效; 对手不受影响

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        rel = _grant_related(game, hero, SELFLESS_PORTRAIT)
        game.add_family_flag(hero, rel.id, FLAG_SELFLESS_BATTLECRY,
                             source=source)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 35 批 1 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (SELFLESS_PORTRAIT, SelflessPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
