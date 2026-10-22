"""批次 trinkets3 — 饰品第三批（18 张，作业单 2026-09-01）。

所有数值来源: `data/bg_trinkets.json`（CardDB）文本 + `CardDef.num(0/1)`;
文本无占位符的卡按 SOP §3 以文本字面量实现，并在各类 Params: 行声明。

实现（18 个 id / 18 张卡）:
  BG30_MagicItem_902  Holy Mallet          — SoC: 最左 + 最右随从获圣盾
  BG30_MagicItem_962  Training Certificate — SoC: 两个最低攻随从属性翻倍
  BG30_MagicItem_995  Bronze Timepiece     — SoC: 每个随从 +⌊atk/2⌋ 生命
  BG30_MagicItem_984  Charging Staff       — EoT: 圣盾随从 +3 攻
  BG32_MagicItem_231  Gilded Anchor        — EoT: 金色随从 +num(0)/+num(1)
  BG32_MagicItem_276  Enigmatic Headstone  — EoT: 亡灵光环 +2 攻
  BG32_MagicItem_281  Wizard's Pipe        — 施放酒馆法术: 无类型随从 +4/+4
  BG30_MagicItem_924  Booty Bay Brew       — 花费金币: 两个友方海盗 +num
  BG30_MagicItem_981  The Eye of Dalaran   — 无类型友方死亡: 随机酒馆法术
  BG30_MagicItem_951  Lava Lamp            — 售出 6 个随从: 随机元素
  BG30_MagicItem_710  Fungalmancer Sticker — 售出 5 个随从: 随机鱼人
  BG30_MagicItem_419  Exquisite Dishware   — EoT: 每个受控类型随机随从
  BG30_MagicItem_880  Feral Talisman       — 全体有种族随从光环 +2/+1
  BG30_MagicItem_989  Artisanal Urn        — 亡灵光环 +3 攻
  BG30_MagicItem_979  Primordial Terrarium — 打出元素: 下个酒馆法术 -1 费
  BG30_MagicItem_705  Bartend-o-Tron's Oilcan — 升级费 -3，每回合重复
  BG30_MagicItem_841  Glowing Gauntlet     — 酒馆随从 +num/+num; 酒馆 7 张
  BG32_MagicItem_284  Aggem Sticker        — EoT: 每类型 7 颗血宝石

DEFERRED: 无。

ENGINE NEEDS（本批上报——现有原语可表达，但作用域/覆盖面存在缺口）:
  1. ~~Glowing Gauntlet 展示数是 game 级标记~~ **已解决（2026-09-02
     复核）**: 引擎 refresh_tavern 现已支持 hero 级
     `hero._tavern_offer_override`（hero 级优先于 game 级异变覆写），
     本卡写 hero 级 → 只影响绑定者酒馆，不污染对手（对抗审查实测
     对手馆 3 张不变）。原注记过时。
  2. ~~Feral Talisman 光环不覆盖无类型随从~~ **已解决（2026-09-02
     复核）**: entity._aura_atk/_aura_health 的 Race.ALL 光环现已命中
     全部随从（含 race == Race.NONE）——"Your minions" 语义正确
     （对抗审查实测无类型 1/1 → 3/2）。原注记过时。

引擎接线核实（SOP §14 假接线排查）:
  - NEXT_SPELL_COST_REDUCTION 读取点 = game.buy_from_tavern（game.py:456）
  - UPGRADE_COST_MOD 读取点 = game.upgrade_tavern（game.py:977）
  - _tavern_offer_override 读取点 = game.refresh_tavern（hero 级优先，回退 game 级）
  - ApplyRaceAura 读取点 = Minion._aura_atk/_aura_health（entity.py:116/150）
  - TavernBuff 持久面读取点 = refresh_tavern 新入馆随从（game.py:394）
  - TAVERN_SPELL_CAST 只对 is_pool_spell 法术 fire（game.py:954）
  - GOLD_SPENT 每次 spend_gold 交易 fire 一次（携带 amount=交易总额）
"""

