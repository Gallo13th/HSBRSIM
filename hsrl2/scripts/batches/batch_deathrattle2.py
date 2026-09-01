"""批次 deathrattle2 — 18 张池随从（作业单 2026-08-21）。

实现状态总览（详见各类 docstring 与批次报告）:
  OK:       BG32_820 Firescale Hoarder / BG32_842 Glowing Cinder /
            BG32_880 Friendly Geist / BG33_821 Shipwrecked Rascal /
            BG34_633 Draconic Warden / BG34_690 Plaguerunner /
            BG35_143 Deepwater Chieftain / BG35_604 Sewer Lord
            （含 token 链 BG19_010 Sewer Rat → Half-Shell）/
            BG36_202 Tasty Lobster / BG36_730 Trapped Clapper（仅基础版）/
            BG36_731 Imp-lusionist / BG36_760 Captain Cookie /
            BG36_854 Rescue Bot / BGS_121 Gentle Djinni /
            BGS_018 Goldrinn, the Great Wolf（含金色注册）
  DEFERRED: BG34_856 Waveling（死亡起点持久监听器被死亡路径立即注销）/
            BG36_209 Ravaging Scorpid（Beetle 卡名恒定光环无引擎机制）/
            BGS_012 Kangor's Apprentice（无战斗死亡日志）/
            BG36_730_G Trapped Clapper 金色（Fodder 每刷新多重加挂不支持）

金色模型约定（与 scripts/minions.py 模块 docstring 一致）:
  - battlecry 钩子实现"每次触发的基础值"——金色打出时引擎触发 2 次，
    总额 = 2×基础值 = 金色文本总额
  - deathrattle 单次触发，金色注册类直接实现金色文本总额（数量字面量
    来自金色文本原文，无模板参数）

池法术 Get 路径裁定（本批次统一，见 _get_pool_spell docstring）:
  acquire 优先占池、池空时生成不占池（dark gift 批次 Mystic Essence
    先例）。与作业单"available=0 落空"字面读法存在偏差——理由:
  法术池每张仅 1 副本（RULES §3.6.1），金色 "Get 2 <specific spell>"
  文本总额是卡牌效果权威，硬性池闸会使金色总额恒降为 1（详见批次报告）。

deathrattle 实现模式注记（引擎 bug 规避，见批次报告）:
  check_deaths 作为最外层驱动（招募期死亡: recruit_phase_attack /
  EoT / 效果消灭）时**无重入保护**——亡语钩子返回 Action 会经
  run_actions→queue.resolve→每动作后 check_deaths 嵌套重入，此时
  濒死随从仍 DEAD&&PLAY（zone 移除晚于亡语钩子）→ 死亡被二次处理
  （亡语双发/graveyard 双插/亡语计数双计）。战斗路径由
  ActionQueue._resolving 保护不受影响。本批全部 deathrattle 因此
  采用**直接执行**模式（Action(...).do(game) / 实体方法，先例:
  game.py dark gifts、SnarkyShark on_sell），battlecry 仍按惯例
  返回 Action（play 路径无此问题）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hsrl2.actions import GainKeyword, GetRandomMinion, Summon
from hsrl2.actions.racefx import ApplyRaceAura
from hsrl2.entity import Buff as BuffEnchant
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero

_BEAST_RACES = (Race.BEAST, Race.ALL)      # ALL 视为所有种族 (RULES §6.18)


# ══════════════════ 池法术 Get 公共路径 ══════════════════


def _get_pool_spell(game: "Game", hero: "Hero", spell_id: str,
                    count: int) -> None:
    """Get a <specific 池法术> ×count: acquire 优先占池、池空生成不占池。

    - 池内有副本: spell_pool.acquire（占用期间不再出现在任何酒馆，
      RULES §3.6.1）→ create_spell → pending_hand_add（满手排队, P6）
    - 池空（被购走未施放）: 直接 create_spell 生成——先例: dark gift
      Mystic Essence（game.py "池空: 生成不占池（作业单约定）"）。
      理由: 法术池每张 1 副本，金色 "Get 2 copies" 文本总额必须可达成
    - count>1 时逐份走上述路径（两份可同时存在: 第一份占池、第二份
      池空生成）
    """
    for _ in range(count):
        if game.spell_pool.available(spell_id) > 0:
            if not game.spell_pool.acquire(spell_id):
                from hsrl2.game import GameStateError
                raise GameStateError(
                    f"pool spell acquire failed for {spell_id}")
        game.pending_hand_add(
            hero, game.create_spell(spell_id, controller=hero))


def _bounty_ids(game: "Game") -> list:
    """Bounty 卡集 = 5 张 T3 海盗酒馆法术（wiki/Bounty: "a cycle of five
    tavern tier 3 tavern spells... only in lobbies with pirates",
    Patch 32.2）。数据指纹: pool spell + name 以 "Bounty" 结尾 +
    subsets 含 'pirate'（Forest's Bounty T5 无海盗 subset，非 Bounty）。
    """
    return [d.id for d in game.db.pool_spells()
            if d.name.endswith("Bounty") and "pirate" in d.subsets]


def _chromadrake_ids(game: "Game") -> list:
    """Chromadrake 卡集 = 5 张多彩幼龙 token（Blue/Black/Green/Bronze/Red，
    BG34_634t..BG34_638t）。数据指纹: MINION + name 以 "Chromadrake"
    结尾 + 非金色定义。非池卡 → 获取不占池（SOP §3 token 语义）。
    """
    return [d.id for d in game.db._by_id.values()
            if d.is_minion and not d.is_golden_def
            and d.name.endswith("Chromadrake")]


# ══════════════════ BG32_820 Firescale Hoarder ══════════════════


class FirescaleHoarderScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get a Shiny Ring.

    Formal spec:
      1. battlecry（每次触发）与 deathrattle（单次触发）各获取 1 张
         Shiny Ring（BG28_168，池法术 T3——data is_pool_spell 权威）
         进手牌: _get_pool_spell 路径（acquire 占池优先 / 池空生成，
         见模块 docstring 裁定）+ pending_hand_add（满手排队, P6）
      2. 死亡触发时 source 已 GRAVEYARD，锚点 source.controller
      3. 金色 battlecry: 每次触发仍 1 张（引擎金色战吼 ×2 → 总额 2 =
         金色文本 "Get 2 Shiny Rings" 总额，minions.py 金色模型约定）

    Test: test_batch_deathrattle2.py — BC/DR 各得 1 张且占池 / 池空仍
    生成 / 金色打出总额 2 / 金色亡语 2 张

    Params: 无模板参数（"a Shiny Ring" = 1 张/次，文本原文）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG28_168", 1)   # token/法术 id 无数据链，字面量
        return None

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG28_168", 1)
        return None


class FirescaleHoarderGoldenScript(FirescaleHoarderScript):
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get 2 Shiny Rings.

    Formal spec:
      1. battlecry 继承基础版（每次触发 1 张）——引擎对金色战吼触发
         2 次 → 总额 2 张
      2. deathrattle 单次触发直接实现金色文本总额: 2 张

    Test: 金色打出 2 张 / 金色亡语 2 张（第一份占池、第二份池空生成）

    Params: 文本字面量 2（金色文本 "Get 2 Shiny Rings"，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG28_168", 2)
        return None


# ══════════════════ BG32_842 Glowing Cinder ══════════════════


class GlowingCinderScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Your Elementals give an extra
    +{0} Health this game.

    Formal spec:
      1. 死亡时（deathrattle 单次触发，锚点 source.controller）:
         hero 的 ELEMENTAL_EXTRA_HEALTH（tags.py 1055，"元素 give-Health
         效果加成"）现值 + num(0)（叠加式——多次触发多次累加）
      2. 该 tag 由未来元素系 give-Health 脚本消费（与
         TAVERN_SPELL_EXTRA_ATK / tavern_spell_buff 同构; 当前消费方
         尚未迁移，tag 写入即本卡 CORRECT 边界）
      3. 金色版文本同构仅数值差异（金色 num(0)=4）→ 同一脚本类复用，
         数值经金色 CardDef 自然体现

    Test: DR 后 hero tag == num(0)；金色 == 金色 num(0)；二次触发叠加

    Params: {0}=2（36.2.2 基线，金色 =4）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        hero.set(GameTag.ELEMENTAL_EXTRA_HEALTH,
                 hero.get(GameTag.ELEMENTAL_EXTRA_HEALTH, 0) + d.num(0))
        return None


# ══════════════════ BG32_880 Friendly Geist ══════════════════


class FriendlyGeistScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Your Tavern spells give an
    extra +{0} Attack this game.

    Formal spec:
      1. 死亡时: hero 的 TAVERN_SPELL_EXTRA_ATK（tags.py 1053）现值 +
         num(0)（叠加式）; 消费方 = actions.racefx.tavern_spell_buff
         （法术批次对随从施加增益的统一出口）——链路已就绪
      2. 金色版同构（金色 num(0)=2）→ 同一脚本类复用

    Test: DR 后 TAVERN_SPELL_EXTRA_ATK == num(0) / 金色 == 2 /
    不误写 ELEMENTAL_EXTRA_HEALTH / 二次触发叠加

    Params: {0}=1（36.2.2 基线，金色 =2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        hero.set(GameTag.TAVERN_SPELL_EXTRA_ATK,
                 hero.get(GameTag.TAVERN_SPELL_EXTRA_ATK, 0) + d.num(0))
        return None


# ══════════════════ BG33_821 Shipwrecked Rascal ══════════════════


class ShipwreckedRascalScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get a random
    <b>Bounty</b>.

    Formal spec:
      1. battlecry（每次触发）与 deathrattle（单次触发）各随机获取
         1 张 Bounty（5 张海盗 T3 池法术 BG33_811..815，卡集判定见
         _bounty_ids——wiki "a cycle of five tavern tier 3 tavern
         spells"）进手牌: game.rng.choice 选中 → _get_pool_spell 路径
         （acquire 占池优先 / 池空生成）
      2. 金色 battlecry: 每次触发 1 张（引擎 ×2 → 总额 2 =
         金色文本 "Get 2 random Bounties"）

    Test: BC/DR 到手卡 ∈ Bounty 卡集 / 金色亡语 2 张且互异（池唯一性）/
    不取 Forest's Bounty

    Params: 无模板参数（"a random Bounty" = 1 张/次）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = _bounty_ids(game)
        sid = game.rng.choice(cands, label="bounty_pick")
        _get_pool_spell(game, hero, sid, 1)
        return None

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cands = _bounty_ids(game)
        sid = game.rng.choice(cands, label="bounty_pick")
        _get_pool_spell(game, hero, sid, 1)
        return None


class ShipwreckedRascalGoldenScript(ShipwreckedRascalScript):
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get 2 random
    <b>Bounties</b>.

    Formal spec:
      1. battlecry 继承基础版（每次触发 1 张，引擎 ×2 → 总额 2）
      2. deathrattle 单次触发实现总额: 2 次独立随机获取（两次独立
         rng.choice; 池唯一性下第二张必然与第一张不同——第一张已
         acquire 占池，第二张从剩余可见候选中随机）

    Test: 金色亡语得 2 张不同 Bounty

    Params: 文本字面量 2（金色文本原文，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(2):
            cands = _bounty_ids(game)
            sid = game.rng.choice(cands, label="bounty_pick")
            _get_pool_spell(game, hero, sid, 1)
        return None


# ══════════════════ BG34_633 Draconic Warden ══════════════════


class DraconicWardenScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get a random
    <b>Chromadrake</b>.

    Formal spec:
      1. battlecry（每次触发）与 deathrattle（单次触发）各随机获取
         1 只 Chromadrake（Blue/Black/Green/Bronze/Red，BG34_634t..
         BG34_638t，卡集判定见 _chromadrake_ids）进手牌:
         game.rng.choice → create_minion + pending_hand_add
      2. Chromadrake 是非池 token（is_pool_minion=False）→ 获取**不占
         随从池**（SOP §3: token 不占池; 与 GetRandomMinion 的池语义
         区分——本卡文本为固定卡集随机，非池内随机）
      3. 金色 battlecry: 每次触发 1 只（引擎 ×2 → 总额 2 = 金色文本
         "Get 2 random Chromadrakes"）

    Test: BC/DR 到手卡 ∈ Chromadrake 卡集 / 池 available 不变 /
    金色亡语 2 只

    Params: 无模板参数（"a random Chromadrake" = 1 只/次）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cid = game.rng.choice(_chromadrake_ids(game),
                              label="chromadrake_pick")
        game.pending_hand_add(
            hero, game.create_minion(cid, controller=hero))
        return None

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        cid = game.rng.choice(_chromadrake_ids(game),
                              label="chromadrake_pick")
        game.pending_hand_add(
            hero, game.create_minion(cid, controller=hero))
        return None


class DraconicWardenGoldenScript(DraconicWardenScript):
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get 2 random
    <b>Chromadrakes</b>.

    Formal spec:
      1. battlecry 继承基础版（每次触发 1 只，引擎 ×2 → 总额 2）
      2. deathrattle 单次触发实现总额: 2 次独立随机获取（不占池）

    Test: 金色亡语得 2 只 Chromadrake

    Params: 文本字面量 2（金色文本原文，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(2):
            cid = game.rng.choice(_chromadrake_ids(game),
                                  label="chromadrake_pick")
            game.pending_hand_add(
                hero, game.create_minion(cid, controller=hero))
        return None


# ══════════════════ BG34_690 Plaguerunner ══════════════════


class PlaguerunnerScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Your Undead have +{0} Attack
    this game, wherever they are. <i>(+{1} if triggered outside combat!)</i>

    Formal spec:
      1. 死亡时（单次触发）: ApplyRaceAura(controller, UNDEAD, atk, 0).do
         (game)——叠加式永久种族光环，board/hand/未来获得的所有 Undead
         实时生效（Minion._aura_atk，"wherever they are"）
      2. atk 取值: 战斗中死亡（game.in_combat）→ num(0); 非战斗死亡
         （招募期消灭效果）→ num(1)（更高值——36.2.2 文本
         "+{1} if triggered outside combat!"，无 v1 的递增 scale）
      3. 金色版同构（金色 num=4/8）→ 同一脚本类复用
      4. 直接执行模式（模块 docstring: 死亡路径重入规避）

    Test: 战斗中死亡 Undead 光环 +num(0) / 非战斗死亡 +num(1) /
    非 Undead 不受影响 / 金色 4/8

    Params: {0}=2 {1}=4（36.2.2 基线，金色 4/8）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        atk = d.num(0) if game.in_combat else d.num(1)
        ApplyRaceAura(hero, Race.UNDEAD, atk, 0,
                      source_id=source.card_id).do(game)
        return None


# ══════════════════ BG35_143 Deepwater Chieftain ══════════════════


class DeepwaterChieftainScript:
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get a Deepwater
    Clan.

    Formal spec:
      1. battlecry（每次触发）与 deathrattle（单次触发）各获取 1 张
         Deepwater Clan（BG35_149，**池法术** T4——data is_pool_spell
         权威，"Give a minion +2/+2. Give your Murlocs +2/+2."）
         进手牌: _get_pool_spell 路径（acquire 占池优先 / 池空生成）
      2. 金色 battlecry: 每次触发 1 张（引擎 ×2 → 总额 2 = 金色文本
         "Get 2 Deepwater Clans"）

    Test: BC/DR 得 1 张 BG35_149 且占池 / 金色亡语 2 张

    Params: 无模板参数（"a Deepwater Clan" = 1 张/次）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG35_149", 1)
        return None

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG35_149", 1)
        return None


class DeepwaterChieftainGoldenScript(DeepwaterChieftainScript):
    """
    Natural language: <b>Battlecry and Deathrattle:</b> Get 2 Deepwater
    Clans.

    Formal spec:
      1. battlecry 继承基础版（每次触发 1 张，引擎 ×2 → 总额 2）
      2. deathrattle 单次触发实现总额: 2 张

    Test: 金色亡语得 2 张 BG35_149

    Params: 文本字面量 2（金色文本原文，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG35_149", 2)
        return None


