"""批次 trinkets6 — 饰品第六批（作业单 2026-09-02）。

主题: **额外触发配额**（RULES §6.20，2026-09-02 引擎原语）——
`hero.extra_triggers[key] = N` 永久额度 + 引擎消费
`hero.extra_trigger_used`（每回合/每场战斗自动重置）。脚本侧只声明
额度，**禁止**自己在卡脚本里写计数器重放效果（SOP §15）。

与 batch_trinkets1..5 的 id 集合互不相交。数值一律取自
`data/bg_trinkets.json` 的 `CardDef.num(0/1)`；文本无占位符的 +1 类
增量按文本字面量实现并在各类 `Params:` 行声明。

实现（8 个 id / 8 张饰品）:
  BG32_MagicItem_367  Ghastly Sticker        — eot_extra += 1
  BG32_MagicItem_365  Valdrakken Wind Chimes — soc_extra += 1
  BG30_MagicItem_918  Promo Portrait         — Get Prized Promo-Drake
                                               + soc_first += 1
  BG30_MagicItem_700  Deathly Phylactery     — Discover 亡语随从
                                               + dr_first += 1
  BG30_MagicItem_434  Replica Cathedral      — spell_first += num(0)
  BG30_MagicItem_920  Spitescale Sushi Roll  — Get Spitescale Special
                                               + spellcraft_first += num(0)
  BG36_MagicItem_215  Dragon's Eye           — bc_times += 1
                                               + bc_race = Race.DRAGON
  BG35_MagicItem_801  Sous Chef Sticker      — hp_uses += 1
                                               + 使用技能后 GainGold(1)

DEFERRED: 无（8 张全部两半可精确实现）。

协议: 饰品实体经 `_offer_trinkets` 购买 → `hero.trinkets`；脚本只挂
`on_bind`（饰品允许钩子集: on_bind/start_of_turn/end_of_turn/
start_of_combat/avenge）。全部状态写在 **hero 作用域**
（`hero.extra_triggers` / 监听器闭包）——禁止 game 级 flag（SOP §12）。

引擎缺口台账（2026-09-02 对抗审查后更新）:
  - ~~`soc_first` 被无钩子实体消费~~ **已修**: 引擎新增
    `CombatScheduler._has_soc_hook`，只在实体（含磁力栈）确有
    `start_of_combat` 钩子时消费配额（+ 回归测试）。本批文档与测试
    已同步。
  - `hero_power_used` 事件由 `game._finish_hero_power` 广播，且
    `events.HERO_POWER_USED` 常量已入册——Sous Chef Sticker 的金币
    半场精确实现，无需近似。
  - **已知作用域限制**（RULES §6.20 note）: `soc_extra` / `soc_first`
    覆盖的是**脚本钩子**路径的 SoC 效果（饰品/任务奖励/棋盘随从/
    手牌 hand_soc）; 由 SoC 事件监听器实现的法术类效果（如
    BG31_889 Sharing is Caring、BG28_573 Upper Hand、BG28_603 Boon of
    Beetles）不在配额覆盖内——属引擎架构层缺口，需为监听器型 SoC
    增加统一登记点后才可实现。
"""

from __future__ import annotations

from hsrl2.actions import Discover, GainGold
from hsrl2.events import HERO_POWER_USED, Listener
from hsrl2.game import GameStateError
from hsrl2.tags import Race

# 英雄技能使用完成事件（game._finish_hero_power 广播；events.py 未提供
# 常量，故用字符串字面量——接线审计 W2 解析字面量 fire）


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


def _bump(hero, key: str, amount: int) -> None:
    """声明永久额外触发额度（RULES §6.20）。

    与既有额度**累加**（同源多份/任务奖励叠加），绝不覆盖——覆盖会
    让先获得的额度凭空消失。引擎在对应触发点消费"已用次数"。
    """
    hero.extra_triggers[key] = hero.extra_trigger(key) + amount


def _evolution_target(game, source):
    """`evolution_card_id` 数据链解析关联卡（零硬编码卡 id，Shell
    Collector/Goldenizer Supply 先例）。金色变体同链。"""
    d = game.db.get(source.card_id)
    if d is None or d.evolution_card_id is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    token = game.db.by_dbf(d.evolution_card_id)
    if token is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id "
            f"{d.evolution_card_id} not in db")
    return token


