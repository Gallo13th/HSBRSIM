"""批次 bloodgem — 血宝石池随从 6 张（作业单 2026-08-21）。

OK 5 张（含金色 id，金色=独立卡定义）:
  BG20_100 Razorfen Geomancer / BG23_017 Sanguine Champion /
  BG33_430 Prodigious Tusker / BG34_682 Razorfen Flapper /
  BG34_683 Briarback Drummer / BG36_510 Vigilant Bristlemane

DEFERRED 1 张（不注册）: BG36_333 Jailbird Juggernaut。
  batch_rally2.py 已将其 DEFERRED 且未注册（本批 grep 复核——无
  registry 冲突）; 本批复核依赖缺口仍在（per-minion 血宝石计数不可
  完整观测 + 无 insert_attack 原子），维持 DEFERRED，详见该类
  docstring。主线解冻时以 batch_rally2.JailbirdJuggernautScript 为
  唯一落点，删除本文件占位避免双份文档。

BG34_689 Blood Gem Barrage（池法术，data 核实）: 本批仅实现其
**Get 路径**语义（Flapper 亡语 / Drummer 战吼获取 → 占法术池，
池空生成不占池——batch_deathrattle2 _get_pool_spell 同裁定）。
其施放脚本（"After the Tavern is Refreshed this game..."）属法术
批次，本批未注册。

共性语义:
- 血宝石三操作（actions/bloodgem.py）: GetBloodGems=进手牌（非池卡
  不占池）、PlayBloodGems=立即生效（数值 = BG20_GEM CardDef +
  hero BLOOD_GEM_BONUS_ATK/HEALTH tags，_gem_values 读取点统一）、
  ImproveBloodGems=hero 加成 tag 叠加（"this game" 永久，hero tag
  不在战斗快照内——Sanguine Refiner 先例）
- 金色战吼模型: 引擎 play_minion 对金色触发 2 次 × 基础每次值 =
  金色文本总额（batch_deathrattle2 Firescale Hoarder 先例）; 金色
  亡语单次触发 = 金色文本总额
- "Whenever ... attacks" 触发器 = AFTER_ATTACK 广播点（引擎 C4:
  伤害与死亡结算后; batch_rally2 Deathstrider 先例），
  recruit_phase_attack 同样广播 → 招募期攻击照常触发
- "cast a spell on this" = card_played(card=法术, target=this)
  （play_spell 广播 target——Wave2 G2; 效果施法路径不广播 card_played
  ——batch_rally2 统一裁定，本批遵循）; 随从打出的 card_played 不带
  target kwarg，天然不触发
- 亡语/池获取类钩子直接执行状态变更并 return None
  （batch_deathrattle/batch_deathrattle2 惯例——重入缺陷虽已修复，
  惯例保留与全库一致）
"""

from __future__ import annotations

from hsrl2.actions.bloodgem import (
    GetBloodGems,
    ImproveBloodGems,
    PlayBloodGems,
)
from hsrl2.events import AFTER_ATTACK, CARD_PLAYED, Listener
from hsrl2.game import GameStateError

# 身份标识常量（card id 非数值——bloodgem.BLOOD_GEM_VARIANTS 先例;
# 漂移守护测试对照 db）
BLOOD_GEM_BARRAGE_ID = "BG34_689"   # Blood Gem Barrage（池法术 T3）


def _get_barrages(game, hero, count: int) -> None:
    """Get count 张 Blood Gem Barrage 进手牌。

    裁定与 batch_deathrattle2._get_pool_spell 一致（法术池每张 1 副本）:
      - 池内有副本: spell_pool.acquire 占池（RULES §3.6.1）→
        create_spell → pending_hand_add（满手排队, P6）
      - 池空: 直接生成不占池（dark gift Mystic Essence 先例）——
        金色 "Get 2 copies" 文本总额必须可达成
    """
    for _ in range(count):
        if game.spell_pool.available(BLOOD_GEM_BARRAGE_ID) > 0:
            if not game.spell_pool.acquire(BLOOD_GEM_BARRAGE_ID):
                raise GameStateError(
                    f"pool spell acquire failed for "
                    f"{BLOOD_GEM_BARRAGE_ID}")
        game.pending_hand_add(
            hero, game.create_spell(BLOOD_GEM_BARRAGE_ID,
                                    controller=hero))


