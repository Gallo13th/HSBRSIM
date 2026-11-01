"""纯经济沙盒：只有 recruit 阶段的单 learner 环境（无对手 / 无战斗 / 无血量 / 无排名）。

目的
----
完整游戏里「终局名次」对施法缩放**没有梯度**（``docs/SCALING_SIGNAL.md``：控制存活后
r≈0），而人类强度 99% 来自缩放（``runs/ceiling_probe/REPORT.md``）。所以先在一个
**只有金币与酒馆**的 MDP 里学会「金币 → 载体 → 施法 → 复利」，再回到完整游戏。

沙盒定义
--------
- **状态**：与正常训练**同一套编码** —— ``hsbg.env.obs_std`` 的 3227 floats + 124 cards
  （``hsbg.az.env_api.observe``），动作 245 与 mask 也是同一套。
- **动作**：recruit 阶段的全部合法动作（买 / 卖 / roll / 升级 / 施法 / 冻结 / 换位 /
  英雄技能 / 黑暗赠礼 / 饰品选择 / 发现）。每回合最多 ``action_cap`` 个（默认 40，
  与 s16 训练同口径），之后只剩 EndTurn（引擎 ``turn_action_caps``）。
- **跳过战斗/伤害**：**不改 Rust**。三处纯配置：
  1. ``damage_caps=[[1,0]]`` + ``damage_cap_until_alive=0`` → 每场战斗的伤害被
     ``min(out.damage, 0)=0`` 截断，**任何座位都不会掉血**，也就永远不会被淘汰；
  2. 其余 7 席每回合一开始就被**立刻 EndTurn**（空战团，一次 step 一个座位），
     所以「所有活着的座位都结束了 → combat_round → start_turn」这条引擎原生路径
     直接把我们推进到下一回合的 recruit；
  3. ``max_turns=turns``：第 ``turns`` 回合战斗后引擎自己 ``Phase::GameOver``，
     沙盒回合数与引擎终止一致（不会跑出第 16 回合）。
  战斗本身仍然会发生（空战团对空战团/我方战团，1 次攻击就结束），但它**不影响
  任何状态**；没有血量、没有淘汰、没有名次。
- **终止**：``turns``（默认 15）个 recruit 阶段结束。
- **奖励**（不是名次）：
  - ``log_strength``（默认）：每回合 ``r_t = L_t - L_{t-1}``，
    ``L_t = log1p(Σ_t 战团) / log1p(strength_ref)``；望远镜求和 = ``L_T``。
  - ``auc_strength``：每回合 ``r_t = L_t``（= Σ log，鼓励早强）。
  - ``final_strength``：只有最后一回合 ``r_T = L_T``（纯终局，最难学）。
  - ``board_delta``：**逐决策**的势函数塑形 ``r = L(Σ_t) - L(Σ_{t-1})``（同一
    potential，整局求和仍等于 ``L_T``）。只改信用分配、不改最优策略，密集信号
    让"买这张牌抬了多少身材"立刻有梯度。
  - ``--sandbox-reward-mix "tier:0.1,carrier:0.2,tavern:0.05,spells:0.05,gold:0.02"``
    在每回合奖励上加 tier / 载体数 / 酒馆永久 buff / 施法数 / 剩余金币项。
- **金币**（``--gold-mode``，见 ``docs/COMPOUND_INCOME.md``）：
  - ``fixed``（默认，= 旧的 ``set``）：每回合开始把 seat 0 的金币**重置**为
    ``--gold-per-turn N``。这是与真实经济的主要偏差（真实收入会随饰品/载体增长）。
  - ``add``：**不覆写**引擎收入，在本回合引擎给的金币上再加
    ``N + --gold-add k×(turn−1)``（线性：模拟「每回合多 k 金」的金币生成饰品）。
    ``k=0`` 时就是旧的 ``add`` 口径（引擎自然收入 + N）。
  - ``growth``：同样不覆写引擎收入，再加
    ``scale × (N×(1+--gold-growth-rate)^(turn−1) + --gold-per-carrier×上回合载体数)``
    （几何 + 载体正反馈：买载体 → 收入↑ → 买更多载体）。
  - ``--sandbox-income-scale``（默认 1.0）整体缩放沙盒注入项，做上界探针。
  - ``--gold-cap``（默认 99，0 = 不封顶）是注入后的金币上限；引擎自己的
    ``(base+max_gold_bonus).min(99)`` 只作用于自然补币，不作用于本注入。

输出（每回合）
--------------
战团 Σ、tier、载体数、施法数、酒馆永久 buff 总量（``stats.tavern_atk+tavern_hp``，
即 Devilish Distractor 那条「酒馆随从本局 +1/+2」的累计）。

CLI
---
    python -m hsbg.az.train.economy_sandbox --policy teacher --games 20 --gold-per-turn 10
    python -m hsbg.az.train.economy_sandbox --policy random  --games 20 --gold-per-turn 15
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

#: 沙盒座位：单 learner（其余座位只是「占位」的对手）
SEAT = 0
#: EndTurn 动作（与 ACTION_SPACE_STD 一致）
END_TURN = 0
N_ACTIONS = 245
OBS_FLOATS = 3227
OBS_CARDS = 124

#: 沙盒奖励默认归一化尺度：``L = log1p(Σ)/log1p(STRENGTH_REF)`` ∈ [0, ~1]，
#: 与 value 头 ``tanh`` 的 [-1,1] 量级匹配（真实 t15 p50=26516 → 0.89）。
STRENGTH_REF = 30000.0

#: 默认载体卡（``data/scaling/carriers.json`` 的 ``primary_ids``：11 张 + 金色 22 个 id）
CARRIER_IDS: Tuple[str, ...] = (
    "BG27_005", "BG27_005_G", "BG28_633", "BG28_633_G", "BG28_707", "BG28_707_G",
    "BG28_741", "BG28_741_G", "BG34_692", "BG34_692_G", "BG36_108", "BG36_108_G",
    "BG36_640", "BG36_640_G", "BG36_703", "BG36_703_G", "BG36_704", "BG36_704_G",
    "BG36_762", "BG36_762_G", "BG36_853", "BG36_853_G",
)


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))


def carrier_ids(path: Optional[str] = None) -> Tuple[str, ...]:
    """读取载体 id 集合（``data/scaling/carriers.json`` 的 primary_ids；缺失时用内置表）。"""
    p = path or os.path.join(_root(), "data", "scaling", "carriers.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        ids = tuple(str(x) for x in (d.get("primary_ids") or ()))
        if ids:
            return ids
    except Exception:  # noqa: BLE001 - 数据缺失时用内置常量
        pass
    return CARRIER_IDS


# ── 配置 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SandboxConfig:
    """沙盒配置（引擎侧只用到 ``engine_config()`` 的那些 key）。"""

    turns: int = 15
    gold_per_turn: int = 10
    #: 收入口径（``--gold-mode``）：
    #: ``fixed`` = 每回合把金币重置为 ``gold_per_turn``（= 旧的 ``set``；**默认、逐位等价**）；
    #: ``add`` = 引擎自然收入 + ``gold_per_turn + gold_add×(turn−1)``（线性收入）；
    #: ``growth`` = 引擎自然收入 + ``scale×(gold_per_turn×(1+rate)^(turn−1) + per_carrier×载体数)``
    #: （几何收入 + 载体正反馈）。``add``/``growth`` **不覆写**引擎收入，所以饰品/法术
    #: 生成的金币与 max-gold 加成会保留（fixed 会把回合开始的金币盖掉）。
    gold_mode: str = "fixed"
    #: ``add`` 模式每回合额外收入的**斜率**（第 t 回合额外 ``gold_add×(t−1)`` 金）
    gold_add: int = 0
    #: ``growth`` 模式每回合收入的复利率（第 t 回合 base×``(1+rate)^(t−1)``）
    gold_growth_rate: float = 0.0
    #: ``growth`` 模式每个「上回合在场上」的载体额外给的金币（滚雪球项；0 = 关）
    gold_per_carrier: int = 0
    #: 注入项的全局缩放（上界探针；1.0 = 原样，逐位等价）
    income_scale: float = 1.0
    #: 注入后的金币上限（0 = 不封顶）。默认 99 与引擎 ``(base+max_gold_bonus).min(99)`` 一致
    gold_cap: int = 99
    #: 每回合动作上限（与 s16 训练的 ``--max-actions-per-turn 40`` 同口径）
    action_cap: int = 40
    num_players: int = 8
    reward: str = "log_strength"
    reward_mix: str = ""
    strength_ref: float = STRENGTH_REF
    # ── exp_growth 奖励参数（"几何级数/指数成长"口径；见 docs/COMP_LINES_TINY.md §3）
    #: 终局强度的权重 w1（``L_T = log1p(Σ_T)/log1p(strength_ref)``）
    growth_w_final: float = 1.0
    #: 超线性增长权重 w2：``Σ_{t>=growth_from} max(0, ΔlnΣ_t − growth_slope_base)``。
    #: 默认 0.2：value 头是 ``tanh``（值域 [-1,1]），整局回报必须留在 ~[-2,2] 内，
    #: 所以 w1=1.0（L_T ≤ 0.89）+ w2=0.2（≤0.1/回合×6）+ w3=0.3 是安全上限。
    growth_w_super: float = 0.2
    #: 基线对数斜率（"线性成长"的参照）：ΔlnΣ 低于它不加分
    growth_slope_base: float = 0.35
    #: 从第几回合开始给超线性奖励（用户口径：t10..t15）
    growth_from: int = 10
    #: 指数段权重 w3：``max(0, ln(Σ_T/Σ_12) − ln3)``（t12→t15 涨 3 倍的额外加成）
    growth_w_ratio: float = 0.0
    #: 目标指数段的参照回合（默认 t12 → t15 涨 3×）
    growth_ref_turn: int = 12
    growth_target_ratio: float = 3.0
    lobby_types: Tuple[str, ...] = ()
    lobby_races: int = 5
    seed: int = 0
    #: 饰品（Trinket）开关：``None`` = 引擎默认（第 6 回合小饰品 / 第 9 回合大饰品，
    #: 每档 4 选 1，**与改动前的沙盒逐位一致**）；``True`` = 显式钉住 6/9 回合 + 4 选项；
    #: ``False`` = 关掉饰品（两个阈值推到 999）。饰品选择在引擎里是
    #: ``Pending::Trinket``，编码为 ``Choose(0..3)`` = 动作 30..33（见 docs/COMP_LINES_TINY.md §2）。
    trinkets: Optional[bool] = None
    #: ``True`` = 开局 tier6 + 升级免费（与 ``engine_ceiling_probe --cheat tier6``
    #: 同口径：``upgrade_costs=[0]*6`` + 每回合 ``debug set_player tier=6``）。
    #: 默认 ``False``：真实经济的升级价格。
    free_tier6: bool = False
    #: 额外的引擎配置覆盖（高级用；会被上面几项之后的断言保护）
    extra: Tuple[Tuple[str, Any], ...] = ()

    # ── 引擎配置 ────────────────────────────────────────────────────────
    def engine_config(self) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {
            # 跳过战斗影响的全部手段：伤害恒为 0 → 永不掉血/淘汰
            "damage_caps": [[1, 0]],
            "damage_cap_until_alive": 0,
            # 第 turns 回合战斗后由引擎自己结束（不会跑到 turns+1）
            "max_turns": int(self.turns),
            # 每回合动作上限（之后只剩 EndTurn / pending 选择）
            "turn_action_caps": [int(self.action_cap)] * max(1, int(self.turns) + 1),
            "max_actions_per_turn": int(self.action_cap),
            "num_players": int(self.num_players),
        }
        if self.free_tier6:
            # 升级免费：引擎每回合按 ``upgrade_costs[tier]`` 重算价格，全部设 0
            cfg["upgrade_costs"] = [0] * 6
        if self.trinkets is not None:
            if self.trinkets:
                # 显式钉住引擎默认的饰品档位（第 6 回合小饰品、第 9 回合大饰品、4 选 1）。
                # 值等于 ``RulesConfig::default()``，所以这正是「把默认写死」而已。
                cfg["lesser_trinket_turn"] = 6
                cfg["greater_trinket_turn"] = 9
                cfg["trinket_choices"] = 4
            else:
                # 关掉：两个阈值推到 999（`turn == lesser` 与 `turn >= greater` 都不成立）。
                # 不能设 0：``greater_due = turn >= greater`` 会从第 1 回合就一直成立。
                cfg["lesser_trinket_turn"] = 999
                cfg["greater_trinket_turn"] = 999
        if self.lobby_types:
            cfg["lobby_types"] = [str(x) for x in self.lobby_types]
            cfg["lobby_races"] = max(int(self.lobby_races), len(cfg["lobby_types"]))
        for k, v in self.extra:
            cfg[str(k)] = v
        return cfg

    def engine_json(self) -> str:
        return json.dumps(self.engine_config())

    def replaced(self, **kw: Any) -> "SandboxConfig":
        return replace(self, **kw)

    # ── 奖励 ────────────────────────────────────────────────────────────
    def mix_terms(self) -> List[Tuple[str, float]]:
        out: List[Tuple[str, float]] = []
        for part in str(self.reward_mix or "").split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise ValueError(f"reward_mix 项 {part!r} 需要 'name:weight'")
            name, w = part.split(":", 1)
            out.append((name.strip(), float(w)))
        return out

    def validate(self) -> None:
        if self.turns <= 0:
            raise ValueError("turns 必须 > 0")
        if self.gold_per_turn < 0:
            raise ValueError("gold_per_turn 必须 >= 0")
        if self.gold_mode not in ("fixed", "set", "add", "growth"):
            raise ValueError("gold_mode 只能是 fixed|add|growth（set 是 fixed 的旧别名）")
        if int(self.gold_add) < 0:
            raise ValueError("gold_add 必须 >= 0")
        if float(self.gold_growth_rate) < 0.0:
            raise ValueError("gold_growth_rate 必须 >= 0")
        if int(self.gold_per_carrier) < 0:
            raise ValueError("gold_per_carrier 必须 >= 0")
        if float(self.income_scale) < 0.0:
            raise ValueError("income_scale 必须 >= 0")
        if int(self.gold_cap) < 0:
            raise ValueError("gold_cap 必须 >= 0（0 = 不封顶）")
        if self.reward not in ("log_strength", "auc_strength", "final_strength",
                               "board_delta", "t12_t15", "exp_growth"):
            raise ValueError("reward 只能是 log_strength|auc_strength|final_strength|"
                             "board_delta|t12_t15|exp_growth")
        if not (0.0 <= float(self.growth_slope_base) <= 5.0):
            raise ValueError("growth_slope_base 必须在 0..5")
        if not (1 <= int(self.growth_from) <= 200):
            raise ValueError("growth_from 必须在 1..200")
        if not (2 <= int(self.num_players) <= 8):
            raise ValueError("num_players 必须在 2..8")
        for name, _w in self.mix_terms():
            if name not in ("tier", "carrier", "tavern", "spells", "gold", "sigma"):
                raise ValueError(f"reward_mix 未知项 {name!r}")


# ── 观测包 ──────────────────────────────────────────────────────────────────


@dataclass
class SandboxObs:
    """一次决策输入（与正常训练同一套编码）。"""

    features: np.ndarray   # f32[3227]
    cards: np.ndarray      # i32[124]
    mask: np.ndarray       # bool[245]
    turn: int

    @property
    def n_legal(self) -> int:
        return int(self.mask.sum())


def stack_obs(obs: Sequence[SandboxObs]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把一批 ``SandboxObs`` 叠成模型输入 ``(features, cards, mask)``。"""
    n = len(obs)
    f = np.empty((n, OBS_FLOATS), dtype=np.float32)
    c = np.empty((n, OBS_CARDS), dtype=np.int32)
    m = np.empty((n, N_ACTIONS), dtype=bool)
    for i, o in enumerate(obs):
        f[i] = o.features
        c[i] = o.cards
        m[i] = o.mask
    return f, c, m


