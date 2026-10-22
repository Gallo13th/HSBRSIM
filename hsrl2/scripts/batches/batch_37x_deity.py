"""批次 37x_deity — F-07 Deity 子系统 + 10 张池内 Deity 卡中的 7 张实现
（3 张依赖 Discard 子系统，留待 F-08）。

背景与证据
═══════════════════════════════════════════════════════════════════════
37.0 新机制 Deity（旧神隐藏目标）：
  - 官方 `BG_OldGod`（Secret Deity [DNT]）: "After 4 friendly
    Aberrations die each combat, awaken a {1}/{2} {5} ({0} left!)"，
    QUEST_PROGRESS_TOTAL=4、NUM_1=4、NUM_2=NUM_3=1、
    NUM_6=130610(`BGFYM_000` C'Thun)；`BACON_DEITY_SIGIL`/
    `BACON_OLD_GOD` 标记；START_OF_COMBAT/OBJECTIVE。
  - 官方公告（36.6.1；36.6.3 阈值 3→4）: 每名玩家开局隐藏随机获得
    C'Thun 或 Y'Shaarj；友方 Aberration 死亡推进进度；达到阈值后
    "Deity joins the fight"。
  - 引擎原语（F-07，`hsrl2/deity.py` + `Game` 方法）已覆盖:
    隐藏状态/属性累加/战斗中 Aberration 死亡进度/每场重置/
    awaken 召唤（属性=当前 Deity 状态）。
  - **C'Thun 的 awaken 特效 DEFERRED**（"split amongst your other
    minions" 的分配/余数规则无证据）；Y'Shaarj 亡语本批实现。

本批注册（15 + 2 个 token 脚本）
═══════════════════════════════════════════════════════════════════════
  BG36_108 / _G  Vicious Mindslasher：Whenever you cast a Tavern spell,
      give this and your Deity +{0}/+{1}.（数据 1/2；金 2/4）
  BG36_109 / _G  The Shadow of Doubt：Whenever a card is added to your
      hand, give your Deity +{0}/+{1}.（数据 4/5；金 8/10）
  BG36_110 / _G  Joyous：Battlecry: Give your Deity +{0}/+{1}.
      （数据 2/1；金 4/2 = 两次触发总额 → 用 `_per_trigger_def`）
  BG36_111 / _G  Sha of Fear：Whenever you cast a Tavern spell, give
      your minions and Deity +{0}/+{1}.（数据 3/3；金 6/6）
  BG36_113 / _G  Drifting Sacrifice：Reborn. Deathrattle: Give your
      Deity +{0}/+{1}.（数据 2/1；金 4/2）
  BG36_318 / _G  Faceless Converter：Deathrattle: Give your Deity
      +{0}/+{1}.（Improved by each Tavern spell you've cast this game!）
      （数据 2/1；金 4/2；倍率 = 1 + TAVERN_SPELLS_CAST_THIS_GAME）
  BG36_103 / _G  N'raqi Sapper：Battlecry and Deathrattle: Get an
      Energizing Chamber.（金 BC 引擎双触发；金 DR 2 份）
  BG36_371       Energizing Chamber（池内 T5 酒馆法术，cost 1）：
      Give your Deity +{0}/+{1}. If you discard this, cast it twice.
      （discard 分支不可达——Discard 子系统缺失，边界记档）
  BGFYM_011 / _G Y'Shaarj（Deity token）：Deathrattle: Summon your
      first {0} Aberrations that died this combat with their maximum
      stats (except Deities).（NUM_1=2/金 4）
  **C'Thun token `BGFYM_000`/_G 不注册**（split 规则 DEFERRED，见 F-07）。

DEFERRED（本批后仍缺）
═══════════════════════════════════════════════════════════════════════
  - BG36_099 Brain Rotter / BG36_106 Cutthroat K'Thir / BGFYM_005
    Harbinger Aph'lass：均需 **Discard 子系统** —— 已于 2026-10-18
    由 F-08 `batch_37x_discard` 注册（台账关闭）。
  - BG28_583 Geomagus Roogug（触发链无权威上限）为 F-08 后唯一剩余
    池内缺口。

数值/语义权威
═══════════════════════════════════════════════════════════════════════
- 数值一律 `CardDef.num(i)`；**金色战吼总额**用 `_per_trigger_def`
  （引擎金色战吼触发 2 次）；金色死亡/触发类不翻倍（读各自 CardDef）。
- Deity 属性写入唯一出口 `Game.give_deity_stats(hero, atk, health)`
  （F-07）；"give this and your Deity" 的自身增益用普通 `Buff`（非酒馆
  法术效果，不叠 TAVERN_SPELL_EXTRA）。
- "Each Tavern spell you've cast this game" = hero tag
  `TAVERN_SPELLS_CAST_THIS_GAME`（引擎 `play_spell` 对 is_pool_spell
  递增）；倍率 = 1 + 计数（Improve 家族口径）。
- 随机一律 `game.rng`；池内法术 Get 走 `grant_card_copy_to_hand`
  （Engergizing Chamber is_pool_spell=True）。

Test: `hsrl2/tests/test_batch_37x_deity.py`（真实 `play_minion` /
`play_spell` / `destroy_minion` / `run_script_hook` / `_process_single_death`
战斗死亡路径；正负对照 + 金色独立 CardDef）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import Buff
from hsrl2.events import TAVERN_SPELL_CAST, Listener
from hsrl2.game import GameStateError
from hsrl2.tags import GameTag

if TYPE_CHECKING:                                  # pragma: no cover
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# ── 卡 id ──
VICIOUS_MINDSLASHER = "BG36_108"
VICIOUS_MINDSLASHER_G = "BG36_108_G"
SHADOW_OF_DOUBT = "BG36_109"
SHADOW_OF_DOUBT_G = "BG36_109_G"
JOYOUS = "BG36_110"
JOYOUS_G = "BG36_110_G"
SHA_OF_FEAR = "BG36_111"
SHA_OF_FEAR_G = "BG36_111_G"
DRIFTING_SACRIFICE = "BG36_113"
DRIFTING_SACRIFICE_G = "BG36_113_G"
FACELESS_CONVERTER = "BG36_318"
FACELESS_CONVERTER_G = "BG36_318_G"
NRAQI_SAPPER = "BG36_103"
NRAQI_SAPPER_G = "BG36_103_G"
ENERGIZING_CHAMBER = "BG36_371"
YSHAARJ = "BGFYM_011"
YSHAARJ_G = "BGFYM_011_G"

#: Deity token（Y'Shaarj 亡语 "except Deities" 过滤用）
DEITY_TOKEN_IDS = frozenset({"BGFYM_000", "BGFYM_011"})

_DEITY_CARDS = (
    VICIOUS_MINDSLASHER, VICIOUS_MINDSLASHER_G,
    SHADOW_OF_DOUBT, SHADOW_OF_DOUBT_G,
    JOYOUS, JOYOUS_G,
    SHA_OF_FEAR, SHA_OF_FEAR_G,
    DRIFTING_SACRIFICE, DRIFTING_SACRIFICE_G,
    FACELESS_CONVERTER, FACELESS_CONVERTER_G,
    NRAQI_SAPPER, NRAQI_SAPPER_G,
    ENERGIZING_CHAMBER, YSHAARJ, YSHAARJ_G,
)


def _num(game: "Game", card_id: str, index: int) -> int:
    """`CardDef.num(index)` 权威取值; 缺失 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return int(value)


