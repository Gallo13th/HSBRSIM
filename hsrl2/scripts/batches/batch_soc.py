"""批次 soc — 10 张 Start of Combat 池随从（作业单 2026-08-21）。

覆盖: BG24_500 Amber Guardian / BG26_354 Choral Mrrrglr /
BG26_805 Humming Bird / BG27_556 Diremuck Forager / BG31_999 Stitched
Salvager / BG32_330 Flighty Scout / BG32_822 Fire-forged Evoker /
BG34_142 Costume Enthusiast / BG36_245 Runic Arcanist / BG36_620
Boom-in-a-Box（含金色 id; 金色=独立卡定义）。

实现状态总览（详见各类 docstring）:
  OK:       BG24_500 / BG26_354 / BG26_805 / BG27_556 / BG31_999 /
            BG32_822 / BG34_142 / BG36_245（含金色注册）
  DEFERRED: BG32_330 Flighty Scout（SoC 手牌触发点）/ BG36_620
            Boom-in-a-Box（SoC 无法定位当前战斗对手棋盘）

SoC 顺序保证（combat.py _start_of_combat_phase, RULES §4.2）: 饰品 →
任务奖励 → 随从（棋盘左→右）→ 英雄技能。战斗内 SoC buff 为 plain
Buff——战后快照恢复自动清除（RULES §3.5，官方 SoC 增益仅本场）。

引擎缺口报告（本批次发现，主线处理）:
  1. **手牌 SoC 触发点缺失**: _start_of_combat_phase 只遍历
     hero.board → "If this minion is in your hand" 类 SoC（Flighty
     Scout）永不触发（对照: SoT 已有手牌钩子 _begin_recruit_for B4）。
  2. **SoC 无法定位当前战斗对手**: run_combat 不向脚本层暴露战斗对
     (a, b)（ctx={}、game 无 current combat 属性）→ "all other
     minions" 含敌方的 SoC（Boom-in-a-Box）不可实现; 遍历 game.heroes
     在 >2 人局会误伤非参战英雄棋盘且其变化不在战斗快照内（不可回滚
     的越权写），禁止近似。需 ctx 传 opponent 或 game 暴露当前战斗对。
  3. **SoC 随从快照列表不跳过执行期间死亡者**: `for m in
     list(hero.board)` 的快照在钩子执行期间不重估——金色 Stitched
     Salvager 摧毁右邻后，引擎仍会对已死右邻补跑其 SoC 钩子（call_script
     无 dead 检查）。本批次金色 Salvager 测试避开该形态。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainKeyword
from hsrl2.events import AFTER_ATTACK, SUMMON, TAVERN_SPELL_CAST, Listener
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

_DRAGON_RACES = (Race.DRAGON, Race.ALL)      # ALL 视为所有种族 (RULES §6.18)
_BEAST_RACES = (Race.BEAST, Race.ALL)
_MURLOC_RACES = (Race.MURLOC, Race.ALL)

SHINY_RING_ID = "BG28_168"   # 文本指名卡（Runic Arcanist 无数据链字段，
                             # 卡 id 字面量——Firescale Hoarder 同先例）


def _hand_minions(hero) -> list:
    """手牌中的随从实体（法术/其他实体不参与属性聚合）。"""
    return [c for c in hero.hand
            if isinstance(c, Minion) and not c.dead]


# ══════════════════ BG24_500 Amber Guardian ══════════════════


class AmberGuardianScript:
    """
    Natural language: [x]<b>Taunt</b>
    <b>Start of Combat:</b> Give another
     friendly Dragon +{0}/+{1}
    and <b>Divine Shield</b>.

    Formal spec:
      1. SoC（单次触发）: 候选 = 同棋盘存活、非 source（"another"）、
         race ∈ (DRAGON, ALL) 的随从; 无候选 → 落空
      2. 随机 1 条（rng.choice）获得 +num(0)/+num(1) Buff 与
         Divine Shield（GainKeyword，fire keyword_gained）
      3. Taunt 由 create_minion 关键词映射（CardDef.keywords 权威）
      4. 战斗内 Buff/DS 经快照恢复战后回滚（RULES §3.5）
      5. 金色 "two other friendly Dragons" → times=2（rng.sample 抽
         2 条不同; 候选不足给 min(2, n) 条——金色注册类）

    Test: test_batch_soc.py — 随机另一条龙 +num/+num 且获 DS / 自身与
    非龙不受 / 无候选落空 / 金色两条

    Params: {0}=2 {1}=2（36.2.2 基线，金色同值）
    """

    times = 1   # 金色 "two" → 2（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        candidates = [m for m in hero.board
                      if m is not source and not m.dead
                      and m.race in _DRAGON_RACES]
        if not candidates:
            return None
        n = min(source.scripts.times, len(candidates))
        picks = (candidates if n == len(candidates)
                 else game.rng.sample(candidates, n,
                                      label="amber_guardian_dragons"))
        actions = []
        for m in picks:
            actions.append(Buff(m, atk=d.num(0), health=d.num(1)))
            actions.append(GainKeyword(m, GameTag.DIVINE_SHIELD))
        return actions


class AmberGuardianGoldenScript(AmberGuardianScript):
    """
    Natural language: [x]<b>Taunt</b>
    <b>Start of Combat:</b> Give two
     other friendly Dragons +{0}/+{1}
    and <b>Divine Shield</b>.

    Formal spec: 同基础版，times=2——rng.sample 抽 **2 条不同**友方龙
    （候选仅 1 条时给 1 条，官方"最多"语义）。

    Test: test_batch_soc.py — 金色两条龙各获 buff+DS

    Params: {0}=2 {1}=2（金色 CardDef 同值）
    """

    times = 2


# ══════════════════ BG26_354 Choral Mrrrglr ══════════════════


class ChoralMrrrglrScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Gain
    the stats of all the
    minions in your hand.

    Formal spec:
      1. SoC: Σ(手牌全部 Minion 的 atk) 与 Σ(手牌全部 Minion 的
         max_health)——属性聚合用 max_health（SOP §3 快照纪律），
         法术/其他实体不参与; 空手牌（或全法术）→ 落空
      2. Buff(self, Σatk, Σhp)——战斗内 plain buff，战后快照恢复
         清除（官方: 战斗内获得、战后消失，RULES §3.5）
      3. 手牌实体不被消耗/修改（只读聚合）
      4. 金色 "twice" → passes=2（两次独立 Buff，金色注册类）

    Test: test_batch_soc.py — Σ 属性入手（法术不计）/ 空手落空 /
    战后回滚 / 金色 ×2

    Params: 无数值参数（"all the minions in your hand" 无模板参数）
    """

    passes = 1   # 金色 "twice" → 2（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hand = _hand_minions(hero)
        if not hand:
            return None
        atk = sum(m.atk for m in hand)
        hp = sum(m.max_health for m in hand)
        return [Buff(source, atk=atk, health=hp)
                for _ in range(source.scripts.passes)]


