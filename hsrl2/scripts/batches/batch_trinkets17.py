"""批次 trinkets17 — 饰品第十七批（作业单 2026-09-13，台账片 5/6）。

任务清单 = `TRINKET_LEDGER.md` 明细 #90–#109（20 张）。全部 id 均为
`CardDB.trinket_offer_pool()` 中的**商店本体**（运行核验 20/20；
`_953/_954/_960/_998/_150/_151/_152/_154/_155/_156/_300/_303/_305/
_306/_309/_310/_430/_431t/_432/_433`）。数值一律 `CardDef.num(i)`
（`CardDef` 无参数而文本含字面量者按 SOP §3 在各类 `Params:` 行声明
文本权威）; 关联卡优先走数据链 `CardDef.evolution_card_id` →
`CardDB.by_dbf`（RULES §7.4.6），数据链缺失的**第二张**关联卡按
hearthstone.wiki.gg "Related cards" 段落以名称查 `CardDB` 取 id（禁止
凭记忆写 id）; 随机一律 `game.rng`; 全部状态写在 hero 作用域 /
source 实体属性 / 监听闭包（无 game 级 flag——SOP §12 item 9）。

注册 17 张饰品 + 1 张 Spellcraft 法术（CORRECT）
═══════════════════════════════════════════════════════════════════════
  BG32_MagicItem_953  Goldgrubber Portrait — Get a Goldgrubber + an
                                             Aureate Laureate
  BG32_MagicItem_954  Auric Offering      — EoT: 最左随从 +4/+3；
                                             每个友方金色随从再重复一次
  BG32_MagicItem_960  Crocheted Sungill   — SoC: 手牌最高生命随从
                                             +4/+4；有空位时召唤其
                                             **本场战斗限定**副本
  BG32_MagicItem_998  Behemoth Portrait   — Get an Arcane Behemoth
  BG35_MagicItem_150  Cursed Crystal      — 每次酒馆刷新后馆内随从
                                             +num(0)/+num(1)「本回合」
  BG35_MagicItem_151  Defiler Portrait    — Get a Woodland Defiler；
                                             酒馆中的 Fodder +num(0)/+num(1)
  BG35_MagicItem_152  Demonic Tapestry    — 主动刷新 num(1) 次后，馆内
                                             最高档随从以生命代金购买
                                             （实体级 HEALTH_BUY，RULES §7.4.7）
  BG35_MagicItem_154  Ur'zul Sticker      — 打出恶魔后，另一个友方恶魔
                                             吞噬馆内随机随从并继承属性
  BG35_MagicItem_155  Felburned Ledger    — 英雄受伤后，本回合酒馆法术
                                             额外 +num(0)/+num(1)
  BG35_MagicItem_300  Copper Coil         — 每次磁力吸附给宿主
                                             +num(0)/+num(1) 并永久递增
  BG35_MagicItem_303  Skipper Portrait    — Get a Timewarped Skipper
  BG35_MagicItem_305  Conch Portrait      — Get a Cloning Conch；每
                                             num(1) 个回合开始重复
  BG35_MagicItem_306  Jailer Sticker      — Spellcraft 法术（306t）:
                                             摧毁一个友方亡灵，随机获得
                                             一张亡灵
  BG35_MagicItem_309  Errgl Sticker       — 随机 Get Mama/Papa Mrrglton；
                                             每回合开始重复
  BG35_MagicItem_310  Radio Star Portrait — Get a Timewarped Radio Star
                                             并给它 Reborn
  BG35_MagicItem_430  Scrapsmith Portrait — Get a Bristlemane Scrapsmith；
                                             友方嘲讽随从死亡后对己方
                                             Scrapsmith 各施放 1 颗永久血宝石
  BG35_MagicItem_432  Blood Amulet        — 触发亡语后对 num(0)=3 个
                                             随机友方随从各施放 1 颗永久
                                             血宝石

DEFERRED 3 张（**不注册**；逐张给出依赖 + 实现路径——SOP §6b 二态铁律）
════════════════════════════════════════════════════════════════════════
  - BG35_MagicItem_156 Flaming Portrait — "Get a Flaming Enforcer.
    Whenever your Flaming Enforcers trigger, also give the stats to
    their neighbors."
    RULES §7.4.6 **例外条**: 本卡效果**依赖被授予卡的行为**——"your
    Flaming Enforcers trigger" 指关联卡 `BG34_500` Flaming Enforcer
    的 EoT 吞噬触发（已注册，REGISTRY 核实）。引擎只分发
    `run_script_hook(随从, "end_of_turn")`，**没有**"某随从触发后"的
    可观察扩展点; 唯一可得的间接信号 `minion_consumed(demon=, minion=)`
    无法区分"本次触发获得的属性"（金色 `BG34_500_G` 的 mult=2 与
    其它吞噬来源的差异需要读兄弟批次脚本的内部状态），且"neighbors"
    的相邻判定与触发时机（Enforcer 自身属性已入账前后）无权威。
    实现路径: (a) 引擎把"随从钩子触发"广播为事件
    `minion_triggered(hook=, source=, value=…)`（EoT 吞噬的增量），或
    (b) `ConsumeMinion` 事件载荷增 `gained_atk/gained_health` 后，本卡
    监听并 `Buff(neighbors, atk=gained_atk, health=gained_health)`。
    被阻塞卡: 156。
  - BG35_MagicItem_431t Thornspike Pauldron — "After you trigger a
    **Deathrattle**, your **Blood Gems** give an extra +{2}/+{4} until
    next combat."
    **数值数据链缺口**: 印面值 = +2/+1（wiki.gg 页 + XML 核实:
    `TAG_SCRIPT_DATA_NUM_3=2`、`TAG_SCRIPT_DATA_NUM_5=1`），但
    `CardDef` 只导出 `TAG_SCRIPT_DATA_NUM_1..4`（tools/
    generate_bg_data.py L227-238）→ `num(3) is None`，{4} 对应的
    NUM_5 **无任何读取通道**（`CardDef.raw` 亦只有 JSON 已导出字段）。
    硬编码 1 违反"数值一律 CardDef.num()"纪律 → 整卡 DEFERRED。
    Dependency: 生成器导出 `TAG_SCRIPT_DATA_NUM_5` → `script_data_num_5`
    + `CardDef.num()` 支持 index 4（或 `CardDef.raw` 保留全 tag）。
    实现路径（数据补齐后）: on_bind 注册 `deathrattle_trigger`
    （minion.controller is 本人）→ `ImproveBloodGems(hero, num(2),
    num(4))` 并记录本回合增量; 下一次 `start_of_combat` 回退该增量
    （"until next combat" = 持续到下一场战斗开始——官方 bug 报告
    us.forums.blizzard.com/en/hearthstone/t/160488 明确"as written,
    should stay on until the beginning of the next combat"）。
    被阻塞卡: 431t。
  - BG35_MagicItem_433 Vinespeaker Portrait — "Get a Vinespeaker.
    Your Vinespeakers also improve the Health given by your **Blood
    Gems**."
    双重阻塞（RULES §7.4.6 例外条）: (a) 关联卡 `BG35_437`
    Vinespeaker **未注册**（REGISTRY 核实; 36.2.2 已移出随从池
    `is_pool_minion=False`，其本体 "After a friendly Deathrattle
    minion dies, your Blood Gems give an extra +2 Attack this game"
    无脚本）→ "your Vinespeakers" 没有任何触发行为; (b) "also improve
    the **Health**" 需要 Vinespeaker 脚本的 `ImproveBloodGems` 出口读取
    hero 级"额外 Health"标记（生产消费点），本饰品单独实现会得到永不
    生效的授予物（SOP §12 item 14 禁止）。
    Dependency: 先迁 `BG35_437`（含金色 `BG35_437_G` num(0)=4 的
    攻击增量）+ 引擎/该脚本提供读取点（例: `hero._vinespeaker_bonus_
    health` 由 Vinespeaker 的 Improve 出口消费）。被阻塞卡: 433。

关联卡台账（RULES §7.4.6 —— "Get a X" 交付正确即 CORRECT；被交付卡
自身脚本未迁移只登记、不阻塞，除非本卡效果依赖其行为）
════════════════════════════════════════════════════════════════════════
  | 饰品 | 关联卡（数据链 dbf → id） | 被授予卡脚本状态 |
  |---|---|---|
  | BG32_MagicItem_953 | 61066 → `BGS_066` Goldgrubber（非池）**+** wiki
  | "Related cards" 第二张 `BG32_236` Aureate Laureate（T1 池随从） |
  | Goldgrubber 未注册（不影响交付）; Aureate Laureate 已注册
  | （batch_unfreeze，含 on_enter_hand "always Golden" 恒金） |
  | BG32_MagicItem_998 | 119613 → `BG31_360` Arcane Behemoth（非池） |
  | 未注册（不影响交付） |
  | BG35_MagicItem_151 | 130076 → `BG35_151` Woodland Defiler（非池） |
  | 未注册（不影响交付） |
  | BG35_MagicItem_303 | 127129 → `BG34_Giant_072` Timewarped Skipper
  | （非池） | 未注册（不影响交付） |
  | BG35_MagicItem_305 | 110400 → `BG28_601` Cloning Conch（BACON_SPELL,
  | 非池法术） | 未注册（不影响交付） |
  | BG35_MagicItem_309 | 131145 → `BG35_140` Mama Mrrglton（T? 池随从）
  | **+** wiki "Related cards" 第二张 `BG35_141` Papa Mrrglton（池） |
  | 两张均已注册（不在本批依赖） |
  | BG35_MagicItem_310 | 127447 → `BG34_Giant_330` Timewarped Radio Star
  | （非池） | 未注册（不影响交付） |
  | BG35_MagicItem_430 | 97115 → `BG24_707` Bristlemane Scrapsmith
  | （非池; 金色 `BG24_707_G`） | 未注册（不影响交付——本饰品自行按
  | card_id 识别己方 Scrapsmith 并施放血宝石） |
  | BG35_MagicItem_433 | 130157 → `BG35_437` Vinespeaker | **未注册 →
  | 整卡 DEFERRED**（§7.4.6 例外） |
  | BG35_MagicItem_156 | 126924 → `BG34_500` Flaming Enforcer | 已注册
  | （batch_consume）但触发扩展点缺失 → 整卡 DEFERRED（§7.4.6 例外） |

接线（audit_script_wiring W1/W2/W3）: 饰品只挂 `on_bind` /
`start_of_turn` / `end_of_turn` / `start_of_combat`（白名单）; 监听事件
均为引擎真实 fire: `tavern_refresh`（refresh_tavern 尾部）、
`minion_bought`（buy_from_tavern）、`death`（_process_single_death）、
`deathrattle_trigger`（_process_death_inner）、`hero_damage_taken`
（Hero.take_damage）、`magnetized`（attach_magnetic）、`card_played`
（_run_play_effects）、`minion_consumed`（actions/consume.py）。
脚本侧无 `game._x`/`hero._x` 写入（状态在 source 实体或监听闭包）。
"""

