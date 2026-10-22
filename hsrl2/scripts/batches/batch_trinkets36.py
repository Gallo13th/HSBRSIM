"""饰品第 36 批 —— Macaw Portrait 解冻（RULES §7.4.17 条件化战吼第二消费者，2026-09-13）

本批 1 张（全部 CORRECT，商店池 Lesser 档 spell_school=11）:

  - `BG32_MagicItem_803` Macaw Portrait — "Get a Monstrous Macaw.
    Your Monstrous Macaws **also trigger your left-most Battlecry**."

实现: 与 `batch_trinkets35`（Selfless Portrait）**同一开关通道**
（§7.4.16 家族行为开关 + §7.4.17 条件化战吼），但消费点在载荷
`MonstrousMacawScript.rally`——Macaw 本体**没有** `battlecry` 钩子，
故本卡**不声明** `battlecry_flag`: `battlecry_flag` 的语义是"该脚本的
`battlecry` 钩子是否条件化"（声明它会令 `granted_battlecry` 恒真，
语义误导; 单独声明虽不改 `has_battlecry`——无钩子——但属错误接线）。
载荷直接读 `FLAG_MACAW_EXTRA_BATTLECRY`。

读法裁定（原 DEFERRED 阻塞 = "最左战吼"资格集口径）:
  资格集 = 存活友方中**具有战吼者**（`game.has_battlecry`），左→右首个。
  权威: 32.2 官方论坛复现串 "[32.2] Macaw Portrait + Glowgullet Warlord"
  （2025-05-15）棋盘 `M G x B y z`——Macaw 攻击**同时**触发最左亡语 G 与
  最左**战吼** B，**跳过中间的非战吼 x** ⇒ "your left-most Battlecry"
  = 最左**带战吼的**随从，与本体卡面 "your left-most Deathrattle" 同构
  （载荷 `rally` 的亡语项同样按"挂有亡语者"资格集选）。
  次数: 每次 Rally 触发 **1 次**（饰品文本无 "twice"; 金色
  `TB_BaconUps_135` 的 "twice" 只修饰亡语 → `passes=2` 只管亡语）。

前序台账（`batch_trinkets15` / `24` / `28` / `29` / `30` / `31`）:
  该卡曾 DEFERRED，两条阻塞**均已消除**:
    (a) 载荷 `BGS_078` Monstrous Macaw 已注册（`batch_payload_minions`，
        亡语/Rally 路径完整）;
    (b) "also trigger your left-most Battlecry"缺引擎读取点与资格集口径
        → 本批落地（§7.4.17 门禁 + 论坛复现权威）。
  文本无模板参数（Params: 无 `{0}/{1}`）。

协议: 饰品实体经 `_offer_trinkets` 购买 / `grant_trinket` 授予 →
`hero.trinkets`；脚本只挂 `on_bind`（接线审计 W1 白名单）。
`source` 传入饰品实体: 开关生效期校验其仍在 `hero.trinkets`
（被替换/移除 → 追加项同步消失，同 §6.19 / §7.4.15 / §7.4.16 口径）。

AMBIGUOUS 留档（记录，不据此改动）:
  1. 金色 Macaw 的追加战吼是否也应"twice"（即 2 次）——官方文本未述;
     本实现按"饰品文本无 twice + 金色文本的 twice 只修饰亡语"取 1 次，
     并在 `test_batch_trinkets36.py` 锁定行为。
  2. 本体是否排除——饰品文本无 "except this minion's"; Macaw 本体无战吼，
     实际无影响（若将来有"给 Macaw 加战吼"的卡，需重新裁定）。
"""

from __future__ import annotations

from hsrl2.scripts.batches.batch_payload_minions import (
    FLAG_MACAW_EXTRA_BATTLECRY,
)
from hsrl2.scripts.batches.batch_trinkets33 import _grant_related

MACAW_PORTRAIT = "BG32_MagicItem_803"


class MacawPortraitScript:
    """
    Natural language: [x]Get a Monstrous Macaw. Your Monstrous Macaws also
    trigger your left-most <b>Battlecry</b>.

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）:
         `game.trinket_related_card(本饰品 id)` 经 `evolution_card_id`
         数据链解析关联卡（BGS_078 Monstrous Macaw）; 解析失败 →
         `GameStateError`（fail-loud，SOP §6b）
      2. `game.grant_trinket_related_card(hero, 本饰品 id)` 授予 1 份
         进手牌
      3. `game.add_family_flag(hero, 关联卡 id,
         FLAG_MACAW_EXTRA_BATTLECRY, source=source)` —— 该英雄的
         Monstrous Macaw（含金色，基础卡 id 归一）Rally 时**追加**
         "trigger your left-most Battlecry" 一次
      4. **不改效果本体**: Rally 的亡语项与追加项全在载荷
         `MonstrousMacawScript.rally`（本脚本不复刻，SOP §12）;
         本卡**不声明** `battlecry_flag`（语义是"本脚本 battlecry 钩子
         条件化"; Macaw 本体并无战吼钩子）
      5. owner 隔离: 开关只写本英雄; 对手 Macaw 不追加触发
      6. 生效期: 饰品被替换/移除 → 追加项同步失效
         （`source` 不在 `hero.trinkets` 即失效）
      7. 数值零硬编码（本饰品 CardDef 无模板参数）

    Test: test_batch_trinkets36.py — 真实 `grant_trinket` 后手牌出现
    BGS_078 且开关生效; 真实攻击路径（`CombatScheduler._execute_attack`）
    下同一 Rally 触发最左亡语 + 最左**战吼**（跳过更靠左的非战吼随从）;
    无饰品负对照不追加; 金色亡语 2 次 / 战吼 1 次; 统一入口计数与广播;
    与 Selfless Portrait 组合时最左战吼可为"获得战吼的无私英雄";
    饰品移除后失效; 对手不受影响

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        rel = _grant_related(game, hero, MACAW_PORTRAIT)
        game.add_family_flag(hero, rel.id, FLAG_MACAW_EXTRA_BATTLECRY,
                             source=source)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 36 批 1 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (MACAW_PORTRAIT, MacawPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