# ── 单环境 ──────────────────────────────────────────────────────────────────


class EconomySandbox:
    """只有 recruit 阶段的单座位（seat 0）沙盒环境。

    接口与 gym 类似：``reset(seed) -> SandboxObs``、``step(action) -> (obs, reward, done, info)``。
    ``info`` 是该回合结束瞬间的度量（``turn_metrics``），``done=True`` 时附带
    ``episode``（整局汇总）。
    """

    def __init__(self, config: Optional[SandboxConfig] = None, *,
                 carriers: Optional[Iterable[str]] = None,
                 core_ids: Optional[Iterable[str]] = None):
        self.cfg = config or SandboxConfig()
        self.cfg.validate()
        self._cfg_json = self.cfg.engine_json()
        self._mix = self.cfg.mix_terms()
        self._carriers = set(carriers) if carriers is not None else set(carrier_ids())
        #: 复利核心牌（``data/scaling/compound_cards.json`` 的目标流派核心集）；只用于度量。
        #: ``None`` = 不统计（不新增 "core" 键 → 旧路径的度量逐位不变）。
        self._core = set(core_ids) if core_ids is not None else None
        self._engine = None
        self.g = None
        self.seed = int(self.cfg.seed)
        self.turn = 0
        self.done = True
        self.turn_metrics: List[Dict[str, Any]] = []
        self._prev_L = 0.0
        self._prev_sigma = 0
        self._last_sigma = 0
        self._end_metrics: Optional[Dict[str, Any]] = None
        self.last_info: Dict[str, Any] = {}
        #: 饰品统计（只在 ``cfg.trinkets is not None`` 时才写进度量/汇总）
        self.trinket_offers = 0
        self.trinket_picks: List[str] = []
        self._trinket_checked_turn = -1
        self._trinket_views = 0
        #: 本局金币/回合（金币课程可以逐局改，不必重建环境）：默认取 cfg
        self.gold_per_turn = int(self.cfg.gold_per_turn)
        #: 本回合注入的金币 / 回合开始的实际金幣（measured by ``_inject_gold``）
        self._turn_gold_income = 0
        self._turn_gold_start = 0

    # ── 引擎 ────────────────────────────────────────────────────────────
    @property
    def engine(self):
        if self._engine is None:
            import hsbg_engine  # 惰性：没有引擎也能 import 本模块
            self._engine = hsbg_engine
        return self._engine

    @staticmethod
    def _mask(game, seat: int) -> np.ndarray:
        return np.frombuffer(bytes(game.legal_mask(int(seat))), dtype=np.uint8).astype(bool)

    # ── 生命周期 ────────────────────────────────────────────────────────
    def reset(self, seed: Optional[int] = None) -> SandboxObs:
        self.seed = int(self.cfg.seed if seed is None else seed)
        self.g = self.engine.Game(self.seed, self._cfg_json)
        self.turn_metrics = []
        self._prev_L = 0.0
        self._prev_sigma = 0
        self._last_sigma = 0
        self._end_metrics = None
        self._turn_gold_income = 0
        self._turn_gold_start = 0
        self.trinket_offers = 0
        self.trinket_picks = []
        self._trinket_checked_turn = -1
        self._trinket_views = 0
        self.done = False
        self.last_info = {}
        self._hero_select()
        if self.g.is_over():
            # 极端配置（例如不存在的英雄池）也不会卡死：直接放弃这局
            self.done = True
            return self._obs()
        self.turn = int(self.g.turn)
        self._begin_turn(self.turn)
        return self._obs()

    def _hero_select(self, max_steps: int = 64) -> None:
        """英雄选择：先让**对手**选（第一个合法），最后 seat 0 也选第一个。

        seat 0 的英雄是策略的一部分（观测/动作都含），但沙盒里我们**不把英雄选择
        当决策**：它和真实训练的编码一致，但沙盒目标是经济缩放，英雄差异进噪声。
        需要时用 ``--hero-first-seat`` 让策略自己选（见 CLI）。
        """
        for _ in range(max_steps):
            if int(self.g.turn) > 0:
                return
            acted = False
            for p in list(range(1, int(self.g.num_players))) + [SEAT]:
                if self.g.needs_action(p):
                    legal = np.flatnonzero(self._mask(self.g, p))
                    if legal.size:
                        self.g.step(p, int(legal[0]))
                        acted = True
                        break
            if not acted:
                return

    def _begin_turn(self, t: int) -> None:
        """回合开始：注入金币 + 把其余座位立刻 EndTurn（它们不会做任何决策）。"""
        self._inject_gold(t)
        self._drive_opponents(t)

    def _income_carriers(self) -> int:
        """上回合结束时在场的载体数（``growth`` 的滚雪球项；第 1 回合为 0）。"""
        if self.turn_metrics:
            return max(0, int(self.turn_metrics[-1].get("carriers") or 0))
        return 0

    def income_for_turn(self, turn: int) -> int:
        """本回合沙盒要注入的金币量（**不含**引擎自然收入；``fixed`` 时它就是全部金币）。

        纯函数（只读配置 + 上回合载体数），便于单测直接核对三档轨迹::

            fixed : n_t = gold_per_turn
            add   : n_t = gold_per_turn + gold_add×(t−1)
            growth: n_t = gold_per_turn×(1+rate)^(t−1) + gold_per_carrier×carriers_{t−1}

        最后统一乘 ``income_scale`` 再取整。
        """
        t = max(1, int(turn))
        mode = self.cfg.gold_mode
        if mode in ("fixed", "set"):
            raw = float(self.gold_per_turn)
        elif mode == "add":
            raw = float(self.gold_per_turn) + float(self.cfg.gold_add) * (t - 1)
        elif mode == "growth":
            raw = float(self.gold_per_turn) * (
                (1.0 + float(self.cfg.gold_growth_rate)) ** (t - 1))
            raw += float(self.cfg.gold_per_carrier) * float(self._income_carriers())
        else:  # pragma: no cover - validate() 已挡住
            raise ValueError(f"未知 gold_mode: {mode!r}")
        return int(round(float(self.cfg.income_scale) * raw))

    def _inject_gold(self, turn: int) -> None:
        """回合开始：设置金币 + 把 seat 0 的血补满。

        补血是**必要**的：池里有以生命值支付的牌（``costs_health``），seat 0 一旦
        被打到 0 血就会被淘汰；而其余 7 席在回合一开始就已经 EndTurn，于是引擎会
        认为"所有人都结束了"→ 立刻打完本轮 → 跳到 GameOver（实测：25k 局里偶发
        一次，表现为 ``非法动作 ... game over``）。血量在沙盒里没有意义（无战斗伤害），
        所以每回合直接回满。

        金币口径见 :meth:`income_for_turn`：

        - ``fixed``（含旧别名 ``set``）：``gold = n``（**覆写**引擎刚补的金币）；
        - ``add``/``growth``：``gold = 引擎金币 + n``（**保留**饰品/法术生成的收入）；
        - 两种都受 ``gold_cap``（默认 99）约束。
        """
        n = int(self.income_for_turn(turn))
        set_like = self.cfg.gold_mode in ("fixed", "set")
        cmd: Dict[str, Any] = {"cmd": "set_player", "p": SEAT, "health": 30}
        if self.cfg.free_tier6:
            # 与 ceiling_probe 的 ``--cheat tier6`` 一致：每回合把 tier 打到 6 且升级免费
            cmd.update({"tier": 6, "upgrade_cost": 0})
        if set_like:
            # 与改动前逐位一致：n=0 时不写 gold 键（保持引擎自然补币）
            if n > 0:
                cmd["gold"] = n if not self.cfg.gold_cap else min(int(self.cfg.gold_cap), n)
        elif n > 0:
            # add/growth：在引擎本回合给出的金币之上再加（不覆写）
            gold = int(self._gold()) + n
            if self.cfg.gold_cap:
                gold = min(int(self.cfg.gold_cap), gold)
            cmd["gold"] = int(gold)
        self.g.debug(json.dumps(cmd))
        # 度量：本回合注入项 + 回合开始的实际金币（Σ/金币 分母；见 docs/COMPOUND_INCOME.md）
        self._turn_gold_income = int(n)
        self._turn_gold_start = int(self._gold())

    def set_gold_per_turn(self, n: int) -> None:
        """改本局之后每回合的金币（金币课程用；下一回合生效）。"""
        self.gold_per_turn = max(0, int(n))

    def _gold(self) -> int:
        f, _c = self.g.observe(SEAT)
        arr = np.frombuffer(bytes(f), dtype="<f4")
        return int(round(float(arr[7]) * 10.0))     # obs_std G_GOLD=7，scale 10

    def _drive_opponents(self, t: int, max_steps: int = 16) -> None:
        """其余座位：空战团直接 EndTurn；pending（饰品/发现）用第一个合法动作消化。"""
        for p in range(1, int(self.g.num_players)):
            for _ in range(max_steps):
                if int(self.g.turn) != t or not self.g.needs_action(p):
                    break
                m = self._mask(self.g, p)
                if m[END_TURN]:
                    self.g.step(p, END_TURN)
                    continue
                legal = np.flatnonzero(m)
                if not legal.size:
                    break
                self.g.step(p, int(legal[0]))

    # ── 观测 ────────────────────────────────────────────────────────────
    def _obs(self) -> SandboxObs:
        fa, ca = self.g.observe(SEAT)
        feats = np.frombuffer(bytes(fa), dtype="<f4").copy()
        cards = np.frombuffer(bytes(ca), dtype="<i4").copy()
        return SandboxObs(features=feats, cards=cards,
                          mask=self._mask(self.g, SEAT), turn=int(self.g.turn))

    def _pending_kind(self) -> str:
        """当前待选（``me.pending``）的 kind；没有待选时返回 ``""``。

        只在饰品计量开启、且这一步是 ``Choose`` 时才调用（一次 ``view`` ≈0.45 ms），
        所以不影响默认路径的开销与结果。
        """
        try:
            v = json.loads(self.g.view(SEAT))
            p = (v.get("me") or {}).get("pending") or {}
            return str(p.get("kind") or "") if isinstance(p, dict) else ""
        except Exception:  # noqa: BLE001 - 计量失败不影响对局
            return ""

    def obs(self) -> SandboxObs:
        return self._obs()

    # ── 搜索用：轻量克隆 / 状态转移（不度量、不发奖）─────────────────────
    def clone(self) -> "EconomySandbox":
        """复制一份独立状态供 PUCT 分支用（引擎 ``Game.copy()``，实测 ~8 µs）。

        只复制**状态机**需要的东西（引擎 / 金币档位 / turn / done）；度量与奖励
        历史清空（搜索不做 reward / 不读 ``view``）。``cfg`` 只读共享。
        """
        e = object.__new__(EconomySandbox)
        e.cfg = self.cfg
        e._cfg_json = self._cfg_json
        e._mix = self._mix
        e._carriers = self._carriers
        e._engine = self._engine
        e.g = None if self.g is None else self.g.copy()
        e.seed = int(self.seed)
        e.turn = int(self.turn)
        e.done = bool(self.done)
        e.gold_per_turn = int(self.gold_per_turn)
        e.turn_metrics = []
        e._prev_L = 0.0
        e._prev_sigma = 0
        e._last_sigma = 0
        e._end_metrics = None
        e._turn_gold_income = int(self._turn_gold_income)
        e._turn_gold_start = int(self._turn_gold_start)
        e.last_info = {}
        e.trinket_offers = 0
        e.trinket_picks = []
        e._trinket_checked_turn = int(self._trinket_checked_turn)
        e._trinket_views = int(self._trinket_views)
        return e

    def search_step(self, action: int) -> bool:
        """搜索用状态转移：引擎 ``step`` + 新回合的金币/回血/对手 ``EndTurn``。

        与 :meth:`step` 的**状态机一致**（同一 ``_inject_gold`` / ``_drive_opponents``
        路径），但**不取 ``view``、不算奖励、不写 turn_metrics**（搜索每步 ~50 µs）。
        返回 ``True`` 表示这个动作把回合推进了。
        """
        if self.done or self.g is None or bool(self.g.is_over()):
            return False
        t = int(self.g.turn)
        self.g.step(SEAT, int(action))
        if bool(self.g.is_over()):
            return False
        if int(self.g.turn) != t:
            self.turn = int(self.g.turn)
            self._inject_gold(self.turn)
            self._drive_opponents(self.turn)
            return True
        return False

    # ── 度量 ────────────────────────────────────────────────────────────
    def measure(self) -> Dict[str, Any]:
        """当前（seat 0）状态的全部度量；一次 ``view(0)``。"""
        v = json.loads(self.g.view(SEAT))
        me = v.get("me") or {}
        st = me.get("stats") or {}
        board = me.get("board") or []
        sigma = sum(int(m.get("atk") or 0) + int(m.get("hp") or 0) for m in board)
        carriers = sum(1 for m in board if str(m.get("id") or "") in self._carriers)
        out: Dict[str, Any] = {
            "turn": int(v.get("turn") or self.g.turn),
            "sigma": int(sigma),
            "tier": int(me.get("tier") or 0),
            "board_len": len(board),
            "carriers": int(carriers),
            "spells": int(st.get("spells_cast") or 0),
            "tavern_buff": int(st.get("tavern_atk") or 0) + int(st.get("tavern_hp") or 0),
            "gold": int(me.get("gold") or 0),
            "hand_len": len(me.get("hand") or []),
            "minions_bought": int(st.get("minions_bought") or 0),
            "refreshes": int(st.get("refreshes") or 0),
            # 金色卡（三连奖励的产物）：真实高强战团 62.1% 身材来自 ``_G``
            "goldens": int(sum(1 for m in board if bool(m.get("golden")))),
            # 收入度量（Σ/金币 的分母；docs/COMPOUND_INCOME.md）：
            #   gold_income = 本回合沙盒**注入**的金币（不含引擎自然/饰品收入）
            #   gold_start  = 本回合开始实际拿到的金币（= 引擎补币 + 饰品回合开始收入 + 注入）
            "gold_income": int(self._turn_gold_income),
            "gold_start": int(self._turn_gold_start),
        }
        if self._core is not None:
            # 目标流派核心牌在场数（复利先验的效果度量；未配置时不新增键）
            out["core"] = int(sum(1 for m in board
                                  if str(m.get("id") or "") in self._core))
        if self.cfg.trinkets is not None:
            # 饰品（只在开启计量时新增键：默认路径的度量逐位不变）
            trs = [str(x.get("id") or "") for x in (me.get("trinkets") or ())]
            out["trinkets"] = trs
            out["trinket_count"] = len(trs)
            if trs:
                # 本局**曾经拥有过**的饰品（大饰品可能替换小饰品，这里取并集）
                self.trinket_picks = sorted(set(self.trinket_picks) | set(trs))
        return out

    @staticmethod
    def sigma_from_features(features: np.ndarray) -> int:
        """从 3227 观测的 board 块（7×31，atk/hp 已 /10）解码战团 Σ。"""
        b = np.asarray(features, dtype=np.float32)[68:285].reshape(7, 31)
        present = b[:, 0] > 0.5
        if not bool(present.any()):
            return 0
        return int(round(float((b[present, 1] + b[present, 2]).sum()) * 10.0))

    def _L(self, sigma: int) -> float:
        return math.log1p(max(0, int(sigma))) / math.log1p(float(self.cfg.strength_ref))

    def _turn_reward(self, met: Dict[str, Any]) -> float:
        L = self._L(int(met["sigma"]))
        mode = self.cfg.reward
        if mode == "log_strength":
            r = L - self._prev_L
        elif mode == "auc_strength":
            r = L
        elif mode == "t12_t15":
            # 目标（L 归一化口径，与 value 头/叶值同一曲线）：
            #   T = L(Σ12) + 0.5·L(Σ15)
            # 逐回合密集分解（精确望远镜，形状优势不变）：
            #   t<=12: r_t = 1.5·(L_t − L_{t−1})；t>12: r_t = 0.5·(L_t − L_{t−1})
            #   Σ_t r_t = 1.5·L12 + 0.5·(L15 − L12) = 1.0·L12 + 0.5·L15
            coef = 1.5 if int(met["turn"]) <= 12 else 0.5
            r = coef * (L - self._prev_L)
        elif mode == "exp_growth":
            # 「几何级数/指数成长」口径（用户的核心判断）：线性成长拿不到额外奖励，
            # 只有**加速**才加分。逐回合分解（每回合都有梯度，不靠稀疏终局）：
            #   r_t = w1·(L_t − L_{t−1})                           # 终局强度（望远镜 → w1·L_T）
            #       + w2·max(0, ΔlnΣ_t − slope_base)   (t ≥ t0)     # 超线性（加速）奖励
            #       + w3·max(0, ln(Σ_T/Σ_12) − ln 3)   (只在 t = T) # 指数段（t12→t15 ≥3×）
            # ΔlnΣ_t = ln(1+Σ_t) − ln(1+Σ_{t−1}) 是本回合的**对数斜率**：
            #   · 线性铺场（每回合 +常数）→ ΔlnΣ 递减 → 只有早期那几回合可能过基线；
            #   · 复利（Σ 每回合乘常数）→ ΔlnΣ 恒定 → t10..t15 每回合都拿满 w2。
            sig = max(0, int(met["sigma"]))
            r = float(self.cfg.growth_w_final) * (L - self._prev_L)
            if int(met["turn"]) >= int(self.cfg.growth_from):
                d = math.log1p(sig) - math.log1p(max(0, int(self._prev_sigma)))
                r += float(self.cfg.growth_w_super) * max(
                    0.0, d - float(self.cfg.growth_slope_base))
            if float(self.cfg.growth_w_ratio) and int(met["turn"]) >= int(self.cfg.turns):
                s0 = self._sigma_at(int(self.cfg.growth_ref_turn))
                if s0 > 0 and sig > 0:
                    r += float(self.cfg.growth_w_ratio) * max(
                        0.0, math.log(sig / s0) - math.log(
                            max(1.0, float(self.cfg.growth_target_ratio))))
        else:  # final_strength：只在最后一回合给
            last = int(met["turn"]) >= int(self.cfg.turns)
            r = L if last else 0.0
        for name, w in self._mix:
            if name == "tier":
                r += w * (float(met["tier"]) / 6.0)
            elif name == "carrier":
                r += w * (float(met["carriers"]) / 7.0)
            elif name == "tavern":
                r += w * (math.log1p(float(met["tavern_buff"])) / math.log1p(200.0))
            elif name == "spells":
                r += w * (math.log1p(float(met["spells"])) / math.log1p(300.0))
            elif name == "sigma":
                r += w * L
            elif name == "gold":
                r += w * (float(met["gold"]) / 10.0)
        self._prev_L = L
        self._prev_sigma = max(0, int(met["sigma"]))
        return float(r)

    def _sigma_at(self, turn: int) -> int:
        """历史某回合的战团 Σ（不在 ``turn_metrics`` 里时返回 0）。"""
        for r in self.turn_metrics:
            if int(r.get("turn") or -1) == int(turn):
                return max(0, int(r.get("sigma") or 0))
        return 0

    # ── 步进 ────────────────────────────────────────────────────────────
    def step(self, action: int) -> Tuple[SandboxObs, float, bool, Dict[str, Any]]:
        if self.done:
            raise RuntimeError("沙盒已终止：先 reset()")
        a = int(action)
        if not (0 <= a < N_ACTIONS):
            raise ValueError(f"动作越界: {a}")
        if bool(self.g.is_over()):
            # 引擎已经结束（回合上限 / 只剩 1 人）：把本回合度量补上并收尾
            met = self.measure()
            self.turn_metrics.append(met)
            self.done = True
            return self._obs(), self._turn_reward(met), True, {
                "turn_metrics": met, "episode": self.episode_summary(),
                "truncated": True}
        t = int(self.g.turn)
        # 饰品选择计量：这一步是 Choose 且待选正是 ``trinket`` → 记一次「饰品选择机会」。
        # 只在 ``cfg.trinkets is not None`` 时做，并且**每回合最多查一次 view**
        # （饰品只会在第 6/9 回合出现；不加这个门的话，随机策略下的每一次
        #  Discover/ChooseOne 都会多调一次 view()，实测占采样时间的 ~25%）。
        if self.cfg.trinkets is not None and 30 <= a <= 46 \
                and bool(self._mask(self.g, SEAT)[a]):
            if int(self._trinket_checked_turn) != t:
                self._trinket_checked_turn = t
                self._trinket_views = 0
            if int(self._trinket_views) < 8:      # 每回合最多查 8 次（饰品只在 6/9 回合）
                self._trinket_views += 1
                if self._pending_kind() == "trinket":
                    self.trinket_offers += 1
        # 结束回合的瞬间先度量（此时 board 已是本回合最终形态）
        if a == END_TURN and bool(self._mask(self.g, SEAT)[END_TURN]):
            self._end_metrics = self.measure()
        try:
            self.g.step(SEAT, a)
        except Exception as exc:  # noqa: BLE001 - 非法动作：显式暴露，不做静默兜底
            raise RuntimeError(f"非法动作 {a}（turn {t}）: {exc}") from exc

        info: Dict[str, Any] = {}
        reward = 0.0
        advanced = int(self.g.turn) != t or bool(self.g.is_over())
        if self.cfg.reward == "board_delta":
            # 逐决策势函数塑形（不调用 view，只用观测里的 board atk/hp）
            sig1 = self.sigma_from_features(self._obs().features)
            reward += self._L(sig1) - self._L(self._last_sigma)
            self._last_sigma = sig1
        if advanced:
            met = self._end_metrics if self._end_metrics is not None else self.measure()
            self._end_metrics = None
            self.turn_metrics.append(met)
            if self.cfg.reward != "board_delta":
                reward = self._turn_reward(met)
            else:
                self._prev_L = self._L(int(met["sigma"]))
                self._prev_sigma = max(0, int(met["sigma"]))
            info["turn_metrics"] = met
            over = bool(self.g.is_over()) or int(self.g.turn) > int(self.cfg.turns)
            if over or len(self.turn_metrics) >= int(self.cfg.turns):
                self.done = True
                info["episode"] = self.episode_summary()
            else:
                self.turn = int(self.g.turn)
                self._begin_turn(self.turn)
        self.last_info = info
        return self._obs(), reward, self.done, info

    # ── 汇总 ────────────────────────────────────────────────────────────
    def episode_summary(self) -> Dict[str, Any]:
        """整局汇总：t12/t15 Σ、tier 分布、载体率、施法数、酒馆 buff。"""
        rows = self.turn_metrics
        by_turn = {int(r["turn"]): r for r in rows}

        def _at(t: int) -> Dict[str, Any]:
            return by_turn.get(int(t), {})

        def _val(t: int, key: str, default: int = 0) -> int:
            return int(_at(t).get(key, default))

        last = rows[-1] if rows else {}
        tiers = [int(r["tier"]) for r in rows] or [0]
        out: Dict[str, Any] = {
            "seed": int(self.seed),
            "turns": len(rows),
            "sigma_by_turn": {int(r["turn"]): int(r["sigma"]) for r in rows},
            "sigma_t12": _val(12, "sigma"),
            "sigma_t15": _val(15, "sigma", int(last.get("sigma") or 0)),
            "tier_t12": _val(12, "tier"),
            "tier_t15": _val(15, "tier", int(last.get("tier") or 0)),
            "tier_final": int(last.get("tier") or 0),
            "tier_hist": tiers,
            "carriers_t15": _val(15, "carriers", int(last.get("carriers") or 0)),
            "carriers_max": max((int(r["carriers"]) for r in rows), default=0),
            "spells_t15": _val(15, "spells", int(last.get("spells") or 0)),
            "spells_max": max((int(r["spells"]) for r in rows), default=0),
            "tavern_buff_t15": _val(15, "tavern_buff", int(last.get("tavern_buff") or 0)),
            "goldens_t15": _val(15, "goldens", int(last.get("goldens") or 0)),
            "goldens_max": max((int(r.get("goldens") or 0) for r in rows), default=0),
            "gold_hist": [int(r["gold"]) for r in rows],
            "gold_start_hist": [int(r.get("gold_start") or 0) for r in rows],
            "gold_income_hist": [int(r.get("gold_income") or 0) for r in rows],
            # Σ/金币 的分母：整局**拿到**的金币（每回合开始的实际金币之和）。fixed 口径下
            # 就是 15×gold_per_turn（= 450）；真实 10k+ 的 9.9 Σ/金币 用同一个分母。
            "gold_total_income": sum(int(r.get("gold_start") or 0) for r in rows),
            "gold_total_injected": sum(int(r.get("gold_income") or 0) for r in rows),
            "rows": [dict(r) for r in rows],
            "config": {
                "turns": int(self.cfg.turns), "gold_per_turn": int(self.gold_per_turn),
                "gold_mode": self.cfg.gold_mode, "action_cap": int(self.cfg.action_cap),
                "gold_add": int(self.cfg.gold_add),
                "gold_growth_rate": float(self.cfg.gold_growth_rate),
                "gold_per_carrier": int(self.cfg.gold_per_carrier),
                "income_scale": float(self.cfg.income_scale),
                "gold_cap": int(self.cfg.gold_cap),
                "reward": self.cfg.reward, "reward_mix": self.cfg.reward_mix,
                "free_tier6": bool(self.cfg.free_tier6),
                "num_players": int(self.cfg.num_players)},
        }
        if self._core is not None:
            # 复利核心牌在场数的整局口径：t15 / 单局最大 / 有核心牌的回合数
            out["core_t15"] = _val(15, "core", int(last.get("core") or 0))
            out["core_max"] = max((int(r.get("core") or 0) for r in rows), default=0)
            out["core_turns"] = sum(1 for r in rows if int(r.get("core") or 0) > 0)
        # ── 成长曲线形状（grow 口径；纯函数，任何 reward 模式都记）──────────
        out.update(growth_shape(out["sigma_by_turn"]))
        # ── 饰品（只在开启了饰品计量时新增键）────────────────────────────────
        if self.cfg.trinkets is not None:
            picked = [str(x) for x in (self.trinket_picks or ())]
            if not picked and rows:
                picked = [str(x) for x in (last.get("trinkets") or ())]
            out["trinket_offers"] = int(self.trinket_offers)
            out["trinket_ids"] = picked
            out["trinket_count"] = len(picked)
        return out