from __future__ import annotations

from typing import List

from hsrl2 import entity
from hsrl2.actions import Buff, GainKeyword, GetRandomMinion
from hsrl2.actions.bloodgem import PlayBloodGems
from hsrl2.actions.consume import CONSUME_EVENT, ConsumeRandomTavernMinion
from hsrl2.events import (
    AFTER_ATTACK,
    CARD_PLAYED,
    DEATH,
    DEATHRATTLE_TRIGGER,
    HERO_DAMAGE_TAKEN,
    MAGNETIZED,
    MINION_BOUGHT,
    TAVERN_REFRESH,
    Listener,
)
from hsrl2.game import GameStateError
from hsrl2.minion import Minion
from hsrl2.tags import GameTag, Race, Zone

# ── 常量（卡 id 身份标识 / 文本字面量，非数值权威）──

# 文本字面量（CardDef 无模板参数，SOP §3 允许并在此声明）:
_AURIC_ATK = 4          # BG32_MagicItem_954 "give your left-most minion +4/+3"
_AURIC_HEALTH = 3
_SUNGILL_ATK = 4        # BG32_MagicItem_960 "Give ... +4/+4"
_SUNGILL_HEALTH = 4

# 第二张关联卡的 card_id（数据链 `evolution_card_id` 只携带一张——
# RULES §7.4.6 单关联卡协议; id 按名称查 CardDB 取，非记忆）:
#   - `BG32_236` Aureate Laureate: wiki.gg/Battlegrounds/Goldgrubber_Portrait
#     "Related cards" 明示生成 Goldgrubber + Aureate Laureate
_AUREATE_LAUREATE = "BG32_236"
#   - `BG35_141` Papa Mrrglton: wiki.gg/Battlegrounds/Errgl_Sticker
#     "Related cards" 明示生成 Mama Mrrglton + Papa Mrrglton（随机二选一）
_PAPA_MRRGLTON = "BG35_141"

# "your Scrapsmiths" 资格集: Bristlemane Scrapsmith 的基础 + 金色本体
# （`db.golden_version` 同源数据，身份集非数值）
_SCRAPSMITH_IDS = frozenset({"BG24_707", "BG24_707_G"})

# 全种族随从匹配一切种族查询（Amalgam 规则，RULES §8/§6.18）
_DEMON_RACES = (Race.DEMON, Race.ALL)
_UNDEAD_RACES = (Race.UNDEAD, Race.ALL)


def _hero(ctx):
    return (ctx or {}).get("hero")


def _num(game, card_id: str, index: int) -> int:
    """CardDef.num(index) 权威取值；缺失即 fail-loud（禁止静默 0）。"""
    d = game.db.get(card_id)
    value = d.num(index) if d is not None else None
    if value is None:
        raise GameStateError(
            f"{card_id}: missing num({index}) template parameter")
    return value


def _living(hero) -> List[Minion]:
    return [m for m in hero.board if not m.dead]


def _card_tier(game, e) -> int:
    """馆内实体档位（CardDef.tech_level 权威——酒馆法术实体无
    `tech_level` 属性，统一回查 CardDef; 金馆实体 card_id 为金卡定义，
    档位与基础一致）。"""
    d = game.db.get(e.card_id)
    if d is not None:
        return d.tech_level
    return getattr(e, "tech_level", 0) or 0


# ══════════════ BG32_MagicItem_953 Goldgrubber Portrait ══════════════


