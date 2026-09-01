"""批次 hero_passives2 — 被动英雄技能第二批 15 项（作业单 2026-08-23）。

前置: 引擎已就绪三大原语（本批解冻依赖，grep 验证 2026-08-23）:
  - ``Game.start_game`` 对每个英雄调 ``REGISTRY[power.id].on_bind``（
    game.py:160-172，hero_passives 批上报缺口 #1 已修）
  - ``end_recruit_phase`` 广播 ``turn_end``（game.py:1413-1415，缺口 #2
    已修——EoT 效果之前、与 TURN_START 对称）
  - ``replace_hero_power``（game.py:899）+ ``hero_power_def`` 优先读
    ``hero._active_power_id``（缺口 #3 已修）

数据侦察（36.2.2 bg_hero_powers.json 162 项，剔除 hero_passives /
hero_actives 两批已注册 31 项后的被动剩余）+ 逐卡 wiki 查证选卡 15:

  OK 15（注册键 = 技能 card_id）:
    TB_BaconShop_HP_087  Ragnaros BUY, INSECT!（DEFERRED 解冻）
    TB_BaconShop_HP_087t Sulfuras（Ragnaros 替换目标，独立注册）
    BG20_HERO_102p       Overlord Saurfang For the Horde!
    BG28_HERO_800p       Tae'thelan Bloodwatcher
    BG24_HERO_204p       Enhance-o Mechano Enhancification
    TB_BaconShop_HP_038  King Mukla Bananarama
    BG20_HERO_280p5      Kurtrus Ashfallen Glaive Ricochet
    BG26_HERO_104p       Rock Master Voone Upbeat Harmony
    TB_BaconShop_HP_088  Chenvaala Avalanche
    TB_BaconShop_HP_107  Greybough Sprout It Out!
    TB_BaconShop_HP_042  Dancin' Deryl Hat Trick
    TB_BaconShop_HP_080  Mr. Bigglesworth Kel'Thuzad's Kitty
    TB_BaconShop_HP_085t Rakanishu Tavern Lighting
    BG_EX1_014t          Bananas（Mukla token 支撑脚本，此前未注册）
    BG_TB_006            Big Banana（同上）

  DEFERRED 台账（查证不足/引擎缺口，不注册——二态铁律 SOP §6b）:
    BG21_HERO_000p  Cariel "Conviction"——主动面 "Give {2} random
        friendly minions +{0}/+{1}" 可实现，但被动面 "After each combat,
        choose an improvement" 的改进选项集为客户端硬编码; wiki
        Cariel Roame / HSReplay 页均无选项枚举（2026-08-23 查证）→
        部分实现 = 第三态，整体 DEFERRED。
    TB_BaconShop_HP_054 Millhouse——"Minions and Refreshes cost 2 Gold.
        Upgrading costs (1) more": 刷新费在 refresh_tavern 内联
        spend_gold(C.REFRESH_COST)（game.py:290）无覆写钩子; 随从购买费
        亦无持久覆写点（buy_from_tavern 逐实体读 COST tag）→ 需主线:
        持久 buy/refresh 费用覆写协议。
    BG35_HERO_001p   Genn "King of Duality"——"Discover two Hero Powers
        to replace this"（35.2 新增; wiki 仅 Dis cover/Replace 机制标签）。
        34.2 补丁确立 "second Hero Power" 官方概念（Timewarped Power
        系列全部 "Make X your second Hero Power"）——双技能并行/轮换
        语义无公开细节; 引擎 hero._active_power_id 单槽。候选集亦未公布。
    TB_BaconShop_HP_057 Finley "Adventure!"——"Discover a Hero Power"
        候选集无任何官方记载（本局英雄? 全池? 含被动?）; wiki 英雄页
        无 Notes（2026-08-23 查证）。
    BG20_HERO_202p   Master Nguyen——同上候选集缺口 + 每回合轮换接线。
    BG33_HERO_001p_ALT Loh / BG20_HERO_242p Guff——"get a Triple Reward"
        的奖励 tier 规则未公布（常规三连 = 被三连卡 tier+1，引擎
        _grant_triple_reward 亦锚定金色实体; 英雄技能授予场景无来源卡;
        wiki Triple Reward token 文本 "Discover a minion from Tier {动态}"
        未给规则; patch notes 无）→ 奖励面不可证。
    TB_BaconShop_HP_069 Illidan / BG22_HERO_305p Onyxia——"attack
        immediately" 依赖 insert_attack 嵌套攻击原语（AGENTS.md 已知缺口）。
    BG22_HERO_004p   Varden——"Freeze them both" 需随从级冻结粒度
        （引擎 freeze_tavern 仅整馆）。
    TB_BaconShop_HP_065 Aranna——"the first minion you buy each turn is
        free" 需随从购买折扣 tag（引擎仅 NEXT_SPELL_COST_REDUCTION
        法术侧）。
    TB_BaconShop_HP_014 Sindragosa——随从费(2)+馆少 1 展示+EoT 整馆
        冻结三钩子（经济覆写协议缺失）。

引擎缺口汇总（新上报主线）:
  1. 持久随从购买费/刷新费覆写协议（Millhouse/Sindragosa/Aranna 阻塞）
  2. ELEMENTAL_PLAYED 常量声明但引擎零 fire（events.py:45）——本批
     Chenvaala 经 card_played+种族过滤替代实现（语义等价），常量待清理
  3. 英雄技能多槽/候选集协议（Genn/Finley/Nguyen 阻塞——候选集首先
     需官方证据）
  4. "get a Triple Reward" 奖励 tier 规则（Loh/Guff 阻塞，需查证或
     官方规则补充）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2 import entity
from hsrl2.actions import GainKeyword
from hsrl2.actions.tavern_buff import ApplyTavernBuff, BuffCurrentTavern, \
    TavernBuff
from hsrl2.events import (
    CARD_PLAYED,
    HERO_ELIMINATED,
    MINION_BOUGHT,
    MINION_SOLD,
    SUMMON,
    TAVERN_REFRESH,
    TURN_END,
    TURN_START,
    Listener,
)
from hsrl2.game import GameStateError, PendingChoice, _plain_copy_to_hand
from hsrl2.minion import Minion
from hsrl2.spell import Spell
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

# 事件名常量 events.py 未导出（引擎以字面量 fire，game.py:389）
SPELL_BOUGHT = "spell_bought"

# ── 官方 "Bonus Keyword" 池（wiki.gg Battlegrounds/Bonus_Keyword 定义页，
# 2026-08-23 查证: "one of 6 keywords ... Divine Shield, Reborn, Stealth,
# Taunt, Venomous, or Windfury"——不含 Poisonous/Cleave）──
_BONUS_KEYWORD_TAGS = (
    GameTag.DIVINE_SHIELD,
    GameTag.REBORN,
    GameTag.STEALTH,
    GameTag.TAUNT,
    GameTag.VENOMOUS,
    GameTag.WINDFURY,
)

_ELEMENTAL_RACES = (Race.ELEMENTAL, Race.ALL)

# Tae'thelan 免费标记值: 引擎 buy_from_tavern 以 max(0, cost - discount)
# 结算 NEXT_SPELL_COST_REDUCTION（game.py:360-363），任何 ≥ 最高法术价
# 的值即 "costs (0)" 的可观测等价（机制常量，非卡牌数值）
_FREE_SPELL_SENTINEL = 10 ** 6

# Mukla 香蕉 token 卡 id（power CardDef 无 evolution 链 → 卡 id 字面量，
# 引擎 FODDER_CARD_ID 先例; 数值/文本由 token CardDef 权威）
_BANANA_ID = "BG_EX1_014t"       # Bananas "Give a minion +1/+1."
_BIG_BANANA_ID = "BG_TB_006"     # Big Banana "Give a minion +2/+2."

# Chenvaala 文本字面量（CardDef 无模板参数）
_ELEMENTALS_PER_REDUCE = 3       # "After you play 3 Elementals"
_UPGRADE_COST_REDUCE = 3         # "reduce the Cost of upgrading by (3)"


def _power_def(game: "Game", power_id: str):
    d = game.db.get(power_id)
    if d is None:
        raise GameStateError(f"unknown hero power {power_id!r}")
    return d


# ═══════════════════ TB_BaconShop_HP_087 Ragnaros BUY, INSECT! ═══════════════════

class RagnarosScript:
    """
    Natural language: After you buy 12 cards, get Sulfuras. <i>(@ left!)</i>

    依据（2026-08-23 查证）: wiki Battlegrounds/BUY,_INSECT!——36.2.0
    起 16→12（与 36.2.2 数据 TAG_SCRIPT_DATA_NUM_1=12 一致）; wiki
    mechanics 标注 Passive Hero Power + **Replace Hero Power**;
    BACON_EVOLUTION_CARD_ID=64426 → Sulfuras。引擎 replace_hero_power
    + turn_end 广播已由主线落地（本批 DEFERRED 解冻条件齐备）。

    Formal spec:
      1. on_bind 注册两个持久监听器（owner=hero）:
         a) minion_bought (minion=)——minion.controller is hero
         b) spell_bought (spell=, hero=)——hero is 绑定英雄
         "12 cards" = 任何购买（随从 + 酒馆法术; wiki Buying-related
         标签覆盖两类购买路径）
      2. 计数: 闭包 state 跨回合计数; 达 num(0)=12 触发一次即完成
         （Sulfuras 为终态技能，无 repeat）
      3. 触发: Sulfuras 卡 id 经 power CardDef evolution_card_id
         （dbf 64426）数据链解析（零硬编码）→ game.replace_hero_power
         （hero_power_def 此后优先返回 Sulfuras; 官方 wiki "Replace
         Hero Power" 语义）→ 立即调 SulfurasScript.on_bind 注册 EoT
         监听（start_game 接线只覆盖开局技能，替换时点需脚本自接线;
         当回合 turn_end 即生效）
      4. done 标记后两监听器退化为 no-op（技能身份已切换，计数终止）

    Test: test_batch_hero_passives2.py — 买 11 张不替换 / 第 12 张
    （随从+法术混合计数）替换为 Sulfuras / 替换后同回合 turn_end 即
    双端 +8/+8 / use_hero_power 恒 False（passive 协议）

    Params: {0}=12（script_data_num_1; 阈值）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "TB_BaconShop_HP_087")
        threshold = d.num(0)
        if threshold is None or d.evolution_card_id is None:
            raise GameStateError(
                "TB_BaconShop_HP_087: broken data chain "
                f"(num0={threshold}, evo={d.evolution_card_id})")
        sulfuras_def = game.db.by_dbf(d.evolution_card_id)
        if sulfuras_def is None:
            raise GameStateError(
                f"TB_BaconShop_HP_087: evolution dbf "
                f"{d.evolution_card_id} not in db")
        state = {"bought": 0, "done": False}

        def _maybe_swap(g) -> None:
            if state["done"] or state["bought"] < threshold:
                return
            state["done"] = True
            g.replace_hero_power(hero, sulfuras_def.id)
            from hsrl2.scripts import REGISTRY
            sulf_script = REGISTRY.get(sulfuras_def.id)
            if sulf_script is not None and hasattr(sulf_script, "on_bind"):
                sulf_script.on_bind(hero, g)

        def on_minion_bought(g, minion=None, **kw):
            if state["done"] or not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            state["bought"] += 1
            _maybe_swap(g)

        def on_spell_bought(g, hero=None, _owner=hero, **kw):
            if state["done"] or hero is not _owner:
                return
            state["bought"] += 1
            _maybe_swap(g)

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_minion_bought))
        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=hero, callback=on_spell_bought))


