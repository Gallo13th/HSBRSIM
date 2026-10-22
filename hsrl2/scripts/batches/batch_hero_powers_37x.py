"""批次 hero_powers_37x — 37.0 新英雄主技能 + 旧赛季可精确实现技能。

作业来源: `docs/AUDIT_ENGINE_MECHANICS.md` G-H1（P0: 17/118 英雄主技能无
脚本 = env 全英雄池下的死技能）。本批按 skill 优先序实现**能用现有引擎
原语精确表达**的技能；缺子系统者保持未注册（二态铁律，SOP §6b）并在
模块末「DEFERRED 台账」逐条记录 blocker。

本批注册（6 个主技能）:
  BG36_HERO_000p  Drest'agath — Incubate          主动: 弃 1 张牌 → 随机
                                                   Aberration 入手
  BG36_HERO_002p  Kith'ix — Dark Ritual          主动: 随机 2 随从入手，
                                                   打出一张时弃掉另一张
  BG33_HERO_001p_ALT Loh — Heroic Inspiration    被动: 15 个友方随从攻击后
                                                   获得 Triple Reward
  BG20_HERO_242p  Guff Runetotem — Natural Balance 被动: 购买累计 20 个
                                                   Tier 后获得 Triple Reward
  BG35_HERO_001p  Genn — King of Duality          被动: 第 4 回合 Discover
                                                   两个英雄技能替换本技能
  BG24_HERO_100p  Sire Denathrius — Whodunit?     被动: 开局从 2 个任务中
                                                   选 1（引擎任务协议）

无来源 Triple Reward 的档位裁定（Loh / Guff）
------------------------------------------------
官方 wiki 卡页无 Notes，Triple Reward 法术文本为动态 "Tier @"
（[hsbg.cards 59604](https://hsbg.cards/card/59604-triple-reward)；
wiki Triple Reward 页无规则说明）。常规三连奖励档 = 被三连卡 tier+1；
英雄技能场景**无来源卡**。卡面唯一可观测锚点 = 本人当前酒馆等级 →
按**自然语言解读**取 `hero.tavern_tier`（封顶 `max_tavern_tier`），
发现协议复用引擎 `Discover(min_tier=tier, max_tier=tier,
kind="triple_reward")`（与 `_grant_triple_reward` 的池预留/未选释放/
金色语义一致）。这是已记档的**解读边界**，不是伪造：若官方后续明确
档位规则，只需改 `_detached_triple_reward` 一处。

DEFERRED 台账（11 个主技能，不注册 —— 缺子系统/语义无权威）
------------------------------------------------------------
  BG20_HERO_202p Master Nguyen  — hero 级技能 rebind/unbind 缺失
      （被替换被动 on_bind 监听器/英雄 tag 常驻 → 每回合轮换残留）；
      候选池 helper 已就绪（`batch_hero_remaining._draftable_hero_power_ids`）。
  BG20_HERO_283p Galewing       — flightpath 路线/完成时点无数据权威
      （choice token BG20_HERO_283p_t1..t3 存在，但"Complete"时点与
      回退可选无官方 Notes）；rebind 同 Nguyen。
  BG21_HERO_000p Cariel Roame   — "After each combat, choose an
      improvement" 的改进选项集/叠加协议无公开枚举证据（wiki
      derived_choiceCardDbfIds 给 3 张 token，但官方无 Notes）。
  BG25_HERO_100p Putricide      — Craft 多步合成子系统未建（部件选择/
      属性合并/关键词互斥）。
  BG31_HERO_801p Jim Raynor     — Battlecruiser Upgrade 子系统：10 张
      upgrade（card_type 42）无脚本 + 馆内注入/附着协议未建。
  BG31_HERO_811p Kerrigan       — Zerg 分级解锁 + Larva 每回合 morph
      选择子系统未建（811p2/p3 变体同族）。
  BG34_HERO_000p Murozond       — Timewarp（Major）商店/Chronum 子系统。
  BG34_HERO_004p Morchie        — Timewarp（Minor）商店子系统。
  TB_BaconShop_HP_020 Akazamzarak — Secret 区/触发协议（BG 无 Secret
      子系统；16 张 TB_Bacon_Secrets_* 无英雄区接线）。
  TB_BaconShop_HP_101 Silas Darkmoon — Darkmoon Ticket token/馆内计数
      子系统（CardDB 内无 Ticket token 定义）。
  TB_BaconShop_HP_106 Tickatus  — Darkmoon Prize 卡池/档位映射子系统
      （BGS_Treasures_* 无 Tier N 映射数据）。
最小原语与优先级建议见 `docs/ENGINE_SUBSYSTEM_GAPS.md`（Lead 汇总用）。
"""

