"""批次 unlock_final — "新引擎原语解锁"终批（作业单 2026-09-15，13 张）。

台账来源: 派发作业单给定的 13 个 id。13/13 在 `CardDB` 存在、
13/13 在 `CardDB.trinket_offer_pool()` 中（运行核验——商店可提供成员，
唯一例外见下），且在本批之前 13/13 全部不在 `REGISTRY`（与既有
batch_trinkets1..29 注册集合互不相交）。

数值一律 `CardDef.num(i)`（缺失 → fail-loud，禁止硬编码；文本无占位符
的字面量按 SOP §3 在各类 `Params:` 行显式声明）；关联卡一律走数据链
`CardDef.evolution_card_id` → `CardDB.by_dbf`（RULES §7.4.6）；随机一律
`game.rng`（本批仅 902 使用，经全仓统一口径的池感知入口）；状态写在
hero 级 tag / source 实体属性（无 game 级 flag——SOP §12 item 9）。

**新引擎原语逐条核对（2026-09-02，RULES §7.4.10b/§7.4.13）**
═══════════════════════════════════════════════════════════════════════
  | 原语（生产点） | 本批消费卡 | 核验结论 |
  |----------------|-----------|---------|
  | `Game.add_card_aura(source, card_ids, atk, health)`（`ds.py` §7.4.10b; `Entity._aura_atk/_aura_health` 任意区域读取） | 216 | 增量式 + 金色按 `TRIPLE_BASE_CARD_ID` 回落 → 家族计数正确 |
  | `last_minion_died(hero=)` + `hero._combat_dead_snaps`（`game.py::_fire_last_minion_died` / `_process_death_inner`） | 907 / 732 | 每场每英雄一次、需本场确有死亡 → 两条文本精确可表达 |
  | `refresh_tavern(copies_of_warband=True)`（`game.py` L434） | 930 | 白板副本零池操作 + `add_tavern_entity` 持久 Buff |
  | `Game.trigger_friendly_rallies(hero, ctx=None)`（`game.py` L2512） | 214 | EoT 空 ctx; Rally 脚本经 `_rally_target` 自取（None 安全） |
  | hero 级 `CHOOSE_BOTH`（`game.py` L938/L1293 双路径） | 308 | 随从与法术两条 Choose One 路径均已读 |
  | `minion_consumed` 载荷 `from_tavern=/consumer=/stats_*`（`actions/consume.py` L136） | 902 | `from_tavern` + 受害者控制者即可钉死"你的酒馆" |
  | `minion_consumed` 载荷 `consumer=`（同） | 156 | **不足以精确表达**——见 DEFERRED 台账 |
  | `BLOOD_GEM_BONUS_HEALTH`（`actions/bloodgem.py::_gem_values`/`ImproveBloodGems`） | 433 | hero 级读取点，与 Vinespeaker 的 Attack 出口同源可镜像 |
  | `hero._tavern_cost_rules` / `_tavern_extra_keyword`（`game.py` L479/L630） | 743 / 755 | 条件报价与关键词展示位读取点；source 有效性检查就绪 |
  | `refresh_tavern(keywords=)`（`game.py` L479; `MinionPool.candidates`） | 755 | `CardDef.keywords` 字符串域（`"battlecry"`/`"magnetic"`） |
  | `GameTag.TRIPLE_THRESHOLD`（`check_for_triple` L1127） | 439 | **hero 级全域单值**，无 per-race 口径 → 见 DEFERRED |
  | `CardDef.num(0..4)` | 711 | 数值可读但 "improve this" 的**档位递增**无数据字段 → 见 DEFERRED |

**CORRECT 11 项（10 饰品 + 1 Spellcraft token）**
═══════════════════════════════════════════════════════════════════════
  BG36_MagicItem_216 Eternal Portrait (Greater, school=12) —
      on_bind: `grant_card_copy_to_hand(hero, 金色 Eternal Knight def,
      golden=True)`（数据链 `evolution_card_id=95262` → `BG25_008_G`）;
      注册 `death` 持久监听: 友方 Undead 死亡 → `add_card_aura(source,
      家族, atk=n0×k, health=n1×k)`（k=累计死亡数——增量式逐次 +n0/+n1，
      任意区域"wherever this is"）。家族 = 基础 id ∪ 金色 id。

  BG32_MagicItem_907 S'Thara Sticker (Greater, school=12) —
      注册 `last_minion_died` 持久监听: 本人棋盘清空时从
      `hero._combat_dead_snaps`（按死亡顺序）取**第一只 Demon**
      （race ∈ {DEMON, ALL}），`create_minion(card_id, golden=snapshot)`
      → `BASE_ATK/BASE_HEALTH = 快照 atk/max_health`（"with its maximum
      stats"）→ `game.summon`。无 Demon 死亡 → 落空。

  BG35_MagicItem_732 Soul Fermenter (Greater, school=12) —
      `start_of_combat`: 先对**最左 3 只**存活随从各自轻量快照
      （card_id/golden/atk/max_health/keywords，脚本自存于 source），
      再逐只 `game.destroy_minion`（统一 Destroy 入口，走完整死亡链）。
      注册 `last_minion_died` 持久监听: 本人棋盘清空时按快照顺序
      resummon（属性/关键词复原）。板不足 3 只 → 摧毁全部。

  BG35_MagicItem_930 Warband Whistle (Greater, school=12) —
      on_bind: `game.refresh_tavern(hero, free=True,
      copies_of_warband=True)`——"Gain a free Refresh that contains plain
      copies of minions in your warband"（白板副本零池操作，持久酒馆
      Buff 仍经 `add_tavern_entity` 生效）。

  BG36_MagicItem_214 Insurrectionist's Blade (Greater, school=12) —
      `end_of_turn`: `game.trigger_friendly_rallies(hero)`（空 ctx）。

  BG36_MagicItem_308 Trailblazer Sticker (Greater, school=12) —
      on_bind: hero 级 `CHOOSE_BOTH=True`（引擎随从 + 法术两条 Choose
      One 路径均读）。

  BG32_MagicItem_902 Statue of Hir'eek (Greater, school=12) —
      on_bind: 剩余计数 = `num(0)`（=2）; 注册 `minion_consumed` 持久
      监听: `from_tavern=True` 且受害者控制者 = 本人 → 计数 -1;
      归零 → 计数复位并 `_random_tavern_spell`（tier ≤ 酒馆等级，池感知，
      与 Holli'dae / Mystic Essence / `SpellPool.draw_tavern` 同口径）。

  BG35_MagicItem_743 Electrode Attractor (Greater, school=12) —
      on_bind: `hero._tavern_cost_rules.append((source, 磁力机械判定, 2))`
      + `hero._tavern_extra_keyword.append((source, {"magnetic"}, 1))`。

  BG35_MagicItem_755 Chillmere Mosaic (Greater, school=12) + token
      `BG35_MagicItem_755t`（Spellcraft 法术, `spellcraft_id=131310`）—
      饰品 on_bind `grant_spellcraft_spell`（引擎每回合再生成）;
      法术 on_play: `refresh_tavern(hero, free=True,
      keywords={"battlecry"})` → 对本次刷新产生的战吼随从注册
      `hero._tavern_cost_rules`（谓词 = 本次实体集合成员，价 1）→
      `turn_end` 清除该规则（source = `spellcraft_source_uuid` 反查到的
      饰品，规则随回合结束失效）。

  BG35_MagicItem_433 Vinespeaker Portrait (Greater, school=12) —
      on_bind: `grant_card_copy_to_hand`（数据链 130157 → `BG35_437`，
      非池 T5）+ 注册 `death` 持久监听: 友方**带亡语**随从死亡（与
      Vinespeaker 本体脚本同条件 `_has_deathrattle`）→ 对本人棋盘上每只
      Vinespeaker 执行 `ImproveBloodGems(hero, 0, 该实体 num(0))`
      （"also improve the **Health**"，增量 = 该 Vinespeaker 的 Attack
      改进值）。

**DEFERRED 1 张（不注册）+ 已迁出 2 张（156/439 由 `batch_misc_final`
注册，2026-09-02：`minion_triggered` 与 `hero.triple_threshold_race`
原语落地后其阻塞解除；下两条保留为历史台账）（Status / Dependency /
Implementation path
逐张见各类 docstring，禁止第三态——SOP §6b）**
═══════════════════════════════════════════════════════════════════════
  - [已迁出] BG35_MagicItem_156 Flaming Portrait — 原阻塞:
    `minion_consumed(consumer=)`
    **无法区分"Flaming Enforcer 自身 EoT 触发"与"被别的卡驱动吞噬"**:
    已注册的 `BG28_607` Corrupted Cupcakes（"Choose a friendly Demon.
    It consumes 3 random minions in the Tavern"）与 `BG36_503`
    Soulkeeping Jailer（"Your Demons each consume a random minion"）
    均可选中 Flaming Enforcer → 按 `consumer=` 镜像会**过触发**
    （ENGINE_BACKLOG B2-15 仍为未完成项）。需
    `minion_triggered(hook=, source=, value=)` 观察点。

  - [已迁出] BG30_MagicItem_439 Designer Eyepatch — 原阻塞:
    `TRIPLE_THRESHOLD` 是 hero 级
    **全域单值**（`game.py::check_for_triple` L1127），文本是 **Pirate
    限定**（数据 `subset_pirate=1`）。写入 2 会让所有随从 2 份成金 =
    过度适用。需 per-race 阈值读取点。

  - BG30_MagicItem_711 Marine Signet — "and improve this" 的**档位递增**
    无数据字段、无官方权威（wiki 页无 Notes；该卡 `triple_upgrade_id`
    为空，无升级变体可解析）；"({0} left!)" 的滚动计数本身可实现，但
    "improve this" 无法兑现 → 整卡不可 CORRECT。

关联卡台账（RULES §7.4.6——"Get a X" 交付正确即 CORRECT；被交付卡自身
脚本未迁移只登记、不阻塞，除非本卡效果**依赖**其行为）
═══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（`evolution_card_id` → `db.by_dbf`） | 脚本状态 |
  |------|--------------------------------------------|-----------|
  | BG36_MagicItem_216 | 95262 → `BG25_008_G` Eternal Knight（金色独立定义）| 已注册 |
  | BG35_MagicItem_433 | 130157 → `BG35_437` Vinespeaker（非池 T5）| 已注册（payload 批）|
  | BG35_MagicItem_156 | 126924 → `BG34_500` Flaming Enforcer（池 T4）| 已注册（consume 批）|
  | 其余 10 张 | `evolution_card_id` 为空（36.2.2 逐条核实） | — |
  说明: 216 的 `evolution_card_id` 指向**金色**定义 → 交付走
  `grant_card_copy_to_hand(..., golden=True)`（池记账按基础定义 1 份，
  `GILDED_NOT_TRIPLED` 出售回 1 份）。

DEFERRED 守卫同步（只改他批测试的 DEFERRED 容器 / `len(...)` 计数 +
紧邻注释，未改任何行为断言）: `test_batch_trinkets16/17/18/20/25/26`。
"""

