"""批次 trinkets13 — 饰品第十三批: 片 3（作业单 2026-09-02，20 张）。

与 batch_trinkets1..12 的 id 集合互不相交（bg_trinkets.json 片 3:
BG30_MagicItem_876 … BG32_MagicItem_172）。全部 id 均为
`CardDB.trinket_offer_pool()` 中的**商店本体**（无 `t`/`t2` 升级变体、
无纯 token）。数值一律 `CardDef.num(i)`；文本无占位符的增量按 SOP §3
在各类 `Params:` 行声明。随机一律 `game.rng`。全部状态写在 hero 作用域 /
source 实体闭包（无 game 级 flag——SOP §12 item 9）。

本批依赖的引擎原语（均为主线已落地 / 本工作区已提交的公开 API）:
  - `game.trinket_related_card(trinket_id)` + `game.grant_trinket_related_card
    (hero, trinket_id)` + `game.grant_card_copy_to_hand(hero, card_def)`
    （RULES §7.4.6 关联卡协议——Portrait/Sticker 族 "Get a <卡>" 的统一
    入口; 数据链 `CardDef.evolution_card_id` → `db.by_dbf`，零硬编码卡 id）
  - `game.copy_trinket(hero, trinket_id, replace=实体)`（RULES §7.4.3 副本
    条款——"transforms into a copy of it" 允许同一饰品两份副本; 绕过跨局
    去重 `_trinkets_granted` 且副本 on_bind 照常接线）
  - `TavernBuff` / `ApplyTavernBuff` / `BuffCurrentTavern`
    （actions/tavern_buff.py; 读取点 = `refresh_tavern` 新入馆随从）
  - `hero._tavern_offer_override`（读取点 = `refresh_tavern` 展示数覆写，
    Glowing Gauntlet BG30_MagicItem_841 先例）
  - `GOLD_SPENT`（`spend_gold` 每次支出 fire，携带 amount= 与 hero=）
  - `spell_resolving(spell=, target=, cast_no=)`（手牌施放路径每 cast 一次;
    `PlayBloodGems` 直施路径**不** fire——"played from your hand" 的精确
    判别点）
  - `game.last_opponent_warband(hero)`（RULES §4.8a 上一对手战前战团快照）

注册 13 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG30_MagicItem_876  Manipulator Portrait  — Get a Faceless Manipulator
  BG30_MagicItem_879  Dalaran Cheese Wheel  — 酒馆随从 +num(1)/+num(1);
                                              每 num(0)=4 次**主动**刷新
                                              再加一层
  BG30_MagicItem_888  Souvenir Stand        — 买到 Greater 饰品时复制
                                              一份（本体+副本两份都在，
                                              `copy_trinket`）
  BG30_MagicItem_919  Nazjatar Postcard     — 打出纳迦后随机获得 1 张
                                              Spellcraft 法术
  BG30_MagicItem_921  Flagbearer Portrait   — Get Sky Pirate Flagbearer;
                                              "Sky Pirate" +6 攻
  BG30_MagicItem_930  Burgling Claw         — 每回合开始: 上一对手战团中
                                              最高档随从的白板副本进手牌
  BG30_MagicItem_942  Mecha-Jaraxxus Sticker— Get 2 random Magnetic
                                              Mecha-Demons; 每回合再来 2
  BG30_MagicItem_943  Surveyor Portrait     — Get Hot-Air Surveyor;
                                              **手牌打出**的血宝石额外
                                              +num(0)/+num(1)
  BG30_MagicItem_991  Felbat Portrait       — Get Famished Felbat;
                                              酒馆恒 7 个随从位
  BG30_MagicItem_999  Fancy Spellbook       — 每累计花 num(2)=7 金施放
                                              Shiny Ring（滚动计数）
  BG31_MagicItem_903  Wisdomball Supply     — Get Knockoff Wisdomball;
                                              每回合再来 1 张
  BG32_MagicItem_170  Spell-powered Wrench  — 打出磁力随从后: 对随机友方
                                              机械施放 Repair Job
  BG32_MagicItem_172  Boom's Monster Portrait— Get Dr. Boom's Monster;
                                              每回合再来 1 只

DEFERRED（本批评估后放弃；不注册，附具体缺失依赖 + 实现路径）
═══════════════════════════════════════════════════════════════════════
  - BG30_MagicItem_917 Rusty Trident — "Start of Combat: Give your Naga
    'Deathrattle: Get a random Spellcraft spell.'"。
    已由 `batch_trinkets23` 注册（`grant_combat_deathrattle` 原语已落地）。
    Dependency（历史）: **共享 grant_combat_deathrattle 引擎原语**。"random
    Spellcraft spell" 侧已可由 `_spellcraft_spell_ids` 数据链表达
    （batch_spells2 先例），但战斗内授予亡语目前只有 batch_hero_combat3
    的私有 `_grant_combat_deathrattle` + COMBAT_END 恢复协议（写
    `_script_overrides` 与 `hero._combat_dr_grants`），不是引擎公开
    原语。实现路径: 引擎在 game/actions 暴露
    `grant_combat_deathrattle(game, owner, minion, fn)`（含战斗快照/
    COMBAT_END 恢复语义）→ 本卡 SoC 取全体友方 Naga → 授予
    `dr_fn = GetBloodGems 式随机 Spellcraft 入手`。被阻塞卡:
    917 + 952（同族）。
  - BG30_MagicItem_944 Redeemer Portrait — "Get a Nalaa the Redeemer.
    Your Nalaa the Redeemers give an extra +{0}/+{1}."
    Dependency: 载荷 BG28_551 Nalaa the Redeemer **未注册**（REGISTRY
    无此 id，且其本体 "Whenever you cast a Tavern spell, give a friendly
    minion of each type +X/+Y" 无脚本），且无"某指定随从的 give 效果
    额外 +N"的读取通道。实现路径: (a) 先实现 BG28_551 本体脚本并让其
    读取 hero 级加成（如 `hero._nalaa_bonus_atk/health`，需引擎侧存在
    读取点以满足 W3）；(b) 本饰品 on_bind 递增该 hero 级加成。单实现
    本卡会得到一个永不生效的授予物（SOP §12 item 14 禁止）。
  - BG30_MagicItem_952 Jarred Frostling — "Start of Combat: Give 2
    friendly Elementals 'Deathrattle: Summon a Flourishing Frostling'."
    已由 `batch_trinkets23` 注册（`grant_combat_deathrattle` 原语已落地）。
    Dependency（历史）: 同 917（共享 grant_combat_deathrattle 原语）。授予物
    BG26_537 Flourishing Frostling 数据存在（token，零池操作）;
    "2 friendly Elementals" 无 [Targeted] → 随机 2 只（rng.sample）。
  - BG30_MagicItem_971 Enforcer Portrait — "Get a Lightfang Enforcer.
    Your Lightfang Enforcers have all minion types."
    Dependency: **多/全种族身份改写**。`GameTag.RACE` 是单值 tag;
    `Race.ALL` 语义是"匹配一切种族查询"而非"显示为全部类型"（会把
    Beast/Mech/… 一并匹配，属近似而非精确）。同缺口已由 batch_trinkets8
    / batch_trinkets11（BG30_MagicItem_418 Bronzebeard Portrait）备案。
    实现路径: `RACES` 集合 tag（或双种族位掩码）+ 全部种族匹配/查询
    读取点统一改造后，在 on_bind 给本人 Lightfang Enforcer 实例改写。
  - BG30_MagicItem_987 Balladist Portrait — "Get a Lovesick Balladist.
    At the start of each turn, get another. Your Lovesick Balladists also
    give Attack."
    Dependency: **Attack 增量无数据权威**。BG26_814 的 XML 只有
    `TAG_SCRIPT_DATA_NUM_2=1`（=Health 基值），`{0}`（Attack）在数据中
    缺失（`CardDef.num(0) is None`）；wiki Lovesick Balladist/Balladist
    Portrait 页均无 Notes 说明该 Attack 的数值或其与 Gold-spent 强化
    的关系（本批已查证）。候选读法: (A) Attack = 与 Health 同值
    (num(1)+gold_spent); (B) Attack = 仅 gold_spent; (C) Attack 为
    portrait 隐藏固定值。且 BG26_814 脚本（batch_battlecry）当前不读
    任何"portrait 加成"通道。实现路径: 官方实测/数据补
    `TAG_SCRIPT_DATA_NUM_1` + BG26_814 脚本增读 hero 级加成。
  - BG30_MagicItem_992 Darnassus Pie — "Minions in the Tavern have +1/+1
    for each minion you've sold this turn."
    Dependency: **动态逐回合酒馆 Buff**。`TavernBuff` 是静态数值描述子，
    无"按回合内计数实时求值"协议（2026-09-02 已落地）; 现有近似（出售时一次性 add_buff）
    会漏掉"出售后入馆的新随从继承当前计数"与"回合开始计数清零后
    冻结保留项仍带旧 buff"两条语义。实现路径: 引擎提供酒馆随从动态
    属性读取钩子（按 `tavern_sold_this_turn` 实时重算，或在 minion_sold
    时对全馆重算并让后续入馆继承当前计数）。同缺口已由 batch_trinkets1
    T992 备案。
    Status: 已由 batch_trinkets24 注册（动态逐回合酒馆 Buff 原语已于 2026-09-02 落地）
  - BG30_MagicItem_994 Yogg-Tastic Pastry — "Spin the Wheel of Yogg-Saron.
    At the start of each turn, spin it again."
    Dependency: **Wheel of Yogg-Saron 子系统 + 轮盘结果表**。数据中无
    任何 Wheel token/结果表（`grep` 全库无 wheel 实现）; 同缺口已由
    batch_quest_rewards3（BG24_Reward_135 Yogg-tastic Tasties）与
    batch_anomalies3（BG27_Anomaly_503 The Yogg-iseum）备案。实现路径:
    引擎实现轮盘奖池（每个结果的 card_id/数值来源需数据权威）+
    `spin_wheel(hero)` 原语。

引擎缺口（本批发现，未修改引擎）: 无新增——917/952 的缺口为主线已
备案的 grant_combat_deathrattle; 927 之外无其它阻塞。

接线审计读取点（供 W1/W2/W3 核对）: `_tavern_offer_override`
（refresh_tavern 读取）、`tavern_buffs`（refresh_tavern 读取）、
`GOLD_SPENT`/`TAVERN_REFRESH`/`SUMMON`/`CARD_PLAYED`/`TRINKET_BOUGHT`
（均引擎 fire）、`spell_resolving`（`_finish_play_spell` fire）。
"""