class GoldgrubberPortraitScript:
    """
    Natural language: Get a Goldgrubber and an Aureate Laureate.

    Formal spec:
      1. on_bind: 两张关联卡各自交付一份**白板**副本进手牌
         （RULES §7.4.6 "Get a X" 协议）:
           a) 第一张走数据链 `game.grant_trinket_related_card`
              （`evolution_card_id` 61066 → `BGS_066` Goldgrubber，
              `is_pool_minion=False` → 零池操作）
           b) 第二张按 wiki "Related cards" 常量 `BG32_236` Aureate
              Laureate（T1 **池随从**）经 `grant_card_copy_to_hand`
              交付 → `minion_pool.acquire` 占池 1 份; 池中无副本 →
              该条落空（RULES §2.4/§7.4.6）
      2. Aureate Laureate 自身的 `on_enter_hand`（batch_unfreeze）
         使其入手即恒金（"always Golden"）并打 `GILDED_NOT_TRIPLED`
         ——统一入手钩子的自然结果，本脚本不做近似
      3. 满手 → 各条自走 `pending_hand_add` 等待队列（RULES §3.3）
      4. 两条互相独立: 任一条解析失败不影响另一条
      5. 只进本人手牌（对手手牌不变）

    Test: test_batch_trinkets17.py — 绑定后手牌恰多 Goldgrubber 与
      Aureate Laureate 各 1 张（后者 GOLDEN tag = 恒金）/
      `minion_pool.available(BG32_236)` 恰 -1（对照 +1 回补后复原）/
      BGS_066 非池卡池计数不变 / 对手手牌不变 /
      满手时两张都入等待队列

    Params: 无模板参数（两张卡的身份由数据链 + wiki 关联表钉死）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        # a) Goldgrubber（数据链，非池）
        game.grant_trinket_related_card(h, source.card_id)
        # b) Aureate Laureate（wiki 关联表第二张，池随从 → 占池）
        laureate = game.db.get(_AUREATE_LAUREATE)
        if laureate is not None:
            game.grant_card_copy_to_hand(h, laureate)
        return None


# ══════════════ BG32_MagicItem_954 Auric Offering ══════════════


class AuricOfferingScript:
    """
    Natural language: [x]At the end of each turn,
    give your left-most minion
    +4/+3. Repeat for each
    friendly Golden minion.

    Formal spec:
      1. `end_of_turn`（饰品 EoT 钩子）: 目标 = 本人棋盘**最左**存活随从
         （`hero.board` 顺序 = 展示顺序; 无随从 → 整个效果落空）
      2. 施加次数 = 1 + 本人棋盘存活**金色**随从数
         （`Minion.is_golden` = GOLDEN tag 实体判定——金色随从是独立卡
         定义，与是否三连无关）; 每次施加同一 `Buff(+4/+3)`（数值为
         文本字面量——CardDef 无模板参数，SOP §3 声明）
      3. 重复施加在同一最左随从（文本 "give your left-most minion …
         Repeat"，不是"give each golden minion"）; 金色随从含最左自身
      4. 只作用于本人（对手棋盘/对手 EoT 不触发）; 满板/空板/无金色
         均按上式自然退化
      5. 无"this turn"/"this combat"限定 → buff 永久（非战斗快照回收）

    Test: test_batch_trinkets17.py — 无金色时最左随从恰 +4/+3（且第二
      只不变）/ 1 只金色时 +8/+6 / 2 只金色时 +12/+9（正对照与无饰品
      基线同 setup 对比）/ 空板不报错 / 对手绑定后其 EoT 不影响本人 /
      `CardDef.num` 缺失证明文本字面量权威（num(0) is None）

    Params: atk=4 health=3（"…+4/+3" 文本字面量——BG32_MagicItem_954
            num(0..3) 全为 None）
    """

    @staticmethod
    def end_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        living = _living(h)
        if not living:
            return None
        leftmost = living[0]
        goldens = sum(1 for m in living if m.is_golden)
        times = 1 + goldens
        return [Buff(leftmost, atk=_AURIC_ATK, health=_AURIC_HEALTH)
                for _ in range(times)]


# ══════════════ BG32_MagicItem_960 Crocheted Sungill ══════════════


class CrochetedSungillScript:
    """
    Natural language: <b>Start of Combat:</b> Give the highest-Health
    minion from your hand +4/+4. When you have space, summon it for this
    combat only.

    Formal spec:
      1. `start_of_combat`: 候选 = 本人**手牌**中全部存活 `Minion`
         （法术不是 minion）; 取当前 `health` 最大者（英文 "Health" =
         当前生命; "maximum Health" 才指上限——RULES §7.4.8 /
         SOP §16 item 23 裁定），并列 `game.rng.choice` 任选
         （label 审计）
      2. 立即对该手牌实体 `Buff(+4/+4)`（文本字面量; CardDef 无模板
         参数）——**永久**留在手牌，之后打出时带该属性
      3. "When you have space, summon it for this combat only"
         （对照 batch_soc `BG27_556` Diremuck Forager 同句式先例）:
           a) 板位有空 → 立刻召唤一份**战斗副本**:
              `create_minion(同 card_id, golden 同源)` +
              `restore_state(手牌实体快照)`（含步骤 2 的 buff）+
              `game.summon`; **手牌实体不离手**
           b) 满板 → 注册战斗内 `AFTER_ATTACK` 检查点（owner=饰品），
              每次攻击结算后若板位已释放则补召; 监听器随引擎监听器表
              快照恢复出队，不外溢招募期
           c) 副本不在战前 `board_before` 快照 → 战后随 `run_combat`
              的 board 恢复消失（"for this combat only"）
      4. 单场只召唤一次（source 实体 `_sungill_done` 标记）; 手牌无
         随从 → 整条落空（不注册检查点）
      5. 只作用于本人手牌/棋盘

    Test: test_batch_trinkets17.py — 真实 `run_combat`: 手牌最高生命
      随从 +4/+4 且仍在手牌 / 战斗中该副本入场（属性含 buff）/
      战后副本消失、手牌实体保留 / 满板 SoC 不召且战斗内腾位后补召 /
      空手牌不报错 / 对手手牌不受影响 / 低生命手牌随从被选中的正对照

    Params: atk=4 health=4（"…+4/+4" 文本字面量——BG32_MagicItem_960
            num(0..3) 全为 None）
    """

    @staticmethod
    def start_of_combat(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        hand_minions = [m for m in h.hand
                        if isinstance(m, Minion) and not m.dead]
        if not hand_minions:
            return None
        top = max(m.health for m in hand_minions)
        tied = [m for m in hand_minions if m.health == top]
        origin = game.rng.choice(tied, label="sungill_hand_pick")
        game.run_actions(Buff(origin, atk=_SUNGILL_ATK,
                              health=_SUNGILL_HEALTH))
        source._sungill_origin = origin
        source._sungill_copy = None

        def _try_summon(g):
            if getattr(source, "_sungill_copy", None) is not None:
                return
            o = getattr(source, "_sungill_origin", None)
            if o is None or o.dead or h.board_full():
                return
            copy = g.create_minion(o.card_id, controller=h,
                                   golden=o.is_golden)
            if copy is None:
                return
            copy.restore_state(o.snapshot_state())
            if not g.summon(h, copy):
                return
            source._sungill_copy = copy

        _try_summon(game)
        if getattr(source, "_sungill_copy", None) is None:
            def on_after_attack(g, **kw):
                _try_summon(g)

            game.events.register(Listener(
                event=AFTER_ATTACK, owner=source, callback=on_after_attack))
        return None


# ══════════════ BG32_MagicItem_998 Behemoth Portrait ══════════════


class BehemothPortraitScript:
    """
    Natural language: [x]Get an Arcane Behemoth.

    Formal spec:
      1. on_bind: 数据链 `game.grant_trinket_related_card`
         （`evolution_card_id` 119613 → `BG31_360` Arcane Behemoth，
         `is_pool_minion=False` → 零池操作）交付一份白板副本进手牌
         （RULES §7.4.6）
      2. 满手 → `pending_hand_add` 等待队列（RULES §3.3）
      3. 只进本人手牌; 关联卡自身脚本迁移状态不阻塞本卡

    Test: test_batch_trinkets17.py — 绑定后手牌恰多 1 张 BG31_360 /
      池计数不变量（非池卡）/ 对手手牌不变 / 满手排队

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════ BG35_MagicItem_150 Cursed Crystal ══════════════