def _per_trigger_def(game: "Game", source):
    """金色战吼"每次触发值"解析: 金色实体回基础 CardDef。

    引擎对金色随从战吼触发 2 次；金色 CardDef 数值若已含"两次总额"
    （如 Joyous 金 4/2 = 2×(2/1)），每次触发必须用基础定义。
    """
    d = game.db.get(source.card_id)
    if d is not None and d.is_golden_def and d.triple_base_id is not None:
        base = game.db.by_dbf(d.triple_base_id)
        if base is not None:
            return base
    return d


def _give_deity(game: "Game", hero, atk: int, health: int) -> None:
    game.give_deity_stats(hero, atk, health)


class ViciousMindslasherScript:
    """
    Natural language: Whenever you cast a Tavern spell, give this and
    your <b>Deity</b> +{0}/+{1}.

    依据: CardDefs 37.0 BG36_108（T3 1/2 Aberration，NUM_1=1 NUM_2=2）；
    金色 BG36_108_G（NUM_1=2 NUM_2=4）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: 事件
         `tavern_spell_cast`(spell=)——条件 spell.controller is
         source.controller（"you cast"；Spellcraft/血宝石不广播）。
      2. 触发: 本体 `Buff(+NUM_1/+NUM_2)` + `Game.give_deity_stats`
         同额（"give this and your Deity"）。
      3. 金色数值由金色 CardDef 体现（触发类不翻倍）。

    Test: test_batch_37x_deity.py — 真实 play_spell 后本体/Deity 同步
    +1/+2 / 对手施放不触发 / 金色 +2/+4 / 非池法术不触发。

    Params: {0}=1 {1}=2（金色 2/4）
    """

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not hero:
                return
            dd = g.db.get(source.card_id)
            g.give_deity_stats(hero, int(dd.num(0)), int(dd.num(1)))
            g.run_actions([Buff(source, atk=int(dd.num(0)),
                                health=int(dd.num(1)))])

        game.events.register(Listener(
            event=TAVERN_SPELL_CAST, owner=source, callback=on_cast))
        return None

    #: Transform 后重新接线（SOP §16c 模式 40）
    on_transform = on_summon


