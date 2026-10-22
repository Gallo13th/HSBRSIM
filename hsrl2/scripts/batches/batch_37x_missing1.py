"""批次 37x_missing1 — 差分 harness 高频「缺脚本」卡（S14→37.0 遗留池）。

背景
═══════════════════════════════════════════════════════════════════════
`runs/diff_report.md`（679 场官方 BG 战斗，HDT BobsBuddy 日志）把
247 条 ENGINE_DIVERGENCE 归因为 `missing_script`，按频次 TOP 为:
  BG27_004(59) / BG34_630(36) / BG34_921(31) / BG35_801(26) / BG31_171(22)。
本批实现其中 5 张 + 1 张同族高频卡（BG25_039 Pufferquil，15）：

  BG27_004 Surf n' Surf（+金色 BG27_004_G）— Spellcraft 随从：
           打出即获得法术 BG27_004t/Gt「Crab Mount」；
  BG27_004t / BG27_004_Gt Crab Mount — 法术：给一个随从
           「亡语: 召唤 3/2 / 6/4 Crab」直到下回合；
  BG34_630 Twilight Hatchling（+金色）— 亡语: 召唤（金色两只）
           3/3 Whelp 并立即攻击；
  BG34_921 Ring Bearer（+金色）— 任一友方随从攻击时施放 Shiny Ring
           （金色两次）；
  BG35_801 Gluttonous Trogg（+金色）— 购买 4 张牌后 +4/+4（金色 +8/+8）
           一次性触发；
  BG25_039 Pufferquil（+金色）— 每当一个法术以本随从为目标，获得
           Venomous 直到下回合（金色永久）。

**DEFERRED（不注册）**: BG31_171 Moonsteel Juggernaut —— "improve this"
的**增量数值**无权威（CardDefs 只有 NUM_1=0 计数 / NUM_2=6 卫星尺寸，
wiki Notes 缺失、39.2 补丁说明只有基础值；社区实测样例是旧 3/3 时代的
+3/+3，无法确定当前 6/6 时代增量）。按 SOP §6b 第 4 步撤注册，详见
`MoonsteelJuggernautScript` docstring。

池状态说明（重要）
═══════════════════════════════════════════════════════════════════════
这 6 张卡在官方 **37.0.0 (255130)** 数据里都**已不在轮换池**（Patch
36.2.0 起移除；`bg_pool_minions.json` 无它们的 `IS_BACON_POOL_MINION`
tag），因此对**当前环境训练**无直接收益；但差分 harness 回放的是
34.x-35.x 历史对局，这些卡的缺失仍被算作 `no_script` 归因。本批的
价值 = 历史官方战斗复现的机制一致率（Lead 指定的「官方机制一致率」
指标），并顺带让数据中的旧卡可被随机/继承类效果正确使用。

实现要点（通用）
═══════════════════════════════════════════════════════════════════════
- 数值一律 `CardDef.num(i)`（金色独立 CardDef 自动体现倍率）;
  无模板参数的（Crab 尺寸 / 触发次数）用文本字面量并在 docstring 记
  wiki 引注。
- 金色行为分支读**金色 CardDef 文本**（"two"/"twice"/无
  "until next turn"），以 `source.is_golden` 判定；金色脚本类单独注册，
  但行为数据驱动者只继承基础类。
- 只经公开动作/事件：`Summon` / `Buff` / `GainKeyword` /
  `execute_immediate_attack`（完整单次攻击语义）/ 引擎事件
  （`before_attack` / `minion_bought` / `spell_bought` / `spell_resolved`
  / `turn_start`）。`_opponent_of` / `_random_enemy_target` 为本地
  复现 RULES §4.4 目标规则（不触引擎私有方法）。

Test: `hsrl2/tests/test_batch_37x_missing1.py`（真实 `game.summon` /
`game.run_combat` / `game.play_minion` / 真实事件广播 / 金色独立 CardDef /
负对照 + 正对照；每个行为方法都有「钩子换 no-op 后必失败」的断言）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2.actions import Buff, GainKeyword, Summon
from hsrl2.combat import execute_immediate_attack
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.events import (
    BEFORE_ATTACK,
    MINION_BOUGHT,
    SPELL_BOUGHT,
    SPELL_RESOLVED,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.scripts.spells import _expire_at_next_turn
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Zone

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 卡 id（CardDB 按名核实；token 无数据链字段者以 wiki Related cards 为准）──
SURF_N_SURF = "BG27_004"            # 1/1 T1 Naga/Beast, spellcraft_id=105949
SURF_N_SURF_G = "BG27_004_G"        # 2/2 金色, spellcraft_id=105950
CRAB_MOUNT = "BG27_004t"            # 法术 "Crab Mount" (3/2 Crab)
CRAB_MOUNT_G = "BG27_004_Gt"        # 金色法术 "Crab Mount" (6/4 Crab)
CRAB = "BG27_004t2"                 # 3/2 Crab token
CRAB_G = "BG27_004_Gt2"             # 6/4 Crab token（金色法术）
TWILIGHT_HATCHLING = "BG34_630"     # 1/1 T1 Dragon, deathrattle
TWILIGHT_HATCHLING_G = "BG34_630_G"  # 2/2 金色（亡语召唤两只）
TWILIGHT_WHELP = "BG34_630t"        # 3/3 Whelp token
RING_BEARER = "BG34_921"            # 5/10 T6
RING_BEARER_G = "BG34_921_G"        # 10/20 金色
SHINY_RING = "BG28_168"             # 池法术 T3 "Give your minions +1/+1"
GLUTTONOUS_TROGG = "BG35_801"       # 2/3 T1
GLUTTONOUS_TROGG_G = "BG35_801_G"   # 4/6 金色
PUFFERQUIL = "BG25_039"             # 2/6 T3 Naga/Quilboar
PUFFERQUIL_G = "BG25_039_G"         # 4/12 金色

#: 法术 → 召唤 Crab token（CardDefs 无数据链字段; wiki Related cards 权威:
#: BG27_004t "Crab Mount" → BG27_004t2 Crab 3/2；金色法术 BG27_004_Gt
#: 文本 6/4 → BG27_004_Gt2，两 token 的 name/属性经 CardDB 核实）
_CRAB_BY_SPELL = {CRAB_MOUNT: CRAB, CRAB_MOUNT_G: CRAB_G}


# ══════════════════════════════════════════════════════════════════════
# 公共工具
# ══════════════════════════════════════════════════════════════════════


def _num(game: "Game", card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return int(value)


def _hero_of(entity) -> Optional["Hero"]:
    return getattr(entity, "controller", None)


def _opponent_of(game: "Game", hero: "Hero") -> Optional["Hero"]:
    """当前战斗对手（`run_combat` 暴露 `game._active_combat`）。

    招募期无战斗对 → None（"立即攻击"类效果在招募期无目标可打）。
    """
    ac = getattr(game, "_active_combat", None)
    if ac is None:
        return None
    a, b = ac
    return b if a is hero else (a if b is hero else None)


def _random_enemy_target(game: "Game",
                         opponent: "Hero") -> Optional[Minion]:
    """敌方攻击目标（RULES §4.4: 随机、嘲讽强制优先、潜行不可击）。"""
    living = [m for m in opponent.living_minions()
              if not m.has(GameTag.STEALTH)]
    if not living:
        return None
    taunts = [m for m in living if m.taunt]
    return game.rng.choice(taunts or living, label="force_attack_target")


def _summon_token(game: "Game", hero: "Hero", card_id: str,
                  position: Optional[int],
                  atk: Optional[int] = None,
                  health: Optional[int] = None) -> Optional[Minion]:
    """召唤 token（数据驱动属性: 与 CardDef 基值不符时补差 buff）。

    满场 → `game.summon` 返回 False（MINION_OVERFLOW），本次召唤落空。
    """
    token = game.create_minion(card_id, controller=hero)
    if token is None:
        return None
    if atk is not None and health is not None:
        delta_atk = int(atk) - int(token.atk)
        delta_health = int(health) - int(token.max_health)
        if delta_atk > 0 or delta_health > 0:
            token.add_buff(BuffEnchant(atk=max(0, delta_atk),
                                       health=max(0, delta_health)))
    if not game.summon(hero, token, position):
        return None
    return token


def _attack_immediately(game: "Game", hero: "Hero",
                        attacker: Optional[Minion]) -> None:
    """召唤物立即攻击战斗对手（完整单次攻击语义；招募期/无目标落空）。"""
    if attacker is None or attacker.dead or attacker.zone != Zone.PLAY:
        return
    if attacker.atk <= 0:
        return
    opponent = _opponent_of(game, hero)
    if opponent is None:
        return
    defender = _random_enemy_target(game, opponent)
    if defender is None:
        return
    execute_immediate_attack(game, attacker, defender)


# ══════════════════════════════════════════════════════════════════════
# BG34_630 Twilight Hatchling — 亡语: 召唤 Whelp 并立即攻击
# ══════════════════════════════════════════════════════════════════════


class TwilightHatchlingScript:
    """
    Natural language: <b>Deathrattle:</b> Summon a {0}/{1} Whelp that
    attacks immediately.

    依据: wiki.gg/Battlegrounds/Twilight_Hatchling?oldid=907172 ——
    普通 1/1 T1 Dragon, DEATHRATTLE=1, TAG_SCRIPT_DATA_NUM_1=3 /
    NUM_2=3（Whelp 尺寸 3/3）; Related cards: Twilight Whelp
    （`BG34_630t` 3/3, dbfId 126748）。金色 BG34_630_G（2/2）文本为
    "Summon **two** {0}/{1} Whelps"（NUM 仍为 3/3——即两只 3/3 非金
    Whelp，而非 6/6 金色 token；金色 token BG34_630_Gt 6/6 属三连
    体系，本卡文本不引用）。

    Formal spec:
      1. deathrattle（死亡处理路径；source 已离场，以 controller 为锚点）:
         召唤数 = 1（基础）/ 2（金色，读金色文本 "two"），每只 =
         Twilight Whelp token `BG34_630t`，尺寸 = 本卡 CardDef
         num(0)/num(1)（=3/3；与 token 基值不符时补差 buff——数据漂移免疫）
      2. 召唤位置 = ctx["position"]（引擎死亡流程给出的死者让出的板位；
         缺失 → 最右）；满场 → `game.summon` 返回 False，该只落空
         （官方满场亡语召唤物丢弃）
      3. "attacks immediately" = 召唤成功后立即对战斗对手发起一次完整
         攻击（`combat.execute_immediate_attack`——同时双向伤害/圣盾/
         剧毒/AFTER_ATTACK 与轮转攻击同一路径，SOP §10）; 目标 =
         嘲讽优先、其余随机、潜行不可击（RULES §4.4）; 0 攻不攻击;
         招募期死亡（无 `_active_combat`）不攻击
      4. 召唤与攻击**直接执行**（死亡处理路径内禁 Action 入队——
         batch_avenge_misc 直接执行模式）; 死亡先于召唤的顺序由引擎保证

    Test: test_batch_37x_missing1.py — 真实 `game.run_combat`: 本卡死亡
    后板上出现 3/3 Whelp 且敌方随机随从受到 3 点伤害 / 金色召唤两只 /
    满场不召唤不崩溃 / 招募期死亡不召唤攻击 / 无战斗对落空

    Params: {0}=3 {1}=3（BG34_630 num(0)/num(1)；金色 _G 同值）
    """

    whelps = 1
    token_id = TWILIGHT_WHELP

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = _hero_of(source)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        if d is None:
            raise GameStateError(
                f"TwilightHatchling: missing CardDef {source.card_id!r}")
        count = (TwilightHatchlingGoldenScript.whelps if source.is_golden
                 else TwilightHatchlingScript.whelps)
        position = (ctx or {}).get("position")
        whelp_def = game.db.get(TwilightHatchlingScript.token_id)
        if whelp_def is None:
            raise GameStateError(
                f"TwilightHatchling: missing token "
                f"{TwilightHatchlingScript.token_id!r}")
        whelp_atk = d.num(0) if d.num(0) is not None else whelp_def.atk
        whelp_hp = d.num(1) if d.num(1) is not None else whelp_def.health
        for _ in range(count):
            whelp = _summon_token(game, hero, TwilightHatchlingScript.token_id,
                                  position, atk=whelp_atk, health=whelp_hp)
            _attack_immediately(game, hero, whelp)
        return None


class TwilightHatchlingGoldenScript(TwilightHatchlingScript):
    """
    Natural language: <b>Deathrattle:</b> Summon two {0}/{1} Whelps that
    attack immediately.

    Formal spec: 同基础版，召唤数 = 2（金色文本 "two" 字面量；尺寸仍取
    金色 CardDef num(0)/num(1) = 3/3）。两只各自独立立即攻击。

    Test: test_batch_37x_missing1.py — 金色亡语召唤两只 3/3 且两只都
    立即攻击（敌方两处伤害合计 ≥2×3 或敌方随从死亡）

    Params: {0}=3 {1}=3（BG34_630_G num(0)/num(1)）
    """

    whelps = 2


# ══════════════════════════════════════════════════════════════════════
# BG34_921 Ring Bearer — 友方攻击时施放 Shiny Ring
# ══════════════════════════════════════════════════════════════════════


class RingBearerScript:
    """
    Natural language: Whenever a friendly minion attacks, cast Shiny Ring.

    依据: CardDefs 37.0 `BG34_921`（5/10 T6, TRIGGER_VISUAL=1,
    BACON_EVOLUTION_CARD_ID=109230 → Shiny Ring dbf, TAG_SCRIPT_DATA_NUM_1=1）;
    金色 `BG34_921_G`（10/20）文本 = "Whenever a friendly minion attacks,
    cast Shiny Ring **twice**"（行为分支读金色文本——SOP §3"金色分支"
    纪律）。wiki.gg/Battlegrounds/Ring_Bearer?oldid=904312 为 35.2.2
    旧读法（金色 "Whenever 2 friendly minions attack ... twice"），与
    37.0 CardDefs 文本不同——**以 CardDefs 为权威**（项目权威序）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source，离场自动注销）:
         `before_attack`（攻击宣告时点、伤害结算前——引擎在
         `atk_power = attacker.atk` 快照**之前** fire，故本次攻击即吃到
         Shiny Ring 增益，符合官方"触发先于伤害"）
      2. 条件: `attacker.controller is 本人`（"friendly minion"; 对手
         攻击不触发）
      3. 每次触发 = **完整施放 Shiny Ring 一次**（卡面指名法术
         `BG28_168`，T3 池法术 "Give your minions +{0}/+{1}"，
         num=1/1）: 对本人棋盘全部存活随从（"your minions" 无 "other"，
         含攻方自身与 Ring Bearer）各 +num(0)/+num(1)。基础 1 次、
         金色 2 次（"twice"）——与 Runic Arcanist（同 "Cast Shiny
         Ring" 措辞）/**Firescale Hoarder** 先例同口径：效果直施，
         不经 `play_spell`（不耗手牌/不占池/不计 TAVERN_SPELLS_CAST）
      4. 战斗内 plain buff → 战后快照回滚（RULES §3.5；官方战斗内
         施放的 Shiny Ring 非常驻）
      5. 攻击来源不限一次攻击: 每次 `before_attack`（含风怒的第二次
         攻击、招募期/效果直攻的 `execute_immediate_attack`）各触发一次

    Test: test_batch_37x_missing1.py — 真实 `game.run_combat`: 友方攻击
    时全板 +1/+1 且该次攻击伤害含增益 / 对手攻击不触发 / 金色每次
    +2/+2 / 自身攻击也触发 / 战后回滚

    Params: 法术侧 {0}=1 {1}=1（BG28_168 CardDef 权威）; "twice" = 金色
           文本字面量（基础 1 次 / 金色 2 次）
    """

    casts = 1

    @staticmethod
    def on_summon(source, game, ctx):
        hero = _hero_of(source)
        if hero is None:
            return None

        def on_attack(g, attacker=None, defender=None, **kw):
            if attacker is None or attacker.controller is not hero:
                return
            ring = g.db.get(SHINY_RING)
            if ring is None:
                return
            atk_gain = ring.num(0)
            hp_gain = ring.num(1)
            if atk_gain is None or hp_gain is None:
                return
            times = (RingBearerGoldenScript.casts if source.is_golden
                     else RingBearerScript.casts)
            for _ in range(times):
                for m in list(hero.board):
                    if not m.dead:
                        g.run_actions(Buff(m, atk=atk_gain, health=hp_gain))

        game.events.register(Listener(
            event=BEFORE_ATTACK, owner=source, callback=on_attack))
        return None


class RingBearerGoldenScript(RingBearerScript):
    """
    Natural language: Whenever a friendly minion attacks, cast Shiny Ring
    twice.

    Formal spec: 同基础版，每次触发施放 2 次（金色文本 "twice" 字面量）
    ——两次独立结算，全板各 +2×num。

    Test: test_batch_37x_missing1.py — 金色友方攻击后全板 +2/+2

    Params: 同基础版；"twice" = 金色文本字面量（casts=2）
    """

    casts = 2


# ══════════════════════════════════════════════════════════════════════
# BG35_801 Gluttonous Trogg — 买 4 张牌后 +4/+4（一次性）
# ══════════════════════════════════════════════════════════════════════


class GluttonousTroggScript:
    """
    Natural language: Once you buy 4 cards, gain +{1}/+{2}.
    <i>({0} left!)</i>

    依据: CardDefs 37.0 BG35_801（2/3 T1, TRIGGER_VISUAL=1,
    BACON_TRIGGER_XY=1, NUM_1=4 / NUM_2=4 / NUM_3=4）；金色 (_G 4/6)
    NUM_2=NUM_3=8。卡面 "@..." 第二段为触发后的 **"(Done!)"** 状态
    ——"Once" = **一次性**（不是每 4 张重复触发）。
    wiki.gg/Battlegrounds/Gluttonous_Trogg?oldid=904427（35.2.0 Added）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）:
         - `minion_bought`（minion=；随从购买: 含免费购买/三连前实体）
         - `spell_bought`（spell=, hero=；酒馆法术购买）
         只统计 `controller is 本人` 的购买（对手购买不计）;
         监听从**本随从入场后**开始计数（入场前已买的不计——官方
         计数器随随从存在而存在）
      2. 计数达 num(0)=4: 立即对 source `Buff(num(1), num(2))`
         （基础 +4/+4、金色 +8/+8——金色 CardDef 自然体现），置
         done 标记（"(Done!)"）;
      3. "buy a card" 口径: 随从 + 酒馆法术都算（两种买事件都监听）;
         `Get`/Discover/生成卡不计数（非购买）；
      4. 多只 Trogg 各自独立计数（每只各自的监听器/状态——官方每只
         分别计数）；source 在计数过程中离场（卖出/死亡）则监听器自动
         注销且不再补触发（Buff 目标必须仍在场）
      5. 触发后监听器保留但 done 守卫使其不再计数（幂等）
      6. **B 类迁移（2026-10-18）**: 官方 `TAG_SCRIPT_DATA_NUM_1` 注入
         = 当前购买进度（1..4；回放窗口前基线）。注入 < 阈值 → 以该
         进度为起点继续计数；注入 ≥ 阈值 → 视为已 "(Done!)"（不重放
         Buff，官方打印属性已含该增益）；无注入 → 从 0 计数（旧行为
         逐位不变）。

    Test: test_batch_37x_missing1.py — 真实 `buy_from_tavern` 买 3 随从
    不触发 / 第 4 张（随从或法术）触发 +4/+4 / 之后继续买不再触发 /
    金色 +8/+8 / 对手购买不计数 / 入场前的购买不计数；
    test_dynamic_state_migration.py — NUM_1 注入 3 → 再买 1 张即触发。

    Params: {0}=4 {1}=4 {2}=4（BG35_801；金色 {0}=4 {1}=8 {2}=8）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        hero = _hero_of(source)
        if hero is None:
            return None
        threshold = _num(game, source.card_id, 0)
        injected = (source.get_script_data(1)
                    if source.is_script_data_injected(1) else None)
        if injected is None:
            state = {"count": 0, "done": False}
        else:
            done = int(injected) >= threshold
            state = {"count": int(injected), "done": done}

        def _tick(g: "Game") -> None:
            if state["done"]:
                return
            state["count"] += 1
            if state["count"] < threshold:
                return
            state["done"] = True
            if source.dead or source.zone != Zone.PLAY:
                return
            d = g.db.get(source.card_id)
            if d is None:
                return
            atk_gain = d.num(1)
            hp_gain = d.num(2)
            if atk_gain is None or hp_gain is None:
                return
            g.run_actions(Buff(source, atk=atk_gain, health=hp_gain))

        def on_minion_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not hero:
                return
            _tick(g)

        def on_spell_bought(g, spell=None, **kw):
            # 引擎签名: fire(..., spell=entity, hero=hero)——`hero` 走 **kw
            # 捕获（避免与闭包 hero 混淆）
            buyer = kw.get("hero")
            if buyer is not hero:
                return
            _tick(g)

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=source, callback=on_minion_bought))
        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=source, callback=on_spell_bought))
        return None


