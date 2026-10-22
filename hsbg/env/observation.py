"""观测构建 —— 严格对齐 ``hsbg/env/spec.py`` 与 ``docs/ENV_SPEC.md``。

核心约束
--------
- **槽位同源**：本模块只读驱动层生成的 :class:`hsbg.env.driver.Zones`
  （与动作枚举使用同一份有序列表），因此 ``EntityToken.slot`` 与
  ``CandidateAction.src_slot/tgt_slot`` 严格一一对应。
- **可观测性边界**（POMDP）：只暴露己方完整信息 + 上一场对手的战前战团
  （官方可见）+ 大厅公开信息（血量/护甲/等级/存活/名次）；对手当前手牌/
  金币/酒馆展示永不进入观测。
- 观测是纯数据（frozen dataclass + tuple），可直接 pickle 跨进程传输。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import hsrl2.constants as C
from hsrl2.game import Game, PendingChoice
from hsrl2.hero import Hero
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import CardType, GameTag, Race

from hsbg.env import driver
from hsbg.env.spec import (
    CARD_TYPE_ANOMALY,
    CARD_TYPE_HERO,
    CARD_TYPE_HERO_POWER,
    CARD_TYPE_MINION,
    CARD_TYPE_QUEST,
    CARD_TYPE_REWARD,
    CARD_TYPE_SPELL,
    CARD_TYPE_TRINKET,
    CARD_TYPE_UNKNOWN,
    CandidateAction,
    EntityToken,
    HeroToken,
    LobbyPlayer,
    Observation,
    PHASE_CHOICE,
    PHASE_RECRUIT,
    PendingChoice as PendingChoiceToken,
    ZONE_BOARD,
    ZONE_CHOICE,
    ZONE_HAND,
    ZONE_NONE,
    ZONE_OPPONENT,
    ZONE_QUEST,
    ZONE_TAVERN,
    ZONE_TRINKET,
)

__all__ = [
    "ENTITY_TOKEN_VERSION",
    "entity_token",
    "build_observation",
    "build_extra_state",
    "estimate_rank",
    "card_type_name",
    "race_names",
    "keyword_names",
]

#: 观测协议版本（spec.Observation.version）
ENTITY_TOKEN_VERSION = int(Observation.__dataclass_fields__[
    "version"].default)          # 跟随 spec.py（v2），不手抄

# ══════════════════════════════════════════════════════════════════════
# 归一化映射（引擎枚举 → spec 字符串）
# ══════════════════════════════════════════════════════════════════════

_CARD_TYPE_NAME: Dict[int, str] = {
    int(CardType.MINION): CARD_TYPE_MINION,
    int(CardType.SPELL): CARD_TYPE_SPELL,
    int(CardType.BACON_SPELL): CARD_TYPE_SPELL,
    int(CardType.HERO): CARD_TYPE_HERO,
    int(CardType.HERO_POWER): CARD_TYPE_HERO_POWER,
    int(CardType.BACON_TRINKET): CARD_TYPE_TRINKET,
    int(CardType.BACON_QUEST_REWARD): CARD_TYPE_REWARD,
    int(CardType.BACON_ANOMALY): CARD_TYPE_ANOMALY,
}

_RACE_NAME: Dict[int, str] = {
    int(Race.UNDEAD): "undead",
    int(Race.MURLOC): "murloc",
    int(Race.DEMON): "demon",
    int(Race.MECH): "mech",
    int(Race.ELEMENTAL): "elemental",
    int(Race.BEAST): "beast",
    int(Race.PIRATE): "pirate",
    int(Race.DRAGON): "dragon",
    int(Race.ALL): "all",
    int(Race.QUILBOAR): "quilboar",
    int(Race.NAGA): "naga",
}

#: (spec 关键词, GameTag, 脚本钩子名)
_KEYWORD_TAGS: Tuple[Tuple[str, Any, str], ...] = (
    ("taunt", GameTag.TAUNT, ""),
    ("divine_shield", GameTag.DIVINE_SHIELD, ""),
    ("poisonous", GameTag.POISONOUS, ""),
    ("venomous", GameTag.VENOMOUS, ""),
    ("reborn", GameTag.REBORN, ""),
    ("windfury", GameTag.WINDFURY, ""),
    ("mega_windfury", getattr(GameTag, "MEGA_WINDFURY", None), ""),
    ("cleave", GameTag.CLEAVE, ""),
    ("deathrattle", GameTag.DEATHRATTLE, "deathrattle"),
    ("battlecry", GameTag.BATTLECRY, "battlecry"),
    ("start_of_combat", GameTag.START_OF_COMBAT, "start_of_combat"),
    ("rally", GameTag.RALLY, "rally"),
    ("avenge", GameTag.AVENGE, ""),
    ("magnetic", GameTag.MAGNETIC, ""),
    ("spellcraft", GameTag.SPELLCRAFT, ""),
    ("activate", GameTag.ACTIVATE, "activate"),
    ("stealth", GameTag.STEALTH, ""),
    ("choose_one", GameTag.CHOOSE_ONE, "choose_options"),
)


def card_type_name(obj: Any) -> str:
    """实体/卡定义 → spec 卡牌类型字符串。"""
    if obj is None:
        return CARD_TYPE_UNKNOWN
    # CardDef: card_type 是 CardType 枚举；实体: CARDTYPE tag
    ct = getattr(obj, "card_type", None)
    if ct is None:
        ct = obj.get(GameTag.CARDTYPE, None) if hasattr(obj, "get") else None
    if ct is None:
        return CARD_TYPE_UNKNOWN
    try:
        return _CARD_TYPE_NAME.get(int(ct), CARD_TYPE_UNKNOWN)
    except Exception:                                     # noqa: BLE001
        return CARD_TYPE_UNKNOWN


def race_names(races: Any) -> Tuple[str, ...]:
    """Race 集合 → spec 种族字符串（排序稳定，供策略做 one-hot）。"""
    if not races:
        return ()
    out: List[str] = []
    for r in races:
        try:
            name = _RACE_NAME.get(int(r))
        except Exception:                                 # noqa: BLE001
            name = None
        if name is None:
            continue
        out.append(name)
    # 排序保证确定性（不依赖 frozenset 迭代顺序）
    return tuple(sorted(set(out)))


def keyword_names(obj: Any) -> Tuple[str, ...]:
    """实体关键词 → spec 关键词字符串（GameTag + 脚本钩子）。"""
    tags = getattr(obj, "tags", None)
    if tags is None:
        # CardDef: keywords 是字符串集合
        kws = getattr(obj, "keywords", None) or ()
        return tuple(sorted({str(k).lower() for k in kws}))
    scripts = getattr(obj, "scripts", None)
    out: List[str] = []
    for name, tag, hook in _KEYWORD_TAGS:
        present = False
        if tag is not None and obj.has(tag):
            present = True
        if not present and scripts is not None and hook:
            attr = getattr(scripts, hook, None)
            if attr is not None:
                present = True
        if present:
            out.append(name)
    # Choose One（脚本声明）与 Spellcraft（CardDef.spellcraft_id）补充
    if scripts is not None and getattr(scripts, "choose_options", None):
        if "choose_one" not in out:
            out.append("choose_one")
    return tuple(out)


def _entity_uuid_int(obj: Any) -> int:
    raw = getattr(obj, "uuid", None)
    if not isinstance(raw, str):
        return 0
    try:
        return int(raw, 16) % (1 << 63)
    except ValueError:
        return 0


def _token_cost(game: Optional[Game], obj: Any, d: Any) -> int:
    try:
        cost = obj.get(GameTag.COST, None)
    except Exception:                                     # noqa: BLE001
        cost = None
    if cost is not None:
        return int(cost)
    if d is not None:
        base = getattr(d, "cost", 0) or 0
        # 随从的买入价默认 3（CardDef.cost 是打出价；战棋随从无手牌费）
        if isinstance(obj, Minion):
            return int(base) if base else 3
        return int(base)
    return 0


def _token_from_minion(game: Optional[Game], m: Minion, zone: str,
                       slot: int) -> EntityToken:
    d = None
    if game is not None:
        try:
            d = game.db.get(m.card_id)
        except Exception:                                 # noqa: BLE001
            d = None
    return EntityToken(
        card_id=m.card_id,
        card_type=card_type_name(d if d is not None else m),
        zone=zone,
        slot=slot,
        atk=int(getattr(m, "atk", 0) or 0),
        health=int(getattr(m, "health", 0) or 0),
        tier=int(getattr(m, "tech_level", 0) or 0),
        cost=_token_cost(game, m, d),
        races=race_names(getattr(m, "races", ())),
        keywords=keyword_names(m),
        golden=bool(getattr(m, "is_golden", False)),
        entity_id=_entity_uuid_int(m),
        name=str(getattr(m, "name", "") or m.card_id),
    )


def _token_from_def(game: Optional[Game], d: Any, zone: str,
                    slot: int) -> EntityToken:
    return EntityToken(
        card_id=str(getattr(d, "id", "")),
        card_type=card_type_name(d),
        zone=zone,
        slot=slot,
        atk=int(getattr(d, "atk", 0) or 0),
        health=int(getattr(d, "health", 0) or 0),
        tier=int(getattr(d, "tech_level", 0) or 0),
        cost=int(getattr(d, "cost", 0) or 0),
        races=race_names(getattr(d, "races", ())),
        keywords=tuple(sorted({str(k).lower()
                               for k in (getattr(d, "keywords", ()) or ())})),
        golden=bool(getattr(d, "is_golden_def", False)),
        entity_id=0,
        name=str(getattr(d, "name", "") or getattr(d, "id", "")),
    )


def entity_token(game: Optional[Game], obj: Any, *, zone: str = ZONE_NONE,
                 slot: int = -1,
                 force_card_type: Optional[str] = None) -> EntityToken:
    """任意引擎对象 → :class:`EntityToken`（稳健，不抛异常）。

    支持: Minion / Spell / 通用 Entity / CardDef / card_id(str) /
    ``(card_id, extra_id)`` 元组（Dark Gift 选项）/ None（放弃选项）。
    """
    if obj is None:
        return EntityToken(card_id="", card_type=CARD_TYPE_UNKNOWN,
                           zone=zone, slot=slot, name="pass")
    try:
        if isinstance(obj, Minion):
            tok = _token_from_minion(game, obj, zone, slot)
        elif isinstance(obj, Spell):
            d = None
            if game is not None:
                try:
                    d = game.db.get(obj.card_id)
                except Exception:                         # noqa: BLE001
                    d = None
            tok = EntityToken(
                card_id=obj.card_id,
                card_type=CARD_TYPE_SPELL,
                zone=zone, slot=slot,
                atk=0, health=0,
                tier=int(getattr(d, "tech_level", 0) or 0) if d else 0,
                cost=_token_cost(game, obj, d),
                races=race_names(getattr(d, "races", ())) if d else (),
                keywords=(),
                golden=False,
                entity_id=_entity_uuid_int(obj),
                name=str(getattr(obj, "name", "") or obj.card_id),
            )
        elif isinstance(obj, Hero):
            tok = EntityToken(card_id=obj.card_id, card_type=CARD_TYPE_HERO,
                              zone=zone, slot=slot,
                              atk=0, health=int(obj.health),
                              tier=int(obj.tavern_tier),
                              cost=0, entity_id=_entity_uuid_int(obj),
                              name=str(obj.name or obj.card_id))
        elif isinstance(obj, str):
            d = None
            if game is not None:
                try:
                    d = game.db.get(obj)
                except Exception:                         # noqa: BLE001
                    d = None
            if d is not None:
                tok = _token_from_def(game, d, zone, slot)
            else:
                tok = EntityToken(card_id=obj, card_type=CARD_TYPE_UNKNOWN,
                                  zone=zone, slot=slot, name=obj)
        elif isinstance(obj, tuple):
            head = str(obj[0]) if obj else ""
            tail = str(obj[1]) if len(obj) > 1 else ""
            d = None
            if game is not None:
                try:
                    d = game.db.get(head)
                except Exception:                         # noqa: BLE001
                    d = None
            if d is not None:
                tok = _token_from_def(game, d, zone, slot)
                tok = EntityToken(
                    card_id=tok.card_id, card_type=tok.card_type,
                    zone=zone, slot=slot, atk=tok.atk, health=tok.health,
                    tier=tok.tier, cost=tok.cost, races=tok.races,
                    keywords=tok.keywords, golden=tok.golden,
                    entity_id=0, name=f"{tok.name}|{tail}")
            else:
                tok = EntityToken(card_id=head, card_type=CARD_TYPE_UNKNOWN,
                                  zone=zone, slot=slot, name=f"{head}|{tail}")
        elif hasattr(obj, "id") and hasattr(obj, "card_type"):
            # CardDef
            tok = _token_from_def(game, obj, zone, slot)
        else:
            # 其它引擎对象（饰品/任务/任务奖励实体）
            cid = str(getattr(obj, "card_id", "") or getattr(obj, "id", ""))
            d = None
            if game is not None and cid:
                try:
                    d = game.db.get(cid)
                except Exception:                         # noqa: BLE001
                    d = None
            ct = card_type_name(d) if d is not None else card_type_name(obj)
            tok = EntityToken(
                card_id=cid, card_type=ct, zone=zone, slot=slot,
                atk=int(getattr(obj, "atk", 0) or 0),
                health=int(getattr(obj, "health", 0) or 0),
                tier=int(getattr(obj, "tech_level", 0) or 0),
                cost=int(getattr(obj, "cost", 0) or 0),
                races=race_names(getattr(obj, "races", ())),
                keywords=keyword_names(obj),
                golden=bool(getattr(obj, "is_golden", False)),
                entity_id=_entity_uuid_int(obj),
                name=str(getattr(obj, "name", "") or cid),
            )
    except Exception:                                     # noqa: BLE001
        return EntityToken(card_id=str(getattr(obj, "card_id", "") or ""),
                           card_type=CARD_TYPE_UNKNOWN, zone=zone, slot=slot,
                           name=str(getattr(obj, "name", "") or ""))
    if force_card_type is not None:
        tok = EntityToken(
            card_id=tok.card_id, card_type=force_card_type, zone=tok.zone,
            slot=tok.slot, atk=tok.atk, health=tok.health, tier=tok.tier,
            cost=tok.cost, races=tok.races, keywords=tok.keywords,
            golden=tok.golden, entity_id=tok.entity_id, name=tok.name)
    return tok


# ══════════════════════════════════════════════════════════════════════
# 名次 / 大厅
# ══════════════════════════════════════════════════════════════════════


def estimate_rank(hero: Hero, lobby_heroes: Sequence[Hero],
                  eliminated_rank: Dict[int, int]) -> int:
    """当前名次估计。

    - 已淘汰: 环境记录的淘汰名次（被淘汰当时 ``alive_count + 1``）；
    - 存活: ``1 + 存活玩家中 (health + armor) 严格更高者数量``
      （并列同名次）。
    """
    recorded = eliminated_rank.get(id(hero))
    if recorded:
        return recorded
    if not hero.is_alive:
        return max(1, len(lobby_heroes))
    my_hp = int(hero.health) + int(hero.armor)
    better = 0
    for h in lobby_heroes:
        if h is hero or not h.is_alive:
            continue
        if int(h.health) + int(h.armor) > my_hp:
            better += 1
    return 1 + better


# ══════════════════════════════════════════════════════════════════════
# 观测构建
# ══════════════════════════════════════════════════════════════════════


def _hero_token(game: Game, hero: Hero, zones: driver.Zones,
                candidates: Sequence[CandidateAction]) -> HeroToken:
    power_ids = zones.power_ids
    main_pid = power_ids[0] if power_ids else ""
    pdef = zones.powers[0] if zones.powers else None
    power_cost = 0
    power_usable = False
    if pdef is not None:
        from hsrl2.scripts import REGISTRY
        script = REGISTRY.get(main_pid) or REGISTRY.get(pdef.id)
        try:
            power_cost = int(game.hero_power_cost(hero, pdef, script))
        except Exception:                                 # noqa: BLE001
            power_cost = int(getattr(pdef, "cost", 0) or 0)
        # 可用性直接问驱动层（choice 阶段 candidates 只有 choose，不能用它推断）
        try:
            for d in driver._enumerate_hero_powers(game, hero, zones):
                if d.power_id == main_pid:
                    power_usable = True
                    break
        except Exception:                                 # noqa: BLE001
            power_usable = False
    return HeroToken(
        hero_id=hero.card_id,
        health=int(hero.health),
        armor=int(hero.armor),
        tier=int(hero.tavern_tier),
        gold=int(hero.gold),
        upgrade_cost=int(hero.upgrade_cost),
        power_id=str(main_pid),
        power_cost=power_cost,
        power_usable=power_usable,
        tavern_tier_max=int(getattr(game, "max_tavern_tier", 6)),
    )


def _lobby(game: Game, agent: Hero, lobby_heroes: Sequence[Hero],
           eliminated_rank: Dict[int, int]) -> Tuple[LobbyPlayer, ...]:
    out: List[LobbyPlayer] = []
    for h in lobby_heroes:
        out.append(LobbyPlayer(
            name=str(h.name or h.card_id),
            health=int(h.health),
            armor=int(h.armor),
            tier=int(h.tavern_tier),
            alive=bool(h.is_alive),
            is_agent=(h is agent),
            eliminated_rank=int(eliminated_rank.get(id(h), 0)),
        ))
    return tuple(out)


def _pending_token(game: Game, hero: Hero,
                   pending: PendingChoice) -> PendingChoiceToken:
    kind = str(getattr(pending, "kind", ""))
    options: List[EntityToken] = []
    for i, opt in enumerate(pending.options):
        ct = CARD_TYPE_QUEST if kind == "quest_offer" else None
        options.append(entity_token(game, opt, zone=ZONE_CHOICE, slot=i,
                                    force_card_type=ct))
    return PendingChoiceToken(
        kind=kind,
        options=tuple(options),
        for_agent=(getattr(pending, "owner", None) is hero),
        prompt="",
    )


def _plain_extra(value: Any) -> Any:
    """递归深拷贝为**纯数据**（dict/list/str/int/float/bool/None）。

    观测 v2 的 ``extra`` 必须可 pickle、不含引擎对象（Hero/Minion/Spell/
    PendingChoice 等）、且与 ``info["obs_extra"]`` 语义一致。正常路径只含
    允许类型；兜底把异常类型转 ``str``（防止新字段误带引擎引用）。
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k) if not isinstance(k, (str, int, float, bool))
                else k: _plain_extra(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_extra(v) for v in value]
    return str(value)


