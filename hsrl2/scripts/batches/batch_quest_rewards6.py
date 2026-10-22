"""批次 quest_rewards6 — 任务奖励第六批: 两个新引擎读取点兑现
（作业单 2026-09-15，2 张）。

台账来源: `batch_hero_rewards_final.py` 文末 DEFERRED 台账第 6/7 条
（`BG27_Reward_812` Scepter of Guidance / `BG28_Reward_501` Temporal
Tampering）。两张此前均因**读取点缺失**DEFERRED，本轮引擎补齐后注册。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码）; 状态写在
hero 级属性 / `extra_triggers`（无 game 级 flag——SOP §12 item 9）;
随机: 本批 2 张均无随机; owner 隔离: `ctx["hero"]` 缺失退回
`source.controller`。

**新引擎原语逐条核对（2026-09-15，RULES §7.4.14）**
═══════════════════════════════════════════════════════════════════════
  | 原语（生产点） | 本批消费卡 | 语义 |
  |----------------|-----------|------|
  | `hero._tavern_race_guarantee = (race, n)`（消费点
    `game.py::refresh_tavern`——本次刷新的**前 n 个随从位专供**该种族
    （含 `Race.ALL` 多类型随从），其余位走通用/白名单池; hero 级优先、
    回落 game 级; 池不足 N → 按可得数回落通用池，**不注入**） | 812 |
    全量种族白名单（`races=`）是"排除其它种族"，本原语是"保证 N 个位"，
    两者语义不同（SOP §6b 禁止用前者近似后者）。 |
  | `hero.extra_triggers["tavern_spell_extra_cast"]`（消费点
    `game.py::_finish_play_spell`，`card_def.is_pool_spell` 门禁下
    `casts += N`; **永久**额度、不消费/不按回合重置; 与 Balinda 的棋盘
    `SPELL_DOUBLER` 光环、`spell_first` 配额三者**独立叠加**） | 501 |
    `spell_first` 是"任意法术的第一个多结算一次"（会误双施 Spellcraft/
    血宝石），不可复用; 本键只对酒馆法术生效。 |

**CORRECT 2 项（注册 2 个 id）**
═══════════════════════════════════════════════════════════════════════
  BG27_Reward_812 Scepter of Guidance —
      "The Tavern always offers 2 {0} whenever it is Refreshed."
      `num(0)`=92 = `Race.NAGA`（XML `BACON_MINION_TYPE_REWARD=1` 证实
      {0} 是类型）; "2" 是卡面字面量（无占位符，SOP §3 显式声明）。
      on_bind → 本人 `_tavern_race_guarantee = (Race.NAGA, 2)`（永久，
      每次刷新都生效）。

  BG28_Reward_501 Temporal Tampering —
      "Your Tavern spells cast an extra time."
      "an extra time" = 每张酒馆法术**多结算 1 次**（卡面字面量 1，
      无占位符）。on_bind → `extra_triggers["tavern_spell_extra_cast"] += 1`
      （accumulate——多来源各自叠加; 与 batch_trinkets6 `_grant_extra_trigger`
      同一约定）。

**DEFERRED 台账（本批无新增）**
═══════════════════════════════════════════════════════════════════════
  剩余任务奖励 5 张的依赖以 `batch_hero_rewards_final.py` 文末台账为准:
  135 Wheel of Yogg-Saron（结果表无数据权威）/ 313 Wondrous Wisdomball
  （概率与类别表无权威）/ 362 Essence of Zerus（授予物 `BGS_029`
  Shifter Zerus 缺手牌变形脚本）/ 719 The Golden Hammer（缺
  temporary-golden 原语）/ 555t No Place Like Holmes（回报数值无权威）。

测试: `hsrl2/tests/test_batch_quest_rewards6.py`（行为层: 真实
`complete_quest` 绑定路径 + 真实 `refresh_tavern` / `play_spell` /
`use_hero_power` 正负对照 + owner 隔离 + 池不足回落 + 非池法术门禁）
"""

from __future__ import annotations

from hsrl2.game import GameStateError
from hsrl2.tags import Race

# 卡面字面量（CardDef.num 全 None / 文本无占位符）
_OFFERS = 2            # 812 "always offers 2 {0}" 的 2
_EXTRA_CASTS = 1       # 501 "cast an extra time" 的 1
_RACE_GUARANTEE_KEY = "_tavern_race_guarantee"
_SPELL_EXTRA_KEY = "tavern_spell_extra_cast"


def _hero_of(source, ctx):
    hero = None
    if ctx is not None:
        hero = ctx.get("hero")
    if hero is None:
        hero = getattr(source, "controller", None)
    return hero


