"""批次 trinkets11 — 饰品第 11 批（台账 `docs/agents/TRINKET_LEDGER.md` 片 1）。

本批 20 个 id 全部来自台账片 1（BG30_MagicItem_301 … _541），与
batch_trinkets1..10 的 id 集合互不相交；数值一律 `CardDef.num(0/1)`，
金色走 `db.golden_version`，随机一律 `game.rng`。

★ `BG30_MagicItem_438t` Mug of the Sire 的注册裁定（作业单要求先判断）:
  运行时核实 `"BG30_MagicItem_438t" in db.trinket_offer_pool()` → **True**
  （`CardDB.trinket_offer_pool` 只排除「尾 `t`/`t2` **且有同名本体**」的
  升级变体；db 中不存在名为 "Mug of the Sire" 的第二张卡，故它是**独立
  的商店可提供 Greater 饰品**，不是被某效果授予的升级形态）→ 本批按
  普通商店饰品注册。

注册 11 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG30_MagicItem_301  Eternal Portrait     — Get an Eternal Knight;
                                             SoC: 己方 Eternal Knight 获得
                                             Taunt + Reborn
  BG30_MagicItem_303  Automaton Portrait   — SoC: 有空位则召唤 1 个
                                             Ancestral Automaton
  BG30_MagicItem_310  Rivendare Portrait   — Get a Titus Rivendare;
                                             SoC: 己方 Titus 生命翻倍
  BG30_MagicItem_407  Ship in a Bottle     — SoC: 随机海盗「召唤并入手」
                                             （召唤体立即攻击）
  BG30_MagicItem_410  Quilligraphy Set     — Avenge(num(0)=3): 血宝石
                                             本局额外 +1 生命
  BG30_MagicItem_411  Hoggy Bank           — SoC: 己方 Quilboar 获得
                                             「亡语: 获得 2 颗血宝石」
  BG30_MagicItem_420  Book of Medivh       — Discover 一张酒馆法术;
                                             每回合开始再来一次
  BG30_MagicItem_438t Mug of the Sire      — 召唤因战团满员而失败的随从
                                             时，己方随从 +5 攻击
  BG30_MagicItem_441  Tinyfin Onesie       — SoC: 最左随从获得手牌中
                                             最高生命随从的属性
  BG30_MagicItem_442  Blood Golem Sticker  — 友方 Quilboar 死亡时召唤
                                             属性等于其血宝石的 Golem
  BG30_MagicItem_541  Nether Pendant       — 酒馆随从 +num(1)/+num(1);
                                             每 num(0) 次战斗外受伤 +1/+1

DEFERRED 9 张（**不注册**；逐张给出缺失依赖与实现路径——SOP §6b 二态铁律）
══════════════════════════════════════════════════════════════════════
  - BG30_MagicItem_402 Conductor Portrait —
    "Get a Snarling Conductor. Whenever you **discard** a card, this plays
    a Blood Gem on all your minions."
    Dependency: 引擎**完全没有弃牌机制**（`grep -i discard hsrl2/` 只命中
    python 的 set.discard / pytest 注释，零生产调用点）——授予物
    Snarling Conductor（BG28_585）自身文本 "At the start of your turn,
    discard a spell to gain 4 Gold." 同样无法兑现（且该卡未注册）。
    需要: `events.CARD_DISCARDED` 事件 + `game.discard_card(hero, entity)`
    协议（选择器 + 手牌移除）→ 之后本饰品挂 `CARD_DISCARDED` 监听即可
    （另需 Snarling Conductor 本体脚本）。被阻塞卡: 402 + BG28_585。
  - BG30_MagicItem_416 Token of the Old Gods —
    "**Spellcraft:** Choose a minion. Then choose a minion from a Tier
    higher to transform it into."（数据 `spellcraft_id=112813` →
    BG30_MagicItem_416t）
    Dependency: 引擎 Spellcraft 只服务**棋盘随从**
    （`spellcraft.generate_for_hero` 遍历 `hero.board` 且
    `_make_spellcraft_spell` 读 `CardDef.spellcraft_id` 后以
    `minion.controller` 入手）——`hero.trinkets` 既不在遍历范围，也无
    「临时法术的来源实体」语义。需要: trinket 版 Spellcraft 生成点
    （`generate_for_hero` 同时遍历 hero.trinkets + `source_kind` 区分），
    且该法术是**两段定向**（先选随从、再按 tier+1 过滤第二段候选）——
    现有 `needs_target`/PendingChoice 只有单段目标。被阻塞卡: 416 + 429。
  - BG30_MagicItem_418 Bronzebeard Portrait —
    "…Your Brann Bronzebeards are **both Murlocs and Dragons**."
    Dependency: `GameTag.RACE` 是**单值** tag；`Race.ALL` 语义为「匹配
    一切种族」而非「显示为两个种族」（会把 Beast/Mech/… 一并匹配）。
    需要多值种族身份（`RACES` 集合 tag）或「双种族」表达。
    同一缺口已由 batch_trinkets8 台账备案（418/971），本批沿用。
  - BG30_MagicItem_423 Innkeeper's Stein —
    "The Tavern offers an **extra minion of a higher Tier** whenever it is
    Refreshed."
    Dependency: 引擎唯一的展示数钩子是 `GameTag.TAVERN_OFFER_MOD`（+N
    个通用展示位），而 `refresh_tavern` 的抽取上下界是
    `min_tier = max(game._tavern_min_tier, hero._tavern_min_tier)` /
    `max_tier = hero.tavern_tier`（**上界恒等于酒馆等级**）——无法让
    「某一个额外展示位」从 tier+1 抽取。需要: `hero._tavern_extra_`
    `higher_tier` 计数 + refresh_tavern 在常规抽取之外单独
    `draw_tavern(max_tier=tier+1, min_tier=tier+1, count=1)`。
  - BG30_MagicItem_429 Demonblood Gourd — **已解冻（2026-09-02 主线）**:
    引擎补齐"饰品版 Spellcraft 生成点"（`spellcraft.generate_for_hero`
    遍历 `hero.board + hero.trinkets + hero.quest_rewards`、
    `create_entity` 依 `spellcraft_id` 打 SPELLCRAFT tag）→ 本批连同
    法术 `BG30_MagicItem_429t` 一起注册（单段定向）。
  - BG30_MagicItem_431 Azerite Portrait —
    "Get a Living Azerite. Your Living Azerites **also** give stats to
    friendly Elementals."
    Dependency: (a) 授予物 Living Azerite（BG28_707）本体脚本**未注册**
    （REGISTRY 无此 id，"Whenever you cast a Tavern spell, give Elementals
    in the Tavern +{0}/+{1} this game" 无实现）；(b) "also" 是**改写另一张
    卡的脚本行为**的效果类别，引擎无「按 card_id 家族给某张卡追加效果」
    的协议（`set_script_override` 只作用于**已存在实体**，无法覆盖未来
    获得的副本，也无法跨英雄限定 owner）。需要: (a) 先实现 BG28_707
    本体 + (b) 一个 owner 级「Living Azerite 额外结算面」读取点。
  - BG30_MagicItem_432 Belcher Portrait — **已解冻（2026-09-02 主线）**:
    引擎在 Venomous 消耗时广播 `KEYWORD_LOST(minion=, tag=VENOMOUS)`
    （combat.py）→ 本批实现（战内 Buff + `combat_end` 重放为永久）。
  - BG30_MagicItem_439 Designer Eyepatch —
    "You only need 2 copies of a **Pirate** to make it Golden."
    Dependency: 三连阈值是 **hero 级单值** `hero.get(GameTag.TRIPLE_`
    `THRESHOLD, 3)`（game.py::check_for_triple），且 `check_for_triple`
    的候选集是「同名 card_id」——无「按种族分档阈值」的读取点
    （Clocksworth 是全局 2）。需要: `hero._triple_threshold_by_race`
    + check_for_triple 按 `db.get(acquired.card_id).race` 选取阈值
    （并按 RULES §10.1 记档）。
  - BG30_MagicItem_440 Boom Controller —
    "When you have space, summon an exact copy of your first Mech that
    died each combat."
    Dependency: 该卡 XML 权威标签只有 `START_OF_COMBAT=1`
    （CardDefs.xml 113095; wiki XML tags 同），但 "your first Mech that
    **died each combat**" 指向**战斗内持续触发**——SoC 时点本场尚无人
    死亡（`game.combat_death_log` 在 `run_combat` 开头清空），SoC 单
    检查点必然空转；而 AFTER_ATTACK 循环补召正是主线在 SOP §13 item 3
    明令禁止的形态（Drek'Thar/Ozumat 曾「死一只→补一只」致 2001 轮
    `CombatLoopError`）。需要: 主线先裁定「战斗内每场一次的
    after-death 补位协议」（有界重入 + 与攻击循环的终止性证明），
    届时以 `DEATH` 记录本场首个机械快照 + 有界补召实现。
    **不得**按文本字面自建 AFTER_ATTACK 无限补位。

机制口径（本批实现所依赖的既有原语）
══════════════════════════════════════════════════════════════════════
  - 关联卡数据链: `CardDef.evolution_card_id` → `CardDB.by_dbf`（零硬编码
    卡 id）；「家族」= 本体 + `db.golden_version(本体)`（金色=独立卡定义）。
  - 池感知获取: `_pool_candidates`（剩余量 > 0 / 本局禁用种族 / race /
    tier）+ `minion_pool.acquire` + `pending_hand_add`（RULES §2.3/§2.4/
    §3.3）。**Summon 语义不占池**（战斗/效果召唤的临时体，战后随
    `board_before` 复原消失——batch_hero_passives Y'Shaarj 同款裁定）。
  - 「Summon and get a random X」= 1 份池记账（"get" 的手牌副本）+ 1 个
    不占池的召唤体，同 card_id（Y'Shaarj TB_BaconShop_HP_103 先例）。
  - SoC 期间的战斗对经 `game._active_combat` 定位（SOP §9 协议）。
  - 战斗内授予亡语 = `_script_overrides` 链式包装 + `DEATHRATTLE` tag，
    战后由持久 `COMBAT_END` 监听恢复（`_script_overrides` **不在**
    `Minion.snapshot_state` 快照范围内——batch_hero_combat3
    `_grant_combat_deathrattle` 同款协议）。
  - 酒馆持久 Buff = `TavernBuff` + `ApplyTavernBuff`（未来入馆随从）+
    `BuffCurrentTavern`（当前馆内随从）——见 actions/tavern_buff.py。
  - 血宝石 = `GEMS_PLAYED_ON` 记账 + `_gem_values`（单颗当前价值 =
    `BG20_GEM.num(0/1)` + `BLOOD_GEM_BONUS_*`）+ `ImproveBloodGems`
    （hero 级本局加成 tag）。
  - 战斗外英雄受伤 = `HERO_DAMAGE_TAKEN(hero=, amount=)` 且
    `not game.in_combat`（战斗败方伤害发生在 `in_combat=True` 窗口内，
    自动被排除）。

全部状态写在 **source（饰品实体）属性 / 脚本闭包 / hero 契约 tag**，
无 game 级 flag（SOP §12 item 9）。饰品脚本只挂
`on_bind` / `start_of_turn` / `start_of_combat` / `avenge`
（接线审计 W1 白名单）。跨批复用的公共符号: `hsrl2.actions.discover.
_pool_candidates`（池过滤唯一口径）、`hsrl2.actions.bloodgem.
_gem_values`、`batch_spells4.DiscoverTavernSpellOfTier`（酒馆法术发现，
batch_anomalies3 先例）。
"""