def _extra_hero_state(game: Game, hero: Hero) -> Dict[str, Any]:
    """英雄级经济/标志标量（观测 v2 ``extra`` 平铺使用）。"""
    return {
        "frozen_tavern": bool(hero.frozen_tavern),
        "free_refresh_left": int(hero.get(GameTag.FREE_REFRESH_REMAINING, 0)),
        "health_refreshes_left": int(
            hero.get(GameTag.HEALTH_REFRESHES_LEFT, 0)),
        "refresh_cost": int(hero.get(GameTag.REFRESH_COST_OVERRIDE,
                                       C.REFRESH_COST)),
        "gold_spent_this_turn": int(
            hero.get(GameTag.GOLD_SPENT_THIS_TURN, 0)),
        "cards_played_this_turn": int(
            hero.get(GameTag.CARDS_PLAYED_THIS_TURN, 0)),
        "tavern_spells_cast_this_turn": int(
            hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_TURN, 0)),
        "tavern_spells_cast_this_game": int(
            hero.get(GameTag.TAVERN_SPELLS_CAST_THIS_GAME, 0)),
        "minions_sold_this_turn": int(
            hero.get(GameTag.MINIONS_SOLD_THIS_TURN, 0)),
        "blood_gem_atk_bonus": int(
            hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0)),
        "blood_gem_health_bonus": int(
            hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0)),
        "next_spell_cost_reduction": int(
            hero.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0)),
    }