from __future__ import annotations

from hsrl2.actions import Buff, Discover, GetRandomMinion
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    BEFORE_ATTACK,
    CARD_PLAYED,
    COMBAT_END,
    MINION_BOUGHT,
    SPELL_BOUGHT,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race

# ── 通用帮助 ──


def _power_num(game, power_id: str, index: int, name: str) -> int:
    """技能模板参数（缺失 fail-loud——PARAM_MISSING 禁止默认值近似）。"""
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    v = d.num(index)
    if v is None:
        raise GameStateError(f"{power_id}: template param {{{index}}} "
                             f"({name}) missing")
    return v


def _detached_triple_reward(hero, game):
    """无来源 Triple Reward（Loh / Guff）——档位 = 本人当前酒馆等级。

    裁定依据与边界见模块 docstring「无来源 Triple Reward 的档位裁定」。
    返回引擎 `Discover` Action（池预留/未选释放/满手排队/金色语义与
    常规三连奖励同源）。
    """
    tier = min(max(1, hero.tavern_tier), game.max_tavern_tier)
    return Discover(hero, count=3, min_tier=tier, max_tier=tier,
                    kind="triple_reward")


def _random_minion_to_hand(hero, game):
    """随机池随从入手（占池 + 满手排队）。返回 Minion 或 None。"""
    cands = _pool_candidates(game, hero=hero)
    if not cands:
        return None
    card_id = game.rng.choice(cands, label="random_minion_to_hand")
    if not game.minion_pool.acquire(card_id):
        return None
    m = game.create_minion(card_id, controller=hero)
    game.pending_hand_add(hero, m)
    return m


# ══════════════════ BG36_HERO_000p Incubate（Drest'agath） ═══════════════


class IncubateScript:
    """
    Natural language: Discard a card to get a random Aberration.

    数据/权威: CardDefs 37.0 BG36_HERO_000p（dbfId=134503, COST=1）;
    wiki 卡页 `Battlegrounds/Incubate?action=raw`（oldid 页面模板:
    custom_mechanicTags = "Discard&&Generate", custom_refTags =
    "Random&&Aberration-generating"——确认 **Discard + Generate Random
    Aberration** 两个动作）。37.0 Aberration 种族（Race.ABERRATION=126）
    池内 17 张已注册（batch_37x_* 批）。

    Formal spec:
      1. needs_target = True + `target_candidates` = **本人手牌**全部实体
         （弃牌可选随从/法术——"Discard a card" 通名）；引擎挂
         `hero_power_target` PendingChoice，挂起期以同一候选域复核
         （`_hero_power_target_ok`）。
      2. hero_power(ctx.target): `game.discard_card(hero, target)` 唯一
         弃牌入口（计数/事件/on_discard 钩子全生效）。
      3. 弃牌成功 → `GetRandomMinion(hero, race=Race.ABERRATION)`——
         池感知随机 Aberration 入手（占池 + 满手排队）；池空 → 落空
         （官方真实语义）。
      4. 手牌为空 → 候选不足，`use_hero_power` 返回 False（不扣费）。

    Test: test_batch_hero_powers_37x.py — 使用后手牌 -1（目标被弃）、
    随机 Aberration 入手且占池、金币 -1、弃牌计数 +1；手牌空不可用;
    目标在挂起期离开手牌 → 本次作废不扣费。

    Params: 无模板参数（cost=1 数据字段；Aberration 候选 = 全池）
    """

    needs_target = True

    @staticmethod
    def target_candidates(hero, game):
        return list(hero.hand)

    @staticmethod
    def hero_power(hero, game, ctx):
        target = (ctx or {}).get("target")
        if target is None or target not in hero.hand:
            return None   # 挂起期目标离手（引擎已复核，防御性）
        if not game.discard_card(hero, target, source=None):
            return None
        return GetRandomMinion(hero, race=Race.ABERRATION)