# ══════════════ 对抗审查（2026-09-02）歧义裁定台账 ══════════════
# 逐条运行时复核后确认"数据无唯一解"的项，按项目"裁定先例"处理
# （给理由 + 保持现状 + 本条即审计记录）; 不满足此三条的一律改实现。
#
# A1 Feral Talisman / Artisanal Urn 的光环是否覆盖手牌:
#    裁定 = **覆盖**（引擎统一口径: hero.race_auras 对 board + hand +
#    未来入场的匹配随从实时生效，即"wherever they are"）。理由:
#    (a) 本引擎的种族光环只有这一个语义（ApplyRaceAura 注释即
#    "wherever they are" 家族），Enigmatic Headstone 的
#    "(wherever they are)" 与 Feral Talisman 的无后缀文本共用同一
#    原语，若按"有后缀才覆盖手牌"拆成两套作用域，需要给每张光环卡
#    引入作用域字段并回归全部既有光环卡（含 game.py 的当前血同步路径）;
#    (b) 酒馆战棋的手牌展示同样显示光环加成。差额只在"手牌内显示
#    属性"，不影响战斗/池/经济。**若后续取得官方反证（"无后缀 =
#    仅棋盘"），改法: ApplyRaceAura 增 scope 字段 + 逐卡声明。**
# A2 Glowing Gauntlet "The Tavern always has 7 cards":
#    裁定 = **7 个随从位**（酒馆法术位独立）。理由: T6 基础展示数为
#    6 随从 + 1 法术 = 7 张，若按"总张数 7"则该卡在 T6 完全无效果
#    （极不可能是设计意图）; 按"7 随从位"则 T6 净 +1 随从位。
# A3 ALL 类型（Amalgam）在"每个类型"类效果中计为 10 个标准种族
#    （Exquisite Dishware 抽 10 张 / Aggem Sticker 喂 10×7 宝石）:
#    与既有引擎口径一致（SOP §9 "ALL 匹配任意类型查询"）。
# A4 Booty Bay Brew "Whenever you spend Gold" = 每次 spend_gold **交易**
#    触发一次（不按金额次数）——引擎事件粒度（game.spend_gold 单次
#    fire）。交易级触发是既有 GOLD_SPENT 全部消费者的一致口径。
# A5 Bronze Timepiece "half its Attack" **向下取整**（atk // 2）:
#    HS 的"一半"类数值一律向下取整（伤害/属性同源先例）。
# A6 Training Certificate 并列最低攻: `game.rng` 随机取（官方并列
#    选取顺序未公布——Malygos "官方权重未公布" 裁定先例）。
# A7 Lava Lamp 阈值: 数据 num(0) == num(1) == 6，脚本取 num(1)
#    （文本占位符是 {1}）; 两者数值相同故行为不可区分。

from __future__ import annotations

from hsrl2.actions import Buff, GainKeyword, GetRandomMinion
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.actions.tavern_buff import (
    ApplyTavernBuff,
    BuffCurrentTavern,
    TavernBuff,
)
from hsrl2.events import (
    CARD_PLAYED,
    DEATH,
    GOLD_SPENT,
    MINION_SOLD,
    TAVERN_SPELL_CAST,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# 全部标准种族（Amalgam 规则: All 即每个类型——batch_rally.ALL_BG_RACES /
# batch_spells3 Misplaced Tea Set / batch_deathrattle Motley Phalanx 同源）
_ALL_MINION_RACES = tuple(
    r for r in Race if r not in (Race.INVALID, Race.NONE, Race.ALL)
)

_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)


def _hero(ctx):
    return ctx.get("hero") if ctx else None


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _controlled_types(hero) -> tuple:
    """本人棋盘"控制的不同类型"（标准种族顺序，去重）。

    race == ALL 的随从按官方 All 型规则视为**每个**标准种族
    （batch_spells3 Misplaced Tea Set / batch_deathrattle Motley Phalanx
    同款裁定）; race == NONE 不计（无类型不是类型）。
    """
    present = set()
    for m in hero.board:
        if m.dead:
            continue
        # 类型身份集合（AC-3）: ALL → 全 10 族; NONE → 空集;
        # 双类型贡献两个类型; 家族类型改写（Portrait）同样计入。
        present.update(m.races)
    return tuple(r for r in _ALL_MINION_RACES if r in present)


def _random_spell_from_pool(game, hero, label: str) -> None:
    """Get a random Tavern spell——池感知（占池 + 满手排队）。

    候选 = 池法术中 spell_pool 仍有副本者（RULES §2.3/§6.18），经
    `Game.tavern_spell_candidates()` 施加**存在档白名单**（异变
    101/102 非存在档法术不可达）;
    池耗尽 → 效果落空（Rodeo Performer / Bigwig Bandit 同款约定）。
    """
    cands = game.tavern_spell_candidates()
    if not cands:
        return
    card_id = game.rng.choice(cands, label=label)
    if not game.spell_pool.acquire(card_id):
        return
    game.pending_hand_add(hero, game.create_spell(card_id, controller=hero))


