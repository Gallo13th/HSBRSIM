"""批次 trinkets7 — 饰品第七批（作业单 2026-09-02）。

与 batch_trinkets1..6 的 id 集合互不相交。数值一律取自
`data/bg_trinkets.json` 的 `CardDef.num(0/1)`；文本无占位符的卡按
SOP §3 以文本字面量实现并在各类 `Params:` 行声明。

主题: **单卡触发的饰品**——每张的效果都能落在既有引擎原语上:
  - 酒馆法术增幅标签（`TAVERN_SPELL_EXTRA_ATK/HEALTH`，消费点
    `actions.racefx.tavern_spell_buff`）
  - 免费刷新（`GameTag.FREE_REFRESH_REMAINING`，消费点
    `game.refresh_tavern`）
  - 升级费加值（`GameTag.UPGRADE_COST_MOD`，消费点
    `game.upgrade_tavern`）
  - 事件监听（`card_played` / `tavern_spell_cast` / `minion_bought` /
    `summon` / `reborn` / `after_attack` / `tavern_refresh`）
  - 池感知获取（`GetRandomMinion` / `actions.discover._pool_candidates`
    + `minion_pool.acquire`）
  - 关联卡数据链（`CardDef.evolution_card_id` → `CardDB.by_dbf`）

实现（19 个 id / 19 张饰品）:
  BG32_MagicItem_700  Marvelous Mushroom    — 酒馆法术 +num/+num，每回合
                                              永久递增
  BG35_MagicItem_710  Miniature Ship        — 施放酒馆法术: 海盗 +num/+num
  BG36_MagicItem_205  Deathwhisper Sticker  — 友方复生: 全体 +num/+num
  BG32_MagicItem_888  Recycling Sticker     — 打出元素: 1 次免费刷新
  BG36_MagicItem_300  Frigid Blossom        — 刷新后升级费 -1
  BG36_MagicItem_307  Wand of Divination    — 对随从施法 num(0) 次: +1 金
  BG35_MagicItem_890  Sunken Anchor         — num(0) 张随机 Bounty，
                                              每回合再来
  BG30_MagicItem_993  Pagle's Fishing Rod   — 随机 T7 随从，每回合再来
  BG35_MagicItem_301  Scraper Sticker       — 随机磁力机械，每回合再来
  BG30_MagicItem_430  Rockin' Music Box     — 随机战吼随从，每回合再来
  BG30_MagicItem_706  Reflective Pendant    — 随机友方随从的 plain copy，
                                              每回合再来
  BG30_MagicItem_972  Karazhan Chess Set    — SoC: 复制最左随从
  BG30_MagicItem_916  Essence of Dreams     — num(0) 张 Dreamer's Embrace
                                              （数据链），每回合 +num(1)
  BG32_MagicItem_360  Baleful Incense       — SoC: 最左/最右亡灵 Reborn
  BG36_MagicItem_200  Herding Horn          — 友方 Rally 攻击: 免费刷新
  BG36_MagicItem_212  Wolfhead Flail        — EoT: 触发最左两个亡语
  BG36_MagicItem_840  Secret Schematic      — 买到机械: 随机酒馆法术
  BG35_MagicItem_700  Wildfeather Duster    — num(1) 只野兽后: 随机野兽
  BG35_MagicItem_731  Deathtouch Apple      — 友方亡灵复生: 再给 Reborn
                                              （每回合 num(1) 次）

DEFERRED（本批评估后放弃；每张附具体引擎依赖）:
  - BG30_MagicItem_942 Mecha-Jaraxxus Sticker — "Get 2 random Magnetic
    Mecha-Demons"。36.2.2 数据实测: 池内**没有任何** race=DEMON 且
    keywords 含 magnetic 的随从（0 个）→ 效果恒空转。Dependency: 补丁
    新增 Magnetic Demon，或数据层给出 "Mecha-Demon" 子集定义。
  - BG32_MagicItem_366 Guiding Candle — "Your first two Refreshes each
    turn contain only Tier 6 cards"。引擎只有 `hero._tavern_offer_tier_only`
    （含义 = 与酒馆等级同档）与 `_tavern_min_tier` 下限，没有"指定第 N
    档"的过滤，也没有"每回合前 N 次刷新"计数协议。
    Dependency: `hero._tavern_offer_tier_exact` + 每回合刷新计数。
  - BG30_MagicItem_804 Ancient Wishbone — "Your Hero Power triggers
    twice"。`use_hero_power` 只支持 `uses_per_turn` / `hp_uses`（多次
    **使用**），没有"技能效果结算翻倍"的钩子。
    Dependency: hero_power 效果倍率协议。
  - BG30_MagicItem_986 Peacebloom Candle — "The first {1} Tavern spells
    you buy each turn are free"。引擎只有单次 `NEXT_SPELL_COST_REDUCTION`
    （购买成交后清零），没有每回合 N 次免费法术购买计数。
    Dependency: `FREE_SPELL_BUYS_THIS_TURN` 及 `buy_from_tavern` 消费点。
  - BG32_MagicItem_957 Grifter Portrait — "The first Pirate you buy each
    turn is free"。`FREE_MINION_BUYS_THIS_TURN` 不受种族过滤。
    Dependency: 种族限定免费购买协议。
  - BG32_MagicItem_921 Cowrie Necklace — "Tavern spells that give stats
    cost (2) less"。需要按"法术效果类别（give stats）"持久折扣；池只有
    单次 `NEXT_SPELL_COST_REDUCTION`。Dependency: 分类持久折扣协议。
  - BG35_MagicItem_713 Trusty Crowbar — "Whenever you get a Pirate..."。
    引擎无 hero 级"获得卡牌"事件（`on_enter_hand` 是实体级脚本钩子，
    且无法反查获得者/来源）。Dependency: hero 级 card_gained 事件。
  - BG30_MagicItem_703 Mystery Cube / BG30_MagicItem_888 Souvenir Stand /
    BG30_MagicItem_891 Trip Vouchers / BG36_MagicItem_305 Rune of
    Transmutation / BG35_MagicItem_816 Orb of the Unknown — 饰品
    **非商店授予/替换**族。会话内实测: 主线正并行落地
    `Game.grant_trinket` / `grant_random_trinket` / `replace_trinket` +
    `trinket_bought` / `trinket_granted` 事件（工作区未提交），本批
    **不注册依赖在飞引擎改动的卡**（避免与主线并发改动竞态）。逐卡
    剩余依赖:
      * BG35_MagicItem_816 Orb of the Unknown — "Get a random Lesser
        Trinket": 仅需 `grant_random_trinket(hero, "lesser")`（已在飞）。
      * BG30_MagicItem_703 Mystery Cube — "Choose from 2 new Lesser
        Trinkets to replace this for free": 还需"2 选 1 免费替换"的
        PendingChoice 协议（无现成 Action）。
      * BG30_MagicItem_888 Souvenir Stand — "transforms into a copy of
        it": `grant_trinket` 的 `_trinkets_granted` 去重会拒绝第二张
        同名 Greater，需"允许重复授予已获得饰品"的复制协议。
      * BG30_MagicItem_891 Trip Vouchers — "In 2 turns, choose a Greater
        Trinket to buy and replace this": 需"延迟 + 付费选择 +
        replace_trinket"链路。
      * BG36_MagicItem_305 Rune of Transmutation — "replace this with a
        random Greater **Naga** Trinket": `grant_random_trinket` 无
        subset 过滤参数。
  - BG30_MagicItem_992 Darnassus Pie — "Minions in the Tavern have +1/+1
    for each minion you've sold this turn"。`TavernBuff` 是静态数值
    描述子，无"随回合内计数动态重算"协议（2026-09-02 已落地）。
    Dependency: 动态酒馆 Buff（按 hero 计数求值）。
    Status: 已由 batch_trinkets24 注册（动态逐回合酒馆 Buff 原语已于 2026-09-02 落地）
  - BG32_MagicItem_417 Tarecgosa Sticker — "Your left and right-most
    Dragons permanently keep Bonus Keywords and stats gained in combat"。
    引擎 PERSIST 是**单实体 tag**（Tarecgosa / Persistent Poet），不支持
    "按位置 + 种族持续授予"的光环。Dependency: 位置/种族 PERSIST 光环。
  - BG36_MagicItem_373 Multilayered Shield — "improved by each different
    friendly minion type"。需要随棋盘类型数实时重算的酒馆法术增幅
    光环，无重算协议。Dependency: 动态 `TAVERN_SPELL_EXTRA_*` 光环。
  - BG30_MagicItem_823 Wax Imprinter — "Gain 2 Gold and take 2 damage.
    ... (if possible)"。`(if possible)` 无权威读法（是否指生命不足
    以承受则跳过 / 是否允许致死），SOP §6b 查证无证据。
    Dependency: 官方裁定或实测。
  - BG32_MagicItem_280 Eclectic Shrine — "Give a friendly minion of each
    different type +{0}/{1}. Improve this permanently"。两处无权威读法:
    (a) All 型随从是否可为每个类型重复获得同一 buff；
    (b) "improve this permanently" 在首次触发**前**还是**后**递增。
    Dependency: 官方裁定。
    Status: 已由 batch_trinkets24 注册（两处历史 AMBIGUOUS 已由仓内既有先例裁定，2026-09-02 落地）
  - BG30_MagicItem_917 Rusty Trident — "SoC: Give your Naga
    'Deathrattle: Get a random Spellcraft spell.'"。战斗内授予亡语目前
    只有 batch_hero_combat3 的私有 `_grant_combat_deathrattle` + COMBAT_END
    恢复协议（无共享引擎原语），且 "random Spellcraft spell" 没有数据
    字段定义可授予集合（Vashj 技能自建 ad-hoc 列表）。
    Dependency: 共享 grant_combat_deathrattle 原语 + Spellcraft 法术集合。
  - BG35_MagicItem_840 Chromatic Tear — "Get a random Chromadrake"。
    数据中 Chromadrake 家族只有 `_Gt`/`t` token（5 色），没有"家族"
    字段；按名字启发式建候选集不符合"零硬编码卡 id"纪律。
    Dependency: 数据层族字段（或明示的 5 色候选清单）。

协议: 饰品实体经 `_offer_trinkets` 购买 → `hero.trinkets`；脚本只挂
`on_bind` / `start_of_turn` / `end_of_turn` / `start_of_combat`（接线
审计 W1 白名单）。全部状态写在 **hero 作用域**（GameTag / 闭包）或
**source 实体属性**（非 game 级 flag——SOP §12 item 9）。
"""