from __future__ import annotations

from typing import List, Optional

from hsrl2.actions.bloodgem import ImproveBloodGems
from hsrl2.events import DEATH, MINION_CONSUMED, TURN_END, Listener
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

# `last_minion_died` 尚无 events.py 常量（引擎以字符串字面量广播——
# RULES §7.4.10b; 已作为引擎缺口登记，本批以模块常量自持避免魔法串漂移）
LAST_MINION_DIED = "last_minion_died"

_DEMON_RACES = (Race.DEMON, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)


# ══════════════════ 共用小工具 ══════════════════


def _hero(ctx):
    """on_bind 的 ctx 承载 hero（`grant_trinket` 协议）。"""
    return (ctx or {}).get("hero")


def _num(game, card_id: str, i: int) -> int:
    """模板参数唯一来源（缺失 → fail-loud，禁止默认值近似）。"""
    d = game.db.get(card_id)
    v = d.num(i) if d is not None else None
    if v is None:
        raise GameStateError(
            f"{card_id} missing template param num({i})")
    return v


def _dynamic_baseline(source) -> int:
    """官方 `TAG_SCRIPT_DATA_NUM_3` 注入基线（F-03 通道；无注入 → 0）。

    "After a friendly Undead dies, your Eternal Knights have +X/+Y this
    game" 的累计次数可由官方轨迹注入 NUM_3；视作回放窗口前已积累的
    基线，与回放窗口内引擎观测死亡数相加。默认 0 → 旧行为逐位不变。
    """
    game = getattr(source, "game", None)
    if game is None:
        return 0
    value = source.script_data_or_card(3)
    return int(value) if value else 0


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _has_deathrattle(m) -> bool:
    """挂有亡语的实体（关键词 tag 或脚本钩子）——与 `BG35_437`
    VinespeakerScript / `batch_payload_minions::_has_deathrattle` 同口径。"""
    return m.has(GameTag.DEATHRATTLE) or getattr(
        m.scripts, "deathrattle", None) is not None