# ══════════════════ BG35_604 Sewer Lord（token 链: BG19_010 Sewer Rat → BG19_010t Half-Shell） ══════════════════


class SewerLordScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Summon two Sewer Rats that
    summon _2/3 Turtles with <b>Taunt</b>.

    Formal spec:
      1. 死亡时: 召唤 2 只 Sewer Rat（BG19_010 token，非池卡不占池;
         最右位置，game.summon 默认）——Rat 自身亡语见 SewerRatScript
      2. 金色版（BG35_604_G "Summon two Golden Sewer Rats that summon
         4/6 Turtles"）: 召唤 2 只金色 Rat（BG19_010_G，独立金色卡
         定义，经 db.golden_version 数据链解析）
      3. token id "BG19_010" 无数据链字段（Rat 无 evolution/companion
         链），字面量注明; 满场由 game.summon 处理（MINION_OVERFLOW）
      4. 直接执行模式（模块 docstring: 死亡路径重入规避）

    Test: DR 后棋盘 +2 只 3/2 Sewer Rat / 金色版出 2 只 6/4 金色 Rat

    Params: 文本字面量 2（"two"，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(2):
            Summon(hero, "BG19_010").do(game)
        return None


class SewerLordGoldenScript(SewerLordScript):
    """
    Natural language: [x]<b>Deathrattle:</b> Summon two Golden Sewer Rats
    that summon 4/6 Turtles with <b>Taunt</b>.

    Formal spec:
      1. 同基础版但召唤金色 Sewer Rat（db.golden_version(BG19_010)
         → BG19_010_G，数据链解析非字面量）; 数量仍 2
      2. 金色 Rat 的亡语由其独立注册的 SewerRatScript 按
         CardDef.is_golden_def 分流召唤金色 Half-Shell
      3. 直接执行模式（模块 docstring: 死亡路径重入规避）

    Test: 金色 DR 后棋盘 +2 只 6/4 金色 Rat（card_id == BG19_010_G）

    Params: 文本字面量 2（"two"，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        golden_rat = game.db.golden_version(game.db.get("BG19_010"))
        rat_id = golden_rat.id if golden_rat is not None else "BG19_010"
        for _ in range(2):
            Summon(hero, rat_id).do(game)
        return None


class SewerRatScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Summon a 2/3 Turtle with
    <b>Taunt</b>.（金色: Summon a 4/6 Turtle with <b>Taunt</b>.)

    Formal spec:
      1. 死亡时: 召唤 1 只 Half-Shell token——普通 Rat（BG19_010）→
         BG19_010t（2/3）; 金色 Rat（BG19_010_G，独立卡定义）→
         BG19_010_Gt（4/6）。属性取自 Half-Shell 独立卡定义（金色=
         独立卡定义约定），无模板参数
      2. Taunt: Half-Shell CardDef.keywords **不含** taunt（生成器
         文本兜底未覆盖 "<b>Taunt</b>" 纯关键词文本）——引擎缺口自举:
         召唤后 GainKeyword(TAUNT).do(game)（fire keyword_gained;
         先例: Spellcraft tag 自举，批次 Spellcraft 注记）
      3. 同一脚本类注册普通/金色两个 Rat id（行为同构，分流经
         CardDef.is_golden_def）; 直接执行模式（模块 docstring:
         死亡路径重入规避）

    Test: Rat 死亡召唤 2/3 带 Taunt Half-Shell / 金色 Rat 出 4/6
    金色 Half-Shell

    Params: 无模板参数（Half-Shell 属性以卡定义为权威）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        turtle_id = "BG19_010_Gt" if d.is_golden_def else "BG19_010t"
        turtle = game.create_minion(turtle_id, controller=hero)
        game.summon(hero, turtle)
        GainKeyword(turtle, GameTag.TAUNT).do(game)
        return None


# ══════════════════ BG36_202 Tasty Lobster ══════════════════


class TastyLobsterScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Give a random friendly Beast
    +{0}/+{1}. Improve your future Tasty Lobsters.

    Formal spec:
      1. 死亡时（单次触发）: 随机 1 只友方存活 Beast（含 ALL 种族，
      Amalgam 规则; source 已死被排除）获得 +num(0)+I 攻击 /
         +num(1)+I 生命，I = 已累积的 Improve 加成（见 3）
      2. Improve（官方 Improve 关键词，先例文本: 移除法术 Back to
         Back "Your future Back to Backs give an extra +4/+4"）:
         每次亡语触发后，加成 I += (触发副本 num(0), num(1))——基础
         +1/+1、金色 +2/+2（金色=独立卡定义数值自然体现）;
         hero.tasty_lobster_improvement 持久存续（race_auras 同款
         动态属性先例，英雄级状态不随战斗快照回滚 → "this game"）
      3. 未来 Lobster（含金色、含 Hoarding Hyena 等召唤的副本）亡语
         读数 = 自身 num + I 全额（"give an extra +X/+X"——extra 对
         任何未来副本等额追加，不随副本品质翻倍）
      4. 裁定注: 无友方 Beast 时加成部分照常结算（Improve 是亡语文本
         的独立分句，仅随机目标部分落空）
      5. 直接执行模式（模块 docstring: 死亡路径重入规避）

    Test: 首只 Lobster 亡语 +num(0)/num(1) / 第二只亡语 +num+I /
    非 Beast 不受 buff / 金色亡语 +金色num+I 且 I += 金色num

    Params: {0}=1 {1}=1（36.2.2 基线，金色 2/2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        imp_a, imp_h = getattr(hero, "tasty_lobster_improvement", (0, 0))
        beasts = [m for m in hero.board
                  if not m.dead and m.race in _BEAST_RACES]
        if beasts:
            target = game.rng.choice(beasts, label="tasty_lobster_target")
            target.add_buff(BuffEnchant(atk=d.num(0) + imp_a,
                                        health=d.num(1) + imp_h))
        hero.tasty_lobster_improvement = (imp_a + d.num(0),
                                          imp_h + d.num(1))
        return None


# ══════════════════ BG36_730 Trapped Clapper ══════════════════


class TrappedClapperScript:
    """
    Natural language: <b>Deathrattle:</b> Add a <b>Fodder</b> to your
    next {0} <b>Refreshes</b>.

    Formal spec:
      1. 死亡时: game._fodder_refresh_pending[hero] += num(0)——与
         Demonology Dark Gift 完全同款协议（game.py _gift_demonology;
         refresh_tavern 每次刷新消费 1 点 pending 并向酒馆附加 1 枚
         Demon Fodder token BG35_150t，非池卡不占池）
      2. 每次刷新 1 枚 Fodder、共 num(0)=3 次刷新（官方 "Add a Fodder
         to your next 3 Refreshes"）
      3. 金色版 "Add two Fodders to your next {0} Refreshes"（每次
         刷新 2 枚）**未注册**——引擎 pending 协议为 Dict[Hero, int]
         （刷新次数计数，每次固定加挂 1 枚），无每刷新多重加挂支持，
         见 TrappedClapperGoldenScript（DEFERRED）

    Test: DR 后 pending == num(0) / 两次刷新各出 1 枚 Fodder 且
    pending 递减 / 未触发 DR 时刷新无 Fodder

    Params: {0}=3（36.2.2 基线）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        # 协议 v2: (剩余刷新次数, 每次附加枚数)——基础版每次 1 枚
        prev = game._fodder_refresh_pending.get(hero, (0, 0))
        game._fodder_refresh_pending[hero] = (
            prev[0] + d.num(0), max(prev[1], 1))
        return None