from __future__ import annotations

from typing import Optional

from hsrl2.actions import (
    Buff,
    GainGold,
    GainKeyword,
    GetRandomMinion,
)
import hsrl2.constants as C
from hsrl2.actions.discover import _pool_candidates
from hsrl2.events import (
    AFTER_ATTACK,
    CARD_PLAYED,
    MINION_BOUGHT,
    REBORN_EVENT,
    SUMMON,
    TAVERN_REFRESH,
    TAVERN_SPELL_CAST,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell as SpellType
from hsrl2.tags import GameTag, Race

# 含 All 型的匹配族（Amalgam 全种族，RULES §6.4 匹配规则的通用裁定）
_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)
_BEAST_RACES = (Race.BEAST, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)
_MECH_RACES = (Race.MECH, Race.ALL)


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


def _living(hero):
    return [m for m in hero.board if not m.dead]


def _bump_tag(hero, tag: GameTag, amount: int) -> None:
    """hero tag 叠加式递增（TAVERN_SPELL_EXTRA_*/FREE_REFRESH_REMAINING
    等引擎读取点均按"叠加"语义，禁止覆盖）。"""
    hero.set(tag, hero.get(tag, 0) + amount)


def _random_pool_minion(game, hero, *, count: int = 1, race=None,
                        keyword: Optional[str] = None,
                        min_tier: Optional[int] = None,
                        max_tier: Optional[int] = None,
                        label: str = "trinket_random_minion") -> int:
    """从共享池随机获取 count 只过滤后的随从（池感知，RULES §2.3/§2.4）。

    - 候选过滤复用 `actions.discover._pool_candidates`（剩余量 > 0 /
      本局禁用种族 / tier / 种族），keyword 再按 CardDef.keywords 过滤
    - 每次抽取后重新求候选，池耗尽即少拿（官方落空语义）
    - 选中 `minion_pool.acquire` 占池 → create_minion →
      pending_hand_add（满手排队 RULES §3.3）
    返回实际获得的只数。
    """
    gained = 0
    for _ in range(count):
        cands = _pool_candidates(game, race, min_tier, max_tier)
        if keyword is not None:
            cands = [cid for cid in cands
                     if keyword in game.db.get(cid).keywords]
        if not cands:
            break
        pick = game.rng.choice(cands, label=label)
        if not game.minion_pool.acquire(pick):
            continue
        game.pending_hand_add(hero, game.create_minion(pick, controller=hero))
        gained += 1
    return gained


