"""Blood Gem（鲜血宝石）系统 — RULES §6.15。

Blood Gem = 定向法术（**非** Spellcraft: 不设 SPELLCRAFT tag、不回合末丢弃），
基础数值唯一来源: BG20_GEM CardDef.num(0)/num(1)（data 36.2.2 已核对 1/1）。
英雄增强走 tags BLOOD_GEM_BONUS_ATK/HEALTH（1051/1052，tags.py 已入册）。
变体（DS/Reborn/Taunt）仅当**从手牌打出变体宝石**且目标是 Quilboar
（含 Race.ALL）时由 on_play 脚本授予关键词。

含 4 个法术脚本类（BG20_GEM ×4 注册于 scripts/registry.py）。
注: audit_script_params.py 仅扫描 scripts/，本文件脚本类照常在
docstring 声明 "Params:"（主线可扩展审计范围）。
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from hsrl2.actions.stats import Buff, GainKeyword
from hsrl2.game import GameStateError
from hsrl2.queue import Action
from hsrl2.tags import GameTag, Race

if TYPE_CHECKING:
    from hsrl2.game import Game
    from hsrl2.hero import Hero
    from hsrl2.minion import Minion

# 变体名 → 卡 id（card id 是身份标识非数值; data 核对: 4 张均
# num(0)=1 num(1)=1，变体文本 "...If it's a Quilboar, also give it <b>X</b>"）
BLOOD_GEM_VARIANTS = {
    None: "BG20_GEM",
    "divine_shield": "BG20_GEM_DivineShield",
    "reborn": "BG20_GEM_Reborn",
    "taunt": "BG20_GEM_Taunt",
}

# 变体卡 id → 授予关键词 tag（来源: 各变体卡文本，非模板参数）
VARIANT_KEYWORD_TAG = {
    "BG20_GEM_DivineShield": GameTag.DIVINE_SHIELD,
    "BG20_GEM_Reborn": GameTag.REBORN,
    "BG20_GEM_Taunt": GameTag.TAUNT,
}


def _gem_values(game: "Game", card_id: str,
                hero: "Hero") -> tuple[int, int]:
    """单颗宝石对 hero 施加的 (atk, health) = CardDef.num + hero 增强 tags。

    num 缺失（模板参数漂移）抛 GameStateError——fail-loud，禁止默认值近似。
    """
    d = game.db.get(card_id)
    if d is None:
        raise GameStateError(f"unknown Blood Gem card_id {card_id}")
    base_atk = d.num(0)
    base_health = d.num(1)
    if base_atk is None or base_health is None:
        raise GameStateError(
            f"{card_id} missing Blood Gem template params "
            f"(num0={base_atk}, num1={base_health})")
    return (base_atk + hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0),
            base_health + hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0))


class GetBloodGems(Action):
    """获得 count 颗血宝石（进手牌; 满手排队等待 RULES §3.3）。

    - 血宝石不是 Spellcraft——不设 SPELLCRAFT tag（不回合末丢弃）
    - variant: None=vanilla / "divine_shield" / "reborn" / "taunt"
    - 血宝石是非池卡: 不占 spell_pool（token 语义）
    - 引擎缺口绕过: create_spell 不绑定 REGISTRY 脚本（create_minion
      在 game.py:1240 绑定），此处手动绑定; 主线在 create_spell 统一
      修复后本绑定冗余但无害
    """

    def __init__(self, hero: "Hero", count: int,
                 variant: Optional[str] = None) -> None:
        if variant not in BLOOD_GEM_VARIANTS:
            raise GameStateError(f"unknown Blood Gem variant {variant!r}")
        self.hero = hero
        self.count = count
        self.variant = variant

    def do(self, game: "Game") -> None:
        from hsrl2.scripts import REGISTRY  # 延迟导入避免循环依赖
        card_id = BLOOD_GEM_VARIANTS[self.variant]
        script = REGISTRY.get(card_id)
        if script is None:
            raise GameStateError(
                f"Blood Gem {card_id} has no registered script")
        for _ in range(self.count):
            s = game.create_spell(card_id, controller=self.hero)
            s.scripts = script
            game.pending_hand_add(self.hero, s)


class PlayBloodGems(Action):
    """立即对目标施放 count 颗 **vanilla** 血宝石。

    官方 "plays N Blood Gems"（Rally/亡语等触发）语义 = 不经手牌、
    不耗金币，直接施加 N 次 buff:
      每颗 Buff(target, atk=BG20_GEM.num(0)+bonus_atk,
                      health=BG20_GEM.num(1)+bonus_health)
    - 基础值唯一来源: BG20_GEM CardDef.num(0/1)
    - bonus 读 target.controller 的 BLOOD_GEM_BONUS_ATK/HEALTH tags
    - vanilla 语义: 变体关键词（DS/Taunt/Reborn）仅在从手牌打出**变体**
      宝石时由其 on_play 脚本给予，本 Action 不给
    - source 仅作来源追溯（vanilla 数值不依赖）; 不广播
      card_played/tavern_spell_cast（该事件语义为手牌打出——
      "played Blood Gem" 专用事件为引擎缺口，见作业报告）
    """

    def __init__(self, target: "Minion", count: int,
                 source=None) -> None:
        self.target = target
        self.count = count
        self.source = source

    def do(self, game: "Game") -> None:
        hero = self.target.controller
        if hero is None:
            raise GameStateError(
                f"PlayBloodGems target {self.target.card_id} "
                f"has no controller")
        buffs = []
        for _ in range(self.count):
            atk, health = _gem_values(game, "BG20_GEM", hero)
            buffs.append(Buff(self.target, atk=atk, health=health, gem=True))
        # per-minion 宝石计数 + 广播（Jailbird "stats equal to this
        # minion's Blood Gems" / Gem Confiscation "steals all Blood Gems"
        # 的数据源; blood_gem_played 事件供 "whenever you play a
        # Blood Gem" 类触发器）
        from hsrl2.tags import GameTag
        n = self.target.get(GameTag.GEMS_PLAYED_ON, 0) + self.count
        self.target.set(GameTag.GEMS_PLAYED_ON, n)
        for _ in range(self.count):
            game.events.fire(game, "blood_gem_played",
                             target=self.target, player=hero)
        game.run_actions(buffs)


class ImproveBloodGems(Action):
    """hero 的血宝石额外加成递增（BLOOD_GEM_BONUS_ATK/HEALTH tags）。

    "Your Blood Gems give an extra +X/+Y"（奖励/饰品类效果）的通用实现，
    对手牌打出与 PlayBloodGems 施放的宝石同时生效（bonus 在
    _gem_values 读取点统一计算）。数值由调用方从对应 CardDef.num() 传入。
    """

    def __init__(self, hero: "Hero", atk: int = 0, health: int = 0) -> None:
        self.hero = hero
        self.atk = atk
        self.health = health

    def do(self, game: "Game") -> None:
        self.hero.set(GameTag.BLOOD_GEM_BONUS_ATK,
                      self.hero.get(GameTag.BLOOD_GEM_BONUS_ATK, 0)
                      + self.atk)
        self.hero.set(GameTag.BLOOD_GEM_BONUS_HEALTH,
                      self.hero.get(GameTag.BLOOD_GEM_BONUS_HEALTH, 0)
                      + self.health)


# ══════════════════ 血宝石法术脚本（REGISTRY 注册） ══════════════════


class BloodGemScript:
    """
    Natural language: Give a minion +{0}/+{1}.

    Formal spec:
      1. on_play（从手牌打出，play_spell 已移出手牌后触发）: 目标
         minion 获得 +(num(0)+持有者 BLOOD_GEM_BONUS_ATK)/
         +(num(1)+持有者 BLOOD_GEM_BONUS_HEALTH)，持有者=source.controller
      2. 无 target 抛 GameStateError——血宝石是定向法术，引擎 play_spell
         尚无 needs_target→PendingChoice 分流（引擎缺口，见作业报告），
         fail-loud 不静默; 非 Minion 目标同样抛错
      3. 仅创建 entity.Buff 附魔，无其他实体

    Test: play_spell(hero, gem, target=m) → m 攻/血各 +num(0)/num(1)

    Params: {0}=1 {1}=1
    """

    # 变体子类覆写: Quilboar 目标额外获得的关键词（None = vanilla）
    KEYWORD_TAG: Optional[GameTag] = None

    # 定向协议（引擎 play_spell needs_target 分流——压测 fail-loud 暴露
    # 后接入; 候选=友方存活随从）
    needs_target = True

    @staticmethod
    def target_candidates(source, game):
        hero = getattr(source, "controller", None)
        return [m for m in hero.board if not m.dead] if hero else []

    @classmethod
    def on_play(cls, source, game, ctx):
        from hsrl2.minion import Minion
        target = (ctx or {}).get("target")
        if target is None:
            # needs_target 协议下引擎保证非 None; 直调（效果直施路径）
            # 无候选时诚实落空
            return None
        if not isinstance(target, Minion):
            raise GameStateError(
                f"{source.card_id} target must be a Minion, "
                f"got {type(target).__name__}")
        hero = source.controller
        atk, health = _gem_values(game, source.card_id, hero)
        # gem 标记（Gem Confiscation "steals all Blood Gems" 的移转数据源）
        actions = [Buff(target, atk=atk, health=health, gem=True)]
        if (cls.KEYWORD_TAG is not None
                and target.race in (Race.QUILBOAR, Race.ALL)):
            actions.append(GainKeyword(target, cls.KEYWORD_TAG))
        # 记账与广播——与 PlayBloodGems 完全对齐（per-minion 计数 +
        # blood_gem_played 事件; Jailbird/窃取类脚本的两路径统一数据源）
        from hsrl2.tags import GameTag as _GT
        n = target.get(_GT.GEMS_PLAYED_ON, 0) + 1
        target.set(_GT.GEMS_PLAYED_ON, n)
        game.events.fire(game, "blood_gem_played",
                         target=target, player=hero)
        return actions


class BloodGemDivineShieldScript(BloodGemScript):
    """
    Natural language: Give a minion +{0}/+{1}. If it's a Quilboar, also
    give it <b>Divine Shield</b>.

    Formal spec: vanilla buff（同 BloodGemScript）+ 目标 race 为
    QUILBOAR 或 ALL 时 GainKeyword(DIVINE_SHIELD)。

    Test: Quilboar 目标获得圣盾; 非 Quilboar 只得 buff 无圣盾

    Params: {0}=1 {1}=1
    """

    KEYWORD_TAG = GameTag.DIVINE_SHIELD


class BloodGemRebornScript(BloodGemScript):
    """
    Natural language: Give a minion +{0}/+{1}. If it's a Quilboar, also
    give it <b>Reborn</b>.

    Formal spec: vanilla buff + QUILBOAR/ALL 目标 GainKeyword(REBORN)。

    Test: Quilboar 目标获得 Reborn; 非 Quilboar 不获得

    Params: {0}=1 {1}=1
    """

    KEYWORD_TAG = GameTag.REBORN


class BloodGemTauntScript(BloodGemScript):
    """
    Natural language: Give a minion +{0}/+{1}. If it's a Quilboar, also
    give it <b>Taunt</b>.

    Formal spec: vanilla buff + QUILBOAR/ALL 目标 GainKeyword(TAUNT)。

    Test: Quilboar 目标获得 Taunt; 非 Quilboar 不获得

    Params: {0}=1 {1}=1
    """

    KEYWORD_TAG = GameTag.TAUNT


class StealBloodGems(Action):
    """窃取目标的全部血宝石（移转到 recipient）。

    官方: Gem Confiscation "It steals all Blood Gems from its neighbors."
    语义: 目标身上 gem=True 标记的 buff 全部移转给 recipient（数值不变
    ——移转而非重算，Improve 加成不重roll）; GEMS_PLAYED_ON 计数同步
    转移; 移转的血宝石不计入 recipient 的 "played" 事件（非施放）。
    """

    def __init__(self, recipient: "Minion", victim: "Minion") -> None:
        self.recipient = recipient
        self.victim = victim

    def do(self, game: "Game") -> None:
        from hsrl2.tags import GameTag
        gem_buffs = [b for b in self.victim._buffs if b.gem]
        if not gem_buffs:
            return
        stolen_count = self.victim.get(GameTag.GEMS_PLAYED_ON, 0)
        for b in gem_buffs:
            self.victim._buffs.remove(b)
            self.recipient._buffs.append(b)
            if b.health > 0:
                self.recipient.set(
                    GameTag.HEALTH, self.recipient.health + b.health)
        # 受害者当前血 clamp 到新上限（HS 语义——BUG-5）
        if self.victim.health > self.victim.max_health:
            self.victim.set(GameTag.HEALTH, self.victim.max_health)
        self.victim.set(GameTag.GEMS_PLAYED_ON, 0)
        self.recipient.set(
            GameTag.GEMS_PLAYED_ON,
            self.recipient.get(GameTag.GEMS_PLAYED_ON, 0) + stolen_count)


def random_bounty_card_id(game: "Game") -> Optional[str]:
    """随机一张 Bounty（constants.BOUNTY_SPELL_IDS——36.2.2 数据核实
    的五张 T3 法术）。Bounty 非SpellPool 池卡（不占池），直接生成。"""
    import hsrl2.constants as C
    cands = sorted(C.BOUNTY_SPELL_IDS)
    if not cands:
        return None
    return game.rng.choice(cands, label="random_bounty")