class CursedCrystalScript:
    """
    Natural language: [x]After the Tavern is
    <b>Refreshed</b>, give its
    minions +{0}/+{1} this turn.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: **`tavern_refresh_complete`**
         （hero=, auto=）——引擎在 `tavern_refresh` 的**全部监听器跑完后**
         广播（game.refresh_tavern 尾部）。"After the Tavern is Refreshed"
         是被动句式（对照 Frigid Blossom 的 "you Refresh"）→ **自动与
         手动刷新都算**
      2. 每次刷新对馆内**每个 `Minion`** 施加 `+num(0)/+num(1)` 的
         **temporary Buff**（`entity.Buff(temporary=True)`——附魔内部
         标记），并登记 (实体, buff) 到 source 实体属性
      2b. **按刷新次数叠加**——"After the Tavern is Refreshed, give its
          minions +X/+Y this turn" 每次刷新都是一次新的授予，冻结保留
          的随从每次刷新各得一份（旧实现自造"同回合只 buff 一次"去重，
          与文本冲突且无信源; 2026-09-02 对抗审查证伪）。"this turn"
          由第 4 条兜住，不会跨回合无限增长
      2c. **刷新窗口内入馆的实体同样得一份**——Laboratory Assistant
          `BG35_150` 的 Demon Fodder 在 `tavern_refresh` 事件里由更晚
          注册的监听器入馆; 在 `tavern_refresh_complete` 结算即可看到
          **完整的刷新后酒馆**，与监听器注册顺序完全无关（旧实现在
          `tavern_refresh` 内按 uuid 打标 → 恒漏掉它; 2026-09-02 对抗
          审查证伪）
      4. "this turn" 过期: 饰品 `start_of_turn`（下一招募阶段开始）
         移除**仍在本人酒馆中**的已登记 buff 并清空登记表; 已被买走
         （离开酒馆）的实体**保留**其属性（购买后战利品不回收——
         这正是本饰品的用途: 强化本轮可购买的馆内随从）。生命值按
         上限 clamp
      5. 绑定当回合**不**追溯当前酒馆（触发时机是"刷新之后"，绑定
         本身不是刷新）; 下一次刷新起生效
      6. 只作用于本人酒馆（对手酒馆不被 buff——hero 作用域监听过滤）

    Test: test_batch_trinkets17.py — 绑定后真实 `refresh_tavern` 馆内
      随从恰 +num(0)/+num(1)、同回合第二次刷新不再叠加（正对照: 新
      入馆随从带 buff）/ 真实 `end_recruit_phase` 推进一回合后仍在馆
      且未被冻结的旧实体失去 buff / 刷新后立即买入的随从跨回合保留
      buff / 自动刷新（auto=True）也触发 / 对手刷新不 buff 本人酒馆 /
      绑定后未刷新时馆内随从无变化（触发时机正对照）

    Params: {0}=3 {1}=3（BG35_MagicItem_150 num(0)/num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)
        source._crystal_buffs = []

        def _grant(e, times):
            for _ in range(times):
                buff = entity.Buff(atk=atk, health=health,
                                   source_id=source.card_id)
                e.add_buff(buff)
                source._crystal_buffs.append((e, buff))

        def on_refresh_complete(g, hero=None, **kw):
            # 在**刷新窗口结束**的观察点结算（引擎在 `tavern_refresh`
            # 全部监听器跑完后广播）→ 馆内此刻的每个随从恰得本次一份;
            # Laboratory Assistant 的 Fodder 在 `tavern_refresh` 内更晚
            # append 也已被包含，且与监听器注册顺序无关（2026-09-02
            # 对抗审查: 在 tavern_refresh 内打标会恒漏掉它）
            if hero is not h:
                return
            for e in list(h.tavern):
                if isinstance(e, Minion) and not e.dead:
                    _grant(e, 1)

        game.events.register(Listener(event="tavern_refresh_complete",
                                      owner=source,
                                      callback=on_refresh_complete))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        for e, buff in list(getattr(source, "_crystal_buffs", [])):
            if h is not None and e in h.tavern:
                e.remove_buff(buff)
                if buff.health > 0:
                    e.set(GameTag.HEALTH, min(e.health, e.max_health))
        source._crystal_buffs = []
        return None


# ══════════════ BG35_MagicItem_151 Defiler Portrait ══════════════


class DefilerPortraitScript:
    """
    Natural language: [x]Get a Woodland Defiler.
    <b>Fodders</b> in the Tavern
    have +{0}/+{1}.

    Formal spec:
      1. on_bind: 数据链交付 Woodland Defiler 白板副本（`evolution_
         card_id` 130076 → `BG35_151`，非池 → 零池操作）
      2. 静态酒馆 Buff 面: 本人酒馆中的 **Fodder** 实体
         （card_id ∈ {`constants.FODDER_CARD_ID` = `BG35_150t`,
         金色 token `BG35_150t_G`}——Fodder 无 tag，身份即卡 id;
         金色 token 资格集旧版漏判，2026-09-02 对抗审查订正）获得
         **实体级永久** `+num(0)/+num(1)`（文本无 "this turn" →
         买入后带走，与 `hero.tavern_buffs` 持久酒馆 Buff 同口径）
      3. 应用点: on_bind 立即对馆内既有 Fodder 一次 + 持久监听
         **`tavern_entity_added`**（`game.add_tavern_entity` 统一入馆
         入口广播——覆盖刷新抽卡 / Fodder token 注入 / 脚本 append
         全部路径，**与监听器注册顺序无关**）。旧实现在 `tavern_refresh`
         事件里按 uuid 打标并按注册顺序执行，Laboratory Assistant
         `BG35_150` 的 Fodder 由**同一事件内更晚**的监听器入馆 → 恒
         吃不到 +4/+4（2026-09-02 对抗审查实测 MAJOR: 饰品先绑→Fodder
         2/2，随从先打→6/6）
      4. **每个 Fodder 实体只授予一次**（source 实体 uuid 集）——
         "have +X/+Y" 是静态陈述，不是每次刷新叠加
      5. 购买后 Fodder 带走该属性（实体级永久 buff）
      6. 只作用于本人酒馆

    Test: test_batch_trinkets17.py — 绑定后手牌多 1 张 BG35_151 /
      馆内预置 Fodder 立即 +num(0)/+num(1) / 真实两轮刷新生成的
      Fodder 各恰 +num(0)/+num(1)（不叠加）/ **Laboratory Assistant
      路径生成的 Fodder 也带 +num(0)/+num(1)**（旧实现恒漏，本条的
      突变对照即旧实现）/ 金色 token `BG35_150t_G` 同样命中 / 非
      Fodder 馆内随从不变（正对照）/ 买入后仍保留属性 / 对手馆内
      Fodder 不变

    Params: {0}=4 {1}=4（BG35_MagicItem_151 num(0)/num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        import hsrl2.constants as C
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)
        game.grant_trinket_related_card(h, source.card_id)
        fodder_ids = {C.FODDER_CARD_ID, f"{C.FODDER_CARD_ID}_G"}
        source._defiler_stamped = set()

        def _stamp(e):
            if not isinstance(e, Minion) or e.dead:
                return
            if e.card_id not in fodder_ids:
                return
            if e.uuid in source._defiler_stamped:
                return
            source._defiler_stamped.add(e.uuid)
            e.add_buff(entity.Buff(atk=atk, health=health,
                                   source_id=source.card_id))

        for e in list(h.tavern):
            _stamp(e)

        def on_tavern_entry(g, hero=None, entity=None, **kw):
            if hero is not h:
                return
            _stamp(entity)

        game.events.register(Listener(event="tavern_entity_added",
                                      owner=source,
                                      callback=on_tavern_entry))
        return None


# ══════════════ BG35_MagicItem_152 Demonic Tapestry ══════════════