# ── 成长曲线形状 ────────────────────────────────────────────────────────────


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    """最小二乘斜率（样本太少或 x 方差为 0 时返回 0）。"""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return 0.0
    return float(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den)


def _quad_coef(xs: Sequence[float], ys: Sequence[float]) -> float:
    """二次拟合的二次项系数（曲率）；用中心化的最小二乘（3×3 正规方程直接解）。"""
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    x = [v - mx for v in xs]
    y = [v - my for v in ys]
    s2 = sum(v ** 2 for v in x)
    s3 = sum(v ** 3 for v in x)
    s4 = sum(v ** 4 for v in x)
    t1 = sum(vi * yi for vi, yi in zip(x, y))
    t2 = sum(vi * vi * yi for vi, yi in zip(x, y))
    det = s2 * s4 - s3 * s3
    if abs(det) < 1e-12:
        return 0.0
    return float((s2 * t2 - s3 * t1) / det)


def growth_shape(sigma_by_turn: Dict[int, int], *,
                 late_from: int = 10, ref_turn: int = 12,
                 target_ratio: float = 3.0) -> Dict[str, Any]:
    """从「每回合战团 Σ」提取成长曲线的形状（用户要的几何/指数判据）。

    记 ``y_t = ln(1 + Σ_t)``（用 log1p 而不是 log，避免 Σ=0 的负无穷）：

    | 键 | 含义 |
    |---|---|
    | ``growth_slope_all`` | 全 15 回合 ``y_t ~ turn`` 的 OLS 斜率（"平均每回合涨几倍 e"） |
    | ``growth_slope_early`` | t ≤ 5 的斜率（初期铺场） |
    | ``growth_slope_late`` | t ≥ ``late_from`` 的斜率（**指数段**的斜率） |
    | ``growth_curv`` | 二次拟合的二次项系数（>0 = 加速/凸曲线） |
    | ``growth_accel`` | ``effective_slope_late − effective_slope_early`` |
    | ``growth_ratio_10_15`` / ``_12_15`` | Σ15/Σ10、Σ15/Σ12（**指数段倍数**） |
    | ``growth_has_exp_segment`` | ``Σ15/Σ12 ≥ target_ratio``（默认 3×） |
    | ``growth_dlog_late_mean`` | t ≥ ``late_from`` 的 Δln(1+Σ) 均值（每回合对数斜率） |
    | ``growth_exp_ratio`` | ``exp(growth_dlog_late_mean)`` = 指数段每回合的几何倍数 |

    真实人类基线（10k+ 局，``docs/CARRIER_SCALING.md``）：t12 Σ=4458、t15 Σ=26516
    → ``ratio_12_15 = 5.95``、``growth_dlog_late_mean ≈ ln(5.95)/3 = 0.59``。
    """
    turns = sorted(int(t) for t in sigma_by_turn)
    ys = {int(t): math.log1p(max(0, int(sigma_by_turn[t]))) for t in turns}

    def _sel(lo: int, hi: int) -> Tuple[List[float], List[float]]:
        xs = [float(t) for t in turns if lo <= t <= hi]
        return xs, [ys[int(t)] for t in turns if lo <= t <= hi]

    xa, ya = _sel(-10 ** 9, 10 ** 9)
    xe, ye = _sel(-10 ** 9, 5)
    xl, yl = _sel(int(late_from), 10 ** 9)
    s_all = _ols_slope(xa, ya)
    s_early = _ols_slope(xe, ye)
    s_late = _ols_slope(xl, yl)
    mean_early = (sum(ye) / len(ye)) if ye else 0.0
    mean_late = (sum(yl) / len(yl)) if yl else 0.0
    dl = [yl[i] - yl[i - 1] for i in range(1, len(yl))]
    dlog_late = (sum(dl) / len(dl)) if dl else 0.0

    def _sigma(t: int) -> int:
        return max(0, int(sigma_by_turn.get(int(t), 0)))

    def _ratio(a: int, b: int) -> float:
        sa, sb = _sigma(a), _sigma(b)
        return (float(sb) / float(sa)) if sa > 0 else 0.0

    return {
        "growth_slope_all": round(s_all, 4),
        "growth_slope_early": round(s_early, 4),
        "growth_slope_late": round(s_late, 4),
        "growth_curv": round(_quad_coef(xa, ya), 5),
        "growth_accel": round(s_late - s_early, 4),
        "growth_level_early": round(mean_early, 4),
        "growth_level_late": round(mean_late, 4),
        "growth_dlog_late_mean": round(dlog_late, 4),
        "growth_exp_ratio": round(math.exp(dlog_late), 4) if dlog_late else 1.0,
        "growth_ratio_10_15": round(_ratio(10, 15), 3),
        "growth_ratio_12_15": round(_ratio(int(ref_turn), 15), 3),
        "growth_has_exp_segment": bool(_ratio(int(ref_turn), 15) >= float(target_ratio)),
    }


