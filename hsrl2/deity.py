"""Deity（旧神）隐藏目标 — 37.0 Aberration 子系统（引擎原语，F-07）。

机制证据
═══════════════════════════════════════════════════════════════════════
- 官方 CardDefs 37.0.0.255130 `BG_OldGod`（"Secret Deity [DNT]"，
  DNT 隐藏目标，START_OF_COMBAT / OBJECTIVE / QUEST_PROGRESS_TOTAL=4）:
  "After 4 friendly Aberrations die each combat, awaken a {1}/{2} {5}.
   <i>({0} left!)</i>@…Done!"；其中
  NUM_1=4（剩余进度）、NUM_2=1、NUM_3=1（初始攻/血）、
  NUM_6=130610 = `BGFYM_000` C'Thun（awakened 卡；`BACON_EVOLUTION_CARD_ID`
  同值）、`BACON_DEITY_SIGIL=1`、`BACON_OLD_GOD` ReferencedTag。
- 官方公告（Patch 36.6.1, 2026-09-22 上线；36.6.3 把阈值 3→4）:
  "Each time a friendly Aberration dies, it advances your Deity's
  progress… only one [of C'Thun / Y'Shaarj] will answer your call…
  chosen at random at the start of each game… Once [4] sacrifices have
  been made, your Deity joins the fight with a game-changing effect."
- 两个 Deity token: `BGFYM_000` C'Thun（"Deity. After this awakens,
  give this minion's stats split amongst your other minions."）与
  `BGFYM_011` Y'Shaarj（"Deity. Deathrattle: Summon your first {0}
  Aberrations that died this combat with their maximum stats (except
  Deities)."，NUM_1=2 / 金色 4）。
- 增/减益读取点（本批 10 张池内卡）: "Give your **Deity** +X/+Y" 家族。

本模块语义（最小通道，证据边界显式）
═══════════════════════════════════════════════════════════════════════
1. 每个英雄有一个**隐藏 Deity 状态**（`Hero.deity: DeityState|None`，
   惰性创建）：官方隐藏随机选 C'Thun/Y'Shaarj。**选择方式**: 为
   保持 `game.rng` 流逐位不变（env 确定性/差分可复现），从
   `GameRNG.seed_value` 与英雄序号确定性派生（跨 seed 近均匀），
   不消耗 rng。证据: 官方选择隐藏、开局即定，不可见于任何日志 tag；
   引擎以确定性派生替代（deviation 记档 F-07）。
2. 初始属性 = 1/1（C'Thun/Y'Shaarj 基础 token）；"give your Deity
   +X/+Y" 直接累加到状态；awaken 时以该状态召唤 Deity token。
3. 进度: **仅战斗中**友方 Aberration（Race.ABERRATION）死亡时 +1
   （`_process_death_inner` 的 death 事件后、离场前，攻/血仍为死亡
   瞬间值）；每场战斗开始重置（卡面 "each combat"）；达到阈值
   `BG_OldGod` NUM_1（=4）且本场尚未 awaken → 召唤 Deity token 到
   战场（`Game.summon` 默认最右空位；官方未公布位置 → 边界记档），
   属性 = 当前 Deity 状态；满场则本次不召唤（后续友方 Aberration
   死亡时重试——"加入战场"需要板位）。
4. **C'Thun 的 awaken 特效 DEFERRED**: "give this minion's stats split
   amongst your other minions" 的**分配规则**（整除/余数去向/是否
   随机）无官方/数据证据 → 不在本批猜测（F-07 台账）。Y'Shaarj 的
   亡语在 `batch_37x_deity` 脚本中按卡面实现。
5. 记录每场战斗的友方 Aberration 死亡序列（card_id, 死亡时攻,
   死亡时最大生命）供 Y'Shaarj "first N … with their maximum stats"
   读取；`except Deities` 由脚本侧按 `DEITY_IDS` 过滤。

本模块只提供**引擎原语**；卡牌脚本在 `hsrl2/scripts/batches/
batch_37x_deity.py`。见 `docs/ENGINE_NOTES.md` F-07。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: 两个 Deity token（官方二选一；两者都是 Aberration token）
DEITY_IDS = ("BGFYM_000", "BGFYM_011")
#: 金色 token（"Make your Deity Golden this game" 类饰品预留；本批未用）
DEITY_GOLDEN_IDS = {"BGFYM_000": "BGFYM_000_G",
                    "BGFYM_011": "BGFYM_011_G"}
#: 基础 token 的 CardDef 初始属性（1/1）
DEITY_BASE_STATS = {"BGFYM_000": (1, 1), "BGFYM_011": (1, 1)}


@dataclass
class DeityState:
    """隐藏 Deity 的状态（非区域实体，不参与战斗快照）。"""
    card_id: str
    golden: bool = False
    atk: int = 1
    health: int = 1
    #: 本场战斗已积累的友方 Aberration 死亡数（每场战斗开始清零）
    progress: int = 0
    #: 本场战斗是否已经 awaken（每场战斗开始清零）
    awakened: bool = False
    #: 官方 `BG_OldGod`（Secret Deity [DNT]）sigil card id；战斗本身不消费，
    #: 供差分注入/审计保存（F-15）。
    sigil_card_id: Optional[str] = None
    #: 是否由外部（diff-harness/测试）显式注入；注入态不参与每场战斗的
    #: progress/awakened 清零（外部状态是权威快照）。
    injected: bool = False

    @property
    def token_card_id(self) -> str:
        return DEITY_GOLDEN_IDS[self.card_id] if self.golden else self.card_id


@dataclass
class DeitySigilState:
    """官方 `BG_OldGod`（Secret Deity [DNT]）sigil 的显式注入状态。

    引擎战斗本身只消费 `DeityState.progress/awakened`；sigil 实体在官方
    客户端是隐藏 objective（BB `Player.FriendlyDeitySigil`/`Minion.
    FriendlyDeitySigil`）。本状态用于保留官方 sigil 身份/进度，默认
    `Hero.deity_sigil=None`，未注入时零副作用。
    """

    card_id: str = "BG_OldGod"
    progress: int = 0
    awakened: bool = False
    injected: bool = True


def threshold_from_db(db) -> int:
    """awaken 阈值 = 官方 `BG_OldGod` 的 NUM_1（数据 255130 = 4）。

    缺失时回落 4（36.6.3 起官方值）；fail-loud 优先（数据权威）。
    """
    d = db.get("BG_OldGod")
    if d is not None:
        num = d.num(0)
        if num is not None:
            return int(num)
    return 4
