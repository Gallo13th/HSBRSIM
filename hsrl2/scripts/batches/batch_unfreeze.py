"""清尾批 unfreeze — 引擎原语收口（2026-08-22 对抗审查）后的 15 张解冻卡。

全部为此前 DEFERRED 台账卡，依赖的引擎原语已就绪（EFFECT_SCRIPT_SOP
§10）: execute_immediate_attack / GEMS_PLAYED_ON / GOLDEN_MINIONS_PLAYED /
card_discovered / spell_resolving+permanence_pending / buff_applied /
HEALTH_REFRESHES_LEFT / on_enter_hand / _gilded_no_reward_uuids /
PERSIST_* / ADJACENT_PERSIST_SOURCE / SPELL_DOUBLER / StealBloodGems /
BOUNTY_SPELL_IDS。既有占位类（batch_misc / batch_rally2 / batch_bloodgem /
batch_econ_misc / batch_activate / batch_spells2 / batch_spells4 的
DEFERRED 段）均未注册——本批注册即接管，占位类待主线清理。

数据核实（data/bg_cards.json 36.2.2）:
  BG36_333 Jailbird Juggernaut T7 Quilboar rally; {0}/{1} 为动态显示
            参数（num=None 属预期——Golem 实时攻/血）; 金色 "double
            this minion's Blood Gems"（**单个** Golem 属性 ×2，金色
            文本权威——作业单 "金色双 Golem" 注与卡面不符，以卡面为准）
  Golem token = BG30_MagicItem_442t Blood Golem（wiki Related cards
            权威; 非池卡不占池）
  BG23_009 Lava Lurker num(0)=1/回合金色 2（每回合可永久化施放数）
  BG26_524 Malchezaar num(0)=2/金色 4（每回合健康刷新次数）
  BG36_508 Cagey Conjurer activate_cost=1=num(0)、num(1)=2/金色 4
  BG36_344 Hooktusk num(0)=num(1)=1/金色 2/2
  BG24_018 Tortollan Blue Shell 卖价 5/金色 10（文本字面量，无占位符）
  BG26_137 Bream Counter num(0)=num(1)=6/金色 12/12
  BG35_814 Scarlet Survivor num(0)=6 阈值（金基础 6/6 即达标）
  BG33_825 Proud Privateer / BG35_883 Balinda / BG29_813 Poet /
  BG21_015 Tarecgosa / BG32_236 Aureate Laureate / BG31_892 Fandral's
  Fortune / BG28_698 Gem Confiscation: 无模板参数

Choose One 候选集与 batch_rally2 Bramble Tunneler 同一定义（数据
choose_one 标志含 BG31_327 Trailblazer 噪声——该卡是 Choose One 光环
而非 Choose One 卡，人工核对清单排除）。
"""

from __future__ import annotations

from hsrl2.actions import Buff, GainKeyword
from hsrl2.actions.bloodgem import PlayBloodGems, StealBloodGems, _gem_values
from hsrl2.events import Listener
from hsrl2.game import GameStateError, PendingChoice
from hsrl2.minion import Minion
from hsrl2.queue import Action
from hsrl2.tags import GameTag, Race, Zone

# Golem token（wiki Related cards + bg_cards.json 双核实; 非池卡）
_TOKEN_BLOOD_GOLEM = "BG30_MagicItem_442t"

# Choose One 池卡全集（batch_rally2 Bramble Tunneler 同款人工核对清单;
# 数据 choose_one 标志对 BG31_327 误标——其为双效光环卡，排除）
CHOOSE_ONE_MINION_IDS = frozenset({
    "BG27_084",   # Sprightly Scarab
    "BG30_123",   # Fearless Foodie
    "BG31_320",   # Crater Miner
    "BG32_237",   # Intrepid Botanist
    "BG36_330",   # Sly Infiltrator
    "BG36_332",   # Snare Trapper
    "BG36_341",   # Veteran Brigand
})
CHOOSE_ONE_SPELL_IDS = frozenset({
    "BG31_880",   # Alliance Flag
    "BG31_881",   # Time Management
    "BG31_886",   # Forest's Bounty
    "BG31_890",   # Boundless Potential
})


def _board_neighbors(target) -> list:
    """target 棋盘存活相邻随从（±1 位）; 不在棋盘 → 空（batch_rally2 同款）。"""
    hero = getattr(target, "controller", None)
    board = hero.board if hero is not None else []
    if target not in board:
        return []
    pos = target.zone_position
    return [m for m in board
            if m is not target and not m.dead
            and abs(m.zone_position - pos) == 1]


# ══════════════════ 1. BG36_333 Jailbird Juggernaut ══════════════════


class SummonGolemForceAttack(Action):
    """召唤属性覆写 Golem 并立即对 rally 目标发起完整单次攻击。

    - token: BG30_MagicItem_442t Blood Golem（非池卡不占池）
    - 属性覆盖式设定（SummonTokenSetStats 先例，batch_deathrattle）
    - 立即攻击 = combat.execute_immediate_attack（SOP §10 原语:
      完整单次攻击语义——双向同时伤害/圣盾/剧毒/死亡结算/AFTER_ATTACK）
    - 0/0 Golem（0 颗宝石，卡面即显示 (0/0)）: 召唤后立即死亡
      （HEALTH=0 → dead），死亡波次由外层队列处理; 0 攻不发起攻击
      （C9 同语义）。满场: game.summon 走 minion_overflow 丢弃，不攻击
    """

    def __init__(self, hero, golem_atk: int, golem_health: int,
                 defender) -> None:
        self.hero = hero
        self.golem_atk = golem_atk
        self.golem_health = golem_health
        self.defender = defender

    def do(self, game) -> None:
        golem = game.create_minion(_TOKEN_BLOOD_GOLEM,
                                   controller=self.hero)
        golem.set(GameTag.BASE_ATK, self.golem_atk)
        golem.set(GameTag.BASE_HEALTH, self.golem_health)
        golem.set(GameTag.HEALTH, self.golem_health)
        game.summon(self.hero, golem)
        if golem.dead or golem.zone != Zone.PLAY or golem.atk <= 0:
            return
        from hsrl2.combat import execute_immediate_attack
        execute_immediate_attack(game, golem, self.defender)