# ══════════════════ BG20_100 Razorfen Geomancer ══════════════════


class RazorfenGeomancerScript:
    """
    Natural language: <b>Battlecry:</b> Get 2 <b>Blood Gems</b>.

    Formal spec:
      1. battlecry（每次触发）: GetBloodGems(hero, times)——times 颗
         vanilla 血宝石进手牌（满手 pending_hand_add 排队，RULES §3.3）;
         血宝石非池卡不占池（GetBloodGems 保证）
      2. 金色版文本 "Get 4 Blood Gems" = 引擎金色战吼 ×2 × 每次触发 2
         → 总额 4，同一脚本类注册两个 id
      3. hero 缺失（引擎异常态）→ 落空 return None

    Test: test_batch_bloodgem.py — 打出后手牌 +2 张 BG20_GEM 且不占池 /
    金色打出总额 4 张

    Params: 无模板参数（"2"/"4" 为文本字面量; 宝石数值唯一来源
    BG20_GEM CardDef）
    """

    times = 2   # 文本 "2"（无模板参数，字面量核对官方文本）

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GetBloodGems(hero, source.scripts.times)


# ══════════════════ BG23_017 Sanguine Champion ══════════════════


class SanguineChampionScript:
    """
    Natural language: [x]<b>Battlecry and Deathrattle:</b>
    Your <b>Blood Gems</b> give an
    extra +1/+1 this game.

    Formal spec:
      1. battlecry（每次触发）与 deathrattle（单次触发）各执行
         ImproveBloodGems(hero, atk, health): hero 的
         BLOOD_GEM_BONUS_ATK/HEALTH 各叠加 +1/+1（"this game" 永久;
         hero tag 不在战斗快照内，战后保留; 叠加式）
      2. 生效点: _gem_values 读取点统一（手牌打出与 PlayBloodGems
         施放的宝石同时生效，bloodgem.py 保证）
      3. 金色战吼: 每次触发仍 +1/+1（引擎 ×2 → 总额 +2/+2 = 金色
         文本）; 金色亡语单次触发直接给金色总额 +2/+2（金色子类）
      4. 亡语触发时 source 已 GRAVEYARD，锚点 source.controller;
         亡语钩子直接执行 Action.do 并 return None
         （batch_deathrattle2 Firescale Hoarder 同构先例）
      5. hero 缺失 → 落空

    Test: test_batch_bloodgem.py — BC 后 tag +1/+1 且 gem_values 集成
    生效 / DR 再叠加 / 金色 BC 总额 +2/+2 / 金色 DR +2/+2

    Params: 无模板参数（+1/+1 为文本字面量，金色 +2/+2; 宝石基础数值
    唯一来源 BG20_GEM CardDef）
    """

    bc_atk = 1        # 每次战吼触发值（文本字面量，无模板参数）
    bc_health = 1
    dr_atk = 1        # 亡止单次触发值
    dr_health = 1

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        s = source.scripts
        return ImproveBloodGems(hero, s.bc_atk, s.bc_health)

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        s = source.scripts
        ImproveBloodGems(hero, s.dr_atk, s.dr_health).do(game)
        return None


