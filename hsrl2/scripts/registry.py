"""脚本注册表: card_id → 脚本类。

规则:
  - 只增不改（脚本类被引用后不可重命名，需新增别名迁移）
  - 重复 card_id 注册直接 KeyError（防覆盖）
  - bind_all(game) 在 Game 构造后调用，把脚本绑定到实体工厂
"""

from typing import Any, Dict

REGISTRY: Dict[str, Any] = {}

# 引擎钩子名合法集合（EFFECT_SCRIPT_SOP §2）
VALID_HOOKS = {
    "battlecry", "deathrattle", "start_of_combat", "avenge", "rally",
    "start_of_turn", "end_of_turn", "on_sell", "on_summon", "on_play",
    "activate", "atk", "health",
}


def register(card_id: str, script_class: Any) -> None:
    if card_id in REGISTRY:
        raise KeyError(f"script already registered for {card_id}")
    REGISTRY[card_id] = script_class


def bind_all(db) -> int:
    """校验 REGISTRY 中的 card_id 都存在于 CardDB。返回绑定数。"""
    missing = [cid for cid in REGISTRY if db.get(cid) is None]
    if missing:
        raise KeyError(f"scripts reference unknown cards: {missing[:10]}")
    return len(REGISTRY)


# ── 批次 1（作业单 2026-08-21）+ 批次 1b（依赖就绪后实现）: OK 卡注册 ──
# （含金色 id，金色=独立卡定义）
# BG26_523 Tichondrius 已于 2026-08-21 主线修复时机缺口后实现并注册
# （HERO_DAMAGE_TAKEN 战后施伤 + 监听器表战斗快照恢复）
from hsrl2.scripts.minions import (  # noqa: E402
    ElectricSynthesizerGoldenScript,
    ElectricSynthesizerScript,
    GlowscaleScript,
    GlimGuardianScript,
    KelpKeeperGoldenScript,
    KelpKeeperScript,
    LockedUpMutineerScript,
    MeteoriteCrasherGoldenScript,
    MeteoriteCrasherScript,
    MiniMyrmidonScript,
    OneAmalgamTourGroupScript,
    PrivateInvestigatorScript,
    SnarkySharkScript,
    ThousandthPaperDrakeGoldenScript,
    ThousandthPaperDrakeScript,
    TichondriusScript,
    WaveriderScript,
)
from hsrl2.scripts.spells import (  # noqa: E402
    GlowscaleSpellScript,
    MiniMyrmidonGoldenSpellScript,
    MiniMyrmidonSpellScript,
    WaveriderSpellScript,
)

register("BG26_523", TichondriusScript)

register("BG36_509", PrivateInvestigatorScript)
register("BG36_509_G", PrivateInvestigatorScript)          # 金色 num(1)=6 自然体现
register("BG29_810", ThousandthPaperDrakeScript)
register("BG29_810_G", ThousandthPaperDrakeGoldenScript)   # 两个最左龙
register("BG26_963", ElectricSynthesizerScript)
register("BG26_963_G", ElectricSynthesizerGoldenScript)    # SoC +2/+2 / 战吼基础值×2
register("BG31_843", MeteoriteCrasherScript)
register("BG31_843_G", MeteoriteCrasherGoldenScript)       # "twice" → times=2
register("BG29_888", GlimGuardianScript)
register("BG29_888_G", GlimGuardianScript)                 # 金色 num(0)=4 自然体现
# ── 批次 1b ──
register("BG36_701", KelpKeeperScript)
register("BG36_701_G", KelpKeeperGoldenScript)             # "twice" = 2 次独立随机触发
register("BG30_102", OneAmalgamTourGroupScript)
register("BG30_102_G", OneAmalgamTourGroupScript)          # 金色 num=4/2 自然体现
register("BG36_206", SnarkySharkScript)
register("BG36_206_G", SnarkySharkScript)                  # 金色链自动解析 BG36_205_G
register("BG36_521", LockedUpMutineerScript)
register("BG36_521_G", LockedUpMutineerScript)            # 金色 num(0)=2 自然体现
# ── Spellcraft 批次（首批 3/9; 法术脚本 scripts/spells.py）──
# 随从: on_summon tag 自举 + 立即获得法术; 法术 id 含金色版（金色
# 法术是独立卡定义——金色随从 spellcraft_id 直接指向 BG*_Gt）
register("BG23_000", MiniMyrmidonScript)
register("BG23_000_G", MiniMyrmidonScript)                # → BG23_000_Gt (+4)
register("BG23_007", WaveriderScript)
register("BG23_007_G", WaveriderScript)                   # → BG23_007_Gt (+4/+4)
register("BG23_008", GlowscaleScript)
register("BG23_008_G", GlowscaleScript)                   # → BG23_008_Gt (同文)
register("BG23_000t", MiniMyrmidonSpellScript)
register("BG23_000_Gt", MiniMyrmidonGoldenSpellScript)    # +4（文本字面量）
register("BG23_007t", WaveriderSpellScript)
register("BG23_007_Gt", WaveriderSpellScript)             # +4/+4
register("BG23_008t", GlowscaleSpellScript)
register("BG23_008_Gt", GlowscaleSpellScript)             # 同文

# ── Blood Gem 法术（作业单 2026-08-21: 血宝石系统）──
# 脚本类定义于 hsrl2/actions/bloodgem.py（作业白名单文件; 非池卡，
# 不受 audit_card_registry_v2 池卡缺口审计覆盖）
from hsrl2.actions.bloodgem import (  # noqa: E402
    BloodGemDivineShieldScript,
    BloodGemRebornScript,
    BloodGemScript,
    BloodGemTauntScript,
)

register("BG20_GEM", BloodGemScript)
register("BG20_GEM_DivineShield", BloodGemDivineShieldScript)
register("BG20_GEM_Reborn", BloodGemRebornScript)
register("BG20_GEM_Taunt", BloodGemTauntScript)
