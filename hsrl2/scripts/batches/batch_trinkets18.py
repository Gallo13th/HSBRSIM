"""批次 trinkets18 — 饰品第 18 批（台账 `docs/agents/TRINKET_LEDGER.md` 片 6/7 子集，20 张）。

本批 20 个 id 与 batch_trinkets1..17 的 id 集合互不相交；数值一律
`CardDef.num(0/1)`，金色走 `db.golden_version`，随机一律 `game.rng`
（`rng.choice` / `rng.sample`），无 `import random`。

注册 13 张饰品 + 1 张 Spellcraft 法术（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG35_MagicItem_435  Bloodbound Ring      — 手牌打出鲜血宝石后，本饰品
                                             对本人带圣盾的随从各打一颗宝石
  BG35_MagicItem_701  Fang Anklet          — SoC: 本人野兽 +X/+Y（本场战斗）;
                                             每召唤一只野兽永久提升 X/Y
  BG35_MagicItem_712  Privateer Portrait   — Get a Proud Privateer + num(0)
                                             张随机 Bounty; 每回合再来 num(0) 张
  BG35_MagicItem_714  Powder Keg           — SoC: 随机 num(0) 只友方海盗获得
                                             「亡语: 召唤 1/1 Sky Pirate，赋予
                                             其本随从攻击力，并立即攻击」
  BG35_MagicItem_733  Jailer Sticker       — Spellcraft: Destroy a friendly
                                             Undead to get 2 random Undead
  BG35_MagicItem_733t （同上的法术本体）
  BG35_MagicItem_740  Sky Golem Portrait   — Get a Falling Sky Golem;
                                             SoC: 本人随从获得「亡语: 使你的
                                             随从永久 +num(0)/+num(1)」
  BG35_MagicItem_741  Beatboxer Portrait   — Get a Polarizing Beatboxer
  BG35_MagicItem_742  Accord-o-Tron Portrait — EoT: 把一张 Accord-o-Tron 磁力
                                             吸附到本人最左与最右的机械上
  BG35_MagicItem_750  Magicfin Sticker     — 每次购买酒馆法术（每回合 num(0)
                                             次）得 1/1 Murloc 并"教会"该法术
  BG35_MagicItem_753  Murky Sticker        — EoT: 最左两只随从 +base×
                                             (1+本局战吼数)
  BG35_MagicItem_754  Dramaloc Sticker     — SoC: 本人鱼人获得手牌中最高攻击
                                             随从的攻击力
  BG35_MagicItem_803  Maxwell Sticker      — Get the Buddy of your Hero Power
  BG35_MagicItem_817  Lens Case            — Get a Duplicating Lens; 每 num(1)
                                             回合开始再来一张

DEFERRED 6 张（**不注册**；逐张给出缺失依赖与实现路径——SOP §6b 二态铁律）
═══════════════════════════════════════════════════════════════════════
  - BG35_MagicItem_702 Stegodon Portrait — "Get a Stomping Stegodon. SoC:
    Give your two left-most Beasts Divine Shield."
    Dependency: **关联卡数据链缺失**。XML 实体（`hsdata/CardDefs.xml`
    L245446-245478, dbf 130897）除 `START_OF_SOCIAL`/`BACON_SUBSET_BEAST`
    外**没有** `BACON_EVOLUTION_CARD_ID`(2519) / `BACON_CARD_DBID_REWARD`
    等任何关联卡 tag（同批 712/740/741/742/750/812/817 均有 2519，可对照）
    → `game.trinket_related_card` 恒 None，RULES §7.4.6 的 CORRECT 判据
    (a)「关联卡定义经数据链正确解析」不成立。被点名卡在 db 中确为
    `BG33_840` "Stomping Stegodon"（`is_pool_minion=False` 池外卡），但
    **禁止从卡名猜测 id**（SOP §11 item 5）。
    实现路径: 生成器/数据层为该卡补 `evolution_card_id`（或主线裁定
    引擎按唯一卡名回退解析）后，on_bind 交付白板副本（池外卡零池操作）+
    SoC 给最左两只野兽 `GainKeyword(DIVINE_SHIELD)`。
    Status: 已由 batch_trinkets25 注册（关联卡数据链缺失以唯一名回退解析，2026-09-02 落地）
  - BG35_MagicItem_713 Trusty Crowbar — "Whenever you get a Pirate, give
    your left-most minion +num(0)/+num(1)."（num=12/12）
    已由 `batch_trinkets23` 注册（本条保留历史台账）。原 Dependency
    **无 hero 级"获得卡牌"事件**已解除: 引擎 `hero.add_to_hand` 现 fire
    `card_gained(hero=, card=)`（RULES §7.4.6b），实现见
    `batch_trinkets23.TrustyCrowbarScript`；原先只覆盖购买/发现的
    `minion_bought`/`spell_bought`/`card_discovered` 已不再是唯一信号。
  - BG35_MagicItem_732 Soul Fermenter — "SoC: Destroy your 3 left-most
    minions. After your last minion dies, resummon them."
    Dependency: **"你的最后一只随从死亡"触发点缺失**。引擎只有逐次 DEATH
    事件（`_process_death_inner`），无"该次死亡后己方棋盘为空"的官方
    结算时点/顺序权威；且"resummon them"需要战前 3 只的属性快照 +
    战斗内召唤回放协议（`game.combat_death_log` 只记录实体，无 max-stats
    快照字段）。同一缺口已由 batch_trinkets16 对 `BG32_MagicItem_907`
    （"After your last minion dies each combat…"）逐条备案。
    实现路径: 引擎提供"最后随从死亡"钩子（DEATH 结算尾部 + 己方棋盘空
    判定）与战斗内 max-stats 快照 API 后，SoC 记录 3 只快照并消灭之
    （`HEALTH=0` + `check_deaths`），再在钩子内按快照重召。
  - BG35_MagicItem_743 Electrode Attractor — "Magnetic Mechs cost (2).
    The Tavern offers an extra one whenever it is Refreshed."
    Dependency: (a) 价格侧 `GameTag.TAVERN_MINION_COST_OVERRIDE` 是
    **hero 级无条件**平价覆写（Sindragosa/Millhouse），无"仅 Magnetic
    Mech"限定；脚本侧只能在 `tavern_refresh` 后给馆内实体逐个写
    `COST=2`——非刷新路径入馆的磁力机械（Toki/Tess/Varden 注入、
    Golden Touch 等）会漏价，属近似（SOP §6b 禁止）。(b) 额外展示位
    `TAVERN_OFFER_MOD` 是**通用**展示位数，`refresh_tavern` 的抽取
    （`minion_pool.draw_tavern`）只支持种族白名单，无"额外的这一张必须
    是 Magnetic Mech"的关键词限定抽取点（手写候选采样会绕过池权重）。
    实现路径: 引擎增 `hero._tavern_keyword_only`（本次刷新的关键词白名单）
    或 `refresh_tavern(..., keyword=)` + 实体级条件报价（如
    `hero._minion_cost_keyword = (MAGNETIC, 2)`）后按 `num(0)=2` 实现。
  - BG35_MagicItem_755 Chillmere Mosaic — "Spellcraft: Refresh the Tavern
    with Battlecry minions. They cost (1)."（法术本体 `BG35_MagicItem_755t`）
    Dependency: **关键词限定刷新原语缺失**。`refresh_tavern` 支持
    `races=`（种族白名单）/`spells_only=`，无关键词白名单；"Refresh the
    Tavern **with Battlecry minions**"要求馆内全部展示项都带 BATTLECRY，
    脚本侧"先普通刷新再逐项替换"会重写引擎刷新语义（冻结保留集 / 金馆
    金色化 / Elven Elite 档位 / 池权重抽样 / `tavern_refresh` 标记），
    属近似（batch_spells_final `_refresh_tavern_of_type` 已把同类手写
    镜像收口回引擎，不得再开旁路）。"They cost (1)" 侧已就绪（实体级
    `COST` 被 `buy_from_tavern` 读取，game.py:504）。
    实现路径: `refresh_tavern(keyword_filter={BATTLECRY})`（抽取时按
    `CardDef.keywords` 过滤）+ 入馆实体写 `COST=1`。**载荷未就绪**
    （法术本体不可实现）→ 本饰品一并 DEFERRED（SOP §12 item 14）。
  - BG35_MagicItem_812 Corrupted Tome — "Get a Triple Prize. Whenever you
    would get a Triple Reward, get a Triple Prize instead."
    Dependency: (a) **三连奖励替换钩子缺失**: `_grant_triple_reward` 是
    引擎内部固定路径（直接 `Discover(kind="triple_reward")`），无
    `hero._triple_reward_override` 之类读取点，也没有可在奖励发放前
    拦截的事件（`card_discovered` 在选项结算后才广播）；(b) 授予物
    `BG35_MagicItem_812t` Triple Prize 的 "Discover a Tier 3 Darkmoon
    Prize" 依赖 **Darkmoon Prize 子系统**（RULES §11.4，全仓无 Prize
    候选表/结算实现）。
    实现路径: 引擎增三连奖励分支点（如
    `hero._triple_reward_card_id`，`check_for_triple` 读取并用
    `grant_card_copy_to_hand` 替代 Discover）+ Darkmoon Prize 候选池
    数据后，注册 `812` 与 `812t`。
  - BG35_MagicItem_818 Mysterious Orb — "Gain num(0)=10 Gold. Your next
    Trinket is a Lesser Trinket."
    Dependency: **"下一次饰品档位覆写"读取点缺失**。`_offer_trinkets(hero,
    kind)` 的 kind 由回合推导（T6→lesser / T9→greater，外加
    `hero._trinket_early` 提前档），无 `hero._next_trinket_kind` 之类
    覆写字段；脚本自行写字段属"写入后无人读取"的空转标记
    （audit_script_wiring W3，SOP §11 item 3）。金币半场（GainGold
    num(0)）已就绪但**不得单独注册**（整卡半实现 = 第三态）。
    实现路径: 引擎在 `_begin_recruit_for` 的 offer 判定处读取
    `hero._next_trinket_kind`（消费后清零）后，on_bind 写
    `GainGold(h, num(0))` + 该字段。

机制口径（本批实现所依赖的既有原语）
══════════════════════════════════════════════════════════════════════
  - 关联卡数据链: `CardDef.evolution_card_id` → `CardDB.by_dbf`
    （`game.trinket_related_card` / `grant_trinket_related_card`，
    RULES §7.4.6）。池随从/池法术按池占返，池外卡零池操作，满手排队。
  - "Get a X" 裁定（RULES §7.4.6）: 交付正确即 CORRECT；关联卡自身脚本
    未迁移只登记台账（见文末「关联卡台账」），**例外**是其行为被本卡
    引用时整卡 DEFERRED（本批 755 适用）。
  - 战斗内授予亡语 = **引擎原语** `game.grant_combat_deathrattle(
    hero, minion, extra_fn)`（2026-09-02 主线收口: `_script_overrides`
    链式包装 + `DEATHRATTLE` tag，追加效果返回的 Action(s) 与原生结果
    合并; 战后由 `run_combat` 的 finally 统一恢复，脚本**不需要**再挂
    `COMBAT_END` 清理监听）。
  - 立即攻击 = 本文件 `_immediate_attack`（`combat.execute_immediate_attack`
    完整单次攻击语义，RULES §4.4 嘲讽优先/潜行不可击；与
    batch_trinkets11 / batch_hero_combat3 同协议，本地实现以消除跨批
    私有符号依赖——batch_trinkets11 正由主线收口重写）。
  - 战斗期临时增益（"this combat"）= 普通 `Buff`；SoC 阶段在
    `run_combat` 战前快照**之内**，战后自动回滚（RULES §3.5；
    batch_trinkets11 TinyfinOnesie / HolyMallet 同口径）。
  - "永久" 战斗内增益 = 战内 `Buff` + `COMBAT_END`（复原之后广播）
    重放（Belcher Portrait 先例，batch_trinkets11）。
  - 手牌打出判别 = `CARD_PLAYED`（spell 路径在**效果结算后**广播，
    game.py `_finish_play_spell` 尾部；`PlayBloodGems` 直施路径不 fire）
    ——"from hand" 的精确判别点（batch_trinkets13 Surveyor Portrait 同源）。
  - 战吼本局计数 = hero `COUNTER_BATTLECRIES`（引擎在每次战吼触发时
    +1，Brann/金色双倍各计一次，game.py play_minion）——"你的本局战吼数"
    的既有权威读取点。
  - 血宝石 = `_gem_values`（`BG20_GEM.num + BLOOD_GEM_BONUS_*`）+
    `GEMS_PLAYED_ON` 记账 + `blood_gem_played` 广播（actions/bloodgem.py）。
  - Bounty = `bloodgem.random_bounty_card_id`（5 张 T3 池法术，
    **调用即占池**，池尽返回 None）。
  - 磁力吸附 = `game.attach_magnetic(hero, magnetic_minion, host)`
    （实体当前属性并入 + 关键词/亡语栈叠，RULES §6.14）。
  - Spellcraft: 饰品实体参与每回合生成（`spellcraft.generate_for_hero`
    扫描 `hero.trinkets`），脚本**不得**再写 start_of_turn 生成。
  - "left and right-most" 单实体去重（HolyMallet / BalefulIncense 先例）。

接线审计读取点（W1/W2/W3 核对）: 饰品仅定义 `on_bind` / `start_of_turn`
/ `end_of_turn` / `start_of_combat`（W1 白名单）；监听事件名均为引擎真实
fire: `card_played`（game.py:1231）、`summon`（game.py:1058）、
`combat_end`（game.py run_combat）、`spell_bought`（game.py:589）。
无 game 级私有标记（SOP §12 item 9）；脚本侧仅写 `source.*` 闭包/实体
属性（`_fang_anklet_improves` / `_sky_golem_pending` / `_lens_case_n`）。

关联卡台账（RULES §7.4.6——交付正确即 CORRECT，关联卡脚本状态另行跟踪）
══════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链 dbf → id） | 被授予卡脚本状态 |
  |---|---|---|
  | BG35_MagicItem_712 | 122520 → BG33_825 Proud Privateer（池 T5） | 已注册 |
  | BG35_MagicItem_733 | spellcraft 131134 → BG35_MagicItem_733t | **本批注册** |
  | BG35_MagicItem_740 | 130798 → BG35_342 Falling Sky Golem（池 T6） | 已注册 |
  | BG35_MagicItem_741 | 98713 → BG26_149 Polarizing Beatboxer（池 T7） | 已注册 |
  | BG35_MagicItem_742 | 98576 → BG26_147 Accord-o-Tron（池 T3） | 已注册 |
  | BG35_MagicItem_817 | 130853 → BG35_MagicItem_817t Duplicating Lens | **未迁移**（池外法术；"Choose a minion from Tier 3 or below. Get a plain copy of it." 的 Choose 目标域（友方/任意/含酒馆）与 "plain copy" 池记账口径需主线裁定——本饰品不依赖其行为，仅登记） |
  | BG35_MagicItem_750 | 122285 → BG33_890t Magicfin Apprentice (1/1 Murloc token) | 已注册（batch_final_unfreeze，消费 `_taught_spell_id`） |
"""