def _extra_powers(game: Game, hero: Hero) -> List[Dict[str, Any]]:
    """主槽 + 第二槽英雄技能状态（费用/次数/是否被动/是否需要目标）。"""
    from hsrl2.scripts import REGISTRY
    powers: List[Dict[str, Any]] = []
    try:
        pids = list(game.hero_power_ids(hero))
    except Exception:                                     # noqa: BLE001
        pids = []
    for idx, pid in enumerate(pids):
        pdef = game.hero_power_def_for(hero, pid)
        script = REGISTRY.get(pid) or (
            REGISTRY.get(pdef.id) if pdef is not None else None)
        try:
            cost = int(game.hero_power_cost(hero, pdef, script)) \
                if pdef is not None else 0
        except Exception:                                 # noqa: BLE001
            cost = 0
        max_uses = int(getattr(script, "uses_per_turn", 1)
                       + hero.extra_trigger("hp_uses"))
        uses_left = max(0, max_uses - int(
            hero._power_uses_this_turn.get(pid, 0)))
        per_game = getattr(script, "uses_per_game", None)
        game_uses_left = None
        if per_game is not None:
            game_uses_left = max(0, int(per_game) - int(
                hero._power_uses_this_game.get(pid, 0)))
        powers.append({
            "slot": idx,
            "power_id": pid,
            "cost": cost,
            "uses_left_this_turn": uses_left,
            "uses_per_turn": max_uses,
            "uses_left_this_game": game_uses_left,
            "passive": bool(getattr(script, "passive", False)),
            "needs_target": bool(getattr(script, "needs_target", False)),
            "target_count": int(getattr(script, "target_count", 1)),
        })
    return powers