def _in_family(m, family: frozenset) -> bool:
    """金色按 `TRIPLE_BASE_CARD_ID` 回落匹配（RULES §6.19）。"""
    cid = getattr(m, "card_id", None)
    bid = m.get(GameTag.TRIPLE_BASE_CARD_ID, None) or cid
    return cid in family or bid in family


def _related_and_base(game, card_id: str):
    """饰品关联卡定义与其基础定义（`evolution_card_id` 数据链）。"""
    rel = game.trinket_related_card(card_id)
    if rel is None:
        return None, None
    if rel.is_golden_def and rel.triple_base_id:
        base = game.db.by_dbf(rel.triple_base_id) or rel
    else:
        base = rel
    return rel, base


def _family_ids(game, base_def) -> frozenset:
    """卡家族 id 集合（基础 ∪ 金色独立定义——零硬编码卡 id）。"""
    ids = {base_def.id}
    golden = game.db.golden_version(base_def)
    if golden is not None:
        ids.add(golden.id)
    return frozenset(ids)


def _random_tavern_spell(game, hero, label: str) -> bool:
    """获得 1 张随机酒馆法术（池感知）。

    tier 口径: `tech_level <= hero.tavern_tier`（与 Holli'dae /
    Mystic Essence / `SpellPool.draw_tavern` 全仓统一，2026-09-02 裁定），
    并经 `Game.tavern_spell_candidates` 施加**存在档白名单**（异变
    101/102 非存在档法术不可达）。占池 → create_spell →
    `pending_hand_add`; 候选为空 → False（落空）。
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


def _alive_neighbors(m: Minion) -> List[Minion]:
    """m 在棋盘上的存活左右邻（zone_position ±1）。"""
    hero = getattr(m, "controller", None)
    if hero is None or m not in hero.board:
        return []
    pos = m.zone_position
    return [x for x in hero.board
            if x is not m and not x.dead
            and abs(x.zone_position - pos) == 1]


def _live_light_snapshot(m: Minion) -> dict:
    """轻量快照（禁止 deepcopy tags——RULES §7.4.10b 性能裁定）。

    属性口径 = `stats_without_aura()`（base + 附魔，**不含光环**）——
    `_summon_from_snapshot` 把快照值直接写为 BASE_ATK/HEALTH，光环由新
    实体在棋盘上实时重算; 记录 `m.atk`（含光环）会双计（2026-09-13
    对抗验证 MAJOR: S'Thara Sticker 907 / Soul Fermenter 732）。
    """
    _atk, _health = m.stats_without_aura()
    return {
        "card_id": m.card_id,
        "golden": m.is_golden,
        "atk": _atk,
        "max_health": _health,
        "keywords": tuple(t for t, v in m.tags.items() if v is True),
    }


def _summon_from_snapshot(game, hero, snap: dict) -> Optional[Minion]:
    """按轻量快照 resummon（属性作为基础属性，关键词复原）。"""
    m = game.create_minion(snap["card_id"], controller=hero,
                           golden=bool(snap["golden"]))
    if m is None:
        return None
    m.set(GameTag.BASE_ATK, snap["atk"])
    m.set(GameTag.BASE_HEALTH, snap["max_health"])
    for tag in snap["keywords"]:
        m.set(tag, True)
    if not game.summon(hero, m):
        return None
    return m


# ══════════════════ BG36_MagicItem_216 Eternal Portrait ══════════════════


class EternalPortraitScript:
    """
    Natural language: [x]Get a Golden Eternal Knight.
    After a friendly Undead dies,
    your Eternal Knights have
    +{0}/+{1} this game.

    Formal spec:
      1. on_bind: `game.trinket_related_card` 数据链（95262）→
         `BG25_008_G` 金色 Eternal Knight 独立定义 →
         `grant_card_copy_to_hand(hero, 金色 def, golden=True)`
         （占池 1 份基础副本 + `GILDED_NOT_TRIPLED` + 满手排队，
         RULES §7.4.6/§2.3）; 家族 = 基础 id ∪ 金色 id
      2. 注册持久 `death` 监听（owner=饰品 → 替换即失效）: 死者
         `controller is 本人` 且 `race ∈ {UNDEAD, ALL}`（RULES §8 全类型
         视为所有种族）→ 累计计数 k+1 并
         `game.add_card_aura(source, 家族, atk=num(0)×k, health=num(1)×k)`
         ——增量式接口按差值更新，故每次触发实际 +num(0)/+num(1)
      3. 光环作用于**任意区域**的家族实体（"wherever this is"：
         棋盘/手牌/酒馆——后续 `create_minion` 的家族实体经
         `_card_aura_active` 实时读取）; 招募期与战斗内死亡均计（"this
         game"）
      4. 无 Undead 死亡 → 不注册光环（零副作用）
      5. 官方 `TAG_SCRIPT_DATA_NUM_3` 注入（F-03 通道）: 累计
         `k = 回放窗口内观测死亡数 + 注入基线`；无注入 → 旧行为逐位
         不变（`script_data_or_card(3)` 回落 CardDef，本卡 NUM_3=None）。

    Test: test_batch_unlock_final.py — 绑定后手牌恰 1 张金色 Eternal
      Knight（GOLDEN + TRIPLE_BASE_CARD_ID + 基础池 -1）/ 真人
      `_process_single_death` 死 1 只友方 Undead → 场上 Eternal Knight
      +num(0)/+num(1) / 死 2 只 → 累计 +2×num(0)/+2×num(1) / 非 Undead
      死亡不计 / 对手 Undead 死亡不计 / 后入手的手牌 Eternal Knight 同享

    Params: {0}=4 {1}=2（36.2.2 基线）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        gd, base = _related_and_base(game, source.card_id)
        if gd is not None:
            game.grant_card_copy_to_hand(h, gd, golden=True)
        if base is None:
            return None
        family = _family_ids(game, base)
        n0 = _num(game, source.card_id, 0)
        n1 = _num(game, source.card_id, 1)
        source._eternal_family = family
        source._eternal_deaths = 0

        def on_death(g, minion=None, **kw):
            if minion is None:
                return
            hero = source.controller
            if hero is None or minion.controller is not hero:
                return
            if minion.race not in _UNDEAD_RACES:
                return
            source._eternal_deaths += 1
            # F-03 通道: 官方 NUM_3 注入基线 + 回放窗口内观测死亡数
            k = source._eternal_deaths + _dynamic_baseline(source)
            g.add_card_aura(source, source._eternal_family,
                            atk=n0 * k, health=n1 * k)

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        return None