# ══════════════════ BG36_731 Imp-lusionist ══════════════════


class ImpLusionistScript:
    """
    Natural language: <b>Deathrattle:</b> Get a Methodical Madness.
    （金色: <b>Deathrattle:</b> Get {0} copies of Methodical Madness.）

    Formal spec:
      1. 死亡时（单次触发）: 获取 num(0) 张 Methodical Madness
         （BG36_880 池法术 T4，"Choose a friendly Demon. It consumes
         2 random Tavern minions..."）进手牌——数量直接来自模板参数
         num(0)（基础=1 / 金色=2，金色文本 "Get {0} copies" 参数化）
      2. _get_pool_spell 路径: 第一张 acquire 占池、后续张池空生成
         （法术池每张 1 副本，金色 2 份总额必须可达成——模块 docstring
         裁定）
      3. 基础/金色同一脚本类复用（num(0) 经各自 CardDef 自然体现）

    Test: DR 得 num(0) 张 BG36_880 / 金色得 2 张 / 占池 1 份

    Params: {0}=1（基础; 金色 CardDef num(0)=2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        _get_pool_spell(game, hero, "BG36_880", d.num(0))
        return None


# ══════════════════ BG36_760 Captain Cookie ══════════════════


class CaptainCookieScript:
    """
    Natural language: <b>Deathrattle:</b> Get a Chef's Choice.

    Formal spec:
      1. 死亡时（单次触发）: 获取 1 张 Chef's Choice（BG28_518 池法术
         T2，"Choose a minion. Get a different minion of the same
         type."）进手牌: _get_pool_spell 路径
      2. 金色 battlecry n/a; 金色死亡 "Get 2 Chef's Choices" → 金色
         注册类直接实现总额 2

    Test: DR 得 1 张 BG28_518 且占池 / 金色 DR 得 2 张

    Params: 无模板参数（"a Chef's Choice" = 1 张）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG28_518", 1)
        return None