# ═══════════════════ TB_BaconShop_HP_087t Sulfuras ═══════════════════

class SulfurasScript:
    """
    Natural language: At the end of your turn, give your left and right-
    most minions +8/+8.

    依据（2026-08-23 查证）: wiki Battlegrounds/Sulfuras——36.2.0 现行
    文本 +8/+8（33.6 时 +4/+4→36.2 提升为 +8/+8）; mechanics: Passive
    Hero Power; END_OF_TURN_TRIGGER=1。CardDef 无模板参数 → 文本字面量。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: turn_end (turn=)——
         end_recruit_phase 全局单次广播（game.py:1415，EoT 随从效果
         之前）; BG 回合全体同步结束，单次广播即 "your turn" ✓
      2. 目标集 = 去重{board[0], board[-1]}（ZONE_POSITION 最左/最右
         存活语义: 棋盘列表序 = 位置序; 空板落空）
         边角: 单随从棋盘左右同一实体 → 去重后单次 +8/+8（官方对
         "单随从双吃" 边缘行为无记载——wiki Sulfuras 页无 Notes,
         取单效果双目标读法，保守单次; 注记待主线/官方裁定）
      3. 触发: 各目标 add_buff(entity.Buff(atk=8, health=8))——永久
         Buff（回合结束增益跨回合保留，官方语义）; 每回合一次

    Test: test_batch_hero_passives2.py — 三随从板 turn_end 后最左/最右
    各 +8/+8 中间不变 / 单随从板单次 +8/+8 / 空板安全

    Params: atk=8 health=8（"+8/+8" 文本字面量——CardDef 无模板参数）
    """

    passive = True
    _ATK_GAIN = 8     # "+8/+8"（wiki 36.2 现行文本字面量）
    _HP_GAIN = 8

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        atk_gain = SulfurasScript._ATK_GAIN
        hp_gain = SulfurasScript._HP_GAIN

        def on_turn_end(g, turn=0, **kw):
            if not hero.board:
                return
            targets = [hero.board[0]]
            if hero.board[-1] is not hero.board[0]:
                targets.append(hero.board[-1])
            for m in targets:
                if not m.dead:
                    m.add_buff(entity.Buff(atk=atk_gain, health=hp_gain))

        game.events.register(Listener(
            event=TURN_END, owner=hero, callback=on_turn_end))