from __future__ import annotations

from typing import List, Optional

from hsrl2.actions import Buff
from hsrl2.actions.bloodgem import BLOOD_GEM_VARIANTS
from hsrl2.actions.tavern_buff import (
    ApplyTavernBuff,
    BuffCurrentTavern,
    TavernBuff,
)
from hsrl2.events import (
    CARD_PLAYED,
    GOLD_SPENT,
    SUMMON,
    TAVERN_REFRESH,
    TRINKET_BOUGHT,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.scripts.batches.batch_spells2 import _spellcraft_spell_ids
from hsrl2.spell import Spell as SpellType
from hsrl2.tags import CardType, GameTag, Race, Zone

# 含 All 型的匹配族（Amalgam 全种族，RULES §6.4 通用裁定）
_NAGA_RACES = (Race.NAGA, Race.ALL)
_MECH_RACES = (Race.MECH, Race.ALL)

# 文本字面量（CardDef 无模板参数; SOP §3）
SKY_PIRATE_NAME = "Sky Pirate"          # BG30_MagicItem_921 "Your Sky Pirates"
SKY_PIRATE_ATK_BONUS = 6                # "have +6 Attack"
MECHA_DEMON_GRANT_COUNT = 2             # "Get 2 random Magnetic Mecha-Demons"
TAVERN_ALWAYS_SEVEN = 7                 # "The Tavern always has 7 cards"

# 血宝石法术 id 集合（手牌打出判别用; bloodgem.BLOOD_GEM_VARIANTS 权威）
_BLOOD_GEM_IDS = frozenset(BLOOD_GEM_VARIANTS.values())


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


def _grant_related(game, hero, source, count: int = 1) -> bool:
    """`game.trinket_related_card` 数据链 ×count 进手牌（"Get a <卡>"）。

    RULES §7.4.6: `evolution_card_id` → `db.by_dbf` 解析关联卡;
    `grant_card_copy_to_hand` 负责池记账（池随从/池法术先 acquire，池空
    落空; token 零池操作）与满手排队。返回是否至少授予 1 张。
    """
    granted = False
    for _ in range(count):
        if game.grant_trinket_related_card(hero, source.card_id):
            granted = True
    return granted


def _sky_pirate_ids(game) -> set:
    """全部名为 "Sky Pirate" 的随从定义 id（基础 + 金色 token）。

    数据核实（36.2.2）: `BGS_061t`（Sky Pirate 1/1）与其金色
    `TB_BaconUps_141t`（2/2）—— 由 Scallywag `BGS_061` 亡语召唤;
    `BG30_MagicItem_921` 文本 "Your Sky Pirates" 即指该 token 族群。
    按名解析沿用 `_card_id_by_name` 先例（batch_anomalies2/3），
    零硬编码卡 id。
    """
    return {d.id for d in game.db._by_id.values()
            if d.card_type == CardType.MINION and d.name == SKY_PIRATE_NAME}


def _magnetic_mecha_demon_defs(game) -> List:
    """全部 **Magnetic Mecha-Demon** token（数据驱动，零硬编码 id）。

    口径 = 随从 ∧ 非金色定义 ∧ 带 `magnetic` 关键词 ∧ 文本同时含
    "Mechs" 与 "Demons"（即 "Can Magnetize to Mechs *and* Demons"）。
    36.2.2 实测命中 4 张基础 token: BG25_807t Rusted Reggie /
    BG25_807t2 Magtheridon Prime / BG25_807t3 Baltharak /
    BG25_807t4 Shield of the Legion —— 与 wiki "Mecha-Jaraxxus Sticker
    → Related cards" 四张完全一致（证据链双证）。返回按 id 排序以
    保证 rng 可复现。
    """
    out = []
    for d in game.db._by_id.values():
        if d.card_type != CardType.MINION or d.is_golden_def:
            continue
        if "magnetic" not in d.keywords:
            continue
        text = d.text or ""
        if "Mechs" in text and "Demons" in text:
            out.append(d)
    return sorted(out, key=lambda d: d.id)


def _grant_mecha_demons(game, hero, count: int) -> int:
    """随机获取 count 张互异的 Magnetic Mecha-Demon（无放回 sample）。

    "Get N random <族>" 的互异口径沿用 batch_spells2 Spitescale Special
    "Get 3 random Spellcraft spells" 的作业裁定（`game.rng.sample`）;
    候选不足则取 min(count, len)（数据缺口防御）。token 非池卡 →
    `grant_card_copy_to_hand` 零池操作。返回实际授予张数。

    **AMBIGUOUS（留档，RULES §7.4.8）**: 本卡文本无 "different"
    （对比 `BG32_MagicItem_282` "Get {0} **different** Magnetic Mechs"），
    理论上可能允许重复; 官方/数据无权威 → 暂与全仓统一（无放回）。
    **引擎依赖**: 4 张 token 文本 "Can Magnetize to Mechs *and* Demons"
    → `_magnetic_valid` 已补 Demon 合法集（2026-09-02）。
    """
    cands = _magnetic_mecha_demon_defs(game)
    if not cands:
        return 0
    picks = game.rng.sample(cands, min(count, len(cands)),
                            label="mecha_jaraxxus_sticker")
    got = 0
    for d in picks:
        if game.grant_card_copy_to_hand(hero, d):
            got += 1
    return got


# ══════════════ BG30_MagicItem_876 Manipulator Portrait ══════════════

class ManipulatorPortraitScript:
    """
    Natural Language: Get a Faceless Manipulator.

    Formal Spec:
      1. on_bind: `_grant_related(本人, source)` —— 经
         `evolution_card_id`（dbf 103396 → BG_EX1_564）数据链授予
         1 张 **白板副本** 进手牌（满手排队 RULES §3.3）
      2. BG_EX1_564 `is_pool_minion=False`（36.2.2 数据核实）→ 零池
         操作; 授予物本体的战吼脚本是**另一张卡**的迁移项，不在本
         饰品的效果范围内（Promo Portrait/Bassgill Portrait 先例）
      3. 只进本人手牌

    Test: test_batch_trinkets13.py — 绑定后本人手牌恰多 1 张 BG_EX1_564
      且随从池数量不变 / 对手手牌不变 / 真实 end_recruit_phase 不再
      重复授予（无 "each turn" 措辞）

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        return None


# ══════════════ BG30_MagicItem_879 Dalaran Cheese Wheel ══════════════

class DalaranCheeseWheelScript:
    """
    Natural Language: Minions in the Tavern have +{1}/+{1}. Improves every
    4 times you <b>Refresh</b>. <i>({0} left!)</i>

    Formal Spec:
      1. on_bind: TavernBuff(atk=num(1), health=num(1), source_id=本卡)
         经 `ApplyTavernBuff` 登记持久面 + `BuffCurrentTavern` 立即面
         （当前馆内随从即时获得; 读取点 = refresh_tavern 新入馆随从）
      2. on_bind 注册持久 TAVERN_REFRESH 监听器（owner=饰品）:
         **"you Refresh" = 玩家主动刷新** —— 过滤 `hero is 本人` 且
         `auto is False`（回合开始自动刷新不算; Frigid Blossom
         BG36_MagicItem_300 同裁定）
      3. 计数达 num(0)=4 → 归零并**再叠加一层** TavernBuff
         (+num(1)/+num(1)): 追加登记 + 对当前馆内随从立即再 buff
         （当次刷新已先按旧层数填充 → 改善后补上差额）
      4. 数值口径: {1}=num(1)（与文本占位符一致）; {0}=num(0)=4 为
         显示计数（"({0} left!)"），阈值同源
      5. 只作用于本人酒馆（TavernBuff 挂 hero.tavern_buffs）

    Test: test_batch_trinkets13.py — 绑定后当前馆内随从 +num(1)/+num(1)
      / 3 次主动刷新不改善、第 4 次后新入馆随从共 +2×num(1) /
      `refresh_tavern(auto=True)` 不计入（正对照: 手动刷新计入）/
      对手馆内随从无增益

    Params: {0}=4 {1}=1（BG30_MagicItem_879 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        per = _num(game, source.card_id, 1)
        threshold = _num(game, source.card_id, 0)
        tb = TavernBuff(atk=per, health=per, source_id=source.card_id)
        game.run_actions([ApplyTavernBuff(h, tb), BuffCurrentTavern(h, tb)])
        state = {"n": 0}

        def on_refresh(g, hero=None, auto=False, _h=h, **kw):
            if hero is not _h or auto:
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            g.run_actions([ApplyTavernBuff(_h, tb),
                           BuffCurrentTavern(_h, tb)])

        game.events.register(Listener(event=TAVERN_REFRESH, owner=source,
                                      callback=on_refresh))
        return None


# ══════════════ BG30_MagicItem_888 Souvenir Stand ══════════════

class SouvenirStandScript:
    """
    Natural Language: [x]When you buy a
    Greater <b>Trinket</b>, this
    transforms into a
    copy of it.

    Formal Spec:
      1. on_bind 注册持久 TRINKET_BOUGHT 监听器（owner=本饰品实体）:
         引擎 `_offer_trinkets.resolve` 在**授予并记账之后**广播
         `trinket_bought(hero=, trinket=, kind=)`（kind == "greater"）
      2. 条件: `hero is 本人` ∧ `kind == "greater"` ∧ 本实体仍在
         `hero.trinkets`（陈旧防护，SOP §16 item 24）∧ 所购 id ≠ 自身
      3. 触发: `game.copy_trinket(本人, bought.card_id, replace=本实体)`
         —— 副本条款（RULES §7.4.3）: **本体保留 + Stand 变成第二份**
         （`duplicate=True` 跳过跨局去重; 副本 on_bind 照常接线 → 两份
         光环/监听各自生效）。`replace` 移除 Stand 并注销其监听器，
         故本效果每张 Stand 只结算一次
      4. 复制免费（不扣金币）; 只作用于本人

    Test: test_batch_trinkets13.py — 真实 `_offer_trinkets` + choose 买到
      Greater 后: Stand 消失、hero.trinkets 中该 Greater **恰两份**、
      金币只扣 1 份购买费、`_trinkets_granted` 记账 / 买到 Lesser 时
      Stand 保留且只有 1 份所购（正对照）/ 对手饰品栏不变

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_bought(g, hero=None, trinket=None, kind=None,
                      _h=h, _src=source, **kw):
            if hero is not _h or kind != "greater" or trinket is None:
                return
            if _src not in _h.trinkets:
                return
            if trinket.card_id == _src.card_id:
                return
            g.copy_trinket(_h, trinket.card_id, replace=_src,
                           source="souvenir_stand")

        game.events.register(Listener(event=TRINKET_BOUGHT, owner=source,
                                      callback=on_bought))
        return None


# ══════════════ BG30_MagicItem_917 Rusty Trident ══════════════

class RustyTridentScript:
    """
    Status: 已由 batch_trinkets23 注册（本占位类不注册）

    Natural Language: [x]<b>Start of Combat:</b> Give your
    Naga "<b>Deathrattle:</b> Get a
    random <b>Spellcraft</b> spell."

    Status: DEFERRED — requires 共享 grant_combat_deathrattle 原语

    Dependency:
      1. 战斗内授予亡语当前只有 batch_hero_combat3 的私有
         `_grant_combat_deathrattle` + `_restore_granted_deathrattles`
         （写 `minion._script_overrides` 与 `hero._combat_dr_grants`，
         依赖 COMBAT_END 持久监听恢复）——不是引擎公开原语; 跨批次
         import 私有 helper 会把本卡绑死在兄弟批次的内部实现上。
      2. "random Spellcraft spell" 侧**已就绪**（`_spellcraft_spell_ids`
         数据链，batch_spells2 先例）。
      3. 解冻路径: 引擎暴露 `grant_combat_deathrattle(game, owner,
         minion, dr_fn)`（含战斗快照回滚 + COMBAT_END override 恢复）
         → 本卡 SoC 取全体友方 Naga（含 ALL）→ 授予
         `dr_fn = 随机 Spellcraft 法术入手`（create_spell + SPELLCRAFT
         tag + pending_hand_add）。被阻塞卡: 917 + 952（同族）。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ BG30_MagicItem_919 Nazjatar Postcard ══════════════

class NazjatarPostcardScript:
    """
    Natural Language: After you play a Naga, get a random <b>Spellcraft</b>
    spell.

    Formal Spec:
      1. on_bind 注册持久 CARD_PLAYED 监听器（owner=饰品）: 引擎在随从
         战吼结算后广播（`_run_play_effects`），携带 card=
      2. 条件: `isinstance(card, Minion)` ∧ `card.controller is 本人`
         ∧ race ∈ (NAGA, ALL)（Amalgam 规则）
      3. 触发: 候选 = `_spellcraft_spell_ids(game)`（池内 Spellcraft
         随从 `spellcraft_id` 数据链，36.2.2 共 9 张基础法术）;
         `game.rng.choice` 取 1 张 → `create_spell` + 置 `SPELLCRAFT`
         tag（回合末丢弃协议）+ `pending_hand_add`（满手排队）
      4. 非池 token（`is_pool_spell=False`）→ 不占 spell_pool
         （Spitescale Special BG28_606 同口径）
      5. 候选空 → 落空; 只作用于本人（对手打出纳迦不触发）

    Test: test_batch_trinkets13.py — 真实 play_minion 纳迦后入手恰 1 张
      card_id ∈ Spellcraft 数据链且带 SPELLCRAFT tag / 打出非纳迦不入手
      （正对照）/ 对手打出纳迦不影响本人 / 法术池不变量不变

    Params: 无模板参数（"a random Spellcraft spell" = 1 张，文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, _h=h, **kw):
            if not isinstance(card, Minion) or card.controller is not _h:
                return
            if card.race not in _NAGA_RACES:
                return
            cands = _spellcraft_spell_ids(g)
            if not cands:
                return
            sid = g.rng.choice(cands, label="nazjatar_postcard")
            s = g.create_spell(sid, controller=_h)
            s.set(GameTag.SPELLCRAFT, True)
            g.pending_hand_add(_h, s)

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════ BG30_MagicItem_921 Flagbearer Portrait ══════════════

class FlagbearerPortraitScript:
    """
    Natural Language: [x]Get a Sky Pirate
    Flagbearer. Your Sky
    Pirates have +6 Attack.

    Formal Spec:
      1. on_bind: `_grant_related(本人, source)` —— 数据链 dbf 113148 →
         BG30_119 Sky Pirate Flagbearer（非池 token，零池操作）入手
      2. "Your Sky Pirates have +6 Attack" = 对本人控制的、卡名为
         "Sky Pirate" 的随从（BGS_061t / 金色 TB_BaconUps_141t;
         `_sky_pirate_ids` 按名解析）永久 +6 攻击的**光环**
         （"have" = 在场即有）:
           a) on_bind 对当前棋盘存活匹配者各 `Buff(atk=6)`
           b) 注册持久 SUMMON 监听器（owner=饰品）→ 之后召唤的匹配者
              （含战斗中 Scallywag 亡语召唤，SUMMON 事件带 controller）
              同样 `Buff(atk=6)`
      3. 只作用于本人棋盘; 对手的 Sky Pirate 不受影响
      4. 数值 6 = 文本字面量（CardDef 无模板参数）

    Test: test_batch_trinkets13.py — 绑定前已在场的 Sky Pirate 立即
      +6 攻 / 绑定后真实 game.summon 的 Sky Pirate +6 攻（对照无饰品
      为基值）/ 对手召唤/在场 Sky Pirate 不 +6 / 同名非 token 之外
      的普通海盗不受影响（正对照: Sky Pirate 确实 +6）

    Params: atk=6（"+6 Attack" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        ids = _sky_pirate_ids(game)

        def _apply(hero, m):
            if m is None or m.dead or m.controller is not hero:
                return
            if m.card_id not in ids:
                return
            game.run_actions(Buff(m, atk=SKY_PIRATE_ATK_BONUS))

        for m in list(h.board):
            _apply(h, m)

        def on_summoned(g, minion=None, _h=h, **kw):
            _apply(_h, minion)

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summoned))
        return None