class DemonicTapestryScript:
    """
    Natural language: [x]After you <b>Refresh</b> {1} times,
    the highest-Tier minion in the
    Tavern costs Health instead
    of Gold to buy. <i>({0} left!)</i>

    Formal spec:
      1. on_bind 初始化 `source._tapestry_left = num(0)`（=4）、
         `source._tapestry_unlocked = False`; 注册持久监听器
         `tavern_refresh`（hero=, auto=）
      2. **计数只算玩家主动刷新**（`auto is False`）——"you Refresh"
         与 Frigid Blossom 同口径（回合开始的自动刷新不算）
         （RULES §7.4.x auto 标记）; left 归零 → unlocked=True 并立即
         对当前酒馆执行打标
      3. 打标 `_restamp`: 先清除本人酒馆中全部 `Minion` 的实体级
         `HEALTH_BUY` tag（保证"最高档"唯一），再给**最高档**随从
         （`CardDef.tech_level` 比较; 并列取最左——展示顺序）打
         `HEALTH_BUY=True`。消费点 = 引擎 `buy_from_tavern`
         （RULES §7.4.7 实体级以生命代金; game.py 注释明示本卡）
      4. 解锁后打标在**每次刷新**（含自动）重算，并在酒馆构成变化时
         重算: `minion_bought`（买走最高档 → 次高应接替）与
         `minion_consumed`（馆内被吞噬）。买走者顺手清除其 tag
         （防实体留 tag 入牌库）
      5. 未解锁 → 只计数，不打标（负对照）; 少于 1 个随从 → 无标可打
      6. 生命不足时购买失败且 tag 保留（引擎 `buy_from_tavern` 保证）
      7. 只作用于本人酒馆

    Test: test_batch_trinkets17.py — num(0)-1 次主动刷新后无随从带
      HEALTH_BUY（负对照）/ 第 num(0) 次后恰最高档者带 tag、次高不带 /
      自动刷新不推进计数（正对照: 手动推进）/ 真实 `buy_from_tavern`
      以生命支付（金币不变、生命 -cost）且次高随从接替打标 / 未解锁
      时购买走金币 / 对手绑定后本人酒馆无标 / 生命不足购买失败且
      tag 与金币保留

    Params: {0}=4 {1}=4（BG35_MagicItem_152 num(0)/num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        source._tapestry_left = _num(game, source.card_id, 0)
        source._tapestry_unlocked = False

        def _restamp(g):
            best = None
            best_tier = None
            for e in list(h.tavern):
                if not isinstance(e, Minion) or e.dead:
                    continue
                e.clear(GameTag.HEALTH_BUY)
                tier = _card_tier(g, e)
                if best is None or tier > best_tier:
                    best, best_tier = e, tier
            if best is not None:
                best.set(GameTag.HEALTH_BUY, True)

        def on_refresh(g, hero=None, auto=False, **kw):
            if hero is not h:
                return
            if not source._tapestry_unlocked:
                if auto:
                    return
                source._tapestry_left -= 1
                if source._tapestry_left > 0:
                    return
                source._tapestry_unlocked = True
            _restamp(g)

        def on_bought(g, minion=None, **kw):
            if not getattr(source, "_tapestry_unlocked", False):
                return
            if minion is not None:
                minion.clear(GameTag.HEALTH_BUY)
            _restamp(g)

        def on_consumed(g, demon=None, minion=None, **kw):
            if getattr(source, "_tapestry_unlocked", False):
                _restamp(g)

        game.events.register(Listener(event=TAVERN_REFRESH, owner=source,
                                      callback=on_refresh))
        game.events.register(Listener(event=MINION_BOUGHT, owner=source,
                                      callback=on_bought))
        game.events.register(Listener(event=CONSUME_EVENT, owner=source,
                                      callback=on_consumed))
        return None


# ══════════════ BG35_MagicItem_154 Ur'zul Sticker ══════════════


class UrzulStickerScript:
    """
    Natural language: [x]After you play a Demon,
    another friendly Demon
    consumes a minion in the
    Tavern to gain its stats.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `card_played`（card=）
         ——引擎在随从**入场且战吼结算后**广播（game._run_play_effects），
         携带 `card`; 条件:
           - `isinstance(card, Minion)` ∧ `card.controller is 本人`
           - `card.race ∈ (DEMON, ALL)`（Amalgam 规则）
           - `card.zone == Zone.PLAY` —— 排除磁力吸附路径（吸附也在
             `attach_magnetic` 后 fire card_played，但实体 zone=REMOVED;
             文本无 "or Magnetize"，对照 Interpreter/Spark Snapper 先例）
      2. 触发: 候选 = 本人棋盘存活恶魔中**排除刚打出的那张**者
         （"another friendly Demon"）; 无候选 → 落空
      3. 随机选中一个（`game.rng.choice`，label 审计）→
         `ConsumeRandomTavernMinion(consumer)`（actions/consume.py）:
         吞噬馆内一个随机随从，恶魔获得其 atk/max_health（永久 buff），
         受害者回池 + zone=REMOVED、**不触发亡语**、fire
         `minion_consumed`; 馆内无随从 → 该次落空
      4. 每次打出恶魔各触发一次（同回合多个恶魔各自结算）; 金色/普通
         恶魔同为 DEMON 种族
      5. 只作用于本人（对手打出恶魔不触发、本人棋盘不受对手影响）

    Test: test_batch_trinkets17.py — 真实 `play_minion` 一张恶魔:
      另一只友方恶魔属性恰增加馆内某随从快照（馆内少 1 个、池回补
      1 份）/ 刚打出的恶魔自身**不**作为消费者（只有它自己时落空）/
      磁力吸附路径不触发（正对照: 普通打出触发）/ 馆内空落空 /
      对手打出恶魔不触发 / 非恶魔打出不触发

    Params: 无模板参数（增益 = 受害者运行时属性快照）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None

        def on_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not h:
                return
            if card.zone != Zone.PLAY:
                return
            if card.race not in _DEMON_RACES:
                return
            others = [m for m in _living(h)
                      if m is not card and m.race in _DEMON_RACES]
            if not others:
                return
            consumer = g.rng.choice(others, label="urzul_consumer")
            g.run_actions([ConsumeRandomTavernMinion(consumer)])

        game.events.register(Listener(event=CARD_PLAYED, owner=source,
                                      callback=on_played))
        return None


# ══════════════ BG35_MagicItem_155 Felburned Ledger ══════════════


