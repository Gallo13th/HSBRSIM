"""Entity — 一切游戏对象的基类。

设计约束（吸取旧引擎教训）:
  - 所有可见状态进 tags；buff 堆叠进 _buffs
  - 脚本钩子统一签名 (source, game, ctx) -> Action | list[Action] | None
  - ctx 携带上下文（攻击目标、击杀者等），废除旧引擎的 game._last_attack_target 全局
  - 监听器随实体离场自动注销（光环生命周期）
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from hsrl2.tags import CardType, GameTag, Race, Zone

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero


# ── "获得属性"广播抑制（ENGINE_BACKLOG §E D2）──
# 内部机械（附魔**复制**：`copy_buffs_to` 副本/三连合成；战斗快照**复原**
# 重放：`Game.run_combat` finally 块的 persist/poet/dmg_delta 通道）会调用
# `add_buff`，但那些调用**不是**"获得属性"——它们是把本已存在的属性搬到
# 别处或还原回来。若照常广播 `stats_gained`，一张"每当……获得攻击力"的卡
# 会在三连/战后各重复触发 1 次（ENGINE_BACKLOG §E2 结构性推断 2–4 倍计）。
# 抑制计数为模块级（`add_buff` 可能在 `game is None` 的实体上被调用——
# 建实体初始化路径），支持嵌套。
_stats_gained_suppress_depth = 0


@contextmanager
def suppress_stats_gained():
    """抑制窗口内的 `stats_gained` 广播（只影响该事件，不影响
    `buff_applied` 等既有事件）。

    用法（引擎内部机械）::

        with suppress_stats_gained():
            other.add_buff(...)      # 复制/复原，不构成"获得"
    """
    global _stats_gained_suppress_depth
    _stats_gained_suppress_depth += 1
    try:
        yield
    finally:
        _stats_gained_suppress_depth -= 1


def _stats_gained_suppressed() -> bool:
    return _stats_gained_suppress_depth > 0


class Buff:
    """附魔。temporary=True 的 buff 在战斗结束清除。

    gem=True 标记血宝石来源 buff（Gem Confiscation "steals all Blood
    Gems" 移转语义的数据源——不依赖数值比对）。

    persist=True 标记**按来源跨战斗持久化**的 buff（"give ... permanently"
    的战斗内授予口径——Bewitched Ribbon `BG35_MagicItem_923` /
    Cyclist Portrait `BG36_MagicItem_362`）: `Game.run_combat` 的恢复
    阶段只把该实体的 `persist` 附魔**按来源**重放回快照复原后的实体，
    该场战斗内其它变更（temporary/非持久 buff、伤害、临时关键词）照常
    回滚（RULES §3.5 例外 4）。与 `GameTag.PERSIST_COMBAT_CHANGES`
    （单实体全量通道——Tarecgosa 族）不同: 本通道**不**要求实体带 tag，
    也不会连带保留同一实体的其它战内变化; `source_id` 是来源标识
    （卡 id 或家族 id），供审计与逐卡断言。
    """

    __slots__ = ("atk", "health", "temporary", "source_id", "dark_gift",
                 "gem", "persist", "source")

    def __init__(self, atk: int = 0, health: int = 0, *,
                 temporary: bool = False, source_id: str = "",
                 dark_gift: str | None = None, gem: bool = False,
                 persist: bool = False, source: Any = None):
        self.atk = atk
        self.health = health
        self.temporary = temporary
        self.source_id = source_id        # 来源卡牌 id（审计用）
        self.dark_gift = dark_gift        # Dark Gift 附魔名
        self.gem = gem
        self.persist = persist            # 跨战斗持久化（按来源）
        # 来源**实体**（"from other sources" / "another friendly X" 的排除
        # 依据; ENGINE_BACKLOG §E D7）。来源不明 → None（不得臆造）。
        self.source = source

    def __repr__(self) -> str:
        t = " (temp)" if self.temporary else ""
        g = " (gem)" if self.gem else ""
        p = " (persist)" if self.persist else ""
        return f"<Buff +{self.atk}/+{self.health}{t}{g}{p}>"


class Entity:
    """tags 保存全部可见状态；typed 属性只是 tags 的视图。"""

    def __init__(self, card_id: str, name: str = "", *,
                 card_type: CardType = CardType.MINION):
        self.uuid: str = uuid.uuid4().hex[:12]
        self.card_id = card_id
        self.game: Optional["Game"] = None
        self.controller: Optional["Hero"] = None
        self.tags: Dict[GameTag, Any] = {}
        # 动态脚本数据（官方 TAG_SCRIPT_DATA_NUM_1..5，独立命名空间）：
        # 键 = 1..5（或 `tags.ScriptDataNum` 的数值），值 = int。
        # **不能**放进 self.tags——GameTag 的 1068/1069/1070 是引擎内部语义，
        # 与官方 NUM_1/2/3 撞号（见 hsrl2/tags.py 命名空间注释）。
        self._script_data: Dict[int, int] = {}
        # 官方轨迹注入的序号（与 CardDef 静态初始化区分；B 类动态状态
        # 迁移只在**真实注入**时覆盖旧行为，无注入必须逐位不变）。
        self._script_data_injected: set[int] = set()
        self._buffs: List[Buff] = []
        self.scripts: Any = None            # 脚本类（由 scripts/registry 绑定）
        self._script_overrides: Dict[str, Any] = {}
        self.tags[GameTag.CARD_ID] = card_id
        self.tags[GameTag.NAME] = name
        self.tags[GameTag.CARDTYPE] = card_type
        self.tags[GameTag.ZONE] = Zone.INVALID

    # ── tag 存取 ──

    def get(self, tag: GameTag, default: Any = 0) -> Any:
        return self.tags.get(tag, default)

    def set(self, tag: GameTag, value: Any) -> None:
        self.tags[tag] = value

    def has(self, tag: GameTag) -> bool:
        return bool(self.tags.get(tag, False))

    def clear(self, tag: GameTag) -> None:
        self.tags.pop(tag, None)

    # ── 动态脚本数据（官方 TAG_SCRIPT_DATA_NUM_1..5；独立命名空间）──
    #
    # 语义：num=1..5 ↔ 官方 `TAG_SCRIPT_DATA_NUM_<num>`（enumID 1068..1072）。
    # 与 `self.tags` 完全隔离（GameTag 1068/1069/1070 是引擎内部语义）。
    # 读取优先级：动态字典 > CardDef 静态 `script_data_num_n`。
    # 生产点（累计类脚本）与外部注入（官方轨迹重建）都走同一个通道。

    def set_script_data(self, num: int, value: Optional[int]) -> None:
        """写入脚本数值；``value=None`` = 清除动态值（回落到 CardDef）。"""
        n = int(num)
        if not 1 <= n <= 5:
            raise ValueError(f"script data num must be 1..5, got {num}")
        if value is None:
            self._script_data.pop(n, None)
            self._script_data_injected.discard(n)
        else:
            self._script_data[n] = int(value)
            self._script_data_injected.add(n)

    def get_script_data(self, num: int,
                        default: Optional[int] = None) -> Optional[int]:
        """读取**动态**脚本值（未注入过 → default；不回落 CardDef）。"""
        return self._script_data.get(int(num), default)

    def is_script_data_injected(self, num: int) -> bool:
        """该序号是否由外部/生产点**动态注入**（非 CardDef 静态初始化）。"""
        return int(num) in self._script_data_injected

    def clear_script_data(self, num: Optional[int] = None) -> None:
        if num is None:
            self._script_data.clear()
            self._script_data_injected.clear()
        else:
            self._script_data.pop(int(num), None)
            self._script_data_injected.discard(int(num))

    @property
    def script_data(self) -> Dict[int, int]:
        """当前动态脚本值快照（只读副本）。"""
        return dict(self._script_data)

    def init_script_data_from_carddef(self, card_def: Any) -> None:
        """用 CardDef 静态值填充通道（``num(0)..num(4)`` → NUM_1..NUM_5）。

        注意：只填**非 None** 的静态值；动态计数（如 Eternal Knight 的
        "本局死亡数"）应由生产点写 NUM_3 或由外部注入。
        """
        if card_def is None:
            return
        for index in range(1, 6):
            value = getattr(card_def, f"script_data_num_{index}", None)
            if value is not None:
                self._script_data[index] = int(value)

    def script_data_or_card(self, num: int,
                            card_def: Any = None) -> Optional[int]:
        """动态值优先，没有则回落 CardDef 静态值（官方 ``num(n-1)``）。"""
        stored = self.get_script_data(num)
        if stored is not None:
            return stored
        if card_def is None and self.game is not None:
            card_def = self.game.db.get(self.card_id)
        if card_def is None:
            return None
        return getattr(card_def, f"script_data_num_{int(num)}", None)

    # ── 通用属性 ──

    @property
    def zone(self) -> Zone:
        return Zone(self.get(GameTag.ZONE, Zone.INVALID))

    @zone.setter
    def zone(self, value: Zone) -> None:
        old = Zone(self.get(GameTag.ZONE, Zone.INVALID))
        self.set(GameTag.ZONE, value)
        # ── 离场即注销监听器（本模块首段契约"监听器随实体离场自动注销"的
        # 强制收口; ENGINE_BACKLOG #40）──
        # 唯一的区域赋值出口: 任何"棋盘 → 手牌 / 酒馆 / REMOVED /
        # GRAVEYARD"的移动都经此自动 `unregister_owner`。此前该契约靠每个
        # 离场路径**显式**调用 `events.unregister_owner`——漏一处，实体的
        # 监听器就在离场后继续触发（实测泄漏: Double Stitch 棋盘→手牌、
        # Expert Aviator 战斗副本→REMOVED、Jandice 棋盘→酒馆、Malygos
        # Arcane Alteration 手牌→REMOVED）。
        # 两条独立触发条件:
        #   (1) **随从进入 `REMOVED`/`GRAVEYARD`**（永久离场）：从**任何**
        #       区域都注销。随从是唯一可上棋盘的实体类型，它在手牌里也可能
        #       带**离场前注册**的监听器（Dark Gift `_make_counter_gift` 计数
        #       gift、`on_enter_hand` 被动、`LOCKED_IN_HAND` 解锁 tick）——
        #       一旦被移入 `REMOVED`（Malygos Arcane Alteration 替换手牌、
        #       三连合并、磁力吸附等）就不会再回来，其监听器若残留会在后续
        #       事件里继续改写一个已离场实体的属性（本 setter 修复前的
        #       Malygos 泄漏即此；此前需逐路径显式注销）。
        #       **不含 `Spell`**：法术从不进入 `PLAY`（RULES §6.22），其
        #       `zone=REMOVED` 只是"卡面结算完成/离开手牌区"的常规终态，
        #       而法术 owner 的监听器是**效果期接线**（如 Chillmere Mosaic
        #       法术注册 `TURN_END` 清除本回合费用规则），必须活过
        #       `_finish_play_spell` 的 `zone=REMOVED`，故不在此列注销。
        #   (2) **从 `PLAY` 出去**（`Zone.PLAY` → 非 `PLAY`/非 `SETASIDE`）:
        #       原有条件，覆盖棋盘 → 手牌 / 酒馆 / 死亡清场等。
        # 例外与边界:
        #   - `Zone.SETASIDE` 是复生处理期间的**临时**离场（同一实体稍后
        #     回 `Zone.PLAY`，不重跑 `on_summon`）→ 监听器必须保留。
        #   - `Zone.PLAY` 本身不是离场（含战斗中把新实体放回棋盘）。
        #   - **进入 `HAND`/`TAVERN` 只对来自 `PLAY` 的实体注销**：手牌/
        #     酒馆内的实体本就在离场期注册监听器（`LOCKED_IN_HAND` 解锁
        #     tick、Dark Gift gift、`on_enter_hand` 被动），不得误伤。
        # 不受影响: 英雄 / 饰品 / 任务奖励实体的 `zone` 恒为
        # `Zone.INVALID`（不参与棋盘区域系统），其持久监听器照旧。
        # 幂等: 已显式注销过的路径再注销一次无副作用; 战斗内的注销由
        # `Game.run_combat` 的监听器表快照统一复原（复原后再由 `finally`
        # 的离场收口丢弃永久离场者）。
        leaving_to_graveyard = (
            value in (Zone.REMOVED, Zone.GRAVEYARD)
            and self.get(GameTag.CARDTYPE) == CardType.MINION)
        leaving_play = old == Zone.PLAY and value not in (Zone.PLAY,
                                                          Zone.SETASIDE)
        if leaving_to_graveyard or leaving_play:
            game = self.game
            if game is not None:
                game.events.unregister_owner(self)

    @property
    def name(self) -> str:
        return self.get(GameTag.NAME, "")

    @property
    def dead(self) -> bool:
        return self.has(GameTag.DEAD) or self.get(GameTag.HEALTH, 0) <= 0

    # ── 数值（base + buffs；光环由子类扩展） ──

    @property
    def atk(self) -> int:
        total = self.get(GameTag.BASE_ATK, 0)
        for b in self._buffs:
            total += b.atk
        total += self._aura_atk()
        # 动态属性脚本钩子: "Has +X for each Y" 家族（Falling Sky Golem
        # 等 wherever-this-is 静态读数）——脚本返回 int 覆盖或 None 回落
        if self.scripts is not None and not self.has(GameTag.SILENCED):
            atk_fn = getattr(self.scripts, "atk", None)
            if callable(atk_fn):
                result = atk_fn(self)
                if result is not None:
                    return max(0, result)
        return max(0, total)

    def _aura_atk(self) -> int:
        """种族光环（"Your <race> have +X/+Y this game wherever they are"）。

        hero.race_auras: dict[Race, (atk, health)]，叠加式;
        - 随从种族匹配 或 任一侧为 ALL（Amalgam）→ 生效
        - **Race.ALL 光环命中所有随从（含无类型）**——"Your minions have
          +X/+Y"（Feral Talisman）语义；种族限定光环不命中无类型随从
        """
        hero = getattr(self, "controller", None)
        if hero is None:
            return 0
        auras = getattr(hero, "race_auras", None)
        races = getattr(self, "races", None)
        total = (self._tier_aura_atk() + self._card_aura_atk())
        # tier 维度光环（与种族/卡家族并列）
        if not auras or races is None:
            return total
        for aura_race, (atk, _health) in auras.items():
            if aura_race == Race.ALL:
                total += atk          # 全随从光环（含 NONE）
            elif aura_race in races:
                # 类型身份集合（AC-3）——双类型随从同时吃两种族光环
                # （wiki `Multi-type minion` revid 855346 "benefit from the
                # effects of both types"）；ALL 型已在 races 中展开为
                # 全 10 族，无类型随从为空集（不吃限定光环）。
                total += atk
        return total

    def _tier_aura_active(self) -> list:
        """适用于本实体的 tier 维度光环条目（RULES §6.19）。

        条件: 本实体在**该英雄棋盘上**、`tech_level <= max_tier`、
        光环 source 仍属于该英雄（饰品/奖励/棋盘）——否则视为已失效。
        """
        hero = getattr(self, "controller", None)
        if hero is None or getattr(self, "zone", None) != Zone.PLAY:
            return []
        auras = getattr(hero, "tier_auras", None)
        if not auras:
            return []
        tier = getattr(self, "tech_level", None)
        if tier is None:
            return []
        out = []
        for source, max_tier, atk, health in list(auras.values()):
            if tier > max_tier:
                continue
            if not (source in hero.trinkets
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue          # source 已离场 → 光环失效
            out.append((atk, health))
        return out

    def _tier_aura_atk(self) -> int:
        return sum(a for a, _h in self._tier_aura_active())

    def _card_aura_active(self) -> list:
        """适用于本实体的**卡家族光环**条目（RULES §6.19）。

        条件: 家族匹配（`TRIPLE_BASE_CARD_ID` 回落后的 card_id ∈ 家族集合
        或实体自身 card_id ∈ 集合）; 光环 source 仍属于该英雄。
        任意区域生效（"wherever this is"）。
        """
        hero = getattr(self, "controller", None)
        if hero is None:
            return []
        auras = getattr(hero, "card_auras", None)
        if not auras:
            return []
        cid = getattr(self, "card_id", None)
        bid = self.get(GameTag.TRIPLE_BASE_CARD_ID, None) or cid
        out = []
        for source, card_ids, atk, health in list(auras.values()):
            if not (source in getattr(hero, "trinkets", [])
                    or source in getattr(hero, "quest_rewards", [])
                    or source in hero.board):
                continue
            if cid in card_ids or bid in card_ids:
                out.append((atk, health))
        return out

    def _card_aura_atk(self) -> int:
        return sum(a for a, _h in self._card_aura_active())

    def _card_aura_health(self) -> int:
        return sum(h for _a, h in self._card_aura_active())

    @property
    def max_health(self) -> int:
        total = self.get(GameTag.BASE_HEALTH, 0)
        for b in self._buffs:
            total += b.health
        total += self._aura_health()
        # 动态属性脚本钩子（同 atk——Falling Sky Golem 家族）
        if self.scripts is not None and not self.has(GameTag.SILENCED):
            health_fn = getattr(self.scripts, "health", None)
            if callable(health_fn):
                result = health_fn(self)
                if result is not None:
                    return max(1, result) if result > 0 else result
        return max(1, total) if total > 0 else total

    def _aura_health(self) -> int:
        hero = getattr(self, "controller", None)
        if hero is None:
            return 0
        auras = getattr(hero, "race_auras", None)
        races = getattr(self, "races", None)
        total = (sum(h for _a, h in self._tier_aura_active())
                 + self._card_aura_health())
        if not auras or races is None:
            return total
        for aura_race, (_atk, health) in auras.items():
            if aura_race == Race.ALL:
                total += health      # 全随从光环（含 NONE）
            elif aura_race in races:
                total += health
        return total

    def stats_without_aura(self) -> tuple:
        """**base + 附魔**（不含光环与动态属性脚本钩子）。

        "exact copy" / "with its maximum stats" 类快照的唯一口径
        （RULES §6.19/§7.4.10b）: 光环（种族 / tier / 卡家族）与
        `scripts.atk/health` 动态钩子都由**新实体在棋盘上实时重算**;
        若快照记录 `atk`/`max_health`（含光环）再写回 BASE_ATK/HEALTH，
        实时光环会**双计**（2026-09-13 对抗验证实测: Mech +2/+2 光环下
        Boom Controller 的 4/4 副本被复原成 6/6）。
        """
        atk = self.get(GameTag.BASE_ATK, 0)
        health = self.get(GameTag.BASE_HEALTH, 0)
        for b in self._buffs:
            atk += b.atk
            health += b.health
        return atk, health

    @property
    def health(self) -> int:
        return self.get(GameTag.HEALTH, 0)

    @health.setter
    def health(self, value: int) -> None:
        self.set(GameTag.HEALTH, max(0, value))
        if self.get(GameTag.HEALTH, 0) <= 0:
            self.set(GameTag.DEAD, True)

    # ── buff 管理 ──

    def add_buff(self, buff: Buff) -> None:
        """应用 buff（"获得属性"的唯一生产点）。

        引擎钩子:
          - ENCHANT_IMMUNE（Fishbait "This can't gain stats"）: 正值
            增益不生效，直接丢弃（官方: 无法获得属性）
          - 永久化翻转（Lava Lurker "The first Spellcraft spell ...
            is permanent"）: game._permanence_pending 命中本实体时，
            temporary buff 转永久
          - buff_applied 事件（Scarlet Survivor 阈值监听等）
          - **stats_gained 事件**（"Whenever a friendly [X] gains
            Attack / gains stats" 家族的唯一观察点——ENGINE_BACKLOG §E）

        `stats_gained` 载荷（逐字段）:
          - `minion`    = 属性上升的实体（本次 `add_buff` 的 self）
          - `atk`       = 本次附魔的**攻击增量**（可负/可 0——监听方自行
                          只认 `atk > 0`;"获得攻击力"= 攻击力上升）
          - `health`    = 本次附魔的生命增量（同上）
          - `permanent` = `not buff.temporary`（RULES §3.5: 招募期 buff
                          永久 / 战斗期 buff 战后消失 → A4）
          - `source`    = 触发本次附魔的**来源实体**（行动来源，见
                          `Game.run_script_hook` / `ActionQueue.resolve`
                          的 `game._action_source` 解析顺序）;
                          来源不可判定时为 None——不得臆造
                          （BG21_018 "from other sources" / BG31_820
                          "another friendly Pirate" / BG26_966 "a different
                          friendly Dragon" 的排除依据; §E D7）
          - `source_id` = 附魔携带的来源卡 id。**现状**: 绝大多数附魔点
                          未传（空串），仅少数脚本传家族/卡 id; 供审计与
                          家族标识（与 `source` 粒度不同——后者是实体）。

        触发域（§E D1/D2 逐路径裁定——见 ENGINE_BACKLOG §E 最终表）:
          - 计入: #1 `add_buff`（含 #2 `Buff` Action / #3 持久酒馆 buff
            入馆 / #13 Dark Gift）——同一生产点，附魔真正施加于实体
          - **排除**: #4 `copy_buffs_to`（副本）/ #5 三连 `_combine` /
            #6 战斗快照复原重放——它们是**复制/复原**，不是"获得";
            经 `suppress_stats_gained()` 抑制
          - **不计**: #7 磁力（BASE_ATK 相加，无附魔）/ #8 `SetStats`
            覆盖 / #9 脚本直写 BASE_ATK / #10 `Transform`（`_buffs`
            整体转移）/ #11 计算式光环 / #12 `atk` 动态钩子 / #14 血宝石
            移转（直插 `_buffs`）/ #15 治疗——均**不经** `add_buff`，
            故天然不广播（判据与理由见 §E）
        """
        if buff.atk > 0 or buff.health > 0:
            if self.has(GameTag.ENCHANT_IMMUNE):
                return
        if buff.temporary and self.game is not None \
                and getattr(self.game, "_permanence_pending", None) \
                == self.uuid:
            buff.temporary = False
        self._buffs.append(buff)
        if buff.health > 0:
            self.set(GameTag.HEALTH, self.health + buff.health)
        if self.game is not None:
            from hsrl2.events import Listener  # noqa: F401
            self.game.events.fire(self.game, "buff_applied",
                                  target=self, buff=buff)
            # "获得属性"广播: 附魔已入 `_buffs`、HEALTH 已同步**之后**
            # （§E A7 时点）。内部机械（复制/复原）在抑制窗口内不广播。
            if not (_stats_gained_suppressed()
                    or getattr(self.game, "_restore_no_gain", False)):
                source = getattr(buff, "source", None)
                if source is None:
                    source = getattr(self.game, "_action_source", None)
                self.game.events.fire(
                    self.game, "stats_gained", minion=self,
                    atk=buff.atk, health=buff.health,
                    permanent=not buff.temporary,
                    source=source, source_id=buff.source_id)

    def copy_buffs_to(self, other: "Entity") -> None:
        """把本实体的全部附魔**独立复制**到 other（副本/三连金色合成）。

        必须复制而非共享同一 Buff 实例: Buff 是可变对象，共享会让
        任一侧的移除（Vol'jin "until next turn" 过期、Lava Lurker
        永久化翻转、法术塑造到期）连带清掉另一侧的附魔——对抗审查
        2026-09-02 实测 `id(copy.buffs[0]) == id(original.buffs[0])`。

        复制**不是获得**（ENGINE_BACKLOG §E D2）: 整段复制在
        `suppress_stats_gained()` 窗口内执行 → 副本/三连金色携带的
        属性不会对"每当……获得攻击力"类监听重复触发。
        """
        with suppress_stats_gained():
            for b in self._buffs:
                other.add_buff(Buff(atk=b.atk, health=b.health,
                                    temporary=b.temporary,
                                    source_id=b.source_id,
                                    dark_gift=b.dark_gift, gem=b.gem,
                                    persist=b.persist, source=b.source))

    def remove_buff(self, buff: Buff) -> None:
        if buff in self._buffs:
            self._buffs.remove(buff)
            # 当前血不可超上限（HS 语义: 移除生命增益即 clamp——
            # 对抗审查 BUG-5）
            if self.health > self.max_health:
                self.set(GameTag.HEALTH, self.max_health)

    def clear_temporary_buffs(self) -> None:
        self._buffs = [b for b in self._buffs if not b.temporary]
        if self.health > self.max_health:
            self.set(GameTag.HEALTH, self.max_health)

    @property
    def buffs(self) -> List[Buff]:
        return list(self._buffs)

    # ── 脚本钩子分发 ──

    def call_script(self, hook: str, ctx: Any = None):
        """调用脚本钩子。静默随从无任何效果。"""
        if self.has(GameTag.SILENCED):
            return None
        override = self._script_overrides.get(hook)
        if override is not None:
            return override(self, self.game, ctx) if callable(override) else override
        if self.scripts is None:
            return None
        fn = getattr(self.scripts, hook, None)
        if fn is None:
            return None
        return fn(self, self.game, ctx)

    def set_script_override(self, hook: str, fn) -> None:
        self._script_overrides[hook] = fn

    def __repr__(self) -> str:
        return f"<{self.card_id} {self.name} ({self.uuid})>"