# ══════════════════ BG36_HERO_002p Dark Ritual（Kith'ix） ═══════════════


class DarkRitualScript:
    """
    Natural language: [x]Get 2 random minions. When you play one, discard
    the other.

    （数据 text 的 "@" 第二段 "When you play or **Pass** one, discard
    the other." 是 37.0 的升级/变体显示态——本批实现基础段；"Pass"
    版本缺触发协议权威，边界记档。）

    数据/权威: CardDefs 37.0 BG36_HERO_002p（dbfId=134505, COST=2）;
    wiki 卡页 `Battlegrounds/Dark_Ritual?action=raw`: mechanicTags =
    "Generate&&Discard", refTags = "Random&&Triggered effect",
    hiddenTags = "Triggered effect - whenever you play a card"（确认
    **获得 2 张随机随从 + 打出触发弃另一张**）；同文本同族卡
    `BG36_308 Faceless Operative`（"When you play one, discard the other"
    已注册，batch_37x_discard 同协议）。

    Formal spec:
      1. hero_power: 两次独立随机 `_pool_candidates`（随机池随从，含
         同 card_id 不同副本的可能）→ 各 acquire + create_minion +
         pending_hand_add（占池/满手排队 RULES §2.3/§3.3）。
      2. 两张均入手 → 建立**双向配对** `hero._dark_ritual_pairs`。
      3. on_bind 注册持久 `card_played` 监听（owner=hero）：打出配对中
         任一张时，若另一张仍在手牌 → `game.discard_card`（唯一弃牌
         入口，弃牌计数/事件/on_discard 全生效）；配对双向清除（幂等）。
      4. 多次使用 = 多组独立配对；一张已离手（出售/弃牌/变形）时该组
         自然失效（另一张打出时无手牌可弃，不报错）。
      5. 池空/池不足 2 张 → 已获得的照常入手，不建立配对（落空）。

    Test: test_batch_hero_powers_37x.py — 使用后手牌 +2 且金币 -2；
    打出其中一张 → 另一张被弃（弃牌计数 +1、手牌清空）；两次使用两组
    配对互不干扰；对手打出无关卡不触发。

    Params: count=2（文本字面量；cost=2 数据字段）
    """

    count = 2

    @staticmethod
    def on_bind(hero, game):
        if getattr(hero, "_dark_ritual_pairs", None) is None:
            hero._dark_ritual_pairs = {}

        def on_played(g, card=None, **kw):
            pairs = getattr(hero, "_dark_ritual_pairs", {})
            partner = pairs.pop(card, None)
            if partner is None:
                return
            pairs.pop(partner, None)
            if partner in hero.hand:
                g.discard_card(hero, partner, source=None)

        game.events.register(Listener(
            event=CARD_PLAYED, owner=hero, callback=on_played))
        return None

    @staticmethod
    def hero_power(hero, game, ctx):
        picks = []
        for _ in range(DarkRitualScript.count):
            m = _random_minion_to_hand(hero, game)
            if m is None:
                break
            picks.append(m)
        if len(picks) == 2:
            pairs = getattr(hero, "_dark_ritual_pairs", None)
            if pairs is None:
                pairs = hero._dark_ritual_pairs = {}
            pairs[picks[0]] = picks[1]
            pairs[picks[1]] = picks[0]
        return None


# ══════════════════ BG33_HERO_001p_ALT Heroic Inspiration（Loh） ════════