# ══════════════════ BG32_MagicItem_907 S'Thara Sticker ══════════════════


class STharaStickerScript:
    """
    Natural language: [x]After your last minion dies
    each combat, summon your
    first Demon that died with
    its maximum stats.

    Formal spec:
      1. 注册持久 `last_minion_died` 监听（owner=饰品）——引擎在
         **本人棋盘不再有存活随从**且本场确有随从死亡时广播，每场
         战斗每英雄一次（RULES §7.4.10b）
      2. 载荷 `hero=` 必须 `is 本人`（owner 隔离）
      3. 候选 = `hero._combat_dead_snaps`（按**死亡顺序**的轻量快照）
         中**第一只** `race ∈ {DEMON, ALL}` 者; 无 → 落空
      4. `create_minion(snap.card_id, controller=hero, golden=snap.golden)`
         → `BASE_ATK/BASE_HEALTH = 快照 atk/max_health`（"with its
         **maximum stats**" = 死亡瞬间属性值）→ `game.summon`
         （满场由 `summon` 处理——空板触发本效果，故实际不为满场）
      5. 不复制关键词（文本只给"maximum stats"）

    Test: test_batch_unlock_final.py — 真实 `run_combat` 内（Demon 先死、
      最后一个随从死）召唤出该 Demon 且 atk/max_health == 死亡快照值 /
      先死的非 Demon 被跳过（取第一只 Demon）/ 无 Demon 死亡 → 不召唤 /
      对手棋盘清空不触发（owner 隔离）/ 招募期 `check_deaths` 不触发
      （`in_combat` 守卫）/ 同 seed 确定性

    Params: 无模板参数（属性 = 死亡快照运行时值）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        def on_last(g, hero=None, **kw):
            h = source.controller
            if h is None or hero is not h:
                return
            snaps = list(getattr(h, "_combat_dead_snaps", []) or [])
            first = next((s for s in snaps
                          if s.get("race") in _DEMON_RACES), None)
            if first is None:
                return
            _summon_from_snapshot(g, h, first)

        game.events.register(Listener(event=LAST_MINION_DIED,
                                      owner=source, callback=on_last))
        return None


# ══════════════════ BG35_MagicItem_732 Soul Fermenter ══════════════════


class SoulFermenterScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Destroy
    your 3 left-most minions.
    After your last minion dies,
    resummon them.

    Formal spec:
      1. `start_of_combat`: 目标 = 本人棋盘**最左 3 只**存活随从
         （板不足 3 只 → 全部）; 先逐只轻量快照（card_id/golden/atk/
         max_health/keywords）存于 source 实体（**禁止**死亡后
         `snapshot_state()`——RULES §7.4.10b 性能裁定），**再**逐只
         `game.destroy_minion(m, source=source)`（统一 Destroy 入口:
         无视圣盾/免疫、走完整死亡链 + `minion_destroyed` 广播）
      2. 注册持久 `last_minion_died` 监听: 载荷 `hero is 本人` 时按快照
         顺序 `_summon_from_snapshot` resummon（属性作为基础属性、
         关键词复原; 顺序 = 快照顺序）
      3. SoC 摧毁即令板空（如原板恰 3 只）→ 同一 SoC 内立即 resummon
         （死亡链在 `destroy_minion` 内结算后广播）; 若仍有存活随从则
         等其全部阵亡
      4. 快照在触发后清空（本场不重复 resummon）; 每场 SoC 重新快照
      5. 空板 → 无快照/无摧毁/不触发

    Test: test_batch_unlock_final.py — 真实 `run_combat` 内 SoC 摧毁最左
      3 只（第 4 只存活）且其全部阵亡后 resummon 3 只、属性/关键词复原 /
      板恰 3 只 → SoC 即摧毁并立即 resummon / 板 2 只 → 摧毁 2 只并
      resummon 2 只 / 空板无副作用 / 更左者优先（第 4 只不受影响）/
      对手棋盘不受影响（owner 隔离）/ 同 seed 确定性

    Params: 3（"your 3 left-most minions" 文本字面量——CardDef 无模板参数）
    """

    COUNT = 3

    @staticmethod
    def on_bind(source, game, ctx):
        def on_last(g, hero=None, **kw):
            h = source.controller
            if h is None or hero is not h:
                return
            snaps = list(getattr(source, "_ferment_snaps", []) or [])
            source._ferment_snaps = []
            for snap in snaps:
                _summon_from_snapshot(g, h, snap)

        game.events.register(Listener(event=LAST_MINION_DIED,
                                      owner=source, callback=on_last))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        targets = _living(hero)[:SoulFermenterScript.COUNT]
        source._ferment_snaps = [_live_light_snapshot(m) for m in targets]
        for m in targets:
            game.destroy_minion(m, source=source)
        return None


