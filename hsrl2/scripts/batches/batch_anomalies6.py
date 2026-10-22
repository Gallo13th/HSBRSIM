"""异变批 6 — Crystal Ball 族（"第二技能槽变成所购饰品的副本"）。

作业单: 36.2.2 异变 `BG35_Anomaly_007` / `BG35_Anomaly_008` 及其第二
技能槽技能 `BG35_Anomaly_007t` / `BG35_Anomaly_008t`。

  OK 4（注册键 = 卡 id）:
    BG35_Anomaly_007   Lesser Fortune       → 开局授予第二技能 Lesser Crystal Ball
    BG35_Anomaly_008   Greater Fortune      → 开局授予第二技能 Greater Crystal Ball
    BG35_Anomaly_007t  Lesser Crystal Ball  → 买 Lesser 饰品时"变成它的副本"
    BG35_Anomaly_008t  Greater Crystal Ball → 买 Greater 饰品时"变成它的副本"

DEFERRED: 无（本批 4 张全部 CORRECT）。

数据侦察（`hsdata/CardDefs.xml` / `data/*.json` 权威）:
  - 异变本体文本: "Start with '<技能名>' as your second Hero Power."
    （`data/bg_anomalies.json`）——授予对象经**数据链**解析:
    `CardDef.evolution_card_id`（131645 / 131647）→ `db.by_dbf` 得
    card_type=10 (HERO_POWER) 的技能（SOP §11 教训 5: 禁止硬编码 id）。
  - 技能文本: "[x]When you buy a Lesser/Greater <b>Trinket</b>, this
    transforms into a copy of it."（`data/bg_hero_powers.json`）
  - 档位口径 = 商店档位: `script_data_num_1` = 6（Lesser, T6）/
    9（Greater, T9）——与 RULES §7.4 "T6 售 Lesser、T9 售 Greater"
    精确一致，故 `CardDef.num(0)` 即"触发档位"的权威表达。
    **注意**: 这两张技能的 `spell_school` 均为 11，那是"饰品"卡牌类别
    标记（card_type=10 的技能上无 Lesser/Greater 语义），不能用作档位
    判据——档位一律读 `num(0)`。

引擎依赖（2026-09-02 主线补齐，RULES §7.4.3 副本条款 / §9.5）:
  - `game.grant_trinket(..., duplicate=True)` / `game.copy_trinket(...)`
    ——同 id 可持有**两份副本**（"hold body + copy"）
  - `game.set_second_slot_trinket(hero, trinket_id)` ——第二技能槽改为
    "该饰品的副本"表示: 槽位标记 = 饰品 id（槽位仍占用→不能再获得第二
    技能），副本实体入 `hero.trinkets`（Avenge/EoT/开局战斗 等扫描域），
    `hero_power_ids` 只列真正的 HERO_POWER 卡（饰品不会被
    `use_hero_power` 当技能误用扣费）
"""

from __future__ import annotations

from hsrl2.events import TRINKET_BOUGHT, Listener
from hsrl2.game import GameStateError
from hsrl2.tags import CardType

# 商店档位 → 购买事件 kind 字符串（`_offer_trinkets(hero, kind)` 口径）
_LESSER_TIER = 6
_GREATER_TIER = 9


def _evolution_power(game):
    """经数据链解析本局异变授予的第二技能（`evolution_card_id` → by_dbf）。

    读取 `game.anomaly` 的 CardDef（不硬编码 id——SOP §11 教训 5）。
    解析失败 / 非 HERO_POWER / 脚本未注册（授予即空转）→ None
    （调用方整卡落空，不授予空转技能——SOP §12 缺陷模式）。
    """
    d = game.db.get(game.anomaly) if game.anomaly else None
    if d is None or d.evolution_card_id is None:
        return None
    power = game.db.by_dbf(d.evolution_card_id)
    if power is None or power.card_type != CardType.HERO_POWER:
        return None
    from hsrl2.scripts import REGISTRY
    if power.id not in REGISTRY:
        return None
    return power


