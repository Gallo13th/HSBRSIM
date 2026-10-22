"""批次 anomalies4 — 异变系统第四批: 第二英雄技能槽（作业单 2026-09-02）。

引擎原语: RULES §9.5「英雄技能槽（Hero Power Slots）」（commit 4167dc8）——
`hero._second_power_id`（异变/奖励在 `on_bind` 中声明）、
`game.hero_power_ids(hero)`、`game.hero_power_def_for(hero, power_id)`、
`game.use_hero_power(hero, target=None, power_id=...)`; 每技能独立的
每回合/每局计数与费用; `start_game` 接线顺序 = 主技能 → 异变 on_bind
（声明第二槽）→ 第二技能槽 on_bind（本批不自行重接线——引擎已实现）。

注册 3 张（第二技能槽族）
═══════════════════════════════════════════════════════════════════════
  - BG32_Anomaly_001 Greater Pouches — 第二技能 = 'Growing Collection'
  - BG32_Anomaly_002 Lesser Pouches  — 第二技能 = 'Fantastic Treasure'
  - BG31_Anomaly_123 Cosmic Duality  — 开局 Discover 一个第二英雄技能
    （真实 Discover/choice，候选池 = `_draftable_hero_power_ids`，
    选中后写第二槽并显式接线被选技能的 on_bind）

技能 id 一律**按名字从 CardDB 解析**（SOP §11 教训 5: 禁止凭记忆写 id）:
  - "Growing Collection" → BG32_HERO_002p（batch_hero_remaining
    GrowingCollectionScript，已注册）
  - "Fantastic Treasure" → BG30_HERO_304p（同批 FantasticTreasureScript）
两张技能均为 passive: 其效果经 `on_bind` 注册 TURN_START once 监听
（第 num(0)+1 回合发放对应档位饰品商店），由引擎的第二槽接线循环触发
——测试断言该监听器真的在 T8/T5 发放 trinket_offer（on_bind 活性证据）。

QUEST REWARD
═══════════════════════════════════════════════════════════════════════
  - BG33_Reward_017 Cosmic Reward — 同 Cosmic Duality 的发现协议，作为
    任务奖励在 `on_bind(source, game, ctx={"hero": hero})` 中接线
    （实现见 `hsrl2/scripts/batches/batch_quest_rewards5.py`，复用本模块
    的 `grant_second_power_discover`）。

DEFERRED 台账（撤注册 — SOP §6b 二态铁律; 逐条附具体缺失引擎原语）
═══════════════════════════════════════════════════════════════════════
饰品替换/变形族（`Crystal Ball` / `Mystery Cube`）——**已迁出**:
  - BG35_Anomaly_002 / `_002t` Anomalous Cube → batch_anomalies5（已实现）
  - BG35_Anomaly_007 / `BG35_Anomaly_008` 及其技能 `_007t` / `_008t`
    （Lesser/Greater Crystal Ball）→ batch_anomalies6（已实现）
  当时阻塞的两项引擎原语已于 2026-09-02 补齐（RULES §7.4.3 副本条款 /
  §9.5 第二槽饰品表示）:
    (a) **饰品购买事件**: `events.TRINKET_BOUGHT`（`_offer_trinkets`
        resolve 广播）——"When you buy a ... Trinket" 的触发点。
    (b) **技能位 → 饰品副本的表示**: `game.set_second_slot_trinket`
        （槽位标记改写为饰品 id + 副本实体入 `hero.trinkets`，
        `hero_power_ids` 只列真正的 HERO_POWER）。
    (c) **每回合 2 选 1 免费饰品的 offer**: 由脚本层 PendingChoice
        （batch_anomalies5 / batch_trinkets9）表达，无需新引擎协议。

载荷（授予物技能）本身 DEFERRED（SOP §12 第 14 条——机制就绪 ≠ 可兑现）:
  - BG27_Anomaly_822 Denathrius' Anima Reserves — 第二技能 =
    'Whodunit?'（`BG24_HERO_100p`）。槽位机制就绪，但 WhodunitScript
    因**任务卡 17 张全部 DEFERRED**（难度的任务/奖励基础值 × 种族 ×
    护甲修正无数据权威，RULES §11.6）而撤注册 →
    选到的任务永不推进，第二槽在真实对局中为**空转技能**。按二态铁律
    整卡保持 DEFERRED，待任务难度权威落地后随 WhodunitScript 一起注册。

英雄身份替换（整卡二态，不得部分实现）:
  - BG31_Anomaly_106 Marin's Treasure Box — "All heroes are Marin the
    Manager. Make 'Growing Collection' your second Hero Power." 需把
    **全体英雄身份**替换为 Marin the Manager（hero.card_id / 技能链 /
    起始护甲/伙伴全部随身份变化）; 引擎无英雄身份替换协议 → 整卡
    DEFERRED（第二槽那句虽已可表达，但部分实现违反二态铁律）。

超出本批卡类（英雄技能，非异变/奖励）:
  - BG35_HERO_001p King of Duality（Genn）— "On Turn 4, Discover two
    Hero Powers to replace this." 需**两连发现 + 双槽替换协议**:
    引擎每英雄只有一个第二槽（`_second_power_id`，RULES §9.5），
    `replace_hero_power` 只维护单一 `_active_power_id`;
    `target_count=2` 是"同一动作依次选两个目标"链，不是"两次独立
    Discover"。记录在此供英雄技能批次接手。

未在候选清单内的其它异变不在本作业单范围。
"""