class FelburnedLedgerScript:
    """
    Natural language: After your hero takes
    damage, your Tavern spells
    give an extra +{0}/+{1}
    this turn.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `hero_damage_taken`
         （hero=, amount=, health_before=, armor_before=）——`Hero.
         take_damage` 广播（护甲吸收也算受伤，官方 Floating Watcher
         口径）。条件 `hero is 本人`
      2. 每次受伤: 本人 `TAVERN_SPELL_EXTRA_ATK += num(0)`、
         `TAVERN_SPELL_EXTRA_HEALTH += num(1)`（RULES §7.4 酒馆法术
         增幅; 消费点 = `actions.racefx.tavern_spell_buff`，所有
         give-stats 酒馆法术的统一出口）; 本回合内多次受伤叠加
      3. "this turn" 过期: 饰品 `start_of_turn`（下一个招募阶段开始）
         **按本回合实际增量精确回退**（只减自己加的部分，不动其它
         来源的持久增幅），随后增量计数归零。战斗内受伤（战败伤害）
         发生在 EoT 之后、下一次 `start_of_turn` 之前 → 同样在下一个
         招募阶段开始被清除（"this turn" = 受伤发生的那一回合）
      4. 只作用于本人（对手受伤不加成本人 tag）
      5. 数值 num(0)/num(1) 权威（=1/1）

    Test: test_batch_trinkets17.py — 绑定后 `hero.take_damage` 一次
      tag 恰 +num(0)/+num(1) 且真实酒馆法术给属性多出该增量（正对照:
      无饰品基线）/ 同回合受伤两次叠 2×num / 下一回合 `start_of_turn`
      后回退到 0（跨回合一次性）/ 回退不影响其它来源预置的持久增幅
      （预置 5 → 受伤 +1 → 回退到 5）/ 对手受伤不加成本人 tag

    Params: {0}=1 {1}=1（BG35_MagicItem_155 num(0)/num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        atk = _num(game, source.card_id, 0)
        health = _num(game, source.card_id, 1)
        source._ledger_atk = 0
        source._ledger_health = 0

        def on_damage(g, hero=None, _h=h, **kw):
            if hero is not _h:
                return
            _h.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                   _h.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + atk)
            _h.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                   _h.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + health)
            source._ledger_atk += atk
            source._ledger_health += health

        game.events.register(Listener(event=HERO_DAMAGE_TAKEN,
                                      owner=source, callback=on_damage))
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        if source._ledger_atk:
            h.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                  max(0, h.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0)
                      - source._ledger_atk))
            source._ledger_atk = 0
        if source._ledger_health:
            h.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                  max(0, h.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0)
                      - source._ledger_health))
            source._ledger_health = 0
        return None


# ══════════════ BG35_MagicItem_300 Copper Coil ══════════════


class CopperCoilScript:
    """
    Natural language: [x]Whenever you <b>Magnetize</b>
    a minion, give it +{0}/+{1}
    and improve this.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `magnetized`
         （host=, attached=）——`attach_magnetic` 尾部广播（game.py），
         `host` = 被吸附的宿主随从（必然属于施放者）
      2. 条件 `host.controller is 本人` 且 `not host.dead`
      3. 每次触发: `Buff(host, atk=bonus_atk, health=bonus_health)`
         （当前档位），随后 `bonus_atk += num(0)`、
         `bonus_health += num(1)`——"improve this" 的增量 = 印面值
         （Improve 家族口径: All-Purpose Kibble / Tumbling Disaster
         先例; 本卡 XML NUM_1/NUM_2 各 1）
      4. 档位跨回合/跨战斗累积（状态在饰品闭包; "improve" 无复位文本）
      5. 只作用于本人（对手磁力不触发）; 无磁力发生 → 档位不推进
         （正对照）

    Test: test_batch_trinkets17.py — 真实 `play_minion(magnetic_target=)`
      首次吸附宿主 +num(0)/+num(1)、第二次吸附 +2×num(0)/+2×num(1)
      （累计 3×）/ 非磁力打出不触发且档位不推进 / 对手吸附不触发 /
      `host.controller` 隔离（两英雄各绑一份互不干扰）

    Params: {0}=1 {1}=1（BG35_MagicItem_300 num(0)/num(1)）;
            improve_step = 印面值 num(0)/num(1)（"improve this" 无独立参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        step_atk = _num(game, source.card_id, 0)
        step_health = _num(game, source.card_id, 1)
        state = {"atk": step_atk, "health": step_health}

        def on_magnetized(g, host=None, attached=None, _h=h, **kw):
            if host is None or host.dead or host.controller is not _h:
                return
            g.run_actions(Buff(host, atk=state["atk"],
                               health=state["health"]))
            state["atk"] += step_atk
            state["health"] += step_health

        game.events.register(Listener(event=MAGNETIZED, owner=source,
                                      callback=on_magnetized))
        return None


# ══════════════ BG35_MagicItem_303 Skipper Portrait ══════════════


class SkipperPortraitScript:
    """
    Natural language: Get a Timewarped Skipper.

    Formal spec:
      1. on_bind: 数据链 `grant_trinket_related_card`（`evolution_
         card_id` 127129 → `BG34_Giant_072` Timewarped Skipper，
         `is_pool_minion=False` → 零池操作）交付白板副本进手牌
      2. 满手 → `pending_hand_add` 等待队列（RULES §3.3）
      3. 只进本人手牌

    Test: test_batch_trinkets17.py — 绑定后手牌恰多 1 张 BG34_Giant_072 /
      池不变量 / 对手手牌不变

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════ BG35_MagicItem_305 Conch Portrait ══════════════


class ConchPortraitScript:
    """
    Natural language: [x]Get a Cloning Conch.
    At the start of every
    {1} turns, repeat this.
    <i>({0} |4(turn, turns) left!)</i>

    Formal spec:
      1. on_bind: 数据链交付 Cloning Conch 白板副本
         （`evolution_card_id` 110400 → `BG28_601`，BACON_SPELL 且
         `is_pool_spell=True`——2026-09-02 按 CardDef 实测订正，旧注写
         False → 与"Get a Tavern spell"族同口径走池占返）;
         并初始化 `source._conch_left = num(0)`（=2，卡面 "{0} turns
         left!" 起始值）
      2. `start_of_turn`（饰品 SoT 钩子）: left -= 1; left 归零 →
         再交付一张（"repeat this"）并把 left 复位为 **num(1)**（=2，
         "every {1} turns" 的周期）
      3. 计数从绑定回合的下一个招募阶段开始（"At the start of every
         N turns"——与 Worn Treasure Map / Azeroth Model Globe 同款
         on_bind 计数先例）
      4. 只作用于本人（对手回合不发放）; 满手走等待队列

    Test: test_batch_trinkets17.py — 绑定后手牌多 1 张 BG28_601 /
      第 1 次 SoT 不发放（left 减到 1）/ 第 num(0) 次 SoT 恰再发放
      1 张且 left 复位为 num(1)（正对照: 无饰品基线手牌数）/
      下一个周期同样恰每 num(1) 次发放 / 对手绑定后其 SoT 不影响本人

    Params: {0}=2 {1}=2（BG35_MagicItem_305 num(0)/num(1)）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)
        source._conch_left = _num(game, source.card_id, 0)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        left = getattr(source, "_conch_left", None)
        if left is None:
            return None
        left -= 1
        if left > 0:
            source._conch_left = left
            return None
        source._conch_left = _num(game, source.card_id, 1)
        game.grant_trinket_related_card(h, source.card_id)
        return None


# ══════════════ BG35_MagicItem_306 Jailer Sticker ══════════════