class ShadowOfDoubtScript:
    """
    Natural language: Whenever a card is added to your hand, give your
    <b>Deity</b> +{0}/+{1}.

    依据: CardDefs 37.0 BG36_109（T6 6/8 Aberration，NUM_1=4 NUM_2=5）；
    金色 BG36_109_G（8/10）。

    Formal spec:
      1. on_summon 注册持久监听器: 事件 `card_gained`(hero=, card=)
         （`Hero.add_to_hand` 的统一广播，购买/生成/发现/复制全路径）。
      2. 条件 hero is source.controller（"your hand"）→
         `Game.give_deity_stats(NUM_1, NUM_2)`。
      3. 金色数值由金色 CardDef 体现。

    Test: test_batch_37x_deity.py — 购买/生成进手牌各触发一次 / 对手
    获得牌不触发 / 金色 8/10 / 满手排队入手仍触发。

    Params: {0}=4 {1}=5（金色 8/10）
    """

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_gained(g, hero=None, card=None, **kw):
            if hero is not source.controller:
                return
            d = g.db.get(source.card_id)
            g.give_deity_stats(hero, int(d.num(0)), int(d.num(1)))

        game.events.register(Listener(
            event="card_gained", owner=source, callback=on_gained))
        return None

    on_transform = on_summon


class JoyousScript:
    """
    Natural language: <b>Battlecry:</b> Give your <b>Deity</b>
    +{0}/+{1}.

    依据: CardDefs 37.0 BG36_110（T1 2/3 Aberration，NUM_1=2 NUM_2=1）；
    金色 BG36_110_G（4/2 = 金色文本总额，引擎金色战吼触发 2 次）。

    Formal spec:
      1. battlecry: `Game.give_deity_stats(NUM_1, NUM_2)`。
      2. 金色: 每次触发用**基础** CardDef（2/1）×引擎 2 次 = 4/2
         （`_per_trigger_def`；否则金卡 8/4 翻倍）。
      3. 无目标。

    Test: test_batch_37x_deity.py — 基础 +2/+1 / 金色 +4/+2 / 重复打出
    累加 / 敌方 Deity 不变。

    Params: {0}=2 {1}=1（金色总额 4/2）
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = _per_trigger_def(game, source)
        game.give_deity_stats(hero, int(d.num(0)), int(d.num(1)))
        return None


class ShaOfFearScript:
    """
    Natural language: Whenever you cast a Tavern spell, give your
    minions and <b>Deity</b> +{0}/+{1}.

    依据: CardDefs 37.0 BG36_111（T7 10/13 Aberration，NUM_1=NUM_2=3）；
    金色 BG36_111_G（6/6）。

    Formal spec:
      1. on_summon 注册持久监听器（owner=source）: `tavern_spell_cast`，
         条件 spell.controller is source.controller。
      2. 触发: 己方棋盘全部存活随从 `Buff(+NUM_1/+NUM_2)`（含本体）+
         同额 `give_deity_stats`（"your minions and Deity"）。
      3. 金色数值由金色 CardDef 体现（触发类不翻倍）。

    Test: test_batch_37x_deity.py — 真实 play_spell 后全板 +3/+3 且
    Deity +3/+3 / 对手施放不触发 / 金色 +6/+6 / 非池法术不触发。

    Params: {0}=3 {1}=3（金色 6/6）
    """

    @staticmethod
    def on_summon(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None

        def on_cast(g, spell=None, **kw):
            if spell is None or spell.controller is not hero:
                return
            dd = g.db.get(source.card_id)
            atk, health = int(dd.num(0)), int(dd.num(1))
            g.give_deity_stats(hero, atk, health)
            g.run_actions([Buff(m, atk=atk, health=health)
                           for m in list(hero.board) if not m.dead])

        game.events.register(Listener(
            event=TAVERN_SPELL_CAST, owner=source, callback=on_cast))
        return None

    on_transform = on_summon


class DriftingSacrificeScript:
    """
    Natural language: <b>Reborn</b> <b>Deathrattle:</b> Give your
    <b>Deity</b> +{0}/+{1}.

    依据: CardDefs 37.0 BG36_113（T3 2/1 Aberration，REBORN+
    DEATHRATTLE，NUM_1=2 NUM_2=1）；金色 BG36_113_G（4/2）。

    Formal spec:
      1. deathrattle: `Game.give_deity_stats(NUM_1, NUM_2)`。
      2. Reborn 由引擎关键词处理（死亡→亡语→复生顺序）；复生体死亡
         再次触发（同普通亡语规则）。
      3. 金色数值由金色 CardDef 体现。

    Test: test_batch_37x_deity.py — 真实 destroy 后 Deity +2/+1 /
    Reborn 真实复生后再次死亡再 +2/+1 / 金色 +4/+2。

    Params: {0}=2 {1}=1（金色 4/2）
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        game.give_deity_stats(hero, int(d.num(0)), int(d.num(1)))
        return None


class FacelessConverterScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Give your <b>Deity</b>
    +{0}/+{1}. <i>(Improved by each Tavern spell you've cast this
    game!)</i>

    依据: CardDefs 37.0 BG36_318（T5 5/5 Aberration，DEATHRATTLE，
    NUM_1=2 NUM_2=1）；金色 BG36_318_G（4/2）。

    Formal spec:
      1. deathrattle: 倍率 = 1 + hero.`TAVERN_SPELLS_CAST_THIS_GAME`
         （is_pool_spell 施放计数，Improve 家族口径）；Deity 获得
         NUM_1×倍率 / NUM_2×倍率。
      2. 金色数值由金色 CardDef 体现；倍率同一计数。

    Test: test_batch_37x_deity.py — 0 法术 +2/+1 / 施放 2 张池法术
    +6/+3 / 金色 4/2 → 12/6 / Spellcraft 非池法术不提高倍率。

    Params: {0}=2 {1}=1（金色 4/2；Improve 增量 = 印面值）
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        casts = hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
        mult = 1 + int(casts)
        game.give_deity_stats(hero, int(d.num(0)) * mult,
                              int(d.num(1)) * mult)
        return None


class EnergizingChamberScript:
    """
    Natural language: [x]Give your <b>Deity</b> +{0}/+{1}. If you
    discard this, cast it twice.

    依据: CardDefs 37.0 BG36_371（池内 T5 酒馆法术，cost 1，
    NUM_1=NUM_2=7）；无金色独立 CardDef。

    Formal spec:
      1. on_play: `Game.give_deity_stats(NUM_1, NUM_2)`。
      2. **discard 分支（F-08 已接线）**: `on_discard`（
         `Game.discard_card` 唯一分发点）→ Deity 增益结算 **2 次**
         （"If you discard this, cast it twice"）；弃置本身不触发
         on_play/不回池（见 F-08）。
      3. 无目标。

    Test: test_batch_37x_deity.py — 施放后 Deity +7/+7 / 池法术记账由
    Get 路径覆盖（N'raqi Sapper）/ 非池施放不占池；
    test_batch_37x_discard.py — 弃置后 Deity +14/+14。

    Params: {0}=7 {1}=7
    """

    @staticmethod
    def on_play(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        game.give_deity_stats(hero, int(d.num(0)), int(d.num(1)))
        return None

    @staticmethod
    def on_discard(source, game, ctx=None):
        """"If you discard this, cast it twice"（F-08）。"""
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        for _ in range(2):
            game.give_deity_stats(hero, int(d.num(0)), int(d.num(1)))
        return None


class NraqiSapperScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get an
    Energizing Chamber.

    依据: CardDefs 37.0 BG36_103（T5 6/3 Aberration，BATTLECRY+
    DEATHRATTLE）；金色 BG36_103_G（12/6，文本 "Get 2 Energizing
    Chambers"）。

    Formal spec:
      1. battlecry: Get 1 张 Energizing Chamber（池内法术 →
         `grant_card_copy_to_hand` 占 spell_pool；满手 pending 队列）。
         金色由引擎金色战吼双触发实现总额 2。
      2. deathrattle: 1 张（基础）/ 2 张（金色——亡语不翻倍，脚本分支）。

    Test: test_batch_37x_deity.py — 基础 BC 1 / 金色 BC 2（引擎双触发）/
    真实 destroy DR 1 / 金色 DR 2 / 池副本 -1/-2 / 满手排队。

    Params: 无数值参数（份数 = 文本字面量 1/2）
    """

    @staticmethod
    def battlecry(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        game.grant_card_copy_to_hand(hero, game.db.get(ENERGIZING_CHAMBER))
        return None

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        count = 2 if source.is_golden else 1
        for _ in range(count):
            game.grant_card_copy_to_hand(
                hero, game.db.get(ENERGIZING_CHAMBER))
        return None


class YShaarjDeityScript:
    """
    Natural language: [x]<b>Deity.</b> <b>Deathrattle:</b> Summon your
    first {0} Aberrations that died this combat with their maximum
    stats <i>(except <b>Deities</b>)</i>.

    依据: CardDefs 37.0 BGFYM_011（T1 1/1 Aberration token，NUM_1=2；
    DEATHRATTLE）；金色 BGFYM_011_G（2/2，NUM_1=4）。

    Formal spec:
      1. deathrattle: 读取 F-07 `Game.deity_combat_deaths(hero)`
         （本场友方 Aberration 死亡序列 [(base_id, 死亡时攻,
         死亡时最大生命)]，按死亡顺序），过滤 Deity token（"except
         Deities"），取前 NUM_1（=2/金 4）条。
      2. 每条以 `create_minion(base_id)` 生成白板副本，属性写为记录值
         （"with their maximum stats"），`Game.summon` 入场（默认最右
         空位；满场落空）。
      3. 金色 NUM_1=4（金色 CardDef）由数据体现；非金/金同一脚本。

    Test: test_batch_37x_deity.py — 真实战斗内 4 只 Aberration 死亡 →
    Deity（Y'Shaarj）awaken；杀 Y'Shaarj 后复活前 2 只且属性=死亡时
    最大属性 / 金色 4 只 / Deity 自身被排除 / 无记录不崩。

    Params: {0}=2（金色 4）
    """

    @staticmethod
    def deathrattle(source, game, ctx=None):
        hero = getattr(source, "controller", None)
        if hero is None:
            return None
        limits = _num(game, source.card_id, 0)
        records = [r for r in game.deity_combat_deaths(hero)
                   if r[0] not in DEITY_TOKEN_IDS]
        for base_id, atk, health in records[:limits]:
            m = game.create_minion(base_id, controller=hero)
            if m is None:
                continue
            m.set(GameTag.BASE_ATK, int(atk))
            m.set(GameTag.BASE_HEALTH, int(health))
            m.set(GameTag.HEALTH, int(health))
            game.summon(hero, m)
        return None


def register() -> list[str]:
    """注册 17 id：7 张 Deity 池卡 ×基础/金色 + Energizing Chamber +
    Y'Shaarj token 基础/金色。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (VICIOUS_MINDSLASHER, ViciousMindslasherScript),
        (VICIOUS_MINDSLASHER_G, ViciousMindslasherScript),
        (SHADOW_OF_DOUBT, ShadowOfDoubtScript),
        (SHADOW_OF_DOUBT_G, ShadowOfDoubtScript),
        (JOYOUS, JoyousScript),
        (JOYOUS_G, JoyousScript),
        (SHA_OF_FEAR, ShaOfFearScript),
        (SHA_OF_FEAR_G, ShaOfFearScript),
        (DRIFTING_SACRIFICE, DriftingSacrificeScript),
        (DRIFTING_SACRIFICE_G, DriftingSacrificeScript),
        (FACELESS_CONVERTER, FacelessConverterScript),
        (FACELESS_CONVERTER_G, FacelessConverterScript),
        (NRAQI_SAPPER, NraqiSapperScript),
        (NRAQI_SAPPER_G, NraqiSapperScript),
        (ENERGIZING_CHAMBER, EnergizingChamberScript),
        (YSHAARJ, YShaarjDeityScript),
        (YSHAARJ_G, YShaarjDeityScript),
    ]
    registered: list[str] = []
    for cid, cls in pairs:
        reg(cid, cls)
        registered.append(cid)
    return registered