# ══════════════ BG30_MagicItem_930 Burgling Claw ══════════════

class BurglingClawScript:
    """
    Natural Language: [x]At the start of each turn, get
    a plain copy of the highest-
    Tier minion in your last
    opponent's warband.

    Formal Spec:
      1. start_of_turn（饰品 SoT 钩子，每回合开始）: 读
         `game.last_opponent_warband(本人)`（RULES §4.8a —— 上一场
         战斗对手的**战前**战团快照; 幽灵战含幽灵阵容; 无战斗记录/
         首回合 → None）
      2. 目标 = 快照中存活 Minion 里 `tech_level` 最高者; 并列取
         **最靠左**（`max` 首个极大值 —— batch_quest_rewards R508/R013
         "highest-Tier minion" 同裁定）
      3. 授予 = **白板副本**进手牌: `create_minion(card_id, controller=
         本人, golden=源.is_golden)`（金色源 → 金色副本，`TRIPLE_BASE_
         CARD_ID` 还原基础 id; 与 `game._plain_copy_to_hand` 同语义）
         + `pending_hand_add`（满手排队）。**复制体不占池**（Rafaam/
         Tess 复制先例——复制对手已有单位不消耗池副本）
      4. 无上一对手 / 快照空 → 落空; 只进本人手牌

    Test: test_batch_trinkets13.py — 真实 end_recruit_phase（含真实
      配对+战斗+下一回合 SoT）后: 本人手牌恰多 1 张 == 对手战团最高档
      卡（两个不同档位对照，低档不入）/ 副本为白板（源带 buff 不带入）
      / 对手手牌不变 / 首回合（无 last opponent）真实 end_recruit_phase
      前调用落空不崩

    Params: 无模板参数（"highest-Tier" 为运行时聚合）
    """

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        warband = game.last_opponent_warband(h)
        if not warband:
            return None
        cands = [m for m in warband
                 if isinstance(m, Minion) and not m.dead]
        if not cands:
            return None
        best = max(cands, key=lambda m: m.tech_level)
        base_id = best.get(GameTag.TRIPLE_BASE_CARD_ID, None) or best.card_id
        copy = game.create_minion(base_id, controller=h,
                                  golden=best.is_golden)
        game.pending_hand_add(h, copy)
        return None


