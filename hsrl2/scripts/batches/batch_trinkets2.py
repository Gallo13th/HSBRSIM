"""批次 trinkets2 — 饰品第二批（20 张饰品 + 1 张 Spellcraft 法术 token）。

所有数值来源: `data/bg_trinkets.json`（CardDB）文本 + `CardDef.num(0/1)`;
文本无占位符的卡按 SOP §3 以文本字面量实现，并在各类 Params: 行声明。

实现（21 个 id / 20 张卡）:
  BG30_MagicItem_847  Goblin Wallet        — EoT: 最大金币 +1（INCOME_CAP_BONUS）
  BG30_MagicItem_403  Ironforge Anvil      — SoC: 无类型随从属性三倍
  BG30_MagicItem_414  Kodo Leather Pouch   — 买卡后 2 个随机友方 +2/+1
  BG30_MagicItem_414t Kodo Leather Pouch   — 同上 Greater（+4/+4）
  BG30_MagicItem_437  Staff of the Scourge — Avenge(5): 随机友方 Undead 获 Reborn
  BG30_MagicItem_542  Emerald Dreamcatcher — SoC: 龙攻击力设为战团最高
  BG30_MagicItem_427  Tiger Carving        — 友方受伤: 另一个友方 +3/+1 永久
  BG30_MagicItem_427t Tiger Carving        — 同上 Greater（+6/+2）
  BG30_MagicItem_900  Dragonwing Glider    — 打出卡牌: 随机友方龙 +4/+4
  BG30_MagicItem_900t Dragonwing Glider    — 同上 Greater（+6/+4）
  BG30_MagicItem_970  Valorous Medallion   — SoC: 全体 +2/+2
  BG30_MagicItem_970t Valorous Medallion   — 同上 Greater（+6/+6）
  BG30_MagicItem_925  Ceremonial Sword     — 友方攻击时该随从 +4 攻
  BG32_MagicItem_270  Wicked Tome          — Avenge(3): 酒馆法术额外 +1 攻
  BG32_MagicItem_270t Wicked Tome          — Avenge(4): 额外 +1/+1
  BG30_MagicItem_544  Nomi Sticker         — 打出元素后酒馆元素 +2/+2 本局
  BG30_MagicItem_544t Nomi Sticker         — 同上 Greater（+5/+5）
  BG30_MagicItem_547  Comfy Coffin         — 施放酒馆法术: 亡灵 +1 攻（光环）
  BG30_MagicItem_547t Comfy Coffin         — 同上 Greater（+2 攻）
  BG30_MagicItem_714  Precious Pearl        — Spellcraft: 每回合给 Harvested
                                              Pearl
  BG30_MagicItem_714t Harvested Pearl       — 法术本体: 目标 +30/+30 到下回合

引擎接线核实（SOP §14 "假接线" 排查）:
  - INCOME_CAP_BONUS 读取点 = hero.income_cap（hero.py:85）→
    game._begin_recruit_for 的金币重置（game.py:195）
  - TAVERN_SPELL_EXTRA_ATK/HEALTH 读取点 = racefx.tavern_spell_buff，
    生产调用点遍布 spells/spells2/spells3/spells4/spells_final/choose_one/
    rally/rally2/misc/eot_sot 等真实法术脚本（非空转）
  - ApplyRaceAura 读取点 = Minion._aura_atk/_aura_health（entity.py:116）
    → board/hand/未来随从实时生效
  - TavernBuff 持久面读取点 = refresh_tavern 新入馆随从（game.py:394）
  - Avenge 计数覆盖 hero.trinkets（game.py:_process_single_death，
    脚本以类属性 avenge_threshold 声明阈值）

DEFERRED: 无。
"""

from __future__ import annotations