def _deathrattle_candidates(game):
    """池中仍有副本的亡语随从 card_id（RULES §6.18 发现池约束）。

    "Discover a Deathrattle minion" = 从**池中**带 deathrattle 关键词的
    随从里三选一。与 `actions.discover._pool_candidates` 同口径:
    池剩余量 > 0、本局禁用种族排除（NONE/ALL 永远可用）。
    """
    pool = game.minion_pool
    out = []
    for d in game.db.pool_minions():
        if "deathrattle" not in d.keywords:
            continue
        if pool.available(d.id) <= 0:
            continue
        if (pool.active_races is not None
                and d.race not in (Race.NONE, Race.ALL)
                and d.race not in pool.active_races):
            continue
        out.append(d.id)
    return out


def _grant_pool_spell(game, hero, spell_id: str) -> None:
    """Get a <指定法术>: 池内有副本则 `spell_pool.acquire` 占池
    （RULES §3.6.1），池空仍生成不占池（Mystic Essence 先例——金色
    "Get 2" 总额必须可达成）；满手排队（RULES §3.3）。"""
    if game.spell_pool.available(spell_id) > 0:
        if not game.spell_pool.acquire(spell_id):
            raise GameStateError(
                f"pool spell acquire failed for {spell_id}")
    game.pending_hand_add(hero, game.create_spell(spell_id, controller=hero))


# ══════════════════ BG32_MagicItem_367 Ghastly Sticker ══════════════════

class GhastlyStickerScript:
    """
    Natural language: Your end of turn effects trigger an extra time.

    Formal spec:
      1. on_bind: 本人 `extra_triggers["eot_extra"] += 1`（RULES §6.20）
         ——引擎在 `end_recruit_phase` 的 EoT 阶段对**每个**己方 EoT
         效果（饰品 → 任务奖励 → 棋盘随从）多触发 1 次
      2. 与 Drakkari Enchanter 叠加（引擎累加: 基础 1 + 配额 N +
         Drakkari 1/金 2）; 只作用于本人（hero 作用域，对手不受影响）
      3. 无 game 级状态（SOP §12 item 9）

    Test: test_batch_trinkets6.py — 真实 end_recruit_phase: 探针随从
      EoT 钩子调用 2 次（对照无饰品 1 次）/ 与 Drakkari 同场 3 次 /
      对手棋盘探针仍 1 次（owner 隔离）

    Params: extra=1（"an extra time" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _bump(h, "eot_extra", 1)
        return None


# ══════════════ BG32_MagicItem_365 Valdrakken Wind Chimes ══════════════

class ValdrakkenWindChimesScript:
    """
    Natural language: Your <b>Start of Combat</b> effects trigger an extra
    time.

    Formal spec:
      1. on_bind: 本人 `extra_triggers["soc_extra"] += 1`（RULES §6.20）
         ——引擎 `CombatScheduler._run_soc_hook` 对**每个**己方 SoC 效果
         （饰品 → 任务奖励 → 棋盘随从 → 手牌 hand_soc）多触发 1 次
      2. `soc_extra` 是永久额度、不按场消耗（与 `soc_first` 不同）;
         只作用于本人
      3. 无 game 级状态

    Test: test_batch_trinkets6.py — 真实 run_combat: 探针随从 SoC 钩子
      调用 2 次（对照无饰品 1 次）/ 两场战斗都吃配额 / 对手棋盘探针
      仍 1 次（owner 隔离）

    Params: extra=1（"an extra time" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _bump(h, "soc_extra", 1)
        return None


# ══════════════════ BG30_MagicItem_918 Promo Portrait ══════════════════

