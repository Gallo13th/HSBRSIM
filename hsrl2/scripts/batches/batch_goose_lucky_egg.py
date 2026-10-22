"""批次 goose_lucky_egg — Goose Portrait 链（作业单 2026-09-17 清尾）。

背景: `d981df6`/`cdfffa0` 注册了载荷随从 `BG29_801`/`BG29_801_G`
（Silver Goose）后，`BG30_MagicItem_777` Goose Portrait 的残余阻塞 =
**次生载荷** `BG30_104` Lucky Egg 未注册。本批把该链整条关闭（二态:
CORRECT），不在任何残留缺口上做近似。

注册 3 张（注册键 = 卡 id；金色 = 独立卡定义）
═══════════════════════════════════════════════════════════════════════
  BG30_104 Lucky Egg（T5 2/2 token，`is_pool_minion=False`）
      "<b>Battlecry:</b> <b>Discover</b> a Golden Tier 3 minion to
      transform into."
      金色 `BG30_104_G`（4/4）文本 "...a Golden Tier **4** minion to
      transform into."——档位是**文本字面量**（两卡 CardDef 均无
      `script_data_num_*`；见 `_LUCKY_EGG_TIERS`）。
      数据链: `triple_upgrade_id=113131`（base→golden）、
      `triple_base_id=113130`（golden→base），本批运行核验。

  BG30_MagicItem_777 Goose Portrait
      "[x]Get a Silver Goose. After you summon 3 Silver Fledglings,
      get a Lucky Egg. <i>({0} left!)</i>"
      `num(0)=3`（`script_data_num_1`；文本 {0} 即剩余计数）。
      数据链: `evolution_card_id=107865` → `BG29_801` Silver Goose
      （`BACON_EVOLUTION_CARD_ID_2=113130` → `BG30_104` 次生载荷）。

语义权威（逐条）
═══════════════════════════════════════════════════════════════════════
  1. "Discover a Golden Tier N minion" 的**发现口径**（候选 = 池内恰好该档
     的随从、金色本体、占池 1 份基础副本 + `GILDED_NOT_TRIPLED`、
     未选项回池）**已有同文本先例**: `BG27_Anomaly_572` Treasure Hoard
     "On Turn 5, Discover a Golden Tier 3 minion."（batch_anomalies2，
     走 `Discover(golden=True)`）。本批复用同一池记账口径。
  2. "to transform into" 的**变形口径** = 引擎 `Transform` Action
     （`hsrl2/actions/stats.py`；RULES §6.21）。目标 = Lucky Egg **自身**
     （战吼在随从入场后结算——`game.play_minion` 先 `summon` 再
     `_run_play_effects`，故战吼时 source 已在 `hero.board`）。
  3. 附魔保留 = **不保留**: wiki "Transform" 页 Notes "Cards that
     transform do not keep any enchantments when they transform."
     （Game Mechanics Updates, July 2018）→ `keep_buffs=False`（引擎
     `Transform` 支持；与 Reno 式"Make Golden"的 keep_buffs 语义区分）。
  4. 金色战吼 = **单次总额**（"Tier 4" 是档位升级，不是 "Discover twice"）
     → 沿用 `batch_battlecry.BilgewaterBreakoutGoldenScript` 的既有模式:
     引擎对金色战吼触发 2 次，脚本以实体级 `_lucky_egg_resolved` 守卫只让
     **首次**触发结算（第二次触发 no-op）。同款 SPEC_GAP（Brann/额外触发
     不放大金色总额型战吼）在本族同样不放大——与 Bilgewater 一致，不新增
     引擎原语（本轮实现不触碰引擎）。
  5. Goose Portrait 的**计数口径**: "After you summon 3 Silver Fledglings"
     ——阈值 = `num(0)=3` + 文本字面量 3（一致）；按 token 家族计数
     （`BG29_801t` 基础 / `BG29_801_Gt` 金色——两卡同名 "Silver
     Fledgling"、`triple_base_id` 数据链相连）；计满交付 `BG30_104` 并
     **复位计数**（`{0} left!` 递减显示 + 无 "Once per game" ⇒ 可重复）。
     先例: `batch_trinkets7.WildfeatherDusterScript`（SUMMON 监听 +
     num 阈值 + 计满复位 + 池感知交付）。
  6. **已知引擎级口径（非本卡特有，已披露）**: wiki `Transform` 页 Notes
     另载 "minions transformed as the result of a **Battlecry** will ...
     activate ... 'Whenever you summon' effects"（战吼变形在召唤流程末尾
     追加一次 "Whenever you summon" 阶段）——引擎 `Transform` **不**重放
     召唤流程（`actions/stats.py` 仅 fire "transform" + `on_transform`），
     RULES §6.21 亦裁定"Transform 不触发召唤/战吼类"。按项目权威序
     （CardDefs > RULES > patch notes > wiki）本卡沿用引擎现状; 该横切
     缺口已登记 `ENGINE_BACKLOG`（影响全部 Transform 卡，非本卡阻塞）。

实现要点
═══════════════════════════════════════════════════════════════════════
  - 发现选择用**自建 PendingChoice**（与 `Discover` 同协议: 选项生成即
    `minion_pool.acquire` 预留、resolve 释放未选项、kind=
    "discover_minion" + `discover_golden=True`），因为 `Discover` 的
    resolve 固定"入手牌"，本卡要的是"变形自身"。自建 discover 的池记账
    先例: `batch_hero_combat3.ThorimScript`（同样的 acquire/release 协议）。
  - 变形走 `Transform(source, pick, keep_buffs=False,
    gilded_not_tripled=True, force_golden=True)`——`pick` 是基础 id，
    `force_golden=True` 由 `create_minion` 解析金色独立 CardDef 并写
    `TRIPLE_BASE_CARD_ID`/`GOLDEN`；`gilded_not_tripled` 与
    `Discover(golden=True)` 同口径（出售/淘汰按 1 份回池）。
  - 变形后 source 变为 `Zone.REMOVED`；`on_transform` 由 `Transform`
    统一分发（被动重接线）。`resolve` 要等 `play_minion` 返回、玩家结算
    选择时才执行，其间 source 可能已离场（出售/被消灭）→ 守卫
    `source.controller is not hero or source not in hero.board` 释放预留的
    选中副本后落空（不凭空造实体；池守恒）。
    守卫**不**负责金色二次触发: `_run_play_effects` 会把 N 次金色触发
    全部跑完才轮到任何 PendingChoice 结算，第 2 次触发时蛋仍在场且未
    变形（该路径由 `_lucky_egg_resolved` 处理，见 Formal spec 7）。

Test: `hsrl2/tests/test_batch_goose_lucky_egg.py`（真实 `grant_trinket` /
真实 `game.summon` SUMMON 监听 / 真实 `play_minion`+`PendingChoice` /
真实 `minion_pool` 占返 / 金色独立定义 / 负对照 / 同 seed 确定性）。
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from hsrl2.actions import Transform
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import SUMMON, Listener
from hsrl2.game import GameStateError, PendingChoice

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.minion import Minion

# ── 卡 id（CardDB 按名核实，禁止凭记忆写） ──
GOOSE_PORTRAIT = "BG30_MagicItem_777"   # 饰品（Lesser, spell_school=11）
LUCKY_EGG = "BG30_104"                  # 次生载荷（T5 2/2; dbf 113130）
LUCKY_EGG_G = "BG30_104_G"              # 金色（4/4; dbf 113131; T4 档）
SILVER_GOOSE = "BG29_801"               # 首载荷（evolution_card_id 107865）
FLEDGLING = "BG29_801t"                 # Silver Fledgling 2/2 Taunt
FLEDGLING_G = "BG29_801_Gt"             # Silver Fledgling 4/4 Taunt

# 文本字面量档位（CardDef 无模板参数——两卡均在文本里写死档位）
_LUCKY_EGG_TIERS = {LUCKY_EGG: 3, LUCKY_EGG_G: 4}

# 计数家族: 基础 + 金色 token（同名 "Silver Fledgling"；金色经
# triple_base_id 与基础相连）
_FLEDGLING_FAMILY = frozenset({FLEDGLING, FLEDGLING_G})


def _num(game: "Game", card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _discover_golden_transform(game: "Game", hero: "Hero",
                               source: "Minion", tier: int) -> None:
    """"Discover a Golden Tier <tier> minion to transform into"。

    与 `actions.Discover(golden=True)` **同一池记账协议**（预留/释放/
    金色本体/GILDED_NOT_TRIPLED），差别仅在 resolve = 变形 `source` 自身
    （而非入手牌）。无候选 → 落空（真实游戏池空即落空）。
    """
    cands = _pool_candidates(game, None, tier, tier)
    if not cands:
        return
    k = min(3, len(cands))
    drawn = game.rng.sample(cands, k, label="lucky_egg_options")
    options = [cid for cid in drawn if game.minion_pool.acquire(cid)]
    if not options:
        return

    def resolve(pick: str) -> None:
        if pick not in options:
            raise GameStateError(
                f"LuckyEgg: pick {pick} 不在提供选项中 {options}")
        for cid in options:
            if cid != pick:
                game.minion_pool.release(cid, 1)
        # 结算前 source 已离场（死亡/被移除）→ 释放预留副本、落空
        # （不凭空造实体；池守恒）
        if source.controller is not hero or source not in hero.board:
            game.minion_pool.release(pick, 1)
            return
        game.run_actions(Transform(
            source, pick, keep_buffs=False,
            gilded_not_tripled=True, force_golden=True))

    choice = PendingChoice(hero, list(options), "discover_minion",
                           resolve_callback=resolve)
    choice.discover_golden = True
    game.pending_choices.append(choice)


class LuckyEggScript:
    """
    Natural language: <b>Battlecry:</b> <b>Discover</b> a Golden Tier 3
    minion to transform into.

    Formal spec:
      1. battlecry（入场后结算——`game.play_minion` 先 `summon` 再
         `_run_play_effects`，故 `source in hero.board`）:
         `_discover_golden_transform(game, hero, source, 3)`
      2. 档位来自**文本字面量** `_LUCKY_EGG_TIERS`（CardDef 无
         `script_data_num_*`；金色 `BG30_104_G` 文本为 Tier 4）
      3. 候选 = `_pool_candidates(min_tier=max_tier=tier)`——池剩余量 > 0、
         本局可用种族过滤（与 `Discover` 同口径）
      4. 选项 ≤3 个不同 card_id，生成即 `minion_pool.acquire` 预留;
         resolve: 释放未选项 → `Transform(source, pick,
         keep_buffs=False, gilded_not_tripled=True, force_golden=True)`
         （pick 为基础 id，金色独立 CardDef 由 create_minion 解析）
      5. 无候选 → 落空（无 PendingChoice，source 留在棋盘为白板 2/2）
      6. 附魔不保留（wiki Transform Notes）；金色状态由文本给出（金色
         档位 = Tier 4）
      7. 实体级 `_lucky_egg_resolved` 守卫: 金色文本是"档位升级"而非
         "twice"（单次总额模型，Bilgewater 先例）——引擎对金色战吼触发
         2 次，只让**首次**触发建立发现。`_run_play_effects` 在任何
         PendingChoice 结算前跑完全部触发，故第 2 次触发时 source 仍在
         场且未变形; 守卫拦的是"同一实体重复建选择"，不是离场竞态
         （离场竞态由 `resolve` 内守卫覆盖，见实现要点）

    Test: test_batch_goose_lucky_egg.py — 真实 play_minion → 1 个
    discover_minion 选择 / 选项全为 Tier 3 且 discover_golden=True /
    选中后 source 变为**金色**基础 id 对应的独立 CardDef 且
    GILDED_NOT_TRIPLED / 未选项回池、选中项占 1 份 / 无 T3 候选落空 /
    金色只建立 1 次选择（Tier 4 档）/ 结算前本体离场（真实
    `sell_minion`）→ 释放预留副本、不变形、池守恒（竞态守卫）

    Params: 无模板参数（"Tier 3"/"Tier 4" 为文本字面量；
            BG30_104/`_G` num(0..4) 全 None）
    """

    @staticmethod
    def battlecry(source: "Minion", game: "Game", ctx) -> Optional[object]:
        if getattr(source, "_lucky_egg_resolved", False):
            return None
        source._lucky_egg_resolved = True
        hero = source.controller
        if hero is None:
            return None
        tier = _LUCKY_EGG_TIERS.get(source.card_id)
        if tier is None:
            raise GameStateError(
                f"LuckyEgg: no tier mapped for {source.card_id!r}")
        _discover_golden_transform(game, hero, source, tier)
        return None


class LuckyEggGoldenScript(LuckyEggScript):
    """
    Natural language: <b>Battlecry:</b> <b>Discover</b> a Golden Tier 4
    minion to transform into.

    Formal spec: 同基础版，档位 = 4（`_LUCKY_EGG_TIERS[BG30_104_G]`）。
    **金色战吼单次总额模型**: 引擎对金色随从的战吼触发 2 次
    （`_run_play_effects`），本卡的金色文本是"档位升级"而非 "twice"，
    故沿用 `batch_battlecry.BilgewaterBreakoutGoldenScript` 的
    `_lucky_egg_resolved` 守卫——首次触发建立发现，第二次 no-op。
    （SPEC_GAP: Brann/额外触发对金色总额型战吼不放大，与 Bilgewater 同款，
    不新增引擎原语。）

    Test: test_batch_goose_lucky_egg.py — 真实 play_minion(BG30_104_G)
    恰 1 个选择 / 选项全为 Tier 4 / 选中项为金色 T4 独立定义

    Params: 无模板参数（"Tier 4" 为文本字面量）
    """


class GoosePortraitScript:
    """
    Natural language: [x]Get a Silver Goose. After you summon 3 Silver
    Fledglings, get a Lucky Egg. <i>({0} left!)</i>

    Formal spec:
      1. on_bind(source, game, ctx)（hero=ctx["hero"]）:
         `game.grant_trinket_related_card(hero, 本饰品 id)` 经
         `evolution_card_id=107865` 数据链交付 `BG29_801` Silver Goose
         （解析失败 → `grant_card_copy_to_hand(None)` 返回 False，
         整卡落空——不近似）
      2. 注册持久监听器（owner=饰品）: `SUMMON`（minion=）——条件 =
         `minion.controller is 本人` 且 `minion.card_id ∈ {BG29_801t,
         BG29_801_Gt}`（"Silver Fledglings" 家族: 基础 + 金色 token）
      3. 计数达 `num(0)=3`（文本字面量 3 一致）→ 复位计数并经
         `grant_card_copy_to_hand(hero, BG30_104)` 交付 Lucky Egg
         （token 池外 → 零池操作；满手入等待队列）
      4. 计数跨回合/跨战斗累积（文本无 "this turn"/"in combat" 限定;
         无 "Once per game" ⇒ 计满复位后可重复）
      5. 只有本人召唤计入; 对手召唤 / 其它随从召唤不计
      6. 数值零硬编码：阈值 = `num(0)`；交付卡 = 数据链次生载荷
         `BACON_EVOLUTION_CARD_ID_2=113130` 运行核实 = `BG30_104`
         （本脚本以常量固定，测试钉死与数据链一致）

    Test: test_batch_goose_lucky_egg.py — 真实 grant_trinket 后手牌出现
    BG29_801 且监听生效; 前 2 只 Fledgling 不交付 / 第 3 只交付 1 张
    BG30_104 且计数复位 / 金色 Fledgling 计入同一家族 / 非 Fledgling
    召唤不计 / 对手召唤不计 / 两轮 3 只各交付 1 张

    Params: {0}=3（BG30_MagicItem_777 num(0)；num(1..4) 全 None）
    """

    @staticmethod
    def on_bind(source: "object", game: "Game", ctx) -> None:
        hero = ctx.get("hero") if isinstance(ctx, dict) else None
        if hero is None:
            return None
        game.grant_trinket_related_card(hero, source.card_id)
        threshold = _num(game, source.card_id, 0)
        state = {"n": 0}

        def on_summon(g: "Game", minion: "Minion" = None, **kw) -> None:
            if minion is None or minion.controller is not hero:
                return
            if minion.card_id not in _FLEDGLING_FAMILY:
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            g.grant_card_copy_to_hand(hero, g.db.get(LUCKY_EGG))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summon))
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册 3 张（全部 CORRECT，0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (LUCKY_EGG, LuckyEggScript),
        (LUCKY_EGG_G, LuckyEggGoldenScript),
        (GOOSE_PORTRAIT, GoosePortraitScript),
    ]
    registered = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
