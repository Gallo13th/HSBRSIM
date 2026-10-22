"""差分驱动批 3：TOP 缺脚本卡（按 ROI；679 场官方轨迹分歧频次驱动）。

本批**实现 2 张**（语义/原语均明确、低风险），**3 张 DEFERRED 并附证据**：

1. ``BG34_632`` Incubation Researcher — Avenge(3): Get a random Chromadrake
   （金色 2 只）。Chromadrake 卡集复用 `batch_rally2.CHROMADRAKE_IDS`
   （非池 token，5 色；与 Draconic Warden/Hired Mount 同源先例）。
2. ``BG26_502`` Deep Blue Crooner — Spellcraft：Deep Blues（给一个随从
   +{0}/+{1} until next turn；每次施放改善这张随从未来的 Deep Blues）。
   官方 trace 的 ``ScriptDataNum1/2`` = 该随从当前 Deep Blues 数值
   （例：28/28、140/140；金色与普通各自独立，见 71977/bcc2feb5 轨迹）
   → 通过既有 `get_script_data/set_script_data` 通道读写，
   **无需改 harness**（注入通道已覆盖）。

DEFERRED（证据/原语不足，**不硬编码猜测**）：

* ``BG31_171`` Moonsteel Juggernaut — "At the end of your turn, get two
  {1}/{1} Magnetic Satellites and **improve this**."
  证据：官方 trace 中 Moonsteel 的 ``ScriptDataNum1/2`` 与手中 Satellite
  数值相关但**不一致**（例 00cfafe3224325eb: Moonsteel 132/138 vs 手中
  Satellite 342/342、366/366、132/132；0311764c: 102/114 vs 102/102；
  17493f10: 8/12 vs 4/4、8/8），且与 CardDef num(1)=6（金色 12）不符。
  "improve this" 的改善对象（卫星数值/Satellite 数量/自身？）与步长
  无权威定义（wiki Notes 缺失，CardDefs 仅一个参数 6）。需要：
  **官方 patch notes/wiki Notes 或真实 Power.log 的 EoT 数值序列**；
  若确认"每次 +6/+6 到卫星"，则用 `game.rng` 无随机即可实现，
  最小原语 = 无（现有 create_minion+Buff 够）；当前不猜。
* ``BG34_922`` Maelstrom Emergent — "Your spells cast an extra time in
  combat."（金色 "2 extra times"）。
  证据：引擎战斗内直施效果走 `Game.cast_spell_effect`（batch 37x 多卡
  "cast a spell" 直接 run_actions 或 cast_spell_effect），但**没有**
  "本场战斗内所有己方法术额外结算 N 次"的全局倍率/查询钩子；实施需
  在战斗施法结算路径增加 aura 查询（不改脚本可做的部分为 0）。
  最小原语建议：`Game.combat_spell_extra_casts(hero) -> int`
  （读 hero/战场 aura，默认 0），`cast_spell_effect` 按该值重复效果
  结算；影响面 = 战斗内施法（Ring Bearer/Shiny Ring 等）所有路径，
  需 engine-analyst/Lead 决策，**与 engine-analyst 动态属性迁移不冲突**
  （他在 tags/entity 通道，本项在 game.combat 施法结算）。
* ``BG32_234`` Dastardly Drust — "Whenever you get a Pirate, give your
  minions +{0}/+{1}. Give Golden ones +{2}/+{3} instead."
  证据：引擎无"获得（get）"统一事件——购买走 `buy_from_tavern` 直接
  移动已存在实体、Discover/复制走 `grant_card_copy_to_hand`、生成走
  `create_minion+pending_hand_add`，三者无共同广播点（`entity_created`
  只覆盖 create_minion 且不含购买/发现路径）。最小原语建议：
  在 `Hero.add_to_hand`/`pending_hand_add`/`buy_from_tavern` 的统一
  "进入手牌"路径 fire `minion_gained(hero=, minion=)`（一次性事件，
  含 controller），Drust 监听该事件按"Pirate"过滤；影响面 = 手牌
  获取语义（需检查所有既有"get"路径不重复触发）。当前不猜。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from hsrl2 import entity
from hsrl2.events import Listener
from hsrl2.minion import Minion
from hsrl2.scripts.batches.batch_rally2 import CHROMADRAKE_IDS
from hsrl2.scripts.minions import _SpellcraftMinionMixin
from hsrl2.scripts.spells import _expire_at_next_turn
from hsrl2.tags import GameTag, Zone

if TYPE_CHECKING:  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ══════════════════════════════════════════════════════════════════════
# 卡 id
# ══════════════════════════════════════════════════════════════════════

INCUBATION_RESEARCHER = "BG34_632"
INCUBATION_RESEARCHER_G = "BG34_632_G"
DEEP_BLUE_CROONER = "BG26_502"
DEEP_BLUE_CROONER_G = "BG26_502_G"
DEEP_BLUES = "BG26_502t"
DEEP_BLUES_G = "BG26_502_Gt"


def _hero_of(source) -> Optional["Hero"]:
    return getattr(source, "controller", None)


def _card_num(game: "Game", source, index: int):
    d = game.db.get(source.card_id)
    return d.num(index) if d is not None else None


# ══════════════════════════════════════════════════════════════════════
# BG34_632 Incubation Researcher
# ══════════════════════════════════════════════════════════════════════


class IncubationResearcherScript:
    """
    Natural language: <b>Avenge ({0}):</b> Get a random <b>Chromadrake</b>.

    依据: CardDefs 37.0 ``BG34_632``（T4 2/8 Dragon，avenge_target=3，
    NUM_1=3）；金色 ``BG34_632_G``（4/16）文本 "Get **2** random
    Chromadrakes"。

    Formal spec:
      1. ``avenge``（引擎友方死亡计数达 CardDef.avenge_target=3 时触发；
         RULES §6.11 只统计本场战斗死亡）：随机获取 1 只 Chromadrake
         （基础版）/2 只（金色），逐只独立 `game.rng.choice`。
      2. Chromadrake 卡集 = 5 张非池 token（BG34_634t..638t，
         `batch_rally2.CHROMADRAKE_IDS` 同源，Draconic Warden /
         Hired Mount 先例）；**不占随从池**（SOP §3 token 语义），
         `create_minion` + `pending_hand_add`（满手排队）。
      3. 金色文本 "2 random" = 字面量 2（Avenge 阈值不变）。

    Test: test_batch_diff_driven3.py — 真实战斗内 3 次友方死亡后入手
    1 只 Chromadrake（卡集内、非池、池副本不变）/ 2 次死亡不触发 /
    金色 2 只 / 金色与基础 avenge_target 均为 3。
    """

    picks = 1

    @staticmethod
    def avenge(source, game: "Game", ctx=None):
        hero = _hero_of(source)
        if hero is None:
            return None
        for _ in range(source.scripts.picks):
            cid = game.rng.choice(CHROMADRAKE_IDS,
                                  label="incubation_researcher_pick")
            game.pending_hand_add(
                hero, game.create_minion(cid, controller=hero))
        return None


class IncubationResearcherGoldenScript(IncubationResearcherScript):
    """金色：一次触发获取 2 只随机 Chromadrake（独立随机）。"""

    picks = 2


# ══════════════════════════════════════════════════════════════════════
# BG26_502 Deep Blue Crooner（Spellcraft 随从 + Deep Blues 法术）
# ══════════════════════════════════════════════════════════════════════


def _deep_blue_origin(spell, hero: "Hero") -> Optional[Minion]:
    """经 spellcraft_source_uuid 找生成该法术的随从（在 hero 棋盘上）。"""
    origin_uuid = getattr(spell, "spellcraft_source_uuid", None)
    if origin_uuid is None or hero is None:
        return None
    for m in hero.board:
        if m.uuid == origin_uuid:
            return m
    return None


def _deep_blue_values(origin: Optional[Minion],
                      game: "Game", spell) -> tuple[int, int]:
    """当前 Deep Blues 数值：来源随从动态通道优先（官方注入/战场累计），
    来源离场回退该法术 CardDef 静态值（保守；来源离场后官方无记载）。"""
    if origin is not None:
        base_atk = _card_num(game, origin, 0)
        base_health = _card_num(game, origin, 1)
        atk = origin.get_script_data(1, base_atk)
        health = origin.get_script_data(2, base_health)
        if atk is not None and health is not None:
            return int(atk), int(health)
    d = game.db.get(spell.card_id)
    atk = d.num(0) if d is not None else 0
    health = d.num(1) if d is not None else 0
    return int(atk or 0), int(health or 0)


class DeepBlueCroonerScript(_SpellcraftMinionMixin):
    """
    Natural language: <b>Spellcraft:</b> Give a minion +{0}/+{1} until
    next turn. Improve your future Deep Blues.

    依据: CardDefs 37.0 ``BG26_502``（T3 2/2 Naga，spellcraft_id=98916
    → ``BG26_502t`` Deep Blues 2/2）；金色 ``BG26_502_G``（4/4，
    spellcraft_id=98918 → ``BG26_502_Gt`` 4/4）。

    Formal spec:
      1. on_summon（继承 `_SpellcraftMinionMixin`）: SPELLCRAFT tag 自举
         + 立即获得本随从 spellcraft_id 对应法术（金色 → 金色法术）。
      2. **当前 Deep Blues 数值**存该随从的动态通道 NUM_1/NUM_2：
         官方 trace 的 ``ScriptDataNum1/2`` 即此值（例 28/28、140/140；
         多张 Crooner 各自独立，金色/普通互不相同 —
         trace 71977b9485288739 / bcc2feb5b18576f2）。harness 已按官方
         值注入（deliver2 通道），脚本直接读取：
         `get_script_data(1)/(2)`，无动态值回落 CardDef num(0)/num(1)。
      3. 每次**施放** Deep Blues（法术由本随从生成）: 目标获得当前数值的
         temporary 属性 buff（下回合开始精确移除，
         `_expire_at_next_turn`）；随后该来源随从 NUM_1/NUM_2
         **永久 +基础数值**（普通 2/2，金色 4/4）→ "Improve your future
         Deep Blues"（改善未来副本，本次施放仍用旧值）。
      4. 来源随从离场后法术仍可用但不再改善（回退法术 CardDef 静态值）。

    Test: test_batch_diff_driven3.py — 打出立即获得法术 / 当前值 buff /
    施放后下一次数值 +2/+2（金色 +4/+4）/ 官方注入值 28/28 被消费 /
    下回合过期 / 来源离场不崩。
    """


class DeepBlueSpellScript:
    """
    Natural language: Give a minion +{0}/+{1} until next turn. Improve
    your future Deep Blues.

    Formal spec:
      1. on_play（ctx["target"]）: 目标获得 temporary atk/health buff =
         来源 Crooner 当前 NUM_1/NUM_2（`_deep_blue_values`；来源离场
         回退本法术 CardDef 数值）。
      2. 过期: 目标控制者下一个招募阶段开始精确移除该 buff
         （`scripts/spells._expire_at_next_turn`，RULES §6.13）。
      3. 随后来源 Crooner 的 NUM_1/NUM_2 += 基础数值（普通 2/2，
         金色 4/4 —— 取**随从** CardDef num(0)/num(1)，金色独立定义）。
      4. target=None（无目标）→ 落空但**仍改善**（施放已发生；
         官方无"无目标不改善"证据，按施放语义处理）。

    Test: 同 DeepBlueCroonerScript。
    """

    @staticmethod
    def on_play(source, game: "Game", ctx):
        hero = getattr(source, "controller", None)
        target = (ctx or {}).get("target")
        origin = _deep_blue_origin(source, hero)
        atk, health = _deep_blue_values(origin, game, source)
        if isinstance(target, Minion):
            buff = entity.Buff(atk=atk, health=health, temporary=True,
                               source_id=source.card_id)
            target.add_buff(buff)
            _expire_at_next_turn(game, source, target, buffs=[buff])
        # "Improve your future Deep Blues" —— 改善来源随从的后续数值
        if origin is not None:
            base_atk = _card_num(game, origin, 0)
            base_health = _card_num(game, origin, 1)
            if base_atk is not None and base_health is not None:
                origin.set_script_data(1, atk + int(base_atk))
                origin.set_script_data(2, health + int(base_health))
        return None


class DeepBlueGoldenSpellScript(DeepBlueSpellScript):
    """金色 Deep Blues：数值/改善步长均由金色 Crooner 卡定义体现。"""


# ══════════════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════════════


def register() -> list[str]:
    """注册本批 6 个 card_id（2 张卡 × 普/金 + 2 个 Spellcraft 法术）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (INCUBATION_RESEARCHER, IncubationResearcherScript),
        (INCUBATION_RESEARCHER_G, IncubationResearcherGoldenScript),
        (DEEP_BLUE_CROONER, DeepBlueCroonerScript),
        (DEEP_BLUE_CROONER_G, DeepBlueCroonerScript),
        (DEEP_BLUES, DeepBlueSpellScript),
        (DEEP_BLUES_G, DeepBlueGoldenSpellScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
