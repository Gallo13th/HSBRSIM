"""批次 anomalies5 — 异变第五批: 饰品授予/替换族（作业单 2026-09-11）。

引擎原语（RULES §7.4.3 饰品获取协议 + §9.5 英雄技能槽）:
  - `game.grant_trinket` / `grant_random_trinket` / `replace_trinket` +
    `trinket_bought` / `trinket_granted` 事件
  - `hero._second_power_id` + `Game.hero_power_ids` /
    `hero_power_def_for` / `set_second_hero_power` /
    `wire_hero_power_on_bind`（异变 `on_bind(game)` 声明第二槽，
    `start_game` 随后接线其 `on_bind`）

注册 1 张异变 + 1 张第二技能槽技能
═══════════════════════════════════════════════════════════════════════
  - BG35_Anomaly_002 Anomalous Cube — "Start with 'Mystery Cube' as your
    second Hero Power. It unlocks on Turn 5. <i>({0} turns left!)</i>"
      1. on_bind(game): 经**数据链**解析授予技能（`game.anomaly` 的
         CardDef.evolution_card_id → `db.by_dbf` ——零硬编码卡 id，
         SOP §11 教训 5）; 解析失败 / 非 HERO_POWER / 脚本未注册
         （载荷未就绪，SOP §12 item 14）→ 整卡落空
      2. 每英雄 `game.set_second_hero_power(hero, power_id)`（§9.5 公开
         API——写第二槽 + 幂等接线其 on_bind）
  - BG35_Anomaly_002t Mystery Cube（Hero Power）— "Each turn, choose from
    2 new Lesser Trinkets to replace this for free. (Unlocks on Turn 5.)"
      1. `available` = 回合 ≥ 5（"Unlocks on Turn 5"）且存在**未获得**的
         Lesser 饰品候选（空候选不可用——不白扣使用次数，Elise 先例）
      2. `hero_power`: `game.rng.sample` 取 2 个未获得 Lesser 饰品 →
         PendingChoice(kind="trinket_replace") 免费二选一
      3. resolve: `grant_trinket` 授予选中项（非商店路径——RULES §7.4.3）
         + 清空第二技能槽（"replace this"——技能槽被饰品取代）
      4. `uses_per_game = 1`（可选相位未结算前也禁止第二次使用）
      5. 规则依据: `BG35_Anomaly_002` 的 `TAG_SCRIPT_DATA_NUM_1=4`
         （"4 turns left"）与技能文本 "Unlocks on Turn 5" 一致 → 解锁
         回合 = 5（文本字面量; 技能 CardDef 无 {0} 占位符，num(0)=None）

DEFERRED（本批评估后放弃；逐条附具体引擎依赖）
═══════════════════════════════════════════════════════════════════════
饰品复制/变形族（`Crystal Ball`）——两项引擎原语均不存在（已逐个 grep 核实）:
  - BG35_Anomaly_007 Lesser Fortune — 第二技能 = 'Lesser Crystal Ball'
    (`BG35_Anomaly_007t`: "When you buy a Lesser Trinket, this transforms
    into a copy of it.")。
  - BG35_Anomaly_008 Greater Fortune — 同上 Greater 档
    (`BG35_Anomaly_008t`)。
  Dependency (a) **重复授予一张已获得饰品**: 商店 resolve 在广播
  `trinket_bought` **之前**已把所购 id 记入 `game._trinkets_granted`
  （`game.py::_offer_trinkets.resolve`），而 `game.grant_trinket` 以该集合
  去重（已获得 → 返回 None）→ "a copy of it"（购买后同时持有本体 + 副本）
  无法用 `grant_trinket`/`replace_trinket` 落地; 手搓
  `create_entity + hero.trinkets.append` 绕过协议"唯一入口"契约。
  需要 `grant_trinket(..., duplicate=True)` / `game.copy_trinket(hero,
  entity)`（明示副本不参与去重）。
  Dependency (b) **技能槽 → 饰品实体的 transform 表示**: 引擎无"第二技能
  槽被某饰品实体取代"的表示——`hero._second_power_id` 是 CardDB 技能定义
  通道（`hero_power_def_for` 直接 `db.get(power_id)` 并按技能脚本协议
  分发），`replace_trinket` 只作用于 `hero.trinkets` 内的实体，
  `set_second_hero_power` 只接受技能 id 且第二槽未被占用时才可写。
  同一 (a) 缺口亦阻塞饰品 `BG30_MagicItem_888` Souvenir Stand
  （见 batch_trinkets9 模块 docstring）。

未在候选清单内的其它异变不在本作业单范围。
"""