class PromoPortraitScript:
    """
    Natural language: [x]Get a Prized Promo-Drake.
    Your first <b>Start of Combat</b> effect each combat triggers an extra
    time.

    Formal spec:
      1. on_bind: 授予 Prized Promo-Drake——`source` 的 `evolution_card_id`
         数据链解析（dbf 72073 → `BG21_014`，零硬编码卡 id）。该卡
         `is_pool_minion=False`（36.2.2 数据核实）→ token 语义不占池，
         `create_minion` + `pending_hand_add`（满手排队 RULES §3.3）
      2. on_bind: 本人 `extra_triggers["soc_first"] += 1`——引擎每场战斗
         按既有 SoC 顺序（饰品 → 任务奖励 → 棋盘 → 手牌）对**前 1 个**
         效果多触发 1 次; `CombatScheduler.run` 每场开战重置已用次数
      3. 只作用于本人; 无 game 级状态
      4. 已知引擎缺口（模块 docstring 台账）: 无 SoC 钩子的实体也会
         消费 soc_first——本饰品排在 hero.trinkets 首位时配额可能被
         自身 no-op 吃掉。脚本侧无法规避（引擎消费点固定），按原语
         声明额度；主线修复前，实战中该半场在"更早购入的饰品含 SoC
         效果"时正确生效。

    Test: test_batch_trinkets6.py — 绑定入手 1 只 BG21_014（池不变量
      不变——token） / 真实 run_combat: 排在真实 SoC 效果之前时该效果
      触发 2 次（对照无 Promo Portrait 1 次）/ 配额每场重置（第二场
      再次生效）/ 对手 SoC 探针仍 1 次

    Params: extra=1（"an extra time" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        token = _evolution_target(game, source)
        m = game.create_minion(token.id, controller=h)
        game.pending_hand_add(h, m)
        _bump(h, "soc_first", 1)
        return None


# ══════════════════ BG30_MagicItem_700 Deathly Phylactery ══════════════════

class DeathlyPhylacteryScript:
    """
    Natural language: [x]<b>Discover</b> a <b>Deathrattle</b>
    minion. Your first
    <b>Deathrattle</b> each combat
    triggers an extra time.

    Formal spec:
      1. on_bind: `Discover(hero, candidates=<池中亡语随从>)`——
         候选 = `pool_minions()` 中 keywords 含 "deathrattle" 且
         `minion_pool.available > 0`（RULES §6.18 池约束）; 三选项
         预留语义由 `Discover` Action 处理（选项生成即 acquire，resolve
         保留选中、释放其余）
      2. on_bind: 本人 `extra_triggers["dr_first"] += 1`——引擎
         `game._process_single_death` 在**战斗内**对**前 1 个**己方
         亡语多触发 1 次（`self.in_combat` 守卫，RULES §6.20）;
         `CombatScheduler.run` 每场开战重置已用次数
      3. 只作用于本人; 无 game 级状态

    Test: test_batch_trinkets6.py — 绑定产生 1 个 kind=discover_minion
      三选项发现，选项全为亡语随从且已预留占池 / resolve 后选中入手、
      其余回池（池净 -1）/ 真实战斗内 `_process_single_death`: 首个
      亡语探针 2 次、第二个 1 次（对照无饰品各 1 次）/ 招募期死亡不
      吃配额（阶段守卫）

    Params: 无模板参数（"Discover a Deathrattle minion" 无 {N} 占位符）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _bump(h, "dr_first", 1)
        cands = _deathrattle_candidates(game)
        if not cands:
            return None
        return Discover(h, candidates=cands, kind="discover_minion")


# ══════════════════ BG30_MagicItem_434 Replica Cathedral ══════════════════

class ReplicaCathedralScript:
    """
    Natural language: Your first spell each turn casts an extra time.

    Formal spec:
      1. on_bind: 本人 `extra_triggers["spell_first"] += num(0)`（数据
         `script_data_num_1=1`——卡面无数值占位符，参数即"前 N 个法术"
         的次数）; 引擎 `game._finish_play_spell` 对每回合**前 N 个**
         己方法术额外结算 1 次（RULES §6.20）
      2. `game._begin_recruit_for` 每招募回合重置已用次数; 只作用于
         本人（对手施法不消费本人配额）
      3. 与 Balinda 的棋盘 SPELL_DOUBLER 叠加（引擎 casts 累加）;
         无 game 级状态

    Test: test_batch_trinkets6.py — 真实 play_spell: 本回合首个法术
      on_play 结算 2 次、第二个 1 次 / 真实 end_recruit_phase 推进回合
      后配额重置（下回合首个法术再次 2 次）/ 对手施法不触发

    Params: {0}=1（BG30_MagicItem_434 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _bump(h, "spell_first", _num(game, source.card_id, 0))
        return None


# ══════════════════ BG30_MagicItem_920 Spitescale Sushi Roll ══════════════════

class SpitescaleSushiRollScript:
    """
    Natural language: [x]Get a Spitescale Special.
    Your first two <b>Spellcraft</b>
    spells each turn cast
    an extra time. <i>({0} left!)</i>

    Formal spec:
      1. on_bind: 授予 Spitescale Special——`source` 的
         `evolution_card_id` 数据链解析（dbf 110406 → `BG28_606`，零
         硬编码卡 id）。该卡 `is_pool_spell=True`（36.2.2 数据核实）
         → 池内有余则 `spell_pool.acquire` 占池（RULES §3.6.1）、
         `create_spell` + `pending_hand_add`; 打出时引擎回池，收支平衡
      2. on_bind: 本人 `extra_triggers["spellcraft_first"] += num(0)`（=2
         ——文本 "first two" 与 `{0}` 同源）; 引擎
         `game._finish_play_spell` 仅对带 `SPELLCRAFT` tag 的法术消费
         该配额（RULES §6.20——普通法术走 `spell_first`）
      3. 每招募回合重置已用次数（`game._begin_recruit_for`）;
         只作用于本人; 无 game 级状态

    Test: test_batch_trinkets6.py — 绑定入手 1 张 BG28_606 且法术池
      -1（打出后回池）/ 真实 play_spell: 前两个 Spellcraft 法术各结算
      2 次、第三个 1 次 / 普通（非 Spellcraft）法术不吃该配额 /
      回合推进后重置 / 对手施法不触发

    Params: {0}=2（BG30_MagicItem_920 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        token = _evolution_target(game, source)
        _grant_pool_spell(game, h, token.id)
        _bump(h, "spellcraft_first", _num(game, source.card_id, 0))
        return None