def _extra_dark_gift(game: Game, hero: Hero) -> Dict[str, Any]:
    """S14 黑暗赠礼：是否开启/费用/剩余次数/本回合已用。"""
    st = game.dark_gift_state.get(hero)
    return {
        "enabled": int(game.turn) >= int(C.DARK_GIFT_START_TURN),
        "cost": int(C.DARK_GIFT_COST),
        "uses_left": int(C.DARK_GIFT_USES_PER_GAME
                         if st is None else st.get("uses_left", 0)),
        "used_this_turn": False if st is None else bool(
            st.get("used_this_turn", False)),
    }


def _extra_quest(game: Game, hero: Hero) -> Optional[Dict[str, Any]]:
    """任务：卡 id / 进度 / 目标 / 是否完成 / 奖励 id。"""
    q = getattr(hero, "quest", None)
    if q is None:
        return None
    return {
        "card_id": str(getattr(q, "card_id", "")),
        "progress": int(getattr(hero, "_quest_progress", 0)),
        "target": int(game.quest_target(hero)),
        "completed": bool(getattr(hero, "_quest_completed", False)),
        "reward_ids": [str(getattr(r, "card_id", ""))
                       for r in getattr(hero, "quest_rewards", [])],
        "pending_reward_id": getattr(hero, "_quest_reward_id", None),
    }


