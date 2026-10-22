"""批次 anomalies2 — 异变系统第二批（作业单 2026-09-02）。

实现 8 个异变 id + 2 个 token 法术（异变只分发 on_bind(game)，
EFFECT_SCRIPT_SOP §11 W1；每英雄监听器一律默认参数绑定 `_h=h`
防闭包晚绑定）:

  - Treasure Hoard ×5（BG27_Anomaly_572/559/570/571/573）:
    指定回合 Discover 金色指定 tier 随从（turn = num(0)+1）
  - Golden Arrow（BG31_Anomaly_124）: 每 num(0)=3 回合入手 Golden Arrow
    - token BG31_Anomaly_124t4: 定向（TARGETING_ARROW_TEXT）酒馆法术，
      目标酒馆随从变金色
  - Perfected Alchemy（BG27_Anomaly_751）: 开局入手 The Goldenizer
    - token BG26_813t: 定向（wiki 分类 Targeted）法术，目标友方随从变金色
      （此前 REGISTRY 无脚本 → 本批实现其 on_play）
  - Reckless Enhancement（BG27_Anomaly_505）: 每次酒馆刷新后，馆内每个
    随从随机获得 Taunt/Windfury/Divine Shield/Reborn 之一

金色化实现复用既有 helper（不重复实现）:
  - 酒馆目标 → `batch_spells2._goldenize_tavern`（Golden Touch 先例:
    Transform 只支持棋盘，酒馆走原位替换）
  - 棋盘目标 → `batch_battlecry._goldenize`（Reno/Sanders 语义:
    Transform 到金卡定义、保 buff、GILDED_NOT_TRIPLED、不发三连奖励）
  两者均保留 buff、把 CARD_ID 换成金卡本体、更新 scripts。

未使用任何引擎不读取的标记（无新增 `_flag`）。
"""

from __future__ import annotations

from hsrl2.actions import Discover, GainKeyword
from hsrl2.events import TAVERN_REFRESH, TURN_START, Listener
from hsrl2.minion import Minion
from hsrl2.tags import CardType, GameTag

# Treasure Hoard 族: tier 是卡牌文本的字面量（无 {1} 模板参数），逐 id 表
# 驱动（先例: batch_anomalies._RACE_BY_ID）。turn 一律 num(0)+1。
_TREASURE_HOARD_TIERS = {
    "BG27_Anomaly_572": 3,
    "BG27_Anomaly_559": 4,
    "BG27_Anomaly_570": 5,
    "BG27_Anomaly_571": 6,
    "BG27_Anomaly_573": 7,
}

# Reckless Enhancement 四选一关键词（文本枚举）
_RECKLESS_KEYWORDS = (GameTag.TAUNT, GameTag.WINDFURY,
                      GameTag.DIVINE_SHIELD, GameTag.REBORN)


def _card_id_by_name(game, name, card_type=None):
    """按名字查 card_id（禁止凭记忆写 id——SOP §11 教训 5）。"""
    for d in game.db._by_id.values():
        if d.name == name and (card_type is None or d.card_type == card_type):
            return d.id
    return None


# ══════════════════ BG27_Anomaly_572/559/570/571/573 Treasure Hoard ═══════════