from hsrl2 import entity
from hsrl2.actions import Buff, GainKeyword
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.actions.tavern_buff import (
    ApplyTavernBuff,
    BuffCurrentTavern,
    TavernBuff,
)
from hsrl2.events import (
    BEFORE_ATTACK,
    CARD_PLAYED,
    COMBAT_END,
    DAMAGE,
    MINION_BOUGHT,
    TAVERN_SPELL_CAST,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.scripts.spells import _expire_at_next_turn
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

# 种族判定集合（Race.ALL = 全种族视为所有类型, RULES §6.18）
_DRAGON_RACES = (Race.DRAGON, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)


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


# ══════════════════ BG30_MagicItem_847 Goblin Wallet ══════════════════

class GoblinWalletScript:
    """
    Natural language: At the end of each turn, increase your maximum Gold
    by 1.

    Formal spec:
      1. end_of_turn（饰品自身 EoT 钩子，engine EoT 顺序: 饰品 → 奖励 →
         随从——end_recruit_phase）: 本人（source.controller）
         `INCOME_CAP_BONUS` += 1（叠加式，跨回合累积）
      2. 读取点: hero.income_cap = GOLD_INCOME_CAP(10) + tag
         （hero.py:85）→ `_begin_recruit_for` 的基础收入封顶
         （game.py:195）; 只影响本人 hero 实体，不写 game 级
      3. "maximum Gold" 指每回合基础收入上限，不是即时金币
         （无 GainGold——官方文本是 maximum 而非 Gain）

    Test: test_batch_trinkets2.py — EoT 后 income_cap = 10+1 且实际基础
    收入封顶抬升（g.turn 拉高后 _begin_recruit_for 发放 11 金）/
    对手不受影响

    Params: gold=1（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        h.set(GameTag.INCOME_CAP_BONUS,
              h.get(GameTag.INCOME_CAP_BONUS, 0) + 1)
        return None


# ══════════════════ BG30_MagicItem_403 Ironforge Anvil ══════════════════

class IronforgeAnvilScript:
    """
    Natural language: <b>Start of Combat:</b> Triple the stats of your
    minions with no type.

    Formal spec:
      1. start_of_combat（饰品 SoC 钩子，先于随从/英雄技能——combat.py
         _start_of_combat_phase）: 候选 = 本人棋盘存活且
         `race == Race.NONE`（**仅无类型**，ALL 不算——文本 "with no
         type"）的随从
      2. 每个候选独立三倍: Buff(atk=当前 atk × 2, health=当前
         max_health × 2)——净效果 ×3; 属性快照用 max_health（SOP §3）
      3. 战斗期增益为 plain Buff，战后由 run_combat 快照恢复回滚
         （RULES §3.5 战斗阶段 Buff 不延续）
      4. 三个数字在 Action 列表构造时一并求值，互不影响（每个随从按
         自身战前属性独立三倍）

    Test: test_batch_trinkets2.py — 无类型随从 ×3（含已带 buff 的
     随从）/ 有类型随从不变 / 真实 run_combat 后回滚

    Params: 无模板参数（倍率 3 = 文本字面量 "Triple"）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        out = []
        for m in h.board:
            if m.dead or m.race != Race.NONE:
                continue
            out.append(Buff(m, atk=m.atk * 2, health=m.max_health * 2))
        return out or None


# ══════════════════ BG30_MagicItem_414 / 414t Kodo Leather Pouch ══════════

class KodoLeatherPouchScript:
    """
    Natural language: [x]After you buy a card, give two random friendly
    minions +2/+1.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品——离场/淘汰自动注销）:
         a) MINION_BOUGHT（minion=）: `minion.controller is hero`
            （酒馆随从在 refresh_tavern 以 controller=hero 创建，
            购买者判定成立）
         b) "spell_bought"（spell=, hero=）: `hero is 本人`——"buy a
            card" 覆盖酒馆法术（事件名无 events.py 常量，用字面量）
      2. 触发: 候选 = 本人棋盘存活随从; 随机抽 **min(2, n) 个不重复**
         （game.rng.sample——"two random friendly minions" 为两个不同
         随从; 不足 2 个则给全部，官方"最多两个"语义）
      3. 每个获得 +2/+1 永久 Buff（候选不足时落空不补）
      4. 只看购买事件，卖出/刷新不计

    Test: test_batch_trinkets2.py — 买随从后恰好 2 个随从共 +4/+2 /
     买酒馆法术同样触发 / 对手购买不触发（owner 隔离）/ 414t +8/+8

    Params: atk=2 health=1（文本字面量——CardDef 无模板参数;
            414t atk=4 health=4）
    """

    buff_atk = 2      # 文本字面量 "+2/+1"（414t "+4/+4" 子类覆写）
    buff_health = 1

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        script = source.scripts

        def _give(g):
            cands = [m for m in h.board if not m.dead]
            if not cands:
                return
            k = min(2, len(cands))
            picks = (list(cands) if k == len(cands)
                     else g.rng.sample(cands, k, label="kodo_leather_pouch"))
            for m in picks:
                g.run_actions(Buff(m, atk=script.buff_atk,
                                   health=script.buff_health))

        def on_minion_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            _give(g)

        def on_spell_bought(g, spell=None, hero=None, **kw):
            if spell is None or hero is not h:
                return
            _give(g)

        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_minion_bought))
        game.events.register(Listener(event="spell_bought", owner=source,
                                      callback=on_spell_bought))
        return None