# ══════════════════ BG35_MagicItem_930 Warband Whistle ══════════════════


class WarbandWhistleScript:
    """
    Natural language: [x]Gain a free <b>Refresh</b> that
    contains plain copies of
    minions in your warband.

    Formal spec:
      1. on_bind（无时机关键词 → 获得即生效）:
         `game.refresh_tavern(hero, free=True, copies_of_warband=True)`
         —— 引擎入口（RULES §7.4.10b）: 旧馆内容回池（P1）、本次展示
         内容 = **本人棋盘每只存活随从的白板副本**（零池操作——副本
         非从池获取），仍经 `add_tavern_entity` 受持久酒馆 Buff 影响
      2. `free=True` → 不扣金币、不消耗 `FREE_REFRESH_REMAINING`
      3. 每次绑定恰触发一次（饰品 on_bind 一次）

    Test: test_batch_unlock_final.py — 绑定后酒馆随从 id 多重集 ==
      棋盘随从 id 多重集（金色随从按基础 id 出白板副本）/ 副本属性 ==
      `CardDef` 基础值（无 buff 携带）/ 金币不变 / 池剩余不因副本变化
      （零池操作，对照取走棋盘随从前的快照）/ 无随从棋盘 → 空馆 /
      对手酒馆不受影响（owner 隔离）/ 同 seed 确定性

    Params: 无模板参数（内容 = 运行时战团白板副本）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # `consume_free=False`: 本卡的"免费刷新"是引擎赠送，不得消耗玩家
        # 自有 `FREE_REFRESH_REMAINING`（2026-09-02 对抗验证 BUG-4）
        game.refresh_tavern(h, free=True, copies_of_warband=True,
                            consume_free=False)
        return None


# ══════════════════ BG36_MagicItem_214 Insurrectionist's Blade ══════════════════


class InsurrectionistsBladeScript:
    """
    Natural language: At the end of your turn, trigger all friendly
    <b>Rallies</b>.

    Formal spec:
      1. `end_of_turn`: `game.trigger_friendly_rallies(hero)`——对本人
         棋盘每只**真的会触发 Rally** 的存活随从（脚本钩子或磁力栈叠
         同钩子，`_has_rally_hook`）调用 `run_rally`（`rally_extra`
         配额同源），ctx 为空 dict（RULES §7.4.13——Rally 脚本经
         `_rally_target` 取 `ctx.get("target")`，EoT 无防守方 → None，
         脚本按落空处理，已逐脚本核验 None 安全）
      2. 不消耗攻击次数、不改动棋盘（"trigger" 不是"attack"）
      3. Drakkari / `eot_extra` 的 EoT 翻倍由引擎在调用本钩子外层
         处理（饰品在翻倍域内——RULES §6.20）

    Test: test_batch_unlock_final.py — EoT 触发全部己方 Rally 各一次
      （真实 `end_recruit_phase`）/ 无 Rally 随从 → 0 次且不抛错 /
      对手 Rally 不触发（owner 隔离）/ 磁力栈叠 Rally 同样计入 /
      `rally_extra` 配额使单只额外触发 / 同 seed 确定性

    Params: 无数值参数（触发次数 = 棋盘 Rally 实体数）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        game.trigger_friendly_rallies(hero, {})
        return None


# ══════════════════ BG36_MagicItem_308 Trailblazer Sticker ══════════════════