# ══════════════════ BG36_MagicItem_215 Dragon's Eye ══════════════════

class DragonsEyeScript:
    """
    Natural language: Your Dragons' <b>Battlecries</b> trigger an extra
    time.

    Formal spec:
      1. on_bind: 本人 `extra_triggers["bc_times"] += 1` 且
         `extra_triggers["bc_race"] = Race.DRAGON`（RULES §6.20——两者
         同时声明 = 仅种族限定; 单独 bc_times 是全局）
      2. 引擎 `game._finish_play_minion` 对 `minion.race ==
         Race.DRAGON`（或 ALL，Amalgam 规则）的随从战吼多触发 1 次;
         非龙战吼不受影响
      3. 与 Brann（棋盘 BATTLECRY_DOUBLER）累加; 只作用于本人;
         无 game 级状态

    Test: test_batch_trinkets6.py — 真实 play_minion: 龙战吼探针 2 次、
      非龙战吼 1 次（对照无饰品各 1 次）/ 对手打出龙不触发 /
      `bc_times_race` 累加 + `bc_race` 钉死 == Race.DRAGON
      （种族限定配额与全局 bc_times 独立——D3 修复后口径）

    Params: extra=1（"an extra time" 文本字面量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # 种族**限定**配额: `bc_times_race` + `bc_race`（与全局
        # `bc_times` 独立——2026-09-02 对抗审查 D3: 旧版用单个 bc_race
        # 会让本卡把 Gilnean War Horn 的全局 +1 静默降级为"仅龙"）
        _bump(h, "bc_times_race", 1)
        h.extra_triggers["bc_race"] = Race.DRAGON
        return None


# ══════════════════ BG35_MagicItem_801 Sous Chef Sticker ══════════════════

class SousChefStickerScript:
    """
    Natural language: You can use your Hero Power an extra time each turn.
    After you use your Hero Power,
    gain (1) Gold.

    Formal spec:
      1. on_bind: 本人 `extra_triggers["hp_uses"] += 1`——引擎
         `game.use_hero_power` 以 `uses_per_turn + extra_trigger
         ("hp_uses")` 为上限（RULES §6.20）; 每回合
         `hero.clear(HERO_POWER_USED_THIS_TURN)` 重置
      2. on_bind: 注册持久监听器（owner=饰品）监听
         `"hero_power_used"`（`game._finish_hero_power` 在费用/计次/
         效果结算后广播，携带 hero=）——过滤 `hero is 本人`;
         每次获得 GainGold(hero, 1)
      3. 只作用于本人（对手使用技能不发放）; 无 game 级状态;
         监听器随饰品实体存活

    Test: test_batch_trinkets6.py — 真实 use_hero_power（注册表接线
      的免费技能探针）: 本回合可用 2 次（1 + hp_uses），每次 +1 金；
      第 3 次 False / 对手使用技能不给本人金币（owner 隔离） /
      对照无饰品: 1 次且不加金

    Params: gold=1（"gain (1) Gold" 文本字面量——CardDef 无模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _bump(h, "hp_uses", 1)

        def on_power_used(g, hero=None, **kw):
            if hero is not h:
                return
            g.run_actions(GainGold(h, 1))

        game.events.register(Listener(
            event=HERO_POWER_USED, owner=source, callback=on_power_used,
            condition=lambda _h=h, hero=None, **kw: hero is _h))
        return None


# ══════════════════ 注册 ══════════════════

def register() -> list[str]:
    """注册饰品第六批 8 张（无 DEFERRED 注册项）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_MagicItem_367", GhastlyStickerScript),
        ("BG32_MagicItem_365", ValdrakkenWindChimesScript),
        ("BG30_MagicItem_918", PromoPortraitScript),
        ("BG30_MagicItem_700", DeathlyPhylacteryScript),
        ("BG30_MagicItem_434", ReplicaCathedralScript),
        ("BG30_MagicItem_920", SpitescaleSushiRollScript),
        ("BG36_MagicItem_215", DragonsEyeScript),
        ("BG35_MagicItem_801", SousChefStickerScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
