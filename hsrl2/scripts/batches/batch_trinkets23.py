"""批次 trinkets23 — 饰品第 23 批: 解冻 4 张（原 DEFERRED 台账见
batch_trinkets18 / batch_trinkets13 / batch_trinkets16 模块 docstring）。

本批 4 个 id 与其余批次注册集合互不相交；数值一律 `CardDef.num(0/1)`
（文本无占位符的增量按 SOP §3 在各类 `Params:` 行声明），随机一律
`game.rng`（无 `import random`），全部状态写在 source 实体闭包 /
hero 作用域（无 game 级 flag——SOP §12 item 9）。

解冻依据（引擎原语均由主线落地，2026-09-02）
═══════════════════════════════════════════════════════════════════════
  - `card_gained(hero=, card=)` —— hero 级"获得一张牌"事件
    （RULES §7.4.6b；`hero.add_to_hand` 成功入手时广播，满手入队
    不广播）→ 解锁 `BG35_MagicItem_713` Trusty Crowbar。
  - `game.grant_combat_deathrattle(hero, minion, fn)` —— 战斗内授予
    亡语公开原语（RULES §3.5/§6.13 注; 原生亡语先结算、追加效果后置，
    `_script_overrides` / `DEATHRATTLE` tag 由 `run_combat` 的 finally
    统一恢复，脚本**不再**自行挂 COMBAT_END 清理）→ 解锁
    `BG30_MagicItem_917` Rusty Trident / `BG30_MagicItem_952`
    Jarred Frostling。
  - `game.add_permanent_spellcraft_rule(hero, source, predicate)` ——
    "Your <X>s' Spellcrafts are permanent" 规则原语（RULES §7.4.7a;
    生成 Spellcraft 法术时对**来源随从**求值 predicate → 该次施放把
    目标的 temporary buff 翻转为永久，`_expire_at_next_turn` 不回收）
    → 解锁 `BG32_MagicItem_920` Thaumaturgist Portrait。
  - "随机 Spellcraft 法术" 候选集 = `batch_spells2._spellcraft_spell_ids`
    （池内 Spellcraft 随从 `spellcraft_id` 数据链; 36.2.2 实测 9 张
    基础法术），**不是**缺口（batch_trinkets13 台账的旧注记已不成立）。

注册 4 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG35_MagicItem_713  Trusty Crowbar        — 获得海盗时给最左随从
                                              +num(0)/+num(1)（永久附魔）
  BG30_MagicItem_917  Rusty Trident         — SoC: 本人全部纳迦获得
                                              「亡语: 随机 Spellcraft 法术入手」
  BG30_MagicItem_952  Jarred Frostling      — SoC: 随机 2 只友方元素获得
                                              「亡语: 召唤 Flourishing Frostling」
  BG32_MagicItem_920  Thaumaturgist Portrait— Get a Thaumaturgist;
                                              本人萨满的 Spellcraft 永久

逐卡语义核对（data 权威文本 + wiki 证据 + 运行时探针）
═══════════════════════════════════════════════════════════════════════
  - **713 Trusty Crowbar**。data/bg_trinkets.json 文本
    "Whenever you get a Pirate, give your left-most minion +{0}/+{1}."
    num(0)=num(1)=**12**（36.2.2 基线）。
    Evidence: wiki.gg/wiki/Battlegrounds/Trusty_Crowbar —— 36.4.2
    (2026-09-03) 才改为 +16/+16，本基线仍为 +12/+12（数值一律以
    `data/` 的 num() 为准，禁止跟随 wiki 的后续补丁）。
    口径: `card_gained` 携带 `card=`——**海盗** = 随从 ∧ `race ∈
    (PIRATE, ALL)`（Race.ALL 即全种族融合怪，RULES §6.4 通用裁定）;
    法术/血宝石不触发。"left-most minion" = 本人棋盘最左**存活**随从
    （board[0]，空板落空）。增量是招募阶段附魔（`actions.Buff`，
    temporary=False，RULES §3.5）——永久保留。
  - **917 Rusty Trident**。文本 "Start of Combat: Give your Naga
    'Deathrattle: Get a random Spellcraft spell.'"（无模板参数）。
    Evidence: wiki.gg 页 Wiki tags = `START_OF_COMBAT` / `DEATHRATTLE`
    / `BACON_SPELLCRAFT_ID`，分类含 [Random]（指随机 Spellcraft 法术）
    且**无** [Targeted] → "your Naga" = 本人**全部**纳迦（`race ∈
    (NAGA, ALL)`），非玩家选择。死亡时入手 1 张 Spellcraft 法术
    （`game.rng.choice` 于 `_spellcraft_spell_ids` 候选集; create_spell
    + SPELLCRAFT tag + `pending_hand_add` 满手排队）。
  - **952 Jarred Frostling**。文本 "Start of Combat: Give 2 friendly
    Elementals 'Deathrattle: Summon a Flourishing Frostling'."
    Evidence: wiki.gg 页 Wiki tags = `START_OF_COMBAT` / `DEATHRATTLE`
    / `BACON_EVOLUTION_CARD_ID=101267`，分类含 [Random]，**无**
    [Targeted] → 随机 2 只友方元素（`game.rng.sample` 无放回;
    不足 2 只时全部获得; 0 只落空）。授予物 = 数据链
    `evolution_card_id 101267 → BG26_537`（非池 token，2/1，零池操作）。
  - **920 Thaumaturgist Portrait**。data 文本（36.2.2）
    "Get a Thaumaturgist. Your Thaumaturgists' Spellcrafts are permanent."
    Evidence: wiki.gg 页在 36.4.2 (2026-09-03) 改为 "Get 2
    Thaumaturgists"——本基线 data 无 `{0}` 占位符且 num 全 None，
    文本为单数 "a Thaumaturgist" → **1** 张（数值/数量一律以 data 为准）。
    关联卡数据链 `evolution_card_id 115563 → BG31_924`（池 T2 纳迦，
    `grant_trinket_related_card` 按池占返）。"Your Thaumaturgists" 由
    predicate 按**数据链解析出的关联卡 id + 其金色本体**匹配（零硬编码
    卡 id; 含 `BG31_924_G`），`source` 离场（饰品被替换）规则自动失效
    （`_permanent_spellcraft_matches` 的生命周期校验）。

关联卡 / 授予物台账（RULES §7.4.6 —— 交付正确即 CORRECT；被点名卡的
脚本状态属那张卡的台账，不阻塞本饰品注册）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链） | 被授予卡脚本状态 |
  |---|---|---|
  | BG35_MagicItem_713 | 无（授予亡语/附魔，非交付卡） | — |
  | BG30_MagicItem_917 | 无（授予亡语） | 随机 Spellcraft 法术本体全部已注册 |
  | BG30_MagicItem_952 | 101267 → BG26_537 Flourishing Frostling | **未注册**（非池 token; 其"每个元素 +2/+1"动态属性钩子是那张卡的台账，仅影响召唤体身材，不阻塞"召唤"交付本身） |
  | BG32_MagicItem_920 | 115563 → BG31_924 Thaumaturgist | 已注册（`ThaumaturgistScript` + 法术 `BG31_924t`; 金色 `BG31_924_G` / `BG31_924_Gt` 亦已注册） |

接线审计读取点（W1/W2/W3 核对）: 饰品仅定义 `on_bind` / `start_of_combat`
（W1 白名单）; 监听事件名 `card_gained` 为引擎真实 fire
（hero.py `add_to_hand`）; 无脚本侧 `game._x` / `hero._x` 私有标记写入
（W3 无空转标记）。
"""