class ChoralMrrrglrGoldenScript(ChoralMrrrglrScript):
    """
    Natural language: [x]<b>Start of Combat:</b> Gain
    the stats of all the minions
    in your hand twice.

    Formal spec: 同基础版，passes=2——同一 Σ 值施加两次独立 Buff
    （净效果 2×Σ）。

    Test: test_batch_soc.py — 金色净得 2×Σ

    Params: 无数值参数（"twice" 为金色文本字面量）
    """

    passes = 2


# ══════════════════ BG26_805 Humming Bird ══════════════════


class HummingBirdScript:
    """
    Natural language: <b>Start of Combat:</b> For the rest of this
    combat, your Beasts have +1 Attack.

    Formal spec:
      1. SoC: 对同棋盘全部存活 Beast（race ∈ (BEAST, ALL)，含 source
         自身——文本 "your Beasts" 无 "other"，Humming Bird 是 Beast）
         各 Buff(+attack_bonus, 0)
      2. "For the rest of this combat" = 光环式: 战斗中**后续入场**的
         友方 Beast 同样 +attack_bonus——注册 SUMMON 事件监听器
         （owner=source: 随从战中阵亡即注销——官方光环随源失效;
         监听器在战斗中注册、不在战前快照内 → 战后随监听器表恢复
         消失，天然"仅本场"）
      3. 战斗内 Buff 经快照恢复战后回滚（RULES §3.5）
      4. 金色 "+2 Attack" → attack_bonus=2（金色注册类）

    Test: test_batch_soc.py — 全部 Beast（含自身）+1 / 非兽 +0 /
    战斗中新召 Beast 同享 / 源阵亡后新召兽不再加 / 战后回滚 / 金色 +2

    Params: 无数值参数（"+1" 为文本字面量，CardDef 无模板参数）
    """

    attack_bonus = 1   # 金色 "+2" → 2（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        bonus = source.scripts.attack_bonus
        actions = [Buff(m, atk=bonus, health=0)
                   for m in hero.board
                   if not m.dead and m.race in _BEAST_RACES]

        def on_combat_summon(g, minion=None, **kw):
            g.run_actions(Buff(minion, atk=bonus, health=0))

        game.events.register(Listener(
            event=SUMMON,
            owner=source,
            condition=lambda minion=None, **kw: (
                minion is not None
                and not minion.dead
                and minion.controller is hero
                and minion.race in _BEAST_RACES),
            callback=on_combat_summon,
        ))
        return actions or None