# ═══════════════════ BG20_HERO_102p Overlord Saurfang ═══════════════════

class OverlordSaurfangScript:
    """
    Natural language: Minions in the Tavern have +{1}/+{1}. Improves after
    you buy 3 minions. <i>({0} left!)</i>

    依据（2026-08-23 查证）: wiki Battlegrounds/For_the_Horde!——36.2.0
    起 "Improves after you buy 3 minions"（此前 4/5; 33.6 重做为光环）;
    AURA=1 标签; num(0)=3（触发阈值）num(1)=1（初始与递增值）。引擎
    TavernBuff 持久面 + refresh_tavern 自动应用（game.py:314-320）即
    本光环的官方模型（buff 入实体，购买后保留——BuffCurrentTavern
    docstring 语义）。

    Formal spec:
      1. on_bind: ApplyTavernBuff(TavernBuff(atk=num(1), health=num(1),
         race_filter=None——不限种族))——登记持久面（此后每次刷新的
         新入馆随从自动应用，引擎接线）+ BuffCurrentTavern 立即面
         （开局绑定时馆空 → no-op; 测试中途绑定生效）
      2. 改善面: minion_bought (minion=) 计数（controller is hero）;
         每 num(0)=3 只追加**一条新的** +num(1)/+num(1) TavernBuff
         （TavernBuff 不可变——多条叠加 = 光环值递增: 新入馆随从获得
         全部条目之和）+ BuffCurrentTavern 施加**增量**（当前馆内
         随从即时 +num(1)/+num(1)——官方 "Improves" 对在场展示即时
         生效）
      3. 购买: 已购买随从的 Buff 随实体带走（引擎语义 ✓ 官方: 光环
         属性在购买时烙印为实体属性）; 刷新回池走 release(card_id)
         计数语义，buff 不入池无泄漏
      4. 递进跨回合累积（计数不随回合清零）

    Test: test_batch_hero_passives2.py — 刷新入馆随从全体 +1/+1 /
    买 2 只不改善 / 第 3 只后馆内即时再 +1/+1 且下次刷新新随从共
    +2/+2 / 敌方购买不计数

    Params: {0}=3 {1}=1（script_data_num_1/2）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "BG20_HERO_102p")
        threshold = d.num(0)
        gain = d.num(1)
        if threshold is None or gain is None:
            raise GameStateError(
                "BG20_HERO_102p: missing template params")
        state = {"bought": 0}

        def _step(g) -> None:
            tb = TavernBuff(atk=gain, health=gain,
                            source_id="BG20_HERO_102p")
            g.run_actions([ApplyTavernBuff(hero, tb),
                           BuffCurrentTavern(hero, tb)])

        _step(game)   # 初始 +num(1)/+num(1)（持久面 + 立即面）

        def on_bought(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            state["bought"] += 1
            if state["bought"] >= threshold:
                state["bought"] -= threshold
                _step(g)   # 改善: 追加一条 + 增量立即面

        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_bought))


# ═══════════════════ BG28_HERO_800p Tae'thelan Bloodwatcher ═══════════════════

class TaethelanScript:
    """
    Natural language: Every third Tavern spell you buy costs (0).
    <i>({0} left!)</i>

    依据（2026-08-23 查证）: 数据文本 + HSReplay/Kripp 对局实证
    "Every third Tavern spell you buy costs 0"; num(0)=2（"2 left" ——
    每 2 次付费购买后下一次免费）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: spell_bought (spell=,
         hero=)——hero is 绑定英雄（所有酒馆法术购买路径）
      2. 计数: 闭包 state 终局计数（mod 3）; 第 num(0)=2 次购买后置
         NEXT_SPELL_COST_REDUCTION = max(现值, _FREE_SPELL_SENTINEL)
         ——引擎 buy_from_tavern 对 is_pool_spell 以 max(0, cost -
         discount) 结算并消耗该 tag（game.py:360-363）→ 第 3 次购买
         可观测费用恰为 0 ✓ 官方 "costs (0)"
      3. 第 3 次购买（spell_bought 观测）: 计数归零（免费的那次同样
         是 "买"）; sentinel 已被引擎消耗
      4. 跨回合: 计数与 sentinel 均留存——第 2 次购买后未买第 3 次
         即结束回合，下回合法术首购即为第 3 次（免费）✓ 终局 mod 语义
      5. 与其他折扣源共存: sentinel 取 max 不覆盖既有折扣; Ominous
         Seer 类 +1 叠加在 sentinel 之上仍 ≥ 任何法术价 → 免费语义
         不被破坏

    Test: test_batch_hero_passives2.py — 第 1/2 个法术全价 / 第 3 个
    恰 0 金 / 第 4/5 全价第 6 免费 / 跨回合窗口保持（第 2 次后过回合，
    下回合首购免费）/ 敌方购买不计数

    Params: {0}=2（script_data_num_1; 两次付费后第三次免费）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        paid_window = _power_def(game, "BG28_HERO_800p").num(0)
        if paid_window is None:
            raise GameStateError("BG28_HERO_800p: missing template params")
        state = {"bought": 0}

        def on_spell_bought(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            state["bought"] += 1
            if state["bought"] == paid_window:
                cur = _owner.get(GameTag.NEXT_SPELL_COST_REDUCTION, 0)
                _owner.set(GameTag.NEXT_SPELL_COST_REDUCTION,
                           max(cur, _FREE_SPELL_SENTINEL))
            elif state["bought"] > paid_window:
                state["bought"] = 0   # 免费那次已购（sentinel 被引擎消耗）

        game.events.register(Listener(
            event=SPELL_BOUGHT, owner=hero, callback=on_spell_bought))


# ═══════════════════ BG24_HERO_204p Enhance-o Mechano ═══════════════════

class EnhanceOScript:
    """
    Natural language: After the Tavern is Refreshed, give a random minion
    in it a random Bonus Keyword, twice.

    依据（2026-08-23 查证）: wiki Battlegrounds/Enhancification——36.2.0
    起追加 "twice"（此前单次）; 33.6 起枚举列表改术语 "Bonus Keyword"。
    Bonus Keyword 池 = wiki Battlegrounds/Bonus_Keyword 定义页: 6 关键词
    Divine Shield / Reborn / Stealth / Taunt / Venomous / Windfury（
    本批 _BONUS_KEYWORD_TAGS，与 batch_spells_final 的 S14 移转 8 词集
    不同——那是 Dark Gift 移转语境，本卡用官方 6 词定义页）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: tavern_refresh (hero=)
         ——refresh_tavern 末尾 fire（auto 回合开始刷新与手动刷新双
         路径，官方 "whenever it is Refreshed" ✓; hero is 绑定英雄）
      2. 触发: 两次**独立**随机授予（36.2 "twice"; Kelp Keeper "twice
         = 2 次独立随机触发" 先例）: 每次从馆内 Minion 中 rng.choice
         一个 + 从 6 词池 rng.choice 一个 → run_actions(GainKeyword)
         （fire keyword_gained; 关键词入实体 tag——购买后保留 ✓ 官方
         "Magnetic 保留 Enhancification 关键词" bugfix 佐证实体级）
      3. 馆内无法师约束——仅 Minion; 空馆（无法术可授予的对象）落空;
         两次可命中同一随从/同一关键词（tag 幂等，无叠加效应）
      4. 冻结不触发额外授予（刷新才 fire）

    Test: test_batch_hero_passives2.py — 每次刷新恰 fire 2 次
    keyword_gained 且 tag ∈ 官方 6 词集 / 授予对象为馆内随从 / 敌方
    刷新不触发

    Params: 无模板参数（"twice"=2 次独立授予——频次字面量）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def on_refresh(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            minions = [e for e in _owner.tavern
                       if isinstance(e, Minion)]
            for _ in range(2):
                if not minions:
                    return
                m = g.rng.choice(minions, label="enhance_o_target")
                tag = g.rng.choice(_BONUS_KEYWORD_TAGS,
                                   label="enhance_o_keyword")
                g.run_actions(GainKeyword(m, tag))

        game.events.register(Listener(
            event=TAVERN_REFRESH, owner=hero, callback=on_refresh))


# ═══════════════════ TB_BaconShop_HP_038 King Mukla Bananarama ═══════════════════

class KingMuklaScript:
    """
    Natural language: At the start of your turn, get 2 Bananas and give
    everyone else one.

    依据（2026-08-23 查证）: wiki Battlegrounds/Bananarama——26.6.0 改
    为被动; **26.6.2: "All bananas have a 33% chance of being a Big
    Banana, regardless of who receives them"**（此后无回滚补丁记载 →
    36.2.2 现行行为）。Bananas = BG_EX1_014t "Give a minion +1/+1." /
    Big Banana = BG_TB_006 "Give a minion +2/+2."（36.2.2 数据核实;
    token 非池卡 is_pool_spell=False → 生成不占池）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: turn_start (turn=,
         hero=)——hero is 绑定英雄（每回合一次）
      2. 授予: 自身 2 根 + 其余**存活**英雄各 1 根; 每根独立 33% 判定
         Big（rng.choice 三元组 1/3 命中——patch note 33% 权威）;
         create_spell + pending_hand_add（满手排队，接收方为各英雄
         自己的手牌）
      3. token 非池卡: 不占法术池; 出售/淘汰回池路径对非池法术自动
         跳过（池守恒）
      4. 打出闭环: Bananas / Big Banana 的定向 buff 脚本本批注册
         （BananasScript / BigBananaScript——needs_target 协议）
      5. 卡 id 字面量 _BANANA_ID/_BIG_BANANA_ID（power CardDef 无
         evolution 链，引擎 FODDER_CARD_ID 先例; 效果数值由 token
         CardDef 权威，零数值硬编码）

    Test: test_batch_hero_passives2.py — turn_start 后自身手牌 +2 根
    / 对手 +1 根 / 每根 ∈ {Bananas, Big Banana} 且 33% 判定走 game.rng
    （决策日志含标签）/ 打出 Bananas 定向 +1/+1、Big Banana +2/+2

    Params: self_count=2 others_count=1（文本字面量——CardDef 无模板
            参数; "2 Bananas"/"one"）; big_chance=1/3（patch note 33%）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        def _banana(g, recipient: "Hero"):
            roll = g.rng.choice((0, 1, 2), label="mukla_big_banana")
            cid = _BIG_BANANA_ID if roll == 0 else _BANANA_ID
            g.pending_hand_add(
                recipient, g.create_spell(cid, controller=recipient))

        def on_turn_start(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            for _ in range(2):
                _banana(g, _owner)
            for other in g.heroes:
                if other is _owner or not other.is_alive:
                    continue
                _banana(g, other)

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════════ BG20_HERO_280p5 Kurtrus Ashfallen ═══════════════════

class KurtrusScript:
    """
    Natural language: Once per turn, after you buy 3 minions, get a plain
    copy of one of them. <i>({0} left!)</i>

    依据（2026-08-23 查证）: wiki Battlegrounds/Glaive_Ricochet——
    27.2.0 起 "Discover"→"get"（无选择 UI → 随机）; 27.6 bugfix
    "did not give a copy of the Golden Monkey"（token 亦在复制范围）;
    num(0)=3。

    Formal spec:
      1. on_bind 注册两个持久监听器（owner=hero）:
         a) turn_start (hero=)——回合窗口重置（计数清零 + once 标记
            复位）; hero is 绑定英雄
         b) minion_bought (minion=)——controller is hero
      2. 计数窗口: 本回合购买序列（闭包 state）; 第 num(0)=3 只时:
         rng.choice(窗口 3 只) → game._plain_copy_to_hand（引擎先例
         "复制自有卡不消耗池副本"; 金色源→金色复制，token card_id
         直接 create——Golden Monkey bugfix 语义 ✓; 无 buff plain）
      3. "Once per turn": 触发后本回合 done 标记——后续购买不再计数
         （窗口冻结）; 下一 turn_start 复位
      4. 购买计数仅随从（法术走 spell_bought，"3 minions" 严格词）

    Test: test_batch_hero_passives2.py — 买 2 只不触发 / 第 3 只手牌
    出现窗口内某只的 plain 副本（card_id ∈ 3 id 集、无源 buff）/ 同
    回合再买 3 只不二触发 / turn_start 复位后再触发 / 敌方购买不计数

    Params: {0}=3（script_data_num_1; 触发窗口）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        window = _power_def(game, "BG20_HERO_280p5").num(0)
        if window is None:
            raise GameStateError("BG20_HERO_280p5: missing template params")
        state: dict = {"window": [], "done": False}

        def on_turn_start(g, hero=None, _owner=hero, **kw):
            if hero is not _owner:
                return
            state["window"] = []
            state["done"] = False

        def on_bought(g, minion=None, **kw):
            if state["done"] or not isinstance(minion, Minion):
                return
            if minion.controller is not hero:
                return
            state["window"].append(minion)
            if len(state["window"]) >= window:
                pick = g.rng.choice(state["window"], label="kurtrus_copy")
                _plain_copy_to_hand(g, pick, "glaive_ricochet")
                state["done"] = True

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))
        game.events.register(Listener(
            event=MINION_BOUGHT, owner=hero, callback=on_bought))


# ═══════════════════ BG26_HERO_104p Rock Master Voone ═══════════════════

class RockMasterVooneScript:
    """
    Natural language: At the end of every 3 turns, get a plain copy of
    the left-most card in your hand. <i>({0} turns left!)</i>

    依据: 数据文本（num(0)=3 周期; "End of this turn!" 提示变体）;
    turn_end 引擎广播已就绪（game.py:1415）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: turn_end (turn=)——
         全局单次广播; turn % num(0) == 0 即第 3/6/9… 回合结束触发
         （事件 turn 参数权威，无计数器漂移）
      2. 复制对象: hand[0]（ZONE_POSITION 0 = 最左; 手牌列表序 =
         位置序）——**任意卡类型**: Minion → game._plain_copy_to_hand
         （金色源→金色复制先例; 无 buff）; Spell → create_spell 同 id
         plain 副本。副本经 pending_hand_add 入手（满手排队）
      3. 复制自有卡不消耗池副本（引擎先例）; 空手落空
      4. "every 3 turns" 恒定周期（非一次性）

    Test: test_batch_hero_passives2.py — turn=2 结束无动作 / turn=3
    结束手牌最左（随从）多出同 id plain 副本 / 法术最左同样复制 /
    空手安全 / turn=6 再次触发

    Params: {0}=3（script_data_num_1; 周期）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        period = _power_def(game, "BG26_HERO_104p").num(0)
        if period is None:
            raise GameStateError("BG26_HERO_104p: missing template params")

        def on_turn_end(g, turn=0, **kw):
            if turn <= 0 or turn % period != 0 or not hero.hand:
                return
            left_most = hero.hand[0]
            if isinstance(left_most, Minion):
                _plain_copy_to_hand(g, left_most, "upbeat_harmony")
            elif isinstance(left_most, Spell):
                g.pending_hand_add(
                    hero, g.create_spell(left_most.card_id,
                                         controller=hero))

        game.events.register(Listener(
            event=TURN_END, owner=hero, callback=on_turn_end))


# ═══════════════════ TB_BaconShop_HP_088 Chenvaala ═══════════════════

class ChenvaalaScript:
    """
    Natural language: After you play 3 Elementals, reduce the Cost of
    upgrading the Tavern by (3).

    依据: 数据文本（CardDef 无模板参数 → 双 3 为文本字面量）。
    ELEMENTAL_PLAYED 常量引擎零 fire（本批缺口 #2）→ 经 card_played
    + 种族过滤等价实现（game.py:453 磁力路径 / :536 常规打出路径均
    fire——磁力吸附的打出同样计入 ✓ 官方 "play" 语义）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: card_played (card=)
         ——card 为 Minion 且 card.controller is hero 且 race ∈
         (ELEMENTAL, ALL)（Amalgam 规则 RULES §6.18）
      2. 计数: 闭包 state 跨回合计数; 每 3 只（_ELEMENTALS_PER_REDUCE）
         触发: hero.UPGRADE_COST -= 3（_UPGRADE_COST_REDUCE; 引擎
         upgrade_tavern 读该 tag 且 max(FLOOR=0) 结算——负值防御）
      3. 减费为**当前值**扣减（官方 "reduce the Cost of upgrading" =
         当次升级费的永久扣减; 升级后引擎重置为下一档标准费
         BASE_UPGRADE_COSTS——扣减不跨档携带 ✓）; repeat: 每 3 只
         再触发
      4. 0/1 攻随从打出照常计数（"play" 不看攻击力）

    Test: test_batch_hero_passives2.py — 打 2 只元素不减 / 第 3 只
    UPGRADE_COST -3 / 取模 repeat（第 6 只再 -3）/ 升级后重置为标准
    档位费 / 非元素打出不计

    Params: count=3 reduce=3（双 3 为文本字面量——CardDef 无模板参数）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        state = {"played": 0}

        def on_card_played(g, card=None, **kw):
            if not isinstance(card, Minion):
                return
            if card.controller is not hero or card.race not in \
                    _ELEMENTAL_RACES:
                return
            state["played"] += 1
            if state["played"] >= _ELEMENTALS_PER_REDUCE:
                state["played"] -= _ELEMENTALS_PER_REDUCE
                hero.set(GameTag.UPGRADE_COST,
                         max(0, hero.upgrade_cost - _UPGRADE_COST_REDUCE))

        game.events.register(Listener(
            event=CARD_PLAYED, owner=hero, callback=on_card_played))


# ═══════════════════ TB_BaconShop_HP_107 Greybough ═══════════════════

class GreyboughScript:
    """
    Natural language: Give +1/+2 and Taunt to minions you summon during
    combat.

    依据: 数据文本 "Sprout It Out!"（CardDef 无模板参数 → +1/+2 文本
    字面量）。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: summon (minion=)——
         game.summon 统一入口（亡语召唤/SoC 召唤/战斗召唤全路径 fire）
      2. 条件: g.in_combat（"during combat"——招募期打出/购买入场不
         触发）且 minion.controller is hero
      3. 触发: add_buff(entity.Buff(atk=1, health=2)) + set TAUNT
         （GainKeyword 动作，fire keyword_gained）; 战斗召唤物为临时
         实体战后随复原消失，buff/嘲讽仅本场生效 ✓ 官方临时召唤语义
      4. 满板 minion_overflow 落空不触发（summon 失败路径不 fire
         summon 事件）

    Test: test_batch_hero_passives2.py — in_combat 下召唤 +1/+2+嘲讽 /
    非战斗召唤不触发 / 敌方战斗召唤不触发

    Params: atk=1 health=2（"+1/+2" 文本字面量）
    """

    passive = True
    _ATK_GAIN = 1     # "+1/+2"（文本字面量）
    _HP_GAIN = 2

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        atk_gain = GreyboughScript._ATK_GAIN
        hp_gain = GreyboughScript._HP_GAIN

        def on_summon(g, minion=None, **kw):
            if not isinstance(minion, Minion):
                return
            if not g.in_combat or minion.controller is not hero:
                return
            minion.add_buff(entity.Buff(atk=atk_gain, health=hp_gain))
            minion.set(GameTag.TAUNT, True)

        game.events.register(Listener(
            event=SUMMON, owner=hero, callback=on_summon))


# ═══════════════════ TB_BaconShop_HP_042 Dancin' Deryl ═══════════════════

class DancinDerylScript:
    """
    Natural language: When you play a minion, give it a +1/+1 hat that
    passes to a friendly minion when sold.

    依据: 数据文本 "Hat Trick"（num(0)=num(1)=1 → +num(0)/+num(1)）。
    帽子传递目标为随机友方（被动无选择 UI; "passes to a friendly
    minion" 不定指 → rng）。

    Formal spec:
      1. on_bind 注册两个持久监听器（owner=hero）:
         a) card_played (card=)——card 为 Minion 且 controller is hero
            （含磁力吸附打出路径 game.py:453 ✓ "play a minion"）:
            add_buff(Buff(atk=num(0), health=num(1), source_id=
            "TB_BaconShop_HP_042")) + 闭包 hats[uuid] += 1（帽子记账）
         b) minion_sold (minion=)——controller is hero 且 hats 有账:
            每顶帽子独立传递——recipient = rng.choice(己方棋盘存活且
            ≠ 卖出者)（sell_minion 在移除前 fire（game.py:408），须显式
            排除卖出者）; recipient add_buff(+num(0)/+num(1)) 且
            hats[recipient.uuid] += 1（帽子随实体传承——再卖出时继续
            传递 ✓ "passes to a friendly minion when sold" 链式语义）
      2. 多顶帽子叠加（多次打出同随从? 不可——打出即离手; 场景为
         传递后 recipient 再获新帽）; 无其他友方随从时帽子丢失
         （官方无保留载体，诚实落空）
      3. 手牌出售路径: 手牌随从无帽（帽只在打出时给）→ 不触发

    Test: test_batch_hero_passives2.py — 打出随从 +1/+1 / 卖出后帽子
    传给随机其他棋盘随从（+1/+1 且可继续传承）/ 独自卖出帽子丢失 /
    敌方打出不触发

    Params: {0}=1 {1}=1（script_data_num_1/2; +num(0)/+num(1)）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "TB_BaconShop_HP_042")
        atk_gain = d.num(0)
        hp_gain = d.num(1)
        if atk_gain is None or hp_gain is None:
            raise GameStateError("TB_BaconShop_HP_042: missing params")
        hats: dict = {}

        def _hat_buff(g, m):
            m.add_buff(entity.Buff(atk=atk_gain, health=hp_gain,
                                   source_id="TB_BaconShop_HP_042"))

        def on_card_played(g, card=None, **kw):
            if not isinstance(card, Minion) or card.controller is not hero:
                return
            _hat_buff(g, card)
            hats[card.uuid] = hats.get(card.uuid, 0) + 1

        def on_sold(g, minion=None, **kw):
            if not isinstance(minion, Minion) or minion.controller is not \
                    hero:
                return
            n = hats.pop(minion.uuid, 0)
            for _ in range(n):
                others = [m for m in hero.board
                          if m is not minion and not m.dead]
                if not others:
                    return   # 无传递载体，帽子丢失（诚实落空）
                recipient = g.rng.choice(others, label="deryl_hat_pass")
                _hat_buff(g, recipient)
                hats[recipient.uuid] = hats.get(recipient.uuid, 0) + 1

        game.events.register(Listener(
            event=CARD_PLAYED, owner=hero, callback=on_card_played))
        game.events.register(Listener(
            event=MINION_SOLD, owner=hero, callback=on_sold))