class SanguineChampionGoldenScript(SanguineChampionScript):
    """
    Natural language: [x]<b>Battlecry and Deathrattle:</b>
    Your <b>Blood Gems</b> give an
    extra +2/+2 this game.

    Formal spec:
      1. battlecry 继承基础版（每次触发 +1/+1）——引擎金色战吼 ×2 →
         总额 +2/+2
      2. deathrattle 单次触发实现金色文本总额: +2/+2（覆盖 dr 值）

    Test: test_batch_bloodgem.py — 金色打出 tag +2/+2 / 金色亡语 +2/+2

    Params: 无模板参数（+2/+2 为金色文本字面量）
    """

    dr_atk = 2        # 金色亡语总额（金色文本字面量，无模板参数）
    dr_health = 2


# ══════════════════ BG33_430 Prodigious Tusker ══════════════════


class ProdigiousTuskerScript:
    """
    Natural language: Whenever another friendly minion attacks, this
    plays a <b>Blood Gem</b> on it.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source: 出售/招募期死亡/移除
         自动注销; 战斗中战死注销、战后随监听器表快照恢复——引擎保证）
      2. 事件 AFTER_ATTACK（伤害与死亡结算后广播，C4;
         recruit_phase_attack 同样广播 → 招募期攻击照常触发），
         回调内过滤:
         a) attacker.controller is source.controller（"friendly"）
         b) attacker is not source（"another"）
         c) attacker 已战死 → 跳过（Buff 目标须为有效存活随从;
            AFTER_ATTACK 无论存活与否都广播——Deathstrider 同观测，
            其效果无需目标故不跳，本卡效果以随从为目标故跳过）
      3. 触发: PlayBloodGems(attacker, times)——立即生效 buff
         （数值 = BG20_GEM CardDef + hero 加成 tags; 战斗内施放经
         快照战后回滚——RULES §3.5 默认，Tarecgosa 类持久为显式例外）
      4. times 颗（金色 "plays 2 Blood Gems" → times=2 金色文本字面量）

    Test: test_batch_bloodgem.py — 友方攻击后 attacker 获得宝石 buff /
    Tusker 自身攻击不触发 / 敌方攻击不触发 / 战死 attacker 跳过 /
    金色 2 颗

    Params: 无模板参数（"a Blood Gem" = 1 颗/次; 宝石数值唯一来源
    BG20_GEM CardDef）
    """

    times = 1   # "a Blood Gem"（文本字面量，无模板参数）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_after_attack(g, attacker=None, defender=None, **kw):
            hero = source.controller
            if hero is None or attacker is None:
                return
            if attacker is source:
                return
            if attacker.controller is not hero:
                return
            if attacker.dead:
                return
            g.run_actions(PlayBloodGems(attacker, source.scripts.times))

        game.events.register(Listener(
            event=AFTER_ATTACK,
            owner=source,
            callback=on_after_attack,
        ))
        return None


class ProdigiousTuskerGoldenScript(ProdigiousTuskerScript):
    """
    Natural language: Whenever another friendly minion attacks, this
    plays 2 <b>Blood Gems</b> on it.

    Formal spec: 同基础版，times=2（监听器触发非战吼，引擎不翻倍——
    金色子类显式加倍）。

    Test: test_batch_bloodgem.py — 金色一次攻击 2 颗宝石 buff

    Params: 无模板参数（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ BG34_682 Razorfen Flapper ══════════════════


class RazorfenFlapperScript:
    """
    Natural language: <b>Deathrattle:</b> Get a Blood Gem Barrage.

    Formal spec:
      1. deathrattle（单次触发; source 已 GRAVEYARD，锚点
         source.controller）: _get_barrages(hero, times)——times 张
         BG34_689（池法术，data is_pool_spell 权威）进手牌:
         acquire 优先占法术池 / 池空生成不占池 +
         pending_hand_add（满手排队, P6）
      2. Barrage 施放脚本属法术批次（本批未注册，见模块 docstring）
      3. 亡语钩子直接执行并 return None（引擎死亡语惯例）
      4. hero 缺失 → 落空

    Test: test_batch_bloodgem.py — 亡语后手牌 +1 张 BG34_689 且占池 /
    池空仍生成 / 金色亡语 2 张

    Params: 无模板参数（"a" = 1 张/次，文本原文）
    """

    times = 1   # "a Blood Gem Barrage"（文本字面量，无模板参数）

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_barrages(game, hero, source.scripts.times)
        return None


class RazorfenFlapperGoldenScript(RazorfenFlapperScript):
    """
    Natural language: <b>Deathrattle:</b> Get 2 Blood Gem Barrages.

    Formal spec: 同基础版，times=2（金色亡语单次触发 = 金色文本总额;
    第一份占池、第二份池空生成）。

    Test: test_batch_bloodgem.py — 金色亡语 2 张 BG34_689

    Params: 无模板参数（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ BG34_683 Briarback Drummer ══════════════════