class HummingBirdGoldenScript(HummingBirdScript):
    """
    Natural language: <b>Start of Combat:</b> For the rest of this
    combat, your Beasts have +2 Attack.

    Formal spec: 同基础版，attack_bonus=2（金色文本数值）。

    Test: test_batch_soc.py — 金色在场/新召 Beast +2

    Params: 无数值参数（"+2" 为金色文本字面量）
    """

    attack_bonus = 2


# ══════════════════ BG27_556 Diremuck Forager ══════════════════


class DiremuckForagerScript:
    """
    Natural language: <b>Start of Combat:</b> When you have space,
    summon the highest-Attack Murloc from your hand
    for this combat only.

    Formal spec:
      1. SoC: 重复 count 次（基础 1; 金色 "the two highest-Attack
         Murlocs" → 2——同一次内不重复选取同一手牌实体）:
          a) "when you have space": board_full 预检——有空位即召唤
             （game.summon 的 MINION_OVERFLOW 双保险）
          b) 候选 = hero.hand 中全部存活 Minion、race ∈ (MURLOC, ALL)、
             排除本次已选取者; 无候选 → 剩余作废
          c) 取 atk 最大者（并列 rng.choice 任选; 选取时点读当前手牌
             ——补召窗口读手牌现值）
          d) 召唤**战斗副本**（"for this combat only"，Expert Aviator
             BG34_140 先例）: create_minion(同 card_id, golden 同源)
             + restore_state(手牌实体快照) → game.summon 最右;
             手牌实体不离手（战斗中无手牌交互窗口）; 副本不在战前
             board_before 快照 → 战后随引擎 board 恢复消失（RULES §3.5）
      2. **延后补召**（Evidence 见下）: SoC 时满板 → 注册战斗内
         AFTER_ATTACK 检查点（owner=source， Diremuck 战死即注销;
         战斗中注册的监听器随引擎监听器表快照恢复出队——不外溢
         招募期）; 每次攻击结算后（死亡波次完毕，板位已实释放）
         有空位且有剩余 → 按上款规则补召。
      3. SoC 恒在 run_combat 内触发（in_combat=True）→ 无招募期副本
         滞留问题（Aviator 的 _expire_combat_copy 分支不适用）

    Evidence: "When you have space" = 战斗内条件触发（非 SoC 一次性）:
      - 官方 30.2 patch notes 任务奖励同款句式 "When you have space,
        summon an exact copy of your first Mech **that died each
        combat**"（playhearthstone.com/en-us/blog/24122902）——
        明确的战斗中腾位延迟语义
      - 官方 33.6 patch notes 被动同款句式 "When you have space in
        combat, summon a copy of your highest-Attack minion"
        （playhearthstone.com/en-us/blog/24232759）
      - r/BobsTavern 同族卡 Boon of Beetles 实测: "Full board doesn't
        affect this. It summons when there's space."
        （reddit.com/r/BobsTavern/comments/1dq54cu）
      卡页本身无 Notes（hearthstone.wiki.gg/wiki/Battlegrounds/
      Diremuck_Forager——全文核对）; 35.2.2 文本 "minion"→"Murloc"
      限族（blizzard 35.2.2 patch notes）。wiki 金色框 "+4/+4" 为
      35.2.0 前旧文未更新，XML 36.2.2 金色 = "two highest-Attack
      Murlocs"（权威）。

    Test: test_batch_soc.py — 最高攻 Murloc 副本入场且手牌保留 /
    ALL 种族计入 / 高攻非兽不计 / 空手落空 / 满板 SoC 不召**且战斗中
    腾位后补召** / 战后副本消失 / 金色两只

    Params: 无数值参数（"the highest-Attack Murloc" = 1 只; 金色
    "two" 文本字面量）
    """

    count = 1   # 金色 "the two highest-Attack Murlocs" → 2（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None

        picked: list[Minion] = []          # 单场战斗选取记录
        source._diremuck_picked = picked

        def _try_summon(g) -> None:
            """有空位则召唤至 count 只/无候选/满板（幂等可重入）。"""
            while len(picked) < source.scripts.count:
                if hero.board_full():
                    return
                candidates = [c for c in _hand_minions(hero)
                              if c.race in _MURLOC_RACES
                              and c not in picked]
                if not candidates:
                    return
                top = max(m.atk for m in candidates)
                tied = [m for m in candidates if m.atk == top]
                origin = g.rng.choice(tied, label="diremuck_hand_pick")
                picked.append(origin)
                copy = g.create_minion(origin.card_id, controller=hero,
                                       golden=origin.is_golden)
                copy.restore_state(origin.snapshot_state())
                g.summon(hero, copy)

        _try_summon(game)
        if len(picked) < source.scripts.count:
            # 满板（或边角）→ 战斗内腾位补召
            def on_after_attack(g, **kw):
                _try_summon(g)

            game.events.register(Listener(
                event=AFTER_ATTACK, owner=source,
                callback=on_after_attack))
        return None