class KodoLeatherPouchGreaterScript(KodoLeatherPouchScript):
    """
    Natural language: [x]After you buy a card, give two random friendly
    minions +4/+4.（BG30_MagicItem_414t）

    Formal spec: 同基础版，buff_atk=4 / buff_health=4（文本字面量）
    ——414/414t 是两个独立 CardDef id，数值差异由子类常量表达。

    Test: test_batch_trinkets2.py — 买随从后恰好 2 个随从共 +8/+8

    Params: atk=4 health=4（文本字面量——CardDef 无模板参数）
    """

    buff_atk = 4
    buff_health = 4


# ══════════════════ BG30_MagicItem_437 Staff of the Scourge ══════════════

class StaffOfTheScourgeScript:
    """
    Natural language: <b>Avenge (5):</b> Give a random friendly Undead
    <b>Reborn</b>.

    Formal spec:
      1. Avenge 阈值 5 = `avenge_threshold` 类属性（引擎 avenge 协议:
         _process_single_death 对 hero.trinkets 计数，达阈值清零并调
         `avenge` 钩子）——CardDef 无模板参数（data 只标 avenge=true），
         数值取文本字面量 "Avenge (5)"
      2. avenge: 候选 = 本人棋盘存活 Undead（race UNDEAD 或 ALL ——
         Amalgam 规则）; 无候选 → 落空; `game.rng.choice` 随机 1 个
      3. GainKeyword(REBORN)（Action——avenge 经 run_script_hook 分发，
         返回值照常入队）; 战斗期授予，战后快照恢复回滚（RULES §3.5）
      4. 只作用于本人随从（hero = source.controller）

    Test: test_batch_trinkets2.py — 第 4 次友方死亡不触发 / 第 5 次
     恰好 1 个 Undead 获 Reborn 且计数清零 / 非 Undead 不获 / 阈值与
     CardDef 文本一致

    Params: avenge_threshold=5（文本字面量 "Avenge (5)"）
    """

    avenge_threshold = 5   # 文本字面量（CardDef 无模板参数）

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        cands = [m for m in h.board
                 if not m.dead and m.race in _UNDEAD_RACES]
        if not cands:
            return None
        pick = game.rng.choice(cands, label="staff_of_the_scourge")
        return GainKeyword(pick, GameTag.REBORN)


# ══════════════════ BG30_MagicItem_542 Emerald Dreamcatcher ══════════════

class EmeraldDreamcatcherScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Set your Dragons' Attack
    to the highest in your warband.

    Formal spec:
      1. start_of_combat: highest = max(本人棋盘存活随从 atk)（战团 =
         棋盘随从，含非龙; 空棋盘 → 落空）
      2. 对每个己方龙（race DRAGON 或 ALL）: Buff(atk = highest −
         自身 atk)。"Set" 语义: 由于 highest ≥ 任意自身 atk，差值恒
         ≥ 0，效果等价于直接设为最高值（不会降低任何龙）
      3. 战斗期增益为 plain Buff，战后快照恢复回滚（RULES §3.5）
      4. 非龙不参与也不受影响

    Test: test_batch_trinkets2.py — 龙攻击力抬到战团最高（非龙最高者
     也计入）/ 非龙不变 / 已是最高者不变 / 空棋盘落空

    Params: 无数值参数（"the highest in your warband" 为运行时聚合）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = [m for m in h.board if not m.dead]
        if not living:
            return None
        highest = max(m.atk for m in living)
        out = []
        for m in living:
            if m.race not in _DRAGON_RACES:
                continue
            delta = highest - m.atk
            if delta > 0:
                out.append(Buff(m, atk=delta))
        return out or None