class GluttonousTroggGoldenScript(GluttonousTroggScript):
    """
    Natural language: Once you buy 4 cards, gain +{1}/+{2}. <i>({0} left!)</i>

    Formal spec: 同基础版，增益值由金色 CardDef num(1)/num(2)=8/8 自然
    体现（阈值 num(0) 仍为 4）。行为无差异（无需额外分支）。

    Test: test_batch_37x_missing1.py — 金色触发 +8/+8

    Params: {0}=4 {1}=8 {2}=8（BG35_801_G）
    """


# ══════════════════════════════════════════════════════════════════════
# BG27_004 Surf n' Surf（Spellcraft 随从）+ BG27_004t/Gt Crab Mount（法术）
# ══════════════════════════════════════════════════════════════════════


class SurfNSurfScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Give a minion "<b>Deathrattle:</b>
    Summon a 3/2 Crab" until next turn.

    依据: CardDefs 37.0 BG27_004（1/1 T1 Naga/Beast，spellcraft_id=105949
    → 法术 BG27_004t；金色 BG27_004_G 2/2，spellcraft_id=105950 → 金色
    法术 BG27_004_Gt）。wiki.gg/Battlegrounds/Surf_n%27_Surf?oldid=803508
    （Related cards: Crab Mount / Crab 3/2; 金色文本 6/4 Crab）。

    Formal spec:
      1. Spellcraft 随从的**打出/召唤即时授予**（RULES §6.13）:
         `on_summon` 自举 SPELLCRAFT tag + `grant_spellcraft_spell`
         ——打出当回合即获得一张法术（每回合开始 `generate_for_hero`
         另发一张由引擎负责）；金色随从 → 金色法术（`spellcraft.py`
         经 spellcraft_id 数据链自动选择 BG27_004_Gt）
      2. 法术效果本体见 `CrabMountSpellScript`（本卡自身无其他钩子；
         卡面引号内文本属于被授予法术，不是本随从的亡语——数据
         `DEATHRATTLE=1` tag 为引号文本残留，非原生亡语，不实现
         deathrattle 钩子）

    Test: test_batch_37x_missing1.py — 真实 `play_minion` 后手牌出现
    BG27_004t 且带 SPELLCRAFT tag / 金色随从给出 BG27_004_Gt / 下回合
    开始再生成一张（真实 `_begin_recruit_for`）

    Params: 无模板参数（法术数值见 CrabMountSpellScript）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.SPELLCRAFT, True)
        grant_spellcraft_spell(source, game)
        return None