# ═══════════════════ TB_BaconShop_HP_080 Mr. Bigglesworth ═══════════════════

class MrBigglesworthScript:
    """
    Natural language: After another hero dies, Discover a minion from
    their warband. It keeps enchantments.

    依据（2026-08-23 查证）: wiki Battlegrounds/Kel'Thuzad's_Kitty——
    mechanics: Discover + Keep enchantment + Passive Hero Power;
    DISCOVER=1/USE_DISCOVER_VISUALS=1 标签。

    Formal spec:
      1. on_bind 注册持久监听器（owner=hero）: hero_eliminated (hero=)
         ——_process_eliminations 末尾 fire（game.py:1588）; 阵亡英雄
         board 列表此刻仍持有其实体（回池=池计数归还 + zone=REMOVED，
         不清 board 列表 → 事件时点可读战力编成与附魔 ✓）
      2. 条件: hero（阵亡者）is not 绑定英雄（"another hero"; 自身若
         已阵亡则 is_alive=False 守卫直接返回——阵亡猫不再触发）
      3. Discover 选项: 阵亡者棋盘随从中 rng.sample 上限 3（Discover
         标准 3 选项; 板不足 3 全量; 空板落空）→ PendingChoice(kind=
         "discover_minion")（choose 触发 card_discovered 事件——
         Hooktusk 族联动 ✓）
      4. 选定: create_minion(pick.card_id, golden=pick.is_golden)
         （金色源→金色复制——金色 def 直建 + GOLDEN/TRIPLE_BASE 由
         create_minion golden 路径落位）+ 逐条 add_buff(pick._buffs)
         （"keeps enchantments"——附魔整体移植，check_for_triple 同构）
         + pending_hand_add（满手排队; 入手自动三连检查）
      5. 池记账: 复制生成不占池（阵亡者副本已回池; _plain_copy_to_hand
         "复制自有卡不消耗池副本" 先例——生成语义非池抽取）

    Test: test_batch_hero_passives2.py — 阵亡路径（health=0 +
    _process_eliminations）后 PendingChoice 出现 3 选项 / 选定入手
    副本含源附魔数值 / 金色源产出金色副本 / 空板阵亡落空 / 一次淘汰
    多英雄逐个触发

    Params: options=3（Discover 标准选项数——引擎 Discover Action 同参）
    """

    passive = True
    _DISCOVER_OPTIONS = 3

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        owner_hero = hero

        def on_eliminated(g, hero=None, **kw):
            if hero is None or hero is owner_hero or not \
                    owner_hero.is_alive:
                return
            board = [m for m in hero.board if isinstance(m, Minion)]
            if not board:
                return
            k = min(MrBigglesworthScript._DISCOVER_OPTIONS, len(board))
            options = g.rng.sample(board, k, label="bigglesworth_options") \
                if k < len(board) else list(board)

            def resolve(pick):
                copy = g.create_minion(pick.card_id, controller=owner_hero,
                                       golden=pick.is_golden)
                for b in pick._buffs:
                    copy.add_buff(b)
                g.pending_hand_add(owner_hero, copy)

            g.pending_choices.append(PendingChoice(
                owner_hero, options, "discover_minion",
                resolve_callback=resolve))

        game.events.register(Listener(
            event=HERO_ELIMINATED, owner=hero, callback=on_eliminated))


