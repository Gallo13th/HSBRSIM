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
- **金币**：``--gold-per-turn N``（默认 10）在每回合开始把 seat 0 的金币设成 N
  （``--gold-mode add`` 时改成「自然收入 + N」）。这是与真实经济的主要偏差
  （真实是 3→10 递增、可跨回合攒钱），文档里单列。

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
    #: ``set`` = 每回合把金币设为 N；``add`` = 引擎自然收入 + N（保留真实曲线）
    gold_mode: str = "set"
    #: 每回合动作上限（与 s16 训练的 ``--max-actions-per-turn 40`` 同口径）
    action_cap: int = 40
    num_players: int = 8
    reward: str = "log_strength"
    reward_mix: str = ""
    strength_ref: float = STRENGTH_REF
    lobby_types: Tuple[str, ...] = ()
    lobby_races: int = 5
    seed: int = 0
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
        if self.gold_mode not in ("set", "add"):
            raise ValueError("gold_mode 只能是 set|add")
        if self.reward not in ("log_strength", "auc_strength", "final_strength",
                               "board_delta", "t12_t15"):
            raise ValueError("reward 只能是 log_strength|auc_strength|final_strength|"
                             "board_delta|t12_t15")
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
        self._last_sigma = 0
        self._end_metrics: Optional[Dict[str, Any]] = None
        self.last_info: Dict[str, Any] = {}
        #: 本局金币/回合（金币课程可以逐局改，不必重建环境）：默认取 cfg
        self.gold_per_turn = int(self.cfg.gold_per_turn)

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
        self._last_sigma = 0
        self._end_metrics = None
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
        self._inject_gold()
        self._drive_opponents(t)

    def _inject_gold(self) -> None:
        """回合开始：设置金币 + 把 seat 0 的血补满。

        补血是**必要**的：池里有以生命值支付的牌（``costs_health``），seat 0 一旦
        被打到 0 血就会被淘汰；而其余 7 席在回合一开始就已经 EndTurn，于是引擎会
        认为"所有人都结束了"→ 立刻打完本轮 → 跳到 GameOver（实测：25k 局里偶发
        一次，表现为 ``非法动作 ... game over``）。血量在沙盒里没有意义（无战斗伤害），
        所以每回合直接回满。
        """
        n = int(self.gold_per_turn)
        cmd: Dict[str, Any] = {"cmd": "set_player", "p": SEAT, "health": 30}
        if self.cfg.free_tier6:
            # 与 ceiling_probe 的 ``--cheat tier6`` 一致：每回合把 tier 打到 6 且升级免费
            cmd.update({"tier": 6, "upgrade_cost": 0})
        if n > 0:
            if self.cfg.gold_mode == "set":
                cmd["gold"] = n
            else:  # add：在引擎自然收入之上再加 N
                cmd["gold"] = min(99, int(self._gold()) + n)
        self.g.debug(json.dumps(cmd))

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
        e._last_sigma = 0
        e._end_metrics = None
        e.last_info = {}
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
            self._inject_gold()
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
        }
        if self._core is not None:
            # 目标流派核心牌在场数（复利先验的效果度量；未配置时不新增键）
            out["core"] = int(sum(1 for m in board
                                  if str(m.get("id") or "") in self._core))
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
        return float(r)

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
            "gold_hist": [int(r["gold"]) for r in rows],
            "rows": [dict(r) for r in rows],
            "config": {
                "turns": int(self.cfg.turns), "gold_per_turn": int(self.gold_per_turn),
                "gold_mode": self.cfg.gold_mode, "action_cap": int(self.cfg.action_cap),
                "reward": self.cfg.reward, "reward_mix": self.cfg.reward_mix,
                "free_tier6": bool(self.cfg.free_tier6),
                "num_players": int(self.cfg.num_players)},
        }
        if self._core is not None:
            # 复利核心牌在场数的整局口径：t15 / 单局最大 / 有核心牌的回合数
            out["core_t15"] = _val(15, "core", int(last.get("core") or 0))
            out["core_max"] = max((int(r.get("core") or 0) for r in rows), default=0)
            out["core_turns"] = sum(1 for r in rows if int(r.get("core") or 0) > 0)
        return out


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
    ap.add_argument("--gold-mode", default="set", choices=["set", "add"])
    ap.add_argument("--action-cap", type=int, default=40)
    ap.add_argument("--num-players", type=int, default=8)
    ap.add_argument("--sandbox-reward", dest="reward", default="log_strength",
                    choices=["log_strength", "auc_strength", "final_strength",
                             "board_delta", "t12_t15"])
    ap.add_argument("--sandbox-reward-mix", dest="reward_mix", default="")
    ap.add_argument("--lobby-types", default="")
    ap.add_argument("--free-tier6", dest="free_tier6", type=int, default=0,
                    help="1 = 开局 tier6 + 升级免费（ceiling_probe --cheat tier6 口径）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)

    cfg = SandboxConfig(
        turns=int(args.turns), gold_per_turn=int(args.gold_per_turn),
        gold_mode=str(args.gold_mode), action_cap=int(args.action_cap),
        num_players=int(args.num_players), reward=str(args.reward),
        reward_mix=str(args.reward_mix),
        lobby_types=tuple(x.strip().upper() for x in args.lobby_types.split(",") if x.strip()),
        free_tier6=bool(int(args.free_tier6)),
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