class SurfNSurfGoldenScript(SurfNSurfScript):
    """
    Natural language: [x]<b>Spellcraft:</b> Give a minion "<b>Deathrattle:</b>
    Summon a 6/4 Crab" until next turn.

    Formal spec: 同基础版；金色随从的 spellcraft_id=105950 指向金色法术
    BG27_004_Gt（6/4 Crab 文本），由 `spellcraft.py` 数据链自动选择。

    Test: test_batch_37x_missing1.py — 金色随从给出手牌 BG27_004_Gt

    Params: 无模板参数（金色法术文本字面量 6/4，见 CrabMountGoldenScript）
    """


def _set_crab_deathrattle(game: "Game", hero: "Hero", target: Minion,
                          crab_id: str) -> None:
    """给 target 附加「亡语: 召唤 crab_id」直到下回合（可叠加）。

    叠加协议（同一目标多次 Crab Mount）: 目标实体上维护
    `_crab_mounts: list[crab_id]` + 一份"施放前覆盖"快照; 生效的亡语
    override 每次触发时先跑原生亡语（脚本钩子/既有覆盖），再按当前
    列表逐只召唤。每次施放注册一个 once `turn_start` 过期监听器: 到期
    从列表移除**本次** crab_id，列表清空才恢复原覆盖并清 DEATHRATTLE
    tag（避免两次施放的过期顺序互相覆盖——SOP §16 模式 35 同类问题）。
    """
    grants = getattr(target, "_crab_mounts", None)
    if grants is None:
        saved = dict(target._script_overrides)
        had_deathrattle = target.has(GameTag.DEATHRATTLE)
        target._crab_mount_saved = (saved, had_deathrattle)
        target._crab_mounts = []

        def chained(src, g, ctx):
            result = None
            prev = saved.get("deathrattle")
            if prev is not None:
                result = prev(src, g, ctx) if callable(prev) else prev
            else:
                scripts = getattr(src, "scripts", None)
                fn = getattr(scripts, "deathrattle", None) \
                    if scripts is not None else None
                if fn is not None:
                    result = fn(src, g, ctx)
            actions = []
            if result is not None:
                actions.extend(result if isinstance(result, (list, tuple))
                               else [result])
            position = (ctx or {}).get("position")
            for cid in list(getattr(src, "_crab_mounts", None) or ()):
                actions.append(Summon(hero, cid, position=position))
            return actions or None

        target.set_script_override("deathrattle", chained)
        target.set(GameTag.DEATHRATTLE, True)
    target._crab_mounts.append(crab_id)

    def _expire(g, hero=None, _target=target, _crab=crab_id, **kw):
        crabs = getattr(_target, "_crab_mounts", None)
        if crabs is None:
            return
        if _crab in crabs:
            crabs.remove(_crab)
        if crabs:
            return
        saved, had_deathrattle = _target._crab_mount_saved
        _target._script_overrides.clear()
        _target._script_overrides.update(saved)
        if not had_deathrattle:
            _target.clear(GameTag.DEATHRATTLE)
        for attr in ("_crab_mounts", "_crab_mount_saved"):
            try:
                delattr(_target, attr)
            except AttributeError:
                pass

    game.events.register(Listener(
        event=TURN_START, owner=target, once=True,
        condition=lambda hero=None, _ctrl=hero, **kw: hero is _ctrl,
        callback=_expire))