class JailbirdJuggernautScript:
    """
    Natural language: [x]<b>Rally:</b> Summon a Golem with
    stats equal to this minion's <b>Blood Gems</b> to attack the
    target first. <i>({0}/{1})</i>
    （金色 BG36_333_G: ... stats equal to **double** this minion's
    <b>Blood Gems</b> ...）

    Formal spec:
      1. rally（攻击宣告时、伤害前; ctx["target"] 保证存活）:
         Golem 属性 = GEMS_PLAYED_ON 计数 × 单颗宝石当前价值
         （BG20_GEM.num(0/1) + 目标控制者 BLOOD_GEM_BONUS_*——
         ImproveBloodGems 加成实时反映，与卡面动态显示 ({0}/{1})
         一致; batch_misc DEFERRED 台账既定裁定）
      2. Golem 召唤至本体右侧（token 不占池）后**立即**对 rally
         目标发起完整攻击（execute_immediate_attack——先于本体
         攻击伤害结算，"attack the target first"）; 本体攻击由
         外层 _execute_attack 继续
      3. 金色: 单个 Golem 属性 ×2（金色卡面 "double this minion's
         Blood Gems" 权威; **非**两个 Golem——作业单备注与卡面不符
         处以卡面为准）
      4. 0 颗宝石 → 0/0 Golem（召唤即死，不攻击）

    Test: test_batch_unfreeze.py::TestJailbirdJuggernaut — 宝石数→
    Golem 属性/先攻伤害 / 0 宝石负例 / 金色 ×2 / 满场丢弃

    Params: {0}/{1} 为运行时动态显示参数（CardDef num=None 属预期，
    非 PARAM_MISSING）; 金色倍率 2 为金色文本字面量 "double"
    """

    @staticmethod
    def rally(source, game, ctx):
        target = (ctx or {}).get("target")
        hero = source.controller
        if hero is None or target is None:
            return None
        gems = source.get(GameTag.GEMS_PLAYED_ON, 0)
        mult = 2 if source.is_golden else 1
        if gems > 0:
            gem_atk, gem_health = _gem_values(game, "BG20_GEM", hero)
            golem_atk = gems * gem_atk * mult
            golem_health = gems * gem_health * mult
        else:
            golem_atk = golem_health = 0
        return SummonGolemForceAttack(hero, golem_atk, golem_health,
                                      target)


# ══════════════════ 2. BG23_009 Lava Lurker ══════════════════