# ═══════════════════ TB_BaconShop_HP_085t Rakanishu ═══════════════════

class RakanishuScript:
    """
    Natural language: Your Tavern spells give an extra +{1}/+{1}. At the
    start of every 3 turns, improve this. <i>({0} turns left!)</i>

    依据: 数据文本 "Tavern Lighting"（num(0)=3 周期, num(1)=1 增量）。
    引擎 TAVERN_SPELL_EXTRA_ATK/HEALTH tag 即本效果的官方放大器出口
    （actions/racefx.tavern_spell_buff——spells 批次纪律: 法术 buff
    必经此出口，extra 自动叠加）。

    Formal spec:
      1. on_bind 即时面: 两个 extra tag 各 += num(1)（开局即 +1/+1
         ✓ 文本 "give an extra +1/+1" 现在时; start_game 接线先于
         首回合 turn_start，turn 1 不满足周期不重复加）
      2. 改善面: turn_start (turn=, hero=)——hero is 绑定英雄且
         turn % num(0) == 0（第 3/6/9… 回合开始）: 两 tag 各 +=
         num(1)（递进恒 +1/+1——文本无递增量增长语句）
      3. 作用域: 所有经 tavern_spell_buff 的法术增益（"Your Tavern
         spells" —— is_pool_spell 施放路径; 生成 token 法术（如
         Bananas/Blood Gem）非 Tavern spell 不受增幅 ✓）
      4. 覆盖全体已迁移法术（引擎出口统一，无逐卡豁免）

    Test: test_batch_hero_passives2.py — 绑定后 extra tag = 1/1 /
    第 3 回合开始 = 2/2、第 6 回合 = 3/3 / turn 1-2 不变 /
    tavern_spell_buff 出口实际产出 base+extra 数值 / 敌方回合不递进

    Params: {0}=3 {1}=1（script_data_num_1/2; 周期/增量）
    """

    passive = True

    @staticmethod
    def on_bind(hero: "Hero", game: "Game"):
        d = _power_def(game, "TB_BaconShop_HP_085t")
        period = d.num(0)
        gain = d.num(1)
        if period is None or gain is None:
            raise GameStateError("TB_BaconShop_HP_085t: missing params")

        def _improve():
            hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                     hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + gain)
            hero.set(GameTag.TAVERN_SPELL_EXTRA_HEALTH,
                     hero.get(GameTag.TAVERN_SPELL_EXTRA_HEALTH, 0) + gain)

        _improve()

        def on_turn_start(g, turn=0, hero=None, _owner=hero, **kw):
            if hero is not _owner or turn <= 0 or turn % period != 0:
                return
            _improve()

        game.events.register(Listener(
            event=TURN_START, owner=hero, callback=on_turn_start))