class CaptainCookieGoldenScript(CaptainCookieScript):
    """
    Natural language: <b>Deathrattle:</b> Get 2 Chef's Choices.

    Formal spec:
      1. 同基础版，deathrattle 总额 2 张（第一张占池、第二张池空生成）

    Test: 金色 DR 得 2 张 BG28_518

    Params: 文本字面量 2（金色文本原文，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG28_518", 2)
        return None


# ══════════════════ BG36_854 Rescue Bot ══════════════════


class RescueBotScript:
    """
    Natural language: [x]<b>Taunt</b> <b>Deathrattle:</b> Get a Repair
    Job.

    Formal spec:
      1. 死亡时（单次触发）: 获取 1 张 Repair Job（BG36_624 池法术 T3，
         "Give a minion +{0}/+{1}." num=4/8）进手牌: _get_pool_spell
      2. Taunt 由 create_minion 关键词映射（CardDef.keywords 含
         taunt，_KEYWORD_TAG_MAP 有项）——脚本无需处理
      3. 金色死亡 "Get 2 Repair Jobs" → 金色注册类总额 2

    Test: DR 得 1 张 BG36_624 且占池 / 金色 DR 得 2 张 / Taunt 在场

    Params: 无模板参数（"a Repair Job" = 1 张）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG36_624", 1)
        return None