# ══════════════════ BG30_MagicItem_427 / 427t Tiger Carving ══════════════

class TigerCarvingScript:
    """
    Natural language: [x]Whenever a friendly minion takes damage, give
    another friendly minion +3/+1 permanently.

    Formal spec:
      1. on_bind 注册监听器（owner=饰品）:
         a) DAMAGE（minion=, amount=, source=）: `minion.controller is
            本人` 且 amount > 0（圣盾抵消 amount=0 不算受伤）
         b) COMBAT_END（hero_a=, hero_b=）: "permanently" 的持久化时点
      2. 触发: 候选 = 本人棋盘存活随从且 **排除受伤者**（"another"）;
         无候选 → 落空; game.rng.choice 随机 1 个 → +num(0)/+num(1)
      3. 受伤者当次死亡也触发（damage 广播先于死亡处理，T433 同口径）
      4. **"permanently" 建模**（引擎缺口规避，非近似）: run_combat 在
         finally 里无条件用战前快照 restore_state 回滚**全部**战斗期
         buff（既不读 Buff.temporary 也无 per-buff 持久标记），故战斗内
         即时施加（影响本场战斗）+ 记入 pending，COMBAT_END（本英雄
         参战——含幽灵战）快照恢复**之后**对仍在棋盘的原实体重放一次
         永久 Buff → 净效果等于官方"永久"。招募期受伤不在战斗快照
         范围，直接永久生效且不入 pending（防双计）。
      5. 战斗召唤物（不在战前棋盘）COMBAT_END 时已移除 → 跳过（本就不
         跨战斗存续）
      6. **防双计**: 引擎已持久化战斗增益的随从（Tarecgosa 家族
         PERSIST_COMBAT_CHANGES / 相邻 Persistent Poet 的龙）重放会
         把同一份 Tiger 增益算两次 → 这些目标跳过重放（其增益已由
         引擎持久面保留）

    Test: test_batch_trinkets2.py — 招募期受伤另一随从 +3/+1（恰好
     一个，受伤者被排除）/ 对手随从受伤不触发（owner 隔离）/
     run_combat 后永久保留 net +3/+1（真实快照回滚 + 重放）/ 427t
     +6/+2

    Params: {0}=3 {1}=1（427 num(0)/num(1)）; {0}=6 {1}=2（427t）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        pending: list = []

        def on_damage(g, minion=None, amount=None, **kw):
            if minion is None or not amount:
                return
            if minion.controller is not h:
                return
            cands = [m for m in h.board if not m.dead and m is not minion]
            if not cands:
                return
            pick = g.rng.choice(cands, label="tiger_carving")
            atk = _num(g, source.card_id, 0)
            health = _num(g, source.card_id, 1)
            g.run_actions(Buff(pick, atk=atk, health=health))
            if getattr(g, "_active_combat", None) is not None:
                pending.append((pick, atk, health))

        def _already_persisted(m):
            """引擎已把该随从的战斗增益持久化 → 重放会双计，跳过。

            - PERSIST_COMBAT_CHANGES（Tarecgosa 池卡/暗赠/金 Poet）:
              run_combat 按捕获总增益重放
            - 相邻 ADJACENT_PERSIST_SOURCE 的龙（Persistent Poet）:
              poet_persist 重放
            战后棋盘已复原为战前排布，故此处邻接判定与战前一致。
            """
            if m.has(GameTag.PERSIST_COMBAT_CHANGES):
                return True
            if m.race not in _DRAGON_RACES:
                return False
            if m not in h.board:
                return False
            idx = h.board.index(m)
            for j in (idx - 1, idx + 1):
                if 0 <= j < len(h.board) and \
                        h.board[j].has(GameTag.ADJACENT_PERSIST_SOURCE):
                    return True
            return False

        def on_combat_end(g, hero_a=None, hero_b=None, **kw):
            if h is not hero_a and h is not hero_b:
                return
            for m, atk, health in pending:
                if m in h.board and not m.dead and not _already_persisted(m):
                    g.run_actions(Buff(m, atk=atk, health=health))
            pending.clear()

        game.events.register(Listener(event=DAMAGE, owner=source,
                                      callback=on_damage))
        game.events.register(Listener(event=COMBAT_END, owner=source,
                                      callback=on_combat_end))
        return None


# ══════════════════ BG30_MagicItem_900 / 900t Dragonwing Glider ══════════

class DragonwingGliderScript:
    """
    Natural language: Whenever you play a card, give a friendly Dragon
    +{0}/+{1}.

    Formal spec:
      1. on_bind 注册监听器（owner=饰品）: CARD_PLAYED（card=）——
         随从与法术打出路径都 fire（play_minion 常规/磁力 +
         play_spell），"play a card" 全覆盖; `card.controller is 本人`
         保证 owner 隔离（对手打出不触发）
      2. 触发: 候选 = 本人棋盘存活龙（race DRAGON 或 ALL——Amalgam
         规则）; 无候选 → 落空; 文本无 "Choose"/[Targeted] → 随机 1 个
         （SOP §9 目标语义裁决库）; game.rng.choice
      3. +num(0)/+num(1) 永久 Buff（招募期打出 → 不涉及战斗回滚）
      4. 900/900t 用同一类，数值经各自 CardDef.num() 自然体现

    Test: test_batch_trinkets2.py — 打出随从后随机 1 条龙 +num/+num /
     打出法术同样触发 / 无龙落空 / 对手打出不触发 / 900t num 不同

    Params: {0}=4 {1}=4（900）; {0}=6 {1}=4（900t）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, **kw):
            if card is None or card.controller is not h:
                return
            cands = [m for m in h.board
                     if not m.dead and m.race in _DRAGON_RACES]
            if not cands:
                return
            pick = g.rng.choice(cands, label="dragonwing_glider")
            g.run_actions(Buff(pick, atk=_num(g, source.card_id, 0),
                               health=_num(g, source.card_id, 1)))

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG30_MagicItem_970 / 970t Valorous Medallion ══════════