class LavaLurkerScript:
    """
    Natural language: [x]The first <b>Spellcraft</b> spell
    _played from hand on this
    each turn is permanent.
    _<i>({0} left!)</i>
    （金色 BG23_009_G: The first **2** <b>Spellcraft</b> spells ...）

    Formal spec:
      1. on_summon 注册 spell_resolving Listener（owner=source，
         离场注销）
      2. 命中条件: target is source 且 spell 带 SPELLCRAFT tag 且
         本回合已永久化次数 < num(0)（基础 1/金色 2; 计数记于
         实体属性 _lava_perma_used=(turn, used)，turn_start
         Listener 每回合归零——不依赖 game.turn 单调性）
      3. 命中: 设 game._permanence_pending = source.uuid——引擎
         add_buff 将该次施放对 source 施加的 temporary buff 翻转
         为永久（SOP §10 永久化拦截窗口; _finish_play_spell 每次
         施放后自动清除标记，不外溢）
      4. "{0} left" 为运行时显示参数; num(0)=每回合次数权威
      5. 已知衔接缺口（上报主线）: scripts/spells.py
         _expire_at_next_turn 的精确移除回调不检查 buff.temporary
         ——翻转后的永久 buff 仍会在下一回合开始被回收; 需主线在
         该回调跳过 temporary=False 的 buff（与 Sunken Persistence
         家族同一清理点）。本脚本交付引擎原语语义（翻转），
         test 断言翻转即时态
      6. AMBIGUOUS（docstring 备案）: "played from hand" 与效果
         直施（Cagey Conjurer 类 fire spell_resolving 的路径）在
         事件参数层不可区分; 现有直施路径目标恒为施放者自身，
         不与本卡相交，暂无假阳性面

    Test: test_batch_unfreeze.py::TestLavaLurker — 首个 Spellcraft
    翻转 / 同回合第二个不翻转 / 非 Spellcraft 不翻转 / 金色每回合 2 次

    Params: {0}=1（BG23_009 每回合次数）; 金色 {0}=2（BG23_009_G）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        d = game.db.get(source.card_id)
        per_turn = d.num(0)

        def on_turn_start(g, hero=None, **kw):
            if hero is source.controller:
                source._lava_perma_used = (g.turn, 0)

        def on_resolving(g, spell=None, target=None, cast_no=0, **kw):
            if target is not source or spell is None:
                return
            if not spell.has(GameTag.SPELLCRAFT):
                return
            used_turn, used = getattr(source, "_lava_perma_used",
                                      (None, 0))
            if used_turn != g.turn:
                used_turn, used = g.turn, 0
            if used >= per_turn:
                return
            source._lava_perma_used = (g.turn, used + 1)
            g._permanence_pending = source.uuid

        game.events.register(Listener(
            event="spell_resolving", owner=source,
            callback=on_resolving))
        game.events.register(Listener(
            event="turn_start", owner=source,
            callback=on_turn_start))
        return None


# ══════════════════ 3. BG26_524 Malchezaar, Prince of Dance ══════════════════


class MalchezaarScript:
    """
    Natural language: Two <b>Refreshes</b> each turn cost Health
    instead of Gold. <i>(@ left!)</i>
    （金色 BG26_524_G: **Four** <b>Refreshes</b> ...）

    Formal spec:
      1. on_summon: hero.set(HEALTH_REFRESHES_LEFT, num(0))——
         引擎 refresh_tavern 消费点已就绪（优先免费刷新次数，
         之后健康次数: 扣 1 点生命（护甲先扣）、不足以支付时回落
         金币路径，生存守卫）
      2. TURN_START Listener（owner=source）每回合重置为 num(0)
         （"each turn"）; 多个 Malchezaar 同场幂等不叠加（官方:
         效果不叠乘）
      3. 离场清零: minion_sold / 招募期 death（in_combat 死亡经
         战斗快照恢复，不清——监听器随快照存续） / transform 三
         事件清 HEALTH_REFRESHES_LEFT=0（光环语义: 离场即失效，
         防止残留 tag 泄漏到离场后的回合）
      4. "@ left" 为运行时显示参数，num(0)=次数权威

    Test: test_batch_unfreeze.py::TestMalchezaar — 刷新扣血不扣金 /
    次数用尽回落金币 / 回合重置 / 出售后清零 / 负例（无 Malchezaar
    刷新正常扣金）

    Params: {0}=2（BG26_524 script_data_num_1）; 金色 {0}=4
    """

    @staticmethod
    def on_summon(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        n = game.db.get(source.card_id).num(0)
        hero.set(GameTag.HEALTH_REFRESHES_LEFT, n)

        def reset(g, hero=None, **kw):
            if hero is source.controller:
                source.controller.set(GameTag.HEALTH_REFRESHES_LEFT,
                                      n)

        def clear(g, **kw):
            hero.set(GameTag.HEALTH_REFRESHES_LEFT, 0)

        game.events.register(Listener(
            event="turn_start", owner=source, callback=reset))
        game.events.register(Listener(
            event="minion_sold", owner=source,
            condition=lambda minion=None, **kw: minion is source,
            callback=clear))
        game.events.register(Listener(
            event="death", owner=source,
            condition=lambda minion=None, **kw: (
                minion is source and not game.in_combat),
            callback=clear))
        game.events.register(Listener(
            event="transform", owner=source,
            condition=lambda old=None, **kw: old is source,
            callback=clear))
        return None


# ══════════════════ 4. BG36_508 Cagey Conjurer ══════════════════


class CageyConjurerScript:
    """
    Natural language: [x]<b>Activate ({0}):</b> Cast {1}
    random Tavern spells
    __<i>(targets this if possible)</i>.

    Formal spec:
      1. activate 钩子（引擎已扣 num(0) 费用并管每回合 1 次）
      2. 候选 = db.pool_spells() ∩ 已注册 REGISTRY ∩ spell_pool
         可用 ∩ tech_level ≤ hero.tavern_tier（RULES §3.6.2 酒馆
         法术按等级提供的同构约束; 当前已注册法术 49/75——≥20
         分布阈值，作业单裁定 CORRECT）
      3. 施放 num(1) 次（基础 2/金色 4），每次独立随机
         （game.rng.choice 有放回）; 每施放:
         a. create_spell 直施其脚本 on_play（效果直施先例:
            不占池、不计 TAVERN_SPELLS_CAST——非购买施放）
         b. "targets this if possible": 法术脚本 needs_target 时
            ctx target=source（本随从）
         c. fire spell_resolving(spell=, target=, cast_no=)——
            与引擎施放口径对齐（0 基 cast_no; Lava Lurker/
            Proud Privateer 类拦截器照常工作; 直施路径目标
            恒为本随从）
      4. Choose One 法术直施 → 其脚本自行入队选择（自动化层
         choice_policy 决策）; 无候选（池空）→ 落空（真实行为）
      5. 金色 num(1)=4 自然体现（金色 CardDef 权威）

    Test: test_batch_unfreeze.py::TestCageyConjurer — 施放次数与
    效果（确定性收窄候选池）/ 定向法术打自身 / 无候选落空 / 金色 4 次

    Params: {0}=1（费用，与 activate_cost 一致）{1}=2（BG36_508）;
    金色 {0}=1 {1}=4（BG36_508_G）
    """

    @staticmethod
    def activate(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        from hsrl2.scripts import REGISTRY
        count = game.db.get(source.card_id).num(1)
        cands = [sd.id for sd in game.db.pool_spells()
                 if sd.id in REGISTRY
                 and sd.tech_level <= hero.tavern_tier
                 and game.spell_pool.available(sd.id) > 0]
        if not cands:
            return None
        for i in range(count):
            pick = game.rng.choice(cands, label="cagey_conjurer_spell")
            spell = game.create_spell(pick, controller=hero)
            target = source if getattr(
                spell.scripts, "needs_target", False) else None
            spell_ctx = {"target": target} if target is not None else {}
            game.events.fire(game, "spell_resolving", spell=spell,
                             target=target, cast_no=i)
            game.run_actions(spell.call_script("on_play", spell_ctx))
        return None


# ══════════════════ 5. BG31_892 Fandral's Fortune ══════════════════


class _CombinedChooseOneProxy:
    """被发现的 Choose One **法术**实体的 per-entity 脚本代理。

    引擎 play_spell 的双效分流只扫描棋盘 CHOOSE_BOTH 光环、不读
    法术实体 tag（引擎缺口）——代理隐藏 choose_options 阻止引擎
    入队单选 PendingChoice（双效卡不应有选择窗），其余属性
    （needs_target 等）透传原脚本; on_play 行为由
    set_script_override 的双效闭包接管。
    """

    def __init__(self, base_script) -> None:
        self._base = base_script
        self.choose_options = None
        self.needs_target = getattr(base_script, "needs_target", False)

    def __getattr__(self, name):
        return getattr(self._base, name)


def _mark_combined_effects(entity, game) -> None:
    """给被发现的 Choose One 卡实体挂"恒双效"。

    资格判定以 **CardDef.choose_one 关键词**为权威（法术 Choose One
    脚本无 choose_options 类属性——batch_spells4 _queue_choose_one
    自队模式; 随从脚本才有）。

    - Minion: 引擎 play_minion 已消费实体 CHOOSE_BOTH tag（跳过
      选择直接 choose="both"）→ tag + battlecry override（依次以
      每个 choose key 调原脚本分支——随从 Choose One 脚本按
      ctx["choose"] 直接分派; 金色由引擎触发 2 次 × 双分支 =
      金色总额，每次值由原脚本 _per_trigger_def 保证）; 未注册
      脚本的 Choose One 随从仅置 tag（其 battlecry 缺口由注册
      审计跟踪，本函数不越权）
    - Spell: override 调一次原 on_play 后把其入队的选择**抽干**，
      对每个 key 直接调脚本的 resolve 闭包（双分支全结算、无
      选择窗; scripts 代理隐藏 choose_options 防引擎层提示，
      needs_target 透传——定向 Choose One 法术的目标选择仍由
      引擎正常产生）
    """
    d = game.db.get(entity.card_id)
    if d is None or "choose_one" not in d.keywords:
        return
    base = entity.scripts
    entity.set(GameTag.CHOOSE_BOTH, True)
    if isinstance(entity, Minion):
        if base is None or not getattr(base, "choose_options", None):
            return

        def combined(src, g, c):
            ctx = dict(c or {})
            outs = []
            for key, _label in (getattr(base, "choose_options", None)
                                or []):
                ctx["choose"] = key
                result = base.battlecry(src, g, dict(ctx))
                if result is None:
                    continue
                outs.extend(result if isinstance(result, list)
                            else [result])
            return outs or None

        entity.set_script_override("battlecry", combined)
    else:
        if base is None:
            return
        entity.scripts = _CombinedChooseOneProxy(base)

        def combined_spell(src, g, c):
            before = list(g.pending_choices)
            result = base.on_play(src, g, dict(c or {}))
            for pc in [pc for pc in g.pending_choices
                       if pc not in before]:
                g.pending_choices.remove(pc)
                for key in list(pc.options):
                    if pc.resolve_callback is not None:
                        pc.resolve_callback(key)
            return result

        entity.set_script_override("on_play", combined_spell)


class FandralsFortuneScript:
    """
    Natural language: <b>Discover</b> a <b>Choose One</b> card.
    It has both effects combined.

    Formal spec:
      1. on_play: 候选 = Choose One 池卡（minion: CHOOSE_ONE_MINION_
         IDS ∩ 池可用/active_races（_pool_candidates 语义）; spell:
         CHOOSE_ONE_SPELL_IDS ∩ spell_pool 可用; 清单与 batch_rally2
         Bramble Tunneler 同源——数据 choose_one 标志对 BG31_327
         光环卡误标，人工清单排除）→ rng.sample 3 选项入队
         PendingChoice(kind="discover_choose_one"，kind 以 discover
         前缀保证 card_discovered 事件照常 fire——Hooktusk 联动）
      2. resolve（池感知）: minion → minion_pool.acquire →
         create_minion → set(CHOOSE_BOTH) + _mark_combined_effects →
         pending_hand_add; spell → spell_pool.acquire → create_spell
         → 同标记（满手排队 P6）
      3. "It has both effects combined" = 实体级恒双效: 被发现卡
         打出时跳过二选一、两个分支都结算（per-entity override——
         随从: 逐 key 调 battlecry; 法术: 抽干脚本自队的选择、
         逐 key 调 resolve 闭包; 已注册 Choose One 脚本无需自带
         both 分支）
      4. AMBIGUOUS（备案）: 定向分支的 target 聚合无官方证据
         （双分支各自入队目标选择 vs 单目标双效）——取各自独立
         结算（分支自洽，值语义不变）
      5. 三连排除: 被发现的基础版参与正常三连（合成的新金色实体
         不带 conferred 标记——三连掉 Fandral 属性，官方直觉一致）

    Test: test_batch_unfreeze.py::TestFandralsFortune — 候选/占池/
    恒双效打出（Foodie 双分支） / Choose One 法术双效且无选择窗 /
    普通打出仍二选一（负例）

    Params: 无模板参数（Discover 3 选项为引擎常量）
    """

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        from hsrl2.actions.discover import _pool_candidates
        minion_cands = [cid for cid in _pool_candidates(game)
                        if cid in CHOOSE_ONE_MINION_IDS]
        spell_cands = [cid for cid in CHOOSE_ONE_SPELL_IDS
                       if game.spell_pool.available(cid) > 0]
        cands = minion_cands + spell_cands
        if not cands:
            return None
        k = min(3, len(cands))
        options = game.rng.sample(cands, k, label="fandral_options")

        def resolve(pick_id: str) -> None:
            if pick_id in CHOOSE_ONE_MINION_IDS:
                if not game.minion_pool.acquire(pick_id):
                    raise GameStateError(
                        f"Fandral's Fortune: pool acquire failed "
                        f"for {pick_id}")
                card = game.create_minion(pick_id, controller=hero)
            else:
                if not game.spell_pool.acquire(pick_id):
                    raise GameStateError(
                        f"Fandral's Fortune: spell pool acquire "
                        f"failed for {pick_id}")
                card = game.create_spell(pick_id, controller=hero)
            _mark_combined_effects(card, game)
            game.pending_hand_add(hero, card)

        game.pending_choices.append(PendingChoice(
            hero, options, "discover_choose_one",
            resolve_callback=resolve))
        return None


# ══════════════════ 6. BG28_698 Gem Confiscation ══════════════════


class GemConfiscationScript:
    """
    Natural language: [x]This plays 2 <b>Blood
    Gems</b> on a minion.
    It steals all <b>Blood Gems</b>
    from its neighbors.

    Formal spec:
      1. needs_target=True（"on a minion" 定向——引擎 play_spell
         spell_target PendingChoice 分流; 无候选时落空但照常消耗）
      2. on_play 顺序（文本序）:
         a. PlayBloodGems(target, 2)——vanilla 宝石直施（不经手牌;
            数值=BG20_GEM.num(0/1)+target 控制者 bonus; per-minion
            GEMS_PLAYED_ON 记账 + blood_gem_played 事件）
         b. 对 target 的每个棋盘存活相邻随从 StealBloodGems
            (recipient=target, victim=邻居)——"It steals ... from
            its neighbors"（It=目标随从: 目标**从**邻居处窃取，
            gem 标记 buff 整体移转、数值不重算、GEMS_PLAYED_ON
            计数同步转移）
      3. 边缘位目标（无/单邻居）按实际邻居集结算

    Test: test_batch_unfreeze.py::TestGemConfiscation — 直施 2 颗 +
    双邻居移转记账 / 单邻居 / 无宝石邻居不产生空移转

    Params: count=2（"plays 2 Blood Gems" 文本字面量——CardDef 无
    模板参数）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = (ctx or {}).get("target")
        if target is None:
            return None
        actions = [PlayBloodGems(target, 2, source=source)]
        actions.extend(
            StealBloodGems(target, neighbor)
            for neighbor in _board_neighbors(target))
        return actions


# ══════════════════ 7. BG36_344 Hooktusk, Master Marauder ══════════════════


class HooktuskScript:
    """
    Natural language: [x]After you <b>Discover</b> a card, give
    your other Pirates +{0}/+{1}.
    <i>(Improved by Golden minions
    ___you played this game!)</i>
    （金色 BG36_344_G: ... give your other Pirates +{0}/+{1}.
    ... 同文，num=2/2）

    Formal spec:
      1. on_summon 注册 card_discovered Listener（owner=source）
      2. 命中: kind 以 "discover" 开头或 == "triple_reward"（官方
         语义: 三连奖励文本即 "Discover a minion of a higher
         tier"，属 Discover; kind=="dark_gift" 非Discover 排除）
         且 hero is source.controller
      3. 增益 = (num(0)+GMP, num(1)+GMP)，GMP=hero
         GOLDEN_MINIONS_PLAYED（引擎打出路径自动递增，SOP §10）
         ——"Improved by" 家族加法语义（每实例 +1; Lovesick
         Balladist "Improved by each Gold you spent" 同构先例）
      4. 目标: source 控制者的其他存活 Pirates（race PIRATE 或
         ALL; 含 ALL——Amalgam 规则; 排除 source 自身 "other"）
      5. 金色 num(0)/num(1)=2/2 自然体现（金色 CardDef 权威，
         加法: (2+GMP)/(2+GMP)）

    Test: test_batch_unfreeze.py::TestHooktusk — Discover 后其他
    Pirate +num/GMP 改进 / dark_gift 不触发 / 自身与非 Pirate 排除 /
    triple_reward 触发

    Params: {0}=1 {1}=1（BG36_344）; 金色 {0}=2 {1}=2（BG36_344_G）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        d = game.db.get(source.card_id)

        def on_discovered(g, kind=None, hero=None, **kw):
            ctrl = source.controller
            if ctrl is None or hero is not ctrl:
                return
            if not (kind is not None and (
                    kind.startswith("discover")
                    or kind == "triple_reward")):
                return
            gmp = ctrl.get(GameTag.GOLDEN_MINIONS_PLAYED, 0)
            g.run_actions([
                Buff(m, atk=d.num(0) + gmp, health=d.num(1) + gmp)
                for m in ctrl.board
                if m is not source and not m.dead
                and m.race in (Race.PIRATE, Race.ALL)])

        game.events.register(Listener(
            event="card_discovered", owner=source,
            callback=on_discovered))
        return None


# ══════════════════ 8. BG33_825 Proud Privateer ══════════════════


class ProudPrivateerScript:
    """
    Natural language: Your <b>Bounties</b> cast twice.
    （金色 BG33_825_G: You cast your <b>Bounties</b> three times.）

    Formal spec:
      1. on_summon 注册 spell_resolving Listener（owner=source——
         Wiki tags [Ongoing effect]/[Bounty-related]: 在场持续效果，
         离场即失效）
      2. 命中: spell.card_id ∈ constants.BOUNTY_SPELL_IDS（五张
         T3 法术，数据核实）且 cast_no==0（主施放——引擎 0 基:
         _finish_play_spell `for _ in range(casts)`）且 spell
         控制者是 source 控制者
      3. 追加施放: 基础 1 次 / 金色 2 次（"twice/three times"
         总额 − 主施放 1 次）——直接调 spell.call_script("on_play",
         ctx) 等效双施; **计数与事件按施放次数计**（2026-08-23 修正，
         Evidence 见下）: 每次追加施放各 +1 TAVERN_SPELLS_CAST_
         THIS_TURN/_GAME（is_pool_spell 时）、fire spell_resolving
         （cast_no=1+i，防自监听重入）与 tavern_spell_cast
         （"after you cast" 触发器可见，Balinda 引擎双施同构——
         game._finish_play_spell 计数/广播均按 casts 循环）
      4. 时序备案: spell_resolving 在主施放 on_play **之前** fire
         → 追加施放实际先于主施放结算（对既有五张 Bounty 的
         对称/无序效果无行为差异）
      5. 与 Balinda 叠加: 引擎双施的 cast_no=1 不命中（仅
         cast_no==0 追加）→ Balinda+Privateer = 3 施（基础档）;
         card_played 不逐次追加（"play a card" 按卡计非按施计——
         引擎单卡单播，口径一致）

    Evidence:
      - fantasywarden S13 指南: "every **cast** scaled with your
        current Tavern spell... Proud Privateer will double or
        triple the bounty effects"（逐施缩放口径）
      - 引擎 Balinda 双施先例（game._finish_play_spell: 计数/
        tavern_spell_cast 广播按 casts 次数——官方 29.2.2 bugfix
        "after you cast 时序" 注释同源）
      - 卡页 Wiki tags [Ongoing effect]; 无 Notes（wiki.gg/wiki/
        Battlegrounds/Proud_Privateer 全文核对）

    Test: test_batch_unfreeze.py::TestProudPrivateer — Wealthy
    Bounty 金币 ×2 / 金色 ×3 / 非 Bounty 法术单施（负例）/
    每施计数与 tavern_spell_cast 逐次广播

    Params: 无模板参数（twice/three 为金色文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        import hsrl2.constants as C

        def on_resolving(g, spell=None, target=None, cast_no=0, **kw):
            ctrl = source.controller
            if ctrl is None or spell is None:
                return
            if cast_no != 0 or spell.card_id not in C.BOUNTY_SPELL_IDS:
                return
            if spell.controller is not ctrl:
                return
            extra = 2 if source.is_golden else 1
            d = g.db.get(spell.card_id)
            spell_ctx = ({"target": target}
                         if target is not None else {})
            for i in range(extra):
                if d is not None and d.is_pool_spell:
                    ctrl.set(GameTag.TAVERN_SPELLS_CAST_THIS_TURN,
                             ctrl.get(
                                 GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0)
                             + 1)
                    ctrl.set(GameTag.TAVERN_SPELLS_CAST_THIS_GAME,
                             ctrl.get(
                                 GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)
                             + 1)
                g.events.fire(g, "spell_resolving", spell=spell,
                              target=target, cast_no=1 + i)
                g.run_actions(spell.call_script("on_play",
                                                dict(spell_ctx)))
                if d is not None and d.is_pool_spell:
                    g.events.fire(g, "tavern_spell_cast", spell=spell)

        game.events.register(Listener(
            event="spell_resolving", owner=source,
            callback=on_resolving))
        return None


# ══════════════════ 9. BG35_883 Balinda Stonehearth ══════════════════


class BalindaStonehearthScript:
    """
    Natural language: [x]Your spells that target
    friendly minions cast
    twice.
    （金色 BG35_883_G: ... cast **three** times.）

    Formal spec:
      1. on_summon: source.set(SPELL_DOUBLER)——引擎 _finish_play_
         spell 棋盘扫描消费（定向友方随从法术效果多施; 金色随从
         is_golden 自动 ×3: extra_casts=2; 离场光环失效——监听
         器生命周期由棋盘扫描天然保证）
      2. 引擎既有契约（test_engine_primitives TestSpellDoubler
         已覆盖双施/计数），本类仅声明 tag（Brann 同构）

    Test: test_batch_unfreeze.py::TestBalinda — tag 声明 + 定向法术
    双施集成 / 无 Balinda 单施（负例）/ 金色三施

    Params: 无模板参数（twice/three 为文本字面量，引擎消费）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.SPELL_DOUBLER, True)
        return None


# ══════════════════ 10. BG29_813 Persistent Poet ══════════════════


class PersistentPoetScript:
    """
    Natural language: [x]<b>Divine Shield</b>. Adjacent
    Dragons permanently keep
    <b><b>Bonus Keyword</b>s</b> and stats
    gained in combat.
    （金色 BG29_813_G: ... keep ... and **double** ____stats gained
    in combat.）

    Formal spec:
      1. on_summon: source.set(ADJACENT_PERSIST_SOURCE)——引擎
         run_combat 战后恢复消费（战前相邻为准的相邻龙保留战斗
         属性增益; 倍率 mult=2 if any poet.is_golden——金色
         "double stats" 由引擎读取金色标志自动 ×2）
      2. DS 由 create_minion 关键词映射（data 权威标签）
      3. 引擎既有契约（game.py poet_persist 段），本类仅声明 tag

    Test: test_batch_unfreeze.py::TestPersistentPoet — 相邻龙保留
    战斗增益 / 非相邻回退 / 金色 Poet 双倍 / 非 Dragon 相邻不保留

    Params: 无模板参数
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.ADJACENT_PERSIST_SOURCE, True)
        return None