class RescueBotGoldenScript(RescueBotScript):
    """
    Natural language: [x]<b>Taunt</b> <b>Deathrattle:</b> Get 2 Repair
    Jobs.

    Formal spec:
      1. 同基础版，deathrattle 总额 2 张（第一张占池、第二张池空生成）

    Test: 金色 DR 得 2 张 BG36_624

    Params: 文本字面量 2（金色文本原文，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        _get_pool_spell(game, hero, "BG36_624", 2)
        return None


# ══════════════════ BGS_121 Gentle Djinni ══════════════════


class GentleDjinniScript:
    """
    Natural language: [x]<b>Taunt</b> <b>Battlecry and Deathrattle:</b>
    Get a random Elemental.

    Formal spec:
      1. battlecry（每次触发）与 deathrattle（单次触发）各随机获取
         1 只 Elemental 进手牌: GetRandomMinion(hero, race=ELEMENTAL)
         ——池感知（候选按剩余量过滤、无候选落空——官方池语义;
         acquire 占池 + pending_hand_add 满手排队均由该 Action 保证）
      2. tier 不限（"a random Elemental" 无 tier 限定; ALL 种族
         Amalgam 经 _pool_candidates 的 ALL 匹配规则一并入候选）
      3. 金色 battlecry: 每次触发 1 只（引擎 ×2 → 总额 2 = 金色文本
         "Get 2 random Elementals"）; deathrattle 单次触发实现总额 2
         （直接执行模式，模块 docstring: 死亡路径重入规避）

    Test: BC/DR 得 1 只 Elemental（池 available 减少）/ 金色亡语
    2 只 / Taunt 由 def 关键词映射

    Params: 无模板参数（"a random Elemental" = 1 只/次）
    """

    @staticmethod
    def battlecry(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        return GetRandomMinion(hero, race=Race.ELEMENTAL)

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        GetRandomMinion(hero, race=Race.ELEMENTAL).do(game)
        return None


class GentleDjinniGoldenScript(GentleDjinniScript):
    """
    Natural language: [x]<b>Taunt</b> <b>Battlecry and Deathrattle:</b>
    Get 2 random Elementals.

    Formal spec:
      1. battlecry 继承基础版（每次触发 1 只，引擎 ×2 → 总额 2）
      2. deathrattle 单次触发实现总额: 2 次独立 GetRandomMinion.do
         （两次独立随机，可同卡不同副本; 直接执行模式）

    Test: 金色亡语得 2 只 Elemental

    Params: 文本字面量 2（金色文本原文，无模板参数）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        for _ in range(2):
            GetRandomMinion(hero, race=Race.ELEMENTAL).do(game)
        return None