def _grant_second_power(game, power) -> None:
    """对每个英雄授予第二技能（第二槽已占用 → 该英雄跳过，RULES §9.5）。"""
    for h in game.heroes:
        if getattr(h, "_second_power_id", None) is not None:
            continue
        game.set_second_hero_power(h, power.id)


# ══════════════ BG35_Anomaly_007 Lesser Fortune ══════════════


class LesserFortuneAnomaly:
    """
    Natural language: Start with 'Lesser Crystal Ball' as your second
    Hero Power.

    Evidence: `data/bg_anomalies.json BG35_Anomaly_007`（card_type=43,
    `evolution_card_id=131645` → `BG35_Anomaly_007t` "Lesser Crystal
    Ball", card_type=10, cost=0, num(0)=6 = T6/Lesser 档）。

    Formal spec:
      1. on_bind(game): 经数据链解析授予技能; 任一步失败 → 整卡落空
         （不授予空转技能）
      2. 对每个英雄 `game.set_second_hero_power(hero, power.id)`
         （第二槽已占用 → 跳过该英雄）
      3. 授予后 `game.hero_power_ids(hero)` 含它; 其被动效果由技能脚本
         （`BG35_Anomaly_007t`）在购买 Lesser 饰品时触发

    Test: test_batch_anomalies6.py — 真实 `Game(anomaly=...)` +
      `start_game()` 后两英雄第二槽 == 数据链解析值、`hero_power_ids`
      含它; 对照局（无异常）第二槽为 None

    Params: 无模板参数（技能 id 由 `evolution_card_id` 数据链解析）
    """

    @staticmethod
    def on_bind(game):
        power = _evolution_power(game)
        if power is None:
            return None
        _grant_second_power(game, power)
        return None


# ══════════════ BG35_Anomaly_008 Greater Fortune ══════════════


class GreaterFortuneAnomaly:
    """
    Natural language: Start with 'Greater Crystal Ball' as your second
    Hero Power.

    Evidence: `data/bg_anomalies.json BG35_Anomaly_008`（`evolution_card_id`
    =131647 → `BG35_Anomaly_008t` "Greater Crystal Ball", num(0)=9 =
    T9/Greater 档）。其余同 `LesserFortuneAnomaly`。

    Formal spec: 同 `LesserFortuneAnomaly`（授予 131647 对应的技能）。

    Test: test_batch_anomalies6.py — 与 007 同构、且通过 `num(0)=9`
      验证 Greater 档触发 Greater 饰品购买。

    Params: 无模板参数。
    """

    @staticmethod
    def on_bind(game):
        power = _evolution_power(game)
        if power is None:
            return None
        _grant_second_power(game, power)
        return None


# ══════════════ BG35_Anomaly_007t / _008t Crystal Ball（第二技能槽） ══════════════


