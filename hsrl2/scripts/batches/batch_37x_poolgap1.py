"""批次 37x_poolgap1 — 37.0 当前轮换池内「有效果但无脚本」的 3 张卡。

背景
═══════════════════════════════════════════════════════════════════════
`tools/audit_card_registry_v2.py --strict` 的 pool_minion 门禁缺口
（数据升级 37.0.0 后新增池内随从尚无脚本）共 53 张。本批补其中 3 张
**战斗/招募均有真实收益且语义无歧义**的：

  BG36_849 Heroic Broodmother（T6 7/7 Dragon, 池内）
      Rally: Gain Divine Shield. Start of Combat: Attack immediately.
      （金色 _G 14/14 文本 "Attack immediately **twice**"）
  BG34_403 Eternal Tycoon（T5 4/8 Undead, 池内）
      Avenge (5): Summon an Eternal Knight. It attacks immediately.
      （金色 _G 8/16 文本 "Summon a **Golden** Eternal Knight"；
       token = BG25_008 / 金色 BG25_008_G，均已注册）
  BG31_812 Ichoron the Protector（T4 3/1 Elemental, 池内）
      Divine Shield. Whenever you play an Elemental, give it Divine
      Shield until next turn.（金色 _G 6/2 文本**无** "until next turn"
      → 永久圣盾）

实现要点
═══════════════════════════════════════════════════════════════════════
- "Attack immediately" 走 `combat.execute_immediate_attack`（完整单次
  攻击语义: 同时双向伤害/圣盾/剧毒/AFTER_ATTACK，SOP §10 原语）；
  目标选择本地复现 RULES §4.4（随机、嘲讽优先、潜行不可击）；
  0 攻/已死/无战斗对（`game._active_combat`）→ 该次攻击落空。
- Avenge 阈值由引擎从 `CardDef.avenge_target`（=5）读取并计数，脚本
  只实现 `avenge` 效果体；引擎已保证**仅战斗内**计数（RULES §6.11）。
- "until next turn" 复用 `scripts/spells._expire_at_next_turn` 的
  "下一招募阶段开始单 tick" 口径（与 Spellcraft 族一致）；施放前已
  持有 Divine Shield 时过期不误删（had_before 记录）。
- 金色行为分支读**金色 CardDef 文本**（twice / Golden Knight /
  无 "until next turn"），以 `source.is_golden` 判定。

Test: `hsrl2/tests/test_batch_37x_poolgap1.py`（真实 `run_combat` /
`execute_immediate_attack` / 真实 Avenge 计数路径 / 真实 `play_minion` /
`_begin_recruit_for` 回合开始；正对照 + 负对照）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2.actions import GainKeyword
from hsrl2.combat import execute_immediate_attack
from hsrl2.events import CARD_PLAYED, Listener
from hsrl2.minion import Minion
from hsrl2.scripts.spells import _expire_at_next_turn
from hsrl2.tags import GameTag, Race, Zone

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 卡 id（CardDB 按名核实）──
HEROIC_BROODMOTHER = "BG36_849"
HEROIC_BROODMOTHER_G = "BG36_849_G"
ETERNAL_TYCOON = "BG34_403"
ETERNAL_TYCOON_G = "BG34_403_G"
ETERNAL_KNIGHT = "BG25_008"        # 池内 T2（已注册: 动态属性）
ICHORON = "BG31_812"
ICHORON_G = "BG31_812_G"


# ══════════════════════════════════════════════════════════════════════
# 公共工具（与 batch_37x_missing1 同口径的本地实现，避免跨批 import）
# ══════════════════════════════════════════════════════════════════════


def _opponent_of(game: "Game", hero: "Hero") -> Optional["Hero"]:
    ac = getattr(game, "_active_combat", None)
    if ac is None:
        return None
    a, b = ac
    return b if a is hero else (a if b is hero else None)


def _random_enemy_target(game: "Game",
                         opponent: "Hero") -> Optional[Minion]:
    living = [m for m in opponent.living_minions()
              if not m.has(GameTag.STEALTH)]
    if not living:
        return None
    taunts = [m for m in living if m.taunt]
    return game.rng.choice(taunts or living, label="force_attack_target")


def _force_attack(game: "Game", hero: "Hero", attacker: Minion) -> None:
    """attacker 立即对战斗对手发起一次完整攻击（无目标/0 攻落空）。"""
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
# BG36_849 Heroic Broodmother
# ══════════════════════════════════════════════════════════════════════


class HeroicBroodmotherScript:
    """
    Natural language: <b>Rally:</b> Gain <b>Divine Shield</b>.
    <b>Start of Combat:</b> Attack immediately.

    依据: CardDefs 37.0 BG36_849（7/7 T6 Dragon, Rally + START_OF_COMBAT
    关键词、无模板参数）；金色 _G（14/14）文本 "Start of Combat: Attack
    immediately **twice**"（行为分支读金色文本——SOP §3）。

    Formal spec:
      1. rally（引擎在攻击宣告时、伤害前触发; ctx["target"] = 防御者）:
         `GainKeyword(source, DIVINE_SHIELD)`——圣盾在本次攻击的伤害
         结算前生效（官方 Rally 时点: 攻击宣告后、伤害前，RULES §6.16）
      2. start_of_combat: source 立即对战斗对手发起一次完整攻击
         （`combat.execute_immediate_attack`；目标按 RULES §4.4 随机/
         嘲讽优先/潜行不可击）; 金色 = **两次**（"twice" 文本字面量）:
         逐次结算，第一次攻击后 source 已死/被移除则跳过第二次
      3. SoC 由 `CombatScheduler.run` 在 `_active_combat` 曝光之后调用
         （combat.py L79-L81）→ 对手可定位；招募期无 SoC 钩子
      4. 0 攻随从（被削减后）不发起攻击（C9 口径）；对手无存活随从 →
         该次攻击落空（不崩溃）

    Test: test_batch_37x_poolgap1.py — 真实 `run_combat`: SoC 后 Broodmother
    先攻击（敌方随从掉血）、Rally 使其在攻击时持圣盾 / 金色攻击两次 /
    对手空板落空不崩溃 / 招募期不触发

    Params: 无模板参数（"twice" 为金色文本字面量）
    """

    soc_attacks = 1

    @staticmethod
    def rally(source, game, ctx):
        if source.dead:
            return None
        if source.has(GameTag.DIVINE_SHIELD):
            return None
        return GainKeyword(source, GameTag.DIVINE_SHIELD)

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        times = (HeroicBroodmotherGoldenScript.soc_attacks
                 if source.is_golden else HeroicBroodmotherScript.soc_attacks)
        for _ in range(times):
            if source.dead or source.zone != Zone.PLAY:
                break
            _force_attack(game, hero, source)
        return None


class HeroicBroodmotherGoldenScript(HeroicBroodmotherScript):
    """
    Natural language: <b>Rally:</b> Gain <b>Divine Shield</b>.
    <b>Start of Combat:</b> Attack immediately twice.

    Formal spec: 同基础版，SoC 立即攻击 **两次**（金色文本 "twice"
    字面量；Rally 仍为单次 Gain Divine Shield）。

    Test: test_batch_37x_poolgap1.py — 金色 SoC 打出两次攻击（敌方两处
    伤害或两个随从死亡）

    Params: 无模板参数（"twice" 为金色文本字面量; soc_attacks=2）
    """

    soc_attacks = 2


# ══════════════════════════════════════════════════════════════════════
# BG34_403 Eternal Tycoon
# ══════════════════════════════════════════════════════════════════════


class EternalTycoonScript:
    """
    Natural language: <b>Avenge ({0}):</b> Summon an Eternal Knight.
    It attacks immediately.

    依据: CardDefs 37.0 BG34_403（4/8 T5 Undead; `avenge_target`=5,
    NUM_1=5 = 阈值 {0}）；金色 _G（8/16）文本 "Summon a **Golden**
    Eternal Knight. It attacks immediately"（行为分支读金色文本）。
    token = BG25_008 Eternal Knight（4/2 T2 池内，已注册动态属性脚本）;
    金色 token = BG25_008_G（8/4，同卡家族；create_minion(golden=True)）。

    Formal spec:
      1. avenge（引擎在**战斗内**友方死亡计数达阈值 5 时调用，RULES
         §6.11; 招募期死亡不计数）: 召唤 Eternal Knight（金色
         Tycoon → 金色 Knight，`create_minion(golden=True)`，满场
         `game.summon` 返回 False → 落空）
      2. 召唤成功后该 Knight 立即对战斗对手发起一次完整攻击
         （`execute_immediate_attack`; 目标 RULES §4.4）; Knight 是
         Reborn 前的基础 token，无死亡概率保护——攻击后若战死由其正常
         死亡流程处理（含 Eternal Knight 自身 `deaths_by_card_id`
         记账 → 后续 Knight 动态属性变大，官方机制）
      3. 召唤位置 = 最右（Avenge 钩子 ctx 不携带死者板位——引擎 Avenge
         在死亡流程的 Avenge 步骤调用时死者板位已被其它召唤使用; 官方
         未规定位置，取最右为最保守的确定性选择，docstring 记 AMBIGUOUS
         边界）
      4. 对手无存活随从/无战斗对 → 召唤成功但不攻击（落空不崩溃）

    Test: test_batch_37x_poolgap1.py — 真实 `run_combat` 中 5 次友方死亡
    后召唤 Eternal Knight 并立即攻击 / 金色召唤金色 Knight（8/4）/
    4 次死亡不触发 / 招募期死亡不计数 / 满场召唤落空

    Params: {0}=5（BG34_403 `avenge_target`/NUM_1；金色 _G 同值）
    """

    token_id = ETERNAL_KNIGHT

    @staticmethod
    def avenge(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None or source.dead:
            return None
        golden = bool(source.is_golden)
        token = game.create_minion(EternalTycoonScript.token_id,
                                   controller=hero, golden=golden)
        if token is None:
            return None
        if not game.summon(hero, token):
            return None
        _force_attack(game, hero, token)
        return None


class EternalTycoonGoldenScript(EternalTycoonScript):
    """
    Natural language: [x]<b>Avenge ({0}):</b> Summon a Golden Eternal
    Knight. It attacks immediately.

    Formal spec: 同基础版，召唤体为**金色** Eternal Knight
    （BG25_008_G，8/4; `create_minion(..., golden=True)` 解析独立金色
    CardDef），攻击语义相同。

    Test: test_batch_37x_poolgap1.py — 金色召唤 8/4 金色 Knight

    Params: {0}=5（avenge_target；金色 _G 同值）
    """


# ══════════════════════════════════════════════════════════════════════
# BG31_812 Ichoron the Protector
# ══════════════════════════════════════════════════════════════════════


class IchoronScript:
    """
    Natural language: <b>Divine Shield</b>
    Whenever you play an Elemental, give it <b>Divine Shield</b>
    until next turn.

    依据: CardDefs 37.0 BG31_812（3/1 T4 Elemental, DIVINE_SHIELD 关键词、
    无模板参数）；金色 _G（6/2）文本**无** "until next turn" → 永久圣盾
    （行为分支读金色文本——SOP §3）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 引擎 `card_played`
         （随从打出路径: `play_minion` → summon → `_run_play_effects` →
         `events.fire("card_played", card=minion)`; 打出时实体已在棋盘）
      2. 条件: `card.controller is 本人` 且 `card.has_race(Race.ELEMENTAL)`
         （"you play an Elemental"; 多类型随从含 ELEMENTAL 即算——AC-3
         身份集合语义）; 触发对象 = **被打出的那个 Elemental**（"give
         **it** Divine Shield"）
      3. 效果: 若目标未持圣盾 → `GainKeyword(target, DIVINE_SHIELD)`；
         基础版 "until next turn" = 目标控制者下一招募阶段开始移除
         （`_expire_at_next_turn` 的 keywords 口径; 施放前已持有则不
         误删——如 Ichoron 自身数据自带圣盾）; 金色版**永久**
      4. 对手打出 Elemental 不触发（condition 锁 controller）；非
         Elemental 不触发；Ichoron 自身作为 Elemental 打出同样触发
         （自身已有圣盾 → 无变化，仅记录，不重复施加）

    Test: test_batch_37x_poolgap1.py — 真实 `play_minion` 打出 Elemental
    获得圣盾 / 下一回合开始移除 / 非 Elemental 不触发 / 对手打出不触发 /
    金色永久（跨回合保留）/ 目标施放前已有圣盾过期后保留

    Params: 无模板参数（"until next turn" 为文本字面量）
    """

    temporary = True

    @staticmethod
    def on_summon(source, game, ctx):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_card_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not hero:
                return
            if not card.has_race(Race.ELEMENTAL):
                return
            if card.dead or card.zone != Zone.PLAY:
                return
            had_shield = card.has(GameTag.DIVINE_SHIELD)
            if not had_shield:
                g.run_actions(GainKeyword(card, GameTag.DIVINE_SHIELD))
            temporary = (IchoronGoldenScript.temporary
                         if source.is_golden else IchoronScript.temporary)
            if temporary and not had_shield:
                _expire_at_next_turn(g, None, card,
                                     keywords={GameTag.DIVINE_SHIELD:
                                               had_shield})

        game.events.register(Listener(
            event=CARD_PLAYED, owner=source, callback=on_card_played))
        return None


class IchoronGoldenScript(IchoronScript):
    """
    Natural language: <b>Divine Shield</b>
    Whenever you play an Elemental, give it <b>Divine Shield</b>.

    Formal spec: 同基础版，但**永久**授予（金色文本无 "until next turn"），
    不注册过期监听。

    Test: test_batch_37x_poolgap1.py — 金色: 打出的 Elemental 跨回合仍带
    圣盾

    Params: 无模板参数
    """

    temporary = False


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册 6 张（3 张池内卡 + 各自金色独立卡定义；0 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (HEROIC_BROODMOTHER, HeroicBroodmotherScript),
        (HEROIC_BROODMOTHER_G, HeroicBroodmotherGoldenScript),
        (ETERNAL_TYCOON, EternalTycoonScript),
        (ETERNAL_TYCOON_G, EternalTycoonGoldenScript),
        (ICHORON, IchoronScript),
        (ICHORON_G, IchoronGoldenScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