class BriarbackDrummerScript:
    """
    Natural language: <b>Battlecry:</b> Get a Blood Gem Barrage.

    Formal spec:
      1. battlecry（每次触发）: _get_barrages(hero, 1)——1 张 BG34_689
         （池法术）进手牌（acquire 优先占池 / 池空生成不占池 +
         pending_hand_add; 裁定见模块 docstring）
      2. 金色版文本 "Get 2" = 引擎金色战吼 ×2 × 每次触发 1 → 总额 2，
         同一脚本类注册两个 id
      3. 池获取为直接状态变更（非 Action），return None
         （Firescale Hoarder 先例）

    Test: test_batch_bloodgem.py — 打出后手牌 +1 张 BG34_689 且占池 /
    金色打出总额 2 张 / 池空仍生成

    Params: 无模板参数（"a" = 1 张/次，文本原文）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_barrages(game, hero, 1)
        return None


# ══════════════════ BG36_510 Vigilant Bristlemane ══════════════════


class VigilantBristlemaneScript:
    """
    Natural language: [x]Whenever you cast a spell
    on this, it plays a <b>Blood Gem</b>
    on adjacent minions.

    Formal spec:
      1. on_summon 注册持久监听器（owner=source，生命周期同 Tusker）
      2. 事件 CARD_PLAYED（play_spell 广播 card=法术实体 + target=
         目标——Wave2 G2; 随从打出的 card_played 不带 target kwarg，
         天然不触发; 效果施法路径不广播——batch_rally2 统一裁定），
         回调内过滤:
         a) target is source（"on this"）
         b) card.controller is source.controller（"you cast"——对手
            施放的定向法术不触发）
      3. 触发: 对 source 当前相邻（|zone_position 差|=1）的每个存活
         友方随从 PlayBloodGems(adj, times)——立即生效（数值 =
         BG20_GEM CardDef + hero 加成 tags）; 触发时点在施放法术的
         on_play 效果之后（card_played 广播序），相邻判定取实时棋盘
      4. times 颗（金色 "plays 2 Blood Gems" → times=2）
      5. 无相邻存活随从 → 落空; source 自身不在目标内

    Test: test_batch_bloodgem.py — 对 Bristlemane 施放宝石后两相邻各
    获宝石 buff / 对其他随从施放不触发 / 对手施放不触发 / 打出随从不
    触发 / 金色 2 颗

    Params: 无模板参数（"a Blood Gem" = 1 颗/相邻; 宝石数值唯一来源
    BG20_GEM CardDef）
    """

    times = 1   # "a Blood Gem"（文本字面量，无模板参数）

    @staticmethod
    def on_summon(source, game, ctx):
        def on_card_played(g, card=None, target=None, **kw):
            hero = source.controller
            if hero is None or target is None:
                return
            if target is not source:
                return
            if getattr(card, "controller", None) is not hero:
                return
            pos = source.zone_position
            adjacent = [m for m in hero.board
                        if not m.dead and m is not source
                        and abs(m.zone_position - pos) == 1]
            for m in adjacent:
                g.run_actions(PlayBloodGems(m, source.scripts.times))

        game.events.register(Listener(
            event=CARD_PLAYED,
            owner=source,
            callback=on_card_played,
        ))
        return None


class VigilantBristlemaneGoldenScript(VigilantBristlemaneScript):
    """
    Natural language: [x]Whenever you cast a spell on
    this, it plays 2 <b>Blood Gems</b>
    on adjacent minions.

    Formal spec: 同基础版，times=2（监听器触发非战吼，引擎不翻倍——
    金色子类显式加倍）。

    Test: test_batch_bloodgem.py — 金色触发后相邻各 2 颗宝石 buff

    Params: 无模板参数（"2" 为金色文本字面量）
    """

    times = 2


# ══════════════════ 以下 DEFERRED（不注册 REGISTRY） ══════════════════


class JailbirdJuggernautScript:
    """
    Natural language: [x]<b>Rally:</b> Summon a Golem with
    stats equal to this minion's
    <b>Blood Gems</b> to attack the
    target first. <i>({0}/{1})</i>

    Status: DEFERRED — requires per-minion 血宝石计数 + 召唤即攻击
    （batch_rally2 同名 DEFERRED 类的依赖复核，本批确认缺口仍在）

    Dependency（引擎缺口，主线处理; 实现落点 batch_rally2，解冻时
    删除本占位类）:
      1. **per-minion Blood Gem 计数不可完整观测**: "stats equal to
         this minion's Blood Gems" = 对该随从施放过的宝石总数。观测面:
         a) 手牌打出路径: card_played(card=BG20_GEM 族 4 id,
            target=this) 可计数——但仅覆盖此路径
         b) PlayBloodGems 路径（本批 Tusker/Bristlemane 即引入）:
            施加匿名 entity.Buff，**无任何事件广播**（bloodgem.py
            明示 "played Blood Gem 专用事件为引擎缺口"）→ 不可计数。
            subagent 禁改 bloodgem.py/minion.py，需主线加
            GEMS_PLAYED minion 计数 tag（tags.py 主线专属）或
            Buff source 标注
         c) 仅按 a) 计数会在 Tusker+Jailbird 同场（本批即引入的组合）
            时显著漏计 → 禁止近似实现（SOP 铁律）
      2. **召唤即攻击**: "to attack the target first"——Golem 须在本体
         攻击伤害前对 rally 目标发起完整攻击（双向伤害/圣盾/剧毒/
         死亡结算）。rally 时点位于 CombatScheduler._execute_attack
         内层（combat.py:207），无嵌套攻击原子（本批复核:
         insert_attack 仍不存在）; 需引擎提供
         "insert_attack(attacker, defender)"
      3. Golem token 无 db 定义（本批全库检索 name 含 Golem 的
         非池 token——无 BG36_333 关联 token）; {0}/{1} 为运行时动态
         显示参数，CardDef num 为 None 属预期——非 PARAM_MISSING。
         需合成 token（batch_deathrattle Golemancy 先例）+ 漂移守护
      4. 金色 "double this minion's Blood Gems" → 计数 ×2（金色文本
         字面量）
    """

    @staticmethod
    def rally(source, game, ctx):
        return None


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG20_100", RazorfenGeomancerScript)
    _add("BG20_100_G", RazorfenGeomancerScript)        # ×2 触发 → 4 颗
    _add("BG23_017", SanguineChampionScript)
    _add("BG23_017_G", SanguineChampionGoldenScript)   # DR 覆盖 2/2
    _add("BG33_430", ProdigiousTuskerScript)
    _add("BG33_430_G", ProdigiousTuskerGoldenScript)   # 2 gems
    _add("BG34_682", RazorfenFlapperScript)
    _add("BG34_682_G", RazorfenFlapperGoldenScript)    # 2 Barrages
    _add("BG34_683", BriarbackDrummerScript)
    _add("BG34_683_G", BriarbackDrummerScript)         # ×2 触发 → 2 张
    _add("BG36_510", VigilantBristlemaneScript)
    _add("BG36_510_G", VigilantBristlemaneGoldenScript)  # 2 gems
    return registered