class ValorousMedallionScript:
    """
    Natural language: <b>Start of Combat:</b> Give your minions +2/+2.

    Formal spec:
      1. start_of_combat: 本人棋盘全部存活随从各获 +buff_atk/
         +buff_health plain Buff
      2. 战斗期增益战后由 run_combat 快照恢复回滚（RULES §3.5——
         官方 SoC 增益仅本场）
      3. 970/970t 两个独立 CardDef id，数值差异由子类常量表达
         （CardDef 无模板参数）

    Test: test_batch_trinkets2.py — 全体 +2/+2（含本回合新入场者）/
     无随从落空 / run_combat 后回滚 / 970t +6/+6

    Params: atk=2 health=2（970 文本字面量）; 970t atk=6 health=6
    """

    buff_atk = 2      # 文本字面量 "+2/+2"（970t "+6/+6" 子类覆写）
    buff_health = 2

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        script = source.scripts
        out = [Buff(m, atk=script.buff_atk, health=script.buff_health)
               for m in h.board if not m.dead]
        return out or None


class ValorousMedallionGreaterScript(ValorousMedallionScript):
    """
    Natural language: <b>Start of Combat:</b> Give your minions +6/+6.
    （BG30_MagicItem_970t）

    Formal spec: 同基础版，buff_atk=6 / buff_health=6（文本字面量）。

    Test: test_batch_trinkets2.py — 全体 +6/+6

    Params: atk=6 health=6（文本字面量——CardDef 无模板参数）
    """

    buff_atk = 6
    buff_health = 6


# ══════════════════ BG30_MagicItem_925 Ceremonial Sword ══════════════════