class TreasureHoardAnomaly:
    """
    Natural language: On Turn 5, Discover a Golden Tier 3 minion.
    ({0} |4(turn, turns) left!)

    Evidence: data/bg_anomalies.json 全族核对（文本 + script_data_num_1）:
      BG27_Anomaly_572 On Turn 5 / Golden Tier 3 minion / {0}=4
      BG27_Anomaly_559 On Turn 6 / Golden Tier 4 minion / {0}=5
      BG27_Anomaly_570 On Turn 7 / Golden Tier 5 minion / {0}=6
      BG27_Anomaly_571 On Turn 8 / Golden Tier 6 minion / {0}=7
      BG27_Anomaly_573 On Turn 9 / Golden Tier 7 minion / {0}=8
    倒计时 "({0} turns left!)" 与 "On Turn N" 一致 → 触发回合 = num(0)+1。

    Formal spec:
      1. on_bind: 每英雄注册 once TURN_START 监听（condition 锁英雄
         `hero is _h` 且 `turn == num(0)+1`）
      2. 触发回合: `Discover(hero, min_tier=T, max_tier=T,
         kind="discover_minion", golden=True)`——引擎预留选项（占池）、
         resolve 时授予**金卡本体**（独立 CardDef id，属性翻倍），
         未选项回池
      3. once 消费后不再触发; 每英雄独立一份发现（闭包 `_h=h` 绑定）

    Test: test_batch_anomalies2.py — 触发前无发现 / 触发回合每英雄各 1 个
    发现 / 选项全为 tier T / 选中项入手金色本体（card_id=金卡 def、
    属性翻倍）/ once 不重复 / 英雄隔离

    Params: {0}=4（BG27_Anomaly_572; 559 {0}=5 / 570 {0}=6 /
            571 {0}=7 / 573 {0}=8）; tier 来自文本字面量
            （_TREASURE_HOARD_TIERS）
    """

    @staticmethod
    def on_bind(game):
        aid = game.anomaly
        d = game.db.get(aid) if aid else None
        tier = _TREASURE_HOARD_TIERS.get(aid)
        n0 = d.num(0) if d is not None else None
        if tier is None or n0 is None:
            return None
        trigger_turn = n0 + 1
        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, _turn=trigger_turn,
                      _tier=tier, **kw):
                if hero is not _h or turn != _turn:
                    return
                g.run_actions(Discover(
                    _h, min_tier=_tier, max_tier=_tier,
                    kind="discover_minion", golden=True))

            def cond(hero=None, turn=None, _h=h, _turn=trigger_turn, **kw):
                return hero is _h and turn == _turn

            game.events.register(Listener(
                event=TURN_START, owner=h, callback=on_ts,
                condition=cond, once=True))
        return None


# ══════════════════ BG31_Anomaly_124 Golden Arrow ══════════════════


def _tavern_minion_candidates(source, game):
    """Golden Arrow 目标候选: 酒馆内可金卡化的 Minion。

    排除: 法术/已金色/无金卡本体者（Golden Touch 同构过滤）。
    """
    hero = source.controller
    if hero is None:
        return []
    out = []
    for e in hero.tavern:
        if not isinstance(e, Minion) or e.dead or e.is_golden:
            continue
        d = game.db.get(e.card_id)
        if d is None or game.db.golden_version(d) is None:
            continue
        out.append(e)
    return out


class GoldenArrowSpellScript:
    """
    Natural language: Choose a minion in the Tavern. Make it Golden.

    Evidence: CardDefs.xml BG31_Anomaly_124t4 含 TARGETING_ARROW_TEXT
    （enumID 325, "Goldenize a minion in the Tavern."）→ [Targeted]，
    文本亦含 "Choose"（Kelp Keeper 判别法先例，EFFECT_SCRIPT_SOP §9）。

    Formal spec:
      1. needs_target=True; target_candidates = 酒馆内非金色、存在金卡
         本体的 Minion（法术/已金色/无金卡定义排除）; 无候选 → on_play
         落空（法术照常消耗）
      2. on_play(ctx["target"]) → batch_spells2._goldenize_tavern:
         原位换金卡定义实体、buff 并集保留、满血、GILDED_NOT_TRIPLED
         （回池按 1 份基础卡）、重绑金色脚本、不发三连奖励

    Test: test_batch_anomalies2.py — PendingChoice(kind="spell_target")
    候选=馆内随从 / 选中后 card_id=金卡 def、is_golden、buff 保留、
    GILDED_NOT_TRIPLED / 空馆落空

    Params: 无模板参数（无 {0}/{1} 占位符）
    """

    needs_target = True
    target_candidates = staticmethod(_tavern_minion_candidates)

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        from hsrl2.scripts.batches.batch_spells2 import _goldenize_tavern
        _goldenize_tavern(game, target)
        return None