class _CrystalBallPower:
    """Crystal Ball 族共同实现（档位由 `num(0)` 权威给出）。

    Natural language: [x]When you buy a Lesser/Greater <b>Trinket</b>,
    this transforms into a copy of it.

    Evidence: `data/bg_hero_powers.json`（card_type=10, cost=0;
    `script_data_num_1` = 6/9 = 商店 T6/T9 档; 文本无 {0}/{1} 占位符）。
    官方语义 = "技能槽变成所买饰品的一份副本"（RULES §7.4.3 副本条款:
    本体 + 副本共两份同时生效）; wiki 同类卡（Souvenir Stand）bug 报告
    佐证"copy 是一份真实生效的额外饰品"。

    Formal spec:
      1. `passive = True`（无主动使用）; `on_bind(hero, game)` 注册
         `TRINKET_BOUGHT` 监听器（owner=hero）
      2. condition: 事件 kind 与 `num(0)` 推出的档位一致（6→"lesser",
         9→"greater"）且 **本英雄**的第二槽仍持有本技能
         （`hero._second_power_id == power_id` —— 变形后自我失效，
         无需注销监听器即可停止 cadence）
      3. callback: `game.set_second_slot_trinket(hero, bought.card_id,
         source=...)` —— 槽位标记改写为饰品 id（槽位仍占用），副本实体
         入 `hero.trinkets`（跨局去重豁免 + on_bind 接线）
      4. 变形后 `hero_power_ids(hero)` 不再含本技能（饰品不是技能），
         `use_hero_power(power_id=饰品 id)` 返回 False（不误扣金币）
      5. 每英雄独立（监听器 owner=hero + condition 判定本人）

    Test: test_batch_anomalies6.py — 买对应档位饰品后: 两份副本同时在
      `hero.trinkets`、槽位标记 == 饰品 id、`hero_power_ids` 不再含本
      技能、`use_hero_power` 对该 id 返回 False 且金币不变; 买了**另一
      档位**的饰品不触发（正/负对照）; 对手不受影响; 变形后再买一张
      不会二次变形（槽位已非本技能）

    Params: `num(0)` = 触发档位（6=Lesser / 9=Greater）——数据权威。
    """

    passive = True

    @staticmethod
    def _num0(game, power_id: str):
        d = game.db.get(power_id)
        if d is None:
            raise GameStateError(f"unknown hero power {power_id!r}")
        tier = d.num(0)
        if tier == _LESSER_TIER:
            return "lesser", tier
        if tier == _GREATER_TIER:
            return "greater", tier
        raise GameStateError(
            f"{power_id}: unexpected trigger tier num(0)={tier!r} "
            f"(expected {_LESSER_TIER} or {_GREATER_TIER})")

    @staticmethod
    def _wire(hero, game, power_id: str) -> None:
        kind_str, _tier = _CrystalBallPower._num0(game, power_id)
        owner = hero

        def on_trinket_bought(g, hero=None, trinket=None, kind=None, **kw):
            # 只对本人触发（事件带 hero= 购买者）
            if hero is not owner or trinket is None:
                return
            if getattr(owner, "_second_power_id", None) != power_id:
                return          # 已变形 / 槽位被替换 → 不再触发
            g.set_second_slot_trinket(owner, trinket.card_id,
                                      source=power_id)
            # 第二技能槽变成饰品后，被动来源已消失（RULES §9.5）

        def cond(hero=None, kind=None, **kw):
            return hero is owner and kind == kind_str

        game.events.register(Listener(
            event=TRINKET_BOUGHT, owner=owner, callback=on_trinket_bought,
            condition=cond))


class LesserCrystalBallPower(_CrystalBallPower):
    """
    Natural language: [x]When you buy a Lesser <b>Trinket</b>, this
    transforms into a copy of it.

    Evidence: `data/bg_hero_powers.json BG35_Anomaly_007t`（cost=0,
    num(0)=6 = 商店 T6 = Lesser 档）。

    Formal spec: 见 `_CrystalBallPower`（档位 "lesser"）。

    Test: test_batch_anomalies6.py — 买 Lesser → 变形; 买 Greater → 不
      变形（负对照）。

    Params: num(0)=6（触发档位）。
    """

    @staticmethod
    def on_bind(hero, game):
        _CrystalBallPower._wire(hero, game, "BG35_Anomaly_007t")


class GreaterCrystalBallPower(_CrystalBallPower):
    """
    Natural language: [x]When you buy a Greater <b>Trinket</b>, this
    transforms into a copy of it.

    Evidence: `data/bg_hero_powers.json BG35_Anomaly_008t`（cost=0,
    num(0)=9 = 商店 T9 = Greater 档）。

    Formal spec: 见 `_CrystalBallPower`（档位 "greater"）。

    Test: test_batch_anomalies6.py — 买 Greater → 变形; 买 Lesser → 不
      变形（负对照）。

    Params: num(0)=9（触发档位）。
    """

    @staticmethod
    def on_bind(hero, game):
        _CrystalBallPower._wire(hero, game, "BG35_Anomaly_008t")


def register() -> list[str]:
    """注册异变 2 张 + 第二技能槽技能 2 张。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_Anomaly_007", LesserFortuneAnomaly),
        ("BG35_Anomaly_008", GreaterFortuneAnomaly),
        ("BG35_Anomaly_007t", LesserCrystalBallPower),
        ("BG35_Anomaly_008t", GreaterCrystalBallPower),
    ]
    registered = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