class TrailblazerStickerScript:
    """
    Natural language: Your <b>Choose One</b> cards have both effects
    combined.

    Formal spec:
      1. on_bind: hero 级 `GameTag.CHOOSE_BOTH=True`——引擎两处读取点:
         随从打出路径（`_run_play_effects`）与法术施放路径
         （`play_spell`）均读 hero 级 tag（RULES §7.4.13）
      2. 命中后跳过 `choose_one` PendingChoice，两条分支效果合并结算
      3. 光环式 hero tag（不逐实体改写）→ 之后获得的 Choose One 卡
         同样生效

    Test: test_batch_unlock_final.py — 绑定后打出 Choose One 随从/法术
      不再产生 `choose_one` PendingChoice 且两分支效果均生效 / 无饰品
      对照仍产生选择 / 对手 Choose One 仍走选择（owner 隔离）/
      绑定后**新获得**的 Choose One 卡同样生效 / 同 seed 确定性

    Params: 无模板参数（身份光环）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        h.set(GameTag.CHOOSE_BOTH, True)
        return None


# ══════════════════ BG32_MagicItem_902 Statue of Hir'eek ══════════════════


class StatueOfHireekScript:
    """
    Natural language: [x]After 2 minions in the
    Tavern are consumed, get
    a random Tavern spell.
    <i>({0} left!)</i>

    Formal spec:
      1. on_bind: 剩余计数 = `num(0)`（=2）存于 source 实体
         （"({0} left!)" 运行时滚动值——文本参数是**初值**）
      2. 注册持久 `minion_consumed` 监听: 载荷
         `from_tavern=True`（"in the Tavern" 唯一判据）且受害者
         `controller is 本人`（"**the** Tavern" = 本人酒馆，RULES
         §7.4.10b）→ 计数 -1
      3. 计数归零 → **复位为 num(0)** 并 `_random_tavern_spell`
         （池感知、`tech_level ≤ 酒馆等级`、占池、满手排队；RULES
         §6.18/§3.3）。触发已发生 → 计数照常复位（Jar o' Gems 同款
         滚动计数先例 `batch_trinkets12`）; 池空 → 本次落空但计数已复位
      4. 手牌/棋盘来源吞噬（`from_tavern=False`）不计; 对手酒馆吞噬不计
      5. 计数跨回合持久（文本无"this turn/each combat"限定）

    Test: test_batch_unlock_final.py — 真实 `ConsumeMinion` 吞噬馆内 2 只
      → 恰得 1 张酒馆法术（tier ≤ 酒馆等级）且计数复位为 num(0) /
      只吞 1 只 → 不得且剩 num(0)-1 / 棋盘来源吞噬（from_tavern=False）
      不计 / 对手酒馆吞噬不计（owner 隔离）/ 法术池耗尽 → 落空且不抛错 /
      满手 → 入等待队列 / 池占返配平（获得法术占池 1 份）/
      同 seed 确定性

    Params: {0}=2（触发所需吞噬数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        threshold = _num(game, source.card_id, 0)
        source._hireek_threshold = threshold
        source._hireek_left = threshold

        def on_consume(g, minion=None, from_tavern=False, **kw):
            hero = source.controller
            if hero is None or not from_tavern or minion is None:
                return
            if getattr(minion, "controller", None) is not hero:
                return
            source._hireek_left -= 1
            if source._hireek_left > 0:
                return
            source._hireek_left = source._hireek_threshold
            _random_tavern_spell(g, hero, "statue_of_hireek")

        game.events.register(Listener(event=MINION_CONSUMED, owner=source,
                                      callback=on_consume))
        return None


# ══════════════════ BG35_MagicItem_743 Electrode Attractor ══════════════════


class ElectrodeAttractorScript:
    """
    Natural language: [x]<b>Magnetic</b> Mechs cost (2).
    The Tavern offers an
    extra one whenever it is
    <b>Refreshed</b>.

    Formal spec:
      1. on_bind: `hero._tavern_cost_rules.append((source, pred, 2))`——
         `buy_from_tavern` 读取点（RULES §7.4.13）: `pred(entity)` =
         `entity` 是**磁力机械**（`MAGNETIC` tag 且 `race ∈ {MECH,
         ALL}`；RULES §8）; 命中取 `min(cost, 2)`; source 离场即失效
      2. `hero._tavern_extra_keyword.append((source, {"magnetic"}, 1))`——
         `refresh_tavern` 每次刷新（含 auto）额外抽 1 个**磁力**展示位
         （`MinionPool.candidates(keywords=)` 按 `CardDef.keywords`
         字符串域匹配）
      3. 两项均 hero 级（不得污染对手——SOP §12 item 9）

    Test: test_batch_unlock_final.py — 真实 `buy_from_tavern` 买磁力机械
      恰 2 金（对照同价的非磁力机械原价 3）/ 磁力非机械（若有）不折 /
      非磁力机械不折 / 真实 `refresh_tavern` 后馆内磁力实体数比无饰品
      对照恰多 1 / 对手酒馆与对手购买价不受影响（owner 隔离）/
      饰品移除后两项失效 / 同 seed 确定性

    Params: 2（"(2)" 文本字面量——CardDef 无模板参数）
    """

    COST = 2

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def pred(entity):
            race = getattr(entity, "race", None)
            return (entity.has(GameTag.MAGNETIC)
                    and race in (Race.MECH, Race.ALL))

        h._tavern_cost_rules.append(
            (source, pred, ElectrodeAttractorScript.COST))
        h._tavern_extra_keyword.append((source, {"magnetic"}, 1))
        return None


# ══════════════════ BG35_MagicItem_755 Chillmere Mosaic ══════════════════