def _grant_copies(game, hero, card_id: str, count: int) -> None:
    """指定卡 ×count 进手牌（满手排队 RULES §3.3）。

    池法术（`is_pool_spell`）逐张 `spell_pool.acquire` 占池（RULES
    §3.6.1，池空则净增——Mystic Essence 先例）；非池卡（token / BACON
    SPELL）直接生成。
    """
    d = game.db.get(card_id)
    if d is None:
        raise GameStateError(f"unknown card_id {card_id}")
    for _ in range(count):
        if d.is_pool_spell and game.spell_pool.available(card_id) > 0 \
                and not game.spell_pool.acquire(card_id):
            raise GameStateError(f"spell_pool acquire failed for {card_id}")
        game.pending_hand_add(hero, game.create_spell(card_id,
                                                      controller=hero))


def _grant_evolution_copies(game, hero, source, count: int) -> str:
    """`evolution_card_id` 数据链解析关联卡（零硬编码卡 id）并发放 count 张。

    返回解析出的 card_id（供测试/日志）。
    """
    d = game.db.get(source.card_id)
    if d is None or d.evolution_card_id is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    token = game.db.by_dbf(d.evolution_card_id)
    if token is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id "
            f"{d.evolution_card_id} not in db")
    _grant_copies(game, hero, token.id, count)
    return token.id


def _grant_bounties(game, hero, count: int) -> int:
    """获得 count 张随机 Bounty（`constants.BOUNTY_SPELL_IDS` 五张）。

    36.2.2 数据核实: Bounty 是 `is_pool_spell=True` 的池法术（5 张 T3
    全在 `db.pool_spells()`）→ 候选限定 `spell_pool.available > 0`，
    选中 `spell_pool.acquire` 占池（RULES §2.3；batch_misc Sky Admiral
    Rogers 同口径）。池内 Bounty 耗尽 → 该次落空（官方池约束）。
    "random" 无 "different" 措辞 → 池内仍有副本时允许重复。
    返回实际发放张数。
    """
    granted = 0
    for _ in range(count):
        cands = [b for b in sorted(C.BOUNTY_SPELL_IDS)
                 if game.spell_pool.available(b) > 0]
        if not cands:
            break
        pick = game.rng.choice(cands, label="trinket_bounty")
        if not game.spell_pool.acquire(pick):
            continue
        game.pending_hand_add(hero, game.create_spell(pick,
                                                      controller=hero))
        granted += 1
    return granted


def _random_tavern_spell(game, hero, label: str) -> bool:
    """获得 1 张随机酒馆法术（池感知）。

    tier 口径: `tech_level <= hero.tavern_tier`（与 Holli'dae /
    Mystic Essence / SpellPool.draw_tavern 一致——2026-09-02 Yogg 修复
    后全仓统一），并经 `Game.tavern_spell_candidates` 施加**存在档
    白名单**（异变 101/102 非存在档法术不可达）。占池 → create_spell
    → pending_hand_add。
    """
    cands = game.tavern_spell_candidates(min_tier=1,
                                         max_tier=hero.tavern_tier)
    if not cands:
        return False
    pick = game.rng.choice(cands, label=label)
    if not game.spell_pool.acquire(pick):
        return False
    game.pending_hand_add(hero, game.create_spell(pick, controller=hero))
    return True


def _plain_copy(game, ent: Minion) -> Minion:
    """官方 "plain copy": 无附魔、非金色（S14 用语，batch_quest_rewards
    `_plain_copy` 同构）。

    - 回退基础卡 id（三连金/非三连金均走 TRIPLE_BASE_CARD_ID）后按
      **非金色**创建
    - 不复制 `_buffs`、不复制 GOLDEN 态
    - 复制体不占池（Rafraam/Tess 先例: 复制语义不由池供给）
    """
    base_id = ent.get(GameTag.TRIPLE_BASE_CARD_ID, None) or ent.card_id
    return game.create_minion(base_id, controller=ent.controller,
                              golden=False)