# ══════════════════ BGS_018 Goldrinn, the Great Wolf ══════════════════


class GoldrinnScript:
    """
    Natural language: <b>Deathrattle:</b> Your Beasts have +{0}/+{1}
    until next turn.

    Formal spec:
      1. 死亡时（单次触发）: 对全部友方存活 Beast（含 ALL 种族; source
         自身已死被排除——亡语触发时仍在 board 但 DEAD 已置位）各
         add_buff(+num(0)/+num(1))，非 temporary 附魔
      2. "until next turn" 建模依据: Goldrinn 亡语在战斗中触发，战斗
         buff 由 run_combat 战后快照恢复清除（RULES §3.5 战斗 buff
         不延续; 36.2 官方改文 "For the rest of this combat" →
         "Until next turn" 同义）——plain buff + 快照恢复即官方语义，
         无需 temporary 标记/TURN_START 清除
      3. 金色版同构（金色 num=16/16）→ 同一脚本类复用
      4. 直接执行模式（模块 docstring: 死亡路径重入规避）

    Test: DR 后全部 Beast +num(0)/num(1)、非 Beast 不变 / 金色 +16/+16

    Params: {0}=8 {1}=8（36.2.2 基线，金色 16/16）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        hero = source.controller
        if hero is None:
            return None
        d = game.db.get(source.card_id)
        for m in hero.board:
            if not m.dead and m.race in _BEAST_RACES:
                m.add_buff(BuffEnchant(atk=d.num(0), health=d.num(1)))
        return None


# ══════════════════ 以下为 DEFERRED（不注册 REGISTRY） ══════════════════


class WavelingScript:
    """
    Natural language: [x]<b>Deathrattle:</b> After the Tavern is
    <b>Refreshed</b> this game, give a random minion in it +{0}/+{1}.

    Status: DEFERRED — requires "死亡起点持久监听器"

    Dependency: 亡语钩子内注册的持久 Listener（owner=source，事件
    tavern_refresh，"this game" = 之后每次刷新都触发——非 once）在
    _process_single_death 的非复生路径中于亡语结算**之后**立即被
    events.unregister_owner(m)（game.py 死亡路径）注销; 战斗路径下
    战后监听器表恢复使用**战斗开始前快照**（run_combat
    events_snapshot），快照不含死亡中新注册的监听器 → 监听器在任何
    路径下都会丢失。需要引擎支持"由亡语开始、超越宿主死亡存续的
    持久监听"（如 owner=controller 的受控生命周期或 death-origin
    监听器豁免注销）。禁止用 owner=hero 绕过（作业单明令）。

    Params: {0}=4 {1}=4（36.2.2 基线，金色 "twice" ×2）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        return None