class GoldenArrowAnomaly:
    """
    Natural language: Every 3 turns, get a Golden Arrow.
    ({0} turns left!)

    Evidence: data/bg_anomalies.json BG31_Anomaly_124 — text 含 "Every 3
    turns, get a Golden Arrow." 且 script_data_num_1=3（{0} 倒计时
    "3 turns left!"）; 完成态文本变体 "(Next turn!)"（= 只剩 1 回合时的
    显示）; BACON_EVOLUTION_CARD_ID=119776 → 授予物
    BG31_Anomaly_124t4（wiki 卡片页 "Generates"）。倒计时模型与同批
    TreasureHoardAnomaly 同源（"On Turn N" ↔ num(0)=N−1 → 触发回合 =
    num(0)+1）: 第 1 回合显示 "3 turns left" / 第 2 回合 "2" /
    第 3 回合 "(Next turn!)" / 第 4 回合入手 → 首次触发 = num(0)+1，
    此后每 num(0) 回合（7/10…）。wiki Patch 35.0.0（2026-03-05）
    bugfix: "prevent it from being lost due to a full hand" → 满手必须
    排队（pending_hand_add 等待语义）。

    Formal spec:
      1. on_bind: 每英雄注册常驻 TURN_START 监听（condition 锁英雄 +
         `turn > 1 and (turn - 1) % num(0) == 0`）——"Every N turns" 是
         重复效果，非 once; 相位 = 首次触发 num(0)+1
         （2026-09-02 对抗审查 N2 修正: 旧实现 `turn % num(0) == 0`
         把首次触发提前到第 3 回合，与同批 Treasure Hoard 的
         num(0)+1 模型及 "(Next turn!)" 状态文本都不符）
      2. 每个触发回合开始: `pending_hand_add(hero, create_spell(
         <Golden Arrow token>, controller=hero))`（满手排队等待，不销毁）
      3. 每英雄独立（闭包 `_h=h` 绑定）

    Test: test_batch_anomalies2.py — 第 4 回合每英雄各 1 张、第 7 回合
    各 2 张、非触发回合（含第 1/3/6 回合）不给 / 满手排队并在下回合
    补入 / 英雄隔离

    Params: {0}=3（num(0)=3 → N=3; 首次触发 = N+1 = 4）
    """

    @staticmethod
    def on_bind(game):
        d = game.db.get(game.anomaly) if game.anomaly else None
        every = d.num(0) if d is not None else None
        token = _card_id_by_name(game, "Golden Arrow", CardType.SPELL)
        if not every or token is None:
            return None

        def _due(turn, _n):
            return turn is not None and turn > 1 and (turn - 1) % _n == 0

        for h in game.heroes:
            def on_ts(g, hero=None, turn=None, _h=h, _n=every, _tok=token,
                      **kw):
                if hero is not _h or not _due(turn, _n):
                    return
                g.pending_hand_add(
                    _h, g.create_spell(_tok, controller=_h))

            def cond(hero=None, turn=None, _h=h, _n=every, **kw):
                return hero is _h and _due(turn, _n)

            game.events.register(Listener(
                event=TURN_START, owner=h, callback=on_ts, condition=cond))
        return None


# ══════════════════ BG27_Anomaly_751 Perfected Alchemy ══════════════════


def _friendly_board_candidates(source, game):
    """The Goldenizer 目标候选: 友方棋盘上可金卡化的存活 Minion。"""
    hero = source.controller
    if hero is None:
        return []
    out = []
    for m in hero.board:
        if m.dead or m.is_golden:
            continue
        d = game.db.get(m.card_id)
        if d is None or game.db.golden_version(d) is None:
            continue
        out.append(m)
    return out


class GoldenizerSpellScript:
    """
    Natural language: Make a friendly minion Golden.

    Evidence: data/bg_cards.json BG26_813t "The Goldenizer" — CARDTYPE=42
    （Tavern spell, CardDefs.xml ID 98914）; wiki.gg
    Battlegrounds/The_Goldenizer 分类含 **Targeted**（"Make a friendly
    minion Golden."，无 "random"）→ 定向。REGISTRY 此前无此 id 脚本
    （已核）→ 本批实现 on_play（Perfected Alchemy 的载荷）。

    Formal spec:
      1. needs_target=True; target_candidates = 友方棋盘存活、非金色、
         存在金卡本体的 Minion
      2. on_play(ctx["target"]) → batch_battlecry._goldenize（Reno 语义:
         Transform 到金卡定义、buff 保留、GILDED_NOT_TRIPLED、不发三连
         奖励、重绑金色脚本）

    Test: test_batch_anomalies2.py — 候选=友方棋盘随从 / 选中后
    card_id=金卡 def、is_golden、GILDED_NOT_TRIPLED / 敌方随从不在候选

    Params: 无模板参数（无 {0}/{1} 占位符）
    """

    needs_target = True
    target_candidates = staticmethod(_friendly_board_candidates)

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        from hsrl2.scripts.batches.batch_battlecry import _goldenize
        _goldenize(game, target)
        return None


