"""批次 trinkets21 — 饰品第二十一批（作业单 2026-09-12）: batch_trinkets14
台账中两张 DEFERRED 的"引擎原语落地后"解冻复核。

与 batch_trinkets1..18 的 id 集合互不相交（2 张均为
`CardDB.trinket_offer_pool()` 成员——运行核验; 无 `t`/`t2` 升级变体）。
数值一律 `CardDef.num()`；随机一律 `game.rng`；全部状态写在
hero 作用域 / source 实体 / 只读候选（无 game 级 flag，SOP §12 item 9）。

实现 2 张（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG32_MagicItem_286 Lavish Cape — 每个不同友方随从类型各施放 1 个随机
      酒馆法术; on_bind 首次结算 + 每回合 `start_of_turn` 重复。
      施放入口 `game.cast_spell_effect`（RULES §7.4.7b）——不经手牌/
      不计费/不动法术池/不广播手牌事件; 候选为**只读**池法术枚举
      （`SpellPool.draw_tavern` 会真实抽池，禁止）。定向法术随机取目标、
      无合法目标/无候选 → 该次落空且不消耗任何其它资源。

  BG32_MagicItem_416 War Drum — "One **Battlecry** each turn triggers
      **two** extra times. _({0} left!)_"（36.2.2 数据权威文本;
      num(0)=1, num(1)=2）。on_bind + 每回合 `start_of_turn` 覆写式声明
      两维额外触发配额: `hero.extra_triggers["bc_first"] = num(0)`
      （每回合前 N 个战吼）+ `["bc_first_times"] = num(1)`（每个额外
      触发 M 次）→ 每回合首个战吼共结算 1+2=3 次, 同回合第二个恢复
      1 次（RULES §6.20 `bc_first` / `bc_first_times`）。
      **数据核查订正**: 作业单/RULES §6.20/兄弟批次模块 docstring 引用
      的 "Your first {0} Battlecries each turn trigger an extra time"
      并非本卡文本（见下方跨文件台账）。**禁止**改用 `bc_times`
      （永久全量, 会覆盖 Gilnean War Horn 同 key 额度）。

本批无 DEFERRED —— 两张均经运行探针确认原语足够精确实现。

跨文件台账（本批不改兄弟文件; 建议主线按下表同步）
═══════════════════════════════════════════════════════════════════════
  1. `hsrl2/scripts/batches/batch_trinkets14.py:99-109`
     （BG32_MagicItem_286 模块台账）: "剩余阻塞"（只读候选 + 不同 race
     计数 + `cast_spell_effect`）已由本批消除 → 建议标注
     "已解锁（batch_trinkets21 注册）"。
  2. `hsrl2/scripts/batches/batch_trinkets14.py:130-135`
     （BG32_MagicItem_416 模块台账）: `bc_first` 已扩为两维
     （`bc_first` + `bc_first_times`）→ 建议标注
     "已解锁（batch_trinkets21 注册）"并订正引文为真实文本。
  3. `hsrl2/scripts/batches/batch_trinkets14.py:1121-1149`
     （`WarDrumScript` 类 docstring）: 同上——Dependency 第 1/3/4 条的
     文本与"bc_first 只有单维"的结论均已过时, 建议整段改为
     "已解锁（batch_trinkets21）"。
  4. `docs/BATTLEGROUNDS_RULES.md:561`（§6.20 `bc_first` 行）:
     引文 "Your first N Battlecries each turn trigger an extra time"
     非本卡文本, 建议订正为 "One Battlecry each turn triggers two extra
     times"（N=num(0) 个战吼, 每个额外触发 M=num(1) 次）, 并补
     `bc_first_times` 为独立 key。
  5. `docs/agents/ENGINE_BACKLOG.md:15`（`bc_first` 条目）: 卡 id 写作
     `BG30_MagicItem_416`（实际 `BG32_MagicItem_416`）, 且缺口已闭环;
     建议订正 id 并标注已实现。
  6. 数据侧（非本批范围, 供参考）: wiki.gg/Battlegrounds/Lavish_Cape
     记录 36.2.2 (2026-08-18) 已把 `BG32_MagicItem_286` 移出饰品池
     （"currently not available in games"），但基线 `data/bg_trinkets.json`
     仍将其列入 `trinket_offer_pool()`——生成器缺"可用性"字段（Solo
     商店可能提供已下架饰品）。脚本侧不受影响（只在实际授予时生效）。
  7. `docs/BATTLEGROUNDS_RULES.md` §7.4.7b 的"效果施法不广播
     `tavern_spell_cast`"裁定与官方 bugfix（wiki.gg/Battlegrounds/
     Lavish_Cape: 2025-05-02 "Lavish Cape now correctly works with
     Fire-forged Evoker"）**冲突**——即效果施放**应当**计入
     "After you cast a Tavern spell"。该裁定由主线持有（影响全部效果
     施法卡: Lavish Cape / Cagey Conjurer / Runic Arcanist 等），本批
     按现行裁定实现并在 `LavishCapeScript` docstring spec 8 记档，
     供主线复核后再统一改引擎（脚本侧无需改动）。

接线审计读取点（W1/W2/W3 核对）: 饰品仅分发 `on_bind` /
`start_of_turn`（W1 白名单）; 本批**不注册**任何 Listener（无死监听
风险）; 无 `game._x` 私有标记写入——War Drum 写的是引擎公开消费的
`hero.extra_triggers`（消费点 `game.py::_finish_play_minion`,
RULES §6.20）。`cast_spell_effect` 为公开引擎入口（RULES §7.4.7b）。
"""