# ══════════════ BG30_MagicItem_942 Mecha-Jaraxxus Sticker ══════════════

class MechaJaraxxusStickerScript:
    """
    Natural Language: [x]Get 2 random <b>Magnetic</b>
    Mecha-Demons.
    At the start of each turn,
    get 2 more.

    Formal Spec:
      1. 候选集 = `_magnetic_mecha_demon_defs`（数据驱动: 随从 ∧ 非金色
         ∧ magnetic 关键词 ∧ 文本 "Can Magnetize to Mechs *and* Demons"）
         —— 36.2.2 命中 4 张基础 token（BG25_807t/t2/t3/t4），与 wiki
         "Mecha-Jaraxxus Sticker → Related cards" 四张一致
      2. on_bind: 随机获取 2 张**互异**（`game.rng.sample` —— "Get N
         random <族>" 无放回口径，batch_spells2 Spitescale Special
         作业裁定）→ `grant_card_copy_to_hand`（token 非池卡，零池
         操作）进手牌（满手排队）
      3. start_of_turn（饰品 SoT 钩子）: 同款再获取 2 张
      4. 候选不足 → 取 min(2, len)（数据缺口防御）; 只进本人手牌

    Test: test_batch_trinkets13.py — 绑定后手牌恰 2 张、card_id 都在
      Mecha-Demon 数据链内且互异 / 真实 end_recruit_phase 后再 +2 /
      对手手牌不变 / 候选集非空且 == 4（钉死数据链）

    Params: count=2（"Get 2"/"get 2 more" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_mecha_demons(game, h, MECHA_DEMON_GRANT_COUNT)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_mecha_demons(game, h, MECHA_DEMON_GRANT_COUNT)
        return None


# ══════════════ BG30_MagicItem_943 Surveyor Portrait ══════════════

class SurveyorPortraitScript:
    """
    Natural Language: Get a Hot-Air Surveyor. <b>Blood Gems</b> played from
    your hand give an extra +{0}/+{1}.

    Formal Spec:
      1. on_bind: `_grant_related(本人, source)` —— 数据链 dbf 113152 →
         BG30_121 Hot-Air Surveyor（非池 token，零池操作）入手
      2. 数值 = num(0)/num(1)（36.2.2 均为 6）
      3. on_bind 注册持久 `spell_resolving` 监听器（owner=饰品）:
         该事件在手牌施放路径**每 cast 一次**广播（`_finish_play_spell`，
         携带 spell=, target=, cast_no=），且 `PlayBloodGems` 直施路径
         **不** fire —— 正是 "played **from your hand**" 的精确判别点
      4. 条件: `spell.card_id ∈ BLOOD_GEM_VARIANTS.values()`（全部血宝石
         含 3 个变体）∧ `spell.controller is 本人` ∧ target 是 Minion
         → `Buff(target, atk=num(0), health=num(1), gem=True)`（该颗
         宝石的一部分，`gem` 标记保证 Gem Confiscation 类效果按宝石
         处理）
      5. **不用 `ImproveBloodGems`/`BLOOD_GEM_BONUS_*`**: 该 tag 的
         读取点 `bloodgem._gem_values` 同时服务手牌打出与
         `PlayBloodGems` 直施两条路径 → 会把"非手牌"的宝石一并增幅，
         与文本限定不符。逐 cast 的 spell_resolving 监听是唯一精确
         实现路径
      6. 双施（Balinda/SPELL_DOUBLER）时每 cast 各结算一次（cast_no
         逐次）; 只作用于本人

    Test: test_batch_trinkets13.py — 手牌真实 play_spell 血宝石后目标
      = 基础 +num(0)/+num(1)（对照无饰品仅基础）/ 直施
      `PlayBloodGems` 只吃基础值（"from your hand" 判别，正对照: 同一
      设置下手牌路径确实 +num）/ 对手手牌血宝石不受影响 / 绑定入手
      BG30_121

    Params: {0}=6 {1}=6（BG30_MagicItem_943 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        d = game.db.get(source.card_id)
        if d is None or d.evolution_card_id is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        _grant_related(game, h, source)
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def on_resolving(g, spell=None, target=None, _h=h, **kw):
            if spell is None or spell.controller is not _h:
                return
            if spell.card_id not in _BLOOD_GEM_IDS:
                return
            if not isinstance(target, Minion) or target.dead:
                return
            g.run_actions(Buff(target, atk=atk, health=health, gem=True))

        game.events.register(Listener(event="spell_resolving", owner=source,
                                      callback=on_resolving))
        return None