class DiremuckForagerGoldenScript(DiremuckForagerScript):
    """
    Natural language: <b>Start of Combat:</b> When you have space,
    summon the two highest-Attack Murlocs from your hand
    for this combat only.

    Formal spec: 同基础版，count=2——攻击降序前 2 个**不同**手牌
    Murloc（含 ALL 种族）; 逐只检查板位（中途满板则中止）。

    Test: test_batch_soc.py — 金色召唤两只最高攻 Murloc

    Params: 无数值参数（"two" 为金色文本字面量）
    """

    count = 2


# ══════════════════ BG31_999 Stitched Salvager ══════════════════


def _stitched_family_ids(game) -> frozenset:
    """Stitched Salvager 卡族 id（基础 + 金色，db 数据链解析）——
    "(Except Stitched Salvager.)" 亡语复制排除用。"""
    ids = {"BG31_999"}     # 本卡基础 id 字面量（自身引用）
    golden = game.db.golden_version(game.db.get("BG31_999"))
    if golden is not None:
        ids.add(golden.id)
    return frozenset(ids)


class StitchedSalvagerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Destroy the
    minion to the left. <b>Deathrattle:</b>
    Summon an exact copy of it.
    ______<i>(Except Stitched Salvager.)</i>___

    Formal spec:
      1. SoC: 目标 = source 左侧相邻随从（board[pos-1]，宣告时锁定
         实体引用——C5 先例）; 无左邻（pos=0）→ 落空
      2. Destroy: 快照目标状态（亡语复制的"exact"数据源）→
         health=0（经 health setter 置 DEAD; 无视圣盾——官方 Destroy
         语义）→ game.check_deaths() 触发死亡波次（目标亡语/复生/
         Avenge 照常，战斗内路径）
      3. 记录: source._stitched_victims = [{card_id, golden, snap}]
         （实体动态属性——Tasty Lobster hero 级先例的实体级版;
         restore_state 只回滚 tags/_buffs → 跨战斗残存，见 5）
      4. Deathrattle: 逐个 summon 精确副本——create_minion(card_id,
         golden 同源) + restore_state(snap) + game.summon（HEALTH
         重算为 max_health——含 buff 血量，game.summon 保证）;
         副本 card_id ∈ _stitched_family_ids → 跳过（"(Except
         Stitched Salvager.)"——防 Salvager 链自我复制）;
         **直接执行模式**（batch_deathrattle2 死亡路径重入规避先例）
       5. 边界: 招募期死亡（S14 recruit_phase_attack 反噬可达）时
          _stitched_victims 为最近一场战斗的记录——按重放上次记录
          处理; 每场战斗 SoC 覆写记录。依据（2026-08-23 查证: 卡页
          wiki.gg/wiki/Battlegrounds/Stitched_Salvager 无 Notes，全文
          核对; 官方无招募期死亡路径记载）——数据源为本卡自身记录，
          重放最近记录是"亡语召唤 exact copy"文本在无本场记录时的
          唯一确定读法，边角上报主线备实测。

    Test: test_batch_soc.py — 左邻被消灭（亡语照常触发）/ 亡语召唤
    含 buff/金色的精确副本 / 左边界落空 / 复制排除 Salvager /
    金色双邻

    Params: 无数值参数（16/4 属性以卡定义为权威）
    """

    adjacent = False   # 金色 "Destroy adjacent minions" → True

    @staticmethod
    def _destroy_targets(source, hero) -> list:
        """宣告时锁定的摧毁目标（左邻; 金色含右邻，board 序）。"""
        board = hero.board
        if source not in board:
            return []
        pos = source.zone_position
        targets = []
        if pos > 0:
            targets.append(board[pos - 1])
        if source.scripts.adjacent and pos + 1 < len(board):
            targets.append(board[pos + 1])
        return targets

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        victims = []
        for target in StitchedSalvagerScript._destroy_targets(source, hero):
            if target is None or target.dead:
                continue   # 已被左邻亡语连锁致死
            victims.append({
                "card_id": target.card_id,
                "golden": target.is_golden,
                "snap": target.snapshot_state(),   # 摧毁前状态（exact 源）
            })
            target.health = 0                       # Destroy: 无视圣盾
            game.check_deaths()
        source._stitched_victims = victims
        return None

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        excluded = _stitched_family_ids(game)
        for v in getattr(source, "_stitched_victims", None) or []:
            if v["card_id"] in excluded:
                continue
            copy = game.create_minion(v["card_id"], controller=hero,
                                      golden=v["golden"])
            copy.restore_state(v["snap"])
            game.summon(hero, copy)
        return None


class StitchedSalvagerGoldenScript(StitchedSalvagerScript):
    """
    Natural language: [x]<b>Start of Combat:</b> Destroy
    adjacent minions. <b>Deathrattle:</b>
    Summon exact copies of them.
    ______<i>(Except Stitched Salvager.)</i>___

    Formal spec:
      1. 同基础版，adjacent=True——目标 = 左右双邻（宣告时锁定引用，
         先左后右 board 序销毁; 左邻亡语连锁致死右邻时右邻跳过——
         引用仍记入 victims? 否: 已 dead 者跳过记录与销毁）
      2. Deathrattle: 依次召唤**每个**被摧毁者的精确副本（Salvager
         卡族除外）

    Test: test_batch_soc.py — 金色双邻被毁、亡语双副本

    Params: 无数值参数（32/8 属性以金色卡定义为权威）
    """

    adjacent = True


# ══════════════════ BG32_822 Fire-forged Evoker ══════════════════


class FireForgedEvokerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give your
    Dragons +{0}/+{1}.
    Improves permanently after
    ____you cast a Tavern spell.

    Formal spec:
      1. SoC: 对同棋盘全部存活 Dragon（race ∈ (DRAGON, ALL)，含 source
         自身——"your Dragons" 无 "other"，Evoker 是 Dragon）各
         Buff(+num(0)×M, +num(1)×M)，M = 1 + 已累积 Improve 次数
      2. Improve（官方 Improve 关键词，Tasty Lobster 先例）: 入场
         （on_summon）注册持久监听器（owner=source，出售/招募期死亡
         自动注销; 战斗快照恢复跨战斗存活）——事件 tavern_spell_cast
         （引擎只对 is_pool_spell 法术 fire，经验库 2026-08-21）且
         施法者 = source.controller 时，source._improve_count += 1
         （实体动态属性——restore_state 不回滚，跨战斗持久 = "this
         game"; 离场重入场归零——官方 Improve 随在场累积）
      3. 每施放一个酒馆法术 M+1（+num(0)/+num(1) 每 cast 一次，
         Tasty Lobster "extra" 同构）
      4. SoC buff 战后快照恢复回滚; Improve 计数不回滚
      5. 金色版文本同构（金色 num=4/2）→ 同一脚本类注册两个 id

    Test: test_batch_soc.py — SoC 全龙 +num（含自身）非龙 +0 / 施放
    酒馆法术后下一场 ×2 / 金色 4/2 / 战后 buff 回滚计数保留

    Params: {0}=2 {1}=1（36.2.2 基线，金色 =4/=2）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_tavern_spell(g, spell=None, **kw):
            source._improve_count = getattr(source, "_improve_count", 0) + 1

        game.events.register(Listener(
            event=TAVERN_SPELL_CAST,
            owner=source,
            condition=lambda spell=None, **kw: (
                spell is not None
                and spell.controller is source.controller),
            callback=on_tavern_spell,
        ))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        mult = 1 + getattr(source, "_improve_count", 0)
        return [Buff(m, atk=d.num(0) * mult, health=d.num(1) * mult)
                for m in hero.board
                if not m.dead and m.race in _DRAGON_RACES]


# ══════════════════ BG34_142 Costume Enthusiast ══════════════════


class CostumeEnthusiastScript:
    """
    Natural language: [x]<b>Divine Shield</b>
    <b>Start of Combat:</b> Gain the
    Attack of the highest-Attack
    minion in your hand.

    Formal spec:
      1. SoC: 取手牌全部存活 Minion 的最大 atk（并列不影响——聚合值
         唯一）; 手牌无随从 → 落空
      2. Buff(source, atk=最大atk × mult, 0)——仅攻击无生命加成;
         战后快照恢复回滚（RULES §3.5）
      3. 手牌随从 atk 为实时值（含其 buff/光环），只读不修改
      4. DS 由 create_minion 关键词映射（CardDef.keywords 权威）
      5. 金色 "double the Attack" → mult=2（金色注册类）

    Test: test_batch_soc.py — +最高攻手牌随从攻击 / 空手落空 /
    金色 ×2 / DS 在场

    Params: 无数值参数（攻击值为运行时聚合，无模板参数）
    """

    mult = 1   # 金色 "double" → 2（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        hand = _hand_minions(hero)
        if not hand:
            return None
        top = max(m.atk for m in hand)
        return Buff(source, atk=top * source.scripts.mult)


class CostumeEnthusiastGoldenScript(CostumeEnthusiastScript):
    """
    Natural language: [x]<b>Divine Shield</b>. <b>Start of
    Combat:</b> Gain double the
    Attack of the highest-Attack
    minion in your hand.

    Formal spec: 同基础版，mult=2。

    Test: test_batch_soc.py — 金色 +2×最高攻

    Params: 无数值参数（"double" 为金色文本字面量）
    """

    mult = 2


# ══════════════════ BG36_245 Runic Arcanist ══════════════════


class RunicArcanistScript:
    """
    Natural language: <b>Start of Combat:</b> Cast Shiny Ring twice.

    Formal spec:
      1. SoC: 施放 Shiny Ring（BG28_168，池法术 T3 "Give your
         minions +{0}/+{1}"，num=1/1——卡 id 字面量: 本卡无数据链
         字段，Firescale Hoarder 先例）casts 次（基础 2 "twice";
         金色 4 "4 times"）
      2. "Cast" 施放语义（docstring 裁定）: 每次 cast = 完整应用一次
         法术效果——对 source 控制者棋盘全部存活随从（含自身，
         "your minions" 无 "other"）各 Buff(+num(0), +num(1));
         **不走 play_spell 路径**——不耗手牌/不占池（效果直施，
         非玩家施放）、不计入 TAVERN_SPELLS_CAST_*、不 fire
         tavern_spell_cast（Fire-forged Evoker 等监听不联动）
      3. 战斗内 plain buff → 战后快照恢复回滚（官方 SoC 增益仅本场）
      4. 逐次独立结算（两次各 +1/+1 全板; 中途死亡者跳过后续 cast）

    Test: test_batch_soc.py — 全板 +2×num / 不计酒馆法术施放数 /
    金色 4 次 / 战后回滚

    Params: 法术侧 {0}=1 {1}=1（BG28_168 CardDef 权威）; casts=2
    （"twice" 文本字面量，金色 4）
    """

    casts = 2   # 金色 "Cast Shiny Ring 4 times" → 4（文本字面量）

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        ring = game.db.get(SHINY_RING_ID)
        if ring is None:
            return None   # 数据缺失（bind_all 已保证存在，防御分支）
        actions = []
        for _ in range(source.scripts.casts):
            actions.extend(
                Buff(m, atk=ring.num(0), health=ring.num(1))
                for m in hero.board if not m.dead)
        return actions or None


class RunicArcanistGoldenScript(RunicArcanistScript):
    """
    Natural language: <b>Start of Combat:</b> Cast Shiny Ring 4 times.

    Formal spec: 同基础版，casts=4。

    Test: test_batch_soc.py — 金色全板 +4×num

    Params: casts=4（金色文本字面量）
    """

    casts = 4


# ══════════════════ 以下为 DEFERRED（不注册 REGISTRY） ══════════════════


class FlightyScoutScript:
    """
    Natural language: [x]<b>Start of Combat:</b> If this
    minion is in your hand,
    summon a copy of it.

    Status: DEFERRED — requires "手牌 SoC 触发点"

    Dependency: CombatScheduler._start_of_combat_phase 只遍历
    hero.board（combat.py L72）→ 手牌中的 Flighty Scout 永远收不到
    SoC 钩子（棋盘上的本卡 "is in your hand" 恒假 = no-op）。需要
    引擎在 SoC 阶段遍历手牌实体（对照: SoT 已有手牌钩子先例
    _begin_recruit_for B4）或为该卡走特殊路径。召唤部分（plain
    copy，金色 "double stats"）可经 SummonPlainCopy+buff 实现，
    但二态纪律下整卡 DEFERRED。引擎缺口已列批次模块 docstring #1。

    Params: 无数值参数（金色 "double stats" 文本字面量）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        return None