class CeremonialSwordScript:
    """
    Natural language: Whenever a friendly minion attacks, give it +4
    Attack.

    Formal spec:
      1. on_bind 注册监听器（owner=饰品）: BEFORE_ATTACK（attacker=,
         defender=）——combat.py:220 在**伤害结算前**广播（与 Rally 同
         时点），故 +4 计入本次攻击的攻击力快照（attacker.atk 于
         combat.py:227 读取）; 招募期攻击（game._execute_attack）同
         事件同口径
      2. 仅 `attacker.controller is 本人`（owner 隔离）; 攻击者死亡前
         的每次攻击（含风怒第二次）各触发一次
      3. 战斗期增益战后快照恢复回滚（RULES §3.5——文本无 "permanently"）

    Test: test_batch_trinkets2.py — 单次攻击后攻击者 +4 且本次伤害
     已含 +4（对高血目标验算）/ 对手攻击不触发 / 风怒连续两次各 +4

    Params: atk=4（文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_attack(g, attacker=None, **kw):
            if attacker is None or attacker.dead:
                return
            if attacker.controller is not h:
                return
            g.run_actions(Buff(attacker, atk=4))

        game.events.register(Listener(event=BEFORE_ATTACK, owner=source,
                                      callback=on_attack))
        return None


# ══════════════════ BG32_MagicItem_270 / 270t Wicked Tome ══════════════

class WickedTomeScript:
    """
    Natural language: [x]<b>Avenge (3):</b> Your Tavern spells give an
    extra +1 Attack this game.

    Formal spec:
      1. Avenge 阈值 3 = `avenge_threshold` 类属性（引擎对 hero.trinkets
         计数）; CardDef 无模板参数（data 只标 avenge=true），数值取
         文本字面量 "Avenge (3)"
      2. avenge: 本人 hero 的 `TAVERN_SPELL_EXTRA_ATK`(1053) += 1
         （叠加式，"this game" 永久累积）
      3. **消费点核实**（SOP §14 假接线排查）: 读取方
         `actions/racefx.tavern_spell_buff`（构造 Buff 时叠加
         TAVERN_SPELL_EXTRA_ATK/HEALTH），生产调用点遍布
         spells/spells2/spells3/spells4/spells_final/choose_one/rally/
         rally2/misc/eot_sot 等真实酒馆法术脚本 → 非空转
      4. 只写本人 hero 级 tag，不污染对手

    Test: test_batch_trinkets2.py — 第 2 次死亡不触发 / 第 3 次后
     TAVERN_SPELL_EXTRA_ATK=1 且计数清零 / tavern_spell_buff 出口
     实际多给 +1 攻 / 对手 tag 不变 / 270t 额外 +1/+1 Avenge(4)

    Params: avenge_threshold=3（文本字面量 "Avenge (3)"）;
             atk=1（文本字面量 "extra +1 Attack"）
    """

    avenge_threshold = 3   # 文本字面量（CardDef 无模板参数）

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        h.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
              h.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + 1)
        return None


class WickedTomeGreaterScript(WickedTomeScript):
    """
    Natural language: [x]<b>Avenge ({0}):</b> Your Tavern spells give an
    extra +{1}/+{2} this game.（BG32_MagicItem_270t）

    Formal spec:
      1. avenge_threshold = 4 = num(0)（文本占位 {0}——引擎 avenge 协议
         要求类属性常量，故此处固化并在测试中与 CardDef.num(0) 比对，
         数据漂移即红）
      2. avenge: TAVERN_SPELL_EXTRA_ATK += num(1)（=1）、
         TAVERN_SPELL_EXTRA_HEALTH += num(2)（=1）——双属性叠加
      3. 消费点同基础版（racefx.tavern_spell_buff 叠加攻/血两路）

    Test: test_batch_trinkets2.py — 第 4 次死亡后
     TAVERN_SPELL_EXTRA_ATK/HEALTH 各 +num(1)/+num(2) 且
     avenge_threshold == CardDef.num(0)

    Params: avenge_threshold=4 {1}=1 {2}=1（BG32_MagicItem_270t num(0/1/2)）
    """

    avenge_threshold = 4   # = CardDef.num(0)（文本 "Avenge ({0})"）

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        h.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
              h.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0)
              + _num(game, source.card_id, 1))
        h.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
              h.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
              + _num(game, source.card_id, 2))
        return None


# ══════════════════ BG30_MagicItem_544 / 544t Nomi Sticker ══════════════

class NomiStickerScript:
    """
    Natural language: [x]After you play an Elemental, give Elementals in
    the Tavern +{0}/+{1} this game.

    Formal spec:
      1. on_bind 注册监听器（owner=饰品）: CARD_PLAYED（card=）——
         engine 无 ELEMENTAL_PLAYED fire（batch_hero_passives2 缺口 #2
         先例），经 card_played + 种族过滤等价实现:
         card 是 Minion 且 `controller is 本人` 且 race ∈ (ELEMENTAL,
         ALL)（Amalgam 规则）
      2. 每次触发: TavernBuff(atk=num(0), health=num(1),
         race_filter=ELEMENTAL)——立即面 BuffCurrentTavern（当前馆内
         元素即时 +X/+Y，购买带走）+ 持久面 ApplyTavernBuff（登记
         hero.tavern_buffs，refresh_tavern 对新入馆元素自动应用——
         "this game" 累积: 打出 N 只元素后新入馆元素共 +N·X/+N·Y）。
         与同文本 family 的 Void Pup Trainer / Overlord Saurfang 先例
         同构（"give X in the Tavern +N this game" = 持久光环）
      3. 非元素打出不触发; 对手打出不触发（controller 过滤）
      4. 544/544t 数值经各自 num(0)/num(1) 自然体现

    Test: test_batch_trinkets2.py — 打出元素后馆内元素即时 +num/+num
     且登记持久条 / 刷新后新入馆元素继承（active_races 限定元素）/
     非元素打出不触发 / 对手打出不触发

    Params: {0}=2 {1}=2（544）; {0}=5 {1}=5（544t）
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
            tb = TavernBuff(atk=_num(g, source.card_id, 0),
                            health=_num(g, source.card_id, 1),
                            race_filter=Race.ELEMENTAL,
                            source_id=source.card_id)
            g.run_actions([ApplyTavernBuff(h, tb),
                           BuffCurrentTavern(h, tb)])

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG30_MagicItem_547 / 547t Comfy Coffin ══════════════