# ══════════════ BG30_MagicItem_944 Redeemer Portrait ══════════════

class RedeemerPortraitScript:
    """
    Natural Language: [x]Get a Nalaa the Redeemer.
    Your Nalaa the Redeemers
    give an extra +{0}/+{1}.

    Status: DEFERRED — requires BG28_551 本体脚本 + 指定随从加成通道

    Dependency:
      1. 授予物 BG28_551 Nalaa the Redeemer **未注册**（REGISTRY 无此
         id）——"Whenever you cast a Tavern spell, give a friendly minion
         of each type +X/+Y" 无实现。载荷未就绪时宿主一并 DEFERRED
         （SOP §12 item 14）。
      2. "Your Nalaa the Redeemers give an extra +{0}/+{1}" 需要**改写
         另一张卡脚本行为**的 owner 级通道（且不得影响对手的 Nalaa）;
         `set_script_override` 只作用于已存在实体、无法覆盖未来副本。
      3. 解冻路径: (a) 实现 BG28_551 本体脚本，读 hero 级加成
         （如 `hero._nalaa_bonus_atk/health`，须有引擎侧读取点以满足
         W3）; (b) 本饰品 on_bind 递增该 hero 级加成 + 授予 Nalaa。
         被阻塞卡: 944。

    Params: {0}=4 {1}=4（BG30_MagicItem_944 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ BG30_MagicItem_952 Jarred Frostling ══════════════

class JarredFrostlingScript:
    """
    Status: 已由 batch_trinkets23 注册（本占位类不注册）

    Natural Language: [x]<b>Start of Combat:</b> Give 2
    friendly Elementals
    "<b>Deathrattle:</b> Summon a
    Flourishing Frostling".

    Status: DEFERRED — requires 共享 grant_combat_deathrattle 原语

    Dependency:
      1. 与 BG30_MagicItem_917 同一缺口: 战斗内授予亡语目前只有
         batch_hero_combat3 的私有 `_grant_combat_deathrattle` +
         COMBAT_END 恢复协议（`_script_overrides` /
         `hero._combat_dr_grants`），不是引擎公开原语。
      2. 授予物 BG26_537 Flourishing Frostling 数据存在（非池 token，
         零池操作）; "2 friendly Elementals" 无 [Targeted] → 随机 2 只
         （rng.sample）。
      3. 解冻路径: 引擎暴露 `grant_combat_deathrattle(...)`（含战斗
         快照回滚 + COMBAT_END override 恢复）→ 本卡 SoC 从本人棋盘
         存活元素（含 ALL）随机取 2 → 授予
         `dr_fn = game.summon(hero, create_minion(BG26_537))`。
         被阻塞卡: 917 + 952。

    Params: count=2（"Give 2 friendly Elementals" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ BG30_MagicItem_971 Enforcer Portrait ══════════════