class JailerStickerScript:
    """
    Natural language: <b>Spellcraft:</b> Destroy a friendly Undead to
    get a random Undead.

    Formal spec:
      1. 本饰品是**数据驱动的 Spellcraft 源**: `CardDef.spellcraft_id`
         = 131136 → `BG35_MagicItem_306t`; `create_entity` 依
         `spellcraft_id` 打 SPELLCRAFT tag，`spellcraft.generate_for_hero`
         的扫描域已含 `hero.trinkets`（2026-09-02 引擎扩展）→ 每个
         招募阶段开始生成 1 张临时法术入手（未使用则回合结束丢弃，
         RULES §6.13）
      2. 实效全部由法术脚本 `JailerStickerSpellScript`
         （`BG35_MagicItem_306t`）完成——本类无 on_bind 副作用
         （对照 batch_trinkets11 Demonblood Gourd 同构）
      3. 文本无 "Get a X" 子句 → 不做关联卡交付

    Test: test_batch_trinkets17.py — 绑定饰品实体后真实
      `spellcraft.generate_for_hero` 生成 1 张带 SPELLCRAFT 的
      `BG35_MagicItem_306t` 入手（正对照: 无饰品不生成）+ 法术行为
      见 TestJailerStickerSpell

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class JailerStickerSpellScript:
    """
    Natural language: Destroy a friendly Undead to get a random Undead.

    Formal spec:
      1. `needs_target = True`（XML `TARGETING_ARROW_TEXT` 权威 +
         "Destroy a friendly Undead" 与 Butchering BG28_604 同句式;
         wiki.gg 卡片页无 "Random" 标签）→ 引擎 `play_spell` 分流
         `PendingChoice(kind="spell_target")`
      2. `target_candidates` = 本人棋盘存活 `race ∈ (UNDEAD, ALL)` 随从
      3. `on_play`（目标已选定）: a) Destroy——`target.health = 0` +
         `game.check_deaths()`（完整死亡链: death 事件 → 亡语 → 招募期
         回池; 非伤害路径，无视圣盾/免疫——Maw Caster BGS_020 先例）;
         b) `GetRandomMinion(hero, race=UNDEAD)`——池感知随机获取
         （占池、满手排队、候选封顶 `game.max_tavern_tier`）
      4. **落空纪律**: target 缺失（无合法候选——引擎 no-candidate 路径）
         或非 Minion / 已离场 / 非亡灵 → on_play 返回 None（**不**
         凭空获取；"Destroy … **to** get" 的代价未支付时收益不成立，
         SOP §16 item 15 落空语义）; 法术仍照常消耗
      5. 只作用于本人棋盘与本人手牌

    Test: test_batch_trinkets17.py — 真实 `play_spell` 定向友方亡灵:
      该亡灵走完整死亡链（GRAVEYARD + 池回补）且手牌恰多 1 张亡灵
      （race == UNDEAD）/ 无候选时 Spellcraft 法术照常消耗且不报错 /
      金色/普通亡灵同判 / 对手棋盘与手牌不变

    Params: count=1（"Get a random Undead" 文本字面量——CardDef 无
            模板参数）
    """

    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        h = source.controller
        if h is None:
            return []
        return [m for m in h.board
                if not m.dead and m.race in _UNDEAD_RACES]

    @staticmethod
    def on_play(source, game, ctx):
        h = source.controller
        target = (ctx or {}).get("target")
        if h is None:
            return None
        if not (isinstance(target, Minion) and not target.dead
                and target in h.board and target.race in _UNDEAD_RACES):
            return None          # 未支付摧毁代价 → 不获取（落空）
        # Destroy 统一入口（minion_destroyed 广播; RULES §7.4.11）
        game.destroy_minion(target, source=source)
        return GetRandomMinion(h, race=Race.UNDEAD)


# ══════════════ BG35_MagicItem_309 Errgl Sticker ══════════════


class ErrglStickerScript:
    """
    Natural language: [x]Get a Mama Mrrglton
    or a Papa Mrrglton.
    At the start of each turn,
    repeat this.

    Formal spec:
      1. 两张关联卡: 数据链 `evolution_card_id` 131145 → `BG35_140`
         Mama Mrrglton; **第二张** `BG35_141` Papa Mrrglton（wiki.gg
         Battlegrounds/Errgl_Sticker "Related cards" 明示两张）。
         37.0（255130）起两张均为 `is_pool_minion=False`（退出池内随从）
         → 交付经 `grant_card_copy_to_hand` 的非池副本分支（零池操作）；
      2. 选择是**随机**的（wiki 页面 refTags 明示 "Random"）→
         `game.rng.choice(两者)`（label 审计）
      3. on_bind 立即发放一次; `start_of_turn` 每个招募阶段重复一次
         （文本 "At the start of each turn, repeat this"）
      4. 只进本人手牌（对手不受影响）; 满手走 `pending_hand_add` 队列

    Test: test_batch_trinkets17.py — 绑定后手牌恰多 1 张且 card_id ∈
      {BG35_140, BG35_141}（池 -1）/ 第 1 次 SoT 恰再多 1 张（正对照:
      无饰品基线）/ 对手绑定后其 SoT 不发放到本人 / 满手入等待队列

    Params: 无模板参数（两张卡的身份由数据链 + wiki 关联表钉死）
    """

    @staticmethod
    def _grant(game, h, source) -> None:
        defs = [d for d in (game.db.get("BG35_140"),
                            game.db.get(_PAPA_MRRGLTON)) if d is not None]
        if not defs:
            return
        d = game.rng.choice(defs, label="errgl_pick")
        game.grant_card_copy_to_hand(h, d)

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        ErrglStickerScript._grant(game, h, source)
        return None

    @staticmethod
    def start_of_turn(source, game, ctx):
        h = source.controller
        if h is None:
            return None
        ErrglStickerScript._grant(game, h, source)
        return None


# ══════════════ BG35_MagicItem_310 Radio Star Portrait ══════════════


class RadioStarPortraitScript:
    """
    Natural language: Get a Timewarped Radio Star. Give it <b>Reborn</b>.

    Formal spec:
      1. on_bind: 数据链 `game.trinket_related_card`（`evolution_
         card_id` 127447 → `BG34_Giant_330` Timewarped Radio Star，
         `is_pool_minion=False` → 零池操作）
      2. 交付 = 创建白板副本 + `GainKeyword(copy, REBORN)`（fire
         keyword_gained，与"Give it Reborn"同义且复用引擎关键词
         协议）+ `pending_hand_add`（满手等待，RULES §3.3）。
         **不使用 `grant_card_copy_to_hand`** 的原因: 统一入口只返回
         bool，无法在其产物上追加关键词; 该卡为非池 token，统一入口
         的池记账分支是 no-op，此处按同一口径（create_minion +
         pending_hand_add）显式实现（Curator Sticker 第二张 token /
         Windfall Portrait 同款先例）
      3. 关键词落在**手牌实体**上 → 之后打出时保留 Reborn（实体 tag，
         非战斗临时）
      4. 关联卡解析失败 → 整条落空（不近似）
      5. 只进本人手牌

    Test: test_batch_trinkets17.py — 绑定后手牌恰多 1 张 BG34_Giant_330
      且实体 `has(REBORN)`（正对照: 普通 create_minion 无 Reborn）/
      真实 `play_minion` 打出后场上实体仍有 Reborn / 池计数不变量 /
      对手手牌不变

    Params: 无模板参数（Reborn 为卡面文本条款）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        d = game.trinket_related_card(source.card_id)
        if d is None:
            return None
        if d.is_pool_minion and not game.minion_pool.acquire(d.id):
            return None
        m = game.create_minion(d.id, controller=h)
        if m is None:
            return None
        game.run_actions(GainKeyword(m, GameTag.REBORN))
        game.pending_hand_add(h, m)
        return None


# ══════════════ BG35_MagicItem_430 Scrapsmith Portrait ══════════════


