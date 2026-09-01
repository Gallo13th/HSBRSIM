"""final_unfreeze 尾批 — 解冻 3 张（作业单 2026-08-23）+ 数据化核实。

解冻依据（引擎原语已就绪，EFFECT_SCRIPT_SOP §9/§10 后收口）:
  - combat._execute_attack 的 after_attack 事件携带 excess_damage /
    defender_hp_before（combat.py:287-293——batch_counters DEFERRED 台账
    BGS_126 的既定依赖，主线已交付）
  - game.buy_from_tavern 对法术实体 fire spell_bought(spell=, hero=)
    （game.py:375-378——BG33_891 的既定依赖）
  - game._magnetic_valid 对 BG_DEEP_015(_G) 数据化扩展 UNDEAD
    （game.py:671-686——BG_DEEP_015 无需脚本）

数据核实（data/bg_cards.json 36.2.2 + wiki 双源）:
  BGS_126 Wildfire Elemental 6/3 T3; 金色 id = TB_BaconUps_166
            （db.golden_version 链 triple_upgrade_id 64190; 文本
            "...to both adjacent enemies."——行为差异金色分支）
  BG33_891 Magicfin Mycologist 4/8 T6; num(0) 即 script_data_num_1:
            基础 1（"Once per turn"）/ 金色 BG33_891_G 2（"Twice"）
            token = BG33_890t Magicfin Apprentice 1/1 Murloc T1
            （wiki Related cards 权威; "Battlecry: This casts another
            card. (This minion can't be tripled.)"; 非池卡——引擎
            check_for_triple 对非 is_pool_minion 天然不三连）
  BG_DEEP_015 Prosthetic Hand 3/1 T3; keywords 含 magnetic/reborn
            （引擎自动; 本批不注册，仅测试验证）
  纯关键词卡 BG25_001 (taunt+reborn) / BG_BOT_911 (magnetic+DS+taunt) /
  BGS_119 (DS+windfury) / BGS_131 (venomous): 数据齐全引擎自动，
  不注册，测试验证; BG26_175 三连引擎内建（game.py check_for_triple
  SUB_CARD 段，test_engine_primitives 已覆盖）。

Magicfin teach 语义裁定（wiki 双页核实，2026-08-23）:
  - Mycologist 页: Wiki tags 含 [Battlecry-generating]——"get a 1/1
    Murloc and teach it that spell" = 生成 Magicfin Apprentice token，
    法术由 token 的**战吼**施放（"This casts another card"）
  - 35.2.0 hotfix（2026-04-20）: 金色 Mycologist 每次购买只消耗一个
    充能——per-buy 增量 1 实现
"""

from __future__ import annotations

from hsrl2.actions import Hit
from hsrl2.events import Listener
from hsrl2.game import PendingChoice
from hsrl2.minion import Minion
from hsrl2.tags import GameTag

# Magicfin Apprentice token（wiki Related cards + bg_cards.json 双核实;
# 非池卡不占池，tech_level=1 不入 check_for_triple）
_MAGICFIN_APPRENTICE = "BG33_890t"


def _corpse_adjacent_enemies(defender: Minion) -> list:
    """after_attack 时点死者相邻存活随从（死者控制者一侧）。

    死亡波次已离场让位（RULES §6.9: 板缝合右侧左移）:
      - 无补位: 让出板位 pos 的左邻 = 现板 pos-1、原右邻 = 现板 pos
      - 亡语召唤填位: 填位者占据 pos——取现板相邻两槽
    两种形态统一为"死者让出板位的相邻两槽"（pos-1 与 pos）。

    Evidence（2026-08-23 查证）: hearthstone.wiki.gg/wiki/
    Battlegrounds/Wildfire_Elemental——Wiki tags [Random] +
    [Positional effect]（27.2.0 文本删 "random" 后 tag 维护如故 →
    相邻二选一为随机选取）; 文本史 36.2.0 "an adjacent enemy"、金色
    "both adjacent"（金色 id TB_BaconUps_166 双侧）。多召唤挤位
    （2+ 填位）的相邻槽 = RULES §6.9 亡语召唤填位规则的推论（填位者
    占死者板位，其物理相邻即"死者的相邻"）——卡页无 Notes（全文
    核对），推论依据 RULES §6.9。
    """
    hero = getattr(defender, "controller", None)
    board = hero.board if hero is not None else []
    if defender in board:
        # 防御分支: 复生回归等（引擎该路径 excess=0 不可达，双保险）
        pos = defender.zone_position
        return [m for m in board
                if m is not defender and not m.dead
                and abs(m.zone_position - pos) == 1]
    pos = defender.get(GameTag.ZONE_POSITION, 0)   # 让出板位残值
    return [m for m in board
            if not m.dead and m.zone_position in (pos - 1, pos)]