class EnforcerPortraitScript:
    """
    Natural Language: [x]Get a Lightfang Enforcer.
    Your Lightfang Enforcers
    have all minion types.

    Status: DEFERRED — requires 多/全种族身份改写

    Dependency: `GameTag.RACE` 是单值 tag; `Race.ALL` 语义为"匹配一切
      种族查询"而非"显示为全部类型"（会把 Beast/Mech/… 一并匹配，
      属近似而非精确）。同缺口已由 batch_trinkets8 模块 docstring 与
      batch_trinkets11（Bronzebeard Portrait）就 418/971 族备案。
      解冻路径: `RACES` 集合 tag（或双种族位掩码）+ 全部种族匹配/查询
      读取点（`_pool_candidates` 过滤、种族光环、展示）统一改造后，
      在 on_bind 为本人 Lightfang Enforcer 实例改写种族身份。
      被阻塞卡: 418（他批）+ 971。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ BG30_MagicItem_987 Balladist Portrait ══════════════

class BalladistPortraitScript:
    """
    Natural Language: [x]Get a Lovesick Balladist.
    At the start of each turn,
    get another. Your Lovesick
    __Balladists also give Attack.

    Status: DEFERRED — requires Attack 增量的数据权威 + 本体加成通道

    Dependency:
      1. "also give Attack" 的**数值无权威**: BG26_814 XML 只有
         `TAG_SCRIPT_DATA_NUM_2=1`（Health 基值），`{0}`（Attack）
         在 CardDef 中缺失（`num(0) is None`）; wiki Lovesick Balladist /
         Balladist Portrait 页均无 Notes 说明数值或其与 "each Gold you
         spent this turn" 强化的关系（本批已查证，SOP §6b 第 1 步）。
         候选读法: (A) Attack = 与 Health 同值（num(1)+spent）;
         (B) Attack = 仅 spent; (C) portrait 隐藏固定值。
      2. BG26_814 脚本（batch_battlecry LovesickBalladistScript）当前
         `atk=0` 且不读任何加成通道——还需 owner 级改写协议。
      3. 解冻路径: 官方实测或数据补 `TAG_SCRIPT_DATA_NUM_1` + BG26_814
         脚本增读 hero 级加成（如 `hero._balladist_bonus_atk`，须有
         引擎侧读取点）; 本饰品的 Get/SoT 部分（数据链 dbf 99011 →
         BG26_814，池随从 → `grant_card_copy_to_hand` 占池）已就绪。
         被阻塞卡: 987。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ BG30_MagicItem_991 Felbat Portrait ══════════════