class ComfyCoffinScript:
    """
    Natural language: [x]Whenever you cast a Tavern spell, your Undead
    have +1 Attack this game <i>(wherever they are)</i>.

    Formal spec:
      1. on_bind 注册监听器（owner=饰品）: TAVERN_SPELL_CAST（spell=）
         ——引擎只对 `is_pool_spell` 法术广播（game.py:955），正是
         "Tavern spell" 语义; `spell.controller is 本人` owner 隔离
      2. 每次触发: ApplyRaceAura(hero, UNDEAD, atk=1, health=0)——
         hero.race_auras 叠加式永久光环，经 Minion._aura_atk 对
         棋盘/手牌/**未来获得**的亡灵实时生效（"wherever they are"）
      3. 法术双施（Balinda）按施放次数广播 → 每次各 +1（官方按触发
         次数计）
      4. 547/547t 两个独立 id，数值差异由子类常量表达

    Test: test_batch_trinkets2.py — 施放酒馆法术时 aura=(bonus,0) /
     棋盘亡灵 atk 抬高 / 之后新召唤的亡灵同样享受 / 对手施放不生效 /
     547t +2

    Params: atk=1（547 文本字面量 "+1 Attack"）; 547t atk=2
    """

    attack_bonus = 1      # 文本字面量 "+1 Attack"（547t "+2" 子类覆写）

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        bonus = source.scripts.attack_bonus

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            g.run_actions(ApplyRaceAura(h, Race.UNDEAD, atk=bonus,
                                        health=0, source_id=source.card_id))

        game.events.register(Listener(event=TAVERN_SPELL_CAST, owner=source,
                                      callback=on_cast))
        return None


class ComfyCoffinGreaterScript(ComfyCoffinScript):
    """
    Natural language: [x]Whenever you cast a Tavern spell, your Undead
    have +2 Attack this game <i>(wherever they are)</i>.
    （BG30_MagicItem_547t）

    Formal spec: 同基础版，attack_bonus=2（文本字面量——CardDef 无
    模板参数）

    Test: test_batch_trinkets2.py — 547t aura=(2,0)

    Params: atk=2（文本字面量——CardDef 无模板参数）
    """

    attack_bonus = 2


# ══════════════ BG30_MagicItem_714 Precious Pearl (Spellcraft) ══════════