# ── 向量化（训练采样用：同进程 lockstep）───────────────────────────────────


class VectorEconomySandbox:
    """N 局并行的 lockstep 沙盒（**同进程**：引擎步进在 CPU，网络前向由调用方批处理）。

    ``step(actions)`` 返回 ``(obs_list, rewards, dones, infos)``；``done`` 的环境会
    **立刻用下一个 seed 重置**（obs_list 里给的是新一局的首个观测），已完成的整局
    汇总进 ``self.episodes``（调用方按 ``done`` 收尾轨迹）。
    """

    def __init__(self, config: Optional[SandboxConfig] = None, n_envs: int = 64,
                 seed0: int = 0, core_ids: Optional[Iterable[str]] = None):
        self.cfg = config or SandboxConfig()
        self.n_envs = max(1, int(n_envs))
        self.envs = [EconomySandbox(self.cfg, core_ids=core_ids)
                     for _ in range(self.n_envs)]
        self._next_seed = int(seed0)
        self.episodes: List[Dict[str, Any]] = []
        self.decisions = 0
        self.turn_count = 0

    def _seed(self) -> int:
        s = self._next_seed
        self._next_seed += 1
        return s

    @property
    def gold_per_turn(self) -> int:
        """当前所有环境的每回合金币（金币课程用；新 reset 的局立刻生效）。"""
        return int(self.envs[0].gold_per_turn) if self.envs else 0

    def set_gold_per_turn(self, n: int) -> None:
        """给所有环境改金币（下一回合生效）。金环境用：课程切换时不重建环境。"""
        for e in self.envs:
            e.set_gold_per_turn(int(n))

    def reset(self, seed0: Optional[int] = None) -> List[SandboxObs]:
        if seed0 is not None:
            self._next_seed = int(seed0)
        self.episodes = []
        self.decisions = 0
        self.turn_count = 0
        return [e.reset(self._seed()) for e in self.envs]

    def step(self, actions: Sequence[int]):
        obs: List[SandboxObs] = []
        rewards = np.zeros(self.n_envs, dtype=np.float32)
        dones = np.zeros(self.n_envs, dtype=bool)
        infos: List[Dict[str, Any]] = []
        for i, env in enumerate(self.envs):
            o, r, d, info = env.step(int(actions[i]))
            self.decisions += 1
            if d:
                ep = info.get("episode") or env.episode_summary()
                self.episodes.append(ep)
                self.turn_count += int(ep.get("turns") or 0)
                o = env.reset(self._seed())
                info = dict(info)
                info["episode"] = ep
            obs.append(o)
            rewards[i] = float(r)
            dones[i] = bool(d)
            infos.append(info)
        return obs, rewards, dones, infos