class FelbatPortraitScript:
    """
    Natural Language: [x]Get a Famished Felbat.
    The Tavern always has
    7 cards.

    Formal Spec:
      1. on_bind: `_grant_related(本人, source)` —— 数据链 dbf 72067 →
         BG21_005 Famished Felbat（非池 token，零池操作）入手; 授予物
         本体的 EoT 吞噬脚本是另一张卡的迁移项
      2. on_bind: `hero._tavern_offer_override = 7`（唯一读取点 =
         `refresh_tavern` 展示数覆写，hero 级**优先**于 game 级异变
         覆写 → 只影响绑定者酒馆，不污染对手; Glowing Gauntlet
         BG30_MagicItem_841 同裁定 A2）
      3. 7 = 文本字面量 "always has 7 cards"; 只作用于本人酒馆

    Test: test_batch_trinkets13.py — 绑定后入手 BG21_005 且随从池不变量
      不变 / 真实 refresh_tavern 后本人馆内随从数 == 7（对照未绑定的
      对手仍是基础展示数）/ 对手 `_tavern_offer_override` 未被写入

    Params: count=7（"always has 7 cards" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        h._tavern_offer_override = TAVERN_ALWAYS_SEVEN
        return None


# ══════════════ BG30_MagicItem_992 Darnassus Pie ══════════════

class DarnassusPieScript:
    """
    Status: 已由 batch_trinkets24 注册（动态逐回合酒馆 Buff 原语已于 2026-09-02 落地）

    Natural Language: Minions in the Tavern have +1/+1 for each minion
    you've sold this turn.

    Status: DEFERRED — requires 动态逐回合酒馆 Buff 原语

    Dependency: `TavernBuff` 是静态数值描述子，无"按回合内计数实时求值"
      协议; 现有近似（出售时一次性 add_buff）会漏掉两条语义:
      (a) 出售后**新入馆**的随从应继承当前计数;
      (b) 回合开始计数清零后，冻结保留项不应再带上一回合的 buff。
      解冻路径: 引擎提供酒馆随从动态属性读取钩子（按
      `tavern_sold_this_turn` 实时重算，或在 `minion_sold` 时对全馆
      重算并让后续入馆继承当前计数）。同缺口已由 batch_trinkets1 T992
      备案。被阻塞卡: 992。

    Params: atk=1 health=1（文本字面量 "for each minion you've sold"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ BG30_MagicItem_994 Yogg-Tastic Pastry ══════════════

class YoggTasticPastryScript:
    """
    Natural Language: Spin the Wheel of Yogg-Saron. At the start of each
    turn, spin it again.

    Status: DEFERRED — requires Wheel of Yogg-Saron 子系统 + 结果表数据

    Dependency: 全库无 Wheel 实现、数据中亦无任何 Wheel token/结果表
      （`grep -i wheel hsrl2/` 仅命中无关卡名）。同缺口已由
      batch_quest_rewards3（BG24_Reward_135 Yogg-tastic Tasties）与
      batch_anomalies3（BG27_Anomaly_503 The Yogg-iseum）备案。
      解冻路径: 引擎实现轮盘奖池（每个结果的 card_id/数值需数据权威）
      + `game.spin_wheel(hero)` 原语 → 本卡 on_bind/SoT 各调用一次。
      被阻塞卡: 994（+ 他批 2 张）。

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ BG30_MagicItem_999 Fancy Spellbook ══════════════

class FancySpellbookScript:
    """
    Natural Language: After you spend {2} Gold, cast Shiny Ring.
    <i>({0} Gold left!)</i>

    Formal Spec:
      1. 阈值 = num(2)（文本占位符 `{2}`; 36.2.2 实测 7）; 施放对象 =
         `game.trinket_related_card(source.card_id)`（数据链 dbf 109230
         → BG28_168 Shiny Ring，池法术 T3 "Give your minions +{0}/{1}"）
      2. on_bind 注册持久 GOLD_SPENT 监听器（owner=饰品）: 条件
         `hero is 本人`; `source._fs_progress += amount` 跨回合累计;
         `while p >= 阈值: p -= 阈值 并施放`（滚动 + 单次大额跨多边界;
         Gunpowder Courier BG26_810 同款取模口径）
      3. 施放 = 效果施法（batch_econ_misc2 Eredar Escapist 先例）:
         `create_spell(BG28_168)` + `run_script_hook(spell, "on_play",
         ctx={})` + 实体 `zone=REMOVED` —— 不经手牌、不计费、不占池、
         不广播 `card_played`（防递归）
      4. 数据链断裂 → GameStateError（fail-loud）; 只作用于本人支出

    Test: test_batch_trinkets13.py — 累计 6 金不施放、第 7 金恰好全体
      +num(0)/+num(1) / 一次 14 金连续施放 2 次（+2×num）/ 对手支出
      不触发（正对照: 本人 7 金触发）/ 数据链解析 == BG28_168

    Params: {0}=7 {2}=7（BG30_MagicItem_999 num(0)/num(2)）;
              法术侧 {0}=1 {1}=1（BG28_168 CardDef 权威）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        ring = game.trinket_related_card(source.card_id)
        if ring is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")
        threshold = _num(game, source.card_id, 2)
        state = {"p": 0}

        def on_spent(g, hero=None, amount=0, _h=h, _src=source, **kw):
            if hero is not _h or amount <= 0:
                return
            if _src not in _h.trinkets:
                return
            state["p"] += amount
            while state["p"] >= threshold:
                state["p"] -= threshold
                spell = g.create_spell(ring.id, controller=_h)
                g.run_script_hook(spell, "on_play", ctx={})
                spell.zone = Zone.REMOVED

        game.events.register(Listener(event=GOLD_SPENT, owner=source,
                                      callback=on_spent))
        return None