class PreciousPearlScript:
    """
    Natural language: <b>Spellcraft:</b> Give a minion +30/+30 until next
    turn.

    Formal spec:
      1. 授予路径复用引擎既有 Spellcraft 原语
         `spellcraft.grant_spellcraft_spell`（随从 on_summon 同源函数）:
         读 source（饰品实体）CardDef.spellcraft_id(117945) → 生成
         Harvested Pearl（BG30_MagicItem_714t）法术实体并
         pending_hand_add（满手排队不销毁，RULES §3.3）
      2. on_bind（购买时点——Spellcraft 随从"打出即得第一张"
         RULES §6.13 的饰品等价时点）
      3. 每回合的再次生成由**引擎**负责（2026-09-02: `spellcraft.
         generate_for_hero` 扫描域扩展到 `hero.trinkets` + `create_entity`
         依 `spellcraft_id` 打 SPELLCRAFT tag）——脚本**不得**再写
         `start_of_turn`，否则每回合双发
      4. 未使用的 Spellcraft 法术由 end_recruit_phase 统一丢弃
         （grant 已置 SPELLCRAFT tag，引擎丢弃路径识别）
      5. 法术效果本体见 HarvestedPearlSpellScript

    Test: test_batch_trinkets2.py — 绑定即入手 1 张 Harvested Pearl
     （带 SPELLCRAFT tag）/ 次回合开始再得 1 张 / 对手手牌不受影响 /
     打出后目标 +30/+30 且下一回合开始回落

    Params: 无模板参数（授予物 id 经 CardDef.spellcraft_id 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)     # 获得时立即给第一张
        return None

    # 每回合的再生成由引擎 `generate_for_hero`（trinkets 扫描域）负责


class HarvestedPearlSpellScript:
    """
    Natural language: [x]Give a minion +30/+30 until next turn.
    （BG30_MagicItem_714t; Precious Pearl 的 Spellcraft 法术 token）

    Formal spec:
      1. needs_target=True → play_spell 产生 PendingChoice(
         kind="spell_target")（候选默认全体友方存活随从——game.py:898）;
         显式 target 直接结算
      2. on_play: target 获得 temporary +30/+30 附魔（entity.Buff——
         附魔类，非 Action）; target=None（无候选落空路径）→ 无效果，
         法术照常消耗（play_spell 语义）
      3. "until next turn" = 目标控制者的**下一个招募阶段开始**精确
         移除本次附魔（scripts/spells.py `_expire_at_next_turn`——
         Spellcraft 家族统一过期先例; 引擎 clear_temporary_buffs 无
         调用点，故脚本侧过期）
      4. 该法术非池法术（is_pool_spell=False）→ 不是 Tavern spell，
         不走 tavern_spell_buff（"Your Tavern spells give an extra"
         不适用）

    Test: test_batch_trinkets2.py — 定向施放目标 +atk/+health /
     下一招募阶段开始回落 / 无目标（无候选）落空

    Params: atk=30 health=30（文本字面量——CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        buff = entity.Buff(atk=30, health=30, temporary=True,
                           source_id=source.card_id)
        target.add_buff(buff)
        _expire_at_next_turn(game, source, target, buffs=[buff])
        return None


# ══════════════════ 注册 ══════════════════

def register() -> list[str]:
    """注册饰品第二批 20 张 + Harvested Pearl 法术 token（21 个 id）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_847", GoblinWalletScript),
        ("BG30_MagicItem_403", IronforgeAnvilScript),
        ("BG30_MagicItem_414", KodoLeatherPouchScript),
        ("BG30_MagicItem_414t", KodoLeatherPouchGreaterScript),
        ("BG30_MagicItem_437", StaffOfTheScourgeScript),
        ("BG30_MagicItem_542", EmeraldDreamcatcherScript),
        ("BG30_MagicItem_427", TigerCarvingScript),
        ("BG30_MagicItem_427t", TigerCarvingScript),
        ("BG30_MagicItem_900", DragonwingGliderScript),
        ("BG30_MagicItem_900t", DragonwingGliderScript),
        ("BG30_MagicItem_970", ValorousMedallionScript),
        ("BG30_MagicItem_970t", ValorousMedallionGreaterScript),
        ("BG30_MagicItem_925", CeremonialSwordScript),
        ("BG32_MagicItem_270", WickedTomeScript),
        ("BG32_MagicItem_270t", WickedTomeGreaterScript),
        ("BG30_MagicItem_544", NomiStickerScript),
        ("BG30_MagicItem_544t", NomiStickerScript),
        ("BG30_MagicItem_547", ComfyCoffinScript),
        ("BG30_MagicItem_547t", ComfyCoffinGreaterScript),
        ("BG30_MagicItem_714", PreciousPearlScript),
        # Precious Pearl 的 Spellcraft 法术 token（BG30_MagicItem_714t
        # "Harvested Pearl"，CardDef.spellcraft_id=117945——非池法术）
        ("BG30_MagicItem_714t", HarvestedPearlSpellScript),
    ]
    registered = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