from __future__ import annotations

from typing import List, Optional

from hsrl2.actions import Buff, GainKeyword
from hsrl2.actions.bloodgem import (
    BLOOD_GEM_VARIANTS,
    PlayBloodGems,
    random_bounty_card_id,
)
from hsrl2.actions.discover import GetRandomMinion
from hsrl2.entity import Buff as Enchant
from hsrl2.events import (
    CARD_PLAYED,
    COMBAT_END,
    SPELL_BOUGHT,
    SUMMON,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.spellcraft import grant_spellcraft_spell
from hsrl2.tags import GameTag, Race

# ── 数据核实常量（CardDB 按名核实; SOP §11 教训 5——禁止凭记忆写 id）──

# 血宝石法术 id 集合（手牌打出判别用; bloodgem.BLOOD_GEM_VARIANTS 权威）
_BLOOD_GEM_IDS = frozenset(BLOOD_GEM_VARIANTS.values())

# Sky Pirate 1/1 召唤物（CardDB 按名核实: BGS_061t / 金色 TB_BaconUps_141t;
# batch_trinkets13 `_sky_pirate_ids` 同一 token 族）
_SKY_PIRATE_ID = "BGS_061t"

# Magicfin Apprentice 1/1 Murloc token（wiki Related cards + bg_cards.json
# 双核实; batch_final_unfreeze 同一 token，"teach" 协议消费方）
_MAGICFIN_APPRENTICE_ID = "BG33_890t"

# 种族匹配族（Amalgam ALL 视为匹配，RULES §8/§6.4 通用裁定）
_BEAST_RACES = (Race.BEAST, Race.ALL)
_PIRATE_RACES = (Race.PIRATE, Race.ALL)
_MECH_RACES = (Race.MECH, Race.ALL)
_MURLOC_RACES = (Race.MURLOC, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)


def _hero(ctx):
    return (ctx or {}).get("hero")


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即报错（禁止静默 0——P6 纪律）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _related_card(game, source):
    """`game.trinket_related_card` 数据链解析（RULES §7.4.6）。

    失败 → GameStateError（fail-loud，禁止近似——SOP §6b）。
    """
    card = game.trinket_related_card(source.card_id)
    if card is None:
        raise GameStateError(
            f"{source.card_id}: evolution_card_id broken data chain")
    return card


def _immediate_attack(game, hero, attacker: Minion) -> None:
    """让 attacker 立即对交战对手发起一次完整攻击（"It attacks immediately"）。

    目标选择依照 RULES §4.4 的公开规则（嘲讽强制优先，其余随机；潜行
    不可被攻击）——与引擎 `CombatScheduler._choose_target` 同一口径，以
    `game.rng` 复现; 完整单次攻击语义经 `combat.execute_immediate_attack`
    （SOP §10 原语: 双向同时伤害/圣盾/剧毒/死亡结算/AFTER_ATTACK 与轮转
    攻击同一路径）。

    0 攻随从不能发起攻击；战斗对未知/对手无存活随从 → 落空（落空不消耗
    任何资源）。
    """
    if attacker.dead or attacker.atk <= 0:
        return
    pair = getattr(game, "_active_combat", None)
    if not pair:
        return
    a, b = pair
    opponent = b if a is hero else a if b is hero else None
    if opponent is None:
        return
    living = [m for m in opponent.living_minions()
              if not m.has(GameTag.STEALTH)]
    if not living:
        return
    taunts = [m for m in living if m.taunt]
    defender = game.rng.choice(taunts or living,
                               label="powder_keg_target")
    from hsrl2.combat import execute_immediate_attack
    execute_immediate_attack(game, attacker, defender)


def _grant_bounties(game, hero, count: int) -> int:
    """入手 count 张随机 Bounty（`random_bounty_card_id` 调用即占池）。

    池内 Bounty 耗尽 → 剩余次数落空（已占池的份数不回滚——每张都是独立
    的一次"Get a random Bounty"，池空即无卡可得）。返回实际入手数。
    """
    granted = 0
    for _ in range(count):
        card_id = random_bounty_card_id(game)
        if card_id is None:
            break
        game.pending_hand_add(
            hero, game.create_spell(card_id, controller=hero))
        granted += 1
    return granted


# ══════════════ BG35_MagicItem_435 Bloodbound Ring ══════════════


class BloodboundRingScript:
    """
    Natural language: [x]After you play a <b>Blood Gem</b>
    from hand, this plays a
    <b>Blood Gem</b> on your minions
    with <b>Divine Shield</b>.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_435`（greater, cost 3,
    `subset_quilboar`; CardDef num(0)/num(1) 均 None——效果无数值参数）。
    wiki 页（Battlegrounds/Bloodbound_Ring）Wiki tags 只有 TRIGGER_VISUAL，
    无数值/目标歧义。

    Formal spec:
      1. on_bind 注册持久 `card_played` 监听（owner=饰品实体）: 引擎在
         `_finish_play_spell` **效果结算后**广播 `card_played(card=,
         target=)`（game.py:1231）——正是 "After you play ... from hand" 的
         时点；`PlayBloodGems` 直施路径**不 fire** 该事件，故 "from hand"
         天然被区分（batch_trinkets13 Surveyor Portrait 同源判别）
      2. 条件: `card` 是法术、`card.controller is 本人`、且
         `card.card_id ∈ BLOOD_GEM_VARIANTS.values()`（全部血宝石含 3 个
         变体——bloodgem 权威）
      3. 触发: 本人棋盘存活且带 `DIVINE_SHIELD` 的随从**各**打一颗
         vanilla 血宝石（`PlayBloodGems(minion, 1, source=饰品)`——数值走
         `_gem_values`（`BG20_GEM.num(0/1)` + `BLOOD_GEM_BONUS_*`），
         `GEMS_PLAYED_ON` 记账 + `blood_gem_played` 广播同手牌路径）
      4. 无圣盾随从 → 本次落空（不产生任何 Action）; 本人未打出宝石 →
         不触发（对手打宝石不触发本人饰品）
      5. 不递归: 本监听只认 `card_played`（法术实体），
         `PlayBloodGems` 产生的宝石不会再进该事件

    Test: test_batch_trinkets18.py — 真实 `play_spell` 手牌血宝石后，本人
      带圣盾随从各 +num(0)/+num(1)（期望值取自 `BG20_GEM` CardDef）而
      无圣盾随从不变（正对照）/ 直施 `PlayBloodGems` 不触发（"from hand"
      判别）/ 对手棋盘随从不变（owner 隔离）/ 本人无圣盾随从时落空
      （手牌宝石本身照常结算）

    Params: 无模板参数（CardDef num(0)/num(1) 均为 None；宝石数值来自
            `BG20_GEM` 与 hero 加成 tags）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, **kw):
            if not isinstance(card, Spell) or card.controller is not h:
                return
            if card.card_id not in _BLOOD_GEM_IDS:
                return
            targets = [m for m in _living(h)
                       if m.has(GameTag.DIVINE_SHIELD)]
            if not targets:
                return
            g.run_actions([PlayBloodGems(m, 1, source=source)
                           for m in targets])

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════ BG35_MagicItem_701 Fang Anklet ══════════════


class FangAnkletScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Your Beasts
    have +{0}/+{1} this combat.
    After you summon a Beast,
    improve this permanently.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_701`（greater, cost 3,
    num(0)=1 num(1)=1）。wiki 页 Wiki tags: `Increment attack` /
    `Increment health` / `Start of Combat` / `Summoning-related`——
    "improve" 的增量即卡面数值（num(0)/num(1)），与全仓 Improve 家族
    口径一致（batch_consume Snapper `_snapper_improve` 按 num(1) 递增、
    batch_trinkets15 Heart of the Forest 按 num(1)/num(2) 递增、
    batch_deathrattle2 Tasty Lobster 按 num(0) 递增）。本卡 num=1/1，
    "按印面值递增" 与 "固定 +1/+1 递增" 两种读法在数值上完全重合
    （无歧义风险）。

    Formal spec:
      1. on_bind 注册持久 `summon` 监听（owner=饰品）: `minion.controller
         is 本人` 且 `minion.race ∈ (BEAST, ALL)` → 计数 +1（记在 source
         实体属性 `_fang_anklet_improves`，离场即随饰品失效）。SUMMON 在
         招募期与战斗内**都**广播（game.summon），故战斗内召唤的野兽同样
         永久提升（文本无阶段限定）
      2. start_of_combat: 本人棋盘存活野兽各获
         `Buff(atk=num(0)×(1+n), health=num(1)×(1+n))`——"have +X/+Y
         this combat" 由战前快照战后回滚实现（RULES §3.5，TinyfinOnesie
         /HolyMallet 同口径，脚本不用 temporary=True）
      3. 无野兽 → 该次 SoC 落空（不产生 Action）; 对手召唤野兽不计数、
         对手野兽不被 Buff（owner 隔离）
      4. 提升是**永久**的（下次 SoC 生效，跨战斗保留）; 只作用于本人

    Test: test_batch_trinkets18.py — 真实 `game.summon` 两只野兽后
      SoC 本人野兽 = 基础 3×(num)（对照无饰品仅 base + 无召唤时 1×）/
      SoC 探针在战斗内读到增量、真实 `run_combat` 战后回滚 / 对手
      召唤野兽不计入本人提升 / 非野兽不加成 / `num` 与 CardDef 双向钉死

    Params: {0}=1 {1}=1（BG35_MagicItem_701 num(0/1)，同时是 improve
            增量——见 Evidence）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._fang_anklet_improves = 0

        def on_summoned(g, minion=None, **kw):
            if not isinstance(minion, Minion) or minion.controller is not h:
                return
            if minion.race not in _BEAST_RACES:
                return
            source._fang_anklet_improves = getattr(
                source, "_fang_anklet_improves", 0) + 1

        game.events.register(Listener(event=SUMMON, owner=source,
                                      callback=on_summoned))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        n = getattr(source, "_fang_anklet_improves", 0)
        atk = _num(game, source.card_id, 0) * (1 + n)
        health = _num(game, source.card_id, 1) * (1 + n)
        targets = [m for m in _living(h) if m.race in _BEAST_RACES]
        if not targets:
            return None
        return [Buff(m, atk=atk, health=health) for m in targets]


# ══════════════ BG35_MagicItem_712 Privateer Portrait ══════════════


class PrivateerPortraitScript:
    """
    Natural language: [x]Get a Proud Privateer and
    {0} random <b>Bounties</b>.
    At the start of each turn,
    get another {0} <b>Bounties</b>.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_712`（greater, cost 5,
    num(0)=2, `evolution_card_id=122520 → BG33_825 Proud Privateer`,
    池随从 T5）。Bounty = `constants.BOUNTY_SPELL_IDS`（5 张 T3 池法术，
    `bloodgem.random_bounty_card_id` 权威）。

    Formal spec:
      1. on_bind: 关联卡交付（`grant_trinket_related_card` → 池内
         `minion_pool.acquire` 1 份 + `pending_hand_add`，RULES §7.4.6）;
         随后 `_grant_bounties(本人, num(0)=2)`（每张 `random_bounty_card_id`
         调用即 `spell_pool.acquire`，池尽则剩余次数落空）
      2. start_of_turn（饰品 SoT 钩子）: 同款再发 num(0) 张 Bounty
         （"At the start of each turn, get another {0}"）
      3. 满手 → `pending_hand_add` 排队等待不销毁（RULES §3.3/§7.4.2）
      4. 只进本人手牌; 对手手牌与池记账不受本人饰品影响（owner 隔离）

    Test: test_batch_trinkets18.py — 绑定后手牌恰 +1 张 BG33_825 且池
      -1、Bounty 恰 +num(0) 张（card_id ∈ BOUNTY_SPELL_IDS）且法术池
      各 -1 / 真实 `_begin_recruit_for` 推进回合后再 +num(0) 张 Bounty /
      对手手牌不变 / Bounty 池抽干后落空且不越界

    Params: {0}=2（BG35_MagicItem_712 num(0)——同时是首发的张数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        _grant_bounties(game, h, _num(game, source.card_id, 0))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        _grant_bounties(game, h, _num(game, source.card_id, 0))
        return None


# ══════════════ BG35_MagicItem_714 Powder Keg ══════════════


def _powder_keg_deathrattle(owner):
    """构造「亡语: 召唤 1/1 Sky Pirate + 本随从攻击力 + 立即攻击」的追加效果。

    追加效果以**死亡随从**（src）为参数（`game.grant_combat_deathrattle`
    的 extra_fn 协议）。"give it this minion's Attack" = 授予等量攻击力
    （+X 语义；与 Snazzy Phantom "Give Attack equal to its Attack" /
    Nightbane "Give ... this minion's Attack" 同族措辞口径一致）。
    "It attacks immediately" = `_immediate_attack`（完整单次攻击，
    RULES §4.4 嘲讽优先/潜行不可击）。

    死亡处理路径内**直接执行**（add_buff / summon / execute_immediate_attack，
    禁 Action 入队——batch_hero_combat3 Onyxia 先例）。
    """

    def extra(src, g, ctx, _h=owner, **kw):
        atk = src.atk if isinstance(src, Minion) else 0
        token = g.create_minion(_SKY_PIRATE_ID, controller=_h)
        if token is None:
            return None
        if atk:
            token.add_buff(Enchant(atk=atk))
        if g.summon(_h, token):
            _immediate_attack(g, _h, token)
        return None

    return extra


class PowderKegScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give {0} friendly
    Pirates "<b>Deathrattle:</b> Summon a 1/1
    Sky Pirate and give it this minion's
    Attack. It attacks immediately."

    Evidence: `data/bg_trinkets.json BG35_MagicItem_714`（greater, cost 4,
    num(0)=3, `subset_pirate`）。wiki 页 Wiki tags 含 **[Random]** →
    "Give {0} friendly Pirates" = **随机** num(0) 只友方海盗（非位置/
    非玩家选择），故用 `game.rng.sample` 无放回抽取。Sky Pirate token
    = `BGS_061t`（CardDB 按名核实，1/1 Pirate）。

    Formal spec:
      1. on_bind: 无需脚本侧清理钩子——战斗内授予的亡语 override 由引擎
         `game.grant_combat_deathrattle` / `run_combat` 的 finally 统一
         恢复（2026-09-02 主线收口）
      2. start_of_combat: 本人棋盘存活海盗（race ∈ (PIRATE, ALL)）中
         `game.rng.sample` 随机取 min(num(0), 数量) 只，各经
         `game.grant_combat_deathrattle(h, 海盗, extra)` 获得追加亡语
         （与原生亡语链式叠加，原生先结算）; 不足 num(0) 只时全部获得
      3. 该海盗死亡时: 召唤 1/1 Sky Pirate（token，非池不占池）→ 追加
         `src.atk` 攻击力 → 棋盘未满则立即对交战对手发起一次完整攻击
         （0 攻/满场/无对手存活者 → 不攻击，召唤体留在场上）
      4. 效果仅本场（override 由 `run_combat` finally 恢复; DEATHRATTLE
         tag 由引擎战斗快照回滚）; 只作用于本人棋盘（对手海盗不获授）

    Test: test_batch_trinkets18.py — 真实 run_combat + SoC 后本人海盗带
      DEATHRATTLE 标记与 override（对手海盗不带）/ 战斗内该海盗死亡后
      出现 1/1+src.atk 的 Sky Pirate 且已对敌方完成一次攻击（敌方格挡者
      掉血）/ 真实 end_recruit_phase 后 override 已恢复（再死不产出）/
      无海盗时无授予（正对照: 有则授予）

    Params: {0}=3（BG35_MagicItem_714 num(0)）; token=1/1 Sky Pirate
            `BGS_061t`（数据核实）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        pirates = [m for m in _living(h) if m.race in _PIRATE_RACES]
        if not pirates:
            return None
        n = _num(game, source.card_id, 0)
        picks = game.rng.sample(pirates, min(n, len(pirates)),
                                label="powder_keg_pirates")
        extra = _powder_keg_deathrattle(h)
        for m in picks:
            game.grant_combat_deathrattle(h, m, extra)
        return None


# ══════════════ BG35_MagicItem_733 Jailer Sticker（Spellcraft） ══════════════


class JailerStickerScript:
    """
    Natural language: <b>Spellcraft:</b> Destroy a friendly Undead to get
    2 random Undead.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_733`（greater, cost 4,
    `spellcraft_id=131134 → BG35_MagicItem_733t`; 文本无 {0}/{1} 占位符，
    num 全 None）。RULES §6.13: 饰品实体参与每回合 Spellcraft 生成
    （`spellcraft.generate_for_hero` 扫描 `hero.board + hero.trinkets +
    hero.quest_rewards`；`create_entity` 依 `spellcraft_id` 打 SPELLCRAFT
    tag）。

    Formal spec:
      1. on_bind: 获得时立即给第一张 Spellcraft 法术
         （`spellcraft.grant_spellcraft_spell(source, game)`——RULES §6.13
         "获得法术塑造时立即获得第一张"; 饰品版先例 batch_trinkets2
         Harvested Pearl）。**每回合**的再次生成由**引擎**负责
         （`spellcraft.generate_for_hero`），脚本**不得**再写
         `start_of_turn` 生成（否则同一回合双发）
      2. 实效由法术脚本 `JailerStickerSpellScript`（BG35_MagicItem_733t）
         完成：定向消灭一只友方亡灵 → 随机得 2 张亡灵
      3. 该法术是临时法术（未使用则回合结束丢弃），由引擎处理

    Test: test_batch_trinkets18.py — 绑定后手牌恰 +1 张
      `BG35_MagicItem_733t` 且带 SPELLCRAFT tag / 真实
      `_begin_recruit_for` 下一回合再生成 1 张（不双发：每回合恰 1 张）/
      打出后真实消灭 + 2 张随机亡灵入手（占池）/ 对手手牌不受影响

    Params: 无模板参数（法术 id 经 `CardDef.spellcraft_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        grant_spellcraft_spell(source, game)
        return None


class JailerStickerSpellScript:
    """
    Natural language: Destroy a friendly Undead to get 2 random Undead.

    Evidence: `data/bg_cards.json BG35_MagicItem_733t`（card_type=5,
    cost 3——2026-09-02 按 CardDef 实测订正，旧注写 4; 同名 Lesser 版
    `BG35_MagicItem_306` 的等价效果已在
    batch_hero_actives2 `JailerScript` 实现并验收——destroy 协议与随机
    获取同源）。

    Formal spec:
      1. needs_target=True（"Destroy a friendly Undead" = 定向选择;
         `BG35_MagicItem_306` 的 wiki tags [Targeted] 同族）——
         `target_candidates` = 本人棋盘存活亡灵（race ∈ (UNDEAD, ALL)）
      2. on_play: 目标必须仍是本人棋盘上的存活随从（挂起期离场 → 落空，
         SOP §16 item 24）
      3. Destroy 语义（wiki mechanics "Destroy"）: `HEALTH` 置 0 →
         `game.check_deaths()`（death 事件/亡语/Avenge 照常，招募期死亡
         回池）——batch_hero_actives2 `JailerScript` 同一协议
      4. 返回 **2 个** `GetRandomMinion(race=UNDEAD)`（"2 random Undead"
         = 两次独立随机获取，各自 `minion_pool.acquire`；文本无
         "different" → 允许抽到同名卡的两份副本，RULES §7.4.8 的互异
         口径只针对法术且要求文本/先例支持）。池内亡灵耗尽 → 该次落空

    Test: test_batch_trinkets18.py — 打出后目标亡灵死亡（离场 + 回池）且
      手牌 +2 张亡灵（card_id 均为 UNDEAD，池各 -1）/ 无亡灵候选时
      法术不产生选择且不消耗目标 / 目标在挂起期离场 → 落空不抛错 /
      对手亡灵不受影响

    Params: count=2（文本字面量 "2 random Undead"，CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = getattr(source, "controller", None)
        if hero is None:
            return []
        return [m for m in hero.board
                if not m.dead and m.race in _UNDEAD_RACES]

    @staticmethod
    def on_play(source, game, ctx):
        hero = source.controller
        target = (ctx or {}).get("target")
        if hero is None or not isinstance(target, Minion):
            return None
        if target.dead or target not in hero.board:
            return None
        # Destroy 统一入口（minion_destroyed 广播）
        game.destroy_minion(target, source=source)
        return [GetRandomMinion(hero, race=Race.UNDEAD) for _ in range(2)]


# ══════════════ BG35_MagicItem_740 Sky Golem Portrait ══════════════


class SkyGolemPortraitScript:
    """
    Natural language: [x]Get a Falling Sky Golem. <b>Start
    of Combat:</b> Give your minions
    "<b>Deathrattle:</b> Give your minions
    +{0}/+{1} permanently."

    Evidence: `data/bg_trinkets.json BG35_MagicItem_740`（greater, cost 3,
    num(0)=2 num(1)=2, `evolution_card_id=130798 → BG35_342 Falling Sky
    Golem`，池随从 T6）。"permanently" = 战内增益经战后复原重放
    （batch_trinkets11 BelcherPortrait 先例：战斗内 Buff 会被
    `board_before` 复原回滚，`COMBAT_END` 在复原**之后**广播 → 重放）。

    Formal spec:
      1. on_bind: 关联卡交付（`grant_trinket_related_card`——池随从
         acquire + 入手，RULES §7.4.6）; 注册持久 `COMBAT_END` 监听:
         复原后把本场登记的 (随从) 名单重放 +num(0)/+num(1)（仍存活且
         在本人棋盘者）并恢复战斗内授予的亡语 override
      2. start_of_combat: 本人棋盘**全部**存活随从经
         `game.grant_combat_deathrattle` 获得追加亡语（与原生亡语链式
         叠加，原生先结算）
      3. 该亡语触发时: 本人当前存活随从各 +num(0)/+num(1)（战内即时
         生效）并登记进待重放名单 → 战后对幸存者重放为**永久**增益
      4. 效果仅本场（授予的亡语 override 由 COMBAT_END 恢复）;
         只作用于本人棋盘（对手随从不获授、对手的死亡不触发）

    Test: test_batch_trinkets18.py — 真实 run_combat: 战斗内本人随从死亡
      触发亡语（SoC 后探针读到 DEATHRATTLE 标记）→ 战后幸存随从属性
      比对照高 num(0)/num(1)（永久，招募期读值仍生效）/ 真实
      end_recruit_phase 后 override 已恢复（第二场不再触发）/
      对手随从不获授（owner 隔离）/ 绑定入手 BG35_342 且池 -1

    Params: {0}=2 {1}=2（BG35_MagicItem_740 num(0/1)，同时是授予亡语的
            数值——见 Evidence）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        source._sky_golem_pending = []

        def on_combat_end(g, hero_a=None, hero_b=None, **kw):
            if h is not hero_a and h is not hero_b:
                return
            atk = _num(g, source.card_id, 0)
            health = _num(g, source.card_id, 1)
            pending = list(getattr(source, "_sky_golem_pending", []))
            source._sky_golem_pending = []
            survivors = [m for m in pending if not m.dead and m in h.board]
            if survivors:
                g.run_actions([Buff(m, atk=atk, health=health)
                               for m in survivors])

        game.events.register(Listener(event=COMBAT_END, owner=source,
                                      callback=on_combat_end))
        return None

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)

        def extra(src, g, ctx, _h=h, _src=source, **kw):
            living = [m for m in _h.board if not m.dead]
            if not living:
                return None
            g.run_actions([Buff(m, atk=atk, health=health) for m in living])
            pending = getattr(_src, "_sky_golem_pending", None)
            if pending is None:
                pending = []
                _src._sky_golem_pending = pending
            pending.extend(living)
            return None

        targets = _living(h)
        if not targets:
            return None
        for m in targets:
            game.grant_combat_deathrattle(h, m, extra)
        return None


# ══════════════ BG35_MagicItem_741 Beatboxer Portrait ══════════════


class BeatboxerPortraitScript:
    """
    Natural language: Get a Polarizing Beatboxer.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_741`（greater, cost 6,
    num(0)=1, `evolution_card_id=98713 → BG26_149 Polarizing Beatboxer`，
    池随从 T7）。RULES §7.4.6 "Get a X": 交付正确即 CORRECT，关联卡自身
    脚本状态不影响本卡（`BG26_149` 已注册，见关联卡台账）。

    Formal spec:
      1. on_bind: `grant_trinket_related_card` → `evolution_card_id` 数据链
         解析 → 池内有余则 `minion_pool.acquire` 占池 1 份（RULES §2.3），
         池耗尽 → 落空（RULES §2.4）；`pending_hand_add` 入手（满手排队
         RULES §3.3）
      2. 只进本人手牌（owner 隔离）

    Test: test_batch_trinkets18.py — 绑定后手牌 +1 张 BG26_149 且该卡池
      -1（对照无饰品不变）/ 对手手牌不变 / 池抽干时落空（无入手）

    Params: 无模板参数（num(0)=1 为张数显示，交付固定为 1 张）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════ BG35_MagicItem_742 Accord-o-Tron Portrait ══════════════


class AccordOTronPortraitScript:
    """
    Natural language: [x]At the end of each turn,
    <b>Magnetize</b> an
    Accord-o-Tron to your left-
    and right-most Mechs.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_742`（greater, cost 5,
    `evolution_card_id=98576 → BG26_147 Accord-o-Tron`，池随从 T3
    Magnetic）。wiki 页 Wiki tags: MAGNETIC / Mech-related / Positional
    effect / Triggered effect（无 Notes 反证）。

    机制裁定（本卡两条口径）:
      (a) **池记账**: 文本是 "Magnetize an Accord-o-Tron"（生成一个直接
          吸附的实体），不是 "Get an Accord-o-Tron"（入手，占池）。生成
          体直接并入宿主、不入手/不独立上板，与
          batch_consume `_make_satellite`（"Magnetize a Satellite"）/
          batch_trinkets11 Ship in a Bottle（Summon 体不占池，仅 "get"
          的手牌副本占池）同一口径 → **零池操作**。
      (b) **单机械去重**: 只有 1 只机械时它同时是左端与右端，只吸附一次
          （避免重复 magnetized——batch_trinkets3 HolyMallet /
          batch_trinkets7 BalefulIncense 的 left/right-most 去重先例）。

    Formal spec:
      1. end_of_turn（饰品 EoT 钩子）: 本人棋盘存活机械（race ∈ (MECH,
         ALL)）取位置左端与右端（同一实体时去重）; 无机械 → 落空
      2. 每个锚点: `game.create_minion(98576→BG26_147)` +
         `game.attach_magnetic(hero, 生成体, 锚点)`——属性并入、关键词与
         亡语栈叠、`magnetized` 广播（RULES §6.14）；Accord-o-Tron 的
         "At the start of your turn, gain 1 Gold" 钩子随吸附宿主一并生效
         （引擎磁力效果合并契约）
      3. 生成体不占池、不入手（见机制裁定 (a)）; 只作用于本人棋盘
      4. 重复副本（copy_trinket）各自注册 EoT 钩子 → 效果叠加

    Test: test_batch_trinkets18.py — EoT 后左端/右端机械各获得
      BG26_147 的属性增量（攻/生命各 +CardDef 值）且
      `game._magnetic_stack` 各 +1 条 / 中位机械不变 / 只有 1 只机械时
      只吸附一次（去重，正/负对照）/ 无机械时落空（棋盘与池都不变）/
      对手棋盘不变

    Params: 无模板参数（生成体 id 经 `evolution_card_id` 数据链）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        mechs = [m for m in _living(h) if m.race in _MECH_RACES]
        if not mechs:
            return None
        card = _related_card(game, source)
        anchors = [mechs[0]]
        if mechs[-1] is not mechs[0]:
            anchors.append(mechs[-1])
        for host in anchors:
            tron = game.create_minion(card.id, controller=h)
            if tron is None:
                continue
            game.attach_magnetic(h, tron, host)
        return None


# ══════════════ BG35_MagicItem_750 Magicfin Sticker ══════════════


class MagicfinStickerScript:
    """
    Natural language: [x]After you buy a Tavern
    spell, get a 1/1 Murloc
    and teach it that spell.
    <i>({1} times per turn.)</i>@[x]After you buy a Tavern
    spell, get a 1/1 Murloc
    and teach it that spell.
    <i>({0} left!)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_750`（greater, cost 4,
    num(0)=2 num(1)=2——两个文本变体同值，故每回合限次无歧义）。
    "teach" 协议 = `batch_final_unfreeze.MagicfinMycologistScript` 已验收
    的实体属性通道: 生成 `BG33_890t` Magicfin Apprentice（1/1 Murloc
    token，非池）并写 `_taught_spell_id`，其 battlecry
    （`MagicfinApprenticeScript`）施放被教法术。

    Formal spec:
      1. on_bind 注册持久 `spell_bought` 监听（owner=饰品）: 引擎在
         `buy_from_tavern` 对**法术**实体 fire（game.py:589）——
         购买随从不触发（负例由引擎保证）
      2. 条件: `hero is 本人` 且本回合已用次数 < num(0)（计数按
         `game.turn` 惰性重置——MagicfinMycologist 同款回合戳，避免
         依赖被引擎重置的 tag）
      3. 触发: `create_minion(BG33_890t)` → `token._taught_spell_id =
         spell.card_id` → `pending_hand_add`（满手排队 RULES §3.3;
         token 非池卡不占池、不触发三连）
      4. 只作用于本人（对手购买法术不触发本人饰品）

    Test: test_batch_trinkets18.py — 真实 `buy_from_tavern` 法术 → 手牌
      +1 张 BG33_890t 且 `_taught_spell_id` == 所购法术 id（正对照: 买
      随从不得卡）/ 同回合第 num(0) 次后不再发放、跨回合
      （`_begin_recruit_for` 推进）恢复 / 对手购买不触发 / 打出手牌中的
      Apprentice 会施放被教法术（引擎通道实证）

    Params: {0}=2（每回合限次——BG35_MagicItem_750 num(0)/num(1) 同值）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        limit = _num(game, source.card_id, 0)
        state = {"turn": None, "used": 0}

        def on_bought(g, spell=None, hero=None, **kw):
            if hero is not h or spell is None:
                return
            if state["turn"] != g.turn:
                state["turn"] = g.turn
                state["used"] = 0
            if state["used"] >= limit:
                return
            state["used"] += 1
            token = g.create_minion(_MAGICFIN_APPRENTICE_ID, controller=h)
            if token is None:
                return
            token._taught_spell_id = spell.card_id
            g.pending_hand_add(h, token)

        game.events.register(Listener(event=SPELL_BOUGHT, owner=source,
                                      callback=on_bought))
        return None


# ══════════════ BG35_MagicItem_753 Murky Sticker ══════════════


class MurkyStickerScript:
    """
    Natural language: [x]At the end of each turn, give
    your two left-most minions
    +{0}/+{1}. <i>(Improved by your
    <b>Battlecries</b> triggered this game!)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_753`（greater, cost 2,
    num(0)=1 num(1)=2）。wiki 页 Wiki tags: `Increment attack` /
    `Increment health` / Battlecry-related / Game-related / Positional
    effect（无 Notes 反证）。36.2.2 补丁说明: 由 "+1/+1" 改为 "+1/+2"
    （数值整体提升）——本实现按**印面值递增**（num(0)/num(1) 每战吼
    各加一次），与全仓 Improve 家族口径一致（batch_consume Snapper /
    batch_trinkets15 Heart of the Forest / batch_deathrattle2 Tasty
    Lobster 均以卡面 num 作为递增步长）。对照读法 "固定 +1/+1 递增"
    26.2.2 前与现版本在基值上分叉，无信源支持，不采用。

    Formal spec:
      1. end_of_turn（饰品 EoT 钩子）: 本人棋盘存活随从取位置最左两只
         （不足两只则全部）; 无随从 → 落空
      2. 数值 = num(0)×(1+hero `COUNTER_BATTLECRIES`) /
         num(1)×(1+COUNTER_BATTLECRIES)——`COUNTER_BATTLECRIES` 是引擎
         维护的**本局已触发战吼数**（`play_minion` 每次战吼触发 +1，
         Brann/金色双倍各计一次，game.py:881），正是 "your Battlecries
         triggered this game" 的既有权威读取点（含绑定饰品之前触发的
         战吼——文本 "this game" 明确包含）
      3. 增益为**永久**（普通 `Buff`，非战斗阶段无快照回滚）;
         只作用于本人棋盘（对手棋盘不变）
      4. 两只最左随从是同名/同实体不重复（棋盘索引 0 与 1 天然互异）;
         重复副本各自 EoT 触发 → 叠加

    Test: test_batch_trinkets18.py — 绑定后 EoT: 最左两只各
      +num(0)/+num(1)、第三只不变（对照无饰品不变）/ 引擎计数器
      `COUNTER_BATTLECRIES` +1 后同场景增量 ×2（用真实 `play_minion`
      触发战吼，不手写计数器）/ 对手棋盘不变 / 空棋盘落空

    Params: {0}=1 {1}=2（BG35_MagicItem_753 num(0/1)，同时是递增步长
            ——见 Evidence）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = _living(h)
        if not living:
            return None
        step = 1 + h.get(GameTag.COUNTER_BATTLECRIES, 0)
        atk = _num(game, source.card_id, 0) * step
        health = _num(game, source.card_id, 1) * step
        return [Buff(m, atk=atk, health=health) for m in living[:2]]


# ══════════════ BG35_MagicItem_754 Dramaloc Sticker ══════════════


class DramalocStickerScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Give your
    Murlocs the Attack of the
    highest-Attack minion
    in your hand.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_754`（greater, cost 5,
    num(0)=2——文本无 {0}/{1} 占位符，效果无数值参数）。同族先例:
    batch_trinkets11 TinyfinOnesie（"gains the stats of the
    highest-Health minion in your hand"→`Buff(target, atk=src.atk,
    health=src.max_health)`），本卡是同一句式的攻击力部分。

    Formal spec:
      1. start_of_combat: 来源 = 本人**手牌**中当前攻击力最高的随从
         （平手取更靠前者，稳定 tie-break——TinyfinOnesie 同款）;
         手牌无随从 → 落空
      2. 目标 = 本人棋盘存活鱼人（race ∈ (MURLOC, ALL)，Amalgam 匹配）;
         无鱼人 → 落空
      3. 触发: 每个目标 `Buff(atk=src.atk)`——"give ... the Attack of"
         = 授予等量攻击力（+X；同 Snazzy Phantom "Give Attack equal to
         its Attack" 口径），生命不变; 战前快照战后回滚（RULES §3.5）
      4. 只作用于本人棋盘与本人手牌（对手手牌/棋盘不参与）

    Test: test_batch_trinkets18.py — SoC 后本人鱼人各 +src.atk（期望值
      取自手牌 CardDef）、非鱼人不变、生命不变 / 换更高攻手牌随从后
      增量随之变化（正对照）/ 空手牌落空 / 对手棋盘不变

    Params: 无模板参数（num(0)=2 为计数器显示，效果无数值参数）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        murlocs = [m for m in _living(h) if m.race in _MURLOC_RACES]
        if not murlocs:
            return None
        hand = [m for m in h.hand if isinstance(m, Minion)]
        if not hand:
            return None
        src = hand[0]
        for m in hand[1:]:
            if m.atk > src.atk:
                src = m
        return [Buff(m, atk=src.atk) for m in murlocs]


# ══════════════ BG35_MagicItem_803 Maxwell Sticker ══════════════


class MaxwellStickerScript:
    """
    Natural language: Get the <b>Buddy</b> of your Hero Power.

    Evidence: `data/bg_trinkets.json BG35_MagicItem_803`（lesser, cost 3;
    无 `evolution_card_id`——交付物不是饰品关联卡，而是**英雄定义**的
    伙伴）。数据链 = Hero CardDef `companion_id`（XML BACON_COMPANION_ID
    → dbf; RULES §9.4 核实 109 位英雄有值）。同族先例:
    batch_quest_rewards3 `PartnerInCrimeScript`（"Get your Golden Buddy"
    经同一数据链）。

    Formal spec:
      1. on_bind: `game.db.get(hero.card_id).companion_id` → `db.by_dbf`
         解析伙伴卡（基础版，非金色——文本无 "Golden"）
      2. `create_minion(buddy.id)` + `pending_hand_add`（满手排队
         RULES §3.3）
      3. **零池操作**: 伙伴不在共享池（RULES §9.4/§2——buddy 卡
         `is_pool_minion=False`），不 acquire/release
      4. 英雄定义缺 `companion_id` / 解析失败 → 落空（不近似）
      5. 只进本人手牌（owner 隔离）

    Test: test_batch_trinkets18.py — 绑定后手牌 +1 张本英雄
      `companion_id` 对应卡（断言 card_id 与 db 链一致）/ 池记账不变
      （非池卡）/ 对手手牌不变 / 无伙伴英雄落空

    Params: 无模板参数（伙伴 id 经 hero CardDef `companion_id` 数据链）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        hero_def = game.db.get(h.card_id)
        if hero_def is None or hero_def.companion_id is None:
            return None
        buddy = game.db.by_dbf(hero_def.companion_id)
        if buddy is None:
            return None
        m = game.create_minion(buddy.id, controller=h)
        if m is None:
            return None
        game.pending_hand_add(h, m)
        return None


# ══════════════ BG35_MagicItem_817 Lens Case ══════════════


class LensCaseScript:
    """
    Natural language: [x]Get a Duplicating Lens.
    At the start of every
    {1} turns, repeat this.
    <i>({0} |4(turn, turns) left!)</i>

    Evidence: `data/bg_trinkets.json BG35_MagicItem_817`（lesser, cost 3,
    num(0)=2 num(1)=2, `evolution_card_id=130853 → BG35_MagicItem_817t
    Duplicating Lens`）。cadence 口径与 batch_trinkets5
    `GoldenizerSupplyScript`（"At the end of every {1} turns, get a
    Goldenizer"→ 计数达 num(1) 触发一次）一致；本卡是 "start of every
    {1} turns"，故触发点在 SoT。

    Formal spec:
      1. on_bind: 关联卡交付 1 张（`grant_trinket_related_card` →
         `BG35_MagicItem_817t`，池外法术 → 零池操作 + `pending_hand_add`）
      2. start_of_turn（饰品 SoT 钩子）: 计数 +1（记在 source 实体属性
         `_lens_case_n`）; 达 num(1)=2 → 归零并再交付 1 张
         （"At the start of every {1} turns, repeat this"——绑定当回合不
         计数，首次重复在第 num(1) 次回合开始）
      3. 满手 → `pending_hand_add` 排队等待不销毁（RULES §3.3/§7.4.2）
      4. 只进本人手牌（owner 隔离）; 绑定前已过的回合不追溯

    Test: test_batch_trinkets18.py — 绑定后手牌 +1 张 `_817t` /
      第 1 次 `_begin_recruit_for` 无新卡、第 num(1) 次恰 +1 张
      （计数语义钉死）/ 再满 num(1) 回合再发一张（滚动）/ 对手手牌不变 /
      `_817t` 非池法术（交付不改变法术池）

    Params: {0}=2 {1}=2（BG35_MagicItem_817 num(0)=倒计时显示 /
            num(1)=重复周期）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        source._lens_case_n = 0
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        every = _num(game, source.card_id, 1)
        n = getattr(source, "_lens_case_n", 0) + 1
        if n < every:
            source._lens_case_n = n
            return None
        source._lens_case_n = 0
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════════════════════ 注册 ══════════════════════════════


def register() -> list[str]:
    """注册饰品第 18 批 13 张 + Spellcraft 法术 1 张。

    （6 张 DEFERRED 的依赖与实现路径见模块 docstring；不注册 = 二态铁律
    的 DEFERRED 态，SOP §6b。）
    """
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG35_MagicItem_435", BloodboundRingScript),
        ("BG35_MagicItem_701", FangAnkletScript),
        ("BG35_MagicItem_712", PrivateerPortraitScript),
        ("BG35_MagicItem_714", PowderKegScript),
        ("BG35_MagicItem_733", JailerStickerScript),
        ("BG35_MagicItem_733t", JailerStickerSpellScript),
        ("BG35_MagicItem_740", SkyGolemPortraitScript),
        ("BG35_MagicItem_741", BeatboxerPortraitScript),
        ("BG35_MagicItem_742", AccordOTronPortraitScript),
        ("BG35_MagicItem_750", MagicfinStickerScript),
        ("BG35_MagicItem_753", MurkyStickerScript),
        ("BG35_MagicItem_754", DramalocStickerScript),
        ("BG35_MagicItem_803", MaxwellStickerScript),
        ("BG35_MagicItem_817", LensCaseScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered


# DEFERRED（不注册）类占位——保留 docstring 台账供主线解冻时接管。
# 引擎缺口与实现路径见模块 docstring「DEFERRED 6 张」段。


class StegodonPortraitScript:
    """
    Status: 已由 batch_trinkets25 注册（关联卡数据链缺失以唯一名回退解析，2026-09-02 落地）

    Natural language: [x]Get a Stomping Stegodon.
    <b>Start of Combat:</b> Give
    your two left-most Beasts
    <b>Divine Shield</b>.

    Status: DEFERRED — requires 关联卡数据链（`evolution_card_id`）

    Dependency: XML 实体 `BG35_MagicItem_702`（dbf 130897，
    `hsdata/CardDefs.xml` L245446-245478）**没有** `BACON_EVOLUTION_CARD_ID`
    (2519) 或 `BACON_CARD_DBID_REWARD`(2673) 等关联卡 tag（同批 712/740/
    741/742/750/812/817 均有 2519，可对照核实）→ `game.trinket_related_card`
    恒 None，RULES §7.4.6 的 CORRECT 判据 (a) 不成立。"Stomping Stegodon"
    在 db 中确为 `BG33_840`（`is_pool_minion=False` 池外卡），但禁止从
    卡名猜测 id（SOP §11 item 5）。
    实现路径: 生成器/数据层补 `evolution_card_id`（dbf 122286）或主线裁定
    引擎按唯一卡名回退解析 → on_bind 交付白板副本（池外卡零池操作，
    `grant_card_copy_to_hand`）+ SoC 给本人最左两只野兽
    `GainKeyword(DIVINE_SHIELD)`（left/right 去重先例不适用——本卡是
    "two left-most"，需取前两只不同实体）。

    Params: 无模板参数（num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class TrustyCrowbarScript:
    """
    Status: 已由 `batch_trinkets23.TrustyCrowbarScript` 注册（本占位类不注册，仅留历史台账）

    Natural language: Whenever you get a Pirate,
    give your left-most minion +{0}/+{1}.

    Status: DEFERRED — requires hero 级"获得卡牌"事件（card_gained）

    Dependency: `hero.add_to_hand`（hero.py:207-213）只调实体级
    `run_script_hook(entity, "on_enter_hand")`，**不 fire 任何总线事件**;
    既有 `minion_bought` / `spell_bought` / `card_discovered` 只覆盖购买
    与发现两条路径，英雄技能/亡语/法术直接生成入手的卡牌零信号
    （batch_trinkets7/8 台账同缺口，本批复核维持）。
    实现路径: 引擎在 `hero.add_to_hand` fire `card_gained(hero=, card=)`
    → 本饰品 on_bind 挂监听，`card.race ∈ (PIRATE, ALL)` 时
    `Buff(本人棋盘最左存活随从, atk=num(0), health=num(1))`。

    Params: {0}=12 {1}=12（BG35_MagicItem_713 num(0/1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class SoulFermenterScript:
    """
    Natural language: [x]<b>Start of Combat:</b> Destroy
    your 3 left-most minions.
    After your last minion dies,
    resummon them.

    Status: DEFERRED — requires "最后随从死亡"触发点 + 战斗内属性快照重召

    Dependency: (a) 引擎只有逐次 DEATH 事件（`_process_death_inner`），
    无"该次死亡结算后己方棋盘为空"的官方时点/顺序权威; (b) "resummon
    them" 需要战前 3 只的 max-stats 快照字段（`game.combat_death_log`
    只记录实体）与战斗内召唤回放协议。同族缺口已由 batch_trinkets16
    对 `BG32_MagicItem_907`（"After your last minion dies each combat…"）
    逐条备案。
    实现路径: 引擎提供"最后随从死亡"钩子（DEATH 结算尾部 + 己方棋盘空
    判定）与战斗内 max-stats 快照 API → SoC 记录 3 只快照并
    `HEALTH=0` + `check_deaths()` 消灭之（Destroy 语义: 死亡链照常），
    钩子内按快照重召。

    Params: count=3（文本字面量；CardDef num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class ElectrodeAttractorScript:
    """
    Natural language: [x]<b>Magnetic</b> Mechs cost (2).
    The Tavern offers an
    extra one whenever it is
    <b>Refreshed</b>.

    Status: DEFERRED — requires 关键词限定报价 + 关键词限定额外展示位

    Dependency: (a) `GameTag.TAVERN_MINION_COST_OVERRIDE` 是 hero 级
    **无条件**平价覆写（Sindragosa/Millhouse=2），无"仅 Magnetic Mech"
    限定; 脚本侧在 `tavern_refresh` 后给馆内实体写 `COST=2` 会漏掉
    非刷新路径入馆的磁力机械（Toki/Tess/Varden 注入等）——近似，SOP §6b
    禁止。(b) `TAVERN_OFFER_MOD` 是通用展示位数，`minion_pool.draw_tavern`
    只支持种族白名单，无"这一张额外展示位必须是 Magnetic Mech"的抽取点。
    实现路径: 引擎增 `refresh_tavern(..., keyword=)`（或
    `hero._tavern_keyword_only`）与实体级条件报价读取点（如按
    `hero._minion_cost_keyword`（MAGNETIC 值 + num=2 两项）在
    `buy_from_tavern` 覆写报价）→ 本卡 on_bind 声明两项。

    Params: cost=2（文本字面量 "(2)"；CardDef num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class ChillmereMosaicScript:
    """
    Natural language: [x]<b>Spellcraft:</b> <b>Refresh</b> the
    Tavern with <b>Battlecry</b>
    minions. They cost (1).

    Status: DEFERRED — requires 关键词限定刷新原语（法术本体不可实现）

    Dependency: `refresh_tavern` 支持 `races=` / `spells_only=`，**无**
    关键词白名单; "Refresh the Tavern **with Battlecry minions**" 要求
    馆内全部展示项带 BATTLECRY。脚本侧"先普通刷新再逐项替换"会重写引擎
    刷新语义（冻结保留集 / The Golden Arena 金色化 / Elven Elite 档位 /
    池权重抽样 / `tavern_refresh` auto 标记），属近似——batch_spells_final
    `_refresh_tavern_of_type` 已把同类手写镜像收口回引擎，不得再开旁路。
    "They cost (1)" 侧已就绪（实体级 `COST` 被 `buy_from_tavern` 读取，
    game.py:504）。**载荷未就绪**（Spellcraft 法术 `BG35_MagicItem_755t`
    不可实现）→ 本饰品一并 DEFERRED（SOP §12 item 14 / RULES §7.4.6
    例外条）。
    实现路径: `refresh_tavern(keyword_filter={BATTLECRY})` + 入馆实体写
    `COST=1` → 注册 755 与 755t。

    Params: cost=1（文本字面量；CardDef num 全 None）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class CorruptedTomeScript:
    """
    Natural language: Get a Triple Prize.
    Whenever you would get a Triple Reward, get a Triple Prize instead.

    Status: DEFERRED — requires 三连奖励替换钩子 + Darkmoon Prize 子系统

    Dependency: (a) `_grant_triple_reward`（game.py:1019）是引擎内部固定
    路径（直接 `Discover(kind="triple_reward")`），无
    `hero._triple_reward_override` 之类读取点，也没有可在奖励发放前拦截
    的事件（`card_discovered` 在选项结算后才广播）; (b) 授予物
    `BG35_MagicItem_812t` Triple Prize 的 "Discover a Tier 3 Darkmoon
    Prize" 依赖 **Darkmoon Prize 子系统**（RULES §11.4——全仓无 Prize
    候选表/结算实现）。
    实现路径: 引擎在 `check_for_triple` 的奖励分支读
    `hero._triple_reward_card_id`（`grant_card_copy_to_hand` 替代
    Discover）+ Darkmoon Prize 候选池数据 → 注册 812 与 812t。

    Params: num(0)=3 在 `_812t`（Darkmoon Prize 档位），本卡 num 全 None
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class MysteriousOrbScript:
    """
    Natural language: [x]Gain {0} Gold.
    Your next <b>Trinket</b> is a
    Lesser <b>Trinket</b>.

    Status: DEFERRED — requires "下一次饰品档位覆写"读取点

    Dependency: `_offer_trinkets(hero, kind)` 的 kind 由回合推导
    （T6→lesser / T9→greater，外加 `hero._trinket_early` 提前档，
    game.py:300-310），无 `hero._next_trinket_kind` 覆写字段; 脚本自行
    写字段属"写入后无人读取"的空转标记（audit_script_wiring W3，
    SOP §11 item 3）。金币半场（`GainGold(hero, num(0)=10)`）已就绪但
    **不得单独注册**（整卡半实现 = 第三态，SOP §6b）。
    实现路径: 引擎在 `_begin_recruit_for` 的 offer 判定处读取
    `hero._next_trinket_kind`（消费后清零）→ 本卡 on_bind 写
    `GainGold` + 该字段。

    Params: {0}=10（BG35_MagicItem_818 num(0)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None
