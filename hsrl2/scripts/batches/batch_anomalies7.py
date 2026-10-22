"""异变第 7 批 —— Emergency Landing + 载荷技能 Eject!（2026-09-13）

本批 2 张（全部 CORRECT）:

  - `BG31_Anomaly_117` Emergency Landing — "Twice per turn, you can remove
    all copies of a minion in the Tavern from your pool."
  - `BG31_Anomaly_117t` Eject! — "Choose a minion. Permanently remove all
    copies of it from your pool. <i>(Twice per turn.)</i>"

引擎原语（本批主线新增）: `MinionPool.purge(card_id)` / `is_purged`
——**永久**移除池内全部剩余副本。旧台账（`batch_anomalies_final`）记的
唯一阻塞即"`MinionPool` 无公开移除 API，且 `release`/`ensure_available`
会把已移除的卡重新放回（'permanently' 无法表达）"；purge 后
`available` 恒 0、`candidates` 不列出、`acquire`/`release`/
`ensure_available` 全部拒绝，本局不可逆。

裁定留档（卡面字面量）: "remove all copies of it **from your pool**"
只清**池**——被点名的酒馆展示副本不消失（它已被抽出，不在池内）；其
后续出售/淘汰的 `release` 亦被 purge 拒绝，故不回归池。目标域由异变
文本 "a minion **in the Tavern**" 钉死 = 本英雄酒馆展示位。

协议: 异变 `on_bind(game)` 经**公开 API** `game.set_second_hero_power`
（RULES §9.5: 槽位占用 / 技能不在库 → fail-loud）授予第二技能槽;
技能 `on_bind(hero, game)` / `hero_power` 走技能槽协议。

其余 37 张未注册异变仍在 `batch_anomalies3` / `batch_anomalies_final` 等
批次逐张 DEFERRED 台账（子系统: RACES / Wheel / Darkmoon / Craft /
Timewarp / Buddy / Secrets / 任务进度权威）。
"""

from __future__ import annotations

from hsrl2.game import GameStateError
from hsrl2.minion import Minion

EMERGENCY_LANDING = "BG31_Anomaly_117"     # 异变本体
EJECT = "BG31_Anomaly_117t"                # 载荷英雄技能


def _pool_base_id(game, card_id: str) -> str:
    """金色展示位 → 基础卡 id（池内只有基础 CardDef）。

    池按基础定义记账; 酒馆金色展示（三连金/金色酒馆）的 `card_id` 是
    金色独立定义 → 经 `triple_base_id` 归一，否则 purge 打不中池条目。
    """
    d = game.db.get(card_id)
    if d is not None and getattr(d, "is_golden_def", False) \
            and d.triple_base_id:
        base = game.db.by_dbf(d.triple_base_id)
        if base is not None:
            return base.id
    return card_id


class EjectPower:
    """
    Natural language: [x]Choose a minion. Permanently remove all copies of
    it from your pool. <i>(Twice per turn.)</i>

    Evidence: `data/bg_hero_powers.json BG31_Anomaly_117t`（cost=0、无
    模板参数）; 关联异变 `BG31_Anomaly_117` 文本明确目标域 = "a minion
    **in the Tavern**"; wiki 无 Notes → 按卡面字面量（只清池）。

    Formal spec:
      1. 第二技能槽主动面: `uses_per_turn = 2`（"Twice per turn"）、
         `needs_target = True`、cost = CardDef.cost = 0（数据核实）
      2. `target_candidates(hero, game)` = 本英雄酒馆展示位的存活随从;
         被买走/刷新后目标失效（`_hero_power_target_ok` 复查候选域 →
         本次使用作废、不扣费不计数）
      3. `hero_power(hero, game, ctx)`:
         `game.minion_pool.purge(_pool_base_id(game, target.card_id))`
         ——永久移除该卡池内全部剩余副本; 目标实体**留在酒馆**（"from
         your pool" 不含已抽出副本）
      4. 未知 id / 非随从卡不在池记账域 → `purge` 返回 0 且不标记;
         剩余副本本已为 0 的已知随从（含池外 token）照常标记（六路结果
         不变——本就不在池）; 重复 purge 幂等（返回 0，不报错）

    Test: test_batch_anomalies7.py — 真实开局后第二槽 = Eject! /
    技能可用且 target_candidates = 酒馆位 / 使用后该卡池剩余 = 0 且
    后续刷新不再出现 / 点名另一张不影响 / 每回合第 3 次拒绝 /
    非酒馆目标不可用 / 被点名实体仍在酒馆

    Params: 无模板参数（次数 2 = "Twice per turn" 文本字面量; cost=0）
    """

    uses_per_turn = 2
    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        # 只取**随从**展示位（酒馆同时含酒馆法术 `BACON_SPELL` 实体;
        # "Choose a minion" 不含法术）
        return [m for m in hero.tavern
                if not m.dead and isinstance(m, Minion)]

    @staticmethod
    def hero_power(hero, game, ctx):
        target = ctx.get("target") if ctx else None
        if not isinstance(target, Minion) or target not in hero.tavern:
            raise GameStateError("Eject!: bad target")
        game.minion_pool.purge(_pool_base_id(game, target.card_id))
        return None


class EmergencyLandingAnomaly:
    """
    Natural language: Twice per turn, you can remove all copies of a minion
    in the Tavern from your pool.

    Evidence: `data/bg_anomalies.json BG31_Anomaly_117`（无模板参数）;
    载荷技能 `BG31_Anomaly_117t` Eject!（数据无 `evolution_card_id`
    链 → id 字面量 + 存在性/注册双重守卫）。

    Formal spec:
      1. `on_bind(game)`: 载荷技能在 CardDB 且已注册 → 每英雄
         `game.set_second_hero_power(hero, BG31_Anomaly_117t)`（RULES
         §9.5 公开入口: 槽位已占用 / 技能不在库 → fail-loud，并即时
         接线其 on_bind——本脚本不自行写私有属性）
      2. 载荷缺失/未注册 → 不授予（不注册空转技能，SOP §6b）
      3. 异变对所有英雄生效（全局异变语义）

    Test: test_batch_anomalies7.py — 开局后每英雄 `hero_power_ids` 含
    Eject!（第二槽）/ 无该异变时不含（对照局）/ 异变未注册前不授予
    （注册表守卫）

    Params: 无模板参数（技能 id 由常量 + 数据存在性守卫）
    """

    @staticmethod
    def on_bind(game):
        from hsrl2.scripts import REGISTRY
        if game.db.get(EJECT) is None or REGISTRY.get(EJECT) is None:
            return None
        for h in game.heroes:
            game.set_second_hero_power(h, EJECT)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册异变第 7 批: 1 异变 + 1 第二技能槽技能（全部 CORRECT）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (EMERGENCY_LANDING, EmergencyLandingAnomaly),
        (EJECT, EjectPower),
    ]
    registered = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