class HeroicInspirationScript:
    """
    Natural language: [x]After {1} friendly minions attack, get a Triple
    Reward. <i>({0} left!)</i>

    数据/权威: CardDefs 37.0 BG33_HERO_001p_ALT（dbfId=129164,
    NUM_1=NUM_2=15）；wiki 卡页 `Battlegrounds/Heroic_Inspiration?action=raw`:
    mechanicTags = "Generate", refTags = "Spell-generating&&Triggered
    effect&&Attacking-related", hiddenTags = "Triggered effect - after a
    friendly minion attacks"（确认**友方随从攻击后计数**）。奖励载体
    `derived_relatedCardDbfIds=59604` = Triple Reward 法术（Discover a
    minion from Tier @）。

    Formal spec:
      1. passive=True（被动技能：`use_hero_power` 拒绝主动使用）。
      2. on_bind 注册持久 BEFORE_ATTACK 监听（owner=hero）: 攻击宣告时
         （含风怒第二次攻击/招募期即时攻击——引擎统一生产点）且
         `attacker.controller is hero` → 计数 +1。
      3. 计数达 num(1)=15 → 归零（保留余数）并发放一次无来源 Triple
         Reward（`_detached_triple_reward`: 档位 = 当前酒馆等级，
         边界见模块 docstring）。
      4. 对手随从攻击不计（owner 隔离）；攻击计数跨战斗持续（英雄级）。

    Test: test_batch_hero_powers_37x.py — 14 次攻击无奖励 / 第 15 次挂
    triple_reward Discover（选项全部 = 当前 tier）/ 对手攻击不计数 /
    第 30 次再奖励一次 / 选项选择后入手占池。

    Params: threshold=num(1)=15（显示 num(0)=15 同值）
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        threshold = _power_num(game, "BG33_HERO_001p_ALT", 1,
                               "friendly minions attack")
        hero._loh_attacks = 0

        def on_attack(g, attacker=None, defender=None, **kw):
            if attacker is None or attacker.controller is not hero:
                return
            hero._loh_attacks += 1
            if hero._loh_attacks < threshold:
                return
            hero._loh_attacks -= threshold
            g.run_actions(_detached_triple_reward(hero, g))

        game.events.register(Listener(
            event=BEFORE_ATTACK, owner=hero, callback=on_attack))
        return None


# ══════════════════ BG20_HERO_242p Natural Balance（Guff） ═══════════════


class NaturalBalanceScript:
    """
    Natural language: [x]After you buy 20 Tiers' worth of cards, get a
    Triple Reward. <i>(@ left!)</i>

    数据/权威: CardDefs 37.0 BG20_HERO_242p（dbfId=68130, NUM_1=20）;
    wiki 卡页 `Battlegrounds/Natural_Balance?action=raw`: mechanicTags =
    "Generate", refTags = "Tavern Tier-related&&Spell-generating&
    &Buying-related"（确认**购买 + Tier 累计**）。奖励载体
    `derived_relatedCardDbfIds` 含 Triple Reward 59604。

    Formal spec:
      1. passive=True。
      2. on_bind 注册持久 MINION_BOUGHT + SPELL_BOUGHT 监听（owner=hero）:
         只统计本人购买（minion.controller is hero / 事件 hero kw is
         hero——与 batch_37x_missing1 GluttonousTrogg 同口径）。
      3. 每次购买累加**该卡 Tier**（`CardDef.tech_level`；酒馆法术同
         字段）到 num(0)=20 阈值；达阈值 → 减去 20（余数保留；大 Tier
         购买可能一次跨多个阈值 → while 循环逐次发放）并发放一次无来源
         Triple Reward（档位边界见模块 docstring）。
      4. 对手购买不计数；跨回合累积。

    Test: test_batch_hero_powers_37x.py — 19 个 Tier1 购买无奖励 /
    第 20 个触发 triple_reward / Tier 6 购买一次跨阈值（19+6=25 → 1 次
    奖励且余 5）/ 对手购买不计数 / 法术购买计数。

    Params: threshold=num(0)=20
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        threshold = _power_num(game, "BG20_HERO_242p", 0, "Tiers worth")
        hero._natural_balance_tiers = 0

        def _tick(g, card_id: str) -> None:
            d = g.db.get(card_id)
            if d is None:
                return
            hero._natural_balance_tiers += d.tech_level or 0
            while hero._natural_balance_tiers >= threshold:
                hero._natural_balance_tiers -= threshold
                g.run_actions(_detached_triple_reward(hero, g))

        def on_minion_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not hero:
                return
            _tick(g, minion.card_id)

        def on_spell_bought(g, spell=None, **kw):
            buyer = kw.get("hero")
            if spell is None or buyer is not hero:
                return
            _tick(g, spell.card_id)

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_minion_bought))
        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=hero, callback=on_spell_bought))
        return None


# ══════════════════ BG35_HERO_001p King of Duality（Genn） ═══════════════