from __future__ import annotations

from hsrl2.game import PendingChoice
from hsrl2.scripts.batches.batch_trinkets9 import (
    LESSER_CHOICE_COUNT,
    TRINKET_REPLACE_KIND,
    ungranted_lesser_trinkets,
)
from hsrl2.tags import CardType

# "It unlocks on Turn 5."（BG35_Anomaly_002t 文本字面量; 技能 CardDef
# 无 {0}/{1} 占位符。异变本体 `BG35_Anomaly_002` 的 num(0)=4
# （"4 turns left"）与 "Turn 5" 一致——见模块 docstring）
MYSTERY_CUBE_UNLOCK_TURN = 5


def mystery_cube_power_id(game):
    """按名字解析 Mystery Cube 英雄技能 id（CardDB 权威; 禁止硬编码 id）。

    全库有两张同名 "Mystery Cube"（饰品 card_type=44 / 英雄技能
    card_type=10）——按 CardType.HERO_POWER 过滤后唯一。未找到 → None
    （调用方落空，不猜）。
    """
    for d in game.db._by_id.values():
        if d.card_type == CardType.HERO_POWER and d.name == "Mystery Cube":
            return d.id
    return None


# ══════════════ BG35_Anomaly_002 Anomalous Cube ══════════════


class AnomalousCubeAnomaly:
    """
    Natural language: [x]Start with 'Mystery Cube' as your second Hero
    Power. It unlocks on Turn 5. <i>({0} |4(turn, turns) left!)</i>

    Evidence: data/bg_anomalies.json BG35_Anomaly_002（num(0)=4 =
    "4 turns left"; `evolution_card_id=132432` → `BG35_Anomaly_002t`
    Mystery Cube, card_type=10 Hero Power）。授予技能经**数据链**解析
    （不硬编码 id——SOP §11 教训 5）。

    Formal spec:
      1. on_bind(game): `game.anomaly` 的 CardDef → `evolution_card_id`
         → `db.by_dbf` 得授予技能定义; 解析失败 / 非 HERO_POWER /
         其脚本未注册（载荷空转，SOP §12 item 14）→ 整卡落空
      2. 对每个英雄 `game.set_second_hero_power(hero, power.id)`
         （RULES §9.5: 写 `hero._second_power_id` + 幂等接线其 on_bind;
         第二槽已占用 → 该英雄跳过）
      3. 授予后 `game.hero_power_ids(hero)` 含该技能; 其 `available`
         门槛（Turn 5）由技能脚本负责

    Test: test_batch_anomalies5.py — 真实 `Game(anomaly=...)` +
      `start_game()` 后两英雄第二槽 == 数据链解析值、
      `hero_power_ids` 含它、`use_hero_power(..., power_id=)` 可用;
      对照局（无异常）第二槽为 None

    Params: 无模板参数（技能名出自文本; id 由 CardDB/数据链解析）
    """

    @staticmethod
    def on_bind(game):
        d = game.db.get(game.anomaly) if game.anomaly else None
        if d is None or d.evolution_card_id is None:
            return None
        power = game.db.by_dbf(d.evolution_card_id)
        if power is None or power.card_type != CardType.HERO_POWER:
            return None
        from hsrl2.scripts import REGISTRY
        if power.id not in REGISTRY:
            return None            # 载荷未就绪 → 不授予空转技能
        for h in game.heroes:
            if getattr(h, "_second_power_id", None) is not None:
                continue           # 第二槽已占用（RULES §9.5 单槽）
            game.set_second_hero_power(h, power.id)
        return None


# ══════════════ BG35_Anomaly_002t Mystery Cube (Hero Power) ══════════════