# ══════════════ BG31_MagicItem_903 Wisdomball Supply ══════════════

class WisdomballSupplyScript:
    """
    Natural Language: [x]Get a Knockoff
    Wisdomball. At the start
    of each turn, repeat this.

    Formal Spec:
      1. on_bind: `_grant_related(本人, source)` —— 数据链 dbf 113902 →
         BG30_802 Knockoff Wisdomball（`card_type=42 BACON_SPELL`、
         `is_pool_spell=False` → 非池法术 token，零池操作;
         `grant_card_copy_to_hand` 以 `create_spell` 入手）
      2. start_of_turn（饰品 SoT 钩子）: "repeat this" → 再授予 1 张
      3. 只进本人手牌（满手排队 RULES §3.3）

    Test: test_batch_trinkets13.py — 绑定后本人手牌恰多 1 张 BG30_802
      且法术池不变量不变 / 真实 end_recruit_phase 后再 +1 / 对手手牌
      不变 / 数据链解析 == BG30_802

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_related(game, h, source)
        return None


# ══════════════ BG32_MagicItem_170 Spell-powered Wrench ══════════════

class SpellPoweredWrenchScript:
    """
    Natural Language: After you play a <b>Magnetic</b> minion, cast Repair
    Job on a random friendly Mech.

    Formal Spec:
      1. on_bind 注册持久 CARD_PLAYED 监听器（owner=饰品）: 引擎在
         磁力**吸附**路径（`play_minion` magnetic_target 分支）与
         普通打出路径（`_run_play_effects`）都广播 `card_played`，
         携带 card=
      2. 条件: `isinstance(card, Minion)` ∧ `card.controller is 本人`
         ∧ `card.has(GameTag.MAGNETIC)`（MAGNETIC tag 权威）
      3. 目标 = 本人棋盘存活机械（race ∈ (MECH, ALL)）随机 1 只
         （"a random friendly Mech" 无 "Choose"/[Targeted] → 随机;
         SOP §8 判别法）; 无机械 → 落空（不施放）
      4. 施放 = 效果施法: `create_spell(Repair Job)`（数据链 dbf 133711
         → BG36_624，池法术 T3; **不 acquire** —— 效果施法不占池，
         Eredar Escapist / Seafloor Recruiter 先例）+
         `run_script_hook(spell, "on_play", ctx={"target": 选中机械})`
         （Repair Job `needs_target=True`，`on_play` 读 ctx["target"];
         数值由该法术自身 `num(0)/num(1)` 决定 = +4/+8）+
         实体 zone=REMOVED
      5. 只作用于本人; 对手打出磁力随从/机械不触发

    Test: test_batch_trinkets13.py — 本人打出磁力随从后棋盘某机械恰
      +num(0)/+num(1)（对照无饰品不变）/ 打出非磁力随从不施放（正对照:
      磁力确实施放）/ 对手打出磁力随从不影响本人机械 / 本人无机械时
      落空不崩 / 数据链解析 == BG36_624

    Params: 无模板参数（法术数值取自 BG36_624 CardDef）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        job = game.trinket_related_card(source.card_id)
        if job is None:
            raise GameStateError(
                f"{source.card_id}: evolution_card_id broken data chain")

        def on_played(g, card=None, _h=h, **kw):
            if not isinstance(card, Minion) or card.controller is not _h:
                return
            if not card.has(GameTag.MAGNETIC):
                return
            mechs = [m for m in _h.board
                     if not m.dead and m.race in _MECH_RACES]
            if not mechs:
                return
            pick = g.rng.choice(mechs, label="spell_powered_wrench")
            spell = g.create_spell(job.id, controller=_h)
            g.run_script_hook(spell, "on_play", ctx={"target": pick})
            spell.zone = Zone.REMOVED

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════ BG32_MagicItem_172 Boom's Monster Portrait ══════════════

class BoomsMonsterPortraitScript:
    """
    Natural Language: [x]Get a Dr. Boom's Monster.
    At the start of every turn,
    get another.

    Formal Spec:
      1. on_bind: `_grant_related(本人, source)` —— 数据链 dbf 115676 →
         BG31_176 Dr. Boom's Monster（非池 token，零池操作）入手
      2. start_of_turn（饰品 SoT 钩子）: "get another" → 再授予 1 只
      3. 只进本人手牌（满手排队 RULES §3.3）

    Test: test_batch_trinkets13.py — 绑定后本人手牌恰多 1 只 BG31_176
      且随从池不变量不变 / 真实 end_recruit_phase 后再 +1 / 对手手牌
      不变 / 数据链解析 == BG31_176

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_related(game, h, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_related(game, h, source)
        return None


# ══════════════ 注册 ══════════════

def register() -> list[str]:
    """注册片 3 中 13 张 CORRECT 饰品（DEFERRED 5 张见模块 docstring；917/952 已迁 batch_trinkets23）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_876", ManipulatorPortraitScript),
        ("BG30_MagicItem_879", DalaranCheeseWheelScript),
        ("BG30_MagicItem_888", SouvenirStandScript),
        ("BG30_MagicItem_919", NazjatarPostcardScript),
        ("BG30_MagicItem_921", FlagbearerPortraitScript),
        ("BG30_MagicItem_930", BurglingClawScript),
        ("BG30_MagicItem_942", MechaJaraxxusStickerScript),
        ("BG30_MagicItem_943", SurveyorPortraitScript),
        ("BG30_MagicItem_991", FelbatPortraitScript),
        ("BG30_MagicItem_999", FancySpellbookScript),
        ("BG31_MagicItem_903", WisdomballSupplyScript),
        ("BG32_MagicItem_170", SpellPoweredWrenchScript),
        ("BG32_MagicItem_172", BoomsMonsterPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