# ══════════════════ 1. BGS_126 Wildfire Elemental ══════════════════


class WildfireElementalScript:
    """
    Natural language: After this attacks and\\nkills a minion, deal\\nexcess
    damage to an adjacent enemy.（金色 TB_BaconUps_166: After this attacks
    and kills a minion, deal excess damage to **both adjacent enemies**.）

    Formal spec:
      1. on_summon 注册 after_attack Listener（owner=source，离场注销/
         战斗快照恢复——引擎生命周期契约）
      2. 命中: attacker is source 且 excess_damage > 0（引擎 excess =
         宣告攻击力 − 受击前血量，仅击杀且有余量时 > 0——combat.py
         C4 契约; 圣盾抵消/剧毒无余量均自然为 0）
       3. 目标 = 死者让出板位的相邻存活敌人（_corpse_adjacent_enemies，
          Evidence 见该函数 docstring: wiki Wiki tags [Random]/
          [Positional effect]）——基础版 rng.choice 随机其一，
          金色版两者皆中（金色文本 "both" 字面量，is_golden 分支）
      4. Hit(target, excess_damage, source=source)——走圣盾/亡语/死亡
         波次; 效果伤害不触发剧毒（Hit Action 契约）
      5. 引擎语义备案（非本卡缺陷）: 防御者复生回归时 after_attack
         读到存活 → excess_damage=0 不触发（"attacks and kills" 的
         复生边缘）; 反击致死 source（监听器已随死亡注销）不触发
         ——两者均为官方"死亡触发器不结算"方向一致

    Test: test_batch_final_unfreeze.py::TestWildfireElemental — 5 攻
    2 血 → 相邻吃 3 超额 / 金色双侧 / 恰好击杀与未击杀负例 / 他人
    攻击不触发 / 单邻位确定性

    Params: 无模板参数（excess 运行时计算; "both" 为金色文本行为差异）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        def on_after_attack(g, attacker=None, defender=None,
                            excess_damage=0, defender_hp_before=None,
                            **kw):
            if attacker is not source or excess_damage <= 0:
                return
            if not isinstance(defender, Minion):
                return
            enemies = _corpse_adjacent_enemies(defender)
            if not enemies:
                return
            if source.is_golden:
                targets = enemies
            else:
                targets = [g.rng.choice(enemies, label="wildfire_excess")]
            g.run_actions([Hit(t, excess_damage, source=source)
                           for t in targets])

        game.events.register(Listener(
            event="after_attack", owner=source,
            callback=on_after_attack))
        return None


# ══════════════════ 2. BG33_891 Magicfin Mycologist ══════════════════


class MagicfinMycologistScript:
    """
    Natural language: [x]Once per turn, after you\\nbuy a Tavern spell,
    get a\\n1/1 Murloc and teach\\nit that spell. <i>({0} left!)</i>
    （金色 BG33_891_G: **Twice** per turn, ...）

    Formal spec:
      1. on_summon 注册 spell_bought Listener（owner=source; 事件由
         buy_from_tavern 对法术实体 fire——购买路径唯一，施放/获取
         不触发，game.py:375-378 契约）
      2. 命中: hero is source.controller 且本回合规程未满——计数记于
         source 实体属性 _magicfin_used=(turn, used)（回合戳惰性重置，
         Lava Lurker 同款; 多个 Mycologist 各自独立计程）
      3. 效果: create_minion(BG33_890t)（1/1 Murloc token，非池不占
         池）→ "teach" = token._taught_spell_id = spell.card_id
         （MagicfinApprenticeScript 消费）→ pending_hand_add（"get"
         进手牌，满手排队 RULES §3.3; token 非池卡不触发三连）
      4. 金色 num(0)=2 自然体现; 每次购买消耗一个充能（35.2.0
         hotfix: 金色不再一次买双耗）
      5. 购买随从不触发（spell_bought 仅法术路径 fire——引擎保证，
         测试负例）

    Test: test_batch_final_unfreeze.py::TestMagicfinMycologist — 购买
    得 1/1 学徒+法术标记 / 同回合限一次 / 跨回合重置 / 金色两次 /
    买随从不触发 / 双 Mycologist 独立计程

    Params: {0}=1（BG33_891 每回合规程）; 金色 {0}=2（BG33_891_G）
    """

    @staticmethod
    def on_summon(source, game, ctx):
        limit = game.db.get(source.card_id).num(0)

        def on_spell_bought(g, spell=None, hero=None, **kw):
            ctrl = source.controller
            if ctrl is None or hero is not ctrl:
                return
            used_turn, used = getattr(source, "_magicfin_used",
                                      (None, 0))
            if used_turn != g.turn:
                used_turn, used = g.turn, 0
            if used >= limit:
                return
            source._magicfin_used = (g.turn, used + 1)
            token = g.create_minion(_MAGICFIN_APPRENTICE, controller=ctrl)
            token._taught_spell_id = spell.card_id
            g.pending_hand_add(ctrl, token)

        game.events.register(Listener(
            event="spell_bought", owner=source,
            callback=on_spell_bought))
        return None


class MagicfinApprenticeScript:
    """
    Natural language: <b>Battlecry:</b> This casts another card.
    <i>(This minion can't be tripled.)</i>（BG33_890t token;
    36.2.2 数据文本 "This casts {0}"——{0} 为运行时注入的被教法术名）

    Formal spec:
      1. battlecry: 读实体属性 _taught_spell_id（Mycologist teach
         写入; 无标记 → 战吼落空——token 恒经 Mycologist 生成，防御）
      2. create_spell(被教法术) 直施（Cagey Conjurer 直施先例: 不占
         池、不入手、不计 TAVERN_SPELLS_CAST——非购买施放）; fire
         spell_resolving(spell=, target=, cast_no=0) 后跑 on_play
         （引擎 _finish_play_spell 同口径——Proud Privateer Bounty
         双施/Lava Lurker 永久化拦截器照常工作）
      3. 定向法术: PendingChoice(kind="spell_target")，候选 = 友方
         存活随从（play_spell 默认同构; 含 token 自身——引擎官方
         战吼可自指）; 无候选 → 落空; Choose One 法术: 其脚本自队
         选择（batch_spells4 协议）
      4. "can't be tripled": 引擎 check_for_triple 对非 is_pool_minion
         天然跳过——数据通道，无需脚本
      5. Brann/金色战吼双倍由引擎 play_minion 处理（battlecry 关键
         词在册）→ 被教法术施放两次

    Test: test_batch_final_unfreeze.py::TestMagicfinApprentice — 直施
    Shiny Ring 全体+1/+1 / 定向 Sacred Gift 选择目标得圣盾 / 三学徒
    不三连 / 无标记落空

    Params: 无模板参数（{0} 为运行时被教法术名，非卡面数值）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        taught_id = getattr(source, "_taught_spell_id", None)
        hero = source.controller
        if taught_id is None or hero is None:
            return None
        spell = game.create_spell(taught_id, controller=hero)
        script = spell.scripts

        def cast(target=None):
            spell_ctx = {"target": target} if target is not None else {}
            game.events.fire(game, "spell_resolving", spell=spell,
                             target=target, cast_no=0)
            game.run_actions(spell.call_script("on_play", spell_ctx))

        if script is not None and getattr(script, "needs_target", False):
            cand_fn = getattr(script, "target_candidates", None)
            candidates = (list(cand_fn(spell, game))
                          if cand_fn is not None
                          else [m for m in hero.board if not m.dead])
            if not candidates:
                return None          # 无候选 → 落空（play_spell 同构）
            game.pending_choices.append(PendingChoice(
                hero, candidates, "spell_target",
                resolve_callback=lambda pick: cast(pick)))
            return None
        cast()
        return None


# ══════════════════ 注册 ══════════════════


def register() -> list[str]:
    """注册本批次全部脚本（含金色 id），返回注册的 card_id 列表。

    不注册（数据/引擎通道核实，测试验证）:
      BG_DEEP_015(_G) Prosthetic Hand — Magnetic/Reborn 关键词 +
        _magnetic_valid UNDEAD 扩展均引擎数据化
      BG25_001 / BG_BOT_911 / BGS_119 / BGS_131 — 纯关键词卡
      BG26_175 Elemental of Surprise — 三连引擎内建
    """
    from hsrl2.scripts.registry import register as _register

    registered: list[str] = []

    def _add(card_id: str, script_cls) -> None:
        _register(card_id, script_cls)
        registered.append(card_id)

    _add("BGS_126", WildfireElementalScript)
    _add("TB_BaconUps_166", WildfireElementalScript)   # 金色: both 相邻
    _add("BG33_891", MagicfinMycologistScript)
    _add("BG33_891_G", MagicfinMycologistScript)       # 金色 num(0)=2
    _add(_MAGICFIN_APPRENTICE, MagicfinApprenticeScript)   # token 战吼
    return registered