class MysteryCubePowerScript:
    """
    Natural language: Each turn, choose from 2 new Lesser <b><b>Trinket</b>s
    </b> to replace this for free. <i>(Unlocks on Turn 5.)</i>

    Evidence: data/bg_hero_powers.json `BG35_Anomaly_002t`（card_type=10,
    cost=0, num(0)=None; 文本 "Unlocks on Turn 5"）。与饰品版
    `BG30_MagicItem_703` 同文（后者为被动触发 "At the start of each
    turn, repeat this"；技能版是**主动**技——"Each turn, choose ..."，
    点击后二选一，选中即替换本技能）。

    Formal spec:
      1. `available(hero, game)`: `game.turn >= 5`（"Unlocks on Turn 5"）
         且 `ungranted_lesser_trinkets(game, hero)` 非空（候选耗尽时不可用——
         不白扣每局使用次数，Elise T4 先例）
      2. `hero_power(hero, game, ctx)`: `game.rng.sample` 取
         num(`LESSER_CHOICE_COUNT`)=2 个**未获得** Lesser 饰品 CardDef →
         PendingChoice(kind="trinket_replace", owner=hero)
      3. resolve(pick): 陈旧防护（槽已被替换 / 选项已被并发授予 → 落空）
         → `game.grant_trinket(hero, pick.id, source="mystery_cube")`
         （非商店路径: 实体入 `hero.trinkets` + 跑其 on_bind +
         广播 `trinket_granted`；**免费**，不扣金币、不广播
         `trinket_bought`）→ 清空 `hero._second_power_id`
         （"replace this"——技能槽被所选饰品取代）
      4. `uses_per_game = 1`: 每局一次（选择挂起期间亦禁止第二次使用）
      5. 只作用于本人（per-hero 独立选择）

    Test: test_batch_anomalies5.py — Turn 1..4 不可用且无选择（正对照:
      Turn 5 可用并产生 2 选项）/ 选项互异、均为未获得 Lesser /
      选中后饰品入栏且 `_trinkets_granted` 记账、金币不变、第二槽清空
      （`hero_power_ids` 不再含本技能）/ 每局一次（首次使用后第二次
      `use_hero_power` 返回 False）/ 对手不受影响 / 候选耗尽时 available
      为 False 不可用 / 陈旧选项（已被并发授予）不产生第二份且不清槽

    Params: choices=2（"choose from 2" 文本字面量）unlock_turn=5
             （"Unlocks on Turn 5." 文本字面量）
    """

    # "replace this" = 技能槽被饰品取代（一次性）; 挂起期亦禁止再用
    uses_per_game = 1

    @staticmethod
    def available(hero, game) -> bool:
        if game.turn < MYSTERY_CUBE_UNLOCK_TURN:
            return False
        return bool(ungranted_lesser_trinkets(game, hero))

    @staticmethod
    def hero_power(hero, game, ctx):
        pool = ungranted_lesser_trinkets(game, hero)
        if not pool:
            return None
        options = game.rng.sample(
            pool, min(LESSER_CHOICE_COUNT, len(pool)),
            label="mystery_cube_power")
        pid = mystery_cube_power_id(game)

        def resolve(pick):
            if pick is None:
                return
            if pid is not None \
                    and getattr(hero, "_second_power_id", None) != pid:
                return              # 槽已被其它效果替换 → 陈旧选择落空
            # 落空路径必须**回滚本局使用次数**（否则 uses_per_game=1 的
            # 技能变成永久死技能——2026-09-02 对抗审查 MINOR）
            if pick.id in hero.trinkets_granted:
                game.refund_hero_power_use(hero, pid)
                return              # 选项已被并发授予 → 落空（保留槽）
            if game.grant_trinket(hero, pick.id,
                                  source="mystery_cube") is None:
                game.refund_hero_power_use(hero, pid)
                return
            hero._second_power_id = None   # "replace this"

        game.pending_choices.append(PendingChoice(
            hero, options, TRINKET_REPLACE_KIND, resolve_callback=resolve))
        return None


def register() -> list[str]:
    """注册异变 1 张 + 第二技能槽技能 1 张（DEFERRED 台账见 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_Anomaly_002", AnomalousCubeAnomaly),
        ("BG35_Anomaly_002t", MysteryCubePowerScript),
    ]
    registered = []
    for aid, cls in pairs:
        reg(aid, cls)
        registered.append(aid)
    return registered