class CrabMountSpellScript:
    """
    Natural language: [x]Give a minion "<b>Deathrattle:</b> Summon a 3/2
    Crab" until next turn.

    依据: CardDefs 37.0 BG27_004t（法术, card_type=42）；金色
    BG27_004_Gt 文本 6/4 → token BG27_004_Gt2（CardDB 核实 6/4）;
    基础 token BG27_004t2（3/2）。两 token 无数据链字段（wiki
    Related cards 权威 + CardDB 属性核实）。

    Formal spec:
      1. needs_target=True → 引擎 `play_spell` 产生
         PendingChoice(kind="spell_target")；候选默认全体友方存活随从
         （与同措辞 Spellcraft 法术 DeepSea Angler 先例同口径）;
         显式 target 直接生效; target 缺失/离场 → 落空（法术照常消耗）
      2. on_play: 给目标附加「亡语: 召唤 Crab」**直到下回合开始**
         （"until next turn" = 下一个招募阶段开始单 tick，RULES §6.13
         注; 复用 `scripts/spells._expire_at_next_turn` 的时点口径）
      3. 亡语叠加: 多次施放同一目标 = 多条亡语，各自召唤自己的 Crab
         （3/2 基础法术、6/4 金色法术可叠加在同一点）——实现见
         `_set_crab_deathrattle`（列表 + 单份覆盖快照）
      4. 该亡语在**本场战斗内**正常触发（目标战死 → 召唤 Crab，位置 =
         死者让出的板位）; 原生亡语保留并**先**结算（官方 Dark Gift
         附加顺序同口径——引擎 `grant_combat_deathrattle` 链式语义）
      5. 过期时恢复原生覆盖/DEATHRATTLE tag（若原本没有才清除）；
         目标在过期前离场 → 监听器随实体注销（无需恢复）

    Test: test_batch_37x_missing1.py — 真实 `game.cast_spell_effect` /
    `play_spell`: 目标得到 DEATHRATTLE 且战斗内死亡召唤 3/2 Crab /
    金色法术召唤 6/4 Crab / 下回合开始移除（`_begin_recruit_for`
    真实驱动）/ 原生亡语保留并先结算 / 无目标落空 / 满场召唤落空

    Params: 无模板参数（Crab 尺寸为文本字面量，token CardDef 权威）
    """

    crab_id = CRAB
    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        hero = _hero_of(source)
        if hero is None or not isinstance(target, Minion):
            return None
        if target.dead or target.zone != Zone.PLAY \
                or target.controller is not hero:
            return None
        crab_id = _CRAB_BY_SPELL.get(source.card_id)
        if crab_id is None:
            raise GameStateError(
                f"CrabMount: no crab token mapped for {source.card_id!r}")
        _set_crab_deathrattle(game, hero, target, crab_id)
        return None