def _exact_copy(game, hero, src: Minion) -> Minion:
    """精确副本（Zerek/Reno 先例: 同 card_id + golden 同源 + 全量 buff
    并集——"a copy" 与 "a plain copy" 是两个不同用语）。"""
    copy = game.create_minion(src.card_id, controller=hero,
                              golden=src.is_golden)
    src.copy_buffs_to(copy)
    return copy


def _has_rally_hook(m) -> bool:
    """随从是否具有 Rally 效果（"Rally minion" 判定）。

    双通道: GameTag.RALLY（data 关键词权威）**或** 脚本类含 rally 钩子
    （金色卡定义不携带关键词标志——batch_rally2 已报告的数据缺口，
    脚本存在性是行为权威）。
    """
    if m.has(GameTag.RALLY):
        return True
    return getattr(m.scripts, "rally", None) is not None


# ══════════════════ BG32_MagicItem_700 Marvelous Mushroom ══════════════════

class MarvelousMushroomScript:
    """
    Natural language: Your Tavern spells give an extra +{0}/+{1}.
    At the start of each turn, improve this.

    Formal spec:
      1. on_bind: 本人 `TAVERN_SPELL_EXTRA_ATK += num(0)`、
         `TAVERN_SPELL_EXTRA_HEALTH += num(1)`——叠加式；消费点 =
         `actions.racefx.tavern_spell_buff`（所有 give-stats 酒馆法术的
         统一出口，"Your Tavern spells give an extra +X" 家族）
      2. start_of_turn（饰品 SoT 钩子）: 同额再叠加一次——"At the start
         of each turn, improve this"（永久递增，跨回合累积）
      3. 只作用于本人（hero 作用域 tag），对手的法术不受影响

    Test: test_batch_trinkets7.py — 绑定后 tag = num(0)/num(1) / 真实
      play_spell(Shiny Ring) 使目标 +（基础+额外）/ 真实
      end_recruit_phase 后 tag 翻倍（下回合法术再加一档）/ 对手施法
      不吃本人增幅

    Params: {0}=1 {1}=1（BG32_MagicItem_700 num(0/1)）
    """

    @staticmethod
    def _improve(hero, game, source) -> None:
        _bump_tag(hero, GameTag.TAVERN_SPELL_EXTRA_ATK,
                  _num(game, source.card_id, 0))
        _bump_tag(hero, GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                  _num(game, source.card_id, 1))

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        MarvelousMushroomScript._improve(h, game, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        MarvelousMushroomScript._improve(h, game, source)
        return None


# ══════════════════ BG35_MagicItem_710 Miniature Ship ══════════════════

class MiniatureShipScript:
    """
    Natural language: After you cast a Tavern spell, give your Pirates
    +{0}/+{1}.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: TAVERN_SPELL_CAST
         （spell=）——引擎只对 `is_pool_spell` 法术广播（game.py），
         正是 "Tavern spell" 语义; `spell.controller is 本人` owner 隔离
      2. 每次触发: 本人棋盘每个存活海盗（race ∈ (PIRATE, ALL)，Amalgam
         规则）获得 Buff(atk=num(0), health=num(1)) 永久增益
      3. 无海盗 → 落空（不补偿）; 法术双施按施放次数各广播一次

    Test: test_batch_trinkets7.py — 真实 play_spell 酒馆法术 → 海盗
      +num/+num、非海盗不变 / 对手施放不触发 / 无饰品对照不加

    Params: {0}=2 {1}=2（BG35_MagicItem_710 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not h:
                return
            atk = _num(g, source.card_id, 0)
            health = _num(g, source.card_id, 1)
            targets = [m for m in _living(h) if m.race in _PIRATE_RACES]
            if not targets:
                return
            g.run_actions([Buff(m, atk=atk, health=health)
                           for m in targets])

        game.events.register(Listener(event=TAVERN_SPELL_CAST,
                                      owner=source, callback=on_cast))
        return None


# ══════════════════ BG36_MagicItem_205 Deathwhisper Sticker ══════════════════

class DeathwhisperStickerScript:
    """
    Natural language: After a friendly minion is <b>Reborn</b>, give your
    minions +{0}/+{1}.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: REBORN_EVENT（minion=）——
         引擎在复生体**原位回归后**广播（game._process_death_inner 步骤
         4），故复生体本身也在棋盘上、同样获得增益
      2. 过滤 `minion.controller is 本人`（对手复生不触发）
      3. 每次触发: 本人棋盘全部存活随从获得 Buff(num(0), num(1))；
         战斗期增益由 run_combat 快照回滚（RULES §3.5），招募期
         （Fishbait 等）为永久增益

    Test: test_batch_trinkets7.py — 战斗内真实 _process_single_death 触发
      复生 → 全体 +num/+num（含复生体）/ 对手复生不触发 / 无饰品对照

    Params: {0}=2 {1}=2（BG36_MagicItem_205 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_reborn(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            atk = _num(g, source.card_id, 0)
            health = _num(g, source.card_id, 1)
            living = _living(h)
            if not living:
                return
            g.run_actions([Buff(m, atk=atk, health=health)
                           for m in living])

        game.events.register(Listener(event=REBORN_EVENT, owner=source,
                                      callback=on_reborn))
        return None


# ══════════════════ BG32_MagicItem_888 Recycling Sticker ══════════════════

class RecyclingStickerScript:
    """
    Natural language: After you play an Elemental, gain a free
    <b>Refresh</b>.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: CARD_PLAYED（card=）——
         仅 `isinstance(card, Minion)`（法术也走 card_played）且
         `card.controller is 本人`，race ∈ (ELEMENTAL, ALL)
      2. 每次触发: 本人 `FREE_REFRESH_REMAINING += 1`——消费点
         `game.refresh_tavern`（非 auto 刷新优先消耗免费次数，不扣金币）
      3. 叠加式（多次打出元素累计多次免费刷新）; 只作用于本人

    Test: test_batch_trinkets7.py — 真实 play_minion 元素 → 免费刷新
      +1 且随后 refresh_tavern 不扣金币 / 非元素不触发 / 对手打出元素
      不影响本人

    Params: refresh=1（"a free Refresh" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not h:
                return
            if card.race not in _ELEMENTAL_RACES:
                return
            _bump_tag(h, GameTag.FREE_REFRESH_REMAINING, 1)

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG36_MagicItem_300 Frigid Blossom ══════════════════

class FrigidBlossomScript:
    """
    Natural language: [x]After you <b>Refresh</b>, reduce the cost of
    upgrading the Tavern by (1).

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: TAVERN_REFRESH（hero=,
         auto=）——引擎在酒馆**填充完成后**广播（game.refresh_tavern
         尾部）
      2. **"you Refresh" = 玩家主动刷新**: 过滤 `hero is 本人` 且
         `auto is False`——`tavern_refresh` 的 auto 标记是 2026-09-02
         引擎为"Whenever you Refresh the Tavern N times"家族加的区分点
         （回合开始的自动刷新不算"you Refresh"）; 官方 bug 报告
         （Frigid Blossom 不响应 Toki Temporal Tavern 的刷新路径）
         佐证该卡绑定的是**主动刷新**事件
      3. 每次触发 `UPGRADE_COST_MOD -= 1`——消费点
         `game.upgrade_tavern`（cost = max(FLOOR, upgrade_cost + MOD)，
         故负值即为降价）
      4. 叠加式; 只作用于本人

    Test: test_batch_trinkets7.py — 真实 refresh_tavern 后 MOD = -1 /
      自动刷新（auto=True）不触发（正对照: 手动刷新触发）/ 真实
      upgrade_tavern 少付 1 金（对照无饰品）/ 对手刷新不触发

    Params: reduction=1（"by (1)" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_refresh(g, hero=None, auto=False, **kw):
            if hero is not h or auto:
                return
            h.set(GameTag.UPGRADE_COST_MOD,
                  h.get(GameTag.UPGRADE_COST_MOD, 0) - 1)

        game.events.register(Listener(event=TAVERN_REFRESH, owner=source,
                                      callback=on_refresh))
        return None


# ══════════════════ BG36_MagicItem_307 Wand of Divination ══════════════════

class WandOfDivinationScript:
    """
    Natural language: [x]After you cast 3 spells on minions, gain 1 Gold.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: CARD_PLAYED（card=,
         target=）——引擎在法术**结算后**广播且携带 target（game.py）
      2. 计数条件: `isinstance(card, Spell)` 且 `card.controller is
         本人` 且 `isinstance(target, Minion)` 且 `not target.dead`
         （"spells on minions"）; 计数跨回合累积（文本无 "this turn"）
      3. 达到 num(0)=3 → 清零并 GainGold(hero, 1)
      4. 只进本人金币; 对手施法不计数

    Test: test_batch_trinkets7.py — 前 2 次对随从施法定向法术不发放 /
      第 3 次恰好 +1 金且计数清零 / 无随从目标的法术不计数 / 对手施法
      不计数

    Params: {0}=3（BG36_MagicItem_307 num(0)） gold=1（"gain 1 Gold"
              文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 0)
        state = {"n": 0}

        def on_played(g, card=None, target=None, **kw):
            if card is None or card.controller is not h:
                return
            if not isinstance(card, SpellType):
                return
            if not isinstance(target, Minion) or target.dead:
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            g.run_actions(GainGold(h, 1))

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════════ BG35_MagicItem_890 Sunken Anchor ══════════════════

class SunkenAnchorScript:
    """
    Natural language: Get {0} random <b>Bounties</b>. At the start of each
    turn, repeat this.

    Formal spec:
      1. on_bind: 获得 num(0)=2 张随机 Bounty（`constants.BOUNTY_SPELL_IDS`
         五张 T3 法术）——36.2.2 数据核实 Bounty 是 `is_pool_spell=True`
         的池法术，故候选限定 `spell_pool.available > 0`、选中
         `spell_pool.acquire` 占池（RULES §2.3），create_spell +
         pending_hand_add（满手排队 RULES §3.3）; 池耗尽 → 落空
      2. start_of_turn（饰品 SoT 钩子）: 同款再发放 num(0) 张——"At the
         start of each turn, repeat this"
      3. 只进本人手牌

    Test: test_batch_trinkets7.py — 绑定入手 num(0) 张且 id ∈
      BOUNTY_SPELL_IDS、法术池 -num(0) / 真实 end_recruit_phase 后再
      入手 num(0) 张 / 对手手牌不变 / 无饰品对照不获取

    Params: {0}=2（BG35_MagicItem_890 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_bounties(game, h, _num(game, source.card_id, 0))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_bounties(game, h, _num(game, source.card_id, 0))
        return None


# ══════════════════ BG30_MagicItem_993 Pagle's Fishing Rod ══════════════════

class PaglesFishingRodScript:
    """
    Natural language: [x]Get a random Tier 7 minion. At the start of each
    turn, get another.

    Formal spec:
      1. on_bind: GetRandomMinion(hero, min_tier=7, max_tier=7)——池中仍有
         副本的 Tier 7 随从里随机取一只（RULES §2.4; 36.2.2 数据中
         tech_level=7 的池随从 12 只），占池 + 满手排队
      2. start_of_turn（饰品 SoT 钩子）: 同款再获取——"At the start of
         each turn, get another"
      3. 只进本人手牌; T7 池耗尽 → 落空（官方池约束）

    Test: test_batch_trinkets7.py — 绑定入手 1 只 tech_level==7 且 T7 池
      -1 / 真实 end_recruit_phase 再入手 1 只 / 对手手牌不变 /
      无饰品对照不获取

    Params: tier=7（"Tier 7" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def _get(h, game):
        return GetRandomMinion(h, min_tier=7, max_tier=7)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return PaglesFishingRodScript._get(h, game)

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return PaglesFishingRodScript._get(h, game)


# ══════════════════ BG35_MagicItem_301 Scraper Sticker ══════════════════

class ScraperStickerScript:
    """
    Natural language: Get a random <b>Magnetic</b> Mech. At the start of
    each turn, get another.

    Formal spec:
      1. on_bind: 从池中随机获取 1 只 race ∈ (MECH, ALL) 且 keywords 含
         "magnetic" 的随从（36.2.2 数据: 6 只磁力机械），占池 + 满手排队
      2. start_of_turn（饰品 SoT 钩子）: 同款再获取
      3. 只进本人手牌; 池耗尽 → 落空

    Test: test_batch_trinkets7.py — 绑定入手 1 只磁力机械且该 id 池 -1 /
      真实 SoT 再入手 / 对手手牌不变

    Params: count=1（"a random Magnetic Mech" 文本字面量）
    """

    @staticmethod
    def _get(h, game):
        _random_pool_minion(game, h, count=1, race=Race.MECH,
                            keyword="magnetic", label="scraper_sticker")
        return None

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return ScraperStickerScript._get(h, game)

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return ScraperStickerScript._get(h, game)


# ══════════════════ BG30_MagicItem_430 Rockin' Music Box ══════════════════

class RockinMusicBoxScript:
    """
    Natural language: [x]Get a random <b>Battlecry</b> minion. At the start
    of each turn, get another.

    Formal spec:
      1. on_bind: 从池中随机获取 1 只 keywords 含 "battlecry" 的随从
         （36.2.2 数据: 39 只战吼池随从），占池 + 满手排队
      2. start_of_turn（饰品 SoT 钩子）: 同款再获取
      3. 只进本人手牌; 池耗尽 → 落空

    Test: test_batch_trinkets7.py — 绑定入手 1 只战吼随从且池 -1 /
      真实 SoT 再入手 / 对手手牌不变

    Params: count=1（"a random Battlecry minion" 文本字面量；CardDef
              num(0)=1 与文本一致）
    """

    @staticmethod
    def _get(h, game):
        _random_pool_minion(game, h, count=1, keyword="battlecry",
                            label="rockin_music_box")
        return None

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return RockinMusicBoxScript._get(h, game)

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return RockinMusicBoxScript._get(h, game)


# ══════════════════ BG30_MagicItem_706 Reflective Pendant ══════════════════

class ReflectivePendantScript:
    """
    Natural language: [x]Get a plain copy of a random friendly minion.
    At the start of each turn, repeat this.

    Formal spec:
      1. on_bind: `game.rng.choice(本人棋盘存活随从)` → plain copy
         （`_plain_copy`: 回退基础卡 id、非金色、不复制 `_buffs`）→
         pending_hand_add（满手排队 RULES §3.3）
      2. start_of_turn（饰品 SoT 钩子）: 同款再取一份
      3. 空棋盘 → 落空; 复制体不占池（复制语义不由池供给）;
         只进本人手牌

    Test: test_batch_trinkets7.py — 绑定入手 1 只与某友方随从同 id 的
      **无附魔**副本（源 +5/+5 而副本为基准属性）/ 池不变 / 真实 SoT
      再入手 1 只 / 空棋盘落空 / 对手手牌不变

    Params: count=1（"a plain copy" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def _get(h, game):
        living = _living(h)
        if not living:
            return None
        src = game.rng.choice(living, label="reflective_pendant")
        game.pending_hand_add(h, _plain_copy(game, src))
        return None

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return ReflectivePendantScript._get(h, game)

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return ReflectivePendantScript._get(h, game)


# ══════════════════ BG30_MagicItem_972 Karazhan Chess Set ══════════════════

class KarazhanChessSetScript:
    """
    Natural language: <b>Start of Combat:</b> Summon a copy of your
    left-most minion.

    Formal spec:
      1. start_of_combat: 本人棋盘**最左**存活随从 → 精确副本
         （`_exact_copy`: 同 card_id + golden 同源 + 全量 buff 并集；
         "a copy" ≠ "a plain copy"）→ `game.summon(hero, copy)`
         （position=None 最右; 满场由 MINION_OVERFLOW 处理）
      2. 战斗内召唤物由 run_combat 快照整体回滚（RULES §3.5）;
         复制体不占池
      3. 空棋盘 → 落空; 只作用于本人棋盘

    Test: test_batch_trinkets7.py — 真实 run_combat: 战斗内 SUMMON 事件
      记录到与最左随从同 id 的复制体（且带源 buff）/ 无饰品对照无复制 /
      对手棋盘不产生复制

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = _living(h)
        if not living:
            return None
        game.summon(h, _exact_copy(game, h, living[0]))
        return None


# ══════════════════ BG30_MagicItem_916 Essence of Dreams ══════════════════

class EssenceOfDreamsScript:
    """
    Natural language: [x]Get {0} |4(copy, copies) of Dreamer's Embrace.
    At the start of each turn, get {1} more.

    Formal spec:
      1. on_bind: 授予 num(0) 张 Dreamer's Embrace——`source` 的
         `evolution_card_id` 数据链解析（dbf 105266 → `BG28_883`，零
         硬编码卡 id）。该卡 `card_type=42`（BACON_SPELL）且
         `is_pool_spell=False`（36.2.2 数据核实）→ token 语义，
         `_grant_copies` 不占法术池; create_spell + pending_hand_add
      2. start_of_turn（饰品 SoT 钩子）: 再授予 num(1) 张
      3. 只进本人手牌（满手排队 RULES §3.3）

    Test: test_batch_trinkets7.py — 绑定入手 num(0) 张 BG28_883 且法术池
      不变 / 真实 end_recruit_phase 后再入手 num(1) 张 / 对手手牌不变 /
      数据链解析 == BG28_883

    Params: {0}=2 {1}=1（BG30_MagicItem_916 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _grant_evolution_copies(game, h, source,
                                _num(game, source.card_id, 0))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_evolution_copies(game, h, source,
                                _num(game, source.card_id, 1))
        return None


# ══════════════════ BG32_MagicItem_360 Baleful Incense ══════════════════

class BalefulIncenseScript:
    """
    Natural language: <b>Start of Combat:</b> Give your left and right-most
    Undead <b>Reborn</b>.

    Formal spec:
      1. start_of_combat: 本人棋盘存活亡灵（race ∈ (UNDEAD, ALL)）按棋盘
         顺序的左端与右端各获 GainKeyword(REBORN)（"left and right-most
         Undead" = 亡灵子序列的两端）
      2. 仅 1 只亡灵时同一实体只授予一次（去重，避免重复 keyword_gained）
      3. 无亡灵 → 落空; 战斗期关键词由 run_combat 快照回滚（RULES §3.5）

    Test: test_batch_trinkets7.py — 3 亡灵 + 1 非亡灵: 仅左右端亡灵获
      Reborn、中位与非亡灵不获 / 战斗内探针在 SoC 后读到 Reborn 集合
      （对照无饰品）/ 对手亡灵不获

    Params: 无模板参数（CardDef 无 {0}/{1} 占位符）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        undead = [m for m in _living(h) if m.race in _UNDEAD_RACES]
        if not undead:
            return None
        targets = [undead[0]]
        if undead[-1] is not undead[0]:
            targets.append(undead[-1])
        return [GainKeyword(m, GameTag.REBORN) for m in targets]


# ══════════════════ BG36_MagicItem_200 Herding Horn ══════════════════

class HerdingHornScript:
    """
    Natural language: Whenever a friendly <b>Rally</b> minion attacks, gain
    a free <b>Refresh</b>.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: AFTER_ATTACK
         （attacker=）——引擎在伤害与死亡结算后广播（combat.py C4）
      2. 条件: `attacker.controller is 本人` 且 attacker 是 Rally 随从
         （`_has_rally_hook` 双通道: GameTag.RALLY 或脚本 rally 钩子）
      3. 触发: 本人 `FREE_REFRESH_REMAINING += 1`（消费点
         `game.refresh_tavern`）; 攻击者已战死不影响（"attacks" 完成）
      4. 只作用于本人（对手 Rally 攻击不发放）

    Test: test_batch_trinkets7.py — 真实攻击（execute_immediate_attack）
      的 Rally 随从 → 免费刷新 +1 且随后刷新不扣金 / 非 Rally 攻击者
      不触发 / 对手 Rally 攻击不给本人

    Params: refresh=1（"a free Refresh" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_attack(g, attacker=None, defender=None, **kw):
            if attacker is None or attacker.controller is not h:
                return
            if not _has_rally_hook(attacker):
                return
            _bump_tag(h, GameTag.FREE_REFRESH_REMAINING, 1)

        game.events.register(Listener(event=AFTER_ATTACK, owner=source,
                                      callback=on_attack))
        return None


# ══════════════════ BG36_MagicItem_212 Wolfhead Flail ══════════════════

class WolfheadFlailScript:
    """
    Natural language: At the end of your turn, trigger your two left-most
    <b>Deathrattles</b>.

    Formal spec:
      1. end_of_turn（饰品 EoT 钩子）: 本人棋盘按从左到右取**前 2 个**
         持 DEATHRATTLE tag 的存活随从（含磁力并入宿主——attach_magnetic
         置 tag），各以 `run_script_hook(m, "deathrattle")` 触发一次
      2. **无死亡**触发（Deathstrider 同构先例）: 不计入
         COUNTER_DEATHRATTLES、不广播 deathrattle_trigger、不回池
      3. 少于 2 个亡语随从 → 有几个触发几个; 0 个 → 落空
      4. 只作用于本人棋盘（对手亡语不触发）

    Test: test_batch_trinkets7.py — 3 个亡语随从: 最左两个各触发 1 次、
      第三个 0 次 / 无亡语落空 / 对手亡语不被本人饰品触发 / 无饰品对照
      0 次

    Params: count=2（"your two left-most" 文本字面量）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        bearers = [m for m in _living(h) if m.has(GameTag.DEATHRATTLE)]
        if not bearers:
            return None
        for m in bearers[:2]:
            # 统一亡语入口（RULES §6.20）: Titus/dr_extra 同样生效
            game.trigger_deathrattle(m, hero=h)
        return None


# ══════════════════ BG36_MagicItem_840 Secret Schematic ══════════════════

class SecretSchematicScript:
    """
    Natural language: [x]After you buy a Mech, get a random Tavern spell.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: MINION_BOUGHT（minion=）
         ——引擎在 `buy_from_tavern` 成功入手后广播
      2. 条件: `minion.controller is 本人` 且 race ∈ (MECH, ALL)
      3. 触发: 获得 1 张随机酒馆法术（池感知; tier ≤ 本人酒馆等级——
         与 Holli'dae/Mystic Essence/`SpellPool.draw_tavern` 同口径），
         `spell_pool.acquire` 占池 → create_spell + pending_hand_add
      4. 池空 → 落空; 只作用于本人（对手买机械不发放）

    Test: test_batch_trinkets7.py — 真实 buy_from_tavern 机械 → 入手 1 张
      池法术且法术池 -1 / 买非机械不发放 / 对手买机械不影响本人 /
      无饰品对照

    Params: count=1（"a random Tavern spell" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_bought(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if minion.race not in _MECH_RACES:
                return
            _random_tavern_spell(g, h, "secret_schematic")

        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        return None


# ══════════════════ BG35_MagicItem_700 Wildfeather Duster ══════════════════

class WildfeatherDusterScript:
    """
    Natural language: [x]After you summon {1} Beasts, get a random Beast.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: SUMMON（minion=）——过滤
         `minion.controller is 本人` 且 race ∈ (BEAST, ALL); 计数 += 1
      2. 达阈值 num(1)=6 → 清零并 GetRandomMinion(hero, race=BEAST)
         （池感知: 占池 RULES §2.3 + 满手排队 RULES §3.3）
      3. 计数跨回合累积（文本无 "this turn"）; 状态存于脚本闭包
      4. 只进本人手牌; 对手召唤野兽不计数

    Test: test_batch_trinkets7.py — 前 num(1)-1 只不发放 / 第 num(1) 只
      恰好入手 1 只野兽且池 -1 / 非野兽召唤不计数 / 对手召唤不计数 /
      阈值 == CardDef.num(1)

    Params: {0}=6 {1}=6（BG35_MagicItem_700 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        threshold = _num(game, source.card_id, 1)
        state = {"n": 0}

        def on_summon(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if minion.race not in _BEAST_RACES:
                return
            state["n"] += 1
            if state["n"] < threshold:
                return
            state["n"] = 0
            g.run_actions(GetRandomMinion(h, race=Race.BEAST))

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summon))
        return None


# ══════════════════ BG35_MagicItem_731 Deathtouch Apple ══════════════════

class DeathtouchAppleScript:
    """
    Natural language: [x]After a friendly Undead is <b>Reborn</b>, give it
    <b>Reborn</b>. <i>({1} times per turn.)</i>

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: REBORN_EVENT（minion=）——
         引擎在复生体原位回归**之后**广播，且复生时已 `clear(REBORN)`
         （game._process_death_inner 步骤 4），故此处重新授予合法、
         不发生同一次死亡内的递归
      2. 条件: `minion.controller is 本人` 且 race ∈ (UNDEAD, ALL)
      3. 每回合最多 num(1)=3 次（"({1} times per turn.)"）——闭包按
         `game.turn` 归零; 达上限后不再授予
      4. 授予 GainKeyword(minion, REBORN)——可再次复生（符文本）;
         只作用于本人亡灵

    Test: test_batch_trinkets7.py — 战斗内亡灵复生后重新带 REBORN /
      同回合第 num(1)+1 次不再授予（上限）/ 真实 end_recruit_phase 推进
      回合后配额重置 / 非亡灵复生不授予 / 对手复生不授予

    Params: {0}=3 {1}=3（BG35_MagicItem_731 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        limit = _num(game, source.card_id, 1)
        state = {"turn": None, "used": 0}

        def on_reborn(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if minion.race not in _UNDEAD_RACES:
                return
            if state["turn"] != g.turn:
                state["turn"] = g.turn
                state["used"] = 0
            if state["used"] >= limit:
                return
            state["used"] += 1
            g.run_actions(GainKeyword(minion, GameTag.REBORN))

        game.events.register(Listener(event=REBORN_EVENT, owner=source,
                                      callback=on_reborn))
        return None


# ══════════════════ 注册 ══════════════════

def register() -> list[str]:
    """注册饰品第七批 19 张（无 DEFERRED 注册项——台账见模块 docstring）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_MagicItem_700", MarvelousMushroomScript),
        ("BG35_MagicItem_710", MiniatureShipScript),
        ("BG36_MagicItem_205", DeathwhisperStickerScript),
        ("BG32_MagicItem_888", RecyclingStickerScript),
        ("BG36_MagicItem_300", FrigidBlossomScript),
        ("BG36_MagicItem_307", WandOfDivinationScript),
        ("BG35_MagicItem_890", SunkenAnchorScript),
        ("BG30_MagicItem_993", PaglesFishingRodScript),
        ("BG35_MagicItem_301", ScraperStickerScript),
        ("BG30_MagicItem_430", RockinMusicBoxScript),
        ("BG30_MagicItem_706", ReflectivePendantScript),
        ("BG30_MagicItem_972", KarazhanChessSetScript),
        ("BG30_MagicItem_916", EssenceOfDreamsScript),
        ("BG32_MagicItem_360", BalefulIncenseScript),
        ("BG36_MagicItem_200", HerdingHornScript),
        ("BG36_MagicItem_212", WolfheadFlailScript),
        ("BG36_MagicItem_840", SecretSchematicScript),
        ("BG35_MagicItem_700", WildfeatherDusterScript),
        ("BG35_MagicItem_731", DeathtouchAppleScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