from __future__ import annotations

from hsrl2.game import GameStateError, PendingChoice
from hsrl2.tags import CardType

# ── 按名字解析的授予技能（CardDB 权威; SOP §11 教训 5）──

POWER_NAME_GROWING_COLLECTION = "Growing Collection"   # BG32_HERO_002p
POWER_NAME_FANTASTIC_TREASURE = "Fantastic Treasure"   # BG30_HERO_304p

# Cosmic Duality / Cosmic Reward 的 Discover 展示数 = 3
# （Discover 协议默认三选一; 文本无占位符——SOP §14 第 2 条:
#  `Discover.count` 是选项数）
DISCOVER_CHOICES = 3


def power_id_by_name(game, name: str):
    """按 CardDef.name 解析英雄技能 id（禁止硬编码 id）。

    `CardDB._by_id` 含全部 bg_hero_powers.json 定义（card_type=10）;
    同名技能在全库唯一（实测 "Growing Collection"/"Fantastic
    Treasure" 各恰 1 张）。未找到 → None（调用方落空，不猜）。
    """
    for d in game.db._by_id.values():
        if d.card_type == CardType.HERO_POWER and d.name == name:
            return d.id
    return None


def registered_power_id_by_name(game, name: str):
    """解析技能 id 且要求其脚本已注册（未注册 → None）。

    载荷未就绪的技能授予后是空转技能（SOP §12 第 14 条）——宁缺毋错。
    """
    from hsrl2.scripts import REGISTRY
    pid = power_id_by_name(game, name)
    if pid is None or pid not in REGISTRY:
        return None
    return pid


def grant_second_power_discover(hero, game) -> bool:
    """开局/奖励: Discover 一个英雄技能并写入第二技能槽（RULES §9.5）。

    返回 True=已入队 PendingChoice; False=落空（无候选/第二槽已占用）。

    契约:
      1. 候选池 = `batch_hero_remaining._draftable_hero_power_ids`
         （英雄绑定的技能全集 = 116 个; Finley "Adventure!" 同源裁定）,
         排除本英雄**当前主技能**（Discover 不提供已持有技能——
         Finley 先例: wiki Power of the Storm banned pool 剔除自身）。
      2. 每英雄只有一个第二槽（RULES §9.5 "第二技能槽"单数）:
         `_second_power_id` 已有值（另一异变/奖励已授予）→ 本次落空，
         不覆盖（覆盖会让旧技能监听器成为幽灵）。
      3. `rng.sample` 取 3 个互异候选 → PendingChoice(kind=
         "discover_hero_power"，options=技能 id 字符串; 复用 Finley 的
         kind 与自动化层 choice_policy 协议）。
      4. resolve(power_id): 仅接受在 options 内且 CardDB 存在的 id
         （陈旧/非法选择落空）→ 写 `hero._second_power_id` +
         引擎公开 API `game.set_second_hero_power`（RULES §9.5: 写第二槽
         + 幂等接线其 on_bind）——本选择在 `start_game` 的接线循环**之后**
         才结算，被动技能的 on_bind 监听器必须在此补接线（Finley 同款
         先例; 2026-09-02 引擎新增公开入口，脚本不再跨批次 import 私有
         帮助函数）。
    """
    from hsrl2.scripts.batches.batch_hero_remaining import (
        _draftable_hero_power_ids,
    )

    if getattr(hero, "_second_power_id", None) is not None:
        return False        # 第二槽已占用（RULES §9.5 单槽）
    exclude = set()
    main = game.hero_power_def(hero)
    if main is not None:
        exclude.add(main.id)
    pool = _draftable_hero_power_ids(game, exclude=exclude)
    if not pool:
        return False        # 无候选 → 落空（不建选择）
    options = game.rng.sample(pool, min(DISCOVER_CHOICES, len(pool)),
                              label="second_hero_power")

    def resolve(power_id):
        if power_id not in options:
            return          # 陈旧/非法选项 → 落空
        try:
            game.set_second_hero_power(hero, power_id)
        except GameStateError:
            # 结算窗口内第二槽被他人占用 / 技能定义缺失 → 落空
            return

    game.pending_choices.append(PendingChoice(
        hero, options, "discover_hero_power", resolve_callback=resolve))
    return True


# ══════════════ BG32_Anomaly_001 Greater Pouches ══════════════