class PerfectedAlchemyAnomaly:
    """
    Natural language: Start with a Goldenizer.

    Evidence: data/bg_anomalies.json BG27_Anomaly_751 —
    BACON_EVOLUTION_CARD_ID=98914 → "The Goldenizer" BG26_813t
    （名字查证，非凭记忆; wiki 卡片页 Related cards 亦列出 Perfected
    Alchemy）。

    Formal spec:
      1. on_bind: 每英雄 `pending_hand_add(hero, create_spell(
         "The Goldenizer" 按名字解析, controller=hero))`——开局入手
         （满手排队，不销毁）
      2. 授予物是既有卡 BG26_813t; 其 on_play 由本批
         GoldenizerSpellScript 实现（REGISTRY 脚本绑定）

    Test: test_batch_anomalies2.py — 开局每英雄手牌各 1 张 BG26_813t /
    打出后友方随从变金色 / 英雄隔离

    Params: 无模板参数（无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(game):
        cid = _card_id_by_name(game, "The Goldenizer")
        if cid is None:
            return None
        for h in game.heroes:
            spell = game.create_spell(cid, controller=h)
            if spell is not None:
                game.pending_hand_add(h, spell)
        return None


# ══════════════════ BG27_Anomaly_505 Reckless Enhancement ══════════════════


class RecklessEnhancementAnomaly:
    """
    Natural language: Minions in the Tavern each randomly gain Taunt,
    Windfury, Divine Shield, or Reborn.

    Evidence: data/bg_anomalies.json BG27_Anomaly_505（无模板参数）;
    wiki.gg Battlegrounds/Reckless_Enhancement 同文（该异变 31.6.0 起
    已移出异变池——按作业单要求实现效果本身）。引擎
    `game.refresh_tavern` 在酒馆**填充完成后** fire "tavern_refresh"
    （game.py 尾部）→ 监听点正确。

    Formal spec:
      1. on_bind: 每英雄注册常驻 TAVERN_REFRESH 监听（condition 锁英雄）
      2. 每次刷新后: 对馆内每个存活 Minion 用 `game.rng.choice` 从
         [Taunt, Windfury, Divine Shield, Reborn] 随机取一个，
         `GainKeyword` 授予（fire keyword_gained）
      3. 已带某关键词者再抽到同一关键词为自然 no-op（tag 已置位）

    Test: test_batch_anomalies2.py — 真实回合（冻结馆保留的 vanilla
    随从）刷新后**恰好**获得四关键词之一 / 受控事件下计数为 1 /
    不影响棋盘 / 英雄隔离

    Params: 无模板参数（无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(game):
        for h in game.heroes:
            def on_refresh(g, hero=None, _h=h, **kw):
                if hero is not _h:
                    return
                actions = []
                for e in _h.tavern:
                    if not isinstance(e, Minion) or e.dead:
                        continue
                    tag = g.rng.choice(_RECKLESS_KEYWORDS,
                                       label="reckless_enhancement")
                    actions.append(GainKeyword(e, tag))
                g.run_actions(actions)

            game.events.register(Listener(
                event=TAVERN_REFRESH, owner=h, callback=on_refresh))
        return None


def register() -> list[str]:
    """注册异变 8 id + token 法术 2 id。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        # Treasure Hoard ×5（同一脚本类，turn/tier 由 id 解析）
        ("BG27_Anomaly_572", TreasureHoardAnomaly),
        ("BG27_Anomaly_559", TreasureHoardAnomaly),
        ("BG27_Anomaly_570", TreasureHoardAnomaly),
        ("BG27_Anomaly_571", TreasureHoardAnomaly),
        ("BG27_Anomaly_573", TreasureHoardAnomaly),
        # Golden Arrow（异变 + token 法术）
        ("BG31_Anomaly_124", GoldenArrowAnomaly),
        ("BG31_Anomaly_124t4", GoldenArrowSpellScript),
        # Perfected Alchemy（异变 + Goldenizer token 法术）
        ("BG27_Anomaly_751", PerfectedAlchemyAnomaly),
        ("BG26_813t", GoldenizerSpellScript),
        # Reckless Enhancement
        ("BG27_Anomaly_505", RecklessEnhancementAnomaly),
    ]
    registered = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