class CrabMountGoldenScript(CrabMountSpellScript):
    """
    Natural language: [x]Give a minion "<b>Deathrattle:</b> Summon a 6/4
    Crab" until next turn.

    Formal spec: 同基础版，Crab token = BG27_004_Gt2（6/4，CardDB 核实；
    金色法术文本字面量 6/4）。金色法术由金色 Surf n' Surf 的
    spellcraft_id=105950 生成。

    Test: test_batch_37x_missing1.py — 金色法术死亡召唤 6/4 Crab

    Params: 无模板参数（6/4 为金色法术文本字面量）
    """

    crab_id = CRAB_G


# ══════════════════════════════════════════════════════════════════════
# BG25_039 Pufferquil — 法术以本随从为目标 → 获得 Venomous
# ══════════════════════════════════════════════════════════════════════


class PufferquilScript:
    """
    Natural language: Whenever a spell is cast on this, gain <b>Venomous</b>
    until next turn.

    依据: CardDefs 37.0 BG25_039（2/6 T3 Naga/Quilboar, TRIGGER_VISUAL=1，
    无模板参数）；金色 BG25_039_G（4/12）文本 = "Whenever a spell is cast
    on this, gain <b>Venomous</b>."（**无 "until next turn"** —— 金色
    行为分支读金色文本，SOP §3 金色分支纪律）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 引擎
         `spell_resolved(spell=, target=, cast_no=)`——真实施放结算点
         （手牌 `play_spell` 与效果直施 `cast_spell_effect` 两条路径
         都 fire；每 cast 一次一份，含双施）
      2. 条件 `target is source`（法术以本随从为目标）；敌我双方施放
         都算（文本无 "your" 限定）; 目标离场后监听器自动注销
      3. 效果: `GainKeyword(source, VENOMOUS)`（走引擎动作: 广播
         keyword_gained / 战斗内毒液消耗语义一致）
      4. 基础版: "until next turn" = 目标控制者下一个招募阶段开始单 tick
         移除（`_expire_at_next_turn` 的 keywords 恢复口径——施放前
         已持有 Venomous 则过期时**不**移除，避免误删原生毒液）
      5. 金色版: **永久**获得（金色文本无 "until next turn"），注册
         同一监听但不过期（`temporary=False` 分支）

    Test: test_batch_37x_missing1.py — 真实 `play_spell` 定向法术命中后
    获得 VENOMOUS / 下一回合开始移除 / 施放前已有 Venomous 时过期后
    保留 / 非本随从目标不触发 / 金色永久（跨回合保留）

    Params: 无模板参数（"until next turn" 为文本字面量）
    """

    temporary = True

    @staticmethod
    def on_summon(source, game, ctx):
        hero = _hero_of(source)
        if hero is None:
            return None

        def on_spell_resolved(g, spell=None, target=None, cast_no=None,
                             **kw):
            if target is not source or source.dead \
                    or source.zone != Zone.PLAY:
                return
            had_venomous = source.has(GameTag.VENOMOUS)
            g.run_actions(GainKeyword(source, GameTag.VENOMOUS))
            temporary = (PufferquilGoldenScript.temporary
                         if source.is_golden
                         else PufferquilScript.temporary)
            if temporary:
                _expire_at_next_turn(g, spell, source,
                                     keywords={GameTag.VENOMOUS:
                                               had_venomous})

        game.events.register(Listener(
            event=SPELL_RESOLVED, owner=source,
            callback=on_spell_resolved))
        return None