from __future__ import annotations

from typing import List

from hsrl2.actions import Buff, GainKeyword, Summon
from hsrl2.actions.consume import ConsumeRandomTavernMinion
from hsrl2.actions.bloodgem import GetBloodGems, ImproveBloodGems, \
    _gem_values
from hsrl2.actions.discover import _pool_candidates
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, \
    TavernBuff
from hsrl2.events import (
    AFTER_ATTACK,
    COMBAT_END,
    DEATH,
    HERO_DAMAGE_TAKEN,
    KEYWORD_LOST,
    MINION_OVERFLOW,
    SUMMON,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

# Quilboar 匹配族（Amalgam 全种族，RULES §6.4 通用裁定）
_QUILBOAR_RACES = (Race.QUILBOAR, Race.ALL)

# Blood Golem token（wiki Related cards + bg_cards.json 双核实;
# `BG30_MagicItem_442t` 非池卡，与 batch_unfreeze/batch_misc 同一 token 裁定）
_BLOOD_GOLEM_TOKEN = "BG30_MagicItem_442t"

# 血宝石基础卡 id（单颗当前价值由 _gem_values 权威计算，非本批硬编码数值）
_BLOOD_GEM_ID = "BG20_GEM"

# "+5 Attack"（BG30_MagicItem_438t 文本字面量——CardDef num(0)/num(1) 均为
# None，无模板参数）
_MUG_OF_THE_SIRE_ATK = 5

# "Get 2 Blood Gems"（BG30_MagicItem_411 文本字面量——CardDef 无模板参数）
_HOGGY_BANK_GEMS = 2

# "+1 Health"（BG30_MagicItem_410 文本字面量——num(1) 为 None，
# num(0)=3 是 Avenge 阈值/计数器显示）
_QUILLIGRAPHY_EXTRA_HEALTH = 1

# "Improves" 的增量（BG30_MagicItem_541；官方 Improve 关键词无数字时
# 每次 +1/+1——卡片 XML 无该增量参数: NUM_1=3 为计数、NUM_2=2 为基数）
_NETHER_PENDANT_STEP = 1


def _hero(ctx):
    return (ctx or {}).get("hero")


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _related_card_id(game, source) -> str:
    """`game.trinket_related_card`（RULES §7.4.6 关联卡协议）解析出的 card_id。

    数据链 = `CardDef.evolution_card_id` → `CardDB.by_dbf`（零硬编码卡 id）。
    解析失败 → GameStateError（fail-loud，禁止近似——SOP §6b）。
    """
    card = game.trinket_related_card(source.card_id)
    if card is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    return card.id


def _family_ids(game, source) -> frozenset:
    """关联卡指向的随从**家族**（本体 + 金色独立卡定义）。

    金色版本是 CardDefs 中的独立实体——"your Eternal Knights" /
    "your Titus Rivendares" 必须同时覆盖本体与金色本体
    （batch_counters `_ETERNAL_KNIGHT_IDS` 同族裁定，此处改为数据链解析、
    零硬编码 id）。
    """
    base_id = _related_card_id(game, source)
    base_def = game.db.get(base_id)
    ids = {base_id}
    golden = game.db.golden_version(base_def) if base_def is not None else None
    if golden is not None:
        ids.add(golden.id)
    return frozenset(ids)


def _restore_granted_deathrattles(owner, game=None) -> None:
    """[兼容保留] 恢复战斗内授予的亡语 override。

    2026-09-02 起引擎在 `run_combat` 结束时**统一恢复**（见
    `Game._restore_combat_deathrattles`）——本函数仅为尚未迁移的跨批调用
    保留（如 batch_trinkets18 的早期实现），内部委托引擎; 新脚本请直接
    用 `game.grant_combat_deathrattle(...)`，不要再注册 COMBAT_END 清理。
    """
    g = game if game is not None else getattr(owner, "game", None)
    if g is not None:
        g._restore_combat_deathrattles(owner)


def _grant_in_combat_deathrattle(owner, game, m: Minion, extra_fn) -> None:
    """战斗内授予亡语——委托引擎 `game.grant_combat_deathrattle`
    （2026-09-02 主线收口: 链式顺序/返回值合并/战后 override 恢复统一由
    引擎负责，脚本不再自带 COMBAT_END 恢复监听）。"""
    game.grant_combat_deathrattle(owner, m, extra_fn)


def _immediate_attack(game, hero, attacker: Minion) -> None:
    """让 attacker 立即对交战对手发起一次完整攻击（"It attacks immediately"）。

    目标选择依照 RULES §4.4 的公开规则（嘲讽强制优先，其余随机；潜行
    不可被攻击）——与引擎 `CombatScheduler._choose_target` 同一口径，此处
    以 `game.rng` 复现以避免脚本调用引擎私有方法。完整单次攻击语义经
    `combat.execute_immediate_attack`（SOP §10 原语: 双向同时伤害/圣盾/
    剧毒/死亡结算/AFTER_ATTACK 与轮转攻击同一路径）。

    0 攻随从不能发起攻击（C9；batch_unfreeze Jailbird 同守卫）;
    战斗对未知/对手无存活随从 → 落空。
    """
    if attacker.dead or attacker.zone != Zone.PLAY or attacker.atk <= 0:
        return
    pair = getattr(game, "_active_combat", None)
    if not pair:
        return
    a, b = pair
    opponent = b if a is hero else a if b is hero else None
    if opponent is None:
        return
    living = [m for m in opponent.living_minions()
              if not m.has(GameTag.STEALTH)]
    if not living:
        return
    taunts = [m for m in living if m.taunt]
    defender = game.rng.choice(taunts or living,
                               label="ship_in_a_bottle_target")
    from hsrl2.combat import execute_immediate_attack
    execute_immediate_attack(game, attacker, defender)


# ══════════════ BG30_MagicItem_301 Eternal Portrait ══════════════

class EternalPortraitScript:
    """
    Natural language: [x]Get an Eternal Knight.
    <b>Start of Combat:</b> Give your
    Eternal Knights <b>Taunt</b>
    and <b>Reborn</b>.

    Formal spec:
      1. on_bind: Get an Eternal Knight——`evolution_card_id` 数据链解析
         （dbf 95261 → BG25_008，`is_pool_minion=True`）→ 池内有余则
         `minion_pool.acquire` 占池 1 份（RULES §2.3），池耗尽 → 落空
         （RULES §2.4）; `pending_hand_add` 入手（满手排队 RULES §3.3）
      2. start_of_combat（饰品 SoC 钩子，先于攻击循环）: 家族 =
         {BG25_008, BG25_008_G}（金色=独立卡定义，同为 "your Eternal
         Knights"）中本人棋盘存活者 → 各获 `Taunt` 与 `Reborn`
         （`GainKeyword`; 已持有者跳过，避免重复 keyword_gained）
      3. 无 Eternal Knight → 本次 SoC 落空（不产生任何 Action）
      4. 只作用于本人棋盘（对手的 Eternal Knight 不被授予）

    Test: test_batch_trinkets11.py — 绑定入手 1 只 BG25_008 且该卡池 -1 /
      SoC 后本人棋盘 Eternal Knight（含金色 BG25_008_G）同时带
      TAUNT+REBORN、非 Knight 不带关键词 / 无 Knight 时探针读到 0 个带
      关键词者（正对照: 同 setup 有 Knight 时 >0）/ 对手 Knight 不被授予

    Params: 无模板参数（CardDef num(0)/num(1) 均为 None——文本无 {0}/{1}）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        ids = _family_ids(game, source)
        actions = []
        for m in _living(h):
            if m.card_id not in ids:
                continue
            if not m.has(GameTag.TAUNT):
                actions.append(GainKeyword(m, GameTag.TAUNT))
            if not m.has(GameTag.REBORN):
                actions.append(GainKeyword(m, GameTag.REBORN))
        return actions or None


# ══════════════ BG30_MagicItem_303 Automaton Portrait ══════════════

class AutomatonPortraitScript:
    """
    Natural language: <b>Start of Combat:</b> When you have space, summon
    an Ancestral Automaton.

    Formal spec:
      1. start_of_combat（饰品 SoC 钩子）: 本人棋盘**有空位**
         （`not hero.board_full()`）时召唤 1 个 Ancestral Automaton——
         `evolution_card_id` 数据链解析（dbf 108432 → BG_TTN_401）
      2. "When you have space" 是**条件**而非第二个触发时机: 本卡 XML
         权威标签只有 `START_OF_COMBAT=1`（CardDefs.xml 111403），与
         Drek'Thar「When you have space in combat」族的 SoC 单检查点
         裁定一致（SOP §13 item 3）；无空位 → 落空（**不**触发
         `minion_overflow`，因为"有空位才召唤"本身不构成一次失败的召唤）
      3. Summon 不占池（召唤语义——战后随 `board_before` 复原消失）
      4. 每场战斗一次（SoC 钩子天然每场一次; soc_extra 配额会按
         RULES §6.20 追加次数，届时逐次结算）

    Test: test_batch_trinkets11.py — SoC 后本人棋盘恰好 +1 只 BG_TTN_401、
      对手棋盘不变、随从池不变量不变（Summon 语义）/ 满场时 0 只且无
      minion_overflow（正对照: 非满场时 +1 只）

    Params: 无模板参数（CardDef num(0)/num(1) 均为 None）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None or h.board_full():
            return None
        card_id = _related_card_id(game, source)
        return Summon(h, card_id)


# ══════════════ BG30_MagicItem_310 Rivendare Portrait ══════════════

class RivendarePortraitScript:
    """
    Natural language: [x]Get a Titus Rivendare.
    <b>Start of Combat:</b> Double
    the Health of your
    Titus Rivendares.

    Formal spec:
      1. on_bind: Get a Titus Rivendare——`evolution_card_id`（dbf 97408
         → BG25_354，池随从 T5）→ 池感知获取 + 满手排队（同 301）
      2. start_of_combat: 家族 {BG25_354, BG25_354_G} 中本人棋盘存活者
         各 `Buff(health=该随从 max_health)`——"Double the Health" =
         **属性值**翻倍（当前生命不含损益；SOP §3 用 max_health 作
         属性快照），增量 = max_health ⇒ 之后 max_health 恰好 ×2
      3. 无 Titus → 落空; 战斗快照战后回滚（RULES §3.5）——本效果为
         战斗内增益
      4. 只作用于本人棋盘

    Test: test_batch_trinkets11.py — 绑定入手 1 只 BG25_354 且池 -1 /
      SoC 后本人 Titus 的 max_health 恰好 ×2、攻击力不变 / 非 Titus 不
      变（正对照）/ 对手 Titus 不变 / 每次 SoC 叠加一倍（真实 run_combat
      两场后 = 4×——"each combat" 语义）

    Params: 无模板参数（CardDef num(0)/num(1) 均为 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        ids = _family_ids(game, source)
        actions = [Buff(m, health=m.max_health)
                   for m in _living(h) if m.card_id in ids]
        return actions or None


# ══════════════ BG30_MagicItem_407 Ship in a Bottle ══════════════

class ShipInABottleScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Summon
    and get a random Pirate.
    It attacks immediately.

    Formal spec:
      1. start_of_combat: 候选 = `_pool_candidates(race=PIRATE)`
         （池剩余量 > 0、含 Amalgam ALL、排除本局禁用种族——RULES
         §2.4/§6.18）; 空 → 落空
      2. `game.rng.choice` 选中 cid 后 `minion_pool.acquire(cid)` **1 份**
         ——"get" 的手牌副本占池（RULES §2.3; 多语言文本佐证单一对象:
         jaJP「ランダムな海賊を1体召喚＆入手する」/ esES「Invocas y
         obtienes un pirata aleatorio」——Y'Shaarj TB_BaconShop_HP_103
         "Summon and get a minion of your Tier" 同一语义模型）
      3. "Summon": 棋盘未满时 `create_minion` + `Summon`（战斗召唤体不
         占池、战后随 board_before 复原消失）; 满板时仅入手（Y'Shaarj
         先例）
      4. "It attacks immediately": 召唤体立即对交战对手发起一次完整攻击
         （`_immediate_attack`——目标选择依 RULES §4.4 嘲讽优先/其余随机、
         潜行不可被攻击; 完整走 `combat.execute_immediate_attack`）。
         0 攻/无对手存活随从 → 不攻击（召唤体留在场上）
      5. "get": `create_minion` 副本 `pending_hand_add`（满手排队
         RULES §3.3）
      6. 只作用于本人（对手的 SoC 不触发本人饰品）; 池空 → 整体落空

    Test: test_batch_trinkets11.py — SoC 后本人棋盘 +1 只海盗且手牌出现
      同 card_id 副本、海盗池恰好 -1 / 召唤体已对敌方完成一次攻击
      （敌方格挡者掉血 = 召唤体攻击力）/ 满板时仅手牌 +1（无棋盘体）/
      对手棋盘与手牌不变 / 池内海盗耗尽时整体落空（无召唤无入手）

    Params: count=1（"a random Pirate" 文本字面量——CardDef 无 {0}/{1}）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        cands = _pool_candidates(game, race=Race.PIRATE)
        if not cands:
            return None
        pick = game.rng.choice(cands, label="ship_in_a_bottle")
        if not game.minion_pool.acquire(pick):
            return None
        if not h.board_full():
            summoned = game.create_minion(pick, controller=h)
            if game.summon(h, summoned):
                _immediate_attack(game, h, summoned)
        game.pending_hand_add(
            h, game.create_minion(pick, controller=h))
        return None


# ══════════════ BG30_MagicItem_410 Quilligraphy Set ══════════════

class QuilligraphySetScript:
    """
    Natural language: [x]<b>Avenge ({0}):</b> Your <b>Blood
    Gems</b> give an extra
    +1 Health this game.

    Formal spec:
      1. Avenge 阈值 = num(0) = 3 = 类属性 `avenge_threshold`（饰品实体
         无 AVENGE tag，引擎对 `hero.trinkets` 统一计数、**仅战斗内**、
         每场清零——RULES §6.11）; 类属性无法在 import 期读 CardDef，测试
         钉死 `QuilligraphySetScript.avenge_threshold == num(0)`
      2. avenge: `ImproveBloodGems(hero, health=1)`——hero 级
         `BLOOD_GEM_BONUS_HEALTH` 本局累加（"this game"），对手牌打出与
         `PlayBloodGems` 施放的宝石同时生效（`_gem_values` 唯一读取点）
      3. 攻击力不加（"an extra +1 Health" 仅生命）; 多次达阈值逐次累加
      4. 只作用于本人（对手死亡不计数、对手的宝石不加成）

    Test: test_batch_trinkets11.py — 战斗内 num(0)-1 次友方死亡后
      BLOOD_GEM_BONUS_HEALTH 仍为 0 / 第 num(0) 次恰好 +1 且攻击加成不变 /
      真实打出一颗血宝石后目标生命增量比对照多 1（正对照: 无饰品不加）/
      招募期死亡不计数（阶段守卫）/ 对手死亡不计入本人阈值

    Params: {0}=3（BG30_MagicItem_410 num(0)，即 Avenge 阈值/计数显示）;
              extra_health=1（文本字面量 "+1 Health"）
    """

    avenge_threshold = 3   # == CardDef.num(0)（测试钉死）

    @staticmethod
    def avenge(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return ImproveBloodGems(h, health=_QUILLIGRAPHY_EXTRA_HEALTH)


# ══════════════ BG30_MagicItem_411 Hoggy Bank ══════════════

class HoggyBankScript:
    """
    Natural language: [x]<b>Start of Combat:</b>
    Give your Quilboar
"<b>Deathrattle:</b> Get 2
<b>Blood Gems</b>."

    Formal spec:
      1. on_bind: 无需清理钩子——战斗内授予的亡语 override 由**引擎**
         在 `run_combat` 结束时统一恢复（`game.grant_combat_deathrattle`;
         `_script_overrides` 不在战斗快照范围内，2026-09-02 主线收口）
      2. start_of_combat: 本人棋盘存活 Quilboar（race ∈ (QUILBOAR, ALL)，
         含 Amalgam）逐个获得「亡语: 获得 2 颗血宝石」——
         `GetBloodGems(controller, 2)`（vanilla 血宝石; 非池 token 不占
         法术池）; 与随从原生亡语**链式叠加**（原生先结算、追加后置）
      3. 无 Quilboar → 落空（不授予任何 override）
      4. 只作用于本人棋盘; 复生者回归后再死亡语照常再触发
      5. 效果仅本场（授予的 override 由引擎在 run_combat 结束时恢复;
         DEATHRATTLE tag 由引擎快照恢复）

    Test: test_batch_trinkets11.py — SoC 后本人 Quilboar 带 DEATHRATTLE
      标记与 override、非 Quilboar 不带 / 战斗内该 Quilboar 死亡后手牌
      恰好 +2 颗血宝石（card_id ∈ 变体集）/ 真实 run_combat 结束后
      override 已恢复（再死亡不再给宝石——一次性语义）+ DEATHRATTLE tag
      回滚 / 无 Quilboar 时无授予（正对照: 有则授予）/ 对手 Quilboar 不
      被授予

    Params: count=2（"Get 2 Blood Gems" 文本字面量——CardDef 无 {0}/{1}）
    """

    # on_bind 无需清理钩子（引擎统一恢复 override）

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None

        def extra(src, g, _ctx):
            if src.controller is None:
                return None
            return GetBloodGems(src.controller, _HOGGY_BANK_GEMS)

        for m in _living(h):
            if m.race in _QUILBOAR_RACES:
                _grant_in_combat_deathrattle(h, game, m, extra)
        return None


# ══════════════ BG30_MagicItem_420 Book of Medivh ══════════════

class BookOfMedivhScript:
    """
    Natural language: <b>Discover</b> a Tavern spell. At the start of each
    turn, <b>Discover</b> another.

    Formal spec:
      1. on_bind: `DiscoverTavernSpellOfTier(hero, hero.tavern_tier,
         min_tier=1)`——候选 = `game.tavern_spell_candidates` 中
         `1 ≤ tech_level ≤ hero.tavern_tier` 且 `spell_pool` 有剩余
         （RULES §3.6.1 每张 1 副本）**并经存在档白名单**（异变
         101/102 非存在档不可达——2026-09-02 对抗审查 must-fix:
         旧实现 101 的 T3 曾给出含 T2 的选项）; 3 选项预留语义 +
         resolve 保留选中/
         释放其余（batch_spells4 实现）; 文本无 "Tier N" → 口径为
         「≤ 酒馆等级」（RULES §3.6.1 note，与 `SpellPool.draw_tavern`
         / Mystic Essence 全仓统一）
      2. start_of_turn（饰品 SoT 钩子）: 同款再 Discover 一次——
         "At the start of each turn, Discover another"
      3. 法术池耗尽 / 无候选 → 该次落空（不产生 PendingChoice）
      4. 只作用于本人（PendingChoice owner = 本人英雄）

    Test: test_batch_trinkets11.py — 绑定后恰产生 1 个本人的
      kind=discover_tavern_spell 选择且 3 选项均为池法术、选项已占池 /
      resolve 后手中出现所选法术、未选项回池（法术池净 -1）/ 真实
      end_recruit_phase 推进回合后 SoT 再产生 1 个选择 / 对手无选择
      （正对照: 本人有）/ 池内法术耗尽时不产生选择

    Params: 无模板参数（CardDef num(0)/num(1) 均为 None）
    """

    @staticmethod
    def _discover(h, game):
        from hsrl2.scripts.batches.batch_spells4 import \
            DiscoverTavernSpellOfTier
        return DiscoverTavernSpellOfTier(h, h.tavern_tier, min_tier=1)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        return BookOfMedivhScript._discover(h, game)

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        return BookOfMedivhScript._discover(h, game)


# ══════════════ BG30_MagicItem_438t Mug of the Sire ══════════════

class MugOfTheSireScript:
    """
    Natural language: [x]Whenever you would
    summon a minion that
    doesn't fit in your warband,
    give your minions +5 Attack.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `minion_overflow`
         （minion=）——引擎在 `play_minion` / `game.summon` 因
         `hero.board_full()` 放弃召唤时广播（"would summon a minion that
         doesn't fit in your warband" = 因满员失败的召唤；tag: 无
         START_OF_COMBAT/AURA——这是唯一在语义上精确对应的引擎信号）
      2. 条件: `minion.controller is 本人`（对手满员召唤不给本人加成）
      3. 触发: 本人棋盘全部存活随从各 `Buff(atk=5)`（"+5 Attack" 文本
         字面量; CardDef num(0)/num(1) 均为 None）；招募期为永久增益，
         战斗内增益战后随快照回滚（RULES §3.5）
      4. 空板 → 落空（无目标仍消耗事件，不产生 Action）
      5. 每次失败的召唤各触发一次，逐次叠加

    Test: test_batch_trinkets11.py — 满板时 `play_minion` 失败后本人棋盘
      全部随从攻 +5、手牌随从仍在手（正对照: 非满板成功打出则 +0）/
      对手满员召唤不授予本人加成（owner 隔离）/ 已死亡随从不在目标内 /
      CardDef num(0)/num(1) 均为 None（钉死"文本字面量"前提）

    Params: atk=5（"+5 Attack" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_overflow(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            targets = _living(h)
            if not targets:
                return
            g.run_actions([Buff(m, atk=_MUG_OF_THE_SIRE_ATK)
                           for m in targets])

        game.events.register(Listener(event=MINION_OVERFLOW, owner=source,
                                      callback=on_overflow))
        return None


# ══════════════ BG30_MagicItem_441 Tinyfin Onesie ══════════════

class TinyfinOnesieScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Your
    left-most minion gains the
    stats of the highest-Health
    minion in your hand.

    Formal spec:
      1. start_of_combat: 目标 = 本人棋盘**最左**存活随从
         （`hero.board` 顺序 = 站位，取首个非死亡者）
      2. 属性来源 = 本人**手牌**中**当前生命最高**的随从
         （"Health" = 当前值，SOP §16 item 23；平手取更靠前者，
         稳定 tie-break）; 手牌无随从 / 棋盘空 → 落空
      3. 触发: `Buff(target, atk=src.atk, health=src.max_health)`——
         "gains the stats of" = 攻/属性值全额追加（复制属性用 max_health，
         SOP §3）
      4. 只作用于本人棋盘与本人手牌（对手的手牌/棋盘不参与）
      5. 战斗快照战后回滚（RULES §3.5）

    Test: test_batch_trinkets11.py — SoC 后最左随从的攻/生命各增加手牌
      最高生命随从的 atk/max_health；次高生命的手牌随从与棋盘其他随从
      不变（正对照）/ 最左随从自动更新为增益后的最左（再一场 SoC 叠加）/
      对手棋盘最左不变 / 空手牌时落空（无变化）

    Params: 无模板参数（CardDef num(0)/num(1) 均为 None）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = _living(h)
        if not living:
            return None
        hand = [m for m in h.hand if isinstance(m, Minion)]
        if not hand:
            return None
        src = hand[0]
        for m in hand[1:]:
            if m.health > src.health:
                src = m
        return Buff(living[0], atk=src.atk, health=src.max_health)


# ══════════════ BG30_MagicItem_442 Blood Golem Sticker ══════════════

class BloodGolemStickerScript:
    """
    Natural language: [x]Whenever a friendly Quilboar
    dies, summon a Golem with
    stats equal to its <b>Blood Gems</b>.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `death`（minion=）——
         引擎在死者**离场前**广播（game.py `_process_death_inner` 步骤 1）
      2. 条件: `minion.controller is 本人` 且 race ∈ (QUILBOAR, ALL)
         （Amalgam）; 文本无阶段/次数限定（wiki 35.4.2 起移除 "(N times
         per combat.)"）→ 招募期与战斗内死亡都触发，不设 `in_combat` 闸门
      3. 快照属性 = `GEMS_PLAYED_ON × 单颗宝石当前价值`
         （`_gem_values(BG20_GEM)` = num + `BLOOD_GEM_BONUS_*`）——
         与 batch_unfreeze Jailbird / batch_misc DEFERRED 台账同一裁定
         （"stats equal to its Blood Gems"）
      4. 召唤 `BG30_MagicItem_442t` Blood Golem（非池 token 不占池），
         覆盖 `BASE_ATK/BASE_HEALTH/HEALTH`
      5. **落位时机**: DEATH 在离场之前广播，此刻死者仍占板位
         （`board_full()` 含死者）——故召唤在 DEATH 内直接尝试，失败
         （满员）则挂入 `pending`，在随后的 `after_attack` / `summon`
         事件（板位已释放）再补召; 成功即出队
      6. 0 颗宝石 → 0/0 Golem（Jailbird 同裁定: 召唤即死，死亡波次由外层
         `check_deaths` 收集）
      7. 只作用于本人（对手 Quilboar 死亡不召唤）

    Test: test_batch_trinkets11.py — 手打 2 颗血宝石的 Quilboar 死后
      棋盘出现 1 个 BG30_MagicItem_442t 且其攻/血 == 2×单颗宝石值 /
      0 颗宝石 → 0/0（死亡）/ 非 Quilboar 死亡不召唤 / 对手 Quilboar
      死亡不给本人召唤（owner 隔离）/ 满板（7/7 含 1 名死亡 Quilboar）
      时在真实 `run_combat` 内于 after_attack 补召成功

    Params: token=BG30_MagicItem_442t（wiki Related cards + 数据核实）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        pending: List[dict] = []

        def flush(g) -> None:
            while pending and not h.board_full():
                snap = pending.pop(0)
                golem = g.create_minion(_BLOOD_GOLEM_TOKEN, controller=h)
                golem.set(GameTag.BASE_ATK, snap["atk"])
                golem.set(GameTag.BASE_HEALTH, snap["health"])
                golem.set(GameTag.HEALTH, snap["health"])
                g.summon(h, golem)

        def on_death(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if minion.race not in _QUILBOAR_RACES:
                return
            gems = minion.get(GameTag.GEMS_PLAYED_ON, 0)
            if gems > 0:
                gem_atk, gem_health = _gem_values(g, _BLOOD_GEM_ID, h)
                atk, health = gems * gem_atk, gems * gem_health
            else:
                atk = health = 0
            pending.append({"atk": atk, "health": health})
            flush(g)

        def on_retry(g, **kw):
            if pending:
                flush(g)

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        game.events.register(Listener(event=AFTER_ATTACK, owner=source,
                                      callback=on_retry))
        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_retry))
        return None


# ══════════════ BG30_MagicItem_541 Nether Pendant ══════════════

class NetherPendantScript:
    """
    Natural language: [x]Minions in the Tavern have
    +{1}/+{1}. Improves every 3
    times your hero takes damage
    __outside combat. <i>({0} left!)</i>

    Formal spec:
      1. on_bind: 立即面 `BuffCurrentTavern` + 持久面 `ApplyTavernBuff`
         （`TavernBuff(atk=num(1), health=num(1), source_id=本饰品)`）——
         当前馆内随从立刻 +num(1)/+num(1)，未来入馆随从由
         `refresh_tavern` 自动套用（actions/tavern_buff.py 协议）
      2. on_bind 注册持久监听器（owner=饰品）: `hero_damage_taken`
         （hero=, amount=）; 条件 `hero is 本人` 且 `not game.in_combat`
         ——"outside combat"（战斗内受伤含战败伤害，均发生在
         `in_combat=True` 窗口）; 护甲吸收也算受伤（引擎语义）
      3. 计数达 num(0)=3 → 清零并 **Improve**: 酒馆 Buff 基数 +1/+1
         （"Improves" 无数字参数 → 每次 +1/+1; CardDef 只有
         NUM_1=3 计数 / NUM_2=2 基数两个模板参数）; 已登记描述子被
         **替换**（避免 refresh 重复叠加）并对当前馆内随从补 +1/+1
         （aura 提升对已在馆者同样生效）
      4. 计数跨回合累积（文本无 "this turn"）; 只作用于本人酒馆
         （TavernBuff 写 hero 作用域——不污染对手酒馆，SOP §12 item 9）
      5. 未满 num(0) 次 → 不 Improve; 0 伤害 → 不计数

    Test: test_batch_trinkets11.py — 绑定后当前馆内随从 +num(1)/
      +num(1)、真实 refresh_tavern 新入馆随从同样带 num(1)/num(1) /
      战斗外受伤 num(0)-1 次不 Improve、第 num(0) 次恰好 +1/+1（馆内
      随从增量累加表现为 num(1)+1 与再入馆者同值）/ 战斗内受伤不计数
      （阶段守卫：真实 run_combat 战败伤害不触发）/ 对手受伤不计数且
      对手酒馆不被 buff

    Params: {0}=3 {1}=2（BG30_MagicItem_541 num(0)/num(1)）;
              improve_step=1（"Improves" 无参数 → 每次 +1/+1）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        base = _num(game, source.card_id, 1)
        left = _num(game, source.card_id, 0)
        state = {"level": base, "n": 0}
        tb = TavernBuff(atk=base, health=base, source_id=source.card_id)
        source._nether_pendant_tb = tb
        game.run_actions([ApplyTavernBuff(h, tb), BuffCurrentTavern(h, tb)])

        def _register(level: int):
            return TavernBuff(atk=level, health=level,
                              source_id=source.card_id)

        def on_damage(g, hero=None, amount=0, _h=h, **kw):
            if hero is not _h or g.in_combat:
                return
            state["n"] += 1
            if state["n"] < left:
                return
            state["n"] = 0
            state["level"] += _NETHER_PENDANT_STEP
            old = source._nether_pendant_tb
            new_tb = _register(state["level"])
            source._nether_pendant_tb = new_tb
            buffs = list(getattr(_h, "tavern_buffs", []))
            buffs = [b for b in buffs if b is not old]
            buffs.append(new_tb)
            _h.tavern_buffs = buffs
            delta = TavernBuff(atk=_NETHER_PENDANT_STEP,
                               health=_NETHER_PENDANT_STEP,
                               source_id=source.card_id)
            g.run_actions(BuffCurrentTavern(_h, delta))

        game.events.register(Listener(event=HERO_DAMAGE_TAKEN, owner=source,
                                      callback=on_damage))
        return None



# ══════════════ BG30_MagicItem_432 Belcher Portrait ══════════════


class BelcherPortraitScript:
    """
    Natural language: [x]Get an Operatic Belcher.
    Whenever a friendly minion loses <b>Venomous</b>, it gains +4/+4
    permanently.

    Evidence: `data/bg_trinkets.json BG30_MagicItem_432`（lesser;
    `evolution_card_id` → Operatic Belcher）。"+4/+4" 为文本字面量
    （CardDef 无 {0}/{1} 占位符）。引擎依赖（2026-09-02 主线补齐）:
    Venomous 消耗时广播 `KEYWORD_LOST(tag=VENOMOUS)`（combat.py）。

    Formal spec:
      1. on_bind: 数据链授予 Operatic Belcher（`grant_trinket_related_card`）
      2. 注册 KEYWORD_LOST 监听（owner=本饰品）: 条件 = tag==VENOMOUS 且
         失去者属于本人 → 立即 `Buff(minion, +4/+4)`（本场战斗内生效）
      3. "permanently": 战内增益会被战后棋盘复原回滚 → 记录本场名单，
         `combat_end`（复原**之后**广播）把 +4/+4 作为永久 Buff 重放
         （与 Devout Hellcaller 的 PERSIST 通道同目的; 此处因受益者
         战中才确定，无法战前打 PERSIST tag，改用 combat_end 重放——
         且战内 buff 不在"伤害窗口增量"内，不会被引擎重复重放）
      4. 只作用于本人（对手随从失去 Venomous 不触发）

    Test: test_batch_trinkets11.py — 真实 run_combat: 带 Venomous 的友方
      随从毒杀敌人后该随从 +4/+4 且**战后仍在**（招募期属性保留）/ 敌方
      失去 Venomous 不触发（owner 隔离）/ 无饰品对照不变

    Params: 无模板参数（+4/+4 为文本字面量）
    """

    _GAIN = 4

    @staticmethod
    def on_bind(source, game, ctx):
        hero = _hero(ctx)
        if hero is None:
            return None
        game.grant_trinket_related_card(hero, source.card_id)
        pending: list = []

        def cond(minion=None, tag=None, **kw):
            return (tag == GameTag.VENOMOUS and minion is not None
                    and minion.controller is hero)

        def on_lost(g, minion=None, **kw):
            pending.append(minion)
            g.run_actions(Buff(minion, atk=BelcherPortraitScript._GAIN,
                               health=BelcherPortraitScript._GAIN))

        def on_end(g, hero_a=None, hero_b=None, **kw):
            if hero is not hero_a and hero is not hero_b:
                return
            for m in pending:
                if not m.dead and m in hero.board:
                    g.run_actions(Buff(
                        m, atk=BelcherPortraitScript._GAIN,
                        health=BelcherPortraitScript._GAIN))
            pending.clear()

        game.events.register(Listener(event=KEYWORD_LOST, owner=source,
                                      callback=on_lost, condition=cond))
        game.events.register(Listener(
            event=COMBAT_END, owner=source, callback=on_end,
            condition=lambda hero_a=None, hero_b=None, **kw:
                hero is hero_a or hero is hero_b))
        return None


# ══════════════ BG30_MagicItem_429 Demonblood Gourd ══════════════


class DemonbloodGourdScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Choose a friendly minion.
    It consumes a random minion in the Tavern to gain its stats.

    Evidence: `data/bg_trinkets.json BG30_MagicItem_429`（greater,
    cost 3; `spellcraft_id=112401` → `BG30_MagicItem_429t`）。饰品版
    Spellcraft = 每回合生成该法术（`spellcraft.generate_for_hero` 扫描域
    2026-09-02 扩展到 `hero.trinkets`；`create_entity` 依 `spellcraft_id`
    打 SPELLCRAFT tag），法术自身脚本见 `DemonbloodGourdSpellScript`。

    Formal spec:
      1. on_bind: 数据链授予关联卡（文本无 "Get a X" 子句 → 无授予；
         本饰品只提供 Spellcraft）
      2. 每回合开始由引擎生成 1 张 `BG30_MagicItem_429t` 入手（临时法术，
         未使用则回合结束丢弃——RULES §6.13）
      3. 实效由法术脚本完成（定向吞噬酒馆随机随从并继承其属性）

    Test: test_batch_trinkets11.py + test_engine_gaps（引擎侧生成/丢弃）
      —— 生成一张带 SPELLCRAFT 的法术入手、真实 `play_spell` 定向友方
      随从后该随从吞噬酒馆随机随从并获得其属性（池/酒馆计数配平）/
      无饰品对照不生成

    Params: 无模板参数（效果量由法术脚本与吞噬目标决定）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class DemonbloodGourdSpellScript:
    """
    Natural language: Choose a friendly minion. It consumes a random
    minion in the Tavern to gain its stats.

    Evidence: `data/bg_cards.json BG30_MagicItem_429t`（card_type=5,
    cost 3）。引擎原语: `actions.consume.ConsumeRandomTavernMinion`
    （RULES §6.x 吞噬——不触发亡语、池记账由引擎负责）。

    Formal spec:
      1. needs_target=True（"Choose a friendly minion"——引擎经
         `spell_target` 生成 PendingChoice，候选 = 本人存活随从）
      2. on_play: 目标 = ctx["target"]; 无目标 → 落空（法术照常消耗）
      3. 返回 `ConsumeRandomTavernMinion(target)`——target 吞噬本人酒馆中
         的**随机**随从（`game.rng`）并获得其属性; 酒馆无可吞噬随从 →
         落空（Consume 内部直接 return）

    Test: test_batch_trinkets11.py::TestDemonbloodGourd — 真实
      `play_spell` 定向: 酒馆随从被移除、目标属性增加等于其快照、
      亡语不触发、对手不受影响 / 酒馆空 → 落空

    Params: 无模板参数
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or target is None:
            return None
        return ConsumeRandomTavernMinion(target)


# ══════════════════════════════ 注册 ══════════════════════════════

def register() -> list[str]:
    """注册饰品第 11 批 13 张 + Spellcraft 法术 1 张。

    （2026-09-02 主线解冻: 432 Belcher Portrait 依赖的 Venomous 失去事件、
    429 Demonblood Gourd 依赖的"饰品版 Spellcraft 生成点"均已在引擎落地;
    其余 7 张 DEFERRED 台账见模块 docstring。）
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG30_MagicItem_432", BelcherPortraitScript),
        ("BG30_MagicItem_429", DemonbloodGourdScript),
        ("BG30_MagicItem_429t", DemonbloodGourdSpellScript),
        ("BG30_MagicItem_301", EternalPortraitScript),
        ("BG30_MagicItem_303", AutomatonPortraitScript),
        ("BG30_MagicItem_310", RivendarePortraitScript),
        ("BG30_MagicItem_407", ShipInABottleScript),
        ("BG30_MagicItem_410", QuilligraphySetScript),
        ("BG30_MagicItem_411", HoggyBankScript),
        ("BG30_MagicItem_420", BookOfMedivhScript),
        ("BG30_MagicItem_438t", MugOfTheSireScript),
        ("BG30_MagicItem_441", TinyfinOnesieScript),
        ("BG30_MagicItem_442", BloodGolemStickerScript),
        ("BG30_MagicItem_541", NetherPendantScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered


# DEFERRED（不注册）类占位——保留 docstring 台账供主线解冻时接管。
# 引擎缺口与实现路径见模块 docstring「DEFERRED 9 张」段。

class ConductorPortraitScript:
    """
    Natural language: [x]Get a Snarling Conductor.
    Whenever you discard a
    card, this plays a <b>Blood Gem</b>
    on all your minions.

    Status: DEFERRED — requires 弃牌机制（events.CARD_DISCARDED +
    game.discard_card）

    Dependency:
      1. 引擎零弃牌实现（`grep -i discard hsrl2/` 只命中 set.discard /
         pytest 注释）——"Whenever you **discard** a card" 无任何可监听
         信号; 授予物 BG28_585 Snarling Conductor 自身
         "At the start of your turn, discard a spell to gain 4 Gold." 同
         样依赖该机制（且该卡未注册）。
      2. 解冻路径: 引擎补 `game.discard_card(hero, entity)`（手牌移除 +
         `events.CARD_DISCARDED(hero=, card=)`）+ BG28_585 本体脚本 →
         本饰品 `on_bind` 挂 CARD_DISCARDED 监听 → 对本人棋盘全部
         `PlayBloodGems(m, 1)`（"plays a Blood Gem on all your minions"）。

    Params: count=1（"a Blood Gem" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TokenOfTheOldGodsScript:
    """
    Natural language: [x]<b>Spellcraft:</b> Choose a
    minion. Then choose a
    minion from a Tier higher
    to transform it into.

    Status: DEFERRED — requires trinket 版 Spellcraft 生成点 + 两段定向协议

    Dependency:
      1. 数据链存在（`spellcraft_id=112813` → BG30_MagicItem_416t），但
         `spellcraft.generate_for_hero` 只遍历 `hero.board`、
         `_make_spellcraft_spell` 以 `minion.controller` 入手——
         `hero.trinkets` 完全不在 Spellcraft 系统内（打出的临时法术还
         需要来源实体语义）。
      2. 该法术是**两段定向**（先选 minion、再按 tier+1 过滤第二段）——
         现有 `needs_target` / PendingChoice 只有单段目标。
      3. 解冻路径: `generate_for_hero` 增遍历 `hero.trinkets`（tag 自举
         同随从） + 引擎二级目标协议（PendingChoice 链）后实现
         `BG30_MagicItem_416t` 法术脚本（Transform Action，池记账按
         `Transform` 既有协议）。被阻塞卡: 416 + 429。

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BronzebeardPortraitScript:
    """
    Natural language: [x]Get a Brann Bronzebeard and
    a random <b>Battlecry</b> minion.
    Your Brann Bronzebeards are
    both Murlocs and Dragons.

    Status: DEFERRED — requires 多值种族身份

    Dependency: `GameTag.RACE` 是单值 tag; `Race.ALL` 语义为"匹配一切
    种族"而非"显示为两个种族"（会把 Beast/Mech/… 一并匹配，属近似而
    非精确）。batch_trinkets8 模块 docstring 已就同一缺口备案本卡
    （418/971 族）。解冻路径: `RACES` 集合 tag（或双种族位掩码）+
    种族匹配/查询全部读取点（`CardDef.race` 派生的 filter、光环、
    `_pool_candidates`）统一改造。

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class InnkeepersSteinScript:
    """
    Natural language: [x]The Tavern offers an extra
    minion of a higher Tier
    whenever it is <b>Refreshed</b>.

    Status: DEFERRED — requires "额外展示位按 tier+1 抽取"协议

    Dependency: 唯一展示数钩子 `GameTag.TAVERN_OFFER_MOD`（+N 个通用
    展示位）无法让**某一个**额外位从更高档抽取——`refresh_tavern` 的
    抽取上界恒为 `max_tier = hero.tavern_tier`。解冻路径:
    `hero._tavern_extra_higher_tier` 计数 + refresh_tavern 常规抽取后
    追加 `minion_pool.draw_tavern(tier+1, tier+1, count=_n)` 并经
    `inject_tavern_minion` 入馆（唯一入口）。

    Params: count=1（"an extra minion" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class AzeritePortraitScript:
    """
    Natural language: [x]Get a Living Azerite.
    Your Living Azerites
    also give stats to
    friendly Elementals.

    Status: DEFERRED — requires BG28_707 本体脚本 + "改写他卡行为"协议

    Dependency:
      1. 授予物 BG28_707 Living Azerite **未注册**（REGISTRY 无此 id）:
         "Whenever you cast a Tavern spell, give Elementals in the Tavern
         +{0}/+{1} this game." 无实现——载荷未就绪（SOP §12 item 14）。
      2. "also give stats to friendly Elementals" 是**改写另一张卡脚本
         行为**的效果类别: `set_script_override` 只作用于**已存在实体**，
         无法覆盖未来获得的副本、也无法按 owner 限定（饰品不得改写对手
         的 Living Azerite）。解冻路径: (a) 先实现 BG28_707 本体（含
         `hero.azerite_bonus` 家族机制）; (b) 引擎提供 owner 级
         「Living Azerite 额外结算面」读取点（如引擎侧
         新增 hero 级 `_azerite_extra_elemental` 标志并由本体脚本读取）。

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class DesignerEyepatchScript:
    """
    Natural language: You only need 2 copies of a Pirate to make it Golden.

    Status: DEFERRED — requires 按种族分档的三连阈值

    Dependency: 三连阈值是 hero 级单值
    `hero.get(GameTag.TRIPLE_THRESHOLD, 3)`（game.py::check_for_triple），
    且候选集为「同名 card_id」——无按种族取阈值的读取点（Clocksworth
    是全局 2）。解冻路径: `hero._triple_threshold_by_race`（race → N）
    + `check_for_triple` 按 `db.get(acquired.card_id).race` 选阈值
    （含 Amalgam ALL 的种族归属裁定）。

    Params: count=2（"2 copies" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class BoomControllerScript:
    """
    Natural language: [x]When you have space,
    summon an exact copy
    of your first Mech that
    died each combat.

    Status: DEFERRED — requires 有界的「战斗内 after-death 补位」协议

    Dependency:
      1. 该卡 XML 权威标签只有 `START_OF_COMBAT=1`（CardDefs.xml 113095;
         wiki XML tags 同），但"your first Mech that **died each
         combat**"指向战斗内持续触发——SoC 时点本场尚无死亡
         （`game.combat_death_log` 在 `run_combat` 开头清空），SoC 单
         检查点必然空转（注册即 no-op = 禁止的第三态）。
      2. AFTER_ATTACK 循环补召正是主线在 SOP §13 item 3 明令禁止的形态
         （Drek'Thar/Ozumat 曾"死一只→补一只"致 2001 轮
         `CombatLoopError`）——不得按文本字面自建无限补位。
      3. 解冻路径: 主线先裁定该族的**有界**触发协议（每场次数上限或
         与攻击循环的终止性证明），届时以 `DEATH` 记录本场首个机械的
         `(card_id, golden, snapshot_state)`，在有界补位点
         `create_minion + restore_state + summon`（精确副本 = 含 buff/
         金色——Zerek/`_exact_copy` 口径）。

    Params: 无模板参数（script_data_num_2=99 为内部计数参数，非文本占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None