# ── 参考策略（基线 / BC 教师）───────────────────────────────────────────────


class SandboxPolicies:
    """沙盒基线策略集合（都返回 245 动作空间里的合法动作）。"""

    def __init__(self, game: Any, kind: str = "random", *, seed: int = 0):
        self.kind = str(kind)
        self.rng = np.random.default_rng(int(seed))
        self._teacher = None
        self._script = None
        if self.kind in ("teacher", "carrier_teacher"):
            sys.path.insert(0, os.path.join(_root(), "scripts"))
            from carrier_teacher import CarrierTeacher  # noqa: PLC0415
            self._teacher = CarrierTeacher()
        elif self.kind in ("spell", "greedy"):
            sys.path.insert(0, os.path.join(_root(), "scripts"))
            from engine_ceiling_probe import ScriptPolicy  # noqa: PLC0415
            self._script = ScriptPolicy(mode=self.kind, curve="mid")

    @property
    def name(self) -> str:
        return self.kind

    def act(self, game: Any, mask: np.ndarray, seat: int = SEAT) -> int:
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            return END_TURN
        if self.kind == "random":
            return int(legal[self.rng.integers(legal.size)])
        if self.kind == "end":
            return END_TURN if mask[END_TURN] else int(legal[0])
        # 教师策略都要 view()（decide_view 自己处理 pending / 动作上限）
        v = json.loads(game.view(seat))
        me = v.get("me") or {}
        if self._teacher is not None:
            self._teacher.set_lobby(v.get("lobby_races"), me)
            a = self._teacher.decide_view(v, mask)
        elif bool(me.get("pending")):
            a = self._script._pending(v, seat, me["pending"])
        else:
            a = self._script._recruit(v, me, mask)
        a = int(a) if a is not None else END_TURN
        if 0 <= a < N_ACTIONS and mask[a]:
            return a
        return int(END_TURN if mask[END_TURN] else legal[0])