# ═══════════════════ Bananas / Big Banana（Mukla token 支撑脚本） ═══════════════════

class BananasScript:
    """
    Natural language: Give a minion +1/+1.

    依据: 36.2.2 数据 BG_EX1_014t（token 非池卡; 无模板参数 → 文本
    字面量）。此前无注册（打出无效果）——本批随 Mukla 一并注册闭环。

    Formal spec:
      1. needs_target=True（"Give a minion" 定向——play_spell 产生
         PendingChoice(kind="spell_target")，默认候选=友方棋盘存活
         随从; 无候选 → 落空但法术照常消耗）
      2. 选定: target.add_buff(entity.Buff(atk=1, health=1)) 永久 buff。
         非 Tavern spell token（不走 tavern_spell_buff extra 出口——
         Rakanishu 增幅语义仅限酒馆法术）

    Test: test_batch_hero_passives2.py — Mukla 授予 → 打出 → 定向
    选择 → 目标 +1/+1

    Params: atk=1 health=1（文本字面量——CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = ctx.get("target")
        if target is None:
            return None
        target.add_buff(entity.Buff(atk=1, health=1))
        return None


class BigBananaScript:
    """
    Natural language: Give a minion +2/+2.

    依据: 36.2.2 数据 BG_TB_006（token; 无模板参数 → 文本字面量）。

    Formal spec: 同 BananasScript，+2/+2。

    Test: test_batch_hero_passives2.py — 打出后目标 +2/+2

    Params: atk=2 health=2（文本字面量——CardDef 无模板参数）
    """

    needs_target = True

    @staticmethod
    def on_play(source, game, ctx):
        target = ctx.get("target")
        if target is None:
            return None
        target.add_buff(entity.Buff(atk=2, health=2))
        return None


def register() -> list[str]:
    """注册本批次被动英雄技能 + 支撑 token 脚本（注册键 = 卡 id）。

    OK 15 项（12 被动技能 + Sulfuras 替换目标 + 2 香蕉 token）;
    DEFERRED 台账见模块 docstring（Cariel/Millhouse/Genn/Finley/
    Nguyen/Loh/Guff/Illidan/Onyxia/Varden/Aranna/Sindragosa——
    查证不足或引擎缺口，缺口审计盯）。"""
    from hsrl2.scripts.registry import register as reg

    registered: list[str] = []
    for power_id, script in (
        ("TB_BaconShop_HP_087", RagnarosScript),
        ("TB_BaconShop_HP_087t", SulfurasScript),
        ("BG20_HERO_102p", OverlordSaurfangScript),
        ("BG28_HERO_800p", TaethelanScript),
        ("BG24_HERO_204p", EnhanceOScript),
        ("TB_BaconShop_HP_038", KingMuklaScript),
        ("BG20_HERO_280p5", KurtrusScript),
        ("BG26_HERO_104p", RockMasterVooneScript),
        ("TB_BaconShop_HP_088", ChenvaalaScript),
        ("TB_BaconShop_HP_107", GreyboughScript),
        ("TB_BaconShop_HP_042", DancinDerylScript),
        ("TB_BaconShop_HP_080", MrBigglesworthScript),
        ("TB_BaconShop_HP_085t", RakanishuScript),
        ("BG_EX1_014t", BananasScript),
        ("BG_TB_006", BigBananaScript),
    ):
        reg(power_id, script)
        registered.append(power_id)
    return registered
