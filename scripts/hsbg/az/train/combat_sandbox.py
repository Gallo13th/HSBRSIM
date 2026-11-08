"""轻量**战斗**沙盒：复用 ``economy_sandbox`` 的 recruit 阶段，每回合结束打 **1 场**
引擎原生战斗（对手 = 从真实人类战团库按分位采样的一条战团）。

为什么需要它（`docs/FULL_GAME_TRANSFER.md` §5 的定论）：无战斗的经济沙盒里，
「多买一张随从」不会变成名次，最优解是**少买留钱**；策略因此学不出完整对局需要的
强度（完整对局 t15 Σ 22.5）。这里把「战斗 → 掉血/胜负」这层回报补上，但**只打 1 场**
（不做 7 席），保持 ~1/6 的开销。

设计（与 ``EconomySandbox`` 的差别，全部是**加法**）：
1. 引擎 ``num_players=2``、**去掉伤害封印**（``damage_caps``），战斗按引擎真实伤害结算；
2. 每回合开始把 seat 1 换成一条采样的人类战团（``human_board_pool.inject_turn``，
   ``fidelity=full``），并把它的血量重置到 30（保证每回合是一场**新**决斗）；
3. **不再每回合回满 learner 的血**（父类 ``_inject_gold`` 会 ``set_player health=30``，
   那会让伤害没有后果）——learner 血量跨回合累积，归零即淘汰、回合终止；
4. 奖励 = ``win(+1) / lose(-1)`` + **伤害差归一化** ``(dealt − taken)/hp_start``
   + 终局 ``log1p(Σ)/log1p(strength_ref)``（沿用父类的望远镜 Σ 奖励作为终局项）。

用法::

    from hsbg.az.train.combat_sandbox import CombatConfig, CombatSandbox
    cfg = CombatConfig(turns=15, gold_mode="fixed", gold_per_turn=20,
                       gold_profile="3,4,5,...", tier_reward_coef=0.1,
                       opponent_quantile="p75")
    env = CombatSandbox(cfg)
    obs = env.reset()
    ...  # 与 EconomySandbox 完全相同的 step/obs 接口
    env.episode_summary()   # 额外含 combat 字段：wins/losses/damage_taken/win_rate
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from hsbg.az.train import economy_sandbox as _ES
from hsbg.az.train.economy_sandbox import (  # noqa: F401  (re-export 给调用方)
    END_TURN, N_ACTIONS, OBS_CARDS, OBS_FLOATS, SEAT, EconomySandbox, SandboxConfig,
    SandboxObs, VectorEconomySandbox, stack_obs, summarize)

HP_START = 30
_POOL_CACHE: Dict[Tuple[str, str], Any] = {}


@dataclass(frozen=True)
class CombatConfig(SandboxConfig):
    """在沙盒配置上加战斗项（全部有默认值 ⇒ 旧的 ``SandboxConfig`` 用法不受影响）。"""

    #: 真实战团库（jsonl）；空 = 不注入（退化为纯 recruit，便于对照）
    opponent_boards: str = "data/real_library/library_real_quasi_full.jsonl"
    #: 采样分位：p50 / p75 / p90（``load_pool(sample=...)``）
    opponent_quantile: str = "p75"
    #: learner 初始血量（淘汰线）
    hp_start: int = HP_START
    #: 是否在每回合刷新对手（True = 每回合一场新决斗）
    refresh_opponent: bool = True
    #: 奖励里的战斗项系数（0 = 纯 Σ 口径，用于对照）
    combat_reward_coef: float = 1.0
    #: 伤害差归一化除数（0 = 用 hp_start）
    dmg_norm: float = 0.0
    #: 对手注入保真度（full = 含手牌/关键词等准完整字段）
    opponent_fidelity: str = "full"

    def engine_config(self) -> Dict[str, Any]:
        """引擎配置：**去掉伤害封印** + ``num_players=2``（learner + 1 对手）。

        父类用 ``damage_caps=[[1, 0]]`` 把伤害恒置 0（无战斗沙盒的前提）；这里必须
        让引擎按真实伤害结算，否则「战斗」没有后果。
        """
        cfg = dict(super().engine_config())
        cfg.pop("damage_caps", None)
        cfg.pop("damage_cap_until_alive", None)
        cfg["num_players"] = 2
        return cfg


def _load_opp_pool(path: str, quantile: str):
    """进程级缓存的人类战团池（同一个进程里的多个 env 共用）。"""
    key = (str(path), str(quantile))
    if key in _POOL_CACHE:
        return _POOL_CACHE[key]
    pool = None
    try:
        from hsbg.az.train.human_board_pool import load_pool  # noqa: PLC0415
        pool = load_pool(str(path), sample=str(quantile))
    except BaseException:  # noqa: BLE001 - 池不可用时退化为纯 recruit
        pool = None
    _POOL_CACHE[key] = pool
    return pool


class CombatSandbox(EconomySandbox):
    """``EconomySandbox`` + 每回合 1 场引擎原生战斗（对手 = 真实人类战团）。"""

    def __init__(self, config: Optional[CombatConfig] = None, *,
                 carriers: Optional[Sequence[str]] = None,
                 core_ids: Optional[Sequence[str]] = None) -> None:
        if config is None:
            config = CombatConfig()
        super().__init__(config, carriers=carriers, core_ids=core_ids)
        self.cfg: CombatConfig = config          # type: ignore[assignment]
        self._pool = _load_opp_pool(config.opponent_boards,
                                    config.opponent_quantile)
        self._hb_rng = random.Random(int(config.seed) * 1000003 + 29)
        from hsbg.az.train.human_board_pool import HumanBoardStats  # noqa: PLC0415
        self._hb_stats = HumanBoardStats(fidelity=str(config.opponent_fidelity))
        self._combat: Dict[str, Any] = self._new_combat_state()

    # ── 战斗记账 ────────────────────────────────────────────────────────
    def _new_combat_state(self) -> Dict[str, Any]:
        return {"wins": 0, "losses": 0, "ties": 0, "damage_taken": 0,
                "damage_dealt": 0, "combats": 0, "hp": int(self.cfg.hp_start),
                "killed": False, "per_turn": []}

    def _hp(self, seat: int) -> int:
        try:
            p = json.loads(self.g.player_json(int(seat)))
            return int(p.get("health") or 0)
        except BaseException:  # noqa: BLE001
            return 0


    # ── 金币注入：**不写 health**（否则每回合回满，伤害没有后果）────────
    def _inject_gold(self, turn: int) -> None:
        n = int(self.income_for_turn(turn))
        set_like = self.cfg.gold_mode in ("fixed", "set")
        cmd: Dict[str, Any] = {"cmd": "set_player", "p": SEAT}
        if self.cfg.free_tier6:
            cmd.update({"tier": 6, "upgrade_cost": 0})
        if set_like:
            if n > 0:
                cmd["gold"] = n if not self.cfg.gold_cap else min(int(self.cfg.gold_cap), n)
        elif n > 0:
            gold = int(self._gold()) + n
            if self.cfg.gold_cap:
                gold = min(int(self.cfg.gold_cap), gold)
            cmd["gold"] = int(gold)
        self.g.debug(json.dumps(cmd))
        self._turn_gold_income = int(n)
        self._turn_gold_start = int(self._gold())
        self._turn_actions = 0
        self._turn_cap = int(self.cfg.action_cap_for_turn(self._turn_gold_start))

    # ── 每回合：换一条人类战团给 seat 1，然后让它 EndTurn ────────────────
    def _drive_opponents(self, t: int, max_steps: int = 16) -> None:
        if self._pool is not None and bool(self.cfg.refresh_opponent) and int(t) >= 1:
            try:
                from hsbg.az.train.human_board_pool import inject_turn  # noqa: PLC0415
                inject_turn(self.g, self._pool, int(t), seats_count=1, p=1.0,
                            rng=self._hb_rng, learner_seat=SEAT, stats=self._hb_stats,
                            set_tier=True, fidelity=str(self.cfg.opponent_fidelity),
                            fast_inject=False)
                # 对手血量重置：每回合是一场新决斗（learner 的血才是累积资源）
                self.g.debug(json.dumps({"cmd": "set_player", "p": 1,
                                         "health": int(self.cfg.hp_start)}))
            except BaseException:  # noqa: BLE001 - 注入失败不影响 recruit
                pass
        super()._drive_opponents(t, max_steps)

    # ── step：跨回合时结算这一场战斗 ────────────────────────────────────
    def step(self, action: int):
        t_before = int(getattr(self.g, "turn", -1)) if self.g is not None else -1
        hp0 = self._hp(SEAT)
        hp1 = self._hp(1)
        obs, reward, done, info = super().step(action)
        t_after = int(getattr(self.g, "turn", -1)) if self.g is not None else -1
        if t_after == t_before or t_after < 0:
            return obs, reward, done, info
        hp0b = self._hp(SEAT)
        taken = max(0, int(hp0) - int(hp0b))
        dealt = max(0, int(hp1) - int(self._hp(1)))
        st = self._combat
        st["combats"] += 1
        st["damage_taken"] += taken
        st["damage_dealt"] += dealt
        st["hp"] = int(hp0b)
        if dealt > taken:
            st["wins"] += 1
            win = 1.0
        elif taken > dealt:
            st["losses"] += 1
            win = -1.0
        else:
            st["ties"] += 1
            win = 0.0
        norm = float(self.cfg.dmg_norm) or float(self.cfg.hp_start)
        combat_r = float(self.cfg.combat_reward_coef) * (
            win + (float(dealt) - float(taken)) / max(1.0, norm))
        st["per_turn"].append({"turn": int(t_after) - 1, "taken": int(taken),
                               "dealt": int(dealt), "win": float(win),
                               "hp": int(hp0b)})
        reward = float(reward) + float(combat_r)
        if int(hp0b) <= 0 and not bool(done):
            # learner 被淘汰：结束这一局（引擎有时不会立刻 is_over）
            st["killed"] = True
            done = True
            import math  # noqa: PLC0415
            _L = math.log1p(max(0.0, float(st.get("sigma_t15") or 0))) / math.log1p(
                float(self.cfg.strength_ref))
            reward = float(reward) + _L * 0.0     # 终局 Σ 项已由父类望远镜给出
        return obs, reward, done, info

    # ── 汇总：父类指标 + 战斗指标 ───────────────────────────────────────
    def episode_summary(self) -> Dict[str, Any]:
        out = dict(super().episode_summary())
        st = self._combat
        n = max(1, int(st["combats"]))
        out.update({
            "combat": True,
            "combats": int(st["combats"]),
            "wins": int(st["wins"]), "losses": int(st["losses"]),
            "ties": int(st["ties"]),
            "win_rate": float(st["wins"]) / float(n),
            "damage_taken": int(st["damage_taken"]),
            "damage_dealt": int(st["damage_dealt"]),
            "hp_end": int(st["hp"]), "killed": bool(st["killed"]),
            "combat_turns": st["per_turn"],
        })
        return out

    def reset(self, seed: Optional[int] = None) -> SandboxObs:
        self._combat = self._new_combat_state()
        self._hb_rng = random.Random((int(self.cfg.seed if seed is None else seed))
                                     * 1000003 + 29)
        return super().reset(seed)


class VectorCombatSandbox(_ES.VectorEconomySandbox):
    """多环境版（与 ``VectorEconomySandbox`` 同接口，只是每个 env 是 ``CombatSandbox``）。"""

    def __init__(self, config: Optional[CombatConfig] = None, n_envs: int = 64,
                 seed0: Optional[int] = None, *,
                 carriers: Optional[Sequence[str]] = None,
                 core_ids: Optional[Sequence[str]] = None) -> None:
        if config is None:
            config = CombatConfig()
        self.cfg: CombatConfig = config          # type: ignore[assignment]
        n = max(1, int(n_envs))
        s0 = int(config.seed if seed0 is None else seed0)
        self.envs = [CombatSandbox(config.replaced(seed=s0 + i),
                                   carriers=carriers, core_ids=core_ids)
                     for i in range(n)]
        self.n_envs = n
        # 与 ``VectorEconomySandbox`` 保持同样的状态字段（父类方法会用到）
        self._next_seed = int(s0) + n
        self.episodes = []
        self.decisions = 0
        self.turn_count = 0


def summarize_combat(episodes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """``summarize`` + 战斗聚合（win rate / 伤害 / 存活）。"""
    out = dict(summarize(episodes))
    n = max(1, len(episodes))

    def col(key: str) -> List[float]:
        return [float(e.get(key) or 0) for e in episodes]

    out.update({
        "win_rate": float(np.mean(col("win_rate"))) if episodes else 0.0,
        "wins_mean": float(np.mean(col("wins"))) if episodes else 0.0,
        "damage_taken_mean": float(np.mean(col("damage_taken"))) if episodes else 0.0,
        "damage_dealt_mean": float(np.mean(col("damage_dealt"))) if episodes else 0.0,
        "killed_rate": float(np.mean([1.0 if e.get("killed") else 0.0
                                      for e in episodes])) if episodes else 0.0,
        "hp_end_mean": float(np.mean(col("hp_end"))) if episodes else 0.0,
    })
    return out