def run_episode(cfg: SandboxConfig, seed: int, policy: str = "random",
                policy_seed: int = 0) -> Dict[str, Any]:
    """跑一局沙盒并返回 episode_summary（+ 收益汇总）。"""
    env = EconomySandbox(cfg)
    obs = env.reset(seed)
    pol = SandboxPolicies(env.g, policy, seed=policy_seed)
    total = 0.0
    steps = 0
    while not env.done:
        a = pol.act(env.g, obs.mask)
        obs, r, done, info = env.step(a)
        total += float(r)
        steps += 1
    ep = info.get("episode") or env.episode_summary()
    ep = dict(ep)
    ep["return"] = float(total)
    ep["decisions"] = int(steps)
    ep["policy"] = pol.name
    return ep


# ── CLI ─────────────────────────────────────────────────────────────────────


def _pct(vals: Sequence[float], q: float) -> float:
    if not vals:
        return 0.0
    return float(np.percentile(np.asarray(vals, dtype=np.float64), q))


def summarize(episodes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """把多局汇总成 p50/p90 报告（t12/t15 Σ、tier、载体率、施法数、酒馆 buff）。"""
    def col(key: str) -> List[float]:
        return [float(e.get(key) or 0) for e in episodes]

    tiers = col("tier_final")
    out = {
        "games": len(episodes),
        "sigma_t12_p50": _pct(col("sigma_t12"), 50),
        "sigma_t12_p90": _pct(col("sigma_t12"), 90),
        "sigma_t12_max": max(col("sigma_t12"), default=0),
        "sigma_t15_p50": _pct(col("sigma_t15"), 50),
        "sigma_t15_p90": _pct(col("sigma_t15"), 90),
        "sigma_t15_max": max(col("sigma_t15"), default=0),
        "tier_p50": _pct(tiers, 50),
        "tier_dist": {int(t): int(tiers.count(t)) for t in sorted(set(tiers))},
        "carrier_rate": float(np.mean([1.0 if float(e.get("carriers_t15") or 0) > 0 else 0.0
                                       for e in episodes])) if episodes else 0.0,
        "carriers_p50": _pct(col("carriers_t15"), 50),
        # 「载体在场回合数」= 该局 boards 上至少 1 张载体的招募末回合数（docs/CARRIER_SCALING.md §4）
        "carrier_turns_mean": float(np.mean([
            sum(1 for r in (e.get("rows") or []) if int(r.get("carriers") or 0) > 0)
            for e in episodes])) if episodes else 0.0,
        "spells_p50": _pct(col("spells_t15"), 50),
        "spells_max": max(col("spells_t15"), default=0),
        "tavern_buff_p50": _pct(col("tavern_buff_t15"), 50),
        "tavern_buff_max": max(col("tavern_buff_t15"), default=0),
        "return_mean": float(np.mean(col("return"))) if episodes else 0.0,
        "decisions_mean": float(np.mean(col("decisions"))) if episodes else 0.0,
    }
    # ── 收入 / Σ 每金币（docs/COMPOUND_INCOME.md 的核心口径）────────────────
    # 分母 = 整局拿到的金币（``gold_total_income``）；分子用 t12 Σ（与文档的 2.9 / 9.9
    # 同口径）与 t15 Σ 各报一次。
    if any("gold_total_income" in e for e in episodes):
        gi = col("gold_total_income")
        s12 = col("sigma_t12")
        s15 = col("sigma_t15")
        out["gold_total_income_p50"] = _pct(gi, 50)
        out["gold_total_income_mean"] = float(np.mean(gi)) if gi else 0.0
        out["sigma12_per_gold_p50"] = _pct(
            [a / b for a, b in zip(s12, gi) if b > 0], 50)
        out["sigma15_per_gold_p50"] = _pct(
            [a / b for a, b in zip(s15, gi) if b > 0], 50)
        out["goldens_p50"] = _pct(col("goldens_t15"), 50) if any(
            "goldens_t15" in e for e in episodes) else 0.0
    # 「目标流派核心牌在场数」只有在环境配了 ``core_ids`` 时才出现（默认不新增键）：
    # 核心牌 = ``data/scaling/compound_cards.json`` 里该流派的核心集（见
    # docs/COMPOUND_CHAINS.md）。度量口径与 ``carriers`` 完全平行。
    if any("core_t15" in e for e in episodes):
        cc = col("core_t15")
        out["core_t15_p50"] = _pct(cc, 50)
        out["core_t15_mean"] = float(np.mean(cc)) if cc else 0.0
        out["core_rate"] = float(np.mean([
            1.0 if float(e.get("core_max") or 0) > 0 else 0.0 for e in episodes])) \
            if episodes else 0.0
        out["core_turns_mean"] = float(np.mean(
            [float(e.get("core_turns") or 0) for e in episodes])) if episodes else 0.0
    # ── 成长曲线形状（用户的核心判据：几何/指数成长，而不是线性更长）──────
    if any("growth_slope_late" in e for e in episodes):
        out["growth_slope_all_p50"] = _pct(col("growth_slope_all"), 50)
        out["growth_slope_late_p50"] = _pct(col("growth_slope_late"), 50)
        out["growth_slope_late_p90"] = _pct(col("growth_slope_late"), 90)
        out["growth_slope_early_p50"] = _pct(col("growth_slope_early"), 50)
        out["growth_curv_p50"] = _pct(col("growth_curv"), 50)
        out["growth_accel_p50"] = _pct(col("growth_accel"), 50)
        out["growth_dlog_late_p50"] = _pct(col("growth_dlog_late_mean"), 50)
        out["growth_exp_ratio_p50"] = _pct(col("growth_exp_ratio"), 50)
        out["growth_ratio_12_15_p50"] = _pct(col("growth_ratio_12_15"), 50)
        out["growth_ratio_10_15_p50"] = _pct(col("growth_ratio_10_15"), 50)
        out["growth_ratio_12_15_p90"] = _pct(col("growth_ratio_12_15"), 90)
        out["exp_segment_rate"] = float(np.mean([
            1.0 if e.get("growth_has_exp_segment") else 0.0 for e in episodes])) \
            if episodes else 0.0
        out["t15_over_t12_p50"] = out["growth_ratio_12_15_p50"]
    # ── 饰品（只在开启饰品计量时出现）───────────────────────────────────
    if any("trinket_count" in e for e in episodes):
        tc = col("trinket_count")
        out["trinkets_p50"] = _pct(tc, 50)
        out["trinkets_mean"] = float(np.mean(tc)) if tc else 0.0
        out["trinket_offer_rate"] = float(np.mean([
            1.0 if float(e.get("trinket_offers") or 0) > 0 else 0.0 for e in episodes])) \
            if episodes else 0.0
        out["trinket_offers_mean"] = float(np.mean(
            [float(e.get("trinket_offers") or 0) for e in episodes])) if episodes else 0.0
        if any("trinket_hit" in e for e in episodes):
            out["trinket_hit_rate"] = float(np.mean([
                1.0 if e.get("trinket_hit") else 0.0 for e in episodes])) \
                if episodes else 0.0
            out["trinket_hits_mean"] = float(np.mean(
                [float(e.get("trinket_hits") or 0) for e in episodes])) if episodes else 0.0
    # 「对载体施法数」只有在调用方做了载体审计（``carrier_audit=1``）时才出现：
    # 口径与完整游戏 ``quality_monitor --carrier-audit 1`` 的
    # ``casts_on_carrier`` 一致（目标选择命中载体 eid 的次数）。
    if any("casts_on_carrier" in e for e in episodes):
        cc = col("casts_on_carrier")
        out["casts_on_carrier_mean"] = float(np.mean(cc)) if cc else 0.0
        out["casts_on_carrier_p50"] = _pct(cc, 50)
        out["casts_on_carrier_max"] = max(cc, default=0)
        given = [float(e.get("casts_on_carrier") or 0) for e in episodes
                 if float(e.get("carriers_t15") or 0) > 0]
        out["casts_on_carrier_mean_given_carrier"] = (
            float(np.mean(given)) if given else 0.0)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="纯经济沙盒：基线 / 度量 CLI")
    ap.add_argument("--policy", default="teacher",
                    choices=["random", "end", "teacher", "carrier_teacher", "spell", "greedy"])
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--turns", type=int, default=15)
    ap.add_argument("--gold-per-turn", type=int, default=10)
    ap.add_argument("--gold-mode", default="fixed",
                    choices=["fixed", "add", "growth", "set"],
                    help="收入口径：fixed=每回合重置为 gold_per_turn（= 旧 set，默认）；"
                         "add=引擎收入 + gold_per_turn + gold_add×(turn−1)（线性）；"
                         "growth=引擎收入 + scale×(base×(1+rate)^(turn−1) + per_carrier×载体数)")
    ap.add_argument("--gold-add", type=int, default=0,
                    help="add 模式每回合额外收入的斜率（第 t 回合 +gold_add×(t−1) 金）")
    ap.add_argument("--gold-growth-rate", type=float, default=0.0,
                    help="growth 模式每回合收入的复利率（0.15 = 每回合 ×1.15）")
    ap.add_argument("--gold-per-carrier", type=int, default=0,
                    help="growth 模式每个上回合在场载体额外给的金币（滚雪球项）")
    ap.add_argument("--sandbox-income-scale", dest="income_scale", type=float, default=1.0,
                    help="注入项整体缩放（上界探针；默认 1.0）")
    ap.add_argument("--gold-cap", type=int, default=99,
                    help="注入后的金币上限（0 = 不封顶）")
    ap.add_argument("--action-cap", type=int, default=40)
    ap.add_argument("--num-players", type=int, default=8)
    ap.add_argument("--sandbox-reward", dest="reward", default="log_strength",
                    choices=["log_strength", "auc_strength", "final_strength",
                             "board_delta", "t12_t15", "exp_growth"])
    ap.add_argument("--sandbox-reward-mix", dest="reward_mix", default="")
    ap.add_argument("--lobby-types", default="")
    ap.add_argument("--sandbox-trinkets", dest="trinkets", type=int, default=-1,
                    help="饰品开关：-1=引擎默认（第 6/9 回合 4 选 1，逐位等价旧路径）；"
                         "1=显式开启；0=关闭")
    ap.add_argument("--growth-w-final", type=float, default=1.0)
    ap.add_argument("--growth-w-super", type=float, default=1.0)
    ap.add_argument("--growth-slope-base", type=float, default=0.35)
    ap.add_argument("--growth-from", type=int, default=10)
    ap.add_argument("--growth-w-ratio", type=float, default=0.0)
    ap.add_argument("--free-tier6", dest="free_tier6", type=int, default=0,
                    help="1 = 开局 tier6 + 升级免费（ceiling_probe --cheat tier6 口径）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    cfg = SandboxConfig(
        turns=int(args.turns), gold_per_turn=int(args.gold_per_turn),
        gold_mode=str(args.gold_mode), action_cap=int(args.action_cap),
        gold_add=int(args.gold_add),
        gold_growth_rate=float(args.gold_growth_rate),
        gold_per_carrier=int(args.gold_per_carrier),
        income_scale=float(args.income_scale),
        gold_cap=int(args.gold_cap),
        num_players=int(args.num_players), reward=str(args.reward),
        reward_mix=str(args.reward_mix),
        lobby_types=tuple(x.strip().upper() for x in args.lobby_types.split(",") if x.strip()),
        free_tier6=bool(int(args.free_tier6)),
        trinkets=(None if int(args.trinkets) < 0 else bool(int(args.trinkets))),
        growth_w_final=float(args.growth_w_final),
        growth_w_super=float(args.growth_w_super),
        growth_slope_base=float(args.growth_slope_base),
        growth_from=int(args.growth_from),
        growth_w_ratio=float(args.growth_w_ratio),
        seed=int(args.seed))
    eps = [run_episode(cfg, int(args.seed) + i, args.policy, policy_seed=i)
           for i in range(int(args.games))]
    rep = summarize(eps)
    rep["config"] = cfg.engine_config()
    rep["policy"] = args.policy
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    # 每回合曲线（第一局的 per-turn 表，便于肉眼看缩放轨迹）
    if eps:
        rows = eps[0].get("rows") or []
        print("\nturn  Σ     tier carriers spells tavern_buff gold")
        for r in rows:
            print(f"{r['turn']:4d} {r['sigma']:5d} {r['tier']:5d} {r['carriers']:7d} "
                  f"{r['spells']:6d} {r['tavern_buff']:10d} {r['gold']:4d}")
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"summary": rep, "episodes": eps}, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