class BoomInABoxScript:
    """
    Natural language: <b>Taunt</b>
    <b>Start of Combat:</b> Deal {0} damage to all other minions.

    Status: DEFERRED — requires "SoC 定位当前战斗对手"

    Dependency: "all other minions" 含**敌方**棋盘（RULES §6.12
    "对敌方造成伤害"）——但 run_combat 不向脚本层暴露战斗对 (a, b)
    （SoC ctx={}、game 无 current combat 属性）。遍历 game.heroes 在
    >2 人局会误伤非参战英雄棋盘，且其变化不在战斗快照内（不可回滚
    的越权写）——禁止近似。需要引擎在 SoC ctx 传入 opponent 或
    game 暴露当前战斗对。引擎缺口已列批次模块 docstring #2。
    （实现草案: 双方 board 序逐个 Hit(m, num(0), source)，死亡波次
    由 Hit 内部 check_deaths 处理; 金色 "twice" = 两轮独立伤害序列）

    Params: {0}=3（36.2.2 基线，金色同值 ×2 轮）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        return None


# ══════════════════ 注册 ══════════════════

# （含金色 id——金色=独立卡定义）
_REGISTRATIONS = [
    ("BG24_500", AmberGuardianScript),
    ("BG24_500_G", AmberGuardianGoldenScript),     # "two other" Dragons
    ("BG26_354", ChoralMrrrglrScript),
    ("BG26_354_G", ChoralMrrrglrGoldenScript),     # "twice"
    ("BG26_805", HummingBirdScript),
    ("BG26_805_G", HummingBirdGoldenScript),       # "+2 Attack"
    ("BG27_556", DiremuckForagerScript),
    ("BG27_556_G", DiremuckForagerGoldenScript),   # "two highest"
    ("BG31_999", StitchedSalvagerScript),
    ("BG31_999_G", StitchedSalvagerGoldenScript),  # "adjacent minions"
    ("BG32_822", FireForgedEvokerScript),
    ("BG32_822_G", FireForgedEvokerScript),        # 金色 num=4/2 自然体现
    ("BG34_142", CostumeEnthusiastScript),
    ("BG34_142_G", CostumeEnthusiastGoldenScript), # "double"
    ("BG36_245", RunicArcanistScript),
    ("BG36_245_G", RunicArcanistGoldenScript),     # "4 times"
    # DEFERRED 未注册: BG32_330(+_G) Flighty Scout（手牌 SoC 触发点）/
    # BG36_620(+_G) Boom-in-a-Box（SoC 对手棋盘定位）
]


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []
    for card_id, script_cls in _REGISTRATIONS:
        _register(card_id, script_cls)
        registered.append(card_id)
    return registered