# ══════════════════ 11. BG21_015 Tarecgosa ══════════════════


class TarecgosaScript:
    """
    Natural language: This permanently keeps <b><b>Bonus Keyword</b>s</b>
    and stats gained in combat.

    Formal spec:
      1. on_summon: source.set(PERSIST_COMBAT_CHANGES)——引擎
         run_combat 战后按"捕获总增益 × 倍率"重放为永久 Buff
         （倍率 1×——池卡版; 关键词按 _PERSIST_KEYWORD_TAGS 覆写
         保留）; 池卡 Tarecgosa **不设** PERSIST_DOUBLE（那是
         Tarecgosa's Blessing Dark Gift / 金色版专用）

    Test: test_batch_unfreeze.py::TestTarecgosa — 战斗增益保留 /
    无 tag 随从回退（负例）

    Params: 无模板参数
    """

    @staticmethod
    def on_summon(source, game, ctx):
        source.set(GameTag.PERSIST_COMBAT_CHANGES, True)
        return None


class TarecgosaGoldenScript(TarecgosaScript):
    """
    Natural language: This permanently keeps <b><b>Bonus Keyword</b>s</b>
    and **double** stats gained in combat.
    （BG21_015_G）

    Formal spec: 同基础版 + PERSIST_DOUBLE（引擎恢复倍率 2×）。

    Test: test_batch_unfreeze.py::TestTarecgosa — 金色双倍保留

    Params: 无模板参数（double 为金色文本字面量）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        TarecgosaScript.on_summon(source, game, ctx)
        source.set(GameTag.PERSIST_DOUBLE, True)
        return None


# ══════════════════ 12. BG24_018 Tortollan Blue Shell ══════════════════


class TortollanBlueShellScript:
    """
    Natural language: If you lost your last combat, this minion
    sells for 5 Gold.
    （金色 BG24_018_G: ... sells for **10** Gold.）

    Formal spec:
      1. on_sell（引擎 sell_minion 先 fire on_sell 后读 SELL_VALUE
         ——时序已核对 game.sell_minion:377-381）: source 控制者
         _last_combat_result == "loss"（引擎 run_combat 战后写入，
         SOP §10 契约）→ source.set(SELL_VALUE, 卖价)
      2. 卖价: 基础 5 / 金色 10（文本字面量，无占位符; is_golden
         分支）; win/draw/无战斗记录 → 常规卖价 1（不改 tag）

    Test: test_batch_unfreeze.py::TestTortollanBlueShell — 败局卖
    5 / 金色败局 10 / 胜局与无记录卖 1（负例）

    Params: sell=5（BG24_018 文本字面量）; 金色 sell=10
    （BG24_018_G）
    """

    @staticmethod
    def on_sell(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        if getattr(hero, "_last_combat_result", None) != "loss":
            return None
        source.set(GameTag.SELL_VALUE, 10 if source.is_golden else 5)
        return None


# ══════════════════ 13. BG26_137 Bream Counter ══════════════════


class BreamCounterScript:
    """
    Natural language: While this is in your hand, after you play
    a Murloc, gain +{0}/+{1}.

    Formal spec:
      1. on_enter_hand（hero.add_to_hand 触发——SOP §10 手牌钩子）
         注册 card_played Listener（owner=source）
      2. 命中: card 是 Minion 且 card.controller is source.
         controller 且 card.race ∈ (MURLOC, ALL)（Amalgam 规则）
         且 source.zone == HAND（"While this is in your hand"——
         打出/移手后条件自闭; 实体离场（卖出/打出后被清场）时
         监听器注销）
      3. 命中: Buff(source, +num(0)/+num(1))——buff 落在实体上，
         打出后随实体保留
      4. 引擎缺口备案: buy_from_tavern 直改 hand 不经 add_to_hand
         ——购买入手的 Bream Counter 不触发 on_enter_hand（监听器
         未注册，购买路径失联; 需主线把购买路径统一到 add_to_hand）
      5. 金色 num(0)/num(1)=12/12 自然体现

    Test: test_batch_unfreeze.py::TestBreamCounter — 打 Murloc 手牌
    中成长 / 非 Murloc 不触发 / ALL 种族计入 / 离手后不再触发

    Params: {0}=6 {1}=6（BG26_137）; 金色 {0}=12 {1}=12（BG26_137_G）
    """

    @staticmethod
    def on_enter_hand(source, game, ctx):
        d = game.db.get(source.card_id)

        def on_played(g, card=None, **kw):
            if source.zone != Zone.HAND:
                return
            if not isinstance(card, Minion):
                return
            if card.controller is not source.controller:
                return
            if card.race not in (Race.MURLOC, Race.ALL):
                return
            g.run_actions(Buff(source, atk=d.num(0),
                               health=d.num(1)))

        game.events.register(Listener(
            event="card_played", owner=source, callback=on_played))
        return None


# ══════════════════ 14. BG32_236 Aureate Laureate ══════════════════


class AureateLaureateScript:
    """
    Natural language: <b>Divine Shield</b>
    This minion is always Golden, but doesn't give a Triple Reward.

    Formal spec:
      1. on_enter_hand: source.set(GOLDEN, True)——实体恒金:
         check_for_triple 跳过 is_golden（天然不入三连）、出售/
         淘汰按金色回池 3 份、打出计入 GOLDEN_MINIONS_PLAYED
         （Hooktusk/Maritime Extortionist 数据源——官方一致）
      2. game._gilded_no_reward_uuids.add(uuid)——SOP §10 Gilding
         协议（三连奖励发放处的排除集合; 本卡永不来自三连合成，
         双保险入册）
      3. DS 由 create_minion 关键词映射; 基础/金色卡定义同 2/2
         （数值无差异，"always Golden" 是身份属性）
      4. 引擎缺口备案: 同 Bream Counter——buy_from_tavern 购买
         路径不触发 on_enter_hand（购买入手不恒金，需主线统一
         购买路径到手牌钩子）

    Test: test_batch_unfreeze.py::TestAureateLaureate — 入手恒金 +
    no_reward 册 / 三连检查对其免疫 / 金色版同构

    Params: 无模板参数
    """

    @staticmethod
    def on_enter_hand(source, game, ctx):
        source.set(GameTag.GOLDEN, True)
        game._gilded_no_reward_uuids.add(source.uuid)
        source.set(GameTag.GILDED_NOT_TRIPLED, True)   # 回池按 1 份
        return None


# ══════════════════ 15. BG35_814 Scarlet Survivor ══════════════════


class ScarletSurvivorScript:
    """
    Natural language: Once this reaches {0} Attack, gain
    <b>Divine Shield</b>.@Once this reaches {0} Attack, gain
    <b>Divine Shield</b>. <i>(Done!)</i>

    Formal spec:
      1. on_summon: 初始检查（atk ≥ num(0) → GainKeyword(DS)——
         金色 6/6 即时达标）+ 注册 buff_applied Listener
         （owner=source; target is source）——属性到达即触发
         （buff/光环/宝石各路径 add_buff 全覆盖）
      2. "Once"（一次性，卡面 "(Done!)" 终态）: 招募期首次达标
         时置实体属性 _scarlet_done=True; 已 DS/已 done 不重复
      3. 语义裁定（2026-08-23 查证维持）: 战斗内达标（game.in_combat）
         仅授予本场 DS（引擎战后快照恢复按 RULES §3.5 回收，与
         其他战斗内关键词同口径）且**不消耗**一次性成就——招募期
         再次达标仍可永久获得; 招募期达标则为永久（无快照回收）。
         佐证: 官方 35.6.0 bugfix "Fixed a bug where Scarlet Survivor
         **died before gaining Divine Shield**"（wiki.gg/wiki/
         Battlegrounds/Scarlet_Survivor#Patch_changes）——战斗内达标
         即时获得 DS（时点在死亡结算前），且官方将其作为可修复缺陷
         （战斗内达标是官方预期路径）; 卡页无 Notes（全文核对）。
      4. atk 读取经实体属性视图（base+buffs+光环+动态钩子）
      5. 金色阈值 num(0)=6 与基础版相同（金色基础 6/6 召唤即达标
         ——即时 DS）

    Test: test_batch_unfreeze.py::TestScarletSurvivor — 初始不达标
    无 DS / buff 至阈值获得 DS / 阈值下不触发（负例）/ 金色即达 /
    一次性（再次 buff 不重复）

    Params: {0}=6（BG35_814 与 BG35_814_G 同值，data 核实）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        threshold = game.db.get(source.card_id).num(0)

        def maybe_gain(g):
            if getattr(source, "_scarlet_done", False):
                return
            if source.atk < threshold:
                return
            if not g.in_combat:
                source._scarlet_done = True
            g.run_actions(GainKeyword(source, GameTag.DIVINE_SHIELD))

        def on_buff(g, target=None, buff=None, **kw):
            if target is source:
                maybe_gain(g)

        game.events.register(Listener(
            event="buff_applied", owner=source, callback=on_buff))
        if source.atk >= threshold:
            maybe_gain(game)
        return None


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。"""
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BG36_333", JailbirdJuggernautScript)
    _add("BG36_333_G", JailbirdJuggernautScript)   # 金色: Golem ×2（is_golden）
    _add("BG23_009", LavaLurkerScript)
    _add("BG23_009_G", LavaLurkerScript)           # 金色 num(0)=2 自然体现
    _add("BG26_524", MalchezaarScript)
    _add("BG26_524_G", MalchezaarScript)           # 金色 num(0)=4 自然体现
    _add("BG36_508", CageyConjurerScript)
    _add("BG36_508_G", CageyConjurerScript)        # 金色 num(1)=4 自然体现
    _add("BG31_892", FandralsFortuneScript)        # 池法术无金色定义
    _add("BG28_698", GemConfiscationScript)        # 同上
    _add("BG36_344", HooktuskScript)
    _add("BG36_344_G", HooktuskScript)             # 金色 num=2/2 自然体现
    _add("BG33_825", ProudPrivateerScript)
    _add("BG33_825_G", ProudPrivateerScript)       # 金色 is_golden ×3
    _add("BG35_883", BalindaStonehearthScript)
    _add("BG35_883_G", BalindaStonehearthScript)   # 引擎金色 ×3
    _add("BG29_813", PersistentPoetScript)
    _add("BG29_813_G", PersistentPoetScript)       # 引擎金色 ×2
    _add("BG21_015", TarecgosaScript)
    _add("BG21_015_G", TarecgosaGoldenScript)      # double → PERSIST_DOUBLE
    _add("BG24_018", TortollanBlueShellScript)
    _add("BG24_018_G", TortollanBlueShellScript)   # 金色卖价 10（is_golden）
    _add("BG26_137", BreamCounterScript)
    _add("BG26_137_G", BreamCounterScript)         # 金色 12/12 自然体现
    _add("BG32_236", AureateLaureateScript)
    _add("BG32_236_G", AureateLaureateScript)      # 金色版同构（数据同 2/2）
    _add("BG35_814", ScarletSurvivorScript)
    _add("BG35_814_G", ScarletSurvivorScript)      # 阈值同 6（金色 6/6 即达）
    return registered