class ScrapsmithPortraitScript:
    """
    Natural language: [x]Get a Bristlemane Scrapsmith.
    After a friendly minion with
    <b>Taunt</b> dies, play a permanent
    <b>Blood Gem</b> on your Scrapsmiths.

    Formal spec:
      1. on_bind: 数据链交付 Bristlemane Scrapsmith 白板副本
         （`evolution_card_id` 97115 → `BG24_707`，非池 → 零池操作）
      2. on_bind 注册持久监听器（owner=饰品）: `death`（minion=）——
         引擎在**离场之前**广播（_process_single_death 步骤 1，故
         `minion.controller`/关键词仍可读; 招募期与战斗内两路径都 fire）
      3. 条件: `minion.controller is 本人` ∧ `minion.has(TAUNT)`
         （关键词先于离场清理由引擎顺序保证）
      4. 触发: "your Scrapsmiths" = 本人棋盘上 card_id ∈ {基础, 金色}
         的存活 Scrapsmith（死者自身若为 Scrapsmith 已被 `dead` 过滤）
         → 对每个各执行 `PlayBloodGems(m, count=1)`（actions/bloodgem.py:
         vanilla 宝石，数值 = `BG20_GEM.num(0/1)` + hero 的
         BLOOD_GEM_BONUS_*; 永久 buff 非 temporary、含 GEMS_PLAYED_ON
         记账 + blood_gem_played 广播）
      5. 无 Scrapsmith → 该次落空（不影响触发本身）; 无 taunt 死亡 →
         不触发（正对照）
      6. 只作用于本人（对手嘲讽死亡不触发、对手棋盘不得宝石）

    Test: test_batch_trinkets17.py — 真实战斗内友方嘲讽随从死亡后
      己方 Scrapsmith atk/max_health 各 +宝石面值、GEMS_PLAYED_ON==1 /
      非嘲讽友方死亡不触发（负对照）/ 对手嘲讽死亡不触发、对手
      Scrapsmith 不变 / 己方无 Scrapsmith 时不报错 / 招募期死亡
      （`_process_single_death` 直调）同样触发

    Params: count=1（"a permanent Blood Gem" 文本字面量——CardDef 无
            模板参数）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        game.grant_trinket_related_card(h, source.card_id)

        def on_death(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            if not minion.has(GameTag.TAUNT):
                return
            smiths = [m for m in h.board
                      if not m.dead and m.card_id in _SCRAPSMITH_IDS]
            if not smiths:
                return
            g.run_actions([PlayBloodGems(m, count=1, source=source)
                           for m in smiths])

        game.events.register(Listener(event=DEATH, owner=source,
                                      callback=on_death))
        return None


# ══════════════ BG35_MagicItem_432 Blood Amulet ══════════════


class BloodAmuletScript:
    """
    Natural language: [x]After you trigger a
    <b>Deathrattle</b>, this plays a
    permanent <b>Blood Gem</b> on
    {0} random friendly minions.

    Formal spec:
      1. on_bind 注册持久监听器（owner=饰品）: `deathrattle_trigger`
         （minion=）——`_process_death_inner` 在亡语结算后广播
         （此时 source 可能已 GRAVEYARD，但 `controller` 仍可用）
      2. 条件 `minion.controller is 本人`（"you trigger a Deathrattle"
         = 己方亡语; 对手亡语不触发——owner 隔离）
      3. 触发: 候选 = 本人棋盘**存活**随从; `n = min(num(0), len(候选))`
         （不足则全给——官方"不足 N 个则给全部"口径）;
         `game.rng.sample(候选, n)` 取**互不重复**的随机 n 个（"random
         friendly minions"）; 对每个执行 `PlayBloodGems(m, count=1)`
         （永久宝石; 记账与广播由 action 统一处理）
      4. 空板 → 该次落空; 每次亡语触发各结算一次
      5. 只作用于本人（对手亡语不触发、对手随从不得宝石）

    Test: test_batch_trinkets17.py — 真实亡灵死亡触发后恰 num(0) 个
      己方随从各 +宝石面值（GEMS_PLAYED_ON 各 1）/ 不足 num(0) 个时
      全部获得（正对照: 3 只板全中）/ 空板落空不报错 / 对手亡语不
      触发、对手棋盘不变 / 同一随从不因随机重复获得两次

    Params: {0}=3（BG35_MagicItem_432 num(0); "this plays a permanent
            Blood Gem on {0} random friendly minions"）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        h = _hero(ctx)
        if h is None:
            return None
        count = _num(game, source.card_id, 0)

        def on_deathrattle(g, minion=None, **kw):
            if minion is None or minion.controller is not h:
                return
            pool = _living(h)
            if not pool:
                return
            picks = g.rng.sample(pool, min(count, len(pool)),
                                 label="blood_amulet_targets")
            g.run_actions([PlayBloodGems(m, count=1, source=source)
                           for m in picks])

        game.events.register(Listener(event=DEATHRATTLE_TRIGGER,
                                      owner=source, callback=on_deathrattle))
        return None


# ══════════════ 未注册（DEFERRED；台账见模块 docstring） ══════════════


class FlamingPortraitScript:
    """
    Natural language: [x]Get a Flaming Enforcer.
    Whenever your Flaming
    Enforcers trigger, also give
    the stats to their neighbors.

    Status: DEFERRED — requires 随从钩子触发广播（值载荷）

    Dependency: 关联卡 `BG34_500` Flaming Enforcer（已注册）的 EoT 吞噬
    触发没有可观察扩展点——唯一间接信号 `minion_consumed(demon=,
    minion=)` 无法区分本次触发获得的属性（金色 `BG34_500_G` mult=2）
    与其它吞噬来源; "neighbors" 相邻判定/触发时机亦无权威。实现路径:
    引擎广播 `minion_triggered(hook=, source=, value=…)`，或
    `ConsumeMinion` 载荷增 `gained_atk/gained_health` → 本卡监听并对
    相邻随从 `Buff`。RULES §7.4.6 例外条（依赖被授予卡行为）。

    Params: 无模板参数（"the stats" = 运行时增量）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class ThornspikePauldronScript:
    """
    Natural language: [x]After you trigger a
    <b>Deathrattle</b>, your
    <b>Blood Gems</b> give an extra
    +{2}/+{4} until next combat.

    Status: DEFERRED — requires TAG_SCRIPT_DATA_NUM_5 数据导出

    Dependency: 印面值 +2/+1（wiki.gg 页 + XML: NUM_3=2、NUM_5=1），但
    `CardDef` 只导出 NUM_1..4（tools/generate_bg_data.py L227-238）→
    `num(3) is None`，{4} 无读取通道; 硬编码违反数值纪律。实现路径:
    生成器导出 `script_data_num_5`（+ `CardDef.num(4)`）后，on_bind
    注册 `deathrattle_trigger` → `ImproveBloodGems(hero, num(2),
    num(4))` 并在下一场战斗开始（`start_of_combat`）回退该增量
    （"until next combat"——官方 bug 报告 t/160488 明确应持续到下一场
    战斗开始）。

    Params: {2}=2（num(2) 可读） {4}=NUM_5（**当前无数据通道**）
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


class VinespeakerPortraitScript:
    """
    Natural language: [x]Get a Vinespeaker.
    Your Vinespeakers also
    improve the Health given
    by your <b>Blood Gems</b>.

    Status: DEFERRED — requires 关联卡 BG35_437 迁移 + Health 增量通道

    Dependency: (a) `BG35_437` Vinespeaker **未注册**（REGISTRY 核实;
    36.2.2 已移出随从池），其本体 "After a friendly Deathrattle minion
    dies, your Blood Gems give an extra +2 Attack this game" 无脚本 →
    "your Vinespeakers" 无触发行为; (b) "also improve the Health" 需要
    Vinespeaker 的 `ImproveBloodGems` 出口读取 hero 级 Health 增量
    （生产消费点），否则本饰品写标记也是假接线（SOP §14 item 1）。
    RULES §7.4.6 例外条（依赖被授予卡行为）。

    Params: 无模板参数
    """

    @staticmethod
    def on_bind(source, game, ctx):
        return None


# ══════════════ 注册 ══════════════


def register() -> list[str]:
    """注册饰品第十七批 17 张 + Spellcraft 法术 1 张
    （DEFERRED 3 张见模块 docstring，不注册）。"""
    from hsrl2.scripts.registry import register as reg

    pairs = [
        ("BG32_MagicItem_953", GoldgrubberPortraitScript),
        ("BG32_MagicItem_954", AuricOfferingScript),
        ("BG32_MagicItem_960", CrochetedSungillScript),
        ("BG32_MagicItem_998", BehemothPortraitScript),
        ("BG35_MagicItem_150", CursedCrystalScript),
        ("BG35_MagicItem_151", DefilerPortraitScript),
        ("BG35_MagicItem_152", DemonicTapestryScript),
        ("BG35_MagicItem_154", UrzulStickerScript),
        ("BG35_MagicItem_155", FelburnedLedgerScript),
        ("BG35_MagicItem_300", CopperCoilScript),
        ("BG35_MagicItem_303", SkipperPortraitScript),
        ("BG35_MagicItem_305", ConchPortraitScript),
        ("BG35_MagicItem_306", JailerStickerScript),
        ("BG35_MagicItem_306t", JailerStickerSpellScript),
        ("BG35_MagicItem_309", ErrglStickerScript),
        ("BG35_MagicItem_310", RadioStarPortraitScript),
        ("BG35_MagicItem_430", ScrapsmithPortraitScript),
        ("BG35_MagicItem_432", BloodAmuletScript),
    ]
    registered = []
    for tid, cls in pairs:
        reg(tid, cls)
        registered.append(tid)
    return registered