# ══════════════════ BG30_MagicItem_902 Holy Mallet ══════════════════

class HolyMalletScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give your left and
    right-most minions <b>Divine Shield</b>.

    Formal spec:
      1. start_of_combat（饰品 SoC 钩子）: 目标 = 本人棋盘**存活**随从中
         位置最左（索引 0）与最右（索引 -1）者; 仅 1 个随从时该随从同时
         是左右两端，只授予一次（去重）; 空棋盘 → 落空
      2. 每个目标 GainKeyword(DIVINE_SHIELD)（Action——广播
         keyword_gained）; 战斗期授予，战后由 run_combat 战前快照恢复
         回滚（RULES §3.5 战斗关键词不延续）
      3. 只作用于本人棋盘（对手不受影响）

    Test: test_batch_trinkets3.py — [A,B,C] 仅 A/C 获圣盾 / 单随从恰好
     1 次 / 真 run_combat 后回滚 / 对手棋盘不获

    Params: 无模板参数（"left and right-most" 为运行时位置）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = [m for m in h.board if not m.dead]
        if not living:
            return None
        targets = [living[0]]
        if living[-1] is not living[0]:
            targets.append(living[-1])
        return [GainKeyword(m, GameTag.DIVINE_SHIELD) for m in targets]


# ══════════════════ BG30_MagicItem_962 Training Certificate ══════════════

class TrainingCertificateScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Double the stats of
    your two lowest-Attack minions.

    Formal spec:
      1. start_of_combat: 重复 2 次（"two"）——每次从本人棋盘存活随从中取
         当前**攻击力最低**者并排除本次已选者（并列 rng.choice 任选，
         Diremuck/_pick_extreme 先例）; 不足 2 个随从时只处理实际数量
      2. 每个被选者 Buff(atk=该随从当前 atk, health=该随从当前
         max_health)——净效果 ×2; 生命快照用 max_health 而非当前血量
         （SOP §3 属性快照纪律）; 属性在 Action 构造时求值，故两个目标
         的选择与数值均基于**未翻倍**的战前属性（等价于"战前最低攻的
         两个随从各自翻倍"）
      3. 战斗期增益战后快照回滚（RULES §3.5）

    Test: test_batch_trinkets3.py — [1攻,2攻,4攻] 前两者翻倍、最高攻不变 /
     单随从只翻 1 个 / 真 run_combat 后回滚 / 对手棋盘不变

    Params: count=2（文本字面量 "two"）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        picked: list = []
        out: list = []
        for _ in range(2):
            cands = [m for m in h.board if not m.dead and m not in picked]
            if not cands:
                break
            low = min(m.atk for m in cands)
            tied = [m for m in cands if m.atk == low]
            pick = (tied[0] if len(tied) == 1
                    else game.rng.choice(tied, label="training_certificate"))
            picked.append(pick)
            out.append(Buff(pick, atk=pick.atk, health=pick.max_health))
        return out or None


# ══════════════════ BG30_MagicItem_995 Bronze Timepiece ══════════════

class BronzeTimepieceScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give each of your
    minions Health equal to half its Attack.

    Formal spec:
      1. start_of_combat: 本人棋盘每个存活随从获得 Buff(health=atk // 2)
         ——"half its Attack" 计当前攻击力整除 2（Hearthstone 整数运算
         截断 = 向下取整; 卡页与 patch notes 无相反的取整注记）;
         攻击力 <2 → 增益 0，不产生空 Buff
      2. 每个随从按自身攻击力独立计算（数值在 Action 构造时快照，
         同一次触发内互不影响）
      3. 战斗期增益战后快照回滚（RULES §3.5）

    Test: test_batch_trinkets3.py — 偶数攻 +atk/2 / 奇数攻向下取整
     （3 攻 → +1，排除向上取整）/ 0 攻不产生增益 / 真 run_combat 后回滚

    Params: divisor=2（文本字面量 "half"）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        out = [Buff(m, health=m.atk // 2)
               for m in h.board if not m.dead and m.atk // 2 > 0]
        return out or None


# ══════════════════ BG30_MagicItem_984 Charging Staff ══════════════

class ChargingStaffScript:
    """
    Natural language: [x]At the end of each turn, give your minions
    with <b>Divine Shield</b> +3 Attack.

    Formal spec:
      1. end_of_turn（饰品 EoT 钩子——end_recruit_phase: 饰品 → 奖励 →
         随从）: 本人棋盘每个**存活且持有 DIVINE_SHIELD** 的随从获得
         Buff(atk=3) 永久增益
      2. 无圣盾随从（含无圣盾者的其他随从）不受影响; 空棋盘/无圣盾 →
         落空（返回 None）
      3. 只作用于本人棋盘

    Test: test_batch_trinkets3.py — 仅圣盾随从 +3 攻 / 非圣盾不变 /
     对手不变

    Params: atk=3（文本字面量 "+3 Attack"）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        out = [Buff(m, atk=3) for m in h.board
               if not m.dead and m.has(GameTag.DIVINE_SHIELD)]
        return out or None


# ══════════════════ BG32_MagicItem_231 Gilded Anchor ══════════════

class GildedAnchorScript:
    """
    Natural language: At the end of each turn, give your Golden minions
    +{0}/+{1}.

    Formal spec:
      1. end_of_turn: 本人棋盘每个**存活且金色**（GOLDEN tag——金色是
         独立卡定义，实体 is_golden 权威）的随从获得
         Buff(atk=num(0), health=num(1)) 永久增益
      2. 非金色随从不受影响; 无金色随从 → 落空
      3. 只作用于本人棋盘

    Test: test_batch_trinkets3.py — 金色随从 +num(0)/+num(1) / 非金色
     不变 / 对手金色不变 / 期望值取自 CardDef.num

    Params: {0}=3 {1}=3（BG32_MagicItem_231 num(0/1)）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)
        out = [Buff(m, atk=atk, health=health) for m in h.board
               if not m.dead and m.is_golden]
        return out or None


# ══════════════════ BG32_MagicItem_276 Enigmatic Headstone ══════════════

class EnigmaticHeadstoneScript:
    """
    Natural language: At the end of each turn, your Undead have
    +2 Attack this game <i>(wherever they are)</i>.

    Formal spec:
      1. end_of_turn: ApplyRaceAura(hero, UNDEAD, atk=2, health=0)——
         hero.race_auras 叠加式**永久**光环（"this game"）; 同一饰品每
         回合叠加一次（官方 "repeat" 语义: 第 N 回合后 +2N 攻）
      2. 读取点 = Minion._aura_atk（entity.py:116）——棋盘/手牌/**未来
         获得**的亡灵实时生效（"wherever they are"）; 不写 game 级
      3. 只作用于本人（hero 作用域），对手亡灵不受影响

    Test: test_batch_trinkets3.py — EoT 后 race_auras[UNDEAD]=(2,0) /
     棋盘亡灵 +2 攻 / 之后新召唤亡灵同样 +2 / 两回合后 (4,0) /
     对手不变

    Params: atk=2（文本字面量 "+2 Attack"）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return ApplyRaceAura(h, Race.UNDEAD, atk=2, health=0,
                             source_id=source.card_id)


# ══════════════════ BG32_MagicItem_281 Wizard's Pipe ══════════════

class WizardsPipeScript:
    """
    Natural language: [x]Whenever you cast a Tavern spell, give your
    minions with no type +4/+4.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品——离场/淘汰自动注销）:
         TAVERN_SPELL_CAST（spell=）——引擎只对 `is_pool_spell` 法术
         广播（game.py:954），正是 "Tavern spell" 语义（Spellcraft/血
         宝石等非池法术不计）; `spell.controller is 本人` owner 隔离
      2. 触发: 本人棋盘每个存活且 `race == Race.NONE`（**严格无类型**;
         ALL 不算——文本 "with no type"）的随从获得 Buff(+4/+4) 永久
         增益
      3. 无无类型随从 → 落空; 无类型随从在打出元素等之后的类型变化由
         引擎 RACE tag 决定（本卡只读当前 race）
      4. 法术双施（Balinda）按施放次数各广播一次 → 每次各 +4/+4

    Test: test_batch_trinkets3.py — 真实打出酒馆法术 → 无类型随从
     +4/+4、有种族随从不变 / 对手施放不触发 / 无无类型随从落空 /
     对手棋盘不变

    Params: atk=4 health=4（文本字面量 "+4/+4"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            out = [Buff(m, atk=4, health=4) for m in h.board
                   if not m.dead and m.race == Race.NONE]
            if out:
                g.run_actions(out)

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        return None


# ══════════════════ BG30_MagicItem_924 Booty Bay Brew ══════════════

class BootyBayBrewScript:
    """
    Natural language: Whenever you spend Gold, give two friendly Pirates
    +{0}/+{1}.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: GOLD_SPENT（hero=,
         amount=）——game.spend_gold 每次**交易**广播一次（购买/刷新/
         升级/Activate/Dark Gift 等统一入口; 交易总额在 amount）。
         "Whenever you spend Gold" 按交易次数触发（引擎事件粒度 = 一次
         消费行为; 卡页 Wiki tags 无 per-Gold 注记，且无逐金事件源）
      2. 触发条件: `hero is 本人`（owner 隔离）且 amount > 0
      3. 候选 = 本人棋盘存活海盗（race PIRATE 或 ALL——Amalgam 规则）;
         随机抽 **min(2, n) 个不重复**（game.rng.sample——"two
         friendly Pirates" 为两个不同随从; 不足 2 个则给全部）
      4. 每个获 +num(0)/+num(1) 永久增益; 无海盗 → 落空不补
      5. 只作用于本人棋盘（对手花费不触发）

    Test: test_batch_trinkets3.py — spend_gold(3) 后恰好 2 个海盗共
     +2·num(0)/+2·num(1)、第三个海盗/非海盗不变 / 对手花费不触发 /
     连续两次花费各触发一次 / 期望值取自 CardDef.num

    Params: {0}=3 {1}=3（BG30_MagicItem_924 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_spend(g, hero=None, amount=0, **kw):
            if hero is not h or amount <= 0:
                return
            cands = [m for m in h.board
                     if not m.dead and m.race in _PIRATE_RACES]
            if not cands:
                return
            k = min(2, len(cands))
            picks = (list(cands) if k == len(cands)
                     else g.rng.sample(cands, k, label="booty_bay_brew"))
            atk = _num(g, source.card_id, 0)
            health = _num(g, source.card_id, 1)
            g.run_actions([Buff(m, atk=atk, health=health) for m in picks])

        game.events.register(Listener(event=GOLD_SPENT, owner=source,
                                      callback=on_spend))
        return None


# ══════════════════ BG30_MagicItem_981 The Eye of Dalaran ══════════════

class EyeOfDalaranScript:
    """
    Natural language: [x]Whenever a friendly minion with no type dies,
    get a random Tavern spell.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: DEATH（minion=）——招募期
         与战斗内死亡都触发（文本无阶段限定）; `minion.controller is
         本人` 且 `minion.race == Race.NONE`（严格无类型; ALL 不算）
      2. 触发: 从 db.pool_spells() 中 spell_pool 仍有副本者随机 1 张
         （game.rng.choice）→ spell_pool.acquire 占池（RULES §2.3）→
         create_spell → pending_hand_add（满手排队 RULES §3.3）
      3. 池耗尽 → 效果落空（Rodeo Performer/Bigwig Bandit 同款约定）
      4. 每次合格死亡各触发一次; 只进本人手牌（对手不受影响）

    Test: test_batch_trinkets3.py — 无类型友方死亡 → 恰好 1 张池法术
     入手且 spell_pool 余量 -1 / 有种族友方死亡不触发 / 对手无类型
     死亡不触发（owner 隔离）/ 对手手牌不变

    Params: 无模板参数（"a random Tavern spell" = 1 张）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_death(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if minion.race != Race.NONE:
                return
            _random_spell_from_pool(g, h, "eye_of_dalaran_spell")

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        return None


# ══════════════════ BG30_MagicItem_951 Lava Lamp ══════════════

class LavaLampScript:
    """
    Natural language: After you sell {1} minions, get a random Elemental.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: MINION_SOLD（minion=）——
         `minion.controller is 本人`（出售随从的归属者）; 计数 += 1
      2. 计数达阈值 num(1)=6 时**清零**并 GetRandomMinion(hero,
         race=ELEMENTAL)——池感知（占池 RULES §2.3 + 满手排队
         RULES §3.3）; 文本 {1} 是阈值、{0} 是剩余显示值（同源 6）
      3. 计数跨回合累积（文本无 "this turn"）; 计数状态存于脚本闭包
         （随饰品实体存活，退役即失效）
      4. 超阈值不重复发放（每次恰好 1 只随机元素）

    Test: test_batch_trinkets3.py — 第 5 次出售不发放 / 第 6 次恰好
     1 只随机元素入手且 minion_pool 元素余量 -1 / 计数清零后第 12 次
     再发放 / 阈值 == CardDef.num(1)

    Params: {0}=6 {1}=6（BG30_MagicItem_951 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 1)
        progress = [0]          # 闭包可变状态（源码无需写实体私有属性）

        def on_sold(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            progress[0] += 1
            if progress[0] < threshold:
                return
            progress[0] = 0
            g.run_actions(GetRandomMinion(h, race=Race.ELEMENTAL))

        game.events.register(Listener(event=MINION_SOLD, owner=source,
                                      callback=on_sold))
        return None


# ══════════════════ BG30_MagicItem_710 Fungalmancer Sticker ══════════════

class FungalmancerStickerScript:
    """
    Natural language: [x]After you sell 5 minions, get a random Murloc.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: MINION_SOLD（minion=）——
         `minion.controller is 本人`; 计数 += 1
      2. 计数达阈值 num(0)=5（文本 "sell 5 minions" 与 {0} 显示值同源，
         CardDef 无 {1} 参数）时清零并 GetRandomMinion(hero,
         race=MURLOC)——池感知 + 满手排队
      3. 计数跨回合累积; 状态存于脚本闭包（随饰品实体存活）

    Test: test_batch_trinkets3.py — 第 4 次出售不发放 / 第 5 次恰好
     1 只随机鱼人入手且 minion_pool 鱼人余量 -1 / 阈值 ==
     CardDef.num(0)

    Params: {0}=5（BG30_MagicItem_710 num(0)——文本 "sell 5 minions"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        progress = [0]

        def on_sold(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            progress[0] += 1
            if progress[0] < threshold:
                return
            progress[0] = 0
            g.run_actions(GetRandomMinion(h, race=Race.MURLOC))

        game.events.register(Listener(event=MINION_SOLD, owner=source,
                                      callback=on_sold))
        return None


# ══════════════════ BG30_MagicItem_419 Exquisite Dishware ══════════════

class ExquisiteDishwareScript:
    """
    Natural language: [x]At the end of each turn, get a random minion of
    each different type you control.

    Formal spec:
      1. end_of_turn: types = `_controlled_types(hero)`——本人棋盘存活
         随从的类型集合（标准种族顺序去重）; race == ALL 的随从按官方
         All 型规则贡献**全部**标准种族（Misplaced Tea Set / Motley
         Phalanx 同款裁定, batch_spells3），race == NONE 不计
      2. 对每个受控类型各 GetRandomMinion(hero, race=r)——池感知
         （占池 RULES §2.3 + 满手排队 RULES §3.3）; 池中无该种族候选
         → 该类型落空（不补偿）
      3. 每次 EoT 独立结算（"each turn"）; 空棋盘/全无类型 → 落空
      4. 只进本人手牌（对手不受影响）

    Test: test_batch_trinkets3.py — 鱼人+亡灵棋盘 → 恰好 2 只随从入手
     且分别覆盖两个类型 / 无类型随从单独在场 → 落空 / ALL 随从在场
     → 每个标准种族各 1 只（覆盖全 10 类）/ 对手手牌不变

    Params: 无模板参数（"a random minion of each" = 每类型 1 只）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        types = _controlled_types(h)
        if not types:
            return None
        return [GetRandomMinion(h, race=r) for r in types]


# ══════════════════ BG30_MagicItem_880 Feral Talisman ══════════════

class FeralTalismanScript:
    """
    Natural language: Your minions have +2/+1.

    Formal spec:
      1. on_bind: ApplyRaceAura(hero, Race.ALL, atk=2, health=1)——
         hero.race_auras 叠加式永久光环; 读取点 = Entity._aura_atk/
         _aura_health（entity.py:116/150），对棋盘/手牌/**未来获得**的
         全部有种族随从（含 ALL 本体）实时生效（"wherever they are"）
      2. 引擎 `_aura_atk/_aura_health` 对 `race == Race.NONE` 提前返回 0
         ——本光环覆盖有种族随从，不覆盖无类型随从（ENGINE NEEDS #2）
      3. 只写本人 hero 作用域（对手不受影响）

    Test: test_batch_trinkets3.py — 鱼人/亡灵/ALL 随从各 +2/+1（含手牌
     与之后新召唤者）/ 对手随从不变

    Params: atk=2 health=1（文本字面量 "+2/+1"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return ApplyRaceAura(h, Race.ALL, atk=2, health=1,
                             source_id=source.card_id)


# ══════════════════ BG30_MagicItem_989 Artisanal Urn ══════════════

class ArtisanalUrnScript:
    """
    Natural language: Your Undead have +3 Attack.

    Formal spec:
      1. on_bind: ApplyRaceAura(hero, UNDEAD, atk=3, health=0)——永久
         光环; 读取点 = Minion._aura_atk; 棋盘/手牌/未来亡灵实时生效
      2. 非亡灵不受影响; ALL 种族随从按 Amalgam 规则命中
      3. 只写本人 hero 作用域（对手亡灵不变）

    Test: test_batch_trinkets3.py — 亡灵 +3 攻 / 鱼人不变 / 之后新召唤
     亡灵同样 +3 / 对手亡灵不变

    Params: atk=3（文本字面量 "+3 Attack"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return ApplyRaceAura(h, Race.UNDEAD, atk=3, health=0,
                             source_id=source.card_id)


# ══════════════════ BG30_MagicItem_979 Primordial Terrarium ════════════

class PrimordialTerrariumScript:
    """
    Natural language: [x]After you play an Elemental, your next Tavern
    spell costs (1) less.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: CARD_PLAYED（card=）——
         引擎无 ELEMENTAL_PLAYED fire（Nomi Sticker 先例），经
         card_played + 种族过滤等价实现: card 是 Minion 且
         `controller is 本人` 且 race ∈ (ELEMENTAL, ALL)
      2. 每次触发: hero.NEXT_SPELL_COST_REDUCTION += 1（叠加式——多次
         打出元素则折扣累加）
      3. 消费点核实（SOP §14）: game.buy_from_tavern（game.py:456）在
         购买 is_pool_spell 时读取该 tag、扣减折扣并清零——只影响下一次
         酒馆法术购买
      4. 非元素打出不触发; 对手打出不触发

    Test: test_batch_trinkets3.py — 打出元素后 tag=1 / 非元素不触发 /
     随后真实 buy_from_tavern 一张 2 费酒馆法术只花 1 金且 tag 清零 /
     再买一张恢复全价 / 对手 tag 不变

    Params: reduce=1（文本字面量 "costs (1) less"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion):
                return
            if card.controller is not h or card.race not in _ELEMENTAL_RACES:
                return
            h.set(GameTag.NEXT_SPELL_COST_REDUCTION,
                  h.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0) + 1)

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════ BG30_MagicItem_705 Bartend-o-Tron's Oilcan ══════════════

class BartendOTronOilcanScript:
    """
    Natural language: [x]Reduce the Cost of upgrading the Tavern by (3).
    At the start of each turn, repeat this.

    Formal spec:
      1. on_bind: hero.UPGRADE_COST_MOD -= 3（升级费加值 tag）
      2. start_of_turn（饰品 SoT 钩子）: 同款再减 3——"At the start of
         each turn, repeat this" 的逐回合叠加语义（第 N 个招募回合开始
         时累计 -3N）
      3. 消费点核实（SOP §14）: game.upgrade_tavern（game.py:977）
         `cost = max(UPGRADE_COST_FLOOR, hero.upgrade_cost +
         hero.get(UPGRADE_COST_MOD, 0))`——减费真实生效，下限 0
      4. 只写本人 hero 作用域（对手升级费不变）

    Test: test_batch_trinkets3.py — 绑定后升级费 -3 / 真实
     upgrade_tavern 少付 3 金 / 再开始一回合累计 -6 / 对手 UPGRADE_COST_MOD
     与升级费不变

    Params: reduce=3（文本字面量 "(3)"）
    """

    @staticmethod
    def _apply(h) -> None:
        h.set(GameTag.UPGRADE_COST_MOD,
              h.get(GameTag.UPGRADE_COST_MOD, 0) - 3)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        BartendOTronOilcanScript._apply(h)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        BartendOTronOilcanScript._apply(h)
        return None


# ══════════════════ BG30_MagicItem_841 Glowing Gauntlet ══════════════

class GlowingGauntletScript:
    """
    Natural language: [x]Minions in the Tavern have +{0}/+{1}. The Tavern
    always has 7 cards.

    Formal spec:
      1. on_bind:
         a) TavernBuff(atk=num(0), health=num(1), source_id=本卡)——
            ApplyTavernBuff 登记持久面（refresh_tavern 对**新入馆**随从
            自动应用, game.py:394）+ BuffCurrentTavern 立即面（当前馆内
            随从即时获得）; 无 race_filter = 命中酒馆内全部随从
         b) `hero._tavern_offer_override = 7`——"Your Tavern always has
            7 cards"; 读取点 = refresh_tavern（hero 级**优先**于 game 级
            异变覆写）覆盖展示数计算。hero 级 → 只影响绑定者酒馆
            （对手馆展示数不受影响; 2026-09-02 对抗审查实测复核）;
            数值增益面同样是 hero 作用域
      2. 只对本人酒馆随从加数值（TavernBuff 挂在 hero.tavern_buffs）;
         对手馆内随从不受增益

    Test: test_batch_trinkets3.py — 绑定后真实刷新 → 馆内每个随从
     +num(0)/+num(1)、二次刷新新入馆者同样继承 / 对手馆内随从无增益 /
     本人馆内随从数 == 7（override 读取点真实生效）

    Params: {0}=3 {1}=3（BG30_MagicItem_841 num(0/1)） offer=7
             （文本字面量 "always has 7 cards"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        tb = TavernBuff(atk=_num(game, source.card_id, 0),
                        health=_num(game, source.card_id, 1),
                        source_id=source.card_id)
        game.run_actions([ApplyTavernBuff(h, tb),
                          BuffCurrentTavern(h, tb)])
        # hero 级覆写（"Your Tavern always has 7 cards"——不得污染对手;
        # 引擎 refresh_tavern 优先读 hero._tavern_offer_override）
        h._tavern_offer_override = 7
        return None


# ══════════════════ BG32_MagicItem_284 Aggem Sticker ══════════════

class AggemStickerScript:
    """
    Natural language: [x]At the end of your turn, this plays {0}
    <b>Blood Gems</b> on a friendly minion of each type.

    Formal spec:
      1. end_of_turn: 对每个标准种族 r ∈ _ALL_MINION_RACES:
         候选 = 本人棋盘存活、race ∈ (r, ALL) 的随从; 有候选 →
         game.rng.choice 随机 1 个（"a friendly minion of each type"
         独立选取裁定——Misplaced Tea Set / Motley Phalanx 先例;
         同一随从可被多个种族分别命中，Amalgam 场景可叠全部 10 份）;
         无候选 → 该类型跳过
      2. 对每个选中者 PlayBloodGems(target, count=num(0))——立即施放
         num(0)=7 颗 **vanilla** 血宝石（不经手牌、不耗金币）:
         每颗数值 = BG20_GEM.num(0/1) + 持有者
         BLOOD_GEM_BONUS_ATK/HEALTH（bloodgem._gem_values 统一出口）;
         per-minion GEMS_PLAYED_ON 记账 + blood_gem_played 广播
         （Jailbird/Gem Confiscation 数据源）
      3. "this plays"——宝石由饰品（非玩家手牌）施放，走 PlayBloodGems
         而非 GetBloodGems
      4. 只作用于本人棋盘（对手不受影响）

    Test: test_batch_trinkets3.py — 鱼人+亡灵棋盘 → 两只各 +7·宝石值、
     GEMS_PLAYED_ON==num(0)、无类型随从不受影响 / 两次 EoT 叠加 /
     对手棋盘不变

    Params: {0}=7（BG32_MagicItem_284 num(0)）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        count = _num(game, source.card_id, 0)
        out = []
        for race in _ALL_MINION_RACES:
            cands = [m for m in h.board
                     if not m.dead and m.race in (race, Race.ALL)]
            if not cands:
                continue
            pick = game.rng.choice(cands, label="aggem_sticker_target")
            out.append(PlayBloodGems(pick, count, source=source))
        return out or None


# ══════════════════ 注册 ══════════════════

def register() -> list[str]:
    """注册饰品第三批 18 张（无 DEFERRED）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_902", HolyMalletScript),
        ("BG30_MagicItem_962", TrainingCertificateScript),
        ("BG30_MagicItem_995", BronzeTimepieceScript),
        ("BG30_MagicItem_984", ChargingStaffScript),
        ("BG32_MagicItem_231", GildedAnchorScript),
        ("BG32_MagicItem_276", EnigmaticHeadstoneScript),
        ("BG32_MagicItem_281", WizardsPipeScript),
        ("BG30_MagicItem_924", BootyBayBrewScript),
        ("BG30_MagicItem_981", EyeOfDalaranScript),
        ("BG30_MagicItem_951", LavaLampScript),
        ("BG30_MagicItem_710", FungalmancerStickerScript),
        ("BG30_MagicItem_419", ExquisiteDishwareScript),
        ("BG30_MagicItem_880", FeralTalismanScript),
        ("BG30_MagicItem_989", ArtisanalUrnScript),
        ("BG30_MagicItem_979", PrimordialTerrariumScript),
        ("BG30_MagicItem_705", BartendOTronOilcanScript),
        ("BG30_MagicItem_841", GlowingGauntletScript),
        ("BG32_MagicItem_284", AggemStickerScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