class KingOfDualityScript:
    """
    Natural language: On Turn 4, <b>Discover</b> two Hero Powers to
    replace this. <i>({0} turns left!)</i>

    数据/权威: CardDefs 37.0 BG35_HERO_001p（dbfId=129685, NUM_1=3,
    ReferencedTag DISCOVER）；wiki 卡页
    `Battlegrounds/King_of_Duality?action=raw`: mechanicTags =
    "Discover&&Replace Hero Power", refTags = "Turn-related"（确认
    **第 4 回合（num(0)+1）→ Discover 英雄技能 → 替换本技能**）。

    语义解读（边界记档）: "Discover two Hero Powers to replace this"
    = 连续两次独立 Discover（各三选一），第一个替换**主技能槽**，第二个
    进入**第二技能槽**（RULES §9.5 引擎第二槽协议；34.2 官方
    "second Hero Power" 概念）。官方无 Notes 明示两槽映射，本读法是
    唯一能同时满足"两个技能 + 替换 this"的引擎落点；若后续官方澄清
    （如二选一或双主槽）只改本类 `_resolve_first/_resolve_second`。

    Formal spec:
      1. passive=True。
      2. on_bind 注册一次性 TURN_START 监听（owner=hero，
         condition=turn==num(0)+1==4 且 hero is owner）——触发后自动注销。
      3. 触发: 候选池 = `batch_hero_remaining._draftable_hero_power_ids`
         （绑定英雄且**已注册**的技能全集，排除本技能）→ rng.sample 3 →
         PendingChoice(kind="discover_hero_power")。
      4. 第一次选择: `replace_hero_power(hero, pick)` +
         `wire_hero_power_on_bind`（引擎替换不自动接线 on_bind）→ 再挂
         第二次 Discover（排除已选技能）。
      5. 第二次选择: `set_second_hero_power(hero, pick)`（引擎内接线
         on_bind）。
      6. 候选不足 3 时全给；0 个候选（全未注册）→ 不产生选择（落空）。

    Test: test_batch_hero_powers_37x.py — 第 3 回合不触发 / 第 4 回合
    连续两个 discover_hero_power 选择 / 第一选择后主技能=所选 /
    第二选择后第二槽=所选且主槽不变 / 两个所选技能均在已注册池 /
    选择后 on_bind 接线生效（被选被动技能有可见效果则验证——
    用测试桩注入 REGISTRY 后还原）。

    Params: trigger_turn=num(0)+1=4（"{0} turns left" 倒计时口径同
    batch_hero_remaining Marin 饰品提前档）
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        trigger_turn = _power_num(game, "BG35_HERO_001p", 0, "turns left") + 1
        from hsrl2.scripts.batches.batch_hero_remaining import (
            _draftable_hero_power_ids,
        )

        def on_turn_start(g, hero=None, turn=None, _owner=hero,
                          _turn=trigger_turn, **kw):
            if hero is not _owner or turn != _turn:
                return
            pool = [pid for pid in _draftable_hero_power_ids(g)
                    if pid != "BG35_HERO_001p"]
            if not pool:
                return
            k = min(3, len(pool))
            options = g.rng.sample(pool, k, label="genn_power_options")
            KingOfDualityScript._offer(g, hero, options,
                                       _draftable_hero_power_ids)

        game.events.register(Listener(
            event=TURN_START, owner=hero, once=True,
            condition=lambda hero=None, turn=None, _owner=hero,
            _t=trigger_turn, **kw: hero is _owner and turn == _t,
            callback=on_turn_start))
        return None

    @staticmethod
    def _offer(game, hero, options, pool_fn) -> None:
        def resolve_first(pick) -> None:
            if pick not in options:
                raise GameStateError(
                    f"King of Duality: pick {pick!r} not in {options}")
            game.replace_hero_power(hero, pick)
            game.wire_hero_power_on_bind(hero, pick)
            rest = [pid for pid in pool_fn(game)
                    if pid != pick and pid != "BG35_HERO_001p"]
            if not rest:
                return
            k = min(3, len(rest))
            second = game.rng.sample(rest, k, label="genn_second_options")

            def resolve_second(pick2) -> None:
                if pick2 not in second:
                    raise GameStateError(
                        f"King of Duality: pick2 {pick2!r} not in {second}")
                game.set_second_hero_power(hero, pick2)

            game.pending_choices.append(PendingChoice(
                hero, second, "discover_hero_power",
                resolve_callback=resolve_second))

        game.pending_choices.append(PendingChoice(
            hero, list(options), "discover_hero_power",
            resolve_callback=resolve_first))


# ══════════════════ BG24_HERO_100p Whodunit?（Sire Denathrius） ══════════


class WhodunitScript:
    """
    Natural language: At the start of the game, choose one of two
    <b>Quests</b>.

    数据/权威: CardDefs 37.0 BG24_HERO_100p（dbfId=92961）；任务子系统
    2026-09-18 落地（`batch_quests` 19 张注册、目标值权威 = 各卡 wiki
    "baseline requirement"，见 `docs/agents/QUEST_DEFERRED_SPEC.md`）；
    任务/奖励配对规则官方未公布 → 沿用引擎 `_offer_quests` 的裁定
    （等权随机配对，Malygos 先例）。

    Formal spec:
      1. passive=True（纯开局选择）。
      2. on_bind（= start_game 接线，`wire_hero_power_on_bind`）:
         任务候选 = `game.quest_offer_pool()`（= 可进度化任务卡 ∩
         REGISTRY 池门禁——**不**用 BG24_Quest_* 前缀；避免发出
         DEFERRED 的 BG24_Quest_328 与公告 token BG24_Quest_Bob）；
         奖励候选 = 全部 `BG24_Reward_*` 卡 id。rng.sample 2 个互异
         任务，各配一张 rng.choice 随机奖励 → PendingChoice(
         kind="quest_offer"，options=(quest_id, reward_id) 二元组)。
      3. resolve((qid, rid)):
         create_entity(任务) → hero.quest / `_quest_progress=0` /
         `_quest_completed=False`；**先**暂存 `_quest_reward_id = rid`
         再 `run_on_bind(quest, ctx={"hero": hero})`（阈值式任务可能
         入场即达标 → `complete_quest` 必须能立刻发奖——与引擎
         `_offer_quests.resolve` 同顺序）。
      4. `game._quest_offered.add(hero)`——一处英雄同时只有一个任务；
         抑制第 4 回合标准 quest offer 重复发放。

    Test: test_batch_hero_powers_37x.py — start_game 后产生
    quest_offer 选择且 options 长度 2、任务 id 全部 ∈ quest_offer_pool()、
    奖励 id 前缀 BG24_Reward_；选择后 hero.quest 指向所选任务、奖励已
    暂存、`_quest_offered` 含 hero；第 4 回合 `_begin_recruit_for` 不再
    产生标准 quest_offer。

    Params: count=2（"one of two Quests" 文本字面量）
    """

    passive = True

    @staticmethod
    def on_bind(hero, game):
        quest_pool = [d.id for d in game.quest_offer_pool()]
        rewards = [d.id for d in game.db._by_id.values()
                   if d.id.startswith("BG24_Reward_")]
        if not quest_pool or not rewards:
            return None
        k = min(2, len(quest_pool))
        quests = game.rng.sample(quest_pool, k, label="whodunit_quest")
        pairs = [(q, game.rng.choice(rewards, label="whodunit_reward_pair"))
                 for q in quests]
        # 一个英雄一个任务：抑制第 4 回合标准 offer
        game._quest_offered.add(hero)

        def resolve(pair) -> None:
            qid, rid = pair
            quest_entity = game.create_entity(qid, controller=hero)
            hero.quest = quest_entity
            hero._quest_progress = 0
            hero._quest_completed = False
            # 先暂存奖励再接线：阈值式任务 on_bind 可能当场达标
            hero._quest_reward_id = rid
            game.run_on_bind(quest_entity, ctx={"hero": hero})

        game.pending_choices.append(PendingChoice(
            hero, pairs, "quest_offer", resolve_callback=resolve))
        return None


# ══════════════════ 注册 ══════════════════

_SCRIPTS = {
    "BG36_HERO_000p": IncubateScript,
    "BG36_HERO_002p": DarkRitualScript,
    "BG33_HERO_001p_ALT": HeroicInspirationScript,
    "BG20_HERO_242p": NaturalBalanceScript,
    "BG35_HERO_001p": KingOfDualityScript,
    "BG24_HERO_100p": WhodunitScript,
}


def register() -> list[str]:
    """注册本批 6 个英雄主技能（DEFERRED 11 个见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    registered = []
    for power_id, script in _SCRIPTS.items():
        reg(power_id, script)
        registered.append(power_id)
    return registered