class RavagingScorpidScript:
    """
    Natural language: [x]After a friendly minion attacks, your Beetles
    have +{2}/+{3} this game. <b>Deathrattle:</b> Summon a {0}/{1} Beetle.

    Status: DEFERRED — requires "卡牌身份（Beetle）恒定光环"

    Dependency: "your Beetles have +5/+5 this game" 是**卡名范围**的
    恒定光环（Beetle token BG28_603t 及其金色，同族: Silky
    Shimmermoth / Boon of Beetles / Beetle Band）。引擎唯一恒定光环
    机制 hero.race_auras 以 Race 为键（entity._aura_atk），Beetle 的
    Race 是 BEAST——按种族挂 aura 会错误惠及全部野兽（作业单提示的
    ApplyRaceAura(BEAST) 与卡牌文本冲突，不采用）; atk/health 动态
    脚本钩子未接入 Minion.atk/max_health。需主线将 race_auras 推广
    为 card_id 键光环或接线动态属性钩子。亡语部分（Summon 2/2
    Beetle）可独立实现，但二态纪律下整卡 DEFERRED。

    Params: {0}=2 {1}=2 {2}=5 {3}=5（36.2.2 基线，金色 2/2/10/10）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        return None


class KangorsApprenticeScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Summon plain copies of your
    first 2 Mechs that died this combat.

    Status: DEFERRED — requires "战斗死亡日志（按死亡顺序）"

    Dependency: 引擎仅记录 combat_summon_log（战斗召唤日志，
    game.run_combat 重置），无 combat_death_log——_process_single_death
    不记录死亡顺序。Kangor 需要"本场战斗中你最先进死亡的 2 只 Mech"
    的有序死亡记录（金色 4 只）。禁止随机近似（作业单明令）。
    SummonPlainCopy Action 已就绪，缺的只是数据源。

    Params: 文本字面量 2（金色文本 "first 4"）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        return None


class TrappedClapperGoldenScript:
    """
    Natural language: [x]<b>Deathrattle:</b> Add two <b>Fodders</b> to
    your next {0} <b>Refreshes</b>.

    Status: DEFERRED — requires "Fodder 每刷新多重加挂"

    Dependency: 金色文本 = 此后 {0}=3 次刷新**每次**附加 2 枚 Fodder。
    引擎协议 game._fodder_refresh_pending: Dict[Hero, int] 只计数
    刷新次数，refresh_tavern 每次刷新固定加挂 1 枚（C.FODDER_CARD_ID）
    ——无每刷新枚数维度。基础版 BG36_730 已注册（TrappedClapperScript，
    每次 1 枚 ×3 次）; pending += 6 不是等价实现（1×6 次刷新 ≠ 2×3 次）。
    需主线扩展协议（如 Dict[Hero, Tuple[int, int]] 次数×枚数）。

    Params: {0}=3（金色 CardDef num(0)=3，"two" 为每刷新枚数文本字面量）
    """

    @staticmethod
    def deathrattle(source, game, ctx):
        return None


# ══════════════════ 注册 ══════════════════

# （含金色 id——金色=独立卡定义; token 链 Sewer Rat 一并注册）
_REGISTRATIONS = [
    ("BG32_820", FirescaleHoarderScript),
    ("BG32_820_G", FirescaleHoarderGoldenScript),
    ("BG32_842", GlowingCinderScript),
    ("BG32_842_G", GlowingCinderScript),          # 金色 num(0)=4 自然体现
    ("BG32_880", FriendlyGeistScript),
    ("BG32_880_G", FriendlyGeistScript),          # 金色 num(0)=2 自然体现
    ("BG33_821", ShipwreckedRascalScript),
    ("BG33_821_G", ShipwreckedRascalGoldenScript),
    ("BG34_633", DraconicWardenScript),
    ("BG34_633_G", DraconicWardenGoldenScript),
    ("BG34_690", PlaguerunnerScript),
    ("BG34_690_G", PlaguerunnerScript),           # 金色 num=4/8 自然体现
    ("BG35_143", DeepwaterChieftainScript),
    ("BG35_143_G", DeepwaterChieftainGoldenScript),
    ("BG35_604", SewerLordScript),
    ("BG35_604_G", SewerLordGoldenScript),
    ("BG19_010", SewerRatScript),                 # token 链（非池卡）
    ("BG19_010_G", SewerRatScript),               # 金色 Rat → 金色 Half-Shell
    ("BG36_202", TastyLobsterScript),
    ("BG36_202_G", TastyLobsterScript),           # 金色 num=2/2 自然体现
    ("BG36_730", TrappedClapperScript),
    # BG36_730_G: DEFERRED（TrappedClapperGoldenScript，Fodder 多重加挂）
    ("BG36_731", ImpLusionistScript),
    ("BG36_731_G", ImpLusionistScript),           # 金色 num(0)=2 自然体现
    ("BG36_760", CaptainCookieScript),
    ("BG36_760_G", CaptainCookieGoldenScript),
    ("BG36_854", RescueBotScript),
    ("BG36_854_G", RescueBotGoldenScript),
    ("BGS_121", GentleDjinniScript),
    ("TB_BaconUps_165", GentleDjinniGoldenScript),   # 金色独立卡 id
    ("BGS_018", GoldrinnScript),
    ("TB_BaconUps_085", GoldrinnScript),          # 金色 num=16/16 自然体现
    # DEFERRED 未注册: BG34_856(+_G) Waveling / BG36_209(+_G) Ravaging
    # Scorpid / BGS_012(+TB_BaconUps_087) Kangor's Apprentice /
    # BG36_730_G Trapped Clapper 金色
]


def register() -> list:
    from hsrl2.scripts.registry import register as _register
    ids = []
    for card_id, cls in _REGISTRATIONS:
        _register(card_id, cls)
        ids.append(card_id)
    return ids