class ChillmereMosaicScript:
    """
    Natural language: [x]<b>Spellcraft:</b> <b>Refresh</b> the
    Tavern with <b>Battlecry</b>
    minions. They cost (1).

    Formal spec:
      1. on_bind: `spellcraft.grant_spellcraft_spell(source, game)`
         （RULES §6.13 "获得法术塑造时立即获得第一张"）; 每回合再次生成
         由引擎 `spellcraft.generate_for_hero`（扫 `hero.trinkets`）负责
         ——脚本**不得**再写 `start_of_turn`（否则同回合双发）
      2. 实效由法术脚本 `ChillmereMosaicSpellScript`
         （`BG35_MagicItem_755t`，数据链 `spellcraft_id=131310`）完成

    Test: test_batch_unlock_final.py — 绑定后手牌恰 +1 张
      `BG35_MagicItem_755t` 且带 SPELLCRAFT tag / 真实
      `_begin_recruit_for` 下一回合再生成 1 张（每回合恰 1，不双发）/
      对手手牌不受影响 / 无饰品对照 0 张

    Params: 无模板参数（法术 id 经 `CardDef.spellcraft_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)
        return None


class ChillmereMosaicSpellScript:
    """
    Natural language: [x]<b>Refresh</b> the Tavern with
    <b>Battlecry</b> minions. They cost (1).

    Formal spec:
      1. on_play: `game.refresh_tavern(hero, free=True,
         keywords={"battlecry"})`——全部随从位取自**战吼**随从
         （`MinionPool.candidates(keywords=)` 按 `CardDef.keywords`）;
         法术自身即是"Refresh"的代价 → `free=True`（不扣金币）;
         旧馆内容回池（P1）、入馆经 `add_tavern_entity`（持久 Buff）
      2. 对本次刷新产生的**战吼随从**注册 `hero._tavern_cost_rules`
         条目 `(origin, pred, 1)`——谓词 = "实体 ∈ 本次产生的集合"
         （**只**折本次展示的随从，而非永久折所有战吼随从; 精确表达
         "They cost (1)" 的指代域）。`origin` = `spellcraft_source_uuid`
         反查到的饰品实体（source 有效性检查生效; 反查失败回落 None）
      3. 注册 `turn_end` 一次性监听（owner=法术）在回合结束清除该规则
         ——规则只在本次招募期有效（法术未使用则回合末被引擎丢弃，
         规则从不产生）
      4. 无战吼展示（池中无战吼随从）→ 仅刷新，不加规则

    Test: test_batch_unlock_final.py — 真实 `play_spell` 后馆内**全部**
      随从位均为战吼随从（对照无施法不变）/ 本次随从购买价恰 1 金 /
      **下一次**刷新的新随从按原价（规则不越界）/ 回合结束（真实
      `end_recruit_phase`）后规则清除 / 对手酒馆/购买价不受影响
      （owner 隔离）/ 无战吼池 → 不抛错 / 同 seed 确定性

    Params: 1（"They cost (1)" 文本字面量）; 法术 id 走 `spellcraft_id`
    """

    COST = 1

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        # 引擎赠送的刷新不消耗玩家自有免费次数（2026-09-02 BUG-4 口径）
        game.refresh_tavern(hero, free=True, keywords={"battlecry"},
                            consume_free=False)
        captured = [e for e in hero.tavern
                    if isinstance(e, Minion) and e.has(GameTag.BATTLECRY)]
        if not captured:
            return None
        origin = None
        uuid = getattr(source, "spellcraft_source_uuid", None)
        if uuid:
            for t in hero.trinkets:
                if getattr(t, "uuid", None) == uuid:
                    origin = t
                    break
        # 2026-09-02 对抗验证 BUG-1: 旧实现用 `id(entity)` 记录"本次刷新的
        # 战吼随从"→ 同回合再刷新时旧实体回池释放、CPython 复用地址，
        # 新抽随从白拿 1 费。改用**稳定身份 `uuid`**。
        entry = (origin,
                 (lambda e, _c=frozenset(x.uuid for x in captured):
                  getattr(e, "uuid", None) in _c),
                 ChillmereMosaicSpellScript.COST)
        hero._tavern_cost_rules.append(entry)

        def cleanup(g, turn=None, **kw):
            try:
                hero._tavern_cost_rules.remove(entry)
            except ValueError:
                pass

        game.events.register(Listener(event=TURN_END, owner=source,
                                      callback=cleanup, once=True))
        return None


# ══════════════════ BG35_MagicItem_433 Vinespeaker Portrait ══════════════════


class VinespeakerPortraitScript:
    """
    Natural language: [x]Get a Vinespeaker.
    Your Vinespeakers also
    improve the Health given
    by your <b>Blood Gems</b>.

    Formal spec:
      1. on_bind: `game.trinket_related_card` 数据链（130157）→
         `BG35_437`（非池 T5）→ `grant_card_copy_to_hand`（零池操作，
         RULES §7.4.6）; 家族 = 基础 id ∪ 金色 id（`BG35_437_G`）
      2. 注册持久 `death` 监听: 死者 `controller is 本人` 且
         `_has_deathrattle(minion)`——与 `BG35_437` VinespeakerScript
         的触发条件**逐字同构**（该条件即"Vinespeaker 触发"的充要条件，
         不存在其它可驱动 Vinespeaker 的路径）
      3. 对本人棋盘**每只** Vinespeaker（家族匹配、存活）执行
         `ImproveBloodGems(hero, 0, num(0) of 该实体 card_id)`——
         增量 = 该 Vinespeaker 的 Attack 改进值（基础 2 / 金色 4，
         由各自独立 CardDef 决定），写入 hero 级
         `BLOOD_GEM_BONUS_HEALTH`（对所有后续宝石路径统一生效）
      4. 无 Vinespeaker 在场 / 死者无亡语 → 无副作用

    Test: test_batch_unlock_final.py — 绑定后手牌恰 1 张 `BG35_437` /
      真实 `_process_single_death` 死 1 只友方亡语随从 →
      `BLOOD_GEM_BONUS_HEALTH` 增加该 Vinespeaker 的 num(0) 且随后
      `PlayBloodGems` 实际多给等量生命（**生产消费点**验证）/
      场上 2 只 Vinespeaker → 各计一次 / 金色 Vinespeaker 计 num(0)=4 /
      非亡语随从死亡不计 / 对手亡语随从死亡不计 / 棋盘无 Vinespeaker
      时死亡不计 / owner 隔离 / 同 seed 确定性

    Params: 无模板参数（增量 = 载荷 Vinespeaker 的 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        _, base = _related_and_base(game, source.card_id)
        if base is None:
            return None
        game.grant_card_copy_to_hand(h, base)
        family = _family_ids(game, base)

        def on_death(g, minion=None, **kw):
            hero = source.controller
            if hero is None or minion is None:
                return
            if minion.controller is not hero:
                return
            if not _has_deathrattle(minion):
                return
            for m in _living(hero):
                if not _in_family(m, family):
                    continue
                d = g.db.get(m.card_id)
                if d is None or d.num(0) is None:
                    continue
                ImproveBloodGems(hero, 0, d.num(0)).do(g)

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        return None