from __future__ import annotations

from typing import List

from hsrl2.game import GameStateError
from hsrl2.minion import Minion

# 本批卡 id（CardDB 按名核实，SOP §11 教训 5——禁止凭记忆写 id）
LAVISH_CAPE = "BG32_MagicItem_286"      # Lavish Cape（Greater）
WAR_DRUM = "BG32_MagicItem_416"         # War Drum（Lesser）

# 额外触发配额 key（RULES §6.20）
_BC_FIRST = "bc_first"                  # 每回合前 N 个战吼
_BC_FIRST_TIMES = "bc_first_times"      # 每个额外触发 M 次（缺省 1）

# rng.choice 审计标签（全仓约定: 每次随机带可读 label）
_CAPE_LABEL = "lavish_cape_spell"


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _num(game, card_id: str, index: int) -> int:
    """CardDef 模板参数（缺失 → fail-loud，SOP §3）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _distinct_minion_types(game, hero) -> int:
    """本人棋盘**存活**随从的不同 minion type 数（"each different
    friendly minion type"）。

    裁定（SOP §6b 第 1 步 + 仓内同文本先例）:
      - 去重键 = 实体当前 `race` tag（单值）;
      - `Race.NONE`（无类型，如 Patient Scout）**计入**为一种;
      - `Race.ALL`（Amalgam，如 Motley Phalanx）计入为**一种**
        （一只随从只有一个 race tag，不为每个类型各算一次）。
    依据: 同一文本 "for each different friendly minion type" 的
    `BG34_272` Menagerie Tableware（`batch_spells_final.py`）已裁定
    "NONE 算一种、ALL 算一种"，并把 v1 的 "排除 NONE/ALL" 明确记为
    缺陷不沿用。本批沿用该口径并在测试中钉死两种边界。
    空棋盘 → 0（不施放）。只读——不修改任何实体。
    """
    living = _living(hero)
    if not living:
        return 0
    return len({m.race for m in living})


def _tavern_spell_candidates(game, hero) -> List[str]:
    """**只读**随机酒馆法术候选（严格不动法术池）。

    tier 口径: `CardDef.tech_level <= hero.tavern_tier`（全仓统一的
    "a random Tavern spell" 语义——Holli'dae / Mystic Essence /
    `SpellPool.draw_tavern` / Yogg 修复后口径; 2026-09-02 裁定），经
    `Game.tavern_spell_candidates(pool_aware=False)` 施加**存在档
    白名单**（异变 101/102 非存在档法术不可达）。
    **不使用** `SpellPool.draw_tavern`（会真实抽池）——效果施法路径下
    "施放即回池"净变化为 0（RULES §7.4.7b），故候选不按池余量过滤、
    也不 acquire/release（无池记账需要回滚）。
    候选为空（酒馆等级过低）→ 调用方落空。
    """
    return game.tavern_spell_candidates(min_tier=1,
                                        max_tier=hero.tavern_tier,
                                        pool_aware=False)


# ══════════════ BG32_MagicItem_286 Lavish Cape ══════════════


class LavishCapeScript:
    """
    Natural language: Cast a random Tavern spell for each different
    friendly minion type. At the start of each turn, repeat this.

    Formal spec:
      1. 触发点（"At the start of each turn, repeat this"）:
         `on_bind` 结算一次（获得饰品即"this"发生——同族先例
         `BG32_MagicItem_950` Gritty Portrait / `BG32_MagicItem_951`
         Gold Pendant 的 on_bind + start_of_turn 双点模型，
         batch_trinkets16），此后每个招募阶段开始由
         `start_of_turn` 钩子重复（引擎 `_begin_recruit_for` 对
         `hero.trinkets` 逐张分发）
      2. 次数 = 本人棋盘存活随从的**不同 race** 数
         （`_distinct_minion_types`）; 空棋盘 → 0 次（落空）
      3. 每次施放: 候选 = `_tavern_spell_candidates`（只读池法术枚举,
         `tech_level <= hero.tavern_tier`）中 `game.rng.choice` 独立抽取
         → `game.cast_spell_effect(hero, card_id)`（RULES §7.4.7b
         效果施法统一入口: 不经手牌/不计费/不动法术池/不广播手牌事件;
         定向法术从 `target_candidates`（未声明则本人存活随从）随机取
         目标, 无合法目标 → 返回 False 落空不抛错）。每次抽取相互独立
         ——同一法术可在同一次结算内被重复施放（无 "different" 措辞）
      4. 逐次独立结算: 某次因无候选/无合法目标落空（返回 False）
         → 不崩溃、不消耗金币/手牌/池, 继续剩余次数
      5. 资源不变量: 不扣金币、不入手牌、不动法术池/随从池
      6. 只作用于本人棋盘（race 计数与施放增益目标均为本人）;
         owner 隔离由 `source.controller` 保证
      7. 副本条款（RULES §7.4.3）: 两份副本各自 `on_bind` 各结算一次
         （实例无私有状态, 不做跨副本去重）
      8. 施放**事件语义**（引擎级裁定, RULES §7.4.7b）: `cast_spell_effect`
         不广播 `tavern_spell_cast`、不计 `TAVERN_SPELLS_CAST_*` → 官方
         bugfix（wiki.gg/Battlegrounds/Lavish_Cape: 2025-05-02 "Lavish
         Cape now correctly works with Fire-forged Evoker"）记载的
         "效果施放应触发 'After you cast a Tavern spell'"交互在引擎侧
         **未建模**（同 `BG36_245` Runic Arcanist 先例, batch_soc 明载）。
         本批按现行引擎裁定实现; 该交互作为主线台账项上报（见报告 ⑤），
         不属本饰品可单独修补的范围（一条引擎裁定影响全部效果施法卡）。

    Test: test_batch_trinkets21.py — 3 种类型 → 3 次施放且候选全为
      tier ≤ 酒馆等级的池法术 / 同族 3 只 → 1 次 / NONE 两只 → 1 次、
      NONE+野兽 → 2 次 / Amalgam 一只 → 1 次、Amalgam+野兽 → 2 次 /
      真实 `end_recruit_phase` 跨回合再施放 / 对手棋盘不变且对手类型
      不计入 / 酒馆等级 0（无候选）→ 0 次且金币/手牌/池不变 /
      空棋盘 0 次（正对照: 加一只 → 1 次）/ 池法术候选集只读（前后
      余量不变）/ 同 seed 序列可复现 / 两份副本各结算一次 /
      单候选定向法术无合法目标 → 落空且无副作用。

    Params: 无模板参数（CardDef num(0..3) 全 None——"for each
      different type" 是动态计数, 无数值占位符）
    """

    @staticmethod
    def _cast_for_each_type(game, source) -> int:
        """按不同类型数施放随机酒馆法术; 返回成功结算的次数。"""
        hero = source.controller
        if hero is None:
            return 0
        times = _distinct_minion_types(game, hero)
        if times <= 0:
            return 0
        cands = _tavern_spell_candidates(game, hero)
        if not cands:
            return 0
        cast = 0
        for _ in range(times):
            sid = game.rng.choice(cands, label=_CAPE_LABEL)
            if game.cast_spell_effect(hero, sid):
                cast += 1
        return cast

    @staticmethod
    def on_bind(source, game, ctx):
        LavishCapeScript._cast_for_each_type(game, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        LavishCapeScript._cast_for_each_type(game, source)
        return None


# ══════════════ BG32_MagicItem_416 War Drum ══════════════


class WarDrumScript:
    """
    Natural language: [x]One <b>Battlecry</b> each turn
    triggers two extra times.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind 与每回合 `start_of_turn` 均**覆写式**写入本人（owner
         隔离: `source.controller`）的两维额外触发配额:
           `hero.extra_triggers["bc_first"] = num(0)`（=1: 每回合前 N 个
             战吼享受额度）
           `hero.extra_triggers["bc_first_times"] = num(1)`（=2: 每个
             命中战吼**额外触发** M 次 → 共 1+2=3 次结算）
         引擎消费点 `game.py::_finish_play_minion`: 每个战吼结算时若
         `consume_extra_trigger("bc_first")` 成功则 `times +=
         max(1, extra_trigger("bc_first_times") or 1)`（RULES §6.20）
      2. "each turn" 语义: 引擎 `_begin_recruit_for` 每回合重置
         `extra_trigger_used["bc_first"]`（额度本身由本卡在
         `start_of_turn` 覆写, 不依赖引擎自重置额度）→ 每回合**首个**
         战吼 3 次结算, 同回合第二个恢复 1 次
      3. 与 `bc_times`（永久全量, Gilnean War Horn / Turbulent Tombs
         等来源）**独立叠加**, 互不覆盖: 引擎按两个 key 分别累加
         `times = 1 + bc_times + (bc_first 命中 ? bc_first_times : 0)`;
         本卡只写 `bc_first` / `bc_first_times` 两个 key, 从不触碰
         `bc_times`（RULES §6.20 / SOP §15 明令）
      4. 数值: num(0)=1（"One Battlecry" / `{0} left!` 显示位）,
         num(1)=2（"two extra times"）——缺数据 fail-loud, 不硬编码

    Test: test_batch_trinkets21.py — 绑定后两 key == CardDef num /
      每回合首个战吼 3 次结算（计数探针）/ 同回合第二个仅 1 次 /
      真实 `_begin_recruit_for` 换回合后首个又是 3 次 / 与 `bc_times`
      叠加为 1+bc_times+M 且 `bc_times` 值未被覆盖 / 无饰品对照仅 1 次 /
      start_of_turn 覆写式恢复被外部改写的额度 / 对手配额不受影响。

    Params: {0}=num(0)=1 {1}=num(1)=2（BG32_MagicItem_416）
    """

    @staticmethod
    def _declare(source, game) -> bool:
        """覆写式声明两维额度; 返回是否声明成功。"""
        hero = source.controller
        if hero is None:
            return False
        n = _num(game, source.card_id, 0)
        m = _num(game, source.card_id, 1)
        hero.extra_triggers[_BC_FIRST] = n
        hero.extra_triggers[_BC_FIRST_TIMES] = m
        return True

    @staticmethod
    def on_bind(source, game, ctx):
        WarDrumScript._declare(source, game)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        WarDrumScript._declare(source, game)
        return None


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册本批 2 张 CORRECT 饰品。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        (LAVISH_CAPE, LavishCapeScript),
        (WAR_DRUM, WarDrumScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