def _extra_trinkets(hero: Hero) -> List[Dict[str, Any]]:
    """饰品卡 id + 计数器状态（Avenge/Lockbox/Activate）。"""
    trinkets: List[Dict[str, Any]] = []
    for t in getattr(hero, "trinkets", []):
        counters: Dict[str, int] = {}
        for tag, name in ((GameTag.AVENGE_COUNTER, "avenge_counter"),
                          (GameTag.LOCKBOX_TURNS_LEFT, "lockbox_turns_left"),
                          (GameTag.ACTIVATE_USED_THIS_TURN,
                           "activate_used_this_turn")):
            try:
                if t.has(tag):
                    counters[name] = int(t.get(tag, 0))
            except Exception:                             # noqa: BLE001
                continue
        trinkets.append({"card_id": str(getattr(t, "card_id", "")),
                         "counters": counters})
    return trinkets


def _board_states(arr: Any) -> List[Dict[str, Any]]:
    """随从临时状态（EntityToken 无法表达的 tag 位）。"""
    states: List[Dict[str, Any]] = []
    for m in arr:
        try:
            states.append({
                "entity_id": _entity_uuid_int(m),
                "card_id": str(getattr(m, "card_id", "")),
                "zone_position": int(m.get(GameTag.ZONE_POSITION, 0)),
                "exhausted": bool(m.has(GameTag.EXHAUSTED)),
                "frozen": bool(m.has(GameTag.FROZEN)),
                "activate_used_this_turn": bool(
                    m.has(GameTag.ACTIVATE_USED_THIS_TURN)),
                "windfury_attacks": int(
                    m.get(GameTag.WINDFURY_ATTACKS, 0)),
                "divine_shield_hits": int(
                    m.get(GameTag.DIVINE_SHIELD_HITS, 0)),
                "venomous_consumed": bool(
                    m.has(GameTag.VENOMOUS_CONSUMED)),
            })
        except Exception:                                 # noqa: BLE001
            continue
    return states