# ══════════════ 未注册（DEFERRED；台账见模块 docstring） ══════════════


class FlamingPortraitScript:
    """
    Natural language: [x]Get a Flaming Enforcer.
    Whenever your Flaming
    Enforcers trigger, also give
    the stats to their neighbors.

    Status: DEFERRED — requires `minion_triggered(hook=, source=, value=)`
    观察点（自身 EoT 触发 vs 被别的卡驱动吞噬不可区分）

    Dependency: `minion_consumed(consumer=, stats_atk=, stats_health=)`
    载荷（2026-09-02, B2-6）能取到"消费者=你的 Flaming Enforcer"与
    受害者属性快照，且金色倍率可经 `consumer.scripts.mult` 还原——但
    `consumer=` **无法区分触发来源**: 已注册的 `BG28_607` Corrupted
    Cupcakes（"Choose a friendly Demon. It consumes 3 random minions
    in the Tavern to gain their stats"）与 `BG36_503` Soulkeeping
    Jailer（"Your Demons each consume a random minion in the Tavern"）
    都可选中 Flaming Enforcer 并使其吞噬——此时是**别的卡**在驱动，
    不是 Flaming Enforcer 的触发式效果。按 `consumer=` 镜像会过触发
    （ENGINE_BACKLOG B2-15 仍为未完成项）。

    Implementation path: 引擎在 `run_script_hook`（或各关键钩子出口）
    广播 `minion_triggered(hook=, source=, value={atk,health,...})`;
    本卡监听 `hook="end_of_turn"` 且 `source` ∈ Flaming Enforcer 家族
    → 以载荷增量（含金色倍率）镜像给 `_alive_neighbors(source)`。
    RULES §7.4.6 例外条（依赖被授予卡行为）。

    Params: 无模板参数（"the stats" = 运行时增量）
    """


class DesignerEyepatchScript:
    """
    Natural language: You only need 2 copies of a Pirate to make it
    Golden.

    Status: DEFERRED — requires per-race 三连阈值读取点

    Dependency: `GameTag.TRIPLE_THRESHOLD` 是 **hero 级全域单值**
    （`game.py::check_for_triple` L1127 `hero.get(TRIPLE_THRESHOLD, 3)`
    与 `game.py::_combine`），文本限定 **Pirate**（数据
    `subset_pirate=1`）。写入 `TRIPLE_THRESHOLD=2` 会让**所有**随从
    2 份成金 = 过度适用（近似实现，SOP §6b 禁止）。

    Implementation path: 新增 `GameTag.TRIPLE_THRESHOLD_RACE` /
    `hero.triple_threshold_by_race`（race → N）并在
    `check_for_triple` 取该卡 `acquired.race` 的阈值（与全局
    `TRIPLE_THRESHOLD` 取较小值）; 本卡 on_bind 写
    `{PIRATE: 2}`（含 Race.ALL 语义按 RULES §8 处理）。
    同缺口卡: `batch_trinkets27`/`batch_trinkets29` 的 439 台账。

    Params: 无模板参数（"2" 为文本字面量）
    """


class MarineSignetScript:
    """
    Natural language: [x]After you play 4 minions,
    get a random Tier {1}
    Tavern spell and improve
    this. <i>({0} left!)</i>@[x]After you play 4 minions,
    get a random Tier {1}
    Tavern spell.

    Status: DEFERRED — requires "improve this" 的档位递增数据链

    Dependency: "({0} left!)" 的滚动计数（num(0)=4）与 "get a random
    Tier {1} Tavern spell"（num(1)=1）本身可用现有原语表达，但
    "**and improve this**" 指向饰品的升级变体，而本卡
    `triple_upgrade_id` 为空（36.2.2 数据核实: 无 `BG30_MagicItem_711t`
    之类升级定义）、wiki.gg 页无 Notes 说明递增目标（既有 "improve
    this" 卡全部递增**属性值**，此处无属性字段可递增）→ 无法兑现，
    整卡不可 CORRECT（SOP §6b 第 4 步）。

    Implementation path: 数据链补齐（升级变体 id / 递增字段）后:
    on_bind 注册 `card_played`（"play a minion" 域——RULES §7.4.12）
    监听，计数达 num(0) → `_random_tavern_spell`（恰好 Tier num(1)）
    + 升级/递增本实体。任一步缺权威 → 维持 DEFERRED。

    Params: {0}=4 {1}=1（36.2.2 基线）
    """


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册本批 10 饰品 + 1 Spellcraft 法术（DEFERRED 1 张见模块
    docstring，不注册——二态铁律 SOP §6b）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG36_MagicItem_216", EternalPortraitScript),
        ("BG32_MagicItem_907", STharaStickerScript),
        ("BG35_MagicItem_732", SoulFermenterScript),
        ("BG35_MagicItem_930", WarbandWhistleScript),
        ("BG36_MagicItem_214", InsurrectionistsBladeScript),
        ("BG36_MagicItem_308", TrailblazerStickerScript),
        ("BG32_MagicItem_902", StatueOfHireekScript),
        ("BG35_MagicItem_743", ElectrodeAttractorScript),
        ("BG35_MagicItem_755", ChillmereMosaicScript),
        ("BG35_MagicItem_755t", ChillmereMosaicSpellScript),
        ("BG35_MagicItem_433", VinespeakerPortraitScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