class GreaterPouchesAnomaly:
    """
    Natural language: Start with 'Growing Collection' as your second Hero
    Power.

    Evidence: data/bg_anomalies.json BG32_Anomaly_001（无模板参数）;
    授予技能按名字从 CardDB 解析 = `BG32_HERO_002p`（CardDef.name 唯一;
    batch_hero_remaining.GrowingCollectionScript 已注册，passive:
    on_bind 注册 TURN_START once 监听，第 num(0)+1 = 8 回合发放 Greater
    饰品商店）。引擎 `start_game` 三段接线顺序保证第二槽的 on_bind 在
    首回合开始前就位（RULES §9.5）。

    Formal spec:
      1. on_bind(game): 解析 'Growing Collection' 技能 id; 解析失败或
         其脚本未注册 → 整卡落空（不授予空转技能）
      2. 每英雄 `_second_power_id = BG32_HERO_002p`（引擎随后接线其
         on_bind——本脚本不自行接线）

    Test: test_batch_anomalies4.py — 真实开局后 `hero_power_ids` 含该
    技能（len==2、第二槽 == 数据解析值）/ 第 8 回合每英雄各得 1 个
    greater 档 trinket_offer（on_bind 监听器活性证据）/ 对照局第 8 回合
    无 offer / 技能 passive 不可点击（`use_hero_power` 对第二槽 False）

    Params: 无模板参数（技能名出自文本; id 由 CardDB 解析）
    """

    @staticmethod
    def on_bind(game):
        pid = registered_power_id_by_name(game, POWER_NAME_GROWING_COLLECTION)
        if pid is None:
            return None
        for h in game.heroes:
            h._second_power_id = pid
        return None


# ══════════════ BG32_Anomaly_002 Lesser Pouches ══════════════


class LesserPouchesAnomaly:
    """
    Natural language: Start with 'Fantastic Treasure' as your second Hero
    Power.

    Evidence: data/bg_anomalies.json BG32_Anomaly_002（无模板参数）;
    授予技能按名字解析 = `BG30_HERO_304p`（batch_hero_remaining.
    FantasticTreasureScript，passive: 第 num(0)+1 = 5 回合发放 Lesser
    饰品商店）。

    Formal spec:
      1. on_bind(game): 解析 'Fantastic Treasure' 技能 id; 失败/未注册
         → 落空
      2. 每英雄 `_second_power_id = BG30_HERO_304p`

    Test: test_batch_anomalies4.py — 真实开局后第二槽 = 数据解析值 /
    第 5 回合每英雄各得 1 个 lesser 档（spell_school=11）trinket_offer /
    第 6 回合标准 lesser 档不重复发放（记账 (hero,kind) 生效）/ 对照局
    第 5 回合无 offer、第 6 回合才有

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(game):
        pid = registered_power_id_by_name(game,
                                          POWER_NAME_FANTASTIC_TREASURE)
        if pid is None:
            return None
        for h in game.heroes:
            h._second_power_id = pid
        return None


# ══════════════ BG31_Anomaly_123 Cosmic Duality ══════════════


class CosmicDualityAnomaly:
    """
    Natural language: At the start of the game, Discover a second Hero
    Power.

    Evidence: data/bg_anomalies.json BG31_Anomaly_123（无模板参数）。
    "Discover" = 真实玩家选择（非随机近似; SOP §8 Kelp Keeper 先例）→
    PendingChoice; 候选池 = 英雄绑定的技能全集
    （`_draftable_hero_power_ids`, Finley "Adventure!" 同源裁定: 116 个
    技能; token 技能不绑定英雄故排除）。三选一为 Discover 默认展示数。

    Formal spec:
      1. on_bind(game): 每英雄 `grant_second_power_discover(hero, game)`
         ——候选排除本英雄主技能; 第二槽已占用 → 该英雄落空
      2. 选项 = `rng.sample` 3 个互异技能 id（per-hero 独立采样）
      3. resolve: 选中技能写 `hero._second_power_id` + 显式接线其
         on_bind（本选择在 start_game 接线循环之后结算）
      4. 非法/陈旧选择 id → 落空（槽不变）

    Test: test_batch_anomalies4.py — 开局每英雄恰 1 个
    discover_hero_power 且 owner 隔离; 选项 ⊆ 候选池、不含本人主技能、
    互异且恰 3 个; 选中后第二槽 = 选中 id; **真的可用**（选 Hollidae
    `BG28_HERO_801p` → `use_hero_power(power_id=...)` 手牌 +1 法术、
    池占用 +1）; 用过第二技能后主技能仍可用（次数独立）; 第二技能
    同回合不可再用; 选中 passive 技能（Growing Collection）时其
    on_bind 监听器活性（T8 greater offer）; 非法 id 落空（正对照:
    合法选择确实写入槽）; 预置第二槽 → 该英雄不再获得选择（对手照常）

    Params: 无模板参数; choices=3（Discover 默认展示数）
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            grant_second_power_discover(h, game)
        return None


def register() -> list[str]:
    """注册异变 3 张（DEFERRED 台账见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_Anomaly_001", GreaterPouchesAnomaly),
        ("BG32_Anomaly_002", LesserPouchesAnomaly),
        ("BG31_Anomaly_123", CosmicDualityAnomaly),
    ]
    registered = []
    for aid, cls in pairs:
        reg(aid, cls)
        registered.append(aid)
    return registered