def _hand_states(arr: Any) -> List[Dict[str, Any]]:
    states: List[Dict[str, Any]] = []
    for e in arr:
        try:
            states.append({"entity_id": _entity_uuid_int(e),
                           "card_id": str(getattr(e, "card_id", "")),
                           "locked_in_hand": bool(
                               e.has(GameTag.LOCKED_IN_HAND))})
        except Exception:                                 # noqa: BLE001
            continue
    return states


def _hero_ref(h: Any) -> Optional[Dict[str, Any]]:
    if h is None:
        return None
    return {"hero_id": str(getattr(h, "card_id", "")),
            "name": str(getattr(h, "name", "") or ""),
            "health": int(getattr(h, "health", 0) or 0),
            "alive": bool(getattr(h, "is_alive", False))}


def build_extra_state(
        game: Game,
        hero: Hero,
        *,
        zones: Optional[driver.Zones] = None,
        lobby_heroes: Optional[Sequence[Hero]] = None,
        eliminated_rank: Optional[Dict[int, int]] = None,
        turn_stats: Optional[Dict[str, int]] = None,
        env_stats: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """观测契约 v2 ``extra`` 的**唯一数据源**（同时供 ``info["obs_extra"]``）。

    纯数据（可 pickle、无引擎对象），只读：不修改引擎状态、不消耗 RNG。
    键集合（与 ``docs/ENV_INTERFACE_GAPS.md`` §A2 一致）：

    - 英雄标量: ``frozen_tavern, free_refresh_left, health_refreshes_left,
      refresh_cost, gold_spent_this_turn, cards_played_this_turn,
      tavern_spells_cast_this_turn/_game, minions_sold_this_turn,
      blood_gem_atk_bonus, blood_gem_health_bonus, next_spell_cost_reduction``
    - 技能: ``powers``（列表，含主/副槽）+ ``power_uses_left``（dict）+
      ``second_power_id/second_power_cost/second_power_uses_left``
    - Dark Gift: ``dark_gift`` + ``dark_gift_uses_left``
    - 任务: ``quest``（或 None）+ ``quest_progress/quest_target/
      quest_completed/quest_reward_ids``
    - 饰品: ``trinkets`` + ``trinket_ids``
    - 随从临时状态: ``board_states/hand_states`` + ``minion_flags``
      （entity_id → 标志 dict，含 locked_in_hand）
    - 等待队列: ``pending_hand_queue``（数量）+ ``pending_hand_card_ids``
    - 对手身份（官方 HUD 可见）: ``next_opponent/last_opponent``（hero_id str）
      + ``next_opponent_info/last_opponent_info``（详情 dict）
    - 大厅公开: ``elimination``（含名次）+ ``elimination_order``（先淘汰先出）
    - 战斗: ``last_combat``（**只有己方**本场/上回合战斗摘要，避免隐藏信息）
    - 己方死亡计数: ``deaths_by_card_id``
    - 统计: ``turn_stats/env_stats``（调用方提供时）
    """
    if zones is None:
        zones = driver.collect_zones(game, hero)
    if lobby_heroes is None:
        lobby_heroes = list(game.heroes)
    if eliminated_rank is None:
        eliminated_rank = {}

    extra: Dict[str, Any] = {"version": ENTITY_TOKEN_VERSION,
                             "turn": int(game.turn)}
    extra.update(_extra_hero_state(game, hero))
    powers = _extra_powers(game, hero)
    extra["powers"] = powers
    extra["power_uses_left"] = {str(p["power_id"]):
                                int(p["uses_left_this_turn"])
                                for p in powers}
    second = powers[1] if len(powers) > 1 else None
    extra["second_power_id"] = str(second["power_id"]) if second else ""
    extra["second_power_cost"] = int(second["cost"]) if second else -1
    extra["second_power_uses_left"] = int(
        second["uses_left_this_turn"]) if second else 0
    dark_gift = _extra_dark_gift(game, hero)
    extra["dark_gift"] = dark_gift
    extra["dark_gift_uses_left"] = int(dark_gift["uses_left"])
    quest = _extra_quest(game, hero)
    extra["quest"] = quest
    extra["quest_progress"] = int(quest["progress"]) if quest else 0
    extra["quest_target"] = int(quest["target"]) if quest else 0
    extra["quest_completed"] = bool(quest["completed"]) if quest else False
    extra["quest_reward_ids"] = list(quest["reward_ids"]) if quest else []
    trinkets = _extra_trinkets(hero)
    extra["trinkets"] = trinkets
    extra["trinket_ids"] = [t["card_id"] for t in trinkets]
    board_states = _board_states(zones.board)
    hand_states = _hand_states(zones.hand)
    extra["board_states"] = board_states
    extra["hand_states"] = hand_states
    minion_flags: Dict[int, Dict[str, Any]] = {}
    for st in board_states:
        minion_flags[int(st["entity_id"])] = {
            k: v for k, v in st.items()
            if k not in ("entity_id", "card_id")}
    for st in hand_states:
        minion_flags[int(st["entity_id"])] = {
            "locked_in_hand": bool(st["locked_in_hand"])}
    extra["minion_flags"] = minion_flags
    queue = [(h, e) for (h, e) in getattr(game, "pending_hand_queue", [])
             if h is hero]
    extra["pending_hand_queue"] = len(queue)
    extra["pending_hand_card_ids"] = [
        str(getattr(e, "card_id", "")) for (_h, e) in queue]
    try:
        next_ref = _hero_ref(game.next_opponent(hero))
    except Exception:                                     # noqa: BLE001
        next_ref = None
    try:
        last_ref = _hero_ref(game.last_opponent(hero))
    except Exception:                                     # noqa: BLE001
        last_ref = None
    extra["next_opponent"] = next_ref["hero_id"] if next_ref else None
    extra["next_opponent_info"] = next_ref
    extra["last_opponent"] = last_ref["hero_id"] if last_ref else None
    extra["last_opponent_info"] = last_ref
    eliminated: List[Dict[str, Any]] = []
    for h in lobby_heroes:
        r = eliminated_rank.get(id(h))
        if r:
            eliminated.append({"hero_id": str(getattr(h, "card_id", "")),
                               "name": str(getattr(h, "name", "") or ""),
                               "rank": int(r)})
    eliminated.sort(key=lambda x: -x["rank"])   # 先淘汰（名次大）在前
    extra["elimination"] = eliminated
    extra["elimination_order"] = [e["hero_id"] for e in eliminated]
    # 战斗结果：官方只对玩家展示**自己**的战斗；不透出他人战斗细节
    try:
        results = dict(getattr(game, "_last_combat_results", {}) or {})
    except Exception:                                     # noqa: BLE001
        results = {}
    res = results.get(hero)
    extra["last_combat"] = (None if res is None else {
        "winner": getattr(getattr(res, "winner", None), "name", None),
        "loser": getattr(getattr(res, "loser", None), "name", None),
        "damage_dealt": int(getattr(res, "damage_dealt", 0) or 0),
        "capped_damage": int(getattr(res, "capped_damage", 0) or 0),
        "rounds": int(getattr(res, "rounds", 0) or 0),
    })
    extra["deaths_by_card_id"] = {
        str(k): int(v) for k, v in
        dict(getattr(hero, "deaths_by_card_id", {}) or {}).items()}
    if turn_stats is not None:
        extra["turn_stats"] = dict(turn_stats)
    if env_stats is not None:
        extra["env_stats"] = dict(env_stats)
    return _plain_extra(extra)

def build_observation(
        game: Game,
        hero: Hero,
        candidates: Sequence[CandidateAction],
        *,
        phase: str = PHASE_RECRUIT,
        pending: Optional[PendingChoice] = None,
        zones: Optional[driver.Zones] = None,
        lobby_heroes: Optional[Sequence[Hero]] = None,
        eliminated_rank: Optional[Dict[int, int]] = None,
        total_players: Optional[int] = None,
        turn: Optional[int] = None,
        log: str = "",
        extra: Optional[Dict[str, Any]] = None) -> Observation:
    """构建一步观测（槽位与 ``candidates`` 使用同一份 ``zones``）。

    ``extra``: 观测 v2 的决策状态袋；调用方（``game_env``）传入自己的
    ``extra_state()`` 以保证与 ``info["obs_extra"]`` **同源**；独立使用本
    函数时自动调用 :func:`build_extra_state` 构建（同样为纯数据）。
    """
    if zones is None:
        zones = driver.collect_zones(game, hero)
    if lobby_heroes is None:
        lobby_heroes = list(game.heroes)
    if eliminated_rank is None:
        eliminated_rank = {}
    total = int(total_players if total_players is not None
                else len(lobby_heroes))
    alive_count = sum(1 for h in lobby_heroes if h.is_alive)
    rank = estimate_rank(hero, lobby_heroes, eliminated_rank)

    board = tuple(_token_from_minion(game, m, ZONE_BOARD, i)
                  for i, m in enumerate(zones.board))
    hand = tuple(entity_token(game, e, zone=ZONE_HAND, slot=i)
                 for i, e in enumerate(zones.hand))
    tavern = tuple(entity_token(game, e, zone=ZONE_TAVERN, slot=i)
                   for i, e in enumerate(zones.tavern))
    trinkets = tuple(entity_token(game, e, zone=ZONE_TRINKET, slot=i)
                     for i, e in enumerate(zones.trinkets))
    opponent = tuple(entity_token(game, m, zone=ZONE_OPPONENT, slot=i)
                     for i, m in enumerate(zones.opponent_board))
    quest = None
    if getattr(hero, "quest", None) is not None:
        quest = entity_token(game, hero.quest, zone=ZONE_QUEST, slot=0,
                             force_card_type=CARD_TYPE_QUEST)

    pending_tok = _pending_token(game, hero, pending) if pending is not None \
        else None
    if pending is not None and phase == PHASE_RECRUIT:
        phase = PHASE_CHOICE

    if extra is None:
        extra = build_extra_state(
            game, hero, zones=zones, lobby_heroes=lobby_heroes,
            eliminated_rank=eliminated_rank)
    else:
        # 传入的 dict 可能是调用方复用/可变对象 → 深拷贝纯数据，保证
        # 每个 Observation 的 extra 相互独立且不含引擎对象
        extra = _plain_extra(extra)
    return Observation(
        version=ENTITY_TOKEN_VERSION,
        turn=int(turn if turn is not None else game.turn),
        phase=phase,
        hero=_hero_token(game, hero, zones, candidates),
        board=board,
        hand=hand,
        tavern=tavern,
        trinkets=trinkets,
        quest=quest,
        opponent_board=opponent,
        lobby=_lobby(game, hero, lobby_heroes, eliminated_rank),
        alive_count=alive_count,
        total_players=total,
        rank=rank,
        pending_choice=pending_tok,
        candidates=tuple(candidates),
        extra=extra,
        log=log,
    )