class PufferquilGoldenScript(PufferquilScript):
    """
    Natural language: Whenever a spell is cast on this, gain <b>Venomous</b>.

    Formal spec: 同基础版，但**永久**获得 Venomous（金色文本无
    "until next turn"），不注册过期监听。

    Test: test_batch_37x_missing1.py — 金色命中后跨回合仍带 VENOMOUS

    Params: 无模板参数
    """

    temporary = False


# ══════════════════════════════════════════════════════════════════════
# DEFERRED（不注册 REGISTRY）
# ══════════════════════════════════════════════════════════════════════


class MoonsteelJuggernautScript:
    """
    Natural language: [x]At the end of your turn, get two {1}/{1}
    <b>Magnetic</b> Satellites and improve this.

    依据（已查）: CardDefs 37.0 BG31_171（8/8 T6 Mech；NUM_1=0 计数基值、
    NUM_2=6 卫星尺寸；金色 _G 16/16、NUM_2=12）；Satellite token
    BG31_171t（6/6 Magnetic）/ BG31_171_Gt（12/12）经 CardDB 核实；
    wiki.gg/Battlegrounds/Moonsteel_Juggernaut?oldid=904650（35.4.2 起
    8/8 + two 6/6；Related cards: Satellite）。**"improve this" 的增量
    数值无权威**: CardDefs 没有该增量参数（NUM_1 是计数、NUM_2 是当前
    尺寸）; wiki 页面无 Notes 说明增量; 官方补丁说明只列基础值变化;
    社区 bug 报告（us.forums.blizzard.com 138805, 2024-12-03）的实测
    样例只覆盖旧 3/3 时代（3/3 → 6/6 → 9/9，暗示 +3/+3），但当前
    6/6 时代是否仍为 +3/+3 无证据。按 SOP §6b 第 4 步（确实查无证据 →
    DEFERRED 撤注册，宁缺毋错）处理，等待官方/实测信源。

    Status: DEFERRED — requires "improve this" 增量数值的权威来源
    Dependency: CardDefs/patch notes/实测给出每次触发后的 Satellite
                尺寸增量（候选读法: 固定 +3/+3、按当前尺寸翻倍、
                或其他）; 在此之前不注册（禁止瞎实现）。

    Test: test_batch_37x_missing1.py — 断言 BG31_171 未注册（DEFERRED
    台账守卫；结构性测试）
    """


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册 11 张（10 张 CORRECT + 0 DEFERRED 注册）: 5 张主卡 + 1 张
    替换卡及其金色/法术变体。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        # Surf n' Surf（Spellcraft 随从）+ Crab Mount（法术）
        (SURF_N_SURF, SurfNSurfScript),
        (SURF_N_SURF_G, SurfNSurfGoldenScript),
        (CRAB_MOUNT, CrabMountSpellScript),
        (CRAB_MOUNT_G, CrabMountGoldenScript),
        # Twilight Hatchling
        (TWILIGHT_HATCHLING, TwilightHatchlingScript),
        (TWILIGHT_HATCHLING_G, TwilightHatchlingGoldenScript),
        # Ring Bearer
        (RING_BEARER, RingBearerScript),
        (RING_BEARER_G, RingBearerGoldenScript),
        # Gluttonous Trogg
        (GLUTTONOUS_TROGG, GluttonousTroggScript),
        (GLUTTONOUS_TROGG_G, GluttonousTroggGoldenScript),
        # Pufferquil
        (PUFFERQUIL, PufferquilScript),
        (PUFFERQUIL_G, PufferquilGoldenScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