# ══════════════ BG27_Reward_812 Scepter of Guidance ══════════════


class ScepterOfGuidanceScript:
    """
    Natural language: The Tavern always offers 2 {0} whenever it is
    <b>Refreshed</b>.

    Evidence: data/bg_quest_rewards.json BG27_Reward_812; `num(0)`=92
    = `Race.NAGA`（XML `BACON_MINION_TYPE_REWARD=1` 证明 {0} 是随从类型，
    非数量）; 文本 "2" 为无占位符字面量。"always offers 2 {0}" =
    每次刷新**保证 2 个展示位**为该类型（非"全馆限定该类型"——后者是
    Overseer's Orb / Only <race> 异变的全量白名单语义）。

    Formal spec:
      1. on_bind(source, game, ctx): hero = ctx["hero"]（缺失退回
         source.controller）; 缺失 → 落空
      2. `num(0)` 转 `Race`; 非法 → `GameStateError`（fail-loud，
         禁止静默近似）
      3. `hero._tavern_race_guarantee = (Race.NAGA, 2)`——hero 级**永久**
         读取点; 引擎 `refresh_tavern` 取前 2 个随从位从
         `{NAGA, Race.ALL}` 抽取，其余位走通用池
      4. 只作用于本英雄（owner 隔离——不污染对手酒馆）

    Test: test_batch_quest_rewards6.py — 真实 `complete_quest` 后:
      本人酒馆前 2 个随从位为纳迦/全类型; 对手无该奖励 → 前 2 位不受
      约束（负对照 + 正对照）; 重复刷新仍保证（永久）; 池不足时回落
      通用池且总位数不变（不注入）; num(0) 非法 → GameStateError

    Params: {0}=num(0)=92=Race.NAGA; offers=2（卡面字面量，无占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero_of(source, ctx)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        race_id = d.num(0) if d is not None else None
        if race_id is None:
            raise GameStateError(
                "BG27_Reward_812 Scepter of Guidance: missing num(0) race")
        try:
            race = Race(int(race_id))
        except ValueError as exc:
            raise GameStateError(
                f"BG27_Reward_812: num(0)={race_id} is not a valid Race"
            ) from exc
        setattr(hero, _RACE_GUARANTEE_KEY, (race, _OFFERS))
        return None


# ══════════════ BG28_Reward_501 Temporal Tampering ══════════════


class TemporalTamperingScript:
    """
    Natural language: Your Tavern spells cast an extra time.

    Evidence: data/bg_quest_rewards.json BG28_Reward_501（无模板参数）。
    "Tavern spells" = `CardDef.is_pool_spell`（引擎计数口径与
    `TAVERN_SPELLS_CAST_*` 一致）; "an extra time" = 每次施放多结算 1 次
    （卡面字面量）；效果为**永久**（无回合限制）。

    Formal spec:
      1. on_bind(source, game, ctx): hero = ctx["hero"]（缺失退回
         source.controller）; 缺失 → 落空
      2. `hero.extra_triggers["tavern_spell_extra_cast"] += 1`
      3. 引擎 `_finish_play_spell`: 该法术是酒馆法术
         （`card_def.is_pool_spell`）时 `casts += N`——每个酒馆法术多结算
         N 次; 不消费、不按回合重置; 非酒馆法术（Spellcraft/血宝石/
         生成 token 法术）不受影响
      4. 与棋盘 `SPELL_DOUBLER`（Balinda）光环、`spell_first` 配额独立

    Test: test_batch_quest_rewards6.py — 真实 `complete_quest` 后:
      酒馆法术（Tavern Dish Banana）数值双倍（`num(0)*2`）且
      `TAVERN_SPELLS_CAST_THIS_GAME` 计 2; 非池法术（Lantern Light，
      `is_pool_spell=False`）只结算一次（负对照）; 第二个酒馆法术仍双倍
      （永久，非"第一个"）; 对手无该奖励 → 单次（owner 隔离）;
      叠加 `spell_first` → 3 次

    Params: extra=1（卡面字面量 "an extra time"，无占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero_of(source, ctx)
        if hero is None:
            return None
        hero.extra_triggers[_SPELL_EXTRA_KEY] = (
            hero.extra_trigger(_SPELL_EXTRA_KEY) + _EXTRA_CASTS)
        return None


def register() -> list[str]:
    """注册任务奖励批 6（2 张: 种族保证 + 酒馆法术额外施放）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG27_Reward_812", ScepterOfGuidanceScript),
        ("BG28_Reward_501", TemporalTamperingScript),
    ]
    registered = []
    for rid, cls in pairs:
        reg(rid, cls)
        registered.append(rid)
    return registered