from __future__ import annotations

from hsrl2.actions import Buff
from hsrl2.events import Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.scripts.batches.batch_spells2 import _spellcraft_spell_ids
from hsrl2.tags import GameTag, Race

# 含 All 型的匹配族（融合怪全种族，RULES §6.4 通用裁定）
_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_NAGA_RACES = (Race.NAGA, Race.ALL)
_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)

# 文本字面量（CardDef 无模板参数; SOP §3）
FROSTLING_ID = "BG26_537"      # Flourishing Frostling（数据链 dbf 101267）
FROSTLING_COUNT = 2            # "Give 2 friendly Elementals"


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero) -> list:
    return [m for m in hero.board if not m.dead]


# ══════════════ BG35_MagicItem_713 Trusty Crowbar ══════════════

class TrustyCrowbarScript:
    """
    Natural language: Whenever you get a Pirate, give your left-most
    minion +{0}/+{1}.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_713`（greater,
    `spell_school=12`, `subset_pirate`, `script_data_num_1/2=12/12`）。
    wiki.gg 页 36.4.2 改为 +16/+16，本基线（36.2.2）仍为 +12/+12——
    数值以 `CardDef.num(i)` 为准。

    Formal spec:
      1. on_bind: 注册持久 `card_gained` 监听器（owner=饰品; 引擎在
         `hero.add_to_hand` 成功入手时广播，满手排队不广播——
         RULES §7.4.6b）。
      2. 条件: `hero is 本人` ∧ `card` 为随从 ∧ `card.race ∈
         (PIRATE, ALL)`（融合怪按海盗计——RULES §6.4）。
      3. 触发: 本人棋盘最左存活随从（board[0]）获得
         `Buff(atk=num(0), health=num(1))`（temporary=False——招募阶段
         永久附魔，RULES §3.5）; 空板落空（不消耗任何资源）。
      4. 只作用于本人（对手获得海盗不触发）。

    Test: test_batch_trinkets23.py — 真实购买海盗后最左随从 +12/+12 /
      非海盗不触发（正对照）/ 对手获得海盗不影响本人 / 空板落空 /
      永久附魔（temporary=False） / 两份副本各触发一次（+2×num） /
      融合怪按海盗计。

    Params: {0}=12 {1}=12（BG35_MagicItem_713 num(0/1)，36.2.2 基线）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None

        def on_gained(g, hero=None, card=None, _h=hero, _src=source, **kw):
            if hero is not _h or not isinstance(card, Minion):
                return
            if card.race not in _PIRATE_RACES:
                return
            board = _living(_h)
            if not board:
                return
            atk = _num(g, _src.card_id, 0)
            health = _num(g, _src.card_id, 1)
            g.run_actions(Buff(board[0], atk=atk, health=health))

        game.events.register(Listener(event="card_gained", owner=source,
                                      callback=on_gained))
        return None


# ══════════════ BG30_MagicItem_917 Rusty Trident ══════════════

def _rusty_trident_deathrattle(src, g, ctx, **kw):
    """追加亡语: 随机 1 张 Spellcraft 法术入手（`spellcraft_source_uuid`
    不设——非随从生成，无 Sunken Persistence 豁免; 与 batch_spells2
    Spitescale Special 同口径）。候选 = 池内 Spellcraft 随从
    `spellcraft_id` 数据链（36.2.2 共 9 张基础法术）。
    """
    hero = src.controller
    if hero is None:
        return None
    cands = _spellcraft_spell_ids(g)
    if not cands:
        return None
    sid = g.rng.choice(cands, label="rusty_trident")
    spell = g.create_spell(sid, controller=hero)
    if spell is None:
        return None
    spell.set(GameTag.SPELLCRAFT, True)
    g.pending_hand_add(hero, spell)
    return None


class RustyTridentScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give your Naga
    "<b>Deathrattle:</b> Get a random <b>Spellcraft</b> spell."

    Evidence: wiki.gg/wiki/Battlegrounds/Rusty_Trident —— Wiki tags
    `START_OF_COMBAT` / `DEATHRATTLE` / `BACON_SPELLCRAFT_ID`，分类含
    [Random]（随机 Spellcraft 法术）且无 [Targeted] → "your Naga" 指
    本人全部纳迦。`data/bg_trinkets.json` 无模板参数。

    Formal spec:
      1. start_of_combat: 本人棋盘存活 `race ∈ (NAGA, ALL)` 的随从
         全部（非随机挑选）经 `game.grant_combat_deathrattle(hero, m,
         _rusty_trident_deathrattle)` 获得追加亡语（原生亡语先结算，
         追加后置——引擎链式协议）。
      2. 该纳迦死亡时（战斗内）: `game.rng.choice` 于
         `_spellcraft_spell_ids(game)` 候选集取 1 张 →
         `create_spell` + 置 `SPELLCRAFT` tag + `pending_hand_add`
         （满手排队）; 候选空 → 落空。
      3. 仅本场战斗: override 与 `DEATHRATTLE` tag 由 `run_combat`
         finally / 战斗快照统一恢复，脚本不写 COMBAT_END 清理。
      4. 只作用于本人棋盘（对手纳迦不获授）; 无纳迦落空。

    Test: test_batch_trinkets23.py — SoC 后本人纳迦带 DEATHRATTLE 与
      override（对手纳迦不带）/ 战斗内死亡入手恰 1 张候选集内法术且带
      SPELLCRAFT tag / 战后 override 恢复且战后死亡不再产出 /
      无纳迦落空（正对照）/ 两份副本各授一次。

    Params: 无模板参数（"a random Spellcraft spell" = 1 张，文本字面量）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        nagas = [m for m in _living(hero) if m.race in _NAGA_RACES]
        if not nagas:
            return None
        for m in nagas:
            game.grant_combat_deathrattle(hero, m,
                                          _rusty_trident_deathrattle)
        return None


# ══════════════ BG30_MagicItem_952 Jarred Frostling ══════════════

def _jarred_frostling_deathrattle(src, g, ctx, **kw):
    """追加亡语: 召唤 1 只 Flourishing Frostling（BG26_537，非池 token，
    零池操作; 满场由 `game.summon` 走 MINION_OVERFLOW 语义）。
    """
    hero = src.controller
    if hero is None:
        return None
    token = g.create_minion(FROSTLING_ID, controller=hero)
    if token is None:
        return None
    g.summon(hero, token)
    return None


class JarredFrostlingScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give 2
    friendly Elementals
    "<b>Deathrattle:</b> Summon a
    Flourishing Frostling".

    Evidence: wiki.gg/wiki/Battlegrounds/Jarred_Frostling —— Wiki tags
    `START_OF_COMBAT` / `DEATHRATTLE` /
    `BACON_EVOLUTION_CARD_ID=101267`，分类含 [Random] 且无 [Targeted]
    → 随机 2 只友方元素。授予物数据链解析 = BG26_537。

    Formal spec:
      1. start_of_combat: 本人棋盘存活 `race ∈ (ELEMENTAL, ALL)` 的
         随从经 `game.rng.sample` 无放回随机取 min(2, 数量) 只
         （不足 2 只时全部获得）; 0 只落空。
      2. 选中的元素各经 `game.grant_combat_deathrattle(hero, m,
         _jarred_frostling_deathrattle)` 获得追加亡语（原生亡语先
         结算，追加后置）。
      3. 该元素死亡时（战斗内）: `create_minion(BG26_537)` +
         `game.summon`（满场走 MINION_OVERFLOW; 非池 token 零池操作）。
      4. 仅本场战斗（override/tag 由引擎统一恢复）; 只作用于本人棋盘。

    Test: test_batch_trinkets23.py — SoC 后本人恰 2 只元素带
      DEATHRATTLE（对手元素不带）/ 1 只时该只获得 / 无元素落空
      （正对照）/ 战斗内该元素死亡召唤 BG26_537 / 战后 override 恢复 /
      两份副本各授一次。

    Params: count=2（"Give 2 friendly Elementals" 文本字面量；
    CardDef num 全 None）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        elementals = [m for m in _living(hero)
                      if m.race in _ELEMENTAL_RACES]
        if not elementals:
            return None
        k = min(FROSTLING_COUNT, len(elementals))
        for m in game.rng.sample(elementals, k, label="jarred_frostling"):
            game.grant_combat_deathrattle(
                hero, m, _jarred_frostling_deathrattle)
        return None


# ══════════════ BG32_MagicItem_920 Thaumaturgist Portrait ══════════════

class ThaumaturgistPortraitScript:
    """
    Natural language: [x]Get a Thaumaturgist.
    Your Thaumaturgists'
    <b>Spellcrafts</b> are permanent.

    Evidence: `data/bg_quest_rewards.json`/`bg_trinkets.json BG32_MagicItem_920`
    （greater, cost 2, `evolution_card_id=115563 → BG31_924`,
    `spellcraft_id`/AURA 标记）。wiki.gg 页在 36.4.2 改为 "Get 2
    Thaumaturgists"，本基线（36.2.2）data 文本为单数且 num 全 None
    → 交付 **1** 张（数量以 data 文本为准）。

    Formal spec:
      1. on_bind: `game.grant_trinket_related_card(hero, source.card_id)`
         —— 数据链 `evolution_card_id` → `db.by_dbf` 解析 BG31_924，
         池随从按 `minion_pool.acquire` 占池，池空落空（入手 0 张），
         满手经 `pending_hand_add` 排队。
      2. 规则注册: `game.add_permanent_spellcraft_rule(hero, source,
         predicate)` —— predicate 匹配 `card_id ∈ {关联卡, 其金色本体}`
         （零硬编码卡 id，含 BG31_924_G）。生成 Spellcraft 法术时引擎
         对**来源随从**求值 → 命中则该次施放把目标的 temporary buff
         翻转为永久（RULES §7.4.7a），下一代 `_expire_at_next_turn`
         不回收。
      3. `source` 离场（饰品被替换）后 `_permanent_spellcraft_matches`
         的生命周期校验使规则失效（引擎侧保证）。
      4. 只作用于本人（对手的 Thaumaturgist 不被标记）。

    Test: test_batch_trinkets23.py — 绑定后入手 1 张 BG31_924 且池
      available-1 / 池空落空但规则仍注册（正对照: 池空下后续
      Spellcraft 仍永久）/ 本人萨满的法术 permanent_spellcraft=True 且
      施放后 buff temporary=False、跨回合不回收（无饰品对照会回收）/
      非萨满来源的法术不标记 / 金色萨满匹配 / 饰品离场规则失效 /
      对手萨满不标记 / 两份副本各交付 1 张。

    Params: 无模板参数（"Get a Thaumaturgist" = 1 张，文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        game.grant_trinket_related_card(hero, source.card_id)
        related = game.trinket_related_card(source.card_id)
        if related is None:
            return None
        ids = {related.id}
        golden = game.db.golden_version(related)
        if golden is not None:
            ids.add(golden.id)

        def matches(minion, _ids=ids):
            return getattr(minion, "card_id", None) in _ids

        game.add_permanent_spellcraft_rule(hero, source, matches)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 23 批（解冻 4 张）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_MagicItem_713", TrustyCrowbarScript),
        ("BG30_MagicItem_917", RustyTridentScript),
        ("BG30_MagicItem_952", JarredFrostlingScript),
        ("BG32_MagicItem_920", ThaumaturgistPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
